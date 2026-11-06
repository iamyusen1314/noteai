"""Offline Haiku 5.5 request adaptation; no supplier, cloud, or production DB."""
import asyncio
import atexit
from contextlib import ExitStack, asynccontextmanager
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import httpx
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT, ROOT / "model", ROOT / "gateway"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
_IMPORT_TEMP = tempfile.TemporaryDirectory(prefix="noteai-haiku55-import-")
atexit.register(_IMPORT_TEMP.cleanup)
with mock.patch("dotenv.load_dotenv", return_value=False), mock.patch.dict(os.environ, {
    "DATABASE_URL": "", "NOTEAI_SQLITE_PATH": str(Path(_IMPORT_TEMP.name) / "private.sqlite"),
    "PYTHON_DOTENV_DISABLED": "1",
}):
    import model_router as router
    import claude_gateway_protocol as protocol
    from gateway import claude_gateway as gateway


USAGE = {"input_tokens": 9, "output_tokens": 3,
         "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


class _WireTransport:
    """Run actual router wire and Gateway parameter validation before replying."""
    def __init__(self):
        self.requests = []
        self.parameters = []

    def capture(self, request):
        self.requests.append(request)
        body = json.loads(router.GatewayClaudeTransport._body(request))
        self.parameters.append(gateway._provider_kwargs(gateway._validate_payload(body)))

    async def create_message(self, request):
        self.capture(request)
        return router.ClaudeMessageResult(("complete",), USAGE, request.model, "end_turn")

    def create_message_sync(self, request):
        self.capture(request)
        return router.ClaudeMessageResult(("complete",), USAGE, request.model, "end_turn")

    async def stream_message(self, request):
        self.capture(request)
        yield router.ClaudeStreamEvent("content", "complete")
        yield router.ClaudeStreamEvent("usage", usage=USAGE,
            model=request.model, stop_reason="end_turn")


class Haiku55TransportTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.temp = tempfile.TemporaryDirectory(prefix="noteai-haiku55-case-")
        self.addCleanup(self.temp.cleanup)
        self.stack.enter_context(mock.patch.dict(os.environ, {
            "DATABASE_URL": "", "NOTEAI_SQLITE_PATH": str(Path(self.temp.name) / "private.sqlite"),
            "NOTEAI_PUBLIC_PRODUCT": "0", "NOTEAI_MODEL_CONFIG_ENABLED": "0",
            "NOTEAI_CLAUDE_TRANSPORT": "local", "PYTHON_DOTENV_DISABLED": "1",
        }))
        self.stack.enter_context(mock.patch("dotenv.load_dotenv", return_value=False))
        self.stack.enter_context(mock.patch.object(socket.socket, "connect",
            side_effect=AssertionError("external network forbidden")))
        self.stack.enter_context(mock.patch.object(socket.socket, "connect_ex",
            side_effect=AssertionError("external network forbidden")))
        self.stack.enter_context(mock.patch.object(router, "_record_claude_usage"))

    def request(self, model=protocol.HAIKU_5_5, *, max_tokens=16000, **options):
        return router.ClaudeMessageRequest(model=model, max_tokens=max_tokens,
            messages=({"role": "user", "content": "unchanged complete source"},),
            system="unchanged system", operation_id="offline_haiku55_operation_123456", **options)

    def test_legacy_wire_and_provider_parameters_remain_exact(self):
        for model in (router.CLAUDE_HAIKU, router.CLAUDE_SONNET):
            for parameters in ({"temperature": 0.7}, {"thinking_budget": 1100}):
                with self.subTest(model=model, parameters=parameters):
                    request = self.request(model, max_tokens=1200, **parameters)
                    expected = {"operation_id": request.operation_id, "model": model,
                        "max_tokens": 1200, "system": request.system,
                        "messages": list(request.messages), "temperature": parameters.get("temperature"),
                        "thinking_budget": parameters.get("thinking_budget")}
                    self.assertEqual(router.GatewayClaudeTransport._body(request),
                        json.dumps(expected, ensure_ascii=False, separators=(",", ":")).encode())
                    provider = {"model": model, "max_tokens": 1200,
                        "messages": list(request.messages), "system": request.system}
                    if "thinking_budget" in parameters:
                        provider["thinking"] = {"type": "enabled", "budget_tokens": 1100}
                    else:
                        provider["temperature"] = 0.7
                    self.assertEqual(router._local_claude_kwargs(request), provider)
                    self.assertEqual(gateway._provider_kwargs(gateway._validate_payload(expected)), provider)

    def test_async_stream_and_sync_use_55_adaptive_with_route_effort(self):
        transport = _WireTransport()
        provenance = {"task": "content_gen", "step": "expert_main"}
        async def run():
            self.assertEqual(await router._call_claude(protocol.HAIKU_5_5, "system", "source",
                thinking=True, max_tokens=16000, provenance=provenance), "complete")
            self.assertEqual([x async for x in router._stream_claude(protocol.HAIKU_5_5,
                "system", "source", thinking=False, max_tokens=2600, provenance=provenance)],
                [("content", "complete")])
        with mock.patch.object(router, "get_claude_transport", return_value=transport), \
                mock.patch.object(router._runtime_config, "resolve_effort", return_value="high") as route:
            asyncio.run(run())
            self.assertEqual(router.call_claude_sync(model=protocol.HAIKU_5_5,
                messages=[{"role": "user", "content": "source"}], max_tokens=4096,
                temperature=0.3, thinking_budget=1024, trace_step="legacy_diagnosis"), "complete")
        self.assertGreaterEqual(route.call_count, 2)
        for request, parameters in zip(transport.requests, transport.parameters):
            self.assertIsNone(request.temperature)
            self.assertIsNone(request.thinking_budget)
            self.assertNotIn("temperature", parameters)
            self.assertNotIn("budget_tokens", parameters["thinking"])
            self.assertEqual(router._local_claude_kwargs(request), parameters)
        self.assertEqual([x["thinking"] for x in transport.parameters],
            [{"type": "adaptive"}, {"type": "disabled"}, {"type": "disabled"}])
        self.assertEqual([x["output_config"]["effort"] for x in transport.parameters],
            ["high", "high", "medium"])
        self.assertEqual([x["max_tokens"] for x in transport.parameters], [16000, 2600, 4096])

    def test_only_exact_semantic_features_gets_disabled_low_and_300_tokens(self):
        transport = _WireTransport()
        with mock.patch.object(router, "get_claude_transport", return_value=transport):
            for model, step, maximum in ((protocol.HAIKU_5_5, "semantic_features", 120),
                    (router.CLAUDE_HAIKU, "semantic_features", 120),
                    (protocol.HAIKU_5_5, "legacy_diagnosis", 5000),
                    (protocol.HAIKU_5_5, "ocr_text_merge", 5000)):
                self.assertEqual(router.call_claude_sync(model=model,
                    messages=[{"role": "user", "content": "source"}], max_tokens=maximum,
                    temperature=0.3, trace_step=step), "complete")
        first, old, diagnosis, ocr = transport.parameters
        self.assertEqual((first["thinking"], first["output_config"], first["max_tokens"]),
            ({"type": "disabled"}, {"effort": "low"}, 300))
        self.assertEqual((old["temperature"], old["max_tokens"]), (0.3, 120))
        self.assertNotIn("thinking", old)
        self.assertNotIn("output_config", old)
        self.assertEqual((diagnosis["thinking"], diagnosis["output_config"], diagnosis["max_tokens"]),
            ({"type": "adaptive"}, {"effort": "medium"}, 5000))
        self.assertEqual((ocr["thinking"], ocr["output_config"], ocr["max_tokens"]),
            ({"type": "adaptive"}, {"effort": "low"}, 5000))
        with mock.patch.object(router._runtime_config, "resolve_effort", return_value="high") as route:
            configured = router._claude_model_options(protocol.HAIKU_5_5,
                {"task": "semantic", "step": "ocr_text_merge"}, max_tokens=5000)
        route.assert_called_once_with("semantic", protocol.HAIKU_5_5)
        self.assertEqual(configured, {"thinking_mode": "adaptive", "effort": "high"})
        for maximum in (120, 700, 2600, 4096, 4097):
            parameters = router._local_claude_kwargs(self.request(max_tokens=maximum))
            self.assertEqual(parameters["max_tokens"], maximum)
            self.assertEqual(parameters["thinking"]["type"], "disabled" if maximum <= 4096 else "adaptive")

    def test_supported_efforts_and_illegal_pairs_fail_before_provider(self):
        for effort in protocol.HAIKU_5_5_EFFORTS:
            request = self.request(effort=effort)
            self.assertEqual(router._local_claude_kwargs(request)["output_config"], {"effort": effort})
            wire = json.loads(router.GatewayClaudeTransport._body(request))
            self.assertEqual(gateway._provider_kwargs(gateway._validate_payload(wire))["output_config"],
                {"effort": effort})
        for effort, mode in (("max", "disabled"), ("xhigh", "disabled"),
                ("invalid", "adaptive"), ([], "adaptive"), ("medium", "enabled"), ("medium", "")):
            with self.subTest(effort=effort, mode=mode):
                with self.assertRaises(router.ClaudeGatewayError) as error:
                    router.GatewayClaudeTransport._body(self.request(effort=effort, thinking_mode=mode))
                self.assertTrue(error.exception.fallback_safe)
                body = {"operation_id": "offline_haiku55_operation_123456", "model": protocol.HAIKU_5_5,
                    "max_tokens": 1200, "messages": [{"role": "user", "content": "source"}],
                    "effort": effort, "thinking_mode": mode}
                with self.assertRaises(gateway.GatewayRejection):
                    gateway._validate_payload(body)
        for mode in ("adaptive", "disabled"):
            for effort in ("low", "medium", "high"):
                self.assertEqual(router._local_claude_kwargs(self.request(effort=effort,
                    thinking_mode=mode))["thinking"], {"type": mode})
        with self.assertRaises(router.ClaudeGatewayError):
            router.GatewayClaudeTransport._body(self.request(router.CLAUDE_HAIKU, effort="medium"))
        with self.assertRaises(router.ClaudeGatewayError):
            router.GatewayClaudeTransport._body(self.request(max_tokens=4096, effort="max"))

    def test_empty_thinking_refusal_and_output_limits_never_deliver_or_replay(self):
        @asynccontextmanager
        async def admission(*args, **kwargs):
            yield
        class FailureTransport(_WireTransport):
            reason = "end_turn"
            async def create_message(self, request):
                self.capture(request)
                # An actual provider can finish its output budget with thinking
                # only. The adapter must not turn absence of text into success.
                return router.ClaudeMessageResult((), USAGE, request.model, self.reason)
            async def stream_message(self, request):
                self.capture(request)
                yield router.ClaudeStreamEvent("thinking", "private")
                yield router.ClaudeStreamEvent("usage", usage=USAGE,
                    model=request.model, stop_reason=self.reason)
        transport = FailureTransport()
        async def run():
            for reason in ("end_turn", "refusal", "max_tokens"):
                transport.reason = reason
                for streaming in (False, True):
                    before = len(transport.requests)
                    with self.assertRaises(router.ClaudeGatewayError):
                        if streaming:
                            _ = [x async for x in router.stream("content_gen", "system", "source",
                                thinking=True, max_tokens=2600)]
                        else:
                            await router.call("content_gen", "system", "source",
                                thinking=True, max_tokens=2600)
                    self.assertEqual(len(transport.requests), before + 1)
                    self.assertEqual(transport.parameters[-1]["thinking"], {"type": "disabled"})
        with mock.patch.object(router._public_product, "enabled", return_value=True), \
                mock.patch.object(router._public_product, "model_admission", side_effect=admission), \
                mock.patch.object(router._runtime_config, "resolve", side_effect=lambda task, model, maximum:
                    (protocol.HAIKU_5_5, maximum)), \
                mock.patch.object(router, "get_claude_transport", return_value=transport), \
                mock.patch.object(router, "_call_kimi", side_effect=AssertionError("no substitute")):
            asyncio.run(run())
        self.assertEqual(len(transport.requests), 6)

    def test_signed_gateway_create_stream_and_prefill_limits_use_real_provider_adapter(self):
        calls = []
        def message(model):
            return SimpleNamespace(model=model, stop_reason="end_turn", usage=SimpleNamespace(**USAGE,
                cache_creation=None), content=[SimpleNamespace(type="thinking", thinking="private"),
                    SimpleNamespace(type="text", text="complete")])
        async def create(**kwargs):
            calls.append(kwargs)
            return message(kwargs["model"])
        class Stream:
            def __init__(self, kwargs):
                self.kwargs = kwargs
            async def __aenter__(self):
                calls.append(self.kwargs)
                return self
            async def __aexit__(self, *args):
                pass
            async def __aiter__(self):
                yield SimpleNamespace(type="content_block_delta",
                    delta=SimpleNamespace(type="thinking_delta", thinking="private"))
                yield SimpleNamespace(type="content_block_delta",
                    delta=SimpleNamespace(type="text_delta", text="complete"))
            async def get_final_message(self):
                return message(self.kwargs["model"])
        provider = gateway.AnthropicProvider()
        provider._client = SimpleNamespace(messages=SimpleNamespace(create=create,
            stream=lambda **kwargs: Stream(kwargs)))
        with mock.patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": "offline-not-a-key",
            "NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID": "offline-key",
            "NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET": "offline-secret",
            "NOTEAI_CLAUDE_GATEWAY_AUTHORITY": "gateway.test",
            "NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH": "offline-config",
            "NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH": "offline-epoch",
            "NOTEAI_CLAUDE_GATEWAY_INSTANCE_COUNT": "1",
            "NOTEAI_CLAUDE_GATEWAY_MAX_BODY_BYTES": "8388608",
            "NOTEAI_CLAUDE_GATEWAY_MAX_TOKENS": "16000",
            "NOTEAI_CLAUDE_GATEWAY_CONTROL_MODE": "memory",
            "NOTEAI_CLAUDE_GATEWAY_CAPACITY_ENABLED": "0",
        }), mock.patch.object(gateway, "_PROVIDER", provider), \
                mock.patch.object(gateway, "_NONCES", gateway.InMemoryNonceStore()), \
                mock.patch.object(gateway, "_LIMITER", gateway.ConcurrencyLimiter(2)), \
                mock.patch.object(gateway, "_RATE_LIMITER", gateway.InMemoryRateLimiter(1000)), \
                mock.patch.object(gateway, "_CONTROL_STORE", None), TestClient(gateway.app) as client:
            def post(path, payload):
                body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
                headers = protocol.auth_headers(key_id="offline-key", secret="offline-secret",
                    method="POST", path=path, authority="gateway.test",
                    config_epoch="offline-config", key_epoch="offline-epoch", body=body)
                return client.post(path, content=body, headers=headers)
            for path in (protocol.MESSAGES_PATH, protocol.STREAM_PATH):
                request = router.ClaudeMessageRequest(model=protocol.HAIKU_5_5, max_tokens=16000,
                    messages=({"role": "user", "content": "complete source"},))
                response = post(path, json.loads(router.GatewayClaudeTransport._body(request)))
                self.assertEqual(response.status_code, 200, response.text)
                self.assertNotIn("private", response.text)
                if path == protocol.MESSAGES_PATH:
                    value = router.GatewayClaudeTransport._decode_result(response)
                    self.assertEqual((value.text_blocks, value.model, value.stop_reason),
                        (("complete",), protocol.HAIKU_5_5, "end_turn"))
                else:
                    values = [json.loads(x) for x in response.text.splitlines()]
                    self.assertEqual([x["type"] for x in values], ["content", "usage", "done"])
                    self.assertEqual(values[1]["usage"], USAGE)
            for bad in ({"temperature": 0.7}, {"thinking_budget": 1024},
                    {"top_p": 0.9}, {"top_k": 5}, {"effort": "max", "thinking_mode": "disabled"},
                    {"messages": [{"role": "assistant", "content": "prefill"}]}):
                request = router.ClaudeMessageRequest(model=protocol.HAIKU_5_5, max_tokens=1200,
                    messages=({"role": "user", "content": "source"},))
                payload = json.loads(router.GatewayClaudeTransport._body(request))
                payload.update(bad)
                self.assertEqual(post(protocol.MESSAGES_PATH, payload).status_code, 422)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(x["thinking"] == {"type": "adaptive"}
            and x["output_config"] == {"effort": "medium"} and "temperature" not in x for x in calls))


if __name__ == "__main__":
    unittest.main()
