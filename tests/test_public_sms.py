"""SMS admission/recovery on disposable SQLite and opt-in isolated PG16.

Provider calls use synthetic in-memory outcomes. No production Secret is loaded.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

os.environ["PYTHON_DOTENV_DISABLED"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
db = importlib.import_module("db")
security = importlib.import_module("account_security")
sms = importlib.import_module("sms_delivery")

ENV = {"NOTEAI_OTP_MODE": "aliyun_sms", "NOTEAI_DEPLOYMENT_STAGE": "test",
       "NOTEAI_SMS_SIGN_NAME": "测试短信", "NOTEAI_SMS_TEMPLATE_CODE": "SMS_123456",
       "NOTEAI_SMS_RAM_ROLE": "isolated-test-role", "NOTEAI_SMS_PLATFORM_LIMITS": "100:1000",
       "NOTEAI_SMS_SINGLE_SEGMENT": "1"}
PNVS_ENV = {"NOTEAI_OTP_MODE": "aliyun_pnvs", "NOTEAI_SMS_SIGN_NAME": "恒创联众",
            "NOTEAI_SMS_TEMPLATE_CODE": "100001", "NOTEAI_SMS_PLATFORM_LIMITS": "pnvs_interval_60"}


class SmsAdmissionTests(unittest.TestCase):
    postgres = False

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_path = db._DB_PATH
        db._DB_PATH = Path(self.temp.name) / "sms.db"
        self.env = mock.patch.dict(os.environ, {**ENV, "DATABASE_URL": ""})
        self.env.start()
        db.init_db()
        self.owner_execute("UPDATE auth_sms_budget SET enabled=1")

    def tearDown(self):
        self.env.stop()
        db._DB_PATH = self.old_path
        self.temp.cleanup()

    def owner_execute(self, sql, params=()):
        return db.execute(sql, params)

    def issue(self, phone="13800138000", purpose="register_phone", source="192.0.2.1"):
        return security.issue_verification(channel="phone", destination=phone, purpose=purpose,
                                           requester_fingerprint=source)

    def reserve(self):
        return db.fetchone("SELECT reserved_milli_cny FROM auth_sms_budget")[0]

    def test_provider_sees_committed_reservation_not_plaintext(self):
        def send(config, **kw):
            self.assertEqual(self.reserve(), 60)
            row = db.fetchone("SELECT * FROM auth_verification_challenges WHERE id=?", (kw["challenge_id"],))
            self.assertNotEqual(row["code_hash"], kw["code"])
            self.assertNotIn(kw["code"], json.dumps(dict(row)))
            return sms.DeliveryResult("accepted", "OK", "request-one", "biz-one")
        with mock.patch.object(sms, "send", side_effect=send) as provider:
            result = self.issue()
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(result["delivery"], "sms")
        self.assertTrue(security.sms_available())

    def test_unknown_preserves_budget_and_received_code_single_use(self):
        captured = {}
        def send(config, **kw):
            captured.update(kw)
            return sms.DeliveryResult("unknown", "TRANSPORT_UNKNOWN")
        with mock.patch.object(sms, "send", side_effect=send) as provider:
            result = self.issue()
        self.assertEqual(result["delivery"], "sms_unknown")
        self.assertEqual(self.reserve(), 60)
        consume = dict(challenge_id=result["challenge_id"], code=captured["code"], channel="phone",
                       destination="13800138000", purpose="register_phone")
        self.assertEqual(security.consume_verification(**consume), "+8613800138000")
        with self.assertRaises(security.VerificationRejected):
            security.consume_verification(**consume)
        self.assertEqual(provider.call_count, 1)

    def test_rejected_delivery_cannot_be_consumed(self):
        captured = {}
        def send(config, **kw):
            captured.update(kw)
            return sms.DeliveryResult("rejected", "DENIED", "request-one")
        with mock.patch.object(sms, "send", side_effect=send):
            with self.assertRaises(security.VerificationDeliveryUnavailable): self.issue()
        with self.assertRaises(security.VerificationRejected):
            security.consume_verification(challenge_id=captured["challenge_id"], code=captured["code"],
                                          channel="phone", destination="13800138000", purpose="register_phone")
        self.assertEqual(self.reserve(), 60)

    def test_real_random_code_expires_and_wrong_attempts_persist(self):
        captured = {}
        def send(config, **kw):
            captured.update(kw)
            return sms.DeliveryResult("accepted", "OK", "r", "b")
        with mock.patch.object(sms, "send", side_effect=send): self.issue()
        consume = dict(challenge_id=captured["challenge_id"], channel="phone",
                       destination="13800138000", purpose="register_phone")
        wrong = "000000" if captured["code"] != "000000" else "111111"
        for _ in range(5):
            with self.assertRaises(security.VerificationRejected): security.consume_verification(**consume, code=wrong)
        self.assertEqual(db.fetchone("SELECT attempt_count FROM auth_verification_challenges WHERE id=?",
                                    (captured["challenge_id"],))[0], 5)
        with self.assertRaises(security.VerificationRejected):
            security.consume_verification(**consume, code=captured["code"])
        with mock.patch.object(sms, "send", side_effect=send):
            self.issue("13800138001", source="192.0.2.2")
        with mock.patch.object(security, "_now", return_value=security._now() + timedelta(minutes=11)):
            with self.assertRaises(security.VerificationRejected):
                security.consume_verification(challenge_id=captured["challenge_id"], code=captured["code"],
                    channel="phone", destination="13800138001", purpose="register_phone")

    def test_cross_purpose_contact_and_source_limits(self):
        with mock.patch.object(sms, "send", return_value=sms.DeliveryResult("accepted", "OK", "r", "b")) as provider:
            self.issue()
            for phone, purpose, source in (("+8613800138000", "login_phone", "192.0.2.2"),
                                           ("13800138001", "login_phone", "192.0.2.1")):
                with self.assertRaises(security.VerificationRejected): self.issue(phone, purpose, source)
            self.assertEqual(provider.call_count, 1)
        self.assertEqual(self.reserve(), 60)

    def test_last_reservation_is_cross_connection_atomic(self):
        self.owner_execute("UPDATE auth_sms_budget SET reserved_milli_cny=9940")
        barrier = threading.Barrier(2)
        def one(i):
            barrier.wait()
            try: return self.issue(f"1380013800{i}", source=f"192.0.2.{i}")["delivery"]
            except security.VerificationDeliveryUnavailable: return "closed"
        with mock.patch.object(sms, "send", return_value=sms.DeliveryResult("accepted", "OK", "r", "b")) as provider:
            with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(one, (1, 2)))
        self.assertEqual(sorted(results), ["closed", "sms"])
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(self.reserve(), 10000)
        self.assertFalse(security.sms_available())

    def test_commit_unknown_does_not_dispatch(self):
        original = db.transaction
        @contextmanager
        def lost_ack(*args, **kwargs):
            with original(*args, **kwargs) as tx: yield tx
            raise OSError("synthetic commit acknowledgment lost")
        with mock.patch.object(db, "transaction", lost_ack), mock.patch.object(sms, "send") as provider:
            with self.assertRaises(OSError): self.issue()
        self.assertEqual(provider.call_count, 0)
        self.assertEqual(self.reserve(), 60)
        self.assertEqual(db.fetchone("SELECT state FROM auth_sms_deliveries")[0], "reserved")

    def test_result_store_loss_does_not_resend_or_refund(self):
        original, calls = db.transaction, 0
        @contextmanager
        def fail_result(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2: raise OSError("synthetic result store disconnected")
            with original(*args, **kwargs) as tx: yield tx
        with mock.patch.object(db, "transaction", fail_result), \
             mock.patch.object(sms, "send", return_value=sms.DeliveryResult("accepted", "OK", "r", "b")) as provider:
            result = self.issue()
        self.assertEqual(result["delivery"], "sms_unknown")
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(self.reserve(), 60)

    def test_rejected_delivery_remains_rejected_when_sends_disabled(self):
        captured = {}
        def send(config, **kw):
            captured.update(kw)
            return sms.DeliveryResult("rejected", "DENIED", "request-one")
        with mock.patch.object(sms, "send", side_effect=send):
            with self.assertRaises(security.VerificationDeliveryUnavailable): self.issue()
        with mock.patch.dict(os.environ, {"NOTEAI_OTP_MODE": "disabled"}):
            with self.assertRaises(security.VerificationRejected):
                security.consume_verification(challenge_id=captured["challenge_id"], code=captured["code"],
                    channel="phone", destination="13800138000", purpose="register_phone")

    def test_known_rejection_with_store_loss_is_not_returned_as_unknown(self):
        original, calls = db.transaction, 0
        @contextmanager
        def fail_result(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2: raise OSError("synthetic store loss")
            with original(*args, **kwargs) as tx: yield tx
        with mock.patch.object(db, "transaction", fail_result), \
             mock.patch.object(sms, "send", return_value=sms.DeliveryResult("rejected", "DENIED")) as provider:
            with self.assertRaises(security.VerificationDeliveryUnavailable): self.issue()
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(self.reserve(), 60)

    def test_runtime_cannot_reset_budget(self):
        self.owner_execute("UPDATE auth_sms_budget SET reserved_milli_cny=60")
        for sql in ("UPDATE auth_sms_budget SET reserved_milli_cny=0",
                    "UPDATE auth_sms_budget SET limit_milli_cny=59940"):
            with self.assertRaises(Exception): db.execute(sql)
        self.assertEqual(self.reserve(), 60)

    def test_consumption_race_only_one_wins(self):
        captured = {}
        def send(config, **kw):
            captured.update(kw)
            return sms.DeliveryResult("accepted", "OK", "r", "b")
        with mock.patch.object(sms, "send", side_effect=send): self.issue()
        barrier = threading.Barrier(2)
        def consume(_):
            barrier.wait()
            try:
                security.consume_verification(challenge_id=captured["challenge_id"], code=captured["code"],
                    channel="phone", destination="13800138000", purpose="register_phone")
                return "consumed"
            except security.VerificationRejected: return "rejected"
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(consume, (1, 2)))
        self.assertEqual(sorted(results), ["consumed", "rejected"])


@unittest.skipUnless(os.environ.get("NOTEAI_ISOLATED_SMS_PG16") == "1", "dedicated isolated PG16 required")
class SmsPostgresTests(SmsAdmissionTests):
    postgres = True
    owner_dsn = "postgresql://postgres@noteai-public-auth-pg16-20260912/noteai_test"
    app_dsn = "postgresql://noteai_app@noteai-public-auth-pg16-20260912/noteai_test"

    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.psycopg = psycopg
        with psycopg.connect(cls.owner_dsn, autocommit=True) as conn:
            version = conn.execute("SHOW server_version_num").fetchone()[0]
            if not 160000 <= int(version) < 170000: raise AssertionError("PG16 required")
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname='noteai_app'").fetchone():
                conn.execute("CREATE ROLE noteai_app LOGIN")
        with mock.patch.dict(os.environ, {"DATABASE_URL": cls.owner_dsn}):
            db.apply_postgres_migrations()
        with psycopg.connect(cls.owner_dsn, autocommit=True) as conn:
            conn.execute("GRANT USAGE ON SCHEMA public TO noteai_app")
            conn.execute("GRANT SELECT,INSERT,UPDATE ON auth_verification_challenges,users,user_sessions,"
                         "user_contract_acceptances,auth_login_limits TO noteai_app")
            conn.execute("GRANT DELETE ON user_sessions TO noteai_app")

    def setUp(self):
        with self.psycopg.connect(self.owner_dsn, autocommit=True) as conn:
            conn.execute("TRUNCATE auth_sms_deliveries,auth_sms_budget,auth_verification_challenges")
            conn.execute("INSERT INTO auth_sms_budget(id,limit_milli_cny,enabled) "
                         "VALUES('website-accounts-20260912',10000,1)")
        self.env = mock.patch.dict(os.environ, {**ENV, "DATABASE_URL": self.app_dsn})
        self.env.start()

    def tearDown(self): self.env.stop()

    def owner_execute(self, sql, params=()):
        with self.psycopg.connect(self.owner_dsn, autocommit=True) as conn:
            return conn.execute(sql.replace("?", "%s"), params)

    def test_runtime_cannot_change_ceiling_enable_or_delete(self):
        for sql in ("UPDATE auth_sms_budget SET enabled=0", "DELETE FROM auth_sms_budget",
                    "UPDATE auth_sms_budget SET limit_milli_cny=60000"):
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege): db.execute(sql)

    def test_api_registration_login_own_account_and_logout_on_pg16(self):
        from fastapi.testclient import TestClient
        api = importlib.import_module("api")
        phone, captured = "138" + str(int.from_bytes(os.urandom(4), "big") % 100_000_000).zfill(8), {}
        def send(config, **kw):
            captured.update(kw)
            return sms.DeliveryResult("accepted", "OK", "request-one", "biz-one")
        with mock.patch.dict(os.environ, {"NOTEAI_PUBLIC_ACCOUNT_ONLY": "1", "NOTEAI_DEPLOYMENT_STAGE": "production",
                                          "NOTEAI_PUBLIC_ORIGINS": "https://noteaipro.com,https://www.noteaipro.com"}), \
             mock.patch.object(sms, "send", side_effect=send), \
             mock.patch.object(api._private_storage, "configure_from_environment", side_effect=AssertionError("business startup")):
            with TestClient(api.app, headers={"Origin": "https://noteaipro.com"}) as client:
                challenge = client.post("/auth/verification/request", json={
                    "channel": "phone", "destination": phone, "purpose": "register_phone"})
                self.assertEqual(challenge.status_code, 202, challenge.text)
                result = client.post("/auth/register/otp", json={"phone": phone,
                    "challenge_id": challenge.json()["challenge_id"], "code": captured["code"],
                    "contract_version": "account-access-2026-09-12", "privacy_accepted": True})
                self.assertEqual(result.status_code, 200, result.text)
                token = result.json()["token"]
                me = client.get("/auth/me", headers={"Authorization": "Bearer " + token})
                self.assertEqual(me.status_code, 200, me.text)
                self.assertTrue(me.json()["phone_verified"])
                self.assertEqual(client.post("/notes/track-url", json={}).status_code, 404)
                self.assertEqual(client.post("/auth/logout", json={}, headers={"Authorization": "Bearer " + token}).status_code, 200)
                self.assertEqual(client.get("/auth/me", headers={"Authorization": "Bearer " + token}).status_code, 401)
                # Advance only the isolated admission clock; no real wait/provider.
                later = security._now() + timedelta(seconds=61)
                with mock.patch.object(security, "_now", return_value=later):
                    challenge = client.post("/auth/verification/request", json={
                        "channel": "phone", "destination": phone, "purpose": "login_phone"})
                self.assertEqual(challenge.status_code, 202, challenge.text)
                result = client.post("/auth/login/otp", json={"phone": phone,
                    "challenge_id": challenge.json()["challenge_id"], "code": captured["code"]})
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(client.get("/auth/me", headers={"Authorization": "Bearer invalid"}).status_code, 401)


class PnvsAdmissionTests(SmsAdmissionTests):
    def setUp(self):
        super().setUp()
        override = mock.patch.dict(os.environ, PNVS_ENV)
        override.start()
        self.addCleanup(override.stop)

    def test_provider_identity_and_no_cross_product_configuration(self):
        with mock.patch.object(sms, "send", return_value=sms.DeliveryResult("accepted", "OK", "r", "b")):
            self.issue()
        self.assertEqual(db.fetchone("SELECT provider FROM auth_sms_deliveries")[0], "aliyun_pnvs")
        for mismatch in ({"NOTEAI_SMS_TEMPLATE_CODE": "SMS_123456"},
                         {"NOTEAI_SMS_PLATFORM_LIMITS": "100:1000"},
                         {"NOTEAI_SMS_SIGN_NAME": "NoteAI"}):
            with mock.patch.dict(os.environ, mismatch), self.assertRaises(ValueError):
                sms.configuration()

    def test_existing_sqlite_provider_constraint_fails_before_dispatch(self):
        # Existing local SQLite files are not rebuilt implicitly. A legacy CHECK
        # must fail closed; production uses the compatible PostgreSQL migration.
        sql = db.fetchone("SELECT sql FROM sqlite_master WHERE name='auth_sms_deliveries'")[0]
        self.owner_execute("DROP TABLE auth_sms_deliveries")
        self.owner_execute(sql.replace("provider IN ('aliyun_sms','aliyun_pnvs')", "provider = 'aliyun_sms'"))
        db.init_db()
        with mock.patch.object(sms, "send") as provider:
            with self.assertRaises(Exception): self.issue()
        provider.assert_not_called()
        self.assertEqual(self.reserve(), 0)


@unittest.skipUnless(os.environ.get("NOTEAI_ISOLATED_SMS_PG16") == "1", "dedicated isolated PG16 required")
class PnvsPostgresTests(SmsPostgresTests):
    def setUp(self):
        super().setUp()
        override = mock.patch.dict(os.environ, PNVS_ENV)
        override.start()
        self.addCleanup(override.stop)

    test_provider_identity_and_no_cross_product_configuration = PnvsAdmissionTests.test_provider_identity_and_no_cross_product_configuration

    def test_0023_preserves_legacy_delivery_and_cumulative_budget(self):
        with mock.patch.dict(os.environ, ENV), mock.patch.object(
                sms, "send", return_value=sms.DeliveryResult("accepted", "OK", "r", "b")):
            self.issue()
        before = dict(db.fetchone("SELECT * FROM auth_sms_deliveries"))
        sql = (Path(__file__).resolve().parents[1] / "model/migrations/postgres/0023_pnvs_sms_provider.sql").read_text()
        with self.psycopg.connect(self.owner_dsn) as conn:
            conn.execute("ALTER TABLE auth_sms_deliveries DROP CONSTRAINT auth_sms_deliveries_provider_check")
            conn.execute("ALTER TABLE auth_sms_deliveries ADD CONSTRAINT auth_sms_deliveries_provider_check CHECK(provider='aliyun_sms')")
            conn.execute(sql)
        self.assertEqual(dict(db.fetchone("SELECT * FROM auth_sms_deliveries")), before)
        self.assertEqual(self.reserve(), 60)
        self.assertTrue(security.sms_available())


if __name__ == "__main__": unittest.main()
