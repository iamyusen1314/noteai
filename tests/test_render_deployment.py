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

    def test_init_db_never_runs_postgres_migrations(self):
        with (
            mock.patch.object(db, "using_postgres", return_value=True),
            mock.patch.object(db, "apply_postgres_migrations") as apply_migrations,
            mock.patch.object(db, "_init_sqlite") as init_sqlite,
        ):
            db.init_db()

        apply_migrations.assert_not_called()
        init_sqlite.assert_not_called()

    def test_service_start_commands_never_run_predeploy(self):
        for name in (
            "render_start_api.sh",
            "render_start_admin.sh",
            "render_run_market_timing.sh",
            "render_run_crawler.sh",
        ):
            with self.subTest(name=name):
                source = (SCRIPTS_DIR / name).read_text(encoding="utf-8")
                self.assertNotIn("render_predeploy.py", source)
                self.assertNotIn("NOTEAI_MIGRATE_ON_START", source)

    def test_postgres_migration_lock_precedes_version_read(self):
        source = (MODEL_DIR / "db.py").read_text(encoding="utf-8")
        migration = source.split("def apply_postgres_migrations()", 1)[1].split("def init_db()", 1)[0]

        self.assertLess(
            migration.index("pg_advisory_xact_lock"),
            migration.index("SELECT version, sha256 FROM schema_migrations"),
        )

    def test_render_blueprint_declares_all_required_service_types(self):
        import yaml

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
        self.assertEqual(
            blueprint.count("preDeployCommand: python /app/scripts/render_predeploy.py"),
            1,
        )
        self.assertNotIn("NOTEAI_MIGRATE_ON_START", blueprint)
        self.assertIn("property: connectionString", blueprint)
        secret_name = "ANTHROPIC_API" + "_KEY"
        self.assertNotIn(f"{secret_name}: ", blueprint)
        self.assertNotIn("NOTEAI_XHS_TOKEN_DISCOVERY", blueprint)
        self.assertNotIn("NOTEAI_XHS_LOW_MEMORY_BROWSER", blueprint)
        self.assertNotIn("NOTEAI_XHS_BROWSER_TARGETS_PER_SESSION", blueprint)
        self.assertNotIn("NOTEAI_XHS_STOP_ON_CHALLENGE", blueprint)
        self.assertIn('NOTEAI_XHS_CHALLENGE_COOLDOWN_MINUTES', blueprint)
        self.assertIn('value: "360"', blueprint)
        market_timing_block = blueprint.split(
            "name: noteai-staging-market-timing", 1
        )[1].split("name: noteai-staging-tracking", 1)[0]
        self.assertIn("NOTEAI_XHS_COLLECTION_SUSPENDED", market_timing_block)
        self.assertIn('value: "1"', market_timing_block)
        self.assertEqual(blueprint.count("NOTEAI_XHS_COLLECTION_SUSPENDED"), 2)
        self.assertEqual(blueprint.count("value: spider_xhs_http"), 2)
        self.assertGreaterEqual(blueprint.count("NOTEAI_XHS_FRESHNESS_REQUIRED"), 2)
        self.assertNotIn("MALLOC_ARENA_MAX", blueprint)

        services = {
            service["name"]: service
            for service in yaml.safe_load(blueprint)["services"]
        }

        def env(service_name):
            return {
                item["key"]: item.get("value")
                for item in services[service_name].get("envVars", [])
            }

        self.assertEqual(env("noteai-staging-api")["NOTEAI_RUNTIME_TARGET"], "api-runtime")
        self.assertEqual(env("noteai-staging-api")["NOTEAI_RUNTIME_ROLE"], "api")
        self.assertEqual(env("noteai-staging-admin")["NOTEAI_RUNTIME_TARGET"], "admin-runtime")
        self.assertEqual(env("noteai-staging-admin")["NOTEAI_RUNTIME_ROLE"], "admin")
        for service_name in ("noteai-staging-market-timing", "noteai-staging-tracking"):
            with self.subTest(service_name=service_name):
                self.assertEqual(env(service_name)["NOTEAI_RUNTIME_TARGET"], "xhs-http-runtime")
                self.assertEqual(env(service_name)["NOTEAI_RUNTIME_ROLE"], "xhs-http")
                self.assertEqual(env(service_name)["NOTEAI_XHS_ACQUISITION_ADAPTER"], "spider_xhs_http")
                self.assertEqual(env(service_name)["NOTEAI_XHS_COLLECTION_SUSPENDED"], "1")

    def test_admin_does_not_use_public_readiness_as_provider_status_source(self):
        blueprint = (Path(__file__).resolve().parents[1] / "render.yaml").read_text(encoding="utf-8")
        admin_block = blueprint.split("name: noteai-staging-admin", 1)[1].split("- type: cron", 1)[0]
        self.assertNotIn("NOTEAI_API_READINESS_URL", admin_block)
        self.assertNotIn("ANTHROPIC_API_KEY", admin_block)
        self.assertNotIn("MOONSHOT_API_KEY", admin_block)

    def test_admin_system_ui_uses_explicit_status_contract_without_undefined_fields(self):
        admin_html = (MODEL_DIR / "admin.html").read_text(encoding="utf-8")
        self.assertIn("ai_runtime", admin_html)
        self.assertIn("database_backend", admin_html)
        self.assertIn("database_ok", admin_html)
        self.assertNotIn("s.kimi_key_prefix", admin_html)
        self.assertNotIn("s.db_size_mb", admin_html)

    def test_prompt_migration_entrypoint_is_packaged_and_predeploy_audits_first(self):
        dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8")
        self.assertGreaterEqual(dockerfile.count("migrate_managed_prompts_v04.py"), 2)
        predeploy = (SCRIPTS_DIR / "render_predeploy.py").read_text(encoding="utf-8")
        audit_at = predeploy.index("prompt_manager.audit_versioned_baseline()")
        apply_at = predeploy.index("prompt_manager.apply_versioned_baseline()")
        self.assertLess(audit_at, apply_at)
        self.assertIn("prompt_baseline_audit=ok", predeploy)
        self.assertNotIn("prompt_result['content']", predeploy)
        self.assertNotIn("prompt_result['sha256']", predeploy)

    def test_admin_crawler_exposes_runtime_cookie_health(self):
        admin_html = (MODEL_DIR / "admin.html").read_text(encoding="utf-8")
        self.assertIn("cookie_runtime_status", admin_html)
        self.assertIn("cw-cookie-sub", admin_html)
        self.assertIn("登录已失效", admin_html)

    def test_admin_distinguishes_cumulative_freshness_from_latest_source_health(self):
        admin_html = (MODEL_DIR / "admin.html").read_text(encoding="utf-8")
        self.assertIn("当日累计新鲜证据", admin_html)
        self.assertIn("最新一轮来源退化", admin_html)
        self.assertIn("latest_run_source_health", admin_html)
        self.assertIn("搜索访问挑战冷却中", admin_html)
        self.assertIn("access_status", admin_html)
        self.assertIn("['insufficient','degraded']", admin_html)
        self.assertIn("本轮新增 / 今日累计", admin_html)
        self.assertIn("row.details?.latest_run_evidence_count", admin_html)
        self.assertIn("row.evidence_count", admin_html)
        self.assertIn("账号已被平台退出", admin_html)
        self.assertIn("采集已合规暂停", admin_html)

    def test_hot_keywords_does_not_eagerly_import_jieba(self):
        source = (MODEL_DIR / "hot_keywords.py").read_text(encoding="utf-8")
        module_prefix = source.split("def match_keywords", 1)[0]
        self.assertNotIn("import jieba", module_prefix)

    def test_market_timing_scroll_does_not_depend_on_page_execution_context(self):
        source = (MODEL_DIR / "scheduler_a.py").read_text(encoding="utf-8")
        self.assertIn("page.mouse.wheel(0, 700)", source)
        self.assertNotIn('page.evaluate("window.scrollBy(0, 700)")', source)

    def test_market_timing_explicitly_triggers_and_parses_search_discovery(self):
        source = (MODEL_DIR / "scheduler_a.py").read_text(encoding="utf-8")
        self.assertIn('input[placeholder="搜索小红书"]', source)
        self.assertIn("async def _trigger_search_input", source)
        self.assertIn('"search/trending/query"', source)
        self.assertIn('payload.get("queries")', source)
        self.assertIn('payload.get("ai_words")', source)

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
