import json
import os
from pathlib import Path
import re
import sys
import unittest
from unittest import mock

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
import spider_xhs_http as legacy
import spider_xhs_v5 as v5

USER = "0123456789abcdef01234567"
BUDGET = {"initialization": 2, "collection": 34, "total": 36}


class TrendsV5Tests(unittest.TestCase):
    def credentials(self):
        return legacy.SessionCredentials.from_records([
            {"name": "a1", "value": "a" * 52, "domain": ".xiaohongshu.com"},
            {"name": "web_session", "value": "FAKE_FULL_SESSION", "domain": ".xiaohongshu.com"},
            {"name": "gid", "value": "FAKE_EXISTING_GID", "domain": ".xiaohongshu.com"},
        ])

    def init(self):
        return [httpx.Response(200, text="function getdss() {return '1789010000000';}; NEVER_EXECUTE();"),
                httpx.Response(200, json={"success": True, "code": 0, "data": {"user_id": USER}})]

    def ok(self):
        return httpx.Response(200, json={"success": True, "code": 0, "data": {
            "items": [{"note_card": {"display_title": "合成美食测试标题"}}], "has_more": False}})

    def reader(self, responses, *, real_sign=False, admit=None, complete=None):
        requests, events, admissions, finishes = [], [], [], []
        queue = list(responses)
        def request(req):
            requests.append(req)
            value = queue.pop(0)
            if isinstance(value, BaseException):
                raise value
            return value
        def admission(kind):
            admissions.append(kind)
            return len(admissions)
        def finish(attempt, **kwargs):
            finishes.append((attempt, kwargs))
        client = httpx.Client(transport=httpx.MockTransport(request), trust_env=False)
        self.addCleanup(client.close)
        reader = v5.V5Trends(credentials=self.credentials(), assert_ready=lambda: None,
            budget=BUDGET, admit=admit or admission, complete=complete or finish,
            client=client, observe=events.append)
        if not real_sign:
            reader._headers = mock.Mock(return_value={})
        return reader, requests, events, admissions, finishes

    def test_real_signing_full_session_and_public_adapter_routes(self):
        reader, sent, events, admitted, completed = self.reader(self.init()+[self.ok()]*3, real_sign=True)
        adapter = legacy.SpiderXHSHTTPAdapter(credentials=self.credentials(), client=reader.client,
                                               http_observer=events.append)
        with mock.patch.dict(os.environ, {"NOTEAI_XHS_PROTOCOL": "pc_v5", "NOTEAI_XHS_SERVICE": "trends",
                                         "NOTEAI_XHS_V5_BUDGET_JSON": json.dumps(BUDGET)}), \
             mock.patch.object(adapter, "_assert_ready"), \
             mock.patch("trends_contract.admit_provider_request", side_effect=reader.admit), \
             mock.patch("trends_contract.complete_provider_request", side_effect=reader.complete):
            adapter.homefeed()
            adapter.search_recommend("美食 探店")
            adapter.search_notes("美食 探店")
            adapter.close()
        self.assertEqual([str(r.url).split("?", 1)[0] for r in sent], [
            v5.DSL_URL.split("?", 1)[0], v5.BASE+v5.SESSION_API, v5.BASE+v5.TRENDS_HOME_API,
            v5.BASE+v5.TRENDS_RECOMMEND_API, v5.TRENDS_SEARCH_BASE+v5.TRENDS_SEARCH_API])
        self.assertNotIn("cookie", sent[0].headers)
        self.assertEqual(sent[2].headers["xy-direction"], str(v5.wire.generate_xy_direction(USER)))
        for index in (2, 4):
            self.assertIn("x-rap-param", sent[index].headers)
            self.assertIn("Chrome/152", sent[index].headers["user-agent"])
        self.assertNotIn("x-rap-param", sent[3].headers)
        self.assertNotIn("cache-control", sent[2].headers)
        self.assertIn("gid=FAKE_EXISTING_GID", sent[4].headers["cookie"])
        body = json.loads(sent[4].content)
        self.assertNotIn("filters", body)
        self.assertRegex(body["session_id"], r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        self.assertGreater(int(body["search_id"], 36), 1 << 64)
        self.assertEqual(admitted, ["homefeed", "search_recommend", "search_notes"])
        self.assertEqual([row[1] for row in completed], [{"outcome": "succeeded"}]*3)
        self.assertEqual([e["sequence"] for e in events], [1,1,2,2,3,3,4,4,5,5])
        self.assertNotIn("FAKE", json.dumps(events))
        self.assertNotIn(USER, json.dumps(events))

    def test_two_initialization_plus_34_collection_and_no_37th_http(self):
        reader, sent, _, admitted, completed = self.reader(self.init()+[self.ok()]*34)
        for _ in range(34):
            reader.request("POST", v5.TRENDS_HOME_API, {})
        with self.assertRaisesRegex(legacy.XHSAdapterError, "operation_not_allowed"):
            reader.request("POST", v5.TRENDS_HOME_API, {})
        self.assertEqual((len(sent), len(admitted), len(completed)), (36, 34, 34))
        self.assertEqual((reader.initialization_count, reader.collection_count), (2, 34))

    def test_budget_is_explicit_and_cannot_increase_collection(self):
        for budget in ["", None, {}, dict(BUDGET, collection=35,total=37),
                       dict(BUDGET,total=35), dict(BUDGET,initialization=True), dict(BUDGET,extra=0)]:
            with self.subTest(budget=budget), self.assertRaisesRegex(legacy.XHSAdapterError, "trends_v5_budget_required"):
                v5.trends_budget(budget)
        self.assertEqual(v5.trends_budget({"initialization":2,"collection":1,"total":3})["total"], 3)

    def test_session_rejection_preserves_unknown_cause_and_stops_without_collection(self):
        reader, sent, events, admitted, _ = self.reader([self.init()[0], httpx.Response(200,json={
            "success":False,"code":-3,"msg":"FAKE_PRIVATE_UNKNOWN"})])
        with self.assertRaises(legacy.XHSAdapterError) as caught:
            reader.request("POST", v5.TRENDS_HOME_API, {})
        self.assertEqual(caught.exception.code, "remote_business_error")
        self.assertEqual(events[-1]["response_diagnostics"]["business_code"], -3)
        with self.assertRaisesRegex(legacy.XHSAdapterError, "operation_not_allowed"):
            reader.request("POST", v5.TRENDS_HOME_API, {})
        self.assertEqual((len(sent), admitted), (2, []))
        self.assertNotIn("FAKE", json.dumps(events))

    def test_session_signer_failure_reports_session_without_a_session_dispatch(self):
        reader, sent, events, admitted, _ = self.reader([self.init()[0]])
        reader._headers = mock.Mock(side_effect=legacy.XHSAdapterError("signer_failed"))
        with self.assertRaises(legacy.XHSAdapterError) as caught:
            reader.request("POST", v5.TRENDS_HOME_API, {})
        self.assertEqual(caught.exception.stage, "session")
        self.assertEqual(len(sent), 1)
        self.assertEqual([e["request_kind"] for e in events], ["dsl", "dsl"])
        self.assertFalse(admitted)

    def test_actual_access_restriction_stops_and_keeps_original_failure(self):
        reader, sent, _, admitted, completed = self.reader(self.init()+[httpx.Response(461,json={"code":0})])
        with self.assertRaises(legacy.XHSAdapterError) as caught:
            reader.request("POST", v5.TRENDS_HOME_API, {})
        self.assertEqual(caught.exception.code, "access_restricted")
        self.assertEqual(completed, [(1,{"outcome":"failed","error_code":"access_restricted"})])
        with self.assertRaises(legacy.XHSAdapterError):
            reader.request("GET", v5.TRENDS_RECOMMEND_API+"?keyword=test")
        self.assertEqual((len(sent),admitted),(3,["homefeed"]))

    def test_network_unknown_is_admitted_once_not_returned_or_retried(self):
        reader, sent, events, _, completed = self.reader(self.init()+[httpx.ReadTimeout("FAKE_PRIVATE_VALUE")])
        with self.assertRaisesRegex(legacy.XHSAdapterError,"network_error"):
            reader.request("POST", v5.TRENDS_HOME_API, {})
        self.assertEqual(completed, [(1,{"outcome":"outcome_unknown","error_code":"network_error"})])
        self.assertEqual(events[-1]["phase"], "unknown")
        self.assertEqual(len(sent),3)
        self.assertNotIn("FAKE_PRIVATE", json.dumps(events))

    def test_finalize_failure_is_never_finalized_twice(self):
        complete = mock.Mock(side_effect=RuntimeError("private DB failure"))
        reader, sent, _, admitted, _ = self.reader(self.init()+[self.ok()],complete=complete)
        with self.assertRaisesRegex(legacy.XHSAdapterError,"trends_provider_finalize_failed"):
            reader.request("POST", v5.TRENDS_HOME_API, {})
        self.assertEqual((len(sent),admitted,complete.call_count),(3,["homefeed"],1))

    def test_admission_denial_prevents_business_http(self):
        admit = mock.Mock(side_effect=RuntimeError("quota"))
        reader, sent, _, _, completed = self.reader(self.init(),admit=admit)
        with self.assertRaisesRegex(legacy.XHSAdapterError,"trends_provider_admission_failed"):
            reader.request("POST", v5.TRENDS_HOME_API, {})
        self.assertEqual((len(sent),completed),(2,[]))

    def test_invalid_routes_and_queries_reject_before_initialization(self):
        for method, api in [("POST",v5.DETAIL_API),("POST","/api/sns/web/v1/comment/post"),
                            ("GET",v5.TRENDS_RECOMMEND_API+"?keyword=x&other=y"),
                            ("GET",v5.TRENDS_RECOMMEND_API+"?keyword=x&keyword=y"),
                            ("POST",v5.TRENDS_HOME_API+"?extra=1")]:
            reader, sent, _, _, _ = self.reader([])
            with self.subTest(api=api), self.assertRaisesRegex(legacy.XHSAdapterError,"operation_not_allowed"):
                reader.request(method,api,{})
            self.assertFalse(sent)

    def test_expired_context_never_bootstraps_again(self):
        reader, sent, _, _, _ = self.reader(self.init()+[self.ok()])
        reader.request("POST",v5.TRENDS_HOME_API,{})
        reader._headers = v5.V5Trends._headers.__get__(reader)
        reader.dsl_fetched_at -= 301
        with self.assertRaisesRegex(legacy.XHSAdapterError,"signing_context_expired"):
            reader.request("POST",v5.TRENDS_HOME_API,{})
        self.assertEqual(len(sent),3)

    def test_unproven_business_success_stops_first_homefeed_without_followup(self):
        for payload in ({}, {"success": True}, {"success": "true", "code": 0},
                        {"success": True, "code": False}, {"success": True, "code": "ok"},
                        {"success": True, "code": 0, "data": {"code": -3}},
                        {"success": True, "code": 0, "data": {"message": "access denied FAKE_PRIVATE"}}):
            with self.subTest(payload_shape=sorted(payload)):
                reader, sent, events, admitted, completed = self.reader(
                    self.init()+[httpx.Response(200, json=payload), self.ok()])
                with self.assertRaises(legacy.XHSAdapterError) as caught:
                    reader.request("POST", v5.TRENDS_HOME_API, {})
                self.assertEqual(caught.exception.code, "remote_business_error")
                self.assertEqual(caught.exception.stage, "homefeed")
                self.assertEqual(caught.exception.diagnostics["http_status"], 200)
                if isinstance(payload.get("data"), dict) and "code" in payload["data"]:
                    self.assertEqual(caught.exception.diagnostics["nested_business_code"], -3)
                with self.assertRaisesRegex(legacy.XHSAdapterError, "operation_not_allowed"):
                    reader.request("GET", v5.TRENDS_RECOMMEND_API+"?keyword=test")
                self.assertEqual((len(sent), admitted), (3, ["homefeed"]))
                self.assertEqual(completed, [(1, {"outcome": "failed", "error_code": "remote_business_error"})])
                self.assertNotIn("FAKE_PRIVATE", json.dumps(events))

    def test_first_homefeed_requires_usable_note_data_without_freeze_inference(self):
        for data in (None, {}, {"items": []}, {"items": [None, {}]},
                     {"items": [{"note_card": {"display_title": "  "}}]}):
            with self.subTest(data_shape=type(data).__name__):
                reader, sent, _, admitted, completed = self.reader(self.init()+[
                    httpx.Response(200, json={"success": True, "code": 0, "data": data}), self.ok()])
                with self.assertRaises(legacy.XHSAdapterError) as caught:
                    reader.request("POST", v5.TRENDS_HOME_API, {})
                self.assertEqual((caught.exception.code, caught.exception.stage), ("remote_schema_error", "homefeed"))
                self.assertEqual(caught.exception.diagnostics["business_code"], 0)
                with self.assertRaisesRegex(legacy.XHSAdapterError, "operation_not_allowed"):
                    reader.request("POST", v5.TRENDS_HOME_API, {})
                self.assertEqual((len(sent), admitted), (3, ["homefeed"]))
                self.assertEqual(completed, [(1, {"outcome": "failed", "error_code": "remote_schema_error"})])

    def test_empty_search_and_numeric_string_zero_remain_valid(self):
        empty = httpx.Response(200, json={"success": True, "code": "0", "data": {"items": [], "code": "0"}})
        reader, sent, _, admitted, completed = self.reader(self.init()+[self.ok(), empty, empty])
        reader.request("POST", v5.TRENDS_HOME_API, {})
        self.assertEqual(reader.request("GET", v5.TRENDS_RECOMMEND_API+"?keyword=test")["data"]["items"], [])
        self.assertEqual(reader.request("POST", v5.TRENDS_SEARCH_API, {})["data"]["items"], [])
        self.assertEqual((len(sent), len(admitted)), (5, 3))
        self.assertEqual([result for _, result in completed], [{"outcome": "succeeded"}]*3)

    def test_unproven_session_success_prevents_any_collection_admission(self):
        reader, sent, _, admitted, _ = self.reader([self.init()[0], httpx.Response(200, json={
            "code": 0, "data": {"user_id": USER}})])
        with self.assertRaises(legacy.XHSAdapterError) as caught:
            reader.request("POST", v5.TRENDS_HOME_API, {})
        self.assertEqual((caught.exception.code, caught.exception.stage), ("remote_business_error", "session"))
        self.assertEqual((len(sent), admitted), (2, []))


if __name__ == "__main__":
    unittest.main()
