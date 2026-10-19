"""Offline cover policy contracts; fixtures are choices, never enabled defaults."""
import copy
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))

import cover_policy as cover


class CoverPolicyTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "enabled": True, "operation": "cover_generate", "provider": "test_ark",
            "model_id": "test-seedream-pro-pinned-20261019", "width": 1000, "height": 2000,
            "credits": "4.25", "retention_seconds": 86400, "max_physical_calls": 3,
            "provider_budget": "2.00", "budget_currency": "CNY",
            "image_pricing": {"mode": "seedream_pro_pixel_tier", "currency": "CNY",
                              "version": "test-price-v1", "output_le_2610000": "0.30",
                              "output_gt_2610000": "0.60", "extra_input": "0.02"},
        }
        self.models = {"test_ark": {self.config["model_id"]}}

    def policy(self, config=None):
        return cover.validate_policy(self.config if config is None else config, supported_models=self.models)

    def test_missing_or_disabled_policy_never_activates(self):
        for config in (None, {}, {"enabled": False}, {"enabled": "true"}, {"enabled": 1}):
            with self.subTest(config=config), self.assertRaisesRegex(cover.CoverPolicyError, "COVER_DISABLED"):
                cover.validate_policy(config, supported_models=self.models)

    def test_required_product_choices_are_not_defaulted(self):
        for field in ("operation", "provider", "model_id", "width", "height", "credits", "retention_seconds",
                      "max_physical_calls", "provider_budget", "budget_currency", "image_pricing"):
            config = copy.deepcopy(self.config)
            del config[field]
            with self.subTest(field=field), self.assertRaises(cover.CoverPolicyError):
                self.policy(config)

    def test_unknown_task_or_provider_or_model_has_no_fallback(self):
        for field, value in (("operation", "semantic"), ("provider", "kimi"), ("model_id", "unknown-model")):
            config = copy.deepcopy(self.config)
            config[field] = value
            with self.subTest(field=field), self.assertRaises(cover.CoverPolicyError):
                self.policy(config)
        with self.assertRaises(cover.CoverPolicyError):
            cover.resolve_cover_route("generate", self.policy())
        self.assertEqual(cover.resolve_cover_route("cover_generate", self.policy()),
                         {"provider": "test_ark", "model_id": self.config["model_id"]})

    def test_allowlist_cannot_enable_dynamic_alias(self):
        config = copy.deepcopy(self.config)
        config["model_id"] = "test-seedream-latest"
        with self.assertRaisesRegex(cover.CoverPolicyError, "dynamic"):
            cover.validate_policy(config, supported_models={"test_ark": {config["model_id"]}})

    def test_scalar_string_allowlist_is_not_substring_model_selection(self):
        with self.assertRaises(cover.CoverPolicyError):
            cover.validate_policy(self.config, supported_models={"test_ark": self.config["model_id"]})

    def test_no_nonfinite_negative_zero_or_boolean_product_values(self):
        for field, values in (("credits", ["NaN", "Infinity", "-1", "0", True]),
                              ("provider_budget", ["NaN", "-1", "0", False]),
                              ("retention_seconds", [0, -1, True, 1.5]),
                              ("max_physical_calls", [0, -1, True]),
                              ("width", [0, True]), ("height", [-1, "2000"])):
            for value in values:
                config = copy.deepcopy(self.config)
                config[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(cover.CoverPolicyError):
                    self.policy(config)

    def test_price_currency_and_version_explicit(self):
        for field, value in (("currency", "USD"), ("version", ""), ("extra_input", None),
                             ("output_le_2610000", "NaN"), ("mode", "guessed")):
            config = copy.deepcopy(self.config)
            config["image_pricing"][field] = value
            with self.subTest(field=field), self.assertRaises(cover.CoverPolicyError):
                self.policy(config)

    def test_pro_inclusive_pixel_threshold_and_first_input_free(self):
        self.config.update(width=1305, height=2000)
        self.assertEqual(cover.estimate_image_call(self.policy(), input_images=1), Decimal("0.30"))
        self.config["width"] = 1306
        self.assertEqual(cover.estimate_image_call(self.policy(), input_images=1), Decimal("0.60"))

    def test_single_and_nine_images_and_exact_decimal_arithmetic(self):
        policy = self.policy()
        self.assertEqual(cover.estimate_image_call(policy, input_images=1), Decimal("0.30"))
        self.assertEqual(cover.estimate_image_call(policy, input_images=9), Decimal("0.46"))
        self.config["image_pricing"]["extra_input"] = "0.003"
        self.assertEqual(cover.estimate_image_call(self.policy(), input_images=9), Decimal("0.324"))
        for count in (0, 10, True, 1.5):
            with self.subTest(count=count), self.assertRaises(cover.CoverPolicyError):
                cover.estimate_image_call(policy, input_images=count)

    def test_flat_price_uses_passed_tariff(self):
        self.config["image_pricing"] = {"mode": "per_image", "currency": "CNY", "version": "fixture-flat-v2",
                                        "output": "0.175", "extra_input": "0.01"}
        self.assertEqual(cover.estimate_image_call(self.policy(), input_images=9), Decimal("0.255"))

    def test_quote_separates_credits_public_estimate_and_unknown_actual(self):
        quote = cover.build_quote(self.policy(), input_images=9, other_planned_calls=2, other_estimated_cost="0.11")
        self.assertEqual(quote["operation"], "cover_generate")
        self.assertEqual(quote["credits"], "4.25")
        self.assertEqual(quote["estimated_provider_cost"], "0.57")
        self.assertEqual(quote["planned_physical_calls"], 3)
        self.assertEqual(quote["charged_credits"], "0")
        self.assertEqual(quote["charge_timing"], "after_saved_cover")
        self.assertEqual(quote["cost_status"], "public_estimate")
        self.assertIsNone(quote["actual_provider_cost"])

    def test_quote_rejects_over_budget_and_uncounted_model_calls(self):
        policy = self.policy()
        for kwargs in ({"planned_image_calls": 4}, {"other_planned_calls": 3},
                       {"other_estimated_cost": "0.1"}, {"other_planned_calls": 2, "other_estimated_cost": "1.71"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(cover.CoverPolicyError):
                cover.build_quote(policy, input_images=1, **kwargs)
        quote = cover.build_quote(policy, input_images=1, other_planned_calls=2, other_estimated_cost="1.70")
        self.assertEqual(quote["estimated_provider_cost"], "2.00")

    def test_explicit_zero_image_call_plan_does_not_invent_supplier_generation(self):
        quote = cover.build_quote(self.policy(), input_images=1, planned_image_calls=0,
                                 other_planned_calls=2, other_estimated_cost="0.11")
        self.assertEqual(quote["planned_physical_calls"], 2)
        self.assertEqual(quote["estimated_image_cost"], "0.00")
        self.assertEqual(quote["estimated_provider_cost"], "0.11")
        self.assertIsNone(quote["actual_provider_cost"])

    def test_quote_snapshot_is_stable_and_changes_with_policy_or_materials(self):
        a = cover.build_quote(self.policy(), input_images=1)
        self.assertEqual(a, cover.build_quote(self.policy(), input_images=1))
        b = cover.build_quote(self.policy(), input_images=9)
        self.assertNotEqual(a["quote_version"], b["quote_version"])
        self.config["credits"] = "5"
        c = cover.build_quote(self.policy(), input_images=1)
        self.assertNotEqual(a["quote_version"], c["quote_version"])
        self.config["credits"] = "4.25"
        self.config["retention_seconds"] += 1
        d = cover.build_quote(self.policy(), input_images=1)
        self.assertNotEqual(a["quote_version"], d["quote_version"])

    def test_cost_ledger_deduplicates_same_physical_identity(self):
        row = {"call_id": "physical-1", "status": "billed", "estimated_cost": "0.46",
               "actual_cost": "0.43", "evidence_ref": "fixture-receipt-1", "currency": "CNY"}
        result = cover.summarize_costs([row, dict(row)])
        self.assertEqual(result["physical_calls"], 1)
        self.assertEqual(result["actual_cost"], Decimal("0.43"))
        conflict = {**row, "actual_cost": "0.45"}
        with self.assertRaisesRegex(cover.CoverPolicyError, "conflicting"):
            cover.summarize_costs([row, conflict])

    def test_unknown_retains_estimate_and_never_becomes_exact_zero(self):
        rows = [{"call_id": "physical-1", "status": "unknown", "estimated_cost": "0.46", "currency": "CNY"},
                {"call_id": "physical-2", "status": "billed", "estimated_cost": "0.30", "actual_cost": "0.28",
                 "evidence_ref": "fixture-receipt-2", "currency": "CNY"}]
        result = cover.summarize_costs(rows)
        self.assertIsNone(result["actual_cost"])
        self.assertEqual(result["known_billed_cost"], Decimal("0.28"))
        self.assertEqual(result["estimated_cost"], Decimal("0.76"))
        self.assertEqual(result["unknown_calls"], 1)
        self.assertIsNone(cover.summarize_costs([])["actual_cost"])

    def test_estimated_cost_needs_billing_evidence_before_actual_label(self):
        base = {"call_id": "physical-1", "status": "estimated", "estimated_cost": "0.30", "currency": "CNY"}
        self.assertIsNone(cover.summarize_costs([base])["actual_cost"])
        for row in ({**base, "actual_cost": "0.30"},
                    {**base, "status": "billed", "actual_cost": "0.30"},
                    {**base, "status": "billed", "actual_cost": "NaN", "evidence_ref": "receipt"}):
            with self.subTest(row=row), self.assertRaises(cover.CoverPolicyError):
                cover.summarize_costs([row])

    def test_mixed_currencies_not_silently_added(self):
        rows = [{"call_id": "physical-1", "status": "unknown", "estimated_cost": "0.46", "currency": "CNY"},
                {"call_id": "physical-2", "status": "estimated", "estimated_cost": "0.30", "currency": "USD"}]
        with self.assertRaises(cover.CoverPolicyError):
            cover.summarize_costs(rows)

    def test_only_original_unstarted_work_is_automatically_resumable(self):
        self.assertEqual(cover.recovery_action(dispatched=False, outcome="pending"), "resume_original_unstarted_task")
        self.assertEqual(cover.recovery_action(dispatched=True, outcome="pending"), "reconcile_original_request")
        self.assertEqual(cover.recovery_action(dispatched=True, outcome="unknown"), "reconcile_original_request")
        self.assertEqual(cover.recovery_action(dispatched=True, outcome="succeeded"), "recover_original_result")
        self.assertEqual(cover.recovery_action(dispatched=True, outcome="failed"), "finish_original_failure")
        with self.assertRaises(cover.CoverPolicyError):
            cover.recovery_action(dispatched=False, outcome="unknown")

    def test_reopen_download_and_query_require_no_new_charge_quote(self):
        for action in ("reopen", "download", "query"):
            self.assertFalse(cover.action_requires_new_quote(action))
        for action in ("generate", "regenerate"):
            self.assertTrue(cover.action_requires_new_quote(action))
        with self.assertRaises(cover.CoverPolicyError):
            cover.action_requires_new_quote("unknown-task")


if __name__ == "__main__":
    unittest.main()
