"""ASGI JSAPI recovery through independently verified, synthetic Payment receipts."""
import base64
import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import unittest
from unittest import mock

import httpx
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

from tests import test_wechat_jsapi_api as fixtures

api, db, payment = fixtures.api, fixtures.db, fixtures.payment
direct = fixtures.direct
import payment_runtime
import wechat_payment_reconcile as recovery

INTERNAL = "/internal/payments/wechat/query-receipt"


class NoOutboundTransport:
    def request(self, *_args, **_kwargs):
        raise AssertionError("Payment must not perform outbound I/O")

    def reconciliation(self, *_args, **_kwargs):
        raise AssertionError("Payment must not fetch provider bills")


class WechatJsapiReconcileApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.WechatJsapiApiTests.setUpClass()

    def setUp(self):
        # Composition reuses isolation, real users/sessions and OAuth without
        # inheriting/rerunning the original API tests.
        self.fixture = fixtures.WechatJsapiApiTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.client, self.provider = self.fixture.client, self.fixture.provider
        stack = self.fixture.stack
        stack.enter_context(mock.patch.dict(os.environ, {
            "NOTEAI_WECHATPAY_MERCHANT_PRIVATE_KEY_B64": "",
            "NOTEAI_WECHATPAY_MERCHANT_CERTIFICATE_SERIAL": "",
        }))
        gateway = direct.WeChatPayGateway(
            app_id=fixtures.APP_ID, merchant_id="1900000109",
            platform_certificate_serial="0123456789ABCDEF",
            platform_public_key_pem=fixtures.payment_fixtures.public_pem(self.fixture.wechat_private),
            api_v3_key=None, callback_url="https://noteaipro.com/payments/wechat/callback",
            prod_mode=True, transport=NoOutboundTransport(),
        )
        stack.enter_context(mock.patch.object(payment_runtime, "_callback_available", return_value=True))
        stack.enter_context(mock.patch.object(payment_runtime, "_direct_callback_gateway", return_value=gateway))
        self.payment_client = TestClient(payment_runtime.app, client=("127.0.0.1", 48001))
        self.addCleanup(self.payment_client.close)
        self.original_relay = recovery.relay_receipt
        self.relay = stack.enter_context(mock.patch.object(recovery, "relay_receipt", side_effect=self.deliver))

    def order(self, key="recovery-api-order-001", *, native=False):
        context = None if native else self.fixture.context(key=key)
        response = self.fixture.order(context, key=key)
        self.assertEqual(response.status_code, 200, response.text)
        return dict(db.fetchone("SELECT * FROM payment_orders WHERE id=?", (response.json()["order"]["id"],)))

    def body(self, row, state="SUCCESS"):
        result = {"appid": fixtures.APP_ID, "mchid": "1900000109",
                  "out_trade_no": row["merchant_order_no"], "trade_state": state}
        if state not in {"NOTPAY", "CLOSED"}:
            result.update({"trade_type": "JSAPI", "payer": {"openid": fixtures.OPENID},
                           "amount": {"total": 1200, "currency": "CNY"}})
        if state == "SUCCESS":
            result.update({"transaction_id": "synthetic-recovery-" + row["id"].replace("-", ""),
                           "success_time": self.fixture.now.isoformat()})
        return result

    def receipt(self, body):
        raw = json.dumps(body, separators=(",", ":")).encode()
        stamp, nonce = str(int(datetime.now(timezone.utc).timestamp())), "synthetic-recovery-response-nonce"
        signature = self.fixture.wechat_private.sign(
            f"{stamp}\n{nonce}\n".encode() + raw + b"\n", padding.PKCS1v15(), hashes.SHA256())
        return {"body_b64": base64.b64encode(raw).decode(), "headers": {
            "Wechatpay-Timestamp": stamp, "Wechatpay-Nonce": nonce,
            "Wechatpay-Serial": "0123456789ABCDEF",
            "Wechatpay-Signature": base64.b64encode(signature).decode(),
            "Wechatpay-Signature-Type": "WECHATPAY2-SHA256-RSA2048",
        }}

    def deliver(self, user_id, order_id, receipt):
        response = self.payment_client.post(INTERNAL,
            json={"user_id": user_id, "order_id": order_id, "receipt": receipt})
        if response.status_code != 200 or response.json().get("ok") is not True:
            raise recovery.ReconciliationError("PAYMENT_QUERY_RESULT_UNCONFIRMED")

    def refresh(self, row, close=False, **request_options):
        headers = request_options.pop("headers", self.fixture.headers())
        return self.client.post("/payments/orders/" + row["id"] + "/refresh",
                                headers=headers, json={"close_unpaid": close}, **request_options)

    def status(self, row):
        return db.fetchone("SELECT payment_status FROM payment_orders WHERE id=?", (row["id"],))["payment_status"]

    def assert_empty_finance(self):
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM payment_cash_ledger")["n"], 0)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM payment_entitlement_ledger")["n"], 0)

    def test_success_receipt_settles_once_and_terminal_refresh_never_requeries(self):
        row = self.order()
        receipt = self.receipt(self.body(row))
        self.provider.export_payment_query_receipt.return_value = receipt
        response = self.refresh(row)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["order"]["entitlement_status"], "applied")
        self.assertEqual(self.refresh(row).status_code, 200)
        # A genuine duplicate relay is also harmless independently of API's
        # terminal short-circuit.
        self.deliver(self.fixture.owner, row["id"], receipt)
        self.provider.export_payment_query_receipt.assert_called_once()
        self.provider.create_payment.assert_called_once()
        self.provider.close_unpaid_payment.assert_not_called()
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM payment_cash_ledger WHERE entry_type='payment_received'")["n"], 1)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM payment_entitlement_ledger")["n"], 1)

    def test_explicit_notpay_close_requires_later_signed_closed_without_payer(self):
        row = self.order()
        self.provider.export_payment_query_receipt.side_effect = [
            self.receipt(self.body(row, "NOTPAY")), self.receipt(self.body(row, "CLOSED"))]
        response = self.refresh(row, close=True)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(response.json()["order"]["payment_status"], {"failed", "closed"})
        self.assertEqual(self.provider.export_payment_query_receipt.call_count, 2)
        self.provider.close_unpaid_payment.assert_called_once()
        self.assertEqual(self.refresh(row, close=True).status_code, 200)
        self.assertEqual(self.provider.export_payment_query_receipt.call_count, 2)
        self.provider.create_payment.assert_called_once()
        self.assert_empty_finance()

    def test_unknown_close_and_userpaying_keep_original_pending_without_new_create(self):
        for index, state in enumerate(("NOTPAY", "USERPAYING")):
            with self.subTest(state=state):
                row = self.order(key=f"recovery-unknown-{index}")
                self.provider.export_payment_query_receipt.side_effect = None
                self.provider.export_payment_query_receipt.return_value = self.receipt(self.body(row, state))
                self.provider.export_payment_query_receipt.reset_mock()
                self.provider.close_unpaid_payment.reset_mock()
                self.provider.close_unpaid_payment.side_effect = TimeoutError("synthetic close outcome unknown")
                creates = self.provider.create_payment.call_count
                response = self.refresh(row, close=True)
                self.assertEqual(response.status_code, 503 if state == "NOTPAY" else 200, response.text)
                self.assertEqual(self.status(row), "pending")
                self.assertEqual(self.refresh(row, close=True).status_code, 429)
                self.provider.export_payment_query_receipt.assert_called_once()
                self.assertEqual(self.provider.close_unpaid_payment.call_count, 1 if state == "NOTPAY" else 0)
                self.assertEqual(self.provider.create_payment.call_count, creates)
        self.assert_empty_finance()

    def test_cooldown_is_durable_across_requests_and_releases_only_after_15_seconds(self):
        row = self.order()
        self.provider.export_payment_query_receipt.return_value = self.receipt(self.body(row, "NOTPAY"))
        self.assertEqual(self.refresh(row).status_code, 200)
        stored = db.fetchone("SELECT wechat_jsapi_last_query_at FROM payment_orders WHERE id=?", (row["id"],))["wechat_jsapi_last_query_at"]
        another_client = TestClient(api.app)
        self.addCleanup(another_client.close)
        repeated = another_client.post("/payments/orders/" + row["id"] + "/refresh",
                                       headers=self.fixture.headers(), json={"close_unpaid": False})
        self.assertEqual(repeated.status_code, 429, repeated.text)
        self.assertGreater(int(repeated.headers["Retry-After"]), 0)
        self.provider.export_payment_query_receipt.assert_called_once()
        with mock.patch.object(recovery, "datetime") as clock:
            clock.now.return_value = datetime.fromtimestamp(stored + 15, tz=timezone.utc)
            self.assertEqual(self.refresh(row).status_code, 200)
        self.assertEqual(self.provider.export_payment_query_receipt.call_count, 2)
        self.assertEqual(db.fetchone("SELECT wechat_jsapi_last_query_at FROM payment_orders WHERE id=?", (row["id"],))["wechat_jsapi_last_query_at"], stored + 15)
        self.provider.create_payment.assert_called_once()

    def test_owner_native_strict_bool_origin_auth_and_paused_checkout_boundaries(self):
        row, native = self.order(), self.order(key="recovery-native-order", native=True)
        self.assertEqual(self.refresh(row, headers=self.fixture.headers(user=self.fixture.other)).status_code, 404)
        self.assertEqual(self.refresh(native).status_code, 409)
        for value in ("true", 1, None):
            self.assertEqual(self.refresh(row, close=value).status_code, 422)
        self.assertEqual(self.refresh(row, headers={"Origin": "https://noteaipro.com"}).status_code, 401)
        self.assertEqual(self.refresh(row, headers={**self.fixture.headers(), "Origin": "https://attacker.invalid"}).status_code, 403)
        self.assertEqual(self.client.get("/payments/orders/" + row["id"] + "/refresh", headers=self.fixture.headers()).status_code, 404)
        self.provider.export_payment_query_receipt.assert_not_called()
        self.provider.export_payment_query_receipt.return_value = self.receipt(self.body(row, "NOTPAY"))
        with mock.patch.dict(os.environ, {"NOTEAI_PAYMENT_ORDERING_ENABLED": "0", "NOTEAI_WECHAT_JSAPI_ENABLED": "0"}):
            response = self.refresh(row)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.status(row), "pending")
        self.assertEqual(self.provider.create_payment.call_count, 2)

    def test_internal_rejects_remote_peer_forgery_extra_flags_and_wrong_identity(self):
        row = self.order()
        receipt = self.receipt(self.body(row))
        body = {"user_id": self.fixture.owner, "order_id": row["id"], "receipt": receipt}
        remote = TestClient(payment_runtime.app, client=("198.51.100.10", 48002))
        self.addCleanup(remote.close)
        self.assertEqual(remote.post(INTERNAL, json=body).status_code, 403)
        changed = copy.deepcopy(body)
        changed["receipt"]["body_b64"] = base64.b64encode(b'{"trade_state":"SUCCESS"}').decode()
        mutations = [changed, {**body, "receipt": {**receipt, "response_verified": True}},
                     {**body, "response_verified": True}, {**body, "user_id": self.fixture.other},
                     {**body, "receipt": self.receipt({**self.body(row), "out_trade_no": "different-order"})}]
        for mutation in mutations:
            with self.subTest(fields=sorted(mutation)):
                self.assertIn(self.payment_client.post(INTERNAL, json=mutation).status_code, (400, 404))
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM payment_events")["n"], 0)
        self.assertEqual(self.status(row), "pending")
        self.assert_empty_finance()

    def test_fixed_loopback_relay_rejects_redirect_type_size_and_unconfirmed_result(self):
        original_client = httpx.Client
        requests = []
        scenario = {"name": "success"}

        def handler(request):
            requests.append(request)
            self.assertEqual(str(request.url), recovery.RELAY_TARGET)
            self.assertEqual(request.method, "POST")
            self.assertNotIn("authorization", request.headers)
            self.assertEqual(set(json.loads(request.content)), {"user_id", "order_id", "receipt"})
            if scenario["name"] == "redirect":
                return httpx.Response(302, headers={"Location": "https://attacker.invalid"})
            if scenario["name"] == "type":
                return httpx.Response(200, headers={"Content-Type": "text/plain"}, content=b'{"ok":true}')
            if scenario["name"] == "size":
                return httpx.Response(200, headers={"Content-Type": "application/json"}, content=b"x" * 8193)
            return httpx.Response(200, json={"ok": scenario["name"] == "success"})

        def client(**kwargs):
            self.assertIs(kwargs["follow_redirects"], False)
            self.assertIs(kwargs["trust_env"], False)
            return original_client(transport=httpx.MockTransport(handler), **kwargs)

        with mock.patch.object(recovery.httpx, "Client", side_effect=client):
            self.original_relay("synthetic-owner", "00000000-0000-4000-8000-000000000001", {})
            for name in ("redirect", "type", "size", "unconfirmed"):
                scenario["name"] = name
                before = len(requests)
                with self.assertRaises(recovery.ReconciliationError):
                    self.original_relay("synthetic-owner", "00000000-0000-4000-8000-000000000001", {})
                self.assertEqual(len(requests), before + 1)
            before = len(requests)
            with self.assertRaises(recovery.ReconciliationError):
                self.original_relay("synthetic-owner", "00000000-0000-4000-8000-000000000001", {"body_b64": "x" * recovery.RECEIPT_BYTES})
            self.assertEqual(len(requests), before)

    def test_nginx_and_public_gate_expose_only_owner_refresh_not_internal_relay(self):
        root = Path(__file__).resolve().parents[1]
        locations = (root / "deploy/production/public-account.locations.conf").read_text()
        website = (root / "deploy/production/public-website.nginx.conf").read_text()
        match = re.search(r'location ~ "[^"\n]*/refresh\$" \{(.*?)\n\}', locations, re.S)
        self.assertIsNotNone(match)
        self.assertIn("limit_except POST { deny all; }", match[1])
        self.assertIn("client_max_body_size 8k;", match[1])
        self.assertNotIn(INTERNAL, locations + website)
        self.assertIn("location / { return 404; }", website)
        path = "/payments/orders/00000000-0000-4000-8000-000000000001/refresh"
        with mock.patch.dict(os.environ, {"NOTEAI_PAYMENT_ORDERING_ENABLED": "0", "NOTEAI_WECHAT_JSAPI_ENABLED": "0"}):
            self.assertTrue(api._public_product.allowed_route("POST", path))
        with mock.patch.dict(os.environ, {"NOTEAI_PAYMENT_CALLBACK_RELAY_ENABLED": "0"}):
            self.assertFalse(api._public_product.allowed_route("POST", path))
        self.assertEqual(self.client.post(INTERNAL, headers=self.fixture.headers(), json={}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
