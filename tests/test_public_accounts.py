"""Offline checks of the public route boundary and existing OTP transactions."""
import importlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
_temp = tempfile.TemporaryDirectory()
os.environ["NOTEAI_SQLITE_PATH"] = str(Path(_temp.name) / "import.db")
db = importlib.import_module("db")
api = importlib.import_module("api")
security = importlib.import_module("account_security")
public = importlib.import_module("public_account")


class PublicAccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = db._DB_PATH
        db._DB_PATH = Path(self.temp.name) / "accounts.db"
        self.env = mock.patch.dict(os.environ, {
            "DATABASE_URL": "", "NOTEAI_DEPLOYMENT_STAGE": "test",
            "NOTEAI_PUBLIC_ACCOUNT_ONLY": "1", "NOTEAI_OTP_MODE": "test",
            "NOTEAI_OTP_TEST_CODE": "246810",
            "NOTEAI_PUBLIC_ORIGINS": "https://noteaipro.com,https://www.noteaipro.com",
        })
        self.env.start()
        db.init_db()
        self.client = TestClient(api.app, headers={"Origin": "https://noteaipro.com"})

    def tearDown(self):
        self.env.stop()
        db._DB_PATH = self.old_db
        self.temp.cleanup()

    def issue(self, purpose="register_phone", phone="13800138000"):
        result = self.client.post("/auth/verification/request", json={
            "channel": "phone", "destination": phone, "purpose": purpose,
        })
        self.assertEqual(result.status_code, 202, result.text)
        self.assertNotIn("246810", result.text)
        return result.json()["challenge_id"]

    def register(self, challenge, code="246810"):
        return self.client.post("/auth/register/otp", json={
            "phone": "13800138000", "challenge_id": challenge, "code": code,
            "contract_version": public.CONTRACT_VERSION, "privacy_accepted": True,
        })

    def test_register_login_me_logout_and_single_use(self):
        challenge = self.issue()
        result = self.register(challenge)
        self.assertEqual(result.status_code, 200, result.text)
        token = result.json()["token"]
        headers = {"Authorization": "Bearer " + token}
        me = self.client.get("/auth/me", headers=headers)
        self.assertEqual(me.status_code, 200)
        self.assertTrue(me.json()["phone_verified"])
        self.assertEqual(me.json()["contract_version"], public.CONTRACT_VERSION)
        self.assertEqual(self.register(challenge).status_code, 400)
        acceptance = db.fetchone("SELECT * FROM user_contract_acceptances LIMIT 1")
        self.assertEqual(acceptance["cross_border_notice_acknowledged_at"], "")
        self.assertEqual(self.client.post("/auth/logout", json={}, headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/auth/me", headers=headers).status_code, 401)
        challenge = self.issue("login_phone")
        login = self.client.post("/auth/login/otp", json={
            "phone": "13800138000", "challenge_id": challenge, "code": "246810",
        })
        self.assertEqual(login.status_code, 200, login.text)
        other = self.client.get("/auth/me", headers={"Authorization": "Bearer invalid"})
        self.assertEqual(other.status_code, 401)

    def test_every_unopened_route_rejected_before_handler(self):
        protected = [(method, route.path) for route in api.app.routes
                     for method in getattr(route, "methods", [])
                     if (method, route.path) not in public.ALLOWED_ROUTES]
        self.assertGreater(len(protected), 50)
        with mock.patch.object(db, "transaction", side_effect=AssertionError("unexpected DB")), \
             mock.patch.object(db, "fetchone", side_effect=AssertionError("unexpected DB")):
            for method, path in protected:
                with self.subTest(method=method, path=path):
                    response = self.client.request(method, path, content=b"{}", headers={"Content-Type": "application/json"})
                    self.assertEqual(response.status_code, 404)

    def test_origin_content_type_and_body_size_fail_closed(self):
        path = "/auth/register/otp"
        with mock.patch.object(db, "transaction", side_effect=AssertionError("unexpected DB")):
            self.assertEqual(self.client.post(path, json={}, headers={"Origin": "https://attacker.invalid"}).status_code, 403)
            self.assertEqual(self.client.post(path, content="phone=123").status_code, 415)
            self.assertEqual(self.client.post(path, content="x" * 8193, headers={"Content-Type": "application/json"}).status_code, 413)
            self.assertEqual(self.client.post("/auth/register/otp/", json={}).status_code, 404)
            self.assertEqual(self.client.post("/auth%2Fregister%2Fotp", json={}).status_code, 404)

    def test_unopened_otp_purpose_and_phone_less_registration_rejected(self):
        for channel, purpose in [("email", "verify_email"), ("phone", "password_reset"), ("phone", "bind_phone")]:
            result = self.client.post("/auth/verification/request", json={
                "channel": channel, "destination": "13800138000", "purpose": purpose,
            })
            self.assertEqual(result.status_code, 400)
        self.assertEqual(self.client.post("/auth/register", json={}).status_code, 404)
        self.assertEqual(self.client.post("/auth/register/otp", json={
            "challenge_id": "a", "code": "246810", "contract_version": public.CONTRACT_VERSION,
            "privacy_accepted": True,
        }).status_code, 422)

    def test_otp_wrong_attempts_persist_no_user_or_session_created(self):
        challenge = self.issue()
        for _ in range(5):
            self.assertEqual(self.register(challenge, "000000").status_code, 400)
        self.assertEqual(self.register(challenge).status_code, 400)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM users")["n"], 0)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM user_sessions")["n"], 0)

    def test_account_startup_skips_all_business_initialization(self):
        with mock.patch.object(api._private_storage, "configure_from_environment", side_effect=AssertionError("private storage")), \
             mock.patch.object(api, "_ensure_model_artifacts_once", side_effect=AssertionError("model")), \
             mock.patch.object(api._pm, "apply_versioned_baseline", side_effect=AssertionError("prompts")), \
             mock.patch.object(api, "stop_scheduler", side_effect=AssertionError("scheduler")):
            with TestClient(api.app) as client:
                self.assertEqual(client.get("/health/live").status_code, 200)
        with mock.patch.dict(os.environ, {"NOTEAI_DEPLOYMENT_STAGE": "production", "NOTEAI_OTP_MODE": "test"}):
            with self.assertRaises(RuntimeError):
                public.validate_startup(db)

    def test_user_agent_cannot_create_another_source_quota(self):
        from starlette.requests import Request
        first = Request({"type": "http", "headers": [(b"user-agent", b"one")], "client": ("192.0.2.1", 12)})
        second = Request({"type": "http", "headers": [(b"user-agent", b"two")], "client": ("192.0.2.1", 34)})
        self.assertEqual(api._auth_request_fingerprint(first), api._auth_request_fingerprint(second))


if __name__ == "__main__":
    unittest.main()
