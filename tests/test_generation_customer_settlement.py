"""A failed user delivery can be refunded without rewriting supplier uncertainty."""

from __future__ import annotations

import importlib
import json
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
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
        for changed in (
            {"expected_provider_call_id": "another-call"},
            {"expected_lease_expires_at": "2026-01-01T00:00:00+00:00"},
            {"expected_credits": 9},
        ):
            with self.assertRaises(ValueError):
                idempotency.reconcile_undelivered_generate(
                    self.user_id, claim["request_id"], **{**kwargs, **changed})
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM usage_records WHERE source='refunded'")["n"], 1)
        self.assertEqual(billing.get_quota_status(self.user_id)["total_available_credits"], 12)
        self.assertEqual(db.fetchone("SELECT state FROM public_trial_calls WHERE id='one-original-call'")["state"], "unknown")

    def mixed_failed_claim(self):
        claim = self.claim()
        usage_id = claim["charge"]["usage_id"]
        for index in range(6):
            call_id = f"original-call-{index}"
            model_id = f"original-model-{index}" if index < 5 else None
            if model_id:
                db.execute("INSERT INTO model_usage_records(id,usage_record_id,provider,model,"
                           "input_tokens,output_tokens,known_cost_rmb,usage_status,recorded_at,"
                           "price_currency,usd_cny,price_version,pricing_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (model_id, usage_id, "doubao", "synthetic-model", 6000 + index, 60 + index,
                           .004 + index / 1000000, "complete", billing._now(), "CNY", 1.0, "synthetic", "exact"))
            db.execute("INSERT INTO public_trial_calls(id,budget_id,user_id,request_hash,state,"
                       "reserve_milli_cny,http_status,created_at,usage_record_id,model_usage_record_id,"
                       "usage_fingerprint) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (call_id,
                       "website-free-product-20260912", self.user_id, "synthetic-hash",
                       "responded" if model_id else "dispatched", 517, 200 if model_id else None,
                       billing._now(), usage_id, model_id, "a" * 64 if model_id else None))
        self.assertTrue(idempotency.mark_failed_and_refund(claim, failure_code="stream_cancelled"))
        self.expire(claim)
        row = db.fetchone("SELECT * FROM idempotency_requests WHERE id=?", (claim["request_id"],))
        manifest = [dict(row) for row in db.fetchall("SELECT id,state,http_status,model_usage_record_id "
                                                    "FROM public_trial_calls ORDER BY id")]
        kwargs = dict(expected_usage_id=usage_id, expected_provider_calls=manifest,
                      expected_lease_expires_at=row["lease_expires_at"], expected_credits=8,
                      expected_subscription_id=row["charged_subscription_id"],
                      expected_period_start=row["charged_period_start"], original_execution_ended=True)
        return claim, kwargs

    def supplier_snapshot(self):
        return ([dict(row) for row in db.fetchall("SELECT * FROM public_trial_calls ORDER BY id")],
                [dict(row) for row in db.fetchall("SELECT * FROM model_usage_records ORDER BY id")])

    def test_mixed_six_call_settlement_refunds_once_and_preserves_failure_clock_and_supplier_facts(self):
        claim, kwargs = self.mixed_failed_claim()
        before = self.supplier_snapshot()
        failed_at = db.fetchone("SELECT failed_at FROM idempotency_requests WHERE id=?",
                               (claim["request_id"],))["failed_at"]
        first = idempotency.reconcile_undelivered_generate_calls(self.user_id, claim["request_id"], **kwargs)
        second = idempotency.reconcile_undelivered_generate_calls(self.user_id, claim["request_id"], **kwargs)
        self.assertEqual(first, second)
        self.assertEqual(first["refund_status"], "refunded")
        self.assertEqual(billing.get_quota_status(self.user_id)["total_available_credits"], 12)
        self.assertEqual(before, self.supplier_snapshot())
        final = db.fetchone("SELECT failed_at,refunded_at,failure_code FROM idempotency_requests WHERE id=?",
                            (claim["request_id"],))
        self.assertEqual(final["failed_at"], failed_at)
        self.assertIsNotNone(final["refunded_at"])
        self.assertEqual(final["failure_code"], "stream_cancelled")
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM usage_records WHERE source='refunded'")["n"], 1)

    def test_mixed_manifest_and_charge_identity_must_match_even_after_refund(self):
        claim, kwargs = self.mixed_failed_claim()
        changed_call = {**kwargs["expected_provider_calls"][-1], "state": "unknown"}
        changes = [
            {"expected_usage_id": "different-usage"}, {"expected_credits": 9},
            {"expected_subscription_id": "different-subscription"},
            {"expected_period_start": "2000-01-01T00:00:00Z"},
            {"expected_lease_expires_at": "2000-01-01T00:00:00Z"},
            {"expected_provider_calls": kwargs["expected_provider_calls"][:-1]},
            {"expected_provider_calls": [*kwargs["expected_provider_calls"][:-1], changed_call]},
            {"expected_provider_calls": [*kwargs["expected_provider_calls"], changed_call]},
            {"expected_provider_calls": []}, {"expected_provider_calls": [changed_call] * 65},
            {"expected_credits": float("nan")}, {"expected_credits": True},
        ]
        for refunded in (False, True):
            if refunded:
                idempotency.reconcile_undelivered_generate_calls(self.user_id, claim["request_id"], **kwargs)
            for changed in changes:
                with self.subTest(refunded=refunded, changed=changed), self.assertRaises(ValueError):
                    idempotency.reconcile_undelivered_generate_calls(
                        self.user_id, claim["request_id"], **{**kwargs, **changed})
            with self.assertRaises(ValueError):
                idempotency.reconcile_undelivered_generate_calls("another-user", claim["request_id"], **kwargs)

    def test_mixed_original_must_be_failed_expired_and_confirmed_ended(self):
        claim, kwargs = self.mixed_failed_claim()
        for changed in ({"original_execution_ended": False}, {"original_execution_ended": 1}):
            with self.assertRaises(ValueError):
                idempotency.reconcile_undelivered_generate_calls(
                    self.user_id, claim["request_id"], **{**kwargs, **changed})
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        db.execute("UPDATE idempotency_requests SET lease_expires_at=? WHERE id=?", (future, claim["request_id"]))
        with self.assertRaises(ValueError):
            idempotency.reconcile_undelivered_generate_calls(self.user_id, claim["request_id"],
                **{**kwargs, "expected_lease_expires_at": future})
        db.execute("UPDATE idempotency_requests SET lease_expires_at=?,status='running' WHERE id=?",
                   (kwargs["expected_lease_expires_at"], claim["request_id"]))
        with self.assertRaises(ValueError):
            idempotency.reconcile_undelivered_generate_calls(self.user_id, claim["request_id"], **kwargs)
        self.assertEqual(billing.get_quota_status(self.user_id)["total_available_credits"], 4)

    def test_mixed_saved_result_or_live_durable_admission_blocks_refund(self):
        claim, kwargs = self.mixed_failed_claim()
        now = billing._now()
        db.execute("INSERT INTO notes(id,user_id,title,body,source,created_at) VALUES(?,?,?,?,?,?)",
                   (claim["request_id"], self.user_id, "saved", "delivered", "generate", now))
        with self.assertRaises(ValueError):
            idempotency.reconcile_undelivered_generate_calls(self.user_id, claim["request_id"], **kwargs)
        db.execute("DELETE FROM notes WHERE id=?", (claim["request_id"],))
        for context in ({"task_continuation": {"status": "completed"}},
                        {"task_continuation": {"result": {"title": "delivered"}}}, "corrupt-json"):
            db.execute("INSERT INTO chat_sessions(id,user_id,generate_ctx_json,created_at,updated_at) "
                       "VALUES(?,?,?,?,?)", (claim["request_id"], self.user_id,
                       context if isinstance(context, str) else json.dumps(context), now, now))
            with self.assertRaises(ValueError):
                idempotency.reconcile_undelivered_generate_calls(self.user_id, claim["request_id"], **kwargs)
            db.execute("DELETE FROM chat_sessions WHERE id=?", (claim["request_id"],))
        operation_id = "11111111-1111-4111-8111-111111111111"
        db.execute("INSERT INTO ai_operations(id,subject_hash,request_hash,operation_kind,"
                   "available_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                   (operation_id, "a" * 64, "b" * 64, "generate", now, now, now))
        db.execute("INSERT INTO ai_operation_admissions(operation_id,idempotency_request_id,created_at) "
                   "VALUES(?,?,?)", (operation_id, claim["request_id"], now))
        with self.assertRaises(ValueError):
            idempotency.reconcile_undelivered_generate_calls(self.user_id, claim["request_id"], **kwargs)
        self.assertEqual(billing.get_quota_status(self.user_id)["total_available_credits"], 4)

    def test_concurrent_mixed_settlement_restores_only_original_eight(self):
        claim, kwargs = self.mixed_failed_claim()
        before = self.supplier_snapshot()
        barrier = threading.Barrier(2)
        def settle():
            barrier.wait(timeout=3)
            return idempotency.reconcile_undelivered_generate_calls(self.user_id, claim["request_id"], **kwargs)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: settle(), range(2)))
        self.assertTrue(all(result["refund_status"] == "refunded" for result in results))
        self.assertEqual(billing.get_quota_status(self.user_id)["total_available_credits"], 12)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM usage_records WHERE source='refunded'")["n"], 1)
        self.assertEqual(before, self.supplier_snapshot())


if __name__ == "__main__":
    unittest.main()
