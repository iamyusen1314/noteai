"""Published ACS3 vector and isolated HTTP transport checks; synthetic data only."""
import hashlib
import json
import io
import logging
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import sms_delivery as sms


class SmsTransportTests(unittest.TestCase):
    def setUp(self):
        self.config = sms.Config("测试短信", "SMS_123456", "isolated-test-role")
        self.credential = SimpleNamespace(access_key_id="synthetic-key", access_key_secret="synthetic-secret",
                                          security_token="synthetic-sts")
        self.request_id, self.biz_id = "12345678-abcd-1234-abcd-123456789012", "90000000000000000001"

    def test_official_acs3_signature_vector(self):
        headers = {"host": "ecs.cn-shanghai.aliyuncs.com", "x-acs-action": "RunInstances",
            "x-acs-version": "2014-05-26", "x-acs-date": "2023-10-26T10:22:32Z",
            "x-acs-signature-nonce": "3156853299f313e23d1673dc12e1703d",
            "x-acs-content-sha256": hashlib.sha256(b"").hexdigest()}
        query = "ImageId=win2019_1809_x64_dtc_zh-cn_40G_alibase_20230811.vhd&RegionId=cn-shanghai"
        _, signature = sms._signature(query, headers, "YourAccessKeySecret")
        self.assertEqual(signature, "06563a9e1b43f5dfe96b81484da74bceab24a1d853912eee15083a6f0f3283c0")

    def invoke(self, handler):
        with mock.patch.object(sms, "_credentials", return_value=self.credential), \
             mock.patch.object(sms.httpx, "HTTPTransport", return_value=httpx.MockTransport(handler)) as factory:
            result = sms.send(self.config, phone="+8613800138000", code="987654", challenge_id="local-synthetic-challenge")
        factory.assert_called_once_with(retries=0, trust_env=False)
        return result

    def test_exact_signed_query_body_and_sts(self):
        def handler(req):
            self.assertEqual(req.method, "POST")
            self.assertEqual(req.url.host, "dysmsapi.aliyuncs.com")
            self.assertEqual(req.content, b"")
            self.assertNotIn(b"+", req.url.query)
            self.assertIn("x-acs-security-token", req.headers["Authorization"])
            self.assertEqual(req.headers["x-acs-security-token"], "synthetic-sts")
            headers = {k: v for k, v in req.headers.items() if k.startswith("x-acs-") or k == "host"}
            names, signature = sms._signature(req.url.query.decode(), headers, self.credential.access_key_secret)
            self.assertEqual(req.headers["Authorization"], f"ACS3-HMAC-SHA256 Credential=synthetic-key,SignedHeaders={names},Signature={signature}")
            params = parse_qs(req.url.query.decode())
            self.assertEqual(params["SignName"], ["测试短信"])
            self.assertEqual(params["TemplateParam"], ['{"code":"987654"}'])
            self.assertEqual(set(params), {"PhoneNumbers", "SignName", "TemplateCode", "TemplateParam", "OutId"})
            return httpx.Response(200, json={"Code": "OK", "RequestId": self.request_id, "BizId": self.biz_id})
        self.assertEqual(self.invoke(handler).state, "accepted")

    def test_pnvs_custom_code_uses_approved_pair_and_no_automatic_retry(self):
        self.config = sms.Config("恒创联众", "100001", "isolated-test-role", "aliyun_pnvs")
        def handler(req):
            self.assertEqual(req.url.host, "dypnsapi.aliyuncs.com")
            self.assertEqual(req.headers["x-acs-action"], "SendSmsVerifyCode")
            params = parse_qs(req.url.query.decode())
            self.assertNotIn("PhoneNumbers", params)
            self.assertEqual(params["PhoneNumber"], ["13800138000"])
            self.assertEqual(params["TemplateCode"], ["100001"])
            self.assertEqual(params["SignName"], ["恒创联众"])
            self.assertEqual(json.loads(params["TemplateParam"][0]), {"code": "987654", "min": "10"})
            self.assertEqual(params["AutoRetry"], ["0"])
            self.assertEqual(params["ReturnVerifyCode"], ["false"])
            self.assertEqual(params["Interval"], ["60"])
            self.assertEqual(params["ValidTime"], ["600"])
            return httpx.Response(200, json={"Code": "OK", "Success": True,
                "RequestId": self.request_id, "Model": {"BizId": self.biz_id + "^1",
                "OutId": "local-synthetic-challenge"}})
        result = self.invoke(handler)
        self.assertEqual(result.state, "accepted")
        self.assertEqual(result.biz_id, self.biz_id + "^1")

    def test_pnvs_incomplete_or_mismatched_success_is_unknown(self):
        self.config = sms.Config("恒创联众", "100001", "isolated-test-role", "aliyun_pnvs")
        for model, success in (({}, True), ({"BizId": self.biz_id}, False),
            ({"BizId": self.biz_id}, "true"), ({"BizId": self.biz_id, "OutId": "other"}, True)):
            with self.subTest(model=model, success=success):
                result = self.invoke(lambda req: httpx.Response(200, json={"Code": "OK",
                    "Success": success, "RequestId": self.request_id, "Model": model}))
                self.assertEqual(result.state, "unknown")

    def test_pnvs_transport_failure_does_not_resend(self):
        self.config = sms.Config("恒创联众", "100001", "isolated-test-role", "aliyun_pnvs")
        self.test_redirect_timeout_invalid_response_never_retries()

    def test_pnvs_independent_inner_request_reference_and_strict_success(self):
        self.config = sms.Config("恒创联众", "100001", "isolated-test-role", "aliyun_pnvs")
        inner = "abcdef12-abcd-1234-abcd-123456789012"
        for outer, nested, success, out_id, expected in (
            (None, inner, True, "local-synthetic-challenge", "accepted"),
            (self.request_id, inner, True, "local-synthetic-challenge", "accepted"),
            (None, None, True, "local-synthetic-challenge", "unknown"),
            (None, inner, "true", "local-synthetic-challenge", "unknown"),
            (None, inner, True, "other", "unknown"),
        ):
            with self.subTest(outer=outer, nested=nested, success=success, out_id=out_id):
                result = self.invoke(lambda req: httpx.Response(200, json={"Code": "OK",
                    "Success": success, "RequestId": outer, "Model": {"RequestId": nested,
                    "BizId": self.biz_id, "OutId": out_id}}))
                self.assertEqual(result.state, expected)
                self.assertEqual(result.request_id, outer or nested or "")

    def test_pnvs_unknown_diagnostics_do_not_include_response_or_code(self):
        self.config = sms.Config("恒创联众", "100001", "isolated-test-role", "aliyun_pnvs")
        with self.assertLogs("sms_delivery", level="WARNING") as captured:
            result = self.invoke(lambda req: httpx.Response(200, json={"Code": "OK", "Success": True,
                "Message": "synthetic-private-body", "Model": {"BizId": self.biz_id,
                "VerifyCode": "987654", "RequestId": "synthetic-invalid-reference-with-private-content!"}}))
        self.assertEqual(result.state, "unknown")
        diagnostic = json.loads(captured.records[0].getMessage().split(" ", 1)[1])
        self.assertEqual(diagnostic, {"http_status": 200, "code_is_string": True, "code_is_ok": True,
            "success_is_bool": True, "success_is_true": True, "outer_request_id_valid": False,
            "inner_request_id_valid": False, "biz_id_valid": True})
        self.assertNotIn("987654", " ".join(captured.output))
        self.assertNotIn("synthetic-", " ".join(captured.output))

    def test_redirect_timeout_invalid_response_never_retries(self):
        for kind in ("redirect", "timeout", "server-error", "large", "missing-id"):
            seen = []
            def handler(req):
                seen.append(req)
                if kind == "redirect": return httpx.Response(302, headers={"Location": "https://unrelated.invalid"})
                if kind == "timeout": raise httpx.ReadTimeout("synthetic secret URL must not escape", request=req)
                if kind == "large": return httpx.Response(200, content=b"x" * 20000)
                if kind == "missing-id": return httpx.Response(200, json={"Code": "OK"})
                return httpx.Response(500, json={"Code": "FAIL", "RequestId": self.request_id})
            with self.subTest(kind=kind):
                result = self.invoke(handler)
                self.assertEqual(result.state, "unknown")
                self.assertEqual(len(seen), 1)
                self.assertNotIn("987654", repr(result))

    def test_provider_raw_messages_and_child_logs_are_not_exposed(self):
        output, root = io.StringIO(), logging.getLogger()
        handler_log = logging.StreamHandler(output)
        root.addHandler(handler_log)
        def handler(req):
            child = logging.getLogger("httpcore.http11")
            child.setLevel(logging.DEBUG)
            child.debug("synthetic-credential-leak")
            return httpx.Response(400, json={"Code": "987654", "Message": "synthetic-secret-full-body",
                                            "RequestId": self.request_id})
        try: result = self.invoke(handler)
        finally: root.removeHandler(handler_log)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(result.state, "rejected")
        self.assertEqual(result.code, "PROVIDER_REJECTED")
        self.assertNotIn("987654", repr(result))
        self.assertNotIn("synthetic-secret", repr(result))


if __name__ == "__main__": unittest.main()
