"""Mock-transport Seedream wire/ledger tests; no real model invocation."""
import base64
import contextlib
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
        for count in (0, 4, True):
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

    def test_read_timeout_is_unknown_and_original_call_is_not_reissued(self):
        def fail(request):
            raise httpx.ReadTimeout("fixture", request=request)
        with self.assertRaises(seedream.SeedreamError) as failure:
            self.generate(handler=fail)
        self.assertTrue(failure.exception.outcome_unknown)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.records[-1]["status"], "unknown")
        self.assertTrue(self.response.call_args.kwargs["unknown"])

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
