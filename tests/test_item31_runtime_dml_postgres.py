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


class CanaryAckFaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.activation = str(uuid.uuid4())
        self.runtime = object.__new__(dml.CanaryRuntime)
        self.runtime.role = "payment"
        self.runtime.binding = {"provider": "wechatpay_direct", "activation": self.activation,
            "work_directory": str(self.directory), "reconciliation_run_id": None}
        self.runtime.database = mock.Mock()
        self.runtime.database.fetchone.return_value = {"id": str(uuid.uuid4()),
            "payment_status": "succeeded", "entitlement_status": "applied"}
        self.runtime.scope = mock.Mock()
        self.runtime._admission_check = mock.Mock()
        self.result = {"ok": True, "duplicate": False, "order_id": str(uuid.uuid4()),
            "callback_audit": {"provider": "wechatpay_direct", "event_type": "payment.succeeded",
                "callback_identity_sha256": "a" * 64, "callback_payload_sha256": "b" * 64}}
        patcher = mock.patch.dict(os.environ, {"NOTEAI_ITEM31_WECHAT_ACK_FAILURE_ONCE": self.activation})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_one_fault_for_concurrent_and_recreated_helpers(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(lambda _: self.runtime.reserve_wechat_ack_failure(self.result), range(4)))
        self.assertEqual(outcomes.count(True), 1)
        second = object.__new__(dml.CanaryRuntime)
        second.__dict__.update(self.runtime.__dict__)
        self.assertFalse(second.reserve_wechat_ack_failure(self.result))
        marker = self.directory / "wechat-ack-failure-once.json"
        self.assertEqual(marker.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(marker.read_text())["state"], "FAULT_RESERVED")

    def test_wrong_scope_and_nonpayment_results_do_not_reserve(self):
        for change in ({"duplicate": True}, {"ok": False}, {"code": "UNKNOWN"}, {"ignored": True},
                       {"callback_audit": {**self.result["callback_audit"], "event_type": "refund.succeeded"}}):
            self.assertFalse(self.runtime.reserve_wechat_ack_failure({**self.result, **change}))
        with mock.patch.dict(os.environ, {"NOTEAI_ITEM31_WECHAT_ACK_FAILURE_ONCE": ""}):
            self.assertFalse(self.runtime.reserve_wechat_ack_failure(self.result))
        self.runtime.scope.validate_order.side_effect = ValueError("wrong order")
        self.assertFalse(self.runtime.reserve_wechat_ack_failure(self.result))
        self.assertFalse((self.directory / "wechat-ack-failure-once.json").exists())

    def test_uncertain_file_write_is_not_retried(self):
        with mock.patch.object(dml.os, "fsync", side_effect=OSError("isolated test failure")):
            self.assertFalse(self.runtime.reserve_wechat_ack_failure(self.result))
        marker = self.directory / "wechat-ack-failure-once.json"
        original = marker.read_bytes()
        self.assertFalse(self.runtime.reserve_wechat_ack_failure(self.result))
        self.assertEqual(marker.read_bytes(), original)


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
        # The production Docker COPY gives this existing tool a top-level name.
        # Do not snapshot/restore all sys.modules: NumPy cannot be reimported.
        sys.modules.setdefault("collect_item31_canary_dml", dml)
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
        self.addCleanup(lambda: self.api.app.state._state.pop("item31_canary_runtime", None))
        self.addCleanup(lambda: self.runtime.app.state._state.pop("item31_canary_runtime", None))

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
            "NOTEAI_PAYMENT_CANARY_OWNER_TEST_ASSERTION": "ITEM31-OWNER-CONTROLLED-TEST-ORDER",
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

    def test_wechat_committed_callback_fault_then_duplicate_has_one_entitlement(self):
        provider = "wechatpay_direct"
        with ExitStack() as stack:
            uid, token, key, key_hash, targets, app_id, env = self.subject(provider)
            gateway = mock.Mock()
            gateway.create_payment.side_effect = lambda request: self.pending(request, provider, app_id)
            self.configure(stack, provider, app_id, env, gateway)
            with self.stage(provider, targets) as writer:
                scope = self.scope(writer, uid, key, key_hash, app_id, provider)
                runtime = object.__new__(dml.CanaryRuntime)
                runtime.role, runtime.database, runtime.scope = "payment", self.db, scope
                runtime.binding = {"activation": writer.capture.context["activation"], "provider": provider,
                    "work_directory": str(writer.capture.path.parent), "reconciliation_run_id": None}
                self.runtime.app.state.item31_canary_runtime = runtime
                stack.enter_context(mock.patch.dict(os.environ, {
                    "NOTEAI_ITEM31_WECHAT_ACK_FAILURE_ONCE": runtime.binding["activation"]}))
                created = self.post_order(provider, token, key)
                self.assertEqual(created.status_code, 200, created.text)
                row = self.db.fetchone("SELECT * FROM payment_orders WHERE id=?", (created.json()["order"]["id"],))
                path, raw, headers = self.signed_callback(provider, row)
                first = self.callbacks.post(path, content=raw, headers=headers)
                self.assertEqual(first.status_code, 503, first.text)
                self.assertEqual(first.json()["detail"], "PAYMENT_CANARY_ACK_DELIVERY_TEST")
                self.assertEqual(self.db.fetchone("SELECT balance FROM credits WHERE user_id=?", (uid,))["balance"], 30)
                # Same authenticated provider fixture; production must receive a
                # genuine provider redelivery, never replay these fixture bytes.
                second = self.callbacks.post(path, content=raw, headers=headers)
                self.assertEqual(second.status_code, 200, second.text)
                self.assertEqual(self.db.fetchone("SELECT balance FROM credits WHERE user_id=?", (uid,))["balance"], 30)
                duplicate = self.db.fetchone("SELECT duplicate_delivery_count FROM payment_events WHERE order_id=?", (row["id"],))
                self.assertEqual(duplicate["duplicate_delivery_count"], 1)
                gateway.create_payment.assert_called_once()
            self.assertEqual(self.stage_counts["payment_cash_ledger"], 1)
            self.assertEqual(self.stage_counts["payment_entitlement_ledger"], 1)
            self.assertEqual(self.stage_counts["payment_events"], 3)

    def test_real_startup_shutdown_binds_standard_api_payment_and_executor_entry(self):
        # Exercise the actual ASGI startup/shutdown hooks. Only unrelated model/
        # prompt warmup and provider transport/production role checks are mocked.
        for provider in ("wechatpay_direct", "alipay_direct"):
            with self.subTest(provider=provider), ExitStack() as stack:
                uid, token, key, key_hash, targets, app_id, env = self.subject(provider)
                gateway = mock.Mock()
                gateway.create_payment.side_effect = lambda request: self.pending(request, provider, app_id)
                self.configure(stack, provider, app_id, env, gateway)
                context = self.api._item31_create_canary_context(provider_name=provider, user_id=uid,
                    product_kind="credit_package", product_id="starter", idempotency_key=key, prod_mode=True)
                directory = Path(stack.enter_context(tempfile.TemporaryDirectory()))
                activation = str(uuid.uuid4())
                binding = {"activation": activation, "provider": provider, "targets": targets,
                    "work_directory": str(directory), "user_id": uid, "idempotency_key_hash": key_hash,
                    "app_id": app_id, "create_context": context, "reconciliation_run_id": None}
                path = directory / "binding.json"
                raw = json.dumps(binding, sort_keys=True).encode()
                path.write_bytes(raw)
                path.chmod(0o600)
                stack.enter_context(mock.patch.dict(os.environ, {"NOTEAI_ITEM31_DML_BINDING_FILE": str(path),
                    "NOTEAI_ITEM31_DML_BINDING_SHA256": hashlib.sha256(raw).hexdigest()}))
                owner = self.connect()
                stack.callback(owner.close)
                for statement in dml.installation_sql(activation, targets):
                    owner.execute(statement)
                stack.callback(lambda: [owner.execute(s) for s in dml.removal_sql(list(targets))])
                def default_autocommit_false():
                    connection = self.connect()
                    connection.autocommit = False
                    return connection
                stack.enter_context(mock.patch.object(self.db, "get_conn", default_autocommit_false))
                stack.enter_context(mock.patch.object(self.api._private_storage, "configure_from_environment"))
                for name in ("_ensure_model_artifacts_once", "get_v04_composite_model", "get_model", "_init_analysis_log", "_init_user_learn"):
                    stack.enter_context(mock.patch.object(self.api, name))
                stack.enter_context(mock.patch.object(self.api, "_SCHEDULER_AVAILABLE", False))
                stack.enter_context(mock.patch.object(self.api._pm, "audit_versioned_baseline"))
                with mock.patch.dict(os.environ, {"NOTEAI_RUNTIME_ROLE": "payment"}):
                    with TestClient(self.runtime.app) as callback_client:
                        payment_runtime = self.runtime.app.state.item31_canary_runtime
                        with mock.patch.dict(os.environ, {"NOTEAI_RUNTIME_ROLE": "api"}):
                            with TestClient(self.api.app):
                                created = self.post_order(provider, token, key)
                                self.assertEqual(created.status_code, 200, created.text)
                                row = self.db.fetchone("SELECT * FROM payment_orders WHERE id=?", (created.json()["order"]["id"],))
                                route, body, headers = self.signed_callback(provider, row)
                                with mock.patch.dict(os.environ, {"NOTEAI_RUNTIME_ROLE": "payment"}):
                                    result = callback_client.post(route, content=body, headers=headers)
                                    self.assertEqual(result.status_code, 200, result.text)
                                # The existing main CLI must actually provide the
                                # bound factory; no alternate operator wrapper.
                                def operator(argv, *, transaction_factory):
                                    self.assertIsNotNone(transaction_factory)
                                    with transaction_factory.action(), transaction_factory(write=True) as tx:
                                        tx.execute("UPDATE payment_orders SET updated_at=updated_at WHERE id=?", (row["id"],))
                                    return {"ok": True}
                                with mock.patch.dict(os.environ, {"NOTEAI_RUNTIME_ROLE": "payment-canary"}), \
                                     mock.patch.object(sys, "argv", ["payment_canary_executor.py", "query-payment", provider, row["id"]]), \
                                     mock.patch.object(self.executor, "execute", side_effect=operator), \
                                     mock.patch("builtins.print"):
                                    self.assertEqual(self.executor.main(), 0)
                        self.assertIs(self.runtime.app.state.item31_canary_callback_resolver, payment_runtime.scope)
                result = payment_runtime.result
                self.assertEqual(result["write_mutations_by_table"]["payment_orders"], 5)
                self.assertEqual(result["write_mutations_by_table"]["payment_events"], 2)
                self.assertEqual(dml.read_journal(directory / "canary-dml.jsonl", **payment_runtime.capture.context), result)
                self.assertFalse((directory / "capture.sock").exists())
                # A completed capture is not silently replaced at restart.
                with mock.patch.dict(os.environ, {"NOTEAI_RUNTIME_ROLE": "payment"}), self.assertRaises(ValueError):
                    dml.configured_runtime("payment", self.db)
                self.api.app.state._state.pop("item31_canary_runtime", None)
                self.runtime.app.state._state.pop("item31_canary_runtime", None)

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

    def test_callback_can_finish_before_api_provider_response_without_downgrade(self):
        for provider in ("wechatpay_direct", "alipay_direct"):
            with self.subTest(provider=provider), ExitStack() as stack:
                uid, token, key, key_hash, targets, app_id, env = self.subject(provider)
                gateway = mock.Mock()
                def respond(request):
                    row = self.db.fetchone("SELECT * FROM payment_orders WHERE merchant_order_no=?", (request["merchant_order_no"],))
                    route, body, headers = self.signed_callback(provider, row)
                    result = self.callbacks.post(route, content=body, headers=headers)
                    self.assertEqual(result.status_code, 200, result.text)
                    return self.pending(request, provider, app_id)
                gateway.create_payment.side_effect = respond
                self.configure(stack, provider, app_id, env, gateway)
                with self.stage(provider, targets) as writer:
                    self.scope(writer, uid, key, key_hash, app_id, provider)
                    response = self.post_order(provider, token, key)
                    self.assertEqual(response.status_code, 200, response.text)
                row = self.db.fetchone("SELECT * FROM payment_orders WHERE id=?", (response.json()["order"]["id"],))
                self.assertEqual(row["payment_status"], "succeeded")
                self.assertEqual(row["entitlement_status"], "applied")
                self.assertEqual(self.stage_counts["payment_cash_ledger"], 1)
                self.assertEqual(self.stage_counts["payment_entitlement_ledger"], 1)
                gateway.create_payment.assert_called_once()

    def test_malformed_runtime_activation_and_hash_only_never_open_connections(self):
        for settings in ({"NOTEAI_PAYMENT_CANARY_ENABLED": " 1 "},
                         {"NOTEAI_ITEM31_DML_BINDING_SHA256": "a" * 64}):
            with self.subTest(settings=settings), mock.patch.dict(os.environ, settings, clear=True), \
                 mock.patch.object(self.db, "get_conn") as connect:
                with self.assertRaisesRegex(ValueError, "ITEM31_RUNTIME_BINDING_FAILED"):
                    asyncio.run(self.runtime.startup())
                connect.assert_not_called()

    def test_same_user_other_order_rejected_before_operator_provider_admission(self):
        provider = "wechatpay_direct"
        uid, token, key, key_hash, targets, app_id, env = self.subject(provider)
        with ExitStack() as stack:
            gateway = mock.Mock()
            gateway.create_payment.side_effect = lambda request: self.pending(request, provider, app_id)
            self.configure(stack, provider, app_id, env, gateway)
            with self.stage(provider, targets) as writer:
                scope = self.scope(writer, uid, key, key_hash, app_id, provider)
                response = self.post_order(provider, token, key)
                row = self.db.fetchone("SELECT * FROM payment_orders WHERE id=?", (response.json()["order"]["id"],))
                # Existing order lookup is independent of canary key binding.
                # Simulate its legitimate same-subject different-key result.
                other = {**dict(row), "idempotency_key_hash": "e" * 64}
                with mock.patch.object(self.executor, "_activation", return_value={"order_id": row["id"]}), \
                     mock.patch.object(self.executor, "_assert_runtime_context"), \
                     mock.patch.object(self.executor, "_order", return_value=other), \
                     mock.patch.object(self.executor, "_gateway") as provider_factory, \
                     mock.patch.object(self.executor, "_admit_action") as admit:
                    with self.assertRaises(ValueError):
                        self.executor.execute(["query-payment", provider, row["id"]], transaction_factory=scope.writer)
                    provider_factory.assert_not_called()
                    admit.assert_not_called()

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

    def test_registered_ack_loss_prevents_business_sql_and_preserves_unknown(self):
        provider = "wechatpay_direct"
        uid, _, key, _, targets, app_id, _ = self.subject(provider)
        order = self.payment.create_order(uid, "credit_package", "starter", idempotency_key=key,
                                         app_id=app_id, prod_mode=True, provider_name=provider)
        with self.assertRaisesRegex(ValueError, "capture incomplete"):
            with self.stage(provider, targets) as writer:
                with dml.CaptureBroker(writer.capture, writer.capture.path.parent / "capture.sock") as broker:
                    proxy = dml.CaptureProxy(broker.path, context=writer.capture.context)
                    original = proxy._call
                    def lost(operation, **fields):
                        value = original(operation, **fields)
                        if operation == "register":
                            proxy._broken = True
                            proxy.connection.shutdown(dml.socket.SHUT_RDWR)
                            raise OSError("synthetic lost registration ACK")
                        return value
                    proxy._call = lost
                    try:
                        remote_writer = dml.CanaryWriter(proxy, self.connect, self.db.Transaction)
                        with self.assertRaisesRegex(OSError, "lost registration ACK"), proxy.action():
                            self.payment.admit_payment_submission(order["id"], transaction_factory=remote_writer)
                    finally:
                        proxy.close()
                self.assertTrue(writer.capture.broken)
                self.assertEqual(len(writer.capture.bindings), 1)
                self.assertEqual(self.db.fetchone("SELECT payment_status FROM payment_orders WHERE id=?",
                                                  (order["id"],))["payment_status"], "created")

    def test_api_admission_commit_ack_loss_never_calls_provider_or_default_writer(self):
        provider = "wechatpay_direct"
        uid, token, key, key_hash, targets, app_id, env = self.subject(provider)
        gateway = mock.Mock()
        count = 0
        def connect():
            nonlocal count
            count += 1
            connection = self.connect()
            if count != 2:
                return connection
            class LostCommit:
                def __getattr__(self, key):
                    return getattr(connection, key)
                def commit(self):
                    connection.commit()
                    raise OSError("synthetic lost COMMIT ACK")
            return LostCommit()
        with ExitStack() as stack:
            self.configure(stack, provider, app_id, env, gateway)
            with self.assertRaisesRegex(ValueError, "capture incomplete"):
                with self.stage(provider, targets) as writer:
                    writer.connect = connect
                    self.scope(writer, uid, key, key_hash, app_id, provider)
                    with self.assertRaisesRegex(OSError, "lost COMMIT ACK"):
                        self.post_order(provider, token, key)
                    self.assertTrue(writer.capture.broken)
                    row = self.db.fetchone("SELECT payment_status FROM payment_orders WHERE user_id=?", (uid,))
                    self.assertEqual(row["payment_status"], "pending")
                    gateway.create_payment.assert_not_called()
                    with self.assertRaisesRegex(ValueError, "canary writer unavailable"):
                        self.payment.mark_payment_submission_unknown(
                            self.db.fetchone("SELECT id FROM payment_orders WHERE user_id=?", (uid,))["id"],
                            transaction_factory=writer)

    def test_executor_queries_refund_reconcile_and_settlement_write_real_rows(self):
        # This database was created by this test class on the isolated PG socket.
        # Reset only disposable synthetic rows so a whole-day bill has no earlier
        # test canaries; production data/roles are never involved.
        self.assertTrue(self.database.startswith("noteai_item31_test_"))
        self.db.execute("TRUNCATE users CASCADE")
        for provider in ("wechatpay_direct", "alipay_direct"):
            with self.subTest(provider=provider), ExitStack() as stack:
                uid, token, key, key_hash, targets, app_id, env = self.subject(provider)
                create_gateway = mock.Mock()
                create_gateway.create_payment.side_effect = lambda request: self.pending(request, provider, app_id)
                self.configure(stack, provider, app_id, env, create_gateway)
                gateway = self.fixture.wechat if provider == "wechatpay_direct" else self.fixture.alipay
                with self.stage(provider, targets) as writer:
                    self.scope(writer, uid, key, key_hash, app_id, provider)
                    created = self.post_order(provider, token, key)
                    self.assertEqual(created.status_code, 200, created.text)
                row = self.db.fetchone("SELECT * FROM payment_orders WHERE id=?", (created.json()["order"]["id"],))
                activation = {"action": "query-payment", "provider": provider, "order_id": row["id"],
                    "activation_id": str(uuid.uuid4()), "user_id_sha256": self.executor._identity(uid, "payment-canary-user-v1"),
                    "subject_hash": row["subject_hash"], "amount_fen": 1200, "bill_date": "", "expires_at": int(time.time()) + 300}
                ledger = Path(self.scratch) / provider
                ledger.mkdir(mode=0o700)
                stack.enter_context(mock.patch.object(self.executor, "_ACTION_LEDGER_DIRECTORY", str(ledger)))
                stack.enter_context(mock.patch.object(self.executor, "_assert_runtime_context"))
                stack.enter_context(mock.patch.object(self.executor, "_bound_canary_user_id_sha256", return_value=activation["user_id_sha256"]))
                stack.enter_context(mock.patch.object(self.executor, "_activation", side_effect=lambda action, *_: {**activation, "action": action}))
                stack.enter_context(mock.patch.object(self.executor, "_gateway", return_value=(gateway, {})))
                pending = self.pending({"merchant_order_no": row["merchant_order_no"]}, provider, app_id)
                with mock.patch.object(gateway, "_query_payment_with_receipt", return_value=(pending, b"verified local query", "local_signature", int(time.time()))):
                    with self.stage(provider, targets) as writer:
                        self.scope(writer, uid, key, key_hash, app_id, provider)
                        self.executor.execute(["query-payment", provider, row["id"]], transaction_factory=writer)
                    self.assertEqual(self.stage_counts, {"payment_orders": 1})
                with self.stage(provider, targets) as writer:
                    self.scope(writer, uid, key, key_hash, app_id, provider)
                    path, raw, headers = self.signed_callback(provider, row)
                    self.assertEqual(self.callbacks.post(path, content=raw, headers=headers).status_code, 200)
                row = self.db.fetchone("SELECT * FROM payment_orders WHERE id=?", (row["id"],))
                def refund_result(request):
                    return self.payment.ProviderRefundResult(
                        merchant_refund_no=request["merchant_refund_no"], provider_refund_id="local_refund_" + row["id"].replace("-", ""),
                        status="pending", amount_fen=1200, app_id=app_id, prod_mode=True, response_verified=True,
                        provider_name=provider, merchant_order_no=row["merchant_order_no"], provider_payment_id=row["provider_payment_id"],
                        provider_submitted_at=int(time.time()) if provider == "wechatpay_direct" else None)
                with mock.patch.object(gateway, "create_refund", side_effect=refund_result) as refund_call:
                    with self.stage(provider, targets) as writer:
                        self.scope(writer, uid, key, key_hash, app_id, provider)
                        self.executor.execute(["submit-refund", provider, row["id"], "customer_request"], transaction_factory=writer)
                    self.assertEqual(self.stage_counts["payment_refunds"], 3)
                    refund_call.assert_called_once()
                refund = self.db.fetchone("SELECT * FROM payment_refunds WHERE order_id=?", (row["id"],))
                terminal = self.payment.ProviderRefundResult(
                    merchant_refund_no=refund["merchant_refund_no"], provider_refund_id=refund["provider_refund_id"],
                    status="succeeded", amount_fen=1200, app_id=app_id, prod_mode=True, response_verified=True,
                    provider_name=provider, merchant_order_no=row["merchant_order_no"], provider_payment_id=row["provider_payment_id"],
                    provider_created_at=int(time.time()), provider_submitted_at=refund["provider_submitted_at"])
                with mock.patch.object(gateway, "_query_refund_with_receipt", return_value=(terminal, b"verified refund query", "local_signature", int(time.time()))):
                    with self.stage(provider, targets) as writer:
                        self.scope(writer, uid, key, key_hash, app_id, provider)
                        self.executor.execute(["query-refund", provider, row["id"]], transaction_factory=writer)
                    self.assertEqual(self.stage_counts["payment_cash_ledger"], 1)
                    self.assertEqual(self.stage_counts["payment_entitlement_ledger"], 1)
                self.assertEqual(self.db.fetchone("SELECT balance FROM credits WHERE user_id=?", (uid,))["balance"], 0)
                day = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
                bill = [{"kind": "payment", "reference": row["merchant_order_no"], "amount_fen": 1200, "status": "succeeded"},
                        {"kind": "refund", "reference": refund["merchant_refund_no"], "amount_fen": 1200, "status": "succeeded"}]
                run_id = str(uuid.uuid4())
                targets["payment_reconciliation_runs"] = ("id", run_id)
                targets["payment_reconciliation_items"] = ("run_id", run_id)
                with mock.patch.object(gateway, "reconciliation_rows", return_value=(b"synthetic verified bill " + provider.encode(), bill)):
                    with self.stage(provider, targets) as writer:
                        result = self.executor.execute(["reconcile", provider, day], transaction_factory=writer, reconciliation_run_id=run_id)
                        self.assertTrue(result["ok"], result)
                    self.assertEqual(self.stage_counts, {"payment_reconciliation_runs": 1})
                for rows in (bill, [{**bill[0], "amount_fen": 1100}], []):
                    source = json.dumps(rows, sort_keys=True).encode()
                    run_id = str(uuid.uuid4())
                    targets["payment_reconciliation_runs"] = ("id", run_id)
                    targets["payment_reconciliation_items"] = ("run_id", run_id)
                    with self.stage(provider, targets) as writer:
                        result = self.payment.reconcile_bill(day, source, rows, prod_mode=True,
                            provider_name=provider, transaction_factory=writer, reconciliation_run_id=run_id)
                        again = self.payment.reconcile_bill(day, source, rows, prod_mode=True,
                            provider_name=provider, transaction_factory=writer, reconciliation_run_id=run_id)
                        self.assertEqual(result["id"], again["id"])
                    self.assertEqual(self.stage_counts["payment_reconciliation_runs"], 1)
                    self.assertEqual(self.stage_counts.get("payment_reconciliation_items", 0), result["discrepancy_count"])
                digest = hashlib.sha256((provider + "synthetic settlement").encode()).hexdigest()
                targets["payment_settlement_summaries"] = ("source_sha256", digest)
                with self.stage(provider, targets) as writer:
                    self.payment.record_settlement_summary(day, source_sha256=digest, gross_fen=1200,
                        refund_fen=1200, fee_fen=0, net_fen=0, prod_mode=True, provider_name=provider,
                        transaction_factory=writer)
                self.assertEqual(self.stage_counts, {"payment_settlement_summaries": 1})

    # Normal Native writers and same-order next-day reconciliation each seal
    # their own short capture. All gateway material below is a synthetic fixture;
    # actual payment-role/Secret-scope checks remain separately verified.
    def _bind_phase_runtime(self, stack, directory, activation, targets, uid, key_hash, app_id, context, run_id=None):
        directory.mkdir(mode=448)
        binding = {'activation': activation, 'provider': 'wechatpay_direct', 'targets': targets, 'work_directory': str(directory), 'user_id': uid, 'idempotency_key_hash': key_hash, 'app_id': app_id, 'create_context': context, 'reconciliation_run_id': run_id}
        path = directory / 'binding.json'
        raw = json.dumps(binding, sort_keys=True).encode()
        path.write_bytes(raw)
        path.chmod(384)
        stack.enter_context(mock.patch.dict(os.environ, {'NOTEAI_ITEM31_DML_BINDING_FILE': str(path), 'NOTEAI_ITEM31_DML_BINDING_SHA256': hashlib.sha256(raw).hexdigest()}))
        return binding

    def test_native_two_closed_captures_one_order(self):
        # The next-day bill covers the full day, so isolate this one-order
        # scenario from earlier synthetic canaries in this disposable test DB.
        self.assertTrue(self.database.startswith("noteai_item31_test_"))
        self.db.execute("TRUNCATE users CASCADE")
        p = 'wechatpay_direct'
        uid, token, key, key_hash, targets, app_id, env = self.subject(p)
        root = Path(self.scratch)
        ledger = root / 'actions'
        ledger.mkdir(mode=448)
        with ExitStack() as common:
            common.enter_context(mock.patch.object(self.payment, '_now', return_value=datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=3)))
            common.enter_context(mock.patch.object(self.executor, '_ACTION_LEDGER_DIRECTORY', str(ledger)))
            common.enter_context(mock.patch.object(self.executor, '_bound_canary_user_id_sha256', return_value=env['NOTEAI_PAYMENT_CANARY_USER_ID_SHA256']))
            common.enter_context(mock.patch.object(self.executor, '_database_role_ok', return_value=True))
            common.enter_context(mock.patch.object(self.executor, '_provider_secret_scope_ok', return_value=True))
            gateway = self.fixture.wechat
            common.enter_context(mock.patch.object(self.executor, '_gateway', return_value=(gateway, {})))
            owner = self.connect()
            common.callback(owner.close)
            create_gateway = mock.Mock()
            create_gateway.create_payment.side_effect = lambda request: self.pending(request, p, app_id)
            with ExitStack() as day1:
                self.configure(day1, p, app_id, env, create_gateway)
                context = self.api._item31_create_canary_context(provider_name=p, user_id=uid, product_kind='credit_package', product_id='starter', idempotency_key=key, prod_mode=True)
                first = self._bind_phase_runtime(day1, root / 'day1', env['NOTEAI_PAYMENT_CANARY_ACTIVATION_ID'], targets, uid, key_hash, app_id, context)
                for sql in dml.installation_sql(first['activation'], targets):
                    owner.execute(sql)
                with mock.patch.dict(os.environ, {'NOTEAI_RUNTIME_ROLE': 'payment'}):
                    broker1 = dml.configured_runtime('payment', self.db)
                self.addCleanup(lambda: broker1.close(clean=False))
                with mock.patch.dict(os.environ, {'NOTEAI_RUNTIME_ROLE': 'api'}):
                    api_runtime = dml.configured_runtime('api', self.db)
                self.addCleanup(api_runtime.close)
                self.api.app.state.item31_canary_create_resolver = api_runtime.scope.create
                self.runtime.app.state.item31_canary_callback_resolver = broker1.scope
                created = self.post_order(p, token, key)
                self.assertEqual(created.status_code, 200, created.text)
                order_id = created.json()['order']['id']
                row = self.db.fetchone('SELECT * FROM payment_orders WHERE id=?', (order_id,))
                route, body, headers = self.signed_callback(p, row)
                result = self.callbacks.post(route, content=body, headers=headers)
                self.assertEqual(result.status_code, 200, result.text)
                row = self.db.fetchone('SELECT * FROM payment_orders WHERE id=?', (order_id,))

                def refund_result(request):
                    return self.payment.ProviderRefundResult(merchant_refund_no=request['merchant_refund_no'], provider_refund_id='synthetic_refund_' + order_id.replace('-', ''), status='pending', amount_fen=1200, app_id=app_id, prod_mode=True, response_verified=True, provider_name=p, merchant_order_no=row['merchant_order_no'], provider_payment_id=row['provider_payment_id'], provider_submitted_at=int(time.time()))
                with mock.patch.dict(os.environ, {'NOTEAI_RUNTIME_ROLE': 'payment-canary', 'NOTEAI_PAYMENT_CANARY_ACTION': 'submit-refund', 'NOTEAI_PAYMENT_CANARY_ORDER_ID': order_id}), mock.patch.object(gateway, 'create_refund', side_effect=refund_result) as refund_call:
                    operator1 = dml.configured_runtime('payment-canary', self.db)
                    try:
                        result = self.executor.execute(['submit-refund', p, order_id, 'customer_request'], transaction_factory=operator1.writer)
                        self.assertTrue(result['ok'], result)
                        with self.assertRaisesRegex(self.executor.PaymentCanaryError, 'ACTION_ALREADY_ADMITTED'):
                            self.executor.execute(['submit-refund', p, order_id, 'customer_request'], transaction_factory=operator1.writer)
                        refund_call.assert_called_once()
                    finally:
                        operator1.close()
                refund = self.db.fetchone('SELECT * FROM payment_refunds WHERE order_id=?', (order_id,))
                route, body, headers = self.signed_callback(p, row, refund=refund)
                outer = json.loads(body)
                resource = outer['resource']
                cipher = AESGCM(b'synthetic-api-v3-key-material-00')
                payload = json.loads(cipher.decrypt(resource['nonce'].encode(), base64.b64decode(resource['ciphertext']), resource['associated_data'].encode()))
                payload['amount'].pop('currency', None)
                payload['refund_id'] = refund['provider_refund_id']
                resource['ciphertext'] = base64.b64encode(cipher.encrypt(resource['nonce'].encode(), json.dumps(payload, separators=(',', ':')).encode(), resource['associated_data'].encode())).decode()
                body = json.dumps(outer, separators=(',', ':')).encode()
                headers['Wechatpay-Signature'] = base64.b64encode(self.fixture.wechat_private.sign((headers['Wechatpay-Timestamp'] + '\n' + headers['Wechatpay-Nonce'] + '\n').encode() + body + b'\n', padding.PKCS1v15(), hashes.SHA256())).decode()
                result = self.callbacks.post(route, content=body, headers=headers)
                self.assertEqual(result.status_code, 200, result.text)
                broker1.close()
                # The drained API may still own Payment's network namespace.
                # Closing the broker must safely disconnect this idle proxy.
                api_runtime.close()
                self.assertEqual(dml.read_journal(root / 'day1/canary-dml.jsonl', **broker1.capture.context), broker1.result)
                self.assertEqual(broker1.result['status'], 'CAPTURE_COMPLETE_NOT_TERMINAL')
                for sql in dml.removal_sql(list(targets)):
                    owner.execute(sql)
                create_gateway.create_payment.assert_called_once()
            self.api.app.state._state.pop('item31_canary_create_resolver', None)
            self.runtime.app.state._state.pop('item31_canary_callback_resolver', None)
            day1_bytes = (root / 'day1/canary-dml.jsonl').read_bytes()
            day1_ledger = {f.name: f.read_bytes() for f in ledger.glob('*.json')}
            self.assertEqual(len(day1_ledger), 1)
            paid = self.db.fetchone('SELECT * FROM payment_orders WHERE id=?', (order_id,))
            self.assertEqual(paid['refund_status'], 'refunded')
            self.assertEqual(paid['refunded_fen'], 1200)
            self.assertEqual(self.db.fetchone('SELECT balance FROM credits WHERE user_id=?', (uid,))['balance'], 0)
            bill_day = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
            next_epoch = int(time.time()) + 86400
            next_activation = str(uuid.uuid4())
            run_id = str(uuid.uuid4())
            targets2 = dict(targets)
            targets2['payment_reconciliation_runs'] = ('id', run_id)
            targets2['payment_reconciliation_items'] = ('run_id', run_id)
            next_env = {**env, 'NOTEAI_RUNTIME_ROLE': 'payment', 'NOTEAI_PAYMENT_CANARY_ACTION': 'reconcile', 'NOTEAI_PAYMENT_CANARY_ACTIVATION_ID': next_activation, 'NOTEAI_PAYMENT_CANARY_ORDER_ID': order_id, 'NOTEAI_PAYMENT_CANARY_BILL_DATE': bill_day, 'NOTEAI_PAYMENT_CANARY_NOT_BEFORE_EPOCH': str(next_epoch - 5), 'NOTEAI_PAYMENT_CANARY_EXPIRES_EPOCH': str(next_epoch + 300), 'NOTEAI_PAYMENT_CALLBACK_ENABLED': '0', 'NOTEAI_PAYMENT_CALLBACK_RELAY_ENABLED': '0', 'NOTEAI_PAYMENT_ORDERING_ENABLED': '0'}
            bill = [{'kind': 'payment', 'reference': row['merchant_order_no'], 'amount_fen': 1200, 'status': 'succeeded'}, {'kind': 'refund', 'reference': refund['merchant_refund_no'], 'amount_fen': 1200, 'status': 'succeeded'}]
            with ExitStack() as day2:
                day2.enter_context(mock.patch.dict(os.environ, next_env))
                day2.enter_context(mock.patch.object(time, 'time', return_value=next_epoch))
                day2.enter_context(mock.patch.object(self.payment, '_now', return_value=datetime.fromtimestamp(next_epoch, timezone.utc)))
                day2.enter_context(mock.patch.object(self.api._payment_adapter_runtime, 'configured_app_id', return_value=app_id))
                day2.enter_context(mock.patch.object(self.api._payment_adapter_runtime, 'configured_prod_mode', return_value=True))
                second = self._bind_phase_runtime(day2, root / 'day2', next_activation, targets2, uid, key_hash, app_id, context, run_id)
                self.assertNotEqual(first['activation'], second['activation'])
                self.assertEqual(first['create_context'], second['create_context'])
                self.assertEqual(first['idempotency_key_hash'], second['idempotency_key_hash'])
                for sql in dml.installation_sql(second['activation'], targets2):
                    owner.execute(sql)
                self.assertFalse(self.runtime._callback_available(p))
                broker2 = dml.configured_runtime('payment', self.db)
                self.addCleanup(lambda: broker2.close(clean=False))
                with mock.patch.dict(os.environ, {'NOTEAI_RUNTIME_ROLE': 'api'}), self.assertRaisesRegex(ValueError, 'ITEM31_RUNTIME_BINDING_FAILED'):
                    dml.configured_runtime('api', self.db)
                with mock.patch.dict(os.environ, {'NOTEAI_RUNTIME_ROLE': 'payment-canary'}):
                    operator2 = dml.configured_runtime('payment-canary', self.db)
                    try:
                        with self.assertRaisesRegex(ValueError, 'canary create binding'):
                            operator2.scope.create({**context, 'idempotency_identity_sha256': '0' * 64})
                        with self.assertRaisesRegex(ValueError, 'canary callback order'):
                            operator2.scope.validate_order({**dict(paid), 'idempotency_key_hash': '0' * 64})
                        with self.assertRaisesRegex(self.executor.PaymentCanaryError, 'ACTIVATION_INVALID'):
                            self.executor.execute(['submit-refund', p, order_id, 'customer_request'], transaction_factory=operator2.writer)
                        with mock.patch.dict(os.environ, {'NOTEAI_PAYMENT_CANARY_ACTION': 'submit-refund'}), self.assertRaisesRegex(self.executor.PaymentCanaryError, 'ACTION_ALREADY_ADMITTED'):
                            self.executor.execute(['submit-refund', p, order_id, 'customer_request'], transaction_factory=operator2.writer)
                        with mock.patch.object(gateway, 'reconciliation_rows', return_value=(b'synthetic-next-day-verified-bill', bill)) as bill_call:
                            result = self.executor.execute(['reconcile', p, bill_day], transaction_factory=operator2.writer, reconciliation_run_id=run_id)
                            self.assertTrue(result['ok'], result)
                            with self.assertRaisesRegex(self.executor.PaymentCanaryError, 'ACTION_ALREADY_ADMITTED'):
                                self.executor.execute(['reconcile', p, bill_day], transaction_factory=operator2.writer, reconciliation_run_id=run_id)
                            bill_call.assert_called_once()
                    finally:
                        operator2.close()
                broker2.close()
                for sql in dml.removal_sql(list(targets2)):
                    owner.execute(sql)
            self.assertEqual(broker2.result['write_mutations_by_table'], {'payment_reconciliation_runs': 1})
            self.assertEqual(dml.read_journal(root / 'day2/canary-dml.jsonl', **broker2.capture.context), broker2.result)
            self.assertEqual((root / 'day1/canary-dml.jsonl').read_bytes(), day1_bytes)
            for name, raw in day1_ledger.items():
                self.assertEqual((ledger / name).read_bytes(), raw)
            self.assertEqual(len(list(ledger.glob('*.json'))), 2)
            self.assertEqual(dml.read_journal(root / 'day1/canary-dml.jsonl', **broker1.capture.context), broker1.result)

# Imported fixture class is not another test suite in this module.
del PG


class NativeCapturePreparationTests(unittest.TestCase):
    def test_stopped_failure_is_preserved_but_job_or_container_blocks_prepare(self):
        from deploy.production import native_capture as launcher
        for state, job, container, allowed in ((b'failed', b'', b'', True),
                (b'inactive', b'', b'', True), (b'active', b'', b'cid', False),
                (b'failed', b'91', b'', False), (b'failed', b'', b'cid', False)):
            with self.subTest(state=state, job=job, container=container), ExitStack() as stack:
                stack.enter_context(mock.patch.object(launcher, 'HASHES', {}))
                stack.enter_context(mock.patch.object(launcher, 'inspect', return_value={'Image': launcher.API_IMAGE}, create=True))
                def run(args, *unused):
                    self.assertNotIn('reset-failed', args)
                    if args[0] == 'systemctl': return state if 'ActiveState' in args else job
                    if args[1] == 'ps': return container
                    return json.dumps([{'Architecture': 'amd64', 'Os': 'linux'}]).encode()
                stack.enter_context(mock.patch.object(launcher, 'run', side_effect=run, create=True))
                if allowed: launcher.check_original()
                else:
                    with self.assertRaises(AssertionError): launcher.check_original()

    def test_prepare_renders_atomic_owner_sql_without_starting_capture(self):
        from deploy.production import native_capture as launcher
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            parent = Path(temp)
            root = parent / 'trade'
            paths = [parent / name for name in ('api.service', 'api.conf', 'payment.service', 'proxy.conf')]
            for path in paths:
                path.write_text('existing ' + path.name)
            web = parent / 'web'; web.mkdir()
            stack.enter_context(mock.patch.multiple(launcher, ROOT=root, API_UNIT=paths[0],
                API_DROP=paths[1], PAYMENT_UNIT=paths[2], PROXIES=[paths[3]]))
            check = stack.enter_context(mock.patch.object(launcher, 'check_original'))
            stack.enter_context(mock.patch.object(launcher.os, 'chown'))
            stack.enter_context(mock.patch.object(launcher, 'Path', side_effect=lambda value:
                web if str(value) == '/var/www/noteai-public/current' else Path(value)))
            stack.enter_context(mock.patch.object(launcher, 'config_hash', return_value='unchanged-config', create=True))
            stack.enter_context(mock.patch.object(launcher, 'inspect', return_value={'Image': 'unchanged-admin'}, create=True))
            def sql_read(code):
                binding = json.loads((root / 'binding.json').read_text())
                self.assertIn('installation_sql', code)
                return {'install': [x.as_string() for x in dml.installation_sql(binding['activation'], binding['targets'])],
                    'remove': [x.as_string() for x in dml.removal_sql(list(binding['targets']))]}
            stack.enter_context(mock.patch.object(launcher, 'api_read', side_effect=sql_read))
            result = launcher.prepare()
            self.assertEqual(result['state'], 'PREPARED_NOT_ACTIVATED')
            binding = json.loads((root / 'binding.json').read_text())
            for phase in ('install', 'remove'):
                text = (root / (phase + '-dms.sql')).read_text()
                self.assertTrue(text.startswith('DO $noteai$'))
                self.assertEqual(text.count('DO $noteai$'), 1)
                self.assertIn(binding['activation'], text)
                self.assertIn("current_user <> 'noteai_admin'", text)
                self.assertTrue((root / (phase + '.sql')).exists())
            self.assertIn('existing capture must be reconciled', (root / 'install-dms.sql').read_text())
            self.assertIn('capture identity mismatch', (root / 'remove-dms.sql').read_text())
            self.assertFalse((root / 'started.json').exists())
            with self.assertRaises(AssertionError):
                launcher.prepare()
            self.assertEqual(json.loads((root / 'binding.json').read_text()), binding)
            self.assertEqual(check.call_count, 2)

    def test_activate_binds_once_only_ack_to_exact_capture_and_restores_ingress(self):
        from deploy.production import native_capture as launcher
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            root = Path(temp)
            paths = [root / name for name in ('api.service', 'api.conf', 'payment.service')]
            before = {p: b'original unit' for p in paths}
            before[paths[1]] = ('[Service]\nExecStart=/usr/bin/docker run --name=noteai-api-c ' + launcher.API_IMAGE + '\n').encode()
            activation = str(uuid.uuid4())
            binding = {'activation': activation}
            (root / 'binding.json').write_text(json.dumps(binding))
            meta = {'activation': activation, 'binding_sha256': launcher.digest((root / 'binding.json').read_bytes()),
                'config_hash': 'unchanged'}
            stack.enter_context(mock.patch.multiple(launcher, ROOT=root, API_UNIT=paths[0], API_DROP=paths[1], PAYMENT_UNIT=paths[2]))
            stack.enter_context(mock.patch.object(launcher, 'check_original'))
            stack.enter_context(mock.patch.object(launcher, 'originals', return_value=(meta, before)))
            stack.enter_context(mock.patch.object(launcher, 'idle', return_value=True, create=True))
            stack.enter_context(mock.patch.object(launcher, 'api_read', side_effect=[{'n': 15, 'matches': True}, {'ready': True}]))
            stack.enter_context(mock.patch.object(launcher, 'drain'))
            stack.enter_context(mock.patch.object(launcher, 'run', return_value=b'', create=True))
            stack.enter_context(mock.patch.object(launcher, 'health', create=True))
            stack.enter_context(mock.patch.object(launcher, 'config_hash', return_value='unchanged', create=True))
            stack.enter_context(mock.patch.object(launcher, 'put', side_effect=lambda p,b: p.write_bytes(b), create=True))
            stack.enter_context(mock.patch.object(launcher.subprocess, 'run', return_value=mock.Mock(
                returncode=0, stdout=json.dumps([{'State': {'Running': True}}]).encode())))
            stack.enter_context(mock.patch.object(launcher, 'inspect', side_effect=lambda name:
                {'Image': launcher.API_IMAGE if name == 'noteai-api-c' else launcher.PAYMENT_IMAGE, 'Id': name}, create=True))
            restore = stack.enter_context(mock.patch.object(launcher, 'restore_ingress'))
            result = launcher.activate()
            env = dict(line.split('=', 1) for line in (root / 'input.env').read_text().splitlines())
            self.assertEqual(env['NOTEAI_ITEM31_WECHAT_ACK_FAILURE_ONCE'], activation)
            self.assertEqual(env['NOTEAI_PAYMENT_CANARY_ACTIVATION_ID'], activation)
            self.assertEqual(env['NOTEAI_PAYMENT_CANARY_AMOUNT_FEN'], '1200')
            self.assertIn(launcher.PAYMENT_IMAGE, paths[2].read_text())
            self.assertIn(launcher.API_IMAGE, paths[1].read_text())
            self.assertIn(str(root / 'input.env'), paths[2].read_text())
            self.assertEqual(result['state'], 'ACTIVE_OWNER_ONLY')
            restore.assert_called_once_with(before)
            with self.assertRaises(AssertionError):
                launcher.activate()


class NativeCaptureShutdownTests(unittest.TestCase):
    def test_network_owner_remains_until_broker_seals_even_for_unknown_journal(self):
        from deploy.production import native_capture as launcher
        for journal in ({'status':'COMPLETE'}, {'status':'UNKNOWN'}):
            with self.subTest(journal=journal), tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
                root = Path(temp)
                paths = [root / name for name in ('api.service','api.conf','payment.service')]
                before = {p: ('original '+p.name).encode() for p in paths}
                for p in paths:
                    p.write_bytes(b'temporary capture unit')
                web = root / 'web'
                web.mkdir()
                state = {'network_owner':True,'payment':True,'drained':False,'read':False}
                stack.enter_context(mock.patch.multiple(launcher, ROOT=root,
                    API_UNIT=paths[0],API_DROP=paths[1],PAYMENT_UNIT=paths[2]))
                stack.enter_context(mock.patch.object(launcher,'originals',return_value=(
                    {'activation':'synthetic-local','admin_image':'unchanged-admin','web':str(web)},before)))
                stack.enter_context(mock.patch.object(launcher,'Path',side_effect=lambda value:
                    web if str(value)=='/var/www/noteai-public/current' else Path(value)))
                def drain():
                    state['drained']=True
                def run(args,*unused):
                    if args[:2] == ['docker','ps']:
                        return ''
                    if args[:2] == ['systemctl','stop']:
                        self.assertTrue(state['drained'])
                        if args[-1] == 'noteai-payment.service':
                            self.assertTrue(state['network_owner'],'lost PG connection before sealing')
                            state['payment']=False
                        else:
                            self.assertTrue(state['read'],'owner stopped before original journal read')
                            state['network_owner']=False
                    if args[:2] == ['systemctl','start']:
                        state['network_owner']=True
                    return ''
                def read():
                    self.assertFalse(state['payment'])
                    self.assertTrue(state['network_owner'])
                    state['read']=True
                    return journal
                stack.enter_context(mock.patch.object(launcher,'drain',side_effect=drain))
                stack.enter_context(mock.patch.object(launcher,'run',side_effect=run,create=True))
                stack.enter_context(mock.patch.object(launcher,'journal_readback',side_effect=read))
                stack.enter_context(mock.patch.object(launcher,'put',side_effect=lambda p,b:p.write_bytes(b),create=True))
                stack.enter_context(mock.patch.object(launcher,'health',create=True))
                restore = stack.enter_context(mock.patch.object(launcher,'restore_ingress'))
                stack.enter_context(mock.patch.object(launcher,'inspect',side_effect=lambda name:
                    {'Image':launcher.API_IMAGE if name=='noteai-api-c' else 'unchanged-admin'},create=True))
                result = launcher.close()
                self.assertEqual(result['state'],'SERVICES_RESTORED_COLLECTOR_REMOVAL_PENDING')
                self.assertEqual(result['journal'],journal)
                self.assertTrue(state['network_owner'])
                restore.assert_called_once_with(before)
                self.assertEqual({p:p.read_bytes() for p in paths},before)
                self.assertEqual(json.loads((root/'closed.json').read_text()),result)

class NativeBillCaptureTests(unittest.TestCase):
    def test_bill_reuses_trade_context_without_mutating_unknown_history(self):
        from deploy.production import native_capture as launcher
        trade={'activation':str(uuid.uuid4()),'provider':'wechatpay_direct','user_id':launcher.USER_ID,
            'app_id':launcher.APP_ID,'idempotency_key_hash':'original-key','create_context':{'activation_identity_sha256':'original-trade'},
            'work_directory':'old','reconciliation_run_id':None,'targets':{
            'payment_orders':['idempotency_key_hash','original-key'],
            'payment_reconciliation_runs':['id','no-reconcile'], 'payment_reconciliation_items':['id','no-reconcile']}}
        original=json.dumps(trade,sort_keys=True)
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'old.incomplete';p.write_bytes(b'original UNKNOWN journal')
            before=p.read_bytes();run_id=str(uuid.uuid4())
            bill=launcher.bill_binding(trade,Path(temp)/'bill',str(uuid.uuid4()),run_id)
            self.assertEqual(bill['create_context'],trade['create_context'])
            self.assertEqual(bill['targets']['payment_orders'],trade['targets']['payment_orders'])
            self.assertEqual(bill['targets']['payment_reconciliation_items'],['run_id',run_id])
            self.assertEqual(json.dumps(trade,sort_keys=True),original)
            self.assertEqual(p.read_bytes(),before)
            with self.assertRaises(AssertionError):
                launcher.bill_binding(trade,Path(temp),trade['activation'],run_id)

    def test_bill_window_and_flags_do_not_authorize_payment_or_early_bill(self):
        from deploy.production import native_capture as launcher
        from zoneinfo import ZoneInfo
        starts=int(datetime(2026,9,15,10,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp())
        meta={'bill_date':'2026-09-14','order_id':'original-order','activation':'original-bill','binding_sha256':'original-binding'}
        binding={'activation':'original-bill','reconciliation_run_id':str(uuid.uuid4())}
        with self.assertRaises(AssertionError): launcher.bill_environment(meta,binding,starts-1)
        env=launcher.bill_environment(meta,binding,starts)
        self.assertEqual(env['NOTEAI_ITEM31_WECHAT_ACK_FAILURE_ONCE'],'')
        self.assertEqual(env['NOTEAI_PAYMENT_CANARY_ACTION'],'reconcile')
        self.assertEqual(env['NOTEAI_PAYMENT_CANARY_ORDER_ID'],'original-order')
        self.assertEqual(int(env['NOTEAI_PAYMENT_CANARY_EXPIRES_EPOCH'])-starts,3600)
        for flag in ('NOTEAI_PAYMENT_ORDERING_ENABLED','NOTEAI_PAYMENT_CALLBACK_ENABLED','NOTEAI_PAYMENT_CALLBACK_RELAY_ENABLED'):
            self.assertEqual(env[flag],'0')
        with self.assertRaises(AssertionError): launcher.bill_environment(meta,{**binding,'reconciliation_run_id':None},starts)

    def test_bill_close_preserves_api_and_original_unknown_and_blocks_live_operator(self):
        from deploy.production import native_capture as launcher
        for active in (False,True):
            with self.subTest(active=active),tempfile.TemporaryDirectory() as temp,ExitStack() as stack:
                root=Path(temp);payment=root/'payment.service';payment.write_bytes(b'temporary')
                meta={'activation':'original-bill'};before={payment:b'original'}
                stack.enter_context(mock.patch.multiple(launcher,ROOT=root,PAYMENT_UNIT=payment))
                stack.enter_context(mock.patch.object(launcher,'originals',return_value=(meta,before)))
                intact=stack.enter_context(mock.patch.object(launcher,'bill_originals_intact'))
                commands=[]
                def run(args,*unused):
                    commands.append(args)
                    if args[:2]==['docker','ps']:return b'operator' if active else b''
                    if args[:2]==['systemctl','stop']:self.assertEqual(args[-1],'noteai-payment.service')
                    self.assertNotIn('noteai-api.service',args)
                    return b''
                stack.enter_context(mock.patch.object(launcher,'run',side_effect=run,create=True))
                stack.enter_context(mock.patch.object(launcher,'put',side_effect=lambda p,b:p.write_bytes(b),create=True))
                stack.enter_context(mock.patch.object(launcher,'journal_readback',return_value={'status':'UNKNOWN'}))
                if active:
                    result=launcher.close_bill();self.assertEqual(result['state'],'UNKNOWN')
                    self.assertEqual(result['reason'],'operator_still_running_read_original_result')
                    self.assertEqual(len(list(root.glob('close-unknown-*.json'))),1)
                    self.assertEqual(payment.read_bytes(),b'temporary');self.assertFalse((root/'closed.json').exists())
                    self.assertFalse(any(c[0]=='systemctl' for c in commands))
                else:
                    result=launcher.close_bill();self.assertEqual(result['journal'],{'status':'UNKNOWN'})
                    self.assertEqual(result['state'],'BILL_PAYMENT_RESTORED_COLLECTOR_REMOVAL_PENDING')
                    self.assertEqual(payment.read_bytes(),b'original');self.assertEqual(intact.call_count,2)
                    n=len(commands);self.assertEqual(launcher.close_bill(),result);self.assertEqual(len(commands),n)

    def test_bill_cleanup_after_api_drift_restores_payment_without_touching_api(self):
        from deploy.production import native_capture as launcher
        with tempfile.TemporaryDirectory() as temp,ExitStack() as stack:
            root=Path(temp);payment=root/'payment.service';payment.write_bytes(b'temporary')
            stack.enter_context(mock.patch.multiple(launcher,ROOT=root,PAYMENT_UNIT=payment))
            stack.enter_context(mock.patch.object(launcher,'originals',return_value=({'activation':'bill'},{payment:b'original'})))
            stack.enter_context(mock.patch.object(launcher,'bill_originals_intact',side_effect=AssertionError('api_drift')))
            commands=[]
            def run(args,*unused):
                commands.append(args);self.assertNotIn('noteai-api.service',args);return b''
            stack.enter_context(mock.patch.object(launcher,'run',side_effect=run,create=True))
            stack.enter_context(mock.patch.object(launcher,'put',side_effect=lambda p,b:p.write_bytes(b),create=True))
            stack.enter_context(mock.patch.object(launcher,'journal_readback',side_effect=RuntimeError('lost_network')))
            result=launcher.close_bill()
            self.assertEqual(result['state'],'UNKNOWN');self.assertTrue(result['payment_restored'])
            self.assertEqual(result['journal']['status'],'UNKNOWN');self.assertEqual(payment.read_bytes(),b'original')
            self.assertEqual(len(list(root.glob('close-unknown-*.json'))),1)
