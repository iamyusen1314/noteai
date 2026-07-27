import asyncio
import hashlib
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import BackgroundTasks, HTTPException


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

db = importlib.import_module("db")
admin_auth = importlib.import_module("admin_auth")
admin_server = importlib.import_module("admin_server")


class FirstLaunchUiAdminContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._old_db_path = db._DB_PATH
        self._tmpdir = tempfile.TemporaryDirectory()
        db._DB_PATH = Path(self._tmpdir.name) / "noteai.db"
        db.init_db()

    def tearDown(self):
        db._DB_PATH = self._old_db_path
        self._tmpdir.cleanup()

    def test_admin_bearer_is_hashed_at_rest_and_logout_uses_digest(self):
        with mock.patch.dict(
            os.environ,
            {"ADMIN_USERNAME": "contract-admin", "ADMIN_PASSWORD": "synthetic-pass"},
            clear=False,
        ):
            token = admin_auth.admin_login("contract-admin", "synthetic-pass")

        stored = db.fetchone(
            "SELECT token,username FROM admin_sessions WHERE username=?",
            ("contract-admin",),
        )
        self.assertTrue(token.startswith("admin_"))
        self.assertNotEqual(stored["token"], token)
        self.assertEqual(
            stored["token"],
            hashlib.sha256(token.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(
            admin_auth._verify_admin_token(token)["username"],
            "contract-admin",
        )
        admin_auth.admin_logout(token)
        self.assertIsNone(admin_auth._verify_admin_token(token))

    def test_production_capabilities_and_cors_fail_closed(self):
        with mock.patch.dict(
            os.environ,
            {
                "NOTEAI_DEPLOYMENT_STAGE": "production",
                "NOTEAI_CLOUD_RUNTIME": "1",
                "NOTEAI_ADMIN_CORS_ORIGINS": "*,https://admin.noteai.example",
            },
            clear=False,
        ):
            payload = admin_server._admin_capabilities_payload()
            origins = admin_server._admin_cors_origins()

        self.assertEqual(payload["mode"], "production_read_only")
        self.assertTrue(payload["read_only"])
        self.assertTrue(
            all(value is False for value in payload["capabilities"].values())
        )
        self.assertEqual(origins, ["https://admin.noteai.example"])

    def test_local_capabilities_preserve_operator_workflow(self):
        with mock.patch.dict(
            os.environ,
            {
                "NOTEAI_DEPLOYMENT_STAGE": "test",
                "NOTEAI_CLOUD_RUNTIME": "0",
                "NOTEAI_ADMIN_CORS_ORIGINS": "",
                "CORS_ORIGINS": "",
            },
            clear=False,
        ):
            payload = admin_server._admin_capabilities_payload()
            origins = admin_server._admin_cors_origins()

        self.assertEqual(payload["mode"], "local_operator")
        self.assertFalse(payload["read_only"])
        self.assertTrue(all(payload["capabilities"].values()))
        self.assertEqual(origins, ["*"])

    async def test_production_mutations_stop_before_database_or_process_work(self):
        calls = (
            lambda: admin_server.admin_user_adjust(
                "u-1",
                admin_server.UserAdjustInput(
                    action="add_credits",
                    value="1",
                ),
                {"username": "admin"},
            ),
            lambda: admin_server.admin_trigger_check(
                "track-1",
                {"username": "admin"},
            ),
            lambda: admin_server.admin_prompt_update(
                "diagnose",
                admin_server.PromptUpdateInput(content="synthetic"),
                {"username": "admin"},
            ),
            lambda: admin_server.admin_prompt_rollback(
                "diagnose",
                {"version": 1},
                {"username": "admin"},
            ),
            lambda: admin_server.admin_model_deploy(
                "v0.4-composite",
                {"username": "admin"},
            ),
            lambda: admin_server.admin_model_train(
                admin_server.TrainJobInput(description="synthetic"),
                BackgroundTasks(),
                {"username": "admin"},
            ),
            lambda: admin_server.admin_crawler_toggle(
                {"enabled": True},
                {"username": "admin"},
            ),
        )
        restricted = {
            "NOTEAI_DEPLOYMENT_STAGE": "production",
            "NOTEAI_CLOUD_RUNTIME": "1",
        }
        with mock.patch.dict(os.environ, restricted, clear=False), mock.patch.object(
            admin_server.db,
            "fetchone",
            side_effect=AssertionError("database must not be touched"),
        ), mock.patch.object(
            admin_server.db,
            "execute",
            side_effect=AssertionError("database must not be touched"),
        ), mock.patch.object(
            asyncio,
            "create_subprocess_exec",
            side_effect=AssertionError("process must not start"),
        ):
            for invoke in calls:
                with self.subTest(invoke=invoke):
                    with self.assertRaises(HTTPException) as caught:
                        await invoke()
                    self.assertEqual(caught.exception.status_code, 409)

    def test_production_read_paths_do_not_lazy_initialize_settings(self):
        restricted = {
            "NOTEAI_DEPLOYMENT_STAGE": "production",
            "NOTEAI_CLOUD_RUNTIME": "1",
        }
        with mock.patch.dict(os.environ, restricted, clear=False), mock.patch.object(
            admin_server._settings,
            "set_json",
            side_effect=AssertionError("read path must not persist defaults"),
        ):
            registry = admin_server._load_registry()
            crawler = admin_server._load_crawler_config()

        self.assertIn("models", registry)
        self.assertIn("enabled", crawler)

    async def test_production_crawler_status_never_reads_cookie_setting(self):
        def get_json(key, default=None):
            if key == admin_server._XHS_COOKIES_KEY:
                raise AssertionError("production Admin must not read Cookie material")
            return default

        restricted = {
            "NOTEAI_DEPLOYMENT_STAGE": "production",
            "NOTEAI_CLOUD_RUNTIME": "1",
        }
        with mock.patch.dict(os.environ, restricted, clear=False), mock.patch.object(
            admin_server._settings,
            "get_json",
            side_effect=get_json,
        ), mock.patch.object(
            admin_server,
            "_XHS_ACQ_AVAILABLE",
            False,
        ), mock.patch.object(
            admin_server.db,
            "fetchone",
            return_value={"cnt": 0},
        ):
            result = await admin_server.admin_crawler_status(
                admin={"username": "admin"},
            )

        self.assertFalse(result["cookie_file_exists"])
        self.assertEqual(result["cookie_count"], 0)

    async def test_admin_user_payload_is_masked_and_omits_payment_reference(self):
        db.execute(
            "INSERT INTO users("
            "id,username,email,phone,password_hash,password_salt,created_at"
            ") VALUES(?,?,?,?,?,?,?)",
            (
                "u-private",
                "operator-visible",
                "private.person@example.com",
                "13812345678",
                "hash",
                "salt",
                "2026-07-26T00:00:00+00:00",
            ),
        )
        db.execute(
            "INSERT INTO credit_transactions("
            "user_id,type,amount,balance_after,description,paid_rmb,"
            "package_id,payment_ref,recorded_at"
            ") VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "u-private",
                "topup",
                30,
                30,
                "合成测试",
                12,
                "starter",
                "provider-secret-ref",
                "2026-07-26T00:00:00+00:00",
            ),
        )

        listing = await admin_server.admin_users(
            admin={"username": "admin"},
        )
        detail = await admin_server.admin_user_detail(
            "u-private",
            admin={"username": "admin"},
        )
        serialized = json.dumps(
            {"listing": listing, "detail": detail},
            ensure_ascii=False,
        )

        self.assertNotIn("private.person@example.com", serialized)
        self.assertNotIn("13812345678", serialized)
        self.assertNotIn("provider-secret-ref", serialized)
        self.assertEqual(listing["users"][0]["phone_masked"], "138****5678")
        self.assertEqual(
            listing["users"][0]["email_masked"],
            "p***@example.com",
        )
        self.assertNotIn("phone", listing["users"][0])
        self.assertNotIn("email", listing["users"][0])
        self.assertNotIn("payment_ref", detail["credit_txns"][0])

    def test_all_non_login_admin_routes_require_admin_authentication(self):
        public_admin_paths = {"/admin/login", "/admin/health"}
        for route in admin_server.admin_app.routes:
            if not getattr(route, "path", "").startswith("/admin/"):
                continue
            if route.path in public_admin_paths:
                continue
            dependency_calls = {
                dependency.call
                for dependency in route.dependant.dependencies
            }
            self.assertIn(
                admin_auth.get_admin_user,
                dependency_calls,
                route.path,
            )

    def test_visible_contract_copy_and_share_card_are_truthful(self):
        frontend = (ROOT / "NoteAI_Pro_Demo_Framer.html").read_text(
            encoding="utf-8",
        )
        admin = (MODEL_DIR / "admin.html").read_text(encoding="utf-8")
        billing = (MODEL_DIR / "billing.py").read_text(encoding="utf-8")

        self.assertIn("function shareDiagnosisCard(button)", frontend)
        self.assertIn("canvas.toBlob", frontend)
        self.assertIn("navigator.share", frontend)
        self.assertIn("link.download = 'noteai-diagnosis-card.png'", frontend)
        self.assertNotIn("诊断卡片已生成，复制链接成功", frontend)
        self.assertIn("最多3/4调度槽位给优先队列（非完成时效承诺）", frontend)
        self.assertIn("付费创建归档在账户存在期间无产品到期日", frontend)
        self.assertIn("单主账号多小红书账号高频运营", billing)
        self.assertNotIn("付费期间创建内容永久存档", billing)
        self.assertNotIn("3:1 加权任务调度", billing)
        self.assertIn("sessionStorage.getItem('noteai_admin_token')", admin)
        self.assertIn("生产只读控制台", admin)
        self.assertIn("data-capability=\"business_mutation\"", admin)
        self.assertIn("套餐周期积分", admin)
        self.assertNotIn("重置本月积分", admin)
        self.assertIn("/assets/vendor/echarts-5.4.3.min.js", frontend)
        self.assertIn("/assets/vendor/lucide-1.27.0.min.js", frontend)
        self.assertIn("/assets/vendor/echarts-5.4.3.min.js", admin)
        self.assertNotIn("cdnjs.cloudflare.com", frontend + admin)
        self.assertNotIn("unpkg.com", frontend + admin)

    def test_admin_postgres_role_contract_is_credential_free_and_exact(self):
        migration_0015 = (
            MODEL_DIR
            / "migrations"
            / "postgres"
            / "0015_admin_runtime_contract.sql"
        ).read_text(encoding="utf-8")
        migration_0016 = (
            MODEL_DIR
            / "migrations"
            / "postgres"
            / "0016_admin_runtime_role_collision.sql"
        ).read_text(encoding="utf-8")
        role_sql = (
            ROOT / "scripts" / "postgres" / "noteai_admin_runtime_role.sql"
        ).read_text(encoding="utf-8")
        server = (MODEL_DIR / "admin_server.py").read_text(encoding="utf-8")

        self.assertNotIn("GRANT ", migration_0015.upper())
        self.assertNotIn("REVOKE ", migration_0015.upper())
        self.assertNotIn("GRANT ", migration_0016.upper())
        self.assertNotIn("REVOKE ", migration_0016.upper())
        self.assertIn("noteai_system_settings_admin_read_v1", migration_0016)
        self.assertIn(
            "key IN ('model_registry','crawler_config')",
            migration_0016,
        )
        self.assertIn("noteai_ai_outbox_admin_read_v1", migration_0016)
        self.assertNotIn("CREATE ROLE", role_sql.upper())
        self.assertNotIn("PASSWORD", role_sql.upper())
        self.assertIn(
            "GRANT SELECT, INSERT, DELETE ON admin_sessions "
            "TO noteai_admin_runtime",
            role_sql,
        )
        self.assertIn(
            "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public",
            role_sql,
        )
        self.assertIn(
            "SELECT id,username,email,phone,nickname,avatar_emoji,created_at,last_login",
            server,
        )
        self.assertIn(
            "if _is_restricted_admin_runtime()",
            server,
        )


if __name__ == "__main__":
    unittest.main()
