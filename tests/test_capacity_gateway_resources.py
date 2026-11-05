"""Offline full-protocol Gateway capacity and aggregate-body resource checks."""

import asyncio
import json
import os
from pathlib import Path
import socket
import sys
import unittest
from unittest import mock

import httpx


ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT / "model", ROOT / "gateway"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import claude_gateway_protocol as protocol
from control_store import Lease, OperationClaim, OperationState
from gateway import claude_gateway as gateway


USAGE = {"input_tokens": 3, "output_tokens": 2,
         "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


class SharedStore:
    credential_method = "assume-role-with-web-identity"

    def __init__(self):
        self.nonces = set()
        self.operations = {}
        self.leases = {}
        self.limits = []
        self.rates = []
        self.fence = 0

    async def claim_nonce(self, principal, nonce, now, expires):
        identity = (principal, nonce)
        if identity in self.nonces:
            return False
        self.nonces.add(identity)
        return True

    async def admit_rate(self, principal, now, limit, window):
        self.rates.append((limit, window))
        return True

    async def acquire_lease(self, operation, slots, now, seconds):
        self.limits.append(slots)
        occupied = {lease.slot for lease in self.leases.values()}
        slot = next((value for value in range(slots) if value not in occupied), None)
        if slot is None:
            return None
        self.fence += 1
        lease = Lease(slot, operation, f"owner-{self.fence}", self.fence, now + seconds)
        self.leases[lease.owner_token] = lease
        return lease

    async def claim_operation(self, principal, operation):
        if operation in self.operations:
            return OperationClaim(self.operations[operation], False)
        self.operations[operation] = OperationState.CLAIMED
        return OperationClaim(OperationState.CLAIMED, True)

    async def begin_provider(self, operation, lease, dispatch_hash, model, now):
        if lease.owner_token not in self.leases:
            return False
        self.operations[operation] = OperationState.PROVIDER_STARTED
        return True

    async def renew_lease(self, lease, now, seconds):
        return self.leases.get(lease.owner_token)

    async def release_lease(self, lease):
        return self.leases.pop(lease.owner_token, None) is not None

    async def finish_operation(self, operation, lease, state, now, **kwargs):
        if lease.owner_token not in self.leases:
            return False
        self.operations[operation] = state
        await self.release_lease(lease)
        return True

    async def health(self):
        return True


class ControlledProvider:
    def __init__(self):
        self.calls = []
        self.opened = asyncio.Queue()
        self.release = asyncio.Event()
        self.release.set()

    async def create(self, payload):
        self.calls.append(payload["operation_id"])
        self.opened.put_nowait(payload["operation_id"])
        await self.release.wait()
        return ["controlled-result"], dict(USAGE)

    async def stream(self, payload):
        self.calls.append(payload["operation_id"])
        self.opened.put_nowait(payload["operation_id"])
        yield {"type": "content", "text": "controlled-result"}
        await self.release.wait()
        yield {"type": "usage", "usage": dict(USAGE)}


class GatewayResourceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = mock.patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": "offline-fixture-only",
            "NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID": "offline-key",
            "NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET": "offline-fixture-not-a-real-secret",
            "NOTEAI_CLAUDE_GATEWAY_AUTHORITY": "gateway.test",
            "NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH": "offline-config",
            "NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH": "offline-epoch",
            "NOTEAI_CLAUDE_GATEWAY_CONTROL_MODE": "dynamodb",
            "NOTEAI_CLAUDE_GATEWAY_PRINCIPAL_ID": "offline-principal",
            "NOTEAI_CLAUDE_GATEWAY_CAPACITY_ENABLED": "1",
            "NOTEAI_CLAUDE_GATEWAY_CONCURRENCY": "64",
            "NOTEAI_CLAUDE_GATEWAY_REQUESTS_PER_MINUTE": "20000",
            "NOTEAI_CLAUDE_GATEWAY_INFLIGHT_BODY_BYTES": str(32 * 1024 * 1024),
            "NOTEAI_CLAUDE_GATEWAY_MAX_BODY_BYTES": str(8 * 1024 * 1024),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.store = SharedStore()
        self.provider = ControlledProvider()
        for patch in (
            mock.patch.object(gateway, "_CONTROL_STORE", self.store),
            mock.patch.object(gateway, "_PROVIDER", self.provider),
            mock.patch.object(gateway, "_dynamodb_identity_environment_valid", return_value=True),
            mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")),
            mock.patch.object(socket.socket, "connect_ex", side_effect=AssertionError("network forbidden")),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        if hasattr(gateway, "_BODY_LIMITER"):
            patch = mock.patch.object(gateway, "_BODY_LIMITER", gateway.AggregateBodyLimiter())
            patch.start()
            self.addCleanup(patch.stop)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app),
                                        base_url="https://gateway.test")
        self.addAsyncCleanup(self.client.aclose)
        self.tasks = []
        self.addAsyncCleanup(self._finish_tasks)

    async def _finish_tasks(self):
        self.provider.release.set()
        for task in self.tasks:
            if not task.done():
                task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)

    def request(self, suffix="one", content="hello", path=protocol.MESSAGES_PATH):
        payload = {"operation_id": f"offline_capacity_operation_{suffix}",
                   "model": "claude-haiku-4-5-20251001", "max_tokens": 100,
                   "messages": [{"role": "user", "content": content}]}
        body = json.dumps(payload, separators=(",", ":")).encode()
        headers = protocol.auth_headers(
            key_id="offline-key", secret="offline-fixture-not-a-real-secret",
            method="POST", path=path, authority="gateway.test",
            config_epoch="offline-config", key_epoch="offline-epoch", body=body,
        )
        return body, headers

    def start(self, body, headers, path=protocol.MESSAGES_PATH):
        task = asyncio.create_task(self.client.post(path, content=body, headers=headers))
        self.tasks.append(task)
        return task

    async def entered(self):
        return await asyncio.wait_for(self.provider.opened.get(), timeout=2)

    async def test_enabled_full_signed_shared_dispatch_uses_expanded_config(self):
        body, headers = self.request()
        response = await self.client.post(protocol.MESSAGES_PATH, content=body, headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.store.limits, [64])
        self.assertEqual(self.store.rates, [(20000, 60)])
        self.assertEqual(self.store.operations[next(iter(self.store.operations))],
                         OperationState.TERMINAL_USAGE)

    async def test_default_switch_is_off_and_enabled_config_has_finite_upper_bounds(self):
        with mock.patch.dict(os.environ):
            for name in ("NOTEAI_CLAUDE_GATEWAY_CAPACITY_ENABLED",
                         "NOTEAI_CLAUDE_GATEWAY_CONCURRENCY",
                         "NOTEAI_CLAUDE_GATEWAY_REQUESTS_PER_MINUTE"):
                os.environ.pop(name, None)
            self.assertFalse(gateway._capacity_enabled())
            body, headers = self.request("defaults")
            response = await self.client.post(protocol.MESSAGES_PATH, content=body, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.store.limits, [2])
            self.assertEqual(self.store.rates, [(30, 60)])
        with mock.patch.dict(os.environ, {"NOTEAI_CLAUDE_GATEWAY_CONCURRENCY": "99999",
                                         "NOTEAI_CLAUDE_GATEWAY_REQUESTS_PER_MINUTE": "999999"}):
            body, headers = self.request("upper_bounds")
            response = await self.client.post(protocol.MESSAGES_PATH, content=body, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.store.limits[-1], 256)
            self.assertEqual(self.store.rates[-1], (60000, 60))

    async def test_aggregate_bytes_rejects_second_without_provider_or_nonce_claim(self):
        with mock.patch.dict(os.environ, {"NOTEAI_CLAUDE_GATEWAY_INFLIGHT_BODY_BYTES": "1048576"}):
            self.provider.release.clear()
            first = self.start(*self.request("first", "x" * 700000))
            await self.entered()
            body, headers = self.request("second", "y" * 700000)
            second = self.start(body, headers)
            done, _ = await asyncio.wait({second}, timeout=0.1)
            # A missing aggregate gate admits both requests into the provider.
            self.provider.release.set()
            response = await second
            self.assertTrue(done, "second body was admitted rather than rejected before dispatch")
            self.assertEqual(response.status_code, 429, response.text)
            self.assertEqual(response.json()["error"]["code"], "CONCURRENCY_LIMIT")
            self.assertEqual(len(self.provider.calls), 1)
            self.assertEqual(len(self.store.nonces), 1)
            self.assertEqual((await first).status_code, 200)

    async def test_disabled_is_legacy_with_original_config_clamps_and_no_body_reservation(self):
        self.provider.release.clear()
        with mock.patch.dict(os.environ, {
            "NOTEAI_CLAUDE_GATEWAY_CAPACITY_ENABLED": "0",
            "NOTEAI_CLAUDE_GATEWAY_INFLIGHT_BODY_BYTES": "1024",
        }):
            task = self.start(*self.request(content="x" * 2000))
            await self.entered()
            self.assertEqual(gateway._BODY_LIMITER.active_bytes, 0)
            self.assertEqual(self.store.limits, [32])
            self.assertEqual(self.store.rates, [(600, 60)])
            self.provider.release.set()
            self.assertEqual((await task).status_code, 200)

    async def test_small_full_signed_requests_progress_beyond_old_two_slots(self):
        self.provider.release.clear()
        requests = [self.request(str(index)) for index in range(6)]
        tasks = [self.start(*request) for request in requests]
        for _ in tasks:
            await self.entered()
        self.assertEqual(len(self.store.leases), 6)
        self.assertEqual(gateway._BODY_LIMITER.active_requests, 6)
        self.assertEqual(gateway._BODY_LIMITER.active_bytes,
                         sum(len(body) for body, _ in requests))
        self.provider.release.set()
        responses = await asyncio.gather(*tasks)
        self.assertEqual([response.status_code for response in responses], [200] * 6)
        self.assertEqual(gateway._BODY_LIMITER.active_bytes, 0)
        self.assertEqual(gateway._BODY_LIMITER.active_requests, 0)
        self.assertFalse(self.store.leases)

    async def test_cancel_joined_provider_retains_fence_and_releases_body(self):
        self.provider.release.clear()
        first = self.start(*self.request("cancelled"))
        await self.entered()
        self.assertGreater(gateway._BODY_LIMITER.active_bytes, 0)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.assertEqual(gateway._BODY_LIMITER.active_bytes, 0)
        self.assertEqual(gateway._BODY_LIMITER.active_requests, 0)
        self.assertFalse(self.store.leases)
        self.assertEqual(self.store.operations["offline_capacity_operation_cancelled"],
                         OperationState.CANCELLED)
        self.provider.release.set()
        body, headers = self.request("cancelled")
        response = await self.client.post(protocol.MESSAGES_PATH, content=body, headers=headers)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "OPERATION_ALREADY_DISPATCHED")
        self.assertEqual(len(self.provider.calls), 1)

    async def test_unauthenticated_and_nonce_or_operation_replay_preserve_original_protocol(self):
        body, headers = self.request("replay")
        invalid = dict(headers)
        invalid[protocol.HEADER_SIGNATURE] = "not-a-valid-signature"
        rejected = await self.client.post(protocol.MESSAGES_PATH, content=body, headers=invalid)
        self.assertEqual(rejected.status_code, 401)
        self.assertEqual(rejected.json()["error"]["code"], "AUTH_INVALID")
        self.assertFalse(self.store.nonces)
        self.assertFalse(self.provider.calls)
        response = await self.client.post(protocol.MESSAGES_PATH, content=body, headers=headers)
        self.assertEqual(response.status_code, 200)
        replay = await self.client.post(protocol.MESSAGES_PATH, content=body, headers=headers)
        self.assertEqual(replay.status_code, 409)
        self.assertEqual(replay.json()["error"]["code"], "AUTH_REPLAY")
        body, fresh = self.request("replay")
        replay = await self.client.post(protocol.MESSAGES_PATH, content=body, headers=fresh)
        self.assertEqual(replay.status_code, 409)
        self.assertEqual(replay.json()["error"]["code"], "OPERATION_ALREADY_DISPATCHED")
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(gateway._BODY_LIMITER.active_bytes, 0)
        self.assertFalse(self.store.leases)

    def raw_scope(self, path, headers, length):
        raw_headers = [(name.lower().encode(), value.encode()) for name, value in headers.items()
                       if name.lower() not in {"content-length", "host"}]
        raw_headers.append((b"host", b"gateway.test"))
        if length is not None:
            raw_headers.append((b"content-length", str(length).encode()))
        return {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
                "http_version": "1.1", "scheme": "https", "method": "POST",
                "path": path, "raw_path": path.encode(), "query_string": b"",
                "headers": raw_headers, "server": ("gateway.test", 443),
                "client": ("127.0.0.1", 5000), "root_path": ""}

    async def raw_request(self, scope, chunks, send=None):
        sent = []
        incoming = list(chunks)
        async def receive():
            if incoming:
                chunk = incoming.pop(0)
                return {"type": "http.request", "body": chunk,
                        "more_body": bool(incoming)}
            await asyncio.Event().wait()
        async def collect(message):
            sent.append(message)
            if send is not None:
                await send(message)
        await gateway.app(scope, receive, collect)
        return sent

    async def test_chunked_reserves_eight_mib_and_overrun_or_false_length_is_known_prewire(self):
        body, headers = self.request("chunked")
        self.provider.release.clear()
        task = asyncio.create_task(self.raw_request(
            self.raw_scope(protocol.MESSAGES_PATH, headers, None), [body[:10], body[10:]]))
        self.tasks.append(task)
        await self.entered()
        self.assertEqual(gateway._BODY_LIMITER.active_bytes, 8 * 1024 * 1024)
        self.provider.release.set()
        messages = await task
        self.assertEqual(messages[0]["status"], 200)
        self.assertEqual(gateway._BODY_LIMITER.active_bytes, 0)
        for suffix, length, chunks in (
            ("false_length", 1, [body]),
            ("chunk_overflow", None, [b"x" * (8 * 1024 * 1024), b"x"]),
        ):
            with self.subTest(suffix=suffix):
                messages = await self.raw_request(
                    self.raw_scope(protocol.MESSAGES_PATH, headers, length), chunks)
                self.assertEqual(messages[0]["status"], 429)
                self.assertEqual(json.loads(messages[-1]["body"])["error"]["code"],
                                 "CONCURRENCY_LIMIT")
                self.assertEqual(len(self.provider.calls), 1)
                self.assertEqual(len(self.store.nonces), 1)
                self.assertEqual(gateway._BODY_LIMITER.active_bytes, 0)

    async def test_stream_body_reservation_lasts_through_last_send_and_cleanup(self):
        body, headers = self.request("stream", path=protocol.STREAM_PATH)
        last_send = asyncio.Event()
        finish_send = asyncio.Event()
        async def send(message):
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                last_send.set()
                await finish_send.wait()
        task = asyncio.create_task(self.raw_request(
            self.raw_scope(protocol.STREAM_PATH, headers, len(body)), [body], send))
        self.tasks.append(task)
        await asyncio.wait_for(last_send.wait(), 2)
        self.assertEqual(gateway._BODY_LIMITER.active_bytes, len(body))
        self.assertFalse(task.done())
        finish_send.set()
        sent = await task
        self.assertEqual(sent[0]["status"], 200)
        events = [json.loads(message["body"]) for message in sent
                  if message["type"] == "http.response.body" and message.get("body")]
        self.assertEqual([event["type"] for event in events], ["content", "usage", "done"])
        self.assertEqual(gateway._BODY_LIMITER.active_bytes, 0)
        self.assertFalse(self.store.leases)

    async def test_receive_cancel_and_stream_send_failure_do_not_leak_reservations(self):
        body, headers = self.request("receive_cancel")
        waiting = asyncio.Event()
        async def receive():
            waiting.set()
            await asyncio.Event().wait()
        async def send(_message):
            pass
        task = asyncio.create_task(gateway.app(
            self.raw_scope(protocol.MESSAGES_PATH, headers, len(body)), receive, send))
        self.tasks.append(task)
        await waiting.wait()
        self.assertEqual(gateway._BODY_LIMITER.active_bytes, len(body))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(gateway._BODY_LIMITER.active_bytes, 0)
        self.assertFalse(self.store.nonces)
        body, headers = self.request("send_failure", path=protocol.STREAM_PATH)
        async def fail_send(message):
            if message["type"] == "http.response.body":
                raise OSError("controlled downstream disconnected")
        with self.assertRaises(Exception):
            await self.raw_request(self.raw_scope(protocol.STREAM_PATH, headers, len(body)),
                                   [body], fail_send)
        self.assertEqual(gateway._BODY_LIMITER.active_bytes, 0)
        self.assertEqual(gateway._BODY_LIMITER.active_requests, 0)
        self.assertFalse(self.store.leases)

    async def test_health_and_signed_readiness_do_not_compete_for_body_budget(self):
        self.assertTrue(gateway._BODY_LIMITER.try_acquire(32 * 1024 * 1024, 32 * 1024 * 1024))
        try:
            live = await self.client.get("/health/live")
            self.assertEqual(live.status_code, 200)
            with mock.patch.dict(os.environ, {
                "NOTEAI_CLAUDE_GATEWAY_DDB_TABLE": "offline-table",
                "NOTEAI_CLAUDE_GATEWAY_DDB_REGION": "ap-southeast-1",
            }):
                ready = await self.client.get("/health/ready")
                self.assertEqual(ready.status_code, 200)
                headers = protocol.auth_headers(
                    key_id="offline-key", secret="offline-fixture-not-a-real-secret",
                    method="GET", path=protocol.READINESS_PATH, authority="gateway.test",
                    config_epoch="offline-config", key_epoch="offline-epoch", body=b"",
                )
                headers[protocol.HEADER_READINESS_CHALLENGE] = "offline-challenge-12345678"
                signed = await self.client.get(protocol.READINESS_PATH, headers=headers)
                self.assertEqual(signed.status_code, 200, signed.text)
            self.assertEqual(gateway._BODY_LIMITER.active_bytes, 32 * 1024 * 1024)
            self.assertFalse(self.provider.calls)
            self.assertFalse(self.store.nonces)
        finally:
            gateway._BODY_LIMITER.release(32 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
