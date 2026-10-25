"""Cover-only Pro transport: real local accounting, synthetic HTTP, no network."""
import contextlib
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import unittest
import uuid
from unittest import mock

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import ark_media
import billing
import cover_agent_provider as provider
import cover_jobs
import db
import model_admission
import private_storage
import public_product
from tests import test_cover_jobs as job_fixtures


class CoverAgentProviderTests(unittest.TestCase):
    def setUp(self):
        self.fixture = job_fixtures.CoverJobsTests()
        self.fixture.setUp()
        self.env = mock.patch.dict(os.environ, {"NOTEAI_PUBLIC_PRODUCT": "0",
            "NOTEAI_ARK_API_KEY": "offline-cover-agent-fixture"})
        self.env.start()
        self.no_network = mock.patch("socket.socket.connect", side_effect=AssertionError("External network forbidden"))
        self.no_network.start()
        self.admission = model_admission.Admission(model_admission.Limits(physical=2, seedream=1))
        self.admission_patch = mock.patch.object(model_admission, "current", return_value=self.admission)
        self.admission_patch.start()
        self.original_price = billing._pricing_snapshot
        self.price_patch = mock.patch.object(billing, "_pricing_snapshot", side_effect=self.price)
        self.price_patch.start()
        self.task, self.claim = self.fixture.claim()
        self.invocation = public_product.Invocation(self.fixture.user, self.claim["request_id"],
            route="/covers", budget_id=self.claim["policy_snapshot"]["budget_id"])
        self.invocation_marker = public_product._invocation.set(self.invocation)
        self.usage_marker = billing._ACTIVE_USAGE_ID.set(self.claim["charge"]["usage_id"])
        _, original = private_storage.load_media_bytes(self.fixture.source.id,
            user_id=self.fixture.user, purpose="image")
        self.body = {"model": provider.MODEL, "messages": [
            {"role": "system", "content": "Design only from the supplied real photograph."},
            {"role": "user", "content": [{"type": "text", "text": "真实门店封面"}, ark_media.image_part(original)]}],
            "tools": [{"type": "function", "function": {"name": "read_file",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}}],
            "thinking": {"type": "enabled"}, "max_tokens": 8192, "stream": False}
        self.requests = []

    def tearDown(self):
        billing._ACTIVE_USAGE_ID.reset(self.usage_marker)
        public_product._invocation.reset(self.invocation_marker)
        self.price_patch.stop()
        self.admission_patch.stop()
        self.no_network.stop()
        self.env.stop()
        self.fixture.tearDown()

    def price(self, source, model, *, prompt_tokens=0):
        if source == "doubao" and model == provider.MODEL:
            return {"currency": "RMB", "usd_cny": 7.0, "pricing_status": "exact",
                "price_version": provider.PRICE_VERSION, "cache_write_5m": None,
                "cache_write_1h": None, **provider.pricing(prompt_tokens)}
        return self.original_price(source, model, prompt_tokens=prompt_tokens)

    def intent(self, stage="design"):
        call_id = str(uuid.uuid4())
        cover_jobs.before_text_call(self.claim, stage, call_id)
        return call_id

    def response(self, *, tool=False):
        message = {"role": "assistant", "content": "封面已完成", "reasoning_content": "synthetic private reasoning"}
        if tool:
            message.update(content=None, tool_calls=[{"id": "tool_one", "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":"SKILL.md"}'}}])
        return {"id": "chatcmpl-offline", "model": provider.MODEL, "object": "chat.completion",
            "choices": [{"index": 0, "finish_reason": "tool_calls" if tool else "stop", "message": message}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 30,
                "prompt_tokens_details": {"cached_tokens": 20},
                "completion_tokens_details": {"reasoning_tokens": 15}}}

    def transport(self, body=None, status=200, error=None):
        def respond(request):
            self.requests.append(request)
            if error:
                raise error(request)
            return httpx.Response(status, json=body if body is not None else self.response())
        return httpx.MockTransport(respond)

    def call_row(self, call_id):
        return dict(db.fetchone("SELECT * FROM public_trial_calls WHERE id=?", (call_id,)))

    def model_row(self, call_id):
        return dict(db.fetchone("SELECT m.* FROM model_usage_records m JOIN public_trial_calls c "
            "ON c.model_usage_record_id=m.id WHERE c.id=?", (call_id,)))

    @contextlib.contextmanager
    def editable_claim(self):
        # Multi-round Bridge tests use a normally submitted v3 claim, keeping
        # the original one-design/one-QC fixtures and their evidence unchanged.
        policy = {**self.fixture.policy, "design_version": 3, "max_physical_calls": None,
            "workflow_engine": "editable_design_opencode_v1", "design_model": provider.MODEL}
        task = self.fixture.submit(policy_snapshot=policy, quote_version=cover_jobs.policy_quote_version(policy))
        original, self.claim = self.claim, cover_jobs.claim_job(task["job_id"])
        marker = public_product._invocation.set(public_product.Invocation(self.fixture.user,
            self.claim["request_id"], route="/covers", budget_id=policy["budget_id"]))
        meter = billing._ACTIVE_USAGE_ID.set(self.claim["charge"]["usage_id"])
        try:
            yield
        finally:
            billing._ACTIVE_USAGE_ID.reset(meter)
            public_product._invocation.reset(marker)
            self.claim = original

    def test_full_tool_chat_uses_pro_thinking_and_one_original_metered_call(self):
        call_id = self.intent()
        expected = self.response(tool=True)
        with public_product.model_admission_sync(call_id, "doubao"):
            actual = provider.complete(self.body, call_id=call_id, transport=self.transport(expected))
        self.assertEqual(actual, expected)
        self.assertEqual(len(self.requests), 1)
        payload = json.loads(self.requests[0].content)
        self.assertEqual(payload["model"], provider.MODEL)
        self.assertEqual(payload["thinking"], {"type": "enabled"})
        self.assertEqual(payload["max_completion_tokens"], 8192)
        self.assertNotIn("max_tokens", payload)
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["tools"], self.body["tools"])
        self.assertEqual(payload["messages"][1]["content"][1]["image_url"]["url"],
            self.body["messages"][1]["content"][1]["image_url"]["url"])
        self.assertEqual(self.call_row(call_id)["state"], "responded")
        row = self.model_row(call_id)
        self.assertEqual(row["usage_record_id"], self.claim["charge"]["usage_id"])
        self.assertEqual((row["provider"], row["model"], row["usage_status"], row["pricing_status"]),
            ("doubao", provider.MODEL, "complete", "exact"))
        self.assertAlmostEqual(row["known_cost_rmb"], .001404)
        self.assertNotIn("synthetic private reasoning", json.dumps(self.call_row(call_id)))
        self.assertEqual(self.fixture.balances()[1], 0)  # Only delivery can settle credits.
        self.assertEqual(ark_media.MODEL, "doubao-seed-2-0-lite-260428")

    def test_tool_result_and_reasoning_history_are_returned_and_forwarded_without_flattening(self):
        self.body["messages"].extend([self.response(tool=True)["choices"][0]["message"],
            {"role": "tool", "tool_call_id": "tool_one", "content": "read-only synthetic tool result"}])
        call_id = self.intent()
        self.assertEqual(provider.complete(self.body, call_id=call_id, transport=self.transport()), self.response())
        payload = json.loads(self.requests[0].content)
        self.assertEqual(payload["messages"][-2:], self.body["messages"][-2:])
        self.assertEqual(db.fetchone("SELECT count(*) n FROM model_usage_records")["n"], 1)

    def test_price_gap_stops_before_reservation_or_http(self):
        call_id = self.intent()
        with mock.patch.object(billing, "_pricing_snapshot", return_value={"pricing_status": "unpriced"}):
            with self.assertRaisesRegex(provider.CoverAgentProviderError, "COVER_AGENT_PRICE_UNCONFIRMED"):
                provider.complete(self.body, call_id=call_id, transport=self.transport())
        self.assertFalse(self.requests)
        self.assertIsNone(db.fetchone("SELECT id FROM public_trial_calls WHERE id=?", (call_id,)))

    def test_invalid_input_and_unbounded_remote_image_never_reach_transport(self):
        invalid = []
        for change in ({"stream": True}, {"thinking": {"type": "disabled"}},
                {"max_tokens": provider.MAX_OUTPUT_TOKENS + 1}, {"max_completion_tokens": 8192},
                {"messages": [{"role": "user", "content": "a" * provider.MAX_INPUT_TOKENS}]},
                {"model": ark_media.MODEL}, {"service_tier": "fast"}):
            invalid.append({**deepcopy(self.body), **change})
        remote = deepcopy(self.body)
        remote["messages"][1]["content"][1]["image_url"]["url"] = "https://example.invalid/unknown-size.png"
        invalid.append(remote)
        for body in invalid:
            with self.subTest(keys=sorted(body)):
                with self.assertRaises(provider.CoverAgentProviderError):
                    provider.prepare_payload(body)
        self.assertFalse(self.requests)

    def test_inline_pixel_bounds_are_explicit_and_original_payload_is_detached(self):
        original = deepcopy(self.body)
        prepared, bound = provider.prepare_payload(self.body)
        self.assertEqual(self.body, original)
        image = prepared["messages"][1]["content"][1]["image_url"]
        self.assertEqual(image["image_pixel_limit"], {"min_pixels": 1764, "max_pixels": 1764})
        self.assertLess(bound, provider.MAX_INPUT_TOKENS)
        self.assertEqual(provider.estimate(8192)["estimated_cost"], "1.032192")

    def test_output_request_caps_and_estimate_use_actual_maximum(self):
        for maximum, amount in ((8192, "1.032192"), (32768, "1.769472"), (65536, "2.752512")):
            with self.subTest(maximum=maximum):
                body = deepcopy(self.body)
                body.pop("max_tokens")
                body["max_completion_tokens"] = maximum
                prepared, _ = provider.prepare_payload(body)
                self.assertEqual(prepared["max_completion_tokens"], maximum)
                self.assertEqual(prepared["reasoning_effort"], "high")
                quote = provider.estimate(prepared["max_completion_tokens"])
                self.assertEqual((quote["output_token_bound"], quote["estimated_cost"]), (maximum, amount))
        self.assertEqual(provider.estimate()["output_token_bound"], 65536)
        for maximum in (True, 0, -1, 65537):
            with self.subTest(invalid=maximum):
                with self.assertRaises(ValueError):
                    provider.estimate(maximum)
                body = deepcopy(self.body)
                body["max_tokens"] = maximum
                with self.assertRaisesRegex(provider.CoverAgentProviderError, "OUTPUT_LIMIT_INVALID"):
                    provider.prepare_payload(body)
        self.assertEqual(provider.MAX_INPUT_TOKENS, 131072)
        self.assertFalse(self.requests)

    def test_encrypted_assistant_history_is_exact_and_counts_toward_input_bound(self):
        cipher = "PRIVATE_OPAQUE_原样_+/=="
        assistant = self.response(tool=True)["choices"][0]["message"]
        assistant["encrypted_content"] = cipher
        self.body["messages"].extend([assistant,
            {"role": "tool", "tool_call_id": "tool_one", "content": "synthetic known tool result"}])
        prepared, encrypted_bound = provider.prepare_payload(self.body)
        self.assertEqual(prepared["messages"][-2], assistant)
        plain = deepcopy(self.body)
        plain["messages"][-2].pop("encrypted_content")
        self.assertGreater(encrypted_bound - provider.prepare_payload(plain)[1], len(cipher.encode()))
        call_id = self.intent()
        provider.complete(self.body, call_id=call_id, transport=self.transport())
        self.assertEqual(json.loads(self.requests[0].content)["messages"][-2]["encrypted_content"], cipher)
        self.assertNotIn(cipher, json.dumps(self.call_row(call_id)))
        self.assertEqual(len(self.requests), 1)

    def test_empty_encrypted_assistant_turn_is_restored_exactly_and_metered(self):
        from cover_agent_thinking import ThinkingState

        original = self.response(tool=True)
        assistant = original["choices"][0]["message"]
        assistant["encrypted_content"] = ""
        thinking = ThinkingState(self.claim["request_id"])
        safe = thinking.remember(original)
        self.assertNotIn("encrypted_content", safe["choices"][0]["message"])
        self.body["messages"].extend([safe["choices"][0]["message"], {
            "role": "tool", "tool_call_id": "tool_one", "content": "known tool result"}])
        restored = thinking.restore(self.body)
        self.assertEqual(restored["messages"][-2], assistant)
        self.assertEqual(provider.admit_payload(restored), {"allowed": True})
        prepared, bound = provider.prepare_payload(restored)
        self.assertEqual(prepared["messages"][-2], assistant)
        without_field = deepcopy(restored)
        without_field["messages"][-2].pop("encrypted_content")
        self.assertGreater(bound, provider.prepare_payload(without_field)[1])
        call_id = self.intent()
        provider.complete(restored, call_id=call_id, transport=self.transport())
        self.assertEqual(json.loads(self.requests[0].content)["messages"][-2], assistant)
        self.assertEqual(self.call_row(call_id)["state"], "responded")
        self.assertEqual(len(self.requests), 1)

    def test_encrypted_history_rejects_wrong_role_and_nonstring_values(self):
        for role, cipher in (("assistant", None), ("assistant", {}),
                             ("assistant", 1), ("system", "opaque"), ("user", "opaque"),
                             ("tool", "opaque"), ("system", ""), ("user", ""), ("tool", "")):
            with self.subTest(role=role, cipher_type=type(cipher).__name__):
                message = {"role": role, "content": "known text", "encrypted_content": cipher}
                if role == "tool":
                    message["tool_call_id"] = "tool_one"
                body = {"messages": [message]}
                with self.assertRaisesRegex(provider.CoverAgentProviderError, "ENCRYPTED_HISTORY_INVALID"):
                    provider.prepare_payload(body)
        self.assertFalse(self.requests)

    def test_bridge_hook_cost_snapshot_and_native_reserve_share_actual_output_cap(self):
        with self.editable_claim():
            import cover_agent_runtime
            from types import SimpleNamespace

            hooks = []
            def before(stage, call_id, quote):
                hooks.append(dict(quote))
                cover_jobs.before_text_call(self.claim, stage, call_id)
            bridge = cover_agent_runtime.Bridge(job_id=self.claim["request_id"],
                directory=Path(self.fixture.temp.name), sources=[], hooks=SimpleNamespace(before_call=before),
                model_transport=self.transport())
            reserved = []
            for maximum, expected in ((8192, 1033), (32768, 1770), (65536, 2753)):
                body = deepcopy(self.body)
                body["max_tokens"] = maximum
                _, call_id = bridge.model(body)
                row = self.call_row(call_id)
                reserved.append(row["reserve_milli_cny"])
                self.assertEqual(row["reserve_milli_cny"], expected)
                self.assertEqual(hooks[-1]["output_token_bound"], maximum)
                self.assertEqual(bridge.costs[-1]["output_token_bound"], maximum)
                self.assertEqual(hooks[-1]["estimated_cost"], bridge.costs[-1]["estimated_cost"])
                self.assertEqual(json.loads(self.requests[-1].content)["max_completion_tokens"], maximum)
            self.assertEqual(reserved, [1033, 1770, 2753])
            self.assertEqual(len(self.requests), 3)
            self.assertEqual(self.fixture.balances()[1], 0)

    def test_bridge_keeps_cipher_in_python_and_restores_identical_preflight_and_dispatch(self):
        with self.editable_claim():
            import cover_agent_runtime
            from types import SimpleNamespace

            cipher = "SYNTHETIC_PRIVATE_OPAQUE_中文_" * 7
            original = self.response(tool=True)
            original["choices"][0]["message"]["encrypted_content"] = cipher
            responses = iter([original, self.response()])
            def respond(request):
                self.requests.append(request)
                return httpx.Response(200, json=next(responses))
            hooks = SimpleNamespace(before_call=lambda stage, call_id, quote:
                cover_jobs.before_text_call(self.claim, stage, call_id))
            bridge = cover_agent_runtime.Bridge(job_id=self.claim["request_id"],
                directory=Path(self.fixture.temp.name), sources=[], hooks=hooks,
                model_transport=httpx.MockTransport(respond))
            safe, first_id = bridge.model(self.body)
            self.assertNotIn(cipher, json.dumps(safe, ensure_ascii=False))
            self.assertEqual(original["choices"][0]["message"]["encrypted_content"], cipher)
            next_body = deepcopy(self.body)
            next_body["messages"].extend([safe["choices"][0]["message"], {
                "role": "tool", "tool_call_id": "tool_one", "content": "known successful file read"}])
            untouched = deepcopy(next_body)
            with mock.patch.object(provider, "admit_payload", wraps=provider.admit_payload) as admit:
                self.assertEqual(bridge.preflight(next_body), {"allowed": True})
            preflight = admit.call_args.args[0]
            self.assertEqual(preflight["messages"][-2]["encrypted_content"], cipher)
            safe_second, second_id = bridge.model(next_body)
            dispatched = json.loads(self.requests[-1].content)
            self.assertEqual(provider.prepare_payload(preflight)[0], dispatched)
            self.assertEqual(dispatched["messages"][-2], original["choices"][0]["message"])
            self.assertEqual(next_body, untouched)
            self.assertNotIn(cipher, json.dumps(safe_second, ensure_ascii=False))
            self.assertNotIn(cipher, json.dumps(bridge.costs, ensure_ascii=False))
            self.assertEqual([self.call_row(item)["state"] for item in (first_id, second_id)],
                ["responded", "responded"])
            self.assertEqual(len(self.requests), 2)
            self.assertEqual(bridge.ordinal, 2)

    def test_bridge_thinking_failure_after_response_preserves_native_cost_without_retry(self):
        import cover_agent_runtime
        import cover_runtime
        from types import SimpleNamespace

        hooks = SimpleNamespace(before_call=lambda stage, call_id, quote:
            cover_jobs.before_text_call(self.claim, "design", call_id))
        bridge = cover_agent_runtime.Bridge(job_id=self.claim["request_id"],
            directory=Path(self.fixture.temp.name), sources=[], hooks=hooks,
            model_transport=self.transport())
        with mock.patch.object(bridge.thinking, "remember", side_effect=
                cover_agent_runtime.ThinkingError("COVER_AGENT_THINKING_MEMORY_LIMIT")):
            with self.assertRaisesRegex(cover_runtime.CoverRuntimeError, "COVER_AGENT_THINKING_MEMORY_LIMIT"):
                bridge.model(self.body)
        self.assertEqual(bridge.ordinal, 1)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(len(bridge.costs), 1)
        call_id = bridge.costs[0]["call_id"]
        self.assertEqual(self.call_row(call_id)["state"], "responded")
        self.assertEqual(self.model_row(call_id)["usage_status"], "complete")
        self.assertGreater(self.model_row(call_id)["known_cost_rmb"], 0)
        self.assertEqual(self.fixture.balances()[1], 0)

    def test_stop_at_8192_is_usable_and_not_inferred_to_be_truncated(self):
        response = self.response()
        response["usage"]["completion_tokens"] = 8192
        call_id = self.intent()
        self.assertEqual(provider.complete(self.body, call_id=call_id, transport=self.transport(response)), response)
        self.assertEqual(self.call_row(call_id)["state"], "responded")
        self.assertEqual(self.model_row(call_id)["output_tokens"], 8192)
        self.assertEqual(len(self.requests), 1)

    def test_length_with_partial_tool_arguments_is_known_metered_and_never_returned(self):
        response = self.response(tool=True)
        response["choices"][0]["finish_reason"] = "length"
        response["choices"][0]["message"]["encrypted_content"] = "PRIVATE_RESPONSE_CIPHER"
        response["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = '{"path":"index.html","text":"PARTIAL_PRIVATE'
        response["usage"].update(completion_tokens=8192, completion_tokens_details={"reasoning_tokens": 7000})
        call_id = self.intent()
        with self.assertRaises(provider.CoverAgentProviderError) as caught:
            provider.complete(self.body, call_id=call_id, transport=self.transport(response))
        error = caught.exception
        self.assertEqual(error.code, "COVER_AGENT_OUTPUT_LIMIT_REACHED")
        self.assertFalse(error.outcome_unknown)
        self.assertEqual(error.call_id, call_id)
        self.assertEqual(error.output_diagnostics, {"finish_reason": "length", "completion_tokens": 8192,
            "max_completion_tokens": 8192, "reasoning_tokens": 7000})
        self.assertEqual((self.call_row(call_id)["state"], self.call_row(call_id)["http_status"]), ("responded", 200))
        self.assertEqual(self.model_row(call_id)["output_tokens"], 8192)
        self.assertAlmostEqual(self.model_row(call_id)["known_cost_rmb"], .246264)
        self.assertEqual(len(self.requests), 1)
        self.assertNotIn("PRIVATE", json.dumps(error.output_diagnostics))
        self.assertEqual(self.fixture.balances()[1], 0)

    def test_65536_stop_is_accepted_and_observed_over_cap_is_still_rejected(self):
        body = deepcopy(self.body)
        body["max_tokens"] = provider.MAX_OUTPUT_TOKENS
        response = self.response()
        response["usage"]["completion_tokens"] = provider.MAX_OUTPUT_TOKENS
        call_id = self.intent()
        self.assertEqual(provider.complete(body, call_id=call_id, transport=self.transport(response)), response)
        self.assertEqual(self.call_row(call_id)["reserve_milli_cny"], 2753)
        response["usage"]["completion_tokens"] += 1
        prepared, _ = provider.prepare_payload(body)
        with self.assertRaisesRegex(provider.CoverAgentProviderError, "OBSERVED_LIMIT_EXCEEDED"):
            provider._validate_result(response, prepared, {"usage_status": "complete"})
        self.assertEqual(len(self.requests), 1)

    def test_output_diagnostics_project_only_enum_counts_and_valid_reasoning(self):
        prepared, _ = provider.prepare_payload(self.body)
        for finish, expected in (("length", "length"), ("content_filter", "content_filter"),
                                 ("stop", "stop"), ("tool_calls", "tool_calls"),
                                 ("PRIVATE_UNRECOGNIZED_REASON", "other"), (None, "missing")):
            response = self.response()
            response["choices"][0]["finish_reason"] = finish
            response["usage"]["completion_tokens_details"] = {"reasoning_tokens": 31}
            diagnostic = provider._output_diagnostics(response, prepared)
            self.assertEqual(diagnostic["finish_reason"], expected)
            self.assertIsNone(diagnostic["reasoning_tokens"])
            self.assertNotIn("PRIVATE", json.dumps(diagnostic))
        for reasoning in (True, -1, 31, "30", {}):
            response["usage"]["completion_tokens_details"] = {"reasoning_tokens": reasoning}
            self.assertIsNone(provider._output_diagnostics(response, prepared)["reasoning_tokens"])
        response["usage"]["completion_tokens_details"] = {"reasoning_tokens": 30}
        diagnostic = provider._output_diagnostics(response, prepared)
        self.assertEqual(diagnostic["reasoning_tokens"], 30)
        self.assertIsNone(provider.validated_output_diagnostics({**diagnostic, "raw": "PRIVATE"}))
        self.assertIsNone(provider.validated_output_diagnostics({**diagnostic, "finish_reason": {"raw": "PRIVATE"}}))

    def test_approved_128k_input_bound_keeps_complete_skill_sized_text(self):
        self.body["messages"][0]["content"] = "a" * 35974
        _, bound = provider.prepare_payload(self.body)
        self.assertGreater(bound, 32768)
        self.assertLessEqual(bound, 131072)

    def test_input_measurement_preserves_sum_image_count_and_content_free_rejection(self):
        body = deepcopy(self.body)
        body["messages"][1]["content"].append(deepcopy(body["messages"][1]["content"][1]))
        sentinel = "PRIVATE_TEXT_REASONING_PATH_SENTINEL"
        body["messages"][0]["content"] = sentinel + "a" * provider.MAX_INPUT_TOKENS
        body["messages"].append({"role": "assistant", "content": "", "reasoning_content": sentinel})
        with self.assertRaises(provider.CoverAgentProviderError) as caught:
            provider.prepare_payload(body)
        error = caught.exception
        self.assertEqual(error.code, "COVER_AGENT_INPUT_LIMIT_EXCEEDED")
        self.assertFalse(error.outcome_unknown)
        measurement = error.input_diagnostics
        self.assertEqual(measurement["image_count"], 2)  # Repeated images still consume context.
        self.assertEqual(measurement["image_tokens"], 2 * 257)
        self.assertEqual((measurement["message_count"], measurement["tool_count"]), (3, 1))
        self.assertEqual(measurement["framing_tokens"], 128 * (3 + 1) + 1024)
        self.assertEqual(measurement["total_bound"], measurement["text_bytes"]
            + measurement["image_tokens"] + measurement["framing_tokens"])
        self.assertGreater(measurement["total_bound"], provider.MAX_INPUT_TOKENS)
        self.assertTrue(all(type(value) is int for value in measurement.values()))
        serialized = json.dumps(measurement)
        self.assertNotIn(sentinel, serialized)
        self.assertNotIn("data:image", serialized)
        self.assertIsNone(provider.validated_input_diagnostics({**measurement, "raw": sentinel}))
        self.assertIsNone(provider.validated_input_diagnostics({**measurement, "total_bound": 1}))
        self.assertFalse(self.requests)

    def test_exact_input_boundary_is_unchanged_and_only_overflow_attaches_measurement(self):
        body = {"messages": [{"role": "user", "content": ""}]}
        _, overhead = provider.prepare_payload(body)
        body["messages"][0]["content"] = "a" * (provider.MAX_INPUT_TOKENS - overhead)
        prepared, bound = provider.prepare_payload(body)
        self.assertEqual(bound, provider.MAX_INPUT_TOKENS)
        expected = deepcopy(prepared)
        for message in expected["messages"]:
            self.assertEqual(message["content"], body["messages"][0]["content"])
        body["messages"][0]["content"] += "a"
        with self.assertRaises(provider.CoverAgentProviderError) as caught:
            provider.prepare_payload(body)
        self.assertEqual(caught.exception.input_diagnostics["total_bound"], provider.MAX_INPUT_TOKENS + 1)
        invalid = {"messages": body["messages"], "stream": True}
        with self.assertRaises(provider.CoverAgentProviderError) as rejected:
            provider.prepare_payload(invalid)
        self.assertIsNone(rejected.exception.input_diagnostics)

    def test_incomplete_json_200_remains_unknown_without_fallback_or_retry(self):
        call_id = self.intent()
        def respond(request):
            self.requests.append(request)
            return httpx.Response(200, content=b'{"model":')
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(provider.CoverAgentProviderError) as caught:
                provider.complete(self.body, call_id=call_id, transport=httpx.MockTransport(respond))
        self.assertTrue(caught.exception.outcome_unknown)
        self.assertEqual(self.call_row(call_id)["state"], "unknown")
        self.assertEqual(len(self.requests), 1)

    def test_original_money_guard_blocks_1033_milli_reservation_before_http(self):
        call_id = self.intent()
        db.execute("UPDATE public_trial_budget SET reserved_milli_cny=limit_milli_cny-1032 WHERE id=?",
            (self.claim["policy_snapshot"]["budget_id"],))
        with self.assertRaisesRegex(public_product.TrialProviderStopped, "PUBLIC_TRIAL_BUDGET_EXHAUSTED"):
            provider.complete(self.body, call_id=call_id, transport=self.transport())
        self.assertFalse(self.requests)
        self.assertIsNone(db.fetchone("SELECT id FROM public_trial_calls WHERE id=?", (call_id,)))

    def assert_reservation_failure(self, error, kind, *, sqlite_code=None, os_errno=None):
        call_id = self.intent()
        with mock.patch.object(public_product, "_reserve_payload", side_effect=error) as reserve, \
                mock.patch.object(public_product, "mark_model_dispatched") as dispatched, \
                mock.patch.object(ark_media, "_client") as client:
            with self.assertRaises(provider.CoverAgentProviderError) as caught:
                provider.complete(self.body, call_id=call_id, transport=self.transport())
            failure = caught.exception
            self.assertEqual(failure.code, "COVER_AGENT_RESERVATION_UNCONFIRMED")
            self.assertEqual(str(failure), failure.code)
            self.assertTrue(failure.outcome_unknown)
            self.assertEqual(failure.call_id, call_id)
            self.assertEqual(failure.reservation_diagnostics, {"phase": "reservation",
                "exception_type": kind, "sqlite_errorcode": sqlite_code, "os_errno": os_errno,
                "call_id": call_id, "reserve_milli_cny": 1033})
            self.assertIsNone(failure.input_diagnostics)
            self.assertIsNone(failure.output_diagnostics)
            self.assertNotIn("PRIVATE", json.dumps(failure.reservation_diagnostics))
            self.assertEqual(self.invocation.failure, failure.code)
            self.assertIsNone(db.fetchone("SELECT id FROM public_trial_calls WHERE id=?", (call_id,)))
            self.assertEqual(db.fetchone("SELECT count(*) n FROM model_usage_records")["n"], 0)
            with self.assertRaises(public_product.TrialProviderStopped):
                provider.complete(self.body, call_id=call_id, transport=self.transport())
            self.assertEqual(reserve.call_count, 1)
            dispatched.assert_not_called()
            client.assert_not_called()
        self.assertFalse(self.requests)

    def test_sqlite_reservation_failure_keeps_unknown_and_numeric_diagnostic_without_http(self):
        with sqlite3.connect(":memory:") as connection:
            try:
                connection.execute("SELECT * FROM PRIVATE_MISSING_TABLE")
            except sqlite3.OperationalError as error:
                self.assert_reservation_failure(error, "OperationalError", sqlite_code=sqlite3.SQLITE_ERROR)
            else:
                self.fail("Synthetic missing-table fixture did not fail")

    def test_runtime_reservation_failure_keeps_unknown_without_exception_text(self):
        self.assert_reservation_failure(RuntimeError("PRIVATE_SQL_AND_PAYLOAD"), "RuntimeError")

    def test_os_reservation_failure_keeps_unknown_and_only_numeric_errno(self):
        self.assert_reservation_failure(OSError(28, "PRIVATE_FILE_AND_PAYLOAD"), "OSError", os_errno=28)

    def test_reservation_exception_types_use_real_classes_and_reject_hostile_attributes(self):
        for error, expected in ((sqlite3.IntegrityError("PRIVATE"), "IntegrityError"),
                                (sqlite3.DatabaseError("PRIVATE"), "DatabaseError"),
                                (ValueError("PRIVATE"), "OtherError"),
                                (type("OperationalError", (ValueError,), {})("PRIVATE"), "OtherError")):
            with self.subTest(expected=expected):
                value = provider._reservation_diagnostics(error, "safe-call", 1033)
                self.assertEqual(value["exception_type"], expected)
                self.assertNotIn("PRIVATE", json.dumps(value))
        bad = sqlite3.OperationalError("PRIVATE")
        for value in (True, "PRIVATE", -1, 65536):
            bad.sqlite_errorcode = value
            self.assertIsNone(provider._reservation_diagnostics(bad, "safe-call", 1033))
        class Hostile(sqlite3.OperationalError):
            @property
            def sqlite_errorcode(self):
                raise RuntimeError("PRIVATE_ATTRIBUTE_FAILURE")
        self.assertIsNone(provider._reservation_diagnostics(Hostile("PRIVATE"), "safe-call", 1033))

    def test_reservation_diagnostic_validator_is_exact_bounded_and_detached(self):
        value = {"phase": "reservation", "exception_type": "RuntimeError", "sqlite_errorcode": None,
            "os_errno": None, "call_id": "safe-call_1", "reserve_milli_cny": 1033}
        projected = provider.validated_reservation_diagnostics(value)
        self.assertEqual(projected, value)
        self.assertIsNot(projected, value)
        value["call_id"] = "changed"
        self.assertEqual(projected["call_id"], "safe-call_1")
        for change in ({"phase": "PRIVATE"}, {"exception_type": "PRIVATE"},
                       {"call_id": "../PRIVATE"}, {"call_id": 1}, {"reserve_milli_cny": True},
                       {"reserve_milli_cny": -1}, {"reserve_milli_cny": 10**9 + 1},
                       {"sqlite_errorcode": True}, {"sqlite_errorcode": "PRIVATE"},
                       {"sqlite_errorcode": 65536}, {"os_errno": -1}, {"os_errno": []},
                       {"raw_message": "PRIVATE_SQL_AND_PAYLOAD"}):
            with self.subTest(change=change):
                self.assertIsNone(provider.validated_reservation_diagnostics({**projected, **change}))
        self.assertIsNone(provider.validated_reservation_diagnostics({"phase": "reservation"}))
        for reserve in (0, 10**9):
            self.assertIsNotNone(provider.validated_reservation_diagnostics({**projected,
                "reserve_milli_cny": reserve, "sqlite_errorcode": 65535, "os_errno": 0}))

    def test_optional_reservation_diagnostic_failure_never_masks_unknown_stop(self):
        call_id = self.intent()
        with mock.patch.object(public_product, "_reserve_payload", side_effect=RuntimeError("PRIVATE")), \
                mock.patch.object(provider, "validated_reservation_diagnostics", side_effect=RuntimeError("PRIVATE")), \
                mock.patch.object(ark_media, "_client") as client:
            with self.assertRaises(provider.CoverAgentProviderError) as caught:
                provider.complete(self.body, call_id=call_id, transport=self.transport())
        self.assertEqual(caught.exception.code, "COVER_AGENT_RESERVATION_UNCONFIRMED")
        self.assertTrue(caught.exception.outcome_unknown)
        self.assertIsNone(caught.exception.reservation_diagnostics)
        self.assertIsNone(db.fetchone("SELECT id FROM public_trial_calls WHERE id=?", (call_id,)))
        client.assert_not_called()
        self.assertFalse(self.requests)

    def test_known_trial_reservation_stop_is_not_reclassified(self):
        def stopped(*_args, **_kwargs):
            raise public_product.TrialProviderStopped("FIXED_POLICY_STOP")
        with mock.patch.object(public_product, "_reserve_payload", side_effect=stopped) as reserve:
            with self.assertRaises(public_product.TrialProviderStopped) as caught:
                provider.complete(self.body, call_id=self.intent(), transport=self.transport())
        self.assertIs(type(caught.exception), public_product.TrialProviderStopped)
        self.assertEqual(str(caught.exception), "FIXED_POLICY_STOP")
        self.assertFalse(hasattr(caught.exception, "reservation_diagnostics"))
        self.assertEqual(reserve.call_count, 1)
        self.assertFalse(self.requests)

    def test_slot_reservation_stop_keeps_known_unreconciled_semantics(self):
        with mock.patch.object(public_product, "_reserve_payload", side_effect=public_product._SlotsBusy()):
            with self.assertRaises(provider.CoverAgentProviderError) as caught:
                provider.complete(self.body, call_id=self.intent(), transport=self.transport())
        self.assertEqual(caught.exception.code, "MODEL_ADMISSION_UNRECONCILED")
        self.assertFalse(caught.exception.outcome_unknown)
        self.assertIsNone(caught.exception.reservation_diagnostics)
        self.assertFalse(self.requests)

    def test_known_http_denial_does_not_fake_usage_or_retry(self):
        call_id = self.intent()
        with self.assertRaises(provider.CoverAgentProviderError) as caught:
            provider.complete(self.body, call_id=call_id, transport=self.transport(status=403))
        self.assertFalse(caught.exception.outcome_unknown)
        self.assertEqual((self.call_row(call_id)["state"], self.call_row(call_id)["http_status"]), ("responded", 403))
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(db.fetchone("SELECT count(*) n FROM model_usage_records")["n"], 0)

    def test_unknown_wire_outcome_keeps_original_call_and_blocks_next_dispatch(self):
        call_id = self.intent()
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            with self.assertRaises(provider.CoverAgentProviderError) as caught:
                provider.complete(self.body, call_id=call_id, transport=self.transport(
                    error=lambda req: httpx.ReadTimeout("never log request contents", request=req)))
        self.assertTrue(caught.exception.outcome_unknown)
        self.assertEqual(caught.exception.call_id, call_id)
        self.assertEqual(self.call_row(call_id)["state"], "unknown")
        with self.assertRaises(public_product.TrialProviderStopped):
            provider.complete(self.body, call_id=str(uuid.uuid4()), transport=self.transport())
        self.assertEqual(len(self.requests), 1)
        self.assertNotIn("never log request contents", errors.getvalue())
        self.assertNotIn("offline-cover-agent-fixture", errors.getvalue())

    def test_cover_read_timeout_is_separate_from_shared_media_default(self):
        call_id = self.intent()
        provider.complete(self.body, call_id=call_id, transport=self.transport())
        self.assertEqual(self.requests[0].extensions["timeout"],
            {"connect": 10, "read": 900, "write": 90, "pool": 10})
        with ark_media._client(transport=self.transport()) as client:
            self.assertEqual(client.timeout.as_dict(),
                {"connect": 10, "read": 240, "write": 90, "pool": 10})

    def test_host_and_original_job_deadlines_both_bound_request_wait(self):
        now = time.time()
        db.execute("UPDATE cover_jobs SET deadline_at=? WHERE id=?",
            (datetime.fromtimestamp(now + 400, timezone.utc).isoformat(), self.claim["request_id"]))
        with mock.patch.object(provider.time, "time", return_value=now):
            provider.complete(self.body, call_id=self.intent(), transport=self.transport(), deadline=now + 500)
            provider.complete(self.body, call_id=self.intent("qc"), transport=self.transport(), deadline=now + 300)
        self.assertAlmostEqual(self.requests[0].extensions["timeout"]["read"], 260, places=5)
        self.assertAlmostEqual(self.requests[1].extensions["timeout"]["read"], 160, places=5)

    def test_short_or_invalid_host_deadline_never_reserves_or_sends(self):
        call_id = self.intent()
        for deadline in (time.time() + 139, float("inf"), True, "late"):
            with self.subTest(deadline=deadline), \
                    mock.patch.object(public_product, "_reserve_payload") as reserve, \
                    mock.patch.object(public_product, "mark_model_dispatched") as dispatched:
                with self.assertRaisesRegex(provider.CoverAgentProviderError, "COVER_AGENT_TASK_DEADLINE"):
                    provider.complete(self.body, call_id=call_id, transport=self.transport(), deadline=deadline)
                reserve.assert_not_called()
                dispatched.assert_not_called()
        self.assertFalse(self.requests)
        self.assertIsNone(db.fetchone("SELECT id FROM public_trial_calls WHERE id=?", (call_id,)))

    def test_shared_queue_wait_rechecks_deadline_before_reserving(self):
        now = time.time()
        clock = [now]
        @contextlib.contextmanager
        def delayed_permit(*args):
            clock[0] += 301
            yield
        with mock.patch.object(provider.time, "time", side_effect=lambda: clock[0]), \
                mock.patch.object(public_product, "model_admission_sync", side_effect=delayed_permit), \
                mock.patch.object(public_product, "_reserve_payload") as reserve:
            with self.assertRaisesRegex(provider.CoverAgentProviderError, "COVER_AGENT_TASK_DEADLINE"):
                provider.complete(self.body, call_id=self.intent(), transport=self.transport(), deadline=now + 400)
        reserve.assert_not_called()
        self.assertFalse(self.requests)

    def test_proven_pre_send_pool_failure_is_known_but_never_retried(self):
        call_id = self.intent()
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(provider.CoverAgentProviderError) as caught:
                provider.complete(self.body, call_id=call_id, transport=self.transport(
                    error=lambda req: httpx.PoolTimeout("synthetic pool wait", request=req)))
        self.assertFalse(caught.exception.outcome_unknown)
        self.assertEqual(self.call_row(call_id)["state"], "responded")
        self.assertIsNone(self.call_row(call_id)["http_status"])
        self.assertEqual(len(self.requests), 1)

    def test_missing_cache_dimension_is_not_assumed_zero_or_delivered(self):
        call_id = self.intent()
        response = self.response()
        response["usage"].pop("prompt_tokens_details")
        with self.assertRaisesRegex(provider.CoverAgentProviderError, "COVER_AGENT_USAGE_INCOMPLETE"):
            provider.complete(self.body, call_id=call_id, transport=self.transport(response))
        row = self.model_row(call_id)
        self.assertEqual(row["usage_status"], "usage_incomplete")
        self.assertEqual(row["unclassified_input_tokens"], 100)
        self.assertEqual(self.call_row(call_id)["state"], "responded")
        self.assertEqual(len(self.requests), 1)

    def test_usage_is_kept_before_model_mismatch_truncation_and_unknown_tool_rejection(self):
        cases = ["model", "length", "tool", "fallback", "bound"]
        # Independent original jobs keep this test from resetting a failed
        # Invocation or admitting a successor to an unknown paid request.
        for case in cases:
            with self.subTest(case=case):
                task = self.fixture.submit(key="provider-rejection-" + case)
                claim = cover_jobs.claim_job(task["job_id"])
                marker = public_product._invocation.set(public_product.Invocation(self.fixture.user,
                    claim["request_id"], route="/covers", budget_id=claim["policy_snapshot"]["budget_id"]))
                meter = billing._ACTIVE_USAGE_ID.set(claim["charge"]["usage_id"])
                try:
                    call_id = str(uuid.uuid4())
                    cover_jobs.before_text_call(claim, "design", call_id)
                    response = self.response(tool=case == "tool")
                    if case == "model":
                        response["model"] = ark_media.MODEL
                    elif case == "length":
                        response["choices"][0]["finish_reason"] = "length"
                    elif case == "tool":
                        response["choices"][0]["message"]["tool_calls"][0]["function"]["name"] = "undeclared_tool"
                    elif case == "fallback":
                        response["service_status"] = {"model_fallback": {"fallback_triggered": True}}
                    else:
                        response["usage"]["completion_tokens"] = 8193
                    with self.assertRaises(provider.CoverAgentProviderError) as caught:
                        provider.complete(self.body, call_id=call_id, transport=self.transport(response))
                    self.assertFalse(caught.exception.outcome_unknown)
                    self.assertEqual(self.call_row(call_id)["state"], "responded")
                    self.assertIsNotNone(self.call_row(call_id)["model_usage_record_id"])
                finally:
                    billing._ACTIVE_USAGE_ID.reset(meter)
                    public_product._invocation.reset(marker)
        self.assertEqual(len(self.requests), len(cases))
        self.assertEqual(self.fixture.balances()[1], 0)

    def test_local_usage_failure_keeps_known_http_and_unknown_accounting_without_replay(self):
        call_id = self.intent()
        with mock.patch.object(billing, "record_model_usage", side_effect=RuntimeError("synthetic local ledger failure")):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(provider.CoverAgentProviderError) as caught:
                    provider.complete(self.body, call_id=call_id, transport=self.transport())
        self.assertTrue(caught.exception.outcome_unknown)
        row = self.call_row(call_id)
        self.assertEqual((row["state"], row["http_status"], row["model_usage_record_id"]), ("responded", 200, None))
        with self.assertRaises(public_product.TrialProviderStopped):
            provider.complete(self.body, call_id=str(uuid.uuid4()), transport=self.transport())
        self.assertEqual(len(self.requests), 1)

    def test_duplicate_physical_id_never_resends_or_adds_another_reservation(self):
        call_id = self.intent()
        provider.complete(self.body, call_id=call_id, transport=self.transport())
        before = db.fetchone("SELECT reserved_milli_cny FROM public_trial_budget WHERE id=?",
            (self.claim["policy_snapshot"]["budget_id"],))["reserved_milli_cny"]
        with self.assertRaises(provider.CoverAgentProviderError):
            provider.complete(self.body, call_id=call_id, transport=self.transport())
        after = db.fetchone("SELECT reserved_milli_cny FROM public_trial_budget WHERE id=?",
            (self.claim["policy_snapshot"]["budget_id"],))["reserved_milli_cny"]
        self.assertEqual(after, before)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(db.fetchone("SELECT count(*) n FROM model_usage_records")["n"], 1)

    def test_original_cover_context_is_required(self):
        self.invocation.route = "/generate"
        with self.assertRaisesRegex(provider.CoverAgentProviderError, "COVER_AGENT_ORIGINAL_CONTEXT_REQUIRED"):
            provider.complete(self.body, call_id=str(uuid.uuid4()), transport=self.transport())
        self.assertFalse(self.requests)


class PureInputDiagnosticTests(unittest.TestCase):
    def test_text_partition_is_exact_private_and_distinguishes_post_summary_growth(self):
        from cover_agent_thinking import ThinkingState

        # This fixture uses the wire shape after one SDK summary, not a live
        # SDK/session/provider run. Only the real in-memory restore and meter run.
        with mock.patch("sqlite3.connect", side_effect=AssertionError("No diagnostic DB")), \
                mock.patch("socket.socket.connect", side_effect=AssertionError("No diagnostic network")), \
                mock.patch.object(provider, "complete", side_effect=AssertionError("No diagnostic model")):
            size = lambda value: len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())
            body = {"model": provider.MODEL, "stream": False, "messages": [
                {"role": "system", "content": '固定系统 "引号"\n反斜杠\\'},
                {"role": "developer", "content": [{"type": "text", "text": "真实素材约束"}]},
                {"role": "user", "content": [{"type": "text", "text": "真实照片与标题"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "A" * 10000}}]},
                {"role": "assistant", "content": "排字完成\n保留原照",
                    "reasoning_content": "R" * 97, "encrypted_content": "Q" * 113,
                    "tool_calls": [{"id": "synthetic_partition", "type": "function", "function": {
                        "name": "cover_write", "arguments": json.dumps({"path": "poster.html",
                            "text": '<div title="真实">汤泉\\\n</div>'}, ensure_ascii=False)}}]},
                {"role": "tool", "tool_call_id": "synthetic_partition", "content": "已保存\n原照不变"}],
                "tools": [{"type": "function", "function": {"name": "cover_write",
                    "description": '保存 "真实" 封面', "parameters": {"type": "object"}}}]}
            original = deepcopy(body)
            measured = deepcopy(body)
            measured["messages"][2]["content"][1]["image_url"]["url"] = ""
            full_text_bytes = size(measured)
            measurement = provider._measure_input(body, 512, 1)
            breakdown = measurement["text_breakdown"]
            expected = {
                "system_content_bytes": sum(size(message["content"]) for message in measured["messages"][:2]),
                "user_content_bytes": size(measured["messages"][2]["content"]),
                "assistant_content_bytes": size(measured["messages"][3]["content"]),
                "reasoning_content_bytes": size(measured["messages"][3]["reasoning_content"]),
                "encrypted_content_bytes": size(measured["messages"][3]["encrypted_content"]),
                "tool_arguments_bytes": size(measured["messages"][3]["tool_calls"][0]["function"]["arguments"]),
                "tool_result_bytes": size(measured["messages"][4]["content"]),
                "tool_schema_bytes": size(measured["tools"]),
            }
            expected["other_json_bytes"] = full_text_bytes - sum(expected.values())
            self.assertEqual(breakdown, expected)
            self.assertEqual(sum(breakdown.values()), measurement["text_bytes"])
            self.assertEqual(measurement["text_bytes"], full_text_bytes)
            legacy = {key: value for key, value in measurement.items() if key != "text_breakdown"}
            self.assertEqual(legacy, {"text_bytes": full_text_bytes, "image_count": 1, "image_tokens": 512,
                "message_count": 5, "tool_count": 1, "framing_tokens": 1792,
                "total_bound": full_text_bytes + 512 + 1792, "max_input_tokens": 131072})
            self.assertEqual(provider.validated_input_diagnostics(legacy), legacy)
            self.assertEqual(provider.validated_input_diagnostics(measurement), measurement)
            self.assertTrue(body == original)
            other_image = deepcopy(body)
            other_image["messages"][2]["content"][1]["image_url"]["url"] = "data:image/png;base64," + "B" * 20000
            self.assertEqual(provider._measure_input(other_image, 512, 1), measurement)
            diagnostic = json.dumps(measurement, ensure_ascii=False)
            self.assertTrue(all(value not in diagnostic for value in (
                body["messages"][3]["reasoning_content"], body["messages"][3]["encrypted_content"],
                body["messages"][2]["content"][1]["image_url"]["url"])))

            malformed = [None, [], {**breakdown, "unexpected": 0},
                {key: value for key, value in breakdown.items() if key != "other_json_bytes"}]
            for value in (-1, True, 1.0, 2**63, breakdown["other_json_bytes"] + 1):
                malformed.append({**breakdown, "other_json_bytes": value})
            for invalid in malformed:
                self.assertEqual(provider.validated_input_diagnostics({**legacy, "text_breakdown": invalid}), legacy)
            self.assertIsNone(provider.validated_input_diagnostics({**measurement, "total_bound": 0}))
            overflow = {"messages": [{"role": "user", "content": "X" * 150000}]}
            original_stop = provider.admit_payload(overflow)
            original_stop["measurement"].pop("text_breakdown")
            with mock.patch.object(provider, "_text_breakdown", side_effect=RuntimeError("synthetic attribution failure")):
                self.assertEqual(provider._measure_input(body, 512, 1), legacy)
                self.assertEqual(provider.admit_payload({"messages": [{"role": "user", "content": "short"}]}),
                    {"allowed": True})
                self.assertEqual(provider.admit_payload(overflow), original_stop)
                with self.assertRaises(provider.CoverAgentProviderError) as caught:
                    provider.prepare_payload(overflow)
                self.assertEqual(caught.exception.code, "COVER_AGENT_INPUT_LIMIT_EXCEEDED")
                self.assertEqual(caught.exception.input_diagnostics, original_stop["measurement"])

            summary = "## Objective\nPreserve real photos.\n## Work State\nContinue the saved design."
            self.partition_examples = []
            for mode in ("opaque", "visible"):
                state = ThinkingState("synthetic_partition_" + mode)
                state.remember({"choices": [{"message": {"role": "assistant", "content": "old turn",
                    "encrypted_content": "P" * 40000}}]})
                after_summary = {"model": provider.MODEL, "messages": [
                    {"role": "system", "content": "Fixed cover Skill and original task."},
                    {"role": "user", "content": summary}], "tools": [], "stream": False}
                fresh = provider._measure_input(state.restore(after_summary), 0, 0)
                self.assertEqual(fresh["text_breakdown"]["encrypted_content_bytes"], 0)
                self.assertEqual(state.entry_count, 1)  # Retained old RAM is not automatically re-injected.
                for index in range(2):
                    identifier = "synthetic_" + mode + "_" + str(index)
                    response = {"choices": [{"message": {"role": "assistant", "content": None,
                        "tool_calls": [{"id": identifier, "type": "function", "function": {
                            "name": "cover_write", "arguments": json.dumps({"path": "poster.html",
                                "text": "V" * (35000 if mode == "visible" else 16)})}}],
                        "encrypted_content": "C" * (70000 if mode == "opaque" else 32)}}]}
                    safe = state.remember(response)
                    after_summary["messages"].extend([safe["choices"][0]["message"],
                        {"role": "tool", "tool_call_id": identifier,
                            "content": "T" * (35000 if mode == "visible" else 16)}])
                sdk_visible = provider._measure_input(after_summary, 0, 0)
                restored = provider._measure_input(state.restore(after_summary), 0, 0)
                self.assertEqual(sum(restored["text_breakdown"].values()), restored["text_bytes"])
                self.assertGreater(restored["total_bound"], provider.MAX_INPUT_TOKENS)
                if mode == "opaque":
                    self.assertLess(sdk_visible["total_bound"], provider.MAX_INPUT_TOKENS)
                    self.assertGreater(restored["text_breakdown"]["encrypted_content_bytes"], 131072)
                else:
                    self.assertGreater(sdk_visible["total_bound"], provider.MAX_INPUT_TOKENS)
                    self.assertLess(restored["text_breakdown"]["encrypted_content_bytes"], 100)
                    self.assertGreater(restored["text_breakdown"]["tool_arguments_bytes"]
                        + restored["text_breakdown"]["tool_result_bytes"], 131072)
                self.partition_examples.append({"mode": mode, "sdk_visible": sdk_visible, "restored": restored})


if __name__ == "__main__":
    unittest.main()
