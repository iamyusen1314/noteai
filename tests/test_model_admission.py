"""Offline contracts for the shared model scheduler; no supplier calls.

Manager fairness/cancel/grant/queue-bound cases bind the actual core API.
Missing APIs are failures, never silently counted as skipped release proof.
"""
import asyncio
import importlib
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest import mock

MODEL = Path(__file__).resolve().parents[1] / "model"
if str(MODEL) not in sys.path:
    sys.path.insert(0, str(MODEL))
public = importlib.import_module("public_product")


class PublicAdmissionDisabledTests(unittest.TestCase):
    def test_disabled_public_async_admission_is_noop_without_invocation(self):
        async def run():
            async with public.model_admission("synthetic-disabled-async", "claude"):
                return "entered"
        with mock.patch.dict(os.environ, {"NOTEAI_PUBLIC_PRODUCT": "0"}), \
             mock.patch.object(public, "_invocation") as invocation, \
             mock.patch.object(core, "current") as scheduler:
            invocation.get.return_value = None
            self.assertEqual(asyncio.run(run()), "entered")
        scheduler.assert_not_called()

    def test_disabled_public_sync_admission_is_noop_without_invocation(self):
        with mock.patch.dict(os.environ, {"NOTEAI_PUBLIC_PRODUCT": "0"}), \
             mock.patch.object(public, "_invocation") as invocation, \
             mock.patch.object(core, "current") as scheduler:
            invocation.get.return_value = None
            with public.model_admission_sync("synthetic-disabled-sync", "doubao"):
                entered = True
        self.assertTrue(entered)
        scheduler.assert_not_called()

core = importlib.import_module("model_admission")


class _Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now


class FairAdmissionCoreTests(unittest.TestCase):
    def manager(self, **changes):
        values = {"physical": 1, "claude": 1, "kimi": 1, "doubao": 1,
                  "media_workers": 1, "operations": 10, "operations_per_user": 2,
                  "pending_calls": 16, "queue_seconds": 900., "no_progress_seconds": 300.}
        manager = core.Admission(core.Limits(**{**values, **changes}))
        def finish_fixture():
            for queue in (manager.calls, manager.media):
                self.assertEqual(queue.active, {}, "fixture leaked a physical/media permit")
                self.assertEqual(queue._tickets(), [], "fixture leaked a queued ticket")
            for operation in list(manager.operations.values()):
                self.assertEqual(operation.outstanding, 0)
                manager.finish(operation)
            self.assertEqual(manager.operations, {})
            self.assertEqual(manager.aliases, {})
        self.addCleanup(finish_fixture)
        return manager

    def test_round_robin_rotates_user_then_task_without_skipping_family_caps(self):
        manager = self.manager()
        queue = manager.calls
        hold, _ = manager.register("holder", "hold")
        active = queue.enqueue(hold, "hold-call", "claude")
        operations = {key: manager.register(uid, key)[0] for uid, key in
                      (("A", "A1"), ("A", "A2"), ("B", "B1"), ("B", "B2"))}
        tickets = [queue.enqueue(operations[task], call, "claude") for task, call in
                   (("A1", "a1"), ("A1", "a1b"), ("A2", "a2"),
                    ("B1", "b1"), ("B1", "b1b"), ("B2", "b2"))]
        self.assertTrue(all(not ticket.granted for ticket in tickets))
        queue.release(active)
        order = []
        while queue.active:
            self.assertEqual(len(queue.active), 1)
            ticket = next(iter(queue.active.values()))
            order.append(ticket.call_id)
            ticket.progress = True
            queue.release(ticket)
        self.assertEqual(order, ["a1", "b1", "a2", "b2", "a1b", "b1b"])
        self.assertEqual(queue._tickets(), [])
        self.assertTrue(all(op.outstanding == 0 for op in (hold, *operations.values())))

    def test_physical_and_provider_family_permits_are_granted_atomically(self):
        manager = self.manager(physical=2)
        queue = manager.calls
        ops = [manager.register(str(i), str(i))[0] for i in range(4)]
        claude1 = queue.enqueue(ops[0], "claude1", "claude")
        claude2 = queue.enqueue(ops[1], "claude2", "claude")
        ark1 = queue.enqueue(ops[2], "ark1", "doubao")
        self.assertTrue(claude1.granted and ark1.granted)
        self.assertFalse(claude2.granted)
        self.assertEqual(set(queue.active), {"claude1", "ark1"})
        queue.release(ark1)
        self.assertFalse(claude2.granted, "free physical capacity must not bypass the occupied Claude family")
        ark2 = queue.enqueue(ops[3], "ark2", "doubao")
        self.assertTrue(ark2.granted)
        queue.release(claude1)
        self.assertTrue(claude2.granted)
        self.assertEqual(set(queue.active), {"claude2", "ark2"})
        queue.release(claude2)
        queue.release(ark2)
        self.assertEqual(queue.active, {})

    def test_bounded_pending_queue_rejects_before_owning_a_permit(self):
        manager = self.manager(pending_calls=1)
        operations = [manager.register(str(i), str(i))[0] for i in range(3)]
        first = manager.calls.enqueue(operations[0], "first", "claude")
        waiting = manager.calls.enqueue(operations[1], "waiting", "claude")
        with self.assertRaisesRegex(core.AdmissionError, "^MODEL_QUEUE_FULL$"):
            manager.calls.enqueue(operations[2], "rejected", "claude")
        self.assertEqual(operations[2].outstanding, 0)
        self.assertEqual(len(manager.calls._tickets()), 1)
        self.assertEqual(set(manager.calls.active), {"first"})
        manager.calls.release(waiting)
        manager.calls.release(first)
        self.assertEqual(manager.calls.active, {})

    def test_configurable_operation_bound_is_not_a_fixed_public_user_quota(self):
        manager = self.manager(operations=2, operations_per_user=1)
        first, created = manager.register("A", "one")
        self.assertTrue(created)
        same, created = manager.register("A", "one")
        self.assertIs(same, first)
        self.assertFalse(created)
        with self.assertRaisesRegex(core.AdmissionError, "^MODEL_USER_OPERATION_BUSY$"):
            manager.register("A", "second")
        second, _ = manager.register("B", "one")
        with self.assertRaisesRegex(core.AdmissionError, "^MODEL_OPERATIONS_BUSY$"):
            manager.register("C", "one")
        manager.finish(first)
        third, created = manager.register("C", "one")
        self.assertTrue(created)
        manager.finish(second)
        manager.finish(third)
        self.assertEqual(manager.operations, {})

    def test_cancel_in_the_grant_wakeup_race_releases_an_undispatched_ticket(self):
        async def run():
            manager = self.manager()
            holder, _ = manager.register("holder", "one")
            waiter, _ = manager.register("waiter", "one")
            first = manager.calls.enqueue(holder, "held", "claude")
            task = asyncio.create_task(manager.calls.acquire_async(waiter, "race", "claude"))
            await asyncio.sleep(0)
            self.assertEqual(len(manager.calls._tickets()), 1)
            manager.calls.release(first)  # Grants and schedules the wake-up.
            self.assertEqual(set(manager.calls.active), {"race"})
            task.cancel()  # Cancellation wins before the notified task resumes.
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(manager.calls.active, {})
            self.assertEqual(manager.calls._tickets(), [])
            self.assertEqual(waiter.outstanding, 0)
            self.assertEqual(waiter.completed_calls, 0)
        asyncio.run(run())

    def test_cancelled_dispatched_operation_stays_owned_until_original_join(self):
        async def run():
            manager = self.manager()
            operation, _ = manager.register("A", "original")
            first = manager.calls.enqueue(operation, "wire-in-flight", "doubao")
            first.dispatched = True
            task = asyncio.create_task(manager.calls.acquire_async(operation, "not-started", "claude"))
            await asyncio.sleep(0)
            with mock.patch.object(core, "_instance", manager):
                self.assertFalse(public.request_cancel("different-owner", "original"))
                self.assertFalse(operation.cancelled.is_set())
                self.assertTrue(public.request_cancel("A", "original"))
            manager.finish(operation)
            with self.assertRaisesRegex(core.AdmissionError, "^MODEL_OPERATION_CANCELLED$"):
                await task
            self.assertIs(manager.find("A", "original"), operation)
            self.assertEqual(manager.calls.status(operation)["state"], "settling")
            self.assertEqual(set(manager.calls.active), {"wire-in-flight"})
            self.assertFalse(first.closed)
            self.assertEqual(operation.outstanding, 1)
            # Represents original supplier/accounting join, not an idle reclaim.
            first.progress = True
            manager.calls.release(first)
            self.assertIsNone(manager.find("A", "original"))
            self.assertEqual(operation.completed_calls, 1)
        asyncio.run(run())

    def test_waiting_beyond_old_90s_does_not_consume_provider_http_deadline(self):
        clock = _Clock()
        with mock.patch.object(core, "time", clock):
            manager = self.manager()
            holder, _ = manager.register("holder", "one")
            waiter, _ = manager.register("waiter", "one")
            first = manager.calls.enqueue(holder, "first", "claude")
            queued = manager.calls.enqueue(waiter, "later", "claude")
            clock.now = 91
            self.assertFalse(manager.calls._check(queued))
            self.assertFalse(queued.dispatched)
            first.progress = True
            manager.calls.release(first)
            self.assertTrue(manager.calls._check(queued))
            # The real integration must start its existing HTTP deadline only
            # after this permit; this fixture neither extends nor enforces it.
            wire_start = clock.now
            http_read_window = 240
            self.assertEqual(wire_start + http_read_window, 331)
            self.assertEqual(wire_start + http_read_window - clock.now, 240)
            queued.dispatched = True
            manager.calls.release(queued)

    def test_no_progress_and_absolute_queue_expiry_do_not_reclaim_active_wire(self):
        for absolute, expected in ((900., "MODEL_QUEUE_NO_PROGRESS"), (30., "MODEL_QUEUE_WAIT_EXCEEDED")):
            with self.subTest(absolute_queue_seconds=absolute):
                clock = _Clock()
                with mock.patch.object(core, "time", clock):
                    manager = self.manager(queue_seconds=absolute)
                    holder, _ = manager.register("holder", "one")
                    waiter, _ = manager.register("waiter", "one")
                    first = manager.calls.enqueue(holder, "in-flight", "doubao")
                    first.dispatched = True
                    queued = manager.calls.enqueue(waiter, "waiting", "claude")
                    clock.now = 301 if absolute == 900. else 31
                    with self.assertRaisesRegex(core.AdmissionError, "^" + expected + "$"):
                        manager.calls._check(queued)
                    self.assertEqual(set(manager.calls.active), {"in-flight"})
                    self.assertFalse(first.closed)
                    manager.calls.release(queued)
                    self.assertEqual(holder.outstanding, 1)
                    manager.calls.release(first)

    def test_public_nested_reentry_keeps_one_ticket_and_rejects_sibling_identity(self):
        async def run():
            manager = self.manager()
            operation, _ = manager.register("A", "one")
            invocation = public.Invocation("A", "original", admission_state=operation)
            marker = public._invocation.set(invocation)
            try:
                with mock.patch.object(core, "_instance", manager), \
                     mock.patch.dict(os.environ, {"NOTEAI_PUBLIC_PRODUCT": "1"}):
                    async with public.model_admission("wire-id", "claude") as first:
                        async with public.model_admission("wire-id", "claude") as same:
                            self.assertIs(same, first)
                            self.assertEqual(set(manager.calls.active), {"wire-id"})
                        self.assertFalse(first.closed)
                        with self.assertRaisesRegex(public.TrialProviderStopped, "^MODEL_ADMISSION_NESTED_CALL$"):
                            async with public.model_admission("different-wire-id", "claude"):
                                self.fail("a sibling must not reuse a ticket")
                        with self.assertRaisesRegex(public.TrialProviderStopped, "^MODEL_ADMISSION_NESTED_CALL$"):
                            with public.model_admission_sync("wire-id", "doubao"):
                                self.fail("a different provider must not reuse a ticket")
                        public.mark_model_dispatched("wire-id")
                        with self.assertRaisesRegex(public.TrialProviderStopped, "^MODEL_CALL_ALREADY_DISPATCHED$"):
                            public.mark_model_dispatched("wire-id")
                        status = public.queue_status()
                        self.assertEqual(status["state"], "running")
                        self.assertNotIn("position", status)
                        self.assertNotIn("eta", status)
                    self.assertEqual(manager.calls.active, {})
            finally:
                public._invocation.reset(marker)
        asyncio.run(run())

    def test_original_paid_claim_alias_addresses_resume_cancel_status_and_cleanup(self):
        manager = self.manager()
        operation, _ = manager.register("owner", "new-http-request-hash")
        invocation = public.Invocation("owner", "new-clarify-http-id", admission_state=operation)
        marker = public._invocation.set(invocation)
        try:
            with mock.patch.object(core, "_instance", manager), \
                 mock.patch.dict(os.environ, {"NOTEAI_PUBLIC_PRODUCT": "1"}), \
                 mock.patch.object(public, "_reserve_payload") as reserve:
                with self.assertRaisesRegex(public.TrialProviderStopped, "^MODEL_TASK_OWNER_MISMATCH$"):
                    public.bind_task_claim({"user_id": "different-owner", "key_hash": "original-paid-hash"})
                self.assertEqual(manager.aliases, {})
                public.bind_task_claim({"user_id": "owner", "key_hash": "original-paid-hash"})
                self.assertIs(manager.find("owner", "original-paid-hash"), operation)
                self.assertIsNone(manager.find("different-owner", "original-paid-hash"))
                same, created = manager.register("owner", "original-paid-hash")
                self.assertIs(same, operation)
                self.assertFalse(created)
                self.assertEqual(len(manager.operations), 1)
                ticket = manager.calls.enqueue(operation, "resumed-wire", "claude")
                ticket.dispatched = True
                self.assertEqual(public.queue_status("owner", "original-paid-hash")["state"], "running")
                self.assertTrue(public.request_cancel("owner", "original-paid-hash"))
                manager.finish(operation)
                self.assertEqual(public.queue_status("owner", "original-paid-hash")["state"], "settling")
                self.assertIs(manager.find("owner", "new-http-request-hash"), operation)
                ticket.progress = True
                manager.calls.release(ticket)
                self.assertIsNone(manager.find("owner", "original-paid-hash"))
                self.assertIsNone(manager.find("owner", "new-http-request-hash"))
                self.assertEqual(manager.aliases, {})
                reserve.assert_not_called()  # Alias binding is not a new model charge.
        finally:
            public._invocation.reset(marker)


    def test_idle_save_boundary_rejects_new_cancel_but_accepted_cancel_still_blocks_delivery(self):
        manager = self.manager()
        operation, _ = manager.register("owner", "original")
        marker = public._invocation.set(public.Invocation("owner", "request", admission_state=operation))
        try:
            with mock.patch.object(core, "_instance", manager), \
                 mock.patch.dict(os.environ, {"NOTEAI_PUBLIC_PRODUCT": "1"}):
                self.assertFalse(public.queue_status("owner", "original")["can_cancel"])
                self.assertFalse(public.request_cancel("owner", "original"))
                self.assertFalse(operation.cancelled.is_set())
                ticket = manager.calls.enqueue(operation, "last-model", "claude")
                ticket.dispatched = True
                self.assertTrue(public.request_cancel("owner", "original"))
                ticket.progress = True
                manager.calls.release(ticket)
                self.assertTrue(public.request_cancel("owner", "original"), "repeat acknowledges the already accepted event")
                with self.assertRaisesRegex(public.TrialProviderStopped, "^MODEL_OPERATION_CANCELLED$"):
                    public.assert_result_known()
                self.assertEqual(operation.completed_calls, 1, "known supplier work remains accounted after cancellation")
        finally:
            public._invocation.reset(marker)

    def test_cancel_active_is_atomic_with_last_ticket_release_in_both_orders(self):
        for winner in ("release", "cancel"):
            with self.subTest(winner=winner):
                manager = self.manager()
                operation, _ = manager.register("owner", "last-ticket")
                ticket = manager.calls.enqueue(operation, "last-wire", "claude")
                ticket.dispatched = True
                ticket.progress = True
                attempted, checked, allow_set, released = [threading.Event() for _ in range(4)]
                results, errors = [], []
                original_set = operation.cancelled.set

                def cancel():
                    attempted.set()
                    try:
                        results.append(public.request_cancel("owner", "last-ticket"))
                    except BaseException as exc:
                        errors.append(exc)

                def release():
                    try:
                        manager.calls.release(ticket)
                    except BaseException as exc:
                        errors.append(exc)
                    finally:
                        released.set()

                def set_while_active():
                    # The old status-then-set gap allowed the final release
                    # to win after a stale positive cancellation check.
                    self.assertTrue(manager.calls.lock._is_owned())
                    self.assertTrue(manager.media.lock._is_owned())
                    self.assertIn(ticket.call_id, manager.calls.active)
                    checked.set()
                    self.assertTrue(allow_set.wait(3))
                    original_set()

                with mock.patch.object(core, "_instance", manager), \
                     mock.patch.dict(os.environ, {"NOTEAI_PUBLIC_PRODUCT": "1"}):
                    canceller = threading.Thread(target=cancel)
                    releaser = None
                    try:
                        if winner == "release":
                            with manager.calls.lock, manager.media.lock:
                                canceller.start()
                                self.assertTrue(attempted.wait(3))
                                manager.calls.release(ticket)
                            canceller.join(3)
                            self.assertEqual(results, [False])
                            self.assertFalse(operation.cancelled.is_set())
                        else:
                            with mock.patch.object(operation.cancelled, "set", side_effect=set_while_active):
                                canceller.start()
                                self.assertTrue(checked.wait(3))
                                releaser = threading.Thread(target=release)
                                releaser.start()
                                self.assertFalse(released.wait(.02), "last release must wait for the atomic cancel decision")
                                allow_set.set()
                                canceller.join(3)
                                releaser.join(3)
                            self.assertEqual(results, [True])
                            self.assertTrue(operation.cancelled.is_set())
                        self.assertFalse(canceller.is_alive())
                        self.assertEqual(errors, [])
                        self.assertEqual(operation.completed_calls, 1)
                        marker = public._invocation.set(public.Invocation("owner", "last-ticket", admission_state=operation))
                        try:
                            if winner == "cancel":
                                with self.assertRaisesRegex(public.TrialProviderStopped, "^MODEL_OPERATION_CANCELLED$"):
                                    public.assert_result_known()
                            else:
                                public.assert_result_known()
                        finally:
                            public._invocation.reset(marker)
                    finally:
                        allow_set.set()
                        if canceller.ident is not None:
                            canceller.join(3)
                        if releaser is not None:
                            releaser.join(3)
                        manager.calls.release(ticket)

    def test_media_wait_uses_real_call_progress_without_extending_its_queue_deadline(self):
        clock = _Clock()
        with mock.patch.object(core, "time", clock):
            manager = self.manager()
            holder, _ = manager.register("holder", "media-and-model")
            waiter, _ = manager.register("waiter", "queued-media")
            held = manager.media.enqueue(holder, "held-media", "media_worker")
            queued = manager.media.enqueue(waiter, "queued-media", "media_worker")
            original_queued_at = queued.queued_at
            try:
                # Real call completions keep a media worker waiting on model
                # service healthy; no heartbeat or queue-position refresh does.
                for index, now in enumerate((200., 399., 598., 797.)):
                    clock.now = now
                    call = manager.calls.enqueue(holder, "completed-%d" % index, "claude")
                    call.dispatched = True
                    call.progress = True
                    manager.calls.release(call)
                    self.assertFalse(manager.media._check(queued))
                    self.assertEqual(queued.queued_at, original_queued_at)
                    self.assertEqual(manager.media.last_progress, 0.)
                self.assertEqual(holder.completed_calls, 4)
                clock.now = 901.
                with self.assertRaisesRegex(core.AdmissionError, "^MODEL_QUEUE_WAIT_EXCEEDED$"):
                    manager.media._check(queued)
                self.assertFalse(held.closed, "absolute queue expiry cannot reclaim a running media worker")
                self.assertEqual(queued.queued_at, original_queued_at)
            finally:
                manager.media.release(queued)
                manager.media.release(held)


    def test_claude_30rpm_rolls_at_60s_without_physical_or_cancelled_waiter_ghost(self):
        clock = _Clock()
        with mock.patch.object(core, "time", clock):
            manager = self.manager(physical=2, claude=2, pending_calls=64, claude_rpm=30)
            queue = manager.calls
            holder, _ = manager.register("holder", "initial-30")
            for index in range(30):
                ticket = queue.enqueue(holder, f"initial-{index}", "claude")
                self.assertTrue(ticket.granted)
                if index < 29:
                    ticket.dispatched = True
                    ticket.progress = True
                # The last grant is cancelled before dispatch: it conservatively
                # retains one RPM position, but is not a provider/usage claim.
                queue.release(ticket)
            self.assertEqual(len(queue.grants["claude"]), 30)
            first_op, _ = manager.register("A", "waiting-A")
            second_op, _ = manager.register("B", "waiting-B")
            cancel_op, _ = manager.register("C", "cancel-rate-wait")
            first = queue.enqueue(first_op, "31st", "claude")
            second = queue.enqueue(second_op, "32nd", "claude")
            cancelled = queue.enqueue(cancel_op, "cancelled-rate-wait", "claude")
            self.assertFalse(queue.active, "RPM wait must not consume a physical slot")
            self.assertFalse(first.dispatched or second.dispatched or cancelled.dispatched)
            self.assertFalse(queue._check(first))
            queue.cancel(cancel_op)
            with self.assertRaisesRegex(core.AdmissionError, "^MODEL_OPERATION_CANCELLED$"):
                queue._check(cancelled)
            queue.release(cancelled)
            clock.now = 59.999
            self.assertFalse(queue._check(first))
            self.assertFalse(queue.active)
            self.assertEqual(len(queue.grants["claude"]), 30)
            clock.now = 60.0
            # No active call exists to wake this queue. Checking a waiter must
            # re-evaluate the rolling window and fairly grant the original work.
            self.assertTrue(queue._check(first))
            self.assertTrue(queue._check(second))
            self.assertEqual(list(queue.active), ["31st", "32nd"])
            self.assertEqual(len(queue.grants["claude"]), 2)
            self.assertNotIn(cancelled, queue._tickets())
            self.assertNotIn(cancelled.call_id, queue.active)
            self.assertEqual(cancel_op.outstanding, 0)
            queue.release(first)
            queue.release(second)

    def test_ten_users_three_slow_p2_calls_use_own_progress_not_other_users_progress(self):
        clock = _Clock()
        with mock.patch.object(core, "time", clock):
            manager = self.manager(physical=2, claude=2, operations_per_user=1,
                pending_calls=64, claude_rpm=30, queue_seconds=900)
            queue = manager.calls
            operations = [manager.register(f"user-{i}", f"P2-{i}")[0] for i in range(10)]
            tickets = [queue.enqueue(operation, f"P2-{i}-{j}", "claude")
                       for i, operation in enumerate(operations) for j in range(3)]
            self.assertEqual(len(manager.operations), 10)
            completed = []
            while queue.active:
                original_pair = tuple(queue.active.values())
                self.assertLessEqual(len(original_pair), 2)
                for ticket in original_pair:
                    ticket.dispatched = True
                clock.now += 90.0  # Every wave, not just the first pair, is slow.
                for waiting in queue._tickets():
                    self.assertFalse(queue._check(waiting))
                for ticket in original_pair:
                    ticket.progress = True  # Simulated genuine terminal result.
                    completed.append(ticket.call_id)
                    queue.release(ticket)
            self.assertEqual(len(completed), 30)
            self.assertEqual(len(set(completed)), 30)
            self.assertEqual(clock.now, 1350.0)
            self.assertTrue(any(t.granted_at - t.queued_at > 900 for t in tickets))
            self.assertEqual([op.completed_calls for op in operations], [3] * 10)
            self.assertTrue(all(op.last_progress_at for op in operations))
            self.assertFalse(queue._tickets())

            # Another user's genuine progress keeps the global queue live, but
            # must not renew this waiting task's own starvation allowance.
            isolated = self.manager(physical=2, claude=1, doubao=1, pending_calls=64,
                queue_seconds=900, claude_rpm=30)
            blocked_op, _ = isolated.register("blocked-user", "blocked")
            stuck_op, _ = isolated.register("stuck-wire-owner", "original-wire")
            healthy_op, _ = isolated.register("healthy-user", "other-progress")
            started = clock.now
            stuck = isolated.calls.enqueue(stuck_op, "stuck-original", "claude")
            stuck.dispatched = True
            healthy = isolated.calls.enqueue(healthy_op, "healthy-0", "doubao")
            healthy.dispatched = True
            blocked = isolated.calls.enqueue(blocked_op, "blocked-call", "claude")
            for offset in (200, 400, 600, 800, 901):
                clock.now = started + offset
                healthy.progress = True
                isolated.calls.release(healthy)
                healthy = isolated.calls.enqueue(healthy_op, f"healthy-{offset}", "doubao")
                healthy.dispatched = True
                if offset < 900:
                    self.assertFalse(isolated.calls._check(blocked))
                else:
                    with self.assertRaisesRegex(core.AdmissionError, "^MODEL_QUEUE_WAIT_EXCEEDED$"):
                        isolated.calls._check(blocked)
            self.assertEqual(blocked_op.last_progress, started)
            self.assertEqual(blocked_op.completed_calls, 0)
            self.assertFalse(blocked.dispatched)
            self.assertFalse(stuck.closed, "starvation must not reclaim another dispatched wire")
            isolated.calls.release(blocked)
            isolated.calls.release(healthy)
            isolated.calls.release(stuck)


class PublicJSONMemoryBudgetTests(unittest.TestCase):
    def test_missing_length_reserves_cap_shrinks_to_actual_and_rejects_overlimit(self):
        """Actual boundary/auth; tiny bytes test accounting, not memory capacity."""
        import json
        import tempfile
        import db
        import auth
        import public_account

        async def run(boundary, token, owner):
            read_entered, release_body = asyncio.Event(), asyncio.Event()
            handler_entered, finish_handler = asyncio.Event(), asyncio.Event()
            counters = {"handler": 0, "receive": {}}

            async def app(scope, receive, send):
                self.assertEqual(public._invocation.get().user_id, owner)
                counters["handler"] += 1
                self.assertEqual((await receive())["body"], b"{}")
                await send({"type": "http.response.start", "status": 200, "headers": []})
                handler_entered.set()
                await finish_handler.wait()
                await send({"type": "http.response.body", "body": b"{}"})
            boundary.app = app

            async def request(label, length, body=b"{}", hold=False):
                headers = [(b"content-type", b"application/json"), (b"origin", b"https://noteaipro.com"),
                           (b"authorization", ("Bearer " + token).encode()),
                           (b"x-request-id", ("mock-memory-" + label).encode())]
                if length is not None:
                    headers.append((b"content-length", str(length).encode()))
                scope = {"type": "http", "http_version": "1.1", "method": "POST",
                         "path": "/generate/stream", "raw_path": b"/generate/stream", "query_string": b"",
                         "scheme": "https", "headers": headers,
                         "client": ("127.0.0.1", 1234), "server": ("synthetic", 443)}
                sent = []
                counters["receive"][label] = 0
                async def receive():
                    counters["receive"][label] += 1
                    if hold:
                        read_entered.set()
                        await release_body.wait()
                    return {"type": "http.request", "body": body, "more_body": False}
                async def send(message):
                    sent.append(message)
                await boundary(scope, receive, send)
                status = next(x["status"] for x in sent if x["type"] == "http.response.start")
                text = b"".join(x.get("body", b"") for x in sent if x["type"] == "http.response.body")
                return status, json.loads(text)

            # No Content-Length: reserve the full existing cap before reading.
            first = asyncio.create_task(request("missing-length", None, hold=True))
            try:
                await asyncio.wait_for(read_entered.wait(), 3)
                self.assertEqual(boundary.media_json_budget, 128 * 1024 * 1024)
                self.assertEqual(boundary.media_json_bytes, boundary.media_json_budget)
                status, detail = await request("busy", 2)
                self.assertEqual(status, 429)
                self.assertEqual(detail["detail"]["code"], "MODEL_INPUT_CAPACITY_BUSY")
                self.assertEqual(counters["receive"]["busy"], 0)
                release_body.set()
                await asyncio.wait_for(handler_entered.wait(), 3)
                self.assertEqual(boundary.media_json_bytes, 2, "shrink to actual bytes but hold them through SSE")
                status, _ = await request("under-declared", 1)
                self.assertEqual(status, 413)
                self.assertEqual(boundary.media_json_bytes, 2)
                status, _ = await request("over-cap", boundary.media_json_budget + 1)
                self.assertEqual(status, 413)
                self.assertEqual(counters["receive"]["over-cap"], 0)
                self.assertEqual(counters["handler"], 1)
            finally:
                release_body.set()
                finish_handler.set()
                await first
            self.assertEqual(boundary.media_json_bytes, 0)
            self.assertEqual(db.fetchone("SELECT count(*) n FROM usage_records")["n"], 0)
            self.assertEqual(db.fetchone("SELECT count(*) n FROM idempotency_requests")["n"], 0)

        old_path = db._DB_PATH
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.dict(os.environ, {"DATABASE_URL": "", "NOTEAI_PUBLIC_PRODUCT": "1",
                 "NOTEAI_MODEL_CONFIG_ENABLED": "0", "NOTEAI_PUBLIC_ORIGINS": "https://noteaipro.com"}), \
             mock.patch.object(public, "image_enabled", return_value=True):
            try:
                db._DB_PATH = Path(directory) / "memory-boundary.sqlite"
                db.init_db()
                user = auth.create_user("memory-fixture", "SyntheticPassword!42", phone="+8613800990001",
                    phone_verified=True, contract_version=public.CONTRACT_VERSION, privacy_accepted=True,
                    cross_border_notice_acknowledged=True)
                token = auth.create_token(user["id"])
                manager = core.Admission(core.Limits())
                with mock.patch.object(core, "_instance", manager):
                    boundary = public_account.PublicAccountBoundary(None)
                    asyncio.run(run(boundary, token, user["id"]))
                self.assertEqual(manager.operations, {})
                self.assertEqual(manager.aliases, {})
            finally:
                db._DB_PATH = old_path
