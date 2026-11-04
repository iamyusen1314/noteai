"""Ended delivery releases: real local ledgers and image batch, mock HTTP only."""
import asyncio
import contextlib
from datetime import timedelta
import io
import json
import os
from pathlib import Path
import threading
import unittest
import uuid
from unittest import mock

import httpx
from PIL import Image

from tests import test_postdelivery_reservation as fixture

db, billing, public, settlement = fixture.db, fixture.billing, fixture.public_product, fixture.settlement


class EndedProviderCallRecoveryTests(unittest.TestCase):
    setUp = fixture.PostDeliveryReservationTests.setUp
    tearDown = fixture.PostDeliveryReservationTests.tearDown
    reserve = fixture.PostDeliveryReservationTests.reserve
    use_wallet = fixture.PostDeliveryReservationTests.use_wallet
    wallet = fixture.PostDeliveryReservationTests.wallet
    available = fixture.PostDeliveryReservationTests.available
    recovery_snapshot = fixture.PostDeliveryReservationTests.recovery_snapshot

    def pending(self, claim, *, user=None, state="dispatched", reserve=10080):
        call = str(uuid.uuid4())
        db.execute("INSERT INTO public_trial_calls(id,budget_id,user_id,request_hash,state,"
            "reserve_milli_cny,created_at,usage_record_id,provenance_json) VALUES(?,?,?,?,?,?,?,?,?)",
            (call, public.BUDGET_ID, user or self.user, "historical-original", state, reserve,
             billing._now(), claim["charge"]["usage_id"], '{"fixture":"retained"}'))
        db.execute("UPDATE public_trial_budget SET reserved_milli_cny=reserved_milli_cny+? WHERE id=?",
            (reserve, public.BUDGET_ID))
        return call

    def expire(self, claim):
        db.execute("UPDATE idempotency_requests SET lease_expires_at=? WHERE id=?",
            ((fixture.idempotency._now() - timedelta(seconds=5)).isoformat(), claim["request_id"]))

    def recover(self, claim, *, args=None, ended=True):
        snapshot, calls = self.recovery_snapshot(claim) if args is None else args
        return settlement.reconcile_undelivered_reservation(self.user, claim["request_id"],
            expected_snapshot=snapshot, expected_provider_calls=calls, original_execution_ended=ended)

    def test_exact_ended_release_quarantines_once_preserving_unknown_and_all_money(self):
        self.use_wallet(8); claim = self.reserve()
        call = self.pending(claim)
        old_unknown = self.pending(claim, state="unknown", reserve=2753)
        self.expire(claim); args = self.recovery_snapshot(claim)
        before = {row["id"]: dict(row) for row in db.fetchall("SELECT * FROM public_trial_calls")}
        budget = dict(db.fetchone("SELECT * FROM public_trial_budget WHERE id=?", (public.BUDGET_ID,)))
        with self.assertRaises(ValueError):
            self.recover(claim, args=args, ended=False)
        self.assertEqual(self.available()["wallet_held"], 8)
        for _ in range(2):
            self.assertEqual(self.recover(claim, args=args)["status"], "released")
        after = {row["id"]: dict(row) for row in db.fetchall("SELECT * FROM public_trial_calls")}
        self.assertEqual(after[call], {**before[call], "state": "unknown"})
        self.assertEqual(after[old_unknown], before[old_unknown])
        self.assertEqual(dict(db.fetchone("SELECT * FROM public_trial_budget WHERE id=?", (public.BUDGET_ID,))), budget)
        self.assertEqual(self.wallet(), {"balance": 8, "total_used": 0})
        self.assertEqual(self.available()["wallet_held"], 0)
        financial = db.fetchone("SELECT refund_applied,complete_applied FROM idempotency_requests WHERE id=?",
                               (claim["request_id"],))
        self.assertEqual(tuple(financial), (1, 0))
        self.assertEqual(db.fetchone("SELECT credits_used FROM usage_records WHERE id=?",
                         (claim["charge"]["usage_id"],))[0], 0)
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM model_usage_records")[0], 0)

    def test_normal_ended_failure_releases_eight_once_without_replaying_or_charging(self):
        self.use_wallet(8); claim = self.reserve(); call = self.pending(claim)
        before = dict(db.fetchone("SELECT * FROM public_trial_calls WHERE id=?", (call,)))
        for _ in range(2):
            self.assertEqual(settlement.release_undelivered(claim,
                original_execution_ended=True)["status"], "released")
        self.assertEqual(dict(db.fetchone("SELECT * FROM public_trial_calls WHERE id=?", (call,))),
                         {**before, "state": "unknown"})
        self.assertEqual(self.wallet(), {"balance": 8, "total_used": 0})
        self.assertEqual(self.available()["wallet_held"], 0)
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM model_usage_records")[0], 0)

    def test_other_usage_and_other_user_calls_are_untouched(self):
        self.use_wallet(16); first = self.reserve(); second = self.reserve()
        target = self.pending(first)
        sibling = self.pending(second)
        db.execute("INSERT INTO users(id,username,email,password_hash,password_salt,created_at)VALUES(?,?,?,?,?,?)",
            ("other-owner", "other-owner", "other@example.invalid", "fixture", "fixture", billing._now()))
        foreign = self.pending(second, user="other-owner", state="unknown")
        before = {row["id"]: dict(row) for row in db.fetchall("SELECT * FROM public_trial_calls")}
        self.expire(first); self.recover(first)
        after = {row["id"]: dict(row) for row in db.fetchall("SELECT * FROM public_trial_calls")}
        self.assertEqual(after[target], {**before[target], "state": "unknown"})
        self.assertEqual(after[sibling], before[sibling]); self.assertEqual(after[foreign], before[foreign])
        self.assertEqual(self.available()["wallet_held"], 8)

    def test_inconsistent_dispatched_response_or_metering_rolls_back_entire_release(self):
        self.use_wallet(8); claim = self.reserve(); call = self.pending(claim)
        self.expire(claim)
        for kind in ("response", "metering"):
            with self.subTest(kind=kind):
                if kind == "response":
                    db.execute("UPDATE public_trial_calls SET http_status=200 WHERE id=?", (call,))
                else:
                    marker = billing._ACTIVE_USAGE_ID.set(claim["charge"]["usage_id"])
                    try:
                        billing.record_model_usage("doubao", "doubao-seed-2-0-lite-260428",
                            tokens_in=100, tokens_out=10, usage_status="complete", physical_call_id=call)
                    finally:
                        billing._ACTIVE_USAGE_ID.reset(marker)
                args = self.recovery_snapshot(claim)
                before = dict(db.fetchone("SELECT * FROM public_trial_calls WHERE id=?", (call,)))
                with self.assertRaisesRegex(ValueError, "outcome requires reconciliation"):
                    self.recover(claim, args=args)
                self.assertEqual(self.available()["wallet_held"], 8)
                self.assertEqual(tuple(db.fetchone("SELECT status,refund_applied FROM idempotency_requests WHERE id=?",
                                 (claim["request_id"],))), ("running", 0))
                self.assertEqual(dict(db.fetchone("SELECT * FROM public_trial_calls WHERE id=?", (call,))), before)
                if kind == "response":
                    db.execute("UPDATE public_trial_calls SET http_status=NULL WHERE id=?", (call,))

    def test_live_saved_and_durable_work_cannot_be_quarantined(self):
        self.use_wallet(8); claim = self.reserve(); call = self.pending(claim)
        with db.transaction(write=True) as tx:
            row = dict(tx.fetchone("SELECT * FROM idempotency_requests WHERE id=?", (claim["request_id"],)))
            with self.assertRaises(ValueError):
                public._quarantine_ended_reservation_calls(tx, row, original_execution_ended=True)
        with self.assertRaises(ValueError):
            self.recover(claim)  # An unexpired lease alone never authorizes release.
        self.expire(claim)
        db.execute("INSERT INTO notes(id,user_id,title,body,source,created_at)VALUES(?,?,?,?,?,?)",
            (claim["request_id"], self.user, "saved", "saved", "generate", billing._now()))
        with self.assertRaisesRegex(ValueError, "note exists"):
            self.recover(claim)
        db.execute("DELETE FROM notes WHERE id=?", (claim["request_id"],))
        operation = str(uuid.uuid4()); now = billing._now()
        db.execute("INSERT INTO ai_operations(id,subject_hash,request_hash,operation_kind,available_at,created_at,updated_at)"
                   "VALUES(?,?,?,?,?,?,?)", (operation, "a" * 64, "b" * 64, "generate", now, now, now))
        db.execute("INSERT INTO ai_operation_admissions(operation_id,idempotency_request_id,created_at)VALUES(?,?,?)",
                   (operation, claim["request_id"], now))
        with self.assertRaisesRegex(ValueError, "durable operation"):
            self.recover(claim)
        self.assertEqual(self.available()["wallet_held"], 8)
        self.assertEqual(db.fetchone("SELECT state FROM public_trial_calls WHERE id=?", (call,))[0], "dispatched")

    def test_recovered_slot_allows_original_two_parallel_workers_and_all_nine_images(self):
        from tests.test_generation_multiuser_admission import api, ark, admission
        self.use_wallet(8); claim = self.reserve(); call = self.pending(claim)
        self.expire(claim); self.recover(claim)
        old = dict(db.fetchone("SELECT * FROM public_trial_calls WHERE id=?", (call,)))
        billing.record_free_usage(self.user, "generate"); usage = billing._ACTIVE_USAGE_ID.get()
        marker = public._invocation.set(public.Invocation(self.user, "new-complete-nine", route="/generate/stream"))
        lock = threading.Lock(); first_pair = threading.Barrier(2); sent = []; active = maximum = 0
        def supplier(request):
            nonlocal active, maximum
            with lock:
                ordinal = len(sent); sent.append(request.url.path)
                active += 1; maximum = max(maximum, active)
            try:
                if ordinal < 2:
                    first_pair.wait(timeout=5)
                return httpx.Response(200, json={"model": ark.MODEL,
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                              "prompt_tokens_details": {"cached_tokens": 0}},
                    "choices": [{"finish_reason": "stop", "message": {"content": "庭院木桥光线和真实照片内容清晰可见。"}}]})
            finally:
                with lock:
                    active -= 1
        def client(**kwargs):
            return httpx.Client(transport=httpx.MockTransport(supplier), trust_env=False)
        async def summary(*args, **kwargs):
            return "<scene>庭院木桥光线</scene><hooks>真实素材画面</hooks>"
        image = io.BytesIO(); Image.new("RGB", (20, 20), "white").save(image, "PNG")
        try:
            with contextlib.ExitStack() as stack:
                stack.enter_context(mock.patch.dict(os.environ, {"NOTEAI_PUBLIC_PRODUCT": "1",
                    "NOTEAI_ARK_API_KEY": "synthetic-offline-only"}))
                db.execute("UPDATE public_trial_budget SET enabled=1,policy_mode='owner_metered'")
                stack.enter_context(mock.patch.object(admission, "_instance",
                    admission.Admission(admission.Limits(physical=2, doubao=2, media_workers=2))))
                stack.enter_context(mock.patch.object(ark, "_client", side_effect=client))
                stack.enter_context(mock.patch.object(api, "_read_image_input", return_value=image.getvalue()))
                stack.enter_context(mock.patch.object(api, "_runtime_prompt", return_value="合成技术视觉{domain}"))
                stack.enter_context(mock.patch.object(api._mr, "call", side_effect=summary))
                result = asyncio.run(api._generation_visual_batch(
                    ["photo-" + str(i) for i in range(9)], "休闲娱乐体验", "本机合成技术夹具", {}))
        finally:
            public._invocation.reset(marker)
        self.assertEqual(len(sent), 9); self.assertEqual(maximum, 2)
        self.assertEqual(len(result), 9); self.assertTrue(all(isinstance(x, (str, dict)) for x in result))
        self.assertEqual(dict(db.fetchone("SELECT * FROM public_trial_calls WHERE id=?", (call,))), old)
        rows = db.fetchall("SELECT state,http_status,model_usage_record_id FROM public_trial_calls WHERE usage_record_id=?",
                           (usage,))
        self.assertEqual(len(rows), 9)
        self.assertTrue(all(row["state"] == "responded" and row["http_status"] == 200
                            and row["model_usage_record_id"] for row in rows))
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM public_trial_calls WHERE state='dispatched'")[0], 0)


if __name__ == "__main__":
    unittest.main()
