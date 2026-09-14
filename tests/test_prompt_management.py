import asyncio
import hashlib
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODEL_DIR = Path(__file__).resolve().parents[1] / "model"
import sys

sys.path.insert(0, str(MODEL_DIR))

import admin_server
import api
import db
import prompt_baselines
import prompt_composer
import prompt_manager


class PromptBaselineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db_path = db._DB_PATH
        db._DB_PATH = Path(self.temp.name) / "noteai.db"
        db.init_db()
        prompt_manager._cache.clear()
        prompt_manager._cache_ts = 0

    def tearDown(self):
        db._DB_PATH = self.original_db_path
        prompt_manager._cache.clear()
        prompt_manager._cache_ts = 0
        self.temp.cleanup()

    def _insert_legacy_rows(self):
        current = prompt_baselines.load_current_baseline()
        for key in prompt_baselines.PROMPT_KEYS:
            legacy = prompt_baselines.ACCEPTED_LEGACY[key][0]
            db.execute(
                "INSERT INTO managed_prompts(key,label,module,content,version,updated_at) "
                "VALUES(?,?,?,?,?,?)",
                (
                    key,
                    legacy["label"],
                    current[key]["module"],
                    f"known legacy fixture: {key}",
                    legacy["version"],
                    "2026-06-17T00:00:00+00:00",
                ),
            )

    def test_request_keeps_published_prompt_versions_across_parallel_steps(self):
        prompt_manager.apply_versioned_baseline()
        first = prompt_manager.capture_request()
        old = first.rows["agent_content_system"]["content"]
        token = prompt_manager.bind_request(first)
        try:
            db.execute("UPDATE managed_prompts SET content=?,version=version+1 WHERE key=?",
                       ("new published revision", "agent_content_system"))
            prompt_manager.reload()

            async def steps():
                async def step():
                    await asyncio.sleep(0)
                    return prompt_manager.get("agent_content_system")
                return await asyncio.gather(step(), step())

            self.assertEqual(asyncio.run(steps()), [old, old])
            metadata = prompt_manager.request_versions()["agent_content_system"]
            self.assertEqual(metadata["sha256"], hashlib.sha256(old.encode()).hexdigest())
            self.assertNotIn("content", metadata)
            self.assertEqual(prompt_manager.get("absent_test_prompt", "code value"), "code value")
            self.assertEqual(prompt_manager.request_versions()["absent_test_prompt"]["source"], "code_fallback")
        finally:
            prompt_manager.release_request(token)
        second = prompt_manager.capture_request()
        token = prompt_manager.bind_request(second)
        try:
            self.assertEqual(prompt_manager.get("agent_content_system"), "new published revision")
        finally:
            prompt_manager.release_request(token)
        self.assertEqual(prompt_manager.request_versions(), {})

    def test_parallel_calls_keep_exact_templates_and_composed_instruction_hash(self):
        prompt_manager.apply_versioned_baseline()
        snapshot = prompt_manager.capture_request()
        token = prompt_manager.bind_request(snapshot)
        calls = []
        class Transport:
            async def create_message(_self, request):
                calls.append(request)
                await asyncio.sleep(0)
                return api._mr.ClaudeMessageResult(("<opinion>ok</opinion>",),
                    usage={"input_tokens":2,"output_tokens":1,"cache_read_input_tokens":0,"cache_creation_input_tokens":0},
                    model=request.model, stop_reason="end_turn")
        async def run():
            await asyncio.gather(
                api._agent_content("标题", "素材", "美食", [], {}, "本次回答"),
                api._agent_growth("标题", "素材", "旅行", None, {}, "不同商家"),
            )
        try:
            with mock.patch.object(api._mr, "get_claude_transport", return_value=Transport()), \
                 mock.patch.object(api._mr, "claude_transport_mode", return_value="local"), \
                 mock.patch.object(api._mr._public_product, "enabled", return_value=True), \
                 mock.patch.object(api._mr._runtime_config, "resolve", side_effect=lambda task, model, maximum:(model,maximum)), \
                 mock.patch.object(api._mr, "_record_request_claude_usage"), \
                 mock.patch.object(api._mr, "_finish_claude_call"):
                asyncio.run(run())
            self.assertEqual(len(calls), 2)
            for request, key, domain in zip(calls, ("agent_content_system", "agent_growth_system"), ("美食", "旅行")):
                trace = request.call_state["provenance"]
                self.assertEqual(set(trace["prompts"]), {key})
                self.assertEqual(trace["prompt_domain"], domain)
                self.assertEqual(trace["task"], "diagnosis")
                self.assertEqual(trace["prompt_scope"], "call_templates")
                self.assertEqual(trace["instruction_sha256"], hashlib.sha256(request.system.encode()).hexdigest())
                self.assertEqual(trace["prompts"][key]["version"], snapshot.rows[key]["version"])
                self.assertNotIn(request.system, json.dumps(trace, ensure_ascii=False))
            old = json.dumps(calls[0].call_state["provenance"], sort_keys=True)
            prompt_manager.get("chat_system")
            snapshot.used["agent_content_system"]["version"] = 999
            self.assertEqual(json.dumps(calls[0].call_state["provenance"], sort_keys=True), old)
            inline = prompt_manager.call_provenance("diagnosis", "code instructions", prompt_keys=())
            self.assertEqual(inline["prompts"], {})
            self.assertEqual(inline["prompt_scope"], "call_templates")
            legacy = prompt_manager.call_provenance("diagnosis", "instructions")
            self.assertEqual(legacy["prompt_scope"], "request_snapshot")
            self.assertIn("chat_system", legacy["prompts"])
            missing = prompt_manager.call_provenance("diagnosis", "instructions", prompt_keys=("not_loaded",))
            self.assertEqual(missing["missing_prompt_keys"], ["not_loaded"])
        finally:
            prompt_manager.release_request(token)

    def test_new_request_bypasses_cache_without_changing_inflight_snapshot(self):
        prompt_manager.apply_versioned_baseline()
        first = prompt_manager.capture_request()
        db.execute("UPDATE managed_prompts SET content=?,version=version+1 WHERE key=?",
                   ("published inside cache TTL", "chat_system"))
        second = prompt_manager.capture_request()
        self.assertEqual(second.rows["chat_system"]["content"], "published inside cache TTL")
        self.assertNotEqual(first.rows["chat_system"]["content"], second.rows["chat_system"]["content"])

    def test_diagnosis_leaf_requests_keep_material_constraints_and_memory_tail(self):
        prompt_manager.apply_versioned_baseline()
        body = "真实素材。" * 300 + "末尾素材：无糖、不含坚果。"
        context = "图片与商家背景。" * 300 + "硬约束：不能更改价格。\n用户记忆：不要夸大功效。"
        calls = []

        async def capture(task, system, user, **kwargs):
            calls.append((task, system, user))
            return "<opinion>offline fixture</opinion>"

        async def run():
            await asyncio.gather(
                api._agent_content("真实标题", body, "美食", [], {}, context),
                api._agent_growth("真实标题", body, "美食", None, {}, context),
                api._agent_user("真实标题", body, "美食", {}, [], {}, context),
            )

        with mock.patch.object(api._mr, "call", side_effect=capture):
            asyncio.run(run())
        self.assertEqual(len(calls), 3)
        for task, system, user in calls:
            self.assertEqual(task, "diagnosis")
            self.assertIn(body, user)
            self.assertIn(context, user)
            self.assertIn("不计入正文长度/评分", user)

    def test_generation_memory_reaches_creators_arbiter_and_challenger_separate_from_facts(self):
        prompt_manager.apply_versioned_baseline()
        memory = "历史参考标记：旧店地址仅为历史；偏好自然语气。"
        brief = "已核实本次素材。" * 300 + "本次唯一地址：新店。"
        calls = []

        async def capture(task, system, user, **kwargs):
            calls.append((system, user))
            return "<title>离线测试标题</title><body>离线测试正文</body>"

        async def run():
            await api._gent_content("美食", brief, {}, "图片观察", memory)
            await api._gent_growth("美食", brief, None, {}, "图片观察", memory)
            await api._gent_user("美食", brief, {}, "图片观察", memory)
            await api._gent_arbitrate("美食", [], None, [], fact_context=brief, memory_context=memory)
            await api._generate_quality_challenger_candidate(
                domain="美食", brief=brief, image_desc="图片观察", timing=None,
                current_title="原稿", current_body="原稿正文", memory_context=memory)

        with mock.patch.object(api._mr, "call", side_effect=capture), \
             mock.patch.object(api, "_generation_candidate_count", return_value=2):
            asyncio.run(run())
        self.assertGreaterEqual(len(calls), 5)
        # Delivery shaping now makes additional calls; every stage must retain
        # the full source rather than counting exactly five old entry calls.
        self.assertTrue(all(brief in user for _, user in calls))
        for system, user in calls:
            self.assertIn(memory, system)
            self.assertIn("不构成本次", system)
            self.assertNotIn(memory, user)

    def test_generation_uses_real_industry_while_stats_preserve_legacy_fallback(self):
        import hot_keywords
        class StopBeforeProvider(Exception):
            pass
        for domain in ("美妆", "家居", "母婴", "酒店"):
            for endpoint in (api.generate_stream_endpoint, api.generate):
                queries = []
                def timing(title, body, actual_domain):
                    queries.append(actual_domain)
                    raise StopBeforeProvider()
                with mock.patch.object(api, "_compute_market_timing_for_delivery", side_effect=timing), \
                     mock.patch.object(api, "_paid_request_claim", return_value=None), \
                     mock.patch.object(api._billing, "check_and_deduct"), \
                     mock.patch.object(api._billing, "get_subscription", return_value={"tier": "pro"}), \
                     mock.patch.object(api, "_maybe_enrich_facts", new=mock.AsyncMock(return_value={})), \
                     mock.patch.object(api._mr, "call", side_effect=AssertionError("provider forbidden")):
                    try:
                        asyncio.run(endpoint(api.GenerateInput(domain=domain, brief="合法离线素材"),
                                             user={"id": "owner"}, request_id=None))
                    except Exception:
                        pass
                self.assertEqual(queries, [domain])
        with mock.patch.object(hot_keywords, "_load_domain_stats"), \
             mock.patch.object(hot_keywords, "_DOMAIN_STATS", {
                 "穿搭": {"avg_ces": 63, "saturation": .138},
                 "美妆": {"avg_ces": 64, "saturation": .04},
                 "职场": {"avg_ces": 62, "saturation": .095}}):
            self.assertEqual(hot_keywords.get_domain_stats("美妆")["saturation"], .04)
            self.assertEqual(hot_keywords.get_domain_stats("家居")["saturation"], .095)

    def test_memory_isolates_user_and_industry_and_does_not_treat_orphans_as_current_context(self):
        import memory
        for uid in ("owner", "other"):
            db.execute("INSERT INTO users(id,username,password_hash,password_salt,created_at) VALUES(?,?,?,?,?)",
                       (uid, uid, "offline-no-login", "offline", "2026-09-13T00:00:00Z"))
        for nid, uid, domain in (("food", "owner", "美食"), ("beauty", "owner", "美妆"), ("otherfood", "other", "美食")):
            db.execute("INSERT INTO notes(id,user_id,title,body,domain,source,created_at) VALUES(?,?,?,?,?,?,?)",
                       (nid, uid, "offline", "offline", domain, "generate", "2026-09-13T00:00:00Z"))
        memory.add_memory("owner", "style", "本人写作偏好")
        memory.add_memory("other", "style", "其他用户私有偏好")
        for nid, text in (("food", "本人餐饮参考"), ("beauty", "本人美妆参考"), ("otherfood", "错误关联他人笔记"), (None, "无来源历史")):
            memory.add_memory("owner", "context", text, source_note_id=nid)
        result = memory.build_memory_prompt("owner", domain="美食")
        self.assertIn("本人写作偏好", result)
        self.assertIn("本人餐饮参考", result)
        for excluded in ("其他用户私有偏好", "本人美妆参考", "错误关联他人笔记", "无来源历史"):
            self.assertNotIn(excluded, result)
        untouched = db.fetchall("SELECT access_count FROM user_memories WHERE content IN(?,?,?)",
                               ("本人美妆参考", "错误关联他人笔记", "无来源历史"))
        self.assertTrue(all(row["access_count"] == 0 for row in untouched))

    def test_restored_chat_recalls_memory_only_after_owner_and_admission_checks(self):
        from fastapi import HTTPException
        uid, sid = "chat-owner", "restored-offline-chat"
        db.execute("INSERT INTO users(id,username,password_hash,password_salt,created_at) VALUES(?,?,?,?,?)",
                   (uid, uid, "offline-no-login", "offline", "2026-09-13T00:00:00Z"))
        session = {"user_id": uid, "domain": "美食", "messages": [], "note_title": "原标题", "note_body": "原正文"}
        original = dict(api._chat_sessions)
        class StopAtModelInput(Exception):
            pass
        captured = []
        original_builder = api._build_chat_system_prompt
        def capture(session):
            captured.append(original_builder(session))
            raise StopAtModelInput()
        try:
            api._chat_sessions[sid] = session
            self.assertTrue(api._persist_chat_session(sid))
            api._chat_sessions.pop(sid)
            with mock.patch.object(api._memory, "build_memory_prompt", return_value="本人恢复记忆标记") as recall, \
                 mock.patch.object(api, "_build_chat_system_prompt", side_effect=capture), \
                 mock.patch.object(api, "_paid_request_claim", return_value=None), \
                 mock.patch.object(api._billing, "check_and_deduct"), \
                 mock.patch.object(api._billing, "record_free_usage"):
                req = api.ChatMessageInput(session_id=sid, message="继续聊原稿")
                with self.assertRaises(HTTPException):
                    asyncio.run(api.chat_message(req, user={"id": "intruder"}, request_id=None))
                recall.assert_not_called()
                with self.assertRaises(HTTPException):
                    asyncio.run(api.chat_select_plan(api.ChatSelectPlanInput(session_id=sid, option_id="absent"), user={"id": uid}))
                recall.assert_not_called()
                async def run():
                    response = await api.chat_message(req, user={"id": uid}, request_id=None)
                    recall.assert_not_called()
                    return [chunk async for chunk in response.body_iterator]
                events = asyncio.run(run())
                recall.assert_called_once_with(uid, domain="美食")
                self.assertIn("本人恢复记忆标记", captured[0])
                self.assertTrue(any('"error"' in chunk for chunk in events))
                self.assertTrue(api._persist_chat_session(sid))
                row = dict(db.fetchone("SELECT * FROM chat_sessions WHERE id=?", (sid,)))
                self.assertNotIn("本人恢复记忆标记", json.dumps(row, ensure_ascii=False))
        finally:
            api._chat_sessions.clear()
            api._chat_sessions.update(original)

    def _legacy_hash_patch(self):
        real_hash = prompt_baselines.content_sha256

        def fixture_hash(content):
            prefix = "known legacy fixture: "
            if str(content).startswith(prefix):
                key = str(content)[len(prefix):]
                return prompt_baselines.ACCEPTED_LEGACY[key][0]["sha256"]
            return real_hash(content)

        return mock.patch.object(prompt_manager, "_content_sha256", side_effect=fixture_hash), mock.patch.object(
            prompt_baselines, "content_sha256", side_effect=fixture_hash
        )

    def _marker(self):
        return json.loads(
            db.fetchone(
                "SELECT value_json FROM system_settings WHERE key='managed_prompt_baseline'"
            )["value_json"]
        )

    def _write_marker(self, marker):
        db.execute(
            "UPDATE system_settings SET value_json=? WHERE key='managed_prompt_baseline'",
            (json.dumps(marker, ensure_ascii=False),),
        )

    def test_all_current_baselines_are_v04_and_keep_contracts(self):
        prompts = prompt_baselines.load_current_baseline()
        self.assertEqual(set(prompts), set(prompt_baselines.PROMPT_KEYS))
        self.assertEqual(len(prompts), 12)
        banned = prompt_composer.LEGACY_PROMPT_PATTERN
        required = {
            "semantic_features": ("semantic_emotional_intensity", "semantic_empathetic_engagement", "semantic_rhetorical_score"),
            "agent_content_system": ("<opinion>", "<titles>", "<body>", "<confidence>"),
            "agent_visual_system": ("<opinion>", "<titles>", "<body>", "<confidence>"),
            "agent_growth_system": ("<opinion>", "<titles>", "<body>", "<confidence>"),
            "agent_user_system": ("<opinion>", "<titles>", "<body>", "<confidence>"),
            "agent_arbitrate_system": ("<diagnosis>", "<titles>", "<plan>", "<body>"),
            "gent_visual_system": ("<image_desc>", "<inspiration>"),
            "gent_content_system": ("<draft_title>", "<draft_body>"),
            "gent_growth_system": ("<timing_tip>", "<keyword_tip>"),
            "gent_user_system": ("<user_angle>", "<hook>"),
            "gent_arbitrate_system": ("<title>", "<body>", "<variants>", "<rationale>"),
            "chat_system": ("<note>", "<title>", "<body>"),
        }
        for key, prompt in prompts.items():
            with self.subTest(key=key):
                self.assertIsNone(banned.search(prompt["content"]))
                self.assertNotIn("37%权重", prompt["content"])
                for marker in required[key]:
                    self.assertIn(marker, prompt["content"])

    def test_spaced_legacy_wording_is_removed_by_shared_composer(self):
        result = prompt_composer.compose_effective_prompt(
            "agent_content_system",
            "美食",
            "v0.3 模型各品类高分笔记真实基准；CES≥70；37%权重",
        )
        self.assertNotRegex(result.text, r"(?i)v\s*0\.3\s*模型")
        self.assertNotIn("CES≥70", result.text)
        self.assertNotIn("37%权重", result.text)
        self.assertIn("V0.4运行时最高优先级覆盖", result.text)

    def test_known_seed_upgrade_writes_history_and_is_idempotent(self):
        self._insert_legacy_rows()
        manager_patch, baseline_patch = self._legacy_hash_patch()
        with manager_patch, baseline_patch:
            first = prompt_manager.apply_versioned_baseline()
        self.assertEqual(first["updated"], 12)
        self.assertEqual(first["skipped_custom"], 0)
        history_count = db.fetchone("SELECT COUNT(*) AS cnt FROM prompt_history")["cnt"]
        self.assertEqual(history_count, 12)
        second = prompt_manager.apply_versioned_baseline()
        self.assertEqual(second["updated"], 0)
        self.assertEqual(second["already_current"], 12)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS cnt FROM prompt_history")["cnt"], 12)

    def test_empty_database_inserts_current_baseline_once(self):
        first = prompt_manager.apply_versioned_baseline()
        self.assertEqual(first["inserted"], 12)
        self.assertEqual(first["updated"], 0)
        second = prompt_manager.apply_versioned_baseline()
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(second["already_current"], 12)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS cnt FROM prompt_history")["cnt"], 0)

    def test_empty_database_apply_then_rollback_removes_only_inserted_rows(self):
        applied = prompt_manager.apply_versioned_baseline()
        self.assertEqual(applied["inserted"], 12)
        rolled_back = prompt_manager.rollback_versioned_baseline()
        self.assertEqual(rolled_back["restored"], 0)
        self.assertEqual(rolled_back["removed"], 12)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS cnt FROM managed_prompts")["cnt"], 0)
        marker = json.loads(
            db.fetchone(
                "SELECT value_json FROM system_settings WHERE key='managed_prompt_baseline'"
            )["value_json"]
        )
        self.assertEqual(marker["status"], "rolled_back")
        self.assertEqual(marker["restored_count"], 0)
        self.assertEqual(marker["removed_count"], 12)

    def test_inserted_prompt_edit_blocks_whole_rollback_before_delete(self):
        prompt_manager.apply_versioned_baseline()
        db.execute(
            "UPDATE managed_prompts SET content=? WHERE key=?",
            ("later custom", "chat_system"),
        )
        with self.assertRaises(prompt_manager.PromptBaselineRollbackBlocked):
            prompt_manager.rollback_versioned_baseline()
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS cnt FROM managed_prompts")["cnt"], 12)
        marker = json.loads(
            db.fetchone(
                "SELECT value_json FROM system_settings WHERE key='managed_prompt_baseline'"
            )["value_json"]
        )
        self.assertEqual(marker["status"], "applied")

    def test_inserted_prompt_label_only_edit_blocks_whole_rollback(self):
        prompt_manager.apply_versioned_baseline()
        db.execute(
            "UPDATE managed_prompts SET label=? WHERE key=?",
            ("later label", "chat_system"),
        )
        with self.assertRaises(prompt_manager.PromptBaselineRollbackBlocked):
            prompt_manager.rollback_versioned_baseline()
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS cnt FROM managed_prompts")["cnt"], 12)
        self.assertEqual(self._marker()["status"], "applied")

    def test_inserted_prompt_module_only_edit_blocks_whole_rollback(self):
        prompt_manager.apply_versioned_baseline()
        db.execute(
            "UPDATE managed_prompts SET module=? WHERE key=?",
            ("later module", "chat_system"),
        )
        with self.assertRaises(prompt_manager.PromptBaselineRollbackBlocked):
            prompt_manager.rollback_versioned_baseline()
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS cnt FROM managed_prompts")["cnt"], 12)
        self.assertEqual(self._marker()["status"], "applied")

    def test_inserted_prompt_delete_failure_rolls_back_all_deletes_and_marker(self):
        prompt_manager.apply_versioned_baseline()
        original_execute = db.Transaction.execute
        deletes = 0

        def fail_midway(transaction, sql, params=()):
            nonlocal deletes
            if sql.startswith("DELETE FROM managed_prompts"):
                deletes += 1
                if deletes == 3:
                    raise RuntimeError("synthetic rollback failure")
            return original_execute(transaction, sql, params)

        with mock.patch.object(db.Transaction, "execute", fail_midway):
            with self.assertRaises(RuntimeError):
                prompt_manager.rollback_versioned_baseline()
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS cnt FROM managed_prompts")["cnt"], 12)
        marker = json.loads(
            db.fetchone(
                "SELECT value_json FROM system_settings WHERE key='managed_prompt_baseline'"
            )["value_json"]
        )
        self.assertEqual(marker["status"], "applied")

    def test_custom_content_is_skipped_and_dry_run_has_zero_writes(self):
        self._insert_legacy_rows()
        db.execute(
            "UPDATE managed_prompts SET content=? WHERE key=?",
            ("管理员自定义内容", "chat_system"),
        )
        before = db.fetchone("SELECT COUNT(*) AS cnt FROM prompt_history")["cnt"]
        manager_patch, baseline_patch = self._legacy_hash_patch()
        with manager_patch, baseline_patch:
            preview = prompt_manager.apply_versioned_baseline(dry_run=True)
        self.assertEqual(preview["eligible_update"], 11)
        self.assertEqual(preview["skipped_custom"], 1)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS cnt FROM prompt_history")["cnt"], before)
        self.assertIsNone(db.fetchone("SELECT key FROM system_settings WHERE key='managed_prompt_baseline'"))
        self.assertEqual(
            db.fetchone("SELECT content FROM managed_prompts WHERE key='agent_content_system'")["content"],
            "known legacy fixture: agent_content_system",
        )
        manager_patch, baseline_patch = self._legacy_hash_patch()
        with manager_patch, baseline_patch:
            result = prompt_manager.apply_versioned_baseline()
        self.assertEqual(result["updated"], 11)
        self.assertEqual(result["skipped_custom"], 1)
        self.assertEqual(prompt_manager.get("chat_system"), "管理员自定义内容")

    def test_failed_batch_rolls_back_every_prompt(self):
        self._insert_legacy_rows()
        original_execute = db.Transaction.execute
        updates = 0

        def fail_midway(transaction, sql, params=()):
            nonlocal updates
            if sql.startswith("UPDATE managed_prompts"):
                updates += 1
                if updates == 3:
                    raise RuntimeError("synthetic migration failure")
            return original_execute(transaction, sql, params)

        manager_patch, baseline_patch = self._legacy_hash_patch()
        with manager_patch, baseline_patch, mock.patch.object(db.Transaction, "execute", fail_midway):
            with self.assertRaises(RuntimeError):
                prompt_manager.apply_versioned_baseline()
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS cnt FROM prompt_history")["cnt"], 0)
        for key in prompt_baselines.PROMPT_KEYS:
            row = db.fetchone("SELECT content FROM managed_prompts WHERE key=?", (key,))
            self.assertEqual(row["content"], f"known legacy fixture: {key}")

    def test_hash_and_marker_guarded_rollback(self):
        self._insert_legacy_rows()
        manager_patch, baseline_patch = self._legacy_hash_patch()
        with manager_patch, baseline_patch:
            prompt_manager.apply_versioned_baseline()
        result = prompt_manager.rollback_versioned_baseline()
        self.assertEqual(result["restored"], 12)
        self.assertEqual(result["removed"], 0)
        for key in prompt_baselines.PROMPT_KEYS:
            row = db.fetchone("SELECT content FROM managed_prompts WHERE key=?", (key,))
            self.assertEqual(row["content"], f"known legacy fixture: {key}")

        manager_patch, baseline_patch = self._legacy_hash_patch()
        with manager_patch, baseline_patch:
            prompt_manager.apply_versioned_baseline()
        db.execute("UPDATE managed_prompts SET content=? WHERE key=?", ("later custom", "chat_system"))
        with self.assertRaises(prompt_manager.PromptBaselineRollbackBlocked):
            prompt_manager.rollback_versioned_baseline()

    def test_upgraded_prompt_metadata_edit_blocks_whole_rollback(self):
        self._insert_legacy_rows()
        manager_patch, baseline_patch = self._legacy_hash_patch()
        with manager_patch, baseline_patch:
            prompt_manager.apply_versioned_baseline()
        db.execute(
            "UPDATE managed_prompts SET label=? WHERE key=?",
            ("later label", "agent_content_system"),
        )
        with self.assertRaises(prompt_manager.PromptBaselineRollbackBlocked):
            prompt_manager.rollback_versioned_baseline()
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS cnt FROM managed_prompts")["cnt"], 12)
        self.assertEqual(self._marker()["status"], "applied")

        baseline = prompt_baselines.load_current_baseline()["agent_content_system"]
        db.execute(
            "UPDATE managed_prompts SET label=?,module=? WHERE key=?",
            (baseline["label"], "later module", "agent_content_system"),
        )
        with self.assertRaises(prompt_manager.PromptBaselineRollbackBlocked):
            prompt_manager.rollback_versioned_baseline()
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS cnt FROM managed_prompts")["cnt"], 12)

    def test_corrupt_upgraded_marker_shapes_are_uniformly_blocked(self):
        self._insert_legacy_rows()
        manager_patch, baseline_patch = self._legacy_hash_patch()
        with manager_patch, baseline_patch:
            prompt_manager.apply_versioned_baseline()
        original = self._marker()
        first = original["upgraded"][0]
        invalid_shapes = (
            {},
            ["not-a-dict"],
            [first, dict(first)],
            [{**first, "from_version": str(first["from_version"])}],
            [{**first, "to_version": first["from_version"] + 2}],
        )
        for corrupted in invalid_shapes:
            with self.subTest(corrupted=repr(corrupted)[:80]):
                marker = dict(original)
                marker["upgraded"] = corrupted
                self._write_marker(marker)
                with self.assertRaises(prompt_manager.PromptBaselineRollbackBlocked):
                    prompt_manager.rollback_versioned_baseline()
                self.assertEqual(db.fetchone("SELECT COUNT(*) AS cnt FROM managed_prompts")["cnt"], 12)
                self.assertEqual(self._marker()["status"], "applied")


class PromptComposerContractTests(unittest.TestCase):
    def test_api_and_admin_preview_share_composer_for_all_domains(self):
        domains = ["美食", "旅行", "穿搭", "美妆", "家居", "健身", "母婴"]
        with mock.patch.object(api._pm, "get", return_value="V0.4基础内容"):
            for domain in domains:
                with self.subTest(domain=domain):
                    api_text = api._runtime_prompt("agent_content_system", domain)
                    preview = admin_server._build_effective_prompt_preview(
                        "agent_content_system", domain, "V0.4基础内容", 5
                    )
                    self.assertIn(api_text, preview["rendered_text"])
                    self.assertEqual(preview["domain"], domain)
                    self.assertEqual(preview["preview_kind"], "published_industry_layers")
                    self.assertIn(api._get_dk(domain)["content"], preview["rendered_text"])
                    self.assertIn(api._get_quality_contract(domain), preview["rendered_text"])
                    self.assertEqual(preview["edit_scope"], "shared_key_all_industries")
                    self.assertFalse(preview["preview_complete"])
                    self.assertTrue(preview["dynamic_layers"])
                    self.assertNotIn("用户正文", preview["rendered_text"])
                    self.assertNotIn("reasoning", preview["rendered_text"].lower())

        with mock.patch.object(api._pm, "get", return_value="标题：{title}\n正文：{desc}"):
            api_text = api._KIMI_SEMANTIC_PROMPT()
            preview = admin_server._build_effective_prompt_preview(
                "semantic_features", "美食", "标题：{title}\n正文：{desc}", 8
            )
            self.assertEqual(preview["rendered_text"], api_text)
            self.assertEqual(preview["domain"], "通用")
            self.assertEqual(preview["requested_domain"], "美食")
            self.assertEqual(len(preview["dynamic_layers"]), 1)

    def test_every_industry_preview_contains_substantive_shared_runtime_rules(self):
        baseline = prompt_baselines.load_current_baseline()
        for key, row in baseline.items():
            previews = [admin_server._build_effective_prompt_preview(key, domain, row["content"], row["version"])
                        for domain in prompt_composer.SUPPORTED_DOMAINS]
            if key == "semantic_features":
                self.assertEqual(len({p["rendered_text"] for p in previews}), 1)
                continue
            bodies = [p["rendered_text"].split("\n", 1)[1] for p in previews]
            self.assertEqual(len(set(bodies)), 7, key)
            for preview in previews:
                self.assertNotIn("{domain}", preview["rendered_text"])
                self.assertIn(api._get_quality_contract(preview["domain"]), preview["rendered_text"])
                self.assertFalse(preview["preview_complete"])
                self.assertEqual(preview["base_source"], "published_database")

    def test_aliases_are_canonicalized_and_unknown_domains_rejected(self):
        self.assertEqual(prompt_composer.canonicalize_domain("餐饮"), "美食")
        self.assertEqual(prompt_composer.canonicalize_domain("运动健身"), "健身")
        with self.assertRaises(ValueError):
            prompt_composer.canonicalize_domain("<img src=x onerror=alert(1)>")
        with mock.patch.object(api._pm, "get", return_value="V0.4基础内容"):
            for legacy_domain in ("运动", "学习", "职场", "情感", "宠物", "健康"):
                with self.subTest(legacy_domain=legacy_domain):
                    self.assertIn(
                        f"｜{legacy_domain}】",
                        api._runtime_prompt("agent_content_system", legacy_domain),
                    )

    def test_admin_preview_route_requires_admin_dependency(self):
        route = next(
            route for route in admin_server.admin_app.routes
            if getattr(route, "path", "") == "/admin/prompts/{key}/effective"
        )
        dependency_calls = [dependency.call for dependency in route.dependant.dependencies]
        self.assertIn(admin_server._aauth.get_admin_user, dependency_calls)

    def test_postgres_lock_query_uses_for_update(self):
        class FakeTransaction:
            postgres = True

            def __init__(self):
                self.sql = ""

            def fetchone(self, sql, params=()):
                self.sql = sql
                return None

        transaction = FakeTransaction()
        self.assertIsNone(prompt_manager._locked_row(transaction, "chat_system"))
        self.assertTrue(transaction.sql.endswith("FOR UPDATE"))

    def test_pg_baseline_advisory_lock_is_fixed_shared_and_ordered(self):
        class FakeTransaction:
            def __init__(self, postgres):
                self.postgres = postgres
                self.calls = []

            def execute(self, sql, params=()):
                self.calls.append((sql, params))

        postgres = FakeTransaction(True)
        prompt_manager._acquire_baseline_advisory_lock(postgres)
        self.assertEqual(
            postgres.calls,
            [(
                "SELECT pg_advisory_xact_lock(hashtext(?))",
                ("noteai_managed_prompt_baseline_v04",),
            )],
        )
        sqlite = FakeTransaction(False)
        prompt_manager._acquire_baseline_advisory_lock(sqlite)
        self.assertEqual(sqlite.calls, [])

        apply_source = inspect.getsource(prompt_manager.apply_versioned_baseline)
        rollback_source = inspect.getsource(prompt_manager.rollback_versioned_baseline)
        lock_call = "_acquire_baseline_advisory_lock(transaction)"
        self.assertLess(apply_source.index(lock_call), apply_source.index("for key in prompt_baselines.PROMPT_KEYS"))
        self.assertLess(rollback_source.index(lock_call), rollback_source.index("marker_row = transaction.fetchone"))
        self.assertEqual(apply_source.count(lock_call), 1)
        self.assertEqual(rollback_source.count(lock_call), 1)


if __name__ == "__main__":
    unittest.main()
