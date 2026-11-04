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


    def test_live_cover_and_old_orphan_block_zero_calls_then_exact_recovery_keeps_all_nine(self):
        from tests.test_generation_multiuser_admission import api, ark, admission
        from tests.test_cover_jobs import CoverJobsTests
        import cover_jobs
        import cover_agent_provider
        import private_storage
        from datetime import datetime, timezone
        from decimal import Decimal, ROUND_CEILING
        self.use_wallet(8); ended = self.reserve(); orphan = self.pending(ended)
        self.expire(ended); original_args = self.recovery_snapshot(ended)
        before_orphan = dict(db.fetchone("SELECT * FROM public_trial_calls WHERE id=?", (orphan,)))
        normal_user, cover_user = "normal-p1-owner", "live-cover-owner"
        for user in (normal_user, cover_user):
            db.execute("INSERT INTO users(id,username,email,password_hash,password_salt,created_at)VALUES(?,?,?,?,?,?)",
                (user, user, user + "@example.invalid", "fixture", "fixture", billing._now()))
            billing.get_subscription(user); billing.grant_credits(user, 64, "isolated coupling fixture")
        normal = settlement.reserve_claim(user_id=normal_user, operation="generate",
            request_id="original-normal-nine", payload={"fixture": "same nine inputs"})
        normal_usage = normal["charge"]["usage_id"]
        manager = admission.Admission(admission.Limits(physical=2, doubao=2, media_workers=2))
        ready, finish = threading.Event(), threading.Event()
        cover_call = str(uuid.uuid4()); cover_errors = []
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {"NOTEAI_PUBLIC_PRODUCT": "1",
                "NOTEAI_ARK_API_KEY": "synthetic-offline-only"}))
            stack.enter_context(mock.patch.object(admission, "_instance", manager))
            db.execute("UPDATE public_trial_budget SET enabled=1,policy_mode='owner_metered'")
            cover_jobs.init_sqlite_schema()
            private_storage.configure_object_backend(private_storage.InMemoryObjectBackend(),
                                                     key_epoch="coupling-fixture")
            stack.callback(private_storage.reset_object_backend)
            cover = CoverJobsTests()
            cover.user = cover_user; cover.now = datetime.now(timezone.utc)
            cover.report = str(uuid.uuid4()); cover.index = 0
            db.execute("INSERT INTO saved_diagnoses(id,user_id,note_title,domain,diagnosis_json,created_at)"
                "VALUES(?,?,?,?,?,?)", (cover.report, cover_user, "synthetic", "休闲娱乐体验", "{}", billing._now()))
            cover.source = cover.image(cover_user, small=True)
            cover.input = {"note_title": "synthetic", "note_body": "isolated original", "visual_advice": "real pixels"}
            cover.policy = {"enabled": True, "operation": "cover_generate", "provider": "seedream",
                "model_id": cover_jobs.MODEL_ID, "width": 1776, "height": 2368, "credits": 8,
                "retention_seconds": 3 * 86400, "max_physical_calls": None, "max_image_calls": 1,
                "budget_id": cover_jobs.FORMAL_BUDGET_ID, "design_version": 3,
                "workflow_engine": "editable_design_opencode_v1", "design_model": cover_agent_provider.MODEL}
            _, cover_claim = cover.claim()
            operation, owns = manager.register(cover_user, "c" * 64, route="/covers")
            self.assertTrue(owns)
            def live_cover():
                inv = public.Invocation(cover_user, cover_claim["request_id"], route="/covers",
                    budget_id=cover_jobs.FORMAL_BUDGET_ID, admission_state=operation)
                im = public._invocation.set(inv)
                um = billing._ACTIVE_USAGE_ID.set(cover_claim["charge"]["usage_id"])
                try:
                    with public.model_admission_sync(cover_call, "doubao"):
                        cover_jobs.before_text_call(cover_claim, "design:1", cover_call)
                        reserve = int((Decimal(cover_agent_provider.estimate()["estimated_cost"]) * 1000)
                                      .to_integral_value(rounding=ROUND_CEILING))
                        public._reserve_payload({"model": cover_agent_provider.MODEL, "provider": "doubao",
                            "modality": "image", "max_tokens": cover_agent_provider.MAX_OUTPUT_TOKENS},
                            reserve, call_id=cover_call, require_metered=True)
                        public.mark_model_dispatched(cover_call)
                        ready.set()
                        if not finish.wait(15):
                            raise AssertionError("Controlled live cover fixture was not released")
                except BaseException as exc:
                    cover_errors.append(exc); ready.set()
                finally:
                    billing._ACTIVE_USAGE_ID.reset(um); public._invocation.reset(im)
                    manager.finish(operation)
            worker = threading.Thread(target=live_cover)
            worker.start()
            try:
                self.assertTrue(ready.wait(5))
                self.assertEqual(cover_errors, [])
                live_row = dict(db.fetchone("SELECT * FROM public_trial_calls WHERE id=?", (cover_call,)))
                live_parent = dict(db.fetchone("SELECT * FROM cover_jobs WHERE id=?", (cover_claim["request_id"],)))
                self.assertEqual(live_row["state"], "dispatched")
                self.assertEqual(db.fetchone("SELECT COUNT(*) FROM public_trial_calls WHERE state='dispatched'")[0], 2)
                with manager.calls.lock:
                    ticket = manager.calls.active[cover_call]
                    self.assertTrue(ticket.dispatched); self.assertFalse(ticket.closed)
                pixel = io.BytesIO(); Image.new("RGB", (20, 20), "white").save(pixel, "PNG")
                sent, observed, busy_snapshots = [], [], []
                original_reserve = public._reserve_payload
                def inspect_reserve(*args, **kwargs):
                    try:
                        return original_reserve(*args, **kwargs)
                    except public._SlotsBusy:
                        with manager.calls.lock:
                            busy_snapshots.append({"live_tickets": [(t.call_id, t.operation.user_id) for t in manager.calls.active.values()],
                                "rows": [dict(row) for row in db.fetchall("SELECT id,user_id,state,http_status FROM public_trial_calls WHERE state='dispatched'")]})
                        raise
                stack.enter_context(mock.patch.object(public, "_reserve_payload", side_effect=inspect_reserve))
                active = maximum_normal = maximum_global = 0
                lock = threading.Lock()
                def supplier(request):
                    nonlocal active, maximum_normal, maximum_global
                    with lock:
                        sent.append(request.url.path); active += 1
                        maximum_normal = max(maximum_normal, active)
                        maximum_global = max(maximum_global, active + 1)  # Genuine held cover ticket.
                    try:
                        self.assertLessEqual(db.fetchone("SELECT COUNT(*) FROM public_trial_calls WHERE state='dispatched'")[0], 2)
                        return httpx.Response(200, json={"model": ark.MODEL,
                            "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                                      "prompt_tokens_details": {"cached_tokens": 0}},
                            "choices": [{"finish_reason": "stop", "message": {"content": "庭院木桥和光线均为清晰可见的真实素材。"}}]})
                    finally:
                        with lock: active -= 1
                def client(**kwargs):
                    return httpx.Client(transport=httpx.MockTransport(supplier), trust_env=False)
                def pixels(name):
                    observed.append(name); return pixel.getvalue()
                async def summary(*args, **kwargs):
                    return "<scene>庭院木桥光线</scene><hooks>真实素材画面</hooks>"
                stack.enter_context(mock.patch.object(ark, "_client", side_effect=client))
                stack.enter_context(mock.patch.object(api, "_read_image_input", side_effect=pixels))
                stack.enter_context(mock.patch.object(api, "_runtime_prompt", return_value="合成技术视觉{domain}"))
                stack.enter_context(mock.patch.object(api._mr, "call", side_effect=summary))
                inputs = ["photo-" + str(i) for i in range(9)]
                invocation = public.Invocation(normal_user, normal["request_id"], route="/generate/stream")
                im = public._invocation.set(invocation); um = billing._ACTIVE_USAGE_ID.set(normal_usage)
                try:
                    failed = asyncio.run(api._generation_visual_batch(inputs, "休闲娱乐体验", "合成九图", {}))
                    self.assertTrue(any(isinstance(value, public.TrialProviderStopped)
                        and value.args == ("MODEL_ADMISSION_UNRECONCILED",) for value in failed))
                    self.assertEqual(sent, [])
                    self.assertEqual(db.fetchone("SELECT COUNT(*) FROM public_trial_calls WHERE usage_record_id=?",
                                     (normal_usage,))[0], 0)
                    with manager.calls.lock:
                        self.assertEqual(set(manager.calls.active), {cover_call})
                    self.assertEqual(invocation.failure, "MODEL_ADMISSION_UNRECONCILED")
                    settlement.release_undelivered(normal, original_execution_ended=True)
                    failed_usage = normal_usage
                    self.assertEqual(tuple(db.fetchone("SELECT status,refund_applied FROM idempotency_requests WHERE id=?",
                                     (normal["request_id"],))), ("failed", 1))
                    self.recover(ended, args=original_args)
                    self.assertEqual(dict(db.fetchone("SELECT * FROM public_trial_calls WHERE id=?", (orphan,))),
                                     {**before_orphan, "state": "unknown"})
                    # Failed Invocation remains fenced. Compare a distinct local
                    # claim using the same nine inputs, never revive an old task.
                    normal = settlement.reserve_claim(user_id=normal_user, operation="generate",
                        request_id="fresh-normal-nine-after-capacity", payload={"fixture": "same nine inputs"})
                    normal_usage = normal["charge"]["usage_id"]
                    fresh = public.Invocation(normal_user, normal["request_id"], route="/generate/stream")
                    ni = public._invocation.set(fresh); nu = billing._ACTIVE_USAGE_ID.set(normal_usage)
                    normal_before = dict(db.fetchone("SELECT * FROM idempotency_requests WHERE id=?", (normal["request_id"],)))
                    usage_before = dict(db.fetchone("SELECT * FROM usage_records WHERE id=?", (normal_usage,)))
                    try:
                        observed.clear()
                        result = asyncio.run(api._generation_visual_batch(inputs, "休闲娱乐体验", "合成九图", {}))
                        self.assertEqual(len(result), 9)
                        self.assertTrue(all(isinstance(value, (str, dict)) for value in result),
                            {"results": [(type(value).__name__, value.args) for value in result if isinstance(value, Exception)],
                             "busy": busy_snapshots, "sent": len(sent)})
                        self.assertEqual(sorted(observed), sorted(inputs))
                        self.assertEqual(len(sent), 9)
                        self.assertEqual((maximum_normal, maximum_global), (1, 2))
                        self.assertEqual(dict(db.fetchone("SELECT * FROM idempotency_requests WHERE id=?",
                                         (normal["request_id"],))), normal_before)
                        self.assertEqual(db.fetchone("SELECT credits_used FROM usage_records WHERE id=?", (normal_usage,))[0],
                                         usage_before["credits_used"])
                        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM usage_records WHERE user_id=? AND operation='generate'",
                                         (normal_user,))[0], 2)
                        self.assertEqual(db.fetchone("SELECT credits_used FROM usage_records WHERE id=?", (failed_usage,))[0], 0)
                        self.assertEqual(invocation.failure, "MODEL_ADMISSION_UNRECONCILED")
                        with db.transaction(write=True) as tx:
                            sub = billing._get_subscription_tx(tx, normal_user)
                            availability = settlement.availability_in_transaction(tx, normal_user, sub)
                        self.assertEqual(availability["monthly_held"] + availability["wallet_held"], 8)
                    finally:
                        billing._ACTIVE_USAGE_ID.reset(nu); public._invocation.reset(ni)
                finally:
                    billing._ACTIVE_USAGE_ID.reset(um); public._invocation.reset(im)
                self.assertEqual(dict(db.fetchone("SELECT * FROM public_trial_calls WHERE id=?", (cover_call,))), live_row)
                self.assertEqual(dict(db.fetchone("SELECT * FROM cover_jobs WHERE id=?", (cover_claim["request_id"],))), live_parent)
                with manager.calls.lock:
                    self.assertIs(manager.calls.active[cover_call], ticket)
                    self.assertFalse(ticket.closed)
                rows = db.fetchall("SELECT state,http_status,model_usage_record_id FROM public_trial_calls WHERE usage_record_id=?",
                                   (normal_usage,))
                self.assertEqual(len(rows), 9)
                self.assertTrue(all(row["state"] == "responded" and row["http_status"] == 200
                                    and row["model_usage_record_id"] for row in rows))
            finally:
                finish.set(); worker.join(5)
            self.assertFalse(worker.is_alive()); self.assertEqual(cover_errors, [])


if __name__ == "__main__":
    unittest.main()
