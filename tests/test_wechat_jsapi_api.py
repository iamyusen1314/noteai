"""Real ASGI/payment/OAuth contracts over disposable SQLite and synthetic I/O.

No ASGI lifespan, artifact loader, supplier, or production configuration starts.
"""

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock
from uuid import uuid4

from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric import rsa


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
# Match the existing public API harness while preventing dotenv, network and
# original local database access even during the first import in this process.
with tempfile.TemporaryDirectory() as boot:
    with mock.patch.dict(os.environ, {
        "PYTHON_DOTENV_DISABLED": "1", "DATABASE_URL": "",
        "NOTEAI_SQLITE_PATH": str(Path(boot) / "boot.db"),
        "NOTEAI_HOT_KEYWORD_DB_PATH": str(Path(boot) / "hot.db"),
        "NOTEAI_MODEL_ARTIFACT_REQUIRED": "0", "NOTEAI_FACT_SEARCH": "0",
    }), mock.patch("dotenv.load_dotenv", return_value=False), mock.patch(
        "socket.socket.connect", side_effect=AssertionError("offline API import forbids network")
    ):
        import api
        import db
        import billing
        import wechat_jsapi as oauth
        import direct_payment_gateways as direct
        import payment_contract as payment

from tests import test_direct_payment_gateways as payment_fixtures


APP_ID = "wx0123456789abcdef"
OPENID = "openid_synthetic_jsapi_payer"


class WechatJsapiApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wechat_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        folder = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(mock.patch.dict(os.environ, {
            "DATABASE_URL": "", "PYTHON_DOTENV_DISABLED": "1", "NOTEAI_DEPLOYMENT_STAGE": "test",
            "NOTEAI_PUBLIC_PRODUCT": "1", "NOTEAI_PUBLIC_ACCOUNT_ONLY": "1",
            "NOTEAI_PUBLIC_ORIGINS": "https://noteaipro.com,https://www.noteaipro.com",
            "NOTEAI_RUNTIME_ROLE": "api", "NOTEAI_PAYMENT_ORDERING_ENABLED": "1",
            "NOTEAI_PAYMENT_CALLBACK_RELAY_ENABLED": "1", "NOTEAI_PAYMENT_ORDER_PROVIDERS": "wechatpay_direct",
            "NOTEAI_PAYMENT_DEFAULT_PROVIDER": "wechatpay_direct", "NOTEAI_PAYMENT_CANARY_ENABLED": "0",
            "NOTEAI_WECHATPAY_APP_ID": APP_ID, "NOTEAI_WECHATPAY_PROD_MODE": "1",
            "NOTEAI_WECHAT_JSAPI_ENABLED": "1", "NOTEAI_WECHAT_SHARE_APP_ID": APP_ID,
            "NOTEAI_WECHAT_SHARE_APP_SECRET": "S" * 32,
        }))
        self.stack.enter_context(mock.patch.object(db, "_DB_PATH", Path(folder) / "api.db"))
        self.stack.enter_context(mock.patch.object(db, "using_postgres", return_value=False))
        self.stack.enter_context(mock.patch("socket.socket.connect", side_effect=AssertionError("real network forbidden")))
        self.stack.enter_context(mock.patch.object(api, "ensure_model_artifacts", side_effect=AssertionError("artifacts forbidden")))
        self.stack.enter_context(mock.patch.object(api._mr, "call", side_effect=AssertionError("model forbidden")))
        db.init_db()
        billing.clear_active_usage()
        self.addCleanup(billing.clear_active_usage)
        self.now = datetime.now(timezone.utc)
        self.owner, self.other = str(uuid4()), str(uuid4())
        self.tokens = {}
        for uid in (self.owner, self.other):
            token = "offline-session-" + uid
            self.tokens[uid] = token
            db.execute(
                "INSERT INTO users(id,username,password_hash,password_salt,created_at,phone_verified_at) VALUES(?,?,?,?,?,?)",
                (uid, uid, "offline", "offline", self.now.isoformat(), self.now.isoformat()),
            )
            db.execute("INSERT INTO user_sessions(token,user_id,created_at,expires_at) VALUES(?,?,?,?)",
                       (token, uid, self.now.isoformat(), (self.now + timedelta(hours=1)).isoformat()))
            db.execute("INSERT INTO user_contract_acceptances VALUES(?,?,?,?,?)",
                       (uid, api._public_product.CONTRACT_VERSION, self.now.isoformat(), "", "account_settings"))
            billing.get_subscription(uid)
        self.provider = mock.Mock()
        self.provider.create_payment.side_effect = self.create_payment_result
        self.stack.enter_context(mock.patch.object(api._payment_adapter_runtime, "provider_from_environment", return_value=self.provider))
        self.ready = self.stack.enter_context(mock.patch.object(api, "_payment_callback_runtime_ready", new=mock.AsyncMock(return_value=True)))
        self.exchange = self.stack.enter_context(mock.patch.object(oauth, "_request_openid", return_value={"openid": OPENID}))
        # Do not use the TestClient context manager: that would start lifespan.
        self.client = TestClient(api.app)
        self.addCleanup(self.client.close)

    def headers(self, *, user=None, key="jsapi-api-purchase-001", token=None):
        return {"Origin": "https://noteaipro.com", "Authorization": "Bearer " + (token or self.tokens[user or self.owner]),
                "Idempotency-Key": key}

    def begin(self, *, key="jsapi-api-purchase-001"):
        response = self.client.post("/payments/wechat/oauth/begin", headers=self.headers(key=key),
                                    json={"product_kind": "credit_package", "product_id": "starter"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["state"]

    def context(self, *, key="jsapi-api-purchase-001"):
        state = self.begin(key=key)
        response = self.client.post("/payments/wechat/oauth/complete", headers=self.headers(key=key),
                                    json={"state": state, "code": "synthetic-code-001"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"checkout_context": state})
        return state

    def order(self, context=None, *, key="jsapi-api-purchase-001", headers=None, product="starter"):
        body = {"product_kind": "credit_package", "product_id": product, "provider": "wechatpay_direct"}
        if context is not None:
            body["wechat_jsapi_context"] = context
        return self.client.post("/payments/orders", headers=headers or self.headers(key=key), json=body)

    def create_payment_result(self, request):
        jsapi = request.get("payment_method") == "jsapi"
        checkout = ({"channel": "wechatpay_jsapi", "kind": "bridge", "params": {"synthetic": True}}
                    if jsapi else {"channel": "wechatpay_native", "kind": "qr_text", "value": "weixin://wxpay/bizpayurl?pr=synthetic"})
        return payment.ProviderPaymentResult(
            merchant_order_no=request["merchant_order_no"], provider_payment_id=None, status="pending",
            amount_fen=request["amount_fen"], app_id=APP_ID, prod_mode=True, response_verified=True,
            provider_name="wechatpay_direct", checkout_token=json.dumps(checkout),
            wechat_trade_type="JSAPI" if jsapi else "",
            wechat_jsapi_payer_hash=payment.wechat_jsapi_payer_identity_hash(APP_ID, request["payer_openid"]) if jsapi else None,
        )

    def order_count(self):
        return db.fetchone("SELECT COUNT(*) AS n FROM payment_orders")["n"]

    def test_real_oauth_api_order_and_authenticated_callback_grant_once(self):
        state = self.context()
        response = self.order(state)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        public = response.json()["order"]
        row = dict(db.fetchone("SELECT * FROM payment_orders WHERE id=?", (public["id"],)))
        self.assertEqual(row["wechat_jsapi_payer_hash"], payment.wechat_jsapi_payer_identity_hash(APP_ID, OPENID))
        self.assertNotIn(OPENID, json.dumps(row))
        self.provider.create_payment.assert_called_once()
        self.assertEqual(self.provider.create_payment.call_args.args[0]["payer_openid"], OPENID)
        self.assertEqual(public["entitlement_status"], "pending")
        gateway = direct.WeChatPayGateway(
            app_id=APP_ID, merchant_id="1900000109", platform_certificate_serial="0123456789ABCDEF",
            platform_public_key_pem=payment_fixtures.public_pem(self.wechat_private),
            api_v3_key=b"synthetic-api-v3-key-material-00",
            callback_url="https://noteaipro.com/payments/wechat/callback", prod_mode=True,
            transport=payment_fixtures.FakeTransport(),
        )
        raw, headers, clock = payment_fixtures.DirectPaymentGatewayTests._wechat_callback(self, {
            "appid": APP_ID, "mchid": "1900000109", "out_trade_no": row["merchant_order_no"],
            "transaction_id": "synthetic-api-jsapi-transaction", "trade_state": "SUCCESS", "trade_type": "JSAPI",
            "payer": {"openid": OPENID}, "amount": {"total": 1200, "currency": "CNY"},
        }, "TRANSACTION.SUCCESS")
        self.assertTrue(gateway.process_callback(raw, headers, now=clock)["ok"])
        self.assertTrue(gateway.process_callback(raw, headers, now=clock)["duplicate"])
        terminal = self.client.get("/payments/orders/" + row["id"], headers=self.headers())
        self.assertEqual(terminal.json()["entitlement_status"], "applied")
        self.assertEqual(self.client.get("/payments/orders/" + row["id"], headers=self.headers(user=self.other)).status_code, 404)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM payment_cash_ledger WHERE entry_type='payment_received'")["n"], 1)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM payment_entitlement_ledger")["n"], 1)

    def test_context_binds_product_key_owner_and_actual_session_before_order(self):
        state = self.context()
        second_token = "different-live-session-" + self.owner
        db.execute("INSERT INTO user_sessions(token,user_id,created_at,expires_at) VALUES(?,?,?,?)",
                   (second_token, self.owner, self.now.isoformat(), (self.now + timedelta(hours=1)).isoformat()))
        for kwargs in ({"product": "creator"}, {"key": "different-purchase-key"},
                       {"headers": self.headers(user=self.other)}, {"headers": self.headers(token=second_token)}):
            with self.subTest(kwargs=kwargs):
                response = self.order(state, **kwargs)
                self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.order_count(), 0)
        self.provider.create_payment.assert_not_called()
        self.exchange.assert_called_once()

    def test_disabled_and_different_app_id_stay_closed_before_oauth_or_order(self):
        for values in ({"NOTEAI_WECHAT_JSAPI_ENABLED": "0"}, {"NOTEAI_WECHAT_SHARE_APP_ID": "wxfedcba9876543210"}):
            with self.subTest(values=values), mock.patch.dict(os.environ, values):
                capabilities = self.client.get("/payments/capabilities", headers=self.headers()).json()
                self.assertFalse(capabilities["wechat_jsapi_available"])
                response = self.client.post("/payments/wechat/oauth/begin", headers=self.headers(),
                                            json={"product_kind": "credit_package", "product_id": "starter"})
                self.assertIn(response.status_code, (404, 503), response.text)
                self.assertEqual(self.order("a" * 64).status_code, 503)
        self.assertEqual(self.order_count(), 0)
        self.exchange.assert_not_called()
        self.provider.create_payment.assert_not_called()

    def test_native_default_uses_original_request_and_needs_no_oauth(self):
        with mock.patch.dict(os.environ, {"NOTEAI_WECHAT_JSAPI_ENABLED": "0"}), mock.patch.object(
            oauth, "resolve", side_effect=AssertionError("Native must not use OAuth")
        ):
            response = self.order()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(json.loads(response.json()["checkout"])["channel"], "wechatpay_native")
        request = self.provider.create_payment.call_args.args[0]
        self.assertEqual(set(request), {"merchant_order_no", "amount_fen", "currency", "product_kind", "product_id",
                                        "provider_mode", "provider_name", "device_ip"})
        row = db.fetchone("SELECT wechat_jsapi_payer_hash FROM payment_orders")
        self.assertIsNone(row["wechat_jsapi_payer_hash"])
        self.exchange.assert_not_called()

    def test_callback_readiness_stops_authorization_and_order_before_write(self):
        self.ready.return_value = False
        response = self.client.post("/payments/wechat/oauth/begin", headers=self.headers(),
                                    json={"product_kind": "credit_package", "product_id": "starter"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.order("a" * 64).status_code, 503)
        self.assertEqual(self.order_count(), 0)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM payment_wechat_oauth_states")["n"], 0)
        self.exchange.assert_not_called()
        self.provider.create_payment.assert_not_called()

    def test_unknown_payment_is_sealed_against_repeat_post(self):
        context = self.context()
        self.provider.create_payment.side_effect = TimeoutError("synthetic private provider detail")
        first = self.order(context)
        self.assertEqual(first.status_code, 503, first.text)
        self.assertEqual(first.json()["detail"], "PAYMENT_PROVIDER_OUTCOME_UNKNOWN")
        second = self.order(context)
        self.assertEqual(second.status_code, 409, second.text)
        self.assertEqual(second.json()["detail"], "PAYMENT_ORDER_ALREADY_SUBMITTED")
        self.assertEqual(self.order_count(), 1)
        self.provider.create_payment.assert_called_once()
        row = db.fetchone("SELECT payment_status,entitlement_status FROM payment_orders")
        self.assertEqual((row["payment_status"], row["entitlement_status"]), ("pending", "pending"))

    def test_public_boundary_requires_origin_session_and_exact_enabled_routes(self):
        path = "/payments/wechat/oauth/begin"
        body = {"product_kind": "credit_package", "product_id": "starter"}
        self.assertEqual(self.client.post(path, headers={"Origin": "https://noteaipro.com"}, json=body).status_code, 401)
        for origin in ("", "https://attacker.invalid"):
            headers = {**self.headers(), "Origin": origin}
            self.assertEqual(self.client.post(path, headers=headers, json=body).status_code, 403)
        self.assertEqual(self.client.get(path, headers=self.headers()).status_code, 404)
        self.assertEqual(self.client.post(path + "/", headers=self.headers(), json=body).status_code, 404)
        self.assertEqual(self.client.post("/payments/wechat/oauth%2fbegin", headers=self.headers(), json=body).status_code, 404)
        self.assertEqual(self.order_count(), 0)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM payment_wechat_oauth_states")["n"], 0)

    def test_nginx_admits_only_fixed_post_oauth_and_get_callback_assets(self):
        locations = (ROOT / "deploy/production/public-account.locations.conf").read_text()
        for path in ("/payments/wechat/oauth/begin", "/payments/wechat/oauth/complete"):
            match = re.search(r"location = " + re.escape(path) + r" \{(.*?)\n\}", locations, re.S)
            self.assertIsNotNone(match, path)
            self.assertIn("limit_except POST { deny all; }", match[1])
            self.assertIn("client_max_body_size 8k;", match[1])
            self.assertIn("include /etc/nginx/noteai-product-proxy.conf;", match[1])
        website = (ROOT / "deploy/production/public-website.nginx.conf").read_text()
        for path in ("/wechat-pay.html", "/assets/wechat-pay-callback.js"):
            self.assertIn("location = " + path + " { limit_except GET { deny all; } try_files $uri =404; }", website)
        self.assertIn("access_log off;", website)
        build = (ROOT / "scripts/build_render_frontend.sh").read_text()
        self.assertIn('cp "$ROOT_DIR/wechat-pay.html" "$DIST_DIR/wechat-pay.html"', build)


if __name__ == "__main__":
    unittest.main()
