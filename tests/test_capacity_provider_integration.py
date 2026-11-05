"""Real provider adapters/SQLite quota ledger with synthetic HTTP; no network."""
import base64
import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import time
import unittest
import uuid
from unittest import mock

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import ark_media as ark
import billing
import cover_agent_provider as pro
import cover_jobs
import cover_seedream as seedream
import db
import model_admission
import model_capacity
import public_product
from tests import test_ark_media as lite_fixtures
from tests import test_cover_agent_provider as pro_fixtures


def photo(*, quality=90):
    image = Image.linear_gradient("L").resize((800, 900)).convert("RGB")
    output = io.BytesIO()
    image.save(output, "JPEG", quality=quality)
    return output.getvalue()


def lite_response():
    return {"model": ark.MODEL, "choices": [{"finish_reason": "stop",
        "message": {"content": "合成照片中的明暗与主体可供技术验证。"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 10,
                  "prompt_tokens_details": {"cached_tokens": 0}}}


class LiteCapacityMeasurementTests(unittest.TestCase):
    def payload(self, original):
        return {"model": ark.MODEL, "messages": [{"role": "user", "content": [
            ark.image_part(original), {"type": "text", "text": "逐图完整理解"}]}],
            "max_tokens": 4096, "stream": False}

    def test_geometry_and_detail_bound_excludes_base64_and_preserves_wire(self):
        first, second = self.payload(photo(quality=10)), self.payload(photo(quality=98))
        self.assertNotEqual(len(json.dumps(first)), len(json.dumps(second)))
        before = deepcopy(first)
        one, basis = ark._capacity_input_bound(first, audio_possible=False)
        two, _ = ark._capacity_input_bound(second, audio_possible=False)
        self.assertEqual(first, before)
        self.assertEqual(one, two)
        self.assertEqual(basis, "inline_pixels_utf8_bound")
        self.assertTrue(1280 + 256 < one < 8192)
        high = deepcopy(first)
        high["messages"][0]["content"][0]["image_url"]["image_pixel_limit"] = {
            "min_pixels": 1764, "max_pixels": 1764}
        reduced, _ = ark._capacity_input_bound(high, audio_possible=False)
        self.assertLess(reduced, one)  # Existing explicit wire pixel limit wins.

    def test_opaque_video_uses_explicit_context_bound_without_fetching(self):
        payload = {"model": ark.MODEL, "input": [{"role": "user", "content": [
            {"type": "input_video", "file_id": "file-original"},
            {"type": "input_text", "text": "原音轨与画面"}]}]}
        before = deepcopy(payload)
        self.assertEqual(ark._capacity_input_bound(payload, audio_possible=True),
                         (262144, "video_context_upper_bound"))
        self.assertEqual(payload, before)
        image = {"messages": [{"role": "user", "content": [{"type": "image_url",
            "image_url": {"url": "https://example.invalid/original.jpg", "detail": "xhigh"}}]}]}
        bound, basis = ark._capacity_input_bound(image, audio_possible=False)
        self.assertEqual(basis, "opaque_image_max_pixels_bound")
        self.assertTrue(5120 + 256 < bound < 8192)


class LiteCapacityIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.dict(__import__("os").environ, {
            "NOTEAI_MODEL_CAPACITY_ENABLED": "1", "NOTEAI_ARK_API_KEY": "offline-capacity-fixture",
            "NOTEAI_MODEL_CAPACITY_LIMITS_JSON": ""}))
        self.fixture = lite_fixtures.ArkVideoAdmissionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.manager = model_admission.Admission()
        self.stack.enter_context(mock.patch.object(model_admission, "current", return_value=self.manager))
        self.stack.enter_context(mock.patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")))
        self.requests = []

    def call(self, *, error=False):
        def respond(request):
            self.requests.append(request)
            if error:
                raise httpx.ReadTimeout("synthetic unknown response", request=request)
            return httpx.Response(200, json=lite_response())
        return ark.chat("真实原图技术检查", [ark.image_part(photo())],
            transport=httpx.MockTransport(respond))

    def buckets(self):
        return [dict(row) for row in db.fetchall("SELECT * FROM model_capacity_buckets")]

    def test_quota_deferral_waits_outside_transaction_and_dispatches_once(self):
        self.stack.enter_context(mock.patch.dict(__import__("os").environ, {
            "NOTEAI_MODEL_CAPACITY_LIMITS_JSON": json.dumps({ark.MODEL: {
                "rpm": 1, "evidence_ref": "synthetic-one-minute-fixture"}})}))
        clock = [time.time()]
        def now(_tx, _now=None):
            return clock[0]
        self.stack.enter_context(mock.patch.object(model_capacity, "_database_now", side_effect=now))
        self.stack.enter_context(mock.patch.object(public_product.time, "time", side_effect=lambda: clock[0]))
        with db.transaction(write=True) as tx:
            model_capacity.reserve_in_transaction(tx, model_capacity.Demand(ark.MODEL, 1, 1),
                                                  call_id="synthetic-quota-existing")
        before = db.fetchone("SELECT reserved_milli_cny FROM public_trial_budget WHERE id=?",
                             (public_product.BUDGET_ID,))[0]
        waits = []
        operation = public_product._admission_operation()
        def wait(_seconds):
            waits.append(_seconds)
            self.assertEqual(self.requests, [])
            self.assertEqual(db.fetchone("SELECT COUNT(*) FROM public_trial_calls")[0], 0)
            self.assertEqual(db.fetchone("SELECT reserved_milli_cny FROM public_trial_budget WHERE id=?",
                                         (public_product.BUDGET_ID,))[0], before)
            with db.transaction(write=True) as tx:
                self.assertIsNotNone(tx.fetchone("SELECT id FROM public_trial_budget LIMIT 1"))
            clock[0] += 62
        with mock.patch.object(operation.cancelled, "wait", side_effect=wait):
            result = self.call()
        self.assertTrue(waits)
        self.assertIn("合成照片", result)
        self.assertEqual(len(self.requests), 1)
        wire = json.loads(self.requests[0].content)
        self.assertNotIn("_capacity_demand", json.dumps(wire))
        row = dict(db.fetchone("SELECT * FROM public_trial_calls"))
        trace = json.loads(row["provenance_json"])
        self.assertEqual((row["state"], row["http_status"]), ("responded", 200))
        self.assertEqual(trace["capacity"]["estimate_basis"], "inline_pixels_utf8_bound")
        self.assertLess(sum(bucket["token_bound"] for bucket in self.buckets()), 262144)
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM model_usage_records")[0], 1)
        self.assertEqual(db.fetchone("SELECT credits_used FROM usage_records")[0], 0)
        self.assertEqual(self.manager.calls.active, {})

    def test_unknown_retains_quota_and_original_request_never_replays(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(public_product.TrialProviderStopped):
                self.call(error=True)
        rows = self.buckets()
        self.assertEqual(sum(row["request_count"] for row in rows), 1)
        self.assertEqual(db.fetchone("SELECT state FROM public_trial_calls")[0], "unknown")
        with self.assertRaises(public_product.TrialProviderStopped):
            self.call()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.buckets(), rows)
        self.assertEqual(db.fetchone("SELECT credits_used FROM usage_records")[0], 0)

    def test_disabled_mode_skips_measurement_and_keeps_original_metering(self):
        with mock.patch.dict(__import__("os").environ, {"NOTEAI_MODEL_CAPACITY_ENABLED": "0"}), \
                mock.patch.object(ark, "_capacity_input_bound", side_effect=AssertionError("new measurement disabled")):
            self.assertIn("合成照片", self.call())
        self.assertEqual(self.buckets(), [])
        row = db.fetchone("SELECT state,http_status,provenance_json FROM public_trial_calls")
        self.assertEqual(tuple(row)[:2], ("responded", 200))
        self.assertNotIn("capacity", json.loads(row["provenance_json"]))
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM model_usage_records")[0], 1)


class CoverCapacityIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.dict(__import__("os").environ, {
            "NOTEAI_MODEL_CAPACITY_ENABLED": "1", "NOTEAI_MODEL_CAPACITY_LIMITS_JSON": ""}))
        self.fixture = pro_fixtures.CoverAgentProviderTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def test_pro_actual_prepared_bound_nested_ticket_and_unique_accounting(self):
        prepared, bound = pro.prepare_payload(self.fixture.body)
        call_id = self.fixture.intent()
        before = self.fixture.fixture.balances()
        with public_product.model_admission_sync(call_id, "doubao", model_id=pro.MODEL) as ticket:
            pro.complete(self.fixture.body, call_id=call_id, transport=self.fixture.transport())
            self.assertFalse(ticket.closed)
        self.assertEqual(len(self.fixture.requests), 1)
        self.assertEqual(json.loads(self.fixture.requests[0].content), prepared)
        row = db.fetchone("SELECT request_count,token_bound,image_count FROM model_capacity_buckets")
        self.assertEqual(tuple(row), (1, bound + prepared["max_completion_tokens"], 0))
        self.assertLess(bound, pro.MAX_INPUT_TOKENS)
        self.assertEqual(self.fixture.fixture.balances(), before)
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM model_usage_records")[0], 1)
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM public_trial_calls")[0], 1)
        self.assertEqual(self.fixture.admission.calls.active, {})
        self.assertNotIn("synthetic private reasoning", self.fixture.call_row(call_id)["provenance_json"])

    def test_pro_quota_wait_rechecks_useful_read_window_before_wire(self):
        self.stack.enter_context(mock.patch.dict(__import__("os").environ, {
            "NOTEAI_MODEL_CAPACITY_LIMITS_JSON": json.dumps({pro.MODEL: {
                "rpm": 1, "evidence_ref": "synthetic-pro-rate-fixture"}})}))
        clock = [time.time()]
        self.stack.enter_context(mock.patch.object(model_capacity, "_database_now", side_effect=lambda *_args: clock[0]))
        self.stack.enter_context(mock.patch.object(public_product.time, "time", side_effect=lambda: clock[0]))
        with db.transaction(write=True) as tx:
            model_capacity.reserve_in_transaction(tx, model_capacity.Demand(pro.MODEL, 1, 1),
                                                  call_id="synthetic-pro-existing")
        call_id = self.fixture.intent()
        deadline = clock[0] + 400
        waits = []
        operation = public_product._admission_operation()
        def wait(_seconds):
            waits.append(_seconds)
            self.assertEqual(self.fixture.requests, [])
            self.assertIsNone(db.fetchone("SELECT id FROM public_trial_calls WHERE id=?", (call_id,)))
            with db.transaction(write=True) as tx:
                self.assertIsNotNone(tx.fetchone("SELECT id FROM public_trial_budget LIMIT 1"))
            clock[0] += 62
        with mock.patch.object(operation.cancelled, "wait", side_effect=wait):
            pro.complete(self.fixture.body, call_id=call_id,
                         transport=self.fixture.transport(), deadline=deadline)
        self.assertTrue(waits)
        self.assertEqual(len(self.fixture.requests), 1)
        self.assertEqual(self.fixture.requests[0].extensions["timeout"]["read"], 198)
        self.assertEqual(self.fixture.call_row(call_id)["state"], "responded")

    def test_pro_late_after_quota_reservation_is_known_not_dispatched(self):
        clock = [time.time()]
        self.stack.enter_context(mock.patch.object(public_product.time, "time", side_effect=lambda: clock[0]))
        original = public_product.reserve_payload_with_capacity
        def delayed(*args, **kwargs):
            result = original(*args, **kwargs)
            clock[0] += 100
            return result
        call_id = self.fixture.intent()
        with mock.patch.object(public_product, "reserve_payload_with_capacity", side_effect=delayed), \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(pro.CoverAgentProviderError) as caught:
                pro.complete(self.fixture.body, call_id=call_id,
                             transport=self.fixture.transport(), deadline=clock[0] + 400)
        self.assertFalse(caught.exception.outcome_unknown)
        self.assertEqual(self.fixture.requests, [])
        row = self.fixture.call_row(call_id)
        self.assertEqual((row["state"], row["http_status"]), ("responded", None))
        self.assertIsNone(row["model_usage_record_id"])
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM model_usage_records")[0], 0)

    def image_hooks(self):
        def before(stage, call_id, estimate):
            self.assertEqual(stage, "image")
            cover_jobs.begin_image_call(self.fixture.claim, call_id=call_id,
                **{key: estimate[key] for key in ("provider", "model_id", "input_images", "width", "height",
                    "pricing_snapshot", "estimated_cost", "currency", "price_version")})
        def after(record):
            cover_jobs.finish_image_call(self.fixture.claim, record["call_id"],
                **{key: record[key] for key in ("status", "output_images", "billed_images", "actual_cost",
                    "response_hash", "http_status", "provider_request_id") if key in record})
        return before, after

    def test_seedream_counts_one_output_image_and_keeps_original_image_ledger(self):
        background = io.BytesIO()
        Image.new("RGB", (seedream.WIDTH, seedream.HEIGHT), "#778899").save(background, "PNG")
        calls = []
        def respond(request):
            calls.append(request)
            return httpx.Response(200, json={"model": seedream.MODEL,
                "data": [{"b64_json": base64.b64encode(background.getvalue()).decode(),
                          "size": f"{seedream.WIDTH}x{seedream.HEIGHT}"}],
                "usage": {"generated_images": 1, "input_images": 2}})
        before, after = self.image_hooks()
        result, record = seedream.generate_background(source_images=[photo(quality=20), photo(quality=80)],
            prompt="合成技术原照一致性", call_id=str(uuid.uuid4()), before_call=before, on_call=after,
            transport=httpx.MockTransport(respond), deadline=time.time() + 400)
        self.assertEqual(result, background.getvalue())
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(json.loads(calls[0].content)["image"]), 2)
        row = db.fetchone("SELECT request_count,token_bound,image_count FROM model_capacity_buckets")
        self.assertEqual(tuple(row), (1, 0, 1))
        self.assertEqual((record["input_images"], record["billed_images"]), (2, 1))
        image = db.fetchone("SELECT state,input_images,billed_images FROM cover_image_usage")
        self.assertEqual(tuple(image), ("responded", 2, 1))
        self.assertEqual(db.fetchone("SELECT credits_used FROM usage_records WHERE id=?",
            (self.fixture.claim["charge"]["usage_id"],))[0], 0)

    def test_seedream_short_window_stops_before_intent_http_or_money_reserve(self):
        self.stack.enter_context(mock.patch.dict(__import__("os").environ, {
            "NOTEAI_MODEL_CAPACITY_LIMITS_JSON": json.dumps({seedream.MODEL: {
                "ipm": 1, "evidence_ref": "synthetic-image-rate-fixture"}})}))
        clock = [time.time()]
        self.stack.enter_context(mock.patch.object(model_capacity, "_database_now", side_effect=lambda *_args: clock[0]))
        self.stack.enter_context(mock.patch.object(public_product.time, "time", side_effect=lambda: clock[0]))
        with db.transaction(write=True) as tx:
            model_capacity.reserve_in_transaction(tx, model_capacity.Demand(seedream.MODEL, 0, 0, images=1),
                                                  call_id="synthetic-existing-image")
        before, after, http = mock.Mock(), mock.Mock(), mock.Mock()
        operation = public_product._admission_operation()
        def wait(_seconds):
            clock[0] += 2
        with mock.patch.object(operation.cancelled, "wait", side_effect=wait):
            with self.assertRaisesRegex(seedream.SeedreamError, "COVER_SEEDREAM_TASK_DEADLINE"):
                seedream.generate_background(source_images=[photo()], prompt="合成技术",
                    call_id=str(uuid.uuid4()), before_call=before, on_call=after,
                    transport=httpx.MockTransport(http), deadline=clock[0] + 1)
        before.assert_not_called(); after.assert_not_called(); http.assert_not_called()
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM public_trial_calls")[0], 0)
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM cover_image_usage")[0], 0)
        self.assertEqual(sum(row[0] for row in db.fetchall("SELECT reserved_milli_cny FROM public_trial_budget")), 0)

    def test_seedream_quota_wait_exhausting_useful_window_finishes_known_without_http_or_charge(self):
        self.stack.enter_context(mock.patch.dict(__import__("os").environ, {
            "NOTEAI_MODEL_CAPACITY_LIMITS_JSON": json.dumps({seedream.MODEL: {
                "ipm": 1, "evidence_ref": "synthetic-image-window-fixture"}})}))
        clock = [time.time()]
        self.stack.enter_context(mock.patch.object(model_capacity, "_database_now", side_effect=lambda *_args: clock[0]))
        self.stack.enter_context(mock.patch.object(public_product.time, "time", side_effect=lambda: clock[0]))
        with db.transaction(write=True) as tx:
            model_capacity.reserve_in_transaction(tx, model_capacity.Demand(seedream.MODEL, 0, 0, images=1),
                                                  call_id="synthetic-existing-image-window")
        deadline = clock[0] + 400
        original = public_product.reserve_payload_with_capacity
        def quota_then_local_delay(*args, **kwargs):
            self.assertEqual(kwargs["deadline"], deadline - 320)
            value = original(*args, **kwargs)
            clock[0] += 30  # Known local time after the unique physical reserve.
            return value
        waits, http = [], mock.Mock()
        operation = public_product._admission_operation()
        def wait(_seconds):
            waits.append(_seconds)
            self.assertEqual(db.fetchone("SELECT COUNT(*) FROM public_trial_calls")[0], 0)
            with db.transaction(write=True) as tx:
                self.assertIsNotNone(tx.fetchone("SELECT id FROM public_trial_budget LIMIT 1"))
            clock[0] += 62
        before, after = mock.Mock(), mock.Mock()
        call_id = str(uuid.uuid4())
        balances = self.fixture.fixture.balances()
        with mock.patch.object(operation.cancelled, "wait", side_effect=wait), \
                mock.patch.object(public_product, "reserve_payload_with_capacity", side_effect=quota_then_local_delay):
            with self.assertRaises(seedream.SeedreamError) as caught:
                seedream.generate_background(source_images=[photo()], prompt="合成技术尾窗",
                    call_id=call_id, before_call=before, on_call=after,
                    transport=httpx.MockTransport(http), deadline=deadline)
        self.assertTrue(waits)
        self.assertEqual((caught.exception.code, caught.exception.outcome_unknown),
                         ("COVER_SEEDREAM_TASK_DEADLINE", False))
        self.assertEqual(caught.exception.call_id, call_id)
        before.assert_not_called(); after.assert_not_called(); http.assert_not_called()
        row = self.fixture.call_row(call_id)
        self.assertEqual((row["state"], row["http_status"]), ("responded", None))
        self.assertIsNone(row["model_usage_record_id"])
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM public_trial_calls")[0], 1)
        self.assertEqual(db.fetchone("SELECT COUNT(*) FROM cover_image_usage")[0], 0)
        self.assertEqual(sum(r[0] for r in db.fetchall("SELECT image_count FROM model_capacity_buckets")), 2)
        cover_jobs.fail_job(self.fixture.claim, failure_code=caught.exception.code, outcome_unknown=False)
        parent = db.fetchone("SELECT status,refund_applied,complete_applied FROM idempotency_requests WHERE id=?",
                             (self.fixture.claim["request_id"],))
        self.assertEqual(tuple(parent), ("failed", 1, 0))
        self.assertEqual(self.fixture.fixture.balances(), balances)
        self.assertEqual(db.fetchone("SELECT credits_used FROM usage_records WHERE id=?",
            (self.fixture.claim["charge"]["usage_id"],))[0], 0)


if __name__ == "__main__":
    unittest.main()
