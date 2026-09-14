import base64
import hashlib
import importlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qsl, urlencode

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "model"
if str(MODEL) not in sys.path:
    sys.path.insert(0, str(MODEL))

import direct_payment_gateways as direct
import payment_contract

db = importlib.import_module("db")
billing = importlib.import_module("billing")


class FakeTransport:
    def __init__(self):
        self.responses = []
        self.calls = []
        self.bill = None

    def request(self, provider_name, operation, payload):
        self.calls.append((provider_name, operation, dict(payload)))
        if not self.responses:
            raise AssertionError("unexpected request")
        return self.responses.pop(0)

    def reconciliation(self, provider_name, bill_date):
        self.calls.append((provider_name, "reconciliation", bill_date))
        if self.bill is None:
            raise AssertionError("unexpected reconciliation")
        return self.bill


def public_pem(private_key):
    return private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def order(provider):
    return {
        "merchant_order_no": "0123456789abcdef0123456789abcdef",
        "amount_fen": 100,
        "currency": "CNY",
        "product_kind": "credit_package",
        "product_id": "starter",
        "provider_mode": "live",
        "provider_name": provider,
        "device_ip": "203.0.113.10",
    }


def refund(provider):
    return {
        "merchant_refund_no": "NR_0123456789abcdef0123456789abcdef",
        "merchant_order_no": "0123456789abcdef0123456789abcdef",
        "provider_payment_id": "provider_payment_001",
        "amount_fen": 100,
        "currency": "CNY",
        "provider_mode": "live",
        "provider_name": provider,
        "reason_code": "customer_request",
    }


def wechat_trade_bill_source(
    *,
    refund_status="SUCCESS",
    summary_count="2",
    trade_date="2026-09-05",
    app_id="wxSyntheticApp01",
    merchant_id="1900000109",
):
    payment_values = [
        f"{trade_date} 10:00:00",
        app_id,
        merchant_id,
        "0",
        "",
        "42000000000000000000000000000001",
        order("wechatpay_direct")["merchant_order_no"],
        "synthetic-openid",
        "NATIVE",
        "SUCCESS",
        "OTHERS",
        "CNY",
        "1.00",
        "0.00",
        "0",
        "0",
        "0.00",
        "0.00",
        "",
        "",
        "NoteAI",
        "",
        "0.01",
        "0.60%",
        "1.00",
        "0.00",
        "",
    ]
    refund_values = [
        f"{trade_date} 11:00:00",
        app_id,
        merchant_id,
        "0",
        "",
        "42000000000000000000000000000001",
        order("wechatpay_direct")["merchant_order_no"],
        "synthetic-openid",
        "NATIVE",
        "REFUND",
        "OTHERS",
        "CNY",
        "0.00",
        "0.00",
        "50000000000000000000000000000001",
        refund("wechatpay_direct")["merchant_refund_no"],
        "1.00",
        "0.00",
        "ORIGINAL",
        refund_status,
        "NoteAI",
        "",
        "-0.01",
        "0.60%",
        "0.00",
        "1.00",
        "",
    ]
    summary_values = [summary_count, "1.00", "1.00", "0.00", "0.00", "1.00", "1.00"]
    return (
        "\ufeff"
        + ",".join(direct._WECHAT_TRADE_BILL_DETAIL_HEADER)
        + "\r\n"
        + ",".join("`" + value for value in payment_values)
        + "\r\n"
        + ",".join("`" + value for value in refund_values)
        + "\r\n\r\n"
        + ",".join(direct._WECHAT_TRADE_BILL_SUMMARY_HEADER)
        + "\r\n"
        + ",".join("`" + value for value in summary_values)
        + "\r\n"
    ).encode("utf-8")


def alipay_trade_bill_zip_source(*, trade_date="2026-09-05"):
    headers = [
        "支付宝交易号",
        "商户订单号",
        "业务类型",
        "商品名称",
        "创建时间",
        "完成时间",
        "订单金额（元）",
        "退款批次号/请求号",
        "备注",
    ]
    rows = [
        [
            "2026090522000000000000000001",
            order("alipay_direct")["merchant_order_no"],
            "交易",
            "NoteAI Pro starter",
            f"{trade_date} 09:59:00",
            f"{trade_date} 10:00:00",
            "1.00",
            "",
            "synthetic",
        ],
        [
            "2026090522000000000000000001",
            order("alipay_direct")["merchant_order_no"],
            "退款",
            "NoteAI Pro starter",
            f"{trade_date} 10:00:30",
            f"{trade_date} 10:01:00",
            "-1.00",
            refund("alipay_direct")["merchant_refund_no"],
            "synthetic",
        ],
    ]
    detail = (
        "#支付宝业务明细查询\r\n"
        + ",".join(headers)
        + "\r\n"
        + "\r\n".join(",".join(row) for row in rows)
        + "\r\n"
    ).encode("gb18030")
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("2088000000000001_20260905_业务明细.csv", detail)
        archive.writestr("2088000000000001_20260905_业务汇总.csv", b"synthetic")
    return output.getvalue()


class DirectPaymentGatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wechat_private = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        cls.alipay_private = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

    def setUp(self):
        self.wechat_transport = FakeTransport()
        self.wechat = direct.WeChatPayGateway(
            app_id="wxSyntheticApp01",
            merchant_id="1900000109",
            platform_certificate_serial="0123456789ABCDEF",
            platform_public_key_pem=public_pem(self.wechat_private),
            api_v3_key=b"synthetic-api-v3-key-material-00",
            callback_url="https://noteaipro.com/payments/wechat/callback",
            prod_mode=True,
            transport=self.wechat_transport,
        )
        self.alipay_transport = FakeTransport()
        self.alipay = direct.AlipayGateway(
            app_id="2026000000000001",
            seller_id="2088000000000001",
            alipay_public_key_pem=public_pem(self.alipay_private),
            callback_url="https://api.noteaipro.cn/payments/alipay/callback",
            prod_mode=True,
            transport=self.alipay_transport,
        )

    def test_pem_base64_decoder_accepts_only_canonical_single_line_input(self):
        pem = public_pem(self.wechat_private)
        encoded = base64.b64encode(pem.encode("ascii")).decode("ascii")
        self.assertEqual(direct.decode_pem_b64(encoded), pem)
        for malformed in (
            f'"{encoded}"',
            encoded + "\n",
            encoded.rstrip("="),
            "-----BEGIN PUBLIC KEY-----\\nsynthetic\\n",
            "not-base64",
            "",
        ):
            with self.subTest(malformed=malformed[:24]):
                with self.assertRaisesRegex(
                    direct.DirectPaymentGatewayError,
                    "PAYMENT_PROVIDER_KEY_INVALID",
                ):
                    direct.decode_pem_b64(malformed)

    def response(self, provider, body, verified=True, *, verified_at=1788573600):
        raw_body = json.dumps(
            body,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return direct.VerifiedDirectResponse(
            provider_name=provider,
            body=body,
            raw_body=raw_body,
            signature="synthetic-verified-response-signature",
            verified_at=verified_at,
            response_verified=verified,
        )

    def test_wechat_create_and_query_are_provider_bound(self):
        self.wechat_transport.responses.extend(
            [
                self.response(
                    "wechatpay_direct",
                    {"code_url": "weixin://wxpay/bizpayurl?pr=synthetic"},
                ),
                self.response(
                    "wechatpay_direct",
                    {
                        "appid": "wxSyntheticApp01",
                        "mchid": "1900000109",
                        "out_trade_no": order("wechatpay_direct")["merchant_order_no"],
                        "transaction_id": "provider_payment_001",
                        "trade_state": "SUCCESS",
                        "success_time": "2026-09-05T10:00:00+08:00",
                        "amount": {"total": 100, "currency": "CNY"},
                    },
                ),
            ]
        )
        created = self.wechat.create_payment(order("wechatpay_direct"))
        self.assertEqual(created.status, "pending")
        self.assertIsNone(created.provider_payment_id)
        checkout = json.loads(created.checkout_token)
        self.assertEqual(checkout["channel"], "wechatpay_native")
        create_payload = self.wechat_transport.calls[0][2]
        self.assertEqual(create_payload["amount"], {"total": 100, "currency": "CNY"})
        self.assertNotIn("device_ip", create_payload)

        queried = self.wechat.query_payment(
            payment_contract.ProviderPaymentLookup(
                merchant_order_no=order("wechatpay_direct")["merchant_order_no"]
            )
        )
        self.assertEqual(queried.status, "succeeded")
        self.assertEqual(queried.provider_payment_id, "provider_payment_001")

    def test_wechat_success_query_preserves_signed_financial_mismatch(self):
        order_no = order("wechatpay_direct")["merchant_order_no"]
        self.wechat_transport.responses.append(
            self.response(
                "wechatpay_direct",
                {
                    "appid": "wxSyntheticApp01",
                    "mchid": "1900000109",
                    "out_trade_no": order_no,
                    "transaction_id": "different_provider_payment",
                    "trade_state": "SUCCESS",
                    "success_time": "2026-09-05T10:00:00+08:00",
                    "amount": {"total": 101, "currency": "CNY"},
                },
            )
        )

        result = self.wechat.query_payment(
            payment_contract.ProviderPaymentLookup(
                merchant_order_no=order_no,
                provider_payment_id="expected_provider_payment",
                expected_amount_fen=100,
            )
        )

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.provider_payment_id, "different_provider_payment")
        self.assertEqual(result.amount_fen, 101)

    def test_wechat_http_transport_signs_once_and_verifies_exact_response(self):
        merchant_private = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        requests_seen = []

        def handler(request):
            requests_seen.append(request)
            fields = dict(
                re.findall(r'(\w+)="([^"]*)"', request.headers["authorization"])
            )
            message = (
                f"POST\n{request.url.raw_path.decode()}\n"
                f"{fields['timestamp']}\n{fields['nonce_str']}\n".encode("ascii")
                + request.content
                + b"\n"
            )
            merchant_private.public_key().verify(
                base64.b64decode(fields["signature"], validate=True),
                message,
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            self.assertEqual(fields["serial_no"], "FEDCBA9876543210")
            self.assertEqual(
                request.headers["wechatpay-serial"],
                "0123456789ABCDEF",
            )
            raw = b'{"code_url":"weixin://wxpay/bizpayurl?pr=synthetic"}'
            timestamp = fields["timestamp"]
            nonce = "response-nonce"
            signature = base64.b64encode(
                self.wechat_private.sign(
                    f"{timestamp}\n{nonce}\n".encode("ascii") + raw + b"\n",
                    padding.PKCS1v15(),
                    hashes.SHA256(),
                )
            ).decode("ascii")
            return httpx.Response(
                200,
                headers={
                    "Content-Type": "application/json",
                    "Wechatpay-Timestamp": timestamp,
                    "Wechatpay-Nonce": nonce,
                    "Wechatpay-Signature": signature,
                    "Wechatpay-Serial": "0123456789ABCDEF",
                    "Wechatpay-Signature-Type": "WECHATPAY2-SHA256-RSA2048",
                },
                content=raw,
            )

        client = httpx.Client(
            transport=httpx.MockTransport(handler),
            follow_redirects=False,
        )
        transport = direct.HttpxWeChatPayTransport(
            app_id="wxSyntheticApp01",
            merchant_id="1900000109",
            merchant_certificate_serial="FEDCBA9876543210",
            merchant_private_key_pem=merchant_private.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode("ascii"),
            platform_verifier_id="0123456789ABCDEF",
            platform_public_key_pem=public_pem(self.wechat_private),
            client=client,
            clock=lambda: datetime.fromtimestamp(1788573600, tz=timezone.utc),
            nonce_factory=lambda: "request-nonce",
        )
        gateway = direct.WeChatPayGateway(
            app_id="wxSyntheticApp01",
            merchant_id="1900000109",
            platform_certificate_serial="0123456789ABCDEF",
            platform_public_key_pem=public_pem(self.wechat_private),
            api_v3_key=b"synthetic-api-v3-key-material-00",
            callback_url="https://noteaipro.com/payments/wechat/callback",
            prod_mode=True,
            transport=transport,
        )
        result = gateway.create_payment(order("wechatpay_direct"))
        self.assertEqual(result.status, "pending")
        self.assertEqual(len(requests_seen), 1)
        self.assertEqual(
            requests_seen[0].url,
            httpx.URL("https://api.mch.weixin.qq.com/v3/pay/transactions/native"),
        )

    def test_direct_response_stream_has_absolute_deadline(self):
        class DripStream(httpx.SyncByteStream):
            def __iter__(self):
                yield b"{"
                yield b"}"

        ticks = iter((1.0, 15.0, 31.0))
        response = httpx.Response(200, stream=DripStream())
        try:
            with self.assertRaisesRegex(
                direct.DirectPaymentGatewayError,
                "PAYMENT_PROVIDER_TIMEOUT",
            ):
                direct._http_response_bytes(
                    response,
                    deadline=30.0,
                    monotonic_clock=lambda: next(ticks),
                )
        finally:
            response.close()

    def test_wechat_trade_bill_download_is_signed_hashed_and_parsed(self):
        merchant_private = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        source = wechat_trade_bill_source()
        requests_seen = []

        def handler(request):
            requests_seen.append(request)
            fields = dict(
                re.findall(r'(\w+)="([^"]*)"', request.headers["authorization"])
            )
            merchant_private.public_key().verify(
                base64.b64decode(fields["signature"], validate=True),
                (
                    f"GET\n{request.url.raw_path.decode()}\n"
                    f"{fields['timestamp']}\n{fields['nonce_str']}\n\n"
                ).encode("ascii"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            if request.url.path == "/v3/bill/tradebill":
                self.assertEqual(
                    request.url.query.decode(),
                    "bill_date=2026-09-05&bill_type=ALL",
                )
                raw = json.dumps(
                    {
                        "hash_type": "SHA1",
                        "hash_value": hashlib.sha1(source).hexdigest().upper(),
                        "download_url": (
                            "https://api.mch.weixin.qq.com/"
                            "v3/billdownload/file?token=synthetic-token"
                        ),
                    },
                    separators=(",", ":"),
                ).encode()
                timestamp = fields["timestamp"]
                nonce = "response-nonce"
                signature = base64.b64encode(
                    self.wechat_private.sign(
                        f"{timestamp}\n{nonce}\n".encode("ascii") + raw + b"\n",
                        padding.PKCS1v15(),
                        hashes.SHA256(),
                    )
                ).decode("ascii")
                return httpx.Response(
                    200,
                    headers={
                        "Content-Type": "application/json",
                        "Wechatpay-Timestamp": timestamp,
                        "Wechatpay-Nonce": nonce,
                        "Wechatpay-Signature": signature,
                        "Wechatpay-Serial": "0123456789ABCDEF",
                    },
                    content=raw,
                )
            self.assertEqual(
                str(request.url),
                "https://api.mch.weixin.qq.com/"
                "v3/billdownload/file?token=synthetic-token",
            )
            self.assertEqual(request.headers["accept-encoding"], "identity")
            self.assertNotIn("wechatpay-serial", request.headers)
            return httpx.Response(
                200,
                headers={"Content-Type": "text/plain"},
                content=source,
            )

        nonces = iter(("locator-nonce", "download-nonce"))
        transport = direct.HttpxWeChatPayTransport(
            app_id="wxSyntheticApp01",
            merchant_id="1900000109",
            merchant_certificate_serial="FEDCBA9876543210",
            merchant_private_key_pem=merchant_private.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode("ascii"),
            platform_verifier_id="0123456789ABCDEF",
            platform_public_key_pem=public_pem(self.wechat_private),
            client=httpx.Client(
                transport=httpx.MockTransport(handler),
                follow_redirects=False,
            ),
            clock=lambda: datetime.fromtimestamp(1788573600, tz=timezone.utc),
            nonce_factory=lambda: next(nonces),
        )
        bill = transport.reconciliation("wechatpay_direct", "2026-09-05")
        self.assertEqual(bill.source_bytes, source)
        self.assertEqual(bill.authentication_mode, "provider_sha1")
        self.assertEqual(
            tuple(bill.rows),
            (
                {
                    "kind": "payment",
                    "reference": order("wechatpay_direct")["merchant_order_no"],
                    "amount_fen": 100,
                    "status": "succeeded",
                },
                {
                    "kind": "refund",
                    "reference": refund("wechatpay_direct")["merchant_refund_no"],
                    "amount_fen": 100,
                    "status": "succeeded",
                },
            ),
        )
        self.assertEqual(len(requests_seen), 2)

    def test_wechat_trade_bill_rejects_schema_summary_and_manual_refund(self):
        parse_kwargs = {
            "expected_bill_date": "2026-09-05",
            "expected_app_id": "wxSyntheticApp01",
            "expected_merchant_id": "1900000109",
        }
        summary_mismatch = wechat_trade_bill_source(summary_count="3")
        with self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_PROVIDER_BILL_SUMMARY_MISMATCH",
        ):
            direct._parse_wechat_trade_bill(
                summary_mismatch,
                **parse_kwargs,
            )
        manual = wechat_trade_bill_source(refund_status="CHANGE")
        with self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_PROVIDER_BILL_REFUND_REQUIRES_MANUAL",
        ):
            direct._parse_wechat_trade_bill(
                manual,
                **parse_kwargs,
            )
        missing_prefix = wechat_trade_bill_source().replace(b"`CNY", b"CNY", 1)
        with self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_PROVIDER_BILL_SCHEMA_INVALID",
        ):
            direct._parse_wechat_trade_bill(
                missing_prefix,
                **parse_kwargs,
            )

        identity_mismatches = (
            wechat_trade_bill_source(trade_date="2026-09-04"),
            wechat_trade_bill_source(app_id="wxDifferentApp01"),
            wechat_trade_bill_source(merchant_id="1900000110"),
        )
        for mismatched in identity_mismatches:
            with self.subTest(source=hashlib.sha256(mismatched).hexdigest()):
                with self.assertRaisesRegex(
                    direct.DirectPaymentGatewayError,
                    "PAYMENT_PROVIDER_BILL_(?:DATE|IDENTITY)_MISMATCH",
                ):
                    direct._parse_wechat_trade_bill(
                        mismatched,
                        **parse_kwargs,
                    )

    def test_wechat_trade_bill_rejects_untrusted_url_and_digest_mismatch(self):
        merchant_private = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        transport = direct.HttpxWeChatPayTransport(
            app_id="wxSyntheticApp01",
            merchant_id="1900000109",
            merchant_certificate_serial="FEDCBA9876543210",
            merchant_private_key_pem=merchant_private.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode("ascii"),
            platform_verifier_id="0123456789ABCDEF",
            platform_public_key_pem=public_pem(self.wechat_private),
            client=httpx.Client(
                transport=httpx.MockTransport(
                    lambda _request: (_ for _ in ()).throw(
                        AssertionError("untrusted URL reached network")
                    )
                ),
                follow_redirects=False,
            ),
            clock=lambda: datetime.fromtimestamp(1788573600, tz=timezone.utc),
            nonce_factory=lambda: "request-nonce",
            monotonic_clock=lambda: 1.0,
        )
        for url in (
            "http://api.mch.weixin.qq.com/v3/billdownload/file?token=x",
            "https://example.invalid/v3/billdownload/file?token=x",
            "https://user@api.mch.weixin.qq.com/v3/billdownload/file?token=x",
            "https://api.mch.weixin.qq.com:444/v3/billdownload/file?token=x",
            "https://api.mch.weixin.qq.com/v3/other?token=x",
            "https://api.mch.weixin.qq.com/v3/billdownload/file?token=",
            "https://api.mch.weixin.qq.com/v3/billdownload/file?token=x#fragment",
        ):
            with self.subTest(url=url), self.assertRaisesRegex(
                direct.DirectPaymentGatewayError,
                "PAYMENT_PROVIDER_BILL_URL_INVALID",
            ):
                transport._download_trade_bill(url, deadline=30.0)

        locator = direct.VerifiedDirectResponse(
            provider_name="wechatpay_direct",
            body={
                "hash_type": "SHA1",
                "hash_value": hashlib.sha1(b"expected").hexdigest(),
                "download_url": (
                    "https://api.mch.weixin.qq.com/"
                    "v3/billdownload/file?token=synthetic-token"
                ),
            },
            raw_body=b"{}",
            signature="synthetic-signature",
            verified_at=1788573600,
            response_verified=True,
        )
        with patch.object(transport, "request", return_value=locator), patch.object(
            transport,
            "_download_trade_bill",
            return_value=b"different",
        ), self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_PROVIDER_BILL_DIGEST_MISMATCH",
        ):
            transport.reconciliation("wechatpay_direct", "2026-09-05")

    def test_wechat_refunded_payment_query_requires_refund_reconciliation(self):
        self.wechat_transport.responses.append(
            self.response(
                "wechatpay_direct",
                {
                    "appid": "wxSyntheticApp01",
                    "mchid": "1900000109",
                    "out_trade_no": order("wechatpay_direct")["merchant_order_no"],
                    "transaction_id": "provider_payment_001",
                    "trade_state": "REFUND",
                    "amount": {"total": 100, "currency": "CNY"},
                },
            )
        )
        with self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_PROVIDER_REFUND_RECONCILIATION_REQUIRED",
        ):
            self.wechat.query_payment(
                payment_contract.ProviderPaymentLookup(
                    merchant_order_no=order("wechatpay_direct")[
                        "merchant_order_no"
                    ]
                )
            )

    def test_wechat_full_refund_and_reconciliation(self):
        response = {
            "refund_id": "provider_refund_001",
            "out_refund_no": refund("wechatpay_direct")["merchant_refund_no"],
            "out_trade_no": refund("wechatpay_direct")["merchant_order_no"],
            "transaction_id": "provider_payment_001",
            "status": "PROCESSING",
            "create_time": "2026-09-05T10:00:00+08:00",
            "amount": {"refund": 100, "total": 100, "currency": "CNY"},
        }
        self.wechat_transport.responses.append(
            self.response(
                "wechatpay_direct",
                response,
                verified_at=1788659999,
            )
        )
        result = self.wechat.create_refund(refund("wechatpay_direct"))
        self.assertEqual(result.status, "pending")
        self.assertEqual(result.amount_fen, 100)
        self.assertEqual(result.provider_submitted_at, 1788573600)
        payload = self.wechat_transport.calls[0][2]
        self.assertEqual(payload["amount"]["refund"], payload["amount"]["total"])

        rows = (
            {
                "kind": "payment",
                "reference": order("wechatpay_direct")["merchant_order_no"],
                "amount_fen": 100,
                "status": "succeeded",
            },
            {
                "kind": "refund",
                "reference": refund("wechatpay_direct")["merchant_refund_no"],
                "amount_fen": 100,
                "status": "succeeded",
            },
        )
        self.wechat_transport.bill = direct.VerifiedDirectBill(
            provider_name="wechatpay_direct",
            bill_date="2026-09-05",
            source_bytes=b"synthetic-wechat-bill",
            rows=rows,
            authentication_mode="provider_sha1",
        )
        source, returned = self.wechat.reconciliation_rows("2026-09-05")
        self.assertEqual(source, b"synthetic-wechat-bill")
        self.assertEqual(returned, rows)

    def test_wechat_refund_query_preserves_submission_and_success_times(self):
        body = {
            "refund_id": "provider_refund_001",
            "out_refund_no": refund("wechatpay_direct")["merchant_refund_no"],
            "out_trade_no": refund("wechatpay_direct")["merchant_order_no"],
            "transaction_id": "provider_payment_001",
            "status": "SUCCESS",
            "create_time": "2026-09-05T10:00:00+08:00",
            "success_time": "2026-09-05T10:01:00+08:00",
            "amount": {"refund": 100, "total": 100, "currency": "CNY"},
        }
        self.wechat_transport.responses.append(
            self.response("wechatpay_direct", body)
        )
        result = self.wechat.query_refund(
            payment_contract.ProviderRefundLookup(
                merchant_refund_no=refund("wechatpay_direct")[
                    "merchant_refund_no"
                ],
                merchant_order_no=refund("wechatpay_direct")[
                    "merchant_order_no"
                ],
                provider_payment_id="provider_payment_001",
                provider_refund_id="provider_refund_001",
            )
        )
        self.assertEqual(
            result.provider_submitted_at,
            direct._iso_to_epoch("2026-09-05T10:00:00+08:00"),
        )
        self.assertEqual(
            result.provider_created_at,
            direct._iso_to_epoch("2026-09-05T10:01:00+08:00"),
        )

    def test_wechat_refund_requires_signed_body_create_time(self):
        base = {
            "refund_id": "provider_refund_001",
            "out_refund_no": refund("wechatpay_direct")["merchant_refund_no"],
            "out_trade_no": refund("wechatpay_direct")["merchant_order_no"],
            "transaction_id": "provider_payment_001",
            "status": "PROCESSING",
            "amount": {"refund": 100, "total": 100, "currency": "CNY"},
        }
        for invalid in (None, "2026-09-05 10:00:00", " 2026-09-05T10:00:00+08:00"):
            body = dict(base)
            if invalid is not None:
                body["create_time"] = invalid
            self.wechat_transport.responses.append(
                self.response(
                    "wechatpay_direct",
                    body,
                    verified_at=1788659999,
                )
            )
            with self.subTest(create_time=invalid), self.assertRaisesRegex(
                direct.DirectPaymentGatewayError,
                "PAYMENT_PROVIDER_RESPONSE_MISMATCH",
            ):
                self.wechat.create_refund(refund("wechatpay_direct"))

    def _wechat_callback(self, provider_body, event_type, *,
                         resource_nonce="0123456789ab", pretty=False):
        provider_body = dict(provider_body)
        if event_type in {"TRANSACTION.SUCCESS", "REFUND.SUCCESS"}:
            provider_body.setdefault("success_time", "2026-09-05T01:59:59Z")
        associated = "transaction"
        ciphertext = AESGCM(b"synthetic-api-v3-key-material-00").encrypt(
            resource_nonce.encode(),
            json.dumps(provider_body, sort_keys=pretty,
                       indent=2 if pretty else None, separators=(",", ":")).encode(),
            associated.encode(),
        )
        outer = {
            "id": "wechat_event_001",
            "create_time": "2026-09-05T02:00:00Z",
            "event_type": event_type,
            "resource": {
                "algorithm": "AEAD_AES_256_GCM",
                "ciphertext": base64.b64encode(ciphertext).decode(),
                "nonce": resource_nonce,
                "associated_data": associated,
            },
        }
        raw = json.dumps(outer, sort_keys=pretty, indent=2 if pretty else None,
                         separators=(",", ":")).encode()
        timestamp = "1788573600"
        nonce = "header-nonce-001"
        signature = self.wechat_private.sign(
            f"{timestamp}\n{nonce}\n".encode() + raw + b"\n",
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        headers = {
            "Wechatpay-Timestamp": timestamp,
            "Wechatpay-Nonce": nonce,
            "Wechatpay-Signature": base64.b64encode(signature).decode(),
            "Wechatpay-Serial": "0123456789ABCDEF",
        }
        now = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
        return raw, headers, now

    def test_wechat_callback_verifies_signature_and_decrypts_payment(self):
        raw, headers, now = self._wechat_callback(
            {
                "appid": "wxSyntheticApp01",
                "mchid": "1900000109",
                "out_trade_no": order("wechatpay_direct")["merchant_order_no"],
                "transaction_id": "provider_payment_001",
                "trade_state": "SUCCESS",
                "amount": {"total": 100, "currency": "CNY"},
            },
            "TRANSACTION.SUCCESS",
        )
        callback = self.wechat.authenticate_callback(raw, headers, now=now)
        self.assertEqual(callback.event.provider_name, "wechatpay_direct")
        self.assertEqual(callback.event.event_type, "payment.succeeded")
        self.assertEqual(callback.event.data["pay_amt"], "1.00")
        self.assertEqual(
            callback.event.created_time,
            direct._iso_to_epoch("2026-09-05T01:59:59Z"),
        )
        signature_input = (
            headers["Wechatpay-Timestamp"]
            + "\n"
            + headers["Wechatpay-Nonce"]
            + "\n"
        ).encode() + raw + b"\n"
        self.assertEqual(
            callback.signature_input_sha256,
            hashlib.sha256(signature_input).hexdigest(),
        )
        self.assertNotIn("provider_payment_001", repr(callback))

    def test_wechat_reencrypted_notification_is_idempotent_without_losing_facts(self):
        old_db_path = db._DB_PATH
        old_database_url = os.environ.pop("DATABASE_URL", None)
        temp = tempfile.TemporaryDirectory()
        try:
            db._DB_PATH = Path(temp.name) / "callback-identity.db"
            db.init_db()
            billing.clear_active_usage()
            now = datetime.fromtimestamp(1788573600, tz=timezone.utc)
            db.execute("INSERT INTO users(id,username,email,password_hash,password_salt,created_at) "
                       "VALUES(?,?,?,?,?,?)", ("u-redelivery", "redelivery", "test@example.invalid",
                                             "hash", "salt", now.isoformat()))
            billing.get_subscription("u-redelivery")
            created = payment_contract.create_order(
                "u-redelivery", "credit_package", "starter",
                idempotency_key="synthetic-redelivery-identity", app_id="wxSyntheticApp01",
                prod_mode=True, provider_name="wechatpay_direct", now=now)
            row = db.fetchone("SELECT * FROM payment_orders WHERE id=?", (created["id"],))
            body = {"appid": "wxSyntheticApp01", "mchid": "1900000109",
                    "out_trade_no": row["merchant_order_no"],
                    "transaction_id": "synthetic-payment-identity", "trade_state": "SUCCESS",
                    "amount": {"total": 1200, "currency": "CNY"},
                    "payer": {"openid": "private-synthetic-payer"}}
            raw, headers, now = self._wechat_callback(body, "TRANSACTION.SUCCESS")
            first = self.wechat.process_callback(raw, headers, now=now)
            again, again_headers, _ = self._wechat_callback(
                body, "TRANSACTION.SUCCESS", resource_nonce="abcdefghijkl", pretty=True)
            self.assertNotEqual(raw, again)
            second = self.wechat.process_callback(again, again_headers, now=now)
            self.assertTrue(first["ok"])
            self.assertFalse(first["duplicate"])
            self.assertTrue(second["duplicate"])
            self.assertNotEqual(first["callback_audit"]["callback_payload_sha256"],
                                second["callback_audit"]["callback_payload_sha256"])
            self.assertEqual(first["callback_audit"]["event_semantic_sha256"],
                             second["callback_audit"]["event_semantic_sha256"])
            before = dict(db.fetchone("SELECT * FROM payment_events"))
            self.assertEqual(before["payload_sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(before["duplicate_delivery_count"], 1)
            self.assertEqual(len(before["event_semantic_sha256"]), 64)
            self.assertEqual(db.fetchone("SELECT balance FROM credits WHERE user_id=?",
                                         ("u-redelivery",))["balance"], 30)
            for changed in (
                {**body, "amount": {"total": 1300, "currency": "CNY"}},
                {**body, "transaction_id": "different-payment"},
                {**body, "out_trade_no": "different-order"},
                {**body, "payer": {"openid": "different-payer"}},
                {**body, "success_time": "2026-09-05T01:59:58Z"},
            ):
                bad, bad_headers, _ = self._wechat_callback(changed, "TRANSACTION.SUCCESS")
                with self.subTest(changed=list(changed)), self.assertRaisesRegex(
                        payment_contract.PaymentContractError, "PAYMENT_EVENT_ID_COLLISION"):
                    self.wechat.process_callback(bad, bad_headers, now=now)
            self.assertEqual(dict(db.fetchone("SELECT * FROM payment_events")), before)
            for table in ("payment_cash_ledger", "payment_entitlement_ledger", "credit_transactions"):
                self.assertEqual(db.fetchone("SELECT count(*) n FROM " + table)["n"], 1)
            for value in (None, "a" * 64):
                with self.assertRaises(Exception):
                    db.execute("UPDATE payment_events SET event_semantic_sha256=?", (value,))

            # Old executors may still insert NULL during a compatible rollback.
            # They must never acquire a new identity from a later notification.
            callback = self.wechat.authenticate_callback(raw, headers, now=now)
            legacy = replace(callback.event, provider_event_id="legacy-event",
                             authenticated_payload_sha256=None)
            options = dict(expected_app_id="wxSyntheticApp01", expected_prod_mode=True,
                           expected_provider_name="wechatpay_direct", now=now)
            payment_contract.process_authenticated_callback(legacy, raw, callback.signature, **options)
            with self.assertRaisesRegex(payment_contract.PaymentContractError,
                                        "PAYMENT_EVENT_ID_COLLISION"):
                payment_contract.process_authenticated_callback(
                    replace(legacy, authenticated_payload_sha256=callback.event.authenticated_payload_sha256),
                    again, callback.signature, **options)
            legacy_row = db.fetchone("SELECT * FROM payment_events WHERE id<>?", (before["id"],))
            self.assertIsNone(legacy_row["event_semantic_sha256"])
            with self.assertRaises(Exception):
                db.execute("UPDATE payment_events SET event_semantic_sha256=? WHERE id=?",
                           ("a" * 64, legacy_row["id"]))
            self.assertEqual(len(self.wechat_transport.calls), 0)
        finally:
            billing.clear_active_usage()
            db._DB_PATH = old_db_path
            if old_database_url is not None:
                os.environ["DATABASE_URL"] = old_database_url
            temp.cleanup()

    def test_wechat_refund_callback_maps_canonical_event(self):
        raw, headers, now = self._wechat_callback(
            {
                "mchid": "1900000109",
                "out_trade_no": refund("wechatpay_direct")["merchant_order_no"],
                "transaction_id": "provider_payment_001",
                "out_refund_no": refund("wechatpay_direct")["merchant_refund_no"],
                "refund_id": "provider_refund_001",
                "refund_status": "SUCCESS",
                "amount": {
                    "refund": 100,
                    "total": 100,
                    "payer_refund": 90,
                    "payer_total": 90,
                },
            },
            "REFUND.SUCCESS",
        )
        callback = self.wechat.authenticate_callback(raw, headers, now=now)
        self.assertEqual(callback.event.event_type, "refund.succeeded")
        self.assertEqual(callback.event.data["refund_amt"], "1.00")
        self.assertNotIn("provider_submitted_at", callback.event.data)

    def test_wechat_refund_callback_rejects_invalid_official_amounts(self):
        base_amount = {
            "refund": 100,
            "total": 100,
            "payer_refund": 90,
            "payer_total": 90,
        }
        invalid_amounts = (
            {**base_amount, "refund": True},
            {**base_amount, "refund": 100.0},
            {**base_amount, "refund": -100},
            {**base_amount, "refund": 99},
            {**base_amount, "payer_refund": 101},
            {**base_amount, "currency": "CNY"},
        )
        for amount in invalid_amounts:
            raw, headers, now = self._wechat_callback(
                {
                    "mchid": "1900000109",
                    "out_trade_no": refund("wechatpay_direct")[
                        "merchant_order_no"
                    ],
                    "transaction_id": "provider_payment_001",
                    "out_refund_no": refund("wechatpay_direct")[
                        "merchant_refund_no"
                    ],
                    "refund_id": "provider_refund_001",
                    "refund_status": "SUCCESS",
                    "amount": amount,
                },
                "REFUND.SUCCESS",
            )
            with self.subTest(amount=amount), self.assertRaisesRegex(
                direct.DirectPaymentGatewayError,
                "PAYMENT_(?:CALLBACK_BINDING|PROVIDER_[A-Z_]+)_INVALID",
            ):
                self.wechat.authenticate_callback(raw, headers, now=now)

    def test_payment_callbacks_use_provider_payment_time_across_midnight(self):
        wechat_raw, wechat_headers, now = self._wechat_callback(
            {
                "appid": "wxSyntheticApp01",
                "mchid": "1900000109",
                "out_trade_no": order("wechatpay_direct")["merchant_order_no"],
                "transaction_id": "provider_payment_001",
                "trade_state": "SUCCESS",
                "success_time": "2026-09-04T23:59:59+08:00",
                "amount": {"total": 100, "currency": "CNY"},
            },
            "TRANSACTION.SUCCESS",
        )
        wechat = self.wechat.authenticate_callback(
            wechat_raw,
            wechat_headers,
            now=now,
        )
        self.assertEqual(
            wechat.event.created_time,
            direct._iso_to_epoch("2026-09-04T23:59:59+08:00"),
        )
        alipay = self.alipay.authenticate_callback(
            self._alipay_callback(
                gmt_payment="2026-09-04 23:59:59",
                notify_time="2026-09-05 00:00:05",
            )
        )
        self.assertEqual(
            alipay.event.created_time,
            direct._alipay_time_to_epoch("2026-09-04 23:59:59"),
        )

    def test_success_callbacks_require_signed_provider_financial_time(self):
        wechat_raw, wechat_headers, now = self._wechat_callback(
            {
                "appid": "wxSyntheticApp01",
                "mchid": "1900000109",
                "out_trade_no": order("wechatpay_direct")["merchant_order_no"],
                "transaction_id": "provider_payment_001",
                "trade_state": "SUCCESS",
                "success_time": None,
                "amount": {"total": 100, "currency": "CNY"},
            },
            "TRANSACTION.SUCCESS",
        )
        with self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_INVALID_EVENT_CLOCK",
        ):
            self.wechat.authenticate_callback(
                wechat_raw,
                wechat_headers,
                now=now,
            )
        with self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_INVALID_EVENT_CLOCK",
        ):
            self.alipay.authenticate_callback(
                self._alipay_callback(gmt_payment=None)
            )

    def test_wechat_callback_rejects_tamper_and_old_timestamp(self):
        raw, headers, now = self._wechat_callback(
            {
                "appid": "wxSyntheticApp01",
                "mchid": "1900000109",
                "out_trade_no": order("wechatpay_direct")["merchant_order_no"],
                "transaction_id": "provider_payment_001",
                "amount": {"total": 100, "currency": "CNY"},
            },
            "TRANSACTION.SUCCESS",
        )
        with self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_CALLBACK_SIGNATURE_INVALID",
        ):
            self.wechat.authenticate_callback(raw + b" ", headers, now=now)
        with self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_CALLBACK_HEADER_INVALID",
        ):
            self.wechat.authenticate_callback(
                raw,
                headers,
                now=datetime.fromtimestamp(int(headers["Wechatpay-Timestamp"]) + 301, tz=timezone.utc),
            )

    def test_alipay_create_query_and_refund_are_provider_bound(self):
        order_no = order("alipay_direct")["merchant_order_no"]
        refund_no = refund("alipay_direct")["merchant_refund_no"]
        self.alipay_transport.responses.extend(
            [
                self.response(
                    "alipay_direct",
                    {"out_trade_no": order_no, "qr_code": "https://qr.alipay.com/synthetic"},
                ),
                self.response(
                    "alipay_direct",
                    {
                        "out_trade_no": order_no,
                        "trade_no": "provider_payment_001",
                        "trade_status": "TRADE_SUCCESS",
                        "total_amount": "1.00",
                        "send_pay_date": "2026-09-05 10:00:00",
                    },
                ),
                self.response(
                    "alipay_direct",
                    {
                        "out_trade_no": order_no,
                        "out_request_no": refund_no,
                        "trade_no": "provider_payment_001",
                        "fund_change": "Y",
                        "refund_fee": "1.00",
                    },
                ),
                self.response(
                    "alipay_direct",
                    {
                        "out_trade_no": order_no,
                        "out_request_no": refund_no,
                        "trade_no": "provider_payment_001",
                        "refund_status": "REFUND_SUCCESS",
                        "refund_amount": "1.00",
                        "gmt_refund_pay": "2026-09-05 10:01:00",
                    },
                ),
            ]
        )
        created = self.alipay.create_payment(order("alipay_direct"))
        self.assertEqual(created.status, "pending")
        self.assertEqual(json.loads(created.checkout_token)["channel"], "alipay_precreate")
        queried = self.alipay.query_payment(
            payment_contract.ProviderPaymentLookup(merchant_order_no=order_no)
        )
        self.assertEqual(queried.status, "succeeded")
        refunded = self.alipay.create_refund(refund("alipay_direct"))
        self.assertEqual(refunded.status, "pending")
        self.assertIsNone(refunded.provider_refund_id)
        self.assertEqual(refunded.provider_name, "alipay_direct")
        queried_refund = self.alipay.query_refund(
            payment_contract.ProviderRefundLookup(
                merchant_refund_no=refund_no,
                merchant_order_no=order_no,
                provider_payment_id="provider_payment_001",
            )
        )
        self.assertEqual(queried_refund.status, "succeeded")
        self.assertIsNone(queried_refund.provider_refund_id)
        self.assertEqual(
            self.alipay_transport.calls[-1][1],
            "trade.fastpay.refund.query",
        )
        self.assertEqual(
            self.alipay_transport.calls[-1][2]["query_options"],
            ["gmt_refund_pay"],
        )

    def test_alipay_http_transport_signs_once_and_verifies_exact_response_node(self):
        merchant_private = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        requests_seen = []

        def handler(request):
            requests_seen.append(request)
            fields = dict(
                parse_qsl(
                    request.content.decode("ascii"),
                    keep_blank_values=True,
                    strict_parsing=True,
                )
            )
            request_signature = fields.pop("sign")
            sign_source = "&".join(
                f"{key}={fields[key]}"
                for key in sorted(fields)
                if fields[key] != ""
            )
            merchant_private.public_key().verify(
                base64.b64decode(request_signature, validate=True),
                sign_source.encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            self.assertEqual(fields["method"], "alipay.trade.precreate")
            self.assertEqual(
                fields["notify_url"],
                "https://api.noteaipro.cn/payments/alipay/callback",
            )
            self.assertNotIn("notify_url", json.loads(fields["biz_content"]))
            inner = (
                b'{"code":"10000","msg":"Success",'
                b'"out_trade_no":"0123456789abcdef0123456789abcdef",'
                b'"qr_code":"https://qr.alipay.com/synthetic"}'
            )
            response_signature = base64.b64encode(
                self.alipay_private.sign(
                    inner,
                    padding.PKCS1v15(),
                    hashes.SHA256(),
                )
            ).decode("ascii")
            outer = (
                b'{"alipay_trade_precreate_response":'
                + inner
                + b',"sign":"'
                + response_signature.encode("ascii")
                + b'"}'
            )
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html;charset=utf-8"},
                content=outer,
            )

        client = httpx.Client(
            transport=httpx.MockTransport(handler),
            follow_redirects=False,
        )
        transport = direct.HttpxAlipayTransport(
            app_id="2026000000000001",
            merchant_private_key_pem=merchant_private.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode("ascii"),
            alipay_public_key_pem=public_pem(self.alipay_private),
            client=client,
            clock=lambda: datetime.fromtimestamp(1788573600, tz=timezone.utc),
        )
        gateway = direct.AlipayGateway(
            app_id="2026000000000001",
            seller_id="2088000000000001",
            alipay_public_key_pem=public_pem(self.alipay_private),
            callback_url="https://api.noteaipro.cn/payments/alipay/callback",
            prod_mode=True,
            transport=transport,
        )
        result = gateway.create_payment(order("alipay_direct"))
        self.assertEqual(result.status, "pending")
        self.assertEqual(len(requests_seen), 1)

    def test_alipay_trade_bill_download_is_signed_tls_bound_and_parsed(self):
        merchant_private = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        source = alipay_trade_bill_zip_source()
        download_url = (
            "https://dwbillcenter.alipay.com/downloadBillFile.resource"
            "?bizType=X&userId=Y&fileType=csv.zip"
        )
        requests_seen = []

        def handler(request):
            requests_seen.append(request)
            if str(request.url) == direct.ALIPAY_GATEWAY_URL:
                fields = dict(
                    parse_qsl(
                        request.content.decode("ascii"),
                        keep_blank_values=True,
                        strict_parsing=True,
                    )
                )
                request_signature = fields.pop("sign")
                sign_source = "&".join(
                    f"{key}={fields[key]}"
                    for key in sorted(fields)
                    if fields[key] != ""
                )
                merchant_private.public_key().verify(
                    base64.b64decode(request_signature, validate=True),
                    sign_source.encode("utf-8"),
                    padding.PKCS1v15(),
                    hashes.SHA256(),
                )
                self.assertEqual(
                    fields["method"],
                    "alipay.data.dataservice.bill.downloadurl.query",
                )
                self.assertEqual(
                    json.loads(fields["biz_content"]),
                    {"bill_date": "2026-09-05", "bill_type": "trade"},
                )
                inner = json.dumps(
                    {
                        "code": "10000",
                        "msg": "Success",
                        "bill_download_url": download_url,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                response_signature = base64.b64encode(
                    self.alipay_private.sign(
                        inner,
                        padding.PKCS1v15(),
                        hashes.SHA256(),
                    )
                ).decode("ascii")
                outer = (
                    b'{"alipay_data_dataservice_bill_downloadurl_query_response":'
                    + inner
                    + b',"sign":"'
                    + response_signature.encode("ascii")
                    + b'"}'
                )
                return httpx.Response(
                    200,
                    headers={"Content-Type": "application/json;charset=utf-8"},
                    content=outer,
                )
            self.assertEqual(str(request.url), download_url)
            self.assertEqual(request.headers["accept-encoding"], "identity")
            return httpx.Response(
                200,
                headers={"Content-Type": "application/zip"},
                content=source,
            )

        transport = direct.HttpxAlipayTransport(
            app_id="2026000000000001",
            merchant_private_key_pem=merchant_private.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode("ascii"),
            alipay_public_key_pem=public_pem(self.alipay_private),
            client=httpx.Client(
                transport=httpx.MockTransport(handler),
                follow_redirects=False,
            ),
            clock=lambda: datetime.fromtimestamp(1788573600, tz=timezone.utc),
        )
        bill = transport.reconciliation("alipay_direct", "2026-09-05")
        self.assertEqual(bill.source_bytes, source)
        self.assertEqual(
            bill.authentication_mode,
            "signed_locator_tls_exact_url",
        )
        self.assertEqual(
            tuple(bill.rows),
            (
                {
                    "kind": "payment",
                    "reference": order("alipay_direct")["merchant_order_no"],
                    "amount_fen": 100,
                    "status": "succeeded",
                },
                {
                    "kind": "refund",
                    "reference": refund("alipay_direct")["merchant_refund_no"],
                    "amount_fen": 100,
                    "status": "succeeded",
                },
            ),
        )
        self.assertEqual(len(requests_seen), 2)

    def test_alipay_trade_bill_rejects_wrong_day_archive_and_untrusted_url(self):
        with self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_PROVIDER_BILL_DATE_MISMATCH",
        ):
            direct._parse_alipay_trade_bill_zip(
                alipay_trade_bill_zip_source(trade_date="2026-09-04"),
                expected_bill_date="2026-09-05",
            )

        output = io.BytesIO()
        with zipfile.ZipFile(output, mode="w") as archive:
            archive.writestr("../unsafe_业务明细.csv", b"synthetic")
        with self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_PROVIDER_BILL_ARCHIVE_INVALID",
        ):
            direct._parse_alipay_trade_bill_zip(
                output.getvalue(),
                expected_bill_date="2026-09-05",
            )

        merchant_private = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        transport = direct.HttpxAlipayTransport(
            app_id="2026000000000001",
            merchant_private_key_pem=merchant_private.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode("ascii"),
            alipay_public_key_pem=public_pem(self.alipay_private),
            client=httpx.Client(
                transport=httpx.MockTransport(
                    lambda _request: (_ for _ in ()).throw(
                        AssertionError("untrusted URL reached network")
                    )
                ),
                follow_redirects=False,
            ),
            monotonic_clock=lambda: 1.0,
        )
        for url in (
            "http://dwbillcenter.alipay.com/file?token=x",
            "https://example.invalid/file?token=x",
            "https://user@dwbillcenter.alipay.com/file?token=x",
            "https://dwbillcenter.alipay.com:444/file?token=x",
            "https://dwbillcenter.alipay.com/file",
            "https://dwbillcenter.alipay.com/../file?token=x",
        ):
            with self.subTest(url=url), self.assertRaisesRegex(
                direct.DirectPaymentGatewayError,
                "PAYMENT_PROVIDER_BILL_URL_INVALID",
            ):
                transport._download_trade_bill(url, deadline=30.0)

        missing_required = direct.VerifiedDirectResponse(
            provider_name="alipay_direct",
            body={
                "code": "10000",
                "sub_code": "synthetic",
                "bill_download_url": (
                    "https://dwbillcenter.alipay.com/file?token=x"
                ),
            },
            raw_body=b"{}",
            signature="synthetic",
            verified_at=1788573600,
            response_verified=True,
        )
        with patch.object(
            transport,
            "request",
            return_value=missing_required,
        ), self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_PROVIDER_BILL_LOCATOR_INVALID",
        ):
            transport.reconciliation("alipay_direct", "2026-09-05")

    def test_alipay_transport_rejects_unapproved_response_media_types(self):
        for content_type in ("text/plain", "application/xml", ""):
            with self.subTest(content_type=content_type):
                response = httpx.Response(
                    200,
                    headers={"Content-Type": content_type},
                    content=b"{}",
                )
                self.assertFalse(direct._http_alipay_json_content_type(response))

    def _alipay_callback(self, **updates):
        fields = {
            "notify_time": "2026-09-05 10:00:00",
            "notify_type": "trade_status_sync",
            "notify_id": "alipay_notify_001",
            "app_id": "2026000000000001",
            "seller_id": "2088000000000001",
            "out_trade_no": order("alipay_direct")["merchant_order_no"],
            "trade_no": "provider_payment_001",
            "trade_status": "TRADE_SUCCESS",
            "total_amount": "1.00",
            "gmt_payment": "2026-09-05 09:59:59",
            "currency": "CNY",
            "sign_type": "RSA2",
        }
        fields.update(updates)
        content = "&".join(
            f"{key}={fields[key]}"
            for key in sorted(fields)
            if key != "sign_type" and fields[key] != ""
        )
        fields["sign"] = base64.b64encode(
            self.alipay_private.sign(
                content.encode(),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        ).decode()
        return urlencode(fields).encode()

    def test_alipay_callback_verifies_rsa2_and_maps_payment(self):
        raw = self._alipay_callback()
        callback = self.alipay.authenticate_callback(raw)
        self.assertEqual(callback.event.provider_name, "alipay_direct")
        self.assertEqual(callback.event.event_type, "payment.succeeded")
        self.assertEqual(callback.event.data["pay_amt"], "1.00")
        self.assertEqual(
            callback.event.created_time,
            direct._alipay_time_to_epoch("2026-09-05 09:59:59"),
        )
        fields = dict(parse_qsl(raw.decode(), keep_blank_values=True))
        signature_input = "&".join(
            f"{key}={fields[key]}"
            for key in sorted(fields)
            if key not in {"sign", "sign_type"} and fields[key] != ""
        ).encode()
        self.assertEqual(
            callback.signature_input_sha256,
            hashlib.sha256(signature_input).hexdigest(),
        )
        self.assertNotIn("provider_payment_001", repr(callback))

    def test_alipay_callback_rejects_tamper_duplicate_and_fractional_fen(self):
        raw = self._alipay_callback()
        with self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_CALLBACK_SIGNATURE_INVALID",
        ):
            self.alipay.authenticate_callback(raw.replace(b"1.00", b"2.00"))
        with self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_CALLBACK_DUPLICATE_FIELD",
        ):
            self.alipay.authenticate_callback(raw + b"&app_id=duplicate")
        with self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_PROVIDER_AMOUNT_INVALID",
        ):
            self.alipay.authenticate_callback(
                self._alipay_callback(total_amount="1.001")
            )

    def test_constructor_mode_and_key_types_fail_closed(self):
        for invalid_mode in ("false", False):
            with self.subTest(invalid_mode=invalid_mode), self.assertRaisesRegex(
                direct.DirectPaymentGatewayError,
                "PAYMENT_PROVIDER_MODE_INVALID",
            ):
                direct.AlipayGateway(
                    app_id="2026000000000001",
                    seller_id="2088000000000001",
                    alipay_public_key_pem=public_pem(self.alipay_private),
                    callback_url="https://api.noteaipro.cn/payments/alipay/callback",
                    prod_mode=invalid_mode,
                    transport=self.alipay_transport,
                )
        with self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_PROVIDER_API_V3_KEY_INVALID",
        ):
            direct.WeChatPayGateway(
                app_id="wxSyntheticApp01",
                merchant_id="1900000109",
                platform_certificate_serial="0123456789ABCDEF",
                platform_public_key_pem=public_pem(self.wechat_private),
                api_v3_key=32,
                callback_url="https://noteaipro.com/payments/wechat/callback",
                prod_mode=True,
                transport=self.wechat_transport,
            )
        public_key_gateway = direct.WeChatPayGateway(
            app_id="wxSyntheticApp01",
            merchant_id="1900000109",
            platform_certificate_serial="PUB_KEY_ID_SYNTHETIC001",
            platform_public_key_pem=public_pem(self.wechat_private),
            api_v3_key=b"synthetic-api-v3-key-material-00",
            callback_url="https://noteaipro.com/payments/wechat/callback",
            prod_mode=True,
            transport=self.wechat_transport,
        )
        self.assertEqual(
            repr(public_key_gateway),
            "WeChatPayGateway(configuration_redacted=True)",
        )

    def test_direct_gateways_require_canonical_noteai_callback_destinations(self):
        with self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_PROVIDER_CALLBACK_URL_INVALID",
        ):
            direct.AlipayGateway(
                app_id="2026000000000001",
                seller_id="2088000000000001",
                alipay_public_key_pem=public_pem(self.alipay_private),
                callback_url="https://attacker.invalid/collect?x=1",
                prod_mode=True,
                transport=self.alipay_transport,
            )
        with self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_PROVIDER_CALLBACK_URL_INVALID",
        ):
            direct.WeChatPayGateway(
                app_id="wxSyntheticApp01",
                merchant_id="1900000109",
                platform_certificate_serial="0123456789ABCDEF",
                platform_public_key_pem=public_pem(self.wechat_private),
                api_v3_key=b"synthetic-api-v3-key-material-00",
                callback_url="https://api.noteaipro.cn/payments/alipay/callback",
                prod_mode=True,
                transport=self.wechat_transport,
            )

    def test_alipay_precreate_requires_bound_order_and_official_qr_host(self):
        order_no = order("alipay_direct")["merchant_order_no"]
        for body in (
            {"qr_code": "https://qr.alipay.com/synthetic"},
            {"out_trade_no": order_no, "qr_code": "https://example.com/synthetic"},
            {"out_trade_no": order_no, "qr_code": "https://qr.alipay.com:444/synthetic"},
        ):
            with self.subTest(body=body):
                self.alipay_transport.responses.append(
                    self.response("alipay_direct", body)
                )
                with self.assertRaises(direct.DirectPaymentGatewayError):
                    self.alipay.create_payment(order("alipay_direct"))

    def test_callbacks_require_provider_algorithm_and_merchant_binding(self):
        raw, headers, now = self._wechat_callback(
            {
                "appid": "wxSyntheticApp01",
                "mchid": "1900000109",
                "out_trade_no": order("wechatpay_direct")["merchant_order_no"],
                "transaction_id": "provider_payment_001",
                "trade_state": "SUCCESS",
                "amount": {"total": 100, "currency": "CNY"},
            },
            "TRANSACTION.SUCCESS",
        )
        headers["Wechatpay-Signature-Type"] = "UNSUPPORTED"
        with self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_CALLBACK_HEADER_INVALID",
        ):
            self.wechat.authenticate_callback(raw, headers, now=now)

        for updates in (
            {"seller_id": "2088000000000002"},
            {"notify_type": "unsupported"},
        ):
            with self.subTest(updates=updates):
                with self.assertRaisesRegex(
                    direct.DirectPaymentGatewayError,
                    "PAYMENT_CALLBACK_BINDING_INVALID",
                ):
                    self.alipay.authenticate_callback(self._alipay_callback(**updates))

    def test_direct_refund_lookup_requires_canonical_identity(self):
        for gateway in (self.wechat, self.alipay):
            with self.subTest(provider=gateway.provider_name):
                with self.assertRaisesRegex(
                    direct.DirectPaymentGatewayError,
                    "PAYMENT_PROVIDER_REFUND_LOOKUP_INVALID",
                ):
                    gateway.query_refund("merchant-refund-only")

    def test_alipay_response_amount_requires_canonical_decimal_text(self):
        order_no = order("alipay_direct")["merchant_order_no"]
        self.alipay_transport.responses.append(
            self.response(
                "alipay_direct",
                {
                    "out_trade_no": order_no,
                    "trade_no": "provider_payment_001",
                    "trade_status": "TRADE_SUCCESS",
                    "total_amount": 1,
                },
            )
        )
        with self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_PROVIDER_AMOUNT_INVALID",
        ):
            self.alipay.query_payment(order_no)

    def test_process_callback_hands_authenticated_event_to_shared_contract(self):
        raw = self._alipay_callback()
        with patch.object(
            payment_contract,
            "process_authenticated_callback",
            return_value={"ok": True},
        ) as process:
            result = self.alipay.process_callback(raw)
        self.assertTrue(result["ok"])
        audit = result["callback_audit"]
        self.assertEqual(
            set(audit),
            {
                "schema",
                "provider",
                "event_type",
                "callback_identity_sha256",
                "callback_payload_sha256",
                "signature_input_sha256",
                "signature_scheme",
            },
        )
        self.assertEqual(
            audit["callback_payload_sha256"],
            hashlib.sha256(raw).hexdigest(),
        )
        self.assertEqual(audit["signature_scheme"], "RSA2")
        self.assertNotIn("alipay_notify_001", str(audit))
        self.assertNotIn("provider_payment_001", str(audit))
        event = process.call_args.args[0]
        self.assertEqual(event.provider_name, "alipay_direct")
        self.assertEqual(event.event_type, "payment.succeeded")
        self.assertEqual(process.call_args.kwargs["expected_app_id"], "2026000000000001")

    def test_wechat_verified_payment_query_recovers_unknown_exactly_once(self):
        old_db_path = db._DB_PATH
        old_database_url = os.environ.pop("DATABASE_URL", None)
        temp = tempfile.TemporaryDirectory()
        try:
            db._DB_PATH = Path(temp.name) / "direct-payment-query.db"
            db.init_db()
            billing.clear_active_usage()
            now = datetime.fromtimestamp(1788573600, tz=timezone.utc)
            db.execute(
                "INSERT INTO users("
                "id,username,email,password_hash,password_salt,created_at"
                ") VALUES(?,?,?,?,?,?)",
                (
                    "u-direct-query",
                    "direct_query_user",
                    "direct-query@example.com",
                    "hash",
                    "salt",
                    now.isoformat(),
                ),
            )
            billing.get_subscription("u-direct-query")
            created = payment_contract.create_order(
                "u-direct-query",
                "credit_package",
                "starter",
                idempotency_key="direct-payment-query-recovery-001",
                app_id="wxSyntheticApp01",
                prod_mode=True,
                provider_name="wechatpay_direct",
                now=now,
            )
            stored = dict(
                db.fetchone(
                    "SELECT * FROM payment_orders WHERE id=?",
                    (created["id"],),
                )
            )
            self.assertTrue(
                payment_contract.admit_payment_submission(stored["id"], now=now)
            )
            payment_contract.mark_payment_submission_unknown(stored["id"], now=now)
            query_body = {
                "appid": "wxSyntheticApp01",
                "mchid": "1900000109",
                "out_trade_no": stored["merchant_order_no"],
                "transaction_id": "wechat_payment_query_recovery_001",
                "trade_state": "SUCCESS",
                "success_time": "2026-09-04T23:59:59+08:00",
                "amount": {"total": 1200, "currency": "CNY"},
            }
            self.wechat_transport.responses.extend(
                (
                    self.response("wechatpay_direct", query_body),
                    self.response("wechatpay_direct", query_body),
                )
            )
            lookup = payment_contract.ProviderPaymentLookup(
                merchant_order_no=stored["merchant_order_no"]
            )
            applied = self.wechat.process_payment_query(lookup, now=now)
            duplicate = self.wechat.process_payment_query(lookup, now=now)
            self.assertTrue(applied["ok"])
            self.assertTrue(duplicate["duplicate"])
            terminal = db.fetchone(
                "SELECT payment_status,entitlement_status "
                "FROM payment_orders WHERE id=?",
                (stored["id"],),
            )
            self.assertEqual(terminal["payment_status"], "succeeded")
            self.assertEqual(terminal["entitlement_status"], "applied")
            event = db.fetchone(
                "SELECT provider_created_at FROM payment_events "
                "WHERE order_id=? AND event_type='payment.succeeded'",
                (stored["id"],),
            )
            self.assertEqual(
                event["provider_created_at"],
                direct._iso_to_epoch("2026-09-04T23:59:59+08:00"),
            )
            self.assertEqual(
                db.fetchone(
                    "SELECT COUNT(*) AS c FROM payment_cash_ledger "
                    "WHERE order_id=? AND entry_type='payment_received'",
                    (stored["id"],),
                )["c"],
                1,
            )
        finally:
            billing.clear_active_usage()
            db._DB_PATH = old_db_path
            if old_database_url is not None:
                os.environ["DATABASE_URL"] = old_database_url
            temp.cleanup()

    def test_wechat_closed_query_without_transaction_id_terminates_unknown(self):
        old_db_path = db._DB_PATH
        old_database_url = os.environ.pop("DATABASE_URL", None)
        temp = tempfile.TemporaryDirectory()
        try:
            db._DB_PATH = Path(temp.name) / "direct-payment-closed-query.db"
            db.init_db()
            billing.clear_active_usage()
            now = datetime.fromtimestamp(1788573600, tz=timezone.utc)
            db.execute(
                "INSERT INTO users("
                "id,username,email,password_hash,password_salt,created_at"
                ") VALUES(?,?,?,?,?,?)",
                (
                    "u-direct-closed-query",
                    "direct_closed_query_user",
                    "direct-closed-query@example.com",
                    "hash",
                    "salt",
                    now.isoformat(),
                ),
            )
            billing.get_subscription("u-direct-closed-query")
            created = payment_contract.create_order(
                "u-direct-closed-query",
                "credit_package",
                "starter",
                idempotency_key="direct-payment-closed-query-001",
                app_id="wxSyntheticApp01",
                prod_mode=True,
                provider_name="wechatpay_direct",
                now=now,
            )
            stored = dict(
                db.fetchone(
                    "SELECT * FROM payment_orders WHERE id=?",
                    (created["id"],),
                )
            )
            self.assertTrue(
                payment_contract.admit_payment_submission(stored["id"], now=now)
            )
            payment_contract.mark_payment_submission_unknown(stored["id"], now=now)
            query_body = {
                "appid": "wxSyntheticApp01",
                "mchid": "1900000109",
                "out_trade_no": stored["merchant_order_no"],
                "trade_state": "CLOSED",
            }
            self.wechat_transport.responses.extend(
                (
                    self.response("wechatpay_direct", query_body),
                    self.response("wechatpay_direct", query_body),
                    self.response(
                        "wechatpay_direct",
                        query_body,
                        verified_at=1788573900,
                    ),
                )
            )
            lookup = payment_contract.ProviderPaymentLookup(
                merchant_order_no=stored["merchant_order_no"],
                expected_amount_fen=1200,
            )
            applied = self.wechat.process_payment_query(lookup, now=now)
            duplicate = self.wechat.process_payment_query(lookup, now=now)
            later_readback = self.wechat.process_payment_query(lookup, now=now)
            self.assertTrue(applied["ok"])
            self.assertTrue(duplicate["duplicate"])
            self.assertTrue(later_readback["already_terminal"])
            terminal = db.fetchone(
                "SELECT payment_status,provider_payment_id,entitlement_status "
                "FROM payment_orders WHERE id=?",
                (stored["id"],),
            )
            self.assertEqual(terminal["payment_status"], "failed")
            self.assertIsNone(terminal["provider_payment_id"])
            self.assertEqual(terminal["entitlement_status"], "pending")
            self.assertEqual(
                db.fetchone(
                    "SELECT COUNT(*) AS c FROM payment_cash_ledger WHERE order_id=?",
                    (stored["id"],),
                )["c"],
                0,
            )
            self.assertEqual(
                db.fetchone(
                    "SELECT COUNT(*) AS c FROM payment_entitlement_ledger "
                    "WHERE order_id=?",
                    (stored["id"],),
                )["c"],
                0,
            )
        finally:
            billing.clear_active_usage()
            db._DB_PATH = old_db_path
            if old_database_url is not None:
                os.environ["DATABASE_URL"] = old_database_url
            temp.cleanup()

    def test_wechat_closed_query_rejects_mismatched_optional_amount(self):
        order_no = order("wechatpay_direct")["merchant_order_no"]
        self.wechat_transport.responses.append(
            self.response(
                "wechatpay_direct",
                {
                    "appid": "wxSyntheticApp01",
                    "mchid": "1900000109",
                    "out_trade_no": order_no,
                    "trade_state": "CLOSED",
                    "amount": {"total": 101, "currency": "CNY"},
                },
            )
        )
        with self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_PROVIDER_RESPONSE_MISMATCH",
        ):
            self.wechat.query_payment(
                payment_contract.ProviderPaymentLookup(
                    merchant_order_no=order_no,
                    expected_amount_fen=100,
                )
            )

    def test_wechat_closed_query_accepts_independently_omitted_amount_fields(self):
        order_no = order("wechatpay_direct")["merchant_order_no"]
        for amount in ({}, {"total": 100}, {"currency": "CNY"}):
            with self.subTest(amount=amount):
                self.wechat_transport.responses.append(
                    self.response(
                        "wechatpay_direct",
                        {
                            "appid": "wxSyntheticApp01",
                            "mchid": "1900000109",
                            "out_trade_no": order_no,
                            "trade_state": "CLOSED",
                            "amount": amount,
                        },
                    )
                )
                result = self.wechat.query_payment(
                    payment_contract.ProviderPaymentLookup(
                        merchant_order_no=order_no,
                        expected_amount_fen=100,
                    )
                )
                self.assertEqual(result.status, "failed")
                self.assertEqual(result.amount_fen, 100)

    def test_alipay_closed_query_and_callback_require_refund_reconciliation(self):
        order_no = order("alipay_direct")["merchant_order_no"]
        self.alipay_transport.responses.append(
            self.response(
                "alipay_direct",
                {
                    "out_trade_no": order_no,
                    "trade_no": "provider_payment_001",
                    "trade_status": "TRADE_CLOSED",
                    "total_amount": "1.00",
                },
            )
        )
        with self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_PROVIDER_REFUND_RECONCILIATION_REQUIRED",
        ):
            self.alipay.query_payment(
                payment_contract.ProviderPaymentLookup(
                    merchant_order_no=order_no,
                    expected_amount_fen=100,
                )
            )
        with self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_PROVIDER_REFUND_RECONCILIATION_REQUIRED",
        ):
            self.alipay.authenticate_callback(
                self._alipay_callback(trade_status="TRADE_CLOSED")
            )

    def test_alipay_verified_refund_query_enters_shared_ledger_exactly_once(self):
        old_db_path = db._DB_PATH
        old_database_url = os.environ.pop("DATABASE_URL", None)
        temp = tempfile.TemporaryDirectory()
        try:
            db._DB_PATH = Path(temp.name) / "direct-payment.db"
            db.init_db()
            billing.clear_active_usage()
            now = datetime.fromtimestamp(1788573600, tz=timezone.utc)
            db.execute(
                "INSERT INTO users("
                "id,username,email,password_hash,password_salt,created_at"
                ") VALUES(?,?,?,?,?,?)",
                (
                    "u-direct-refund",
                    "direct_refund_user",
                    "direct-refund@example.com",
                    "hash",
                    "salt",
                    now.isoformat(),
                ),
            )
            billing.get_subscription("u-direct-refund")
            created = payment_contract.create_order(
                "u-direct-refund",
                "credit_package",
                "starter",
                idempotency_key="direct-refund-query-001",
                app_id="2026000000000001",
                prod_mode=True,
                provider_name="alipay_direct",
                now=now,
            )
            stored_order = dict(
                db.fetchone(
                    "SELECT * FROM payment_orders WHERE id=?",
                    (created["id"],),
                )
            )
            paid = self.alipay.process_callback(
                self._alipay_callback(
                    out_trade_no=stored_order["merchant_order_no"],
                    total_amount="12.00",
                ),
                now=now,
            )
            self.assertTrue(paid["ok"])
            prepared = payment_contract.prepare_full_refund(
                stored_order["id"],
                reason_code="customer_request",
                now=datetime.fromtimestamp(1788573660, tz=timezone.utc),
            )
            stored_refund = dict(
                db.fetchone(
                    "SELECT * FROM payment_refunds WHERE id=?",
                    (prepared["id"],),
                )
            )
            self.assertTrue(payment_contract.admit_refund_submission(stored_refund["id"]))
            refund_payload = {
                "merchant_refund_no": stored_refund["merchant_refund_no"],
                "merchant_order_no": stored_order["merchant_order_no"],
                "provider_payment_id": "provider_payment_001",
                "amount_fen": 1200,
                "currency": "CNY",
                "provider_mode": "live",
                "provider_name": "alipay_direct",
                "reason_code": "customer_request",
            }
            submission_body = {
                "out_trade_no": stored_order["merchant_order_no"],
                "trade_no": "provider_payment_001",
                "fund_change": "Y",
                "refund_fee": "12.00",
            }
            self.alipay_transport.responses.append(
                self.response("alipay_direct", submission_body)
            )
            submission = self.alipay.create_refund(refund_payload)
            payment_contract.mark_refund_submission(
                stored_refund["id"],
                submission,
                now=datetime.fromtimestamp(1788573720, tz=timezone.utc),
            )
            lookup = payment_contract.ProviderRefundLookup(
                merchant_refund_no=stored_refund["merchant_refund_no"],
                merchant_order_no=stored_order["merchant_order_no"],
                provider_payment_id="provider_payment_001",
            )
            query_body = {
                "out_trade_no": stored_order["merchant_order_no"],
                "out_request_no": stored_refund["merchant_refund_no"],
                "trade_no": "provider_payment_001",
                "refund_status": "REFUND_SUCCESS",
                "refund_amount": "12.00",
                "gmt_refund_pay": "2026-09-05 10:01:00",
            }
            self.alipay_transport.responses.extend(
                [
                    self.response("alipay_direct", query_body),
                    self.response("alipay_direct", query_body),
                    self.response(
                        "alipay_direct",
                        query_body,
                        verified_at=1788573900,
                    ),
                ]
            )
            applied = self.alipay.process_refund_query(
                lookup,
                now=datetime.fromtimestamp(1788573780, tz=timezone.utc),
            )
            duplicate = self.alipay.process_refund_query(
                lookup,
                now=datetime.fromtimestamp(1788573840, tz=timezone.utc),
            )
            later_readback = self.alipay.process_refund_query(
                lookup,
                now=datetime.fromtimestamp(1788573900, tz=timezone.utc),
            )
            self.assertTrue(applied["ok"])
            self.assertTrue(duplicate["duplicate"])
            self.assertTrue(later_readback["already_terminal"])
            terminal_order = db.fetchone(
                "SELECT refund_status,entitlement_status,refunded_fen "
                "FROM payment_orders WHERE id=?",
                (stored_order["id"],),
            )
            terminal_refund = db.fetchone(
                "SELECT status,provider_refund_id FROM payment_refunds WHERE id=?",
                (stored_refund["id"],),
            )
            cash_count = db.fetchone(
                "SELECT COUNT(*) AS c FROM payment_cash_ledger "
                "WHERE refund_id=? AND entry_type='refund_paid'",
                (stored_refund["id"],),
            )["c"]
            reversal_count = db.fetchone(
                "SELECT COUNT(*) AS c FROM payment_entitlement_ledger "
                "WHERE refund_id=?",
                (stored_refund["id"],),
            )["c"]
            self.assertEqual(dict(terminal_order), {
                "refund_status": "refunded",
                "entitlement_status": "reversed",
                "refunded_fen": 1200,
            })
            self.assertEqual(terminal_refund["status"], "succeeded")
            self.assertIsNone(terminal_refund["provider_refund_id"])
            self.assertEqual(cash_count, 1)
            self.assertEqual(reversal_count, 1)
        finally:
            billing.clear_active_usage()
            db._DB_PATH = old_db_path
            if old_database_url is not None:
                os.environ["DATABASE_URL"] = old_database_url
            else:
                os.environ.pop("DATABASE_URL", None)
            temp.cleanup()

    def test_unverified_or_cross_provider_response_fails_closed(self):
        self.wechat_transport.responses.append(
            self.response(
                "wechatpay_direct",
                {"code_url": "weixin://wxpay/bizpayurl?pr=synthetic"},
                verified=False,
            )
        )
        with self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_PROVIDER_RESPONSE_UNVERIFIED",
        ):
            self.wechat.create_payment(order("wechatpay_direct"))

        self.alipay_transport.responses.append(
            self.response(
                "wechatpay_direct",
                {"out_trade_no": "x", "qr_code": "https://qr.alipay.com/x"},
            )
        )
        with self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_PROVIDER_RESPONSE_UNVERIFIED",
        ):
            self.alipay.create_payment(order("alipay_direct"))

    def test_verified_response_requires_exact_authenticated_body_bytes(self):
        self.alipay_transport.responses.append(
            direct.VerifiedDirectResponse(
                provider_name="alipay_direct",
                body={
                    "out_trade_no": order("alipay_direct")["merchant_order_no"],
                    "qr_code": "https://qr.alipay.com/synthetic",
                },
                raw_body=b'{"out_trade_no":"different","qr_code":"https://qr.alipay.com/synthetic"}',
                signature="synthetic-verified-response-signature",
                verified_at=1788573600,
                response_verified=True,
            )
        )
        with self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_PROVIDER_RESPONSE_MISMATCH",
        ):
            self.alipay.create_payment(order("alipay_direct"))

    def test_reconciliation_rejects_unverified_or_unknown_rows(self):
        self.alipay_transport.bill = direct.VerifiedDirectBill(
            provider_name="alipay_direct",
            bill_date="2026-09-05",
            source_bytes=b"synthetic-alipay-bill",
            rows=({"kind": "unknown", "reference": "x", "amount_fen": 1, "status": "succeeded"},),
            authentication_mode="signed_locator_tls_exact_url",
        )
        with self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_PROVIDER_BILL_ROW_INVALID",
        ):
            self.alipay.reconciliation_rows("2026-09-05")

        self.alipay_transport.bill = direct.VerifiedDirectBill(
            provider_name="alipay_direct",
            bill_date="2026-09-05",
            source_bytes=1,
            rows=(),
            authentication_mode="signed_locator_tls_exact_url",
        )
        with self.assertRaisesRegex(
            direct.DirectPaymentGatewayError,
            "PAYMENT_PROVIDER_BILL_SOURCE_INVALID",
        ):
            self.alipay.reconciliation_rows("2026-09-05")

    def test_repr_never_contains_callback_keys(self):
        self.assertEqual(repr(self.wechat), "WeChatPayGateway(configuration_redacted=True)")
        self.assertEqual(repr(self.alipay), "AlipayGateway(configuration_redacted=True)")
        response = self.response("alipay_direct", {"secret": "synthetic"})
        self.assertNotIn("synthetic", repr(response))
        payment_result = payment_contract.ProviderPaymentResult(
            merchant_order_no="merchant-order-secret",
            provider_payment_id="provider-payment-secret",
            status="pending",
            amount_fen=100,
            app_id="application-secret",
            prod_mode=True,
            response_verified=True,
            checkout_token="https://qr.alipay.com/checkout-secret",
            provider_name="alipay_direct",
        )
        refund_result = payment_contract.ProviderRefundResult(
            merchant_refund_no="merchant-refund-secret",
            provider_refund_id="provider-refund-secret",
            status="pending",
            amount_fen=100,
            response_verified=True,
            app_id="application-secret",
            prod_mode=True,
        )
        for secret in (
            "merchant-order-secret",
            "provider-payment-secret",
            "application-secret",
            "checkout-secret",
            "merchant-refund-secret",
            "provider-refund-secret",
        ):
            self.assertNotIn(secret, repr(payment_result))
            self.assertNotIn(secret, repr(refund_result))


if __name__ == "__main__":
    unittest.main()
