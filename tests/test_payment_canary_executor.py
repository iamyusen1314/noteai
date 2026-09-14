import importlib
import inspect
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "model"
if str(MODEL) not in sys.path:
    sys.path.insert(0, str(MODEL))

canary = importlib.import_module("payment_canary_executor")
from scripts import validate_production_env_files as env_validator


ORDER_ID = "00000000-0000-4000-8000-000000000031"
REFUND_ID = "00000000-0000-4000-8000-000000000032"


def live_order():
    return {
        "id": ORDER_ID,
        "user_id": "synthetic-item31-user",
        "subject_hash": "2" * 64,
        "merchant_order_no": "0123456789abcdef0123456789abcdef",
        "provider_payment_id": None,
        "provider": "wechatpay_direct",
        "provider_mode": "live",
        "amount_fen": 1200,
        "payment_status": "pending",
        "entitlement_status": "pending",
        "refund_status": "none",
    }


def activation(action="query-payment"):
    return {
        "action": action,
        "provider": "wechatpay_direct",
        "order_id": ORDER_ID,
        "activation_id": "00000000-0000-4000-8000-000000000030",
        "user_id_sha256": canary._identity(
            "synthetic-item31-user",
            "payment-canary-user-v1",
        ),
        "subject_hash": "2" * 64,
        "amount_fen": 1200,
        "bill_date": "",
        "expires_at": 1788577200,
    }


class PaymentCanaryExecutorTests(unittest.TestCase):
    def test_action_ledger_is_durable_one_use_and_contains_no_raw_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            os.chmod(directory, 0o700)
            # macOS temporary parents may pass down a different group.
            os.chown(directory, os.geteuid(), os.getegid())
            item = activation()
            with patch.object(canary, "_ACTION_LEDGER_DIRECTORY", directory):
                admitted = canary._admit_action(item)
                try:
                    canary._seal_action(
                        admitted,
                        state="completed",
                        result={"ok": True, "provider_operation_count": 1},
                    )
                finally:
                    canary._close_action(admitted)
                paths = list(Path(directory).iterdir())
                self.assertEqual(len(paths), 1)
                self.assertEqual(paths[0].stat().st_mode & 0o777, 0o600)
                stored_text = paths[0].read_text(encoding="ascii")
                stored = json.loads(stored_text)
                self.assertEqual(stored["state"], "completed")
                self.assertRegex(stored["result_sha256"], r"^[0-9a-f]{64}$")
                self.assertEqual(
                    paths[0].stem,
                    stored["action_identity_sha256"],
                )
                self.assertNotIn(item["activation_id"], stored_text)
                self.assertNotIn(item["order_id"], stored_text)
                with self.assertRaisesRegex(
                    canary.PaymentCanaryError,
                    "PAYMENT_CANARY_ACTION_ALREADY_ADMITTED",
                ):
                    canary._admit_action(item)
                with self.assertRaisesRegex(
                    canary.PaymentCanaryError,
                    "PAYMENT_CANARY_ACTION_ALREADY_ADMITTED",
                ):
                    canary._admit_action(
                        {
                            **item,
                            "activation_id": (
                                "00000000-0000-4000-8000-000000000099"
                            ),
                        }
                    )

                distinct = canary._admit_action(
                    {**item, "action": "query-refund"}
                )
                canary._close_action(distinct)
                self.assertEqual(len(list(Path(directory).iterdir())), 2)

    def test_payment_canary_image_and_docs_require_persistent_named_volume(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        docs = (ROOT / "docs" / "DEPLOYMENT_SECRETS.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "install -d -o noteai -g noteai -m 0700", dockerfile
        )
        self.assertIn("/var/lib/noteai/payment-canary-actions", dockerfile)
        self.assertIn("same named Docker", docs)
        self.assertIn("A different\nactivation ID cannot replay", docs)

    def test_immutable_image_user_binding_requires_exact_root_owned_file(self):
        metadata = Mock(
            st_mode=canary.stat.S_IFREG | 0o444,
            st_uid=0,
            st_gid=0,
            st_nlink=1,
            st_size=65,
        )
        with patch.object(canary.os, "open", return_value=31), patch.object(
            canary.os,
            "fstat",
            return_value=metadata,
        ), patch.object(
            canary.os,
            "read",
            return_value=b"a" * 64 + b"\n",
        ), patch.object(canary.os, "close") as close:
            self.assertEqual(canary._bound_canary_user_id_sha256(), "a" * 64)
        close.assert_called_once_with(31)

        metadata.st_mode = canary.stat.S_IFREG | 0o644
        with patch.object(canary.os, "open", return_value=32), patch.object(
            canary.os,
            "fstat",
            return_value=metadata,
        ), patch.object(
            canary.os,
            "read",
            return_value=b"a" * 64 + b"\n",
        ), patch.object(canary.os, "close"):
            with self.assertRaisesRegex(
                canary.PaymentCanaryError,
                "PAYMENT_CANARY_USER_BINDING_INVALID",
            ):
                canary._bound_canary_user_id_sha256()

    def test_malformed_subjects_are_rejected_before_gateway_or_secret_loading(self):
        cases = (
            ["query-payment", "wechatpay_direct", "not-a-uuid"],
            ["query-refund", "wechatpay_direct", "not-a-uuid"],
            ["reconcile", "wechatpay_direct", "2026-9-7"],
            ["submit-refund", "wechatpay_direct", ORDER_ID, "free text"],
        )
        for argv in cases:
            with self.subTest(argv=argv), patch.object(canary, "_gateway") as gateway:
                with self.assertRaises(canary.PaymentCanaryError):
                    canary.execute(list(argv))
                gateway.assert_not_called()

    def test_gateway_requires_exact_live_role_database_and_identity(self):
        gateway = Mock()
        exact_env = {
            "NOTEAI_RUNTIME_ROLE": "payment-canary",
            "NOTEAI_DEPLOYMENT_STAGE": "production",
            "NOTEAI_PAYMENT_CANARY_ENABLED": "1",
        }
        with patch.dict(os.environ, exact_env, clear=True), patch.object(
            canary.db,
            "using_postgres",
            return_value=True,
        ), patch.object(
            canary.db,
            "fetchone",
            side_effect=(
                {
                    "current_role": "noteai_payment",
                    "session_role": "noteai_payment",
                    "transaction_read_only": "off",
                    "default_transaction_read_only": "off",
                    "transaction_isolation": "read committed",
                },
                {
                    "refund_column_present": True,
                    "refund_column_update": True,
                    "event_column_present": True,
                    "event_column_update": True,
                },
                {"required_privileges": True},
            ),
        ), patch.object(
            canary.payment_adapter_runtime,
            "configured_prod_mode",
            return_value=True,
        ), patch.object(
            canary.payment_adapter_runtime,
            "callback_identity_sha256",
            return_value="a" * 64,
        ), patch.object(
            canary.payment_adapter_runtime,
            "provider_from_environment",
            return_value=gateway,
        ) as provider_from_environment:
            configured, identity = canary._gateway("wechatpay_direct")
        self.assertIs(configured, gateway)
        self.assertEqual(identity, "a" * 64)
        provider_from_environment.assert_called_once_with(
            "wechatpay_direct",
            required_role="payment-canary",
        )

        for changed in (
            {**exact_env, "NOTEAI_RUNTIME_ROLE": "api"},
            {**exact_env, "NOTEAI_DEPLOYMENT_STAGE": "staging"},
            {**exact_env, "NOTEAI_PAYMENT_CANARY_ENABLED": "0"},
        ):
            with self.subTest(changed=changed), patch.dict(
                os.environ,
                changed,
                clear=True,
            ), patch.object(
                canary.payment_adapter_runtime,
                "provider_from_environment",
            ) as provider:
                with self.assertRaisesRegex(
                    canary.PaymentCanaryError,
                    "PAYMENT_CANARY_CONTEXT_INVALID",
                ):
                    canary._gateway("wechatpay_direct")
                provider.assert_not_called()

    def test_provider_secret_scope_rejects_cross_provider_callback_and_legacy_keys(self):
        accepted = {
            "wechatpay_direct": {
                "NOTEAI_WECHATPAY_MERCHANT_PRIVATE_KEY_B64": "synthetic",
                "NOTEAI_WECHATPAY_PLATFORM_PUBLIC_KEY_B64": "synthetic",
            },
            "alipay_direct": {
                "NOTEAI_ALIPAY_MERCHANT_PRIVATE_KEY_B64": "synthetic",
                "NOTEAI_ALIPAY_PUBLIC_KEY_B64": "synthetic",
            },
        }
        for provider_name, env in accepted.items():
            with self.subTest(provider=provider_name), patch.dict(
                os.environ,
                env,
                clear=True,
            ):
                self.assertTrue(canary._provider_secret_scope_ok(provider_name))

        forbidden = (
            ("wechatpay_direct", "NOTEAI_WECHATPAY_API_V3_KEY"),
            ("wechatpay_direct", "NOTEAI_ALIPAY_MERCHANT_PRIVATE_KEY_B64"),
            ("alipay_direct", "NOTEAI_WECHATPAY_MERCHANT_PRIVATE_KEY_B64"),
            ("alipay_direct", "NOTEAI_ADAPAY_API_KEY"),
            ("alipay_direct", "NOTEAI_ADAPAY_MERCHANT_PRIVATE_KEY"),
            ("alipay_direct", "NOTEAI_ADAPAY_PUBLIC_KEY"),
            ("wechatpay_direct", "ADMIN_PASSWORD"),
            ("alipay_direct", "UNRELATED_VENDOR_SECRET"),
            ("wechatpay_direct", "ANTHROPIC_API_KEY"),
        )
        for provider_name, key in forbidden:
            with self.subTest(provider=provider_name, key=key), patch.dict(
                os.environ,
                {key: "synthetic"},
                clear=True,
            ):
                self.assertFalse(canary._provider_secret_scope_ok(provider_name))

    def test_provider_secret_scope_covers_every_known_and_deprecated_secret(self):
        known = (
            env_validator._KNOWN_SECRET_KEYS
            | env_validator._DEPRECATED_SECRET_KEYS
        )
        for provider_name, allowed in (
            canary._PROVIDER_ALLOWED_SECRET_NAMES.items()
        ):
            for key in known:
                with self.subTest(provider=provider_name, key=key), patch.dict(
                    os.environ,
                    {key: "synthetic"},
                    clear=True,
                ):
                    self.assertEqual(
                        canary._provider_secret_scope_ok(provider_name),
                        key in allowed,
                    )

    def test_database_role_rejects_read_only_or_incomplete_privileges(self):
        privilege_query_source = inspect.getsource(canary._database_role_ok)
        self.assertNotRegex(
            privilege_query_source,
            r"'(?:SELECT|INSERT|UPDATE|DELETE)(?:,(?:SELECT|INSERT|UPDATE|DELETE))+?'",
        )
        exact = (
            {
                "current_role": "noteai_payment",
                "session_role": "noteai_payment",
                "transaction_read_only": "off",
                "default_transaction_read_only": "off",
                "transaction_isolation": "read committed",
            },
            {
                "refund_column_present": True,
                "refund_column_update": True,
                "event_column_present": True,
                "event_column_update": True,
            },
            {"required_privileges": True},
        )
        with patch.object(canary.db, "using_postgres", return_value=True), patch.object(
            canary.db,
            "fetchone",
            side_effect=exact,
        ):
            self.assertTrue(canary._database_role_ok())

        for index, mutation in (
            (0, {"default_transaction_read_only": "on"}),
            (0, {"transaction_isolation": "repeatable read"}),
            (1, {"refund_column_present": False}),
            (1, {"refund_column_update": False}),
            (1, {"event_column_present": False}),
            (1, {"event_column_update": False}),
            (2, {"required_privileges": False}),
        ):
            rows = [dict(row) for row in exact]
            rows[index].update(mutation)
            with self.subTest(index=index, mutation=mutation), patch.object(
                canary.db,
                "using_postgres",
                return_value=True,
            ), patch.object(canary.db, "fetchone", side_effect=rows):
                self.assertFalse(canary._database_role_ok())

    def test_activation_binds_exact_order_user_subject_amount_and_short_window(self):
        start = 1788573500
        exact = {
            "NOTEAI_PAYMENT_CANARY_ACTION": "query-payment",
            "NOTEAI_PAYMENT_CANARY_PROVIDER": "wechatpay_direct",
            "NOTEAI_PAYMENT_CANARY_ORDER_ID": ORDER_ID,
            "NOTEAI_PAYMENT_CANARY_ACTIVATION_ID": (
                "00000000-0000-4000-8000-000000000030"
            ),
            "NOTEAI_PAYMENT_CANARY_USER_ID_SHA256": activation()[
                "user_id_sha256"
            ],
            "NOTEAI_PAYMENT_CANARY_SUBJECT_HASH": "2" * 64,
            "NOTEAI_PAYMENT_CANARY_AMOUNT_FEN": "1200",
            "NOTEAI_PAYMENT_CANARY_NOT_BEFORE_EPOCH": str(start),
            "NOTEAI_PAYMENT_CANARY_EXPIRES_EPOCH": str(start + 3600),
            "NOTEAI_PAYMENT_CANARY_OWNER_TEST_ASSERTION": (
                "ITEM31-OWNER-CONTROLLED-TEST-ORDER"
            ),
        }
        with patch.dict(os.environ, exact, clear=True), patch.object(
            canary.time,
            "time",
            return_value=start + 1,
        ):
            result = canary._activation(
                "query-payment",
                "wechatpay_direct",
                ORDER_ID,
            )
        self.assertEqual(result["order_id"], ORDER_ID)
        self.assertEqual(result["amount_fen"], 1200)

        mutations = (
            {"NOTEAI_PAYMENT_CANARY_ORDER_ID": REFUND_ID},
            {"NOTEAI_PAYMENT_CANARY_AMOUNT_FEN": "39900"},
            {
                "NOTEAI_PAYMENT_CANARY_EXPIRES_EPOCH": str(
                    start + canary._MAX_ACTIVATION_WINDOW_SECONDS + 1
                )
            },
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), patch.dict(
                os.environ,
                {**exact, **mutation},
                clear=True,
            ), patch.object(canary.time, "time", return_value=start + 1):
                with self.assertRaises(canary.PaymentCanaryError):
                    canary._activation(
                        "query-payment",
                        "wechatpay_direct",
                        ORDER_ID,
                    )

    def test_order_rejects_arbitrary_live_user_or_amount(self):
        expected = activation()
        accepted = live_order()
        with patch.object(
            canary,
            "_bound_canary_user_id_sha256",
            return_value=expected["user_id_sha256"],
        ), patch.object(canary.db, "fetchone", return_value=accepted):
            result = canary._order(ORDER_ID, "wechatpay_direct", expected)
        self.assertEqual(result["id"], ORDER_ID)

        for mutation in (
            {"user_id": "real-customer"},
            {"subject_hash": "3" * 64},
            {"amount_fen": 39900},
            {"provider": "alipay_direct"},
        ):
            with self.subTest(mutation=mutation), patch.object(
                canary,
                "_bound_canary_user_id_sha256",
                return_value=expected["user_id_sha256"],
            ), patch.object(
                canary.db,
                "fetchone",
                return_value={**accepted, **mutation},
            ):
                with self.assertRaisesRegex(
                    canary.PaymentCanaryError,
                    "PAYMENT_CANARY_ORDER_MISMATCH",
                ):
                    canary._order(ORDER_ID, "wechatpay_direct", expected)

        real = {**accepted, "user_id": "real-customer"}
        self_consistent = {
            **expected,
            "user_id_sha256": canary._identity(
                "real-customer",
                "payment-canary-user-v1",
            ),
        }
        with patch.object(
            canary,
            "_bound_canary_user_id_sha256",
            return_value=expected["user_id_sha256"],
        ), patch.object(canary.db, "fetchone", return_value=real):
            with self.assertRaisesRegex(
                canary.PaymentCanaryError,
                "PAYMENT_CANARY_ORDER_MISMATCH",
            ):
                canary._order(
                    ORDER_ID,
                    "wechatpay_direct",
                    self_consistent,
                )

    def test_query_payment_performs_one_operation_with_canonical_amount_binding(self):
        gateway = Mock()
        admitted = canary._ActionAdmission(
            descriptor=31,
            directory_descriptor=32,
            record={},
            identity_sha256="c" * 64,
        )
        before = live_order()
        after = {
            **before,
            "payment_status": "succeeded",
            "entitlement_status": "applied",
        }
        with patch.object(
            canary,
            "_activation",
            return_value=activation(),
        ), patch.object(
            canary,
            "_assert_runtime_context",
        ), patch.object(
            canary,
            "_gateway",
            return_value=(gateway, "b" * 64),
        ), patch.object(
            canary,
            "_order",
            side_effect=(before, after),
        ), patch.object(
            canary,
            "_admit_action",
            return_value=admitted,
        ) as admit, patch.object(
            canary,
            "_seal_action",
        ) as seal, patch.object(
            canary,
            "_close_action",
        ) as close:
            result = canary.execute(
                ["query-payment", "wechatpay_direct", ORDER_ID]
            )

        gateway.process_payment_query.assert_called_once()
        lookup = gateway.process_payment_query.call_args.args[0]
        self.assertEqual(lookup.merchant_order_no, before["merchant_order_no"])
        self.assertEqual(lookup.expected_amount_fen, 1200)
        self.assertEqual(result["provider_operation_count"], 1)
        self.assertEqual(result["automatic_retry_count"], 0)
        self.assertEqual(result["payment_status"], "succeeded")
        self.assertEqual(result["action_admission_sha256"], "c" * 64)
        self.assertNotIn(ORDER_ID, str(result))
        self.assertNotIn(before["merchant_order_no"], str(result))
        admit.assert_called_once_with(activation())
        seal.assert_called_once_with(
            admitted,
            state="completed",
            result={
                key: value
                for key, value in result.items()
                if key != "action_admission_sha256"
            },
        )
        close.assert_called_once_with(admitted)

    def test_provider_exception_seals_action_before_propagation(self):
        gateway = Mock()
        gateway.process_payment_query.side_effect = RuntimeError("provider timeout")
        admitted = canary._ActionAdmission(
            descriptor=31,
            directory_descriptor=32,
            record={},
            identity_sha256="c" * 64,
        )
        with patch.object(
            canary,
            "_activation",
            return_value=activation(),
        ), patch.object(canary, "_assert_runtime_context"), patch.object(
            canary,
            "_gateway",
            return_value=(gateway, "b" * 64),
        ), patch.object(
            canary,
            "_order",
            return_value=live_order(),
        ), patch.object(
            canary,
            "_admit_action",
            return_value=admitted,
        ), patch.object(
            canary,
            "_seal_action",
        ) as seal, patch.object(
            canary,
            "_close_action",
        ) as close, self.assertRaisesRegex(RuntimeError, "provider timeout"):
            canary.execute(["query-payment", "wechatpay_direct", ORDER_ID])
        seal.assert_called_once_with(
            admitted,
            state="sealed_unknown",
            result={"code": "PAYMENT_CANARY_INTERNAL_ERROR"},
        )
        close.assert_called_once_with(admitted)

    def test_refund_provider_exception_is_sealed_without_retry_or_response_write(self):
        gateway = Mock()
        gateway.create_refund.side_effect = RuntimeError("provider timeout")
        order = live_order()
        refund = {
            "id": REFUND_ID,
            "order_id": ORDER_ID,
            "merchant_refund_no": "NR_00000000000040008000000000000032",
            "amount_fen": 1200,
            "status": "requested",
        }
        with patch.object(canary, "_order", return_value=order), patch.object(
            canary.payment_contract,
            "prepare_full_refund",
            return_value={"id": REFUND_ID},
        ) as prepare, patch.object(
            canary.db,
            "fetchone",
            return_value=refund,
        ), patch.object(
            canary.payment_contract,
            "admit_refund_submission",
            return_value=True,
        ) as admit, patch.object(
            canary.payment_contract,
            "provider_refund_request",
            return_value={"bounded": True},
        ), patch.object(
            canary.payment_contract,
            "mark_refund_submission",
        ) as mark:
            with self.assertRaisesRegex(
                canary.PaymentCanaryError,
                "PAYMENT_PROVIDER_OUTCOME_UNKNOWN",
            ):
                canary._submit_refund(
                    gateway,
                    "wechatpay_direct",
                    order,
                    activation("submit-refund"),
                    "customer_request",
                )

        prepare.assert_called_once_with(ORDER_ID, reason_code="customer_request")
        admit.assert_called_once_with(REFUND_ID)
        gateway.create_refund.assert_called_once_with({"bounded": True})
        mark.assert_not_called()

    def test_refund_success_returns_only_bound_request_and_verified_result_digests(self):
        gateway = Mock()
        order = live_order()
        order["provider_payment_id"] = "provider-payment-secret"
        refund = {
            "id": REFUND_ID,
            "order_id": ORDER_ID,
            "merchant_refund_no": "merchant-refund-secret",
            "amount_fen": 1200,
            "status": "requested",
        }
        provider_request = {
            "merchant_refund_no": "merchant-refund-secret",
            "merchant_order_no": order["merchant_order_no"],
            "provider_payment_id": "provider-payment-secret",
            "amount_fen": 1200,
        }
        provider_result = canary.payment_contract.ProviderRefundResult(
            merchant_refund_no="merchant-refund-secret",
            provider_refund_id="provider-refund-secret",
            status="pending",
            amount_fen=1200,
            response_verified=True,
            merchant_order_no=order["merchant_order_no"],
            provider_payment_id="provider-payment-secret",
            provider_name="wechatpay_direct",
            app_id="wxSyntheticApp01",
            prod_mode=True,
            currency="CNY",
            provider_submitted_at=1788573600,
        )
        gateway.create_refund.return_value = provider_result
        with patch.object(
            canary.payment_contract,
            "prepare_full_refund",
            return_value={"id": REFUND_ID},
        ), patch.object(
            canary.db,
            "fetchone",
            return_value=refund,
        ), patch.object(
            canary.payment_contract,
            "admit_refund_submission",
            return_value=True,
        ), patch.object(
            canary.payment_contract,
            "provider_refund_request",
            return_value=provider_request,
        ), patch.object(
            canary.payment_contract,
            "mark_refund_submission",
        ) as mark, patch.object(
            canary,
            "_refund_for_order",
            return_value=({"status": "submitted"}, order),
        ):
            result = canary._submit_refund(
                gateway,
                "wechatpay_direct",
                order,
                activation("submit-refund"),
                "customer_request",
            )

        gateway.create_refund.assert_called_once_with(provider_request)
        mark.assert_called_once_with(REFUND_ID, provider_result)
        self.assertEqual(
            result["request_sha256"],
            canary._digest(
                "noteai-item31-refund-provider-request-v1",
                provider_request,
            ),
        )
        expected_result, expected_refund_identity = canary._refund_result_digest(
            provider_result,
            "wechatpay_direct",
        )
        self.assertEqual(result["response_sha256"], expected_result)
        self.assertEqual(
            result["provider_refund_identity_sha256"],
            expected_refund_identity,
        )
        self.assertEqual(result["provider_operation_count"], 1)
        self.assertEqual(result["automatic_retry_count"], 0)
        for raw_value in (
            "merchant-refund-secret",
            "provider-payment-secret",
            "provider-refund-secret",
            order["merchant_order_no"],
            "wxSyntheticApp01",
        ):
            self.assertNotIn(raw_value, str(result))

    def test_alipay_refund_identity_uses_provider_bound_out_request_number(self):
        result = canary.payment_contract.ProviderRefundResult(
            merchant_refund_no="NR_00000000000040008000000000000032",
            provider_refund_id=None,
            status="pending",
            amount_fen=1200,
            response_verified=True,
            merchant_order_no="NO_00000000000040008000000000000032",
            provider_payment_id="2026090600000000000000000001",
            provider_name="alipay_direct",
            app_id="2026000000000001",
            prod_mode=True,
            currency="CNY",
        )

        _response_sha256, identity_sha256 = canary._refund_result_digest(
            result,
            "alipay_direct",
        )

        self.assertEqual(
            identity_sha256,
            canary._identity(
                result.merchant_refund_no,
                "noteai-item31-alipay-refund-out-request-no-v1",
            ),
        )
        self.assertNotEqual(
            identity_sha256,
            canary._identity(
                result.merchant_refund_no,
                "payment-provider-refund-v1",
            ),
        )
        self.assertNotIn(result.merchant_refund_no, str(identity_sha256))

    def test_reconciliation_output_contains_digests_and_counts_only(self):
        gateway = Mock()
        gateway.reconciliation_rows.return_value = (
            b"authenticated-provider-bill",
            ({"kind": "payment"},),
        )
        reconciled = {
            "status": "matched",
            "row_count": 1,
            "discrepancy_count": 0,
            "source_sha256": "c" * 64,
        }
        with patch.object(
            canary.payment_contract,
            "reconcile_bill",
            return_value=reconciled,
        ) as reconcile:
            result = canary._reconcile(
                gateway,
                "wechatpay_direct",
                "2026-09-07",
            )

        gateway.reconciliation_rows.assert_called_once_with("2026-09-07")
        reconcile.assert_called_once_with(
            "2026-09-07",
            b"authenticated-provider-bill",
            ({"kind": "payment"},),
            prod_mode=True,
            provider_name="wechatpay_direct",
        )
        self.assertEqual(result["provider_operation_count"], 1)
        self.assertEqual(result["source_sha256"], "c" * 64)
        self.assertNotIn("authenticated-provider-bill", str(result))


if __name__ == "__main__":
    unittest.main()
