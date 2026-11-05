"""Shared model admission integration: isolated ledgers and queues, no supplier.

These cases exercise the common rate/money/call transaction and real queue
contracts. Ten mixed users below are a scheduling fixture, not throughput or
complete article/cover acceptance, and retain the real 30 RPM / 1800 s settings.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import asyncio
import hashlib
import json
import os
import socket
import threading
import time
import unittest
import uuid
from unittest import mock

from tests import test_postdelivery_reservation as fixture

db, billing, public = fixture.db, fixture.billing, fixture.public_product
import model_admission as admission
import model_capacity as capacity

LITE = "doubao-seed-2-0-lite-260428"
PRO = "doubao-seed-2-1-pro-260915"
IMAGE = "doubao-seedream-5-0-pro-260628"


class CapacitySharedAdmissionTests(unittest.TestCase):
    reserve = fixture.PostDeliveryReservationTests.reserve
    use_wallet = fixture.PostDeliveryReservationTests.use_wallet
    available = fixture.PostDeliveryReservationTests.available

    def setUp(self):
        fixture.PostDeliveryReservationTests.setUp(self)
        self.environment = mock.patch.dict(os.environ, {
            "NOTEAI_PUBLIC_PRODUCT": "1", "NOTEAI_MODEL_CAPACITY_ENABLED": "1",
            "NOTEAI_MODEL_CAPACITY_SCOPE": "ark-primary",
            "NOTEAI_MODEL_CAPACITY_LIMITS_JSON": "",
            "NOTEAI_MODEL_REMOTE_CONCURRENCY": "16",
            "NOTEAI_MODEL_PHYSICAL_CONCURRENCY": "2", "NOTEAI_CLAUDE_CONCURRENCY": "2",
            "NOTEAI_KIMI_TEXT_CONCURRENCY": "2", "NOTEAI_DOUBAO_CONCURRENCY": "2",
            "NOTEAI_SEEDREAM_CONCURRENCY": "1",
            "NOTEAI_CLAUDE_GATEWAY_REQUESTS_PER_MINUTE": "30",
            "NOTEAI_MODEL_QUEUE_SECONDS": "1800", "NOTEAI_MODEL_NO_PROGRESS_SECONDS": "300",
        })
        self.environment.start()
        self.sockets = [mock.patch.object(socket.socket, name,
            side_effect=AssertionError("No external socket allowed")) for name in ("connect", "connect_ex")]
        for patch in self.sockets:
            patch.start()
        self.use_wallet(1000)
        db.execute("UPDATE public_trial_budget SET enabled=1,policy_mode='owner_metered'")

    def tearDown(self):
        for patch in reversed(self.sockets):
            patch.stop()
        self.environment.stop()
        fixture.PostDeliveryReservationTests.tearDown(self)

    @contextmanager
    def owner(self, manager, *, claim=None):
        claim = claim or self.reserve()
        operation, owns = manager.register(self.user,
            hashlib.sha256(claim["request_id"].encode()).hexdigest(), route="/generate/stream")
        self.assertTrue(owns)
        invocation = public.Invocation(self.user, claim["request_id"], route="/generate/stream",
                                       admission_state=operation)
        marker = public._invocation.set(invocation)
        usage = billing._ACTIVE_USAGE_ID.set(claim["charge"]["usage_id"])
        with mock.patch.object(admission, "_instance", manager):
            try:
                yield claim, invocation, operation
            finally:
                billing._ACTIVE_USAGE_ID.reset(usage)
                public._invocation.reset(marker)
                manager.finish(operation)

    def payload(self, model=LITE):
        image = model == IMAGE
        return {"model": model, "provider": "seedream" if image else "doubao",
                "modality": "image", "max_tokens": 0 if image else 20,
                "_capacity_demand": capacity.Demand(model, 0 if image else 100, 0 if image else 20, 1 if image else 0),
                "_capacity_estimate_basis": "isolated_integration_fixture"}

    def money(self):
        return dict(db.fetchone("SELECT * FROM public_trial_budget WHERE id=?", (public.BUDGET_ID,)))

    def buckets(self):
        return [dict(row) for row in db.fetchall("SELECT * FROM model_capacity_buckets ORDER BY scope_key,quota_key,slot")]

    def seed_full_lite_window(self, timestamp):
        policy = capacity.policy_for(LITE)
        second = int(timestamp)
        db.execute("INSERT INTO model_capacity_buckets(scope_key,quota_key,slot,epoch_second,request_count,token_bound,image_count,input_bound,output_bound) VALUES(?,?,?,?,?,?,?,?,?)",
            (policy.scope_key, policy.quota_key, second % 61, second, 30000, 5000000, 0, 5000000, 0))

    def retained_unknown(self, claim):
        call_id = "historical-unknown-" + uuid.uuid4().hex
        db.execute("INSERT INTO public_trial_calls(id,budget_id,user_id,request_hash,state,"
            "reserve_milli_cny,created_at,usage_record_id,provenance_json) VALUES(?,?,?,?,?,?,?,?,?)",
            (call_id, public.BUDGET_ID, self.user, "older-task-hash", "unknown", 10080,
             billing._now(), claim["charge"]["usage_id"], '{"original":"unchanged"}'))
        db.execute("UPDATE public_trial_budget SET reserved_milli_cny=reserved_milli_cny+10080 WHERE id=?",
                   (public.BUDGET_ID,))
        return dict(db.fetchone("SELECT * FROM public_trial_calls WHERE id=?", (call_id,)))

    def test_mode_zero_keeps_original_two_call_guard_and_no_quota_buckets(self):
        os.environ["NOTEAI_MODEL_CAPACITY_ENABLED"] = "0"
        manager = admission.Admission()
        self.assertEqual((manager.calls.capacity, manager.limits.operations, manager.limits.pending_calls), (2, 10, 64))
        with self.owner(manager) as (_claim, invocation, _operation), \
             mock.patch.object(capacity, "acquire_transaction_lock",
                               side_effect=AssertionError("Disabled mode must not take a capacity lock")):
            for _ in range(2):
                public.reserve_payload_with_capacity({"model": LITE, "max_tokens": 20, "modality": "image"},
                    7, call_id=str(uuid.uuid4()), require_metered=True)
            before = self.money()
            with self.assertRaises(public._SlotsBusy):
                public.reserve_payload_with_capacity({"model": LITE, "max_tokens": 20, "modality": "image"},
                    7, call_id=str(uuid.uuid4()), require_metered=True)
            self.assertEqual(self.money(), before)
            self.assertEqual(invocation.failure, "")
        self.assertEqual(self.buckets(), [])
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM public_trial_calls")[0], 2)

    def test_ten_mixed_users_have_independent_known_pools_but_one_io_bound_and_legacy_rpm(self):
        manager = admission.Admission()
        self.assertEqual((manager.calls.capacity, manager.limits.operations, manager.limits.pending_calls), (16, 100, 512))
        self.assertEqual((manager.limits.claude_rpm, manager.limits.queue_seconds,
                          manager.limits.no_progress_seconds), (30, 1800, 300))
        models = [LITE, PRO, IMAGE] * 3 + ["claude-sonnet-4-6"]
        tickets, operations = [], []
        for index, model in enumerate(models):
            provider = "seedream" if model == IMAGE else "claude" if model.startswith("claude") else "doubao"
            operation, _ = manager.register("mixed-user-" + str(index), str(index), route="/generate/stream")
            operations.append(operation)
            tickets.append(manager.calls.enqueue(operation, "call-" + str(index), provider, model_id=model))
        self.assertTrue(all(ticket.granted for ticket in tickets))
        self.assertEqual(len(manager.calls.active), 10)
        # Filling sockets across models never bypasses the one local I/O bound.
        for index in range(10, 17):
            operation, _ = manager.register("mixed-user-" + str(index), str(index), route="/generate/stream")
            operations.append(operation)
            tickets.append(manager.calls.enqueue(operation, "call-" + str(index), "doubao", model_id=LITE))
        self.assertEqual(len(manager.calls.active), 16)
        self.assertFalse(tickets[-1].granted)
        for ticket in tickets:
            manager.calls.release(ticket)
        for operation in operations:
            manager.finish(operation)
        # The unknown Claude quota retains its original two-call/RPM30 gate.
        first = admission.Operation("legacy-one", "1")
        second = admission.Operation("legacy-two", "2")
        third = admission.Operation("legacy-three", "3")
        live = [manager.calls.enqueue(first, "claude-one", "claude"),
                manager.calls.enqueue(second, "claude-two", "claude")]
        waiting = manager.calls.enqueue(third, "claude-three", "claude")
        self.assertTrue(all(ticket.granted for ticket in live))
        self.assertFalse(waiting.granted)
        for ticket in [*live, waiting]:
            manager.calls.release(ticket)
        with manager.calls.lock:
            manager.calls.grants["claude"].clear()
            manager.calls.grants["claude"].extend([time.monotonic()] * 30)
        rate_limited = manager.calls.enqueue(admission.Operation("legacy-rate", "r"), "claude-rate", "claude")
        lite = manager.calls.enqueue(admission.Operation("known-lite", "l"), "known-lite", "doubao", model_id=LITE)
        self.assertFalse(rate_limited.granted)
        self.assertTrue(lite.granted)
        manager.calls.release(rate_limited); manager.calls.release(lite)

    def test_rate_money_and_unique_call_commit_or_rollback_together(self):
        manager = admission.Admission()
        with self.owner(manager) as (_claim, invocation, _operation):
            before = self.money()
            original_execute = db.Transaction.execute
            def reject_insert(tx, sql, params=()):
                if sql.startswith("INSERT INTO public_trial_calls"):
                    raise RuntimeError("controlled call-row insert failure")
                return original_execute(tx, sql, params)
            with mock.patch.object(db.Transaction, "execute", reject_insert):
                with self.assertRaisesRegex(RuntimeError, "controlled call-row"):
                    public._reserve_payload(self.payload(), 7, call_id="rolled-back", require_metered=True)
            self.assertEqual(self.money(), before)
            self.assertEqual(self.buckets(), [])
            self.assertEqual(db.fetchone("SELECT COUNT(*) FROM public_trial_calls")[0], 0)
            self.assertEqual(invocation.call_ids, set())
            call_id = str(uuid.uuid4())
            public._reserve_payload(self.payload(), 7, call_id=call_id, require_metered=True)
            after = self.money()
            rows = self.buckets()
            physical = dict(db.fetchone("SELECT * FROM public_trial_calls WHERE id=?", (call_id,)))
            trace = json.loads(physical["provenance_json"])
            self.assertEqual((trace["capacity"]["model"], trace["capacity"]["input_bound"],
                              trace["capacity"]["output_bound"]), (LITE, 100, 20))
            self.assertEqual(trace["capacity"]["estimate_basis"], "isolated_integration_fixture")
            self.assertEqual(after["reserved_milli_cny"] - before["reserved_milli_cny"], 7)
            self.assertEqual((rows[0]["request_count"], rows[0]["token_bound"]), (1, 120))
            with self.assertRaisesRegex(capacity.CapacityStateError, "ALREADY_RESERVED"):
                public._reserve_payload(self.payload(), 7, call_id=call_id, require_metered=True)
            self.assertEqual(self.money(), after)
            self.assertEqual(self.buckets(), rows)
            self.assertEqual(dict(db.fetchone("SELECT * FROM public_trial_calls WHERE id=?", (call_id,))), physical)

    def test_quota_wait_holds_no_db_lock_or_failure_then_reserves_the_original_id_once(self):
        manager = admission.Admission()
        clock = [datetime.now(timezone.utc).timestamp()]
        self.seed_full_lite_window(clock[0])
        with self.owner(manager) as (claim, invocation, operation):
            historical = self.retained_unknown(claim)
            before = self.money()
            waits = []
            def waiting(seconds):
                self.assertEqual(invocation.failure, "")
                self.assertEqual(self.money(), before)
                # A distinct BEGIN IMMEDIATE succeeds while waiting, proving
                # the deferring reservation released its original DB lock.
                with db.transaction(write=True) as tx:
                    self.assertEqual(tx.fetchone("SELECT 1")[0], 1)
                waits.append(seconds)
                clock[0] += 61
                return False
            call_id = str(uuid.uuid4())
            with mock.patch.object(capacity, "_database_now", side_effect=lambda tx, now: clock[0]), \
                 mock.patch.object(public.time, "time", side_effect=lambda: clock[0]), \
                 mock.patch.object(operation.cancelled, "wait", side_effect=waiting):
                with public.model_admission_sync(call_id, "doubao", model_id=LITE):
                    result = public.reserve_payload_with_capacity(self.payload(), 7, call_id=call_id, require_metered=True)
            self.assertEqual(result, call_id)
            self.assertEqual(len(waits), 1)
            self.assertEqual(invocation.failure, "")
            self.assertEqual(invocation.call_ids, {call_id})
            self.assertEqual(db.fetchone("SELECT COUNT(*) FROM public_trial_calls WHERE id=?", (call_id,))[0], 1)
            self.assertEqual(self.money()["reserved_milli_cny"] - before["reserved_milli_cny"], 7)
            self.assertEqual(dict(db.fetchone("SELECT * FROM public_trial_calls WHERE id=?", (historical["id"],))), historical)

    def test_cancel_during_quota_wait_never_creates_wire_intent_or_new_cost(self):
        manager = admission.Admission()
        clock = datetime.now(timezone.utc).timestamp()
        self.seed_full_lite_window(clock)
        with self.owner(manager) as (claim, invocation, operation):
            historical = self.retained_unknown(claim)
            before, buckets = self.money(), self.buckets()
            call_id = str(uuid.uuid4())
            def cancel(_seconds):
                self.assertEqual(invocation.failure, "")
                operation.cancelled.set()
                return True
            with mock.patch.object(capacity, "_database_now", return_value=clock), \
                 mock.patch.object(operation.cancelled, "wait", side_effect=cancel):
                with self.assertRaisesRegex(public.TrialProviderStopped, "MODEL_OPERATION_CANCELLED"):
                    with public.model_admission_sync(call_id, "doubao", model_id=LITE):
                        public.reserve_payload_with_capacity(self.payload(), 7, call_id=call_id, require_metered=True)
            self.assertEqual(invocation.call_ids, set())
            self.assertEqual(self.money(), before)
            self.assertEqual(self.buckets(), buckets)
            self.assertIsNone(db.fetchone("SELECT id FROM public_trial_calls WHERE id=?", (call_id,)))
            self.assertEqual(dict(db.fetchone("SELECT * FROM public_trial_calls WHERE id=?", (historical["id"],))), historical)
            self.assertEqual(manager.calls.active, {})

    def test_nested_same_physical_id_and_model_reuses_one_ticket_but_mismatch_is_fenced(self):
        manager = admission.Admission()
        with self.owner(manager) as (_claim, invocation, operation):
            call_id = str(uuid.uuid4())
            with public.model_admission_sync(call_id, "doubao", model_id=LITE) as original:
                with public.model_admission_sync(call_id, "doubao", model_id=LITE) as nested:
                    self.assertIs(nested, original)
                    self.assertEqual(operation.outstanding, 1)
                    self.assertEqual(len(manager.calls.active), 1)
                self.assertFalse(original.closed)
                with self.assertRaisesRegex(public.TrialProviderStopped, "MODEL_ADMISSION_NESTED_CALL"):
                    with public.model_admission_sync(call_id, "doubao", model_id=PRO):
                        self.fail("Different models cannot borrow the same ticket")
            self.assertTrue(original.closed)
            self.assertEqual(manager.calls.active, {})
            self.assertEqual(operation.outstanding, 0)
            self.assertEqual(invocation.failure, "MODEL_ADMISSION_NESTED_CALL")
        with self.owner(manager) as (_claim, invocation, operation):
            async def nested_async():
                call_id = str(uuid.uuid4())
                async with public.model_admission(call_id, "doubao", model_id=PRO) as original:
                    async with public.model_admission(call_id, "doubao", model_id=PRO) as nested:
                        self.assertIs(nested, original)
                        self.assertEqual(operation.outstanding, 1)
                    with self.assertRaisesRegex(public.TrialProviderStopped, "MODEL_ADMISSION_NESTED_CALL"):
                        async with public.model_admission(call_id, "doubao", model_id=LITE):
                            self.fail("Different models cannot borrow an async ticket")
                self.assertTrue(original.closed)
            asyncio.run(nested_async())
            self.assertEqual(manager.calls.active, {})
            self.assertEqual(operation.outstanding, 0)
            self.assertEqual(invocation.failure, "MODEL_ADMISSION_NESTED_CALL")

    def test_database_known_pools_share_io_bound_without_widening_legacy_claude(self):
        manager = admission.Admission()
        with self.owner(manager) as (claim, invocation, _operation):
            historical = self.retained_unknown(claim)
            for model in [LITE, PRO, IMAGE] * 3:
                public._reserve_payload(self.payload(model), 7, call_id=str(uuid.uuid4()), require_metered=True)
            legacy = {"model": "claude-sonnet-4-6", "provider": "claude", "modality": "text", "max_tokens": 16000}
            for _ in range(2):
                public._reserve_payload(legacy, 7, call_id=str(uuid.uuid4()), require_metered=True)
            money, buckets = self.money(), self.buckets()
            with self.assertRaises(public._SlotsBusy):
                public._reserve_payload(legacy, 7, call_id=str(uuid.uuid4()), require_metered=True)
            self.assertEqual(self.money(), money)
            self.assertEqual(self.buckets(), buckets)
            for _ in range(5):
                public._reserve_payload(self.payload(), 7, call_id=str(uuid.uuid4()), require_metered=True)
            self.assertEqual(db.fetchone("SELECT COUNT(*) FROM public_trial_calls WHERE state='dispatched'")[0], 16)
            money, buckets = self.money(), self.buckets()
            with self.assertRaises(public._SlotsBusy):
                public._reserve_payload(self.payload(PRO), 7, call_id=str(uuid.uuid4()), require_metered=True)
            self.assertEqual(self.money(), money)
            self.assertEqual(self.buckets(), buckets)
            self.assertEqual(invocation.failure, "")
            self.assertEqual(dict(db.fetchone("SELECT * FROM public_trial_calls WHERE id=?", (historical["id"],))), historical)

    def test_quota_wait_cannot_start_a_new_call_after_original_claim_lease_expires(self):
        manager = admission.Admission()
        clock = [datetime.now(timezone.utc).timestamp()]
        self.seed_full_lite_window(clock[0])
        with self.owner(manager) as (claim, _invocation, operation):
            historical = self.retained_unknown(claim)
            before, buckets = self.money(), self.buckets()
            def expiry(_seconds):
                # Expiration is a fence against *new* paid dispatch, not proof
                # the original process ended or permission to release its hold.
                db.execute("UPDATE idempotency_requests SET lease_expires_at=? WHERE id=?",
                    ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), claim["request_id"]))
                clock[0] += 61
                return False
            call_id = str(uuid.uuid4())
            with mock.patch.object(capacity, "_database_now", side_effect=lambda tx, now: clock[0]), \
                 mock.patch.object(public.time, "time", side_effect=lambda: clock[0]), \
                 mock.patch.object(operation.cancelled, "wait", side_effect=expiry):
                with self.assertRaisesRegex(public.TrialProviderStopped, "MODEL_TASK_LEASE_EXPIRED"):
                    with public.model_admission_sync(call_id, "doubao", model_id=LITE):
                        public.reserve_payload_with_capacity(self.payload(), 7, call_id=call_id, require_metered=True)
            self.assertEqual(self.money(), before)
            self.assertEqual(self.buckets(), buckets)
            self.assertIsNone(db.fetchone("SELECT id FROM public_trial_calls WHERE id=?", (call_id,)))
            self.assertEqual(tuple(db.fetchone("SELECT status,refund_applied,complete_applied FROM idempotency_requests WHERE id=?",
                (claim["request_id"],))), ("running", 0, 0))
            self.assertEqual(self.available()["wallet_held"], 8)
            self.assertEqual(dict(db.fetchone("SELECT * FROM public_trial_calls WHERE id=?", (historical["id"],))), historical)

    def test_same_original_task_unknown_still_fences_new_dispatch_before_quota_money(self):
        manager = admission.Admission()
        with self.owner(manager) as (claim, invocation, _operation):
            historical = self.retained_unknown(claim)
            request_hash = hashlib.sha256((self.user + ":" + claim["request_id"]).encode()).hexdigest()
            db.execute("UPDATE public_trial_calls SET request_hash=? WHERE id=?", (request_hash, historical["id"]))
            historical = dict(db.fetchone("SELECT * FROM public_trial_calls WHERE id=?", (historical["id"],)))
            before = self.money()
            call_id = str(uuid.uuid4())
            with self.assertRaisesRegex(public.TrialProviderStopped, "PUBLIC_TRIAL_UNKNOWN_NO_REPLAY"):
                public.reserve_payload_with_capacity(self.payload(), 7, call_id=call_id, require_metered=True)
            self.assertEqual(invocation.failure, "PUBLIC_TRIAL_UNKNOWN_NO_REPLAY")
            self.assertEqual(self.money(), before)
            self.assertEqual(self.buckets(), [])
            self.assertIsNone(db.fetchone("SELECT id FROM public_trial_calls WHERE id=?", (call_id,)))
            self.assertEqual(dict(db.fetchone("SELECT * FROM public_trial_calls WHERE id=?", (historical["id"],))), historical)

    def test_full_pro_window_does_not_hold_io_slots_needed_by_available_lite(self):
        """Only waiting Pro calls park; an available model can actually finish."""
        import httpx
        import ark_media
        from PIL import Image
        import io

        os.environ["NOTEAI_MODEL_REMOTE_CONCURRENCY"] = "2"
        manager = admission.Admission()
        policy = capacity.policy_for(PRO)
        second = int(datetime.now(timezone.utc).timestamp())
        db.execute("INSERT INTO model_capacity_buckets(scope_key,quota_key,slot,epoch_second,request_count,token_bound,image_count,input_bound,output_bound) VALUES(?,?,?,?,?,?,?,?,?)",
            (policy.scope_key, policy.quota_key, second % 61, second, 500, 1000000, 0, 1000000, 0))
        pro_bucket = self.buckets()
        owners = ("quota-pro-one", "quota-pro-two", "quota-ready-lite")
        claims, operations, invocations = [], [], []
        for index, user in enumerate(owners):
            db.execute("INSERT INTO users(id,username,email,password_hash,password_salt,created_at) VALUES(?,?,?,?,?,?)",
                (user, user, user + "@example.invalid", "fixture", "fixture", billing._now()))
            billing.get_subscription(user)
            claim = fixture.settlement.reserve_claim(user_id=user, operation="generate",
                request_id="mixed-quota-" + str(index), payload={"fixture": "same original claim"})
            claims.append(claim)
            operation, _ = manager.register(user, str(index), route="/generate/stream")
            operations.append(operation)
            invocations.append(public.Invocation(user, claim["request_id"], route="/generate/stream",
                                                  admission_state=operation))
        pro_waiting = threading.Event()
        lite_done = threading.Event()
        waiters, errors, responses, sent, original_pro_tickets = set(), [], [], [], {}
        lock = threading.Lock()
        original_reserve = capacity.reserve_in_transaction

        def tracked_reserve(tx, demand, **kwargs):
            try:
                return original_reserve(tx, demand, **kwargs)
            except capacity.QuotaDeferred:
                if demand.model_id == PRO:
                    with lock:
                        waiters.add(threading.get_ident())
                        if len(waiters) == 2:
                            pro_waiting.set()
                raise

        def supplier(request):
            sent.append(request.url.path)
            return httpx.Response(200, json={"model": LITE,
                "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                          "prompt_tokens_details": {"cached_tokens": 0}},
                "choices": [{"finish_reason": "stop", "message": {"content": "真实庭院照片清晰可见。"}}]})

        def client(**kwargs):
            return httpx.Client(transport=httpx.MockTransport(supplier), trust_env=False)

        image = io.BytesIO()
        Image.new("RGB", (20, 20), "white").save(image, "PNG")
        photo = image.getvalue()

        def run(index):
            im = public._invocation.set(invocations[index])
            um = billing._ACTIVE_USAGE_ID.set(claims[index]["charge"]["usage_id"])
            try:
                if index < 2:
                    call_id = "waiting-pro-" + str(index)
                    with public.model_admission_sync(call_id, "doubao", model_id=PRO) as ticket:
                        original_pro_tickets[call_id] = ticket
                        public.reserve_payload_with_capacity(self.payload(PRO), 7,
                            call_id=call_id, require_metered=True)
                    errors.append(AssertionError("Full Pro window unexpectedly admitted a call"))
                else:
                    responses.append(ark_media.chat("仅描述这张真实照片", [ark_media.image_part(photo)], max_tokens=20))
            except public.TrialProviderStopped as exc:
                if not (index < 2 and exc.args == ("MODEL_OPERATION_CANCELLED",)):
                    errors.append(exc)
            except BaseException as exc:
                errors.append(exc)
            finally:
                if index == 2:
                    lite_done.set()
                billing._ACTIVE_USAGE_ID.reset(um)
                public._invocation.reset(im)
                manager.finish(operations[index])

        workers = [threading.Thread(target=run, args=(index,)) for index in range(3)]
        with mock.patch.object(admission, "_instance", manager), \
             mock.patch.object(capacity, "reserve_in_transaction", side_effect=tracked_reserve), \
             mock.patch.dict(os.environ, {"NOTEAI_ARK_API_KEY": "synthetic-offline-only"}), \
             mock.patch.object(ark_media, "_client", side_effect=client):
            for worker in workers[:2]:
                worker.start()
            try:
                self.assertTrue(pro_waiting.wait(3), "Both original Pro calls must reach actual quota deferral")
                workers[2].start()
                completed_before_window = lite_done.wait(1)
                self.assertTrue(completed_before_window,
                    "Pro quota wait occupied every I/O slot and blocked a model with available quota")
                self.assertEqual(errors, [])
                self.assertEqual(responses, ["真实庭院照片清晰可见。"])
                self.assertEqual(len(sent), 1)
                self.assertLess(time.time(), second + 60,
                    "Lite must finish before the full Pro window ages out")
                self.assertEqual([row for row in self.buckets() if row["quota_key"] == policy.quota_key], pro_bucket)
                rows = db.fetchall("SELECT id,state,http_status,model_usage_record_id FROM public_trial_calls")
                self.assertEqual(len(rows), 1)
                self.assertEqual((rows[0]["state"], rows[0]["http_status"]), ("responded", 200))
                self.assertIsNotNone(rows[0]["model_usage_record_id"])
                self.assertEqual(db.fetchone("SELECT COUNT(*) FROM model_usage_records")[0], 1)
                self.assertEqual(len(original_pro_tickets), 2)
                self.assertTrue(all(ticket.call_id == key and not ticket.dispatched and not ticket.closed
                                    for key, ticket in original_pro_tickets.items()))
            finally:
                # A failed red case must not dispatch Lite as a cleanup effect.
                if not lite_done.is_set():
                    operations[2].cancelled.set()
                for operation in operations[:2]:
                    operation.cancelled.set()
                for worker in workers:
                    if worker.ident is not None:
                        worker.join(3)
        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertEqual(manager.calls.active, {})
        self.assertEqual(manager.calls._tickets(), [])
        self.assertFalse(getattr(manager.calls, "deferred", {}))
        self.assertTrue(all(operation.outstanding == 0 for operation in operations))
        self.assertTrue(all(ticket.closed for ticket in original_pro_tickets.values()))
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM public_trial_calls WHERE id LIKE 'waiting-pro-%'")[0], 0)

    def test_deferred_ticket_counts_as_pending_and_cancels_without_identity_or_counter_leak(self):
        manager = admission.Admission(admission.Limits(pending_calls=1))
        operation, _ = manager.register("deferred-owner", "original-task", route="/generate/stream")
        queue = manager.calls
        ticket = queue.acquire(operation, "original-physical-call", "doubao", model_id=PRO)
        self.assertEqual(operation.outstanding, 1)
        queue.defer(ticket)
        self.assertEqual(queue.active, {})
        self.assertIs(queue.deferred[ticket.call_id], ticket)
        self.assertEqual(operation.outstanding, 1)
        state = queue.status(operation)
        self.assertEqual((state["state"], state["queued_calls"], state["waiting_operations"], state["can_cancel"]),
                         ("queued", 1, 1, True))
        other = admission.Operation("another-owner", "another-task")
        with self.assertRaisesRegex(admission.AdmissionError, "MODEL_QUEUE_FULL"):
            queue.enqueue(other, "another-call", "doubao", model_id=LITE)
        self.assertEqual(other.outstanding, 0)
        self.assertTrue(manager.cancel_active(operation))
        with self.assertRaisesRegex(admission.AdmissionError, "MODEL_OPERATION_CANCELLED"):
            queue.resume(ticket)
        self.assertTrue(ticket.closed)
        self.assertFalse(ticket.dispatched)
        self.assertEqual((ticket.call_id, ticket.operation), ("original-physical-call", operation))
        self.assertEqual(operation.outstanding, 0)
        self.assertEqual(queue.active, {})
        self.assertEqual(queue.deferred, {})
        self.assertEqual(queue._tickets(), [])
        queue.release(ticket)
        self.assertEqual(operation.outstanding, 0)
        manager.finish(operation)
        self.assertEqual(manager.operations, {})

    def test_resuming_same_claude_ticket_keeps_one_rpm_grant_until_it_ages(self):
        clock = [100.0]
        with mock.patch.object(admission.time, "monotonic", side_effect=lambda: clock[0]):
            manager = admission.Admission()
            operation = admission.Operation("legacy-claude-owner", "original-task")
            queue = manager.calls
            ticket = queue.acquire(operation, "original-claude-call", "claude")
            original = ticket
            self.assertEqual(list(queue.grants["claude"]), [100.0])
            for _ in range(3):
                queue.defer(ticket)
                self.assertEqual(queue.active, {})
                self.assertIs(queue.resume(ticket), original)
                self.assertEqual(list(queue.grants["claude"]), [100.0])
                self.assertEqual((operation.outstanding, operation.completed_calls), (1, 0))
            clock[0] = 161.0
            queue.defer(ticket)
            self.assertIs(queue.resume(ticket), original)
            self.assertEqual(list(queue.grants["claude"]), [161.0])
            self.assertEqual(ticket.rate_granted_at, 161.0)
            self.assertEqual((ticket.call_id, operation.outstanding), ("original-claude-call", 1))
            ticket.dispatched = True
            with self.assertRaisesRegex(admission.AdmissionError, "MODEL_CALL_CANNOT_DEFER"):
                queue.defer(ticket)
            self.assertIs(queue.active[ticket.call_id], ticket)
            queue.release(ticket)
            self.assertEqual(operation.outstanding, 0)
            self.assertEqual(queue.active, {})
            self.assertEqual(queue.deferred, {})


if __name__ == "__main__":
    unittest.main()
