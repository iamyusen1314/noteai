import asyncio
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

db = importlib.import_module("db")
billing = importlib.import_module("billing")
admin_server = importlib.import_module("admin_server")


class BillingTokenCostTests(unittest.TestCase):
    def setUp(self):
        self._old_db_path = db._DB_PATH
        self._tmpdir = tempfile.TemporaryDirectory()
        db._DB_PATH = Path(self._tmpdir.name) / "noteai.db"
        db.init_db()
        billing.clear_active_usage()

    def tearDown(self):
        billing.clear_active_usage()
        db._DB_PATH = self._old_db_path
        self._tmpdir.cleanup()

    def _restore_env(self, old_values):
        for key, value in old_values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _create_user(self, user_id: str = "u-paid"):
        db.execute(
            "INSERT INTO users(id,username,email,password_hash,password_salt,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (user_id, f"{user_id}_name", f"{user_id}@example.com", "hash", "salt", "2026-06-29T00:00:00+00:00"),
        )

    def test_model_usage_replaces_estimated_cost_when_actual_cost_is_known(self):
        billing.record_free_usage("u-token", "score")
        billing.record_model_usage(
            "claude",
            "claude-haiku-4-5-20251001",
            tokens_in=1200,
            tokens_out=320,
            cost_rmb=0.0385,
        )

        summary = billing.get_usage_summary("u-token", days=30)
        score = summary["by_operation"]["score"]

        self.assertEqual(summary["total_tokens"], 1520)
        self.assertEqual(score["tokens_in"], 1200)
        self.assertEqual(score["tokens_out"], 320)
        self.assertEqual(score["model_calls"], 1)
        self.assertEqual(score["cost_rmb"], 0.0385)
        recent = summary["recent_records"][0]
        self.assertEqual(recent["cost_mode"], "actual")
        self.assertIn("claude:claude-haiku", recent["model_names"])

    def test_token_count_keeps_estimated_cost_when_price_is_not_configured(self):
        price_keys = [
            "NOTEAI_MODEL_PRICE_CLAUDE_INPUT_PER_1M_RMB",
            "NOTEAI_MODEL_PRICE_CLAUDE_OUTPUT_PER_1M_RMB",
            "NOTEAI_MODEL_PRICE_CLAUDE_HAIKU_4_5_20251001_INPUT_PER_1M_RMB",
            "NOTEAI_MODEL_PRICE_CLAUDE_HAIKU_4_5_20251001_OUTPUT_PER_1M_RMB",
            "NOTEAI_MODEL_PRICE_CLAUDE_INPUT_PER_1M_USD",
            "NOTEAI_MODEL_PRICE_CLAUDE_OUTPUT_PER_1M_USD",
            "NOTEAI_MODEL_PRICE_CLAUDE_HAIKU_4_5_20251001_INPUT_PER_1M_USD",
            "NOTEAI_MODEL_PRICE_CLAUDE_HAIKU_4_5_20251001_OUTPUT_PER_1M_USD",
        ]
        old_values = {key: os.environ.get(key) for key in price_keys}
        try:
            for key in price_keys:
                os.environ.pop(key, None)
            billing.record_free_usage("u-estimated", "diagnose")
            billing.record_model_usage(
                "claude",
                "claude-haiku-4-5-20251001",
                tokens_in=100,
                tokens_out=50,
            )

            summary = billing.get_usage_summary("u-estimated", days=30)
            diagnose = summary["by_operation"]["diagnose"]

            self.assertEqual(diagnose["total_tokens"], 150)
            self.assertEqual(diagnose["cost_rmb"], billing.OPERATIONS["diagnose"]["cost"])
            self.assertEqual(summary["recent_records"][0]["cost_mode"], "token_counted_estimated_cost")
        finally:
            self._restore_env(old_values)

    def test_kimi_rmb_model_price_computes_actual_cost(self):
        price_keys = [
            "NOTEAI_MODEL_PRICE_KIMI_INPUT_PER_1M_RMB",
            "NOTEAI_MODEL_PRICE_KIMI_OUTPUT_PER_1M_RMB",
            "NOTEAI_MODEL_PRICE_KIMI_K2_5_INPUT_PER_1M_RMB",
            "NOTEAI_MODEL_PRICE_KIMI_K2_5_OUTPUT_PER_1M_RMB",
        ]
        old_values = {key: os.environ.get(key) for key in price_keys}
        try:
            for key in price_keys:
                os.environ.pop(key, None)
            os.environ["NOTEAI_MODEL_PRICE_KIMI_INPUT_PER_1M_RMB"] = "2"
            os.environ["NOTEAI_MODEL_PRICE_KIMI_OUTPUT_PER_1M_RMB"] = "8"
            billing.record_free_usage("u-priced", "chat_fast")
            billing.record_model_usage("kimi", "kimi-k2.5", tokens_in=1000, tokens_out=500)

            summary = billing.get_usage_summary("u-priced", days=30)
            self.assertEqual(summary["by_operation"]["chat_fast"]["cost_rmb"], 0.006)
            self.assertEqual(summary["by_operation"]["chat_fast"]["actual_model_cost_rmb"], 0.006)
        finally:
            self._restore_env(old_values)

    def test_claude_usd_model_price_converts_to_rmb_cost(self):
        price_keys = [
            "NOTEAI_BILLING_USD_CNY",
            "NOTEAI_MODEL_PRICE_CLAUDE_INPUT_PER_1M_USD",
            "NOTEAI_MODEL_PRICE_CLAUDE_OUTPUT_PER_1M_USD",
            "NOTEAI_MODEL_PRICE_CLAUDE_HAIKU_4_5_20251001_INPUT_PER_1M_USD",
            "NOTEAI_MODEL_PRICE_CLAUDE_HAIKU_4_5_20251001_OUTPUT_PER_1M_USD",
        ]
        old_values = {key: os.environ.get(key) for key in price_keys}
        try:
            for key in price_keys:
                os.environ.pop(key, None)
            os.environ["NOTEAI_BILLING_USD_CNY"] = "7"
            os.environ["NOTEAI_MODEL_PRICE_CLAUDE_INPUT_PER_1M_USD"] = "1"
            os.environ["NOTEAI_MODEL_PRICE_CLAUDE_OUTPUT_PER_1M_USD"] = "5"
            billing.record_free_usage("u-claude-usd", "score")
            billing.record_model_usage("claude", "claude-haiku-4-5-20251001", tokens_in=1000, tokens_out=200)

            summary = billing.get_usage_summary("u-claude-usd", days=30)

            # USD cost: 0.001*1 + 0.0002*5 = $0.002. RMB at 7.0 = ¥0.014.
            self.assertEqual(summary["by_operation"]["score"]["cost_rmb"], 0.014)
            self.assertEqual(summary["by_operation"]["score"]["actual_model_cost_rmb"], 0.014)
        finally:
            self._restore_env(old_values)

    def test_auxiliary_usage_does_not_steal_active_model_tokens(self):
        self._create_user("u-analyze")
        billing.record_free_usage("u-analyze", "analyze")
        billing.record_auxiliary_usage("u-analyze", "extra_image")
        billing.record_model_usage("claude", "claude-haiku-4-5-20251001", 600, 200, cost_rmb=0.04)

        summary = billing.get_usage_summary("u-analyze", days=30)

        self.assertEqual(summary["by_operation"]["analyze"]["total_tokens"], 800)
        self.assertEqual(summary["by_operation"]["analyze"]["actual_model_cost_rmb"], 0.04)
        self.assertEqual(summary["by_operation"]["extra_image"]["total_tokens"], 0)

    def test_unpriced_later_call_does_not_downgrade_actual_cost_mode(self):
        price_keys = [
            "NOTEAI_MODEL_PRICE_KIMI_INPUT_PER_1M_RMB",
            "NOTEAI_MODEL_PRICE_KIMI_OUTPUT_PER_1M_RMB",
            "NOTEAI_MODEL_PRICE_KIMI_K2_5_INPUT_PER_1M_RMB",
            "NOTEAI_MODEL_PRICE_KIMI_K2_5_OUTPUT_PER_1M_RMB",
        ]
        old_values = {key: os.environ.get(key) for key in price_keys}
        try:
            for key in price_keys:
                os.environ.pop(key, None)
            billing.record_free_usage("u-mixed", "score")
            billing.record_model_usage("claude", "claude-haiku-4-5-20251001", 100, 40, cost_rmb=0.02)
            billing.record_model_usage("kimi", "kimi-k2.5", 20, 10)

            summary = billing.get_usage_summary("u-mixed", days=30)
            recent = summary["recent_records"][0]

            self.assertEqual(summary["by_operation"]["score"]["total_tokens"], 170)
            self.assertEqual(summary["by_operation"]["score"]["cost_rmb"], 0.02)
            self.assertEqual(recent["cost_mode"], "actual")
        finally:
            self._restore_env(old_values)

    def test_admin_usage_stats_reads_same_token_and_cost_totals(self):
        billing.record_free_usage("u-admin", "score")
        billing.record_model_usage("claude", "claude-haiku-4-5-20251001", 10, 5, cost_rmb=0.02)

        report = admin_server.build_usage_stats_payload(days=30)
        by_op = {row["op"]: row for row in report["by_operation"]}

        self.assertEqual(by_op["score"]["total_tokens"], 15)
        self.assertEqual(by_op["score"]["cost"], 0.02)

    def test_paid_topup_records_real_rmb_and_gift_does_not_count_as_revenue(self):
        self._create_user("u-revenue")

        purchase = billing.purchase_credit_package("u-revenue", "creator", payment_ref="pay_001")
        gift_balance = billing.grant_credits("u-revenue", 50, "测试赠送")

        self.assertEqual(purchase["new_balance"], 100)
        self.assertEqual(gift_balance, 150)

        txns = billing.get_credit_transactions("u-revenue", limit=10)
        gift = next(t for t in txns if t["type"] == "gift")
        topup = next(t for t in txns if t["type"] == "topup")

        self.assertEqual(topup["amount"], 100)
        self.assertEqual(topup["paid_rmb"], 39)
        self.assertEqual(topup["package_id"], "creator")
        self.assertEqual(gift["amount"], 50)
        self.assertEqual(gift["paid_rmb"], 0)

        report = asyncio.run(admin_server.admin_revenue(days=30, admin={"id": "admin"}))
        self.assertEqual(sum(row["rmb"] for row in report["daily_topup"]), 39)
        self.assertEqual(sum(row["credits"] for row in report["daily_topup"]), 100)

    def test_monthly_credits_are_used_before_wallet_credits(self):
        self._create_user("u-costs")
        billing.topup_credits("u-costs", 30, paid_rmb=12, package_id="starter")

        first = billing.check_and_deduct("u-costs", "analyze")
        second = billing.check_and_deduct("u-costs", "analyze")
        generate = billing.check_and_deduct("u-costs", "generate")

        self.assertEqual(first["source"], "subscription")
        self.assertEqual(first["credits_used"], 6.0)
        self.assertEqual(first["monthly_credits_used"], 6.0)
        self.assertEqual(second["source"], "subscription")
        self.assertEqual(second["monthly_credits_used"], 6.0)
        self.assertEqual(generate["source"], "credits")
        self.assertEqual(generate["credits_used"], 8.0)

        sub = db.fetchone("SELECT used_monthly_credits FROM subscriptions WHERE user_id=? AND is_active=1", ("u-costs",))
        balance = db.fetchone("SELECT balance,total_used FROM credits WHERE user_id=?", ("u-costs",))
        self.assertEqual(sub["used_monthly_credits"], 12)
        self.assertEqual(balance["balance"], 22)
        self.assertEqual(balance["total_used"], 8)

    def test_monthly_and_wallet_credits_can_be_mixed_for_one_operation(self):
        self._create_user("u-mixed-charge")
        billing.get_subscription("u-mixed-charge")
        billing.topup_credits("u-mixed-charge", 30, paid_rmb=12, package_id="starter")
        db.execute(
            "UPDATE subscriptions SET used_monthly_credits=10 WHERE user_id=? AND is_active=1",
            ("u-mixed-charge",),
        )

        charge = billing.check_and_deduct("u-mixed-charge", "generate")

        self.assertEqual(charge["source"], "mixed")
        self.assertEqual(charge["credits_used"], 8.0)
        self.assertEqual(charge["monthly_credits_used"], 2.0)
        self.assertEqual(charge["wallet_credits_used"], 6.0)
        sub = db.fetchone("SELECT used_monthly_credits FROM subscriptions WHERE user_id=? AND is_active=1", ("u-mixed-charge",))
        balance = db.fetchone("SELECT balance,total_used FROM credits WHERE user_id=?", ("u-mixed-charge",))
        usage = db.fetchone("SELECT source,credits_used FROM usage_records WHERE user_id=?", ("u-mixed-charge",))
        self.assertEqual(sub["used_monthly_credits"], 12)
        self.assertEqual(balance["balance"], 24)
        self.assertEqual(balance["total_used"], 6)
        self.assertEqual(usage["source"], "mixed")
        self.assertEqual(usage["credits_used"], 8)

    def test_credit_packages_are_part_of_public_billing_contract(self):
        packages = billing.list_credit_packages()
        by_id = {pkg["id"]: pkg for pkg in packages}

        self.assertEqual(by_id["starter"]["credits"], 30)
        self.assertEqual(by_id["starter"]["price_rmb"], 12)
        self.assertEqual(by_id["creator"]["credits"], 100)
        self.assertEqual(by_id["creator"]["price_rmb"], 39)
        self.assertTrue(by_id["creator"]["recommended"])
        self.assertEqual(billing.OPERATIONS["analyze"]["credits"], 6.0)
        self.assertEqual(billing.OPERATIONS["generate"]["credits"], 8.0)
        self.assertEqual(billing.OPERATIONS["chat_rewrite"]["credits"], 3.0)
        self.assertEqual(billing.TIERS["pro"]["monthly_credits"], 260.0)
        self.assertEqual(billing.TIERS["growth"]["monthly_credits"], 560.0)

    def test_refund_operation_charge_restores_credit_balance_and_marks_usage(self):
        self._create_user("u-refund")
        billing.get_subscription("u-refund")
        billing.topup_credits("u-refund", 30, paid_rmb=12, package_id="starter")
        db.execute("UPDATE subscriptions SET used_monthly_credits=12 WHERE user_id=?", ("u-refund",))

        charge = billing.check_and_deduct("u-refund", "analyze")
        billing.record_model_usage("claude", "claude-haiku-4-5-20251001", 1000, 200, cost_rmb=0.02)
        billing.refund_operation_charge("u-refund", "analyze", charge, "测试失败退款")

        credits = db.fetchone("SELECT balance,total_used FROM credits WHERE user_id=?", ("u-refund",))
        usage = db.fetchone("SELECT source,credits_used,cost_rmb FROM usage_records WHERE user_id=?", ("u-refund",))
        refund = db.fetchone("SELECT type,amount,balance_after FROM credit_transactions WHERE user_id=? AND type='refund'", ("u-refund",))

        self.assertEqual(credits["balance"], 30)
        self.assertEqual(credits["total_used"], 0)
        self.assertEqual(usage["source"], "refunded")
        self.assertEqual(usage["credits_used"], 0)
        self.assertEqual(usage["cost_rmb"], 0.02)
        self.assertEqual(refund["amount"], 6)
        self.assertEqual(refund["balance_after"], 30)

    def test_refund_operation_charge_restores_mixed_monthly_and_wallet_credits(self):
        self._create_user("u-mixed-refund")
        billing.get_subscription("u-mixed-refund")
        billing.topup_credits("u-mixed-refund", 30, paid_rmb=12, package_id="starter")
        db.execute("UPDATE subscriptions SET used_monthly_credits=10 WHERE user_id=?", ("u-mixed-refund",))

        charge = billing.check_and_deduct("u-mixed-refund", "generate")
        billing.refund_operation_charge("u-mixed-refund", "generate", charge, "混合扣费失败退款")

        sub = db.fetchone("SELECT used_monthly_credits FROM subscriptions WHERE user_id=? AND is_active=1", ("u-mixed-refund",))
        credits = db.fetchone("SELECT balance,total_used FROM credits WHERE user_id=?", ("u-mixed-refund",))
        usage = db.fetchone("SELECT source,credits_used FROM usage_records WHERE user_id=?", ("u-mixed-refund",))
        refund = db.fetchone("SELECT type,amount,balance_after FROM credit_transactions WHERE user_id=? AND type='refund'", ("u-mixed-refund",))

        self.assertEqual(sub["used_monthly_credits"], 10)
        self.assertEqual(credits["balance"], 30)
        self.assertEqual(credits["total_used"], 0)
        self.assertEqual(usage["source"], "refunded")
        self.assertEqual(usage["credits_used"], 0)
        self.assertEqual(refund["amount"], 6)
        self.assertEqual(refund["balance_after"], 30)


if __name__ == "__main__":
    unittest.main()
