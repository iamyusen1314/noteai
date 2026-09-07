import base64
import importlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

db = importlib.import_module("db")
billing = importlib.import_module("billing")
content_retention = importlib.import_module("content_retention")
payment = importlib.import_module("payment_contract")


PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDTIbNiLODKiT5g/QoQ5QPIssoq
w+3cikZc2I+k9bF/UczKXW5iMy0Eq7GjGTsHeCw2/4koo/Fj9RNoFP/qUCaMYB6Q
yGBkx/5C/qBAIVGIdC2z03ALL7H17YGy5b4sEqPVrvoXD5/iNb6B3MonVlGSQxgN
PRAR6t45o5fLtsGu1wIDAQAB
-----END PUBLIC KEY-----"""
SIGNED_DATA = (
    '{"id":"evt_pay_001","type":"payment.succeeded",'
    '"created_time":1785052800,"prod_mode":false,'
    '"app_id":"app_test_001","data":{"id":"pay_001",'
    '"order_no":"ORDER_PLACEHOLDER","pay_amt":"12.00"}}'
)
SIGNATURE = (
    "fL89vRhhfFmbOSxvPAFsUBsnzNvUcYk9cQzAp7gdLrM8sijWq11aUe/nM1MO"
    "xwkMv/6hnH4O8A3CDzG4uYYZGZpZJwcpnWlZW59qlcx4Apo3YNUDu2f2mQLq"
    "3+o6Rz3jPKNurZVYA2addoV5Dn7HIcutLPpY75QBkpXb+eJfwGg="
)


class PaymentContractTests(unittest.TestCase):
    def setUp(self):
        self.old_db_path = db._DB_PATH
        self.old_database_url = os.environ.pop("DATABASE_URL", None)
        self.temp = tempfile.TemporaryDirectory()
        db._DB_PATH = Path(self.temp.name) / "noteai.db"
        db.init_db()
        billing.clear_active_usage()
        self.now = datetime(2026, 7, 26, 8, 0, 0, tzinfo=timezone.utc)
        self.app_id = "app_test_001"

    def tearDown(self):
        billing.clear_active_usage()
        db._DB_PATH = self.old_db_path
        if self.old_database_url is not None:
            os.environ["DATABASE_URL"] = self.old_database_url
        else:
            os.environ.pop("DATABASE_URL", None)
        self.temp.cleanup()

    def create_user(self, user_id: str = "u-payment") -> None:
        db.execute(
            "INSERT INTO users("
            "id,username,email,password_hash,password_salt,created_at"
            ") VALUES(?,?,?,?,?,?)",
            (
                user_id,
                f"{user_id}_name",
                f"{user_id}@example.com",
                "hash",
                "salt",
                self.now.isoformat(),
            ),
        )
        billing.get_subscription(user_id)

    def create_order(
        self,
        *,
        user_id: str = "u-payment",
        product_kind: str = "credit_package",
        product_id: str = "starter",
        key: str = "payment-request-001",
    ) -> tuple[dict, dict]:
        order = payment.create_order(
            user_id,
            product_kind,
            product_id,
            idempotency_key=key,
            app_id=self.app_id,
            prod_mode=False,
            now=self.now,
        )
        row = dict(
            db.fetchone(
                "SELECT * FROM payment_orders WHERE id=?",
                (order["id"],),
            )
        )
        return order, row

    def event(
        self,
        row: dict,
        *,
        event_id: str = "evt_payment_001",
        event_type: str = "payment.succeeded",
        amount: str | None = None,
        provider_payment_id: str = "pay_001",
    ) -> str:
        return json.dumps(
            {
                "id": event_id,
                "type": event_type,
                "created_time": int(self.now.timestamp()),
                "prod_mode": False,
                "app_id": self.app_id,
                "data": {
                    "id": provider_payment_id,
                    "order_no": row["merchant_order_no"],
                    "pay_amt": amount
                    or f"{int(row['amount_fen']) / 100:.2f}",
                },
            },
            separators=(",", ":"),
        )

    def refund_event(
        self,
        order: dict,
        refund: dict,
        *,
        event_id: str = "evt_refund_001",
        event_type: str = "refund.succeeded",
        amount: str | None = None,
    ) -> str:
        return json.dumps(
            {
                "id": event_id,
                "type": event_type,
                "created_time": int(self.now.timestamp()),
                "prod_mode": False,
                "app_id": self.app_id,
                "data": {
                    "id": refund["provider_refund_id"] or "refund_provider_001",
                    "refund_order_no": refund["merchant_refund_no"],
                    "payment_id": order["provider_payment_id"],
                    "refund_amt": amount
                    or f"{int(refund['amount_fen']) / 100:.2f}",
                },
            },
            separators=(",", ":"),
        )

    def process(self, data: str) -> dict:
        with mock.patch.object(
            payment,
            "verify_adapay_signature",
            return_value=True,
        ):
            return payment.process_signed_callback(
                data,
                "fixture-signature",
                PUBLIC_KEY,
                expected_app_id=self.app_id,
                expected_prod_mode=False,
                now=self.now,
            )

    def succeed_order(self, row: dict, *, event_id: str = "evt_payment_001"):
        result = self.process(self.event(row, event_id=event_id))
        return result, dict(
            db.fetchone(
                "SELECT * FROM payment_orders WHERE id=?",
                (row["id"],),
            )
        )

    def test_schema_and_migration_are_integer_content_free_and_grant_free(self):
        expected = {
            "payment_orders",
            "payment_events",
            "payment_refunds",
            "payment_cash_ledger",
            "payment_entitlement_ledger",
            "payment_credit_positions",
            "payment_credit_consumptions",
            "payment_reconciliation_runs",
            "payment_reconciliation_items",
            "payment_settlement_summaries",
        }
        rows = db.fetchall(
            "SELECT name,sql FROM sqlite_master WHERE type='table' "
            "AND name LIKE 'payment_%'"
        )
        self.assertEqual({row["name"] for row in rows}, expected)
        definitions = "\n".join(str(row["sql"]) for row in rows).lower()
        self.assertNotIn("real not null", definitions)
        self.assertNotIn("callback_body", definitions)
        self.assertNotIn("payer", definitions)
        self.assertNotIn("card_", definitions)
        migration = (
            MODEL_DIR
            / "migrations"
            / "postgres"
            / "0014_payment_execution_contract.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("BIGINT NOT NULL", migration)
        self.assertIn("noteai_payment", migration)
        self.assertNotIn("GRANT ", migration.upper())
        self.assertNotIn("REVOKE ", migration.upper())
        direct_migration = (
            MODEL_DIR
            / "migrations"
            / "postgres"
            / "0018_direct_payment_providers.sql"
        ).read_text(encoding="utf-8")
        for provider_name in (
            "adapay",
            "wechatpay_direct",
            "alipay_direct",
        ):
            self.assertIn(provider_name, direct_migration)
        self.assertIn(
            "GRANT UPDATE(provider_submitted_at)",
            direct_migration,
        )
        self.assertIn(
            "GRANT UPDATE(duplicate_delivery_count)",
            direct_migration,
        )
        direct_executable = "\n".join(
            line for line in direct_migration.splitlines()
            if not line.lstrip().startswith("--")
        )
        self.assertNotRegex(
            direct_executable,
            r"(?i)\b(?:LOGIN|PASSWORD|ALTER ROLE)\b",
        )
        self.assertNotIn("REVOKE ", direct_migration.upper())
        incremental_acl = (
            ROOT
            / "scripts"
            / "postgres"
            / "noteai_production_runtime_roles_0018.sql"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "GRANT UPDATE(provider_submitted_at)\n"
            "    ON payment_refunds TO noteai_payment;",
            incremental_acl,
        )
        self.assertIn(
            "GRANT UPDATE(duplicate_delivery_count)\n"
            "    ON payment_events TO noteai_payment;",
            incremental_acl,
        )
        incremental_executable = "\n".join(
            line for line in incremental_acl.splitlines()
            if not line.lstrip().startswith("--")
        )
        self.assertNotRegex(
            incremental_executable,
            r"(?i)\b(?:LOGIN|PASSWORD|ALTER ROLE)\b",
        )

    def test_catalog_matches_visible_prices_and_has_no_auto_renewal(self):
        payment.assert_catalog_matches_billing()
        self.assertEqual(len(payment.CATALOG), 8)
        contract = (
            ROOT / "docs" / "PAYMENT_PRODUCTION_CONTRACT.md"
        ).read_text(encoding="utf-8")
        self.assertIn("no auto-renewal", contract)
        self.assertIn("integer CNY fen", contract)
        self.assertIn("Studio remains one NoteAI account", contract)

    def test_legacy_sqlite_refund_schema_upgrades_once_to_epoch_submission(self):
        db.execute(
            "DROP TRIGGER IF EXISTS "
            "payment_refunds_provider_submission_immutable_v1"
        )
        db.execute("DROP TRIGGER IF EXISTS payment_refunds_insert_guard_v1")
        db.execute(
            "ALTER TABLE payment_refunds DROP COLUMN provider_submitted_at"
        )

        db.init_db()
        db.init_db()

        columns = {
            row["name"]: row["type"]
            for row in db.fetchall("PRAGMA table_info(payment_refunds)")
        }
        self.assertEqual(columns["provider_submitted_at"], "INTEGER")
        triggers = {
            row["name"]: row["sql"]
            for row in db.fetchall(
                "SELECT name,sql FROM sqlite_master "
                "WHERE type='trigger' AND name LIKE 'payment_refunds_%'"
            )
        }
        self.assertIn(
            "payment_refunds_provider_submission_immutable_v1",
            triggers,
        )
        self.assertIn(
            "NEW.provider_submitted_at IS NOT NULL",
            triggers["payment_refunds_insert_guard_v1"],
        )

    def test_order_is_owner_bound_and_idempotent(self):
        self.create_user()
        first, _row = self.create_order()
        second, _row = self.create_order()
        self.assertEqual(first["id"], second["id"])
        with self.assertRaises(payment.PaymentContractError) as conflict:
            self.create_order(product_id="creator")
        self.assertEqual(conflict.exception.code, "PAYMENT_IDEMPOTENCY_CONFLICT")
        self.assertIsNone(
            payment.get_order_for_user(first["id"], "other-user")
        )
        self.assertEqual(
            payment.get_order_for_user(first["id"], "u-payment")["id"],
            first["id"],
        )
        stored = db.fetchone(
            "SELECT idempotency_key_hash,request_hash,subject_hash "
            "FROM payment_orders WHERE id=?",
            (first["id"],),
        )
        self.assertNotIn(
            "payment-request",
            "|".join(str(value) for value in tuple(stored)),
        )
        full = db.fetchone(
            "SELECT * FROM payment_orders WHERE id=?",
            (first["id"],),
        )
        provider_request = payment.provider_payment_request(
            full,
            device_ip="8.8.8.8",
        )
        self.assertEqual(
            set(provider_request),
            {
                "merchant_order_no",
                "amount_fen",
                "currency",
                "product_kind",
                "product_id",
                "provider_mode",
                "provider_name",
                "device_ip",
            },
        )
        self.assertEqual(provider_request["device_ip"], "8.8.8.8")
        serialized = json.dumps(provider_request)
        for forbidden in (
            "u-payment",
            "subject_hash",
            "idempotency",
            "request_hash",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_active_paid_subscription_blocks_second_paid_order(self):
        self.create_user()
        db.execute(
            "UPDATE subscriptions SET tier='pro' WHERE user_id='u-payment'"
        )
        with self.assertRaises(payment.PaymentContractError) as blocked:
            self.create_order(
                product_kind="subscription",
                product_id="growth",
            )
        self.assertEqual(
            blocked.exception.code,
            "PAYMENT_ACTIVE_SUBSCRIPTION_REQUIRES_MANUAL",
        )

    def test_expired_paid_subscription_does_not_block_new_intent(self):
        self.create_user()
        db.execute(
            "UPDATE subscriptions SET tier='pro',expires_at=? "
            "WHERE user_id='u-payment'",
            ((self.now - timedelta(seconds=1)).isoformat(),),
        )
        order, _row = self.create_order(
            product_kind="subscription",
            product_id="growth",
        )
        self.assertEqual(order["payment_status"], "created")
        self.assertEqual(
            db.fetchone(
                "SELECT is_active FROM subscriptions "
                "WHERE user_id='u-payment' AND tier='pro'"
            )["is_active"],
            0,
        )

    def test_real_sha1withrsa_fixture_and_tamper_rejection(self):
        self.assertTrue(
            payment.verify_adapay_signature(
                SIGNED_DATA,
                SIGNATURE,
                PUBLIC_KEY,
            )
        )
        self.assertFalse(
            payment.verify_adapay_signature(
                SIGNED_DATA.replace("12.00", "13.00"),
                SIGNATURE,
                PUBLIC_KEY,
            )
        )
        self.assertFalse(
            payment.verify_adapay_signature(
                SIGNED_DATA,
                SIGNATURE,
                "not-a-public-key",
            )
        )
        encoded_key = "".join(PUBLIC_KEY.splitlines()[1:-1])
        der = base64.b64decode(encoded_key)
        rsa_algorithm = bytes.fromhex("06092a864886f70d0101010500")
        self.assertIn(rsa_algorithm, der)
        invalid_der = der.replace(
            rsa_algorithm,
            bytes.fromhex("06092a864886f70d0101020500"),
            1,
        )
        invalid_body = base64.b64encode(invalid_der).decode("ascii")
        invalid_key = (
            "-----BEGIN PUBLIC KEY-----\n"
            + "\n".join(
                invalid_body[index : index + 64]
                for index in range(0, len(invalid_body), 64)
            )
            + "\n-----END PUBLIC KEY-----"
        )
        self.assertFalse(
            payment.verify_adapay_signature(
                SIGNED_DATA,
                SIGNATURE,
                invalid_key,
            )
        )
        modulus, _exponent = payment._rsa_public_numbers(PUBLIC_KEY)
        out_of_range_signature = base64.b64encode(
            modulus.to_bytes((modulus.bit_length() + 7) // 8, "big")
        ).decode("ascii")
        self.assertFalse(
            payment.verify_adapay_signature(
                SIGNED_DATA,
                out_of_range_signature,
                PUBLIC_KEY,
            )
        )

    def test_invalid_signature_writes_nothing(self):
        with self.assertRaises(payment.PaymentContractError) as invalid:
            payment.process_signed_callback(
                SIGNED_DATA + " ",
                SIGNATURE,
                PUBLIC_KEY,
                expected_app_id=self.app_id,
                expected_prod_mode=False,
                now=self.now,
            )
        self.assertEqual(
            invalid.exception.code,
            "PAYMENT_CALLBACK_SIGNATURE_INVALID",
        )
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM payment_events")["c"],
            0,
        )

    def test_duplicate_json_keys_fail_before_processing(self):
        body = (
            '{"id":"evt_1","id":"evt_2","type":"payment.succeeded",'
            '"created_time":1785052800,"prod_mode":false,'
            '"app_id":"app_test_001","data":{}}'
        )
        with self.assertRaises(payment.PaymentContractError) as duplicate:
            payment.parse_callback_event(body)
        self.assertEqual(
            duplicate.exception.code,
            "PAYMENT_DUPLICATE_JSON_KEY",
        )
        float_mode = body.replace(
            '"prod_mode":false',
            '"prod_mode":0.0',
        ).replace('"id":"evt_1","id":"evt_2",', '"id":"evt_1",')
        with self.assertRaises(payment.PaymentContractError) as invalid_mode:
            payment.parse_callback_event(float_mode)
        self.assertEqual(
            invalid_mode.exception.code,
            "PAYMENT_INVALID_PROVIDER_MODE",
        )

    def test_credit_payment_is_exactly_once_across_replay_and_new_event(self):
        self.create_user()
        _order, row = self.create_order()
        first, updated = self.succeed_order(row)
        self.assertTrue(first["ok"])
        self.assertEqual(updated["payment_status"], "succeeded")
        self.assertEqual(updated["entitlement_status"], "applied")
        self.assertEqual(
            db.fetchone(
                "SELECT balance FROM credits WHERE user_id='u-payment'"
            )["balance"],
            30,
        )
        replay = self.process(self.event(row))
        self.assertTrue(replay["duplicate"])
        second_replay = self.process(self.event(row))
        self.assertTrue(second_replay["duplicate"])
        self.assertEqual(
            db.fetchone(
                "SELECT id,duplicate_delivery_count FROM payment_events "
                "WHERE reason_code='payment_applied'"
            )["duplicate_delivery_count"],
            2,
        )
        payment_event = db.fetchone(
            "SELECT id FROM payment_events WHERE reason_code='payment_applied'"
        )
        cash = db.fetchone(
            "SELECT source_event_id FROM payment_cash_ledger "
            "WHERE entry_type='payment_received'"
        )
        entitlement = db.fetchone(
            "SELECT source_event_id FROM payment_entitlement_ledger "
            "WHERE entry_type='credit_grant'"
        )
        self.assertEqual(payment_event["id"], cash["source_event_id"])
        self.assertEqual(payment_event["id"], entitlement["source_event_id"])
        second_terminal = self.process(
            self.event(row, event_id="evt_payment_second_terminal")
        )
        self.assertTrue(second_terminal["already_terminal"])
        for table in ("payment_cash_ledger", "payment_entitlement_ledger"):
            self.assertEqual(
                db.fetchone(f"SELECT COUNT(*) AS c FROM {table}")["c"],
                1,
            )

    def test_reused_provider_event_id_with_changed_payload_is_rejected(self):
        self.create_user()
        _order, row = self.create_order()
        self.succeed_order(row)
        with self.assertRaises(payment.PaymentContractError) as collision:
            self.process(
                self.event(
                    row,
                    event_id="evt_payment_001",
                    amount="13.00",
                )
            )
        self.assertEqual(
            collision.exception.code,
            "PAYMENT_EVENT_ID_COLLISION",
        )
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM payment_events")["c"],
            1,
        )
        self.assertEqual(
            db.fetchone(
                "SELECT duplicate_delivery_count FROM payment_events"
            )["duplicate_delivery_count"],
            0,
        )
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM payment_cash_ledger")["c"],
            1,
        )

    def test_live_cash_is_counted_while_test_cash_is_excluded(self):
        self.create_user()
        order = payment.create_order(
            "u-payment", "credit_package", "starter",
            idempotency_key="live-accounting-fixture", app_id=self.app_id,
            prod_mode=True, now=self.now,
        )
        row = dict(db.fetchone("SELECT * FROM payment_orders WHERE id=?", (order["id"],)))
        event = json.loads(self.event(row, amount="13.00"))
        event["prod_mode"] = True
        with mock.patch.object(payment, "verify_adapay_signature", return_value=True):
            result = payment.process_signed_callback(
                json.dumps(event), "fixture-signature", PUBLIC_KEY,
                expected_app_id=self.app_id, expected_prod_mode=True, now=self.now,
            )
        self.assertFalse(result["ok"])
        self.assertEqual(payment.finance_summary(since="2000-01-01"),
                         {"received_fen": 0, "refunded_fen": 0, "net_fen": 0, "unmatched_fen": 1300})

    def test_amount_mismatch_records_cash_truth_but_no_entitlement(self):
        self.create_user()
        _order, row = self.create_order()
        result = self.process(self.event(row, amount="13.00"))
        self.assertFalse(result["ok"])
        stored = db.fetchone(
            "SELECT payment_status,entitlement_status "
            "FROM payment_orders WHERE id=?",
            (row["id"],),
        )
        self.assertEqual(stored["payment_status"], "needs_manual")
        self.assertEqual(stored["entitlement_status"], "pending")
        cash = db.fetchone(
            "SELECT entry_type,amount_fen FROM payment_cash_ledger"
        )
        self.assertEqual(cash["entry_type"], "payment_received_unmatched")
        self.assertEqual(cash["amount_fen"], 1300)
        finance = payment.finance_summary(since="2000-01-01T00:00:00+00:00")
        self.assertEqual(finance["net_fen"], 0)
        self.assertEqual(finance["unmatched_fen"], 0)  # TEST has no real cash.
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM payment_entitlement_ledger"
            )["c"],
            0,
        )
        self.assertIsNone(
            db.fetchone("SELECT balance FROM credits WHERE user_id='u-payment'")
        )

    def test_payment_submission_mismatch_commits_manual_state_before_error(self):
        self.create_user()
        _order, row = self.create_order()
        self.assertTrue(payment.admit_payment_submission(row["id"], now=self.now))
        self.assertFalse(payment.admit_payment_submission(row["id"], now=self.now))
        with self.assertRaises(payment.PaymentContractError) as mismatch:
            payment.mark_payment_submission(
                row["id"],
                payment.ProviderPaymentResult(
                    merchant_order_no=row["merchant_order_no"],
                    provider_payment_id="provider_mismatch_001",
                    status="pending",
                    amount_fen=int(row["amount_fen"]) + 1,
                    app_id=self.app_id,
                    prod_mode=False,
                    checkout_token="synthetic-checkout",
                    response_verified=True,
                ),
                now=self.now,
            )
        self.assertEqual(
            mismatch.exception.code,
            "PAYMENT_PROVIDER_RESPONSE_MISMATCH",
        )
        stored = db.fetchone(
            "SELECT payment_status,provider_payment_id FROM payment_orders "
            "WHERE id=?",
            (row["id"],),
        )
        self.assertEqual(stored["payment_status"], "needs_manual")
        self.assertIsNone(stored["provider_payment_id"])

    def test_unknown_payment_outcome_stays_sealed_and_accepts_late_success(self):
        self.create_user()
        _order, row = self.create_order()
        self.assertTrue(payment.admit_payment_submission(row["id"], now=self.now))
        unknown = payment.mark_payment_submission_unknown(
            row["id"],
            now=self.now + timedelta(seconds=1),
        )
        self.assertEqual(unknown["payment_status"], "pending")
        self.assertFalse(
            payment.admit_payment_submission(
                row["id"],
                now=self.now + timedelta(seconds=2),
            )
        )
        result = self.process(
            self.event(
                row,
                event_id="evt_payment_after_unknown_001",
            )
        )
        self.assertTrue(result["ok"])
        stored = db.fetchone(
            "SELECT payment_status,entitlement_status,terminal_at "
            "FROM payment_orders WHERE id=?",
            (row["id"],),
        )
        self.assertEqual(stored["payment_status"], "succeeded")
        self.assertEqual(stored["entitlement_status"], "applied")
        self.assertIsNotNone(stored["terminal_at"])
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM payment_cash_ledger "
                "WHERE order_id=? AND entry_type='payment_received'",
                (row["id"],),
            )["c"],
            1,
        )

    def test_direct_payment_accepts_pending_create_without_provider_id_then_late_binds(self):
        self.create_user()
        order = payment.create_order(
            "u-payment",
            "credit_package",
            "starter",
            idempotency_key="wechat-direct-late-bind-001",
            app_id=self.app_id,
            prod_mode=False,
            provider_name="wechatpay_direct",
            now=self.now,
        )
        row = dict(
            db.fetchone(
                "SELECT * FROM payment_orders WHERE id=?",
                (order["id"],),
            )
        )
        self.assertTrue(payment.admit_payment_submission(row["id"], now=self.now))
        payment.mark_payment_submission(
            row["id"],
            payment.ProviderPaymentResult(
                merchant_order_no=row["merchant_order_no"],
                provider_payment_id=None,
                status="pending",
                amount_fen=row["amount_fen"],
                app_id=self.app_id,
                prod_mode=False,
                response_verified=True,
                checkout_token="synthetic-wechat-native-code-url",
                provider_name="wechatpay_direct",
            ),
            now=self.now,
        )
        self.assertIsNone(
            db.fetchone(
                "SELECT provider_payment_id FROM payment_orders WHERE id=?",
                (row["id"],),
            )["provider_payment_id"]
        )
        event = payment.CallbackEvent(
            provider_event_id="wechat_event_001",
            event_type="payment.succeeded",
            created_time=int(self.now.timestamp()),
            prod_mode=False,
            app_id=self.app_id,
            provider_name="wechatpay_direct",
            data={
                "order_no": row["merchant_order_no"],
                "payment_id": "wechat_transaction_001",
                "pay_amt": "12.00",
            },
        )
        raw = b'{"verified":"wechat-direct-fixture-001"}'
        result = payment.process_authenticated_callback(
            event,
            raw,
            "verified-signature-fixture",
            expected_app_id=self.app_id,
            expected_provider_name="wechatpay_direct",
            expected_prod_mode=False,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        stored = db.fetchone(
            "SELECT provider_payment_id,payment_status,entitlement_status "
            "FROM payment_orders WHERE id=?",
            (row["id"],),
        )
        self.assertEqual(stored["provider_payment_id"], "wechat_transaction_001")
        self.assertEqual(stored["payment_status"], "succeeded")
        self.assertEqual(stored["entitlement_status"], "applied")
        duplicate = payment.process_authenticated_callback(
            event,
            raw,
            "verified-refreshed-delivery-signature-fixture",
            expected_app_id=self.app_id,
            expected_provider_name="wechatpay_direct",
            expected_prod_mode=False,
            now=self.now,
        )
        self.assertTrue(duplicate["duplicate"])

    def test_direct_refund_uses_merchant_identity_when_provider_refund_id_absent(self):
        self.create_user()
        order = payment.create_order(
            "u-payment",
            "credit_package",
            "starter",
            idempotency_key="alipay-direct-refund-001",
            app_id=self.app_id,
            prod_mode=False,
            provider_name="alipay_direct",
            now=self.now,
        )
        row = dict(db.fetchone("SELECT * FROM payment_orders WHERE id=?", (order["id"],)))
        event = payment.CallbackEvent(
            provider_event_id="alipay_event_001",
            event_type="payment.succeeded",
            created_time=int(self.now.timestamp()),
            prod_mode=False,
            app_id=self.app_id,
            provider_name="alipay_direct",
            data={
                "order_no": row["merchant_order_no"],
                "payment_id": "alipay_trade_001",
                "pay_amt": "12.00",
            },
        )
        payment.process_authenticated_callback(
            event,
            b'{"verified":"alipay-direct-fixture-001"}',
            "verified-signature-fixture",
            expected_app_id=self.app_id,
            expected_provider_name="alipay_direct",
            expected_prod_mode=False,
            now=self.now,
        )
        prepared = payment.prepare_full_refund(
            row["id"],
            reason_code="customer_request",
            now=self.now + timedelta(minutes=1),
        )
        refund = dict(
            db.fetchone(
                "SELECT * FROM payment_refunds WHERE id=?",
                (prepared["id"],),
            )
        )
        payment.mark_refund_submission(
            refund["id"],
            payment.ProviderRefundResult(
                merchant_refund_no=refund["merchant_refund_no"],
                provider_refund_id=None,
                status="pending",
                amount_fen=refund["amount_fen"],
                response_verified=True,
                merchant_order_no=row["merchant_order_no"],
                provider_payment_id="alipay_trade_001",
                provider_name="alipay_direct",
                app_id=self.app_id,
                prod_mode=False,
            ),
            now=self.now + timedelta(minutes=2),
        )
        stored = db.fetchone(
            "SELECT provider_refund_id,status FROM payment_refunds WHERE id=?",
            (refund["id"],),
        )
        self.assertIsNone(stored["provider_refund_id"])
        self.assertEqual(stored["status"], "pending")

    def test_wechat_refund_submission_time_is_write_once_and_query_recoverable(self):
        self.create_user()
        order = payment.create_order(
            "u-payment",
            "credit_package",
            "starter",
            idempotency_key="wechat-refund-recovery-001",
            app_id=self.app_id,
            prod_mode=False,
            provider_name="wechatpay_direct",
            now=self.now,
        )
        stored_order = dict(
            db.fetchone(
                "SELECT * FROM payment_orders WHERE id=?",
                (order["id"],),
            )
        )
        paid_event = payment.CallbackEvent(
            provider_event_id="wechat_refund_recovery_payment",
            event_type="payment.succeeded",
            created_time=int(self.now.timestamp()),
            prod_mode=False,
            app_id=self.app_id,
            provider_name="wechatpay_direct",
            data={
                "order_no": stored_order["merchant_order_no"],
                "payment_id": "wechat_refund_recovery_transaction",
                "pay_amt": "12.00",
            },
        )
        payment.process_authenticated_callback(
            paid_event,
            b'{"verified":"wechat-refund-payment"}',
            "verified-wechat-payment-signature",
            expected_app_id=self.app_id,
            expected_provider_name="wechatpay_direct",
            expected_prod_mode=False,
            now=self.now,
        )
        stored_order = dict(
            db.fetchone(
                "SELECT * FROM payment_orders WHERE id=?",
                (order["id"],),
            )
        )
        prepared = payment.prepare_full_refund(
            order["id"],
            reason_code="customer_request",
            now=self.now + timedelta(minutes=1),
        )
        refund = dict(
            db.fetchone(
                "SELECT * FROM payment_refunds WHERE id=?",
                (prepared["id"],),
            )
        )
        self.assertIsNone(refund["provider_submitted_at"])
        self.assertTrue(payment.admit_refund_submission(refund["id"]))

        # The terminal callback can win the race after the create request
        # timed out, before its signed response was durably bound.
        refund_event = payment.CallbackEvent(
            provider_event_id="wechat_refund_recovery_terminal",
            event_type="refund.succeeded",
            created_time=int((self.now + timedelta(days=1)).timestamp()),
            prod_mode=False,
            app_id=self.app_id,
            provider_name="wechatpay_direct",
            data={
                "refund_order_no": refund["merchant_refund_no"],
                "payment_id": stored_order["provider_payment_id"],
                "refund_id": "wechat_refund_recovery_id",
                "refund_amt": "12.00",
            },
        )
        payment.process_authenticated_callback(
            refund_event,
            b'{"verified":"wechat-refund-terminal"}',
            "verified-wechat-refund-signature",
            expected_app_id=self.app_id,
            expected_provider_name="wechatpay_direct",
            expected_prod_mode=False,
            now=self.now + timedelta(days=1),
        )
        submitted_at = int((self.now + timedelta(minutes=2)).timestamp())
        query_result = payment.ProviderRefundResult(
            merchant_refund_no=refund["merchant_refund_no"],
            provider_refund_id="wechat_refund_recovery_id",
            status="succeeded",
            amount_fen=1200,
            response_verified=True,
            merchant_order_no=stored_order["merchant_order_no"],
            provider_payment_id=stored_order["provider_payment_id"],
            provider_name="wechatpay_direct",
            app_id=self.app_id,
            prod_mode=False,
            provider_submitted_at=submitted_at,
        )
        recovered = payment.mark_refund_query_submission(
            query_result,
            now=self.now + timedelta(days=1, minutes=1),
        )
        self.assertEqual(recovered["status"], "succeeded")
        payment.mark_refund_query_submission(
            query_result,
            now=self.now + timedelta(days=1, minutes=2),
        )
        with self.assertRaisesRegex(
            payment.PaymentContractError,
            "PAYMENT_PROVIDER_RESPONSE_MISMATCH",
        ):
            payment.mark_refund_query_submission(
                payment.ProviderRefundResult(
                    **{
                        **query_result.__dict__,
                        "provider_submitted_at": submitted_at + 1,
                    }
                ),
                now=self.now + timedelta(days=1, minutes=3),
            )
        terminal = db.fetchone(
            "SELECT status,provider_submitted_at FROM payment_refunds "
            "WHERE id=?",
            (refund["id"],),
        )
        self.assertEqual(terminal["status"], "succeeded")
        self.assertEqual(terminal["provider_submitted_at"], submitted_at)
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM payment_cash_ledger "
                "WHERE refund_id=? AND entry_type='refund_paid'",
                (refund["id"],),
            )["c"],
            1,
        )

    def test_wechat_failed_refund_event_preserves_provider_submission_time(self):
        self.create_user()
        order = payment.create_order(
            "u-payment",
            "credit_package",
            "starter",
            idempotency_key="wechat-refund-failed-query-001",
            app_id=self.app_id,
            prod_mode=False,
            provider_name="wechatpay_direct",
            now=self.now,
        )
        stored_order = dict(
            db.fetchone("SELECT * FROM payment_orders WHERE id=?", (order["id"],))
        )
        payment.process_authenticated_callback(
            payment.CallbackEvent(
                provider_event_id="wechat_refund_failed_payment",
                event_type="payment.succeeded",
                created_time=int(self.now.timestamp()),
                prod_mode=False,
                app_id=self.app_id,
                provider_name="wechatpay_direct",
                data={
                    "order_no": stored_order["merchant_order_no"],
                    "payment_id": "wechat_refund_failed_transaction",
                    "pay_amt": "12.00",
                },
            ),
            b'{"verified":"wechat-refund-failed-payment"}',
            "verified-wechat-payment-signature",
            expected_app_id=self.app_id,
            expected_provider_name="wechatpay_direct",
            expected_prod_mode=False,
            now=self.now,
        )
        stored_order = dict(
            db.fetchone("SELECT * FROM payment_orders WHERE id=?", (order["id"],))
        )
        prepared = payment.prepare_full_refund(
            order["id"],
            reason_code="customer_request",
            now=self.now + timedelta(minutes=1),
        )
        refund = dict(
            db.fetchone(
                "SELECT * FROM payment_refunds WHERE id=?",
                (prepared["id"],),
            )
        )
        self.assertTrue(payment.admit_refund_submission(refund["id"]))
        submitted_at = int((self.now + timedelta(minutes=2)).timestamp())
        result = payment.process_authenticated_callback(
            payment.CallbackEvent(
                provider_event_id="wechat_refund_failed_terminal",
                event_type="refund.failed",
                created_time=int((self.now + timedelta(minutes=3)).timestamp()),
                prod_mode=False,
                app_id=self.app_id,
                provider_name="wechatpay_direct",
                data={
                    "refund_order_no": refund["merchant_refund_no"],
                    "payment_id": stored_order["provider_payment_id"],
                    "refund_id": "wechat_refund_failed_id",
                    "refund_amt": "12.00",
                    "provider_submitted_at": submitted_at,
                },
            ),
            b'{"verified":"wechat-refund-failed-terminal"}',
            "verified-wechat-refund-signature",
            expected_app_id=self.app_id,
            expected_provider_name="wechatpay_direct",
            expected_prod_mode=False,
            now=self.now + timedelta(minutes=3),
        )
        self.assertTrue(result["ok"])
        terminal = db.fetchone(
            "SELECT status,provider_submitted_at FROM payment_refunds WHERE id=?",
            (refund["id"],),
        )
        self.assertEqual(terminal["status"], "failed")
        self.assertEqual(terminal["provider_submitted_at"], submitted_at)
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM payment_cash_ledger WHERE refund_id=?",
                (refund["id"],),
            )["c"],
            0,
        )

    def test_refund_intent_cannot_insert_provider_submission_time(self):
        self.create_user()
        _order, row = self.create_order()
        self.succeed_order(row)
        with self.assertRaisesRegex(Exception, "invalid full refund intent"):
            db.execute(
                "INSERT INTO payment_refunds("
                "id,order_id,merchant_refund_no,provider_refund_id,"
                "amount_fen,currency,status,reason_code,"
                "provider_submitted_at,created_at,updated_at,terminal_at"
                ") VALUES(?,?,?,NULL,?,'CNY','requested','customer_request',"
                "?,?,?,NULL)",
                (
                    "00000000-0000-4000-8000-000000000031",
                    row["id"],
                    "NR_00000000000040008000000000000031",
                    int(row["amount_fen"]),
                    int(self.now.timestamp()),
                    self.now.isoformat(),
                    self.now.isoformat(),
                ),
            )

    def test_refund_submission_time_database_fence_is_integer_wechat_only(self):
        self.create_user()
        submitted_at = int(self.now.timestamp())
        for provider_name in ("adapay", "alipay_direct", "wechatpay_direct"):
            with self.subTest(provider_name=provider_name):
                order = payment.create_order(
                    "u-payment",
                    "credit_package",
                    "starter",
                    idempotency_key=f"refund-db-fence-{provider_name}",
                    app_id=self.app_id,
                    prod_mode=False,
                    provider_name=provider_name,
                    now=self.now,
                )
                row = dict(
                    db.fetchone(
                        "SELECT * FROM payment_orders WHERE id=?",
                        (order["id"],),
                    )
                )
                event = payment.CallbackEvent(
                    provider_event_id=f"refund_db_fence_{provider_name}",
                    event_type="payment.succeeded",
                    created_time=submitted_at,
                    prod_mode=False,
                    app_id=self.app_id,
                    provider_name=provider_name,
                    data={
                        "order_no": row["merchant_order_no"],
                        "payment_id": f"payment_{provider_name}",
                        "pay_amt": "12.00",
                    },
                )
                payment.process_authenticated_callback(
                    event,
                    f'{{"verified":"{provider_name}"}}'.encode(),
                    f"verified-{provider_name}-signature",
                    expected_app_id=self.app_id,
                    expected_provider_name=provider_name,
                    expected_prod_mode=False,
                    now=self.now,
                )
                refund = payment.prepare_full_refund(
                    order["id"],
                    reason_code="customer_request",
                    now=self.now,
                )
                with self.assertRaisesRegex(
                    Exception,
                    "payment refund provider submission is immutable",
                ):
                    db.execute(
                        "UPDATE payment_refunds SET provider_submitted_at=? "
                        "WHERE id=?",
                        (submitted_at, refund["id"]),
                    )
                db.execute(
                    "UPDATE payment_refunds SET status='pending' WHERE id=?",
                    (refund["id"],),
                )
                if provider_name != "wechatpay_direct":
                    with self.assertRaisesRegex(
                        Exception,
                        "payment refund provider submission is immutable",
                    ):
                        db.execute(
                            "UPDATE payment_refunds "
                            "SET provider_submitted_at=? WHERE id=?",
                            (submitted_at, refund["id"]),
                        )
                    continue
                for invalid in (submitted_at + 0.5,):
                    with self.subTest(invalid=invalid), self.assertRaisesRegex(
                        Exception,
                        "payment refund provider submission is immutable",
                    ):
                        db.execute(
                            "UPDATE payment_refunds "
                            "SET provider_submitted_at=? WHERE id=?",
                            (invalid, refund["id"]),
                        )
                db.execute(
                    "UPDATE payment_refunds SET provider_submitted_at=? "
                    "WHERE id=?",
                    (submitted_at, refund["id"]),
                )
                stored = db.fetchone(
                    "SELECT provider_submitted_at,"
                    "typeof(provider_submitted_at) AS value_type "
                    "FROM payment_refunds WHERE id=?",
                    (refund["id"],),
                )
                self.assertEqual(stored["provider_submitted_at"], submitted_at)
                self.assertEqual(stored["value_type"], "integer")

    def test_legacy_sqlite_event_schema_upgrades_once_to_duplicate_counter(self):
        db.execute("DROP TRIGGER IF EXISTS payment_events_transition_v1")
        db.execute(
            "ALTER TABLE payment_events DROP COLUMN duplicate_delivery_count"
        )

        db.init_db()
        db.init_db()

        columns = {
            row["name"]: dict(row)
            for row in db.fetchall("PRAGMA table_info(payment_events)")
        }
        counter = columns["duplicate_delivery_count"]
        self.assertEqual(counter["type"], "INTEGER")
        self.assertEqual(counter["notnull"], 1)
        self.assertEqual(counter["dflt_value"], "0")
        transition = db.fetchone(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='payment_events_transition_v1'"
        )["sql"]
        self.assertIn(
            "NEW.duplicate_delivery_count>OLD.duplicate_delivery_count+1",
            transition,
        )

    def test_wechat_reconciliation_uses_shanghai_provider_dates(self):
        self.create_user()
        payment_clock = datetime(2026, 9, 5, 15, 58, tzinfo=timezone.utc)
        refund_clock = datetime(2026, 9, 5, 15, 59, 30, tzinfo=timezone.utc)
        terminal_clock = datetime(2026, 9, 5, 16, 1, tzinfo=timezone.utc)
        order = payment.create_order(
            "u-payment",
            "credit_package",
            "starter",
            idempotency_key="wechat-shanghai-reconcile-001",
            app_id=self.app_id,
            prod_mode=False,
            provider_name="wechatpay_direct",
            now=payment_clock,
        )
        stored_order = dict(
            db.fetchone(
                "SELECT * FROM payment_orders WHERE id=?",
                (order["id"],),
            )
        )
        payment.process_authenticated_callback(
            payment.CallbackEvent(
                provider_event_id="wechat_shanghai_payment",
                event_type="payment.succeeded",
                created_time=int(payment_clock.timestamp()),
                prod_mode=False,
                app_id=self.app_id,
                provider_name="wechatpay_direct",
                data={
                    "order_no": stored_order["merchant_order_no"],
                    "payment_id": "wechat_shanghai_transaction",
                    "pay_amt": "12.00",
                },
            ),
            b'{"verified":"wechat-shanghai-payment"}',
            "verified-wechat-shanghai-payment-signature",
            expected_app_id=self.app_id,
            expected_provider_name="wechatpay_direct",
            expected_prod_mode=False,
            now=terminal_clock,
        )
        stored_order = dict(
            db.fetchone(
                "SELECT * FROM payment_orders WHERE id=?",
                (order["id"],),
            )
        )
        prepared = payment.prepare_full_refund(
            order["id"],
            reason_code="customer_request",
            now=refund_clock,
        )
        refund = dict(
            db.fetchone(
                "SELECT * FROM payment_refunds WHERE id=?",
                (prepared["id"],),
            )
        )
        payment.mark_refund_submission(
            refund["id"],
            payment.ProviderRefundResult(
                merchant_refund_no=refund["merchant_refund_no"],
                provider_refund_id="wechat_shanghai_refund",
                status="pending",
                amount_fen=1200,
                response_verified=True,
                merchant_order_no=stored_order["merchant_order_no"],
                provider_payment_id=stored_order["provider_payment_id"],
                provider_name="wechatpay_direct",
                app_id=self.app_id,
                prod_mode=False,
                provider_submitted_at=int(refund_clock.timestamp()),
            ),
            now=terminal_clock,
        )
        payment.process_authenticated_callback(
            payment.CallbackEvent(
                provider_event_id="wechat_shanghai_refund_terminal",
                event_type="refund.succeeded",
                created_time=int(terminal_clock.timestamp()),
                prod_mode=False,
                app_id=self.app_id,
                provider_name="wechatpay_direct",
                data={
                    "refund_order_no": refund["merchant_refund_no"],
                    "payment_id": stored_order["provider_payment_id"],
                    "refund_id": "wechat_shanghai_refund",
                    "refund_amt": "12.00",
                },
            ),
            b'{"verified":"wechat-shanghai-refund"}',
            "verified-wechat-shanghai-refund-signature",
            expected_app_id=self.app_id,
            expected_provider_name="wechatpay_direct",
            expected_prod_mode=False,
            now=terminal_clock,
        )
        rows = [
            {
                "kind": "payment",
                "reference": stored_order["merchant_order_no"],
                "amount_fen": 1200,
                "status": "succeeded",
            },
            {
                "kind": "refund",
                "reference": refund["merchant_refund_no"],
                "amount_fen": 1200,
                "status": "succeeded",
            },
        ]
        day_five = payment.reconcile_bill(
            "2026-09-05",
            b"synthetic-wechat-day-five",
            rows,
            prod_mode=False,
            provider_name="wechatpay_direct",
            now=terminal_clock,
        )
        self.assertEqual(day_five["status"], "matched")
        day_six = payment.reconcile_bill(
            "2026-09-06",
            b"synthetic-wechat-day-six",
            [],
            prod_mode=False,
            provider_name="wechatpay_direct",
            now=terminal_clock + timedelta(minutes=1),
        )
        self.assertEqual(day_six["status"], "matched")

    def test_entitlement_failure_rolls_back_partial_grant_but_keeps_cash(self):
        self.create_user()
        _order, row = self.create_order()

        def partial_grant(tx, order, event_id, clock):
            tx.execute(
                "INSERT INTO credits("
                "user_id,balance,total_purchased,total_used,updated_at"
                ") VALUES(?,99,99,0,?)",
                (order["user_id"], clock),
            )
            tx.execute(
                "INSERT INTO payment_credit_positions("
                "order_id,user_id,subject_hash,granted_milli,"
                "remaining_milli,state,created_at,updated_at"
                ") VALUES(?,?,?,?,?,'active',?,?)",
                (
                    order["id"],
                    order["user_id"],
                    order["subject_hash"],
                    99000,
                    99000,
                    clock,
                    clock,
                ),
            )
            raise RuntimeError("synthetic partial entitlement failure")

        with mock.patch.object(
            payment,
            "_apply_credit_entitlement",
            side_effect=partial_grant,
        ):
            result = self.process(self.event(row))
        self.assertEqual(result["code"], "PAYMENT_ENTITLEMENT_NEEDS_MANUAL")
        stored = db.fetchone(
            "SELECT payment_status,entitlement_status FROM payment_orders "
            "WHERE id=?",
            (row["id"],),
        )
        self.assertEqual(stored["payment_status"], "succeeded")
        self.assertEqual(stored["entitlement_status"], "needs_manual")
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM payment_cash_ledger")["c"],
            1,
        )
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM credits")["c"],
            0,
        )
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM payment_credit_positions"
            )["c"],
            0,
        )

    def test_preexisting_cash_conflict_never_grants_entitlement(self):
        self.create_user()
        _order, row = self.create_order()
        ignored_event = json.dumps(
            {
                "id": "evt_preexisting_cash_evidence",
                "type": "payment.reviewed",
                "created_time": int(self.now.timestamp()),
                "prod_mode": False,
                "app_id": self.app_id,
                "data": {},
            },
            separators=(",", ":"),
        )
        self.assertTrue(self.process(ignored_event)["ignored"])
        source_event_id = db.fetchone(
            "SELECT id FROM payment_events"
        )["id"]
        db.execute(
            "INSERT INTO payment_cash_ledger("
            "id,order_id,refund_id,entry_type,amount_fen,currency,"
            "source_event_id,recorded_at"
            ") VALUES(?,?,NULL,'payment_received_unmatched',1200,'CNY',?,?)",
            (
                "preexisting-cash-row",
                row["id"],
                source_event_id,
                self.now.isoformat(),
            ),
        )
        result = self.process(
            self.event(
                row,
                event_id="evt_payment_after_cash_conflict",
            )
        )
        self.assertEqual(result["code"], "PAYMENT_CASH_LEDGER_CONFLICT")
        stored = db.fetchone(
            "SELECT payment_status,entitlement_status FROM payment_orders "
            "WHERE id=?",
            (row["id"],),
        )
        self.assertEqual(stored["payment_status"], "needs_manual")
        self.assertEqual(stored["entitlement_status"], "pending")
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM payment_cash_ledger")["c"],
            1,
        )
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM payment_entitlement_ledger"
            )["c"],
            0,
        )

    def test_success_after_failed_payment_is_unmatched_cash_manual_once(self):
        self.create_user()
        _order, row = self.create_order()
        self.process(
            self.event(
                row,
                event_id="evt_payment_failed_first",
                event_type="payment.failed",
            )
        )
        result = self.process(
            self.event(
                row,
                event_id="evt_payment_success_after_failed",
            )
        )
        self.assertEqual(result["code"], "PAYMENT_CONTRADICTORY_TERMINAL")
        repeated = self.process(
            self.event(
                row,
                event_id="evt_payment_success_after_failed_second",
            )
        )
        self.assertEqual(
            repeated["code"],
            "PAYMENT_CONTRADICTORY_TERMINAL",
        )
        stored = db.fetchone(
            "SELECT payment_status,entitlement_status FROM payment_orders "
            "WHERE id=?",
            (row["id"],),
        )
        self.assertEqual(stored["payment_status"], "needs_manual")
        self.assertEqual(stored["entitlement_status"], "pending")
        cash = db.fetchall(
            "SELECT entry_type,amount_fen FROM payment_cash_ledger"
        )
        self.assertEqual(len(cash), 1)
        self.assertEqual(cash[0]["entry_type"], "payment_received_unmatched")
        self.assertEqual(cash[0]["amount_fen"], 1200)
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM payment_entitlement_ledger"
            )["c"],
            0,
        )

    def test_failed_event_after_success_cannot_downgrade(self):
        self.create_user()
        _order, row = self.create_order()
        self.succeed_order(row)
        result = self.process(
            self.event(
                row,
                event_id="evt_payment_stale_failed",
                event_type="payment.failed",
            )
        )
        self.assertTrue(result["ignored"])
        self.assertEqual(
            db.fetchone(
                "SELECT payment_status FROM payment_orders WHERE id=?",
                (row["id"],),
            )["payment_status"],
            "succeeded",
        )

    def test_failed_close_is_not_falsely_treated_as_closed(self):
        self.create_user()
        _order, row = self.create_order()
        result = self.process(
            self.event(
                row,
                event_id="evt_payment_close_failed",
                event_type="payment.close.failed",
            )
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "PAYMENT_CLOSE_NEEDS_MANUAL")
        self.assertEqual(
            db.fetchone(
                "SELECT payment_status FROM payment_orders WHERE id=?",
                (row["id"],),
            )["payment_status"],
            "needs_manual",
        )

    def test_wallet_usage_tracks_and_restores_exact_paid_position(self):
        self.create_user()
        _order, row = self.create_order()
        self.succeed_order(row)
        db.execute(
            "UPDATE subscriptions SET used_monthly_credits=12 "
            "WHERE user_id='u-payment' AND is_active=1"
        )
        charge = billing.check_and_deduct("u-payment", "analyze")
        position = db.fetchone(
            "SELECT granted_milli,remaining_milli,state "
            "FROM payment_credit_positions WHERE order_id=?",
            (row["id"],),
        )
        self.assertEqual(position["remaining_milli"], 24000)
        self.assertEqual(
            db.fetchone(
                "SELECT amount_milli,state FROM payment_credit_consumptions "
                "WHERE usage_id=?",
                (charge["usage_id"],),
            )["amount_milli"],
            6000,
        )
        billing.refund_operation_charge(
            "u-payment",
            "analyze",
            charge,
            "isolated failure",
        )
        restored = db.fetchone(
            "SELECT remaining_milli,state FROM payment_credit_positions "
            "WHERE order_id=?",
            (row["id"],),
        )
        self.assertEqual(restored["remaining_milli"], 30000)
        self.assertEqual(restored["state"], "active")
        self.assertEqual(
            db.fetchone(
                "SELECT state FROM payment_credit_consumptions "
                "WHERE usage_id=?",
                (charge["usage_id"],),
            )["state"],
            "restored",
        )
        with self.assertRaises(Exception):
            db.execute(
                "UPDATE payment_credit_consumptions SET state='consumed' "
                "WHERE usage_id=?",
                (charge["usage_id"],),
            )
        with self.assertRaises(Exception):
            db.execute(
                "UPDATE payment_credit_positions SET user_id='other-user' "
                "WHERE order_id=?",
                (row["id"],),
            )

    def test_full_unused_credit_refund_reconciles_cash_and_entitlement(self):
        self.create_user()
        _order, row = self.create_order()
        self.succeed_order(row)
        prepared = payment.prepare_full_refund(
            row["id"],
            reason_code="customer_request",
            now=self.now + timedelta(minutes=1),
        )
        refund_row = dict(
            db.fetchone(
                "SELECT * FROM payment_refunds WHERE id=?",
                (prepared["id"],),
            )
        )
        payment.mark_refund_submission(
            refund_row["id"],
            payment.ProviderRefundResult(
                merchant_refund_no=refund_row["merchant_refund_no"],
                provider_refund_id="provider_refund_001",
                status="pending",
                amount_fen=refund_row["amount_fen"],
                response_verified=True,
            ),
            now=self.now + timedelta(minutes=2),
        )
        refund_row = dict(
            db.fetchone(
                "SELECT * FROM payment_refunds WHERE id=?",
                (prepared["id"],),
            )
        )
        order_row = dict(
            db.fetchone(
                "SELECT * FROM payment_orders WHERE id=?",
                (row["id"],),
            )
        )
        result = self.process(self.refund_event(order_row, refund_row))
        self.assertTrue(result["ok"])
        self.assertEqual(
            db.fetchone(
                "SELECT SUM(amount_fen) AS total FROM payment_cash_ledger"
            )["total"],
            0,
        )
        self.assertEqual(
            db.fetchone(
                "SELECT balance,total_purchased FROM credits "
                "WHERE user_id='u-payment'"
            )["balance"],
            0,
        )
        self.assertEqual(
            db.fetchone(
                "SELECT state FROM payment_credit_positions WHERE order_id=?",
                (row["id"],),
            )["state"],
            "reversed",
        )
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM payment_entitlement_ledger"
            )["c"],
            2,
        )

    def test_refund_submission_mismatch_commits_manual_state_before_error(self):
        self.create_user()
        _order, row = self.create_order()
        self.succeed_order(row)
        prepared = payment.prepare_full_refund(
            row["id"],
            reason_code="customer_request",
            now=self.now + timedelta(minutes=1),
        )
        refund = dict(
            db.fetchone(
                "SELECT * FROM payment_refunds WHERE id=?",
                (prepared["id"],),
            )
        )
        self.assertTrue(
            payment.admit_refund_submission(
                refund["id"],
                now=self.now + timedelta(minutes=2),
            )
        )
        self.assertFalse(
            payment.admit_refund_submission(
                refund["id"],
                now=self.now + timedelta(minutes=2),
            )
        )
        with self.assertRaises(payment.PaymentContractError) as mismatch:
            payment.mark_refund_submission(
                refund["id"],
                payment.ProviderRefundResult(
                    merchant_refund_no=refund["merchant_refund_no"],
                    provider_refund_id="provider_refund_mismatch",
                    status="pending",
                    amount_fen=int(refund["amount_fen"]) - 1,
                    response_verified=True,
                ),
                now=self.now + timedelta(minutes=2),
            )
        self.assertEqual(
            mismatch.exception.code,
            "PAYMENT_PROVIDER_RESPONSE_MISMATCH",
        )
        stored_refund = db.fetchone(
            "SELECT status,provider_refund_id FROM payment_refunds WHERE id=?",
            (refund["id"],),
        )
        self.assertEqual(stored_refund["status"], "needs_manual")
        self.assertIsNone(stored_refund["provider_refund_id"])
        self.assertEqual(
            db.fetchone(
                "SELECT refund_status FROM payment_orders WHERE id=?",
                (row["id"],),
            )["refund_status"],
            "needs_manual",
        )

    def test_refund_reversal_failure_rolls_back_partial_entitlement_changes(self):
        self.create_user()
        _order, row = self.create_order()
        self.succeed_order(row)
        prepared = payment.prepare_full_refund(
            row["id"],
            reason_code="customer_request",
            now=self.now + timedelta(minutes=1),
        )
        refund = dict(
            db.fetchone(
                "SELECT * FROM payment_refunds WHERE id=?",
                (prepared["id"],),
            )
        )
        payment.mark_refund_submission(
            refund["id"],
            payment.ProviderRefundResult(
                merchant_refund_no=refund["merchant_refund_no"],
                provider_refund_id="provider_refund_partial_reversal",
                status="pending",
                amount_fen=refund["amount_fen"],
                response_verified=True,
            ),
        )
        refund = dict(
            db.fetchone(
                "SELECT * FROM payment_refunds WHERE id=?",
                (refund["id"],),
            )
        )
        order = dict(
            db.fetchone(
                "SELECT * FROM payment_orders WHERE id=?",
                (row["id"],),
            )
        )

        def partial_reversal(tx, order_row, refund_row, event_id, clock):
            tx.execute(
                "UPDATE credits SET balance=0,total_purchased=0 "
                "WHERE user_id=?",
                (order_row["user_id"],),
            )
            tx.execute(
                "UPDATE payment_credit_positions SET remaining_milli=0,"
                "state='reversed' WHERE order_id=?",
                (order_row["id"],),
            )
            raise RuntimeError("synthetic partial reversal failure")

        with mock.patch.object(
            payment,
            "_reverse_credit_entitlement",
            side_effect=partial_reversal,
        ):
            result = self.process(self.refund_event(order, refund))
        self.assertEqual(result["code"], "PAYMENT_REFUND_NEEDS_MANUAL")
        credit = db.fetchone(
            "SELECT balance,total_purchased FROM credits "
            "WHERE user_id='u-payment'"
        )
        self.assertEqual(credit["balance"], 30)
        self.assertEqual(credit["total_purchased"], 30)
        position = db.fetchone(
            "SELECT remaining_milli,state FROM payment_credit_positions "
            "WHERE order_id=?",
            (row["id"],),
        )
        self.assertEqual(position["remaining_milli"], 30000)
        self.assertEqual(position["state"], "active")
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM payment_entitlement_ledger"
            )["c"],
            1,
        )
        self.assertEqual(
            db.fetchone(
                "SELECT SUM(amount_fen) AS total FROM payment_cash_ledger"
            )["total"],
            0,
        )

    def test_success_after_failed_refund_is_unmatched_cash_manual_once(self):
        self.create_user()
        _order, row = self.create_order()
        self.succeed_order(row)
        prepared = payment.prepare_full_refund(
            row["id"],
            reason_code="customer_request",
            now=self.now + timedelta(minutes=1),
        )
        refund = dict(
            db.fetchone(
                "SELECT * FROM payment_refunds WHERE id=?",
                (prepared["id"],),
            )
        )
        payment.mark_refund_submission(
            refund["id"],
            payment.ProviderRefundResult(
                merchant_refund_no=refund["merchant_refund_no"],
                provider_refund_id="provider_refund_contradictory",
                status="pending",
                amount_fen=refund["amount_fen"],
                response_verified=True,
            ),
        )
        refund = dict(
            db.fetchone(
                "SELECT * FROM payment_refunds WHERE id=?",
                (refund["id"],),
            )
        )
        order = dict(
            db.fetchone(
                "SELECT * FROM payment_orders WHERE id=?",
                (row["id"],),
            )
        )
        failed = self.process(
            self.refund_event(
                order,
                refund,
                event_id="evt_refund_failed_first",
                event_type="refund.failed",
            )
        )
        self.assertTrue(failed["ok"])
        failed_order = dict(
            db.fetchone(
                "SELECT * FROM payment_orders WHERE id=?",
                (row["id"],),
            )
        )
        failed_refund = dict(
            db.fetchone(
                "SELECT * FROM payment_refunds WHERE id=?",
                (refund["id"],),
            )
        )
        first = self.process(
            self.refund_event(
                failed_order,
                failed_refund,
                event_id="evt_refund_success_after_failed",
            )
        )
        self.assertEqual(
            first["code"],
            "PAYMENT_REFUND_CONTRADICTORY_TERMINAL",
        )
        manual_order = dict(
            db.fetchone(
                "SELECT * FROM payment_orders WHERE id=?",
                (row["id"],),
            )
        )
        manual_refund = dict(
            db.fetchone(
                "SELECT * FROM payment_refunds WHERE id=?",
                (refund["id"],),
            )
        )
        second = self.process(
            self.refund_event(
                manual_order,
                manual_refund,
                event_id="evt_refund_success_after_failed_second",
            )
        )
        self.assertEqual(
            second["code"],
            "PAYMENT_REFUND_CONTRADICTORY_TERMINAL",
        )
        self.assertEqual(manual_refund["status"], "needs_manual")
        self.assertEqual(manual_order["refund_status"], "needs_manual")
        self.assertEqual(manual_order["entitlement_status"], "needs_manual")
        refund_cash = db.fetchall(
            "SELECT entry_type,amount_fen FROM payment_cash_ledger "
            "WHERE refund_id=?",
            (refund["id"],),
        )
        self.assertEqual(len(refund_cash), 1)
        self.assertEqual(refund_cash[0]["entry_type"], "refund_paid_unmatched")
        self.assertEqual(refund_cash[0]["amount_fen"], -1200)
        self.assertEqual(
            db.fetchone(
                "SELECT state FROM payment_credit_positions WHERE order_id=?",
                (row["id"],),
            )["state"],
            "active",
        )

    def test_consumed_credit_purchase_cannot_prepare_cash_refund(self):
        self.create_user()
        _order, row = self.create_order()
        self.succeed_order(row)
        db.execute(
            "UPDATE subscriptions SET used_monthly_credits=12 "
            "WHERE user_id='u-payment' AND is_active=1"
        )
        billing.check_and_deduct("u-payment", "analyze")
        with self.assertRaises(payment.PaymentContractError) as blocked:
            payment.prepare_full_refund(
                row["id"],
                reason_code="customer_request",
                now=self.now + timedelta(minutes=1),
            )
        self.assertEqual(
            blocked.exception.code,
            "PAYMENT_REFUND_ENTITLEMENT_USED",
        )

    def test_subscription_is_one_30_day_allocation_without_calendar_reset(self):
        self.create_user()
        _order, row = self.create_order(
            product_kind="subscription",
            product_id="pro",
        )
        self.succeed_order(row)
        subscription = db.fetchone(
            "SELECT * FROM subscriptions WHERE user_id='u-payment' "
            "AND is_active=1"
        )
        start = datetime.fromisoformat(subscription["started_at"])
        expires = datetime.fromisoformat(subscription["expires_at"])
        self.assertEqual(expires - start, timedelta(days=30))
        db.execute(
            "UPDATE subscriptions SET used_monthly_credits=17,"
            "period_start=? WHERE id=?",
            (
                (self.now - timedelta(days=45)).isoformat(),
                subscription["id"],
            ),
        )
        with mock.patch.object(billing, "_now", return_value=self.now.isoformat()):
            current = billing.get_subscription("u-payment")
        self.assertEqual(current["used_monthly_credits"], 17)
        paid_id = subscription["id"]
        after_expiry = (expires + timedelta(seconds=1)).isoformat()
        with mock.patch.object(billing, "_now", return_value=after_expiry):
            expired = billing.get_subscription("u-payment")
        self.assertEqual(expired["tier"], "free")
        historical = db.fetchone(
            "SELECT tier,is_active FROM subscriptions WHERE id=?",
            (paid_id,),
        )
        self.assertEqual(historical["tier"], "pro")
        self.assertEqual(historical["is_active"], 0)

    def test_unused_subscription_can_be_fully_refunded(self):
        self.create_user()
        _order, row = self.create_order(
            product_kind="subscription",
            product_id="growth",
        )
        self.succeed_order(row)
        prepared = payment.prepare_full_refund(
            row["id"],
            reason_code="service_not_delivered",
            now=self.now + timedelta(minutes=1),
        )
        refund = dict(
            db.fetchone(
                "SELECT * FROM payment_refunds WHERE id=?",
                (prepared["id"],),
            )
        )
        payment.mark_refund_submission(
            refund["id"],
            payment.ProviderRefundResult(
                merchant_refund_no=refund["merchant_refund_no"],
                provider_refund_id="provider_refund_subscription",
                status="pending",
                amount_fen=refund["amount_fen"],
                response_verified=True,
            ),
        )
        refund = dict(
            db.fetchone(
                "SELECT * FROM payment_refunds WHERE id=?",
                (refund["id"],),
            )
        )
        order = dict(
            db.fetchone(
                "SELECT * FROM payment_orders WHERE id=?",
                (row["id"],),
            )
        )
        result = self.process(
            self.refund_event(
                order,
                refund,
                event_id="evt_refund_subscription",
            )
        )
        self.assertTrue(result["ok"])
        active = db.fetchone(
            "SELECT tier FROM subscriptions WHERE user_id='u-payment' "
            "AND is_active=1"
        )
        self.assertEqual(active["tier"], "free")

    def test_reconciliation_and_settlement_store_only_bounded_evidence(self):
        self.create_user()
        _order, row = self.create_order()
        self.succeed_order(row)
        matched = payment.reconcile_bill(
            self.now.date().isoformat(),
            b"provider-bill-private-content",
            [
                {
                    "kind": "payment",
                    "reference": row["merchant_order_no"],
                    "amount_fen": 1200,
                    "status": "succeeded",
                }
            ],
            prod_mode=False,
            now=self.now,
        )
        self.assertEqual(matched["status"], "matched")
        replay = payment.reconcile_bill(
            self.now.date().isoformat(),
            b"provider-bill-private-content",
            [
                {
                    "kind": "payment",
                    "reference": row["merchant_order_no"],
                    "amount_fen": 1200,
                    "status": "succeeded",
                }
            ],
            prod_mode=False,
            now=self.now + timedelta(seconds=1),
        )
        self.assertEqual(replay["id"], matched["id"])
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM payment_reconciliation_runs "
                "WHERE id=?",
                (matched["id"],),
            )["c"],
            1,
        )
        stored = db.fetchone(
            "SELECT source_sha256,row_count,discrepancy_count "
            "FROM payment_reconciliation_runs WHERE id=?",
            (matched["id"],),
        )
        self.assertEqual(stored["row_count"], 1)
        self.assertEqual(stored["discrepancy_count"], 0)
        database_bytes = Path(db._DB_PATH).read_bytes()
        self.assertNotIn(b"provider-bill-private-content", database_bytes)
        mismatch = payment.reconcile_bill(
            self.now.date().isoformat(),
            b"provider-bill-second-private-content",
            [
                {
                    "kind": "payment",
                    "reference": row["merchant_order_no"],
                    "amount_fen": 1300,
                    "status": "succeeded",
                }
            ],
            prod_mode=False,
            now=self.now + timedelta(minutes=1),
        )
        self.assertEqual(mismatch["status"], "discrepancies")
        self.assertEqual(mismatch["discrepancy_count"], 1)

        alipay_empty = payment.reconcile_bill(
            (self.now + timedelta(days=2)).date().isoformat(),
            b"synthetic-empty-alipay-trade-bill",
            [],
            prod_mode=True,
            provider_name="alipay_direct",
            now=self.now + timedelta(days=3),
        )
        self.assertEqual(alipay_empty["status"], "matched")
        self.assertEqual(alipay_empty["row_count"], 0)
        self.assertEqual(
            db.fetchone(
                "SELECT provider FROM payment_reconciliation_runs WHERE id=?",
                (alipay_empty["id"],),
            )["provider"],
            "alipay_direct",
        )

        for index, provider_status in enumerate(
            ("pending", "failed", "closed"),
            start=1,
        ):
            unresolved = payment.reconcile_bill(
                (self.now + timedelta(days=1)).date().isoformat(),
                f"provider-bill-unresolved-{provider_status}".encode("ascii"),
                [
                    {
                        "kind": "refund",
                        "reference": f"NR_unresolved_{index}",
                        "amount_fen": 1200,
                        "status": provider_status,
                    }
                ],
                prod_mode=False,
                now=self.now + timedelta(minutes=index + 1),
            )
            self.assertEqual(unresolved["status"], "discrepancies")
            self.assertEqual(unresolved["discrepancy_count"], 1)
            discrepancy = db.fetchone(
                "SELECT issue_code FROM payment_reconciliation_items "
                "WHERE run_id=?",
                (unresolved["id"],),
            )
            self.assertEqual(discrepancy["issue_code"], "status_mismatch")
        settlement = payment.record_settlement_summary(
            self.now.date().isoformat(),
            source_sha256="a" * 64,
            gross_fen=1200,
            refund_fen=0,
            fee_fen=20,
            net_fen=1180,
            prod_mode=False,
            provider_name="wechatpay_direct",
            now=self.now,
        )
        self.assertEqual(settlement["status"], "verified")
        self.assertEqual(settlement["provider"], "wechatpay_direct")
        self.assertEqual(
            db.fetchone(
                "SELECT provider FROM payment_settlement_summaries "
                "WHERE id=?",
                (settlement["id"],),
            )["provider"],
            "wechatpay_direct",
        )
        alipay_settlement = payment.record_settlement_summary(
            self.now.date().isoformat(),
            source_sha256="b" * 64,
            gross_fen=800,
            refund_fen=100,
            fee_fen=10,
            net_fen=690,
            prod_mode=False,
            provider_name="alipay_direct",
            now=self.now,
        )
        self.assertEqual(alipay_settlement["provider"], "alipay_direct")
        self.assertEqual(
            db.fetchone(
                "SELECT provider FROM payment_settlement_summaries "
                "WHERE id=?",
                (alipay_settlement["id"],),
            )["provider"],
            "alipay_direct",
        )
        with self.assertRaisesRegex(
            payment.PaymentContractError,
            "PAYMENT_PROVIDER_INVALID",
        ):
            payment.record_settlement_summary(
                self.now.date().isoformat(),
                source_sha256="c" * 64,
                gross_fen=100,
                refund_fen=0,
                fee_fen=0,
                net_fen=100,
                prod_mode=False,
                provider_name="unknown_provider",
                now=self.now,
            )
        with self.assertRaises(payment.PaymentContractError):
            payment.record_settlement_summary(
                self.now.date().isoformat(),
                source_sha256="b" * 64,
                gross_fen=1200,
                refund_fen=0,
                fee_fen=20,
                net_fen=1179,
                prod_mode=False,
            )

    def test_immutable_cash_and_entitlement_ledgers_reject_rewrite_delete(self):
        self.create_user()
        _order, row = self.create_order()
        self.succeed_order(row)
        cash_id = db.fetchone(
            "SELECT id FROM payment_cash_ledger"
        )["id"]
        entitlement_id = db.fetchone(
            "SELECT id FROM payment_entitlement_ledger"
        )["id"]
        with self.assertRaises(Exception):
            db.execute(
                "UPDATE payment_cash_ledger SET amount_fen=1 WHERE id=?",
                (cash_id,),
            )
        with self.assertRaises(Exception):
            db.execute(
                "DELETE FROM payment_entitlement_ledger WHERE id=?",
                (entitlement_id,),
            )

    def test_account_deletion_closes_provider_free_intent_and_pseudonymizes_cash(self):
        self.create_user()
        _pending, pending_row = self.create_order()
        with self.assertRaises(Exception):
            db.execute(
                "UPDATE payment_orders SET user_id='other-user' WHERE id=?",
                (pending_row["id"],),
            )
        with self.assertRaises(Exception):
            db.execute(
                "UPDATE payment_orders SET user_id=NULL,"
                "payment_status='succeeded' WHERE id=?",
                (pending_row["id"],),
            )
        content_retention.request_account_deletion("u-payment")
        self.assertEqual(
            db.fetchone(
                "SELECT payment_status FROM payment_orders WHERE id=?",
                (pending_row["id"],),
            )["payment_status"],
            "closed",
        )

        # A second account with settled cash can complete primary deletion;
        # its live join disappears while immutable finance survives.
        self.create_user("u-payment-settled")
        _order, settled = self.create_order(
            user_id="u-payment-settled",
            key="payment-request-settled",
        )
        self.succeed_order(settled, event_id="evt_payment_settled")
        content_retention.request_account_deletion("u-payment-settled")
        completed = content_retention.process_due_account_deletions(
            now=datetime.now(timezone.utc) + timedelta(hours=25),
        )
        self.assertEqual(len(completed), 2)
        order_after = db.fetchone(
            "SELECT user_id,subject_hash FROM payment_orders WHERE id=?",
            (settled["id"],),
        )
        self.assertIsNone(order_after["user_id"])
        self.assertEqual(len(order_after["subject_hash"]), 64)
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM payment_cash_ledger "
                "WHERE order_id=?",
                (settled["id"],),
            )["c"],
            1,
        )

    def test_unresolved_provider_payment_blocks_account_deletion(self):
        self.create_user()
        _order, row = self.create_order()
        db.execute(
            "UPDATE payment_orders SET payment_status='pending',"
            "provider_payment_id='provider_pending_1' WHERE id=?",
            (row["id"],),
        )
        with self.assertRaises(ValueError) as blocked:
            content_retention.request_account_deletion("u-payment")
        self.assertIn("unresolved payment", str(blocked.exception))

    def test_unavailable_provider_is_fail_closed(self):
        provider = payment.UnavailablePaymentProvider()
        with self.assertRaises(payment.PaymentProviderUnavailable):
            provider.create_payment({})


if __name__ == "__main__":
    unittest.main()
