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


class ClaudeGatewayEndpointTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": "provider-test-key",
            "NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID": "main-test-key",
            "NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET": "test-secret-material",
            "NOTEAI_CLAUDE_GATEWAY_INSTANCE_COUNT": "1",
            "NOTEAI_CLAUDE_GATEWAY_MAX_BODY_BYTES": "8388608",
            "NOTEAI_CLAUDE_GATEWAY_MAX_TOKENS": "16000",
        }, clear=False)
        self.env.start()
        self.original_provider = claude_gateway._PROVIDER
        self.original_nonces = claude_gateway._NONCES
        self.original_limiter = claude_gateway._LIMITER
        self.original_rate_limiter = claude_gateway._RATE_LIMITER
        self.provider = _FakeProvider()
        claude_gateway._PROVIDER = self.provider
        claude_gateway._NONCES = claude_gateway.InMemoryNonceStore()
        claude_gateway._LIMITER = claude_gateway.ConcurrencyLimiter(2)
        claude_gateway._RATE_LIMITER = claude_gateway.InMemoryRateLimiter(1000)
        self.client = TestClient(claude_gateway.app)

    def tearDown(self):
        self.client.close()
        claude_gateway._PROVIDER = self.original_provider
        claude_gateway._NONCES = self.original_nonces
        claude_gateway._LIMITER = self.original_limiter
        claude_gateway._RATE_LIMITER = self.original_rate_limiter
        self.env.stop()

    @staticmethod
    def payload(**updates):
        payload = {
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
            "COPY gateway/claude_gateway.py ./claude_gateway.py",
            "COPY gateway/start.sh ./start.sh",
        ])
        self.assertIn("USER noteai-gateway", dockerfile)
        self.assertIn("--workers 1", start)
        self.assertIn("--no-access-log", start)
        self.assertNotIn("--access-log", start.replace("--no-access-log", ""))
        for forbidden in ("api.py", "db.py", "billing.py", "artifacts", "render_start_api"):
            self.assertNotIn(forbidden, dockerfile)

    def test_documentation_cannot_claim_multi_instance_readiness(self):
        guide = (ROOT / "docs" / "CLAUDE_GATEWAY.md").read_text(encoding="utf-8")
        self.assertIn("single-instance", guide)
        self.assertIn("memory_instance_scope", guide)
        self.assertIn("multi_instance_production_ready: false", guide)
        self.assertIn("shared atomic replay store", guide)


if __name__ == "__main__":
    unittest.main()
