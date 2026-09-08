"""Actual payment HTTP/worker SQL on an explicit disposable PG16 socket.

Gateway credentials and signed callbacks are generated synthetic fixtures.
No production environment, provider network, account or database is used.
"""

import base64
import asyncio
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import tempfile
import threading
import subprocess
import sys
import time
import unittest
from unittest import mock
import uuid
from urllib.parse import urlencode

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient

from tests.test_item31_canary_dml_postgres import CanaryPaymentFlowPostgresTests as PG
from tests.test_item31_canary_dml_postgres import ENABLED
from tools import collect_item31_canary_dml as dml


@unittest.skipUnless(ENABLED, "explicit isolated PG16 container required")
class RuntimeCanaryPostgresTests(unittest.TestCase):
    setUpClass = classmethod(PG.setUpClass.__func__)
    tearDownClass = classmethod(PG.tearDownClass.__func__)
    connect = PG.connect
    stage = PG.stage

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.scratch = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(mock.patch.dict(os.environ, {
            "DATABASE_URL": "postgresql:///noteai_local?host=/var/run/postgresql",
            "PYTHON_DOTENV_DISABLED": "1", "NOTEAI_FACT_SEARCH": "0",
            "NOTEAI_SQLITE_PATH": str(Path(self.scratch) / "unused.db"),
        }, clear=True))
        self.stack.enter_context(mock.patch.object(self.db, "get_conn", self.connect))
        self.api = importlib.import_module("api")
        self.runtime = importlib.import_module("payment_runtime")
        self.direct = importlib.import_module("direct_payment_gateways")
        self.executor = importlib.import_module("payment_canary_executor")
        from tests.test_direct_payment_gateways import DirectPaymentGatewayTests
        DirectPaymentGatewayTests.setUpClass()
        self.fixture = DirectPaymentGatewayTests()
        self.fixture.setUp()
        self.client = TestClient(self.api.app)
        self.callbacks = TestClient(self.runtime.app)
        self.addCleanup(self.client.close)
        self.addCleanup(self.callbacks.close)
        self.addCleanup(lambda: self.api.app.state._state.pop("item31_canary_create_resolver", None))
        self.addCleanup(lambda: self.runtime.app.state._state.pop("item31_canary_callback_resolver", None))

    def subject(self, provider):
        uid = "local_http_" + uuid.uuid4().hex
        self.db.execute(
            "INSERT INTO users(id,username,email,password_hash,password_salt,created_at) "
            "VALUES(?,?,?,'synthetic','synthetic',?)",
            (uid, uid, uid + "@example.invalid", datetime.now(timezone.utc).isoformat()),
        )
        self.payment.billing.get_subscription(uid)
        token = self.api._auth.create_token(uid, "isolated-pg16-canary")
        key = "local_http_" + uuid.uuid4().hex
        key_hash = self.payment._hash("noteai-payment-idempotency-v1", key)
        targets = {
            "payment_orders": ("idempotency_key_hash", key_hash),
            "payment_events": ("provider_event_id_hash", dml.AUTHENTICATED_EVENT),
            "credits": ("user_id", uid), "credit_transactions": ("user_id", uid),
            "subscriptions": ("user_id", "forbidden-subscription-write"),
            "users": ("id", "forbidden-user-write"),
            "usage_records": ("user_id", "forbidden-usage-write"),
            "payment_reconciliation_runs": ("id", "no-reconcile"),
            "payment_reconciliation_items": ("id", "no-reconcile"),
            "payment_settlement_summaries": ("id", "no-settlement"),
        }
        for table in dml.ORDER_TABLES:
            targets[table] = ("order_id", dml.ORDER_FROM_KEY + key_hash)
        app_id = "wxSyntheticApp01" if provider == "wechatpay_direct" else "2026000000000001"
        now = int(time.time())
        env = {
            "NOTEAI_PAYMENT_CANARY_ENABLED": "1", "NOTEAI_PAYMENT_CANARY_ACTION": "create-payment",
            "NOTEAI_PAYMENT_CANARY_PROVIDER": provider, "NOTEAI_PAYMENT_CANARY_ACTIVATION_ID": str(uuid.uuid4()),
            "NOTEAI_PAYMENT_CANARY_USER_ID_SHA256": self.api._item31_identity(uid, "payment-canary-user-v1"),
            "NOTEAI_PAYMENT_CANARY_SUBJECT_HASH": self.payment._subject_hash(uid),
            "NOTEAI_PAYMENT_CANARY_IDEMPOTENCY_KEY_SHA256": self.api._item31_identity(key, "noteai-item31-create-idempotency-v1"),
            "NOTEAI_PAYMENT_CANARY_AMOUNT_FEN": "1200",
            "NOTEAI_PAYMENT_CANARY_SYNTHETIC_ASSERTION": "ITEM31-SYNTHETIC-NO-REAL-USER",
            "NOTEAI_PAYMENT_CANARY_NOT_BEFORE_EPOCH": str(now - 5),
            "NOTEAI_PAYMENT_CANARY_EXPIRES_EPOCH": str(now + 300),
            "NOTEAI_RUNTIME_ROLE": "api", "NOTEAI_DEPLOYMENT_STAGE": "production",
        }
        return uid, token, key, key_hash, targets, app_id, env

    def configure(self, stack, provider, app_id, env, gateway):
        stack.enter_context(mock.patch.dict(os.environ, env))
        stack.enter_context(mock.patch.object(self.api, "_selected_payment_provider", return_value=provider))
        stack.enter_context(mock.patch.object(self.api, "_payment_ordering_available", return_value=True))
        stack.enter_context(mock.patch.object(self.api, "_payment_callback_runtime_ready", new=mock.AsyncMock(return_value=True)))
        stack.enter_context(mock.patch.object(self.api._payment_adapter_runtime, "configured_app_id", return_value=app_id))
        stack.enter_context(mock.patch.object(self.api._payment_adapter_runtime, "configured_prod_mode", return_value=True))
        stack.enter_context(mock.patch.object(self.api._payment_adapter_runtime, "provider_from_environment", return_value=gateway))
        stack.enter_context(mock.patch.object(self.runtime, "_callback_available", return_value=True))
        callback_gateway = self.fixture.wechat if provider == "wechatpay_direct" else self.fixture.alipay
        stack.enter_context(mock.patch.object(self.runtime, "_direct_callback_gateway", return_value=callback_gateway))

    def scope(self, writer, uid, key, key_hash, app_id, provider):
        context = self.api._item31_create_canary_context(
            provider_name=provider, user_id=uid, product_kind="credit_package",
            product_id="starter", idempotency_key=key, prod_mode=True,
        )
        scope = dml.CanaryScope(writer, self.db.fetchone, user_id=uid, idempotency_key_hash=key_hash,
                                app_id=app_id, prod_mode=True, create_context=context)
        self.api.app.state.item31_canary_create_resolver = scope.create
        self.runtime.app.state.item31_canary_callback_resolver = scope
        return scope

    def pending(self, request, provider, app_id):
        return self.payment.ProviderPaymentResult(
            merchant_order_no=request["merchant_order_no"], provider_payment_id=None,
            status="pending", amount_fen=1200, app_id=app_id, prod_mode=True,
            response_verified=True, checkout_token="synthetic-local-checkout", provider_name=provider,
        )

    def post_order(self, provider, token, key):
        return self.client.post("/payments/orders", headers={"Authorization": "Bearer " + token,
                                "Idempotency-Key": key}, json={"product_kind": "credit_package",
                                "product_id": "starter", "provider": provider})

    def signed_callback(self, provider, row, *, event_id=None, amount=1200, refund=None):
        now = datetime.now(timezone.utc)
        event_id = event_id or "local_event_" + uuid.uuid4().hex
        payment_id = "local_payment_" + row["id"].replace("-", "")
        if provider == "wechatpay_direct":
            body = {"mchid": "1900000109", "out_trade_no": row["merchant_order_no"],
                    "transaction_id": payment_id, "success_time": now.isoformat()}
            if refund is None:
                body.update(appid="wxSyntheticApp01", trade_state="SUCCESS",
                            amount={"total": amount, "payer_total": amount, "currency": "CNY"})
            else:
                body.update(out_refund_no=refund["merchant_refund_no"], refund_id="local_refund_" + refund["id"].replace("-", ""),
                            refund_status="SUCCESS", amount={"refund": amount, "total": amount,
                            "payer_refund": amount, "payer_total": amount, "currency": "CNY"})
            nonce, associated = "0123456789ab", "transaction"
            ciphertext = AESGCM(b"synthetic-api-v3-key-material-00").encrypt(
                nonce.encode(), json.dumps(body, separators=(",", ":")).encode(), associated.encode())
            raw = json.dumps({"id": event_id, "create_time": now.isoformat(),
                "event_type": "TRANSACTION.SUCCESS" if refund is None else "REFUND.SUCCESS",
                "resource": {"algorithm": "AEAD_AES_256_GCM", "ciphertext": base64.b64encode(ciphertext).decode(),
                "nonce": nonce, "associated_data": associated}}, separators=(",", ":")).encode()
            timestamp, header_nonce = str(int(now.timestamp())), "synthetic-header-nonce"
            signature = self.fixture.wechat_private.sign(
                (timestamp + "\n" + header_nonce + "\n").encode() + raw + b"\n",
                padding.PKCS1v15(), hashes.SHA256())
            headers = {"Content-Type": "application/json", "Wechatpay-Timestamp": timestamp,
                       "Wechatpay-Nonce": header_nonce, "Wechatpay-Signature": base64.b64encode(signature).decode(),
                       "Wechatpay-Serial": "0123456789ABCDEF"}
            return "/payments/wechat/callback", raw, headers
        self.assertIsNone(refund, "Alipay refund uses authoritative query, not an invented callback")
        clock = now.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
        raw = self.fixture._alipay_callback(out_trade_no=row["merchant_order_no"], trade_no=payment_id,
                notify_id=event_id, total_amount=f"{amount / 100:.2f}", notify_time=clock, gmt_payment=clock)
        return "/payments/alipay/callback", raw, {"Content-Type": "application/x-www-form-urlencoded"}

    def test_actual_api_and_both_signed_callback_routes_share_one_capture(self):
        for provider in ("wechatpay_direct", "alipay_direct"):
            with self.subTest(provider=provider), ExitStack() as stack:
                uid, token, key, key_hash, targets, app_id, env = self.subject(provider)
                gateway = mock.Mock()
                gateway.create_payment.side_effect = lambda request: self.pending(request, provider, app_id)
                self.configure(stack, provider, app_id, env, gateway)
                with self.stage(provider, targets) as writer:
                    with dml.CaptureBroker(writer.capture, writer.capture.path.parent / "capture.sock") as broker:
                        api_proxy = dml.CaptureProxy(broker.path, context=writer.capture.context)
                        callback_proxy = dml.CaptureProxy(broker.path, context=writer.capture.context)
                        try:
                            api_writer = dml.CanaryWriter(api_proxy, self.connect, self.db.Transaction)
                            callback_writer = dml.CanaryWriter(callback_proxy, self.connect, self.db.Transaction)
                            scope = self.scope(api_writer, uid, key, key_hash, app_id, provider)
                            self.runtime.app.state.item31_canary_callback_resolver = dml.CanaryScope(
                                callback_writer, self.db.fetchone, user_id=uid, idempotency_key_hash=key_hash,
                                app_id=app_id, prod_mode=True, create_context=scope.create_context)
                            created = self.post_order(provider, token, key)
                            self.assertEqual(created.status_code, 200, created.text)
                            repeated = self.post_order(provider, token, key)
                            self.assertEqual(repeated.status_code, 409, repeated.text)
                            row = self.db.fetchone("SELECT * FROM payment_orders WHERE id=?", (created.json()["order"]["id"],))
                            path, raw, headers = self.signed_callback(provider, row)
                            for _ in range(2):
                                result = self.callbacks.post(path, content=raw, headers=headers)
                                self.assertEqual(result.status_code, 200, result.text)
                            gateway.create_payment.assert_called_once()
                        finally:
                            api_proxy.close()
                            callback_proxy.close()
                self.assertEqual(self.stage_counts["payment_orders"], 4)
                self.assertEqual(self.stage_counts["payment_events"], 3)
                self.assertEqual(self.stage_counts["payment_cash_ledger"], 1)
                self.assertEqual(self.stage_counts["payment_entitlement_ledger"], 1)
                self.assertEqual(self.db.fetchone("SELECT balance FROM credits WHERE user_id=?", (uid,))["balance"], 30)

    def test_actual_api_provider_unknown_marker_is_counted_without_retry(self):
        provider = "wechatpay_direct"
        uid, token, key, key_hash, targets, app_id, env = self.subject(provider)
        gateway = mock.Mock()
        gateway.create_payment.side_effect = TimeoutError("synthetic provider outcome unknown")
        with ExitStack() as stack:
            self.configure(stack, provider, app_id, env, gateway)
            with self.stage(provider, targets) as writer:
                self.scope(writer, uid, key, key_hash, app_id, provider)
                response = self.post_order(provider, token, key)
                self.assertEqual(response.status_code, 503, response.text)
                self.assertEqual(response.json()["detail"], "PAYMENT_PROVIDER_OUTCOME_UNKNOWN")
            self.assertEqual(self.stage_counts, {"payment_orders": 3})
            gateway.create_payment.assert_called_once()

    def test_native_asyncio_cancel_joins_worker_before_capture_can_finish(self):
        provider = "wechatpay_direct"
        uid, token, key, key_hash, targets, app_id, env = self.subject(provider)
        entered, release = threading.Event(), threading.Event()
        gateway = mock.Mock()
        def delayed(request):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test provider release timeout")
            return self.pending(request, provider, app_id)
        gateway.create_payment.side_effect = delayed
        with ExitStack() as stack:
            self.configure(stack, provider, app_id, env, gateway)
            with self.stage(provider, targets) as writer:
                self.scope(writer, uid, key, key_hash, app_id, provider)
                async def scenario():
                    from starlette.requests import Request
                    request = Request({"type": "http", "app": self.api.app})
                    task = asyncio.create_task(self.api.payment_order_create(
                        self.api.PaymentOrderInput(product_kind="credit_package", product_id="starter", provider=provider),
                        request, key, {"id": uid}))
                    self.assertTrue(await asyncio.to_thread(entered.wait, 3))
                    task.cancel()
                    await asyncio.sleep(0)
                    self.assertFalse(task.done())
                    with self.assertRaisesRegex(ValueError, "action still in flight"):
                        writer.capture.finish(admission_closed=True)
                    self.assertFalse(writer.capture.broken)
                    release.set()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                try:
                    asyncio.run(scenario())
                finally:
                    release.set()
            self.assertEqual(self.stage_counts, {"payment_orders": 3})
            gateway.create_payment.assert_called_once()

    def test_same_key_other_user_does_not_break_scoped_dynamic_order_predicate(self):
        provider = "wechatpay_direct"
        uid, token, key, key_hash, targets, app_id, env = self.subject(provider)
        other_uid, _, _, _, _, _, _ = self.subject(provider)
        self.payment.create_order(other_uid, "credit_package", "starter", idempotency_key=key,
                                  app_id=app_id, prod_mode=True, provider_name=provider)
        gateway = mock.Mock()
        gateway.create_payment.side_effect = lambda request: self.pending(request, provider, app_id)
        with ExitStack() as stack:
            self.configure(stack, provider, app_id, env, gateway)
            with self.stage(provider, targets) as writer:
                self.scope(writer, uid, key, key_hash, app_id, provider)
                created = self.post_order(provider, token, key)
                self.assertEqual(created.status_code, 200, created.text)
                row = self.db.fetchone("SELECT * FROM payment_orders WHERE id=?", (created.json()["order"]["id"],))
                path, raw, headers = self.signed_callback(provider, row)
                self.assertEqual(self.callbacks.post(path, content=raw, headers=headers).status_code, 200)
            self.assertEqual(self.stage_counts["payment_cash_ledger"], 1)
            self.assertIsNone(self.db.fetchone("SELECT * FROM credits WHERE user_id=?", (other_uid,)))

    def test_two_real_process_writers_register_with_one_broker(self):
        provider = "wechatpay_direct"
        uid, _, key, _, targets, app_id, _ = self.subject(provider)
        order = self.payment.create_order(uid, "credit_package", "starter", idempotency_key=key,
                                         app_id=app_id, prod_mode=True, provider_name=provider)
        code = """
import json,sys
from pathlib import Path
import psycopg,db,payment_contract
from tools import collect_item31_canary_dml as dml
path,context,params,order,operation=json.loads(sys.argv[1])
proxy=dml.CaptureProxy(Path(path),context=context)
connect=lambda:psycopg.connect(**params,autocommit=True,row_factory=db._compat_row_factory)
writer=dml.CanaryWriter(proxy,connect,db.Transaction)
try:
    with proxy.action():
        getattr(payment_contract,operation)(order,transaction_factory=writer)
finally:
    proxy.close()
"""
        with self.stage(provider, targets) as writer:
            with dml.CaptureBroker(writer.capture, writer.capture.path.parent / "capture.sock") as broker:
                for operation in ("admit_payment_submission", "mark_payment_submission_unknown"):
                    result = subprocess.run([sys.executable, "-c", code, json.dumps([
                        str(broker.path), writer.capture.context, self.connection_args, order["id"], operation])],
                        capture_output=True, text=True, timeout=15, env={**os.environ,
                        "PYTHONPATH": str(Path(__file__).resolve().parents[1]) + os.pathsep + str(Path(self.db.__file__).parent)})
                    self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.stage_counts, {"payment_orders": 2})

    def test_broker_disconnect_with_open_action_never_seals(self):
        provider = "wechatpay_direct"
        _, _, _, _, targets, _, _ = self.subject(provider)
        with self.assertRaisesRegex(ValueError, "capture incomplete"):
            with self.stage(provider, targets) as writer:
                with dml.CaptureBroker(writer.capture, writer.capture.path.parent / "capture.sock") as broker:
                    proxy = dml.CaptureProxy(broker.path, context=writer.capture.context)
                    proxy._call("action_begin")
                    proxy.close()
                    for thread in broker.threads:
                        thread.join(2)
                    self.assertTrue(writer.capture.broken)

# Imported fixture class is not another test suite in this module.
del PG
