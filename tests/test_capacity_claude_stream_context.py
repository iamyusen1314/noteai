"""Real stream-task boundaries and body tickets; synthetic HTTP, no provider/DB."""
import asyncio
import contextvars
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import claude_gateway_protocol as protocol
import model_admission as admission
import model_router as router
import public_product as public


class ClaudeStreamContextTests(unittest.TestCase):
    def environment(self, enabled):
        return mock.patch.dict(os.environ, {
            "NOTEAI_PUBLIC_PRODUCT": "1",
            "NOTEAI_MODEL_CAPACITY_ENABLED": "1" if enabled else "0",
            "NOTEAI_MODEL_REMOTE_CONCURRENCY": "4",
            "NOTEAI_CLAUDE_TRANSPORT": "gateway",
            "NOTEAI_CLAUDE_GATEWAY_INFLIGHT_BODY_BYTES": str(32 * 1024 * 1024),
        })

    async def body_scenario(self, *, deadline=True):
        manager = admission.Admission()
        operation, _ = manager.register("synthetic-stream-owner", "body-context")
        marker = public._invocation.set(public.Invocation(operation.user_id,
            "body-context", admission_state=operation))
        async def frames():
            async with public.claude_body_slot(b"synthetic-stream-body"):
                yield "content"
                yield "usage-end-turn"
        values, error = [], None
        try:
            with mock.patch.object(admission, "_instance", manager):
                stream = frames()
                execution_context = contextvars.copy_context()
                try:
                    while True:
                        values.append(await router._await_with_gateway_deadline(anext(stream),
                            asyncio.get_running_loop().time() + 2 if deadline else None,
                            execution_context=execution_context))
                except StopAsyncIteration:
                    pass
                except Exception as exc:
                    error = {"class": type(exc).__name__,
                        "different_context": "different Context" in str(exc)}
                finally:
                    await router._close_async_iterator(stream, execution_context=execution_context)
                manager.cancel(operation)
                manager.finish(operation)
                return {"values": values, "error": error,
                    "body_active": len(manager.gateway_bodies.active),
                    "body_waiting": len(manager.gateway_bodies.waiting),
                    "outstanding": operation.outstanding,
                    "operations_after_request_cleanup": len(manager.operations)}
        finally:
            public._invocation.reset(marker)
            manager.finish(operation)

    def test_body_lease_survives_separate_anext_tasks_and_releases_at_end(self):
        for enabled, deadline in ((False, True), (True, True), (True, False)):
            with self.subTest(capacity_enabled=enabled, deadline=deadline), self.environment(enabled):
                result = asyncio.run(self.body_scenario(deadline=deadline))
                print("COVER_CLAUDE_BODY_CONTEXT_PROOF=" + json.dumps({
                    "capacity_enabled": enabled, "deadline": deadline, **result}, sort_keys=True))
                self.assertIsNone(result["error"], result)
                self.assertEqual(result["values"], ["content", "usage-end-turn"])
                self.assertEqual((result["body_active"], result["body_waiting"],
                    result["outstanding"], result["operations_after_request_cleanup"]),
                    (0, 0, 0, 0))

    async def gateway_scenario(self, *, action="collect", disconnect_after_usage=False):
        manager = admission.Admission()
        operation, _ = manager.register("synthetic-stream-owner", "gateway-context")
        marker = public._invocation.set(public.Invocation(operation.user_id,
            "gateway-context", admission_state=operation))
        request = router.ClaudeMessageRequest(model=router.CLAUDE_SONNET,
            max_tokens=16000, messages=({"role": "user", "content": "synthetic source"},))
        usage = {"input_tokens": 3, "output_tokens": 2,
            "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        wire_events = [
            {"type": "content", "text": "synthetic complete output"},
            {"type": "usage", "usage": usage, "model": request.model,
                "stop_reason": "end_turn"},
            {"type": "done"},
        ]
        http_calls, recorded, terminals = [], [], []
        content_received, wire_waiting, wire_release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        def encoded(event):
            return (json.dumps({"protocol_version": protocol.PROTOCOL_VERSION, **event}) + "\n").encode()
        class Wire(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield encoded(wire_events[0])
                if action == "cancel":
                    wire_waiting.set()
                    await wire_release.wait()
                yield encoded(wire_events[1])
                if disconnect_after_usage:
                    raise httpx.ReadError("synthetic stream disconnected after usage")
                yield encoded(wire_events[2])
        def handler(http_request):
            http_calls.append(http_request.url.path)
            return httpx.Response(200, headers={"content-type": "application/x-ndjson"},
                stream=Wire())
        transport = router.GatewayClaudeTransport(base_url="https://gateway.example.invalid",
            authority="gateway.example.invalid", key_id="synthetic-key", secret="synthetic-secret",
            config_epoch="synthetic-config", key_epoch="synthetic-key-epoch",
            http_transport=httpx.MockTransport(handler))
        async def reserve(original, body):
            self.assertIs(original, request)
            self.assertEqual(body, router.GatewayClaudeTransport._body(request))
            original.call_state["id"] = original.operation_id
        def record(model, value, **kwargs):
            recorded.append({"model": model, "usage": value, **kwargs})
        def terminal(call_id, status, **kwargs):
            terminals.append({"call_id": call_id, "status": status, **kwargs})
        values, error, cancel_waited = [], None, False
        try:
            with mock.patch.object(admission, "_instance", manager), \
                 mock.patch.object(router, "get_claude_transport", return_value=transport), \
                 mock.patch.object(public, "admit_claude", side_effect=reserve), \
                 mock.patch.object(router, "_record_claude_usage", side_effect=record), \
                 mock.patch.object(public, "_record_response", side_effect=terminal):
                stream = router._claude_transport_stream(request.model, request,
                    absolute_deadline=asyncio.get_running_loop().time() + 2)
                async def consume():
                    async for event in stream:
                        values.append(event.type)
                        if event.type == "content":
                            content_received.set()
                try:
                    if action == "close":
                        values.append((await anext(stream)).type)
                        await stream.aclose()
                    elif action == "cancel":
                        consumer = asyncio.create_task(consume())
                        await asyncio.wait_for(content_received.wait(), 1)
                        await asyncio.wait_for(wire_waiting.wait(), 1)
                        consumer.cancel()
                        await asyncio.sleep(0)
                        cancel_waited = (not consumer.done()
                            and len(manager.gateway_bodies.active) == 1
                            and len(manager.calls.active) == 1)
                        wire_release.set()
                        await consumer
                    else:
                        await consume()
                except (Exception, asyncio.CancelledError) as exc:
                    error = {"class": type(exc).__name__,
                        "different_context": "different Context" in str(exc),
                        "code": getattr(exc, "code", None)}
                finally:
                    wire_release.set()
                    await stream.aclose()
                manager.cancel(operation)
                manager.finish(operation)
                return {"events": values, "error": error, "http_calls": len(http_calls),
                    "recorded": recorded, "terminal": terminals,
                    "body_active": len(manager.gateway_bodies.active),
                    "body_waiting": len(manager.gateway_bodies.waiting),
                    "remote_active": len(manager.calls.active),
                    "remote_deferred": len(manager.calls.deferred),
                    "outstanding": operation.outstanding,
                    "cancel_waited_for_original": cancel_waited,
                    "operations_after_request_cleanup": len(manager.operations)}
        finally:
            public._invocation.reset(marker)
            manager.finish(operation)

    def test_complete_mock_gateway_stream_settles_without_context_error_or_body_leak(self):
        for enabled in (False, True):
            with self.subTest(capacity_enabled=enabled), self.environment(enabled):
                result = asyncio.run(self.gateway_scenario())
                print("COVER_CLAUDE_STREAM_CONTEXT_PROOF=" + json.dumps({
                    "capacity_enabled": enabled, **result}, sort_keys=True))
                self.assertEqual(result["http_calls"], 1)
                self.assertIsNone(result["error"], result)
                self.assertEqual(result["events"], ["content", "usage"])
                self.assertEqual(len(result["recorded"]), 1)
                self.assertEqual(result["recorded"][0]["usage"]["output_tokens"], 2)
                self.assertEqual(len(result["terminal"]), 1)
                self.assertEqual(result["terminal"][0]["status"], 200)
                self.assertFalse(result["terminal"][0]["unknown"])
                self.assertEqual((result["body_active"], result["body_waiting"],
                    result["remote_active"], result["remote_deferred"],
                    result["outstanding"], result["operations_after_request_cleanup"]),
                    (0, 0, 0, 0, 0, 0))

    def test_usage_then_disconnect_stays_unknown_without_replay_and_releases_tickets(self):
        with self.environment(True):
            result = asyncio.run(self.gateway_scenario(disconnect_after_usage=True))
        self.assertEqual(result["events"], ["content", "usage"])
        self.assertEqual(result["error"]["code"], "GATEWAY_NETWORK_ERROR")
        self.assertFalse(result["error"]["different_context"])
        self.assertEqual(result["http_calls"], 1)
        self.assertEqual(len(result["recorded"]), 1)
        self.assertEqual(len(result["terminal"]), 1)
        self.assertTrue(result["terminal"][0]["unknown"])
        self.assertEqual((result["body_active"], result["remote_active"],
            result["outstanding"], result["operations_after_request_cleanup"]), (0, 0, 0, 0))

    def test_close_and_cancel_drain_original_complete_stream_before_releasing(self):
        for action in ("close", "cancel"):
            with self.subTest(action=action), self.environment(True):
                result = asyncio.run(self.gateway_scenario(action=action))
                self.assertEqual(result["events"], ["content"])
                if action == "cancel":
                    self.assertEqual(result["error"]["class"], "CancelledError")
                    self.assertTrue(result["cancel_waited_for_original"])
                else:
                    self.assertIsNone(result["error"], result)
                self.assertEqual(result["http_calls"], 1)
                self.assertEqual(len(result["recorded"]), 1)
                self.assertEqual(len(result["terminal"]), 1)
                self.assertFalse(result["terminal"][0]["unknown"])
                self.assertEqual((result["body_active"], result["remote_active"],
                    result["outstanding"], result["operations_after_request_cleanup"]), (0, 0, 0, 0))

    def test_two_iterator_contexts_keep_body_tickets_and_owners_isolated(self):
        async def scenario():
            manager = admission.Admission()
            entered = [asyncio.Event(), asyncio.Event()]
            release = [asyncio.Event(), asyncio.Event()]
            leases, operations = {}, {}
            async def consume(index):
                owner = "synthetic-owner-" + str(index)
                operation, _ = manager.register(owner, "isolated-" + str(index))
                operations[index] = operation
                marker = public._invocation.set(public.Invocation(owner, "isolated-" + str(index),
                    admission_state=operation))
                try:
                    async with public.model_admission("isolated-call-" + str(index), "claude",
                            model_id=router.CLAUDE_SONNET) as remote:
                        execution_context = contextvars.copy_context()
                        async def frames():
                            async with public.claude_body_slot(b"synthetic-body" * (index + 1)):
                                body = public._gateway_body_lease.get()["ticket"]
                                self.assertIs(body.operation, operation)
                                self.assertIs(public._model_lease.get(), remote)
                                self.assertEqual(public._invocation.get().user_id, owner)
                                yield body
                                self.assertIs(public._gateway_body_lease.get()["ticket"], body)
                                yield index
                        stream = frames()
                        try:
                            leases[index] = await router._await_with_gateway_deadline(anext(stream),
                                None, execution_context=execution_context)
                            entered[index].set()
                            await release[index].wait()
                            self.assertEqual(await router._await_with_gateway_deadline(anext(stream),
                                None, execution_context=execution_context), index)
                            with self.assertRaises(StopAsyncIteration):
                                await router._await_with_gateway_deadline(anext(stream), None,
                                    execution_context=execution_context)
                        finally:
                            await router._close_async_iterator(stream, execution_context=execution_context)
                finally:
                    public._invocation.reset(marker)
                    manager.cancel(operation)
                    manager.finish(operation)
            with mock.patch.object(admission, "_instance", manager):
                tasks = [asyncio.create_task(consume(index)) for index in range(2)]
                try:
                    await asyncio.wait_for(asyncio.gather(*(event.wait() for event in entered)), 1)
                    self.assertIsNone(public._gateway_body_lease.get())
                    self.assertIsNone(public._model_lease.get())
                    self.assertEqual((len(manager.gateway_bodies.active), len(manager.calls.active)), (2, 2))
                    self.assertIsNot(leases[0], leases[1])
                    release[0].set()
                    await asyncio.wait_for(tasks[0], 1)
                    self.assertTrue(leases[0].closed)
                    self.assertFalse(leases[1].closed)
                    self.assertEqual((len(manager.gateway_bodies.active), len(manager.calls.active)), (1, 1))
                    self.assertEqual(list(manager.operations.values()), [operations[1]])
                    release[1].set()
                    await asyncio.wait_for(tasks[1], 1)
                    self.assertEqual((manager.gateway_bodies.active, manager.calls.active,
                        manager.operations), ({}, {}, {}))
                finally:
                    for event in release:
                        event.set()
                    await asyncio.gather(*tasks, return_exceptions=True)
        with self.environment(True):
            asyncio.run(scenario())

    def test_iterator_aclose_shields_and_joins_same_context_cleanup_after_repeated_cancel(self):
        async def scenario():
            manager = admission.Admission()
            operation, _ = manager.register("synthetic-close-owner", "shielded-close")
            marker = public._invocation.set(public.Invocation(operation.user_id,
                "shielded-close", admission_state=operation))
            cleanup_entered, cleanup_release = asyncio.Event(), asyncio.Event()
            cleanup_observed = []
            async def frames():
                async with public.claude_body_slot(b"synthetic-close-body"):
                    try:
                        yield "content"
                    finally:
                        cleanup_entered.set()
                        await cleanup_release.wait()
                        cleanup_observed.append(public._gateway_body_lease.get()["ticket"].closed)
            execution_context = contextvars.copy_context()
            stream, closing = frames(), None
            try:
                with mock.patch.object(admission, "_instance", manager):
                    self.assertEqual(await router._await_with_gateway_deadline(anext(stream),
                        None, execution_context=execution_context), "content")
                    self.assertIsNone(public._gateway_body_lease.get())
                    closing = asyncio.create_task(router._close_async_iterator(stream,
                        execution_context=execution_context))
                    await asyncio.wait_for(cleanup_entered.wait(), 1)
                    for _ in range(2):
                        closing.cancel()
                        await asyncio.sleep(0)
                        self.assertFalse(closing.done())
                        self.assertEqual(len(manager.gateway_bodies.active), 1)
                    cleanup_release.set()
                    with self.assertRaises(asyncio.CancelledError):
                        await closing
                    self.assertEqual(cleanup_observed, [False])
                    manager.cancel(operation)
                    manager.finish(operation)
                    self.assertEqual((manager.gateway_bodies.active, operation.outstanding,
                        manager.operations), ({}, 0, {}))
            finally:
                cleanup_release.set()
                if closing is not None:
                    await asyncio.gather(closing, return_exceptions=True)
                public._invocation.reset(marker)
                manager.finish(operation)
        with self.environment(True):
            asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
