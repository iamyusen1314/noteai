"""A failed user delivery can be refunded without rewriting supplier uncertainty."""

from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
db = importlib.import_module("db")
billing = importlib.import_module("billing")
idempotency = importlib.import_module("idempotency")


class GenerationCustomerSettlementTests(unittest.TestCase):
    def setUp(self):
        self.previous_db = db._DB_PATH
        self.temp = tempfile.TemporaryDirectory()
        db._DB_PATH = Path(self.temp.name) / "settlement.db"
        db.init_db()
        billing.clear_active_usage()
        self.user_id = "settlement-user"
        db.execute(
            "INSERT INTO users(id,username,email,password_hash,password_salt,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (self.user_id, "settlement-user", "settlement@example.invalid",
             "hash", "salt", billing._now()),
        )

    def tearDown(self):
        billing.clear_active_usage()
        db._DB_PATH = self.previous_db
        self.temp.cleanup()

    def claim(self):
        claim = idempotency.claim_and_charge(
            user_id=self.user_id, operation="generate", request_id="one-original-key",
            payload={"video_file_id": "synthetic-video"},
        )
        self.assertEqual(claim["state"], "owner")
        return claim

    def unknown_call(self, claim):
        db.execute(
            "INSERT INTO public_trial_calls(id,budget_id,user_id,request_hash,state,"
            "reserve_milli_cny,created_at,usage_record_id) VALUES(?,?,?,?,?,?,?,?)",
            ("one-original-call", "website-free-product-20260912", self.user_id,
             "synthetic-hash", "unknown", 7167, billing._now(), claim["charge"]["usage_id"]),
        )

    def settlement_kwargs(self, claim):
        row = db.fetchone("SELECT lease_expires_at FROM idempotency_requests WHERE id=?",
                          (claim["request_id"],))
        return dict(
            expected_usage_id=claim["charge"]["usage_id"],
            expected_provider_call_id="one-original-call",
            expected_lease_expires_at=row["lease_expires_at"],
            expected_credits=8,
            original_execution_ended=True,
        )

    def expire(self, claim):
        expiry = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        db.execute("UPDATE idempotency_requests SET lease_expires_at=? WHERE id=?",
                   (expiry, claim["request_id"]))

    def test_original_terminal_failure_refunds_once_but_preserves_unknown_call(self):
        claim = self.claim()
        self.unknown_call(claim)
        with self.assertRaises(HTTPException):
            billing.refund_operation_charge(self.user_id, "generate", claim["charge"], "direct")
        self.assertTrue(idempotency.mark_failed_and_refund(claim, failure_code="stream_failed"))
        self.assertFalse(idempotency.mark_failed_and_refund(claim, failure_code="stream_failed"))
        task = db.fetchone("SELECT status,refund_applied,complete_applied,failure_code FROM "
                           "idempotency_requests WHERE id=?", (claim["request_id"],))
        self.assertEqual(tuple(task), ("failed", 1, 0, "stream_failed"))
        self.assertEqual(billing.get_quota_status(self.user_id)["total_available_credits"], 12)
        self.assertEqual(db.fetchone("SELECT source FROM usage_records WHERE id=?",
                                     (claim["charge"]["usage_id"],))["source"], "refunded")
        supplier = db.fetchone("SELECT state,model_usage_record_id,reserve_milli_cny FROM "
                               "public_trial_calls WHERE id='one-original-call'")
        self.assertEqual(tuple(supplier), ("unknown", None, 7167))

    def test_disconnect_keeps_refund_pending_until_original_execution_is_proven_ended(self):
        claim = self.claim()
        self.unknown_call(claim)
        self.assertTrue(idempotency.mark_failed_and_refund(claim, failure_code="stream_cancelled"))
        before = idempotency.read_failure_settlement(self.user_id, claim["request_id"])
        self.assertEqual((before["business_status"], before["refund_status"]), ("failed", "pending"))
        self.assertEqual(idempotency.reconcile_failed_request(
            self.user_id, claim["request_id"])["refund_status"], "pending")
        self.assertEqual(billing.get_quota_status(self.user_id)["total_available_credits"], 4)
        self.expire(claim)
        kwargs = self.settlement_kwargs(claim)
        with self.assertRaises(ValueError):
            idempotency.reconcile_undelivered_generate(
                self.user_id, claim["request_id"],
                **{**kwargs, "original_execution_ended": False})
        settled = idempotency.reconcile_undelivered_generate(
            self.user_id, claim["request_id"], **kwargs)
        self.assertEqual((settled["business_status"], settled["refund_status"]),
                         ("failed", "refunded"))
        self.assertEqual(billing.get_quota_status(self.user_id)["total_available_credits"], 12)

    def test_expired_original_running_task_requires_exact_identity_and_no_result(self):
        claim = self.claim()
        self.unknown_call(claim)
        kwargs = self.settlement_kwargs(claim)
        with self.assertRaises(ValueError):
            idempotency.reconcile_undelivered_generate(
                self.user_id, claim["request_id"], **kwargs)
        self.expire(claim)
        kwargs = self.settlement_kwargs(claim)
        with self.assertRaises(ValueError):
            idempotency.reconcile_undelivered_generate(
                self.user_id, claim["request_id"],
                **{**kwargs, "expected_provider_call_id": "a-different-call"})
        with self.assertRaises(ValueError):
            idempotency.reconcile_undelivered_generate(
                "another-user", claim["request_id"], **kwargs)
        db.execute(
            "INSERT INTO notes(id,user_id,title,body,source,created_at) VALUES(?,?,?,?,?,?)",
            (claim["request_id"], self.user_id, "saved", "delivered", "generate", billing._now()),
        )
        with self.assertRaises(ValueError):
            idempotency.reconcile_undelivered_generate(
                self.user_id, claim["request_id"], **kwargs)
        db.execute("DELETE FROM notes WHERE id=?", (claim["request_id"],))
        settled = idempotency.reconcile_undelivered_generate(
            self.user_id, claim["request_id"], **kwargs)
        self.assertEqual(settled["refund_status"], "refunded")
        second = idempotency.reconcile_undelivered_generate(
            self.user_id, claim["request_id"], **kwargs)
        self.assertEqual(second["refund_status"], "refunded")
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM usage_records WHERE source='refunded'")["n"], 1)
        self.assertEqual(billing.get_quota_status(self.user_id)["total_available_credits"], 12)
        self.assertEqual(db.fetchone("SELECT state FROM public_trial_calls WHERE id='one-original-call'")["state"], "unknown")


if __name__ == "__main__":
    unittest.main()
