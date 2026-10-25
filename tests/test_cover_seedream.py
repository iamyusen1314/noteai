"""Mock-transport Seedream wire/ledger tests; no real model invocation."""
import base64
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
import uuid
from unittest import mock

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import ark_media
import cover_seedream as seedream
from tests.test_cover_runtime import synthetic_photo


class CoverSeedreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stream = io.BytesIO()
        Image.new("RGB", (1776, 2368), "#AB957A").save(stream, "PNG")
        cls.background = stream.getvalue()

    def setUp(self):
        self.events, self.requests, self.records = [], [], []
        self.call_id = str(uuid.uuid4())
        self.stack = contextlib.ExitStack()
        self.admit = self.stack.enter_context(mock.patch("public_product.model_admission_sync",
            side_effect=lambda cid, provider: self.admission(cid, provider)))
        self.reserve = self.stack.enter_context(mock.patch("public_product._reserve_payload",
            side_effect=lambda *args, **kw: self.events.append(("reserve", args, kw))))
        self.mark = self.stack.enter_context(mock.patch("public_product.mark_model_dispatched",
            side_effect=lambda cid: self.events.append(("dispatch", cid))))
        self.response = self.stack.enter_context(mock.patch("public_product._record_response",
            side_effect=lambda *args, **kw: self.events.append(("response", args, kw))))
        self.stack.enter_context(mock.patch("public_product.assert_result_known"))
        self.stack.enter_context(mock.patch.object(ark_media, "_headers", return_value={"Authorization": "Bearer test-only-not-a-secret"}))

    def tearDown(self):
        self.stack.close()

    @contextlib.contextmanager
    def admission(self, cid, provider):
        self.events.append(("admission", cid, provider))
        yield
        self.events.append(("release", cid))

    def before(self, stage, cid, estimate):
        self.events.append(("before", stage, cid))
        self.assertEqual((stage, cid), ("image", self.call_id))
        self.assertEqual(estimate["estimated_cost"], "0.60")

    def after(self, record):
        self.events.append(("ledger", record["status"]))
        self.records.append(record)

    def success(self, **updates):
        return {"model": seedream.MODEL, "data": [{"b64_json": base64.b64encode(self.background).decode(),
            "size": "1776x2368", "output_format": "png"}],
            "usage": {"generated_images": 1, "input_images": 1}, **updates}

    def generate(self, *, data=None, handler=None, before=None, after=None):
        def transport(request):
            self.requests.append(request)
            if handler:
                return handler(request)
            return httpx.Response(200, json=data if data is not None else self.success(),
                                  headers={"x-request-id": "fixture-request-123"})
        return seedream.generate_background(source_images=[synthetic_photo()],
            prompt="Abstract paper texture, no objects or text", call_id=self.call_id,
            before_call=before or self.before, on_call=after or self.after,
            transport=httpx.MockTransport(transport))

    def test_official_wire_is_pinned_single_output_b64_and_ledger_precedes_release(self):
        output, record = self.generate()
        self.assertEqual(output, self.background)
        self.assertEqual(len(self.requests), 1)
        request = self.requests[0]
        self.assertEqual(str(request.url), seedream.URL)
        payload = json.loads(request.content)
        self.assertEqual(payload["model"], "doubao-seedream-5-0-pro-260628")
        self.assertEqual(payload["size"], "1776x2368")
        self.assertEqual(payload["response_format"], "b64_json")
        self.assertEqual(payload["output_format"], "png")
        self.assertTrue(payload["image"].startswith("data:image/png;base64,"))
        self.assertFalse(set(payload) & {"stream", "sequential_image_generation", "tools", "layer_decomposition", "n"})
        reserved = self.reserve.call_args
        self.assertEqual(reserved.args[0]["provider"], "seedream")
        self.assertEqual(reserved.args[0]["modality"], "image_generation")
        self.assertEqual(reserved.args[1], 600)
        self.assertEqual(self.admit.call_args.args, (self.call_id, "seedream"))
        order = [event[0] for event in self.events]
        self.assertEqual(order, ["admission", "reserve", "before", "dispatch", "ledger", "response", "release"])
        self.assertEqual(record["output_images"], 1)
        self.assertEqual(record["billed_images"], 1)
        self.assertIsNone(record["actual_cost"])
        self.assertEqual(record["cost_status"], "public_estimate")
        self.assertEqual(record["provider_request_id"], "fixture-request-123")
        self.assertEqual(record["billing_count_basis"], "usage.generated_images:official_success_only_tariff")
        self.assertNotIn("b64_json", record)
        self.assertNotIn("prompt", record)

    def test_estimate_uses_output_pixel_tier_and_explicit_extra_references(self):
        self.assertEqual([seedream.estimate(n)["estimated_cost"] for n in (1, 2, 3)], ["0.60", "0.62", "0.64"])
        self.assertEqual(seedream.estimate(9)["estimated_cost"], "0.76")
        for count in (0, 10, True):
            with self.assertRaises(seedream.SeedreamError):
                seedream.estimate(count)

    def test_optional_supplier_input_count_uses_frozen_request_without_claiming_a_bill(self):
        for usage in ({"generated_images": 1}, {"generated_images": 1, "input_images": None}):
            with self.subTest(usage=usage):
                self.requests.clear()
                output, record = self.generate(data=self.success(usage=usage))
                self.assertEqual(output, self.background)
                self.assertEqual(len(self.requests), 1)
                self.assertEqual(record["input_images"], 1)
                self.assertEqual(record["input_images_basis"], "request_payload")
                self.assertIsNone(record["provider_reported_input_images"])
                self.assertEqual(record["pricing_snapshot"]["input_images_basis"], "request_payload")
                self.assertIsNone(record["actual_cost"])
                self.assertEqual(record["status"], "responded")

    def test_wrong_model_missing_usage_wrong_input_count_and_size_are_unknown_no_retry(self):
        cases = [self.success(model="a-different-model"), self.success(usage={}),
                 self.success(usage={"generated_images": 1, "input_images": 2}),
                 self.success(usage={"generated_images": 1, "input_images": True}),
                 self.success(usage={"generated_images": 1, "input_images": "1"}),
                 self.success(data=[{"size": "1024x1024", "b64_json": base64.b64encode(self.background).decode()}])]
        for data in cases:
            with self.subTest(data_keys=list(data)):
                self.requests.clear()
                with self.assertRaises(seedream.SeedreamError) as failure:
                    self.generate(data=data)
                self.assertTrue(failure.exception.outcome_unknown)
                self.assertEqual(len(self.requests), 1)
                self.assertEqual(self.records[-1]["status"], "unknown")
                self.assertTrue(self.response.call_args.kwargs["unknown"])

    def test_supplier_url_is_not_fetched_or_accepted_as_saved_product(self):
        with self.assertRaises(seedream.SeedreamError):
            self.generate(data=self.success(data=[{"url": "https://untrusted.invalid/image.png", "size": "1776x2368"}]))
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0].method, "POST")

    def test_http_denial_is_explicit_failure_without_retry_or_model_fallback(self):
        with self.assertRaises(seedream.SeedreamError) as failure:
            self.generate(handler=lambda request: httpx.Response(403, json={"error": {"code": "AccessDenied"}}))
        self.assertFalse(failure.exception.outcome_unknown)
        self.assertEqual(failure.exception.code, "COVER_SEEDREAM_HTTP_403")
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.records[-1]["status"], "failed")
        self.assertIsNone(self.records[-1]["billed_images"])
        self.assertIsNone(self.records[-1]["actual_cost"])
        self.assertEqual(self.response.call_args.args, (self.call_id, 403))
        self.assertEqual(failure.exception.response_diagnostics["provider_code"], "AccessDenied")

    def test_http_failure_retains_only_whitelisted_response_diagnostics_after_accounting(self):
        sentinel = "PRIVATE-prompt-token-/private/path"
        body = json.dumps({"error": {"code": "InvalidParameter.InvalidValue", "param": "size",
            "message": sentinel, "detail": sentinel, "innererror": {"token": sentinel}},
            "prompt": sentinel}).encode()
        with self.assertRaises(seedream.SeedreamError) as failure:
            self.generate(handler=lambda request: httpx.Response(400, content=body,
                headers={"x-request-id": "fixture-error-400", "private-header": sentinel}))
        error = failure.exception
        self.assertEqual((error.code, error.outcome_unknown, error.call_id),
                         ("COVER_SEEDREAM_HTTP_400", False, self.call_id))
        self.assertEqual(error.response_diagnostics, {"http_status": 400, "body_kind": "json_error",
            "provider_code": "InvalidParameter.InvalidValue", "parameter": "size",
            "provider_request_id": "fixture-error-400", "response_hash": hashlib.sha256(body).hexdigest()})
        self.assertNotIn(sentinel, json.dumps(error.response_diagnostics) + str(error))
        self.assertEqual([event[0] for event in self.events],
            ["admission", "reserve", "before", "dispatch", "ledger", "response"])
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(len(self.records), 1)
        self.assertEqual(self.records[0]["status"], "failed")
        self.assertNotIn("response_diagnostics", self.records[0])
        self.assertIsNone(self.records[0]["actual_cost"])
        self.assertIsNone(self.records[0]["billed_images"])
        self.assertEqual(self.records[0]["cost_status"], "public_estimate")
        self.response.assert_called_once_with(self.call_id, 400)

    def test_http_failure_unknown_malformed_deep_and_large_bodies_degrade_without_content(self):
        sentinel = "PRIVATE-prompt-token-/private/path"
        valid = b'{"error":{"code":"MissingParameter","param":"image"}}'
        cases = [(json.dumps({"error": {"code": sentinel, "param": sentinel, "message": sentinel}}).encode(),
                  "json_error", "OTHER", None),
                 (b'{"error":[]}', "json_other", "OTHER", None),
                 (b'[]', "json_other", "OTHER", None),
                 (b'<html>' + sentinel.encode(), "non_json", "OTHER", None),
                 (b'[' * 1500 + b'0' + b']' * 1500, "non_json", "OTHER", None),
                 (valid + b' ' * (seedream.MAX_ERROR_DIAGNOSTIC_BYTES - len(valid)),
                  "json_error", "MissingParameter", "image"),
                 (valid + b' ' * (seedream.MAX_ERROR_DIAGNOSTIC_BYTES - len(valid) + 1),
                  "too_large", "OTHER", None)]
        for body, kind, code, parameter in cases:
            with self.subTest(kind=kind, size=len(body)):
                self.requests.clear()
                with self.assertRaises(seedream.SeedreamError) as failure:
                    self.generate(handler=lambda request: httpx.Response(400, content=body,
                        headers={"x-request-id": "/not/an/id"}))
                diagnostic = failure.exception.response_diagnostics
                self.assertEqual((diagnostic["body_kind"], diagnostic["provider_code"], diagnostic["parameter"]),
                                 (kind, code, parameter))
                self.assertIsNone(diagnostic["provider_request_id"])
                self.assertEqual(diagnostic["response_hash"], hashlib.sha256(body).hexdigest())
                self.assertNotIn(sentinel, json.dumps(diagnostic))
                self.assertEqual(failure.exception.code, "COVER_SEEDREAM_HTTP_400")
                self.assertFalse(failure.exception.outcome_unknown)
                self.assertEqual(len(self.requests), 1)

    def test_http_failure_diagnostics_validator_is_exact_bounded_and_detached(self):
        value = {"http_status": 400, "body_kind": "json_error", "provider_code": "OTHER",
            "parameter": None, "provider_request_id": None, "response_hash": "a" * 64}
        validated = seedream.validated_http_failure_diagnostics(value)
        self.assertEqual(validated, value)
        self.assertIsNot(validated, value)
        validated["provider_code"] = "AccessDenied"
        self.assertEqual(value["provider_code"], "OTHER")
        cases = [None, [], {**value, "message": "PRIVATE"},
            {key: item for key, item in value.items() if key != "parameter"}]
        for key, values in {"http_status": (True, 200, 99, 600, "400"),
                "body_kind": ("PRIVATE", None, []), "provider_code": ("PRIVATE", None, []),
                "parameter": ("/private/path", False, []),
                "provider_request_id": ("/private/path", "x" * 161, False, []),
                "response_hash": ("A" * 64, "a" * 63, None, [])}.items():
            cases.extend({**value, key: item} for item in values)
        for invalid in cases:
            with self.subTest(invalid_type=type(invalid).__name__):
                self.assertIsNone(seedream.validated_http_failure_diagnostics(invalid))
                self.assertIsNone(seedream.SeedreamError("original", response_diagnostics=invalid).response_diagnostics)

    def test_http_failure_codes_and_wire_parameters_are_exact_allowlists(self):
        for code in seedream._HTTP_FAILURE_PROVIDER_CODES:
            for parameter in seedream._HTTP_FAILURE_PARAMETERS:
                with self.subTest(code=code, parameter=parameter):
                    body = json.dumps({"error": {"code": code, "param": parameter}}).encode()
                    diagnostic = seedream._http_failure_diagnostics(400, body, None, "a" * 64)
                    self.assertEqual(diagnostic["provider_code"], code)
                    self.assertEqual(diagnostic["parameter"], parameter)
                    self.assertEqual(seedream.validated_http_failure_diagnostics(diagnostic), diagnostic)

    def test_optional_diagnostic_failures_do_not_replace_http_failure(self):
        for name in ("_http_failure_diagnostics", "validated_http_failure_diagnostics"):
            with self.subTest(name=name), mock.patch.object(seedream, name,
                    side_effect=RuntimeError("PRIVATE-diagnostic-failure")):
                self.requests.clear()
                with self.assertRaises(seedream.SeedreamError) as failure:
                    self.generate(handler=lambda request: httpx.Response(400, content=b'{}'))
                self.assertEqual(failure.exception.code, "COVER_SEEDREAM_HTTP_400")
                self.assertFalse(failure.exception.outcome_unknown)
                self.assertIsNone(failure.exception.response_diagnostics)
                self.assertEqual(len(self.requests), 1)

    def test_http_failure_accounting_errors_still_preserve_unknown_before_diagnostics(self):
        for stage in ("image_ledger", "public_terminal"):
            with self.subTest(stage=stage):
                self.requests.clear()
                after = mock.Mock(side_effect=RuntimeError("PRIVATE-ledger-failure")) if stage == "image_ledger" else self.after
                response = mock.patch("public_product._record_response", side_effect=RuntimeError("PRIVATE-terminal-failure"))
                with (response if stage == "public_terminal" else contextlib.nullcontext()), \
                        mock.patch.object(seedream, "_http_failure_diagnostics") as diagnostic:
                    with self.assertRaises(seedream.SeedreamError) as failure:
                        self.generate(after=after, handler=lambda request: httpx.Response(400,
                            json={"error": {"code": "InvalidParameter", "param": "image"}}))
                self.assertTrue(failure.exception.outcome_unknown)
                self.assertEqual(failure.exception.code, "COVER_SEEDREAM_OUTCOME_UNKNOWN")
                self.assertIsNone(failure.exception.response_diagnostics)
                self.assertEqual(len(self.requests), 1)
                diagnostic.assert_not_called()

    def test_read_timeout_is_unknown_and_original_call_is_not_reissued(self):
        def fail(request):
            raise httpx.ReadTimeout("fixture", request=request)
        with self.assertRaises(seedream.SeedreamError) as failure:
            self.generate(handler=fail)
        self.assertTrue(failure.exception.outcome_unknown)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.records[-1]["status"], "unknown")
        self.assertTrue(self.response.call_args.kwargs["unknown"])
        self.assertIsNone(failure.exception.response_diagnostics)

    def test_ledger_ack_failure_stops_delivery_and_keeps_unknown(self):
        with self.assertRaises(seedream.SeedreamError) as failure:
            self.generate(after=mock.Mock(side_effect=RuntimeError("fixture-save-failed")))
        self.assertTrue(failure.exception.outcome_unknown)
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(self.response.call_args.kwargs["unknown"])

    def test_intent_failure_prevents_network_dispatch(self):
        with self.assertRaises(seedream.SeedreamError) as failure:
            self.generate(before=mock.Mock(side_effect=RuntimeError("fixture-intent-failed")))
        self.assertFalse(failure.exception.outcome_unknown)
        self.assertEqual(self.requests, [])
        self.mark.assert_not_called()
        self.assertTrue(self.response.call_args.kwargs["not_dispatched"])


if __name__ == "__main__":
    unittest.main()
