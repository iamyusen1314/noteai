"""Managed Haiku5.5 workflow compatibility; all supplier HTTP is MockTransport.

Reuse the existing full clarification/resume fixture. Only its captured managed
configuration and legacy-wire assertions change; semantic extraction stays real.
Numeric model artifacts are isolated. These tests are not model-quality proof.
"""
import ast
import asyncio
from contextlib import ExitStack
import inspect
import json
import os
import socket
import textwrap
import unittest
from unittest import mock

import httpx

from tests import test_idempotency as original

api = original.api
db = original.db
billing = original.billing
config = api._mr._runtime_config
HAIKU = api._mr._cgp.HAIKU_5_5
SONNET = api._mr.CLAUDE_SONNET
POLICY = {HAIKU: {"rpm": 13000, "itpm": 10000000, "otpm": 2000000,
                  "evidence_ref": "HAIKU55-QUOTA-DEFAULT-ACTUAL001-20261106"},
          SONNET: {"rpm": 10000, "itpm": 10000000, "otpm": 2000000,
                   "evidence_ref": "CAPACITY-CLAUDE-DEFAULT-WORKSPACE-ACTUAL001-20261105"}}


def managed_snapshot():
    old = config.defaults()
    active = config.haiku55_candidate_config(old)
    assert old["chat"]["model"] == active["chat"]["model"] == SONNET
    assert old["arbitrate"] == active["arbitrate"]
    assert {task for task in old if old[task] != active[task]} == {
        "content_gen", "diagnosis", "semantic"}
    return {"active": active, "revision": 7, "active_revision": 7,
            "scope": "production", "source": "isolated_candidate_request_snapshot"}


def _reuse_fixture(name):
    """Derive the actual old fixture, changing only configuration/transport IO.

    Keep its original questions, answers, real pipeline, saved-note assertions,
    GET equivalence, unique8 and duplicate409. No product function is rebuilt.
    """
    source = textwrap.dedent(inspect.getsource(getattr(original.PaidRequestIdempotencyTests, name)))
    tree = ast.parse(source)
    counts = {"state": 0, "http": 0, "legacy_assertions": 0, "numeric_scorer": 0,
              "wire_accounting": 0}

    class CandidateFixture(ast.NodeTransformer):
        def visit_Assign(self, node):
            if any(isinstance(t, ast.Name) and t.id == "state" for t in node.targets):
                counts["state"] += 1
                node.value = ast.parse("managed_snapshot()", mode="eval").body
                return node
            if ast.unparse(node) == "count = len(calls)":
                counts["wire_accounting"] += 1
                return ast.copy_location(ast.parse("count = len(self.wire)").body[0], node)
            return self.generic_visit(node)

        def visit_Call(self, node):
            node = self.generic_visit(node)
            if (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "httpx" and node.func.attr == "MockTransport"):
                counts["http"] += 1
                node.args = [ast.Call(func=ast.Attribute(value=ast.Name(id="self", ctx=ast.Load()),
                    attr="_observe_wire", ctx=ast.Load()), args=node.args, keywords=[])]
            if isinstance(node.func, ast.Name) and node.func.id == "print":
                for child in ast.walk(node):
                    if isinstance(child, ast.Dict):
                        for index, key in enumerate(child.keys):
                            if isinstance(key, ast.Constant) and key.value == "resume_physical":
                                counts["wire_accounting"] += 1
                                child.values[index] = ast.parse(
                                    "len(self.wire) - len(first_physical)", mode="eval").body
            return node

        def visit_Expr(self, node):
            text = ast.unparse(node)
            if "mock.patch.object(api, '_score_generated_note'" in text:
                # The old fixture isolated scoring by skipping its semantic
                # call too. Keep only its _predict artifact stub here.
                counts["numeric_scorer"] += 1
                return None
            replacements = {
                "self.assertEqual(body['model'], api._mr.CLAUDE_HAIKU)":
                    "self.assertEqual(body['model'], HAIKU)",
                "self.assertIsNone(body['thinking_budget'])":
                    "self.assertNotIn('thinking_budget', body)",
                "self.assertEqual(body['temperature'], 0.7)":
                    "self.assertNotIn('temperature', body)",
            }
            wire_replacements = {
                "self.assertEqual(len(linked), len(first_physical) + len(calls))":
                    "self.assertEqual(len(linked), len(self.wire))",
                "self.assertEqual(len(calls), count)":
                    "self.assertEqual(len(self.wire), count)",
            }
            if text in wire_replacements:
                # The real semantic path adds measured HTTP calls that the old
                # fixture's generation-only callback did not see.
                counts["wire_accounting"] += 1
                return ast.copy_location(ast.parse(wire_replacements[text]).body[0], node)
            if text in replacements:
                counts["legacy_assertions"] += 1
                return ast.copy_location(ast.parse(replacements[text]).body[0], node)
            return self.generic_visit(node)

    updated = ast.fix_missing_locations(CandidateFixture().visit(tree))
    expected = {"state": 1, "http": 1, "legacy_assertions": 3 if name == "_run_capacity" else 0,
                "numeric_scorer": 0 if name == "_run_capacity" else 1,
                "wire_accounting": 0 if name == "_run_capacity" else 4}
    assert counts == expected, (name, counts)
    namespace = {**original.__dict__, "managed_snapshot": managed_snapshot, "HAIKU": HAIKU}
    exec(compile(updated, "existing_fixture_candidate_snapshot_only", "exec"), namespace)
    return namespace[name]


class Haiku55WorkflowCompatTests(unittest.TestCase):
    _create_user = original.PaidRequestIdempotencyTests._create_user
    _run_capacity = _reuse_fixture("_run_capacity")
    _original_resume = _reuse_fixture("test_original_waiting_resumes_through_real_pipeline_once")

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.dict(os.environ, {
            "DATABASE_URL": "", "PYTHON_DOTENV_DISABLED": "1", "NOTEAI_POSTDELIVERY_SETTLEMENT": "1",
            "NOTEAI_MODEL_CAPACITY_ENABLED": "1", "NOTEAI_MODEL_REMOTE_CONCURRENCY": "64",
            "NOTEAI_MODEL_ADMITTED_OPERATIONS": "100", "NOTEAI_MODEL_PENDING_CALLS": "512",
            "NOTEAI_MODEL_OPERATIONS_PER_USER": "1", "NOTEAI_MODEL_CAPACITY_LIMITS_JSON": json.dumps(POLICY),
            "NOTEAI_TASK_CLARIFICATION_ENABLED": "1", "NOTEAI_PUBLIC_PRODUCT": "1",
            "NOTEAI_MODEL_CONFIG_ENABLED": "1", "NOTEAI_PUBLIC_ORIGINS": "https://noteaipro.com",
            "NOTEAI_FACT_SEARCH": "0", "ANTHROPIC_API_KEY": "offline-fixture-not-a-provider-key",
        }))
        original.PaidRequestIdempotencyTests.setUp(self)
        self.addCleanup(original.PaidRequestIdempotencyTests.tearDown, self)
        import model_admission
        self.stack.enter_context(mock.patch.object(model_admission, "_instance", None))
        self.stack.enter_context(mock.patch("dotenv.load_dotenv", return_value=False))
        self.stack.enter_context(mock.patch.object(socket.socket, "connect",
            side_effect=AssertionError("supplier network forbidden")))
        self.stack.enter_context(mock.patch.object(socket.socket, "connect_ex",
            side_effect=AssertionError("supplier network forbidden")))
        self.wire = []

    def _check_wire(self, request):
        body = json.loads(request.content)
        self.wire.append(body)
        self.assertLessEqual(len(self.wire), 50, "finite fixture cannot repeat indefinitely")
        self.assertIn(body["model"], {HAIKU, SONNET})
        if body["model"] == HAIKU:
            self.assertNotIn("temperature", body)
            self.assertNotIn("thinking_budget", body)
            semantic = body.get("system") == "你是小红书笔记语义分析专家，只返回JSON，不要解释。"
            if semantic:
                self.assertEqual((body["max_tokens"], body["effort"], body["thinking_mode"]),
                                 (300, "low", "disabled"))
            else:
                self.assertEqual(body["effort"], "medium")
                self.assertEqual(body["thinking_mode"], "disabled" if body["max_tokens"] <= 4096 else "adaptive")
        else:
            self.assertNotIn("effort", body)
            self.assertNotIn("thinking_mode", body)
        return body

    @staticmethod
    def _response(body, text):
        return httpx.Response(200, json={"protocol_version": api._mr._cgp.PROTOCOL_VERSION,
            "text_blocks": [text], "model": body["model"], "stop_reason": "end_turn",
            "usage": {"input_tokens": 1000, "output_tokens": 100,
                      "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}})

    def _observe_wire(self, original_handler):
        def observed(request):
            body = self._check_wire(request)
            if body.get("system") == "你是小红书笔记语义分析专家，只返回JSON，不要解释。":
                return self._response(body, json.dumps({key: 0.6 for key in api.SEMANTIC_FEATURE_COLS}))
            return original_handler(request)
        return observed

    def _proof(self, operation, extra):
        self.assertTrue(any(x["model"] == HAIKU and x.get("thinking_mode") == "adaptive" for x in self.wire))
        self.assertTrue(any(x["model"] == HAIKU and x.get("max_tokens") == 300 for x in self.wire))
        self.assertTrue(any(x["model"] == SONNET for x in self.wire))
        self.assertEqual(len({x["operation_id"] for x in self.wire}), len(self.wire))
        calls = [dict(x) for x in db.fetchall("SELECT state,http_status,model_usage_record_id FROM public_trial_calls")]
        self.assertEqual(len(calls), len(self.wire))
        self.assertTrue(all(x["state"] == "responded" and x["http_status"] == 200 and x["model_usage_record_id"] for x in calls))
        proof = {"operation": operation, "actual_managed_candidate_snapshot": True,
                 "actual_55_expert_semantic_and_Sonnet_wire": True, "physical_known200": len(calls),
                 "old_defaults_and_chat_arbitrate_preserved": True,
                 "real_supplier_calls": 0, "production_DB_calls": 0, "merchant_quality_acceptance": False, **extra}
        print("HAIKU55_WORKFLOW_PROOF=" + json.dumps(proof, sort_keys=True), flush=True)

    def test_managed55_clarification_resume_real_router_save_reopen_and_unique_eight(self):
        self._original_resume()
        self._proof("generate", {"real_ASGI_resume": True, "normal_saved_GET": True,
                                  "duplicate409_no_call": True, "unique_credits": 8})

    def test_managed55_diagnosis_real_agents_semantics_save_reopen_and_unique_six(self):
        uid = "managed55-diagnosis-owner"
        self._create_user(uid)
        db.execute("UPDATE public_trial_budget SET enabled=1,policy_mode='owner_metered' WHERE id=?",
                   (api._public_product.BUDGET_ID,))
        titles = ["蓝猫咖啡店双人套餐两杯拿铁怎么选", "北京路约朋友喝咖啡先看套餐数量清单", "约朋友喝拿铁先说清这份双人套餐数量"]
        tags = "\n#蓝猫咖啡店 #北京路咖啡 #拿铁 #双人套餐 #咖啡探店 #朋友聚会"
        bodies = [
            "蓝猫咖啡店这份双人套餐怎么选？先看清198元对应的内容：9月套餐包含2杯拿铁，热饮不加糖。"
            "两杯饮品合在同一份套餐里，不是每个人各有两杯；约朋友一起点单前，把这个数量说清楚，选择会更直接。"
            "如果两个人平时喝咖啡的习惯不同，可以先讨论是否都想喝拿铁，再决定要不要选择同一份套餐。\n\n"
            "门店位于北京路商圈，营业时间为每日10:00-20:00。把地点和营业时间一并发给同行的朋友，"
            "方便商量见面安排。已确认的信息只有门店位置、营业时间、套餐价格和饮品内容，没有额外说明的项目不用替商家补充。"
            "拿铁是本次套餐中的饮品，可以作为核对清单的一项，不需要把未确认的口感写成体验结论。\n\n"
            "决定点单后，照着2杯拿铁的清单核对即可，实际到店时再确认当日安排。"
            "收藏这份套餐说明，和朋友聊聊各自的点单习惯；如果这份核对方式对你有帮助，也欢迎点赞。" + tags,
            "去北京路商圈约朋友喝咖啡，先把见面时间商量好，再核对门店的信息。蓝猫咖啡店每日10:00-20:00营业，"
            "如果想选9月的双人套餐，可以把198元的价格和包含内容一起发给朋友，避免只看到套餐名字就作决定。\n\n"
            "这份套餐包含2杯拿铁，热饮不加糖。数量是两个人共享一份套餐里的两杯，不是每人各两杯。"
            "如果你们都想喝拿铁，这些信息可以作为点单参考；如果口味偏好不同，也可以先讨论自己想喝的饮品，"
            "再决定套餐是否适合这次见面，不需要为了凑套餐勉强彼此。\n\n"
            "位置、营业时间、价格和数量放在一起，比零散转述更容易对照。到店前再核对当日安排，"
            "点单时确认两杯饮品属于同一套餐，沟通起来会清楚一些。对于没有提供的项目，先留空即可，"
            "不把猜测写成门店承诺。你通常怎样和朋友商量咖啡点单？欢迎在评论里交流，记得点赞和收藏，"
            "下次需要时可以翻出这份清单。" + tags,
            "和朋友一起点咖啡，最容易说岔的是套餐里的数量。蓝猫咖啡店9月双人套餐198元，包含2杯拿铁，"
            "热饮不加糖。这里的两杯属于同一份双人套餐，把数量讲明白，再讨论两个人的口味，比只转发一个价格更有用。\n\n"
            "点单前可以先问彼此是否都想喝拿铁，再核对套餐清单是否符合这次的选择。套餐说明没有涉及的项目，"
            "就不额外作承诺；这份清单只整理已经确认的信息，也不把商品名称直接变成个人体验。"
            "如果你更习惯各点各的，也可以把这些信息当作比较选项，不必急着作决定。\n\n"
            "蓝猫咖啡店位于北京路商圈，每日营业时间为10:00-20:00。商量好时间后，记得把门店位置一起发给同行的人，"
            "到店再确认当日安排。把价格、数量、位置和时间放在一处，后面核对会更方便。"
            "你在意的是套餐数量还是饮品选择？欢迎留言聊聊。收藏这份说明，有需要时再看；喜欢这种清楚的清单也可以点赞。" + tags,
        ]
        source = ("蓝猫咖啡店2026年9月双人套餐198元，包含2杯拿铁，热饮不加糖。"
                  "门店位于北京路商圈，营业时间为每日10:00-20:00。两杯饮品属于同一份双人套餐。")
        expert = ("<opinion>保留已确认套餐信息，按点单取舍组织正文。</opinion>"
                  "<suggestions>标题说明对象，正文保留数量、位置和时间。</suggestions><confidence>0.8</confidence>"
                  "<clarifications>[]</clarifications>")
        arbitration = ("<diagnosis>可把套餐内容集中说明，避免读者反复查找数量。</diagnosis>"
                       + "".join(f"<plan_{letter}_title>{title}</plan_{letter}_title>"
                                 for letter, title in zip("abc", titles))
                       + "<plan>先说套餐内容，再说明位置与营业时间，最后引导核对。</plan>"
                       "<dispute>分析角度不同，事实均以用户原始说明为准。</dispute>")
        body_calls = []

        def gateway_http(request):
            body = self._check_wire(request)
            system = body["system"]
            user = body["messages"][-1]["content"]
            if system == "你是小红书笔记语义分析专家，只返回JSON，不要解释。":
                text = json.dumps({key: 0.6 for key in api.SEMANTIC_FEATURE_COLS})
            elif body["model"] == SONNET and "本阶段只输出诊断和3个标题" in user:
                text = arbitration
            elif body["model"] == HAIKU and body["max_tokens"] == 16000:
                text = expert
            elif body["model"] == HAIKU and "【本方案标题】" in user:
                selected = [index for index, title in enumerate(titles)
                            if f"【本方案标题】{title}" in user]
                self.assertEqual(len(selected), 1, "body must follow its actual assigned title")
                body_calls.append(selected[0])
                text = bodies[selected[0]]
            elif body["model"] == HAIKU and "文案交付编辑" in system:
                selected = [index for index, title in enumerate(titles)
                            if user.startswith("标题：" + title + "\n")]
                self.assertEqual(len(selected), 1)
                text = bodies[selected[0]]
            else:
                self.fail("unexpected model stage in finite diagnosis fixture")
            return self._response(body, text)

        features = {"body_len": 400, "tag_count": 6, "body_cta_count": 2,
                    "body_has_price": 1, "body_has_address": 1, "body_has_hours": 1,
                    "body_has_must_order": 1}

        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://isolated") as client:
                headers = {"Origin": "https://noteaipro.com", "X-Request-ID": "managed55-diagnosis-once"}
                payload = {"domain": "美食", "note_title": titles[0], "desc": source,
                           "merchant_name": "蓝猫咖啡店", "fact_source_policy": "skip"}
                response = await client.post("/analyze/stream", headers=headers, json=payload)
                self.assertEqual(response.status_code, 200, response.text)
                events = [json.loads(v.removeprefix("data: ").strip()) for v in response.text.split("\n\n")
                          if v.startswith("data: ")]
                self.assertEqual(events[-1]["type"], "complete", events)
                result = events[-1]
                diag_id = result["diagnosis_id"]
                read1 = await client.get("/reports/analyze/" + diag_id, headers={"Origin": "https://noteaipro.com"})
                read2 = await client.get("/reports/analyze/" + diag_id, headers={"Origin": "https://noteaipro.com"})
                self.assertEqual(read1.status_code, 200, read1.text)
                self.assertEqual(read1.json(), read2.json())
                self.assertEqual(read1.json()["result"]["diagnosis_id"], diag_id)
                self.assertEqual(read1.json()["result"]["suggested_plans"], result["suggested_plans"])
                count = len(self.wire)
                duplicate = await client.post("/analyze/stream", headers=headers, json=payload)
                self.assertEqual(duplicate.status_code, 409, duplicate.text)
                self.assertEqual(len(self.wire), count)
                return result

        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {
                "NOTEAI_CLAUDE_TRANSPORT": "gateway", "NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH": "synthetic-config-1",
                "NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH": "synthetic-key-1"}))
            transport = api._mr.GatewayClaudeTransport(base_url="https://gateway.example.invalid", key_id="synthetic-key",
                secret="synthetic-only-secret", http_transport=httpx.MockTransport(gateway_http))
            stack.enter_context(mock.patch.object(api._mr, "get_claude_transport", return_value=transport))
            stack.enter_context(mock.patch.object(config, "read", return_value=managed_snapshot()))
            stack.enter_context(mock.patch.object(api._public_product, "authenticated_user", new=mock.AsyncMock(return_value={"id": uid})))
            api.app.dependency_overrides[api._auth.get_current_user] = lambda: {"id": uid}
            stack.callback(api.app.dependency_overrides.clear)
            stack.enter_context(mock.patch.object(api, "_compute_market_timing_for_delivery", return_value=None))
            stack.enter_context(mock.patch.object(api, "_MEM0_AVAILABLE", False))
            stack.enter_context(mock.patch.object(api, "_predict", return_value=(80.0, features)))
            stack.enter_context(mock.patch.object(api, "_v04_publishable_probability", return_value=None))
            stack.enter_context(mock.patch.object(api, "get_v04_preference_ranker", return_value=None))
            result = asyncio.run(run())
        self.assertEqual(body_calls, [0, 1, 2])
        self.assertEqual(len(result["expert_opinions"]), 4)
        self.assertEqual(len(result["suggested_plans"]), 3)
        self.assertTrue(all(p["body"] and not p["quality_failed"] for p in result["suggested_plans"]), result["suggested_plans"])
        row = dict(db.fetchone("SELECT * FROM idempotency_requests WHERE user_id=?", (uid,)))
        self.assertEqual((row["status"], row["credits_used"], row["charge_applied"], row["refund_applied"], row["complete_applied"]),
                         ("completed", 6, 1, 0, 1))
        self.assertEqual(db.fetchone("SELECT count(*) n FROM usage_records WHERE user_id=?", (uid,))["n"], 1)
        self._proof("analyze", {"real_ASGI_diagnosis": True, "normal_saved_GET": True,
            "four_expert_results_with_missing_cover_explicitly_skipped": True,
            "three_distinct_plans_real_quality_checks": True, "duplicate409_no_call": True, "unique_credits": 6})


if __name__ == "__main__":
    unittest.main()
