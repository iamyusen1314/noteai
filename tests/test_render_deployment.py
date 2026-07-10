import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODEL_DIR = Path(__file__).resolve().parents[1] / "model"
SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
import sys

sys.path.insert(0, str(MODEL_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

import admin_auth
import api
import db
import hot_keywords
import prompt_manager
import runtime_settings
import migrate_sqlite_to_postgres


class RenderDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db_path = db._DB_PATH
        db._DB_PATH = Path(self.temp.name) / "noteai.db"
        db.init_db()

    def tearDown(self):
        db._DB_PATH = self.original_db_path
        prompt_manager._cache.clear()
        prompt_manager._cache_ts = 0
        self.temp.cleanup()

    def test_shared_settings_and_admin_session_survive_memory_reset(self):
        runtime_settings.set_json("crawler_config", {"enabled": True})
        self.assertEqual(runtime_settings.get_json("crawler_config"), {"enabled": True})

        with mock.patch.dict(os.environ, {"ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": "test-password"}):
            token = admin_auth.admin_login("admin", "test-password")
            self.assertEqual(admin_auth._verify_admin_token(token)["username"], "admin")
            admin_auth.admin_logout(token)
            self.assertIsNone(admin_auth._verify_admin_token(token))

    def test_prompt_defaults_are_seeded_to_database_without_overwrite(self):
        defaults = {
            "deployment_test": {
                "label": "Deployment",
                "module": "test",
                "content": "first",
            }
        }
        prompt_manager.init_default_prompts(defaults)
        self.assertEqual(prompt_manager.get("deployment_test"), "first")
        db.execute(
            "UPDATE managed_prompts SET content=? WHERE key=?",
            ("edited", "deployment_test"),
        )
        prompt_manager.reload()
        prompt_manager.init_default_prompts(defaults)
        self.assertEqual(prompt_manager.get("deployment_test"), "edited")

    def test_video_frame_cache_can_reload_after_memory_clear(self):
        original_dir = api._VIDEO_CACHE_DIR
        original_cache = dict(api._video_frames)
        try:
            api._VIDEO_CACHE_DIR = Path(self.temp.name) / "video-cache"
            file_id = "0123456789abcdef0123"
            api._store_video_meta(
                file_id,
                {"frames": [b"frame-one", b"frame-two"], "duration_sec": 2.0, "raw_fps": 1.0},
            )
            api._video_frames.clear()
            restored = api._get_video_meta(file_id)
            self.assertEqual(restored["frames"], [b"frame-one", b"frame-two"])
            self.assertEqual(restored["duration_sec"], 2.0)
        finally:
            api._VIDEO_CACHE_DIR = original_dir
            api._video_frames.clear()
            api._video_frames.update(original_cache)

    def test_postgres_hot_keyword_sql_uses_compatible_placeholders_and_functions(self):
        sql = "VALUES (?, ?) ON CONFLICT DO UPDATE SET search_vol=MAX(search_vol, excluded.search_vol)"
        converted = hot_keywords._PostgresCompatConnection._sql(sql)
        self.assertIn("VALUES (%s, %s)", converted)
        self.assertIn("GREATEST(hot_keywords.search_vol, excluded.search_vol)", converted)

    def test_render_blueprint_declares_all_required_service_types(self):
        blueprint = (Path(__file__).resolve().parents[1] / "render.yaml").read_text(encoding="utf-8")
        for name in (
            "noteai-staging-web",
            "noteai-staging-api",
            "noteai-staging-admin",
            "noteai-staging-market-timing",
            "noteai-staging-tracking",
            "noteai-staging-db",
        ):
            self.assertIn(name, blueprint)
        self.assertIn("healthCheckPath: /health/ready", blueprint)
        self.assertIn("property: connectionString", blueprint)
        secret_name = "ANTHROPIC_API" + "_KEY"
        self.assertNotIn(f"{secret_name}: ", blueprint)

    def test_sqlite_migration_defaults_to_count_only_and_excludes_sessions(self):
        counts = migrate_sqlite_to_postgres.source_counts(db._DB_PATH)
        self.assertIn("users", counts)
        self.assertNotIn("user_sessions", counts)
        counts_with_sessions = migrate_sqlite_to_postgres.source_counts(
            db._DB_PATH, include_user_sessions=True
        )
        self.assertIn("user_sessions", counts_with_sessions)


if __name__ == "__main__":
    unittest.main()
