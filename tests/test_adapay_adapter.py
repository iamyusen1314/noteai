import base64
import importlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from urllib.parse import urlencode
from unittest import mock

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

adapter_module = importlib.import_module("adapay_adapter")
db = importlib.import_module("db")
payment = importlib.import_module("payment_contract")
payment_adapter_runtime = importlib.import_module("payment_adapter_runtime")
payment_runtime = importlib.import_module("payment_runtime")


class FakeTransport:
    def __init__(self):
        self.requests = []
        self.responses = []
        self.downloads = []
        self.download_response = None

    def send(self, request):
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected provider request")
        response = self.responses.pop(0)
        if callable(response):
            response = response(request)
        return response

    def download(self, url, *, max_bytes):
        self.downloads.append((url, max_bytes))
        if self.download_response is None:
            raise AssertionError("unexpected bill download")
        return self.download_response


class AdapayAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.merchant_private = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        cls.provider_private = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        cls.merchant_private_pem = cls.merchant_private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("ascii")
        cls.provider_public_pem = cls.provider_private.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")

    def setUp(self):
        self.transport = FakeTransport()
        self.api_key = "mock_synthetic_api_key_000001"
        self.app_id = "app_synthetic_001"
        self.payment_id = "pay_synthetic_001"
        self.refund_id = "refund_synthetic_001"
        self.adapter = adapter_module.AdapayAdapter(
            api_key=self.api_key,
            merchant_private_key_pem=self.merchant_private_pem,
            adapay_public_key_pem=self.provider_public_pem,
            app_id=self.app_id,
            prod_mode=False,
            pay_channel="alipay_qr",
            callback_url=(
                "https://payment.example.invalid/payments/adapay/callback"
            ),
            checkout_hosts=("qr.example.invalid",),
            bill_hosts=("bill.example.invalid",),
            transport=self.transport,
        )

    def envelope(
        self,
        payload,
        *,
        url="https://api.adapay.tech/v1/payments",
        content_type="application/json; charset=utf-8",
    ):
        data = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
        )
        signature = self.provider_private.sign(
            data.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA1(),
        )
        body = json.dumps(
            {
                "data": data,
                "signature": base64.b64encode(signature).decode("ascii"),
            },
            separators=(",", ":"),
        ).encode("utf-8")
        return adapter_module.AdapayHttpResponse(
            status_code=200,
            headers={"content-type": content_type},
            body=body,
            final_url=url,
        )

    def order(self):
        return {
            "merchant_order_no": "NA_synthetic_order_001",
            "amount_fen": 1200,
            "currency": "CNY",
            "product_kind": "credit_package",
            "product_id": "starter",
            "provider_mode": "mock",
            "device_ip": "8.8.8.8",
        }

    def payment_payload(self):
        return {
            "id": self.payment_id,
            "order_no": "NA_synthetic_order_001",
            "prod_mode": "false",
            "app_id": self.app_id,
            "pay_channel": "alipay_qr",
            "pay_amt": "12.00",
            "status": "pending",
            "expend": {
                "qrcode_url": (
                    "https://qr.example.invalid/checkout?token=synthetic"
                )
            },
        }

    def test_create_payment_matches_official_wire_signature_and_minimizes_data(self):
        self.transport.responses.append(self.envelope(self.payment_payload()))

        result = self.adapter.create_payment(self.order())

        self.assertTrue(result.response_verified)
        self.assertEqual(result.provider_payment_id, self.payment_id)
        self.assertEqual(result.amount_fen, 1200)
        self.assertEqual(
            json.loads(result.checkout_token),
            {
                "channel": "alipay_qr",
                "kind": "qr_url",
                "url": (
                    "https://qr.example.invalid/checkout?token=synthetic"
                ),
            },
        )
        request = self.transport.requests[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(
            request.url,
            "https://api.adapay.tech/v1/payments",
        )
        payload = json.loads(request.body)
        self.assertEqual(
            set(payload),
            {
                "order_no",
                "app_id",
                "pay_channel",
                "pay_amt",
                "goods_title",
                "goods_desc",
                "currency",
                "device_info",
                "notify_url",
            },
        )
        self.assertEqual(payload["device_info"]["device_ip"], "8.8.8.8")
        self.assertNotIn("user", request.body.decode("utf-8").lower())
        signature = base64.b64decode(request.headers["signature"])
        self.merchant_private.public_key().verify(
            signature,
            (request.url + request.body.decode("utf-8")).encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA1(),
        )
        rendered = repr(request) + repr(self.adapter)
        self.assertNotIn(self.api_key, rendered)
        self.assertNotIn("PRIVATE KEY", rendered)
        self.assertNotIn(request.headers["signature"], rendered)
        self.assertNotIn(request.url, rendered)

    def test_order_rejects_extra_pii_invalid_ip_and_environment_before_transport(self):
        cases = (
            {**self.order(), "email": "private@example.invalid"},
            {**self.order(), "device_ip": "127.0.0.1"},
            {**self.order(), "device_ip": "not-an-ip"},
            {**self.order(), "provider_mode": "live"},
            {**self.order(), "currency": "USD"},
        )
        for payload in cases:
            with self.subTest(payload_keys=tuple(payload)):
                with self.assertRaises(adapter_module.AdapayAdapterError):
                    self.adapter.create_payment(payload)
        self.assertEqual(self.transport.requests, [])

    def test_unsigned_tampered_redirected_and_oversized_responses_fail_closed(self):
        payload = self.payment_payload()
        valid = self.envelope(payload)
        envelope = json.loads(valid.body)
        envelope["data"] = envelope["data"].replace("12.00", "13.00")
        tampered = adapter_module.AdapayHttpResponse(
            status_code=200,
            headers=valid.headers,
            body=json.dumps(envelope).encode("utf-8"),
            final_url=valid.final_url,
        )
        unsigned = adapter_module.AdapayHttpResponse(
            status_code=200,
            headers=valid.headers,
            body=b'{"status":"failed"}',
            final_url=valid.final_url,
        )
        redirected = adapter_module.AdapayHttpResponse(
            status_code=200,
            headers=valid.headers,
            body=valid.body,
            final_url="https://other.example.invalid/v1/payments",
        )
        oversized = adapter_module.AdapayHttpResponse(
            status_code=200,
            headers=valid.headers,
            body=b"x" * (adapter_module.MAX_PROVIDER_RESPONSE_BYTES + 1),
            final_url=valid.final_url,
        )
        for response in (tampered, unsigned, redirected, oversized):
            self.transport.responses.append(response)
            with self.assertRaises(adapter_module.AdapayAdapterError):
                self.adapter.create_payment(self.order())

    def test_duplicate_response_json_keys_and_unapproved_checkout_host_are_rejected(self):
        duplicate = adapter_module.AdapayHttpResponse(
            status_code=200,
            headers={"content-type": "application/json"},
            body=b'{"data":"{}","data":"{}","signature":"x"}',
            final_url="https://api.adapay.tech/v1/payments",
        )
        self.transport.responses.append(duplicate)
        with self.assertRaisesRegex(
            adapter_module.AdapayAdapterError,
            "PAYMENT_PROVIDER_DUPLICATE_JSON_KEY",
        ):
            self.adapter.create_payment(self.order())

        payload = self.payment_payload()
        payload["expend"]["qrcode_url"] = (
            "https://evil.example.invalid/checkout"
        )
        self.transport.responses.append(self.envelope(payload))
        with self.assertRaisesRegex(
            adapter_module.AdapayAdapterError,
            "PAYMENT_PROVIDER_CHECKOUT_INVALID",
        ):
            self.adapter.create_payment(self.order())

    def test_query_payment_uses_fixed_endpoint_and_verified_response(self):
        url = f"https://api.adapay.tech/v1/payments/{self.payment_id}"
        payload = {
            "id": self.payment_id,
            "order_no": "NA_synthetic_order_001",
            "pay_amt": "12.00",
            "pay_channel": "alipay_qr",
            "status": "succeeded",
        }
        self.transport.responses.append(self.envelope(payload, url=url))

        result = self.adapter.query_payment(self.payment_id)

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.checkout_token, "")
        self.assertEqual(self.transport.requests[0].url, url)

    def refund(self):
        return {
            "merchant_refund_no": "NR_synthetic_refund_001",
            "merchant_order_no": "NA_synthetic_order_001",
            "provider_payment_id": self.payment_id,
            "amount_fen": 1200,
            "currency": "CNY",
            "provider_mode": "mock",
            "reason_code": "customer_request",
        }

    def test_refund_create_stays_pending_and_query_maps_provider_terminal_state(self):
        create_url = (
            f"https://api.adapay.tech/v1/payments/{self.payment_id}/refunds"
        )
        self.transport.responses.append(
            self.envelope(
                {
                    "id": self.refund_id,
                    "payment_id": self.payment_id,
                    "refund_amt": "12.00",
                    "status": "succeeded",
                },
                url=create_url,
            )
        )
        created = self.adapter.create_refund(self.refund())
        self.assertEqual(created.status, "pending")
        self.assertEqual(created.provider_refund_id, self.refund_id)

        query_url = (
            "https://api.adapay.tech/v1/payments/refunds"
            f"?refund_id={self.refund_id}"
        )
        self.transport.responses.append(
            self.envelope(
                {
                    "status": "succeeded",
                    "prod_mode": "false",
                    "refunds": [
                        {
                            "payment_id": self.payment_id,
                            "refund_id": self.refund_id,
                            "refund_order_no": "NR_synthetic_refund_001",
                            "trans_status": "S",
                            "refund_amt": "12.00",
                        }
                    ],
                },
                url=query_url,
            )
        )
        queried = self.adapter.query_refund(self.refund_id)
        self.assertEqual(queried.status, "succeeded")
        self.assertEqual(self.transport.requests[-1].url, query_url)

    def bill_archive(self):
        charge = (
            "#payment\n"
            + ",".join(adapter_module._CHARGE_HEADER)
            + "\n"
            + (
                "20260727080000,"
                f"{self.app_id},{self.payment_id},"
                "NA_synthetic_order_001,支付宝正扫,12.00,0.10,cny,S,,\n"
            )
        )
        refund = (
            "#refund\n"
            + ",".join(adapter_module._REFUND_HEADER)
            + "\n"
            + (
                "20260727090000,"
                f"{self.app_id},{self.refund_id},{self.payment_id},"
                "NR_synthetic_refund_001,NA_synthetic_order_001,"
                "支付宝正扫,12.00,0.00,cny,F\n"
            )
        )
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("Charge_20260727.csv", charge)
            archive.writestr("Refund_20260727.csv", refund)
        return output.getvalue()

    def test_bill_download_validates_https_host_zip_schema_and_rows(self):
        bill_url = "https://bill.example.invalid/day.zip?sig=synthetic"
        self.transport.responses.append(
            self.envelope(
                {
                    "bill_download_url": bill_url,
                    "status": "succeeded",
                    "prod_mode": "false",
                },
                url="https://api.adapay.tech/v1/bill/download",
            )
        )
        source = self.bill_archive()
        self.transport.download_response = adapter_module.AdapayHttpResponse(
            status_code=200,
            headers={"content-type": "application/zip"},
            body=source,
            final_url=bill_url,
        )

        returned_source, rows = self.adapter.reconciliation_rows(
            "2026-07-27"
        )

        self.assertEqual(returned_source, source)
        self.assertNotIn(bill_url, repr(self.transport.download_response))
        self.assertEqual(
            rows,
            (
                {
                    "kind": "payment",
                    "reference": "NA_synthetic_order_001",
                    "amount_fen": 1200,
                    "status": "succeeded",
                },
                {
                    "kind": "refund",
                    "reference": "NR_synthetic_refund_001",
                    "amount_fen": 1200,
                    "status": "failed",
                },
            ),
        )
        request_payload = json.loads(self.transport.requests[0].body)
        self.assertEqual(request_payload, {"bill_date": "20260727"})
        self.assertEqual(
            self.transport.downloads,
            [(bill_url, payment.MAX_RECONCILIATION_SOURCE_BYTES)],
        )

    def test_bill_rejects_cleartext_unapproved_host_and_archive_traversal(self):
        for bill_url in (
            "http://bill.example.invalid/day.zip",
            "https://evil.example.invalid/day.zip",
        ):
            self.transport.responses.append(
                self.envelope(
                    {
                        "bill_download_url": bill_url,
                        "status": "succeeded",
                        "prod_mode": "false",
                    },
                    url="https://api.adapay.tech/v1/bill/download",
                )
            )
            with self.assertRaises(adapter_module.AdapayAdapterError):
                self.adapter.reconciliation_rows("2026-07-27")
        self.assertEqual(self.transport.downloads, [])

        bill_url = "https://bill.example.invalid/day.zip"
        self.transport.responses.append(
            self.envelope(
                {
                    "bill_download_url": bill_url,
                    "status": "succeeded",
                    "prod_mode": "false",
                },
                url="https://api.adapay.tech/v1/bill/download",
            )
        )
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("../Charge.csv", "invalid")
        self.transport.download_response = adapter_module.AdapayHttpResponse(
            status_code=200,
            headers={"content-type": "application/zip"},
            body=archive_bytes.getvalue(),
            final_url=bill_url,
        )
        with self.assertRaisesRegex(
            adapter_module.AdapayAdapterError,
            "PAYMENT_PROVIDER_BILL_ARCHIVE_INVALID",
        ):
            self.adapter.reconciliation_rows("2026-07-27")

    def test_constructor_rejects_old_keys_channels_and_credential_shapes(self):
        weak_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=1024,
        )
        weak_pem = weak_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("ascii")
        with self.assertRaises(adapter_module.AdapayAdapterError):
            adapter_module.AdapayAdapter(
                api_key="short",
                merchant_private_key_pem=weak_pem,
                adapay_public_key_pem=self.provider_public_pem,
                app_id=self.app_id,
                prod_mode=False,
                pay_channel="alipay",
                callback_url="https://payment.example.invalid/callback",
                checkout_hosts=("qr.example.invalid",),
                bill_hosts=("bill.example.invalid",),
                transport=self.transport,
            )


class PaymentRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.merchant_private = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        cls.provider_private = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        cls.merchant_private_pem = cls.merchant_private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("ascii")
        cls.provider_public_pem = cls.provider_private.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")

    def setUp(self):
        self.old_db_path = db._DB_PATH
        self.old_database_url = os.environ.pop("DATABASE_URL", None)
        self.temp = tempfile.TemporaryDirectory()
        db._DB_PATH = Path(self.temp.name) / "noteai.db"
        db.init_db()
        payment_adapter_runtime.reset_for_tests()

    def tearDown(self):
        payment_adapter_runtime.reset_for_tests()
        db._DB_PATH = self.old_db_path
        if self.old_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = self.old_database_url
        self.temp.cleanup()

    def env(self):
        return {
            "NOTEAI_RUNTIME_ROLE": "payment",
            "NOTEAI_DEPLOYMENT_STAGE": "test",
            "NOTEAI_PAYMENT_CALLBACK_ENABLED": "1",
            "NOTEAI_ADAPAY_APP_ID": "app_synthetic_001",
            "NOTEAI_ADAPAY_PUBLIC_KEY": "synthetic-public-key",
            "NOTEAI_ADAPAY_PROD_MODE": "0",
        }

    def test_health_is_provider_free_and_callback_rejects_ambiguous_form(self):
        client = TestClient(payment_runtime.app)
        with mock.patch.dict(os.environ, self.env(), clear=False):
            live = client.get("/health/live")
            ready = client.get("/health/ready")
            with mock.patch.object(
                payment_runtime.payment_contract,
                "process_signed_callback",
            ) as processor:
                response = client.post(
                    "/payments/adapay/callback",
                    headers={
                        "Content-Type": (
                            "application/x-www-form-urlencoded"
                        )
                    },
                    content="data=first&data=second&sign=synthetic",
                )
        self.assertEqual(live.status_code, 200)
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(response.status_code, 400)
        processor.assert_not_called()

    def test_adapter_bootstrap_is_role_bound_and_makes_no_provider_request(self):
        class BootstrapTransport(FakeTransport):
            def close(self):
                pass

        transport = BootstrapTransport()
        private_key = self.merchant_private_pem
        public_key = self.provider_public_pem
        env = {
            "NOTEAI_RUNTIME_ROLE": "api",
            "NOTEAI_ADAPAY_API_KEY": "mock_synthetic_api_key_000001",
            "NOTEAI_ADAPAY_MERCHANT_PRIVATE_KEY": private_key,
            "NOTEAI_ADAPAY_PUBLIC_KEY": public_key,
            "NOTEAI_ADAPAY_APP_ID": "app_synthetic_001",
            "NOTEAI_ADAPAY_PROD_MODE": "0",
            "NOTEAI_ADAPAY_PAY_CHANNEL": "alipay_qr",
            "NOTEAI_ADAPAY_CALLBACK_URL": (
                "https://payment.example.invalid/payments/adapay/callback"
            ),
            "NOTEAI_ADAPAY_CHECKOUT_HOSTS": "qr.example.invalid",
            "NOTEAI_ADAPAY_BILL_HOSTS": "bill.example.invalid",
        }
        with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(
            payment_adapter_runtime.adapay_adapter,
            "HttpxAdapayTransport",
            return_value=transport,
        ):
            self.assertFalse(
                payment_adapter_runtime.configure_from_environment(
                    required_role="payment",
                )
            )
            self.assertTrue(
                payment_adapter_runtime.configure_from_environment(
                    required_role="api",
                )
            )
        self.assertIsInstance(payment.provider(), adapter_module.AdapayAdapter)
        self.assertEqual(transport.requests, [])
        self.assertEqual(transport.downloads, [])

    def test_dedicated_callback_verifies_and_settles_exactly_once(self):
        now = "2026-07-27T08:00:00+00:00"
        user_id = "u-runtime-payment"
        db.execute(
            "INSERT INTO users("
            "id,username,email,password_hash,password_salt,created_at"
            ") VALUES(?,?,?,?,?,?)",
            (
                user_id,
                "runtime_payment",
                "runtime-payment@example.invalid",
                "hash",
                "salt",
                now,
            ),
        )
        import billing

        billing.get_subscription(user_id)
        order = payment.create_order(
            user_id,
            "credit_package",
            "starter",
            idempotency_key="runtime-payment-request-001",
            app_id="app_synthetic_001",
            prod_mode=False,
        )
        row = db.fetchone(
            "SELECT merchant_order_no FROM payment_orders WHERE id=?",
            (order["id"],),
        )
        data = json.dumps(
            {
                "id": "evt_runtime_payment_001",
                "type": "payment.succeeded",
                "created_time": 1785139200,
                "prod_mode": False,
                "app_id": "app_synthetic_001",
                "data": {
                    "id": "pay_runtime_payment_001",
                    "order_no": row["merchant_order_no"],
                    "pay_amt": "12.00",
                },
            },
            separators=(",", ":"),
        )
        signature = self.provider_private.sign(
            data.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA1(),
        )
        body = urlencode(
            {
                "data": data,
                "sign": base64.b64encode(signature).decode("ascii"),
            }
        )
        env = {
            **self.env(),
            "NOTEAI_ADAPAY_PUBLIC_KEY": self.provider_public_pem,
        }
        client = TestClient(payment_runtime.app)
        with mock.patch.dict(os.environ, env, clear=False):
            first = client.post(
                "/payments/adapay/callback",
                headers={
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                content=body,
            )
            replay = client.post(
                "/payments/adapay/callback",
                headers={
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                content=body,
            )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(first.json()["accepted"])
        self.assertTrue(replay.json()["accepted"])
        stored = db.fetchone(
            "SELECT payment_status,entitlement_status "
            "FROM payment_orders WHERE id=?",
            (order["id"],),
        )
        self.assertEqual(stored["payment_status"], "succeeded")
        self.assertEqual(stored["entitlement_status"], "applied")
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM payment_cash_ledger"
            )["c"],
            1,
        )
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM payment_events"
            )["c"],
            1,
        )

    def test_payment_runtime_has_no_user_admin_or_provider_submission_routes(self):
        paths = {route.path for route in payment_runtime.app.routes}
        self.assertEqual(
            paths,
            {
                "/health/live",
                "/health/ready",
                "/payments/adapay/callback",
            },
        )

    def test_wrong_runtime_or_production_database_role_rejects_before_processing(self):
        client = TestClient(payment_runtime.app)
        for overrides in (
            {"NOTEAI_RUNTIME_ROLE": "api"},
            {"NOTEAI_DEPLOYMENT_STAGE": "production"},
        ):
            env = {**self.env(), **overrides}
            with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(
                payment_runtime.payment_contract,
                "process_signed_callback",
            ) as processor:
                response = client.post(
                    "/payments/adapay/callback",
                    headers={
                        "Content-Type": (
                            "application/x-www-form-urlencoded"
                        )
                    },
                    content="data=%7B%7D&sign=synthetic",
                )
            self.assertEqual(response.status_code, 503)
            processor.assert_not_called()
