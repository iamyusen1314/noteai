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
                    self.assertEqual(preview["rendered_text"], api_text)
                    self.assertEqual(preview["domain"], domain)
                    self.assertEqual(preview["preview_kind"], "effective_template")
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
