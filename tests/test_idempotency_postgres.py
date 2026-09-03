"""Disposable PostgreSQL concurrency test for BILL-001.

This module is skipped unless BOTH NOTEAI_RUN_POSTGRES_IDEMPOTENCY_TEST=1 and
NOTEAI_TEST_POSTGRES_URL are set. It must only be run against an approved,
disposable database; normal local/CI test runs never connect externally.
"""

import importlib
import os
import sys
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

db = importlib.import_module("db")
idempotency = importlib.import_module("idempotency")
billing = importlib.import_module("billing")


@unittest.skipUnless(
    os.environ.get("NOTEAI_RUN_POSTGRES_IDEMPOTENCY_TEST") == "1"
    and os.environ.get("NOTEAI_TEST_POSTGRES_URL", "").strip(),
    "approved disposable PostgreSQL test database is not configured",
)
class PostgresPaidRequestConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_database_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = os.environ["NOTEAI_TEST_POSTGRES_URL"]
        if not db.using_postgres():
            raise unittest.SkipTest("NOTEAI_TEST_POSTGRES_URL must be PostgreSQL")
        db.apply_postgres_migrations()
        cls.second_apply = db.apply_postgres_migrations()
        cls.users = []

    @classmethod
    def tearDownClass(cls):
        for user_id in cls.users:
            db.execute("DELETE FROM usage_records WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM credit_transactions WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM users WHERE id=?", (user_id,))
        if cls.old_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = cls.old_database_url

    @classmethod
    def _create_user(cls, label: str) -> str:
        user_id = f"idem-pg-{label}-{uuid.uuid4()}"
        cls.users.append(user_id)
        db.execute(
            "INSERT INTO users(id,username,email,password_hash,password_salt,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (
                user_id,
                user_id,
                f"{user_id}@example.invalid",
                "hash",
                "salt",
                "2026-07-11T00:00:00+00:00",
            ),
        )
        return user_id

    def test_migration_second_apply_is_empty_and_schema_is_digest_only(self):
        self.assertEqual(self.second_apply, [])
        rows = db.fetchall(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=current_schema() AND table_name='idempotency_requests'"
        )
        columns = {row["column_name"] for row in rows}
        self.assertTrue({
            "key_hash", "payload_hash", "status", "lease_token_hash",
            "charged_subscription_id", "charged_period_start",
            "usage_created_at",
            "charge_applied", "refund_applied", "complete_applied",
        }.issubset(columns))
        self.assertFalse({"raw_key", "request_body", "prompt", "reasoning"} & columns)

    def test_twenty_same_key_claims_have_one_owner_charge_and_usage(self):
        user_id = self._create_user("same")

        def claim(_index):
            return idempotency.claim_and_charge(
                user_id=user_id,
                operation="analyze",
                request_id="same-postgres-key",
                payload={"domain": "美食", "body": "digest-only"},
            )["state"]

        with ThreadPoolExecutor(max_workers=20) as pool:
            states = list(pool.map(claim, range(20)))
        self.assertEqual(states.count("owner"), 1)
        self.assertEqual(states.count("in_progress"), 19)
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM usage_records WHERE user_id=?", (user_id,))["c"],
            1,
        )

    def test_concurrent_refund_is_applied_once(self):
        user_id = self._create_user("refund")
        billing.get_subscription(user_id)
        billing.topup_credits(user_id, 6)
        db.execute(
            "UPDATE subscriptions SET used_monthly_credits=12 WHERE user_id=? AND is_active=1",
            (user_id,),
        )
        claim = idempotency.claim_and_charge(
            user_id=user_id,
            operation="analyze",
            request_id="postgres-refund-once",
            payload={"domain": "美食", "body": "digest-only"},
        )
        with ThreadPoolExecutor(max_workers=20) as pool:
            finalized = list(pool.map(
                lambda _index: idempotency.mark_failed_and_refund(claim),
                range(20),
            ))
        self.assertEqual(finalized.count(True), 1)
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM credit_transactions WHERE user_id=? AND type='refund'",
                (user_id,),
            )["c"],
            1,
        )
        credits = db.fetchone("SELECT balance,total_used FROM credits WHERE user_id=?", (user_id,))
        self.assertEqual(float(credits["balance"]), 6.0)
        self.assertEqual(float(credits["total_used"]), 0.0)
        usage = db.fetchone(
            "SELECT source,credits_used FROM usage_records WHERE id=?",
            (claim["charge"]["usage_id"],),
        )
        self.assertEqual(usage["source"], "refunded")
        self.assertEqual(float(usage["credits_used"]), 0.0)

    def test_upgrade_and_first_claim_concurrency_leave_one_active_subscription(self):
        user_id = self._create_user("upgrade-race")

        def upgrade(_index):
            billing.upgrade_subscription(user_id, "pro")
            return "upgrade"

        def claim(_index):
            try:
                return idempotency.claim_and_charge(
                    user_id=user_id,
                    operation="analyze",
                    request_id="postgres-upgrade-race-key",
                    payload={"domain": "美食", "body": "digest-only"},
                )["state"]
            except HTTPException as exc:
                return f"http-{exc.status_code}"

        with ThreadPoolExecutor(max_workers=20) as pool:
            futures = [pool.submit(upgrade, index) for index in range(10)]
            futures.extend(pool.submit(claim, index) for index in range(10))
            states = [future.result() for future in futures]
        self.assertIn("owner", states)
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM subscriptions WHERE user_id=? AND is_active=1",
                (user_id,),
            )["c"],
            1,
        )

    def test_twenty_distinct_keys_with_one_affordable_charge_never_go_negative(self):
        user_id = self._create_user("distinct")

        def claim(index):
            try:
                return idempotency.claim_and_charge(
                    user_id=user_id,
                    operation="generate",
                    request_id=f"distinct-postgres-{index}",
                    payload={"domain": "美食", "body": f"payload-{index}"},
                )["state"]
            except HTTPException as exc:
                return f"http-{exc.status_code}"

        with ThreadPoolExecutor(max_workers=20) as pool:
            states = list(pool.map(claim, range(20)))
        self.assertEqual(states.count("owner"), 1)
        self.assertEqual(states.count("http-402"), 19)
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM idempotency_requests WHERE user_id=?",
                (user_id,),
            )["c"],
            1,
        )
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM usage_records WHERE user_id=?",
                (user_id,),
            )["c"],
            1,
        )
        sub = db.fetchone(
            "SELECT used_monthly_credits FROM subscriptions WHERE user_id=? AND is_active=1",
            (user_id,),
        )
        credits = db.fetchone("SELECT balance FROM credits WHERE user_id=?", (user_id,))
        self.assertEqual(sub["used_monthly_credits"], 8)
        self.assertGreaterEqual(float(credits["balance"]), 0)
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM subscriptions WHERE user_id=? AND is_active=1",
                (user_id,),
            )["c"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
