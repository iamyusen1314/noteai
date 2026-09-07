import importlib
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "model"
if str(MODEL) not in sys.path:
    sys.path.insert(0, str(MODEL))

import direct_payment_gateways as direct
import payment_contract

db = importlib.import_module("db")
billing = importlib.import_module("billing")


class PaymentQueryFinancialEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.old_db_path = db._DB_PATH
        self.old_database_url = os.environ.pop("DATABASE_URL", None)
        self.temp = tempfile.TemporaryDirectory()
        db._DB_PATH = Path(self.temp.name) / "query-financial-evidence.db"
        db.init_db()
        billing.clear_active_usage()
        self.now = datetime.fromtimestamp(1788573600, tz=timezone.utc)
        db.execute(
            "INSERT INTO users("
            "id,username,email,password_hash,password_salt,created_at"
            ") VALUES(?,?,?,?,?,?)",
            (
                "u-query-evidence",
                "query_evidence_user",
                "query-evidence@example.com",
                "hash",
                "salt",
                self.now.isoformat(),
            ),
        )
        billing.get_subscription("u-query-evidence")
        self.order = payment_contract.create_order(
            "u-query-evidence",
            "credit_package",
            "starter",
            idempotency_key="query-evidence-order-001",
            app_id="wxSyntheticApp01",
            prod_mode=True,
            provider_name="wechatpay_direct",
            now=self.now,
        )
        self.stored_order = dict(
            db.fetchone(
                "SELECT * FROM payment_orders WHERE id=?",
                (self.order["id"],),
            )
        )
        self.assertTrue(
            payment_contract.admit_payment_submission(
                self.stored_order["id"],
                now=self.now,
            )
        )
        payment_contract.mark_payment_submission_unknown(
            self.stored_order["id"],
            now=self.now,
        )

    def tearDown(self):
        billing.clear_active_usage()
        db._DB_PATH = self.old_db_path
        if self.old_database_url is not None:
            os.environ["DATABASE_URL"] = self.old_database_url
        else:
            os.environ.pop("DATABASE_URL", None)
        self.temp.cleanup()

    def _payment_query(self, *, amount_fen=1200, payment_id="payment-query-001"):
        return direct._process_verified_payment_query(
            payment_contract.ProviderPaymentResult(
                merchant_order_no=self.stored_order["merchant_order_no"],
                provider_payment_id=payment_id,
                status="succeeded",
                amount_fen=amount_fen,
                app_id="wxSyntheticApp01",
                prod_mode=True,
                response_verified=True,
                provider_name="wechatpay_direct",
                provider_created_at=1788573599,
            ),
            b'{"authenticated":"payment-query"}',
            "synthetic-verified-signature",
            1788573600,
            expected_app_id="wxSyntheticApp01",
            expected_provider_name="wechatpay_direct",
            expected_prod_mode=True,
            now=self.now,
        )

    def test_signed_success_payment_mismatch_records_unmatched_cash_once(self):
        first = self._payment_query(amount_fen=1300)
        duplicate = self._payment_query(amount_fen=1300)

        self.assertEqual(first["code"], "PAYMENT_ORDER_MISMATCH")
        self.assertTrue(duplicate["duplicate"])
        order = db.fetchone(
            "SELECT payment_status,entitlement_status FROM payment_orders "
            "WHERE id=?",
            (self.stored_order["id"],),
        )
        self.assertEqual(order["payment_status"], "needs_manual")
        self.assertEqual(order["entitlement_status"], "pending")
        events = db.fetchone(
            "SELECT COUNT(*) AS c FROM payment_events WHERE order_id=?",
            (self.stored_order["id"],),
        )
        cash = db.fetchall(
            "SELECT entry_type,amount_fen FROM payment_cash_ledger "
            "WHERE order_id=?",
            (self.stored_order["id"],),
        )
        self.assertEqual(events["c"], 1)
        self.assertEqual(
            [dict(row) for row in cash],
            [{"entry_type": "payment_received_unmatched", "amount_fen": 1300}],
        )

    def test_signed_success_refund_mismatch_records_unmatched_cash_once(self):
        paid = self._payment_query()
        self.assertTrue(paid["ok"])
        prepared = payment_contract.prepare_full_refund(
            self.stored_order["id"],
            reason_code="customer_request",
            now=self.now,
        )
        refund = dict(
            db.fetchone(
                "SELECT * FROM payment_refunds WHERE id=?",
                (prepared["id"],),
            )
        )
        self.assertTrue(payment_contract.admit_refund_submission(refund["id"]))
        result = payment_contract.ProviderRefundResult(
            merchant_refund_no=refund["merchant_refund_no"],
            provider_refund_id="refund-query-001",
            status="succeeded",
            amount_fen=1300,
            response_verified=True,
            merchant_order_no=self.stored_order["merchant_order_no"],
            provider_payment_id="payment-query-001",
            provider_name="wechatpay_direct",
            app_id="wxSyntheticApp01",
            prod_mode=True,
            provider_submitted_at=1788573601,
            provider_created_at=1788573602,
        )

        def run():
            return direct._process_verified_refund_query(
                result,
                b'{"authenticated":"refund-query"}',
                "synthetic-verified-refund-signature",
                1788573603,
                expected_app_id="wxSyntheticApp01",
                expected_provider_name="wechatpay_direct",
                expected_prod_mode=True,
                now=self.now,
            )

        first = run()
        duplicate = run()

        self.assertEqual(first["code"], "PAYMENT_REFUND_MISMATCH")
        self.assertTrue(duplicate["duplicate"])
        terminal_refund = db.fetchone(
            "SELECT status FROM payment_refunds WHERE id=?",
            (refund["id"],),
        )
        order = db.fetchone(
            "SELECT refund_status,entitlement_status FROM payment_orders "
            "WHERE id=?",
            (self.stored_order["id"],),
        )
        cash = db.fetchall(
            "SELECT entry_type,amount_fen FROM payment_cash_ledger "
            "WHERE refund_id=?",
            (refund["id"],),
        )
        reversals = db.fetchone(
            "SELECT COUNT(*) AS c FROM payment_entitlement_ledger "
            "WHERE refund_id=?",
            (refund["id"],),
        )
        self.assertEqual(terminal_refund["status"], "needs_manual")
        self.assertEqual(order["refund_status"], "needs_manual")
        self.assertEqual(order["entitlement_status"], "applied")
        self.assertEqual(
            [dict(row) for row in cash],
            [{"entry_type": "refund_paid_unmatched", "amount_fen": -1300}],
        )
        self.assertEqual(reversals["c"], 0)

    def test_signed_refund_query_backfills_submission_time_after_callback(self):
        self.assertTrue(self._payment_query()["ok"])
        prepared = payment_contract.prepare_full_refund(
            self.stored_order["id"],
            reason_code="customer_request",
            now=self.now,
        )
        refund = dict(
            db.fetchone(
                "SELECT * FROM payment_refunds WHERE id=?",
                (prepared["id"],),
            )
        )
        self.assertTrue(payment_contract.admit_refund_submission(refund["id"]))

        def result(submitted_at):
            return payment_contract.ProviderRefundResult(
                merchant_refund_no=refund["merchant_refund_no"],
                provider_refund_id="refund-query-backfill-001",
                status="succeeded",
                amount_fen=1200,
                response_verified=True,
                merchant_order_no=self.stored_order["merchant_order_no"],
                provider_payment_id="payment-query-001",
                provider_name="wechatpay_direct",
                app_id="wxSyntheticApp01",
                prod_mode=True,
                provider_submitted_at=submitted_at,
                provider_created_at=1788573602,
            )

        callback = direct._process_verified_refund_query(
            result(None),
            b'{"authenticated":"refund-callback-without-submission-time"}',
            "synthetic-verified-callback-signature",
            1788573603,
            expected_app_id="wxSyntheticApp01",
            expected_provider_name="wechatpay_direct",
            expected_prod_mode=True,
            now=self.now,
        )
        self.assertTrue(callback["ok"])
        self.assertIsNone(
            db.fetchone(
                "SELECT provider_submitted_at FROM payment_refunds WHERE id=?",
                (refund["id"],),
            )["provider_submitted_at"]
        )

        def query(submitted_at, raw):
            return direct._process_verified_refund_query(
                result(submitted_at),
                raw,
                "synthetic-verified-query-signature",
                1788573604,
                expected_app_id="wxSyntheticApp01",
                expected_provider_name="wechatpay_direct",
                expected_prod_mode=True,
                now=self.now,
            )

        raw = b'{"authenticated":"refund-query-with-submission-time"}'
        backfilled = query(1788573601, raw)
        duplicate = query(1788573601, raw)
        contradictory = query(
            1788573610,
            b'{"authenticated":"contradictory-refund-query"}',
        )

        self.assertTrue(backfilled["already_terminal"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(
            contradictory["code"],
            "PAYMENT_REFUND_CONTRADICTORY_TERMINAL",
        )
        stored = db.fetchone(
            "SELECT status,provider_submitted_at FROM payment_refunds WHERE id=?",
            (refund["id"],),
        )
        self.assertEqual(stored["status"], "succeeded")
        self.assertEqual(stored["provider_submitted_at"], 1788573601)


if __name__ == "__main__":
    unittest.main()
