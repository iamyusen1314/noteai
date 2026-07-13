import asyncio
import concurrent.futures
import io
import json
import os
import secrets
import socket
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import httpx
from fastapi.testclient import TestClient
from starlette.datastructures import Headers
from starlette.requests import ClientDisconnect


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
GATEWAY_DIR = ROOT / "gateway"
for directory in (MODEL_DIR, GATEWAY_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import claude_gateway_protocol as protocol
import model_router
import api
from gateway import claude_gateway
from gateway import rehearsal
from control_store import (
    ControlStoreUnavailable,
    Lease,
    OperationClaim,
    OperationState,
)
from dynamodb_control_store import DynamoDBControlStore


def _complete_usage(**updates):
    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    usage.update(updates)
    return usage


class _FakeProvider:
    def __init__(self):
        self.calls = []
        self.error = None

    async def create(self, payload):
        self.calls.append(("create", payload))
        if self.error:
            raise self.error
        return ["safe-result"], _complete_usage(input_tokens=3, output_tokens=2)

    async def stream(self, payload):
        self.calls.append(("stream", payload))
        if self.error:
            raise self.error
        yield {"type": "thinking", "text": "private-reasoning"}
        yield {"type": "content", "text": "safe-"}
        yield {"type": "content", "text": "stream"}
        yield {"type": "usage", "usage": _complete_usage(input_tokens=4, output_tokens=2)}


class _FakeSharedControlStore:
    def __init__(self):
        self.nonces = {}
        self.rates = {}
        self.operations = {}
        self.lease = None
        self.fence = 0
        self.calls = []
        self.available = True
        self.fail_begin_after_apply = False
        self.renew_count = 0
        self.lose_lease_on_renew = False
        self.credential_method = "assume-role-with-web-identity"

    def _require_available(self):
        if not self.available:
            raise ControlStoreUnavailable("unavailable")

    async def claim_nonce(self, principal, nonce, now, expires):
        self._require_available()
        self.calls.append(("nonce", principal, now, expires))
        key = (principal, nonce)
        if self.nonces.get(key, 0) > now:
            return False
        self.nonces[key] = expires
        return True

    async def admit_rate(self, principal, now, limit, window):
        self._require_available()
        self.calls.append(("rate", principal, now))
        candidate = int(float(now) // window) * window
        stored_window, count = self.rates.get(principal, (candidate, 0))
        if candidate > stored_window:
            stored_window, count = candidate, 0
        if count >= limit:
            return False
        self.rates[principal] = (stored_window, count + 1)
        return True

    async def acquire_lease(self, operation, _slots, now, seconds):
        self._require_available()
        if self.lease is not None and self.lease.expires_at > now:
            return None
        self.fence += 1
        self.lease = Lease(0, operation, f"owner-{self.fence}", self.fence, now + seconds)
        self.calls.append(("lease", operation, self.fence))
        return self.lease

    async def claim_operation(self, principal, operation):
        self._require_available()
        state = self.operations.get(operation)
        if state is not None:
            return OperationClaim(state, False)
        self.operations[operation] = OperationState.CLAIMED
        self.calls.append(("claim", principal, operation))
        return OperationClaim(OperationState.CLAIMED, True)

    async def begin_provider(self, operation, lease, _dispatch, _model, _now):
        self._require_available()
        if (
            self.operations.get(operation) != OperationState.CLAIMED
            or lease != self.lease
            or lease.expires_at <= _now
        ):
            return False
        self.operations[operation] = OperationState.PROVIDER_STARTED
        self.calls.append(("begin", operation))
        if self.fail_begin_after_apply:
            raise ControlStoreUnavailable("response lost after apply")
        return True

    async def renew_lease(self, lease, now, seconds):
        self._require_available()
        self.renew_count += 1
        self.calls.append(("renew", lease.operation_hash))
        if lease != self.lease or lease.expires_at <= now:
            return None
        if self.lose_lease_on_renew:
            return None
        self.lease = Lease(
            lease.slot, lease.operation_hash, lease.owner_token,
            lease.fence, now + seconds,
        )
        return self.lease

    async def finish_operation(
        self, operation, lease, state, _now, *, retention_seconds, **kwargs,
    ):
        self._require_available()
        if lease != self.lease or self.operations.get(operation) != OperationState.PROVIDER_STARTED:
            return False
        self.operations[operation] = state
        self.lease = None
        self.calls.append(("finish", operation, state, kwargs.get("usage")))
        return True

    async def release_lease(self, lease):
        if lease == self.lease:
            self.lease = None
            return True
        return False

    async def health(self):
        self._require_available()
        return True


class ClaudeGatewayEndpointTests(unittest.TestCase):
    authority = "gateway.test"
    config_epoch = "test-config-1"
    key_epoch = "test-key-1"

    def setUp(self):
        self.env = mock.patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": "provider-test-key",
            "NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID": "main-test-key",
            "NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET": "test-secret-material",
            "NOTEAI_CLAUDE_GATEWAY_AUTHORITY": self.authority,
            "NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH": self.config_epoch,
            "NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH": self.key_epoch,
            "NOTEAI_CLAUDE_GATEWAY_INSTANCE_COUNT": "1",
            "NOTEAI_CLAUDE_GATEWAY_MAX_BODY_BYTES": "8388608",
            "NOTEAI_CLAUDE_GATEWAY_MAX_TOKENS": "16000",
            "NOTEAI_CLAUDE_GATEWAY_CONTROL_MODE": "memory",
        }, clear=False)
        self.env.start()
        self.original_provider = claude_gateway._PROVIDER
        self.original_nonces = claude_gateway._NONCES
        self.original_limiter = claude_gateway._LIMITER
        self.original_rate_limiter = claude_gateway._RATE_LIMITER
        self.original_control_store = claude_gateway._CONTROL_STORE
        self.provider = _FakeProvider()
        claude_gateway._PROVIDER = self.provider
        claude_gateway._NONCES = claude_gateway.InMemoryNonceStore()
        claude_gateway._LIMITER = claude_gateway.ConcurrencyLimiter(2)
        claude_gateway._RATE_LIMITER = claude_gateway.InMemoryRateLimiter(1000)
        claude_gateway._CONTROL_STORE = None
        self.client = TestClient(claude_gateway.app)

    def tearDown(self):
        self.client.close()
        claude_gateway._PROVIDER = self.original_provider
        claude_gateway._NONCES = self.original_nonces
        claude_gateway._LIMITER = self.original_limiter
        claude_gateway._RATE_LIMITER = self.original_rate_limiter
        claude_gateway._CONTROL_STORE = self.original_control_store
        self.env.stop()

    @staticmethod
    def payload(**updates):
        payload = {
            "operation_id": "test_operation_id_1234567890",
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 1200,
            "system": "system",
            "messages": [{"role": "user", "content": "hello"}],
            "temperature": 0.7,
            "thinking_budget": None,
        }
        payload.update(updates)
        return payload

    @staticmethod
    def encoded(payload):
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()

    def headers(self, path, body, **updates):
        headers = protocol.auth_headers(
            key_id="main-test-key",
            secret="test-secret-material",
            method="POST",
            path=path,
            authority=self.authority,
            config_epoch=self.config_epoch,
            key_epoch=self.key_epoch,
            body=body,
            nonce=updates.pop("nonce", None),
            timestamp=updates.pop("timestamp", None),
        )
        headers.update(updates)
        return headers

    def post(self, path=protocol.MESSAGES_PATH, payload=None, headers=None):
        body = self.encoded(payload or self.payload())
        return self.client.post(
            path,
            content=body,
            headers=headers or self.headers(path, body),
        )

    def test_signed_non_stream_and_stream_contracts(self):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "protocol_version": protocol.PROTOCOL_VERSION,
            "text_blocks": ["safe-result"],
            "usage": _complete_usage(input_tokens=3, output_tokens=2),
        })

        body = self.encoded(self.payload())
        stream = self.client.post(
            protocol.STREAM_PATH,
            content=body,
            headers=self.headers(protocol.STREAM_PATH, body),
        )
        self.assertEqual(stream.status_code, 200)
        events = [json.loads(line) for line in stream.text.splitlines()]
        self.assertEqual([event["type"] for event in events], ["content", "content", "usage", "done"])
        self.assertFalse(any("thinking" in json.dumps(event) for event in events))

    def test_stream_provider_failure_before_first_public_event_is_json_error(self):
        self.provider.error = RuntimeError("secret prompt https://provider.invalid/private")
        response = self.post(path=protocol.STREAM_PATH)

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.headers["content-type"].split(";", 1)[0], "application/json")
        self.assertEqual(response.json(), {
            "protocol_version": protocol.PROTOCOL_VERSION,
            "error": {"code": "PROVIDER_ERROR", "message": "request rejected"},
        })
        self.assertNotIn("secret", response.text)
        self.assertNotIn("provider.invalid", response.text)
        self.assertEqual(claude_gateway._LIMITER.active, 0)

    def test_stream_provider_failure_after_content_has_fixed_ndjson_terminal(self):
        class PartialProvider:
            async def stream(self, _payload):
                yield {"type": "content", "text": "safe-part"}
                raise RuntimeError("secret prompt https://provider.invalid/private")

        claude_gateway._PROVIDER = PartialProvider()
        response = self.post(path=protocol.STREAM_PATH)

        self.assertEqual(response.status_code, 200)
        events = [json.loads(line) for line in response.text.splitlines()]
        self.assertEqual([event["type"] for event in events], ["content", "error"])
        self.assertEqual(events[0]["text"], "safe-part")
        self.assertEqual(events[1]["error"], {
            "code": "PROVIDER_ERROR",
            "message": "provider request failed",
        })
        self.assertNotIn("secret", response.text)
        self.assertNotIn("provider.invalid", response.text)
        self.assertEqual(claude_gateway._LIMITER.active, 0)

    def test_preflight_stream_cleanup_is_owned_when_body_never_or_partly_runs(self):
        class LifecycleProvider:
            def __init__(self, fail_after_first=False):
                self.fail_after_first = fail_after_first
                self.close_calls = 0

            async def stream(self, _payload):
                try:
                    yield {"type": "content", "text": "safe-part"}
                    if self.fail_after_first:
                        raise RuntimeError("private provider failure")
                    yield {"type": "usage", "usage": _complete_usage(output_tokens=1)}
                finally:
                    self.close_calls += 1

        async def build_response(provider):
            claude_gateway._PROVIDER = provider
            claude_gateway._LIMITER = claude_gateway.ConcurrencyLimiter(1)
            with mock.patch.object(
                claude_gateway,
                "_read_and_validate",
                new=mock.AsyncMock(return_value=self.payload()),
            ):
                return await claude_gateway.stream_message(object())

        async def exercise(mode, *, fail_after_first=False):
            provider = LifecycleProvider(fail_after_first=fail_after_first)
            response = await build_response(provider)
            self.assertEqual(claude_gateway._LIMITER.active, 1)
            if mode == "never_started":
                await response.body_iterator.aclose()
                await response.body_iterator.aclose()
            elif mode == "partly_started":
                await response.body_iterator.__anext__()
                await response.body_iterator.aclose()
                await response.body_iterator.aclose()
            else:
                chunks = [chunk async for chunk in response.body_iterator]
                self.assertTrue(chunks)
                await response.body_iterator.aclose()
            return provider

        for mode, fail_after_first in (
            ("never_started", False),
            ("partly_started", False),
            ("completed", False),
            ("completed", True),
        ):
            with self.subTest(mode=mode, fail_after_first=fail_after_first):
                provider = asyncio.run(exercise(mode, fail_after_first=fail_after_first))
                self.assertEqual(provider.close_calls, 1)
                self.assertEqual(claude_gateway._LIMITER.active, 0)

    def test_endless_thinking_preflight_times_out_and_cleans_up(self):
        class ThinkingProvider:
            def __init__(self):
                self.close_calls = 0

            async def stream(self, _payload):
                try:
                    while True:
                        yield {"type": "thinking", "text": "private-reasoning"}
                finally:
                    self.close_calls += 1

        async def exercise():
            provider = ThinkingProvider()
            claude_gateway._PROVIDER = provider
            claude_gateway._LIMITER = claude_gateway.ConcurrencyLimiter(1)
            with mock.patch.object(
                claude_gateway,
                "_read_and_validate",
                new=mock.AsyncMock(return_value=self.payload()),
            ), mock.patch.object(
                claude_gateway,
                "_preflight_timeout_seconds",
                return_value=0.02,
            ):
                response = await claude_gateway.stream_message(object())
            return provider, response

        provider, response = asyncio.run(exercise())
        self.assertEqual(response.status_code, 504)
        self.assertEqual(json.loads(response.body), {
            "protocol_version": protocol.PROTOCOL_VERSION,
            "error": {"code": "PROVIDER_TIMEOUT", "message": "request rejected"},
        })
        self.assertNotIn("thinking", response.body.decode())
        self.assertNotIn("private-reasoning", response.body.decode())
        self.assertEqual(provider.close_calls, 1)
        self.assertEqual(claude_gateway._LIMITER.active, 0)

    def test_response_level_cleanup_on_header_and_mid_body_send_failure(self):
        class LifecycleProvider:
            def __init__(self):
                self.close_calls = 0

            async def stream(self, _payload):
                try:
                    yield {"type": "content", "text": "safe-part"}
                    yield {"type": "usage", "usage": _complete_usage(output_tokens=1)}
                finally:
                    self.close_calls += 1

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "method": "POST",
            "path": protocol.STREAM_PATH,
            "headers": [],
        }

        async def receive():
            return {"type": "http.disconnect"}

        async def exercise(fail_on, *, cancelled=False):
            provider = LifecycleProvider()
            claude_gateway._PROVIDER = provider
            claude_gateway._LIMITER = claude_gateway.ConcurrencyLimiter(1)
            with mock.patch.object(
                claude_gateway,
                "_read_and_validate",
                new=mock.AsyncMock(return_value=self.payload()),
            ):
                response = await claude_gateway.stream_message(object())

            sends = []

            async def send(message):
                sends.append(message["type"])
                should_fail = (
                    fail_on == "header"
                    and message["type"] == "http.response.start"
                ) or (
                    fail_on == "body"
                    and message["type"] == "http.response.body"
                    and message.get("more_body") is True
                )
                if should_fail:
                    if cancelled:
                        raise asyncio.CancelledError()
                    raise OSError("synthetic disconnect")

            expected = asyncio.CancelledError if cancelled else ClientDisconnect
            with self.assertRaises(expected):
                await response(scope, receive, send)
            active_before_manual_close = claude_gateway._LIMITER.active
            close_calls_before_manual_close = provider.close_calls
            await response.body_iterator.aclose()
            return (
                provider,
                sends,
                active_before_manual_close,
                close_calls_before_manual_close,
            )

        for fail_on, cancelled in (
            ("header", False),
            ("body", False),
            ("header", True),
        ):
            with self.subTest(fail_on=fail_on, cancelled=cancelled):
                provider, sends, active, close_calls = asyncio.run(
                    exercise(fail_on, cancelled=cancelled)
                )
                self.assertEqual(close_calls, 1)
                self.assertEqual(provider.close_calls, 1)
                self.assertEqual(active, 0)
                self.assertEqual(sends[0], "http.response.start")
                if fail_on == "body":
                    self.assertIn("http.response.body", sends)

    def test_signature_binds_every_security_context_field(self):
        base = {
            "secret": "test-secret-material",
            "method": "POST",
            "path": protocol.MESSAGES_PATH,
            "authority": self.authority,
            "config_epoch": self.config_epoch,
            "key_epoch": self.key_epoch,
            "key_id": "main-test-key",
            "protocol_version": protocol.PROTOCOL_VERSION,
            "content_type": "application/json",
            "timestamp": "1700000000",
            "nonce": "fixed-nonce-value-1234",
            "body": b"{}",
        }
        baseline = protocol.signature(**base)
        variants = (
            ("method", "PUT"),
            ("path", protocol.STREAM_PATH),
            ("authority", "other.test"),
            ("config_epoch", "test-config-2"),
            ("key_epoch", "test-key-2"),
            ("key_id", "other-key"),
            ("protocol_version", "claude-gateway.v0"),
            ("content_type", "text/plain"),
            ("timestamp", "1700000001"),
            ("nonce", "other-nonce-value-1234"),
            ("body", b'{"changed":true}'),
        )
        for field, value in variants:
            changed = dict(base)
            changed[field] = value
            self.assertNotEqual(protocol.signature(**changed), baseline, field)

    def test_nonce_replay_is_rejected(self):
        body = self.encoded(self.payload())
        headers = self.headers(protocol.MESSAGES_PATH, body, nonce="fixed-nonce-value-1234")
        first = self.client.post(protocol.MESSAGES_PATH, content=body, headers=headers)
        second = self.client.post(protocol.MESSAGES_PATH, content=body, headers=headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["error"]["code"], "AUTH_REPLAY")

    def test_future_timestamp_nonce_cannot_be_replayed_after_old_ttl_would_expire(self):
        body = self.encoded(self.payload())
        base_time = 1_700_000_000
        future_timestamp = base_time + 200
        headers = self.headers(
            protocol.MESSAGES_PATH,
            body,
            nonce="future-nonce-value-1234",
            timestamp=future_timestamp,
        )
        with mock.patch.object(claude_gateway.time, "time", return_value=base_time):
            first = self.client.post(protocol.MESSAGES_PATH, content=body, headers=headers)
        with mock.patch.object(claude_gateway.time, "time", return_value=base_time + 350):
            replay = self.client.post(protocol.MESSAGES_PATH, content=body, headers=headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 409)
        self.assertEqual(replay.json()["error"]["code"], "AUTH_REPLAY")

    def test_concurrent_same_nonce_has_exactly_one_success(self):
        body = self.encoded(self.payload())
        headers = self.headers(
            protocol.MESSAGES_PATH,
            body,
            nonce="concurrent-nonce-value-1234",
        )

        def send():
            return self.client.post(protocol.MESSAGES_PATH, content=body, headers=headers).status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            statuses = sorted(pool.map(lambda _index: send(), range(2)))
        self.assertEqual(statuses, [200, 409])
        self.assertEqual(len(self.provider.calls), 1)

    def test_previous_hmac_key_rotation_and_unknown_key_fail_closed(self):
        rotation_env = {
            "NOTEAI_CLAUDE_GATEWAY_PREVIOUS_HMAC_KEY_ID": "previous-key",
            "NOTEAI_CLAUDE_GATEWAY_PREVIOUS_HMAC_SECRET": "previous-secret",
        }
        body = self.encoded(self.payload())
        previous_headers = protocol.auth_headers(
            key_id="previous-key",
            secret="previous-secret",
            method="POST",
            path=protocol.MESSAGES_PATH,
            authority=self.authority,
            config_epoch=self.config_epoch,
            key_epoch=self.key_epoch,
            body=body,
        )
        unknown_headers = protocol.auth_headers(
            key_id="unknown-key",
            secret="unknown-secret",
            method="POST",
            path=protocol.MESSAGES_PATH,
            authority=self.authority,
            config_epoch=self.config_epoch,
            key_epoch=self.key_epoch,
            body=body,
        )
        with mock.patch.dict(os.environ, rotation_env):
            previous = self.client.post(protocol.MESSAGES_PATH, content=body, headers=previous_headers)
            unknown = self.client.post(protocol.MESSAGES_PATH, content=body, headers=unknown_headers)
        self.assertEqual(previous.status_code, 200)
        self.assertEqual(unknown.status_code, 401)
        self.assertEqual(unknown.json()["error"]["code"], "AUTH_INVALID")

        with mock.patch.dict(os.environ, {
            "NOTEAI_CLAUDE_GATEWAY_PREVIOUS_HMAC_KEY_ID": "partial-key",
            "NOTEAI_CLAUDE_GATEWAY_PREVIOUS_HMAC_SECRET": "",
        }):
            self.assertEqual(self.client.get("/health/ready").status_code, 503)

    def test_signature_context_query_duplicates_and_staleness_fail_closed(self):
        body = self.encoded(self.payload())
        expired = self.headers(
            protocol.MESSAGES_PATH,
            body,
            timestamp=int(time.time()) - 1000,
        )
        self.assertEqual(
            self.client.post(protocol.MESSAGES_PATH, content=body, headers=expired).json()["error"]["code"],
            "AUTH_EXPIRED",
        )

        wrong_version = self.headers(protocol.MESSAGES_PATH, body)
        wrong_version[protocol.HEADER_PROTOCOL_VERSION] = "claude-gateway.v0"
        self.assertEqual(
            self.client.post(protocol.MESSAGES_PATH, content=body, headers=wrong_version).json()["error"]["code"],
            "PROTOCOL_VERSION_UNSUPPORTED",
        )

        wrong_key = self.headers(protocol.MESSAGES_PATH, body)
        wrong_key[protocol.HEADER_KEY_ID] = "other-key"
        self.assertEqual(
            self.client.post(protocol.MESSAGES_PATH, content=body, headers=wrong_key).json()["error"]["code"],
            "AUTH_INVALID",
        )

        query_response = self.client.post(
            protocol.MESSAGES_PATH + "?debug=1",
            content=body,
            headers=self.headers(protocol.MESSAGES_PATH, body),
        )
        self.assertEqual(query_response.json()["error"]["code"], "QUERY_NOT_ALLOWED")

        duplicate_headers = list(self.headers(protocol.MESSAGES_PATH, body).items())
        duplicate_headers.append((protocol.HEADER_SIGNATURE, "0" * 64))
        duplicate = self.client.post(
            protocol.MESSAGES_PATH,
            content=body,
            headers=duplicate_headers,
        )
        self.assertEqual(duplicate.json()["error"]["code"], "AUTH_HEADER_INVALID")

        unsupported_type = self.headers(protocol.MESSAGES_PATH, body)
        unsupported_type["Content-Type"] = "application/json; charset=utf-8"
        unsupported = self.client.post(
            protocol.MESSAGES_PATH,
            content=body,
            headers=unsupported_type,
        )
        self.assertEqual(unsupported.json()["error"]["code"], "CONTENT_TYPE_UNSUPPORTED")

        for forbidden_name, forbidden_value in (
            ("Authorization", "Bearer user-token"),
            ("Cookie", "session=user"),
            ("Content-Encoding", "gzip"),
        ):
            forbidden_headers = self.headers(protocol.MESSAGES_PATH, body)
            forbidden_headers[forbidden_name] = forbidden_value
            forbidden = self.client.post(
                protocol.MESSAGES_PATH,
                content=body,
                headers=forbidden_headers,
            )
            self.assertEqual(forbidden.json()["error"]["code"], "FORBIDDEN_HEADER")

    def test_model_body_token_thinking_temperature_and_image_limits(self):
        cases = (
            (self.payload(operation_id="short"), "INVALID_REQUEST"),
            (self.payload(model="claude-unknown"), "MODEL_NOT_ALLOWED"),
            (self.payload(max_tokens=16001), "TOKEN_LIMIT_EXCEEDED"),
            (self.payload(thinking_budget=1024, temperature=0.7), "INVALID_REQUEST"),
            (self.payload(thinking_budget=1200, temperature=None), "TOKEN_LIMIT_EXCEEDED"),
            (self.payload(temperature=2), "INVALID_REQUEST"),
            (self.payload(messages=[]), "INVALID_REQUEST"),
            (self.payload(messages=[{"role": "system", "content": "bad"}]), "INVALID_REQUEST"),
            (self.payload(messages=[{"role": "user", "content": "ok", "extra": "bad"}]), "INVALID_REQUEST"),
            (self.payload(system="x" * 500_001), "CONTENT_LIMIT_EXCEEDED"),
            (self.payload(messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AA=="}}
            ]}]), "IMAGES_DISABLED"),
            (self.payload(messages=[{"role": "user", "content": [
                {"type": "text", "text": "ok", "extra": "bad"}
            ]}]), "IMAGES_DISABLED"),
        )
        for payload, code in cases:
            with self.subTest(code=code):
                self.assertEqual(self.post(payload=payload).json()["error"]["code"], code)

        remote = self.payload(messages=[{"role": "user", "content": [{
            "type": "image",
            "source": {"type": "url", "url": "https://example.invalid/image.png"},
        }]}])
        self.assertEqual(self.post(payload=remote).json()["error"]["code"], "REMOTE_IMAGE_NOT_ALLOWED")

        with mock.patch.dict(os.environ, {"NOTEAI_CLAUDE_GATEWAY_MAX_BODY_BYTES": "1024"}):
            oversized = self.payload(system="x" * 2000)
            self.assertEqual(self.post(payload=oversized).json()["error"]["code"], "PAYLOAD_TOO_LARGE")

    def test_streaming_body_reader_rejects_negative_duplicate_and_chunked_overflow(self):
        class FakeRequest:
            method = "POST"
            url = SimpleNamespace(query="", path=protocol.MESSAGES_PATH)

            def __init__(self, raw_headers, chunks):
                self.headers = Headers(raw=raw_headers)
                self._chunks = chunks

            async def stream(self):
                for chunk in self._chunks:
                    yield chunk

        cases = (
            ([(b"content-length", b"-1")], [b"{}"], "CONTENT_LENGTH_INVALID"),
            ([(b"content-length", b"2"), (b"content-length", b"2")], [b"{}"], "CONTENT_LENGTH_INVALID"),
        )
        for raw_headers, chunks, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(claude_gateway.GatewayRejection) as raised:
                    asyncio.run(claude_gateway._read_and_validate(
                        FakeRequest(raw_headers, chunks),
                        protocol.MESSAGES_PATH,
                    ))
                self.assertEqual(raised.exception.code, code)

        with mock.patch.dict(os.environ, {"NOTEAI_CLAUDE_GATEWAY_MAX_BODY_BYTES": "1024"}):
            with self.assertRaises(claude_gateway.GatewayRejection) as raised:
                asyncio.run(claude_gateway._read_and_validate(
                    FakeRequest([], [b"x" * 700, b"y" * 700]),
                    protocol.MESSAGES_PATH,
                ))
        self.assertEqual(raised.exception.code, "PAYLOAD_TOO_LARGE")

    def test_concurrency_provider_errors_and_instance_scope_are_fixed_and_safe(self):
        claude_gateway._LIMITER.active = claude_gateway._LIMITER.limit
        limited = self.post()
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.json()["error"]["code"], "CONCURRENCY_LIMIT")
        claude_gateway._LIMITER.active = 0

        self.provider.error = RuntimeError("secret prompt and provider response")
        provider_error = self.post()
        self.assertEqual(provider_error.status_code, 502)
        self.assertEqual(provider_error.json()["error"]["code"], "PROVIDER_ERROR")
        self.assertNotIn("secret prompt", provider_error.text)

        with mock.patch.dict(os.environ, {"NOTEAI_CLAUDE_GATEWAY_INSTANCE_COUNT": "2"}):
            ready = self.client.get("/health/ready")
            rejected = self.post()
        self.assertEqual(ready.status_code, 503)
        self.assertFalse(ready.json()["multi_instance_production_ready"])
        self.assertEqual(rejected.json()["error"]["code"], "REPLAY_STORE_INSTANCE_SCOPE")

    def test_per_key_rate_limit_is_bounded_and_rejects_without_queueing(self):
        claude_gateway._RATE_LIMITER = claude_gateway.InMemoryRateLimiter(1, 60)
        first = self.post()
        second = self.post()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json()["error"]["code"], "RATE_LIMIT")
        self.assertEqual(len(self.provider.calls), 1)

    def test_health_explicitly_reports_memory_instance_scope(self):
        ready = self.client.get("/health/ready")
        self.assertEqual(ready.status_code, 200)
        payload = ready.json()
        self.assertEqual(payload["status"], "ready_single_instance")
        self.assertEqual(payload["deployment_scope"], "single_instance_only")
        self.assertEqual(payload["replay_store"], "memory_instance_scope")
        self.assertFalse(payload["multi_instance_production_ready"])

    def _dynamodb_env(self):
        return {
            "NOTEAI_CLAUDE_GATEWAY_CONTROL_MODE": "dynamodb",
            "NOTEAI_CLAUDE_GATEWAY_PRINCIPAL_ID": "noteai-production",
            "NOTEAI_CLAUDE_GATEWAY_DDB_TABLE": "gateway-control",
            "NOTEAI_CLAUDE_GATEWAY_DDB_REGION": "ap-southeast-1",
            "NOTEAI_CLAUDE_GATEWAY_INSTANCE_COUNT": "3",
            "AWS_ROLE_ARN": "arn:aws:iam::123456789012:role/render-noteai-gateway",
            "AWS_WEB_IDENTITY_TOKEN_FILE": "/render/injected/token",
            "AWS_EC2_METADATA_DISABLED": "true",
            "AWS_ACCESS_KEY_ID": "",
            "AWS_SECRET_ACCESS_KEY": "",
            "AWS_SESSION_TOKEN": "",
        }

    def test_dynamodb_non_stream_starts_provider_once_after_durable_begin(self):
        store = _FakeSharedControlStore()
        claude_gateway._CONTROL_STORE = store

        class OrderedProvider(_FakeProvider):
            async def create(inner_self, payload):
                self.assertEqual(
                    store.operations[payload["operation_id"]],
                    OperationState.PROVIDER_STARTED,
                )
                return await super().create(payload)

        provider = OrderedProvider()
        claude_gateway._PROVIDER = provider
        with mock.patch.dict(os.environ, self._dynamodb_env()):
            first = self.post(payload=self.payload(operation_id="shared_operation_123456789"))
            duplicate = self.post(payload=self.payload(operation_id="shared_operation_123456789"))

        self.assertEqual(first.status_code, 200)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["error"]["code"], "OPERATION_ALREADY_DISPATCHED")
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(
            store.operations["shared_operation_123456789"],
            OperationState.TERMINAL_USAGE,
        )
        self.assertEqual(
            [call[0] for call in store.calls if call[0] in {"begin", "finish"}],
            ["begin", "finish"],
        )

    def test_operation_claim_crash_boundaries_are_at_most_once_and_fail_closed(self):
        class ClaimTrackingStore(_FakeSharedControlStore):
            def __init__(inner_self):
                super().__init__()
                inner_self.claim_results = []
                inner_self.begin_attempts = 0
                inner_self.release_count = 0

            async def claim_operation(inner_self, *args):
                result = await super().claim_operation(*args)
                inner_self.claim_results.append(result)
                return result

            async def begin_provider(inner_self, *args):
                inner_self.begin_attempts += 1
                return await super().begin_provider(*args)

            async def release_lease(inner_self, lease):
                inner_self.release_count += 1
                return await super().release_lease(lease)

        async def exercise():
            operation_before_claim = "lease_before_claim_crash_operation_12345"
            pre_claim_store = ClaimTrackingStore()
            abandoned = await pre_claim_store.acquire_lease(
                operation_before_claim, 1, 100, 10,
            )
            self.assertIsNotNone(abandoned)
            self.assertNotIn(operation_before_claim, pre_claim_store.operations)
            pre_claim_provider = _FakeProvider()
            pre_claim_payload = self.payload(operation_id=operation_before_claim)
            pre_claim_payload["_principal_id"] = "noteai-production"
            claude_gateway._CONTROL_STORE = pre_claim_store
            claude_gateway._PROVIDER = pre_claim_provider
            with mock.patch.object(
                claude_gateway, "_read_and_validate",
                new=mock.AsyncMock(return_value=pre_claim_payload),
            ), mock.patch.object(claude_gateway, "_now_epoch", return_value=110):
                first_execution = await claude_gateway.create_message(object())

            operation_after_claim = "claim_before_begin_crash_operation_12345"
            post_claim_store = ClaimTrackingStore()
            abandoned = await post_claim_store.acquire_lease(
                operation_after_claim, 1, 100, 10,
            )
            self.assertIsNotNone(abandoned)
            original_claim = await post_claim_store.claim_operation(
                "noteai-production", operation_after_claim,
            )
            self.assertTrue(original_claim.created)
            post_claim_provider = _FakeProvider()
            post_claim_payload = self.payload(operation_id=operation_after_claim)
            post_claim_payload["_principal_id"] = "noteai-production"
            claude_gateway._CONTROL_STORE = post_claim_store
            claude_gateway._PROVIDER = post_claim_provider
            rejections = []
            with mock.patch.object(
                claude_gateway, "_read_and_validate",
                new=mock.AsyncMock(return_value=post_claim_payload),
            ), mock.patch.object(claude_gateway, "_now_epoch", return_value=110):
                for _ in range(2):
                    try:
                        await claude_gateway.create_message(object())
                    except claude_gateway.GatewayRejection as exc:
                        rejections.append(exc)
            return (
                first_execution, pre_claim_store, pre_claim_provider,
                post_claim_store, post_claim_provider, rejections,
            )

        with mock.patch.dict(os.environ, self._dynamodb_env()):
            (
                first_execution, pre_claim_store, pre_claim_provider,
                post_claim_store, post_claim_provider, rejections,
            ) = asyncio.run(exercise())

        self.assertEqual(first_execution["text_blocks"], ["safe-result"])
        self.assertEqual(len(pre_claim_provider.calls), 1)
        self.assertEqual(pre_claim_store.begin_attempts, 1)
        self.assertEqual(
            pre_claim_store.operations["lease_before_claim_crash_operation_12345"],
            OperationState.TERMINAL_USAGE,
        )
        self.assertEqual([item.created for item in post_claim_store.claim_results], [
            True, False, False,
        ])
        self.assertEqual(
            post_claim_store.operations["claim_before_begin_crash_operation_12345"],
            OperationState.CLAIMED,
        )
        self.assertEqual(post_claim_store.begin_attempts, 0)
        self.assertEqual(post_claim_store.release_count, 2)
        self.assertEqual(post_claim_provider.calls, [])
        self.assertEqual([item.code for item in rejections], [
            "OPERATION_ALREADY_DISPATCHED", "OPERATION_ALREADY_DISPATCHED",
        ])
        self.assertEqual([item.status_code for item in rejections], [409, 409])

    def test_gateway_rechecks_fresh_time_before_begin_at_exact_lease_expiry(self):
        async def exact_expiry():
            store = _FakeSharedControlStore()
            provider = _FakeProvider()
            payload = self.payload(operation_id="paused_exact_expiry_operation_123")
            payload["_principal_id"] = "noteai-production"
            claude_gateway._CONTROL_STORE = store
            claude_gateway._PROVIDER = provider
            rejection = None
            with mock.patch.dict(os.environ, self._dynamodb_env()), \
                 mock.patch.object(
                     claude_gateway, "_read_and_validate",
                     new=mock.AsyncMock(return_value=payload),
                 ), mock.patch.object(
                     claude_gateway, "_lease_seconds", return_value=10,
                 ), mock.patch.object(
                     claude_gateway, "_now_epoch", side_effect=[100, 110],
                 ):
                try:
                    await claude_gateway.create_message(object())
                except claude_gateway.GatewayRejection as exc:
                    rejection = exc
            replacement = await store.acquire_lease(
                "replacement-operation", 1, 110, 10,
            )
            return store, provider, rejection, replacement

        store, provider, rejection, replacement = asyncio.run(exact_expiry())
        self.assertIsNotNone(rejection)
        self.assertEqual(rejection.code, "OPERATION_ALREADY_DISPATCHED")
        self.assertEqual(provider.calls, [])
        self.assertEqual(
            store.operations["paused_exact_expiry_operation_123"],
            OperationState.CLAIMED,
        )
        self.assertIsNotNone(replacement)
        self.assertEqual(replacement.expires_at, 120)
        self.assertGreater(replacement.fence, 1)

        async def still_live():
            store = _FakeSharedControlStore()
            provider = _FakeProvider()
            payload = self.payload(operation_id="paused_still_live_operation_1234")
            payload["_principal_id"] = "noteai-production"
            claude_gateway._CONTROL_STORE = store
            claude_gateway._PROVIDER = provider
            with mock.patch.dict(os.environ, self._dynamodb_env()), \
                 mock.patch.object(
                     claude_gateway, "_read_and_validate",
                     new=mock.AsyncMock(return_value=payload),
                 ), mock.patch.object(
                     claude_gateway, "_lease_seconds", return_value=10,
                 ), mock.patch.object(
                     claude_gateway, "_now_epoch", side_effect=[100, 109, 109],
                 ):
                response = await claude_gateway.create_message(object())
            return store, provider, response

        live_store, live_provider, response = asyncio.run(still_live())
        self.assertEqual(response["text_blocks"], ["safe-result"])
        self.assertEqual(len(live_provider.calls), 1)
        self.assertEqual(
            live_store.operations["paused_still_live_operation_1234"],
            OperationState.TERMINAL_USAGE,
        )

    def test_dynamodb_store_faults_fail_closed_before_and_after_begin_apply(self):
        before = _FakeSharedControlStore()
        before.available = False
        claude_gateway._CONTROL_STORE = before
        with mock.patch.dict(os.environ, self._dynamodb_env()):
            rejected = self.post(payload=self.payload(operation_id="before_fault_operation_123"))
        self.assertEqual(rejected.status_code, 503)
        self.assertEqual(rejected.json()["error"]["code"], "CONTROL_PLANE_UNAVAILABLE")
        self.assertEqual(self.provider.calls, [])

        for phase in ("acquire", "claim"):
            class PhaseFailureStore(_FakeSharedControlStore):
                async def acquire_lease(inner_self, *args):
                    if phase == "acquire":
                        raise ControlStoreUnavailable("acquire failed")
                    return await super().acquire_lease(*args)

                async def claim_operation(inner_self, *args):
                    if phase == "claim":
                        raise ControlStoreUnavailable("claim failed")
                    return await super().claim_operation(*args)

            phase_store = PhaseFailureStore()
            claude_gateway._CONTROL_STORE = phase_store
            with self.subTest(phase=phase), mock.patch.dict(os.environ, self._dynamodb_env()):
                phase_rejected = self.post(payload=self.payload(
                    operation_id=f"{phase}_failure_operation_12345",
                ))
            self.assertEqual(phase_rejected.status_code, 503)
            self.assertEqual(
                phase_rejected.json()["error"]["code"],
                "CONTROL_PLANE_UNAVAILABLE",
            )
            self.assertEqual(self.provider.calls, [])

        after = _FakeSharedControlStore()
        after.fail_begin_after_apply = True
        claude_gateway._CONTROL_STORE = after
        with mock.patch.dict(os.environ, self._dynamodb_env()):
            uncertain = self.post(payload=self.payload(operation_id="after_fault_operation_1234"))
        self.assertEqual(uncertain.status_code, 503)
        uncertain_payload = uncertain.json()
        self.assertEqual(
            uncertain_payload["error"]["code"],
            "CONTROL_PLANE_OUTCOME_UNKNOWN",
        )
        self.assertNotIn("control_stage", uncertain_payload)
        self.assertNotIn("control_reason", uncertain_payload)
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(
            after.operations["after_fault_operation_1234"],
            OperationState.PROVIDER_STARTED,
        )
        self.assertEqual(
            len([call for call in after.calls if call[0] == "begin"]),
            1,
        )

    def test_dynamodb_rotation_uses_one_stable_principal_and_future_nonce_expiry(self):
        store = _FakeSharedControlStore()
        claude_gateway._CONTROL_STORE = store
        rotation = {
            **self._dynamodb_env(),
            "NOTEAI_CLAUDE_GATEWAY_REQUESTS_PER_MINUTE": "2",
            "NOTEAI_CLAUDE_GATEWAY_PREVIOUS_HMAC_KEY_ID": "old-test-key",
            "NOTEAI_CLAUDE_GATEWAY_PREVIOUS_HMAC_SECRET": "old-test-secret",
        }
        current_payload = self.payload(operation_id="current_key_operation_12345")
        current_body = self.encoded(current_payload)
        previous_payload = self.payload(operation_id="previous_key_operation_1234")
        previous_body = self.encoded(previous_payload)
        previous_headers = protocol.auth_headers(
            key_id="old-test-key", secret="old-test-secret", method="POST",
            path=protocol.MESSAGES_PATH,
            authority=self.authority,
            config_epoch=self.config_epoch,
            key_epoch=self.key_epoch,
            body=previous_body,
        )
        with mock.patch.dict(os.environ, rotation):
            current = self.client.post(
                protocol.MESSAGES_PATH, content=current_body,
                headers=self.headers(protocol.MESSAGES_PATH, current_body),
            )
            previous = self.client.post(
                protocol.MESSAGES_PATH, content=previous_body, headers=previous_headers,
            )
            limited_payload = self.payload(operation_id="rotation_limit_operation_1234")
            limited_body = self.encoded(limited_payload)
            limited = self.client.post(
                protocol.MESSAGES_PATH,
                content=limited_body,
                headers=self.headers(protocol.MESSAGES_PATH, limited_body),
            )
        self.assertEqual((current.status_code, previous.status_code), (200, 200))
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.json()["error"]["code"], "RATE_LIMIT")
        principals = {call[1] for call in store.calls if call[0] == "nonce"}
        self.assertEqual(principals, {"noteai-production"})

        future_store = _FakeSharedControlStore()
        claude_gateway._CONTROL_STORE = future_store
        payload = self.payload(operation_id="future_nonce_operation_1234")
        body = self.encoded(payload)
        with mock.patch.dict(os.environ, self._dynamodb_env()), \
             mock.patch.object(claude_gateway.time, "time", return_value=1000):
            headers = self.headers(
                protocol.MESSAGES_PATH, body, nonce="future-nonce-value-123456",
                timestamp=1299,
            )
            first = self.client.post(protocol.MESSAGES_PATH, content=body, headers=headers)
        with mock.patch.dict(os.environ, self._dynamodb_env()), \
             mock.patch.object(claude_gateway.time, "time", return_value=1301):
            replay = self.client.post(protocol.MESSAGES_PATH, content=body, headers=headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 409)
        self.assertEqual(replay.json()["error"]["code"], "AUTH_REPLAY")
        nonce_calls = [call for call in future_store.calls if call[0] == "nonce"]
        self.assertEqual(nonce_calls[0][3], 1599)

    def test_dynamodb_readiness_allows_multiple_instances_only_when_store_is_healthy(self):
        store = _FakeSharedControlStore()
        claude_gateway._CONTROL_STORE = store
        with mock.patch.dict(os.environ, self._dynamodb_env()):
            ready = self.client.get("/health/ready")
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.json()["status"], "ready_multi_instance")
        self.assertTrue(ready.json()["multi_instance_production_ready"])
        self.assertEqual(ready.json()["replay_store"], "dynamodb_shared_atomic")

        store.available = False
        with mock.patch.dict(os.environ, self._dynamodb_env()):
            unavailable = self.client.get("/health/ready")
        self.assertEqual(unavailable.status_code, 503)
        self.assertFalse(unavailable.json()["multi_instance_production_ready"])

    def test_dynamodb_rejects_static_or_non_web_identity_credentials(self):
        store = _FakeSharedControlStore()
        claude_gateway._CONTROL_STORE = store
        static_env = {**self._dynamodb_env(), "AWS_ACCESS_KEY_ID": "static-key"}
        with mock.patch.dict(os.environ, static_env):
            ready = self.client.get("/health/ready")
            rejected = self.post(payload=self.payload(
                operation_id="static_credential_operation_123",
            ))
        self.assertEqual(ready.status_code, 503)
        self.assertEqual(rejected.status_code, 503)
        self.assertEqual(rejected.json()["error"]["code"], "GATEWAY_NOT_CONFIGURED")
        self.assertEqual(self.provider.calls, [])

        store.credential_method = "env"
        with mock.patch.dict(os.environ, self._dynamodb_env()):
            wrong_method_ready = self.client.get("/health/ready")
            wrong_method = self.post(payload=self.payload(
                operation_id="wrong_method_operation_12345",
            ))
        self.assertEqual(wrong_method_ready.status_code, 503)
        self.assertEqual(wrong_method.status_code, 503)
        self.assertEqual(
            wrong_method.json()["error"]["code"], "CONTROL_PLANE_UNAVAILABLE",
        )
        self.assertEqual(self.provider.calls, [])

    def test_dynamodb_provider_deadline_covers_nonstream_and_stream(self):
        class SlowProvider:
            def __init__(self):
                self.calls = []

            async def create(inner_self, payload):
                inner_self.calls.append("create")
                await asyncio.sleep(1)
                return ["late"], _complete_usage(output_tokens=1)

            async def stream(inner_self, payload):
                inner_self.calls.append("stream")
                await asyncio.sleep(1)
                yield {"type": "content", "text": "late"}

        for path, expected_call in (
            (protocol.MESSAGES_PATH, "create"),
            (protocol.STREAM_PATH, "stream"),
        ):
            store = _FakeSharedControlStore()
            provider = SlowProvider()
            claude_gateway._CONTROL_STORE = store
            claude_gateway._PROVIDER = provider
            operation = f"deadline_{expected_call}_operation_1234"
            with self.subTest(path=path), \
                 mock.patch.dict(os.environ, self._dynamodb_env()), \
                 mock.patch.object(
                     claude_gateway, "_provider_deadline_seconds", return_value=0.01,
                 ):
                response = self.post(
                    path=path, payload=self.payload(operation_id=operation),
                )
            self.assertEqual(response.status_code, 504)
            self.assertEqual(response.json()["error"]["code"], "PROVIDER_TIMEOUT")
            self.assertEqual(provider.calls, [expected_call])
            self.assertEqual(store.operations[operation], OperationState.AMBIGUOUS)

    def test_default_lease_exceeds_provider_deadline_plus_margin(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            deadline = claude_gateway._provider_deadline_seconds()
            lease = claude_gateway._lease_seconds()
        self.assertGreater(lease, deadline)
        self.assertGreaterEqual(lease, int(deadline) + 30)

    def test_dynamodb_stream_records_terminal_partial_and_ambiguous_states(self):
        cases = (
            ("success", OperationState.TERMINAL_USAGE, ["content", "content", "usage", "done"]),
            ("partial", OperationState.PARTIAL, ["content", "error"]),
            ("preflight", OperationState.AMBIGUOUS, None),
        )

        for mode, expected_state, expected_events in cases:
            class StreamProvider:
                async def stream(inner_self, _payload):
                    if mode == "preflight":
                        raise RuntimeError("provider failed before content")
                    yield {"type": "content", "text": "public"}
                    if mode == "partial":
                        raise RuntimeError("provider failed after content")
                    yield {"type": "content", "text": "complete"}
                    yield {"type": "usage", "usage": _complete_usage(output_tokens=2)}

            store = _FakeSharedControlStore()
            claude_gateway._CONTROL_STORE = store
            claude_gateway._PROVIDER = StreamProvider()
            operation = f"stream_{mode}_operation_123456"
            with self.subTest(mode=mode), mock.patch.dict(os.environ, self._dynamodb_env()):
                response = self.post(
                    path=protocol.STREAM_PATH,
                    payload=self.payload(operation_id=operation),
                )
            self.assertEqual(store.operations[operation], expected_state)
            if expected_events is None:
                self.assertGreaterEqual(response.status_code, 500)
            else:
                events = [json.loads(line) for line in response.text.splitlines()]
                self.assertEqual([event["type"] for event in events], expected_events)

    def test_dynamodb_stream_renews_lease_and_fails_closed_if_fence_is_lost(self):
        class SlowProvider:
            async def stream(self, _payload):
                await asyncio.sleep(1.2)
                yield {"type": "content", "text": "late"}
                yield {"type": "usage", "usage": _complete_usage(output_tokens=1)}

        healthy = _FakeSharedControlStore()
        claude_gateway._CONTROL_STORE = healthy
        claude_gateway._PROVIDER = SlowProvider()
        healthy_operation = "renewed_stream_operation_12345"
        with mock.patch.dict(os.environ, self._dynamodb_env()), \
             mock.patch.object(claude_gateway, "_lease_seconds", return_value=3):
            completed = self.post(
                path=protocol.STREAM_PATH,
                payload=self.payload(operation_id=healthy_operation),
            )
        self.assertEqual(completed.status_code, 200)
        self.assertGreaterEqual(healthy.renew_count, 1)
        self.assertEqual(
            healthy.operations[healthy_operation], OperationState.TERMINAL_USAGE,
        )

        lost = _FakeSharedControlStore()
        lost.lose_lease_on_renew = True
        claude_gateway._CONTROL_STORE = lost
        lost_operation = "lost_fence_stream_operation_123"
        with mock.patch.dict(os.environ, self._dynamodb_env()), \
             mock.patch.object(claude_gateway, "_lease_seconds", return_value=3):
            rejected = self.post(
                path=protocol.STREAM_PATH,
                payload=self.payload(operation_id=lost_operation),
            )
        self.assertEqual(rejected.status_code, 503)
        self.assertEqual(
            rejected.json()["error"]["code"], "CONTROL_PLANE_OUTCOME_UNKNOWN",
        )
        self.assertEqual(lost.operations[lost_operation], OperationState.AMBIGUOUS)

    def test_dynamodb_stream_usage_then_client_close_stays_terminal_usage(self):
        class UsageFirstProvider:
            def __init__(self):
                self.calls = 0

            async def stream(inner_self, _payload):
                inner_self.calls += 1
                yield {"type": "usage", "usage": _complete_usage(output_tokens=3)}
                await asyncio.sleep(60)

        async def exercise():
            store = _FakeSharedControlStore()
            provider = UsageFirstProvider()
            operation = "usage_then_close_operation_123"
            payload = self.payload(operation_id=operation)
            payload["_principal_id"] = "noteai-production"
            claude_gateway._CONTROL_STORE = store
            claude_gateway._PROVIDER = provider
            with mock.patch.dict(os.environ, self._dynamodb_env()), \
                 mock.patch.object(
                     claude_gateway, "_read_and_validate",
                     new=mock.AsyncMock(return_value=payload),
                 ):
                response = await claude_gateway.stream_message(object())
                first = await response.body_iterator.__anext__()
                await response.body_iterator.aclose()
            return store, provider, operation, json.loads(first)

        store, provider, operation, first = asyncio.run(exercise())
        self.assertEqual(first["type"], "usage")
        self.assertEqual(provider.calls, 1)
        self.assertEqual(store.operations[operation], OperationState.TERMINAL_USAGE)
        finishes = [call for call in store.calls if call[0] == "finish"]
        self.assertEqual(len(finishes), 1)
        self.assertEqual(finishes[0][2], OperationState.TERMINAL_USAGE)


class AnthropicProviderBoundaryTests(unittest.TestCase):
    def test_raw_thinking_delta_is_dropped_before_gateway_events(self):
        usage = SimpleNamespace(
            input_tokens=5,
            output_tokens=2,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
            cache_creation=None,
        )

        class StreamContext:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            def __aiter__(self):
                async def events():
                    yield SimpleNamespace(
                        type="content_block_delta",
                        delta=SimpleNamespace(type="thinking_delta", thinking="private-reasoning"),
                    )
                    yield SimpleNamespace(
                        type="content_block_delta",
                        delta=SimpleNamespace(type="text_delta", text="public-content"),
                    )
                return events()

            def get_final_message(self):
                return SimpleNamespace(usage=usage)

        provider = claude_gateway.AnthropicProvider()
        provider._client = SimpleNamespace(
            messages=SimpleNamespace(stream=lambda **_kwargs: StreamContext())
        )

        async def collect():
            return [event async for event in provider.stream({
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1200,
                "messages": [{"role": "user", "content": "hello"}],
                "system": None,
                "temperature": 0.7,
                "thinking_budget": None,
            })]

        events = asyncio.run(collect())
        self.assertEqual([event["type"] for event in events], ["content", "usage"])
        self.assertEqual(events[0]["text"], "public-content")
        self.assertNotIn("private-reasoning", json.dumps(events))


class GatewayClaudeTransportTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {
            "NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH": "test-config-1",
            "NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH": "test-key-1",
        }, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()

    @staticmethod
    def request():
        return model_router.ClaudeMessageRequest(
            model=model_router.CLAUDE_HAIKU,
            max_tokens=1200,
            system="system",
            messages=({"role": "user", "content": "hello"},),
            temperature=0.7,
        )

    def test_sync_async_and_ndjson_stream_are_signed_and_normalized(self):
        requests = []

        def handler(request: httpx.Request):
            requests.append(request)
            body = request.content
            expected = protocol.signature(
                secret="transport-secret",
                method=request.method,
                path=request.url.path,
                authority=request.headers[protocol.HEADER_AUTHORITY],
                config_epoch=request.headers[protocol.HEADER_CONFIG_EPOCH],
                key_epoch=request.headers[protocol.HEADER_KEY_EPOCH],
                key_id=request.headers[protocol.HEADER_KEY_ID],
                protocol_version=request.headers[protocol.HEADER_PROTOCOL_VERSION],
                content_type=request.headers["content-type"],
                timestamp=request.headers[protocol.HEADER_TIMESTAMP],
                nonce=request.headers[protocol.HEADER_NONCE],
                body=body,
            )
            self.assertEqual(request.headers[protocol.HEADER_SIGNATURE], expected)
            if request.url.path == protocol.STREAM_PATH:
                events = (
                    {"protocol_version": protocol.PROTOCOL_VERSION, "type": "content", "text": "a"},
                    {"protocol_version": protocol.PROTOCOL_VERSION, "type": "usage", "usage": _complete_usage(output_tokens=1)},
                    {"protocol_version": protocol.PROTOCOL_VERSION, "type": "done"},
                )
                content = "".join(json.dumps(event) + "\n" for event in events).encode()
                return httpx.Response(200, content=content, headers={"content-type": "application/x-ndjson"})
            return httpx.Response(200, json={
                "protocol_version": protocol.PROTOCOL_VERSION,
                "text_blocks": ["ok"],
                "usage": _complete_usage(input_tokens=1),
            })

        transport = model_router.GatewayClaudeTransport(
            base_url="https://gateway.example.invalid",
            key_id="transport-key",
            secret="transport-secret",
            http_transport=httpx.MockTransport(handler),
        )
        sync_result = transport.create_message_sync(self.request())
        async_result = asyncio.run(transport.create_message(self.request()))

        async def collect():
            return [event async for event in transport.stream_message(self.request())]

        stream_events = asyncio.run(collect())
        self.assertEqual(sync_result.text_blocks, ("ok",))
        self.assertEqual(async_result.usage, _complete_usage(input_tokens=1))
        self.assertEqual([event.type for event in stream_events], ["content", "usage"])
        self.assertEqual(len(requests), 3)

    def test_transport_enforces_response_media_types_for_sync_async_and_stream(self):
        success_payload = {
            "protocol_version": protocol.PROTOCOL_VERSION,
            "text_blocks": ["ok"],
            "usage": _complete_usage(input_tokens=1),
        }

        def transport_for(handler):
            return model_router.GatewayClaudeTransport(
                base_url="https://gateway.example.com",
                key_id="transport-key",
                secret="transport-secret",
                http_transport=httpx.MockTransport(handler),
            )

        def charset_json(_request):
            return httpx.Response(
                200,
                content=json.dumps(success_payload).encode(),
                headers={"content-type": "Application/JSON; charset=utf-8"},
            )

        accepted = transport_for(charset_json)
        self.assertEqual(accepted.create_message_sync(self.request()).text_blocks, ("ok",))
        self.assertEqual(asyncio.run(accepted.create_message(self.request())).text_blocks, ("ok",))

        def wrong_json_type(_request):
            return httpx.Response(200, content=json.dumps(success_payload).encode(), headers={"content-type": "text/plain"})

        rejected = transport_for(wrong_json_type)
        with self.assertRaises(model_router.ClaudeGatewayError) as sync_error:
            rejected.create_message_sync(self.request())
        with self.assertRaises(model_router.ClaudeGatewayError) as async_error:
            asyncio.run(rejected.create_message(self.request()))
        self.assertEqual(sync_error.exception.code, "GATEWAY_PROTOCOL_ERROR")
        self.assertEqual(async_error.exception.code, "GATEWAY_PROTOCOL_ERROR")

        error_payload = {
            "protocol_version": protocol.PROTOCOL_VERSION,
            "error": {"code": "PROVIDER_UNAVAILABLE", "message": "request rejected"},
        }

        def wrong_error_type(_request):
            return httpx.Response(503, content=json.dumps(error_payload).encode(), headers={"content-type": "text/plain"})

        wrong_error = transport_for(wrong_error_type)
        with self.assertRaises(model_router.ClaudeGatewayError) as error_response:
            wrong_error.create_message_sync(self.request())
        self.assertEqual(error_response.exception.code, "GATEWAY_PROTOCOL_ERROR")

        valid_events = (
            {"protocol_version": protocol.PROTOCOL_VERSION, "type": "usage", "usage": _complete_usage(output_tokens=1)},
            {"protocol_version": protocol.PROTOCOL_VERSION, "type": "done"},
        )

        def wrong_stream_type(_request):
            content = "".join(json.dumps(event) + "\n" for event in valid_events).encode()
            return httpx.Response(200, content=content, headers={"content-type": "application/json"})

        async def collect(transport):
            return [event async for event in transport.stream_message(self.request())]

        with self.assertRaises(model_router.ClaudeGatewayError) as stream_success:
            asyncio.run(collect(transport_for(wrong_stream_type)))
        self.assertEqual(stream_success.exception.code, "GATEWAY_PROTOCOL_ERROR")

        def wrong_stream_error_type(_request):
            return httpx.Response(503, content=json.dumps(error_payload).encode(), headers={"content-type": "application/x-ndjson"})

        with self.assertRaises(model_router.ClaudeGatewayError) as stream_error:
            asyncio.run(collect(transport_for(wrong_stream_error_type)))
        self.assertEqual(stream_error.exception.code, "GATEWAY_PROTOCOL_ERROR")

    def test_transport_has_no_hidden_http_retry_and_gateway_mode_fails_closed(self):
        calls = {"count": 0}

        def handler(_request):
            calls["count"] += 1
            return httpx.Response(503, json={
                "protocol_version": protocol.PROTOCOL_VERSION,
                "error": {"code": "PROVIDER_UNAVAILABLE", "message": "request rejected"},
            })

        transport = model_router.GatewayClaudeTransport(
            base_url="https://gateway.example.invalid",
            key_id="transport-key",
            secret="transport-secret",
            http_transport=httpx.MockTransport(handler),
        )
        with self.assertRaises(model_router.ClaudeGatewayError) as raised:
            transport.create_message_sync(self.request())
        self.assertEqual(raised.exception.code, "PROVIDER_UNAVAILABLE")
        self.assertEqual(calls["count"], 1)

        original = model_router._CLAUDE_TRANSPORT
        try:
            model_router.set_claude_transport(None)
            with mock.patch.dict(os.environ, {"NOTEAI_CLAUDE_TRANSPORT": "gateway"}, clear=True):
                selected = model_router.get_claude_transport()
                self.assertIsInstance(selected, model_router.GatewayClaudeTransport)
                with self.assertRaises(model_router.ClaudeGatewayError) as missing:
                    selected.create_message_sync(self.request())
                self.assertEqual(missing.exception.code, "GATEWAY_NOT_CONFIGURED")
        finally:
            model_router.set_claude_transport(original)

    def test_httpx_failures_map_to_fixed_errors_without_url_or_exception_text(self):
        failures = (
            (lambda request: httpx.ConnectTimeout("secret timeout url", request=request), "GATEWAY_TIMEOUT"),
            (lambda request: httpx.ConnectError("secret network url", request=request), "GATEWAY_NETWORK_ERROR"),
            (lambda request: httpx.RemoteProtocolError("secret protocol url", request=request), "GATEWAY_PROTOCOL_ERROR"),
        )
        for failure_factory, code in failures:
            with self.subTest(code=code):
                def handler(request, factory=failure_factory):
                    raise factory(request)

                transport = model_router.GatewayClaudeTransport(
                    base_url="https://gateway.example.com",
                    key_id="transport-key",
                    secret="transport-secret",
                    http_transport=httpx.MockTransport(handler),
                )
                with self.assertRaises(model_router.ClaudeGatewayError) as raised:
                    transport.create_message_sync(self.request())
                self.assertEqual(raised.exception.code, code)
                self.assertNotIn("secret", str(raised.exception))
                self.assertNotIn("gateway.example.com", str(raised.exception))

    def test_broken_gateway_stream_records_usage_missing_exactly_once(self):
        class BrokenTransport:
            def __init__(self, emit_usage):
                self.emit_usage = emit_usage

            async def stream_message(self, _request):
                if self.emit_usage:
                    yield model_router.ClaudeStreamEvent(
                        "usage",
                        usage=_complete_usage(output_tokens=1),
                    )
                raise model_router.ClaudeGatewayError(
                    "GATEWAY_STREAM_INCOMPLETE",
                    502,
                    usage_audit_required=True,
                )

        async def collect():
            request = self.request()
            return [event async for event in model_router._claude_transport_stream(
                model_router.CLAUDE_HAIKU,
                request,
            )]

        original = model_router._CLAUDE_TRANSPORT
        try:
            for emit_usage in (False, True):
                with self.subTest(emit_usage=emit_usage), \
                     mock.patch.object(model_router, "_record_claude_usage") as record:
                    model_router.set_claude_transport(BrokenTransport(emit_usage))
                    with self.assertRaises(model_router.ClaudeGatewayError):
                        asyncio.run(collect())
                    self.assertEqual(record.call_count, 1)
                    expected_usage = _complete_usage(output_tokens=1) if emit_usage else None
                    self.assertEqual(record.call_args.args, (model_router.CLAUDE_HAIKU, expected_usage))
        finally:
            model_router.set_claude_transport(original)

    def test_pre_provider_gateway_rejection_is_the_only_fallback_safe_response(self):
        def transport_for(code, status):
            def handler(_request):
                return httpx.Response(status, json={
                    "protocol_version": protocol.PROTOCOL_VERSION,
                    "error": {"code": code, "message": "request rejected"},
                })

            return model_router.GatewayClaudeTransport(
                base_url="https://gateway.example.invalid",
                key_id="transport-key",
                secret="transport-secret",
                http_transport=httpx.MockTransport(handler),
            )

        async def collect(transport):
            return [event async for event in transport.stream_message(self.request())]

        with self.assertRaises(model_router.ClaudeGatewayError) as rejected:
            asyncio.run(collect(transport_for("CONCURRENCY_LIMIT", 429)))
        self.assertTrue(rejected.exception.fallback_safe)
        self.assertFalse(rejected.exception.usage_audit_required)

        with self.assertRaises(model_router.ClaudeGatewayError) as control_unavailable:
            asyncio.run(collect(transport_for("CONTROL_PLANE_UNAVAILABLE", 503)))
        self.assertTrue(control_unavailable.exception.fallback_safe)
        self.assertFalse(control_unavailable.exception.usage_audit_required)

        with self.assertRaises(model_router.ClaudeGatewayError) as attempted:
            asyncio.run(collect(transport_for("PROVIDER_UNAVAILABLE", 503)))
        self.assertFalse(attempted.exception.fallback_safe)
        self.assertTrue(attempted.exception.usage_audit_required)

        with self.assertRaises(model_router.ClaudeGatewayError) as replay:
            asyncio.run(collect(transport_for("AUTH_REPLAY", 409)))
        self.assertFalse(replay.exception.fallback_safe)
        self.assertTrue(replay.exception.usage_audit_required)

        for code in ("CONTROL_PLANE_OUTCOME_UNKNOWN", "OPERATION_ALREADY_DISPATCHED"):
            with self.subTest(code=code), self.assertRaises(
                model_router.ClaudeGatewayError
            ) as unsafe:
                asyncio.run(collect(transport_for(code, 503)))
            self.assertFalse(unsafe.exception.fallback_safe)
            self.assertTrue(unsafe.exception.usage_audit_required)

        def in_stream_error(_request):
            event = {
                "protocol_version": protocol.PROTOCOL_VERSION,
                "type": "error",
                "error": {"code": "CONCURRENCY_LIMIT", "message": "request rejected"},
            }
            return httpx.Response(
                200,
                content=(json.dumps(event) + "\n").encode(),
                headers={"content-type": "application/x-ndjson"},
            )

        accepted = model_router.GatewayClaudeTransport(
            base_url="https://gateway.example.invalid",
            key_id="transport-key",
            secret="transport-secret",
            http_transport=httpx.MockTransport(in_stream_error),
        )
        with self.assertRaises(model_router.ClaudeGatewayError) as after_headers:
            asyncio.run(collect(accepted))
        self.assertFalse(after_headers.exception.fallback_safe)
        self.assertTrue(after_headers.exception.usage_audit_required)

    def test_gateway_stream_cancellation_after_dispatch_requires_usage_audit(self):
        class CancelStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                raise asyncio.CancelledError()
                yield b""

        def handler(_request):
            return httpx.Response(
                200,
                stream=CancelStream(),
                headers={"content-type": "application/x-ndjson"},
            )

        transport = model_router.GatewayClaudeTransport(
            base_url="https://gateway.example.invalid",
            key_id="transport-key",
            secret="transport-secret",
            http_transport=httpx.MockTransport(handler),
        )

        async def collect():
            return [event async for event in transport.stream_message(self.request())]

        with self.assertRaises(model_router.ClaudeRequestCancelled) as raised:
            asyncio.run(collect())
        self.assertTrue(raised.exception.usage_audit_required)

    def test_invalid_usage_envelopes_fail_closed(self):
        self.assertFalse(protocol.valid_usage_envelope({"input_tokens": 1}))
        self.assertFalse(protocol.valid_usage_envelope({"input_tokens": -1}))
        self.assertFalse(protocol.valid_usage_envelope({"output_tokens": True}))
        self.assertFalse(protocol.valid_usage_envelope({"input_tokens": 1_000_000_001}))
        self.assertFalse(protocol.valid_usage_envelope({"unknown_tokens": 1}))

        def handler(_request):
            return httpx.Response(200, json={
                "protocol_version": protocol.PROTOCOL_VERSION,
                "text_blocks": ["unsafe-usage"],
                "usage": {"input_tokens": -1},
            })

        transport = model_router.GatewayClaudeTransport(
            base_url="https://gateway.example.invalid",
            key_id="transport-key",
            secret="transport-secret",
            http_transport=httpx.MockTransport(handler),
        )
        with self.assertRaises(model_router.ClaudeGatewayError) as raised:
            transport.create_message_sync(self.request())
        self.assertEqual(raised.exception.code, "GATEWAY_PROTOCOL_ERROR")

    def test_gateway_url_and_stream_terminal_sequence_fail_closed(self):
        self.assertTrue(model_router._valid_gateway_base_url("https://gateway.example.com"))
        for invalid in (
            "http://gateway.example.com",
            "https://user:pass@gateway.example.com",
            "https://gateway.example.com/path",
            "https://gateway.example.com?debug=1",
            "https://gateway.example.com#fragment",
            "https://localhost",
            "https://service.local",
            "https://127.0.0.1",
            "https://[::1]",
            "https://gateway.example.com:8443",
        ):
            self.assertFalse(model_router._valid_gateway_base_url(invalid), invalid)

        sequences = (
            ([{"type": "done"}], "GATEWAY_STREAM_USAGE_MISSING"),
            ([{"type": "usage", "usage": _complete_usage(output_tokens=1)}], "GATEWAY_STREAM_INCOMPLETE"),
            ([
                {"type": "usage", "usage": _complete_usage(output_tokens=1)},
                {"type": "usage", "usage": _complete_usage(output_tokens=1)},
                {"type": "done"},
            ], "GATEWAY_PROTOCOL_ERROR"),
            ([
                {"type": "usage", "usage": _complete_usage(output_tokens=1)},
                {"type": "done"},
                {"type": "usage", "usage": _complete_usage(output_tokens=1)},
            ], "GATEWAY_PROTOCOL_ERROR"),
        )
        for events, code in sequences:
            with self.subTest(code=code):
                lines = [
                    {"protocol_version": protocol.PROTOCOL_VERSION, **event}
                    for event in events
                ]

                def handler(_request, payload=lines):
                    content = "".join(json.dumps(event) + "\n" for event in payload).encode()
                    return httpx.Response(
                        200,
                        content=content,
                        headers={"content-type": "application/x-ndjson"},
                    )

                transport = model_router.GatewayClaudeTransport(
                    base_url="https://gateway.example.com",
                    key_id="transport-key",
                    secret="transport-secret",
                    http_transport=httpx.MockTransport(handler),
                )

                async def collect():
                    return [event async for event in transport.stream_message(self.request())]

                with self.assertRaises(model_router.ClaudeGatewayError) as raised:
                    asyncio.run(collect())
                self.assertEqual(raised.exception.code, code)

    def test_gateway_readiness_and_legacy_path_do_not_require_local_anthropic_key(self):
        env = {
            "NOTEAI_CLAUDE_TRANSPORT": "gateway",
            "NOTEAI_CLAUDE_GATEWAY_URL": "https://gateway.example.invalid",
            "NOTEAI_CLAUDE_GATEWAY_AUTHORITY": "gateway.example.invalid",
            "NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH": "test-config-1",
            "NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH": "test-key-1",
            "NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID": "transport-key",
            "NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET": "transport-secret",
            "MOONSHOT_API_KEY": "moonshot-test-key",
            "NOTEAI_READINESS_REQUIRE_AI_KEYS": "1",
        }
        xml = "<diagnosis>d</diagnosis><titles>t</titles><plan>p</plan><body>b</body>"
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(api._mr, "call_claude_sync", return_value=xml), \
             mock.patch.object(api._database_readiness_probe, "result", return_value={"ok": True}), \
             mock.patch.object(api, "get_v04_composite_model", return_value=object()), \
             mock.patch.object(api, "get_model", return_value=object()), \
             mock.patch.object(model_router, "_gateway_remote_readiness", return_value={
                 "remote_ready": True,
                 "remote_error_code": None,
             }):
            readiness = model_router.claude_transport_readiness()
            parsed = api._call_claude("prompt")
            api_readiness, status_code = api._readiness_payload()
        self.assertEqual(readiness, {
            "mode": "gateway",
            "configured": True,
            "supported": True,
            "remote_checked": False,
            "remote_ready": None,
            "remote_error_code": None,
        })
        self.assertEqual(parsed, ("d", ["t"], "p", "b"))
        self.assertEqual(status_code, 200)
        self.assertTrue(api_readiness["checks"]["ai"]["ok"])
        self.assertEqual(api_readiness["checks"]["ai"]["claude_transport"], "gateway")
        self.assertTrue(api_readiness["checks"]["ai"]["claude_remote_ready"])


class ClaudeGatewayTrustBoundaryContractTests(unittest.TestCase):
    authority = "noteai-staging-claude-gateway.onrender.com"
    config_epoch = "staging-config-20260713"
    key_epoch = "staging-key-1"

    def test_v2_signature_binds_authority_and_configuration_epochs(self):
        self.assertEqual(protocol.PROTOCOL_VERSION, "claude-gateway.v2")
        base = {
            "secret": "contract-secret",
            "method": "POST",
            "path": protocol.MESSAGES_PATH,
            "authority": self.authority,
            "config_epoch": self.config_epoch,
            "key_epoch": self.key_epoch,
            "key_id": "contract-key",
            "protocol_version": protocol.PROTOCOL_VERSION,
            "content_type": "application/json",
            "timestamp": "1783968000",
            "nonce": "readiness_nonce_1234567890",
            "body": b'{"safe":true}',
        }
        baseline = protocol.signature(**base)
        for field, value in (
            ("authority", "other-gateway.onrender.com"),
            ("config_epoch", "staging-config-previous"),
            ("key_epoch", "staging-key-previous"),
        ):
            with self.subTest(field=field):
                changed = dict(base)
                changed[field] = value
                self.assertNotEqual(protocol.signature(**changed), baseline)

    def test_gateway_url_requires_one_exact_canonical_ascii_authority(self):
        expected_url = f"https://{self.authority}"
        self.assertTrue(model_router._valid_gateway_base_url(expected_url, self.authority))
        for invalid_url in (
            f"https://{self.authority}.",
            f"https://{self.authority}/",
            f"https://{self.authority.upper()}",
            "https://tést.onrender.com",
            "https://%6eoteai-staging-claude-gateway.onrender.com",
            "https://other-gateway.onrender.com",
        ):
            with self.subTest(url=invalid_url):
                self.assertFalse(
                    model_router._valid_gateway_base_url(invalid_url, self.authority)
                )

        for invalid_authority in (
            f"{self.authority}.",
            self.authority.upper(),
            "tést.onrender.com",
            "%6eoteai-staging-claude-gateway.onrender.com",
            "127.0.0.1",
        ):
            with self.subTest(authority=invalid_authority):
                self.assertFalse(model_router._valid_gateway_authority(invalid_authority))

    def test_dns_requires_every_a_and_aaaa_result_global(self):
        public_answers = (
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:2800:220:1:248:1893:25c8:1946", 443, 0, 0)),
        )
        with mock.patch.object(socket, "getaddrinfo", return_value=public_answers):
            self.assertEqual(
                model_router._resolve_global_gateway_addresses(self.authority),
                ("93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"),
            )

        mixed_answers = public_answers + (
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443)),
        )
        with mock.patch.object(socket, "getaddrinfo", return_value=mixed_answers), \
             self.assertRaises(model_router.ClaudeGatewayError) as raised:
            model_router._resolve_global_gateway_addresses(self.authority)
        self.assertEqual(raised.exception.code, "GATEWAY_DNS_NOT_GLOBAL")

    def test_dns_rejects_non_unicast_and_transition_addresses(self):
        rejected = (
            "224.0.0.1",
            "239.255.255.250",
            "ff02::1",
            "64:ff9b::7f00:1",
            "::ffff:93.184.216.34",
            "2002:5db8:d822::1",
            "2001:0000:4136:e378:8000:63bf:3fff:fdd2",
        )
        for address in rejected:
            family = socket.AF_INET6 if ":" in address else socket.AF_INET
            sockaddr = (address, 443, 0, 0) if family == socket.AF_INET6 else (address, 443)
            answer = ((family, socket.SOCK_STREAM, 6, "", sockaddr),)
            with self.subTest(address=address):
                with mock.patch.object(socket, "getaddrinfo", return_value=answer), \
                     self.assertRaises(model_router.ClaudeGatewayError) as raised:
                    model_router._resolve_global_gateway_addresses(self.authority)
                self.assertEqual(raised.exception.code, "GATEWAY_DNS_NOT_GLOBAL")

    def test_pinned_network_backend_uses_ip_and_preserves_origin_sni(self):
        response = (
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
            b"Content-Length: 2\r\nConnection: close\r\n\r\n{}"
        )

        class FakeSyncStream:
            def __init__(self):
                self.writes = []
                self.sent = False
                self.sni = []

            def read(self, _max_bytes, timeout=None):
                if self.sent:
                    return b""
                self.sent = True
                return response

            def write(self, buffer, timeout=None):
                self.writes.append(bytes(buffer))

            def close(self):
                return None

            def start_tls(self, ssl_context, server_hostname, timeout=None):
                self.sni.append(server_hostname)
                return self

            def get_extra_info(self, _info):
                return None

        class FakeSyncBackend:
            def __init__(self):
                self.hosts = []
                self.stream = FakeSyncStream()

            def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
                self.hosts.append((host, port))
                return self.stream

        sync_backend = FakeSyncBackend()
        sync_transport = httpx.HTTPTransport(verify=True, trust_env=False, retries=0)
        sync_transport._pool._network_backend = sync_backend
        model_router._pin_httpx_transport_backend(
            sync_transport,
            self.authority,
            "93.184.216.34",
            async_mode=False,
        )
        with httpx.Client(transport=sync_transport, trust_env=False) as client:
            self.assertEqual(client.get(f"https://{self.authority}/wire").status_code, 200)
        sync_wire = b"".join(sync_backend.stream.writes)
        self.assertEqual(sync_backend.hosts, [("93.184.216.34", 443)])
        self.assertEqual(sync_backend.stream.sni, [self.authority])
        self.assertIn(f"Host: {self.authority}\r\n".encode(), sync_wire)

        class FakeAsyncStream:
            def __init__(self):
                self.writes = []
                self.sent = False
                self.sni = []

            async def read(self, _max_bytes, timeout=None):
                if self.sent:
                    return b""
                self.sent = True
                return response

            async def write(self, buffer, timeout=None):
                self.writes.append(bytes(buffer))

            async def aclose(self):
                return None

            async def start_tls(self, ssl_context, server_hostname, timeout=None):
                self.sni.append(server_hostname)
                return self

            def get_extra_info(self, _info):
                return None

        class FakeAsyncBackend:
            def __init__(self):
                self.hosts = []
                self.stream = FakeAsyncStream()

            async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
                self.hosts.append((host, port))
                return self.stream

            async def sleep(self, seconds):
                await asyncio.sleep(seconds)

        async def async_wire_probe():
            backend = FakeAsyncBackend()
            transport = httpx.AsyncHTTPTransport(verify=True, trust_env=False, retries=0)
            transport._pool._network_backend = backend
            model_router._pin_httpx_transport_backend(
                transport,
                self.authority,
                "93.184.216.34",
                async_mode=True,
            )
            async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
                result = await client.get(f"https://{self.authority}/wire")
            return result, backend

        async_result, async_backend = asyncio.run(async_wire_probe())
        async_wire = b"".join(async_backend.stream.writes)
        self.assertEqual(async_result.status_code, 200)
        self.assertEqual(async_backend.hosts, [("93.184.216.34", 443)])
        self.assertEqual(async_backend.stream.sni, [self.authority])
        self.assertIn(f"Host: {self.authority}\r\n".encode(), async_wire)

    def test_private_httpcore_backend_shape_and_version_fail_closed(self):
        transport = httpx.HTTPTransport(verify=True, trust_env=False, retries=0)
        try:
            with mock.patch.object(model_router.httpcore, "__version__", "9.9.9"), \
                 self.assertRaises(model_router.ClaudeGatewayError) as wrong_version:
                model_router._pin_httpx_transport_backend(
                    transport, self.authority, "93.184.216.34", async_mode=False,
                )
            self.assertEqual(
                wrong_version.exception.code,
                "GATEWAY_TRANSPORT_INCOMPATIBLE",
            )
            with mock.patch.object(transport, "_pool", object()), \
                 self.assertRaises(model_router.ClaudeGatewayError) as wrong_shape:
                model_router._pin_httpx_transport_backend(
                    transport, self.authority, "93.184.216.34", async_mode=False,
                )
            self.assertEqual(
                wrong_shape.exception.code,
                "GATEWAY_TRANSPORT_INCOMPATIBLE",
            )
        finally:
            transport.close()

    def test_gateway_sync_async_and_sse_have_real_total_deadlines(self):
        class SlowTransport:
            def __init__(self):
                self.async_calls = 0
                self.sync_calls = 0
                self.cancelled = 0

            async def create_message(self, _request):
                self.async_calls += 1
                try:
                    await asyncio.sleep(60)
                finally:
                    self.cancelled += 1

            def create_message_sync(self, _request):
                self.sync_calls += 1
                raise AssertionError("gateway sync SDK path must not be used")

            async def stream_message(self, _request):
                try:
                    await asyncio.sleep(60)
                    yield model_router.ClaudeStreamEvent("content", text="late")
                finally:
                    self.cancelled += 1

        slow = SlowTransport()
        original = model_router._CLAUDE_TRANSPORT
        env = {"NOTEAI_CLAUDE_TRANSPORT": "gateway"}
        try:
            model_router.set_claude_transport(slow)
            with mock.patch.dict(os.environ, env, clear=False), \
                 mock.patch.object(model_router, "_claude_timeout_seconds", return_value=0.02), \
                 mock.patch.object(model_router, "_record_claude_usage") as usage:
                started = time.monotonic()
                with self.assertRaises(model_router.ClaudeGatewayError) as sync_error:
                    model_router.call_claude_sync(
                        model=model_router.CLAUDE_HAIKU,
                        messages=[{"role": "user", "content": "synthetic"}],
                        max_tokens=120,
                    )
                self.assertLess(time.monotonic() - started, 0.5)
                self.assertEqual(sync_error.exception.code, "CLAUDE_OUTCOME_UNKNOWN")
                self.assertTrue(sync_error.exception.usage_audit_required)
                self.assertEqual((slow.async_calls, slow.sync_calls), (1, 0))
                usage.assert_called_once_with(model_router.CLAUDE_HAIKU, None)

                async def collect_stream():
                    return [event async for event in model_router._claude_transport_stream(
                        model_router.CLAUDE_HAIKU,
                        GatewayClaudeTransportTests.request(),
                    )]

                started = time.monotonic()
                with self.assertRaises(model_router.ClaudeGatewayError) as stream_error:
                    asyncio.run(collect_stream())
                self.assertLess(time.monotonic() - started, 0.5)
                self.assertEqual(stream_error.exception.code, "CLAUDE_OUTCOME_UNKNOWN")
                self.assertTrue(stream_error.exception.usage_audit_required)
                self.assertEqual(usage.call_count, 2)
                usage.assert_has_calls([
                    mock.call(model_router.CLAUDE_HAIKU, None),
                    mock.call(model_router.CLAUDE_HAIKU, None),
                ])
        finally:
            model_router.set_claude_transport(original)
        self.assertGreaterEqual(slow.cancelled, 2)

        async def slow_claude(*_args, **_kwargs):
            await asyncio.sleep(60)

        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(model_router, "_call_claude", side_effect=slow_claude), \
             mock.patch.object(model_router, "_claude_timeout_seconds", return_value=0.02), \
             mock.patch.object(model_router, "MODEL_RETRY_ATTEMPTS", 1):
            started = time.monotonic()
            with self.assertRaises(model_router.ClaudeGatewayError) as async_error:
                asyncio.run(model_router.call("diagnosis", "system", "synthetic"))
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(async_error.exception.code, "CLAUDE_OUTCOME_UNKNOWN")

    def test_gateway_sync_deadline_does_not_wait_for_stuck_dns_or_dispatch(self):
        env = {
            "NOTEAI_CLAUDE_TRANSPORT": "gateway",
            "NOTEAI_CLAUDE_GATEWAY_URL": f"https://{self.authority}",
            "NOTEAI_CLAUDE_GATEWAY_AUTHORITY": self.authority,
            "NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH": self.config_epoch,
            "NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH": self.key_epoch,
            "NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID": "contract-key",
            "NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET": "contract-secret",
        }
        resolver_entered = threading.Event()
        release_resolver = threading.Event()

        def stuck_resolver(_authority):
            resolver_entered.set()
            release_resolver.wait(0.8)
            return ("93.184.216.34",)

        transport = model_router.GatewayClaudeTransport(
            base_url=f"https://{self.authority}",
            authority=self.authority,
            config_epoch=self.config_epoch,
            key_epoch=self.key_epoch,
            key_id="contract-key",
            secret="contract-secret",
        )
        original = model_router._CLAUDE_TRANSPORT
        try:
            model_router.set_claude_transport(transport)
            with mock.patch.dict(os.environ, env, clear=True), \
                 mock.patch.object(
                     model_router,
                     "_resolve_global_gateway_addresses",
                     side_effect=stuck_resolver,
                 ), \
                 mock.patch.object(model_router, "_claude_timeout_seconds", return_value=0.03), \
                 mock.patch.object(model_router, "_pin_httpx_transport_backend") as pin, \
                 mock.patch.object(httpx.AsyncClient, "post", new_callable=mock.AsyncMock) as post, \
                 mock.patch.object(model_router, "_record_claude_usage") as usage:
                started = time.monotonic()
                with self.assertRaises(model_router.ClaudeGatewayError) as raised:
                    model_router.call_claude_sync(
                        model=model_router.CLAUDE_HAIKU,
                        messages=[{"role": "user", "content": "synthetic"}],
                        max_tokens=120,
                    )
                elapsed = time.monotonic() - started
                self.assertTrue(resolver_entered.is_set())
                self.assertLess(elapsed, 0.2)
                self.assertEqual(raised.exception.code, "GATEWAY_PRE_DISPATCH_TIMEOUT")
                self.assertFalse(raised.exception.usage_audit_required)
                usage.assert_not_called()
                pin.assert_not_called()
                post.assert_not_awaited()
                release_resolver.set()
                time.sleep(0.05)
                pin.assert_not_called()
                post.assert_not_awaited()
        finally:
            release_resolver.set()
            model_router.set_claude_transport(original)

    def test_dns_executor_cancellation_storm_keeps_real_work_bounded(self):
        executor = model_router._BoundedGatewayDNSExecutor(
            max_workers=2,
            max_pending=2,
        )
        release_resolver = threading.Event()
        resolver_lock = threading.Lock()
        resolver_calls = {"count": 0}
        dispatches = []

        def stuck_resolver(_authority):
            with resolver_lock:
                resolver_calls["count"] += 1
            release_resolver.wait(1)
            return ("93.184.216.34",)

        def wire_handler(request):
            dispatches.append(request.url.path)
            return httpx.Response(
                200,
                json={
                    "protocol_version": protocol.PROTOCOL_VERSION,
                    "text_blocks": ["recovered"],
                    "usage": _complete_usage(input_tokens=1, output_tokens=1),
                },
            )

        def pin_to_fake_wire(_transport, _authority, _address, *, async_mode):
            self.assertTrue(async_mode)
            return httpx.MockTransport(wire_handler)

        transport = model_router.GatewayClaudeTransport(
            base_url=f"https://{self.authority}",
            authority=self.authority,
            config_epoch=self.config_epoch,
            key_epoch=self.key_epoch,
            key_id="contract-key",
            secret="contract-secret",
        )

        async def wait_until(predicate, timeout=0.5):
            deadline = asyncio.get_running_loop().time() + timeout
            while not predicate():
                if asyncio.get_running_loop().time() >= deadline:
                    raise AssertionError("synthetic executor state did not converge")
                await asyncio.sleep(0.001)

        async def exercise():
            loop = asyncio.get_running_loop()

            async def business_deadline_request():
                return await model_router._await_with_gateway_deadline(
                    transport.create_message(GatewayClaudeTransportTests.request()),
                    loop.time() + 0.05,
                    unstructured_cancel_usage_audit_required=True,
                    unstructured_cancel_usage_model=model_router.CLAUDE_HAIKU,
                )

            deadline_tasks = [
                asyncio.create_task(business_deadline_request())
                for _ in range(2)
            ]
            external_tasks = [
                asyncio.create_task(transport.create_message(
                    GatewayClaudeTransportTests.request()
                ))
                for _ in range(2)
            ]
            try:
                await wait_until(lambda: (
                    resolver_calls["count"] == 2
                    and executor._work_queue.qsize() >= 2
                ))
                deadline_results = await asyncio.gather(
                    *deadline_tasks,
                    return_exceptions=True,
                )
                for task in external_tasks:
                    task.cancel()
                external_results = await asyncio.gather(
                    *external_tasks,
                    return_exceptions=True,
                )

                rejection_codes = []
                storm_started = time.monotonic()
                for _ in range(12):
                    before = executor._work_queue.qsize()
                    task = asyncio.create_task(transport.create_message(
                        GatewayClaudeTransportTests.request()
                    ))
                    for _poll in range(20):
                        await asyncio.sleep(0)
                        if task.done() or executor._work_queue.qsize() > before:
                            break
                    if not task.done():
                        task.cancel()
                    try:
                        await task
                    except model_router.ClaudeGatewayError as exc:
                        rejection_codes.append(exc.code)
                    except asyncio.CancelledError:
                        pass

                before_release = {
                    "deadline_codes": [
                        getattr(result, "code", None)
                        for result in deadline_results
                    ],
                    "external_cancelled": sum(
                        isinstance(result, asyncio.CancelledError)
                        for result in external_results
                    ),
                    "rejection_codes": rejection_codes,
                    "queue_size": executor._work_queue.qsize(),
                    "resolver_calls": resolver_calls["count"],
                    "storm_elapsed": time.monotonic() - storm_started,
                    "pin_calls": pin.call_count,
                    "dispatches": len(dispatches),
                }
            finally:
                release_resolver.set()

            await wait_until(lambda: (
                resolver_calls["count"] == 4
                and executor._submission_slots._value == 4
            ))
            await asyncio.sleep(0.01)
            after_release = {
                "queue_size": executor._work_queue.qsize(),
                "resolver_calls": resolver_calls["count"],
                "pin_calls": pin.call_count,
                "dispatches": len(dispatches),
            }
            recovered = await transport.create_message(
                GatewayClaudeTransportTests.request()
            )
            return before_release, after_release, recovered

        try:
            with mock.patch.object(
                model_router,
                "_GATEWAY_DNS_EXECUTOR",
                executor,
            ), mock.patch.object(
                model_router,
                "_resolve_global_gateway_addresses",
                side_effect=stuck_resolver,
            ), mock.patch.object(
                model_router,
                "_pin_httpx_transport_backend",
                side_effect=pin_to_fake_wire,
            ) as pin, mock.patch.object(
                model_router,
                "_record_claude_usage",
            ) as usage:
                before_release, after_release, recovered = asyncio.run(exercise())
        finally:
            release_resolver.set()
            executor.shutdown(wait=True, cancel_futures=False)

        self.assertEqual(
            before_release["deadline_codes"],
            ["GATEWAY_PRE_DISPATCH_TIMEOUT"] * 2,
        )
        self.assertEqual(before_release["external_cancelled"], 2)
        self.assertEqual(
            before_release["rejection_codes"],
            ["GATEWAY_DNS_RESOLUTION_FAILED"] * 12,
        )
        self.assertLess(before_release["storm_elapsed"], 0.2)
        self.assertLessEqual(before_release["queue_size"], 2)
        self.assertEqual(before_release["resolver_calls"], 2)
        self.assertEqual(before_release["pin_calls"], 0)
        self.assertEqual(before_release["dispatches"], 0)
        self.assertEqual(after_release, {
            "queue_size": 0,
            "resolver_calls": 4,
            "pin_calls": 0,
            "dispatches": 0,
        })
        self.assertEqual(recovered.text_blocks, ("recovered",))
        self.assertEqual(pin.call_count, 1)
        self.assertEqual(dispatches, [protocol.MESSAGES_PATH])
        usage.assert_not_called()

    def test_gateway_absolute_deadline_preserves_external_cancellation(self):
        entered = asyncio.Event()

        async def cancellable_work():
            entered.set()
            await asyncio.sleep(60)

        async def exercise():
            deadline = asyncio.get_running_loop().time() + 1
            task = asyncio.create_task(model_router._await_with_gateway_deadline(
                cancellable_work(),
                deadline,
                unstructured_cancel_usage_audit_required=True,
                unstructured_cancel_usage_model=model_router.CLAUDE_HAIKU,
            ))
            await entered.wait()
            task.cancel()
            await task

        with mock.patch.object(model_router, "_record_claude_usage") as usage:
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(exercise())
        usage.assert_not_called()

    def test_public_call_gateway_deadline_covers_semaphore_and_retry_backoff(self):
        env = {"NOTEAI_CLAUDE_TRANSPORT": "gateway"}

        async def blocked_on_semaphore():
            model_router._SEMAPHORES.clear()
            semaphore = model_router._get_semaphore("claude", 1)
            await semaphore.acquire()
            try:
                return await asyncio.wait_for(
                    model_router.call("diagnosis", "system", "synthetic"),
                    timeout=0.3,
                )
            finally:
                semaphore.release()

        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(model_router, "CLAUDE_CONCURRENCY", 1), \
             mock.patch.object(model_router, "_claude_timeout_seconds", return_value=0.03), \
             mock.patch.object(model_router, "_call_claude", new_callable=mock.AsyncMock) as claude, \
             mock.patch.object(model_router, "_record_claude_usage") as usage:
            started = time.monotonic()
            with self.assertRaises(model_router.ClaudeGatewayError) as semaphore_error:
                asyncio.run(blocked_on_semaphore())
        self.assertLess(time.monotonic() - started, 0.2)
        self.assertEqual(semaphore_error.exception.code, "GATEWAY_PRE_DISPATCH_TIMEOUT")
        claude.assert_not_awaited()
        usage.assert_not_called()

        safe_error = model_router.ClaudeGatewayError(
            "CONTROL_PLANE_UNAVAILABLE", 503, fallback_safe=True,
        )
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(model_router, "_claude_timeout_seconds", return_value=0.055), \
             mock.patch.object(model_router, "MODEL_RETRY_ATTEMPTS", 3), \
             mock.patch.object(model_router, "MODEL_RETRY_BASE_DELAY", 0.025), \
             mock.patch.object(
                 model_router,
                 "_call_claude",
                 new_callable=mock.AsyncMock,
                 side_effect=safe_error,
             ) as claude, \
             mock.patch.object(model_router, "_call_kimi", new_callable=mock.AsyncMock) as kimi, \
             mock.patch.object(model_router, "_record_claude_usage") as usage:
            started = time.monotonic()
            with self.assertRaises(model_router.ClaudeGatewayError) as retry_error:
                asyncio.run(asyncio.wait_for(
                    model_router.call("diagnosis", "system", "synthetic"),
                    timeout=0.3,
                ))
        self.assertLess(time.monotonic() - started, 0.2)
        self.assertEqual(retry_error.exception.code, "GATEWAY_PRE_DISPATCH_TIMEOUT")
        self.assertEqual(claude.await_count, 2)
        kimi.assert_not_awaited()
        usage.assert_not_called()

    def test_public_call_gateway_deadline_covers_claude_to_kimi_fallback(self):
        env = {"NOTEAI_CLAUDE_TRANSPORT": "gateway"}

        async def hanging_kimi(*_args, **_kwargs):
            await asyncio.sleep(60)

        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(model_router, "_claude_timeout_seconds", return_value=0.03), \
             mock.patch.object(model_router, "MODEL_RETRY_ATTEMPTS", 1), \
             mock.patch.object(
                 model_router,
                 "_call_claude",
                 new_callable=mock.AsyncMock,
                 side_effect=model_router.ClaudeGatewayError(
                     "CONTROL_PLANE_UNAVAILABLE", 503, fallback_safe=True,
                 ),
             ) as claude, \
             mock.patch.object(
                 model_router,
                 "_call_kimi",
                 new_callable=mock.AsyncMock,
                 side_effect=hanging_kimi,
             ) as kimi, \
             mock.patch.object(model_router, "_record_claude_usage") as usage:
            started = time.monotonic()
            with self.assertRaises(model_router.ClaudeGatewayError) as raised:
                asyncio.run(asyncio.wait_for(
                    model_router.call("diagnosis", "system", "synthetic"),
                    timeout=0.3,
                ))
        self.assertLess(time.monotonic() - started, 0.2)
        self.assertEqual(raised.exception.code, "MODEL_DEADLINE_EXCEEDED")
        self.assertEqual(claude.await_count, 1)
        self.assertEqual(kimi.await_count, 1)
        usage.assert_not_called()

    def test_public_stream_gateway_deadline_covers_safe_kimi_fallback(self):
        env = {"NOTEAI_CLAUDE_TRANSPORT": "gateway"}
        calls = {"primary": 0, "fallback": 0}

        async def safe_primary(*_args, **_kwargs):
            calls["primary"] += 1
            raise model_router.ClaudeGatewayError(
                "CONTROL_PLANE_UNAVAILABLE", 503, fallback_safe=True,
            )
            yield ("content", "unreachable")

        async def hanging_kimi(*_args, **_kwargs):
            calls["fallback"] += 1
            await asyncio.sleep(60)

        async def collect():
            return [chunk async for chunk in model_router.stream(
                "diagnosis", "system", "synthetic",
            )]

        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(model_router, "_claude_timeout_seconds", return_value=0.03), \
             mock.patch.object(model_router, "_stream_claude", side_effect=safe_primary), \
             mock.patch.object(model_router, "_call_kimi", side_effect=hanging_kimi), \
             mock.patch.object(model_router, "_record_claude_usage") as usage:
            started = time.monotonic()
            with self.assertRaises(model_router.ClaudeGatewayError) as raised:
                asyncio.run(asyncio.wait_for(collect(), timeout=0.3))
        self.assertLess(time.monotonic() - started, 0.2)
        self.assertEqual(raised.exception.code, "MODEL_DEADLINE_EXCEEDED")
        self.assertEqual(calls, {"primary": 1, "fallback": 1})
        usage.assert_not_called()

    def test_stream_chat_gateway_deadline_covers_sonnet_to_haiku_fallback(self):
        env = {"NOTEAI_CLAUDE_TRANSPORT": "gateway"}
        calls = {"primary": 0, "fallback": 0}

        async def safe_primary(*_args, **_kwargs):
            calls["primary"] += 1
            raise model_router.ClaudeGatewayError(
                "CONTROL_PLANE_UNAVAILABLE", 503, fallback_safe=True,
            )
            yield model_router.ClaudeStreamEvent("content", text="unreachable")

        async def hanging_haiku(*_args, **_kwargs):
            calls["fallback"] += 1
            await asyncio.sleep(60)

        async def collect():
            return [chunk async for chunk in model_router.stream_chat(
                "system", [], "synthetic",
            )]

        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(model_router, "_claude_timeout_seconds", return_value=0.03), \
             mock.patch.object(model_router, "_claude_transport_stream", side_effect=safe_primary), \
             mock.patch.object(model_router, "_call_claude", side_effect=hanging_haiku), \
             mock.patch.object(model_router, "_record_claude_usage") as usage:
            started = time.monotonic()
            with self.assertRaises(model_router.ClaudeGatewayError) as raised:
                asyncio.run(asyncio.wait_for(collect(), timeout=0.3))
        self.assertLess(time.monotonic() - started, 0.2)
        self.assertEqual(raised.exception.code, "CLAUDE_OUTCOME_UNKNOWN")
        self.assertTrue(raised.exception.usage_audit_required)
        self.assertEqual(calls, {"primary": 1, "fallback": 1})
        usage.assert_called_once_with(model_router.CLAUDE_HAIKU, None)

    def test_readiness_probe_is_single_flight_and_timed_out_green_is_discarded(self):
        env = {
            "NOTEAI_CLAUDE_GATEWAY_URL": f"https://{self.authority}",
            "NOTEAI_CLAUDE_GATEWAY_AUTHORITY": self.authority,
            "NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH": self.config_epoch,
            "NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH": self.key_epoch,
            "NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID": "contract-key",
            "NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET": "contract-secret",
            "NOTEAI_CLAUDE_GATEWAY_READINESS_CACHE_TTL_SECONDS": "5",
        }
        release = threading.Event()
        entered = threading.Event()
        calls = {"count": 0}

        def delayed_green(_transport):
            calls["count"] += 1
            entered.set()
            release.wait(1)
            return {"remote_ready": True, "remote_error_code": None}

        model_router._GATEWAY_READINESS_CACHE.update({
            "key": None, "expires_at": 0.0, "value": None,
            "generation": 0, "inflight": None,
        })
        results = []
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(
                 model_router.GatewayClaudeTransport,
                 "probe_readiness",
                 autospec=True,
                 side_effect=delayed_green,
             ), \
             mock.patch.object(model_router, "_gateway_readiness_timeout_seconds", return_value=0.03):
            threads = [
                threading.Thread(
                    target=lambda: results.append(model_router._gateway_remote_readiness())
                )
                for _ in range(6)
            ]
            for thread in threads:
                thread.start()
            self.assertTrue(entered.wait(0.5))
            for thread in threads:
                thread.join(0.5)
            release.set()
            for thread in threads:
                thread.join(0.5)
            time.sleep(0.05)

        self.assertEqual(calls["count"], 1)
        self.assertEqual(len(results), 6)
        self.assertTrue(all(not result["remote_ready"] for result in results))
        self.assertNotEqual(
            (model_router._GATEWAY_READINESS_CACHE.get("value") or {}).get("remote_ready"),
            True,
        )

    def test_readiness_old_generation_cannot_cache_green_for_new_key(self):
        env = {
            "NOTEAI_CLAUDE_GATEWAY_URL": f"https://{self.authority}",
            "NOTEAI_CLAUDE_GATEWAY_AUTHORITY": self.authority,
            "NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH": self.config_epoch,
            "NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH": self.key_epoch,
            "NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID": "contract-key",
            "NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET": "contract-secret",
            "NOTEAI_CLAUDE_GATEWAY_READINESS_CACHE_TTL_SECONDS": "5",
        }
        entered = threading.Event()
        release = threading.Event()
        calls = []

        def probe(transport):
            calls.append(transport.key_epoch)
            if transport.key_epoch == self.key_epoch:
                entered.set()
                release.wait(1)
                return {"remote_ready": True, "remote_error_code": None}
            return {
                "remote_ready": False,
                "remote_error_code": "NEW_GENERATION_RED",
            }

        model_router._GATEWAY_READINESS_CACHE.update({
            "key": None, "expires_at": 0.0, "value": None,
            "generation": 0, "inflight": None,
        })
        old_results = []
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(
                 model_router.GatewayClaudeTransport,
                 "probe_readiness",
                 autospec=True,
                 side_effect=probe,
             ), \
             mock.patch.object(model_router, "_gateway_readiness_timeout_seconds", return_value=0.5):
            old_waiter = threading.Thread(
                target=lambda: old_results.append(model_router._gateway_remote_readiness())
            )
            old_waiter.start()
            self.assertTrue(entered.wait(0.5))

            os.environ["NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH"] = "staging-key-2"
            busy = model_router._gateway_remote_readiness()
            release.set()
            old_waiter.join(0.5)
            current = model_router._gateway_remote_readiness()

        self.assertFalse(old_waiter.is_alive())
        self.assertEqual(busy["remote_error_code"], "GATEWAY_READINESS_BUSY")
        self.assertEqual(old_results, [{
            "remote_ready": False,
            "remote_error_code": "GATEWAY_READINESS_TIMEOUT",
        }])
        self.assertEqual(current, {
            "remote_ready": False,
            "remote_error_code": "NEW_GENERATION_RED",
        })
        self.assertEqual(calls, [self.key_epoch, "staging-key-2"])
        self.assertEqual(
            model_router._GATEWAY_READINESS_CACHE["value"],
            current,
        )

    def test_transport_rejects_redirect_even_with_valid_success_payload(self):
        def redirect(_request):
            return httpx.Response(307, json={
                "protocol_version": protocol.PROTOCOL_VERSION,
                "text_blocks": ["must-not-be-accepted"],
                "usage": _complete_usage(),
            })

        transport = model_router.GatewayClaudeTransport(
            base_url=f"https://{self.authority}",
            authority=self.authority,
            config_epoch=self.config_epoch,
            key_epoch=self.key_epoch,
            key_id="contract-key",
            secret="contract-secret",
            http_transport=httpx.MockTransport(redirect),
        )
        with self.assertRaises(model_router.ClaudeGatewayError) as raised:
            transport.create_message_sync(GatewayClaudeTransportTests.request())
        self.assertEqual(raised.exception.code, "GATEWAY_PROTOCOL_ERROR")

    def test_transport_verifies_signed_remote_readiness_response(self):
        seen = []

        def handler(request):
            seen.append(request)
            challenge = request.headers[protocol.HEADER_READINESS_CHALLENGE]
            nonce = request.headers[protocol.HEADER_NONCE]
            payload = {
                "protocol_version": protocol.PROTOCOL_VERSION,
                "service": "noteai-claude-gateway",
                "status": "ready_multi_instance",
                "deployment_scope": "shared_control_plane",
                "replay_store": "dynamodb_shared_atomic",
                "config_epoch": self.config_epoch,
                "key_epoch": self.key_epoch,
                "server_time": int(time.time()),
                "challenge": challenge,
                "nonce": nonce,
            }
            payload["attestation"] = protocol.readiness_attestation(
                "contract-secret", payload,
            )
            return httpx.Response(200, json=payload)

        transport = model_router.GatewayClaudeTransport(
            base_url=f"https://{self.authority}",
            authority=self.authority,
            config_epoch=self.config_epoch,
            key_epoch=self.key_epoch,
            key_id="contract-key",
            secret="contract-secret",
            http_transport=httpx.MockTransport(handler),
        )
        result = transport.probe_readiness()
        self.assertTrue(result["remote_ready"])
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].method, "GET")
        self.assertEqual(seen[0].headers["host"], self.authority)

    def test_remote_readiness_rejects_bad_attestation_context_clock_redirect_and_timeout(self):
        def handler_for(mode):
            def handler(request):
                if mode == "timeout":
                    raise httpx.ReadTimeout("synthetic", request=request)
                if mode == "redirect":
                    return httpx.Response(307, json={})
                payload = {
                    "protocol_version": protocol.PROTOCOL_VERSION,
                    "service": "noteai-claude-gateway",
                    "status": "ready_multi_instance",
                    "deployment_scope": "shared_control_plane",
                    "replay_store": "dynamodb_shared_atomic",
                    "config_epoch": self.config_epoch,
                    "key_epoch": self.key_epoch,
                    "server_time": int(time.time()),
                    "challenge": request.headers[protocol.HEADER_READINESS_CHALLENGE],
                    "nonce": request.headers[protocol.HEADER_NONCE],
                }
                if mode == "protocol":
                    payload["protocol_version"] = "claude-gateway.v0"
                elif mode == "epoch":
                    payload["config_epoch"] = "other-config"
                elif mode == "challenge":
                    payload["challenge"] = "other_challenge_1234567890"
                elif mode == "clock":
                    payload["server_time"] -= 3600
                payload["attestation"] = protocol.readiness_attestation(
                    "contract-secret", payload,
                )
                if mode == "attestation":
                    payload["attestation"] = "0" * 64
                return httpx.Response(200, json=payload)

            return handler

        expectations = {
            "attestation": "GATEWAY_READINESS_SIGNATURE_INVALID",
            "protocol": "GATEWAY_READINESS_MISMATCH",
            "epoch": "GATEWAY_READINESS_EPOCH_MISMATCH",
            "challenge": "GATEWAY_READINESS_MISMATCH",
            "clock": "GATEWAY_READINESS_CLOCK_SKEW",
            "redirect": "GATEWAY_READINESS_HTTP_ERROR",
            "timeout": "GATEWAY_READINESS_TIMEOUT",
        }
        for mode, code in expectations.items():
            with self.subTest(mode=mode):
                transport = model_router.GatewayClaudeTransport(
                    base_url=f"https://{self.authority}",
                    authority=self.authority,
                    config_epoch=self.config_epoch,
                    key_epoch=self.key_epoch,
                    key_id="contract-key",
                    secret="contract-secret",
                    http_transport=httpx.MockTransport(handler_for(mode)),
                )
                with self.assertRaises(model_router.ClaudeGatewayError) as raised:
                    transport.probe_readiness()
                self.assertEqual(raised.exception.code, code)
                self.assertNotIn("synthetic", str(raised.exception))

    def test_remote_readiness_cache_never_serves_expired_green(self):
        env = {
            "NOTEAI_CLAUDE_GATEWAY_URL": f"https://{self.authority}",
            "NOTEAI_CLAUDE_GATEWAY_AUTHORITY": self.authority,
            "NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH": self.config_epoch,
            "NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH": self.key_epoch,
            "NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID": "contract-key",
            "NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET": "contract-secret",
            "NOTEAI_CLAUDE_GATEWAY_READINESS_CACHE_TTL_SECONDS": "0",
        }
        model_router._GATEWAY_READINESS_CACHE.update({
            "key": None, "expires_at": 0.0, "value": None,
            "generation": 0, "inflight": None,
        })
        unavailable = model_router.ClaudeGatewayError(
            "GATEWAY_READINESS_TIMEOUT", 503, fallback_safe=True,
        )
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(
                 model_router.GatewayClaudeTransport,
                 "probe_readiness",
                 side_effect=[
                     {"remote_ready": True, "remote_error_code": None},
                     unavailable,
                 ],
             ) as probe:
            first = model_router._gateway_remote_readiness()
            second = model_router._gateway_remote_readiness()
        self.assertTrue(first["remote_ready"])
        self.assertFalse(second["remote_ready"])
        self.assertEqual(second["remote_error_code"], "GATEWAY_READINESS_TIMEOUT")
        self.assertEqual(probe.call_count, 2)

    def test_timeout_order_is_provider_then_http_then_gateway_business(self):
        with mock.patch.dict(os.environ, {
            "NOTEAI_CLAUDE_TRANSPORT": "gateway",
            "NOTEAI_CLAUDE_GATEWAY_BUSINESS_TIMEOUT_SECONDS": "210",
        }, clear=False):
            self.assertEqual(
                model_router._claude_timeout_seconds("semantic", False, 120),
                210.0,
            )
        with mock.patch.dict(os.environ, {"NOTEAI_CLAUDE_TRANSPORT": "local"}, clear=False):
            self.assertEqual(model_router._claude_timeout_seconds("semantic", False, 120), 30.0)
            self.assertEqual(model_router._claude_timeout_seconds("content_gen", False, 120), 45.0)
            self.assertEqual(model_router._claude_timeout_seconds("diagnosis", False, 120), 55.0)
            self.assertEqual(model_router._claude_timeout_seconds("arbitrate", True, 16000), 180.0)

        transport = model_router.GatewayClaudeTransport(
            base_url=f"https://{self.authority}",
            authority=self.authority,
            config_epoch=self.config_epoch,
            key_epoch=self.key_epoch,
            key_id="contract-key",
            secret="contract-secret",
            http_transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
        )
        self.assertEqual(transport.timeout.read, 190.0)
        with mock.patch.dict(os.environ, {
            "NOTEAI_CLAUDE_GATEWAY_PROVIDER_DEADLINE_SECONDS": "180",
        }, clear=False):
            self.assertEqual(claude_gateway._provider_deadline_seconds(), 180.0)

        with mock.patch.dict(os.environ, {
            "NOTEAI_CLAUDE_GATEWAY_HTTP_TIMEOUT_SECONDS": "180",
        }, clear=False), self.assertRaises(model_router.ClaudeGatewayError) as invalid:
            transport.create_message_sync(GatewayClaudeTransportTests.request())
        self.assertEqual(invalid.exception.code, "GATEWAY_TIMEOUT_CONFIG_INVALID")

    def test_signed_remote_readiness_does_not_claim_nonce_rate_or_operation(self):
        store = _FakeSharedControlStore()
        provider = _FakeProvider()
        env = {
            "ANTHROPIC_API_KEY": "provider-test-key",
            "NOTEAI_CLAUDE_GATEWAY_AUTHORITY": self.authority,
            "NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH": self.config_epoch,
            "NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH": self.key_epoch,
            "NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID": "contract-key",
            "NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET": "contract-secret",
            "NOTEAI_CLAUDE_GATEWAY_CONTROL_MODE": "dynamodb",
            "NOTEAI_CLAUDE_GATEWAY_INSTANCE_COUNT": "2",
            "NOTEAI_CLAUDE_GATEWAY_DDB_TABLE": "synthetic-table",
            "NOTEAI_CLAUDE_GATEWAY_DDB_REGION": "ap-southeast-1",
            "NOTEAI_CLAUDE_GATEWAY_PRINCIPAL_ID": "synthetic-principal",
            "AWS_ROLE_ARN": "synthetic-role",
            "AWS_WEB_IDENTITY_TOKEN_FILE": "/synthetic/token",
            "AWS_EC2_METADATA_DISABLED": "true",
        }
        challenge = "challenge_1234567890abcdef"
        nonce = "readiness_nonce_1234567890"
        body = b""
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(claude_gateway, "_CONTROL_STORE", store), \
             mock.patch.object(claude_gateway, "_PROVIDER", provider):
            headers = protocol.auth_headers(
                key_id="contract-key",
                secret="contract-secret",
                method="GET",
                path=protocol.READINESS_PATH,
                authority=self.authority,
                config_epoch=self.config_epoch,
                key_epoch=self.key_epoch,
                body=body,
                nonce=nonce,
            )
            headers[protocol.HEADER_READINESS_CHALLENGE] = challenge
            with TestClient(claude_gateway.app) as client:
                response = client.get(protocol.READINESS_PATH, headers=headers)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["challenge"], challenge)
        self.assertEqual(payload["nonce"], nonce)
        self.assertEqual(payload["service"], "noteai-claude-gateway")
        self.assertEqual(payload["protocol_version"], protocol.PROTOCOL_VERSION)
        self.assertEqual(payload["deployment_scope"], "shared_control_plane")
        self.assertEqual(payload["replay_store"], "dynamodb_shared_atomic")
        self.assertEqual(payload["config_epoch"], self.config_epoch)
        self.assertEqual(payload["key_epoch"], self.key_epoch)
        self.assertTrue(protocol.verify_readiness_attestation("contract-secret", payload))
        self.assertNotIn("key_id", payload)
        self.assertNotIn("secret", json.dumps(payload).lower())
        self.assertFalse(store.calls)
        self.assertFalse(provider.calls)

    def test_gateway_rejects_host_or_epoch_mismatch_before_provider(self):
        env = {
            "ANTHROPIC_API_KEY": "provider-test-key",
            "NOTEAI_CLAUDE_GATEWAY_AUTHORITY": self.authority,
            "NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH": self.config_epoch,
            "NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH": self.key_epoch,
            "NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID": "contract-key",
            "NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET": "contract-secret",
            "NOTEAI_CLAUDE_GATEWAY_CONTROL_MODE": "memory",
            "NOTEAI_CLAUDE_GATEWAY_INSTANCE_COUNT": "1",
        }
        body = ClaudeGatewayEndpointTests.encoded(
            ClaudeGatewayEndpointTests.payload(),
        )
        for changed_header, changed_value in (
            ("Host", "other-gateway.onrender.com"),
            (protocol.HEADER_AUTHORITY, "other-gateway.onrender.com"),
            (protocol.HEADER_CONFIG_EPOCH, "other-config"),
            (protocol.HEADER_KEY_EPOCH, "other-key"),
        ):
            provider = _FakeProvider()
            with self.subTest(header=changed_header), \
                 mock.patch.dict(os.environ, env, clear=True), \
                 mock.patch.object(claude_gateway, "_PROVIDER", provider):
                headers = protocol.auth_headers(
                    key_id="contract-key",
                    secret="contract-secret",
                    method="POST",
                    path=protocol.MESSAGES_PATH,
                    authority=self.authority,
                    config_epoch=self.config_epoch,
                    key_epoch=self.key_epoch,
                    body=body,
                )
                headers[changed_header] = changed_value
                with TestClient(claude_gateway.app) as client:
                    response = client.post(
                        protocol.MESSAGES_PATH,
                        content=body,
                        headers=headers,
                    )
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["error"]["code"], "AUTH_CONTEXT_INVALID")
            self.assertFalse(provider.calls)

    def test_anthropic_clients_have_explicit_timeout_and_zero_retries(self):
        provider = claude_gateway.AnthropicProvider()
        with mock.patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": "gateway-test",
            "NOTEAI_CLAUDE_GATEWAY_PROVIDER_DEADLINE_SECONDS": "180",
        }, clear=False), mock.patch.object(
            claude_gateway.anthropic, "AsyncAnthropic",
        ) as gateway_client:
            provider._get_client()
        self.assertEqual(gateway_client.call_args.kwargs["timeout"], 180.0)
        self.assertEqual(gateway_client.call_args.kwargs["max_retries"], 0)


class GatewayRehearsalTests(unittest.TestCase):
    output_fields = {
        "schema", "mode", "status_codes", "error_codes",
        "fake_provider_calls", "instance_marker", "commit_prefix",
        "control_config_marker", "control_stage", "control_reason",
    }

    @staticmethod
    def env(**updates):
        values = {
            "RENDER": "true",
            "RENDER_SERVICE_NAME": "noteai-staging-claude-gateway",
            "RENDER_EXTERNAL_HOSTNAME": "noteai-staging-claude-gateway.onrender.com",
            "NOTEAI_GATEWAY_REHEARSAL_ACK": "staging-zero-claude",
            "NOTEAI_CLAUDE_GATEWAY_AUTHORITY": "noteai-staging-claude-gateway.onrender.com",
            "NOTEAI_CLAUDE_GATEWAY_CONTROL_MODE": "dynamodb",
            "NOTEAI_CLAUDE_GATEWAY_INSTANCE_COUNT": "2",
            "NOTEAI_CLAUDE_GATEWAY_CONCURRENCY": "2",
            "NOTEAI_CLAUDE_GATEWAY_REQUESTS_PER_MINUTE": "30",
            "NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID": "rehearsal-test-key",
            "NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET": "rehearsal-test-secret",
            "NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH": "staging-config-test",
            "NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH": "staging-key-test",
            "NOTEAI_CLAUDE_GATEWAY_DDB_TABLE": "rehearsal-control",
            "NOTEAI_CLAUDE_GATEWAY_DDB_REGION": "ap-southeast-1",
            "NOTEAI_CLAUDE_GATEWAY_PRINCIPAL_ID": "normal-staging-principal",
            "WEB_CONCURRENCY": "1",
            "AWS_ROLE_ARN": "arn:aws:iam::123456789012:role/render-rehearsal",
            "AWS_WEB_IDENTITY_TOKEN_FILE": "/render/injected/token",
            "AWS_EC2_METADATA_DISABLED": "true",
            "AWS_ACCESS_KEY_ID": "",
            "AWS_SECRET_ACCESS_KEY": "",
            "AWS_SESSION_TOKEN": "",
            "RENDER_INSTANCE_ID": "instance-test-a",
            "RENDER_GIT_COMMIT": "0123456789abcdef0123456789abcdef01234567",
        }
        values.update(updates)
        return values

    def test_guard_requires_exact_staging_shell_contract(self):
        expected = self.env()
        self.assertTrue(rehearsal.guard_environment(expected))
        for key in (
            "RENDER", "RENDER_SERVICE_NAME", "RENDER_EXTERNAL_HOSTNAME",
            "NOTEAI_CLAUDE_GATEWAY_CONTROL_MODE",
            "NOTEAI_GATEWAY_REHEARSAL_ACK",
        ):
            with self.subTest(key=key):
                rejected = dict(expected)
                rejected[key] = "wrong"
                self.assertFalse(rehearsal.guard_environment(rejected))

        negative_updates = {
            "AWS_ACCESS_KEY_ID": "static-access-key",
            "AWS_SECRET_ACCESS_KEY": "static-secret-key",
            "AWS_SESSION_TOKEN": "static-session-token",
            "NOTEAI_CLAUDE_GATEWAY_DDB_REGION": "us-east-1",
            "NOTEAI_CLAUDE_GATEWAY_DDB_TABLE": "",
            "AWS_ROLE_ARN": "not-an-iam-role-arn",
            "AWS_WEB_IDENTITY_TOKEN_FILE": "",
            "AWS_EC2_METADATA_DISABLED": "false",
            "NOTEAI_CLAUDE_GATEWAY_PRINCIPAL_ID": "",
            "RENDER_INSTANCE_ID": "",
            "RENDER_GIT_COMMIT": "0123456789abcdef",
        }
        for key, value in negative_updates.items():
            with self.subTest(negative=key):
                self.assertFalse(rehearsal.guard_environment(self.env(**{key: value})))

        output = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch("sys.stdout", output):
            exit_code = rehearsal.main([
                "operation",
                "--operation-id", "rehearsal_operation_1234567890",
                "--namespace", "rehearsal-contract-test",
            ])
        self.assertEqual(exit_code, 2)
        payload = json.loads(output.getvalue())
        self.assertEqual(set(payload), self.output_fields)
        self.assertEqual(payload["error_codes"], ["REHEARSAL_GUARD_REJECTED"])
        self.assertEqual(payload["fake_provider_calls"], 0)
        self.assertEqual(payload["control_stage"], "NONE")
        self.assertEqual(payload["control_reason"], "NONE")

        malformed_output = io.StringIO()
        with mock.patch("sys.stdout", malformed_output):
            malformed_exit = rehearsal.main(["operation", "--help"])
        self.assertEqual(malformed_exit, 2)
        malformed_payload = json.loads(malformed_output.getvalue())
        self.assertEqual(set(malformed_payload), self.output_fields)
        self.assertEqual(malformed_payload["error_codes"], ["REHEARSAL_ARGUMENT_INVALID"])
        self.assertEqual(malformed_payload["fake_provider_calls"], 0)
        self.assertEqual(malformed_payload["control_stage"], "NONE")
        self.assertEqual(malformed_payload["control_reason"], "NONE")

        sanitized = rehearsal._fixed_output(
            "operation",
            [503],
            ["CONTROL_PLANE_OUTCOME_UNKNOWN"],
            0,
            diagnostic_stage="sensitive-stage-sentinel",
            diagnostic_reason="sensitive-reason-sentinel",
        )
        self.assertEqual(sanitized["control_stage"], "UNKNOWN")
        self.assertEqual(sanitized["control_reason"], "UNKNOWN")
        self.assertNotIn("sensitive-stage-sentinel", repr(sanitized))
        self.assertNotIn("sensitive-reason-sentinel", repr(sanitized))

    def test_guarded_shell_rehearsal_exposes_only_fixed_begin_diagnostic(self):
        sensitive_values = (
            "sensitive-message-sentinel",
            "sensitive-request-id-sentinel",
            "https://sensitive.example.invalid/control",
            "sensitive-table-sentinel",
            "arn:aws:iam::123456789012:role/sensitive-role-sentinel",
            "sensitive-principal-sentinel",
            "sensitive-operation-sentinel",
            "Message",
            "RequestId",
            "SensitiveFields",
        )

        class AccessDeniedError(Exception):
            def __init__(inner_self):
                super().__init__(sensitive_values[0])
                inner_self.response = {
                    "Error": {
                        "Code": "AccessDeniedException",
                        "Message": sensitive_values[0],
                    },
                    "ResponseMetadata": {"RequestId": sensitive_values[1]},
                    "SensitiveFields": list(sensitive_values[2:7]),
                }

        class BeginDeniedClient:
            def put_item(inner_self, **_kwargs):
                return {}

            def update_item(inner_self, **kwargs):
                key = kwargs.get("Key", {}).get("pk", {}).get("S", "")
                if key.startswith("LEASE#"):
                    return {"Attributes": {"fence": {"N": "1"}}}
                return {}

            def transact_write_items(inner_self, **_kwargs):
                raise AccessDeniedError()

        store = DynamoDBControlStore(
            "control-table",
            BeginDeniedClient(),
            credential_method="assume-role-with-web-identity",
        )
        args = rehearsal._parser().parse_args([
            "operation",
            "--operation-id", "rehearsal_operation_diagnostic_12345",
            "--namespace", "rehearsal-diagnostic-test",
        ])
        with mock.patch.dict(os.environ, self.env(), clear=False), \
             mock.patch.object(
                 DynamoDBControlStore, "from_env", return_value=store,
             ), mock.patch("builtins.print") as print_call, \
             mock.patch("logging.Logger._log") as log_call:
            result = asyncio.run(rehearsal._run(args))

        self.assertEqual(set(result), self.output_fields)
        self.assertEqual(result["status_codes"], [503])
        self.assertEqual(
            result["error_codes"], ["CONTROL_PLANE_OUTCOME_UNKNOWN"],
        )
        self.assertEqual(result["fake_provider_calls"], 0)
        self.assertEqual(result["control_stage"], "BEGIN_PROVIDER")
        self.assertEqual(result["control_reason"], "ACCESS_DENIED")
        serialized = json.dumps(result, sort_keys=True)
        for sensitive in sensitive_values:
            self.assertNotIn(sensitive, serialized)
        print_call.assert_not_called()
        fixed_logs = repr(log_call.call_args_list)
        self.assertIn("CONTROL_PLANE_OUTCOME_UNKNOWN", fixed_logs)
        for sensitive in sensitive_values:
            self.assertNotIn(sensitive, fixed_logs)

    def test_load_mode_is_bounded_cpu_only_and_fixed_output(self):
        class AdvancingClock:
            def __init__(self):
                self.now = 0.0
                self.sleeps = []

            def __call__(self):
                self.now += 0.02
                return self.now

            async def sleep(self, delay):
                self.sleeps.append(delay)
                self.now += delay

        clock = AdvancingClock()
        with mock.patch.dict(os.environ, self.env(), clear=False), \
             mock.patch.object(
                 rehearsal, "_signed_asgi_post",
                 side_effect=AssertionError("load must not send HTTP"),
             ) as asgi_post, \
             mock.patch.object(
                 claude_gateway, "_get_control_store",
                 side_effect=AssertionError("load must not open DynamoDB"),
             ) as control_store, \
             mock.patch.object(
                 claude_gateway.anthropic, "AsyncAnthropic",
                 side_effect=AssertionError("load must not create Anthropic client"),
             ) as anthropic_client:
            result = asyncio.run(rehearsal.execute_load(
                60,
                clock=clock,
                sleeper=clock.sleep,
            ))
        self.assertEqual(set(result), self.output_fields)
        self.assertEqual(result["mode"], "load")
        self.assertEqual(result["status_codes"], [200])
        self.assertEqual(result["error_codes"], ["OK"])
        self.assertEqual(result["fake_provider_calls"], 0)
        self.assertRegex(result["control_config_marker"], r"^[0-9a-f]{12}$")
        self.assertGreater(len(clock.sleeps), 1)
        self.assertEqual(rehearsal.LOAD_DUTY_CYCLE, 0.95)
        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn(self.env()["NOTEAI_CLAUDE_GATEWAY_DDB_TABLE"], serialized)
        self.assertNotIn(self.env()["AWS_ROLE_ARN"], serialized)
        self.assertNotIn(
            self.env()["NOTEAI_CLAUDE_GATEWAY_PRINCIPAL_ID"], serialized,
        )
        asgi_post.assert_not_called()
        control_store.assert_not_called()
        anthropic_client.assert_not_called()

    def test_load_parser_requires_start_and_enforces_duration_bounds(self):
        with self.assertRaises(rehearsal.RehearsalSafetyError):
            rehearsal._parser().parse_args([
                "load", "--duration-seconds", "300",
            ])
        parsed = rehearsal._parser().parse_args([
            "load", "--start-at", "4102444800", "--duration-seconds", "300",
        ])
        self.assertEqual(parsed.mode, "load")
        self.assertEqual(parsed.duration_seconds, "300")
        for invalid in ("59", "601", "not-a-number"):
            with self.subTest(duration=invalid), \
                 self.assertRaises(rehearsal.RehearsalSafetyError):
                rehearsal._bounded_int(invalid, 60, 600)
        self.assertEqual(rehearsal._bounded_int("60", 60, 600), 60)
        self.assertEqual(rehearsal._bounded_int("600", 60, 600), 600)

    def test_fake_provider_runtime_hard_blocks_anthropic_client_creation(self):
        fake = rehearsal.FixedFakeProvider()
        original = claude_gateway.AnthropicProvider._get_client
        with rehearsal._fake_provider_runtime(fake):
            with self.assertRaises(rehearsal.RehearsalSafetyError):
                claude_gateway.AnthropicProvider()._get_client()
            with self.assertRaises(rehearsal.RehearsalSafetyError):
                claude_gateway.anthropic.AsyncAnthropic(api_key="must-not-open")
        self.assertIs(claude_gateway.AnthropicProvider._get_client, original)
        self.assertEqual(fake.calls, 0)

    def test_same_operation_concurrency_runs_exactly_one_fake_provider(self):
        class RetentionStore(_FakeSharedControlStore):
            retention_seconds = None

            def __init__(inner_self):
                super().__init__()
                inner_self.leases = {}
                inner_self.claim_count = 0
                inner_self.claim_barrier = asyncio.Event()
                inner_self.begin_attempts = 0
                inner_self.release_count = 0

            async def acquire_lease(inner_self, operation, slots, now, seconds):
                inner_self._require_available()
                self.assertEqual(slots, 2)
                for slot in range(slots):
                    lease = inner_self.leases.get(slot)
                    if lease is None or lease.expires_at <= now:
                        inner_self.fence += 1
                        lease = Lease(
                            slot, operation, f"owner-{inner_self.fence}",
                            inner_self.fence, now + seconds,
                        )
                        inner_self.leases[slot] = lease
                        inner_self.calls.append(("lease", operation, slot))
                        return lease
                return None

            async def claim_operation(inner_self, *args):
                claim = await super().claim_operation(*args)
                inner_self.claim_count += 1
                if inner_self.claim_count == 2:
                    inner_self.claim_barrier.set()
                else:
                    await inner_self.claim_barrier.wait()
                return claim

            async def begin_provider(
                inner_self, operation, lease, _dispatch, _model, now,
            ):
                inner_self.begin_attempts += 1
                inner_self._require_available()
                if (
                    inner_self.operations.get(operation) != OperationState.CLAIMED
                    or inner_self.leases.get(lease.slot) != lease
                    or lease.expires_at <= now
                ):
                    return False
                inner_self.operations[operation] = OperationState.PROVIDER_STARTED
                inner_self.calls.append(("begin", operation))
                return True

            async def finish_operation(
                inner_self, operation, lease, state, now,
                *, retention_seconds, **kwargs,
            ):
                inner_self.retention_seconds = retention_seconds
                inner_self._require_available()
                if (
                    inner_self.leases.get(lease.slot) != lease
                    or inner_self.operations.get(operation)
                    != OperationState.PROVIDER_STARTED
                ):
                    return False
                inner_self.operations[operation] = state
                inner_self.leases.pop(lease.slot, None)
                inner_self.calls.append(("finish", operation, state))
                return True

            async def release_lease(inner_self, lease):
                inner_self.release_count += 1
                if inner_self.leases.get(lease.slot) == lease:
                    inner_self.leases.pop(lease.slot, None)
                    return True
                return False

        store = RetentionStore()
        operation_id = "rehearsal_operation_exact_one_12345"
        with mock.patch.dict(os.environ, self.env(), clear=False):
            result = asyncio.run(rehearsal.execute_operation(
                operation_id,
                "rehearsal-operation-test",
                0.05,
                request_count=2,
                control_store=store,
            ))
        self.assertEqual(set(result), self.output_fields)
        self.assertEqual(result["status_codes"].count(200), 1)
        self.assertEqual(result["status_codes"].count(409), 1)
        self.assertEqual(result["fake_provider_calls"], 1)
        self.assertCountEqual(
            result["error_codes"], ["OK", "OPERATION_ALREADY_DISPATCHED"],
        )
        self.assertNotIn("CONTROL_PLANE_OUTCOME_UNKNOWN", result["error_codes"])
        self.assertEqual(store.begin_attempts, 1)
        self.assertEqual(store.release_count, 1)
        self.assertEqual(store.retention_seconds, 24 * 60 * 60)
        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn(operation_id, serialized)
        self.assertNotIn("rehearsal-operation-test", serialized)
        self.assertEqual(result["commit_prefix"], "0123456789ab")
        self.assertRegex(result["instance_marker"], r"^[0-9a-f]{12}$")

    def test_three_operations_share_exactly_two_provider_slots(self):
        class TwoSlotStore(_FakeSharedControlStore):
            def __init__(inner_self):
                super().__init__()
                inner_self.leases = {}

            async def acquire_lease(inner_self, operation, slots, now, seconds):
                inner_self._require_available()
                self.assertEqual(slots, 2)
                for slot in range(slots):
                    lease = inner_self.leases.get(slot)
                    if lease is None or lease.expires_at <= now:
                        inner_self.fence += 1
                        lease = Lease(
                            slot, operation, f"owner-{inner_self.fence}",
                            inner_self.fence, now + seconds,
                        )
                        inner_self.leases[slot] = lease
                        inner_self.calls.append(("lease", operation, slot))
                        return lease
                return None

            async def begin_provider(
                inner_self, operation, lease, _dispatch, _model, now,
            ):
                inner_self._require_available()
                if (
                    inner_self.operations.get(operation) != OperationState.CLAIMED
                    or inner_self.leases.get(lease.slot) != lease
                    or lease.expires_at <= now
                ):
                    return False
                inner_self.operations[operation] = OperationState.PROVIDER_STARTED
                inner_self.calls.append(("begin", operation))
                return True

            async def finish_operation(
                inner_self, operation, lease, state, _now,
                *, retention_seconds, **kwargs,
            ):
                inner_self._require_available()
                if (
                    inner_self.leases.get(lease.slot) != lease
                    or inner_self.operations.get(operation)
                    != OperationState.PROVIDER_STARTED
                ):
                    return False
                inner_self.operations[operation] = state
                inner_self.leases.pop(lease.slot, None)
                inner_self.calls.append(("finish", operation, state))
                return True

            async def release_lease(inner_self, lease):
                if inner_self.leases.get(lease.slot) == lease:
                    inner_self.leases.pop(lease.slot, None)
                    return True
                return False

        operation_ids = [
            f"rehearsal_operation_two_slot_{index}_1234567890"
            for index in range(3)
        ]
        store = TwoSlotStore()
        fake = rehearsal.FixedFakeProvider(0.05)
        bodies = [rehearsal._operation_body(value) for value in operation_ids]

        async def run_requests():
            with rehearsal._rehearsal_control_environment(
                "rehearsal-two-slot-test", control_store=store,
            ), rehearsal._fake_provider_runtime(fake):
                return await asyncio.gather(*(
                    rehearsal._signed_asgi_post(body) for body in bodies
                ))

        with mock.patch.dict(os.environ, self.env(), clear=False):
            responses = asyncio.run(run_requests())
        self.assertEqual([response.status_code for response in responses].count(200), 2)
        self.assertEqual([response.status_code for response in responses].count(429), 1)
        self.assertEqual(
            [rehearsal._response_code(response) for response in responses].count(
                "CONCURRENCY_LIMIT"
            ),
            1,
        )
        self.assertEqual(fake.calls, 2)

    def test_rate_mode_counts_signed_invalid_json_without_provider(self):
        store = _FakeSharedControlStore()
        with mock.patch.dict(os.environ, self.env(
            NOTEAI_CLAUDE_GATEWAY_REQUESTS_PER_MINUTE="2",
        ), clear=False):
            result = asyncio.run(rehearsal.execute_rate(
                "rehearsal-rate-test",
                3,
                control_store=store,
            ))
        self.assertEqual(set(result), self.output_fields)
        self.assertEqual(result["status_codes"], [400, 400, 429])
        self.assertEqual(
            result["error_codes"],
            ["INVALID_JSON", "INVALID_JSON", "RATE_LIMIT"],
        )
        self.assertEqual(result["fake_provider_calls"], 0)
        self.assertEqual(len([call for call in store.calls if call[0] == "rate"]), 3)


class ClaudeGatewayPackagingTests(unittest.TestCase):
    def test_blueprints_safe_load_to_one_consistent_staging_gateway_contract(self):
        import yaml

        main = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
        gateway_doc = yaml.safe_load(
            (ROOT / "render.gateway.yaml").read_text(encoding="utf-8")
        )
        api_service = next(
            service for service in main["services"]
            if service.get("name") == "noteai-staging-api"
        )
        self.assertEqual(len(gateway_doc["services"]), 1)
        gateway_service = gateway_doc["services"][0]
        self.assertEqual(gateway_service["name"], "noteai-staging-claude-gateway")
        self.assertEqual(gateway_service["plan"], "starter")
        self.assertEqual(gateway_service["region"], "singapore")

        def env(service):
            return {
                item["key"]: item.get("value")
                for item in service.get("envVars", [])
            }

        api_env = env(api_service)
        gateway_env = env(gateway_service)
        self.assertEqual(api_env["NOTEAI_CLAUDE_TRANSPORT"], "local")
        self.assertEqual(
            api_env["NOTEAI_CLAUDE_GATEWAY_AUTHORITY"],
            gateway_env["NOTEAI_CLAUDE_GATEWAY_AUTHORITY"],
        )
        for key in (
            "NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH",
            "NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH",
        ):
            self.assertEqual(api_env[key], gateway_env[key])
        provider = float(api_env["NOTEAI_CLAUDE_GATEWAY_PROVIDER_DEADLINE_SECONDS"])
        gateway_http = float(api_env["NOTEAI_CLAUDE_GATEWAY_HTTP_TIMEOUT_SECONDS"])
        business = float(api_env["NOTEAI_CLAUDE_GATEWAY_BUSINESS_TIMEOUT_SECONDS"])
        self.assertEqual(
            provider,
            float(gateway_env["NOTEAI_CLAUDE_GATEWAY_PROVIDER_DEADLINE_SECONDS"]),
        )
        self.assertEqual((provider, gateway_http, business), (180.0, 190.0, 210.0))
        self.assertLess(provider, gateway_http)
        self.assertLess(gateway_http, business)
        self.assertEqual(gateway_env["NOTEAI_CLAUDE_GATEWAY_INSTANCE_COUNT"], "2")
        self.assertEqual(gateway_env["WEB_CONCURRENCY"], "1")
        self.assertEqual(gateway_env["NOTEAI_CLAUDE_GATEWAY_CONTROL_MODE"], "dynamodb")
        self.assertEqual(gateway_env["NOTEAI_CLAUDE_GATEWAY_CONCURRENCY"], "2")
        self.assertEqual(gateway_env["NOTEAI_CLAUDE_GATEWAY_REQUESTS_PER_MINUTE"], "30")
        self.assertNotIn("numInstances", gateway_service)
        self.assertEqual(gateway_service["maxShutdownDelaySeconds"], 240)
        self.assertEqual(gateway_service["scaling"], {
            "minInstances": 2,
            "maxInstances": 4,
            "targetCPUPercent": 60,
            "targetMemoryPercent": 70,
        })

        requirements = (ROOT / "model" / "requirements.txt").read_text(encoding="utf-8")
        self.assertEqual(requirements.splitlines().count("httpcore==1.0.9"), 1)

    def test_blueprint_is_one_autoscaling_gateway_service(self):
        blueprint = (ROOT / "render.gateway.yaml").read_text(encoding="utf-8")
        self.assertEqual(blueprint.count("- type:"), 1)
        self.assertIn("name: noteai-staging-claude-gateway", blueprint)
        self.assertIn("region: singapore", blueprint)
        self.assertIn("healthCheckPath: /health/ready", blueprint)
        self.assertIn('NOTEAI_CLAUDE_GATEWAY_INSTANCE_COUNT', blueprint)
        self.assertIn('value: "2"', blueprint)
        self.assertIn("WEB_CONCURRENCY", blueprint)
        self.assertNotIn("numInstances", blueprint)
        self.assertIn("maxShutdownDelaySeconds: 240", blueprint)
        self.assertIn("minInstances: 2", blueprint)
        self.assertIn("maxInstances: 4", blueprint)
        self.assertIn("targetCPUPercent: 60", blueprint)
        self.assertIn("targetMemoryPercent: 70", blueprint)
        self.assertIn(
            "      - key: NOTEAI_CLAUDE_GATEWAY_CONTROL_MODE\n"
            "        value: dynamodb",
            blueprint,
        )
        self.assertNotIn(
            "      - key: NOTEAI_CLAUDE_GATEWAY_CONTROL_MODE\n"
            "        value: memory",
            blueprint,
        )
        self.assertIn("AWS_EC2_METADATA_DISABLED", blueprint)
        self.assertIn("AWS_ROLE_ARN", blueprint)
        self.assertNotIn("AWS_WEB_IDENTITY_TOKEN_FILE", blueprint)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", blueprint)
        self.assertIn("NOTEAI_CLAUDE_GATEWAY_PROVIDER_DEADLINE_SECONDS", blueprint)
        self.assertIn(
            "      - key: NOTEAI_CLAUDE_GATEWAY_AUTHORITY\n"
            "        value: noteai-staging-claude-gateway.onrender.com",
            blueprint,
        )
        self.assertIn("NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH", blueprint)
        self.assertIn("NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH", blueprint)
        self.assertIn(
            "      - key: NOTEAI_CLAUDE_GATEWAY_PROVIDER_DEADLINE_SECONDS\n"
            "        value: \"180\"",
            blueprint,
        )
        self.assertIn(
            "      - key: NOTEAI_CLAUDE_GATEWAY_PREFLIGHT_TIMEOUT_SECONDS\n"
            "        value: \"175\"",
            blueprint,
        )
        self.assertIn("NOTEAI_CLAUDE_GATEWAY_TERMINAL_RETENTION_SECONDS", blueprint)
        self.assertNotIn("NOTEAI_CLAUDE_GATEWAY_OPERATION_TTL_SECONDS", blueprint)
        for forbidden in (
            "DATABASE_URL", "MOONSHOT_API_KEY", "AWS_ACCESS_KEY_ID",
            "NOTEAI_MODEL_ARTIFACT", "type: cron", "databases:", "disk:",
        ):
            self.assertNotIn(forbidden, blueprint)

        staging = (ROOT / "render.yaml").read_text(encoding="utf-8")
        self.assertIn(
            "      - key: NOTEAI_CLAUDE_TRANSPORT\n"
            "        value: local",
            staging,
        )
        self.assertIn("NOTEAI_CLAUDE_GATEWAY_URL", staging)
        self.assertIn("NOTEAI_CLAUDE_GATEWAY_AUTHORITY", staging)
        self.assertIn("NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH", staging)
        self.assertIn("NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH", staging)
        self.assertIn(
            "      - key: NOTEAI_CLAUDE_GATEWAY_HTTP_TIMEOUT_SECONDS\n"
            "        value: \"190\"",
            staging,
        )
        self.assertIn(
            "      - key: NOTEAI_CLAUDE_GATEWAY_PROVIDER_DEADLINE_SECONDS\n"
            "        value: \"180\"",
            staging,
        )
        self.assertIn(
            "      - key: NOTEAI_CLAUDE_GATEWAY_BUSINESS_TIMEOUT_SECONDS\n"
            "        value: \"210\"",
            staging,
        )

    def test_gateway_image_is_minimal_non_root_and_one_worker(self):
        dockerfile = (ROOT / "gateway" / "Dockerfile").read_text(encoding="utf-8")
        start = (ROOT / "gateway" / "start.sh").read_text(encoding="utf-8")
        copy_lines = [line.strip() for line in dockerfile.splitlines() if line.startswith("COPY ")]
        self.assertEqual(copy_lines, [
            "COPY gateway/requirements.txt ./requirements.txt",
            "COPY model/claude_gateway_protocol.py ./claude_gateway_protocol.py",
            "COPY gateway/control_store.py ./control_store.py",
            "COPY gateway/dynamodb_control_store.py ./dynamodb_control_store.py",
            "COPY gateway/claude_gateway.py ./claude_gateway.py",
            "COPY gateway/rehearsal.py ./rehearsal.py",
            "COPY gateway/start.sh ./start.sh",
        ])
        self.assertIn("USER noteai-gateway", dockerfile)
        self.assertIn("--workers 1", start)
        self.assertIn("--no-access-log", start)
        self.assertNotIn("--access-log", start.replace("--no-access-log", ""))
        self.assertNotIn("rehearsal", start.lower())
        for forbidden in ("api.py", "db.py", "billing.py", "artifacts", "render_start_api"):
            self.assertNotIn(forbidden, dockerfile)
        rehearsal_source = (
            ROOT / "gateway" / "rehearsal.py"
        ).read_text(encoding="utf-8")
        for forbidden_import in (
            "import model.db", "from model import db", "import billing", "from model import api",
        ):
            self.assertNotIn(forbidden_import, rehearsal_source)
        self.assertNotIn("NOTEAI_GATEWAY_REHEARSAL_ACK", (
            ROOT / "render.gateway.yaml"
        ).read_text(encoding="utf-8"))
        requirements = (ROOT / "gateway" / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("boto3==1.43.44", requirements)

    def test_documentation_scopes_multi_instance_rehearsal_without_capacity_claims(self):
        guide = (ROOT / "docs" / "CLAUDE_GATEWAY.md").read_text(encoding="utf-8")
        self.assertIn("single-process staging", guide)
        self.assertIn("memory_instance_scope", guide)
        self.assertIn("multi_instance_production_ready: false", guide)
        self.assertIn("shared atomic replay store", guide)
        self.assertIn("CONTROL_PLANE_OUTCOME_UNKNOWN", guide)
        self.assertIn("provider_started", guide.lower())
        self.assertIn("Any existing claim", guide)
        self.assertIn("at-most-once and fail-closed", guide)
        self.assertIn("Boundary D", guide)
        self.assertIn("Boundary E", guide)
        self.assertIn("created=false", guide)
        self.assertIn("TransactionConflict", guide)
        self.assertIn("Staging Blueprint now selects `dynamodb`", guide)
        self.assertIn("shell-only", guide)
        self.assertIn("zero-Claude", guide)
        self.assertIn("2→4→2", guide)
        self.assertIn("Auto Sync = No", guide)
        self.assertIn("Manual Sync", guide)
        self.assertIn("approximately 95% duty cycle", guide)
        self.assertIn("60–600 seconds", guide)
        self.assertIn("5–8 minutes", guide)
        self.assertIn("Do not manually set four instances", guide)
        self.assertIn("does not establish that real Claude", guide)
        self.assertIn("Rolling deploy", guide)
        self.assertIn("Single-instance restart", guide)
        self.assertIn("CONTROL_PLANE_UNAVAILABLE", guide)
        self.assertIn("CONTROL_PLANE_OUTCOME_UNKNOWN", guide)
        self.assertIn("Never open or read", guide)
        self.assertIn("blue/green or a full drain", guide)
        self.assertIn("numInstances: 1", guide)
        self.assertIn("merely omitting `scaling`", guide)
        self.assertIn("Never delete, stop, throttle", guide)
        self.assertIn("24 hours", guide)
        self.assertIn("not a 1,000-user capacity proof", guide)

    def test_aws_control_plane_template_is_retained_least_privilege_and_oidc_only(self):
        import yaml

        template = (
            ROOT / "infra" / "aws" / "claude_gateway_control_plane.yaml"
        ).read_text(encoding="utf-8")
        document = yaml.safe_load(template)
        self.assertIn("AWS::DynamoDB::Table", template)
        self.assertIn("BillingMode: PAY_PER_REQUEST", template)
        self.assertIn("AttributeName: expires_at", template)
        self.assertIn("SSEEnabled: true", template)
        self.assertEqual(template.count("DeletionPolicy: Retain"), 1)
        self.assertIn("ap-southeast-1", template)
        self.assertIn("RenderOIDCSubject", template)
        self.assertIn('AllowedPattern: "^[^*?]+$"', template)
        self.assertIn("sts:AssumeRoleWithWebIdentity", template)
        policies = document["Resources"]["RenderGatewayRole"]["Properties"]["Policies"]
        self.assertEqual(len(policies), 1)
        self.assertEqual(policies[0]["PolicyName"], "claude-gateway-control-table-only")
        statements = policies[0]["PolicyDocument"]["Statement"]
        self.assertEqual(len(statements), 1)
        statement = statements[0]
        self.assertEqual(statement["Effect"], "Allow")
        self.assertEqual(set(statement["Action"]), {
            "dynamodb:DescribeTable",
            "dynamodb:GetItem",
            "dynamodb:PutItem",
            "dynamodb:UpdateItem",
            "dynamodb:DeleteItem",
            "dynamodb:ConditionCheckItem",
        })
        self.assertNotIn("dynamodb:TransactWriteItems", statement["Action"])
        self.assertEqual(statement["Resource"], {
            "Fn::GetAtt": ["ControlTable", "Arn"],
        })
        self.assertNotRegex(template, r"Resource:\s*[\"']?\*[\"']?")
        self.assertNotIn("dynamodb:*", template)
        self.assertNotIn("AWS_ACCESS_KEY_ID", template)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", template)


if __name__ == "__main__":
    unittest.main()
