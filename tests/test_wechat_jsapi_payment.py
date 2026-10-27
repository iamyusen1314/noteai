"""Offline JSAPI contract tests; all provider I/O uses synthetic signed data."""

import base64
import importlib
import json
import os
import re
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
import direct_payment_gateways as direct
import payment_contract as payment
from tests import test_direct_payment_gateways as fixtures

db = importlib.import_module("db")
billing = importlib.import_module("billing")
APP_ID = "wxSyntheticApp01"
OPENID = "synthetic-jsapi-openid"


class WeChatJsapiPaymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wechat_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.merchant_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        self.old_db_path = db._DB_PATH
        self.old_database_url = os.environ.pop("DATABASE_URL", None)
        self.temp = tempfile.TemporaryDirectory()
        db._DB_PATH = Path(self.temp.name) / "jsapi.db"
        db.init_db()
        billing.clear_active_usage()
        self.now = datetime.fromtimestamp(1788573600, tz=timezone.utc)
        db.execute(
            "INSERT INTO users(id,username,email,password_hash,password_salt,created_at) "
            "VALUES(?,?,?,?,?,?)",
            ("jsapi-user", "jsapi_user", "jsapi@example.com", "hash", "salt", self.now.isoformat()),
        )
        billing.get_subscription("jsapi-user")
        self.transport = fixtures.FakeTransport()
        self.gateway = self.gateway_for(self.transport)

    def tearDown(self):
        billing.clear_active_usage()
        db._DB_PATH = self.old_db_path
        if self.old_database_url is not None:
            os.environ["DATABASE_URL"] = self.old_database_url
        self.temp.cleanup()

    def gateway_for(self, transport):
        return direct.WeChatPayGateway(
            app_id=APP_ID, merchant_id="1900000109",
            platform_certificate_serial="0123456789ABCDEF",
            platform_public_key_pem=fixtures.public_pem(self.wechat_private),
            api_v3_key=b"synthetic-api-v3-key-material-00",
            callback_url="https://noteaipro.com/payments/wechat/callback",
            prod_mode=True, transport=transport,
        )

    def create_order(self, key="jsapi-order-001", openid=OPENID):
        payer_hash = payment.wechat_jsapi_payer_identity_hash(APP_ID, openid)
        value = payment.create_order(
            "jsapi-user", "credit_package", "starter", idempotency_key=key,
            app_id=APP_ID, prod_mode=True, provider_name="wechatpay_direct",
            wechat_jsapi_payer_hash=payer_hash, now=self.now,
        )
        return value, dict(db.fetchone("SELECT * FROM payment_orders WHERE id=?", (value["id"],)))

    def provider_body(self, row, **changes):
        result = {
            "appid": APP_ID, "mchid": "1900000109",
            "out_trade_no": row["merchant_order_no"],
            "transaction_id": "synthetic-jsapi-transaction",
            "trade_state": "SUCCESS", "trade_type": "JSAPI",
            "success_time": "2026-09-05T01:59:59Z",
            "amount": {"total": 1200, "currency": "CNY"},
            "payer": {"openid": OPENID},
        }
        result.update(changes)
        return result

    def response(self, body):
        return direct.VerifiedDirectResponse(
            provider_name="wechatpay_direct", body=body,
            raw_body=json.dumps(body, separators=(",", ":")).encode(),
            signature="synthetic-verified-signature", verified_at=int(self.now.timestamp()),
            response_verified=True,
        )

    def test_jsapi_payer_scope_idempotency_and_transient_request(self):
        public, row = self.create_order()
        self.assertEqual(self.create_order()[0]["id"], public["id"])
        self.assertNotIn("wechat_jsapi_payer_hash", public)
        self.assertNotIn(OPENID, json.dumps(row))
        self.assertNotEqual(
            row["wechat_jsapi_payer_hash"],
            payment.wechat_jsapi_payer_identity_hash("wxOtherSynthetic", OPENID),
        )
        with self.assertRaisesRegex(payment.PaymentContractError, "IDEMPOTENCY_CONFLICT"):
            self.create_order(openid="different-payer")
        with self.assertRaisesRegex(payment.PaymentContractError, "IDEMPOTENCY_CONFLICT"):
            payment.create_order(
                "jsapi-user", "credit_package", "starter", idempotency_key="jsapi-order-001",
                app_id=APP_ID, prod_mode=True, provider_name="wechatpay_direct", now=self.now,
            )
        for openid in ("", "different-payer"):
            with self.assertRaises(payment.PaymentContractError):
                payment.provider_payment_request(row, device_ip="", wechat_jsapi_openid=openid)
        request = payment.provider_payment_request(row, device_ip="", wechat_jsapi_openid=OPENID)
        self.assertEqual(request["payment_method"], "jsapi")
        self.assertEqual(request["payer_openid"], OPENID)
        for forbidden in ("user_id", "subject_hash", "app_id_hash", "wechat_jsapi_payer_hash"):
            self.assertNotIn(forbidden, request)
        with self.assertRaises(Exception):
            db.execute("UPDATE payment_orders SET wechat_jsapi_payer_hash=NULL WHERE id=?", (row["id"],))

    def test_jsapi_request_and_bridge_signature_use_merchant_rsa_once(self):
        _public, row = self.create_order()
        requests = []

        def handler(request):
            requests.append(request)
            self.assertEqual(request.url.path, "/v3/pay/transactions/jsapi")
            fields = dict(re.findall(r'(\w+)="([^"]*)"', request.headers["authorization"]))
            signed = (
                f"POST\n{request.url.raw_path.decode()}\n{fields['timestamp']}\n{fields['nonce_str']}\n".encode()
                + request.content + b"\n"
            )
            self.merchant_private.public_key().verify(
                base64.b64decode(fields["signature"]), signed, padding.PKCS1v15(), hashes.SHA256()
            )
            payload = json.loads(request.content)
            self.assertEqual(payload["payer"], {"openid": OPENID})
            self.assertEqual(payload["amount"], {"total": 1200, "currency": "CNY"})
            expiry = datetime.fromisoformat(payload["time_expire"])
            self.assertLess(abs((expiry - datetime.now(timezone.utc)).total_seconds() - 900), 5)
            raw = b'{"prepay_id":"synthetic-prepay-001"}'
            signature = self.wechat_private.sign(
                f"{fields['timestamp']}\nresponse-nonce\n".encode() + raw + b"\n",
                padding.PKCS1v15(), hashes.SHA256(),
            )
            return httpx.Response(200, content=raw, headers={
                "Content-Type": "application/json", "Wechatpay-Timestamp": fields["timestamp"],
                "Wechatpay-Nonce": "response-nonce", "Wechatpay-Serial": "0123456789ABCDEF",
                "Wechatpay-Signature": base64.b64encode(signature).decode(),
            })

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            transport = direct.HttpxWeChatPayTransport(
                app_id=APP_ID, merchant_id="1900000109", merchant_certificate_serial="FEDCBA9876543210",
                merchant_private_key_pem=self.merchant_private.private_bytes(
                    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
                ).decode(), platform_verifier_id="0123456789ABCDEF",
                platform_public_key_pem=fixtures.public_pem(self.wechat_private), client=client,
                clock=lambda: self.now, nonce_factory=lambda: "request-nonce",
            )
            result = self.gateway_for(transport).create_payment(
                payment.provider_payment_request(row, device_ip="", wechat_jsapi_openid=OPENID)
            )
        checkout = json.loads(result.checkout_token)
        self.assertEqual((checkout["channel"], checkout["kind"]), ("wechatpay_jsapi", "bridge"))
        params = checkout["params"]
        self.assertEqual(params["signType"], "RSA")
        message = f"{APP_ID}\n{params['timeStamp']}\n{params['nonceStr']}\n{params['package']}\n".encode()
        self.merchant_private.public_key().verify(
            base64.b64decode(params["paySign"]), message, padding.PKCS1v15(), hashes.SHA256()
        )
        self.assertEqual(len(requests), 1)
        self.assertNotIn(OPENID, result.checkout_token)
        self.assertNotIn("synthetic-prepay", repr(result))
        self.assertTrue(payment.admit_payment_submission(row["id"], now=self.now))
        marked = payment.mark_payment_submission(row["id"], result, now=self.now)
        self.assertEqual(marked["payment_status"], "pending")
        self.assertEqual(marked["entitlement_status"], "pending")

    def test_jsapi_submission_rejects_missing_or_wrong_payer_binding(self):
        for index, changes in enumerate(({}, {"wechat_trade_type": "NATIVE"}, {"wechat_jsapi_payer_hash": "0" * 64})):
            with self.subTest(changes=changes):
                _public, row = self.create_order(key=f"jsapi-mark-{index}")
                self.assertTrue(payment.admit_payment_submission(row["id"], now=self.now))
                result = payment.ProviderPaymentResult(
                    merchant_order_no=row["merchant_order_no"], provider_payment_id=None,
                    status="pending", amount_fen=1200, app_id=APP_ID, prod_mode=True,
                    response_verified=True, provider_name="wechatpay_direct",
                    wechat_trade_type="JSAPI" if index else "",
                    wechat_jsapi_payer_hash=row["wechat_jsapi_payer_hash"] if index else None,
                )
                with self.assertRaisesRegex(payment.PaymentContractError, "RESPONSE_MISMATCH"):
                    payment.mark_payment_submission(row["id"], replace(result, **changes), now=self.now)
                self.assertFalse(payment.admit_payment_submission(row["id"], now=self.now))
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS c FROM payment_entitlement_ledger")["c"], 0)

    def test_verified_jsapi_callback_and_query_grant_once(self):
        _public, row = self.create_order()
        self.assertTrue(payment.admit_payment_submission(row["id"], now=self.now))
        payment.mark_payment_submission_unknown(row["id"], now=self.now)
        body = self.provider_body(row)
        raw, headers, now = fixtures.DirectPaymentGatewayTests._wechat_callback(self, body, "TRANSACTION.SUCCESS")
        callback = self.gateway.authenticate_callback(raw, headers, now=now)
        self.assertEqual(callback.event.wechat_trade_type, "JSAPI")
        self.assertEqual(callback.event.wechat_jsapi_payer_hash, row["wechat_jsapi_payer_hash"])
        self.assertTrue(self.gateway.process_callback(raw, headers, now=now)["ok"])
        self.assertTrue(self.gateway.process_callback(raw, headers, now=now)["duplicate"])
        self.transport.responses.append(self.response(body))
        result = self.gateway.process_payment_query(
            payment.ProviderPaymentLookup(row["merchant_order_no"], expected_amount_fen=1200), now=now
        )
        self.assertTrue(result["already_terminal"])
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS c FROM payment_cash_ledger WHERE entry_type='payment_received'")["c"], 1)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS c FROM payment_entitlement_ledger")["c"], 1)
        self.assertEqual(payment.get_order_for_user(row["id"], "jsapi-user")["entitlement_status"], "applied")

    def test_jsapi_success_query_mismatch_cannot_grant(self):
        for index, changes in enumerate((
            {"payer": {"openid": "wrong-payer"}}, {"trade_type": "NATIVE"},
            {"trade_type": ""}, {"payer": {}},
        )):
            with self.subTest(changes=changes):
                _public, row = self.create_order(key=f"jsapi-query-{index}")
                self.assertTrue(payment.admit_payment_submission(row["id"], now=self.now))
                self.transport.responses.append(self.response(self.provider_body(row, **changes)))
                try:
                    result = self.gateway.process_payment_query(
                        payment.ProviderPaymentLookup(row["merchant_order_no"], expected_amount_fen=1200), now=self.now
                    )
                    self.assertFalse(result["ok"])
                except direct.DirectPaymentGatewayError as exc:
                    self.assertEqual(exc.code, "PAYMENT_PROVIDER_PAYER_INVALID")
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS c FROM payment_cash_ledger WHERE entry_type='payment_received'")["c"], 0)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS c FROM payment_entitlement_ledger")["c"], 0)

    def test_jsapi_callback_wrong_payer_records_unmatched_cash_without_entitlement(self):
        _public, row = self.create_order()
        self.assertTrue(payment.admit_payment_submission(row["id"], now=self.now))
        raw, headers, now = fixtures.DirectPaymentGatewayTests._wechat_callback(
            self, self.provider_body(row, payer={"openid": "wrong-payer"}), "TRANSACTION.SUCCESS"
        )
        result = self.gateway.process_callback(raw, headers, now=now)
        self.assertEqual(result["code"], "PAYMENT_ORDER_MISMATCH")
        self.assertEqual(payment.get_order_for_user(row["id"], "jsapi-user")["payment_status"], "needs_manual")
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS c FROM payment_cash_ledger WHERE entry_type='payment_received_unmatched'")["c"], 1)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS c FROM payment_entitlement_ledger")["c"], 0)
        self.assertTrue(self.gateway.process_callback(raw, headers, now=now)["duplicate"])


if __name__ == "__main__":
    unittest.main()
