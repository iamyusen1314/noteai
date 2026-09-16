"""Offline adapter -> scheduler -> launcher evidence boundary regressions."""
import asyncio
import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "model"), str(ROOT / "tools")]
import security_redaction as safe
import scheduler_a
import spider_xhs_http as xhs
import market_timing_worker
import execute_item32_readonly_trends_successor as launcher

AT = "2026-09-16T02:30:00.000001+00:00"
PRIVATE = "PRIVATE_COOKIE_VALUE_DO_NOT_RECORD"


def observation(phase="response", kind="homefeed", sequence=3):
    return {"phase": phase, "request_kind": kind, "sequence": sequence, "at": AT,
            "response_diagnostics": {"http_status": 200, "business_code": -100,
                                     "business_code_kind": "integer",
                                     "message_tags": ["login", PRIVATE], "body": PRIVATE},
            "headers": {"cookie": PRIVATE}, "url": "https://private.invalid/" + PRIVATE}


class SafeProviderEvidenceTests(unittest.TestCase):
    def receipt(self, lines):
        raw = "\n".join(json.dumps(line) for line in lines).encode()
        binding = dict(launcher.RUNTIME_OVERLAY_SHA256)
        binding["model/security_redaction.py"] = hashlib.sha256(
            (ROOT / "model/security_redaction.py").read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            launcher, "RUNTIME_OVERLAY_SHA256", binding
        ):
            launcher._record_worker_receipt(Path(directory), raw, exit_code=1, secret_values=[])
            return json.loads((Path(directory) / "worker-receipt.json").read_bytes())

    def test_trends_projection_does_not_widen_tracking_or_copy_raw_fields(self):
        value = observation(sequence=36)
        self.assertEqual(safe.sanitize_xhs_http_event(value), {})
        projected = safe.sanitize_trends_http_event(value)
        self.assertEqual(projected["sequence"], 36)
        self.assertEqual(projected["response_diagnostics"]["business_code"], -100)
        self.assertNotIn(PRIVATE, json.dumps(projected))
        self.assertNotIn("url", projected)
        for changes in ({"sequence": 37}, {"sequence": True}, {"request_kind": "detail"},
                        {"request_kind": []}, {"phase": {}}, {"at": "2026-99-99T02:00+00:00"},
                        {"at": "2026-09-16T02:30:00+08:00"}):
            with self.subTest(changes=changes):
                self.assertEqual(safe.sanitize_trends_http_event({**value, **changes}), {})

    def test_failure_projection_preserves_numeric_codes_without_inferring_cause(self):
        meta = safe.xhs_response_diagnostics(200, {"code": "-100", "success": False,
              "msg": PRIVATE, "data": {"code": -3, "message": "verification required " + PRIVATE}})
        failure = safe.sanitize_trends_failure({"stage": "homefeed", "error_code": "remote_business_error",
                                               "response_diagnostics": meta, "exception": PRIVATE})
        self.assertEqual(failure["response_diagnostics"]["business_code"], "-100")
        self.assertEqual(failure["response_diagnostics"]["nested_business_code"], -3)
        self.assertEqual(failure["error_code"], "remote_business_error")
        self.assertNotIn(PRIVATE, json.dumps(failure))
        hostile = safe.sanitize_trends_failure({"stage": PRIVATE, "error_code": PRIVATE,
                 "response_diagnostics": {"business_code": PRIVATE, "http_status": True}})
        self.assertEqual(hostile, {"stage": "preflight", "error_code": "adapter_failure_unknown",
                                  "response_diagnostics": {}})

    def test_scheduler_failure_and_physical_events_survive_launcher(self):
        calls = []
        class Adapter:
            def homefeed(self, **unused):
                calls.append("homefeed")
                for sequence, kind in enumerate(("dsl", "session", "homefeed"), 1):
                    for phase in ("dispatch", "response"):
                        self.http_observer(observation(phase, kind, sequence))
                raise xhs.XHSAdapterError("remote_business_error", diagnostics=observation()["response_diagnostics"])
            def close(self):
                calls.append("close")
        output = io.StringIO()
        with mock.patch.object(xhs, "SpiderXHSHTTPAdapter", Adapter), contextlib.redirect_stdout(output):
            result = asyncio.run(scheduler_a.scrape_once_http())
        self.assertEqual(calls, ["homefeed", "close"])
        self.assertEqual(list(result), [])
        discovery = scheduler_a.discovery_diagnostics_for_results(result, result.diagnostics)
        self.assertEqual(discovery["provider_failure"]["stage"], "homefeed")
        self.assertEqual(discovery["provider_failure"]["response_diagnostics"]["business_code"], -100)
        self.assertNotIn(PRIVATE, output.getvalue())
        receipt = self.receipt([json.loads(line) for line in output.getvalue().splitlines()])
        self.assertEqual(receipt["provider_failures"], [discovery["provider_failure"]])
        summary = receipt["physical_http_summary"]
        self.assertEqual(summary["initialization_dispatches_observed"], 2)
        self.assertEqual(summary["collection_dispatches_observed"], 1)
        self.assertEqual(summary["response_events_observed"], 3)
        self.assertTrue(summary["observation_complete"])

    def test_initialization_failure_keeps_actual_stage_and_stops_without_search(self):
        calls = []
        class Adapter:
            def homefeed(self, **unused):
                calls.append("homefeed")
                self.http_observer(observation("dispatch", "dsl", 1))
                self.http_observer(observation("unknown", "dsl", 1))
                raise xhs.XHSAdapterError("network_error")
            def close(self):
                calls.append("close")
        output = io.StringIO()
        with mock.patch.object(xhs, "SpiderXHSHTTPAdapter", Adapter), contextlib.redirect_stdout(output):
            result = asyncio.run(scheduler_a.scrape_once_http())
        self.assertEqual(calls, ["homefeed", "close"])
        self.assertEqual(result.diagnostics["provider_failure"], {
            "stage": "dsl", "error_code": "network_error", "response_diagnostics": {}})
        receipt = self.receipt([json.loads(line) for line in output.getvalue().splitlines()])
        self.assertEqual(receipt["physical_http_summary"]["unknown_events_observed"], 1)
        self.assertEqual(receipt["physical_http_summary"]["collection_dispatches_observed"], 0)

    def test_local_signing_failure_uses_explicit_stage_not_previous_http(self):
        class Adapter:
            def homefeed(self, **unused):
                self.http_observer(observation("dispatch", "dsl", 1))
                self.http_observer(observation("response", "dsl", 1))
                failure = xhs.XHSAdapterError("signer_failed")
                failure.stage = "session"
                raise failure
            def close(self):
                pass
        output = io.StringIO()
        with mock.patch.object(xhs, "SpiderXHSHTTPAdapter", Adapter), contextlib.redirect_stdout(output):
            result = asyncio.run(scheduler_a.scrape_once_http())
        self.assertEqual(result.diagnostics["provider_failure"]["stage"], "session")
        self.assertEqual(result.diagnostics["provider_failure"]["response_diagnostics"], {})
        receipt = self.receipt([json.loads(line) for line in output.getvalue().splitlines()])
        self.assertEqual(receipt["physical_http_summary"]["initialization_dispatches_observed"], 1)
        self.assertEqual(receipt["provider_failures"][0]["stage"], "session")

    def test_real_adapter_business_error_reaches_receipt_without_raw_response(self):
        requests = []
        def handle(request):
            requests.append(request)
            return httpx.Response(200, json={"success": False, "code": -3000, "msg": PRIVATE})
        class Signer:
            def sign(self, **unused):
                return {"xs": "synthetic", "xt": "1", "xs_common": "synthetic"}
        credentials = xhs.SessionCredentials.from_records([
            {"name": "a1", "value": PRIVATE}, {"name": "web_session", "value": PRIVATE}])
        output = io.StringIO()
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            adapter = xhs.SpiderXHSHTTPAdapter(credentials=credentials, signer=Signer(), client=client)
            with mock.patch.object(xhs, "SpiderXHSHTTPAdapter", return_value=adapter), \
                 mock.patch.object(xhs, "_assert_collection_allowed"), \
                 mock.patch.dict(os.environ, {"NOTEAI_RUNTIME_ROLE": "xhs-http", "NOTEAI_XHS_SERVICE": "",
                     "NOTEAI_XHS_ACQUISITION_ADAPTER": "spider_xhs_http", "NOTEAI_XHS_PROTOCOL": ""}), \
                 contextlib.redirect_stdout(output):
                result = asyncio.run(scheduler_a.scrape_once_http())
        self.assertEqual(len(requests), 1)
        self.assertEqual(result.diagnostics["provider_failure"]["response_diagnostics"]["business_code"], -3000)
        self.assertNotIn(PRIVATE, output.getvalue())
        receipt = self.receipt([json.loads(line) for line in output.getvalue().splitlines()])
        self.assertEqual(receipt["provider_failures"][0]["response_diagnostics"]["http_status"], 200)
        self.assertEqual(receipt["provider_failures"][0]["error_code"], "remote_business_error")

    def test_worker_daemon_returns_after_failure_without_retry_or_next_interval(self):
        operation = mock.AsyncMock(side_effect=RuntimeError(PRIVATE))
        output = io.StringIO()
        with mock.patch.object(sys, "argv", ["market_timing_worker.py", "--daemon", "--interval", "360"]), \
             mock.patch.object(market_timing_worker, "run_once", operation), \
             mock.patch.object(market_timing_worker.time, "sleep", side_effect=AssertionError("no next interval")), \
             contextlib.redirect_stderr(output):
            self.assertEqual(market_timing_worker.main(), 1)
        self.assertEqual(operation.await_count, 1)
        self.assertNotIn(PRIVATE, output.getvalue())

    def test_34_collection_and_two_initialization_observations_remain_separate(self):
        lines = []
        for sequence, kind in enumerate(["dsl", "session"] + ["homefeed"] * 34, 1):
            for phase in ("dispatch", "response"):
                lines.append({"event": "xhs_trends_http_observation", **observation(phase, kind, sequence)})
        receipt = self.receipt(lines)
        summary = receipt["physical_http_summary"]
        self.assertEqual(summary["initialization_dispatches_observed"], 2)
        self.assertEqual(summary["collection_dispatches_observed"], 34)
        self.assertTrue(summary["observation_complete"])

    def test_missing_or_orphan_terminal_is_not_reported_complete(self):
        for values in ([observation("dispatch", "dsl", 1)], [observation("response", "dsl", 1)],
                       [observation("dispatch", "dsl", 1), observation("response", "session", 1)],
                       [observation("dispatch", "dsl", 1)] * 2):
            with self.subTest(values=values):
                receipt = self.receipt([{"event": "xhs_trends_http_observation", **v} for v in values])
                self.assertFalse(receipt["physical_http_summary"]["observation_complete"])

    def test_launcher_reprojects_even_forged_worker_fields(self):
        receipt = self.receipt([
            {"event": "xhs_trends_provider_failure", "error_code": PRIVATE, "stage": PRIVATE,
             "response_diagnostics": {"http_status": 403, "message_tags": ["login", PRIVATE], "message": PRIVATE}},
            {"event": "xhs_trends_http_observation", **observation("response", "homefeed", 37)},
        ])
        self.assertNotIn(PRIVATE, json.dumps(receipt))
        self.assertEqual(receipt["provider_failures"][0]["error_code"], "adapter_failure_unknown")
        self.assertEqual(receipt["provider_failures"][0]["response_diagnostics"]["http_status"], 403)
        self.assertEqual(receipt["physical_http_summary"]["invalid_observations"], 1)

    def test_old_output_stays_unknown_and_source_binding_mismatch_fails_closed(self):
        receipt = self.receipt([{"event": "trends_run_failed", "error_code": "trends_provider_attempt_evidence_incomplete"}])
        self.assertEqual(receipt["provider_failures"], [])
        self.assertEqual(receipt["physical_http_observations"], [])
        self.assertFalse(receipt["physical_http_summary"]["observation_complete"])
        with mock.patch.object(launcher, "RUNTIME_OVERLAY_SHA256", {"model/security_redaction.py": "0" * 64}):
            with self.assertRaisesRegex(launcher.Item32Error, "worker_diagnostic_source_binding"):
                launcher._worker_diagnostic_projectors()

    def test_recommendation_counts_are_paired_typed_and_trends_only(self):
        value = observation(kind="search_recommend", sequence=13)
        meta = value["response_diagnostics"]
        meta.update(business_code=1000, recommendation_items_total=3, recommendation_items_usable=2)
        projected = safe.sanitize_trends_http_event(value)
        self.assertEqual(projected["response_diagnostics"]["recommendation_items_total"], 3)
        self.assertEqual(projected["response_diagnostics"]["recommendation_items_usable"], 2)
        self.assertNotIn("recommendation_items_total", safe.sanitize_xhs_response_diagnostics(meta))
        self.assertNotIn("recommendation_items_total", safe.sanitize_trends_http_event(
            {**value, "request_kind": "homefeed"})["response_diagnostics"])
        for total, usable in ((True, 1), (3, True), (3.0, 1), (3, "1"), (-1, 0), (1, 2), (3, None)):
            with self.subTest(total=total, usable=usable):
                forged = {**meta, "recommendation_items_total": total, "recommendation_items_usable": usable}
                cleaned = safe.sanitize_xhs_response_diagnostics(forged, recommendations=True)
                self.assertNotIn("recommendation_items_total", cleaned)
                self.assertNotIn("recommendation_items_usable", cleaned)

    def test_recommendation_structure_survives_failure_and_worker_receipt_without_text(self):
        value = observation(kind="search_recommend", sequence=13)
        value["response_diagnostics"].update(business_code=1000, recommendation_items_total=0,
                                              recommendation_items_usable=0, recommendation_text=PRIVATE)
        failure = safe.sanitize_trends_failure({"stage": "search_recommend", "error_code": "remote_schema_error",
                                               "response_diagnostics": value["response_diagnostics"]})
        self.assertEqual(failure["response_diagnostics"]["recommendation_items_usable"], 0)
        receipt = self.receipt([{"event": "xhs_trends_http_observation", **value},
                                {"event": "xhs_trends_provider_failure", **failure}])
        self.assertEqual(receipt["provider_failures"], [failure])
        self.assertEqual(receipt["physical_http_observations"][0]["response_diagnostics"]
                         ["recommendation_items_total"], 0)
        self.assertNotIn(PRIVATE, json.dumps(receipt))

    def test_v5_recommend_extraction_uses_only_direct_sug_items_and_preserves_legacy_default(self):
        payload = {"name": "非推荐旁支", "data": {"sug_items": [
            {"text": " 合成推荐词 "}, {"text": "合成推荐词"}, {"word": "另一推荐词"},
            {"name": " "}, {"nested": {"text": "旁支假推荐"}}], "title": "其他标题"}}
        self.assertEqual(scheduler_a._extract_recommend_keywords(payload, trends_v5=True),
                         ["合成推荐词", "另一推荐词"])
        self.assertIn("旁支假推荐", scheduler_a._extract_recommend_keywords(payload))
        self.assertEqual(scheduler_a._extract_recommend_keywords({"data": {"items": [{"text": "旁支"}]}},
                                                                  trends_v5=True), [])

    def test_known_secret_output_is_rejected_before_any_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(launcher.Item32Error, "worker_output_secret_detected"):
                launcher._record_worker_receipt(Path(directory), PRIVATE.encode(), exit_code=1, secret_values=[PRIVATE])
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
