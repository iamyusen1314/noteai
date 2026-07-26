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

    def test_catalog_matches_visible_prices_and_has_no_auto_renewal(self):
        payment.assert_catalog_matches_billing()
        self.assertEqual(len(payment.CATALOG), 8)
        contract = (
            ROOT / "docs" / "PAYMENT_PRODUCTION_CONTRACT.md"
        ).read_text(encoding="utf-8")
        self.assertIn("no auto-renewal", contract)
        self.assertIn("integer CNY fen", contract)
        self.assertIn("Studio remains one NoteAI account", contract)

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
        provider_request = payment.provider_payment_request(full)
        self.assertEqual(
            set(provider_request),
            {
                "merchant_order_no",
                "amount_fen",
                "currency",
                "product_kind",
                "product_id",
                "provider_mode",
            },
        )
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
            db.fetchone("SELECT COUNT(*) AS c FROM payment_cash_ledger")["c"],
            1,
        )

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
        self.assertEqual(finance["unmatched_fen"], 1300)
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
        settlement = payment.record_settlement_summary(
            self.now.date().isoformat(),
            source_sha256="a" * 64,
            gross_fen=1200,
            refund_fen=0,
            fee_fen=20,
            net_fen=1180,
            prod_mode=False,
            now=self.now,
        )
        self.assertEqual(settlement["status"], "verified")
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
