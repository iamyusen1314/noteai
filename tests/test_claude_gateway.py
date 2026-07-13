import asyncio
import concurrent.futures
import json
import os
import secrets
import sys
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
from control_store import (
    ControlStoreUnavailable,
    Lease,
    OperationClaim,
    OperationState,
)


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
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": "provider-test-key",
            "NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID": "main-test-key",
            "NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET": "test-secret-material",
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
            body=body,
        )
        unknown_headers = protocol.auth_headers(
            key_id="unknown-key",
            secret="unknown-secret",
            method="POST",
            path=protocol.MESSAGES_PATH,
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
                     claude_gateway.time, "time", side_effect=[100, 110],
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
                     claude_gateway.time, "time", side_effect=[100, 109, 109],
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
        self.assertEqual(uncertain.json()["error"]["code"], "CONTROL_PLANE_OUTCOME_UNKNOWN")
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(
            after.operations["after_fault_operation_1234"],
            OperationState.PROVIDER_STARTED,
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
            path=protocol.MESSAGES_PATH, body=previous_body,
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
                "transport-secret",
                request.method,
                request.url.path,
                request.headers[protocol.HEADER_KEY_ID],
                request.headers[protocol.HEADER_PROTOCOL_VERSION],
                request.headers["content-type"],
                request.headers[protocol.HEADER_TIMESTAMP],
                request.headers[protocol.HEADER_NONCE],
                body,
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
             mock.patch.object(api, "get_model", return_value=object()):
            readiness = model_router.claude_transport_readiness()
            parsed = api._call_claude("prompt")
            api_readiness, status_code = api._readiness_payload()
        self.assertEqual(readiness, {"mode": "gateway", "configured": True, "supported": True})
        self.assertEqual(parsed, ("d", ["t"], "p", "b"))
        self.assertEqual(status_code, 200)
        self.assertTrue(api_readiness["checks"]["ai"]["ok"])
        self.assertEqual(api_readiness["checks"]["ai"]["claude_transport"], "gateway")


class ClaudeGatewayPackagingTests(unittest.TestCase):
    def test_blueprint_is_one_single_instance_gateway_service(self):
        blueprint = (ROOT / "render.gateway.yaml").read_text(encoding="utf-8")
        self.assertEqual(blueprint.count("- type:"), 1)
        self.assertIn("name: noteai-staging-claude-gateway", blueprint)
        self.assertIn("region: singapore", blueprint)
        self.assertIn("healthCheckPath: /health/ready", blueprint)
        self.assertIn('NOTEAI_CLAUDE_GATEWAY_INSTANCE_COUNT', blueprint)
        self.assertIn('value: "1"', blueprint)
        self.assertIn("WEB_CONCURRENCY", blueprint)
        self.assertIn("NOTEAI_CLAUDE_GATEWAY_CONTROL_MODE", blueprint)
        self.assertIn("AWS_EC2_METADATA_DISABLED", blueprint)
        self.assertIn("AWS_ROLE_ARN", blueprint)
        self.assertNotIn("AWS_WEB_IDENTITY_TOKEN_FILE", blueprint)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", blueprint)
        self.assertIn("NOTEAI_CLAUDE_GATEWAY_PROVIDER_DEADLINE_SECONDS", blueprint)
        self.assertIn("NOTEAI_CLAUDE_GATEWAY_TERMINAL_RETENTION_SECONDS", blueprint)
        self.assertNotIn("NOTEAI_CLAUDE_GATEWAY_OPERATION_TTL_SECONDS", blueprint)
        for forbidden in (
            "DATABASE_URL", "MOONSHOT_API_KEY", "AWS_ACCESS_KEY_ID",
            "NOTEAI_MODEL_ARTIFACT", "type: cron", "databases:", "disk:",
        ):
            self.assertNotIn(forbidden, blueprint)

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
            "COPY gateway/start.sh ./start.sh",
        ])
        self.assertIn("USER noteai-gateway", dockerfile)
        self.assertIn("--workers 1", start)
        self.assertIn("--no-access-log", start)
        self.assertNotIn("--access-log", start.replace("--no-access-log", ""))
        for forbidden in ("api.py", "db.py", "billing.py", "artifacts", "render_start_api"):
            self.assertNotIn(forbidden, dockerfile)
        requirements = (ROOT / "gateway" / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("boto3==1.43.44", requirements)

    def test_documentation_cannot_claim_multi_instance_readiness(self):
        guide = (ROOT / "docs" / "CLAUDE_GATEWAY.md").read_text(encoding="utf-8")
        self.assertIn("single-instance", guide)
        self.assertIn("memory_instance_scope", guide)
        self.assertIn("multi_instance_production_ready: false", guide)
        self.assertIn("shared atomic replay store", guide)
        self.assertIn("CONTROL_PLANE_OUTCOME_UNKNOWN", guide)
        self.assertIn("provider_started", guide.lower())

    def test_aws_control_plane_template_is_retained_least_privilege_and_oidc_only(self):
        template = (
            ROOT / "infra" / "aws" / "claude_gateway_control_plane.yaml"
        ).read_text(encoding="utf-8")
        self.assertIn("AWS::DynamoDB::Table", template)
        self.assertIn("BillingMode: PAY_PER_REQUEST", template)
        self.assertIn("AttributeName: expires_at", template)
        self.assertIn("SSEEnabled: true", template)
        self.assertEqual(template.count("DeletionPolicy: Retain"), 1)
        self.assertIn("ap-southeast-1", template)
        self.assertIn("RenderOIDCSubject", template)
        self.assertIn('AllowedPattern: "^[^*?]+$"', template)
        self.assertIn("sts:AssumeRoleWithWebIdentity", template)
        for action in (
            "DescribeTable", "GetItem", "PutItem", "UpdateItem", "DeleteItem",
            "TransactWriteItems",
        ):
            self.assertIn(f"dynamodb:{action}", template)
        self.assertNotRegex(template, r"Resource:\s*[\"']?\*[\"']?")
        self.assertNotIn("dynamodb:*", template)
        self.assertNotIn("AWS_ACCESS_KEY_ID", template)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", template)


if __name__ == "__main__":
    unittest.main()
