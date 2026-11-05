"""API-side Gateway body backpressure with real tickets and synthetic HTTP."""
import asyncio
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest import mock

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import claude_gateway_protocol as protocol
import model_admission as admission
import model_capacity as capacity
import model_router as router
import public_product as public


class GatewayBodyAdmissionTests(unittest.TestCase):
    def request(self):
        return router.ClaudeMessageRequest(model=router.CLAUDE_HAIKU, max_tokens=1200,
            messages=({"role": "user", "content": "真实原文" * 40},),
            operation_id=router._new_operation_id())

    def transport(self, handler):
        return router.GatewayClaudeTransport(base_url="https://gateway.example.invalid",
            key_id="synthetic-key", secret="synthetic-secret", config_epoch="test-config-1",
            key_epoch="test-key-1", http_transport=httpx.MockTransport(handler))

    def response(self):
        return httpx.Response(200, json={"protocol_version": protocol.PROTOCOL_VERSION,
            "text_blocks": ["synthetic-complete"], "model": router.CLAUDE_HAIKU,
            "stop_reason": "end_turn", "usage": {"input_tokens": 10, "output_tokens": 1,
                "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}})

    def environment(self, maximum):
        return mock.patch.dict(os.environ, {"NOTEAI_PUBLIC_PRODUCT": "1",
            "NOTEAI_MODEL_CAPACITY_ENABLED": "1", "NOTEAI_MODEL_REMOTE_CONCURRENCY": "4",
            "NOTEAI_CLAUDE_GATEWAY_INFLIGHT_BODY_BYTES": str(maximum),
            "NOTEAI_MODEL_CAPACITY_LIMITS_JSON": json.dumps({router.CLAUDE_HAIKU: {
                "rpm": 100, "itpm": 1000000, "otpm": 100000,
                "evidence_ref": "synthetic-body-backpressure"}})})

    def test_async_transport_waits_before_quota_and_frees_remote_place_for_other_models(self):
        requests = [self.request() for _ in range(3)]
        bound = len(router.GatewayClaudeTransport._body(requests[0]))
        async def scenario():
            manager = admission.Admission()
            entered, released = asyncio.Event(), asyncio.Event()
            sent, reserved = [], []
            async def reserve(request, body):
                self.assertLessEqual(sum(t.weight for t in manager.gateway_bodies.active.values()), bound)
                reserved.append(request.operation_id)
            async def handler(request):
                sent.append(request.content); entered.set()
                await released.wait()
                return self.response()
            transport = self.transport(handler)
            async def invoke(index):
                operation, _ = manager.register("body-owner-" + str(index), str(index))
                marker = public._invocation.set(public.Invocation(operation.user_id, str(index),
                    admission_state=operation))
                try:
                    return await transport.create_message(requests[index])
                finally:
                    public._invocation.reset(marker); manager.finish(operation)
            with mock.patch.object(admission, "_instance", manager), \
                 mock.patch.object(public, "admit_claude", side_effect=reserve):
                first = asyncio.create_task(invoke(0))
                await asyncio.wait_for(entered.wait(), 1)
                second = asyncio.create_task(invoke(1))
                for _ in range(100):
                    if manager.gateway_bodies.waiting: break
                    await asyncio.sleep(.005)
                self.assertTrue(manager.gateway_bodies.waiting)
                self.assertEqual((len(reserved), len(sent), len(manager.calls.deferred)), (1, 1, 1))
                other = admission.Operation("other-model", "lite")
                ticket = await asyncio.wait_for(manager.calls.acquire_async(other, "lite-call", "doubao",
                    model_id="doubao-seed-2-0-lite-260428"), .5)
                manager.calls.release(ticket)
                second.cancel()
                with self.assertRaises(asyncio.CancelledError): await second
                self.assertEqual((len(reserved), len(sent)), (1, 1))
                released.set(); await first
                third = await invoke(2)
                self.assertEqual(third.text_blocks, ("synthetic-complete",))
                self.assertEqual(sent, [router.GatewayClaudeTransport._body(requests[i]) for i in (0, 2)])
            self.assertEqual((manager.calls.active, manager.calls.deferred, manager.gateway_bodies.active,
                manager.gateway_bodies.waiting, manager.operations), ({}, {}, {}, {}, {}))
        with self.environment(bound): asyncio.run(scenario())

    def test_sync_transport_exception_releases_body_and_original_ticket(self):
        request = self.request(); body = router.GatewayClaudeTransport._body(request)
        with self.environment(len(body)):
            manager = admission.Admission()
            operation, _ = manager.register("sync-owner", "sync")
            marker = public._invocation.set(public.Invocation("sync-owner", "sync", admission_state=operation))
            def handler(_request):
                self.assertEqual(sum(t.weight for t in manager.gateway_bodies.active.values()), len(body))
                raise httpx.ReadTimeout("synthetic remote timeout")
            try:
                with mock.patch.object(admission, "_instance", manager), \
                     mock.patch.object(public, "admit_claude_sync"):
                    with self.assertRaises(router.ClaudeGatewayError) as error:
                        self.transport(handler).create_message_sync(request)
                    self.assertTrue(error.exception.usage_audit_required)
                self.assertEqual((manager.calls.active, manager.calls.deferred,
                    manager.gateway_bodies.active), ({}, {}, {}))
                self.assertEqual(operation.outstanding, 0)
            finally:
                public._invocation.reset(marker); manager.finish(operation)

    def test_stream_retains_body_until_generator_is_closed(self):
        request = self.request(); body = router.GatewayClaudeTransport._body(request)
        async def scenario():
            manager = admission.Admission()
            operation, _ = manager.register("stream-owner", "stream")
            marker = public._invocation.set(public.Invocation("stream-owner", "stream", admission_state=operation))
            async def handler(_request):
                return httpx.Response(200, content=json.dumps({"protocol_version": protocol.PROTOCOL_VERSION,
                    "type": "content", "text": "partial"}) + "\n",
                    headers={"content-type": "application/x-ndjson"})
            try:
                with mock.patch.object(admission, "_instance", manager), \
                     mock.patch.object(public, "admit_claude"):
                    stream = self.transport(handler).stream_message(request)
                    first = await anext(stream)
                    self.assertEqual(first.text, "partial")
                    self.assertEqual(sum(t.weight for t in manager.gateway_bodies.active.values()), len(body))
                    await stream.aclose()
                self.assertEqual((manager.gateway_bodies.active, manager.calls.active,
                                  manager.calls.deferred, operation.outstanding), ({}, {}, {}, 0))
            finally:
                public._invocation.reset(marker); manager.finish(operation)
        with self.environment(len(body)): asyncio.run(scenario())

    def test_disabled_mode_does_not_create_or_require_body_admission(self):
        with mock.patch.dict(os.environ, {"NOTEAI_PUBLIC_PRODUCT": "0", "NOTEAI_MODEL_CAPACITY_ENABLED": "0"}), \
             mock.patch.object(admission, "current", side_effect=AssertionError("legacy must not create body pool")):
            self.assertEqual(self.transport(lambda _request: self.response()).create_message_sync(
                self.request()).text_blocks, ("synthetic-complete",))

    def test_verified_gateway_combined_rpm_configuration_does_not_reject_api_startup(self):
        with self.environment(1024), mock.patch.dict(os.environ, {
                "NOTEAI_CLAUDE_GATEWAY_REQUESTS_PER_MINUTE": "20000"}):
            self.assertEqual(admission.Admission().limits.claude_rpm, 20000)
            with mock.patch.dict(os.environ, {"NOTEAI_MODEL_CAPACITY_ENABLED": "0"}):
                with self.assertRaises(ValueError): admission.Admission()

    def test_quota_wait_releases_body_for_other_claude_model_before_retrying_same_call(self):
        async def scenario():
            manager = admission.Admission()
            operation, _ = manager.register("quota-owner", "quota")
            marker = public._invocation.set(public.Invocation("quota-owner", "quota", admission_state=operation))
            attempts, ready = [], asyncio.Event()
            def reserve():
                attempts.append(public._model_lease.get().call_id)
                self.assertEqual(sum(t.weight for t in manager.gateway_bodies.active.values()), 1024)
                if not ready.is_set(): raise capacity.QuotaDeferred(time.time() + .1, "synthetic RPM full")
                return "original-physical-id"
            async def waiting():
                async with public.model_admission("original-physical-id", "claude", model_id=router.CLAUDE_HAIKU), \
                     public.claude_body_slot(b"x" * 1024):
                    return await public._reserve_callable_with_capacity(reserve)
            try:
                with mock.patch.object(admission, "_instance", manager):
                    task = asyncio.create_task(waiting())
                    try:
                        for _ in range(100):
                            if manager.calls.deferred and attempts: break
                            await asyncio.sleep(.005)
                        self.assertTrue(manager.calls.deferred)
                        self.assertEqual(manager.gateway_bodies.active, {})
                        second = admission.Operation("other-claude-model", "sonnet")
                        other_marker = public._invocation.set(public.Invocation(second.user_id, "sonnet",
                            admission_state=second))
                        try:
                            async with public.model_admission("other-physical-id", "claude", model_id=router.CLAUDE_SONNET), \
                                 public.claude_body_slot(b"y" * 1024):
                                self.assertEqual(sum(t.weight for t in manager.gateway_bodies.active.values()), 1024)
                        finally: public._invocation.reset(other_marker)
                        ready.set()
                        self.assertEqual(await asyncio.wait_for(task, 1), "original-physical-id")
                    finally:
                        if not task.done(): task.cancel()
            finally:
                public._invocation.reset(marker); manager.finish(operation)
            self.assertEqual(set(attempts), {"original-physical-id"})
            self.assertGreaterEqual(len(attempts), 2)
            self.assertEqual((manager.gateway_bodies.active, manager.calls.active, manager.calls.deferred), ({}, {}, {}))
        with self.environment(1024): asyncio.run(scenario())

    def test_sync_quota_rollback_releases_and_reacquires_body_before_committed_reservation(self):
        with self.environment(1024):
            manager = admission.Admission()
            operation, _ = manager.register("sync-quota-owner", "quota")
            marker = public._invocation.set(public.Invocation(operation.user_id, "quota", admission_state=operation))
            attempts = []
            def reserve(*_args, **kwargs):
                attempts.append(kwargs["call_id"])
                self.assertEqual(sum(t.weight for t in manager.gateway_bodies.active.values()), 1024)
                if len(attempts) == 1: raise capacity.QuotaDeferred(time.time() + .015, "synthetic RPM full")
                return kwargs["call_id"]
            def during_wait(seconds):
                self.assertEqual(manager.gateway_bodies.active, {})
                time.sleep(seconds)
            try:
                with mock.patch.object(admission, "_instance", manager), \
                     mock.patch.object(public, "_reserve_payload", side_effect=reserve), \
                     mock.patch.object(operation.cancelled, "wait", side_effect=during_wait):
                    with public.model_admission_sync("same-physical-id", "claude", model_id=router.CLAUDE_HAIKU), \
                         public.claude_body_slot_sync(b"x" * 1024):
                        self.assertEqual(public.reserve_payload_with_capacity({}, 1, call_id="same-physical-id"),
                                         "same-physical-id")
                self.assertEqual(attempts, ["same-physical-id", "same-physical-id"])
                self.assertEqual((manager.gateway_bodies.active, manager.calls.active, manager.calls.deferred), ({}, {}, {}))
            finally:
                public._invocation.reset(marker); manager.finish(operation)

    def test_cancel_after_quota_wake_while_reacquiring_body_is_known_unsent_and_leak_free(self):
        request = self.request()
        body = router.GatewayClaudeTransport._body(request)
        async def scenario():
            manager = admission.Admission()
            operation, _ = manager.register("cancel-reacquire-owner", "cancel-reacquire")
            blocker = admission.Operation("other-claude-owner", "active-body")
            marker = public._invocation.set(public.Invocation(operation.user_id,
                "cancel-reacquire", admission_state=operation))
            attempts, sent, reacquiring = [], [], asyncio.Event()
            original_acquire = public._acquire_gateway_body_async
            acquire_count = 0
            def reserve(observed_request, observed_body):
                self.assertIs(observed_request, request)
                self.assertEqual(observed_body, body)
                self.assertEqual(sum(t.weight for t in manager.gateway_bodies.active.values()), len(body))
                attempts.append(observed_request.operation_id)
                raise capacity.QuotaDeferred(time.time() + .1, "synthetic per-model quota full")
            async def observe_acquire(lease=None):
                nonlocal acquire_count
                acquire_count += 1
                if acquire_count == 2:
                    reacquiring.set()
                return await original_acquire(lease)
            async def handler(observed_request):
                sent.append(observed_request.content)
                return self.response()
            task, blocker_ticket = None, None
            try:
                with mock.patch.object(admission, "_instance", manager), \
                     mock.patch.object(public, "_reserve_claude_once", side_effect=reserve), \
                     mock.patch.object(public, "_acquire_gateway_body_async", side_effect=observe_acquire), \
                     mock.patch.object(public, "_record_response") as record_response:
                    task = asyncio.create_task(self.transport(handler).create_message(request))
                    for _ in range(100):
                        if attempts and manager.calls.deferred:
                            break
                        await asyncio.sleep(.005)
                    self.assertEqual(attempts, [request.operation_id])
                    self.assertEqual(manager.gateway_bodies.active, {})
                    blocker_ticket = await manager.gateway_bodies.acquire_async(
                        blocker, "other-active-body-id", "claude_body", weight=len(body))
                    await asyncio.wait_for(reacquiring.wait(), 1)
                    self.assertTrue(manager.gateway_bodies.waiting)
                    self.assertIn(request.operation_id, manager.calls.deferred)
                    self.assertEqual(operation.outstanding, 2)
                    task.cancel()
                    with self.assertRaises(router.ClaudeRequestCancelled) as cancelled:
                        await task
                    self.assertFalse(cancelled.exception.usage_audit_required)
                    self.assertEqual(attempts, [request.operation_id])
                    self.assertEqual(sent, [])
                    self.assertFalse(request.call_state.get("sent"))
                    self.assertIsNone(request.call_state.get("id"))
                    record_response.assert_not_called()
                    self.assertEqual((manager.calls.active, manager.calls.deferred,
                                      manager.gateway_bodies.waiting, operation.outstanding),
                                     ({}, {}, {}, 0))
                    # Cancellation must release only its own waiting body ticket.
                    self.assertIs(manager.gateway_bodies.active.get(blocker_ticket.call_id),
                                  blocker_ticket)
                    manager.gateway_bodies.release(blocker_ticket)
                    blocker_ticket = None
            finally:
                if task is not None and not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                if blocker_ticket is not None:
                    manager.gateway_bodies.release(blocker_ticket)
                public._invocation.reset(marker)
                manager.finish(operation)
            self.assertEqual((manager.gateway_bodies.active, manager.gateway_bodies.waiting,
                              manager.calls.active, manager.calls.deferred, manager.operations),
                             ({}, {}, {}, {}, {}))
        with self.environment(len(body)):
            asyncio.run(scenario())


if __name__ == "__main__": unittest.main()
