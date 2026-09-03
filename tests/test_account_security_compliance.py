import asyncio
import importlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from fastapi import HTTPException
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

_MODULE_DB_TEMP = tempfile.TemporaryDirectory()
_MODULE_DB_PATH = str(Path(_MODULE_DB_TEMP.name) / "import-safe.db")
_ORIGINAL_SQLITE_PATH = os.environ.get("NOTEAI_SQLITE_PATH")
os.environ["NOTEAI_SQLITE_PATH"] = _MODULE_DB_PATH
db = importlib.import_module("db")
if _ORIGINAL_SQLITE_PATH is None:
    os.environ.pop("NOTEAI_SQLITE_PATH", None)
else:
    os.environ["NOTEAI_SQLITE_PATH"] = _ORIGINAL_SQLITE_PATH
db._DB_PATH = Path(_MODULE_DB_PATH)
account_security = importlib.import_module("account_security")
ai_operations = importlib.import_module("ai_operations")
artifact_loader = importlib.import_module("artifact_loader")
auth = importlib.import_module("auth")
billing = importlib.import_module("billing")
content_retention = importlib.import_module("content_retention")
memory = importlib.import_module("memory")
runtime_settings = importlib.import_module("runtime_settings")
security_redaction = importlib.import_module("security_redaction")
api = importlib.import_module("api")
admin_server = importlib.import_module("admin_server")


class AccountSecurityComplianceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db_path = db._DB_PATH
        db._DB_PATH = Path(self.temp.name) / "security-compliance.db"
        db.init_db()
        self.env = mock.patch.dict(
            os.environ,
            {
                "NOTEAI_OTP_MODE": "test",
                "NOTEAI_OTP_TEST_CODE": "246810",
                "NOTEAI_DEPLOYMENT_STAGE": "test",
            },
            clear=False,
        )
        self.env.start()
        self.client = TestClient(api.app)

    def tearDown(self):
        self.env.stop()
        db._DB_PATH = self.old_db_path
        self.temp.cleanup()

    def _create_user(self, username="safeuser", password="Strong!Pass234"):
        return auth.create_user(username, password)

    def _login(self, username="safeuser", password="Strong!Pass234"):
        return auth.login_user(username, password, requester_fingerprint="test-client")

    @staticmethod
    def _consent() -> dict:
        return {
            "contract_version": content_retention.CONTRACT_VERSION,
            "privacy_accepted": True,
            "cross_border_notice_acknowledged": True,
        }

    def test_password_policy_rejects_weak_common_and_identity_values(self):
        for value in ("short1!", "1234567890", "onlyletters", "safeuser123"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                account_security.validate_password(
                    value,
                    identity_values=("safeuser",),
                )
        self.assertEqual(
            account_security.validate_password("Long&Distinct2026"),
            "Long&Distinct2026",
        )

    def test_password_policy_rejects_formatted_phone_equivalents(self):
        for value in (
            "AA!138-0013-8000",
            "AA!138 0013 8000",
            "AA!+86-138-0013-8000",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                account_security.validate_password(
                    value,
                    identity_values=("+8613800138000",),
                )

    def test_phone_normalization_rejects_unicode_digits_before_storage(self):
        for value in (
            "13١٢٣٤٥٦٧٨٩",
            "13１２３４５６７８９",
            "13१२३४५६७८९",
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "手机号格式错误"):
                    account_security.normalize_phone(value)
                with (
                    mock.patch.object(db, "transaction") as transaction,
                    self.assertRaisesRegex(ValueError, "手机号格式错误"),
                ):
                    account_security.issue_verification(
                        channel="phone",
                        destination=value,
                        purpose="register_phone",
                        requester_fingerprint="unicode-phone-probe",
                    )
                transaction.assert_not_called()

    def test_phone_registration_requires_consumed_verification(self):
        response = self.client.post(
            "/auth/verification/request",
            json={
                "channel": "phone",
                "destination": "13800138000",
                "purpose": "register_phone",
            },
        )
        self.assertEqual(response.status_code, 202)
        issued = response.json()
        self.assertNotIn("code", issued)
        self.assertEqual(issued["destination_masked"], "138****8000")

        rejected = self.client.post(
            "/auth/register",
            json={
                "username": "unverified",
                "password": "Strong!Pass234",
                "phone": "13900139000",
                **self._consent(),
            },
        )
        self.assertEqual(rejected.status_code, 400)

        accepted = self.client.post(
            "/auth/register",
            json={
                "username": "verifieduser",
                "password": "Strong!Pass234",
                "phone": "13800138000",
                "phone_challenge_id": issued["challenge_id"],
                "phone_code": "246810",
                **self._consent(),
            },
        )
        self.assertEqual(accepted.status_code, 200)
        row = db.fetchone(
            "SELECT phone,phone_verified_at FROM users WHERE username=?",
            ("verifieduser",),
        )
        self.assertEqual(row["phone"], "+8613800138000")
        self.assertTrue(row["phone_verified_at"])

    def test_registration_email_is_stored_only_after_verification(self):
        rejected = self.client.post(
            "/auth/register",
            json={
                "username": "emailreject",
                "password": "Strong!Pass234",
                "email": "owner@example.com",
                **self._consent(),
            },
        )
        self.assertEqual(rejected.status_code, 400)
        issued = self.client.post(
            "/auth/verification/request",
            json={
                "channel": "email",
                "destination": "owner@example.com",
                "purpose": "verify_email",
            },
        )
        self.assertEqual(issued.status_code, 202)
        accepted = self.client.post(
            "/auth/register",
            json={
                "username": "emailverified",
                "password": "Strong!Pass234",
                "email": "owner@example.com",
                "email_challenge_id": issued.json()["challenge_id"],
                "email_code": "246810",
                **self._consent(),
            },
        )
        self.assertEqual(accepted.status_code, 200)
        row = db.fetchone(
            "SELECT email,email_verified_at FROM users WHERE username=?",
            ("emailverified",),
        )
        self.assertEqual(row["email"], "owner@example.com")
        self.assertTrue(row["email_verified_at"])

    def test_test_otp_adapter_refuses_production_stage(self):
        with mock.patch.dict(
            os.environ,
            {"NOTEAI_OTP_MODE": "test", "NOTEAI_DEPLOYMENT_STAGE": "production"},
            clear=False,
        ):
            with self.assertRaises(account_security.VerificationDeliveryUnavailable):
                account_security.issue_verification(
                    channel="phone",
                    destination="13800138000",
                    purpose="register_phone",
                )
        count = db.fetchone(
            "SELECT COUNT(*) AS c FROM auth_verification_challenges"
        )["c"]
        self.assertEqual(count, 0)

    def test_test_otp_adapter_requires_explicit_non_production_stage(self):
        with mock.patch.dict(
            os.environ,
            {"NOTEAI_OTP_MODE": "test"},
            clear=True,
        ):
            with self.assertRaises(account_security.VerificationDeliveryUnavailable):
                account_security.issue_verification(
                    channel="phone",
                    destination="13800138000",
                    purpose="register_phone",
                )

    def test_otp_is_single_use_and_attempts_are_bounded(self):
        issued = account_security.issue_verification(
            channel="phone",
            destination="13800138000",
            purpose="register_phone",
        )
        for _ in range(account_security.OTP_MAX_ATTEMPTS):
            with self.assertRaises(account_security.VerificationRejected):
                account_security.consume_verification(
                    challenge_id=issued["challenge_id"],
                    code="000000",
                    channel="phone",
                    destination="13800138000",
                    purpose="register_phone",
                )
        with self.assertRaises(account_security.VerificationRejected):
            account_security.consume_verification(
                challenge_id=issued["challenge_id"],
                code="246810",
                channel="phone",
                destination="13800138000",
                purpose="register_phone",
            )

        single_use = account_security.issue_verification(
            channel="phone",
            destination="13900139000",
            purpose="register_phone",
        )
        self.assertEqual(
            account_security.consume_verification(
                challenge_id=single_use["challenge_id"],
                code="246810",
                channel="phone",
                destination="13900139000",
                purpose="register_phone",
            ),
            "+8613900139000",
        )
        with self.assertRaises(account_security.VerificationRejected):
            account_security.consume_verification(
                challenge_id=single_use["challenge_id"],
                code="246810",
                channel="phone",
                destination="13900139000",
                purpose="register_phone",
            )

    def test_login_lockout_is_hashed_and_account_scoped(self):
        self._create_user()
        for _ in range(account_security.LOGIN_MAX_FAILURES):
            with self.assertRaises(ValueError):
                auth.login_user(
                    "safeuser",
                    "wrong-password",
                    requester_fingerprint="origin-a",
                )
        with self.assertRaises(account_security.LoginTemporarilyBlocked):
            auth.login_user(
                "safeuser",
                "Strong!Pass234",
                requester_fingerprint="origin-a",
            )
        with self.assertRaises(account_security.LoginTemporarilyBlocked):
            auth.login_user(
                "safeuser",
                "Strong!Pass234",
                requester_fingerprint="origin-b",
            )
        row = db.fetchone("SELECT * FROM auth_login_limits LIMIT 1")
        self.assertNotIn("safeuser", json.dumps(dict(row)))

    def test_login_rate_keys_canonicalize_equivalent_phone_forms(self):
        plain = account_security._login_keys("13800138000", "same-origin")
        prefixed = account_security._login_keys("+86 138-0013-8000", "same-origin")
        self.assertEqual(plain, prefixed)

    def test_password_reset_and_change_revoke_all_sessions(self):
        user = self._create_user()
        token_one = self._login()["token"]
        token_two = self._login()["token"]
        challenge = account_security.issue_verification(
            channel="phone",
            destination="13800138000",
            purpose="bind_phone",
            requested_by_user_id=user["id"],
        )
        account_security.consume_verification(
            challenge_id=challenge["challenge_id"],
            code="246810",
            channel="phone",
            destination="13800138000",
            purpose="bind_phone",
            requested_by_user_id=user["id"],
        )
        auth.set_verified_phone(user["id"], "13800138000")
        reset = account_security.issue_verification(
            channel="phone",
            destination="13800138000",
            purpose="password_reset",
        )
        response = self.client.post(
            "/auth/password-reset",
            json={
                "channel": "phone",
                "destination": "13800138000",
                "challenge_id": reset["challenge_id"],
                "code": "246810",
                "new_password": "Changed!Pass2026",
            },
        )
        self.assertEqual(response.status_code, 200)
        for token in (token_one, token_two):
            self.assertEqual(
                self.client.get(
                    "/auth/me",
                    headers={"Authorization": f"Bearer {token}"},
                ).status_code,
                401,
            )

    def test_secret_settings_fail_closed_and_env_injection_works(self):
        db.execute(
            "INSERT INTO system_settings(key,value_json,is_secret,updated_at) "
            "VALUES(?,?,?,?)",
            ("historical_secret", json.dumps({"token": "must-not-read"}), 1, "now"),
        )
        self.assertEqual(runtime_settings.get_json("historical_secret", {}), {})
        with self.assertRaises(runtime_settings.SecretStorageUnavailable):
            runtime_settings.set_json(
                "xhs_cookies",
                [{"name": "session", "value": "secret"}],
                is_secret=True,
            )
        db.execute(
            "INSERT INTO system_settings(key,value_json,is_secret,updated_at) "
            "VALUES(?,?,?,?)",
            ("xhs_cookies", json.dumps([{"value": "forged"}]), 0, "now"),
        )
        self.assertEqual(runtime_settings.get_json("xhs_cookies", []), [])
        with self.assertRaises(runtime_settings.SecretStorageUnavailable):
            runtime_settings.set_json("xhs_cookies", [{"value": "forged"}])
        with mock.patch.dict(
            os.environ,
            {"NOTEAI_XHS_COOKIES_JSON": '[{"name":"safe-count-only"}]'},
            clear=False,
        ):
            self.assertEqual(
                runtime_settings.get_json("xhs_cookies", []),
                [{"name": "safe-count-only"}],
            )

    def test_free_archive_recovery_delete_and_paid_creation_contract(self):
        user = self._create_user()
        created = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        db.execute(
            "INSERT INTO notes(id,user_id,title,body,created_at) VALUES(?,?,?,?,?)",
            ("free-note", user["id"], "title", "body", created),
        )
        free = content_retention.record_content(
            "note", "free-note", user["id"], created_at=created
        )
        self.assertEqual(free["state"], "recovery")
        self.assertEqual(content_retention.recover(
            "note", "free-note", user["id"]
        )["state"], "active")
        content_retention.mark_deleted("note", "free-note", user["id"])
        self.assertFalse(content_retention.is_visible(
            "note", "free-note", user["id"]
        ))

        paid_created = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO notes(id,user_id,title,body,created_at) "
            "VALUES(?,?,?,?,?)",
            ("paid-note", user["id"], "title", "body", paid_created),
        )
        with mock.patch.object(content_retention, "_paid_at_creation", return_value=True):
            paid = content_retention.record_content(
                "note",
                "paid-note",
                user["id"],
                created_at=paid_created,
            )
        self.assertEqual(paid["retention_class"], "paid_indefinite")
        self.assertIsNone(paid["active_until"])

    def test_paid_note_and_diagnosis_delete_then_purge_once(self):
        user = self._create_user()
        login = self._login()
        headers = {"Authorization": f"Bearer {login['token']}"}
        created_at = datetime.now(timezone.utc)
        db.execute(
            "INSERT INTO notes(id,user_id,title,body,created_at) "
            "VALUES(?,?,?,?,?)",
            (
                "paid-delete-note",
                user["id"],
                "paid",
                "body",
                created_at.isoformat(),
            ),
        )
        db.execute(
            "INSERT INTO saved_diagnoses("
            "id,user_id,diagnosis_json,created_at"
            ") VALUES(?,?,?,?)",
            (
                "paid-delete-diagnosis",
                user["id"],
                "{}",
                created_at.isoformat(),
            ),
        )
        with mock.patch.object(
            content_retention,
            "_paid_at_creation",
            return_value=True,
        ):
            content_retention.record_content(
                "note",
                "paid-delete-note",
                user["id"],
                created_at=created_at.isoformat(),
            )
            content_retention.record_content(
                "diagnosis",
                "paid-delete-diagnosis",
                user["id"],
                created_at=created_at.isoformat(),
            )

        deleted_at = datetime.now(timezone.utc)
        with mock.patch.object(
            content_retention,
            "_now",
            return_value=deleted_at,
        ):
            self.assertEqual(
                self.client.delete(
                    "/notes/paid-delete-note",
                    headers=headers,
                ).status_code,
                200,
            )
            self.assertEqual(
                self.client.delete(
                    "/diagnoses/paid-delete-diagnosis",
                    headers=headers,
                ).status_code,
                200,
            )

        expected_purge = deleted_at + timedelta(
            days=content_retention.BACKUP_CLEAR_DAYS
        )
        for content_type, content_id in (
            ("note", "paid-delete-note"),
            ("diagnosis", "paid-delete-diagnosis"),
        ):
            row = db.fetchone(
                "SELECT retention_class,active_until,recovery_until,"
                "deleted_at,purge_after,purged_at "
                "FROM content_retention WHERE content_type=? AND content_id=?",
                (content_type, content_id),
            )
            self.assertEqual(row["retention_class"], "paid_indefinite")
            self.assertIsNone(row["active_until"])
            self.assertIsNone(row["recovery_until"])
            self.assertEqual(row["deleted_at"], deleted_at.isoformat())
            self.assertEqual(row["purge_after"], expected_purge.isoformat())
            self.assertIsNone(row["purged_at"])
            self.assertEqual(
                content_retention.status(
                    content_type,
                    content_id,
                    user["id"],
                )["state"],
                "deleted",
            )

        retry_at = deleted_at + timedelta(days=5)
        with mock.patch.object(
            content_retention,
            "_now",
            return_value=retry_at,
        ):
            self.assertEqual(
                self.client.delete(
                    "/notes/paid-delete-note",
                    headers=headers,
                ).status_code,
                200,
            )
            self.assertEqual(
                self.client.delete(
                    "/diagnoses/paid-delete-diagnosis",
                    headers=headers,
                ).status_code,
                200,
            )
        for content_type, content_id in (
            ("note", "paid-delete-note"),
            ("diagnosis", "paid-delete-diagnosis"),
        ):
            row = db.fetchone(
                "SELECT deleted_at,purge_after FROM content_retention "
                "WHERE content_type=? AND content_id=?",
                (content_type, content_id),
            )
            self.assertEqual(row["deleted_at"], deleted_at.isoformat())
            self.assertEqual(row["purge_after"], expected_purge.isoformat())

        self.assertEqual(
            content_retention.process_due_content_purges(
                now=expected_purge - timedelta(microseconds=1),
            ),
            [],
        )
        self.assertIsNotNone(db.fetchone(
            "SELECT id FROM notes WHERE id='paid-delete-note'"
        ))
        self.assertIsNotNone(db.fetchone(
            "SELECT id FROM saved_diagnoses "
            "WHERE id='paid-delete-diagnosis'"
        ))

        with mock.patch.object(
            db,
            "_retention_now",
            return_value=expected_purge,
        ):
            purged = content_retention.process_due_content_purges(
                now=expected_purge,
            )
        self.assertEqual(
            set(purged),
            {
                "note:paid-delete-note",
                "diagnosis:paid-delete-diagnosis",
            },
        )
        self.assertIsNone(db.fetchone(
            "SELECT id FROM notes WHERE id='paid-delete-note'"
        ))
        self.assertIsNone(db.fetchone(
            "SELECT id FROM saved_diagnoses "
            "WHERE id='paid-delete-diagnosis'"
        ))
        with mock.patch.object(
            db,
            "_retention_now",
            return_value=expected_purge,
        ):
            self.assertEqual(
                content_retention.process_due_content_purges(
                    now=expected_purge,
                ),
                [],
            )

    def test_sqlite_upgrades_legacy_paid_retention_contract(self):
        user = self._create_user()
        now = datetime.now(timezone.utc).isoformat()
        with db.transaction(write=True) as tx:
            tx.execute("DROP TABLE content_retention")
            tx.execute(
                """
                CREATE TABLE content_retention (
                    content_type TEXT NOT NULL,
                    content_id TEXT NOT NULL,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    retention_class TEXT NOT NULL,
                    active_until TEXT,
                    recovery_until TEXT,
                    deleted_at TEXT,
                    purge_after TEXT,
                    purged_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    contract_version TEXT NOT NULL,
                    CHECK (
                        (retention_class='paid_indefinite'
                            AND active_until IS NULL
                            AND recovery_until IS NULL
                            AND purge_after IS NULL)
                        OR
                        (retention_class='free_7d'
                            AND active_until IS NOT NULL
                            AND recovery_until IS NOT NULL
                            AND purge_after IS NOT NULL
                            AND active_until<=recovery_until
                            AND recovery_until<=purge_after)
                    ),
                    PRIMARY KEY(content_type,content_id)
                )
                """
            )
            tx.execute(
                "INSERT INTO content_retention("
                "content_type,content_id,user_id,retention_class,"
                "active_until,recovery_until,deleted_at,purge_after,purged_at,"
                "created_at,updated_at,contract_version"
                ") VALUES(?,?,?,'paid_indefinite',NULL,NULL,NULL,NULL,NULL,?,?,?)",
                (
                    "note",
                    "legacy-paid-note",
                    user["id"],
                    now,
                    now,
                    content_retention.CONTRACT_VERSION,
                ),
            )

        db.init_db()
        schema = db.fetchone(
            "SELECT sql FROM sqlite_master "
            "WHERE type='table' AND name='content_retention'"
        )["sql"]
        self.assertIn("content_retention_state_check", schema)
        retained = db.fetchone(
            "SELECT retention_class,active_until,recovery_until,purge_after "
            "FROM content_retention WHERE content_id='legacy-paid-note'"
        )
        self.assertEqual(retained["retention_class"], "paid_indefinite")
        self.assertIsNone(retained["purge_after"])
        content_retention.mark_deleted(
            "note",
            "legacy-paid-note",
            user["id"],
        )
        deleted = db.fetchone(
            "SELECT retention_class,deleted_at,purge_after "
            "FROM content_retention WHERE content_id='legacy-paid-note'"
        )
        self.assertEqual(deleted["retention_class"], "paid_indefinite")
        self.assertTrue(deleted["deleted_at"])
        self.assertTrue(deleted["purge_after"])

    def test_sqlite_retention_upgrade_copy_fault_rolls_back_and_retries(self):
        user = self._create_user()
        now = datetime.now(timezone.utc).isoformat()
        with db.transaction(write=True) as tx:
            tx.execute("DROP TABLE content_retention")
            tx.execute(
                """
                CREATE TABLE content_retention (
                    content_type TEXT NOT NULL,
                    content_id TEXT NOT NULL,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    retention_class TEXT NOT NULL,
                    active_until TEXT,
                    recovery_until TEXT,
                    deleted_at TEXT,
                    purge_after TEXT,
                    purged_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    contract_version TEXT NOT NULL,
                    PRIMARY KEY(content_type,content_id)
                )
                """
            )
            tx.execute(
                "CREATE INDEX idx_content_retention_user_state "
                "ON content_retention("
                "user_id,content_type,active_until,recovery_until)"
            )
            tx.execute(
                "INSERT INTO content_retention("
                "content_type,content_id,user_id,retention_class,"
                "active_until,recovery_until,deleted_at,purge_after,purged_at,"
                "created_at,updated_at,contract_version"
                ") VALUES(?,?,?,'paid_indefinite',NULL,NULL,NULL,NULL,NULL,?,?,?)",
                (
                    "note",
                    "copy-fault-paid-note",
                    user["id"],
                    now,
                    now,
                    content_retention.CONTRACT_VERSION,
                ),
            )

        class CopyFaultConnection:
            def __init__(self, connection):
                self.connection = connection
                self.injected = False

            def execute(self, sql, params=()):
                normalized = " ".join(str(sql).split()).upper()
                if (
                    not self.injected
                    and normalized.startswith("INSERT INTO CONTENT_RETENTION(")
                    and "FROM CONTENT_RETENTION_LEGACY_H15" in normalized
                ):
                    self.injected = True
                    raise sqlite3.OperationalError("injected copy fault")
                return self.connection.execute(sql, params)

            def __getattr__(self, name):
                return getattr(self.connection, name)

        conn = db._get_sqlite_conn()
        try:
            with self.assertRaisesRegex(
                sqlite3.OperationalError,
                "injected copy fault",
            ):
                db._upgrade_sqlite_content_retention_contract(
                    CopyFaultConnection(conn)
                )
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertIn("content_retention", tables)
            self.assertNotIn("content_retention_legacy_h15", tables)
            schema = conn.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type='table' AND name='content_retention'"
            ).fetchone()["sql"]
            self.assertNotIn("content_retention_state_check_h16", schema)
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM content_retention "
                    "WHERE content_id='copy-fault-paid-note'"
                ).fetchone()["c"],
                1,
            )
            self.assertIsNotNone(conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' "
                "AND name='idx_content_retention_user_state'"
            ).fetchone())

            db._upgrade_sqlite_content_retention_contract(conn)
            upgraded_schema = conn.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type='table' AND name='content_retention'"
            ).fetchone()["sql"]
            self.assertIn(
                "content_retention_state_check_h16",
                upgraded_schema,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM content_retention "
                    "WHERE content_id='copy-fault-paid-note'"
                ).fetchone()["c"],
                1,
            )
            conn.execute(
                "CREATE TABLE content_retention_legacy_h15(marker TEXT)"
            )
            with self.assertRaisesRegex(
                RuntimeError,
                "stale content retention upgrade table blocks startup",
            ):
                db._upgrade_sqlite_content_retention_contract(conn)
            conn.execute("DROP TABLE content_retention_legacy_h15")
        finally:
            conn.close()

    def test_legacy_retention_is_inferred_and_never_indefinitely_active(self):
        user = self._create_user()
        created = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        db.execute(
            "INSERT INTO notes(id,user_id,title,body,created_at) VALUES(?,?,?,?,?)",
            ("legacy-note", user["id"], "title", "body", created),
        )
        inferred = content_retention.status("note", "legacy-note", user["id"])
        self.assertEqual(inferred["retention_class"], "free_7d")
        self.assertEqual(inferred["state"], "recovery")
        missing = content_retention.status("note", "missing-note", user["id"])
        self.assertEqual(missing["state"], "expired")

    def test_paid_classification_uses_subscription_at_creation_time(self):
        user = self._create_user()
        created = datetime.now(timezone.utc) - timedelta(days=40)
        db.execute(
            "INSERT INTO subscriptions("
            "id,user_id,tier,started_at,expires_at,is_active,period_start"
            ") VALUES(?,?,?,?,?,?,?)",
            (
                "historic-paid",
                user["id"],
                "pro",
                (created - timedelta(days=2)).isoformat(),
                (created + timedelta(days=2)).isoformat(),
                0,
                (created - timedelta(days=2)).isoformat(),
            ),
        )
        db.execute(
            "INSERT INTO notes(id,user_id,title,body,created_at) VALUES(?,?,?,?,?)",
            ("historic-paid-note", user["id"], "title", "body", created.isoformat()),
        )
        recorded = content_retention.record_content(
            "note",
            "historic-paid-note",
            user["id"],
            created_at=created.isoformat(),
        )
        self.assertEqual(recorded["retention_class"], "paid_indefinite")

    def test_h17_sqlite_runtime_paid_classification_uses_real_instants(self):
        cases = (
            (
                "offset-paid",
                "2026-01-01T07:30:00+08:00",
                "2026-01-01T08:30:00+08:00",
                "2026-01-01T00:00:00+00:00",
                "paid_indefinite",
            ),
            (
                "offset-free",
                "2025-12-31T16:30:00-08:00",
                "2026-01-01T01:30:00-08:00",
                "2026-01-01T00:00:00+00:00",
                "free_7d",
            ),
            (
                "whitespace-paid",
                " 2026-01-01T07:30:00+08:00 ",
                " 2026-01-01T08:30:00+08:00 ",
                "2026-01-01T00:00:00+00:00",
                "paid_indefinite",
            ),
        )
        for index, (
            label,
            started_at,
            expires_at,
            created_at,
            expected_class,
        ) in enumerate(cases):
            with self.subTest(label=label):
                user = self._create_user(
                    username=f"h17clock{index}",
                    password="Strong!Pass234",
                )
                db.execute(
                    "INSERT INTO subscriptions("
                    "id,user_id,tier,started_at,expires_at,is_active,period_start"
                    ") VALUES(?,?,?,?,?,?,?)",
                    (
                        f"h17-sub-{index}",
                        user["id"],
                        "pro",
                        started_at,
                        expires_at,
                        1,
                        started_at,
                    ),
                )
                db.execute(
                    "INSERT INTO notes(id,user_id,title,body,created_at) "
                    "VALUES(?,?,?,?,?)",
                    (
                        f"h17-note-{index}",
                        user["id"],
                        "title",
                        "body",
                        created_at,
                    ),
                )
                recorded = content_retention.record_content(
                    "note",
                    f"h17-note-{index}",
                    user["id"],
                    created_at=created_at,
                )
                self.assertEqual(
                    recorded["retention_class"],
                    expected_class,
                )

    def test_h18_content_created_at_is_strict_and_canonical(self):
        user = self._create_user(username="h18clock")
        db.execute(
            "INSERT INTO subscriptions("
            "id,user_id,tier,started_at,expires_at,is_active,period_start"
            ") VALUES(?,?,?,?,?,?,?)",
            (
                "h18-clock-sub",
                user["id"],
                "pro",
                "2026-01-01T11:00:00+00:00",
                "2026-01-01T13:00:00+00:00",
                1,
                "2026-01-01T11:00:00+00:00",
            ),
        )
        db.execute(
            "INSERT INTO notes(id,user_id,title,body,created_at) "
            "VALUES(?,?,?,?,?)",
            (
                "h18-whitespace-note",
                user["id"],
                "title",
                "body",
                " 2026-01-01T12:00:00+00:00 ",
            ),
        )
        recorded = content_retention.record_content(
            "note",
            "h18-whitespace-note",
            user["id"],
            created_at=" 2026-01-01T12:00:00+00:00 ",
        )
        self.assertEqual(recorded["retention_class"], "paid_indefinite")
        self.assertEqual(
            db.fetchone(
                "SELECT created_at FROM content_retention "
                "WHERE content_type='note' AND content_id=?",
                ("h18-whitespace-note",),
            )["created_at"],
            "2026-01-01T12:00:00+00:00",
        )

        with self.assertRaisesRegex(
            ValueError,
            "invalid retention content clock",
        ):
            content_retention.record_content(
                "note",
                "h18-invalid-note",
                user["id"],
                created_at="not-a-clock",
            )
        self.assertIsNone(db.fetchone(
            "SELECT content_id FROM content_retention "
            "WHERE content_type='note' AND content_id=?",
            ("h18-invalid-note",),
        ))

    def test_h18_sqlite_retention_identity_is_immutable(self):
        user = self._create_user(username="h18identity")
        created_at = (
            datetime.now(timezone.utc) - timedelta(days=100)
        ).isoformat()
        db.execute(
            "INSERT INTO notes(id,user_id,title,body,created_at) "
            "VALUES(?,?,?,?,?)",
            ("h18-identity-note", user["id"], "title", "body", created_at),
        )
        content_retention.record_content(
            "note",
            "h18-identity-note",
            user["id"],
            created_at=created_at,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(
                "UPDATE content_retention SET content_type='diagnosis',"
                "content_id='h18-ghost',purged_at=?,updated_at=? "
                "WHERE content_type='note' AND content_id=?",
                (
                    datetime.now(timezone.utc).isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                    "h18-identity-note",
                ),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(
                "UPDATE content_retention SET user_id=? "
                "WHERE content_type='note' AND content_id=?",
                (user["id"] + "-other", "h18-identity-note"),
            )
        self.assertIsNotNone(db.fetchone(
            "SELECT content_id FROM content_retention "
            "WHERE content_type='note' AND content_id='h18-identity-note'"
        ))

    def test_h19_sqlite_note_identity_is_immutable_but_parent_is_mutable(self):
        owner = self._create_user(username="h19noteowner")
        other = self._create_user(username="h19noteother")
        created_at = (
            datetime.now(timezone.utc) - timedelta(days=100)
        ).isoformat()
        for note_id, parent_id in (
            ("h19-note-id", None),
            ("h19-note-owner", None),
            ("h19-note-both", None),
            ("h19-note-root", None),
            ("h19-note-child", "h19-note-root"),
        ):
            db.execute(
                "INSERT INTO notes("
                "id,user_id,title,body,parent_id,created_at"
                ") VALUES(?,?,?,?,?,?)",
                (
                    note_id,
                    owner["id"],
                    "title",
                    "body",
                    parent_id,
                    created_at,
                ),
            )
            content_retention.record_content(
                "note",
                note_id,
                owner["id"],
                created_at=created_at,
            )

        for assignment, params in (
            (
                "id=?",
                ("h19-note-moved-id", "h19-note-id", owner["id"]),
            ),
            (
                "user_id=?",
                (other["id"], "h19-note-owner", owner["id"]),
            ),
            (
                "id=?,user_id=?",
                (
                    "h19-note-moved-both",
                    other["id"],
                    "h19-note-both",
                    owner["id"],
                ),
            ),
        ):
            with (
                self.subTest(assignment=assignment),
                self.assertRaises(sqlite3.IntegrityError),
            ):
                db.execute(
                    f"UPDATE notes SET {assignment} WHERE id=? AND user_id=?",
                    params,
                )

        db.execute(
            "UPDATE notes SET parent_id=NULL WHERE id=? AND user_id=?",
            ("h19-note-child", owner["id"]),
        )
        self.assertIsNone(db.fetchone(
            "SELECT parent_id FROM notes WHERE id='h19-note-child'"
        )["parent_id"])

    def test_h19_sqlite_diagnosis_identity_is_immutable(self):
        owner = self._create_user(username="h19diagnosisowner")
        other = self._create_user(username="h19diagnosisother")
        created_at = (
            datetime.now(timezone.utc) - timedelta(days=100)
        ).isoformat()
        for diagnosis_id in (
            "h19-diagnosis-id",
            "h19-diagnosis-owner",
            "h19-diagnosis-both",
        ):
            db.execute(
                "INSERT INTO saved_diagnoses("
                "id,user_id,note_title,diagnosis_json,created_at"
                ") VALUES(?,?,?,?,?)",
                (
                    diagnosis_id,
                    owner["id"],
                    "title",
                    "{}",
                    created_at,
                ),
            )
            content_retention.record_content(
                "diagnosis",
                diagnosis_id,
                owner["id"],
                created_at=created_at,
            )

        for assignment, params in (
            (
                "id=?",
                (
                    "h19-diagnosis-moved-id",
                    "h19-diagnosis-id",
                    owner["id"],
                ),
            ),
            (
                "user_id=?",
                (
                    other["id"],
                    "h19-diagnosis-owner",
                    owner["id"],
                ),
            ),
            (
                "id=?,user_id=?",
                (
                    "h19-diagnosis-moved-both",
                    other["id"],
                    "h19-diagnosis-both",
                    owner["id"],
                ),
            ),
        ):
            with (
                self.subTest(assignment=assignment),
                self.assertRaises(sqlite3.IntegrityError),
            ):
                db.execute(
                    "UPDATE saved_diagnoses SET "
                    f"{assignment} WHERE id=? AND user_id=?",
                    params,
                )

    def test_h20_sqlite_retained_primary_cannot_be_reinserted(self):
        owner = self._create_user(username="h20owner")
        other = self._create_user(username="h20other")
        now = datetime.now(timezone.utc)
        created_at = (now - timedelta(days=100)).isoformat()
        cases = (
            ("note", "h20-note-same", owner["id"]),
            ("note", "h20-note-other", other["id"]),
            ("diagnosis", "h20-diagnosis-same", owner["id"]),
            ("diagnosis", "h20-diagnosis-other", other["id"]),
        )
        for content_type, content_id, _ in cases:
            if content_type == "note":
                db.execute(
                    "INSERT INTO notes("
                    "id,user_id,title,body,created_at"
                    ") VALUES(?,?,?,?,?)",
                    (content_id, owner["id"], "title", "body", created_at),
                )
            else:
                db.execute(
                    "INSERT INTO saved_diagnoses("
                    "id,user_id,note_title,diagnosis_json,created_at"
                    ") VALUES(?,?,?,?,?)",
                    (content_id, owner["id"], "title", "{}", created_at),
                )
            content_retention.record_content(
                content_type,
                content_id,
                owner["id"],
                created_at=created_at,
            )
        self.assertEqual(
            len(content_retention.process_due_content_purges(now=now)),
            4,
        )

        for content_type, content_id, reinsert_owner in cases:
            with (
                self.subTest(
                    content_type=content_type,
                    reinsert_owner=reinsert_owner,
                ),
                self.assertRaises(sqlite3.IntegrityError),
            ):
                if content_type == "note":
                    db.execute(
                        "INSERT OR REPLACE INTO notes("
                        "id,user_id,title,body,created_at"
                        ") VALUES(?,?,?,?,?)",
                        (
                            content_id,
                            reinsert_owner,
                            "reinserted",
                            "body",
                            now.isoformat(),
                        ),
                    )
                else:
                    db.execute(
                        "INSERT OR REPLACE INTO saved_diagnoses("
                        "id,user_id,note_title,diagnosis_json,created_at"
                        ") VALUES(?,?,?,?,?)",
                        (
                            content_id,
                            reinsert_owner,
                            "reinserted",
                            "{}",
                            now.isoformat(),
                        ),
                    )

    def test_h20_sqlite_purge_then_reinsert_in_one_transaction_rolls_back(self):
        owner = self._create_user(username="h20transaction")
        now = datetime.now(timezone.utc)
        created_at = (now - timedelta(days=100)).isoformat()
        for content_type, content_id, table in (
            ("note", "h20-note-transaction", "notes"),
            (
                "diagnosis",
                "h20-diagnosis-transaction",
                "saved_diagnoses",
            ),
        ):
            if content_type == "note":
                db.execute(
                    "INSERT INTO notes("
                    "id,user_id,title,body,created_at"
                    ") VALUES(?,?,?,?,?)",
                    (content_id, owner["id"], "title", "body", created_at),
                )
                insert_sql = (
                    "INSERT INTO notes("
                    "id,user_id,title,body,created_at"
                    ") VALUES(?,?,?,?,?)"
                )
                insert_params = (
                    content_id,
                    owner["id"],
                    "reinserted",
                    "body",
                    now.isoformat(),
                )
            else:
                db.execute(
                    "INSERT INTO saved_diagnoses("
                    "id,user_id,note_title,diagnosis_json,created_at"
                    ") VALUES(?,?,?,?,?)",
                    (content_id, owner["id"], "title", "{}", created_at),
                )
                insert_sql = (
                    "INSERT INTO saved_diagnoses("
                    "id,user_id,note_title,diagnosis_json,created_at"
                    ") VALUES(?,?,?,?,?)"
                )
                insert_params = (
                    content_id,
                    owner["id"],
                    "reinserted",
                    "{}",
                    now.isoformat(),
                )
            content_retention.record_content(
                content_type,
                content_id,
                owner["id"],
                created_at=created_at,
            )
            with (
                self.subTest(content_type=content_type),
                self.assertRaises(sqlite3.IntegrityError),
            ):
                with db.transaction(write=True) as tx:
                    tx.execute(
                        f"DELETE FROM {table} WHERE id=? AND user_id=?",
                        (content_id, owner["id"]),
                    )
                    tx.execute(
                        "UPDATE content_retention SET "
                        "purged_at=?,updated_at=? "
                        "WHERE content_type=? AND content_id=?",
                        (
                            now.isoformat(),
                            now.isoformat(),
                            content_type,
                            content_id,
                        ),
                    )
                    tx.execute(insert_sql, insert_params)
            self.assertIsNotNone(db.fetchone(
                f"SELECT id FROM {table} WHERE id=? AND user_id=?",
                (content_id, owner["id"]),
            ))
            self.assertIsNone(db.fetchone(
                "SELECT purged_at FROM content_retention "
                "WHERE content_type=? AND content_id=?",
                (content_type, content_id),
            )["purged_at"])

    def test_h20_sqlite_retention_requires_matching_primary(self):
        owner = self._create_user(username="h20retentionowner")
        other = self._create_user(username="h20retentionother")
        now = datetime.now(timezone.utc).isoformat()
        with self.assertRaises(sqlite3.IntegrityError):
            content_retention.record_content(
                "note",
                "h20-missing-note",
                owner["id"],
                created_at=now,
            )
        db.execute(
            "INSERT INTO notes(id,user_id,title,body,created_at) "
            "VALUES(?,?,?,?,?)",
            ("h20-owner-note", owner["id"], "title", "body", now),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            content_retention.record_content(
                "note",
                "h20-owner-note",
                other["id"],
                created_at=now,
            )

    def test_h21_sqlite_retention_identity_cannot_be_replaced(self):
        owner = self._create_user(username="h21replace")
        now = datetime.now(timezone.utc)
        created_at = (now - timedelta(days=1)).isoformat()
        for insert_verb, content_id in (
            ("INSERT OR REPLACE", "h21-insert-or-replace"),
            ("REPLACE", "h21-replace"),
        ):
            db.execute(
                "INSERT INTO notes(id,user_id,title,body,created_at) "
                "VALUES(?,?,?,?,?)",
                (content_id, owner["id"], "title", "body", created_at),
            )
            content_retention.record_content(
                "note",
                content_id,
                owner["id"],
                created_at=created_at,
            )
            before = dict(db.fetchone(
                "SELECT * FROM content_retention "
                "WHERE content_type='note' AND content_id=?",
                (content_id,),
            ))
            with (
                self.subTest(insert_verb=insert_verb),
                self.assertRaises(sqlite3.IntegrityError),
            ):
                db.execute(
                    f"{insert_verb} INTO content_retention("
                    "content_type,content_id,user_id,retention_class,"
                    "active_until,recovery_until,deleted_at,purge_after,"
                    "purged_at,created_at,updated_at,contract_version"
                    ") VALUES(?,?,?,'paid_indefinite',NULL,NULL,NULL,NULL,"
                    "NULL,?,?,?)",
                    (
                        "note",
                        content_id,
                        owner["id"],
                        now.isoformat(),
                        now.isoformat(),
                        "forged-contract",
                    ),
                )
            after = dict(db.fetchone(
                "SELECT * FROM content_retention "
                "WHERE content_type='note' AND content_id=?",
                (content_id,),
            ))
            self.assertEqual(after, before)

    def test_h22_record_content_repeat_is_safe_and_idempotent(self):
        owner = self._create_user(username="h22owner")
        other = self._create_user(username="h22other")
        created_at = "2026-01-01T12:00:00+00:00"
        db.execute(
            "INSERT INTO notes(id,user_id,title,body,created_at) "
            "VALUES(?,?,?,?,?)",
            ("h22-note", owner["id"], "title", "body", created_at),
        )
        first = content_retention.record_content(
            "note",
            "h22-note",
            owner["id"],
            created_at=created_at,
        )
        for repeat_clock in (
            created_at,
            " 2026-01-01T20:00:00+08:00 ",
            None,
        ):
            with self.subTest(repeat_clock=repeat_clock):
                repeated = content_retention.record_content(
                    "note",
                    "h22-note",
                    owner["id"],
                    created_at=repeat_clock,
                )
                self.assertEqual(repeated, first)
        with self.assertRaisesRegex(
            ValueError,
            "content retention identity conflict",
        ):
            content_retention.record_content(
                "note",
                "h22-note",
                other["id"],
                created_at=created_at,
            )
        with self.assertRaisesRegex(
            ValueError,
            "content retention creation clock conflict",
        ):
            content_retention.record_content(
                "note",
                "h22-note",
                owner["id"],
                created_at="2026-01-01T12:00:01+00:00",
            )
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM content_retention "
                "WHERE content_type='note' AND content_id='h22-note'"
            )["c"],
            1,
        )

    def test_h17_purge_marker_requires_real_delete_and_nonfuture_clock(self):
        user = self._create_user()
        now = datetime.now(timezone.utc)
        created_at = (now - timedelta(days=100)).isoformat()
        deleted_at = now - timedelta(days=31)
        for content_type, content_id, table in (
            ("note", "h17-purge-note", "notes"),
            ("diagnosis", "h17-purge-diagnosis", "saved_diagnoses"),
        ):
            with self.subTest(content_type=content_type):
                if content_type == "note":
                    db.execute(
                        "INSERT INTO notes(id,user_id,title,body,created_at) "
                        "VALUES(?,?,?,?,?)",
                        (content_id, user["id"], "title", "body", created_at),
                    )
                else:
                    db.execute(
                        "INSERT INTO saved_diagnoses("
                        "id,user_id,diagnosis_json,created_at"
                        ") VALUES(?,?,?,?)",
                        (content_id, user["id"], "{}", created_at),
                    )
                with mock.patch.object(
                    content_retention,
                    "_paid_at_creation",
                    return_value=True,
                ):
                    content_retention.record_content(
                        content_type,
                        content_id,
                        user["id"],
                        created_at=created_at,
                    )
                with mock.patch.object(
                    content_retention,
                    "_now",
                    return_value=deleted_at,
                ):
                    content_retention.mark_deleted(
                        content_type,
                        content_id,
                        user["id"],
                    )

                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(
                        "UPDATE content_retention SET purged_at=?,updated_at=? "
                        "WHERE content_type=? AND content_id=?",
                        (
                            now.isoformat(),
                            now.isoformat(),
                            content_type,
                            content_id,
                        ),
                    )
                self.assertIsNotNone(db.fetchone(
                    f"SELECT id FROM {table} WHERE id=?",
                    (content_id,),
                ))

        with db.transaction(write=True) as tx:
            tx.execute("DROP TRIGGER content_retention_purge_update_h17")
            tx.execute(
                "UPDATE content_retention SET purged_at=?,updated_at=? "
                "WHERE content_type='note' AND content_id=?",
                (
                    now.isoformat(),
                    now.isoformat(),
                    "h17-purge-note",
                ),
            )
        self.assertEqual(
            content_retention.status(
                "note",
                "h17-purge-note",
                user["id"],
            )["state"],
            "expired",
        )
        with db.transaction(write=True) as tx:
            tx.execute(
                "UPDATE content_retention SET purged_at=NULL "
                "WHERE content_type='note' AND content_id=?",
                ("h17-purge-note",),
            )
            db._ensure_sqlite_content_retention_purge_guards(tx.conn)

        future = now + timedelta(days=1)
        with self.assertRaises(sqlite3.IntegrityError):
            with db.transaction(write=True) as tx:
                tx.execute(
                    "DELETE FROM notes WHERE id=? AND user_id=?",
                    ("h17-purge-note", user["id"]),
                )
                tx.execute(
                    "UPDATE content_retention SET purged_at=?,updated_at=? "
                    "WHERE content_type='note' AND content_id=?",
                    (
                        future.isoformat(),
                        future.isoformat(),
                        "h17-purge-note",
                    ),
                )
        self.assertIsNotNone(db.fetchone(
            "SELECT id FROM notes WHERE id='h17-purge-note'"
        ))

        self.assertEqual(
            set(content_retention.process_due_content_purges(now=now)),
            {"note:h17-purge-note", "diagnosis:h17-purge-diagnosis"},
        )
        for content_type, content_id in (
            ("note", "h17-purge-note"),
            ("diagnosis", "h17-purge-diagnosis"),
        ):
            self.assertEqual(
                content_retention.status(
                    content_type,
                    content_id,
                    user["id"],
                )["state"],
                "purged",
            )
        self.assertEqual(
            content_retention._status_payload(
                {
                    "retention_class": "paid_indefinite",
                    "active_until": None,
                    "recovery_until": None,
                    "deleted_at": deleted_at.isoformat(),
                    "purge_after": (
                        deleted_at + timedelta(days=30)
                    ).isoformat(),
                    "purged_at": future.isoformat(),
                },
                now,
                primary_exists=False,
            )["state"],
            "expired",
        )

    def test_content_and_retention_metadata_commit_atomically(self):
        user = self._create_user()
        now = datetime.now(timezone.utc).isoformat()
        sql = "INSERT INTO notes(id,user_id,title,body,created_at) VALUES(?,?,?,?,?)"
        params = ("atomic-note", user["id"], "title", "body", now)
        with mock.patch.object(
            content_retention,
            "_record_content_with_storage",
            side_effect=RuntimeError("synthetic metadata failure"),
        ):
            with self.assertRaises(RuntimeError):
                content_retention.insert_content(
                    sql,
                    params,
                    "note",
                    "atomic-note",
                    user["id"],
                    created_at=now,
                )
        self.assertIsNone(db.fetchone(
            "SELECT id FROM notes WHERE id=?",
            ("atomic-note",),
        ))

    def test_archive_recovery_enforces_owner_boundary(self):
        owner = self._create_user()
        owner_login = self._login()
        other = auth.create_user("otheruser", "Other&Strong2026")
        other_login = auth.login_user(
            "otheruser",
            "Other&Strong2026",
            requester_fingerprint="other-client",
        )
        created = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        db.execute(
            "INSERT INTO notes(id,user_id,title,body,created_at) VALUES(?,?,?,?,?)",
            ("owner-note", owner["id"], "owner title", "body", created),
        )
        content_retention.record_content(
            "note", "owner-note", owner["id"], created_at=created
        )
        denied = self.client.post(
            "/account/archive/recover",
            headers={"Authorization": f"Bearer {other_login['token']}"},
            json={"content_type": "note", "content_id": "owner-note"},
        )
        self.assertEqual(denied.status_code, 404)
        accepted = self.client.post(
            "/account/archive/recover",
            headers={"Authorization": f"Bearer {owner_login['token']}"},
            json={"content_type": "note", "content_id": "owner-note"},
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["retention"]["state"], "active")
        self.assertNotEqual(owner["id"], other["id"])

    def test_export_sanitizes_diagnosis_and_excludes_deleted_content(self):
        user = self._create_user()
        login = self._login()
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO notes(id,user_id,title,body,created_at) VALUES(?,?,?,?,?)",
            ("visible-note", user["id"], "safe title", "safe body", now),
        )
        content_retention.record_content(
            "note", "visible-note", user["id"], created_at=now
        )
        db.execute(
            "INSERT INTO saved_diagnoses("
            "id,user_id,note_title,domain,diagnosis_json,created_at"
            ") VALUES(?,?,?,?,?,?)",
            (
                "visible-diagnosis",
                user["id"],
                "safe",
                "美食",
                json.dumps({
                    "grade": "A",
                    "reasoning": "private chain",
                    "raw_provider_response": "private response",
                }),
                now,
            ),
        )
        content_retention.record_content(
            "diagnosis", "visible-diagnosis", user["id"], created_at=now
        )
        response = self.client.get(
            "/account/export",
            headers={"Authorization": f"Bearer {login['token']}"},
        )
        self.assertEqual(response.status_code, 200)
        serialized = json.dumps(response.json(), ensure_ascii=False)
        self.assertIn("visible-note", serialized)
        self.assertNotIn("private chain", serialized)
        self.assertNotIn("private response", serialized)
        self.assertIn("raw_supplier_responses", serialized)
        archives = response.json()["archives"]
        self.assertIn("chat_sessions", archives)
        self.assertIn("memories", archives)
        self.assertIn("growth_records", archives)
        self.assertIn("tracking", archives)
        self.assertIn("operation_metadata", response.json())

    def test_due_content_purge_removes_primary_copy_idempotently(self):
        user = self._create_user()
        created = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        db.execute(
            "INSERT INTO notes(id,user_id,title,body,created_at) VALUES(?,?,?,?,?)",
            ("purge-note", user["id"], "title", "body", created),
        )
        content_retention.record_content(
            "note",
            "purge-note",
            user["id"],
            created_at=created,
        )
        purged = content_retention.process_due_content_purges(
            now=datetime.now(timezone.utc),
        )
        self.assertEqual(purged, ["note:purge-note"])
        self.assertIsNone(db.fetchone("SELECT id FROM notes WHERE id='purge-note'"))
        self.assertEqual(
            content_retention.status("note", "purge-note", user["id"])["state"],
            "purged",
        )
        self.assertEqual(content_retention.process_due_content_purges(), [])

    def test_account_deletion_immediately_revokes_access_and_sets_deadlines(self):
        user = self._create_user()
        login = self._login()
        response = self.client.request(
            "DELETE",
            "/account",
            headers={"Authorization": f"Bearer {login['token']}"},
            json={"password": "Strong!Pass234"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("primary_delete_by", body)
        self.assertIn("backup_clear_by", body)
        self.assertEqual(body["final_export"]["account"]["username"], "safeuser")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(
            self.client.get(
                "/auth/me",
                headers={"Authorization": f"Bearer {login['token']}"},
            ).status_code,
            401,
        )
        with self.assertRaises(ValueError):
            auth.login_user("safeuser", "Strong!Pass234")
        self.assertTrue(db.fetchone(
            "SELECT deletion_requested_at FROM users WHERE id=?",
            (user["id"],),
        )["deletion_requested_at"])

    def test_redaction_and_public_diagnosis_filters(self):
        secret = (
            "Authorization: Bearer opaque-token "
            "phone 13800138000 email person@example.com "
            "https://example.com/private"
        )
        redacted = security_redaction.redact_text(secret)
        self.assertNotIn("opaque-token", redacted)
        self.assertNotIn("13800138000", redacted)
        self.assertNotIn("person@example.com", redacted)
        self.assertNotIn("example.com/private", redacted)
        safe = api._public_diagnosis_value({
            "grade": "A",
            "reasoning": "hidden",
            "provider_payload": {"secret": "hidden"},
            "nested": {"thinking_trace": "hidden", "score": 88},
        })
        self.assertEqual(safe, {"grade": "A", "nested": {"score": 88}})
        aliases = api._public_diagnosis_value({
            "analysis": "hidden",
            "chain_of_thought": "hidden",
            "cot": "hidden",
            "scratchpad": "hidden",
            "internal_trace": "hidden",
            "raw_completion": "hidden",
            "supplement_prompts": [{"prompt": "请补充真实价格", "reasoning": "hidden"}],
        })
        self.assertEqual(
            aliases,
            {"supplement_prompts": [{"prompt": "请补充真实价格"}]},
        )
        log_path = Path(self.temp.name) / "service.log"
        log_path.write_text(f"[auth] ERROR {secret}\n", encoding="utf-8")
        summary = security_redaction.summarize_log_lines(log_path, 10)
        serialized_summary = json.dumps(summary)
        self.assertFalse(summary["raw_text_included"])
        self.assertEqual(summary["source"], "service.log")
        self.assertNotIn("opaque-token", serialized_summary)
        self.assertNotIn("13800138000", serialized_summary)
        crawler_event = security_redaction.sanitize_crawler_event({
            "action": "failed https://example.com/private",
            "error": secret,
            "url": "https://example.com/private",
        })
        self.assertNotIn("url", crawler_event)
        self.assertNotIn("example.com", json.dumps(crawler_event))

    def test_versioned_legal_contract_is_public_and_truthful(self):
        response = self.client.get("/legal/contracts")
        self.assertEqual(response.status_code, 200)
        contract = response.json()
        self.assertEqual(contract["version"], content_retention.CONTRACT_VERSION)
        self.assertFalse(contract["refund"]["real_payment_gateway_enabled"])
        self.assertTrue(
            contract["cross_border"]["professional_confirmation_required"]
        )

    def test_registration_requires_and_records_versioned_consent(self):
        rejected = self.client.post(
            "/auth/register",
            json={"username": "noconsent", "password": "Strong!Pass234"},
        )
        self.assertEqual(rejected.status_code, 400)
        accepted = self.client.post(
            "/auth/register",
            json={
                "username": "consented",
                "password": "Strong!Pass234",
                **self._consent(),
            },
        )
        self.assertEqual(accepted.status_code, 200)
        user_id = accepted.json()["user"]["id"]
        row = db.fetchone(
            "SELECT * FROM user_contract_acceptances WHERE user_id=?",
            (user_id,),
        )
        self.assertEqual(row["contract_version"], content_retention.CONTRACT_VERSION)
        self.assertEqual(row["source"], "registration")

    def test_password_update_and_session_revoke_roll_back_together(self):
        user = self._create_user()
        self._login()
        original_execute = db.Transaction.execute

        def fail_session_delete(transaction, sql, params=()):
            if sql.startswith("DELETE FROM user_sessions"):
                raise RuntimeError("synthetic delete failure")
            return original_execute(transaction, sql, params)

        with mock.patch.object(db.Transaction, "execute", new=fail_session_delete):
            with self.assertRaises(RuntimeError):
                auth.change_password(
                    user["id"],
                    "Strong!Pass234",
                    "Changed!Pass2026",
                )
        self.assertTrue(auth.login_user(
            "safeuser",
            "Strong!Pass234",
            requester_fingerprint="rollback-check",
        )["token"])

    def test_primary_deletion_processor_is_bounded_and_idempotent(self):
        user = self._create_user()
        db.execute(
            "INSERT INTO usage_records("
            "id,user_id,operation,recorded_at"
            ") VALUES(?,?,?,?)",
            ("usage-before-delete", user["id"], "score", datetime.now(timezone.utc).isoformat()),
        )
        request = content_retention.request_account_deletion(user["id"])
        processed = content_retention.process_due_account_deletions(
            now=datetime.now(timezone.utc) + timedelta(days=2),
        )
        self.assertEqual(processed, [request["id"]])
        self.assertIsNone(db.fetchone("SELECT id FROM users WHERE id=?", (user["id"],)))
        retained = db.fetchone(
            "SELECT user_id FROM usage_records WHERE id='usage-before-delete'"
        )
        self.assertTrue(retained["user_id"].startswith("deleted:"))
        self.assertEqual(
            content_retention.process_due_account_deletions(
                now=datetime.now(timezone.utc) + timedelta(days=2),
            ),
            [],
        )
        completed = content_retention.confirm_backup_cleared(
            request["id"],
            "backup-proof:20260725",
        )
        self.assertEqual(completed["status"], "complete")

    def test_primary_deletion_processor_can_target_one_exact_request(self):
        first = self._create_user()
        second = auth.create_user(
            "exact-delete-second",
            "Strong!Pass234",
        )
        first_request = content_retention.request_account_deletion(first["id"])
        second_request = content_retention.request_account_deletion(second["id"])

        processed = content_retention.process_due_account_deletions(
            now=datetime.now(timezone.utc) + timedelta(days=2),
            request_id=second_request["id"],
        )

        self.assertEqual(processed, [second_request["id"]])
        self.assertIsNotNone(
            db.fetchone("SELECT id FROM users WHERE id=?", (first["id"],))
        )
        self.assertIsNone(
            db.fetchone("SELECT id FROM users WHERE id=?", (second["id"],))
        )
        self.assertEqual(
            db.fetchone(
                "SELECT status FROM account_deletion_requests WHERE id=?",
                (first_request["id"],),
            )["status"],
            "requested",
        )

    def test_repository_contract_contains_no_plaintext_cookie_fallback(self):
        runtime_source = (MODEL_DIR / "runtime_settings.py").read_text(encoding="utf-8")
        scheduler_source = (MODEL_DIR / "scheduler_a.py").read_text(encoding="utf-8")
        crawler_source = (MODEL_DIR / "crawler.py").read_text(encoding="utf-8")
        admin_source = (MODEL_DIR / "admin_server.py").read_text(encoding="utf-8")
        frontend = (ROOT / "NoteAI_Pro_Demo_Framer.html").read_text(encoding="utf-8")
        migration = (
            MODEL_DIR / "migrations/postgres/0009_account_security_compliance.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("NOTEAI_XHS_COOKIES_JSON", runtime_source)
        self.assertNotIn("xhs_cookies.json", scheduler_source)
        self.assertNotIn("_COOKIE_FILE.read_text", crawler_source)
        self.assertIn("summarize_log_lines", admin_source)
        self.assertIn("至少10位", frontend)
        self.assertIn("page-legal", frontend)
        self.assertIn("account_deletion_requests", migration)
        permission_matrix = (
            ROOT / "docs/FIRST_LAUNCH_DB_RUNTIME_PERMISSION_MATRIX.md"
        ).read_text(encoding="utf-8")
        self.assertIn("user_contract_acceptances", permission_matrix)
        self.assertNotIn("GRANT ", migration.upper())
        self.assertNotIn("noteai_service", frontend)
        self.assertIn("暂时不能购买套餐", frontend)
        admin_frontend = (MODEL_DIR / "admin.html").read_text(encoding="utf-8")
        self.assertIn("esc(JSON.stringify(l).slice(0,120))", admin_frontend)


    def test_username_rate_keys_match_case_sensitive_login_semantics(self):
        upper = account_security._login_keys("Alice", "same-origin")
        lower = account_security._login_keys("alice", "same-origin")
        self.assertNotEqual(upper, lower)

    def test_password_rejects_equivalent_phone_forms(self):
        for index, password in enumerate((
            "13800138000!",
            "8613800138000!",
            "+8613800138000!",
        )):
            with self.subTest(password=password), self.assertRaises(ValueError):
                auth.create_user(
                    f"phoneform{index}",
                    password,
                    phone="+86 138-0013-8000",
                    phone_verified=True,
                )

    def test_duplicate_registration_rolls_back_otp_consumption(self):
        auth.create_user(
            "existingphone",
            "Existing!Pass2026",
            phone="13800138000",
            phone_verified=True,
        )
        issued = account_security.issue_verification(
            channel="phone",
            destination="13800138000",
            purpose="register_phone",
        )
        response = self.client.post(
            "/auth/register",
            json={
                "username": "duplicatephone",
                "password": "Distinct!Pass2026",
                "phone": "13800138000",
                "phone_challenge_id": issued["challenge_id"],
                "phone_code": "246810",
                **self._consent(),
            },
        )
        self.assertEqual(response.status_code, 400)
        challenge = db.fetchone(
            "SELECT consumed_at FROM auth_verification_challenges WHERE id=?",
            (issued["challenge_id"],),
        )
        self.assertIsNone(challenge["consumed_at"])

    def test_profile_verification_failure_commits_attempt_but_no_profile_write(self):
        user = self._create_user()
        login = self._login()
        issued = account_security.issue_verification(
            channel="phone",
            destination="13800138000",
            purpose="bind_phone",
            requested_by_user_id=user["id"],
        )
        response = self.client.patch(
            "/auth/profile",
            headers={"Authorization": f"Bearer {login['token']}"},
            json={
                "nickname": "must-not-commit",
                "phone": "13800138000",
                "phone_challenge_id": issued["challenge_id"],
                "phone_code": "000000",
            },
        )
        self.assertEqual(response.status_code, 400)
        challenge = db.fetchone(
            "SELECT attempt_count,consumed_at FROM auth_verification_challenges "
            "WHERE id=?",
            (issued["challenge_id"],),
        )
        self.assertEqual(challenge["attempt_count"], 1)
        self.assertIsNone(challenge["consumed_at"])
        profile = db.fetchone(
            "SELECT nickname,phone FROM users WHERE id=?",
            (user["id"],),
        )
        self.assertIsNone(profile["nickname"])
        self.assertIsNone(profile["phone"])

    def test_sqlite_init_materializes_legacy_retention_and_invalid_clocks_fail_closed(self):
        user = self._create_user()
        created = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        db.execute(
            "INSERT INTO notes(id,user_id,title,body,created_at) VALUES(?,?,?,?,?)",
            ("materialized-note", user["id"], "title", "body", created),
        )
        self.assertIsNone(db.fetchone(
            "SELECT content_id FROM content_retention WHERE content_id=?",
            ("materialized-note",),
        ))
        db.init_db()
        row = db.fetchone(
            "SELECT retention_class,active_until,recovery_until,purge_after "
            "FROM content_retention WHERE content_id=?",
            ("materialized-note",),
        )
        self.assertEqual(row["retention_class"], "free_7d")
        self.assertTrue(row["active_until"] < row["recovery_until"] < row["purge_after"])
        invalid = content_retention._status_payload(
            {
                "retention_class": "paid_indefinite",
                "active_until": created,
                "recovery_until": None,
                "purge_after": None,
            },
            datetime.now(timezone.utc),
        )
        self.assertEqual(invalid["state"], "expired")

    def test_final_deletion_export_cannot_be_disabled_and_includes_user_learn(self):
        user = self._create_user()
        login = self._login()
        db.execute(
            "INSERT INTO user_learn("
            "user_id,pref_key,pref_value,confidence,update_count,updated_at"
            ") VALUES(?,?,?,?,?,?)",
            (
                user["id"],
                "tone",
                "concise",
                0.7,
                2,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        response = self.client.request(
            "DELETE",
            "/account",
            headers={"Authorization": f"Bearer {login['token']}"},
            json={
                "password": "Strong!Pass234",
                "include_final_export": False,
            },
        )
        self.assertEqual(response.status_code, 200)
        final_export = response.json()["final_export"]
        self.assertIsNotNone(final_export)
        self.assertEqual(
            final_export["archives"]["learned_preferences"][0]["pref_key"],
            "tone",
        )

    def test_note_delete_removes_version_chain_chat_and_context_copies(self):
        user = self._create_user()
        login = self._login()
        now = datetime.now(timezone.utc).isoformat()
        for note_id, parent_id in (("root-note", None), ("child-note", "root-note")):
            db.execute(
                "INSERT INTO notes(id,user_id,title,body,parent_id,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (note_id, user["id"], note_id, "body", parent_id, now),
            )
            content_retention.record_content(
                "note",
                note_id,
                user["id"],
                created_at=now,
            )
        db.execute(
            "INSERT INTO chat_sessions("
            "id,user_id,note_id,messages_json,created_at,updated_at"
            ") VALUES(?,?,?,?,?,?)",
            ("chain-chat", user["id"], "child-note", "[]", now, now),
        )
        memory.add_context(
            user["id"],
            "linked summary",
            source_note_id="child-note",
        )
        response = self.client.delete(
            "/notes/root-note",
            headers={"Authorization": f"Bearer {login['token']}"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(db.fetchone(
            "SELECT id FROM chat_sessions WHERE id='chain-chat'"
        ))
        self.assertIsNone(db.fetchone(
            "SELECT id FROM user_memories WHERE source_note_id='child-note'"
        ))

    def test_deletion_write_fence_blocks_followup_records(self):
        user = self._create_user()
        content_retention.request_account_deletion(user["id"])
        with self.assertRaises(ValueError):
            memory.add_memory(user["id"], "context", "must not persist")
        with self.assertRaises(ValueError):
            api._insert_growth_record(
                user_id=user["id"],
                note_id=None,
                domain="美食",
                score=80,
                grade="A",
                action="late_write",
            )
        with self.assertRaises(Exception):
            api._idempotency.claim_and_charge(
                user_id=user["id"],
                operation="diagnose",
                request_id="late-request",
                payload={"safe": True},
            )
        with self.assertRaises(ValueError):
            billing.topup_credits(user["id"], 10)
        with self.assertRaises(ValueError):
            billing.grant_credits(user["id"], 10)
        with self.assertRaises(Exception):
            billing.check_and_deduct(user["id"], "generate")
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM growth_records WHERE user_id=?",
                (user["id"],),
            )["c"],
            0,
        )

    def test_account_deletion_waits_for_running_charge_before_final_export(self):
        user = self._create_user()
        billing.upgrade_subscription(user["id"], "pro")
        login = self._login()
        context = api._idempotency.claim_and_charge(
            user_id=user["id"],
            operation="generate",
            request_id="delete-race-paid-request",
            payload={"safe": True},
        )
        blocked = self.client.request(
            "DELETE",
            "/account",
            headers={"Authorization": f"Bearer {login['token']}"},
            json={"password": "Strong!Pass234"},
        )
        self.assertEqual(blocked.status_code, 409)
        self.assertNotIn("final_export", blocked.json())
        self.assertIsNone(
            db.fetchone(
                "SELECT deletion_requested_at FROM users WHERE id=?",
                (user["id"],),
            )["deletion_requested_at"]
        )

        self.assertTrue(
            api._idempotency.mark_failed_and_refund(
                context,
                failure_code="request_failed",
            )
        )
        deleted = self.client.request(
            "DELETE",
            "/account",
            headers={"Authorization": f"Bearer {login['token']}"},
            json={"password": "Strong!Pass234"},
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertIn("final_export", deleted.json())
        before = {
            "usage": db.fetchone(
                "SELECT source,credits_used FROM usage_records WHERE id=?",
                (context["charge"]["usage_id"],),
            ),
            "subscription": db.fetchone(
                "SELECT used_monthly_credits FROM subscriptions WHERE user_id=? "
                "AND is_active=1",
                (user["id"],),
            ),
        }
        self.assertFalse(
            api._idempotency.mark_failed_and_refund(
                context,
                failure_code="request_failed",
            )
        )
        billing.record_model_usage(
            "kimi",
            "kimi-k2.6",
            tokens_in=100,
            tokens_out=20,
        )
        after = {
            "usage": db.fetchone(
                "SELECT source,credits_used FROM usage_records WHERE id=?",
                (context["charge"]["usage_id"],),
            ),
            "subscription": db.fetchone(
                "SELECT used_monthly_credits FROM subscriptions WHERE user_id=? "
                "AND is_active=1",
                (user["id"],),
            ),
        }
        self.assertEqual(dict(before["usage"]), dict(after["usage"]))
        self.assertEqual(
            dict(before["subscription"]),
            dict(after["subscription"]),
        )
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM model_usage_records "
                "WHERE usage_record_id=?",
                (context["charge"]["usage_id"],),
            )["c"],
            0,
        )

    def test_expired_request_lease_cannot_starve_account_deletion(self):
        user = self._create_user()
        billing.upgrade_subscription(user["id"], "pro")
        login = self._login()
        context = api._idempotency.claim_and_charge(
            user_id=user["id"],
            operation="generate",
            request_id="expired-delete-request",
            payload={"safe": True},
        )
        db.execute(
            "UPDATE idempotency_requests SET lease_expires_at=? WHERE id=?",
            ("2000-01-01T00:00:00+00:00", context["request_id"]),
        )
        deleted = self.client.request(
            "DELETE",
            "/account",
            headers={"Authorization": f"Bearer {login['token']}"},
            json={"password": "Strong!Pass234"},
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertIn("final_export", deleted.json())
        settled = db.fetchone(
            "SELECT status,refund_applied,failure_code "
            "FROM idempotency_requests WHERE id=?",
            (context["request_id"],),
        )
        self.assertEqual(settled["status"], "failed")
        self.assertEqual(settled["refund_applied"], 1)
        self.assertEqual(settled["failure_code"], "lease_expired")
        before = dict(db.fetchone(
            "SELECT used_monthly_credits FROM subscriptions "
            "WHERE user_id=? AND is_active=1",
            (user["id"],),
        ))
        self.assertEqual(before["used_monthly_credits"], 0)
        self.assertFalse(api._idempotency.mark_completed(context))
        self.assertFalse(
            api._idempotency.mark_failed_and_refund(
                context,
                failure_code="request_failed",
            )
        )
        after = dict(db.fetchone(
            "SELECT used_monthly_credits FROM subscriptions "
            "WHERE user_id=? AND is_active=1",
            (user["id"],),
        ))
        self.assertEqual(before, after)

    def test_expired_linked_request_requires_durable_operation_terminal(self):
        user = self._create_user()
        billing.upgrade_subscription(user["id"], "pro")
        login = self._login()
        admitted = api._idempotency.admit_operation(
            user_id=user["id"],
            operation="generate",
            request_id="expired-linked-delete-request",
            payload={"safe": True},
        )
        request = db.fetchone(
            "SELECT i.id FROM idempotency_requests i "
            "JOIN ai_operation_admissions a ON a.idempotency_request_id=i.id "
            "WHERE a.operation_id=?",
            (admitted["operation_id"],),
        )
        db.execute(
            "UPDATE idempotency_requests SET lease_expires_at=? WHERE id=?",
            ("2000-01-01T00:00:00+00:00", request["id"]),
        )
        blocked = self.client.request(
            "DELETE",
            "/account",
            headers={"Authorization": f"Bearer {login['token']}"},
            json={"password": "Strong!Pass234"},
        )
        self.assertEqual(blocked.status_code, 409)
        self.assertTrue(
            ai_operations.cancel_queued_operation(admitted["operation_id"])
        )
        deleted = self.client.request(
            "DELETE",
            "/account",
            headers={"Authorization": f"Bearer {login['token']}"},
            json={"password": "Strong!Pass234"},
        )
        self.assertEqual(deleted.status_code, 200)
        settled = db.fetchone(
            "SELECT status,refund_applied,failure_code "
            "FROM idempotency_requests WHERE id=?",
            (request["id"],),
        )
        self.assertEqual(settled["status"], "failed")
        self.assertEqual(settled["refund_applied"], 1)
        self.assertEqual(settled["failure_code"], "lease_expired")

    def test_admin_user_writes_share_account_deletion_fence(self):
        user = self._create_user()
        billing.upgrade_subscription(user["id"], "pro")
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "UPDATE subscriptions SET used_monthly_credits=8 "
            "WHERE user_id=? AND is_active=1",
            (user["id"],),
        )
        db.execute(
            "INSERT INTO tracked_notes("
            "id,user_id,xhs_url,submitted_at,status"
            ") VALUES(?,?,?,?,?)",
            (
                "admin-fence-note",
                user["id"],
                "https://www.xiaohongshu.com/explore/safe-test-note",
                now,
                "pending",
            ),
        )
        content_retention.request_account_deletion(user["id"])

        async def reset_quota():
            return await admin_server.admin_user_adjust(
                user["id"],
                admin_server.UserAdjustInput(action="reset_quota"),
                admin={"id": "review-admin"},
            )

        async def trigger_tracking():
            return await admin_server.admin_trigger_check(
                "admin-fence-note",
                admin={"id": "review-admin"},
            )

        for mutation in (reset_quota, trigger_tracking):
            with self.subTest(mutation=mutation.__name__):
                with self.assertRaises(HTTPException) as caught:
                    asyncio.run(mutation())
                self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(
            db.fetchone(
                "SELECT used_monthly_credits FROM subscriptions "
                "WHERE user_id=? AND is_active=1",
                (user["id"],),
            )["used_monthly_credits"],
            8,
        )
        self.assertEqual(
            db.fetchone(
                "SELECT status FROM tracked_notes WHERE id=?",
                ("admin-fence-note",),
            )["status"],
            "account_deletion_pending",
        )

    def test_generalized_reasoning_aliases_are_removed(self):
        generalized = api._public_diagnosis_value({
            "assistant_analysis": "hidden",
            "modelReasoning": "hidden",
            "raw": "hidden",
            "safe-score": 91,
        })
        self.assertEqual(generalized, {"safe-score": 91})
        self.assertEqual(
            api._sanitize_chat_persisted_value({
                "assistantAnalysis": "hidden",
                "raw-provider-output": "hidden",
                "answer": "safe",
            }),
            {"answer": "safe"},
        )

    def test_reasoning_alias_matrix_and_legitimate_business_fields(self):
        aliases = {
            "ScratchPad": "hidden",
            "scratchPad": "hidden",
            "scratch_pad": "hidden",
            "CoT": "hidden",
            "COT": "hidden",
            "co_t": "hidden",
            "chainOfThoughts": "hidden",
            "ScratchPads": "hidden",
            "CoTTrace": "hidden",
            "CoTDetails": "hidden",
            "answer": "safe",
            "fact_enrichment": {
                "provider": "approved-source",
                "raw_title": "business title",
            },
            "supplement_prompts": [{"prompt": "需要补充商户名"}],
        }
        expected = {
            "answer": "safe",
            "fact_enrichment": {
                "provider": "approved-source",
                "raw_title": "business title",
            },
            "supplement_prompts": [{"prompt": "需要补充商户名"}],
        }
        self.assertEqual(api._public_diagnosis_value(aliases), expected)
        self.assertEqual(api._sanitize_chat_persisted_value(aliases), expected)

    def test_prefixed_concatenated_and_plural_reasoning_aliases_never_persist(self):
        reasoning_aliases = {
            "assistantCoTTrace": "hidden",
            "preCoT": "hidden",
            "CoTs": "hidden",
            "COTs": "hidden",
            "assistantScratchPad": "hidden",
            "assistantScratchPads": "hidden",
            "modelScratchPadTrace": "hidden",
            "thoughtprocess": "hidden",
            "hiddenthought": "hidden",
            "innerthoughts": "hidden",
            "reasonings": "hidden",
            "thinkings": "hidden",
            "analyses": "hidden",
        }
        payload = {
            **reasoning_aliases,
            "answer": "safe",
            "nested": [{**reasoning_aliases, "content": "safe nested"}],
            "fact_enrichment": {
                "provider": "approved-source",
                "raw_title": "business title",
            },
            "supplement_prompts": [{"prompt": "需要补充商户名"}],
            "cotton_material": "棉质",
            "cottage_style": "乡村风",
            "mascots": ["品牌吉祥物"],
            "apricot_color": "杏色",
            "mascots_metadata": "公开描述",
        }
        expected = {
            "answer": "safe",
            "nested": [{"content": "safe nested"}],
            "fact_enrichment": {
                "provider": "approved-source",
                "raw_title": "business title",
            },
            "supplement_prompts": [{"prompt": "需要补充商户名"}],
            "cotton_material": "棉质",
            "cottage_style": "乡村风",
            "mascots": ["品牌吉祥物"],
            "apricot_color": "杏色",
            "mascots_metadata": "公开描述",
        }
        self.assertEqual(api._public_diagnosis_value(payload), expected)
        self.assertEqual(api._sanitize_chat_persisted_value(payload), expected)

        user = self._create_user()
        session_id = "reasoning-family-persistence"
        api._chat_sessions[session_id] = {
            "user_id": user["id"],
            "domain": "美食",
            "messages": [{"role": "assistant", "content": "safe", **reasoning_aliases}],
            "generate_context": {
                "nested": [{**reasoning_aliases, "content": "safe nested"}],
            },
        }
        self.assertTrue(api._persist_chat_session(session_id))
        row = db.fetchone(
            "SELECT messages_json,generate_ctx_json FROM chat_sessions WHERE id=?",
            (session_id,),
        )
        stored_messages = json.loads(row["messages_json"])
        stored_context = json.loads(row["generate_ctx_json"])
        self.assertEqual(stored_messages, [])
        self.assertEqual(stored_context, {})
        api._chat_sessions.pop(session_id, None)
        restored = api._load_chat_session_from_db(session_id)
        self.assertEqual(
            restored["messages"],
            [],
        )
        self.assertEqual(
            restored["generate_context"],
            {},
        )

    def test_structural_internal_envelopes_never_persist_reload_or_export(self):
        reasoning_aliases = {
            "cots_trace": "hidden",
            "cots-trace": "hidden",
            "CotsTrace": "hidden",
            "assistantCotsTrace": "hidden",
            "postCotsTrace": "hidden",
            "cotsMetadata": "hidden",
            "agentcottrace": "hidden",
            "responsecotdetails": "hidden",
            "llmcotcontent": "hidden",
            "tracecotdelta": "hidden",
            "agentcot": "hidden",
            "postcots": "hidden",
            "llmcot": "hidden",
        }
        public_payload = {
            **reasoning_aliases,
            "systemEnvelope": {"content": "hidden"},
            "systemenvelope": {"content": "hidden"},
            "provider": "hidden",
            "providerEnvelope": {"content": "hidden"},
            "assistantProviderResponse": {"content": "hidden"},
            "providerenvelope": {"content": "hidden"},
            "assistantproviderresponse": {"content": "hidden"},
            "internalpayload": {"content": "hidden"},
            "developerprompt": {"content": "hidden"},
            "history": [{"role": "system", "content": "hidden"}],
            "answer": "safe",
            "fact_enrichment": {
                "provider": "approved-source",
                "raw_title": "business title",
            },
            "supplement_prompts": [{"prompt": "需要补充商户名"}],
            "cotton_material": "棉质",
            "cottage_style": "乡村风",
            "mascots": ["品牌吉祥物"],
        }
        expected_public = {
            "answer": "safe",
            "history": [],
            "fact_enrichment": {
                "provider": "approved-source",
                "raw_title": "business title",
            },
            "supplement_prompts": [{"prompt": "需要补充商户名"}],
            "cotton_material": "棉质",
            "cottage_style": "乡村风",
            "mascots": ["品牌吉祥物"],
        }
        self.assertEqual(
            api._public_diagnosis_value(public_payload),
            expected_public,
        )
        self.assertEqual(
            api._sanitize_chat_persisted_value(public_payload),
            expected_public,
        )
        invalid_business_types = {
            "fact_enrichment": {
                "provider": {"systemEnvelope": "hidden"},
                "raw_title": ["hidden"],
            },
            "supplement_prompts": [
                {"prompt": {"providerEnvelope": "hidden"}},
            ],
        }
        self.assertEqual(
            api._public_diagnosis_value(invalid_business_types),
            {
                "fact_enrichment": {},
                "supplement_prompts": [{}],
            },
        )
        self.assertEqual(
            api._sanitize_chat_persisted_value(invalid_business_types),
            {
                "fact_enrichment": {},
                "supplement_prompts": [{}],
            },
        )

        user = self._create_user()
        session_id = "structural-internal-persistence"
        api._chat_sessions[session_id] = {
            "user_id": user["id"],
            "domain": "美食",
            "messages": [
                {"role": "system", "content": "hidden system prompt"},
                {
                    "role": "user",
                    "content": "safe user",
                    **reasoning_aliases,
                },
                {
                    "role": "assistant",
                    "content": "safe assistant",
                    "systemEnvelope": "hidden",
                },
            ],
            "generate_context": {
                **reasoning_aliases,
                "systemEnvelope": "hidden",
                "providerEnvelope": "hidden",
                "history": [{"role": "system", "content": "hidden"}],
                "answer": "safe context",
                "fact_enrichment": {
                    "provider": "approved-source",
                    "raw_title": "business title",
                },
                "supplement_prompts": [{"prompt": "需要补充商户名"}],
                "cotton_material": "棉质",
            },
            "user_prefs": {
                **reasoning_aliases,
                "systemEnvelope": "hidden",
                "history": [{"role": "system", "content": "hidden"}],
                "preference": "safe preference",
                "mascots": ["品牌吉祥物"],
            },
        }
        self.assertTrue(api._persist_chat_session(session_id))
        row = db.fetchone(
            "SELECT messages_json,user_prefs_json,generate_ctx_json "
            "FROM chat_sessions WHERE id=?",
            (session_id,),
        )
        expected_messages = []
        expected_preferences = {}
        expected_context = {
            "fact_enrichment": {
                "provider": "approved-source",
                "raw_title": "business title",
            },
            "supplement_prompts": [{"prompt": "需要补充商户名"}],
            "cotton_material": "棉质",
        }
        self.assertEqual(json.loads(row["messages_json"]), expected_messages)
        self.assertEqual(
            json.loads(row["user_prefs_json"]),
            expected_preferences,
        )
        self.assertEqual(
            json.loads(row["generate_ctx_json"]),
            expected_context,
        )

        api._chat_sessions.pop(session_id, None)
        restored = api._load_chat_session_from_db(session_id)
        self.assertEqual(restored["messages"], expected_messages)
        self.assertEqual(restored["user_prefs"], expected_preferences)
        self.assertEqual(restored["generate_context"], expected_context)

        exported = api._account_export_payload(user)
        exported_chat = next(
            item
            for item in exported["archives"]["chat_sessions"]
            if item["id"] == session_id
        )
        self.assertEqual(exported_chat["messages"], expected_messages)
        self.assertEqual(
            exported_chat["user_preferences"],
            expected_preferences,
        )
        self.assertEqual(
            exported_chat["generation_context"],
            expected_context,
        )

    def test_unlisted_compact_and_discriminator_envelopes_fail_closed(self):
        compact_survivors = {
            "privatecot": "hidden",
            "rawcot": "hidden",
            "debugcot": "hidden",
            "vendorcot": "hidden",
            "completioncot": "hidden",
            "cotlog": "hidden",
            "cotscontext": "hidden",
            "assistantcotsteps": "hidden",
            "functionCall": "hidden",
            "function_call": "hidden",
            "toolCall": "hidden",
            "tool_call": "hidden",
            "systemcontext": "hidden",
            "providercontext": "hidden",
            "internalcontext": "hidden",
            "developercontext": "hidden",
            "providerdata": "hidden",
            "rawdata": "hidden",
        }
        payload = {
            **compact_survivors,
            "history": [
                {"Role": "system", "content": "hidden"},
                {"ROLE": "developer", "content": "hidden"},
                {"messageRole": "tool", "content": "hidden"},
                {"type": "reasoning", "content": "hidden"},
            ],
            "grade": "A",
            "answer": "safe",
            "fact_enrichment": {
                "provider": "approved-source",
                "raw_title": "business title",
            },
            "supplement_prompts": [{"prompt": "需要补充商户名"}],
            "cotton_material": "棉质",
            "cottage_style": "乡村风",
            "mascots": ["品牌吉祥物"],
            "apricot_color": "杏色",
        }
        expected = {
            "history": [],
            "grade": "A",
            "answer": "safe",
            "fact_enrichment": {
                "provider": "approved-source",
                "raw_title": "business title",
            },
            "supplement_prompts": [{"prompt": "需要补充商户名"}],
            "cotton_material": "棉质",
            "cottage_style": "乡村风",
            "mascots": ["品牌吉祥物"],
            "apricot_color": "杏色",
        }
        self.assertEqual(api._public_diagnosis_value(payload), expected)
        self.assertEqual(api._sanitize_chat_persisted_value(payload), expected)
        self.assertEqual(
            api._sanitize_persisted_diagnosis(payload),
            {
                "grade": "A",
                "fact_enrichment": {
                    "provider": "approved-source",
                    "raw_title": "business title",
                },
                "supplement_prompts": [{"prompt": "需要补充商户名"}],
            },
        )
        self.assertEqual(
            api._sanitize_chat_messages([
                {
                    "role": "assistant",
                    "type": "reasoning",
                    "content": "hidden",
                },
                {
                    "role": "assistant",
                    "reasoning": True,
                    "content": "hidden",
                },
                {"role": "assistant", "content": "safe"},
            ]),
            [{"role": "assistant", "content": "safe"}],
        )

    def test_schema_bound_chat_columns_and_export_reject_unlisted_internal_data(self):
        user = self._create_user()
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO user_learn("
            "user_id,pref_key,pref_value,confidence,update_count,updated_at"
            ") VALUES(?,?,?,?,?,?)",
            (user["id"], "tone", "接地气风格", 0.8, 2, now),
        )
        db.execute(
            "INSERT INTO user_learn("
            "user_id,pref_key,pref_value,confidence,update_count,updated_at"
            ") VALUES(?,?,?,?,?,?)",
            (user["id"], "rawcot", "hidden", 0.8, 2, now),
        )
        session_id = "schema-bound-internal-persistence"
        api._chat_sessions[session_id] = {
            "user_id": user["id"],
            "domain": "美食",
            "messages": [
                {
                    "role": "assistant",
                    "type": "reasoning",
                    "content": "hidden typed reasoning",
                },
                {
                    "role": "assistant",
                    "providercontext": "hidden",
                    "content": "hidden marked content",
                },
                {"role": "assistant", "content": "safe assistant"},
            ],
            "user_prefs": {
                "tone": "接地气风格",
                "privatecot": "hidden",
                "providercontext": "hidden",
                "mascots": ["hidden untyped preference"],
            },
            "generate_context": {
                "current_grade": "良好",
                "fact_enrichment": {
                    "provider": "approved-source",
                    "raw_title": "business title",
                },
                "supplement_prompts": [{"prompt": "需要补充商户名"}],
                "cotton_material": "棉质",
                "privatecot": "hidden",
                "providercontext": "hidden",
                "rawdata": "hidden",
                "history": [
                    {"Role": "system", "content": "hidden"},
                ],
                "typed": {"type": "reasoning", "content": "hidden"},
            },
        }
        self.assertTrue(api._persist_chat_session(session_id))
        row = db.fetchone(
            "SELECT messages_json,user_prefs_json,generate_ctx_json "
            "FROM chat_sessions WHERE id=?",
            (session_id,),
        )
        expected_messages = [
            {"role": "assistant", "content": "safe assistant"},
        ]
        expected_preferences = {"tone": "接地气风格"}
        # H9 makes the generation-context root an explicit schema. The
        # unapproved discriminator-bearing ``typed`` member therefore rejects
        # the whole marked mapping instead of preserving its public-looking
        # siblings.
        expected_context = {}
        self.assertEqual(json.loads(row["messages_json"]), expected_messages)
        self.assertEqual(
            json.loads(row["user_prefs_json"]),
            expected_preferences,
        )
        self.assertEqual(
            json.loads(row["generate_ctx_json"]),
            expected_context,
        )

        api._chat_sessions.pop(session_id, None)
        restored = api._load_chat_session_from_db(session_id)
        self.assertEqual(restored["messages"], expected_messages)
        self.assertEqual(restored["user_prefs"], expected_preferences)
        self.assertEqual(restored["generate_context"], expected_context)

        exported = api._account_export_payload(user)
        exported_chat = next(
            item
            for item in exported["archives"]["chat_sessions"]
            if item["id"] == session_id
        )
        self.assertEqual(exported_chat["messages"], expected_messages)
        self.assertEqual(
            exported_chat["user_preferences"],
            expected_preferences,
        )
        self.assertEqual(
            exported_chat["generation_context"],
            expected_context,
        )
        self.assertEqual(
            exported["archives"]["learned_preferences"],
            [{
                "pref_key": "tone",
                "pref_value": "接地气风格",
                "confidence": 0.8,
                "update_count": 2,
                "updated_at": now,
            }],
        )

    def test_recursive_public_schemas_and_compound_discriminators_fail_closed(self):
        sentinel = "R8_SYNTHETIC_INTERNAL_SENTINEL"
        nested_internal_fields = {
            "apiKey": sentinel,
            "bearer": sentinel,
            "completionData": sentinel,
            "debugTrace": sentinel,
            "hiddenState": sentinel,
            "instructions": sentinel,
            "modelContext": sentinel,
            "password": sentinel,
            "requestBody": sentinel,
            "responseBody": sentinel,
            "sessionId": sentinel,
        }
        diagnosis = api._sanitize_persisted_diagnosis({
            "grade": "良好",
            "features": {
                "body_len": 280.0,
                "mascotcottrace": sentinel,
                "apiKey": sentinel,
            },
            "model_used": {"payload": sentinel},
            "ai_diagnosis": {"channel": "analysis", "content": sentinel},
            "suggested_titles": [
                "公开标题",
                {"type": "tool_call", "content": sentinel},
            ],
            "suggested_plans": [
                {
                    "title": "公开方案",
                    "body": "公开正文",
                    "score": 82.0,
                    "quality_issues": ["公开提示"],
                },
                {
                    "title": "hidden",
                    "body": sentinel,
                    "type": "function_call",
                },
            ],
            "constraint_contract": {
                "items": ["不改标题"],
                "hard_rules": {
                    "keep_title": True,
                    "keep_cover": False,
                    "publish_time": "",
                    **nested_internal_fields,
                },
                "goals": {
                    "follow_growth": True,
                    "commerce_conversion": False,
                    "interaction_rate": False,
                    "exposure": False,
                },
                **nested_internal_fields,
            },
            "fact_enrichment": {
                "enabled": True,
                "provider": "approved-source",
                "raw_title": "business title",
                "mascotcottrace": sentinel,
                "apricot-cotdetails": sentinel,
                "cottonCotTrace": sentinel,
                "cottage_cot_details": sentinel,
                "response_metadata": sentinel,
                **nested_internal_fields,
            },
        })
        self.assertEqual(
            diagnosis,
            {
                "grade": "良好",
                "features": {"body_len": 280.0},
                "suggested_titles": ["公开标题"],
                "suggested_plans": [{
                    "title": "公开方案",
                    "body": "公开正文",
                    "score": 82.0,
                    "quality_issues": ["公开提示"],
                }],
                "constraint_contract": {
                    "items": ["不改标题"],
                    "hard_rules": {
                        "keep_title": True,
                        "keep_cover": False,
                        "publish_time": "",
                    },
                    "goals": {
                        "follow_growth": True,
                        "commerce_conversion": False,
                        "interaction_rate": False,
                        "exposure": False,
                    },
                },
                "fact_enrichment": {
                    "enabled": True,
                    "provider": "approved-source",
                    "raw_title": "business title",
                },
            },
        )
        generic = {
            "cotton_material": "棉质",
            "cottage_style": "乡村风",
            "mascots_metadata": "公开描述",
            "apricot_color": "杏色",
            "mascotcottrace": sentinel,
            "apricot-cotdetails": sentinel,
            "records": [
                {"type": "tool_result", "content": sentinel},
            ],
        }
        expected_generic = {
            "cotton_material": "棉质",
            "cottage_style": "乡村风",
            "mascots_metadata": "公开描述",
            "apricot_color": "杏色",
            "records": [],
        }
        self.assertEqual(api._public_diagnosis_value(generic), expected_generic)
        self.assertEqual(
            api._sanitize_chat_persisted_value(generic),
            expected_generic,
        )
        self.assertEqual(
            api._sanitize_chat_messages([
                {
                    "role": "assistant",
                    "type": "function_call",
                    "content": sentinel,
                },
                {
                    "role": "assistant",
                    "type": "tool_call",
                    "content": sentinel,
                },
                {
                    "role": "assistant",
                    "channel": "analysis",
                    "content": sentinel,
                },
                {"role": "assistant", "content": "safe"},
            ]),
            [{"role": "assistant", "content": "safe"}],
        )
        compound_values = {
            "function_call",
            "function-call",
            "FunctionCall",
            "tool_call",
            "tool.result",
            "ToolResult",
            "system_message",
            "SystemMessage",
            "developerInstruction",
            "providerContext",
            "internal_event",
            "reasoning_trace",
        }
        discriminator_keys = {
            "type",
            "Type",
            "messageType",
            "output_type",
            "typeLabel",
            "kind",
            "payloadKind",
            "messageRole",
        }
        for discriminator_key in discriminator_keys:
            for discriminator_value in compound_values:
                with self.subTest(
                    discriminator_key=discriminator_key,
                    discriminator_value=discriminator_value,
                ):
                    record = {
                        "role": "assistant",
                        "content": sentinel,
                        discriminator_key: discriminator_value,
                    }
                    self.assertNotIn(
                        sentinel,
                        json.dumps(
                            api._public_diagnosis_value(
                                {"records": [record]}
                            ),
                            ensure_ascii=False,
                        ),
                    )
                    self.assertNotIn(
                        sentinel,
                        json.dumps(
                            api._sanitize_persisted_diagnosis(
                                {"suggested_plans": [record]}
                            ),
                            ensure_ascii=False,
                        ),
                    )
                    self.assertEqual(
                        api._sanitize_chat_messages([record]),
                        [],
                    )

    def test_recursive_schema_survivors_never_reach_raw_reload_or_export(self):
        sentinel = "R8_SYNTHETIC_INTERNAL_SENTINEL"
        user = self._create_user(username="recursive-schema-user")
        session_id = "recursive-schema-persistence"
        constraint_contract = {
            "items": ["不改标题"],
            "hard_rules": {
                "keep_title": True,
                "keep_cover": False,
                "publish_time": "",
                "password": sentinel,
            },
            "goals": {
                "follow_growth": True,
                "commerce_conversion": False,
                "interaction_rate": False,
                "exposure": False,
            },
            "apiKey": sentinel,
        }
        api._chat_sessions[session_id] = {
            "user_id": user["id"],
            "domain": "美食",
            "messages": [
                {
                    "role": "assistant",
                    "type": "tool_call",
                    "content": sentinel,
                },
                {
                    "role": "assistant",
                    "channel": "analysis",
                    "content": sentinel,
                },
                {"role": "assistant", "content": "safe assistant"},
            ],
            "generate_context": {
                "current_grade": "良好",
                "constraint_contract": constraint_contract,
                "fact_enrichment": {
                    "enabled": True,
                    "provider": "approved-source",
                    "raw_title": "business title",
                    "mascotcottrace": sentinel,
                    "response_metadata": sentinel,
                    "apiKey": sentinel,
                },
            },
        }
        self.assertTrue(api._persist_chat_session(session_id))
        raw_chat = db.fetchone(
            "SELECT messages_json,generate_ctx_json FROM chat_sessions WHERE id=?",
            (session_id,),
        )
        expected_messages = [{"role": "assistant", "content": "safe assistant"}]
        expected_context = {
            "current_grade": "良好",
            "constraint_contract": {
                "items": ["不改标题"],
                "hard_rules": {
                    "keep_title": True,
                    "keep_cover": False,
                    "publish_time": "",
                },
                "goals": {
                    "follow_growth": True,
                    "commerce_conversion": False,
                    "interaction_rate": False,
                    "exposure": False,
                },
            },
            "fact_enrichment": {
                "enabled": True,
                "provider": "approved-source",
                "raw_title": "business title",
            },
        }
        self.assertEqual(json.loads(raw_chat["messages_json"]), expected_messages)
        self.assertEqual(json.loads(raw_chat["generate_ctx_json"]), expected_context)
        self.assertNotIn(sentinel, raw_chat["messages_json"])
        self.assertNotIn(sentinel, raw_chat["generate_ctx_json"])

        api._chat_sessions.pop(session_id, None)
        restored = api._load_chat_session_from_db(session_id)
        self.assertEqual(restored["messages"], expected_messages)
        self.assertEqual(restored["generate_context"], expected_context)

        diagnosis_id = "recursive-schema-diagnosis"
        created_at = datetime.now(timezone.utc).isoformat()
        diagnosis_payload = api._sanitize_persisted_diagnosis({
            "grade": "良好",
            "features": {
                "body_len": 280.0,
                "mascotcottrace": sentinel,
                "apiKey": sentinel,
            },
            "suggested_plans": [{
                "title": "hidden",
                "body": sentinel,
                "type": "system_message",
            }],
        })
        api._insert_content_with_retention(
            "INSERT INTO saved_diagnoses("
            "id,user_id,note_title,domain,ces_percentile,composite_score,"
            "grade,diagnosis_json,created_at"
            ") VALUES(?,?,?,?,?,?,?,?,?)",
            (
                diagnosis_id,
                user["id"],
                "合成诊断",
                "美食",
                80.0,
                80.0,
                "良好",
                json.dumps(diagnosis_payload, ensure_ascii=False),
                created_at,
            ),
            "diagnosis",
            diagnosis_id,
            user["id"],
            created_at=created_at,
        )
        raw_diagnosis = db.fetchone(
            "SELECT diagnosis_json FROM saved_diagnoses WHERE id=?",
            (diagnosis_id,),
        )["diagnosis_json"]
        self.assertNotIn(sentinel, raw_diagnosis)
        reloaded_diagnosis = asyncio.run(
            api.get_diagnosis(diagnosis_id, user)
        )
        self.assertNotIn(
            sentinel,
            json.dumps(reloaded_diagnosis, ensure_ascii=False),
        )

        exported = api._account_export_payload(user)
        self.assertNotIn(
            sentinel,
            json.dumps(exported, ensure_ascii=False),
        )
        exported_chat = next(
            item
            for item in exported["archives"]["chat_sessions"]
            if item["id"] == session_id
        )
        self.assertEqual(exported_chat["messages"], expected_messages)
        self.assertEqual(
            exported_chat["generation_context"],
            expected_context,
        )

    def test_per_schema_discriminators_and_expert_records_fail_closed(self):
        sentinel = "R9_SYNTHETIC_INTERNAL_SENTINEL"
        discriminator_keys = {
            "type",
            "messageType",
            "typeTag",
            "role",
            "messageRole",
            "roleName",
            "kind",
            "eventKind",
            "kindCode",
            "record_type",
            "messageTypeLabel",
            "payloadRoleMetadata",
            "inputKindEnvelope",
        }
        discriminator_values = {
            "debug_trace",
            "hidden_state",
            "completion_data",
            "model_context",
            "request_body",
            "response_body",
            "session_state",
            "api_key",
            "password",
            "bearer",
            "audit_log",
            "trace_event",
            "diagnostic_context",
            "telemetry_event",
        }
        for discriminator_key in discriminator_keys:
            for discriminator_value in discriminator_values:
                with self.subTest(
                    discriminator_key=discriminator_key,
                    discriminator_value=discriminator_value,
                ):
                    record = {
                        "title": "internal",
                        "body": sentinel,
                        discriminator_key: discriminator_value,
                    }
                    projections = (
                        api._public_diagnosis_value({"records": [record]}),
                        api._sanitize_chat_persisted_value({"records": [record]}),
                        api._sanitize_persisted_diagnosis({
                            "suggested_plans": [record],
                        }),
                        api._sanitize_chat_generate_context({
                            "pending_plan_options": [record],
                        }),
                        api._sanitize_chat_generate_context({
                            "supplement_prompts": [{
                                "prompt": sentinel,
                                discriminator_key: discriminator_value,
                            }],
                        }),
                    )
                    for projected in projections:
                        self.assertNotIn(
                            sentinel,
                            json.dumps(projected, ensure_ascii=False),
                        )

        root_projections = (
            api._sanitize_persisted_diagnosis({
                "type": "debug_trace",
                "ai_diagnosis": sentinel,
            }),
            api._sanitize_chat_generate_context({
                "messageTypeLabel": "hidden_state",
                "fact_context": sentinel,
            }),
            api._sanitize_chat_preferences({
                "payloadRoleMetadata": "completion_data",
                "tone": sentinel,
            }),
        )
        for projected in root_projections:
            self.assertNotIn(
                sentinel,
                json.dumps(projected, ensure_ascii=False),
            )

        expert_projection = api._public_expert_opinions([
            {
                "role": "system_message",
                "opinion": sentinel,
            },
            {
                "role": "专家",
                "type": "tool_result",
                "opinion": sentinel,
            },
            {
                "role": "专家",
                "opinion": "公开意见",
                "evidence": [{
                    "kind": "developer_message",
                    "text": sentinel,
                }],
            },
            {
                "role": "内容专家",
                "opinion": "正常公开意见",
                "evidence": [{
                    "source_type": "v04_feature",
                    "source_key": "body_len",
                    "text": "正常公开证据",
                }],
            },
        ])
        serialized_experts = json.dumps(
            expert_projection,
            ensure_ascii=False,
        )
        self.assertNotIn(sentinel, serialized_experts)
        self.assertIn("正常公开意见", serialized_experts)
        self.assertIn("正常公开证据", serialized_experts)

    def test_r8_survivors_and_real_analyze_shape_never_cross_lifecycle(self):
        root_sentinel = "R9_ROOT_MAPPING_SENTINEL"
        expert_sentinel = "R9_EXPERT_MAPPING_SENTINEL"
        preference_sentinel = "R9_PREFERENCE_MAPPING_SENTINEL"
        user = self._create_user(username="r9-lifecycle-user")

        root_session_id = "r9-root-session"
        api._chat_sessions[root_session_id] = {
            "user_id": user["id"],
            "domain": "美食",
            "messages": [
                {
                    "role": "assistant",
                    "type": "debug_trace",
                    "content": root_sentinel,
                },
                {"role": "assistant", "content": "safe assistant"},
            ],
            "user_prefs": {
                "messageTypeLabel": "hidden_state",
                "tone": preference_sentinel,
            },
            "generate_context": {
                "inputKindEnvelope": "completion_data",
                "fact_context": root_sentinel,
            },
        }
        self.assertTrue(api._persist_chat_session(root_session_id))

        expert_session_id = "r9-expert-session"
        api._chat_sessions[expert_session_id] = {
            "user_id": user["id"],
            "domain": "美食",
            "messages": [
                {"role": "assistant", "content": "safe expert session"},
            ],
            "generate_context": {
                "current_grade": "良好",
                "expert_opinions": [{
                    "role": "专家",
                    "type": "tool_result",
                    "opinion": expert_sentinel,
                }],
                "pending_plan_options": [{
                    "id": "A",
                    "body": expert_sentinel,
                    "messageTypeLabel": "telemetry_event",
                }],
                "supplement_prompts": [{
                    "prompt": expert_sentinel,
                    "payloadRoleMetadata": "audit_log",
                }],
            },
        }
        self.assertTrue(api._persist_chat_session(expert_session_id))

        chat_rows = db.fetchall(
            "SELECT id,messages_json,user_prefs_json,generate_ctx_json "
            "FROM chat_sessions WHERE id IN (?,?) ORDER BY id",
            (root_session_id, expert_session_id),
        )
        raw_chat = json.dumps(
            [dict(row) for row in chat_rows],
            ensure_ascii=False,
        )
        for sentinel in (
            root_sentinel,
            expert_sentinel,
            preference_sentinel,
        ):
            self.assertNotIn(sentinel, raw_chat)

        api._chat_sessions.pop(root_session_id, None)
        api._chat_sessions.pop(expert_session_id, None)
        restored_chat = json.dumps(
            [
                api._load_chat_session_from_db(root_session_id),
                api._load_chat_session_from_db(expert_session_id),
            ],
            ensure_ascii=False,
        )
        for sentinel in (
            root_sentinel,
            expert_sentinel,
            preference_sentinel,
        ):
            self.assertNotIn(sentinel, restored_chat)

        source_endpoint = {
            "scheme": "https",
            "host": "example.invalid",
        }
        nullable_input_fields = {
            "content_intent": None,
            "merchant_visibility": None,
            "merchant_name": None,
            "fact_source_policy": None,
        }
        diagnosis_payloads = {
            "r9-root-diagnosis": api._sanitize_persisted_diagnosis({
                "record_type": "debug_trace",
                "ai_diagnosis": root_sentinel,
            }),
            "r9-expert-diagnosis": api._sanitize_persisted_diagnosis({
                "grade": "良好",
                "expert_opinions": [{
                    "role": "system_message",
                    "opinion": expert_sentinel,
                }],
                "suggested_plans": [{
                    "title": "internal",
                    "body": expert_sentinel,
                    "messageTypeLabel": "completion_data",
                }],
                "market_timing": api.MarketTiming(
                    timing_coefficient=1.0,
                    cloud_sync={
                        "enabled": True,
                        "imported": 1,
                        "source": "authorized_trend",
                        "source_endpoint": source_endpoint,
                    },
                ).model_dump(),
                "input_diagnostics": {
                    "input_mode": "manual",
                    "ocr_char_count": None,
                    "original_desc_len": 10,
                    "scored_desc_len": 10,
                    "feature_body_len": 10.0,
                    "feature_body_main_len": 10.0,
                    "extra_image_context_len": 0,
                    "fact_context_len": 0,
                    "agent_context_len": 0,
                    **nullable_input_fields,
                },
            }),
        }
        created_at = datetime.now(timezone.utc).isoformat()
        for diagnosis_id, diagnosis_payload in diagnosis_payloads.items():
            api._insert_content_with_retention(
                "INSERT INTO saved_diagnoses("
                "id,user_id,note_title,domain,ces_percentile,composite_score,"
                "grade,diagnosis_json,created_at"
                ") VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    diagnosis_id,
                    user["id"],
                    "合成诊断",
                    "美食",
                    80.0,
                    80.0,
                    "良好",
                    json.dumps(diagnosis_payload, ensure_ascii=False),
                    created_at,
                ),
                "diagnosis",
                diagnosis_id,
                user["id"],
                created_at=created_at,
            )

        raw_diagnoses = db.fetchall(
            "SELECT id,diagnosis_json FROM saved_diagnoses "
            "WHERE id IN (?,?) ORDER BY id",
            tuple(diagnosis_payloads),
        )
        raw_diagnosis_json = json.dumps(
            [dict(row) for row in raw_diagnoses],
            ensure_ascii=False,
        )
        self.assertNotIn(root_sentinel, raw_diagnosis_json)
        self.assertNotIn(expert_sentinel, raw_diagnosis_json)

        reloaded_diagnoses = {
            diagnosis_id: asyncio.run(
                api.get_diagnosis(diagnosis_id, user)
            )
            for diagnosis_id in diagnosis_payloads
        }
        serialized_reloads = json.dumps(
            reloaded_diagnoses,
            ensure_ascii=False,
        )
        self.assertNotIn(root_sentinel, serialized_reloads)
        self.assertNotIn(expert_sentinel, serialized_reloads)

        shaped = reloaded_diagnoses["r9-expert-diagnosis"]
        self.assertEqual(
            shaped["market_timing"]["cloud_sync"]["source_endpoint"],
            source_endpoint,
        )
        for key in nullable_input_fields:
            self.assertIn(key, shaped["input_diagnostics"])
            self.assertIsNone(shaped["input_diagnostics"][key])

        exported = api._account_export_payload(user)
        serialized_export = json.dumps(exported, ensure_ascii=False)
        for sentinel in (
            root_sentinel,
            expert_sentinel,
            preference_sentinel,
        ):
            self.assertNotIn(sentinel, serialized_export)
        exported_diagnosis = next(
            item["diagnosis"]
            for item in exported["archives"]["diagnoses"]
            if item["id"] == "r9-expert-diagnosis"
        )
        self.assertEqual(
            exported_diagnosis["market_timing"]["cloud_sync"][
                "source_endpoint"
            ],
            source_endpoint,
        )
        for key in nullable_input_fields:
            self.assertIn(key, exported_diagnosis["input_diagnostics"])
            self.assertIsNone(
                exported_diagnosis["input_diagnostics"][key]
            )

    def test_r9_expert_aliases_roles_and_unicode_lookalikes_fail_closed(self):
        expert_roles = (
            "专家",
            "仲裁专家",
            "内容专家",
            "增长专家",
            "用户专家",
            "视觉专家",
        )
        role_suffixes = (
            "/system_message",
            "::tool_result",
            "_developer_message",
            " hidden_state",
            "-completion_data",
            "|model_context",
            "(request_body)",
            "[response_body]",
            "/audit_log",
            " telemetry_event",
        )
        for role in expert_roles:
            for suffix in role_suffixes:
                sentinel = f"R10_ROLE_SUFFIX_{role}_{suffix}"
                opinion = {
                    "role": role + suffix,
                    "opinion": sentinel,
                }
                projections = (
                    api._public_expert_opinions([opinion]),
                    api._sanitize_persisted_diagnosis({
                        "expert_opinions": [opinion],
                    }),
                    api._sanitize_chat_generate_context({
                        "expert_opinions": [opinion],
                    }),
                )
                for projected in projections:
                    self.assertNotIn(
                        sentinel,
                        json.dumps(projected, ensure_ascii=False),
                    )

        role_aliases = (
            "Role",
            "ROLE",
            "rOle",
            "role-",
            "role.",
            " role ",
            "Ｒｏｌｅ",
            "rоle",
        )
        internal_values = (
            "system_message",
            "tool_result",
            "developer_message",
            "hidden_state",
            "completion_data",
            "model_context",
            "audit_log",
            "telemetry_event",
        )
        for key in role_aliases:
            for internal_value in internal_values:
                sentinel = f"R10_ROLE_ALIAS_{key}_{internal_value}"
                opinion = {
                    key: internal_value,
                    "opinion": sentinel,
                }
                projections = (
                    api._public_expert_opinions([opinion]),
                    api._sanitize_persisted_diagnosis({
                        "expert_opinions": [opinion],
                    }),
                    api._sanitize_chat_generate_context({
                        "expert_opinions": [opinion],
                    }),
                )
                for projected in projections:
                    self.assertNotIn(
                        sentinel,
                        json.dumps(projected, ensure_ascii=False),
                    )

        source_type_aliases = (
            "sourceType",
            "Source_Type",
            "SOURCE_TYPE",
            "source-type",
            "source.type",
            " source_type ",
            "ｓｏｕｒｃｅ＿ｔｙｐｅ",
            "sourceТype",
        )
        for key in source_type_aliases:
            for internal_value in internal_values:
                sentinel = (
                    f"R10_SOURCE_TYPE_ALIAS_{key}_{internal_value}"
                )
                opinion = {
                    "role": "内容专家",
                    "opinion": "公开意见",
                    "evidence": [{
                        key: internal_value,
                        "text": sentinel,
                    }],
                }
                projections = (
                    api._public_expert_opinions([opinion]),
                    api._sanitize_persisted_diagnosis({
                        "expert_opinions": [opinion],
                    }),
                    api._sanitize_chat_generate_context({
                        "expert_opinions": [opinion],
                    }),
                )
                for projected in projections:
                    self.assertNotIn(
                        sentinel,
                        json.dumps(projected, ensure_ascii=False),
                    )

        discriminator_lookalikes = (
            "ｔｙｐｅ",
            "ｒｏｌｅ",
            "ｋｉｎｄ",
            "tyｐe",
            "roлe",
            "kiնd",
        )
        for key in discriminator_lookalikes:
            for internal_value in (
                "hidden_state",
                "tool_result",
                "telemetry_event",
            ):
                sentinel = f"R10_LOOKALIKE_{key}_{internal_value}"
                record = {
                    "title": "internal",
                    "body": sentinel,
                    key: internal_value,
                }
                expert = {
                    "role": "内容专家",
                    key: internal_value,
                    "opinion": sentinel,
                }
                evidence = {
                    "role": "内容专家",
                    "opinion": "公开意见",
                    "evidence": [{
                        key: internal_value,
                        "text": sentinel,
                    }],
                }
                projections = (
                    api._public_diagnosis_value({"records": [record]}),
                    api._sanitize_chat_persisted_value({"records": [record]}),
                    api._sanitize_persisted_diagnosis({
                        "suggested_plans": [record],
                    }),
                    api._sanitize_chat_generate_context({
                        "pending_plan_options": [record],
                    }),
                    api._sanitize_chat_generate_context({
                        "supplement_prompts": [{
                            "prompt": sentinel,
                            key: internal_value,
                        }],
                    }),
                    api._sanitize_persisted_diagnosis({
                        key: internal_value,
                        "ai_diagnosis": sentinel,
                    }),
                    api._sanitize_chat_generate_context({
                        key: internal_value,
                        "fact_context": sentinel,
                    }),
                    api._sanitize_chat_preferences({
                        key: internal_value,
                        "tone": sentinel,
                    }),
                    api._public_expert_opinions([expert]),
                    api._public_expert_opinions([evidence]),
                )
                for projected in projections:
                    self.assertNotIn(
                        sentinel,
                        json.dumps(projected, ensure_ascii=False),
                    )

        canonical = api._public_expert_opinions([
            {
                "role": "内容专家",
                "opinion": "正常公开意见",
                "evidence": [{
                    "source_type": "v04_feature",
                    "source_key": "body_len",
                    "text": "正常公开证据",
                }],
            },
        ])
        self.assertEqual(canonical[0]["role"], "内容专家")
        self.assertEqual(canonical[0]["opinion"], "正常公开意见")
        self.assertEqual(
            canonical[0]["evidence"][0]["text"],
            "正常公开证据",
        )

    def test_h11_exact_schema_keys_block_extended_unicode_discriminators(self):
        discriminator_lookalikes = (
            "τype",
            "typе",
            "tуpе",
            "rоⅼе",
            "rоӏе",
            "κіոԁ",
            "ŕole",
            "r\u0301ole",
            "k\u0301ind",
            "meta_τype",
            "τype_suffix",
            "sоurcе_tуpе",
            "futurePublicField",
        )
        internal_values = (
            "system_message",
            "developer_message",
            "hidden_state",
        )
        for key in discriminator_lookalikes:
            for internal_value in internal_values:
                sentinel = f"H11_SCHEMA_{key}_{internal_value}"
                record = {
                    "title": "internal",
                    "body": sentinel,
                    key: internal_value,
                }
                expert = {
                    "role": "内容专家",
                    key: internal_value,
                    "opinion": sentinel,
                }
                evidence = {
                    "role": "内容专家",
                    "opinion": "公开意见",
                    "evidence": [{
                        key: internal_value,
                        "text": sentinel,
                    }],
                }
                projections = (
                    api._public_diagnosis_value({"records": [record]}),
                    api._sanitize_chat_persisted_value({
                        "records": [record],
                    }),
                    api._sanitize_persisted_diagnosis({
                        "suggested_plans": [record],
                    }),
                    api._sanitize_chat_generate_context({
                        "pending_plan_options": [record],
                    }),
                    api._sanitize_chat_generate_context({
                        "supplement_prompts": [{
                            "prompt": sentinel,
                            key: internal_value,
                        }],
                    }),
                    api._sanitize_persisted_diagnosis({
                        key: internal_value,
                        "ai_diagnosis": sentinel,
                    }),
                    api._sanitize_chat_generate_context({
                        key: internal_value,
                        "fact_context": sentinel,
                    }),
                    api._sanitize_chat_preferences({
                        key: internal_value,
                        "tone": sentinel,
                    }),
                    api._public_expert_opinions([expert]),
                    api._public_expert_opinions([evidence]),
                )
                for projected in projections:
                    self.assertNotIn(
                        sentinel,
                        json.dumps(projected, ensure_ascii=False),
                    )

        historical_marker = "H11_HISTORICAL_PRIVATE"
        historical = api._public_expert_opinion({
            "role": "增长专家",
            "raw": "<opinion>公开增长意见</opinion>",
            "provider": historical_marker,
            "reasoning": historical_marker,
        })
        self.assertEqual(historical["opinion"], "公开增长意见")
        self.assertNotIn(
            historical_marker,
            json.dumps(historical, ensure_ascii=False),
        )

    def test_h11_extended_unicode_survivors_never_cross_lifecycle(self):
        user = self._create_user(username="h11-lifecycle-user")
        sentinels = {
            "expert_role": "H11_LIFECYCLE_EXPERT_ROLE",
            "expert_source": "H11_LIFECYCLE_EXPERT_SOURCE",
            "chat_plan": "H11_LIFECYCLE_CHAT_PLAN",
            "diagnosis_root": "H11_LIFECYCLE_DIAGNOSIS_ROOT",
            "diagnosis_plan": "H11_LIFECYCLE_DIAGNOSIS_PLAN",
        }
        expert_opinions = [
            {
                "rоӏе": "tool_result",
                "opinion": sentinels["expert_role"],
            },
            {
                "role": "内容专家",
                "opinion": "公开意见",
                "evidence": [{
                    "sоurcе_tуpе": "developer_message",
                    "text": sentinels["expert_source"],
                }],
            },
        ]
        session_id = "h11-survivor-chat"
        api._chat_sessions[session_id] = {
            "user_id": user["id"],
            "domain": "美食",
            "messages": [
                {"role": "assistant", "content": "safe assistant"},
            ],
            "generate_context": {
                "expert_opinions": expert_opinions,
                "pending_plan_options": [{
                    "id": "A",
                    "body": sentinels["chat_plan"],
                    "τype": "hidden_state",
                }],
            },
        }
        self.assertTrue(api._persist_chat_session(session_id))

        diagnosis_id = "h11-survivor-diagnosis"
        created_at = datetime.now(timezone.utc).isoformat()
        diagnosis_payload = api._sanitize_persisted_diagnosis({
            "ai_diagnosis": sentinels["diagnosis_root"],
            "k\u0301ind": "hidden_state",
            "expert_opinions": expert_opinions,
            "suggested_plans": [{
                "title": "internal",
                "body": sentinels["diagnosis_plan"],
                "rоⅼе": "hidden_state",
            }],
        })
        api._insert_content_with_retention(
            "INSERT INTO saved_diagnoses("
            "id,user_id,note_title,domain,ces_percentile,composite_score,"
            "grade,diagnosis_json,created_at"
            ") VALUES(?,?,?,?,?,?,?,?,?)",
            (
                diagnosis_id,
                user["id"],
                "合成诊断",
                "美食",
                80.0,
                80.0,
                "良好",
                json.dumps(diagnosis_payload, ensure_ascii=False),
                created_at,
            ),
            "diagnosis",
            diagnosis_id,
            user["id"],
            created_at=created_at,
        )

        raw_chat = db.fetchone(
            "SELECT messages_json,user_prefs_json,generate_ctx_json "
            "FROM chat_sessions WHERE id=?",
            (session_id,),
        )
        raw_diagnosis = db.fetchone(
            "SELECT diagnosis_json FROM saved_diagnoses WHERE id=?",
            (diagnosis_id,),
        )["diagnosis_json"]
        api._chat_sessions.pop(session_id, None)
        reloaded_chat = api._load_chat_session_from_db(session_id)
        reloaded_diagnosis = asyncio.run(
            api.get_diagnosis(diagnosis_id, user)
        )
        exported = api._account_export_payload(user)
        lifecycle_values = (
            json.dumps(dict(raw_chat), ensure_ascii=False),
            raw_diagnosis,
            json.dumps(reloaded_chat, ensure_ascii=False),
            json.dumps(reloaded_diagnosis, ensure_ascii=False),
            json.dumps(exported, ensure_ascii=False),
        )
        for sentinel in sentinels.values():
            for value in lifecycle_values:
                self.assertNotIn(sentinel, value)

    def test_r9_expert_and_unicode_survivors_never_cross_lifecycle(self):
        user = self._create_user(username="r10-lifecycle-user")
        sentinels = {
            "role_suffix": "R10_LIFECYCLE_ROLE_SUFFIX",
            "role_alias": "R10_LIFECYCLE_ROLE_ALIAS",
            "source_alias": "R10_LIFECYCLE_SOURCE_ALIAS",
            "unicode_key": "R10_LIFECYCLE_UNICODE_KEY",
        }
        expert_opinions = [
            {
                "role": "内容专家/system_message",
                "opinion": sentinels["role_suffix"],
            },
            {
                "Role": "tool_result",
                "opinion": sentinels["role_alias"],
            },
            {
                "role": "内容专家",
                "opinion": "公开意见",
                "evidence": [{
                    "sourceType": "developer_message",
                    "text": sentinels["source_alias"],
                }],
            },
        ]
        session_id = "r10-survivor-chat"
        api._chat_sessions[session_id] = {
            "user_id": user["id"],
            "domain": "美食",
            "messages": [
                {"role": "assistant", "content": "safe assistant"},
            ],
            "generate_context": {
                "expert_opinions": expert_opinions,
                "pending_plan_options": [{
                    "id": "A",
                    "body": sentinels["unicode_key"],
                    "ｔｙｐｅ": "hidden_state",
                }],
            },
        }
        self.assertTrue(api._persist_chat_session(session_id))

        diagnosis_id = "r10-survivor-diagnosis"
        created_at = datetime.now(timezone.utc).isoformat()
        diagnosis_payload = api._sanitize_persisted_diagnosis({
            "grade": "良好",
            "expert_opinions": expert_opinions,
            "suggested_plans": [{
                "title": "internal",
                "body": sentinels["unicode_key"],
                "roлe": "hidden_state",
            }],
        })
        api._insert_content_with_retention(
            "INSERT INTO saved_diagnoses("
            "id,user_id,note_title,domain,ces_percentile,composite_score,"
            "grade,diagnosis_json,created_at"
            ") VALUES(?,?,?,?,?,?,?,?,?)",
            (
                diagnosis_id,
                user["id"],
                "合成诊断",
                "美食",
                80.0,
                80.0,
                "良好",
                json.dumps(diagnosis_payload, ensure_ascii=False),
                created_at,
            ),
            "diagnosis",
            diagnosis_id,
            user["id"],
            created_at=created_at,
        )

        raw_chat = db.fetchone(
            "SELECT messages_json,user_prefs_json,generate_ctx_json "
            "FROM chat_sessions WHERE id=?",
            (session_id,),
        )
        raw_diagnosis = db.fetchone(
            "SELECT diagnosis_json FROM saved_diagnoses WHERE id=?",
            (diagnosis_id,),
        )["diagnosis_json"]
        api._chat_sessions.pop(session_id, None)
        reloaded_chat = api._load_chat_session_from_db(session_id)
        reloaded_diagnosis = asyncio.run(
            api.get_diagnosis(diagnosis_id, user)
        )
        exported = api._account_export_payload(user)
        lifecycle_values = (
            json.dumps(dict(raw_chat), ensure_ascii=False),
            raw_diagnosis,
            json.dumps(reloaded_chat, ensure_ascii=False),
            json.dumps(reloaded_diagnosis, ensure_ascii=False),
            json.dumps(exported, ensure_ascii=False),
        )
        for sentinel in sentinels.values():
            for value in lifecycle_values:
                self.assertNotIn(sentinel, value)

    def test_h12_real_producer_shapes_match_exact_public_contract(self):
        evidence = api._expert_evidence_item(
            text="H12 结构化公开证据",
            source_type="v04_feature",
            source_key="body_len",
            label="正文长度",
            value=100,
            benchmark=220,
            status="gap",
            confidence=0.9,
        )
        self.assertEqual(
            api._public_expert_evidence([evidence]),
            [evidence],
        )

        normalized = api._normalize_expert_opinion(
            {
                "role": "增长专家",
                "raw": (
                    "<opinion>H12 公开增长意见</opinion>"
                    "<confidence>0.8</confidence>"
                ),
            },
            features={"body_len": 100.0},
            timing=api.MarketTiming(
                timing_coefficient=1.0,
                latest_capture="2026-07-26T00:00:00",
                source_breakdown={"homefeed": 2},
            ).model_dump(),
            domain="美食",
            percentile=80,
            grade="良好",
        )
        projected = api._public_expert_opinion(normalized)
        self.assertGreater(len(normalized["evidence"]), 0)
        self.assertEqual(projected["evidence"], normalized["evidence"][:4])

        decision = {
            "enabled": False,
            "provider": "none",
            "reason": "user_or_ui_skipped_fact_source",
            "content_intent": "真实种草型",
            "merchant_visibility": "auto",
            "merchant_name": "",
            "policy": "skip",
            "needs_user_supplement": False,
            "supplement_fields": [],
            "supplement_prompt": "",
        }
        disabled = api._disabled_fact_enrichment(
            decision,
            query="H12 公开查询",
        )
        response = api.AnalyzeResponse(
            ces_percentile=80,
            composite_score=80,
            grade="良好",
            visual_score=None,
            features={},
            weaknesses=[],
            ai_diagnosis="H12 公开诊断",
            suggested_titles=["H12 公开标题"],
            improvement_plan="H12 公开计划",
            model_used="offline",
            fact_enrichment=disabled,
        )
        raw = response.model_dump()
        persisted = api._sanitize_persisted_diagnosis(raw)
        self.assertEqual(len(raw), 30)
        self.assertEqual(set(persisted), set(raw))
        self.assertEqual(persisted["fact_enrichment"], disabled)

    def test_h12_dynamic_public_label_maps_are_bounded_across_lifecycle(self):
        valid_map = {
            "homefeed": 2,
            "prototype_source": 3,
            "type": 4,
            "partner_role_v2": 5,
            "合作type源": 6,
            "source:partner/v2": 7,
        }
        self.assertEqual(
            api._sanitize_public_schema_value(
                valid_map,
                ("map", "integer"),
            ),
            valid_map,
        )

        private_marker = "H12_DYNAMIC_PRIVATE_VALUE"
        overlong_key = "source_" + ("x" * 48)
        invalid_map = {
            "homefeed": 2,
            overlong_key: 3,
            "bad\u200dlabel": 4,
            " leading": 5,
            7: 6,
            "private_value": private_marker,
        }
        self.assertEqual(
            api._sanitize_public_schema_value(
                invalid_map,
                ("map", "integer"),
            ),
            {"homefeed": 2},
        )

        user = self._create_user(username="h12-producer-lifecycle")
        evidence = api._expert_evidence_item(
            text="H12_LIFECYCLE_EVIDENCE",
            source_type="v04_feature",
            source_key="body_len",
            label="正文长度",
            value=100,
            benchmark=220,
            status="gap",
            confidence=0.9,
        )
        opinion = {
            "role": "增长专家",
            "opinion": "H12_LIFECYCLE_OPINION",
            "evidence": [evidence],
            "evidence_binding": "v04_structured",
            "confidence": 0.8,
        }
        decision = {
            "enabled": False,
            "provider": "none",
            "reason": "H12_LIFECYCLE_SKIP_REASON",
            "content_intent": "真实种草型",
            "merchant_visibility": "auto",
            "merchant_name": "",
            "policy": "skip",
            "needs_user_supplement": False,
            "supplement_fields": [],
            "supplement_prompt": "",
        }
        disabled = api._disabled_fact_enrichment(
            decision,
            query="H12 生命周期公开查询",
        )

        session_id = "h12-producer-chat"
        api._chat_sessions[session_id] = {
            "user_id": user["id"],
            "domain": "美食",
            "messages": [
                {"role": "assistant", "content": "H12 safe assistant"},
            ],
            "generate_context": {
                "expert_opinions": [opinion],
                "fact_enrichment": disabled,
            },
        }
        self.assertTrue(api._persist_chat_session(session_id))

        diagnosis_id = "h12-producer-diagnosis"
        diagnosis_payload = api._sanitize_persisted_diagnosis({
            "ai_diagnosis": "H12 lifecycle diagnosis",
            "expert_opinions": [opinion],
            "fact_enrichment": disabled,
            "market_timing": {
                "source_breakdown": {
                    **valid_map,
                    **invalid_map,
                },
            },
        })
        created_at = datetime.now(timezone.utc).isoformat()
        api._insert_content_with_retention(
            "INSERT INTO saved_diagnoses("
            "id,user_id,note_title,domain,ces_percentile,composite_score,"
            "grade,diagnosis_json,created_at"
            ") VALUES(?,?,?,?,?,?,?,?,?)",
            (
                diagnosis_id,
                user["id"],
                "H12 synthetic diagnosis",
                "美食",
                80.0,
                80.0,
                "良好",
                json.dumps(diagnosis_payload, ensure_ascii=False),
                created_at,
            ),
            "diagnosis",
            diagnosis_id,
            user["id"],
            created_at=created_at,
        )

        raw_chat_row = db.fetchone(
            "SELECT messages_json,user_prefs_json,generate_ctx_json "
            "FROM chat_sessions WHERE id=?",
            (session_id,),
        )
        raw_chat = json.dumps(
            {
                "messages": json.loads(raw_chat_row["messages_json"]),
                "user_preferences": json.loads(
                    raw_chat_row["user_prefs_json"],
                ),
                "generation_context": json.loads(
                    raw_chat_row["generate_ctx_json"],
                ),
            },
            ensure_ascii=False,
        )
        raw_diagnosis = db.fetchone(
            "SELECT diagnosis_json FROM saved_diagnoses WHERE id=?",
            (diagnosis_id,),
        )["diagnosis_json"]
        api._chat_sessions.pop(session_id, None)
        reloaded_chat = json.dumps(
            api._load_chat_session_from_db(session_id),
            ensure_ascii=False,
        )
        reloaded_diagnosis = json.dumps(
            asyncio.run(api.get_diagnosis(diagnosis_id, user)),
            ensure_ascii=False,
        )
        exported = json.dumps(
            api._account_export_payload(user),
            ensure_ascii=False,
        )

        for value in (raw_chat, reloaded_chat, exported):
            self.assertIn("H12_LIFECYCLE_OPINION", value)
            self.assertIn("H12_LIFECYCLE_EVIDENCE", value)
            self.assertIn("H12_LIFECYCLE_SKIP_REASON", value)
            self.assertIn('"confidence": 0.9', value)
            self.assertIn('"skipped": true', value)
        for value in (raw_diagnosis, reloaded_diagnosis, exported):
            for source_label in valid_map:
                self.assertIn(source_label, value)
            self.assertNotIn(overlong_key, value)
            self.assertNotIn("bad\u200dlabel", value)
            self.assertNotIn('" leading"', value)
        for value in (
            raw_chat,
            raw_diagnosis,
            reloaded_chat,
            reloaded_diagnosis,
            exported,
        ):
            self.assertNotIn(private_marker, value)

    def test_h13_generic_dynamic_maps_use_typed_bounded_contract(self):
        exact_limit_key = "z" * 48
        too_long_key = "z" * 49
        mixed_map = {
            "source.primary/v3": 17,
            exact_limit_key: 48,
            too_long_key: 49,
            "bad\u200dformat": 20,
            "wrong_value": "H13_PRIVATE_MAP_VALUE",
        }
        expected_map = {
            "source.primary/v3": 17,
            exact_limit_key: 48,
        }
        payload = {
            "market_timing": {
                "source_breakdown": dict(mixed_map),
                "pipeline_status": {
                    "xhs": {
                        "latest_health": {
                            "details": {
                                "latest_run_source_breakdown": dict(mixed_map),
                                "latest_run_source_health": {
                                    "source_breakdown": dict(mixed_map),
                                },
                            },
                        },
                    },
                },
            },
        }
        expected = {
            "market_timing": {
                "source_breakdown": dict(expected_map),
                "pipeline_status": {
                    "xhs": {
                        "latest_health": {
                            "details": {
                                "latest_run_source_breakdown": dict(expected_map),
                                "latest_run_source_health": {
                                    "source_breakdown": dict(expected_map),
                                },
                            },
                        },
                    },
                },
            },
        }
        self.assertEqual(api._public_diagnosis_value(payload), expected)
        self.assertEqual(api._sanitize_chat_persisted_value(payload), expected)

    def test_h13_chat_start_preserves_typed_fact_and_market_context(self):
        user = self._create_user(username="h13-real-chat-start")
        decision = {
            "enabled": False,
            "provider": "none",
            "reason": "h13_user_skipped_fact_source",
            "content_intent": "真实种草型",
            "merchant_visibility": "auto",
            "merchant_name": "",
            "policy": "skip",
            "needs_user_supplement": False,
            "supplement_fields": [],
            "supplement_prompt": "",
        }
        fact_enrichment = api._disabled_fact_enrichment(
            decision,
            query="H13 公开事实查询",
        )
        source_breakdown = {
            "homefeed": 3,
            "partner.source/v3": 4,
        }
        response = asyncio.run(
            api.chat_start(
                api.ChatStartInput(
                    note_title="H13 Chat 标题",
                    note_body="H13 Chat 正文",
                    domain="美食",
                    generate_context={
                        "fact_enrichment": fact_enrichment,
                        "market_timing": {
                            "source_breakdown": source_breakdown,
                        },
                    },
                ),
                user,
            )
        )
        session_id = response.session_id
        raw_row = db.fetchone(
            "SELECT generate_ctx_json FROM chat_sessions WHERE id=?",
            (session_id,),
        )
        raw_context = json.loads(raw_row["generate_ctx_json"])
        api._chat_sessions.pop(session_id, None)
        reloaded_context = api._load_chat_session_from_db(
            session_id,
        )["generate_context"]
        exported = api._account_export_payload(user)
        exported_context = next(
            item["generation_context"]
            for item in exported["archives"]["chat_sessions"]
            if item["id"] == session_id
        )
        for context in (
            raw_context,
            reloaded_context,
            exported_context,
        ):
            self.assertEqual(
                context["fact_enrichment"],
                fact_enrichment,
            )
            self.assertEqual(
                context["market_timing"]["source_breakdown"],
                source_breakdown,
            )

    def test_h13_nonfinite_expert_confidence_fails_closed(self):
        for label, value in (
            ("nan", float("nan")),
            ("positive_inf", float("inf")),
            ("negative_inf", float("-inf")),
        ):
            with self.subTest(label=label):
                evidence = api._expert_evidence_item(
                    text=f"H13 {label} producer evidence",
                    source_type="user_input",
                    confidence=value,
                )
                self.assertEqual(evidence["confidence"], 0.0)

                projected = api._public_expert_evidence([{
                    "text": f"H13 {label} public evidence",
                    "source_type": "user_input",
                    "confidence": value,
                }])
                self.assertEqual(
                    projected,
                    [{
                        "text": f"H13 {label} public evidence",
                        "source_type": "user_input",
                    }],
                )

                public_opinion = api._public_expert_opinion({
                    "role": "增长专家",
                    "opinion": f"H13 {label} public opinion",
                    "confidence": value,
                })
                self.assertEqual(public_opinion["confidence"], 0.0)

                normalized = api._normalize_expert_opinion({
                    "role": "增长专家",
                    "raw": (
                        f"<opinion>H13 {label} normalized opinion</opinion>"
                        f"<confidence>{value}</confidence>"
                    ),
                })
                self.assertEqual(normalized["confidence"], 0.0)

    def test_chat_image_failure_uses_stable_public_message(self):
        api._chat_sessions["stable-image-failure"] = {
            "domain": "美食",
            "messages": [],
        }

        async def first_two_events():
            stream = api._chat_sse_generator(
                "stable-image-failure",
                "请优化",
                image_base64="aW1hZ2U=",
            )
            try:
                return [await anext(stream), await anext(stream)]
            finally:
                await stream.aclose()

        secret = "Bearer SECRET https://user:pass@example.invalid/image"
        with mock.patch.object(
            api._httpx,
            "Client",
            side_effect=RuntimeError(secret),
        ):
            events = asyncio.run(first_two_events())
        combined = "".join(events)
        self.assertIn("图片解析暂时不可用", combined)
        self.assertNotIn("SECRET", combined)
        self.assertNotIn("user:pass", combined)
        self.assertNotIn("example.invalid", combined)

    def test_artifact_and_training_failures_never_persist_raw_exception_text(self):
        class FailingS3Client:
            @staticmethod
            def download_file(bucket, key, target):
                raise RuntimeError(
                    "Bearer SECRET https://user:pass@example.invalid/model"
                )

        fake_boto3 = mock.Mock()
        fake_boto3.client.return_value = FailingS3Client()
        target = Path(self.temp.name) / "artifact.bin"
        with mock.patch.dict(sys.modules, {"boto3": fake_boto3}):
            with self.assertRaises(RuntimeError) as caught:
                artifact_loader._download_s3(
                    "private-secret-bucket",
                    "sensitive/model.bin",
                    target,
                )
        public_error = str(caught.exception)
        self.assertNotIn("private-secret-bucket", public_error)
        self.assertNotIn("sensitive/model.bin", public_error)
        self.assertNotIn("SECRET", public_error)
        self.assertIsNone(caught.exception.__cause__)
        training_source = (
            ROOT / "tools/fill_preference_generation_slots.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn('"error": str(exc)', training_source)
        self.assertNotIn("}: {exc}", training_source)
        self.assertIn('"error_code": f"generation_{exception_type}"', training_source)
        spec = importlib.util.spec_from_file_location(
            "fill_preference_generation_slots_test",
            ROOT / "tools/fill_preference_generation_slots.py",
        )
        self.assertIsNotNone(spec)
        trainer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(trainer)
        failed = trainer._failure_artifact(
            {"queue_id": "safe-id"},
            {},
            RuntimeError("Bearer SECRET https://user:pass@example.invalid/run"),
        )
        serialized = json.dumps(failed)
        self.assertIn("generation_runtimeerror", serialized)
        self.assertNotIn("SECRET", serialized)
        self.assertNotIn("user:pass", serialized)

    def test_invalid_sqlite_source_clock_blocks_retention_backfill(self):
        user = self._create_user()
        billing.upgrade_subscription(user["id"], "pro")
        valid_clock = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO notes(id,user_id,title,body,created_at) "
            "VALUES(?,?,?,?,?)",
            ("invalid-clock-note", user["id"], "title", "body", valid_clock),
        )
        for invalid_clock in (
            "not-a-clock",
            "2024-02-30",
            "2451545",
            "0",
            "2024-02-01",
            "2024-02-01T00:00:00.1234567+00:00",
            "2024-02-01T00:00:00+15:00",
            "2024-02-01T24:00:00+00:00",
            "2024-02-01T23:60:00+00:00",
            "2024-02-01T23:59:60+00:00",
            "2024-02-01T00:00:00+08:60",
            "2024-02-01T00:00:00+0860",
            "2024-02-01T00:00:00+14:01",
        ):
            with self.subTest(invalid_clock=invalid_clock):
                db.execute(
                    "UPDATE subscriptions SET started_at=? "
                    "WHERE user_id=? AND is_active=1",
                    (invalid_clock, user["id"]),
                )
                with self.assertRaisesRegex(
                    RuntimeError,
                    "invalid retention source clocks block startup",
                ):
                    db.init_db()
                self.assertIsNone(db.fetchone(
                    "SELECT content_id FROM content_retention "
                    "WHERE content_type='note' AND content_id=?",
                    ("invalid-clock-note",),
                ))
                db.execute(
                    "UPDATE subscriptions SET started_at=? "
                    "WHERE user_id=? AND is_active=1",
                    (valid_clock, user["id"]),
                )

    def test_sqlite_retention_uses_exact_timezone_and_fractional_comparisons(self):
        self.assertEqual(
            db._parse_retention_source_clock(
                "2024-02-01T00:00:00.123456"
            ).isoformat(),
            "2024-02-01T00:00:00.123456+00:00",
        )
        user = self._create_user()
        billing.upgrade_subscription(user["id"], "pro")
        db.execute(
            "UPDATE subscriptions SET started_at=?,expires_at=? "
            "WHERE user_id=? AND is_active=1",
            (
                " 2024-02-01T00:00:00+0800 ",
                "2024-03-01T00:00:00+08",
                user["id"],
            ),
        )
        db.execute(
            "INSERT INTO notes(id,user_id,title,body,created_at) VALUES(?,?,?,?,?)",
            (
                "offset-paid-note",
                user["id"],
                "title",
                "body",
                "2024-02-15T12:00:00+08:00",
            ),
        )
        db.execute(
            "INSERT INTO saved_diagnoses("
            "id,user_id,diagnosis_json,created_at"
            ") VALUES(?,?,?,?)",
            (
                "offset-paid-diagnosis",
                user["id"],
                "{}",
                "2024-02-15T12:00:00Z",
            ),
        )
        db.init_db()
        offset_rows = db.fetchall(
            "SELECT content_id,retention_class FROM content_retention "
            "WHERE content_id IN (?,?) ORDER BY content_id",
            ("offset-paid-note", "offset-paid-diagnosis"),
        )
        self.assertEqual(
            [(row["content_id"], row["retention_class"]) for row in offset_rows],
            [
                ("offset-paid-diagnosis", "paid_indefinite"),
                ("offset-paid-note", "paid_indefinite"),
            ],
        )

        db.execute(
            "UPDATE subscriptions SET started_at=?,expires_at=? "
            "WHERE user_id=? AND is_active=1",
            (
                "2024-04-01T00:00:00.700000+00:00",
                "2024-05-01T00:00:00.000000+00:00",
                user["id"],
            ),
        )
        db.execute(
            "INSERT INTO notes(id,user_id,title,body,created_at) VALUES(?,?,?,?,?)",
            (
                "fractional-free-note",
                user["id"],
                "title",
                "body",
                "2024-04-01T00:00:00.500000+00:00",
            ),
        )
        db.init_db()
        fractional = db.fetchone(
            "SELECT retention_class,created_at,active_until "
            "FROM content_retention WHERE content_type='note' AND content_id=?",
            ("fractional-free-note",),
        )
        self.assertEqual(fractional["retention_class"], "free_7d")
        self.assertEqual(
            fractional["created_at"],
            "2024-04-01T00:00:00.500000+00:00",
        )
        self.assertEqual(
            fractional["active_until"],
            "2024-04-08T00:00:00.500000+00:00",
        )

    def test_permission_matrix_is_exact_and_runtime_errors_do_not_echo_details(self):
        permission_matrix = (
            ROOT / "docs/FIRST_LAUNCH_DB_RUNTIME_PERMISSION_MATRIX.md"
        ).read_text(encoding="utf-8")
        for exact_row in (
            "| `auth_login_limits` | yes | yes | yes | yes |",
            "| `auth_verification_challenges` | yes | yes | yes | no |",
            "| `content_retention` | yes | yes | column-limited | no |",
            "| `account_deletion_requests` | yes | yes | yes | no |",
            "| `user_contract_acceptances` | yes | yes | no | no |",
            "| `notes` | yes | yes | `parent_id` only | yes |",
            "| `saved_diagnoses` | yes | yes | no | yes |",
            "| `ai_operation_admissions` | DELETE |",
            "| `chat_sessions` | DELETE |",
            "| `credit_transactions` | UPDATE |",
            "| `user_learn` | DELETE |",
            "| `users` | DELETE |",
            "| `pg_catalog.hashtext(text)` | yes | yes |",
            "| `pg_catalog.pg_advisory_xact_lock(bigint)` | yes | yes |",
            "'noteai_app', 'pg_catalog.hashtext(text)', 'EXECUTE'",
            "'noteai_app', 'pg_catalog.pg_advisory_xact_lock(bigint)', 'EXECUTE'",
            "'noteai_xhs', 'pg_catalog.hashtext(text)', 'EXECUTE'",
            "'noteai_xhs', 'pg_catalog.pg_advisory_xact_lock(bigint)', 'EXECUTE'",
        ):
            self.assertIn(exact_row, permission_matrix)
        self.assertIn(
            "`UPDATE(active_until,recovery_until,deleted_at,purge_after,"
            "purged_at,updated_at)`",
            permission_matrix,
        )
        self.assertIn(
            "table-level `UPDATE` on `content_retention`",
            permission_matrix,
        )
        self.assertIn(
            "table-level `UPDATE` on `notes`",
            permission_matrix,
        )
        self.assertIn(
            "any `UPDATE` on `saved_diagnoses`",
            permission_matrix,
        )
        migration = (
            MODEL_DIR / "migrations/postgres/0009_account_security_compliance.sql"
        ).read_text(encoding="utf-8").upper()
        self.assertNotIn("GRANT ", migration)
        self.assertEqual(
            migration.count(
                "REVOKE ALL ON FUNCTION\n"
                "    PUBLIC.NOTEAI_RETAINED_PRIMARY_INSERT_GUARD_H20()\n"
                "    FROM PUBLIC"
            ),
            1,
        )
        api_source = (MODEL_DIR / "api.py").read_text(encoding="utf-8")
        crawler_source = (MODEL_DIR / "crawler.py").read_text(encoding="utf-8")
        acquisition_source = (
            MODEL_DIR / "xhs_acquisition.py"
        ).read_text(encoding="utf-8")
        hot_source = (MODEL_DIR / "hot_keywords.py").read_text(encoding="utf-8")
        semantic_source = (
            MODEL_DIR / "enrich_semantic_features.py"
        ).read_text(encoding="utf-8")
        timing_source = (
            MODEL_DIR / "enrich_timing_features.py"
        ).read_text(encoding="utf-8")
        artifact_source = (
            MODEL_DIR / "artifact_loader.py"
        ).read_text(encoding="utf-8")
        fact_source = (
            MODEL_DIR / "fact_enrichment.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn('detail=f"视频解析失败: {exc}"', api_source)
        self.assertNotIn("error_summary = direct_code or str(exc)", crawler_source)
        self.assertNotIn('"error_summary": str(exc)', acquisition_source)
        self.assertNotIn('"host": parsed.netloc', acquisition_source)
        self.assertNotIn('result["source_url"]', hot_source)
        self.assertNotIn('"source_url": source_url', hot_source)
        self.assertNotIn("{type(exc).__name__}: {exc}", semantic_source)
        self.assertNotIn("{type(exc).__name__}: {exc}", timing_source)
        self.assertNotIn("download failed for {url}: {exc}", artifact_source)
        self.assertNotIn('_redact_secret_values(str(exc))', fact_source)

    def test_postgres_migration_persists_canonical_phone_constraint(self):
        migration = (
            MODEL_DIR / "migrations/postgres/0009_account_security_compliance.sql"
        ).read_text(encoding="utf-8")
        constraint_at = migration.index(
            "ADD CONSTRAINT users_phone_canonical_check"
        )
        unique_index_at = migration.index(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone_unique"
        )
        self.assertIn(
            "ALTER TABLE users\n"
            "    ADD CONSTRAINT users_phone_canonical_check",
            migration,
        )
        self.assertIn(
            "phone IS NULL OR phone = '' "
            "OR phone ~ '^\\+861[3-9][0-9]{9}$'",
            migration,
        )
        self.assertLess(constraint_at, unique_index_at)

    def test_postgres_retention_constraint_validates_real_time_order(self):
        migration = (
            MODEL_DIR / "migrations/postgres/0009_account_security_compliance.sql"
        ).read_text(encoding="utf-8")
        retention_constraint = migration.split(
            "CONSTRAINT content_retention_clock_order_check",
            1,
        )[1].split("PRIMARY KEY(content_type,content_id)", 1)[0]
        for clock in (
            "active_until",
            "recovery_until",
            "deleted_at",
            "purge_after",
            "purged_at",
        ):
            self.assertIn(f"btrim({clock}) ~", migration)
            self.assertIn(f"{clock} = btrim({clock})", migration)
        self.assertEqual(retention_constraint.count("))$'"), 8)
        self.assertNotIn("))?$'", retention_constraint)
        self.assertIn(
            "btrim(deleted_at)::timestamptz "
            "<= btrim(purge_after)::timestamptz",
            migration,
        )
        self.assertIn(
            "btrim(active_until)::timestamptz "
            "<= btrim(recovery_until)::timestamptz",
            migration,
        )
        self.assertIn(
            "btrim(recovery_until)::timestamptz "
            "<= btrim(purge_after)::timestamptz",
            migration,
        )
        self.assertIn(
            "btrim(purge_after)::timestamptz "
            "<= btrim(purged_at)::timestamptz",
            migration,
        )
        self.assertNotIn("AND active_until <= recovery_until", migration)
        self.assertNotIn("AND recovery_until <= purge_after", migration)

    def test_h17_postgres_purge_policy_rejects_forged_markers(self):
        migration = (
            MODEL_DIR / "migrations/postgres/0009_account_security_compliance.sql"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "ALTER TABLE content_retention ENABLE ROW LEVEL SECURITY",
            migration,
        )
        self.assertIn(
            "CREATE POLICY content_retention_insert_h20",
            migration,
        )
        self.assertIn(
            "CREATE POLICY content_retention_update_h17",
            migration,
        )
        self.assertEqual(
            migration.count(
                "btrim(purged_at)::timestamptz <= clock_timestamp()"
            ),
            1,
        )
        self.assertEqual(
            migration.count(
                "NOT EXISTS (SELECT 1 FROM notes"
            ),
            1,
        )
        self.assertEqual(
            migration.count(
                "NOT EXISTS (SELECT 1 FROM saved_diagnoses"
            ),
            1,
        )

    def test_h20_postgres_primary_reinsert_guard_locks_retention_identity(self):
        migration = (
            MODEL_DIR / "migrations/postgres/0009_account_security_compliance.sql"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "CREATE FUNCTION public."
            "noteai_retained_primary_insert_guard_h20()",
            migration,
        )
        self.assertIn("LANGUAGE plpgsql SECURITY DEFINER", migration)
        self.assertIn(
            "FROM public.content_retention retention\n"
            "        WHERE retention.content_type = TG_ARGV[0]",
            migration,
        )
        self.assertIn("FOR UPDATE", migration)
        self.assertIn(
            "CREATE TRIGGER notes_retained_primary_insert_h20",
            migration,
        )
        self.assertIn(
            "CREATE TRIGGER saved_diagnoses_retained_primary_insert_h20",
            migration,
        )
        self.assertIn(
            "CREATE POLICY content_retention_insert_h20",
            migration,
        )
        self.assertIn(
            "REVOKE ALL ON FUNCTION\n"
            "    public.noteai_retained_primary_insert_guard_h20()\n"
            "    FROM PUBLIC",
            migration,
        )
        self.assertIn(
            "EXISTS (SELECT 1 FROM notes primary_note",
            migration,
        )
        self.assertIn(
            "EXISTS (SELECT 1 FROM saved_diagnoses primary_diagnosis",
            migration,
        )

    def test_sqlite_retention_rejects_invalid_clocks_and_purge_transitions(self):
        user = self._create_user()
        valid_start = "2026-01-01T00:00:00+00:00"
        valid_recovery = "2026-01-08T00:00:00+00:00"
        valid_purge = "2026-01-31T00:00:00+00:00"
        invalid_rows = (
            (
                "arbitrary-paid",
                "paid_indefinite",
                None,
                None,
                "alpha",
                "omega",
                None,
            ),
            (
                "invalid-calendar-paid",
                "paid_indefinite",
                None,
                None,
                "2026-02-30T00:00:00+00:00",
                "2026-03-31T00:00:00+00:00",
                None,
            ),
            (
                "timezone-naive-free",
                "free_7d",
                "2026-01-01T00:00:00",
                "2026-01-08T00:00:00",
                None,
                "2026-01-31T00:00:00",
                None,
            ),
            (
                "real-time-inverted-paid",
                "paid_indefinite",
                None,
                None,
                "2026-01-01T00:00:00-14:00",
                "2026-01-01T01:00:00+14:00",
                None,
            ),
            (
                "purged-without-deadline-paid",
                "paid_indefinite",
                None,
                None,
                None,
                None,
                valid_purge,
            ),
            (
                "purged-before-deadline-free",
                "free_7d",
                valid_start,
                valid_recovery,
                None,
                valid_purge,
                "2026-01-30T23:59:59+00:00",
            ),
        )
        for row in invalid_rows:
            with self.subTest(content_id=row[0]):
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(
                        "INSERT INTO content_retention("
                        "content_type,content_id,user_id,retention_class,"
                        "active_until,recovery_until,deleted_at,purge_after,"
                        "purged_at,created_at,updated_at,contract_version"
                        ") VALUES('note',?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            row[0],
                            user["id"],
                            row[1],
                            row[2],
                            row[3],
                            row[4],
                            row[5],
                            row[6],
                            valid_start,
                            valid_start,
                            content_retention.CONTRACT_VERSION,
                        ),
                    )
        self.assertEqual(
            content_retention._status_payload(
                {
                    "retention_class": "paid_indefinite",
                    "active_until": None,
                    "recovery_until": None,
                    "deleted_at": None,
                    "purge_after": None,
                    "purged_at": valid_purge,
                },
                datetime.now(timezone.utc),
            )["state"],
            "expired",
        )

    def test_sqlite_retention_rejects_outer_deadline_whitespace(self):
        user = self._create_user()
        now = datetime.now(timezone.utc)
        with self.assertRaises(Exception):
            db.execute(
                "INSERT INTO content_retention("
                "content_type,content_id,user_id,retention_class,"
                "active_until,recovery_until,purge_after,"
                "created_at,updated_at,contract_version"
                ") VALUES(?,?,?,'free_7d',?,?,?,?,?,?)",
                (
                    "note",
                    "whitespace-retention",
                    user["id"],
                    f" {(now + timedelta(days=7)).isoformat()}",
                    (now + timedelta(days=14)).isoformat(),
                    (now + timedelta(days=44)).isoformat(),
                    now.isoformat(),
                    now.isoformat(),
                    content_retention.CONTRACT_VERSION,
                ),
            )

    def test_postgres_migration_ledger_binds_sha256_and_rejects_drift(self):
        import hashlib

        for name, pinned_sha256 in db._POSTGRES_LEGACY_MIGRATION_SHA256.items():
            self.assertEqual(
                hashlib.sha256(
                    (MODEL_DIR / "migrations/postgres" / name).read_bytes()
                ).hexdigest(),
                pinned_sha256,
            )

        class FakeResult:
            def __init__(self, rows=()):
                self._rows = list(rows)

            def fetchall(self):
                return list(self._rows)

        class FakeConnection:
            def __init__(self, rows=()):
                self.rows = list(rows)
                self.calls = []
                self.closed = False

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def execute(self, statement, params=()):
                self.calls.append((statement, params))
                normalized = " ".join(statement.split())
                if normalized.startswith("SELECT version"):
                    return FakeResult(self.rows)
                return FakeResult()

            def close(self):
                self.closed = True

        with tempfile.TemporaryDirectory() as migration_dir:
            migration_path = Path(migration_dir) / "0001_h14_contract.sql"
            marker_sql = "CREATE TABLE h14_sentinel(id integer);"
            migration_path.write_text(marker_sql, encoding="utf-8")
            digest = hashlib.sha256(migration_path.read_bytes()).hexdigest()

            mismatch = FakeConnection(
                [{"version": migration_path.name, "sha256": "0" * 64}]
            )
            with (
                mock.patch.object(db, "using_postgres", return_value=True),
                mock.patch.object(
                    db,
                    "_POSTGRES_MIGRATIONS_DIR",
                    Path(migration_dir),
                ),
                mock.patch.object(
                    db,
                    "_get_postgres_conn",
                    return_value=mismatch,
                ),
                self.assertRaisesRegex(
                    RuntimeError,
                    "migration checksum mismatch",
                ),
            ):
                db.apply_postgres_migrations()
            self.assertFalse(any(
                statement == marker_sql
                for statement, _params in mismatch.calls
            ))

            fresh = FakeConnection()
            with (
                mock.patch.object(db, "using_postgres", return_value=True),
                mock.patch.object(
                    db,
                    "_POSTGRES_MIGRATIONS_DIR",
                    Path(migration_dir),
                ),
                mock.patch.object(
                    db,
                    "_get_postgres_conn",
                    return_value=fresh,
                ),
            ):
                self.assertEqual(
                    db.apply_postgres_migrations(),
                    [migration_path.name],
                )
            self.assertTrue(any(
                "INSERT INTO schema_migrations(version,sha256)" in statement
                and params == (migration_path.name, digest)
                for statement, params in fresh.calls
            ))

            untrusted_legacy = FakeConnection(
                [{"version": migration_path.name, "sha256": None}]
            )
            with (
                mock.patch.object(db, "using_postgres", return_value=True),
                mock.patch.object(
                    db,
                    "_POSTGRES_MIGRATIONS_DIR",
                    Path(migration_dir),
                ),
                mock.patch.object(
                    db,
                    "_get_postgres_conn",
                    return_value=untrusted_legacy,
                ),
                self.assertRaisesRegex(
                    RuntimeError,
                    "migration checksum missing",
                ),
            ):
                db.apply_postgres_migrations()
            self.assertFalse(any(
                statement == marker_sql
                for statement, _params in untrusted_legacy.calls
            ))

            legacy = FakeConnection(
                [{"version": migration_path.name, "sha256": None}]
            )
            with (
                mock.patch.object(db, "using_postgres", return_value=True),
                mock.patch.object(
                    db,
                    "_POSTGRES_MIGRATIONS_DIR",
                    Path(migration_dir),
                ),
                mock.patch.object(
                    db,
                    "_get_postgres_conn",
                    return_value=legacy,
                ),
                mock.patch.dict(
                    db._POSTGRES_LEGACY_MIGRATION_SHA256,
                    {migration_path.name: digest},
                ),
            ):
                self.assertEqual(db.apply_postgres_migrations(), [])
            self.assertTrue(any(
                statement.startswith("UPDATE schema_migrations SET sha256=")
                and params == (digest, migration_path.name)
                for statement, params in legacy.calls
            ))
            self.assertTrue(
                mismatch.closed
                and fresh.closed
                and untrusted_legacy.closed
                and legacy.closed
            )

    def test_postgres_migration_hash_and_execution_share_one_file_snapshot(self):
        import hashlib

        class FakeResult:
            def fetchall(self):
                return []

        class MutatingConnection:
            def __init__(self, path: Path, replacement: str):
                self.path = path
                self.replacement = replacement
                self.calls = []
                self.mutated = False

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def execute(self, statement, params=()):
                self.calls.append((statement, params))
                if (
                    "SELECT version, sha256 FROM schema_migrations" in statement
                    and not self.mutated
                ):
                    self.path.write_text(
                        self.replacement,
                        encoding="utf-8",
                    )
                    self.mutated = True
                return FakeResult()

            def close(self):
                return None

        with tempfile.TemporaryDirectory() as migration_dir:
            migration_path = Path(migration_dir) / "0001_h15_snapshot.sql"
            original = "CREATE TABLE h15_original(id integer);"
            replacement = "CREATE TABLE h15_replacement(id integer);"
            migration_path.write_text(original, encoding="utf-8")
            expected_sha256 = hashlib.sha256(
                original.encode("utf-8")
            ).hexdigest()
            connection = MutatingConnection(
                migration_path,
                replacement,
            )
            with (
                mock.patch.object(db, "using_postgres", return_value=True),
                mock.patch.object(
                    db,
                    "_POSTGRES_MIGRATIONS_DIR",
                    Path(migration_dir),
                ),
                mock.patch.object(
                    db,
                    "_get_postgres_conn",
                    return_value=connection,
                ),
            ):
                self.assertEqual(
                    db.apply_postgres_migrations(),
                    [migration_path.name],
                )
            executed_sql = [
                statement
                for statement, _params in connection.calls
                if statement in {original, replacement}
            ]
            self.assertEqual(executed_sql, [original])
            self.assertTrue(any(
                "INSERT INTO schema_migrations(version,sha256)" in statement
                and params == (migration_path.name, expected_sha256)
                for statement, params in connection.calls
            ))

    def test_postgres_retention_queries_use_typed_time_comparisons(self):
        source = (MODEL_DIR / "content_retention.py").read_text(encoding="utf-8")
        migration = (
            MODEL_DIR / "migrations/postgres/0009_account_security_compliance.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("purge_after::timestamptz<=?::timestamptz", source)
        self.assertIn("primary_delete_by::timestamptz<=?::timestamptz", source)
        self.assertIn("started_at::timestamptz<=?::timestamptz", source)
        self.assertTrue(
            migration.lstrip().startswith("SET LOCAL TIME ZONE 'UTC';")
        )
        self.assertNotIn("INTERVAL '7 days')::text", migration)
        self.assertIn("'YYYY-MM-DD\"T\"HH24:MI:SS.USOF'", migration)

    def test_postgres_retention_source_clocks_and_connections_are_utc_strict(self):
        migration = (
            MODEL_DIR / "migrations/postgres/0009_account_security_compliance.sql"
        ).read_text(encoding="utf-8")
        preflight_at = migration.index("FOR source_clock IN")
        retention_table_at = migration.index(
            "CREATE TABLE IF NOT EXISTS content_retention"
        )
        self.assertLess(preflight_at, retention_table_at)
        for source_query in (
            "SELECT created_at AS source_clock FROM notes",
            "SELECT created_at AS source_clock FROM saved_diagnoses",
            "SELECT started_at AS source_clock FROM subscriptions",
            "SELECT expires_at AS source_clock FROM subscriptions",
        ):
            self.assertIn(source_query, migration)
        self.assertIn("btrim(source_clock)::timestamptz", migration)
        self.assertIn("regexp_match(", migration)
        self.assertIn(
            "invalid retention source clocks block migration",
            migration,
        )
        self.assertIn(r"\.[0-9]{1,6}", migration)
        self.assertNotIn(r"\.[0-9]+", migration)
        self.assertIn("([01][0-9]|2[0-3]):[0-5][0-9]", migration)
        self.assertIn("(:[0-5][0-9]", migration)

        fake_psycopg = mock.Mock()
        sentinel = object()
        fake_psycopg.connect.return_value = sentinel
        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_psycopg}),
            mock.patch.object(
                db,
                "_database_url",
                return_value="postgresql://example.invalid/noteai",
            ),
        ):
            self.assertIs(
                db._get_postgres_conn(
                    connect_timeout_seconds=3,
                    statement_timeout_ms=250,
                ),
                sentinel,
            )
        kwargs = fake_psycopg.connect.call_args.kwargs
        self.assertEqual(kwargs["connect_timeout"], 3)
        self.assertIn("-c timezone=UTC", kwargs["options"])
        self.assertIn("-c statement_timeout=250", kwargs["options"])

    def test_test_billing_flag_is_rejected_in_production_or_unspecified_stage(self):
        self._create_user()
        login = self._login()
        headers = {"Authorization": f"Bearer {login['token']}"}
        for env in (
            {
                "NOTEAI_ENABLE_TEST_BILLING": "1",
                "NOTEAI_DEPLOYMENT_STAGE": "production",
            },
            {"NOTEAI_ENABLE_TEST_BILLING": "1"},
        ):
            with self.subTest(env=env), mock.patch.dict(
                os.environ,
                env,
                clear=True,
            ):
                response = self.client.post(
                    "/billing/topup",
                    headers=headers,
                    json={"amount": 10},
                )
                self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
