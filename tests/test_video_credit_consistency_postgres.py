"""Opt-in checks on a fresh database in the existing local PG16 socket fixture."""
import importlib
import os
import re
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock


@unittest.skipUnless(os.environ.get("NOTEAI_LOCAL_PG16_CANARY_TEST") == "1",
                     "explicit isolated PG16 Unix socket required")
class VideoCreditsPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.test_item31_canary_dml_postgres import CanaryPaymentFlowPostgresTests
        CanaryPaymentFlowPostgresTests.setUpClass.__func__(cls)
        cls.fixture = CanaryPaymentFlowPostgresTests
        cls.billing = importlib.import_module("billing")
        cls.idempotency = importlib.import_module("idempotency")
        # Reproduce the repository's existing API privileges only in this fresh
        # disposable DB. No live role attributes or other databases are edited.
        from tools.collect_production_database_preflight import APP_TABLE_PRIVILEGES
        import psycopg
        root = Path(__file__).resolve().parents[1]
        with cls.fixture.connect(cls) as connection:
            connection.execute("GRANT USAGE ON SCHEMA public TO noteai_app")
            for table, permissions in APP_TABLE_PRIVILEGES.items():
                connection.execute(psycopg.sql.SQL("GRANT {} ON {} TO noteai_app").format(
                    psycopg.sql.SQL(", ".join(permissions)), psycopg.sql.Identifier(table)))
            source = (root / "scripts/postgres/noteai_production_runtime_roles.sql").read_text()
            for statement in re.findall(r"\bGRANT\b[^;]*\bTO noteai_app;", source):
                connection.execute(statement)

    @classmethod
    def tearDownClass(cls):
        cls.fixture.tearDownClass.__func__(cls)

    def connect(self):
        connection = self.fixture.connect(self)
        connection.execute("SET ROLE noteai_app")
        connection.execute("SET statement_timeout='10000ms'")
        return connection

    def setUp(self):
        self.uid = "h5-credit-synthetic-" + uuid.uuid4().hex
        self.env = mock.patch.dict(os.environ, {"DATABASE_URL": "postgresql:///isolated?host=/var/run/postgresql"})
        self.env.start()
        self.connection_patch = mock.patch.object(self.db, "get_conn", self.connect)
        self.connection_patch.start()
        self.db.execute("INSERT INTO users(id,username,email,password_hash,password_salt,created_at) VALUES(?,?,?,'synthetic','synthetic',?)",
                        (self.uid, self.uid, self.uid + "@example.invalid", self.billing._now()))
        self.billing.clear_active_usage()

    def tearDown(self):
        self.billing.clear_active_usage()
        self.connection_patch.stop()
        self.env.stop()

    def claim(self):
        return self.idempotency.claim_and_charge(user_id=self.uid, operation="generate",
            request_id="same-synthetic-video-request", payload={"video_file_id": "synthetic-video"})

    def test_same_key_concurrent_charge_and_usage_read_as_existing_api_role(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            claims = list(pool.map(lambda _: self.claim(), range(8)))
        self.assertEqual(sum(claim["state"] == "owner" for claim in claims), 1)
        summary = self.billing.get_usage_summary(self.uid)
        self.assertEqual(summary["total_credits"], 8)
        self.assertEqual(len(summary["recent_records"]), 1)
        row = summary["recent_records"][0]
        self.assertEqual((row["monthly_credits_used"], row["wallet_credits_used"]), (8, 0))
        self.assertEqual(self.billing.get_quota_status(self.uid)["monthly_credits_remaining"], 4)

    def test_mixed_refund_concurrent_and_ledger_join_as_existing_api_role(self):
        self.billing.get_subscription(self.uid)
        self.db.execute("UPDATE subscriptions SET used_monthly_credits=9 WHERE user_id=?", (self.uid,))
        self.billing.grant_credits(self.uid, 10, "synthetic test fixture")
        claim = self.claim()
        with ThreadPoolExecutor(max_workers=8) as pool:
            refunded = list(pool.map(lambda _: self.idempotency.mark_failed_and_refund(claim), range(8)))
        self.assertEqual(refunded.count(True), 1)
        self.assertEqual(self.billing.get_quota_status(self.uid)["total_available_credits"], 13)
        row = self.billing.get_usage_summary(self.uid)["recent_records"][0]
        self.assertEqual((row["credits_used"], row["refunded_credits"], row["status"]), (0, 8, "refunded"))
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) n FROM credit_transactions WHERE user_id=? AND type='refund'", (self.uid,))["n"], 1)

    def test_headerless_concurrent_refund_uses_original_usage_fence(self):
        self.billing.get_subscription(self.uid)
        self.db.execute("UPDATE subscriptions SET used_monthly_credits=9 WHERE user_id=?", (self.uid,))
        self.billing.grant_credits(self.uid, 10, "synthetic test fixture")
        charge = self.billing.check_and_deduct(self.uid, "generate")
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: self.billing.refund_operation_charge(self.uid, "generate", charge, "synthetic failure"), range(8)))
        self.assertEqual(self.billing.get_quota_status(self.uid)["total_available_credits"], 13)
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) n FROM credit_transactions WHERE user_id=? AND type='refund'", (self.uid,))["n"], 1)


if __name__ == "__main__":
    unittest.main()
