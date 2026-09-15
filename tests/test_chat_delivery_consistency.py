import asyncio
import importlib
import json
import os
import sys
import unittest
from unittest.mock import patch, AsyncMock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("NOTEAI_FACT_SEARCH", "0")

api = importlib.import_module("api")


class _FakeDB:
    def __init__(self, *, fail_note_save=False, note_version=1):
        self.fail_note_save = fail_note_save
        self.note_version = note_version
        self.executed = []

    def fetchall(self, sql, params=()):
        return []  # Legacy note fixture has no persisted media/task context.

    def fetchone(self, sql, params=()):
        if "FROM chat_sessions" in sql and params == ("historic",):
            return {
                "id": "historic",
                "user_id": "u1",
                "note_id": "note-root",
                "domain": "美食",
                "local_time": "2026071112",
                "messages_json": "[]",
                "user_prefs_json": "{}",
                "iteration_count": 4,
                "current_score": 75.3,
                "generate_ctx_json": "{}",
            }
        if "FROM notes" in sql and params == ("note-root", "u1"):
            return {
                "id": "note-root",
                "title": "旧标题",
                "body": "旧正文有20分钟、吃不出柴感，半小时就能完成。",
                "domain": "美食",
                "score": 75.3,
                "grade": "优秀",
                "version": self.note_version,
                "parent_id": None,
            }
        return None

    def execute(self, sql, params=()):
        if self.fail_note_save and sql.startswith("INSERT INTO notes"):
            raise RuntimeError("simulated note save failure")
        self.executed.append((sql, params))


class ChatDeliveryConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.original_db = api._db
        self.original_sessions = dict(api._chat_sessions)
        self.original_stream_chat = api._mr.stream_chat
        self.original_repair = api._repair_chat_note_if_needed
        self.original_shape = api._shape_body_for_delivery
        self.original_sanitize = api._sanitize_title_for_delivery
        self.original_score = api._score_chat_note
        self.original_achievements = api._memory.check_and_record_achievements
        self.original_add_context = api._memory.add_context
        api._memory.check_and_record_achievements = lambda *_args, **_kwargs: []
        api._memory.add_context = lambda *_args, **_kwargs: None

    def tearDown(self):
        api._db = self.original_db
        api._chat_sessions.clear()
        api._chat_sessions.update(self.original_sessions)
        api._mr.stream_chat = self.original_stream_chat
        api._repair_chat_note_if_needed = self.original_repair
        api._shape_body_for_delivery = self.original_shape
        api._sanitize_title_for_delivery = self.original_sanitize
        api._score_chat_note = self.original_score
        api._memory.check_and_record_achievements = self.original_achievements
        api._memory.add_context = self.original_add_context

    def _install_session(self):
        api._chat_sessions.clear()
        api._chat_sessions["s1"] = {
            "note_title": "旧标题",
            "note_body": "旧正文有20分钟、吃不出柴感，半小时就能完成。",
            "domain": "美食",
            "local_time": "2026071112",
            "user_id": "u1",
            "current_score": 75.3,
            "messages": [],
            "iteration_count": 0,
            "note_id": "note-root",
            "_last_note_id": "note-root",
            "note_version": 1,
            "user_constraints": [],
            "generate_context": {},
        }

    @staticmethod
    def _events(message="请删掉20分钟、吃不出柴感和半小时，不要保留这些未经提供的说法"):
        async def collect():
            output = []
            async for chunk in api._chat_sse_generator(
                "s1", message
            ):
                if chunk.startswith("data: "):
                    output.append(json.loads(chunk.removeprefix("data: ").strip()))
            return output

        return asyncio.run(collect())

    def test_explicit_structure_is_not_inferred_from_negation_or_ranges(self):
        for message, count in [("请写成三段", 3), ("合并成3个自然段",3), ("分成2段，正文不要重复标题", 2),
                               ("四段正文", 4), ("正文10段", 10), ("正文分3段，结尾留一个自然的问题", 3)]:
            with self.subTest(message=message):
                contract = api._build_chat_turn_constraint_contract(message, "")
                self.assertEqual(contract["paragraph_count"], count)
        for message in ("不是三段", "不要写成三段", "无需分成三段", "分成三段以上",
                        "至少分成三段", "是否分成三段", "三段正文左右", "三到五段",
                        "请写成三段或四段", "正文三段，保持四段", "三到五段正文", "1—3段正文",
                        "两或三段正文", "分成3段或5段正文", "11段正文", "二十段正文",
                        "不能写成三段", "不希望写成三段"):
            with self.subTest(message=message):
                self.assertIsNone(api._build_chat_turn_constraint_contract(message, "")["paragraph_count"])

    def test_structure_counts_paragraphs_without_tags_and_strips_only_exact_heading(self):
        c = api._build_chat_turn_constraint_contract("请分成三段，正文不要重复标题", "")
        body = "画面介绍。\n\n细节介绍。\n\n你关注哪一点？\n\n#门店 #素材"
        self.assertFalse(api._chat_turn_constraint_violations("素材笔记", body, c))
        duplicate = "**素材笔记**\n\n" + body
        self.assertEqual(api._chat_body_without_title_echo("素材笔记", duplicate, c), body)
        mention = "素材笔记里介绍了画面。\n\n细节。\n\n问题？"
        self.assertEqual(api._chat_body_without_title_echo("素材笔记", mention, c), mention)
        self.assertTrue(api._chat_turn_constraint_violations("素材笔记", "只有一段。", c))

    def test_structure_failure_cannot_save_even_with_high_model_score(self):
        fake_db = _FakeDB(); api._db = fake_db; self._install_session()
        async def stream(**_kwargs):
            yield "content", "已分三段。<note><title>新标题</title><body>第一段。\n\n第二段。\n\n第三段。\n\n独立提问？</body></note>"
        api._mr.stream_chat = stream
        api._shape_body_for_delivery = AsyncMock(side_effect=lambda title, body, *_a, **_kw: body)
        api._repair_chat_note_if_needed = AsyncMock(side_effect=lambda t, b, *_a: (t,b,90,{},"优秀",[],False))
        api._sanitize_title_for_delivery = lambda title, *_a: title
        events = self._events("请合并成3个自然段")
        canonical = next(e for e in events if e.get("type") == "canonical_response")
        self.assertEqual(canonical["status"], "constraint_failed")
        self.assertFalse(any(sql.startswith("INSERT INTO notes") for sql, _ in fake_db.executed))
        self.assertFalse(any(e.get("type") == "note_update" for e in events))
        self.assertEqual(api._mr.stream_chat, stream)
        self.assertEqual(api._repair_chat_note_if_needed.await_count, 1)

    def test_existing_repair_receives_structure_issues_without_extra_stage(self):
        self._install_session()
        session = {**api._chat_sessions["s1"], "_turn_contract": api._build_chat_turn_constraint_contract("请写成三段", "")}
        session["_turn_constraint_brief"] = api._chat_turn_constraint_brief(session["_turn_contract"])
        session["generate_context"] = {"cover_analysis":"[00:10]原音画；未确认房内关系"}
        session["fact_context"] = "本次商家确认：不写价格"
        good = "画面介绍。\n\n细节介绍。\n\n你关注哪一点？"
        with patch.object(api, "_score_generated_note", AsyncMock(return_value=(90, {}, "优秀"))), \
             patch.object(api, "_generated_quality_issues", side_effect=lambda *a, **kw: []), \
             patch.object(api, "_delivery_integrity_issues", side_effect=lambda *a, **kw: []), \
             patch.object(api, "_needs_v04_score_lift", return_value=False), \
             patch.object(api, "_shape_body_for_delivery", AsyncMock(side_effect=lambda t,b,*a,**kw: b)), \
             patch.object(api, "_sanitize_title_for_delivery", side_effect=lambda t,*a: t), \
             patch.object(api._mr, "call", AsyncMock(return_value=f"<note><title>素材笔记</title><body>{good}</body></note>")) as call:
            result = asyncio.run(api._repair_chat_note_if_needed("素材笔记", "只有一段。", session, "请写成三段"))
        self.assertEqual(result[1], good, (result, call.await_count))
        self.assertEqual(call.await_count, 1)
        self.assertIn("正文应为3段", call.call_args.args[2])
        self.assertEqual(call.call_args.kwargs["trace_step"], "chat_quality_repair")
        self.assertIn("[00:10]原音画；未确认房内关系",call.call_args.args[1])
        self.assertIn("本次商家确认",call.call_args.args[1])

    def test_option_structure_survives_reload_and_is_enforced_on_server(self):
        fake_db = _FakeDB(); api._db = fake_db; self._install_session()
        session = api._chat_sessions["s1"]
        request = "请写成三段，正文不要重复标题"
        turn = {**session, "_turn_contract": api._build_chat_turn_constraint_contract(request, ""), "_turn_user_request": request}
        raw = "<option id='A'><title>A标题</title><body>只有一段。</body></option><option id='B'><title>B标题</title><body>第一段。\n\n第二段。\n\n第三段。</body></option>"
        with patch.object(api, "_score_chat_note", AsyncMock(return_value=(90,{},"优秀",[]))), \
             patch.object(api, "_sanitize_title_for_delivery", side_effect=lambda t,*a: t):
            options = asyncio.run(api._build_chat_plan_options(turn, raw))
        restored = api._sanitize_chat_generate_context({"pending_plan_options": options})["pending_plan_options"]
        self.assertFalse(restored[0]["selectable"])
        self.assertTrue(restored[1]["selectable"])
        self.assertEqual(restored[0]["edit_request"], request)
        restored[0]["selectable"] = True  # Server must not trust a UI flag.
        with self.assertRaises(api.HTTPException) as error:
            api._save_chat_plan_option_as_note("s1", session, restored[0], "u1")
        self.assertEqual(error.exception.status_code, 422)
        self.assertFalse(any(sql.startswith("INSERT INTO notes") for sql, _ in fake_db.executed))

    def test_score_lift_cannot_replace_a_compliant_draft_with_wrong_structure(self):
        good = "画面介绍。\n\n细节介绍。\n\n你关注哪一点？"
        contract = api._build_chat_turn_constraint_contract("请写成三段", "")
        session = {"domain":"美食", "_turn_contract":contract,
                   "_turn_constraint_brief":api._chat_turn_constraint_brief(contract)}
        with patch.object(api, "_score_chat_note", AsyncMock(return_value=(75,{},"良好",["标题偏短"]))), \
             patch.object(api, "_needs_v04_score_lift", return_value=True), \
             patch.object(api, "_score_directed_second_pass", AsyncMock(return_value=(
                 "更高分标题", "却只有一段。", 95, {}, "优秀", [], True, "已提分"))) as second:
            result = asyncio.run(api._repair_chat_note_if_needed("原标题",good,session,"请写成三段"))
        self.assertEqual(result[:3], ("原标题",good,75))
        self.assertEqual(second.await_count, 1)

    def test_post_repair_score_lift_keeps_the_repaired_structure(self):
        good = "画面介绍。\n\n细节介绍。\n\n你关注哪一点？"
        contract = api._build_chat_turn_constraint_contract("请写成三段", "")
        session = {"domain":"美食", "_turn_contract":contract,
                   "_turn_constraint_brief":api._chat_turn_constraint_brief(contract)}
        with patch.object(api, "_score_chat_note", AsyncMock(side_effect=[
                (75,{},"良好",["用户约束未满足：正文应为3段"]), (76,{},"良好",[])])), \
             patch.object(api, "_needs_v04_score_lift", return_value=True), \
             patch.object(api, "_shape_body_for_delivery", AsyncMock(side_effect=lambda t,b,*a,**kw: b)), \
             patch.object(api, "_sanitize_title_for_delivery", side_effect=lambda t,*a: t), \
             patch.object(api._mr, "call", AsyncMock(return_value=f"<note><title>修复标题</title><body>{good}</body></note>")), \
             patch.object(api, "_score_directed_second_pass", AsyncMock(return_value=(
                 "更高分标题", "却只有一段。", 95, {}, "优秀", [], True, "已提分"))) as second:
            result = asyncio.run(api._repair_chat_note_if_needed("原标题","只有一段。",session,"请写成三段"))
        self.assertEqual(result[:3], ("修复标题",good,76))
        self.assertTrue(result[-1])
        self.assertEqual(second.await_count, 1)

    def test_no_note_with_explicit_structure_is_not_reported_as_done(self):
        api._db = _FakeDB(); self._install_session()
        async def stream(**_kwargs):
            yield "content", "已经整理成三段了。"
        api._mr.stream_chat = stream
        events = self._events("请写成三段")
        canonical = next(e for e in events if e.get("type") == "canonical_response")
        self.assertEqual(canonical["status"], "no_final_note")
        self.assertFalse(canonical["saved"])

    def test_turn_contract_filters_removed_old_claims_from_fact_source(self):
        contract = api._build_chat_turn_constraint_contract(
            "请删掉20分钟、吃不出柴感和半小时，不要保留这些未经提供的说法",
            "旧正文有20分钟、吃不出柴感，半小时就能完成。",
        )

        filtered = api._chat_fact_source_for_turn(
            {"fact_context": "", "note_body": "旧正文有20分钟、吃不出柴感，半小时就能完成。"},
            contract,
        )

        self.assertCountEqual(contract["forbidden_terms"], ["20分钟", "吃不出柴感", "半小时"])
        self.assertNotIn("20分钟", filtered)
        self.assertNotIn("吃不出柴感", filtered)
        self.assertNotIn("半小时", filtered)

        reversed_contract = api._build_chat_turn_constraint_contract(
            "请把吃不出柴感删掉，但保留其他真实描述",
            "旧正文有20分钟、吃不出柴感，半小时就能完成。",
        )
        self.assertEqual(reversed_contract["forbidden_terms"], ["吃不出柴感"])
        keep_contract = api._build_chat_turn_constraint_contract(
            "不要太广告，保留20分钟这个真实信息",
            "旧正文有20分钟、吃不出柴感，半小时就能完成。",
        )
        self.assertEqual(keep_contract["forbidden_terms"], [])

    def test_general_duration_removal_preserves_only_explicitly_confirmed_existing_term(self):
        source = "已确认训练总时长30分钟；旧稿还写了未经确认的20分钟和半小时。"
        contract = api._build_chat_turn_constraint_contract(
            "删除未经提供的具体时长，但保留30分钟这个已确认事实",
            source,
        )

        self.assertTrue(contract["remove_duration_claims"])
        self.assertEqual(contract["protected_terms"], ["30分钟"])
        filtered = api._chat_filter_source_for_turn_contract(source, contract)
        self.assertIn("30分钟", filtered)
        self.assertNotIn("20分钟", filtered)
        self.assertNotIn("半小时", filtered)
        self.assertFalse(api._chat_turn_constraint_violations("标题", "训练总时长30分钟。", contract))
        self.assertTrue(api._chat_turn_constraint_violations("标题", "训练20分钟，半小时完成。", contract))

    def test_bound_note_version_is_authoritative_for_start_and_failure_fallback(self):
        fake_db = _FakeDB(fail_note_save=True, note_version=5)
        api._db = fake_db

        response = asyncio.run(api.chat_start(
            api.ChatStartInput(
                note_title="旧标题",
                note_body="旧正文有20分钟、吃不出柴感，半小时就能完成。",
                note_id="note-root",
                domain="美食",
                generate_context={"current_score": 75.3},
            ),
            user={"id": "u1"},
        ))
        session = api._chat_sessions[response.session_id]
        self.assertEqual(session["note_version"], 5)

        restored = api._load_chat_session_from_db("historic")
        self.assertIsNotNone(restored)
        self.assertEqual(restored["note_version"], 5)

        # Historical sessions may predate note_version persistence; the
        # terminal fallback must still resolve the bound note's DB version.
        session.pop("note_version")
        api._chat_sessions["s1"] = session

        async def fake_stream_chat(**_kwargs):
            yield "content", "已完成。<note><title>新标题</title><body>只保留真实菜品体验。</body></note>"

        async def clean_shape(title, body, domain, fact_source, route, *, constraint_context=""):
            self.assertIn("不得", constraint_context)
            return body

        async def fake_repair(title, body, session, user_msg, **_kwargs):
            return title, body, 74.1, {}, "良好", [], False

        api._mr.stream_chat = fake_stream_chat
        api._shape_body_for_delivery = clean_shape
        api._repair_chat_note_if_needed = fake_repair
        api._sanitize_title_for_delivery = lambda title, *_args: title

        events = self._events()
        canonical = next(ev for ev in events if ev.get("type") == "canonical_response")
        self.assertEqual(canonical["status"], "save_failed")
        self.assertEqual(canonical["saved_note_version"], 5)
        self.assertEqual(api._chat_sessions["s1"].get("note_version"), 5)

    def test_final_constraint_failure_keeps_previous_version_and_never_claims_save(self):
        fake_db = _FakeDB()
        api._db = fake_db
        self._install_session()

        async def fake_stream_chat(**_kwargs):
            yield "content", "已全部删除。<note><title>新标题</title><body>干净草稿。</body></note>"

        async def reintroducing_shape(*_args, **_kwargs):
            return "后处理又写回20分钟、吃不出柴感和半小时。"

        async def fake_repair(title, body, session, user_msg, **_kwargs):
            return title, body, 74.1, {}, "良好", [], True

        api._mr.stream_chat = fake_stream_chat
        api._shape_body_for_delivery = reintroducing_shape
        api._repair_chat_note_if_needed = fake_repair
        api._sanitize_title_for_delivery = lambda title, *_args: title

        events = self._events()

        self.assertFalse(any(ev.get("type") == "note_update" for ev in events))
        canonical = next(ev for ev in events if ev.get("type") == "canonical_response")
        self.assertFalse(canonical["saved"])
        self.assertEqual(canonical["status"], "constraint_failed")
        self.assertEqual(canonical["title"], "旧标题")
        self.assertEqual(canonical["body"], "旧正文有20分钟、吃不出柴感，半小时就能完成。")
        self.assertFalse(any(sql.startswith("INSERT INTO notes") for sql, _ in fake_db.executed))
        self.assertEqual(api._chat_sessions["s1"]["note_body"], canonical["body"])
        self.assertEqual(api._chat_sessions["s1"]["note_version"], 1)

    def test_saved_canonical_response_note_update_session_and_insert_are_identical(self):
        fake_db = _FakeDB()
        api._db = fake_db
        self._install_session()

        async def fake_stream_chat(**_kwargs):
            yield "content", "已删除旧说法。<note><title>新标题</title><body>只保留真实菜品体验。</body></note>"

        async def clean_shape(title, body, domain, fact_source, route, *, constraint_context=""):
            self.assertIn("不得", constraint_context)
            self.assertNotIn("20分钟", fact_source)
            self.assertNotIn("吃不出柴感", fact_source)
            self.assertNotIn("半小时", fact_source)
            return body

        async def fake_repair(title, body, session, user_msg, **_kwargs):
            return title, body, 74.1, {}, "良好", [], False

        api._mr.stream_chat = fake_stream_chat
        api._shape_body_for_delivery = clean_shape
        api._repair_chat_note_if_needed = fake_repair
        api._sanitize_title_for_delivery = lambda title, *_args: title

        events = self._events()

        note_update = next(ev for ev in events if ev.get("type") == "note_update")
        canonical = next(ev for ev in events if ev.get("type") == "canonical_response")
        inserted = next(params for sql, params in fake_db.executed if sql.startswith("INSERT INTO notes"))
        session = api._chat_sessions["s1"]

        self.assertTrue(canonical["saved"])
        self.assertEqual(canonical["status"], "saved")
        for field in ("title", "body", "score", "grade", "saved_note_id", "saved_note_version"):
            self.assertEqual(canonical[field], note_update[field])
        self.assertEqual((inserted[2], inserted[3], inserted[5], inserted[6], inserted[9]), (
            canonical["title"], canonical["body"], canonical["score"], canonical["grade"], canonical["saved_note_version"],
        ))
        self.assertEqual((session["note_title"], session["note_body"], session["current_score"], session["note_version"]), (
            canonical["title"], canonical["body"], canonical["score"], canonical["saved_note_version"],
        ))
        self.assertFalse(api._chat_turn_constraint_violations(canonical["title"], canonical["body"], canonical["turn_constraint"]))

    def test_note_save_failure_keeps_previous_version_and_emits_no_success_update(self):
        fake_db = _FakeDB(fail_note_save=True)
        api._db = fake_db
        self._install_session()

        async def fake_stream_chat(**_kwargs):
            yield "content", "已完成。<note><title>新标题</title><body>只保留真实菜品体验。</body></note>"

        async def clean_shape(title, body, domain, fact_source, route, *, constraint_context=""):
            self.assertIn("不得", constraint_context)
            return body

        async def fake_repair(title, body, session, user_msg, **_kwargs):
            return title, body, 74.1, {}, "良好", [], False

        api._mr.stream_chat = fake_stream_chat
        api._shape_body_for_delivery = clean_shape
        api._repair_chat_note_if_needed = fake_repair
        api._sanitize_title_for_delivery = lambda title, *_args: title

        events = self._events()

        self.assertFalse(any(ev.get("type") == "note_update" for ev in events))
        canonical = next(ev for ev in events if ev.get("type") == "canonical_response")
        self.assertFalse(canonical["saved"])
        self.assertEqual(canonical["status"], "save_failed")
        self.assertEqual(canonical["title"], "旧标题")
        self.assertEqual(canonical["saved_note_version"], 1)
        self.assertEqual(api._chat_sessions["s1"]["note_body"], canonical["body"])
        self.assertEqual(api._chat_sessions["s1"]["_last_note_id"], "note-root")

    def test_removal_claim_without_final_note_cannot_masquerade_as_completed_rewrite(self):
        fake_db = _FakeDB()
        api._db = fake_db
        self._install_session()

        async def fake_stream_chat(**_kwargs):
            yield "content", "已经全部删掉了，你可以直接发布。"

        api._mr.stream_chat = fake_stream_chat

        events = self._events()

        self.assertFalse(any(ev.get("type") == "note_update" for ev in events))
        canonical = next(ev for ev in events if ev.get("type") == "canonical_response")
        self.assertEqual(canonical["status"], "no_final_note")
        self.assertFalse(canonical["saved"])
        self.assertEqual(canonical["body"], "旧正文有20分钟、吃不出柴感，半小时就能完成。")
        self.assertNotIn("可以直接发布", json.dumps(api._chat_sessions["s1"]["messages"], ensure_ascii=False))
        self.assertFalse(any(sql.startswith("INSERT INTO notes") for sql, _ in fake_db.executed))


if __name__ == "__main__":
    unittest.main()
