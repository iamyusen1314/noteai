"""Text adapters: real SQLite/queue, synthetic HTTP, no external provider."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
import threading
import time
import unittest
import uuid
from unittest import mock

import httpx

from tests import test_postdelivery_reservation as fixture
import model_admission as admission
import model_capacity as capacity
import model_router

db, billing, public = fixture.db, fixture.billing, fixture.public_product


class TextCapacityAdmissionTests(unittest.TestCase):
    use_wallet = fixture.PostDeliveryReservationTests.use_wallet
    reserve = fixture.PostDeliveryReservationTests.reserve

    def setUp(self):
        fixture.PostDeliveryReservationTests.setUp(self)
        self.capacity_env = mock.patch.dict(os.environ, {
            "NOTEAI_PUBLIC_PRODUCT": "1", "NOTEAI_MODEL_CAPACITY_ENABLED": "1",
            "NOTEAI_MODEL_CAPACITY_MOONSHOT_ENABLED": "1",
            "NOTEAI_MODEL_CAPACITY_MOONSHOT_SCOPE": "moonshot-primary",
            "NOTEAI_MODEL_CAPACITY_LIMITS_JSON": "", "NOTEAI_MODEL_REMOTE_CONCURRENCY": "4"})
        self.capacity_env.start()
        with db.transaction(write=True) as tx:
            capacity.init_sqlite_schema(tx.conn)
            tx.execute("UPDATE public_trial_budget SET enabled=1,policy_mode='owner_metered'")
        self.use_wallet(32); self.claim = self.reserve()
        self.manager = admission.Admission()
        self.manager_patch = mock.patch.object(admission, "_instance", self.manager)
        self.manager_patch.start()
        self.operation, _ = self.manager.register(self.user, "f" * 64, route="/generate/stream")
        self.inv = public.Invocation(self.user, self.claim["request_id"], route="/generate/stream",
                                     admission_state=self.operation)
        self.im = public._invocation.set(self.inv)
        self.um = billing._ACTIVE_USAGE_ID.set(self.claim["charge"]["usage_id"])
        self.sent = []

    def tearDown(self):
        billing._ACTIVE_USAGE_ID.reset(self.um); public._invocation.reset(self.im)
        self.manager_patch.stop(); self.capacity_env.stop()
        fixture.PostDeliveryReservationTests.tearDown(self)

    def payload(self):
        return {"model": public.MODEL, "messages": [{"role": "user", "content": "保留原始中文与完整事实"}],
                "max_tokens": 16, "stream": False}

    def supplier(self, request):
        self.sent.append(request.content)
        return httpx.Response(200, json={"model": public.MODEL, "choices": [
            {"finish_reason": "stop", "message": {"content": "合成技术结果"}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 5}})

    def override(self, model=public.MODEL, **values):
        os.environ["NOTEAI_MODEL_CAPACITY_LIMITS_JSON"] = json.dumps({
            model: {**values, "evidence_ref": "controlled-text-admission-fixture"}})

    def rows(self):
        return [dict(row) for row in db.fetchall("SELECT * FROM public_trial_calls ORDER BY created_at,id")]

    async def wait_deferred(self):
        for _ in range(200):
            if self.manager.calls.deferred:
                return
            await asyncio.sleep(.005)
        self.fail("expected quota waiter to park its original ticket")

    def clock(self):
        current = [time.time()]
        return current, mock.patch.object(public.time, "time", side_effect=lambda: current[0]), mock.patch.object(
            capacity, "_database_now", side_effect=lambda _tx, _now: datetime.fromtimestamp(current[0], timezone.utc).timestamp())

    def test_kimi_sync_and_async_full_wire_demand_preserve_payload_cost_and_once_only_dispatch(self):
        with public.kimi_client(transport=httpx.MockTransport(self.supplier), timeout=1) as client:
            first = client.post(public.ENDPOINT, json=self.payload())
        async def run():
            async with public.kimi_async_client(transport=httpx.MockTransport(self.supplier), timeout=1) as client:
                return await client.post(public.ENDPOINT, json=self.payload())
        second = asyncio.run(run())
        self.assertEqual((first.status_code, second.status_code, len(self.sent)), (200, 200, 2))
        self.assertTrue(all(json.loads(body) == self.payload() for body in self.sent))
        for row, body in zip(self.rows(), self.sent):
            saved = json.loads(row["provenance_json"])["capacity"]
            self.assertGreaterEqual(saved["input_bound"], len(body) + 1024)
            self.assertEqual((saved["output_bound"], saved["concurrency"], saved["quota_key"]),
                             (16, 50, "moonshot-account"))
            self.assertEqual((row["reserve_milli_cny"], row["state"], row["http_status"]),
                             (public.RESERVE_MILLI_CNY, "responded", 200))
        self.assertEqual(db.fetchone("SELECT credits_used FROM usage_records WHERE id=?",
                                    (self.claim["charge"]["usage_id"],))[0], 0)
        self.assertEqual(self.manager.calls.active, {})

    def test_async_rate_wait_frees_executor_and_remote_ticket_and_starts_http_deadline_after_ready(self):
        self.override(rpm=1)
        current, wall, database_clock = self.clock()
        deadlines = []
        original = public._kimi_settlement_deadline
        def deadline(*args):
            value = original(*args); deadlines.append(value); return value
        async def run():
            asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=1))
            async with public.kimi_async_client(transport=httpx.MockTransport(self.supplier), timeout=.1) as client:
                await client.post(public.ENDPOINT, json=self.payload())
                task = asyncio.create_task(client.post(public.ENDPOINT, json=self.payload()))
                try:
                    await self.wait_deferred()
                    self.assertEqual((len(self.sent), len(deadlines), self.inv.failure), (1, 1, ""))
                    self.assertEqual(self.manager.calls.active, {})
                    # One-worker executor still serves unrelated short work.
                    marker = await asyncio.wait_for(asyncio.to_thread(lambda: "free-worker"), .5)
                    self.assertEqual(marker, "free-worker")
                    current[0] += 61
                    result = await asyncio.wait_for(task, 2)
                    self.assertEqual(result.status_code, 200)
                    self.assertEqual((len(self.sent), len(deadlines)), (2, 2))
                    self.assertGreater(deadlines[-1], time.monotonic())
                finally:
                    if not task.done(): task.cancel()
        with wall, database_clock, mock.patch.object(public, "_kimi_settlement_deadline", side_effect=deadline):
            asyncio.run(run())
        self.assertEqual(self.manager.calls.deferred, {})
        self.assertEqual(len(self.rows()), 2)

    def test_sync_rate_wait_preserves_same_ticket_identity_and_complete_request(self):
        self.override(rpm=1)
        current, wall, database_clock = self.clock()
        with wall, database_clock:
            with public.kimi_client(transport=httpx.MockTransport(self.supplier), timeout=1) as client:
                client.post(public.ENDPOINT, json=self.payload())
                def age(_seconds): current[0] += 61
                with mock.patch.object(self.operation.cancelled, "wait", side_effect=age):
                    client.post(public.ENDPOINT, json=self.payload())
        self.assertEqual(len(self.sent), 2)
        self.assertEqual((self.manager.calls.active, self.manager.calls.deferred), ({}, {}))
        self.assertEqual(self.inv.failure, "")

    def test_cancel_while_quota_parked_creates_no_second_row_or_http(self):
        self.override(rpm=1)
        async def run():
            async with public.kimi_async_client(transport=httpx.MockTransport(self.supplier), timeout=1) as client:
                await client.post(public.ENDPOINT, json=self.payload())
                task = asyncio.create_task(client.post(public.ENDPOINT, json=self.payload()))
                await self.wait_deferred(); task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
        asyncio.run(run())
        self.assertEqual((len(self.rows()), len(self.sent)), (1, 1))
        self.assertEqual((self.manager.calls.active, self.manager.calls.deferred), ({}, {}))

    def claude(self):
        request = model_router.ClaudeMessageRequest(model=model_router.CLAUDE_HAIKU,
            max_tokens=1200, messages=({"role": "user", "content": "保留完整事实"},),
            operation_id=model_router._new_operation_id())
        return request, model_router.GatewayClaudeTransport._body(request)

    def test_claude_split_quota_demand_keeps_original_cost_wire_and_operation(self):
        request, body = self.claude()
        self.override(request.model, rpm=100, itpm=1000000, otpm=100000)
        async def run():
            async with public.model_admission(request.operation_id, "claude", model_id=request.model):
                await public.admit_claude(request, body)
        asyncio.run(run())
        row = self.rows()[0]; snap = json.loads(row["provenance_json"])["capacity"]
        self.assertEqual((row["id"], request.call_state["id"]), (request.operation_id, request.operation_id))
        self.assertEqual((snap["model"], snap["output_bound"], snap["tpm"]), (request.model, 1200, None))
        self.assertGreaterEqual(snap["input_bound"], len(body) + 1024)
        self.assertEqual((snap["itpm"], snap["otpm"]), (1000000, 100000))
        self.assertEqual(body, model_router.GatewayClaudeTransport._body(request))
        self.assertNotIn("sent", request.call_state)
        public._record_response(request.operation_id, None, not_dispatched=True)

    def test_repeated_cancel_joins_only_short_claude_reservation_and_marks_exact_no_dispatch(self):
        request, body = self.claude()
        self.override(request.model, rpm=100, itpm=1000000, otpm=100000)
        entered, release = threading.Event(), threading.Event()
        once = public._reserve_claude_once
        def blocked(*args):
            entered.set()
            if not release.wait(3): raise AssertionError("fixture failed to release short transaction")
            return once(*args)
        async def run():
            async def admit():
                async with public.model_admission(request.operation_id, "claude", model_id=request.model):
                    await public.admit_claude(request, body)
            task = asyncio.create_task(admit())
            try:
                for _ in range(200):
                    if entered.is_set(): break
                    await asyncio.sleep(.005)
                self.assertTrue(entered.is_set())
                task.cancel(); await asyncio.sleep(.01); task.cancel(); await asyncio.sleep(.01)
                self.assertFalse(task.done())
            finally:
                release.set()
            with self.assertRaises(asyncio.CancelledError): await task
        with mock.patch.object(public, "_reserve_claude_once", side_effect=blocked): asyncio.run(run())
        self.assertEqual(request.call_state, {"id": request.operation_id, "finalized": True})
        self.assertEqual([(row["state"], row["http_status"]) for row in self.rows()], [("responded", None)])
        self.assertEqual((self.manager.calls.active, self.manager.calls.deferred), ({}, {}))
        self.assertEqual(self.sent, [])

    def test_cancelled_commit_ack_unknown_keeps_original_record_and_never_retries_or_sends(self):
        entered, release = threading.Event(), threading.Event()
        original = public._reserve_payload; attempts = []
        def lost_ack(*args, **kwargs):
            result = original(*args, **kwargs); attempts.append(result); entered.set()
            if not release.wait(3): raise AssertionError("fixture failed to release commit acknowledgement")
            raise RuntimeError("synthetic lost local commit acknowledgement")
        async def run():
            async with public.kimi_async_client(transport=httpx.MockTransport(self.supplier), timeout=1) as client:
                task = asyncio.create_task(client.post(public.ENDPOINT, json=self.payload()))
                try:
                    for _ in range(200):
                        if entered.is_set(): break
                        await asyncio.sleep(.005)
                    self.assertTrue(entered.is_set()); task.cancel(); await asyncio.sleep(.01)
                finally: release.set()
                with self.assertRaises(public.TrialProviderStopped) as outcome: await task
                self.assertEqual(outcome.exception.args, ("PUBLIC_TRIAL_RESERVATION_UNKNOWN",))
        with mock.patch.object(public, "_reserve_payload", side_effect=lost_ack): asyncio.run(run())
        self.assertEqual((len(attempts), len(self.rows()), len(self.sent)), (1, 1, 0))
        self.assertEqual((self.rows()[0]["state"], self.rows()[0]["http_status"]), ("dispatched", None))
        self.assertEqual(self.inv.failure, "PUBLIC_TRIAL_RESERVATION_UNKNOWN")
        self.assertEqual(db.fetchone("SELECT SUM(request_count) FROM model_capacity_buckets")[0], 1)


if __name__ == "__main__": unittest.main()
