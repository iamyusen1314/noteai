"""Offline signed query receipts and explicit unpaid close, with no suppliers."""
import base64
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import re
import sys
import unittest
from unittest import mock

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
import direct_payment_gateways as direct
import payment_contract as payment
from tests import test_direct_payment_gateways as fixtures
from tests import test_wechat_jsapi_payment as original

db = original.db
APP_ID, OPENID = original.APP_ID, original.OPENID


class NoOutboundTransport:
    def request(self, *_args, **_kwargs):
        raise AssertionError("Payment cannot make outbound requests")

    def reconciliation(self, *_args, **_kwargs):
        raise AssertionError("Payment cannot fetch bills")


class WechatJSAPIReconcileGatewayTests(unittest.TestCase):
    setUpClass = classmethod(original.WeChatJsapiPaymentTests.setUpClass.__func__)
    gateway_for = original.WeChatJsapiPaymentTests.gateway_for
    create_order = original.WeChatJsapiPaymentTests.create_order
    provider_body = original.WeChatJsapiPaymentTests.provider_body

    def setUp(self):
        original.WeChatJsapiPaymentTests.setUp(self)
        self.network = mock.patch("socket.socket.connect", side_effect=AssertionError("external network forbidden"))
        self.network.start()
        self.payment_gateway = self.gateway_for(NoOutboundTransport())

    def tearDown(self):
        self.network.stop()
        original.WeChatJsapiPaymentTests.tearDown(self)

    def lookup(self, row):
        return payment.ProviderPaymentLookup(row["merchant_order_no"], expected_amount_fen=1200)

    def receipt(self, body, *, raw=None):
        raw = json.dumps(body, separators=(",", ":")).encode() if raw is None else raw
        stamp, nonce = str(int(self.now.timestamp())), "synthetic-response-nonce"
        signature = self.wechat_private.sign(
            f"{stamp}\n{nonce}\n".encode() + raw + b"\n", padding.PKCS1v15(), hashes.SHA256()
        )
        return {"body_b64": base64.b64encode(raw).decode(), "headers": {
            "Wechatpay-Timestamp": stamp, "Wechatpay-Nonce": nonce,
            "Wechatpay-Serial": "0123456789ABCDEF", "Wechatpay-Signature": base64.b64encode(signature).decode(),
            "Wechatpay-Signature-Type": "WECHATPAY2-SHA256-RSA2048",
        }}

    def response(self, body, *, status=200, raw=None):
        receipt = self.receipt(body, raw=raw)
        headers = dict(receipt["headers"])
        if status != 204:
            headers["Content-Type"] = "application/json"
        return httpx.Response(status, content=base64.b64decode(receipt["body_b64"]), headers=headers)

    @contextmanager
    def api_gateway(self, handler):
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            transport = direct.HttpxWeChatPayTransport(
                app_id=APP_ID, merchant_id="1900000109", merchant_certificate_serial="FEDCBA9876543210",
                merchant_private_key_pem=self.merchant_private.private_bytes(
                    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
                ).decode(), platform_verifier_id="0123456789ABCDEF",
                platform_public_key_pem=fixtures.public_pem(self.wechat_private), client=client,
                clock=lambda: self.now, nonce_factory=lambda: "synthetic-request-nonce",
            )
            yield self.gateway_for(transport)

    def assert_empty_finance(self):
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM payment_cash_ledger")["n"], 0)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM payment_entitlement_ledger")["n"], 0)

    def test_notpay_missing_optional_fields_remains_pending_and_export_is_one_get(self):
        public, row = self.create_order()
        self.assertEqual(public["payment_method"], "jsapi")
        self.assertTrue(payment.admit_payment_submission(row["id"], now=self.now))
        body = {"appid": APP_ID, "mchid": "1900000109", "out_trade_no": row["merchant_order_no"], "trade_state": "NOTPAY"}
        requests = []
        def handler(request):
            requests.append(request)
            self.assertEqual(request.method, "GET")
            return self.response(body)
        with self.api_gateway(handler) as gateway:
            receipt = gateway.export_payment_query_receipt(self.lookup(row))
        self.assertEqual(set(receipt), {"body_b64", "headers"})
        self.assertEqual(len(requests), 1)
        self.assertEqual(len(receipt["headers"]), 5)
        result = self.payment_gateway.process_signed_payment_query_receipt(self.lookup(row), receipt, now=self.now)
        self.assertEqual(result, {"ok": True, "pending": True})
        self.assertEqual(payment.get_order_for_user(row["id"], "jsapi-user")["payment_status"], "pending")
        self.assert_empty_finance()

    def test_closed_missing_payer_trade_type_amount_settles_once_without_cash(self):
        _public, row = self.create_order()
        payment.admit_payment_submission(row["id"], now=self.now)
        body = {"appid": APP_ID, "mchid": "1900000109", "out_trade_no": row["merchant_order_no"], "trade_state": "CLOSED"}
        receipt = self.receipt(body)
        result = self.payment_gateway.process_signed_payment_query_receipt(self.lookup(row), receipt, now=self.now)
        self.assertTrue(result["ok"])
        self.assertEqual(payment.get_order_for_user(row["id"], "jsapi-user")["payment_status"], "failed")
        self.assertTrue(self.payment_gateway.process_signed_payment_query_receipt(self.lookup(row), receipt, now=self.now)["duplicate"])
        self.assert_empty_finance()

    def test_unpaid_optional_identity_fields_are_independent_but_supplied_values_must_match(self):
        for index, additions in enumerate(({"trade_type": "JSAPI"}, {"payer": {"openid": OPENID}})):
            with self.subTest(additions=additions):
                _public, row = self.create_order(key=f"optional-unpaid-{index}")
                payment.admit_payment_submission(row["id"], now=self.now)
                body = {"appid": APP_ID, "mchid": "1900000109", "out_trade_no": row["merchant_order_no"],
                        "trade_state": "NOTPAY", **additions}
                result = self.payment_gateway.process_signed_payment_query_receipt(self.lookup(row), self.receipt(body), now=self.now)
                self.assertTrue(result["pending"])
                self.assertEqual(payment.get_order_for_user(row["id"], "jsapi-user")["payment_status"], "pending")
        self.assert_empty_finance()

    def test_api_export_rejects_provider_signature_before_any_relay(self):
        _public, row = self.create_order()
        requests = []
        def handler(request):
            requests.append(request)
            response = self.response(self.provider_body(row))
            response.headers["Wechatpay-Signature"] = "A" * 342 + "=="
            return response
        with self.api_gateway(handler) as gateway:
            with self.assertRaisesRegex(direct.DirectPaymentGatewayError, "RESPONSE_UNVERIFIED"):
                gateway.export_payment_query_receipt(self.lookup(row))
        self.assertEqual(len(requests), 1)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM payment_events")["n"], 0)

    def test_independent_payment_verification_rejects_forged_body_headers_and_verified_flags(self):
        _public, row = self.create_order()
        body = self.provider_body(row)
        valid = self.receipt(body)
        mutations = []
        forged = copy.deepcopy(valid)
        forged["body_b64"] = base64.b64encode(json.dumps({**body, "amount": {"total": 1, "currency": "CNY"}}).encode()).decode()
        mutations.append(forged)
        for field, value in (("Wechatpay-Serial", "FEDCBA9876543210"),
                             ("Wechatpay-Nonce", "different-nonce"),
                             ("Wechatpay-Timestamp", str(int(self.now.timestamp()) - 301)),
                             ("Wechatpay-Signature", "A" * 342 + "==")):
            forged = copy.deepcopy(valid)
            forged["headers"][field] = value
            mutations.append(forged)
        mutations.append({**valid, "response_verified": True})
        for receipt in mutations:
            with self.subTest(receipt_fields=sorted(receipt)):
                with self.assertRaises(direct.DirectPaymentGatewayError):
                    self.payment_gateway.process_signed_payment_query_receipt(self.lookup(row), receipt, now=self.now)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM payment_events")["n"], 0)
        self.assert_empty_finance()

    def test_signed_wrong_order_is_rejected_before_local_writes(self):
        _public, row = self.create_order()
        with self.assertRaisesRegex(direct.DirectPaymentGatewayError, "RESPONSE_MISMATCH"):
            self.payment_gateway.process_signed_payment_query_receipt(
                self.lookup(row), self.receipt(self.provider_body(row, out_trade_no="another-order")), now=self.now
            )
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM payment_events")["n"], 0)

    def test_success_still_requires_original_payer_and_grants_exactly_once(self):
        _public, row = self.create_order()
        payment.admit_payment_submission(row["id"], now=self.now)
        receipt = self.receipt(self.provider_body(row))
        self.assertTrue(self.payment_gateway.process_signed_payment_query_receipt(self.lookup(row), receipt, now=self.now)["ok"])
        self.assertTrue(self.payment_gateway.process_signed_payment_query_receipt(self.lookup(row), receipt, now=self.now)["duplicate"])
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM payment_cash_ledger WHERE entry_type='payment_received'")["n"], 1)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM payment_entitlement_ledger")["n"], 1)

    def test_success_wrong_payer_retains_cash_truth_but_never_grants(self):
        _public, row = self.create_order()
        payment.admit_payment_submission(row["id"], now=self.now)
        result = self.payment_gateway.process_signed_payment_query_receipt(
            self.lookup(row), self.receipt(self.provider_body(row, payer={"openid": "another-payer"})), now=self.now
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "PAYMENT_ORDER_MISMATCH")
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM payment_entitlement_ledger")["n"], 0)

    def test_close_uses_one_signed_post_and_only_later_closed_query_changes_order(self):
        _public, row = self.create_order()
        payment.admit_payment_submission(row["id"], now=self.now)
        requests = []
        def handler(request):
            requests.append(request)
            if request.method == "POST":
                self.assertTrue(request.url.path.endswith("/" + row["merchant_order_no"] + "/close"))
                self.assertEqual(json.loads(request.content), {"mchid": "1900000109"})
                fields = dict(re.findall(r'(\w+)="([^"]*)"', request.headers["authorization"]))
                signed = f"POST\n{request.url.raw_path.decode()}\n{fields['timestamp']}\n{fields['nonce_str']}\n".encode() + request.content + b"\n"
                self.merchant_private.public_key().verify(base64.b64decode(fields["signature"]), signed,
                                                         padding.PKCS1v15(), hashes.SHA256())
                return self.response({}, status=204, raw=b"")
            return self.response({"appid": APP_ID, "mchid": "1900000109", "out_trade_no": row["merchant_order_no"], "trade_state": "CLOSED"})
        with self.api_gateway(handler) as gateway:
            self.assertIsNone(gateway.close_unpaid_payment(self.lookup(row)))
            self.assertEqual(payment.get_order_for_user(row["id"], "jsapi-user")["payment_status"], "pending")
            receipt = gateway.export_payment_query_receipt(self.lookup(row))
        self.payment_gateway.process_signed_payment_query_receipt(self.lookup(row), receipt, now=self.now)
        self.assertEqual([request.method for request in requests], ["POST", "GET"])
        self.assertEqual(payment.get_order_for_user(row["id"], "jsapi-user")["payment_status"], "failed")
        self.assert_empty_finance()

    def test_close_timeout_bad_signature_and_non204_do_not_retry_or_settle(self):
        _public, row = self.create_order()
        payment.admit_payment_submission(row["id"], now=self.now)
        for scenario in ("timeout", "signature", "status", "body"):
            requests = []
            def handler(request):
                requests.append(request)
                if scenario == "timeout":
                    raise httpx.ReadTimeout("synthetic timeout", request=request)
                response = self.response({}, status=200 if scenario == "status" else 204,
                                         raw=b"extra" if scenario == "body" else b"")
                if scenario == "signature":
                    response.headers["Wechatpay-Signature"] = "A" * 342 + "=="
                return response
            with self.subTest(scenario=scenario), self.api_gateway(handler) as gateway:
                with self.assertRaises(direct.DirectPaymentGatewayError):
                    gateway.close_unpaid_payment(self.lookup(row))
            self.assertEqual(len(requests), 1)
            self.assertEqual(payment.get_order_for_user(row["id"], "jsapi-user")["payment_status"], "pending")
        self.assert_empty_finance()

    def test_unpaid_query_relaxation_does_not_apply_to_callbacks_or_wrong_trade_type(self):
        _public, row = self.create_order()
        body = self.provider_body(row, trade_state="CLOSED")
        del body["payer"]
        raw, headers, now = fixtures.DirectPaymentGatewayTests._wechat_callback(self, body, "TRANSACTION.CLOSED")
        with self.assertRaisesRegex(direct.DirectPaymentGatewayError, "PAYER_INVALID"):
            self.gateway.process_callback(raw, headers, now=now)
        unsigned_type = {"appid": APP_ID, "mchid": "1900000109", "out_trade_no": row["merchant_order_no"],
                         "trade_state": "CLOSED", "trade_type": "NATIVE"}
        result = self.payment_gateway.process_signed_payment_query_receipt(self.lookup(row), self.receipt(unsigned_type), now=self.now)
        self.assertEqual(result["code"], "PAYMENT_ORDER_MISMATCH")
        self.assert_empty_finance()

    def test_native_order_public_method_and_query_compatibility(self):
        public = payment.create_order("jsapi-user", "credit_package", "starter", idempotency_key="native-original-001",
                                      app_id=APP_ID, prod_mode=True, provider_name="wechatpay_direct", now=self.now)
        self.assertEqual(public["payment_method"], "native")
        row = dict(db.fetchone("SELECT * FROM payment_orders WHERE id=?", (public["id"],)))
        body = {"appid": APP_ID, "mchid": "1900000109", "out_trade_no": row["merchant_order_no"], "trade_state": "NOTPAY"}
        result = self.payment_gateway.process_signed_payment_query_receipt(self.lookup(row), self.receipt(body), now=self.now)
        self.assertEqual(result, {"ok": True, "pending": True})
        self.assert_empty_finance()


if __name__ == "__main__":
    unittest.main()
