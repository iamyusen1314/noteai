"""Cover-only Pro transport: real local accounting, synthetic HTTP, no network."""
import contextlib
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sys
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
                {"max_tokens": 8193}, {"max_completion_tokens": 8192},
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
        self.assertEqual(provider.estimate()["estimated_cost"], "1.032192")

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


if __name__ == "__main__":
    unittest.main()
