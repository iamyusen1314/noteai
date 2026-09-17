"""Synthetic-only Trends transport -> scheduler -> persisted receipt checks."""
import ast
import asyncio
import contextlib
from datetime import timedelta
from enum import IntEnum
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "model"), str(ROOT / "tools")]
import security_redaction as safe
import spider_xhs_http as adapter_module
import spider_xhs_v5 as v5
import scheduler_a
import execute_item32_readonly_trends_successor as launcher

PRIVATE = "SYNTHETIC_PRIVATE_URL_COOKIE_HEADER_DO_NOT_PERSIST"
AT = "2026-09-17T02:00:00.000001+00:00"


class TrendsTransportDiagnosticsTests(unittest.TestCase):
    @contextlib.contextmanager
    def curl_contract(self):
        # Synthetic classes mirror the signatures/MRO independently read from
        # the existing 0.15 image; this does not claim a local real-curl test.
        class CurlError(Exception):
            def __init__(self, msg, code=0):
                super().__init__(msg)
                self.code = code
        class RequestException(CurlError, OSError):
            def __init__(self, msg, code=0, response=None):
                super().__init__(msg, code)
                self.response = response
        excs = types.ModuleType("curl_cffi.requests.exceptions")
        excs.RequestException = RequestException
        excs.ConnectionError = type("ConnectionError", (RequestException,), {})
        excs.DNSError = type("DNSError", (excs.ConnectionError,), {})
        for name in ("Timeout", "ProxyError", "SSLError"):
            setattr(excs, name, type(name, (RequestException,), {}))
        curl = types.ModuleType("curl_cffi.curl")
        curl.CurlError, curl.CURL_WRITEFUNC_ERROR = CurlError, -99
        requests = types.ModuleType("curl_cffi.requests")
        requests.exceptions = excs
        requests.Session = mock.Mock(return_value=types.SimpleNamespace())
        const = types.ModuleType("curl_cffi.const")
        const.CurlInfo = IntEnum("CurlInfo", {"NAMELOOKUP_TIME": 3145732, "CONNECT_TIME": 3145733,
            "APPCONNECT_TIME": 3145761, "PRETRANSFER_TIME": 3145734,
            "STARTTRANSFER_TIME": 3145745, "TOTAL_TIME": 3145731})
        package = types.ModuleType("curl_cffi")
        package.requests = requests
        with mock.patch.dict(sys.modules, {"curl_cffi": package, "curl_cffi.curl": curl,
                "curl_cffi.requests": requests, "curl_cffi.requests.exceptions": excs,
                "curl_cffi.const": const}):
            yield excs, CurlError

    def reader(self, replies, observer=None):
        sent, events, admissions = [], [], []
        queue = list(replies)

        def send(request):
            sent.append(request)
            reply = queue.pop(0)
            if isinstance(reply, BaseException):
                raise reply
            return reply

        client = httpx.Client(transport=httpx.MockTransport(send), trust_env=False)
        self.addCleanup(client.close)
        credentials = adapter_module.SessionCredentials.from_records([
            {"name": "a1", "value": "a" * 52}, {"name": "web_session", "value": PRIVATE}])
        reader = v5.V5Trends(credentials=credentials, assert_ready=lambda: None,
            budget={"initialization": 2, "collection": 34, "total": 36},
            admit=lambda kind: admissions.append(kind) or len(admissions),
            complete=mock.Mock(), client=client, observe=observer or events.append)
        reader._headers = mock.Mock(return_value={})
        return reader, sent, events, admissions

    def receipt(self, output):
        binding = dict(launcher.RUNTIME_OVERLAY_SHA256)
        binding["model/security_redaction.py"] = hashlib.sha256((ROOT / "model/security_redaction.py").read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(launcher, "RUNTIME_OVERLAY_SHA256", binding):
            launcher._record_worker_receipt(Path(directory), output.encode(), exit_code=1, secret_values=[])
            return json.loads((Path(directory) / "worker-receipt.json").read_bytes())

    def test_timeout_cause_chain_is_fixed_bounded_and_does_not_read_message(self):
        cause = TimeoutError(PRIVATE)
        error = httpx.ReadTimeout(PRIVATE)
        error.__cause__ = cause
        cause.__cause__ = error
        self.assertEqual(v5._trends_exception_chain(error), [
            {"category": "timeout", "source": "httpx"}, {"category": "timeout", "source": "python"}])
        class Hostile(Exception):
            def __str__(self):
                raise AssertionError("must not stringify")
        self.assertEqual(v5._trends_exception_chain(Hostile(PRIVATE)), [{"category": "other", "source": "unknown"}])

    def test_projection_rejects_arbitrary_fields_and_false_numeric_values(self):
        raw = {"failure_phase": "transport", "request_started": True, "elapsed_ms": 20003,
               "response_headers_state": "unknown", "response_body_state": "unknown",
               "response_body_bytes_observed": 0, "body_limit_exceeded": False,
               "exception_chain": [{"source": "curl", "category": "timeout", "curl_errno": 28, "message": PRIVATE}],
               "url": PRIVATE, "headers": {"cookie": PRIVATE}, "exception": PRIVATE}
        projected = safe.sanitize_trends_transport_diagnostics(raw)
        self.assertNotIn(PRIVATE, json.dumps(projected))
        self.assertEqual(projected["exception_chain"][0]["curl_errno"], 28)
        invalid = safe.sanitize_trends_transport_diagnostics({**raw, "elapsed_ms": True,
            "response_body_bytes_observed": -1, "failure_phase": PRIVATE,
            "exception_chain": [{"source": "curl", "category": "timeout", "curl_errno": True}]})
        self.assertNotIn("elapsed_ms", invalid)
        self.assertNotIn("response_body_bytes_observed", invalid)
        self.assertNotIn("failure_phase", invalid)
        self.assertNotIn("curl_errno", invalid["exception_chain"][0])
        event = {"phase": "unknown", "request_kind": "dsl", "sequence": 1, "at": AT, "transport_diagnostics": raw}
        self.assertNotIn("transport_diagnostics", safe.sanitize_xhs_http_event(event))
        self.assertEqual(safe.sanitize_trends_http_event(event)["transport_diagnostics"], projected)

    def test_dsl_timeout_is_unknown_one_init_zero_collection_and_latches(self):
        reader, sent, events, admitted = self.reader([httpx.ReadTimeout(PRIVATE)])
        with self.assertRaises(adapter_module.XHSAdapterError) as caught:
            reader.request("POST", v5.TRENDS_HOME_API, {})
        failure = caught.exception
        self.assertEqual((failure.code, failure.stage, failure.diagnostics), ("network_error", "dsl", {}))
        diag = failure.transport_diagnostics
        self.assertEqual(diag["failure_phase"], "transport")
        self.assertEqual(diag["exception_chain"], [{"category": "timeout", "source": "httpx"}])
        self.assertEqual(diag["response_headers_state"], "unknown")
        self.assertEqual(diag["response_body_state"], "unknown")
        self.assertTrue(diag["request_started"])
        self.assertEqual(events[-1]["transport_diagnostics"], diag)
        with self.assertRaisesRegex(adapter_module.XHSAdapterError, "operation_not_allowed"):
            reader.request("POST", v5.TRENDS_HOME_API, {})
        self.assertEqual((len(sent), admitted, reader.initialization_count, reader.collection_count), (1, [], 1, 0))
        self.assertNotIn(PRIVATE, json.dumps(events))

    def test_observer_before_transport_is_local_and_no_request_is_sent(self):
        events = []
        def observe(value):
            if value["phase"] == "dispatch":
                raise OSError(PRIVATE)
            events.append(value)
        reader, sent, _, _ = self.reader([], observe)
        with self.assertRaises(adapter_module.XHSAdapterError) as caught:
            reader.request("POST", v5.TRENDS_HOME_API, {})
        self.assertFalse(caught.exception.transport_diagnostics["request_started"])
        self.assertEqual(caught.exception.transport_diagnostics["failure_phase"], "observer_dispatch")
        self.assertEqual(sent, [])

    def test_unknown_observer_failure_does_not_replace_original_timeout(self):
        def observe(value):
            if value["phase"] == "unknown":
                raise OSError(PRIVATE)
        reader, sent, _, _ = self.reader([httpx.ReadTimeout(PRIVATE)], observe)
        with self.assertRaises(adapter_module.XHSAdapterError) as caught:
            reader.request("POST", v5.TRENDS_HOME_API, {})
        diag = caught.exception.transport_diagnostics
        self.assertEqual(diag["failure_phase"], "transport")
        self.assertEqual(diag["exception_chain"][0]["category"], "timeout")
        self.assertEqual(diag["observation_error_category"], "os_error")
        self.assertEqual(len(sent), 1)

    def test_response_observer_failure_is_local_with_received_bytes(self):
        def observe(value):
            if value["phase"] == "response":
                raise OSError(PRIVATE)
        reader, sent, _, _ = self.reader([httpx.Response(200, text="function getdss() {return '1789010000000';}")], observe)
        with self.assertRaises(adapter_module.XHSAdapterError) as caught:
            reader.request("POST", v5.TRENDS_HOME_API, {})
        diag = caught.exception.transport_diagnostics
        self.assertEqual(diag["failure_phase"], "observer_response")
        self.assertEqual(diag["response_headers_state"], "received")
        self.assertGreater(diag["response_body_bytes_observed"], 0)
        self.assertEqual(len(sent), 1)

    def test_non_json_session_distinguishes_parse_failure_without_copying_body(self):
        reader, sent, _, admitted = self.reader([
            httpx.Response(200, text="function getdss() {return '1789010000000';}"),
            httpx.Response(200, text=PRIVATE)])
        with self.assertRaises(adapter_module.XHSAdapterError) as caught:
            reader.request("POST", v5.TRENDS_HOME_API, {})
        failure = caught.exception
        self.assertEqual((failure.code, failure.stage), ("remote_non_json", "session"))
        self.assertEqual(failure.transport_diagnostics["failure_phase"], "response_parse")
        self.assertEqual(failure.transport_diagnostics["exception_chain"][0]["category"], "json_parse")
        self.assertEqual((len(sent), admitted), (2, []))
        self.assertNotIn(PRIVATE, json.dumps(failure.transport_diagnostics))

    def test_python_dns_and_tls_types_are_fixed_without_exception_text(self):
        self.assertEqual(v5._trends_exception_chain(v5.socket.gaierror(PRIVATE)), [{"category": "dns", "source": "python"}])
        self.assertEqual(v5._trends_exception_chain(v5.ssl.SSLError(PRIVATE)), [{"category": "tls", "source": "python"}])

    def test_local_response_materialization_error_is_not_a_complete_body(self):
        class Response:
            status_code = 200
            @property
            def content(self):
                raise OSError(PRIVATE)
        reader, _, _, _ = self.reader([])
        reader.client = types.SimpleNamespace(request=mock.Mock(return_value=Response()))
        with self.assertRaises(adapter_module.XHSAdapterError) as caught:
            reader.request("POST", v5.TRENDS_HOME_API, {})
        diag = caught.exception.transport_diagnostics
        self.assertEqual(diag["failure_phase"], "response_parse")
        self.assertEqual(diag["response_headers_state"], "received")
        self.assertEqual(diag["response_body_state"], "unknown")
        self.assertEqual(caught.exception.diagnostics, {"http_status": 200})
        reader.client.request.assert_called_once()

    def test_trends_curl_callback_limit_and_wire_options_are_bounded(self):
        client = object.__new__(v5.TrendsCurlClient)
        client.session = mock.Mock()
        def send(*args, **kwargs):
            self.assertEqual(kwargs["timeout"], 20)
            self.assertFalse(kwargs["allow_redirects"])
            self.assertEqual(kwargs["proxies"], {"all": ""})
            self.assertEqual(kwargs["accept_encoding"], v5.wire.DEFAULT_ACCEPT_ENCODING)
            self.assertEqual(kwargs["content_callback"](b"part"), 4)
            self.assertEqual(kwargs["content_callback"](b"x" * v5.MAX_RESPONSE_BYTES), -99)
            raise OSError(PRIVATE)
        client.session.request.side_effect = send
        with self.curl_contract(), self.assertRaises(OSError):
            client.request("GET", "https://example.invalid", headers={})
        diag = client.last_transport_diagnostics
        self.assertTrue(diag["body_limit_exceeded"])
        self.assertEqual(diag["response_headers_state"], "received")
        self.assertEqual(diag["response_body_state"], "partial")
        self.assertEqual(diag["response_body_bytes_observed"], v5.MAX_RESPONSE_BYTES + 4)
        self.assertNotIn(PRIVATE, json.dumps(diag))

    def test_curl_error_intenum_chain_and_optional_response_are_projected(self):
        class Code(IntEnum):
            TIMEOUT = 28
        with self.curl_contract() as (excs, CurlError):
            error = excs.Timeout(PRIVATE, code=Code.TIMEOUT,
                response=types.SimpleNamespace(status_code=200, elapsed=timedelta(seconds=20.004),
                                               headers={"cookie": PRIVATE}, url=PRIVATE))
            error.__cause__ = CurlError(PRIVATE, Code.TIMEOUT)
            client = object.__new__(v5.TrendsCurlClient)
            client.session = mock.Mock()
            client.session.request.side_effect = error
            reader, _, events, admitted = self.reader([])
            reader.client = client
            with self.assertRaises(adapter_module.XHSAdapterError) as caught:
                reader.request("POST", v5.TRENDS_HOME_API, {})
            diag = caught.exception.transport_diagnostics
        self.assertEqual(diag["exception_chain"], [
            {"category": "timeout", "source": "curl", "curl_errno": 28},
            {"category": "other", "source": "curl", "curl_errno": 28}])
        self.assertEqual(diag["reported_elapsed_ms"], 20004)
        self.assertEqual(diag["partial_response_http_status"], 200)
        self.assertEqual(diag["response_headers_state"], "received")
        self.assertEqual(diag["response_body_state"], "unknown")
        self.assertEqual(caught.exception.diagnostics, {"http_status": 200})
        self.assertEqual((events[-1]["phase"], admitted), ("unknown", []))
        client.session.request.assert_called_once()
        self.assertNotIn(PRIVATE, json.dumps(diag))

    def test_curl_missing_response_does_not_invent_headers_status_or_timing(self):
        with self.curl_contract() as (excs, _):
            client = object.__new__(v5.TrendsCurlClient)
            client.session = mock.Mock()
            client.session.request.side_effect = excs.DNSError(PRIVATE, code=6)
            with self.assertRaises(excs.DNSError):
                client.request("GET", "https://example.invalid", headers={})
            diag = client.last_transport_diagnostics
        self.assertEqual(diag["exception_chain"], [{"category": "dns", "source": "curl", "curl_errno": 6}])
        self.assertEqual(diag["response_headers_state"], "unknown")
        self.assertNotIn("partial_response_http_status", diag)
        self.assertIsNone(diag["reported_elapsed_ms"])

    def test_invalid_optional_curl_response_values_are_not_persisted(self):
        for elapsed in (PRIVATE, timedelta(seconds=-1), timedelta(days=2)):
            with self.subTest(elapsed=type(elapsed).__name__), self.curl_contract() as (excs, _):
                error = excs.SSLError(PRIVATE, code=True,
                    response=types.SimpleNamespace(status_code=True, elapsed=elapsed, headers=PRIVATE))
                client = object.__new__(v5.TrendsCurlClient)
                client.session = mock.Mock(request=mock.Mock(side_effect=error))
                with self.assertRaises(excs.SSLError):
                    client.request("GET", "https://example.invalid", headers={})
                diag = client.last_transport_diagnostics
            self.assertEqual(diag["exception_chain"], [{"category": "tls", "source": "curl"}])
            self.assertNotIn("partial_response_http_status", diag)
            self.assertIsNone(diag["reported_elapsed_ms"])
            self.assertNotIn(PRIVATE, json.dumps(diag))

    def test_only_trends_requests_the_six_confirmed_clocks(self):
        with self.curl_contract():
            from curl_cffi import requests
            from curl_cffi.const import CurlInfo
            requests.Session.side_effect = [types.SimpleNamespace(), types.SimpleNamespace()]
            tracking = v5.CurlClient()
            trends = v5.TrendsCurlClient()
            self.assertFalse(hasattr(tracking.session, "curl_infos"))
            self.assertEqual(trends.session.curl_infos, [getattr(CurlInfo, key) for key in v5._TRENDS_CURL_CLOCKS])
            self.assertEqual(requests.Session.call_args_list[0], requests.Session.call_args_list[1])
            self.assertFalse(requests.Session.call_args.kwargs["trust_env"])

    def test_clock_projection_keeps_zero_and_nulls_missing_nan_and_invalid(self):
        with self.curl_contract():
            from curl_cffi.const import CurlInfo
            for invalid in (float("nan"), float("inf"), -1, True, PRIVATE, 61):
                infos = {CurlInfo.NAMELOOKUP_TIME: 0, CurlInfo.CONNECT_TIME: 0.003,
                         CurlInfo.APPCONNECT_TIME: invalid, CurlInfo.TOTAL_TIME: 20.005, PRIVATE: PRIVATE}
                clocks = v5._trends_curl_timings(types.SimpleNamespace(infos=infos))
                self.assertEqual(clocks["NAMELOOKUP_TIME"], 0)
                self.assertEqual(clocks["CONNECT_TIME"], 3)
                self.assertEqual(clocks["TOTAL_TIME"], 20005)
                self.assertIsNone(clocks["APPCONNECT_TIME"])
                self.assertIsNone(clocks["STARTTRANSFER_TIME"])
                self.assertNotIn(PRIVATE, json.dumps(clocks, allow_nan=False))
            self.assertEqual(v5._trends_curl_timings(None), {key: None for key in v5._TRENDS_CURL_CLOCKS})
        forged = safe.sanitize_trends_transport_diagnostics({"curl_timing_ms": {
            "NAMELOOKUP_TIME": 0, "CONNECT_TIME": float("nan"), "APPCONNECT_TIME": True,
            "PRETRANSFER_TIME": -1, "STARTTRANSFER_TIME": 60001, PRIVATE: PRIVATE}})
        self.assertEqual(forged["curl_timing_ms"], {key: 0 if key == "NAMELOOKUP_TIME" else None
                                                 for key in v5._TRENDS_CURL_CLOCKS})
        self.assertNotIn(PRIVATE, json.dumps(forged, allow_nan=False))

    def test_nullable_clocks_and_curl_chain_survive_the_whole_receipt_path(self):
        with self.curl_contract() as (excs, CurlError):
            from curl_cffi.const import CurlInfo
            error = excs.Timeout(PRIVATE, code=28, response=types.SimpleNamespace(
                status_code=0, elapsed=timedelta(seconds=20),
                infos={CurlInfo.NAMELOOKUP_TIME: 0.004, CurlInfo.CONNECT_TIME: 0,
                       CurlInfo.TOTAL_TIME: 20, "url": PRIVATE}))
            error.__cause__ = CurlError(PRIVATE, code=28)
            client = object.__new__(v5.TrendsCurlClient)
            client.session = mock.Mock(request=mock.Mock(side_effect=error))
            reader, _, _, _ = self.reader([])
            reader.client = client
            class Adapter:
                def homefeed(self, **unused):
                    reader.observe = self.http_observer
                    return reader.request("POST", v5.TRENDS_HOME_API, {})
                def close(self):
                    reader.close()
            output = io.StringIO()
            with mock.patch.object(adapter_module, "SpiderXHSHTTPAdapter", Adapter), contextlib.redirect_stdout(output):
                result = asyncio.run(scheduler_a.scrape_once_http())
            receipt = self.receipt(output.getvalue())
        diag = receipt["provider_failures"][0]["transport_diagnostics"]
        self.assertEqual(diag, result.diagnostics["provider_failure"]["transport_diagnostics"])
        self.assertEqual(receipt["physical_http_observations"][-1]["transport_diagnostics"], diag)
        self.assertEqual(diag["curl_timing_ms"]["NAMELOOKUP_TIME"], 4)
        self.assertEqual(diag["curl_timing_ms"]["CONNECT_TIME"], 0)
        self.assertEqual(diag["curl_timing_ms"]["TOTAL_TIME"], 20000)
        self.assertIsNone(diag["curl_timing_ms"]["APPCONNECT_TIME"])
        self.assertEqual(diag["exception_chain"][0]["curl_errno"], 28)
        self.assertNotIn(PRIVATE, json.dumps(receipt, allow_nan=False))
        client.session.request.assert_called_once()

    def test_real_trends_exception_survives_scheduler_worker_projection_and_launcher(self):
        reader, sent, _, _ = self.reader([httpx.ReadTimeout(PRIVATE)])
        class Adapter:
            def homefeed(self, **unused):
                reader.observe = self.http_observer
                return reader.request("POST", v5.TRENDS_HOME_API, {})
            def close(self):
                reader.close()
        output = io.StringIO()
        with mock.patch.object(adapter_module, "SpiderXHSHTTPAdapter", Adapter), contextlib.redirect_stdout(output):
            result = asyncio.run(scheduler_a.scrape_once_http())
        # market_timing_worker uses this same sanitizer after ScrapeResults.
        discovery = scheduler_a.discovery_diagnostics_for_results(result, result.diagnostics)
        failure = discovery["provider_failure"]
        receipt = self.receipt(output.getvalue())
        self.assertEqual(receipt["provider_failures"], [failure])
        self.assertEqual(failure["transport_diagnostics"]["exception_chain"][0]["category"], "timeout")
        self.assertEqual(receipt["physical_http_observations"][-1]["transport_diagnostics"], failure["transport_diagnostics"])
        summary = receipt["physical_http_summary"]
        self.assertEqual((summary["initialization_dispatches_observed"], summary["collection_dispatches_observed"],
                          summary["response_events_observed"], summary["unknown_events_observed"]), (1, 0, 0, 1))
        self.assertTrue(summary["observation_complete"])
        self.assertEqual(len(sent), 1)
        self.assertNotIn(PRIVATE, output.getvalue())
        self.assertNotIn(PRIVATE, json.dumps(receipt))

    def test_old_unknown_projection_is_not_backfilled(self):
        value = {"stage": "dsl", "error_code": "network_error", "response_diagnostics": {}}
        self.assertEqual(safe.sanitize_trends_failure(value), value)
        receipt = self.receipt(json.dumps({"event": "xhs_trends_provider_failure", **value}))
        self.assertEqual(receipt["provider_failures"], [value])
        self.assertNotIn("transport_diagnostics", receipt["provider_failures"][0])

    def test_changed_sources_compile_without_execution(self):
        for name in ("model/spider_xhs_v5.py", "model/security_redaction.py", "model/scheduler_a.py", __file__):
            path = ROOT / name
            ast.parse(path.read_text(), filename=str(path))


if __name__ == "__main__":
    unittest.main()
