import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import internal_deployment_readiness_gate as gate  # noqa: E402
import verify_internal_zero_provider_smoke_evidence as item27_verifier  # noqa: E402


class InternalDeploymentReadinessGateTests(unittest.TestCase):
    def setUp(self):
        self.manifest = gate.load_manifest()

    def test_current_manifest_is_valid_and_fail_closed(self):
        report = gate.build_report()

        self.assertTrue(report["manifest_valid"])
        self.assertEqual(
            report["layers"]["repository_isolated"],
            {
                "passed": True,
                "percentage": 100,
                "verified": 12,
                "total": 12,
                "blocked": 0,
                "remaining": 0,
            },
        )
        self.assertEqual(report["internal_deployment"]["verified"], 29)
        self.assertEqual(report["internal_deployment"]["total"], 29)
        self.assertEqual(report["internal_deployment"]["percentage"], 100)
        self.assertTrue(report["internal_deployment"]["passed"])
        self.assertEqual(report["complete_public_launch"]["verified"], 29)
        self.assertEqual(report["complete_public_launch"]["total"], 38)
        self.assertEqual(report["complete_public_launch"]["percentage"], 76)
        self.assertFalse(report["complete_public_launch"]["passed"])

    def test_current_schema_is_verified_and_exact_risks_remain_accepted(self):
        report = gate.build_report()
        actionable = {item["id"]: item for item in report["actionable"]}

        self.assertEqual(report["blocked"], [])
        self.assertNotIn("immutable_release_candidate", actionable)
        self.assertNotIn("production_readonly_preflight", actionable)
        self.assertIsNone(report["next_safe_task"])
        self.assertNotIn("production_schema_roles", actionable)
        self.assertNotIn("managed_secret_distribution", actionable)
        self.assertNotIn("private_storage_runtime", actionable)
        self.assertNotIn("api_c_current_release", actionable)
        self.assertNotIn("api_f_current_release", actionable)
        self.assertNotIn("admin_current_release", actionable)
        self.assertNotIn("durable_ai_workers", actionable)
        self.assertNotIn("trends_suspended_runtime", actionable)
        self.assertNotIn("tracking_suspended_runtime", actionable)
        self.assertNotIn("payment_internal_runtime", actionable)
        self.assertNotIn("monitoring_alerting", actionable)
        durable_ai = next(
            control
            for control in self.manifest["layers"][1]["controls"]
            if control["id"] == "durable_ai_workers"
        )
        self.assertEqual(durable_ai["status"], "verified")
        self.assertNotIn("blocker", durable_ai)
        self.assertNotIn("next_task", durable_ai)
        self.assertTrue(
            durable_ai["latest_reconciliation"]
            ["production_terminal_acceptance"]
            ["readiness_credit_added"]
        )
        trends = next(
            control
            for control in self.manifest["layers"][1]["controls"]
            if control["id"] == "trends_suspended_runtime"
        )
        self.assertEqual(trends["status"], "verified")
        self.assertNotIn("blocker", trends)
        self.assertNotIn("next_task", trends)
        trends_acceptance = trends["production_acceptance"]
        self.assertEqual(trends_acceptance["status"], "PASS")
        self.assertFalse(trends_acceptance["unit_active"])
        self.assertFalse(trends_acceptance["unit_enabled"])
        self.assertEqual(trends_acceptance["unit_start_count"], 0)
        self.assertEqual(trends_acceptance["application_container_start_count"], 0)
        self.assertEqual(trends_acceptance["provider_call_count"], 0)
        self.assertTrue(trends_acceptance["readiness_credit_added"])
        tracking = next(
            control
            for control in self.manifest["layers"][1]["controls"]
            if control["id"] == "tracking_suspended_runtime"
        )
        self.assertEqual(tracking["status"], "verified")
        self.assertNotIn("blocker", tracking)
        self.assertNotIn("next_task", tracking)
        tracking_acceptance = tracking["production_acceptance"]
        self.assertEqual(tracking_acceptance["status"], "PASS")
        self.assertFalse(tracking_acceptance["unit_active"])
        self.assertFalse(tracking_acceptance["unit_enabled"])
        self.assertEqual(tracking_acceptance["unit_start_count"], 0)
        self.assertEqual(tracking_acceptance["application_container_start_count"], 0)
        self.assertEqual(tracking_acceptance["provider_call_count"], 0)
        self.assertTrue(tracking_acceptance["readiness_credit_added"])
        payment = next(
            control
            for control in self.manifest["layers"][1]["controls"]
            if control["id"] == "payment_internal_runtime"
        )
        self.assertEqual(payment["status"], "verified")
        self.assertNotIn("blocker", payment)
        self.assertNotIn("next_task", payment)
        payment_acceptance = payment["production_acceptance"]
        self.assertEqual(payment_acceptance["status"], "PASS")
        self.assertFalse(payment_acceptance["unit_active"])
        self.assertFalse(payment_acceptance["unit_enabled"])
        self.assertEqual(payment_acceptance["formal_unit_start_count"], 0)
        self.assertEqual(
            payment_acceptance["formal_application_container_start_count"], 0
        )
        self.assertEqual(payment_acceptance["provider_call_count"], 0)
        self.assertEqual(payment_acceptance["production_database_write_count"], 0)
        self.assertTrue(payment_acceptance["readiness_credit_added"])
        monitoring = next(
            control
            for control in self.manifest["layers"][1]["controls"]
            if control["id"] == "monitoring_alerting"
        )
        self.assertEqual(monitoring["status"], "verified")
        self.assertNotIn("blocker", monitoring)
        self.assertNotIn("next_task", monitoring)
        monitoring_acceptance = monitoring["production_acceptance"]
        self.assertEqual(monitoring_acceptance["status"], "PASS")
        self.assertEqual(monitoring_acceptance["final_runtime_role_count"], 9)
        self.assertEqual(monitoring_acceptance["final_unit_log_bound_count"], 9)
        self.assertEqual(monitoring_acceptance["alert_rule_count"], 9)
        self.assertEqual(
            len(set(monitoring_acceptance["alert_rule_ids"])),
            9,
        )
        self.assertTrue(monitoring_acceptance["all_alert_rules_enabled"])
        self.assertTrue(monitoring_acceptance["all_alert_rule_contracts_exact"])
        self.assertEqual(
            monitoring_acceptance["registered_process_target_count"],
            9,
        )
        self.assertTrue(
            all(
                item["all_required_targets_present"]
                for item in monitoring_acceptance["process_inventory"]
            )
        )
        notification = monitoring_acceptance["notification_test"]
        self.assertEqual(notification["status"], "PASS")
        self.assertEqual(notification["sent_log_match_count"], 1)
        self.assertEqual(notification["send_status_zero_count"], 1)
        self.assertEqual(notification["send_result_list_count"], 1)
        self.assertTrue(notification["actual_notification_delivery_accepted"])
        self.assertEqual(notification["temporary_rule_residue_count"], 0)
        self.assertEqual(
            monitoring_acceptance["production_database_write_count"],
            0,
        )
        self.assertEqual(monitoring_acceptance["paid_resource_create_count"], 0)
        self.assertTrue(monitoring_acceptance["readiness_credit_added"])
        admin = next(
            control
            for control in self.manifest["layers"][1]["controls"]
            if control["id"] == "admin_current_release"
        )
        self.assertEqual(admin["status"], "verified")
        self.assertNotIn("blocker", admin)
        self.assertNotIn("next_task", admin)
        self.assertIn(
            {
                "kind": "path",
                "ref": (
                    "deploy/production/evidence/"
                    "production-admin-current-release-verified-20260805.json"
                ),
            },
            admin["evidence"],
        )
        self.assertIn(
            {
                "kind": "path",
                "ref": "tools/verify_admin_current_release_evidence.py",
            },
            admin["evidence"],
        )
    def _assert_historical_admin_evidence_catalog(self, admin):
        """Archived non-credit evidence catalog; intentionally not a test."""
        self.assertEqual(
            admin["evidence"],
            [
                {
                    "kind": "git",
                    "ref": "5335bdaed933b1f999b5f819c047ec50c11821ae",
                },
                {
                    "kind": "git",
                    "ref": "e7039a3fe73b539325593cf1ba78dcd4a9949910",
                },
                {
                    "kind": "git",
                    "ref": "8434da99b70b3623d619d0fafdac893a97e7b0e3",
                },
                {
                    "kind": "git",
                    "ref": "10a05ebc5857ece9307af207753b36845b47d704",
                },
                {
                    "kind": "git",
                    "ref": "7b65c480604ab3aa3381d81e9692d2ed94f7c23c",
                },
                {
                    "kind": "git",
                    "ref": "d5aa7e537590ed138d254b9909a1ac105ee321ce",
                },
                {
                    "kind": "path",
                    "ref": (
                        "security/vex/"
                        "5335bda-admin-github-native-release-evidence.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "security/vex/"
                        "5335bda-admin-github-native-release.vex.cdx.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "security/vex/"
                        "5335bda-admin-github-native-release-review.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": "tools/verify_5335_admin_native_release_vex.py",
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/evidence/"
                        "production-admin-native-source-candidate-"
                        "verified-20260730.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_private_publication_attempt_evidence.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/evidence/"
                        "production-admin-private-publication-attempt-"
                        "blocked-clean-20260731.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_export_plan.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        ".github/workflows/"
                        "admin-dependency-cache-export.yml"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "scripts/ci/"
                        "export_admin_dependency_cache.sh"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "scripts/ci/"
                        "import_admin_dependency_cache.sh"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_bundle.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "scripts/ci/"
                        "download_admin_dependency_cache_artifact.sh"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_provider_download.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_provider_download.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/plans/"
                        "admin-dependency-cache-export-request-v2.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/evidence/"
                        "admin-dependency-cache-v2-attempt1-failed-20260731.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_v2_failure_evidence.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_v2_failure_evidence.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/plans/"
                        "admin-dependency-cache-export-request-v3.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        ".github/workflows/"
                        "admin-dependency-cache-export-v3.yml"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_export_plan_v3.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_export_plan_v3.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_bundle_v3.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_bundle_verifier_v3.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/fixtures/"
                        "admin_dependency_cache_buildkit_v0.31.2_"
                        "platform_projection.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_transient_state_v3.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_transient_state_v3.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "scripts/ci/"
                        "cleanup_admin_dependency_cache_v3.sh"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_cleanup_v3.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/evidence/"
                        "admin-dependency-cache-v3-attempt1-failed-20260731.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_v3_failure_evidence.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_v3_failure_evidence.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/plans/"
                        "admin-dependency-cache-export-request-v4.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        ".github/workflows/"
                        "admin-dependency-cache-export-v4.yml"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_export_plan_v4.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_export_plan_v4.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_transient_state_v4.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_transient_state_v4.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "scripts/ci/"
                        "cleanup_admin_dependency_cache_v4.sh"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_cleanup_v4.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/evidence/"
                        "admin-dependency-cache-v4-attempt1-failed-20260731.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_v4_failure_evidence.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_v4_failure_evidence.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/plans/"
                        "admin-dependency-cache-export-request-v5.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        ".github/workflows/"
                        "admin-dependency-cache-export-v5.yml"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_export_plan_v5.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_export_plan_v5.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_transient_state_v5.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_transient_state_v5.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": "scripts/ci/cleanup_admin_dependency_cache_v5.sh",
                },
                {
                    "kind": "path",
                    "ref": "tests/test_admin_dependency_cache_cleanup_v5.py",
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_bundle_verifier_v5.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/fixtures/"
                        "admin_dependency_cache_buildx_v0.35.0_"
                        "provenance_gha_disabled_projection.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/fixtures/"
                        "admin_dependency_cache_buildx_v0.35.0_"
                        "rawjson_schema_projection.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/evidence/"
                        "admin-dependency-cache-v5-attempt1-failed-20260731.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_v5_failure_evidence.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_v5_failure_evidence.py"
                    ),
                },
                {
                    "kind": "git",
                    "ref": "ff6e2d6e3849541f1d204769ea2052f850e783cd",
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/plans/"
                        "admin-dependency-cache-export-request-v6.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        ".github/workflows/"
                        "admin-dependency-cache-export-v6.yml"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_export_plan_v6.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_export_plan_v6.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_bundle_v6.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_bundle_verifier_v6.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/fixtures/"
                        "admin_dependency_cache_buildkit_v0.31.2_"
                        "solvestatus_structural_projection.json"
                    ),
                },
                {
                    "kind": "git",
                    "ref": "4455af46c775eb68cff3a7356324bae99263013b",
                },
                {
                    "kind": "git",
                    "ref": "5770f00d7e5756302d34b5f9159066dc3fd5d36d",
                },
                {
                    "kind": "git",
                    "ref": "65b79e14baf4ec9a2ea65442226de7c12f64f611",
                },
                {
                    "kind": "path",
                    "ref": (
                        ".github/release-requests/"
                        "admin-5335bda-dependency-cache-v6.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/evidence/"
                        "admin-dependency-cache-v6-attempt1-failed-20260731.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_v6_failure_evidence.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_v6_failure_evidence.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/plans/"
                        "admin-dependency-cache-export-request-v7.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        ".github/workflows/"
                        "admin-dependency-cache-export-v7.yml"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_export_plan_v7.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_export_plan_v7.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_bundle_v7.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_bundle_verifier_v7.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/fixtures/"
                        "admin_dependency_cache_buildkit_v0.31.2_"
                        "incremental_vertex_projection.json"
                    ),
                },
                {
                    "kind": "git",
                    "ref": "27dcccf1736c40a832a3ca4875aa9ff7bdbe72d5",
                },
                {
                    "kind": "git",
                    "ref": "71692d5f25f6a2d3f248cc62a568f4a2bd5af2cd",
                },
                {
                    "kind": "git",
                    "ref": "4494f50bf9a18422cef6252792bb9c6bbeaf1135",
                },
                {
                    "kind": "git",
                    "ref": "6102ac231b68e3bc6b69db817fd834da0e37e1b9",
                },
                {
                    "kind": "path",
                    "ref": (
                        ".github/release-requests/"
                        "admin-5335bda-dependency-cache-v7.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/evidence/"
                        "admin-dependency-cache-v7-attempt1-failed-20260731.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_v7_failure_evidence.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_v7_failure_evidence.py"
                    ),
                },
                {
                    "kind": "git",
                    "ref": "3714cc2feec65d3059325d0d869ad007083b0276",
                },
                {
                    "kind": "git",
                    "ref": "3381c2fdbcb32480bb364a400250f8d24de74c84",
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/plans/"
                        "admin-dependency-cache-export-request-v8.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        ".github/workflows/"
                        "admin-dependency-cache-export-v8.yml"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_export_plan_v8.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_export_plan_v8.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_bundle_v8.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_bundle_verifier_v8.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/fixtures/"
                        "admin_dependency_cache_buildkit_v0.31.2_"
                        "empty_source_location_projection.json"
                    ),
                },
                {
                    "kind": "git",
                    "ref": "cf253f9b42b096f45405ac55fe546c281a2a748d",
                },
                {
                    "kind": "git",
                    "ref": "354bec3b2d36bfaabc5c3307d49f5dc66255cbbf",
                },
                {
                    "kind": "path",
                    "ref": (
                        ".github/release-requests/"
                        "admin-5335bda-dependency-cache-v8.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/evidence/"
                        "admin-dependency-cache-v8-attempt1-failed-20260731.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_v8_failure_evidence.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_v8_failure_evidence.py"
                    ),
                },
                {
                    "kind": "git",
                    "ref": "6961876b35aba5e52fc7e44a59a4881469d0064f",
                },
                {
                    "kind": "git",
                    "ref": "72f36354471e2d56ea77760d50417bf09b5cd9e1",
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/plans/"
                        "admin-dependency-cache-export-request-v9.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        ".github/workflows/"
                        "admin-dependency-cache-export-v9.yml"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_export_plan_v9.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_export_plan_v9.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_bundle_v9.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_bundle_verifier_v9.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/fixtures/"
                        "admin_dependency_cache_buildkit_v0.31.2_"
                        "vertex_input_omission_projection.json"
                    ),
                },
                {
                    "kind": "git",
                    "ref": "590ffc863d7475b5637e644461c7ac7e8612052b",
                },
                {
                    "kind": "git",
                    "ref": "c2aebc9bdae9cc26c6c29d994bf55b547349e231",
                },
                {
                    "kind": "git",
                    "ref": "fbe629daad669191d4ea9903ffb488c98055f000",
                },
                {
                    "kind": "git",
                    "ref": "0e35e7dca22064402f8a7b569c6b966e4c6ec1a3",
                },
                {
                    "kind": "path",
                    "ref": (
                        ".github/release-requests/"
                        "admin-5335bda-dependency-cache-v9.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/evidence/"
                        "admin-dependency-cache-v9-attempt1-failed-20260731.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_v9_failure_evidence.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_v9_failure_evidence.py"
                    ),
                },
                {
                    "kind": "git",
                    "ref": "512638647c5851aa3258cd472da42894110465af",
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/plans/"
                        "admin-dependency-cache-export-request-v10.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        ".github/workflows/"
                        "admin-dependency-cache-export-v10.yml"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_export_plan_v10.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_export_plan_v10.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_bundle_v10.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_bundle_verifier_v10.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/fixtures/"
                        "admin_dependency_cache_buildkit_v0.31.2_"
                        "cache_observer_projection.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": "scripts/ci/import_admin_dependency_cache_v10.sh",
                },
                {
                    "kind": "git",
                    "ref": "9199fb598790a03302c21dd3968c63b58d03f2c2",
                },
                {
                    "kind": "git",
                    "ref": "b02c4a18d6b77024f17d0e56c1d081a578854b1f",
                },
                {
                    "kind": "git",
                    "ref": "ea2a3b489e74b21a88ea21ecd243cd6a433c7fac",
                },
                {
                    "kind": "git",
                    "ref": "8c8567b99541f1f260d988754daa88f97f00f68e",
                },
                {
                    "kind": "git",
                    "ref": "b01c65d507cf087bea0d80038eafdb08a8e23bf1",
                },
                {
                    "kind": "path",
                    "ref": (
                        ".github/release-requests/"
                        "admin-5335bda-dependency-cache-v10.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/evidence/"
                        "admin-dependency-cache-v10-attempt1-failed-20260731.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_v10_failure_evidence.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_v10_failure_evidence.py"
                    ),
                },
                {
                    "kind": "git",
                    "ref": "458f2482f9a3267bb9050a274f33ae21fc546ed7",
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/plans/"
                        "admin-dependency-cache-export-request-v11.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        ".github/workflows/"
                        "admin-dependency-cache-export-v11.yml"
                    ),
                },
                {
                    "kind": "path",
                    "ref": "scripts/ci/export_admin_dependency_cache_v11.sh",
                },
                {
                    "kind": "path",
                    "ref": "scripts/ci/import_admin_dependency_cache_v11.sh",
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/fixtures/"
                        "admin_dependency_cache_buildkit_v0.31.2_"
                        "export_anchor_observer_projection.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": "tools/verify_admin_dependency_cache_bundle_v11.py",
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_bundle_verifier_v11.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_export_plan_v11.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_export_plan_v11.py"
                    ),
                },
                {
                    "kind": "git",
                    "ref": "c0d049b56aa6efaff7133ac44a9fef7f010cd097",
                },
                {
                    "kind": "git",
                    "ref": "606c474d347b4dad4e08e6f9fd038a82bdae5315",
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/plans/"
                        "admin-dependency-cache-export-request-v12.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        ".github/workflows/"
                        "admin-dependency-cache-export-v12.yml"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_export_plan_v12.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_export_plan_v12.py"
                    ),
                },
                {
                    "kind": "git",
                    "ref": "8b1f197141b9c84b4ffa812080ecabd6af1bbbce",
                },
                {
                    "kind": "git",
                    "ref": "328c07ed173754585c635ebb7b1d8c2587cadf57",
                },
                {
                    "kind": "git",
                    "ref": "2883d3e216fd64a70b94b1ba27b0838dca280f61",
                },
                {
                    "kind": "path",
                    "ref": (
                        ".github/release-requests/"
                        "admin-5335bda-dependency-cache-v12.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/evidence/"
                        "admin-dependency-cache-v12-attempt1-failed-"
                        "20260801.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_v12_failure_evidence.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_v12_failure_evidence.py"
                    ),
                },
                {
                    "kind": "git",
                    "ref": "efef71395fce4319ef11c8065b45db482ba12669",
                },
                {
                    "kind": "git",
                    "ref": "37c3b3fdc24ad90ff6135a7f1e254f92062470b3",
                },
                {
                    "kind": "git",
                    "ref": "81730a511acb553c9a1e29af834924f71650dc9a",
                },
                {
                    "kind": "git",
                    "ref": "ae7ce751d842b2880cdb2d31213a983bcb1f7484",
                },
                {
                    "kind": "git",
                    "ref": "4df6a77e39f2488b852414bb0649babbb37eb98a",
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/plans/"
                        "admin-dependency-cache-export-request-v13.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        ".github/workflows/"
                        "admin-dependency-cache-export-v13.yml"
                    ),
                },
                {
                    "kind": "path",
                    "ref": "scripts/ci/import_admin_dependency_cache_v13.sh",
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/fixtures/admin_dependency_cache_buildkit_v0.31.2_"
                        "cache_record_identity_domains_projection.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": "tools/verify_admin_dependency_cache_bundle_v13.py",
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_bundle_verifier_v13.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": "tools/verify_admin_dependency_cache_export_plan_v13.py",
                },
                {
                    "kind": "path",
                    "ref": "tests/test_admin_dependency_cache_export_plan_v13.py",
                },
                {
                    "kind": "git",
                    "ref": "585edfcb2789b112bbf559bf1d6d75e1843dd54c",
                },
                {
                    "kind": "git",
                    "ref": "e18d24a204c33127a95fe3035b7fce43bdb0b4f8",
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/plans/"
                        "admin-dependency-cache-export-request-v14.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        ".github/workflows/"
                        "admin-dependency-cache-export-v14.yml"
                    ),
                },
                {
                    "kind": "path",
                    "ref": "tools/verify_admin_dependency_cache_export_plan_v14.py",
                },
                {
                    "kind": "path",
                    "ref": "tests/test_admin_dependency_cache_export_plan_v14.py",
                },
                {
                    "kind": "git",
                    "ref": "1ca885d61c48f3cfdb4e99eeedc6fb9f17238bb4",
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/plans/"
                        "admin-dependency-cache-export-request-v15.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        ".github/workflows/"
                        "admin-dependency-cache-export-v15.yml"
                    ),
                },
                {
                    "kind": "path",
                    "ref": "tools/verify_admin_dependency_cache_export_plan_v15.py",
                },
                {
                    "kind": "path",
                    "ref": "tests/test_admin_dependency_cache_export_plan_v15.py",
                },
                {
                    "kind": "git",
                    "ref": "90f9606d6eb860572814cc3ccc0731fb9d366a5a",
                },
                {
                    "kind": "git",
                    "ref": "788a2b48d3dc04bea0f7c26fe7207887131436a7",
                },
                {
                    "kind": "git",
                    "ref": "c61ba14ab77f98dbc63697dc2b3cbe26afdf9df1",
                },
                {
                    "kind": "path",
                    "ref": (
                        ".github/release-requests/"
                        "admin-5335bda-dependency-cache-v15.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/evidence/"
                        "admin-dependency-cache-v15-attempt1-failed-"
                        "20260802.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_v15_failure_evidence.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_v15_failure_evidence.py"
                    ),
                },
                {
                    "kind": "git",
                    "ref": "46595fef4916ca2881dd38c0a14ee630bba79c32",
                },
                {
                    "kind": "git",
                    "ref": "a94ee2b2feb81eafbcb523be2c95da4ee952cbc4",
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/plans/"
                        "admin-dependency-cache-export-request-v16.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        ".github/workflows/"
                        "admin-dependency-cache-export-v16.yml"
                    ),
                },
                {
                    "kind": "path",
                    "ref": "scripts/ci/export_admin_dependency_cache_v16.sh",
                },
                {
                    "kind": "path",
                    "ref": "scripts/ci/import_admin_dependency_cache_v16.sh",
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/fixtures/"
                        "admin_dependency_cache_buildkit_v0.31.2_"
                        "git_main_context_identity_projection.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": "tools/verify_admin_dependency_cache_bundle_v16.py",
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_bundle_verifier_v16.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": "tools/verify_admin_dependency_cache_export_plan_v16.py",
                },
                {
                    "kind": "path",
                    "ref": "tests/test_admin_dependency_cache_export_plan_v16.py",
                },
                {
                    "kind": "git",
                    "ref": "b6f642e68c21341c90bb3c66f810945ada4e084a",
                },
                {
                    "kind": "git",
                    "ref": "095529e03f735494a98ce2302a6e1be570291d8c",
                },
                {
                    "kind": "git",
                    "ref": "fd1444d0a62549b3c353cbc1188e6ba25a77e96e",
                },
                {
                    "kind": "path",
                    "ref": (
                        ".github/release-requests/"
                        "admin-5335bda-dependency-cache-v16.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/evidence/"
                        "admin-dependency-cache-v16-attempt1-failed-"
                        "20260802.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_v16_failure_evidence.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_v16_failure_evidence.py"
                    ),
                },
                {
                    "kind": "git",
                    "ref": "4c2df3b19b4f5493adba78eed89c3a015d76972d",
                },
                {
                    "kind": "git",
                    "ref": "751da973dd7136d792adfafa11e50f5e5e0bd689",
                },
                {
                    "kind": "path",
                    "ref": (
                        ".github/workflows/"
                        "admin-dependency-cache-export-v17.yml"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/plans/"
                        "admin-dependency-cache-export-request-v17.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": "scripts/ci/export_admin_dependency_cache_v17.sh",
                },
                {
                    "kind": "path",
                    "ref": "scripts/ci/import_admin_dependency_cache_v17.sh",
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/fixtures/"
                        "admin_dependency_cache_v17_frontend_lifecycle_and_"
                        "localstate_projection.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_transient_state_v17.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_transient_state_v17.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": "tools/verify_admin_dependency_cache_bundle_v17.py",
                },
                {
                    "kind": "path",
                    "ref": (
                        "tests/"
                        "test_admin_dependency_cache_bundle_verifier_v17.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": (
                        "tools/"
                        "verify_admin_dependency_cache_export_plan_v17.py"
                    ),
                },
                {
                    "kind": "path",
                    "ref": "tests/test_admin_dependency_cache_export_plan_v17.py",
                },
                {
                    "kind": "git",
                    "ref": "7ee9a15425c38e8f0d5382cba488bd4a6ce92d6e",
                },
                {
                    "kind": "git",
                    "ref": "d930990d6a4393c565927306d7ae6b5db1ec4e88",
                },
                {
                    "kind": "git",
                    "ref": "6b8fba3dd8eb5b387b890f7b486a4cfa5e373f36",
                },
                {
                    "kind": "path",
                    "ref": (
                        ".github/release-requests/"
                        "admin-5335bda-dependency-cache-v17.json"
                    ),
                },
                {
                    "kind": "path",
                    "ref": "deploy/production/admin_item20_stage_a_v2.sh",
                },
                {
                    "kind": "path",
                    "ref": "tests/test_admin_item20_stage_a_v2.py",
                },
                {
                    "kind": "path",
                    "ref": "deploy/production/admin_item20_stage_a_v3.sh",
                },
                {
                    "kind": "path",
                    "ref": "tests/test_admin_item20_stage_a_v3.py",
                },
                {
                    "kind": "git",
                    "ref": "6951a003097599f8c82fb46cbdc84b316238ff05",
                },
                {
                    "kind": "path",
                    "ref": "deploy/production/admin_item20_stage_a_v4.sh",
                },
                {
                    "kind": "path",
                    "ref": "tests/test_admin_item20_stage_a_v4.py",
                },
                {
                    "kind": "path",
                    "ref": "deploy/production/admin_item20_stage_a_v5.sh",
                },
                {
                    "kind": "path",
                    "ref": "tests/test_admin_item20_stage_a_v5.py",
                },
                {
                    "kind": "path",
                    "ref": (
                        "deploy/production/"
                        "admin_item20_stage_a_public_ecr.sh"
                    ),
                },
                {
                    "kind": "path",
                    "ref": "tests/test_admin_item20_stage_a_public_ecr.py",
                },
            ],
        )
        self.assertNotIn(
            {
                "kind": "path",
                "ref": (
                    ".github/release-requests/"
                    "admin-5335bda-dependency-cache-v11.json"
                ),
            },
            admin["evidence"],
        )
        self.assertIn(
            {
                "kind": "path",
                "ref": (
                    ".github/release-requests/"
                    "admin-5335bda-dependency-cache-v12.json"
                ),
            },
            admin["evidence"],
        )
        self.assertIn("V11 must never activate", admin["blocker"])
        self.assertIn("exactly two", admin["blocker"])
        self.assertIn("30572921215", admin["blocker"])
        self.assertIn("30591103183", admin["blocker"])
        self.assertIn("91033410635", admin["blocker"])
        self.assertIn("workflow-path run count remains zero", admin["blocker"])
        self.assertIn("30696298423", admin["blocker"])
        self.assertIn("91359681758", admin["blocker"])
        self.assertIn("zero provider artifacts", admin["blocker"])
        self.assertIn("V12 may never be rerun", admin["blocker"])
        self.assertIn("ae7ce751d842b2880cdb2d31213a983bcb1f7484", admin["blocker"])
        self.assertIn("30698918645", admin["blocker"])
        self.assertIn("91366363365", admin["blocker"])
        self.assertIn("30698919672", admin["blocker"])
        self.assertIn("91366366249", admin["blocker"])
        self.assertIn("4df6a77e39f2488b852414bb0649babbb37eb98a", admin["blocker"])
        self.assertIn("30701666137", admin["blocker"])
        self.assertIn("91373623999", admin["blocker"])
        self.assertIn("30701667259", admin["blocker"])
        self.assertIn("91373626894", admin["blocker"])
        self.assertIn("1655/1655", admin["blocker"])
        self.assertIn("6209.827s", admin["blocker"])
        self.assertIn("478/478", admin["blocker"])
        self.assertIn("CI-hermeticity failure", admin["blocker"])
        self.assertIn(
            "V13_INERT_CHECKPOINT_CI_HERMETICITY_FAILED_RECEIPT_EXACT",
            admin["blocker"],
        )
        self.assertIn("V13 must never activate", admin["blocker"])
        self.assertIn("append-only V14 checkpoint", admin["blocker"])
        self.assertIn("585edfcb2789b112bbf559bf1d6d75e1843dd54c", admin["blocker"])
        self.assertIn("exact eleven-file direct child", admin["blocker"])
        self.assertIn("reuses the V13 data plane", admin["blocker"])
        self.assertIn("V13 workflow path zero", admin["blocker"])
        self.assertIn("V13 request ancestry zero", admin["blocker"])
        self.assertIn("V14 plan tests pass normal and optimized Python 12/12", admin["blocker"])
        self.assertIn("e18d24a204c33127a95fe3035b7fce43bdb0b4f8", admin["blocker"])
        self.assertIn("30706546764", admin["blocker"])
        self.assertIn("91386553347", admin["blocker"])
        self.assertIn("30706547955", admin["blocker"])
        self.assertIn("91386556528", admin["blocker"])
        self.assertIn("1657/1657", admin["blocker"])
        self.assertIn("133/133", admin["blocker"])
        self.assertIn("480/480", admin["blocker"])
        self.assertIn("synthetic pull-request context", admin["blocker"])
        self.assertIn(
            "V14_INERT_CHECKPOINT_PR_CONTEXT_FAILED_RECEIPT_EXACT",
            admin["blocker"],
        )
        self.assertIn("V14 must never activate", admin["blocker"])
        self.assertIn("1ca885d61c48f3cfdb4e99eeedc6fb9f17238bb4", admin["blocker"])
        self.assertIn("90f9606d6eb860572814cc3ccc0731fb9d366a5a", admin["blocker"])
        self.assertIn("30709036776", admin["blocker"])
        self.assertIn("91393091573", admin["blocker"])
        self.assertIn("30709038582", admin["blocker"])
        self.assertIn("91393095974", admin["blocker"])
        self.assertIn("1682 tests", admin["blocker"])
        self.assertIn("788a2b48d3dc04bea0f7c26fe7207887131436a7", admin["blocker"])
        self.assertIn("c61ba14ab77f98dbc63697dc2b3cbe26afdf9df1", admin["blocker"])
        self.assertIn("30724578299", admin["blocker"])
        self.assertIn("91433793813", admin["blocker"])
        self.assertIn("30724579324", admin["blocker"])
        self.assertIn("91433796451", admin["blocker"])
        self.assertIn("30724578319", admin["blocker"])
        self.assertIn("91433793914", admin["blocker"])
        self.assertIn(
            "SAME_SOURCE_COPY_PIP_DIGESTS_CACHED identity chain was not proven",
            admin["blocker"],
        )
        self.assertIn("487/487/487", admin["blocker"])
        self.assertIn("V15 may never be rerun", admin["blocker"])
        self.assertIn("46595fef4916ca2881dd38c0a14ee630bba79c32", admin["blocker"])
        self.assertIn("30727588135", admin["blocker"])
        self.assertIn("91442042559", admin["blocker"])
        self.assertIn("30727589274", admin["blocker"])
        self.assertIn("91442045947", admin["blocker"])
        self.assertIn("1692 tests", admin["blocker"])
        self.assertIn("134/134", admin["blocker"])
        self.assertIn("489/489/489", admin["blocker"])
        self.assertIn("a94ee2b2feb81eafbcb523be2c95da4ee952cbc4", admin["blocker"])
        self.assertIn(
            "external-cache-removed same-consumer-builder replay",
            admin["blocker"],
        )
        self.assertIn("b6f642e68c21341c90bb3c66f810945ada4e084a", admin["blocker"])
        self.assertIn("095529e03f735494a98ce2302a6e1be570291d8c", admin["blocker"])
        self.assertIn("fd1444d0a62549b3c353cbc1188e6ba25a77e96e", admin["blocker"])
        self.assertIn("exact 16/4/1", admin["blocker"])
        self.assertIn("30739167685", admin["blocker"])
        self.assertIn("91473336783", admin["blocker"])
        self.assertIn("30739168799", admin["blocker"])
        self.assertIn("91473339876", admin["blocker"])
        self.assertIn("30739167701", admin["blocker"])
        self.assertIn("91473336858", admin["blocker"])
        self.assertIn("producer Git SourceOp", admin["blocker"])
        self.assertIn("UNKNOWN_NOT_REACHED", admin["blocker"])
        self.assertIn("cleanup_effective is true", admin["blocker"])
        self.assertIn("overall_pass is false", admin["blocker"])
        self.assertIn("498/498/498", admin["blocker"])
        self.assertIn("4c2df3b19b4f5493adba78eed89c3a015d76972d", admin["blocker"])
        self.assertIn("30741594513", admin["blocker"])
        self.assertIn("91479900314", admin["blocker"])
        self.assertIn("30741595902", admin["blocker"])
        self.assertIn("91479904223", admin["blocker"])
        self.assertIn("1725 tests", admin["blocker"])
        self.assertIn("136/136", admin["blocker"])
        self.assertIn("500/500/500", admin["blocker"])
        self.assertIn("Exact-four Secret-free terminal receipt", admin["blocker"])
        self.assertIn("V16 may never be rerun", admin["blocker"])
        self.assertIn("19/29 / 19/38", admin["blocker"])
        self.assertIn("751da973dd7136d792adfafa11e50f5e5e0bd689", admin["blocker"])
        self.assertIn("30742513491", admin["blocker"])
        self.assertIn("91482331187", admin["blocker"])
        self.assertIn("30742515068", admin["blocker"])
        self.assertIn("91482335383", admin["blocker"])
        self.assertIn("502/502/502", admin["blocker"])
        self.assertIn("C17", admin["blocker"])
        self.assertIn(
            "7ee9a15425c38e8f0d5382cba488bd4a6ce92d6e",
            admin["blocker"],
        )
        self.assertIn(
            "d930990d6a4393c565927306d7ae6b5db1ec4e88",
            admin["blocker"],
        )
        self.assertIn("30747482874", admin["blocker"])
        self.assertIn("30747484142", admin["blocker"])
        self.assertIn(
            "6b8fba3dd8eb5b387b890f7b486a4cfa5e373f36",
            admin["blocker"],
        )
        self.assertIn("30748098684", admin["blocker"])
        self.assertIn("91497111488", admin["blocker"])
        self.assertIn("FROZEN_V9_EVIDENCE_INVALID", admin["blocker"])
        self.assertIn("FROZEN_V3_VALIDATION_FAILED", admin["blocker"])
        self.assertIn("artifact digest is absent", admin["blocker"])
        self.assertIn("fresh-builder import success proof is absent", admin["blocker"])
        self.assertIn("no R17 or V18 will be created", admin["blocker"])
        self.assertEqual(
            admin["v16_inert_checkpoint_receipt"],
            {
                "checkpoint_commit": (
                    "b6f642e68c21341c90bb3c66f810945ada4e084a"
                ),
                "parent_commit": (
                    "a94ee2b2feb81eafbcb523be2c95da4ee952cbc4"
                ),
                "exact_changed_path_count": 16,
                "all_changed_paths_mode": "100644",
                "push_ci": {
                    "run_id": 30731965367,
                    "job_id": 91453812740,
                    "run_attempt": 1,
                    "conclusion": "success",
                    "ambient_test_count": 1669,
                    "ambient_skipped_count": 28,
                    "ambient_duration_seconds": 1147.429,
                    "v13_scoped_test_count": 10,
                    "v13_isolated_test_count": 1,
                    "v14_detached_test_count": 12,
                    "v15_detached_test_count": 22,
                    "total_test_count": 1714,
                    "production_readiness_checks": "135/135",
                    "quality_gate_passed": True,
                    "docker_compose_passed": True,
                    "artifact_count": 0,
                },
                "pull_request_ci": {
                    "run_id": 30731966620,
                    "job_id": 91453816296,
                    "run_attempt": 1,
                    "conclusion": "success",
                    "ambient_test_count": 1669,
                    "ambient_skipped_count": 28,
                    "ambient_duration_seconds": 979.317,
                    "v13_scoped_test_count": 10,
                    "v13_isolated_test_count": 1,
                    "v14_detached_test_count": 12,
                    "v15_detached_test_count": 22,
                    "total_test_count": 1714,
                    "production_readiness_checks": "135/135",
                    "quality_gate_passed": True,
                    "docker_compose_passed": True,
                    "artifact_count": 0,
                },
                "fresh_actions_ledger": {
                    "page_count": 5,
                    "advertised_run_count": 493,
                    "fetched_run_count": 493,
                    "unique_run_count": 493,
                    "checkpoint_run_count": 2,
                    "v11_workflow_path_run_count": 0,
                    "v12_workflow_path_run_count": 1,
                    "v13_workflow_path_run_count": 0,
                    "v14_workflow_path_run_count": 0,
                    "v15_workflow_path_run_count": 1,
                    "v16_workflow_path_run_count": 0,
                    "v16_request_present": False,
                    "v16_request_addition_count": 0,
                    "v16_external_run_count": 0,
                },
                "readiness": {
                    "internal_verified_count": 19,
                    "internal_total_count": 29,
                    "public_verified_count": 19,
                    "public_total_count": 38,
                    "credit_added": False,
                },
                "execution_scope": {
                    "builder_create_count": 0,
                    "provider_artifact_count": 0,
                    "authenticated_download_count": 0,
                    "cross_provider_transfer_count": 0,
                    "acr_publication_count": 0,
                    "production_deployment_count": 0,
                    "production_database_write_count": 0,
                    "production_service_mutation_count": 0,
                    "public_traffic_mutation_count": 0,
                },
                "activation_authorized": False,
                "external_run_requires_new_explicit_authorization": True,
            },
        )
        v16_failure = admin["v16_attempt1_failure_checkpoint"]
        self.assertEqual(
            v16_failure["control_commit"],
            "fd1444d0a62549b3c353cbc1188e6ba25a77e96e",
        )
        self.assertEqual(
            v16_failure["direct_parent_commit"],
            "095529e03f735494a98ce2302a6e1be570291d8c",
        )
        self.assertEqual(v16_failure["request"]["addition_count"], 1)
        self.assertEqual(v16_failure["unique_run"]["run_id"], 30739167701)
        self.assertEqual(v16_failure["unique_run"]["job_id"], 91473336858)
        self.assertEqual(v16_failure["unique_run"]["run_attempt"], 1)
        self.assertEqual(v16_failure["unique_run"]["conclusion"], "failure")
        self.assertEqual(v16_failure["unique_run"]["artifact_count"], 0)
        self.assertEqual(
            v16_failure["control_head_ci"]["push"]["total_test_count"],
            1714,
        )
        self.assertEqual(
            v16_failure["control_head_ci"]["pull_request"][
                "total_test_count"
            ],
            1714,
        )
        self.assertEqual(
            v16_failure["fresh_actions_ledger"]["unique_run_count"],
            498,
        )
        self.assertEqual(
            v16_failure["failure"]["source_correlated_failure_code"],
            "NETWORK_VERTEX_LIFECYCLE_OUTSIDE_BUILD",
        )
        self.assertEqual(
            v16_failure["failure"]["portability"],
            "UNKNOWN_NOT_REACHED",
        )
        self.assertTrue(v16_failure["cleanup"]["cleanup_effective"])
        self.assertFalse(v16_failure["cleanup"]["overall_pass"])
        self.assertTrue(v16_failure["authorization"]["v16_one_shot_consumed"])
        self.assertTrue(v16_failure["authorization"]["v16_rerun_forbidden"])
        self.assertFalse(v16_failure["readiness"]["credit_added"])
        terminal = v16_failure["terminal_checkpoint_acceptance"]
        self.assertEqual(
            terminal["checkpoint_commit"],
            "4c2df3b19b4f5493adba78eed89c3a015d76972d",
        )
        self.assertEqual(
            terminal["parent_commit"],
            "fd1444d0a62549b3c353cbc1188e6ba25a77e96e",
        )
        self.assertEqual(terminal["exact_changed_path_count"], 11)
        self.assertEqual(terminal["all_changed_paths_mode"], "100644")
        self.assertEqual(
            terminal["effective_state"],
            "V16_TRIGGERED_ATTEMPT1_FAILED_TERMINAL_SUPERSESSION_EXACT",
        )
        self.assertEqual(terminal["push_ci"]["run_id"], 30741594513)
        self.assertEqual(terminal["push_ci"]["job_id"], 91479900314)
        self.assertEqual(terminal["push_ci"]["conclusion"], "success")
        self.assertEqual(terminal["push_ci"]["total_test_count"], 1725)
        self.assertEqual(
            terminal["push_ci"]["production_readiness_checks"],
            "136/136",
        )
        self.assertEqual(terminal["push_ci"]["artifact_count"], 0)
        self.assertEqual(
            terminal["pull_request_ci"]["run_id"],
            30741595902,
        )
        self.assertEqual(
            terminal["pull_request_ci"]["job_id"],
            91479904223,
        )
        self.assertEqual(
            terminal["pull_request_ci"]["conclusion"],
            "success",
        )
        self.assertEqual(
            terminal["pull_request_ci"]["total_test_count"],
            1725,
        )
        self.assertEqual(
            terminal["pull_request_ci"]["production_readiness_checks"],
            "136/136",
        )
        self.assertEqual(
            terminal["pull_request_ci"]["artifact_count"],
            0,
        )
        self.assertEqual(
            terminal["fresh_actions_ledger"]["page_count"],
            5,
        )
        self.assertEqual(
            terminal["fresh_actions_ledger"]["advertised_run_count"],
            500,
        )
        self.assertEqual(
            terminal["fresh_actions_ledger"]["fetched_run_count"],
            500,
        )
        self.assertEqual(
            terminal["fresh_actions_ledger"]["unique_run_count"],
            500,
        )
        self.assertEqual(
            terminal["fresh_actions_ledger"]["checkpoint_run_count"],
            2,
        )
        self.assertEqual(
            terminal["fresh_actions_ledger"]["v16_workflow_path_run_count"],
            1,
        )
        self.assertEqual(
            [
                terminal["fresh_actions_ledger"][
                    f"v{version}_workflow_path_run_count"
                ]
                for version in range(11, 16)
            ],
            [0, 1, 0, 0, 1],
        )
        self.assertEqual(
            terminal["fresh_actions_ledger"]["v16_rerun_or_duplicate_count"],
            0,
        )
        self.assertEqual(
            terminal["execution_scope"]["new_external_cache_run_count"],
            0,
        )
        self.assertFalse(terminal["readiness"]["credit_added"])
        receipt = admin["v16_terminal_receipt_acceptance"]
        self.assertEqual(
            receipt["receipt_commit"],
            "751da973dd7136d792adfafa11e50f5e5e0bd689",
        )
        self.assertEqual(
            receipt["parent_commit"],
            "4c2df3b19b4f5493adba78eed89c3a015d76972d",
        )
        self.assertEqual(receipt["exact_changed_path_count"], 4)
        self.assertEqual(receipt["all_changed_paths_mode"], "100644")
        self.assertEqual(receipt["push_ci"]["run_id"], 30742513491)
        self.assertEqual(receipt["push_ci"]["job_id"], 91482331187)
        self.assertEqual(receipt["push_ci"]["total_test_count"], 1725)
        self.assertEqual(
            receipt["push_ci"]["production_readiness_checks"],
            "136/136",
        )
        self.assertEqual(receipt["push_ci"]["artifact_count"], 0)
        self.assertEqual(receipt["pull_request_ci"]["run_id"], 30742515068)
        self.assertEqual(receipt["pull_request_ci"]["job_id"], 91482335383)
        self.assertEqual(receipt["pull_request_ci"]["total_test_count"], 1725)
        self.assertEqual(
            receipt["pull_request_ci"]["production_readiness_checks"],
            "136/136",
        )
        self.assertEqual(receipt["pull_request_ci"]["artifact_count"], 0)
        self.assertEqual(receipt["fresh_actions_ledger"]["page_count"], 6)
        self.assertEqual(
            [
                receipt["fresh_actions_ledger"][field]
                for field in (
                    "advertised_run_count",
                    "fetched_run_count",
                    "unique_run_count",
                )
            ],
            [502, 502, 502],
        )
        self.assertEqual(
            [
                receipt["fresh_actions_ledger"][
                    f"v{version}_workflow_path_run_count"
                ]
                for version in range(11, 18)
            ],
            [0, 1, 0, 0, 1, 1, 0],
        )
        self.assertFalse(receipt["fresh_actions_ledger"]["v17_request_present"])
        self.assertEqual(receipt["fresh_actions_ledger"]["v17_external_run_count"], 0)
        self.assertFalse(receipt["readiness"]["credit_added"])

        v17 = admin["v17_native_run_acceptance"]
        self.assertEqual(
            v17["result"],
            "FAILED_BEFORE_ARTIFACT_AND_FRESH_BUILDER_IMPORT",
        )
        self.assertEqual(
            v17["activation_head_ci"]["push"],
            {
                "run_id": 30748098675,
                "job_id": 91497111413,
                "run_attempt": 1,
                "conclusion": "success",
                "total_test_count": 1762,
                "ambient_skipped_count": 28,
                "production_readiness_checks": "137/137",
                "artifact_count": 0,
            },
        )
        self.assertEqual(
            v17["activation_head_ci"]["pull_request"],
            {
                "run_id": 30748100955,
                "job_id": 91497116914,
                "run_attempt": 1,
                "conclusion": "success",
                "total_test_count": 1762,
                "ambient_skipped_count": 28,
                "production_readiness_checks": "137/137",
                "artifact_count": 0,
            },
        )
        native = v17["native_evidence"]
        self.assertEqual(native["workflow_run_id"], 30748098684)
        self.assertEqual(native["workflow_job_id"], 91497111488)
        self.assertEqual(native["run_attempt"], 1)
        self.assertEqual(
            native["c17_sha"],
            "7ee9a15425c38e8f0d5382cba488bd4a6ce92d6e",
        )
        self.assertIsNone(native["artifact_digest"])
        self.assertEqual(native["artifact_count"], 0)
        self.assertFalse(native["fresh_builder_import_success"])
        self.assertTrue(
            v17["failure"]["buildkit_cache_export_command_completed"]
        )
        self.assertTrue(v17["failure"]["git_source_lifecycle_passed"])
        self.assertEqual(
            v17["failure"]["codes"],
            ["FROZEN_V9_EVIDENCE_INVALID", "FROZEN_V3_VALIDATION_FAILED"],
        )
        self.assertFalse(v17["failure"]["narrower_v3_subfield_known"])
        self.assertTrue(v17["cleanup"]["cleanup_effective"])
        self.assertFalse(v17["cleanup"]["overall_pass"])
        self.assertTrue(v17["authorization"]["one_shot_consumed"])
        self.assertTrue(v17["authorization"]["v17_rerun_forbidden"])
        self.assertTrue(v17["authorization"]["r17_forbidden"])
        self.assertTrue(v17["authorization"]["v18_forbidden"])
        self.assertFalse(v17["readiness"]["credit_added"])

        stage_a = admin["admin_stage_a_attempt1"]
        self.assertEqual(stage_a["result"], "FAILED_BEFORE_DOCKER_BUILD")
        self.assertEqual(
            stage_a["source_commit"],
            "5335bdaed933b1f999b5f819c047ec50c11821ae",
        )
        self.assertEqual(
            stage_a["cloud_assistant"]["command_invocation_id"],
            "t-sz06stvryp6jaww",
        )
        self.assertEqual(stage_a["cloud_assistant"]["exit_code"], 1)
        self.assertEqual(stage_a["failure"]["phase"], "model_materialization")
        self.assertIn(
            "future feature annotations is not defined",
            stage_a["failure"]["message"],
        )
        self.assertFalse(stage_a["failure"]["docker_build_reached"])
        self.assertFalse(stage_a["failure"]["acr_publication_reached"])
        self.assertFalse(stage_a["failure"]["production_deployment_reached"])
        self.assertTrue(stage_a["cleanup"]["target_images_absent"])
        self.assertTrue(stage_a["cleanup"]["task_root_absent"])
        self.assertEqual(stage_a["cleanup"]["running_container_count"], 0)
        self.assertEqual(stage_a["cleanup"]["builder_instance_status"], "stopped")
        self.assertEqual(stage_a["cleanup"]["builder_stop_mode"], "saving")
        self.assertEqual(stage_a["execution_scope"]["docker_build_count"], 0)
        self.assertEqual(stage_a["execution_scope"]["acr_publication_count"], 0)
        self.assertEqual(stage_a["authorization"]["automatic_retry_count"], 0)
        self.assertEqual(stage_a["authorization"]["rerun_count"], 0)
        self.assertFalse(
            stage_a["authorization"]["second_external_execution_authorized"]
        )
        self.assertFalse(stage_a["readiness"]["credit_added"])
        stage_a_v2 = admin["admin_stage_a_v2_preparation"]
        self.assertEqual(stage_a_v2["result"], "OFFLINE_VALIDATED_NOT_EXECUTED")
        self.assertEqual(
            stage_a_v2["executor"]["path"],
            "deploy/production/admin_item20_stage_a_v2.sh",
        )
        self.assertEqual(stage_a_v2["executor"]["byte_count"], 22254)
        self.assertEqual(
            stage_a_v2["executor"]["sha256"],
            "85e4e60e40e2a3f00c7fe9d1220ec37fdce2eb2772b8ce74ee92b0249755abd6",
        )
        self.assertEqual(stage_a_v2["executor"]["host_python_call_count"], 0)
        self.assertFalse(
            stage_a_v2["compatibility_changes"]["build_context_changed"]
        )
        self.assertFalse(
            stage_a_v2["compatibility_changes"]["dockerfile_changed"]
        )
        self.assertFalse(
            stage_a_v2["compatibility_changes"]["image_content_changed"]
        )
        self.assertTrue(
            stage_a_v2["offline_validation"]["positive_and_negative_fixture_passed"]
        )
        self.assertEqual(
            stage_a_v2["external_scope"]["cloud_assistant_execution_count"],
            0,
        )
        self.assertTrue(
            stage_a_v2["authorization"]["standing_cto_execution_authority_recorded"]
        )
        self.assertTrue(
            stage_a_v2["authorization"]["single_corrected_stage_a_execution_authorized"]
        )
        self.assertFalse(
            stage_a_v2["authorization"]["public_traffic_mutation_authorized"]
        )
        self.assertTrue(stage_a_v2["authorization"]["v17_rerun_forbidden"])
        self.assertTrue(stage_a_v2["authorization"]["r17_forbidden"])
        self.assertTrue(stage_a_v2["authorization"]["v18_forbidden"])
        self.assertFalse(stage_a_v2["readiness"]["credit_added"])

        attempt2 = admin["admin_stage_a_attempt2"]
        self.assertEqual(
            attempt2["result"],
            "FAILED_DURING_SOURCE_FETCH_BEFORE_DOCKER_BUILD",
        )
        self.assertEqual(
            attempt2["controller_commit"],
            "eea0504acf8b6253d066116a5278833dc681ff74",
        )
        self.assertEqual(attempt2["exact_head_ci"]["push"]["run_id"], 30777395304)
        self.assertEqual(
            attempt2["exact_head_ci"]["pull_request"]["run_id"],
            30777397136,
        )
        self.assertEqual(attempt2["exact_head_ci"]["push"]["artifact_count"], 0)
        self.assertEqual(
            attempt2["exact_head_ci"]["pull_request"]["artifact_count"],
            0,
        )
        self.assertEqual(attempt2["uploaded_script"]["status"], "success")
        self.assertEqual(attempt2["uploaded_script"]["scope"], "builder_only")
        self.assertTrue(attempt2["uploaded_script"]["sha256_verified"])
        self.assertEqual(attempt2["cloud_assistant"]["target_count"], 1)
        self.assertEqual(attempt2["cloud_assistant"]["execution_count"], 1)
        self.assertEqual(attempt2["cloud_assistant"]["exit_code"], 128)
        self.assertEqual(attempt2["failure"]["phase"], "source_fetch")
        self.assertEqual(attempt2["failure"]["curl_code"], 52)
        self.assertEqual(attempt2["failure"]["git_fetch_attempt_count"], 1)
        self.assertFalse(attempt2["failure"]["docker_build_reached"])
        self.assertFalse(attempt2["failure"]["acr_publication_reached"])
        self.assertTrue(attempt2["cleanup"]["target_images_absent"])
        self.assertTrue(attempt2["cleanup"]["task_root_absent"])
        self.assertEqual(attempt2["cleanup"]["running_container_count"], 0)
        self.assertEqual(attempt2["cleanup"]["builder_instance_status"], "stopped")
        self.assertEqual(attempt2["cleanup"]["builder_stop_mode"], "saving")
        self.assertEqual(attempt2["cleanup"]["builder_ordinary_stop_count"], 1)
        self.assertEqual(attempt2["cleanup"]["cleanup_only_builder_start_count"], 1)
        self.assertEqual(attempt2["cleanup"]["builder_saving_stop_count"], 1)
        self.assertFalse(
            attempt2["cleanup"]["script_execution_during_cleanup_restart"]
        )
        execution_scope = attempt2["execution_scope"]
        self.assertEqual(execution_scope["existing_builder_start_count"], 2)
        self.assertEqual(execution_scope["new_builder_create_count"], 0)
        self.assertEqual(execution_scope["cloud_assistant_upload_count"], 1)
        self.assertEqual(execution_scope["cloud_assistant_execution_count"], 1)
        self.assertEqual(execution_scope["stage_a_execution_count"], 1)
        self.assertEqual(execution_scope["source_fetch_attempt_count"], 1)
        self.assertEqual(execution_scope["automatic_retry_count"], 0)
        self.assertEqual(execution_scope["manual_rerun_count"], 0)
        self.assertEqual(execution_scope["second_stage_a_execution_count"], 0)
        self.assertEqual(execution_scope["trivy_database_download_count"], 0)
        self.assertEqual(execution_scope["docker_build_count"], 0)
        self.assertEqual(execution_scope["acr_login_count"], 0)
        self.assertEqual(execution_scope["acr_publication_count"], 0)
        self.assertEqual(execution_scope["production_deployment_count"], 0)
        self.assertEqual(
            execution_scope["production_database_connection_count"],
            0,
        )
        self.assertEqual(execution_scope["production_database_write_count"], 0)
        self.assertEqual(execution_scope["production_service_mutation_count"], 0)
        self.assertEqual(execution_scope["public_traffic_mutation_count"], 0)
        self.assertTrue(
            attempt2["authorization"]["single_corrected_stage_a_execution_consumed"]
        )
        self.assertFalse(
            attempt2["authorization"]["additional_stage_a_execution_authorized"]
        )
        self.assertFalse(attempt2["readiness"]["credit_added"])

        stage_a_v3 = admin["admin_stage_a_v3_preparation"]
        self.assertEqual(
            stage_a_v3["result"],
            "OFFLINE_VALIDATED_CI_SUCCESSOR_PENDING",
        )
        self.assertEqual(
            stage_a_v3["predecessor_failure_checkpoint"]["commit"],
            "df9fb2b5167285aedb6fd618d9b819e082fd067e",
        )
        for event in ("push_ci", "pull_request_ci"):
            ci = stage_a_v3["predecessor_failure_checkpoint"][event]
            self.assertEqual(ci["attempt"], 1)
            self.assertEqual(ci["conclusion"], "success")
            self.assertEqual(ci["total_test_count"], 1765)
            self.assertEqual(ci["production_readiness_checks"], "137/137")
            self.assertEqual(ci["artifact_count"], 0)
        self.assertEqual(
            stage_a_v3["predecessor_failure_checkpoint"]["push_ci"]["run_id"],
            30779761306,
        )
        self.assertEqual(
            stage_a_v3["predecessor_failure_checkpoint"]["pull_request_ci"][
                "run_id"
            ],
            30779762936,
        )
        self.assertEqual(
            stage_a_v3["predecessor_failure_checkpoint"]["rerun_count"],
            0,
        )
        ci_attempt = stage_a_v3["exact_head_ci_attempt"]
        self.assertEqual(
            ci_attempt["candidate_commit"],
            "682a18d94322eaae38bcd341e3fd2d741e73580d",
        )
        self.assertEqual(ci_attempt["push_ci"]["run_id"], 30780944104)
        self.assertEqual(ci_attempt["push_ci"]["job_id"], 91585301363)
        self.assertEqual(ci_attempt["push_ci"]["attempt"], 1)
        self.assertEqual(ci_attempt["push_ci"]["conclusion"], "failure")
        self.assertEqual(
            ci_attempt["push_ci"]["completed_ambient_test_count"],
            1704,
        )
        self.assertEqual(ci_attempt["push_ci"]["ambient_skipped_count"], 28)
        self.assertEqual(ci_attempt["push_ci"]["artifact_count"], 0)
        self.assertFalse(
            ci_attempt["push_ci"]["production_readiness_gate_reached"]
        )
        self.assertEqual(
            ci_attempt["pull_request_ci"]["run_id"],
            30780947418,
        )
        self.assertEqual(
            ci_attempt["pull_request_ci"]["job_id"],
            91585310629,
        )
        self.assertEqual(ci_attempt["pull_request_ci"]["attempt"], 1)
        self.assertEqual(ci_attempt["pull_request_ci"]["conclusion"], "success")
        self.assertEqual(ci_attempt["pull_request_ci"]["total_test_count"], 1770)
        self.assertEqual(
            ci_attempt["pull_request_ci"]["production_readiness_checks"],
            "137/137",
        )
        self.assertEqual(ci_attempt["pull_request_ci"]["artifact_count"], 0)
        self.assertEqual(ci_attempt["rerun_count"], 0)
        self.assertFalse(ci_attempt["external_execution_started"])
        self.assertEqual(
            stage_a_v3["executor"]["path"],
            "deploy/production/admin_item20_stage_a_v3.sh",
        )
        self.assertEqual(stage_a_v3["executor"]["byte_count"], 31609)
        self.assertEqual(
            stage_a_v3["executor"]["sha256"],
            "562cceb3f6b08da0b8e0723e4b636d664b6fc67cf622c6da3061601ee8b3f31a",
        )
        self.assertEqual(stage_a_v3["executor"]["host_python_call_count"], 0)
        transport = stage_a_v3["transport_recovery"]
        self.assertEqual(transport["retryable_exit_code"], 128)
        self.assertTrue(transport["retryable_stdout_must_be_empty"])
        self.assertEqual(
            transport["retryable_stderr_lines"],
            [
                "error: RPC failed; curl 52 Empty reply from server",
                "fatal: expected 'packfile'",
            ],
        )
        self.assertEqual(transport["stderr_normalization"], "terminal_cr_only")
        self.assertEqual(transport["maximum_fetch_attempts"], 2)
        self.assertEqual(transport["maximum_conditional_retry_count"], 1)
        self.assertEqual(transport["retry_delay_seconds"], 2)
        self.assertTrue(transport["clean_room_source_root_each_attempt"])
        self.assertEqual(transport["fetch_http_version"], "HTTP/1.1")
        self.assertEqual(transport["git_http_max_requests"], 1)
        self.assertFalse(transport["source_url_changed"])
        self.assertFalse(transport["mirror_proxy_or_credential_change"])
        data_plane = stage_a_v3["data_plane_immutability"]
        self.assertFalse(data_plane["build_context_changed"])
        self.assertFalse(data_plane["dockerfile_changed"])
        self.assertFalse(data_plane["image_content_changed"])
        self.assertEqual(
            data_plane["checkout_identity_block_sha256"],
            "8e2fc83b2c55d5d34e42c46141e7691e4781b9d0931c10b26951adb63e238467",
        )
        self.assertEqual(
            data_plane["model_through_success_cleanup_sha256"],
            "bbb1975a2d0f78c02620850c1d4fedeffd6958b47e7533d3cc7dd23b88c0e3a8",
        )
        offline = stage_a_v3["offline_validation"]
        self.assertEqual(offline["fixture_scenario_count"], 16)
        self.assertTrue(offline["embedded_cr_rejected_without_retry"])
        self.assertTrue(offline["exact_transient_twice_stops_after_two"])
        self.assertTrue(offline["near_and_nontransient_failures_stop_after_one"])
        self.assertTrue(offline["clean_room_residue_reuse_rejected"])
        self.assertTrue(offline["byte_identical_transport_parameters_passed"])
        self.assertEqual(offline["focused_test_count"], 5)
        self.assertEqual(offline["independent_reviewer_pass_count"], 2)
        ci_fix = stage_a_v3["ci_hermeticity_correction"]
        self.assertEqual(
            ci_fix["affected_path"],
            "tests/test_ai_operation_admission.py",
        )
        self.assertTrue(ci_fix["shared_runner_sqlite_wall_clock_assertion_removed"])
        self.assertFalse(ci_fix["arbitrary_wall_clock_limit_relaxed"])
        self.assertTrue(ci_fix["hundred_admission_persistence_assertions_preserved"])
        self.assertTrue(
            ci_fix["provider_attempt_and_model_call_zero_assertions_preserved"]
        )
        self.assertFalse(ci_fix["stage_a_executor_changed"])
        self.assertFalse(ci_fix["build_or_image_content_changed"])
        self.assertEqual(ci_fix["main_local_pass_count"], 5)
        self.assertEqual(ci_fix["independent_local_pass_count"], 20)
        self.assertTrue(ci_fix["managed_capacity_item_remains_unverified"])
        external_scope = stage_a_v3["external_scope"]
        for key in (
            "builder_start_count",
            "cloud_assistant_upload_count",
            "cloud_assistant_execution_count",
            "source_fetch_count",
            "docker_build_count",
            "acr_login_count",
            "acr_publication_count",
            "production_deployment_count",
            "production_database_connection_count",
            "production_database_write_count",
            "production_service_mutation_count",
            "public_traffic_mutation_count",
        ):
            self.assertEqual(external_scope[key], 0, key)
        authorization = stage_a_v3["authorization"]
        self.assertTrue(
            authorization["single_v3_external_execution_authorized_after_exact_head_ci"]
        )
        self.assertTrue(authorization["authorization_is_root_cause_bound"])
        self.assertEqual(
            authorization["maximum_external_stage_a_execution_count"],
            1,
        )
        self.assertFalse(
            authorization["additional_stage_a_execution_on_failure_authorized"]
        )
        self.assertFalse(authorization["public_traffic_mutation_authorized"])
        self.assertFalse(authorization["schema_or_business_data_mutation_authorized"])
        self.assertTrue(authorization["v17_rerun_forbidden"])
        self.assertTrue(authorization["r17_forbidden"])
        self.assertTrue(authorization["v18_forbidden"])
        self.assertFalse(stage_a_v3["readiness"]["credit_added"])
        v3_attempt = admin["admin_stage_a_v3_attempt1"]
        self.assertEqual(
            v3_attempt["result"],
            "FAILED_DURING_FIRST_SOURCE_FETCH_BEFORE_DOCKER_BUILD",
        )
        self.assertEqual(
            v3_attempt["controller_commit"],
            "6951a003097599f8c82fb46cbdc84b316238ff05",
        )
        for event, run_id, job_id in (
            ("push", 30782246083, 91589070216),
            ("pull_request", 30782247926, 91589075091),
        ):
            ci = v3_attempt["exact_head_ci"][event]
            self.assertEqual(ci["run_id"], run_id)
            self.assertEqual(ci["job_id"], job_id)
            self.assertEqual(ci["attempt"], 1)
            self.assertEqual(ci["head_sha"], v3_attempt["controller_commit"])
            self.assertEqual(ci["conclusion"], "success")
            self.assertEqual(ci["total_test_count"], 1770)
            self.assertEqual(ci["ambient_skipped_count"], 28)
            self.assertEqual(ci["production_readiness_checks"], "137/137")
            self.assertEqual(ci["artifact_count"], 0)
        self.assertEqual(v3_attempt["exact_head_ci"]["rerun_count"], 0)
        transport = v3_attempt["transport"]
        self.assertEqual(transport["archive"]["byte_count"], 8851)
        self.assertEqual(
            transport["archive"]["sha256"],
            "a36777a59d5bd364e6757e6abfa697b7e44517427e50386407f235e0c4201c8e",
        )
        self.assertEqual(transport["executor"]["byte_count"], 31609)
        self.assertEqual(
            transport["executor"]["sha256"],
            "562cceb3f6b08da0b8e0723e4b636d664b6fc67cf622c6da3061601ee8b3f31a",
        )
        self.assertEqual(transport["command_wrapper"]["byte_count"], 1142)
        self.assertEqual(
            transport["command_wrapper"]["sha256"],
            "ca69e854cd423c7e2a624c942b5a9f9561c69730a08c92941137157e6303d263",
        )
        self.assertTrue(
            transport["command_wrapper"][
                "pre_execution_archive_and_executor_gate_passed"
            ]
        )
        self.assertEqual(transport["file_send_count"], 1)
        self.assertFalse(transport["api_c_selected"])
        self.assertFalse(transport["api_f_selected"])
        command = v3_attempt["cloud_assistant"]
        self.assertEqual(
            command["command_name"],
            "noteai-admin-item20-stage-a-execute-v3",
        )
        self.assertEqual(command["execution_count"], 1)
        self.assertEqual(command["duration_seconds"], 91)
        self.assertEqual(command["exit_code"], 128)
        failure = v3_attempt["failure"]
        self.assertEqual(failure["phase"], "source_fetch")
        self.assertEqual(failure["source_fetch_attempt_count"], 1)
        self.assertEqual(
            failure["normalized_error_class"],
            "fixed_origin_empty_reply",
        )
        self.assertFalse(failure["v3_retry_signature_match"])
        self.assertEqual(failure["conditional_retry_count"], 0)
        self.assertFalse(failure["docker_build_reached"])
        self.assertFalse(failure["native_release_evidence_reached"])
        cleanup = v3_attempt["cleanup"]
        self.assertTrue(cleanup["target_images_absent"])
        self.assertTrue(cleanup["task_root_absent"])
        self.assertEqual(cleanup["running_container_count"], 0)
        self.assertEqual(cleanup["builder_instance_status"], "stopped")
        self.assertEqual(cleanup["builder_stop_mode"], "saving")
        self.assertTrue(cleanup["public_ipv4_released_in_saving_mode"])
        scope = v3_attempt["execution_scope"]
        self.assertEqual(scope["source_fetch_attempt_count"], 1)
        for key in (
            "conditional_retry_count",
            "automatic_retry_count",
            "manual_rerun_count",
            "second_v3_execution_count",
            "stage_a_v4_execution_count",
            "docker_build_count",
            "native_evidence_set_count",
            "acr_login_count",
            "acr_publication_count",
            "acr_readback_count",
            "stage_c_execution_count",
            "production_database_connection_count",
            "production_database_write_count",
            "production_service_mutation_count",
            "public_traffic_mutation_count",
        ):
            self.assertEqual(scope[key], 0, key)
        v3_authorization = v3_attempt["authorization"]
        self.assertTrue(
            v3_authorization["exact_one_v3_external_execution_consumed"]
        )
        self.assertTrue(v3_authorization["v3_rerun_forbidden"])
        self.assertFalse(
            v3_authorization["additional_stage_a_external_execution_authorized"]
        )
        self.assertTrue(v3_authorization["stage_a_v4_forbidden"])
        self.assertTrue(
            v3_authorization["downstream_stage_b_and_c_blocked_without_image"]
        )
        self.assertFalse(v3_attempt["readiness"]["credit_added"])
        self.assertFalse(v3_attempt["secret_free"]["alibaba_resource_ids_persisted"])
        v3_serialized = json.dumps(v3_attempt, ensure_ascii=False)
        self.assertNotRegex(v3_serialized, r"\b[ictf]-[a-z0-9]{8,}\b")
        self.assertNotRegex(
            v3_serialized,
            r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        )
        checkpoint = v3_attempt["checkpoint_validation"]
        self.assertEqual(checkpoint["changed_path_count"], 4)
        self.assertTrue(checkpoint["json_parse_passed"])
        self.assertTrue(checkpoint["diff_check_passed"])
        self.assertEqual(checkpoint["focused_test_count"], 21)
        self.assertEqual(checkpoint["production_readiness_checks"], "137/137")
        self.assertTrue(checkpoint["temporary_transfer_files_deleted"])
        v4 = admin["admin_stage_a_v4_preparation"]
        self.assertEqual(
            v4["result"],
            "EXACT_HEAD_DUAL_CI_PASSED_ATTEMPT1_FAILED_SCANNER_DB_REFRESH",
        )
        self.assertEqual(
            v4["controller_base_commit"],
            "cfe06fa453e66ade80a25070dec380ea8bd65590",
        )
        self.assertEqual(
            v4["controller_commit"],
            "bc14c6aa6d129816a307b5ffa5241e6882e3e97c",
        )
        self.assertEqual(v4["executor"]["byte_count"], 30980)
        self.assertEqual(
            v4["executor"]["sha256"],
            "2b811021305e81c3250c4b72f7707ac5f8d4c5fcd87ab0ae93e5c671086a8c75",
        )
        local_transport = v4["local_source_transport"]
        self.assertEqual(local_transport["bundle_byte_count"], 159507)
        self.assertEqual(
            local_transport["bundle_sha256"],
            "4e62b0627b4be73d7ccc14d821d34f01894340297729456f9f3e22b45a6e75b3",
        )
        self.assertEqual(local_transport["delta_commit_count"], 11)
        self.assertEqual(local_transport["recovered_history_commit_count"], 197)
        self.assertEqual(local_transport["independent_generation_view_count"], 2)
        self.assertTrue(local_transport["byte_identical_generation_passed"])
        self.assertTrue(local_transport["clean_recipient_import_passed"])
        self.assertTrue(local_transport["file_protocol_only"])
        self.assertEqual(local_transport["remote_count_after_import"], 0)
        self.assertEqual(local_transport["retry_count"], 0)
        self.assertFalse(local_transport["mirror_proxy_or_credential_change"])
        data_plane_v4 = v4["data_plane_immutability"]
        for key in (
            "source_commit_or_tree_changed",
            "dockerfile_changed",
            "model_materialization_changed",
            "build_arguments_changed",
            "image_tags_changed",
            "native_evidence_contract_changed",
        ):
            self.assertFalse(data_plane_v4[key], key)
        review_v4 = v4["independent_review"]
        self.assertTrue(review_v4["p1_evidence_directory_precreation_found"])
        self.assertTrue(review_v4["p1_fixed"])
        self.assertTrue(review_v4["regression_assertion_added"])
        self.assertFalse(review_v4["final_re_review_pending"])
        self.assertEqual(review_v4["final_result"], "PASS")
        self.assertEqual(v4["offline_validation"]["v2_v3_v4_focused_test_count"], 13)
        self.assertEqual(
            v4["offline_validation"]["production_readiness_checks"],
            "137/137",
        )
        external_scope_v4 = v4["external_scope"]
        for key, value in (
            ("builder_start_count", 1),
            ("cloud_assistant_file_send_count", 8),
            ("cloud_assistant_execution_count", 1),
            ("stage_a_execution_count", 1),
            ("trivy_database_download_count", 1),
        ):
            self.assertEqual(external_scope_v4[key], value, key)
        for key in (
            "network_source_fetch_count",
            "docker_build_count",
            "native_evidence_set_count",
            "acr_login_count",
            "acr_publication_count",
            "production_deployment_count",
            "production_database_connection_count",
            "production_database_write_count",
            "production_service_mutation_count",
            "public_traffic_mutation_count",
        ):
            self.assertEqual(external_scope_v4[key], 0, key)
        authorization_v4 = v4["authorization"]
        self.assertTrue(
            authorization_v4[
                "exact_one_v4_external_execution_authorized_after_exact_head_dual_ci"
            ]
        )
        self.assertEqual(authorization_v4["maximum_v4_external_execution_count"], 1)
        self.assertTrue(
            authorization_v4["exact_one_v4_external_execution_consumed"]
        )
        self.assertTrue(authorization_v4["v3_rerun_forbidden"])
        self.assertFalse(authorization_v4["v4_rerun_on_failure_authorized"])
        self.assertTrue(authorization_v4["v4_rerun_forbidden"])
        self.assertFalse(
            authorization_v4["additional_stage_a_external_execution_authorized"]
        )
        self.assertTrue(
            authorization_v4["downstream_stage_b_and_c_blocked_without_image"]
        )
        self.assertFalse(authorization_v4["public_traffic_mutation_authorized"])
        self.assertFalse(authorization_v4["schema_or_business_data_mutation_authorized"])
        self.assertFalse(authorization_v4["paid_ai_or_crawler_authorized"])
        self.assertTrue(authorization_v4["v17_rerun_forbidden"])
        self.assertTrue(authorization_v4["r17_forbidden"])
        self.assertTrue(authorization_v4["v18_forbidden"])
        self.assertFalse(v4["readiness"]["credit_added"])
        v4_attempt = admin["admin_stage_a_v4_attempt1"]
        self.assertEqual(
            v4_attempt["result"],
            "FAILED_DURING_FRESH_TRIVY_DB_REFRESH_BEFORE_DOCKER_BUILD",
        )
        self.assertEqual(v4_attempt["controller_commit"], v4["controller_commit"])
        self.assertEqual(v4_attempt["source_commit"], v4["source_commit"])
        self.assertEqual(v4_attempt["source_tree"], v4["source_tree"])
        for event, run_id, job_id in (
            ("push", 30788036947, 91605487114),
            ("pull_request", 30788039997, 91605496219),
        ):
            ci = v4_attempt["exact_head_ci"][event]
            self.assertEqual(ci["run_id"], run_id)
            self.assertEqual(ci["job_id"], job_id)
            self.assertEqual(ci["attempt"], 1)
            self.assertEqual(ci["head_sha"], v4_attempt["controller_commit"])
            self.assertEqual(ci["conclusion"], "success")
            self.assertEqual(ci["total_test_count"], 1774)
            self.assertEqual(ci["ambient_skipped_count"], 28)
            self.assertEqual(ci["production_readiness_checks"], "137/137")
            self.assertEqual(ci["artifact_count"], 0)
        self.assertEqual(v4_attempt["exact_head_ci"]["rerun_count"], 0)
        payload = v4_attempt["transport"]["payload"]
        self.assertEqual(payload["byte_count"], 168179)
        self.assertEqual(
            payload["sha256"],
            "911b0fefb3501d15d9f2070202e0db0bf4216df23aeb7eb96967c5b3cb9b70e4",
        )
        self.assertEqual(payload["executor_byte_count"], 30980)
        self.assertEqual(
            payload["executor_sha256"],
            "2b811021305e81c3250c4b72f7707ac5f8d4c5fcd87ab0ae93e5c671086a8c75",
        )
        self.assertEqual(payload["bundle_byte_count"], 159507)
        self.assertEqual(
            payload["bundle_sha256"],
            "4e62b0627b4be73d7ccc14d821d34f01894340297729456f9f3e22b45a6e75b3",
        )
        transport_v4 = v4_attempt["transport"]
        self.assertEqual(transport_v4["chunk_count"], 8)
        self.assertEqual(transport_v4["file_send_count"], 8)
        self.assertEqual(transport_v4["target_count"], 1)
        self.assertFalse(transport_v4["api_c_selected"])
        self.assertFalse(transport_v4["api_f_selected"])
        loader = transport_v4["command_loader"]
        self.assertEqual(loader["character_count"], 9351)
        self.assertEqual(loader["wrapper_byte_count"], 6690)
        self.assertEqual(
            loader["wrapper_sha256"],
            "9129df30baa3a77a23d4d896e56b68093857450cfb9354b75734712d2ed174f2",
        )
        self.assertTrue(loader["remote_wrapper_size_and_sha_gate_passed"])
        command_v4 = v4_attempt["cloud_assistant"]
        self.assertEqual(
            command_v4["command_name"],
            "noteai-admin-item20-stage-a-execute-v4",
        )
        self.assertEqual(command_v4["target_count"], 1)
        self.assertEqual(command_v4["execution_count"], 1)
        self.assertEqual(command_v4["duration_seconds"], 306)
        self.assertEqual(command_v4["exit_code"], 1)
        preflight_v4 = v4_attempt["preflight"]
        self.assertTrue(preflight_v4["retained_b55_repository_passed"])
        self.assertTrue(preflight_v4["bundle_identity_passed"])
        self.assertTrue(preflight_v4["host_and_collision_gate_passed"])
        failure_v4 = v4_attempt["failure"]
        self.assertEqual(failure_v4["phase"], "scanner_db_refresh")
        self.assertEqual(
            failure_v4["normalized_error_class"],
            "trivy_internal_default_timeout_progress_unknown",
        )
        self.assertEqual(failure_v4["database_download_attempt_count"], 1)
        self.assertEqual(failure_v4["trivy_internal_timeout_seconds"], 300)
        self.assertEqual(failure_v4["outer_timeout_seconds"], 1200)
        self.assertFalse(failure_v4["outer_timeout_reached"])
        self.assertTrue(failure_v4["download_progress_suppressed"])
        self.assertFalse(failure_v4["zero_progress_proven"])
        self.assertTrue(failure_v4["slow_transfer_possible"])
        self.assertTrue(failure_v4["source_bundle_import_reached"])
        self.assertTrue(failure_v4["model_materialization_reached"])
        self.assertTrue(failure_v4["tool_prep_reached"])
        self.assertFalse(failure_v4["docker_build_reached"])
        self.assertFalse(failure_v4["native_release_evidence_reached"])
        self.assertFalse(failure_v4["acr_login_reached"])
        cleanup_v4 = v4_attempt["cleanup"]
        self.assertTrue(cleanup_v4["target_images_absent"])
        self.assertTrue(cleanup_v4["task_root_absent"])
        self.assertEqual(cleanup_v4["running_container_count"], 0)
        self.assertTrue(cleanup_v4["transfer_cleanup_marker_observed"])
        self.assertEqual(cleanup_v4["builder_instance_status"], "stopped")
        self.assertEqual(cleanup_v4["builder_stop_mode"], "saving")
        self.assertTrue(cleanup_v4["public_ipv4_released_in_saving_mode"])
        scope_v4 = v4_attempt["execution_scope"]
        for key, value in (
            ("existing_builder_start_count", 1),
            ("cloud_assistant_file_send_count", 8),
            ("cloud_assistant_execution_count", 1),
            ("stage_a_execution_count", 1),
            ("trivy_database_download_count", 1),
        ):
            self.assertEqual(scope_v4[key], value, key)
        for key in (
            "new_builder_create_count",
            "network_source_fetch_count",
            "automatic_retry_count",
            "manual_rerun_count",
            "second_v4_execution_count",
            "docker_build_count",
            "native_evidence_set_count",
            "acr_login_count",
            "acr_publication_count",
            "acr_readback_count",
            "stage_c_execution_count",
            "production_database_connection_count",
            "production_database_write_count",
            "production_service_mutation_count",
            "public_traffic_mutation_count",
        ):
            self.assertEqual(scope_v4[key], 0, key)
        v4_attempt_authorization = v4_attempt["authorization"]
        self.assertTrue(
            v4_attempt_authorization["exact_one_v4_external_execution_consumed"]
        )
        self.assertTrue(v4_attempt_authorization["v4_rerun_forbidden"])
        self.assertFalse(
            v4_attempt_authorization[
                "additional_stage_a_external_execution_authorized"
            ]
        )
        self.assertTrue(
            v4_attempt_authorization[
                "downstream_stage_b_and_c_blocked_without_image"
            ]
        )
        self.assertFalse(v4_attempt["readiness"]["credit_added"])
        self.assertFalse(v4_attempt["secret_free"]["alibaba_resource_ids_persisted"])
        v4_serialized = json.dumps(v4_attempt, ensure_ascii=False)
        self.assertNotRegex(v4_serialized, r"\b[ictf]-[a-z0-9]{8,}\b")
        self.assertNotRegex(
            v4_serialized,
            r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        )
        v4_checkpoint = v4_attempt["checkpoint_validation"]
        self.assertEqual(v4_checkpoint["changed_path_count"], 4)
        self.assertTrue(v4_checkpoint["json_parse_passed"])
        self.assertTrue(v4_checkpoint["diff_check_passed"])
        self.assertEqual(v4_checkpoint["focused_test_count"], 21)
        self.assertEqual(v4_checkpoint["production_readiness_checks"], "137/137")
        self.assertTrue(v4_checkpoint["temporary_transfer_directory_deleted"])
        v5 = admin["admin_stage_a_v5_attempt1"]
        self.assertEqual(
            v5["result"],
            "TERMINAL_OFFICIAL_GHCR_SEVERE_THROUGHPUT_TIMEOUT_CLEAN",
        )
        self.assertEqual(
            v5["controller_base_commit"],
            "2cc6bf72258464a6754ee4594a721f64a247cdcd",
        )
        self.assertEqual(
            v5["controller_commit"],
            "cfa7ad336e01befccfd0e9a0dace19761d36fa2e",
        )
        self.assertEqual(v5["source_commit"], v4_attempt["source_commit"])
        self.assertEqual(v5["source_tree"], v4_attempt["source_tree"])
        self.assertEqual(v5["target_tag"], v4_attempt["target_tag"])
        self.assertEqual(v5["executor"]["byte_count"], 31071)
        self.assertEqual(
            v5["executor"]["sha256"],
            "4f2e6c116694347cbfb748ac486f1ab391f9e346df155b50d45c6f158db3a249",
        )
        checkpoint_ci_v5 = v5["accepted_v4_terminal_checkpoint_ci"]
        self.assertEqual(checkpoint_ci_v5["head_sha"], v5["controller_base_commit"])
        for event, run_id, job_id in (
            ("push", 30792006004, 91617330241),
            ("pull_request", 30792008479, 91617338071),
        ):
            ci = checkpoint_ci_v5[event]
            self.assertEqual(ci["run_id"], run_id)
            self.assertEqual(ci["job_id"], job_id)
            self.assertEqual(ci["attempt"], 1)
            self.assertEqual(ci["conclusion"], "success")
            self.assertEqual(ci["total_test_count"], 1775)
            self.assertEqual(ci["ambient_skipped_count"], 28)
            self.assertEqual(ci["production_readiness_checks"], "137/137")
            self.assertEqual(ci["artifact_count"], 0)
        self.assertEqual(checkpoint_ci_v5["exact_head_run_count"], 2)
        self.assertEqual(checkpoint_ci_v5["rerun_count"], 0)
        candidate_ci_v5 = v5["accepted_v5_candidate_ci"]
        self.assertEqual(candidate_ci_v5["head_sha"], v5["controller_commit"])
        for event, run_id, job_id in (
            ("push", 30794361508, 91624483011),
            ("pull_request", 30794364596, 91624493517),
        ):
            ci = candidate_ci_v5[event]
            self.assertEqual(ci["run_id"], run_id)
            self.assertEqual(ci["job_id"], job_id)
            self.assertEqual(ci["attempt"], 1)
            self.assertEqual(ci["conclusion"], "success")
            self.assertEqual(ci["total_test_count"], 1779)
            self.assertEqual(ci["ambient_skipped_count"], 28)
            self.assertEqual(ci["production_readiness_checks"], "137/137")
            self.assertEqual(ci["artifact_count"], 0)
        self.assertEqual(candidate_ci_v5["exact_head_run_count"], 2)
        self.assertEqual(candidate_ci_v5["rerun_count"], 0)
        delta_v5 = v5["minimal_delta_from_v4"]
        self.assertEqual(delta_v5["trivy_internal_timeout_explicit"], "15m")
        self.assertEqual(delta_v5["outer_timeout_seconds"], 1200)
        for key in (
            "v5_namespace_and_invocation_isolated",
            "internal_timeout_below_outer_timeout",
            "no_progress_flag_removed",
            "download_output_streamed_and_retained_with_tee",
            "pipefail_preserves_download_failure",
            "timeout_help_capability_checked_before_network",
        ):
            self.assertTrue(delta_v5[key], key)
        for key in (
            "source_commit_or_tree_changed",
            "dockerfile_changed",
            "model_materialization_changed",
            "build_arguments_changed",
            "image_tags_changed",
            "database_repository_changed",
            "trivy_freshness_gate_changed",
            "offline_scan_contract_changed",
            "native_evidence_contract_changed",
            "registry_or_production_logic_added",
            "custom_ledger_receipt_or_topology_added",
        ):
            self.assertFalse(delta_v5[key], key)
        validation_v5 = v5["local_validation"]
        self.assertTrue(validation_v5["bash_syntax_passed"])
        self.assertTrue(validation_v5["offline_self_test_passed"])
        self.assertTrue(validation_v5["exact_minimal_delta_test_passed"])
        self.assertTrue(validation_v5["timeout_and_progress_contract_test_passed"])
        self.assertEqual(validation_v5["focused_test_count"], 4)
        self.assertEqual(validation_v5["independent_read_only_review"], "PASS")
        self.assertTrue(validation_v5["json_parse_passed"])
        self.assertTrue(validation_v5["diff_check_passed"])
        self.assertEqual(validation_v5["combined_focused_test_count"], 25)
        self.assertEqual(validation_v5["production_readiness_checks"], "137/137")
        transfer_v5 = v5["transfer"]
        self.assertEqual(transfer_v5["git_bundle_byte_count"], 159507)
        self.assertEqual(
            transfer_v5["git_bundle_sha256"],
            "4e62b0627b4be73d7ccc14d821d34f01894340297729456f9f3e22b45a6e75b3",
        )
        self.assertEqual(transfer_v5["payload_byte_count"], 168202)
        self.assertEqual(
            transfer_v5["payload_sha256"],
            "ba6115299a308d3791a65da42ac980be99fa96efdc315a336f03c2d9b3dfe805",
        )
        self.assertEqual(transfer_v5["chunk_count"], 8)
        self.assertEqual(transfer_v5["root_only_file_send_count"], 8)
        self.assertEqual(transfer_v5["wrapper_byte_count"], 4529)
        self.assertEqual(
            transfer_v5["wrapper_sha256"],
            "94f3f2253d437077058d94df8746faa96ed988347da7677078ad89576125e5a8",
        )
        self.assertTrue(transfer_v5["wrapper_calls_v5_executor_exactly_once"])
        self.assertFalse(transfer_v5["custom_ledger_receipt_or_topology_used"])
        terminal_v5 = v5["terminal_execution"]
        self.assertEqual(
            terminal_v5["command_name"],
            "noteai-admin-item20-stage-a-execute-v5",
        )
        self.assertEqual(terminal_v5["command_dispatch_count"], 1)
        self.assertEqual(terminal_v5["command_duration_seconds"], 905)
        self.assertEqual(terminal_v5["exit_code"], 1)
        self.assertEqual(terminal_v5["terminal_phase"], "scanner_db_refresh")
        for key in (
            "retained_b55_preflight_passed",
            "source_import_reached",
            "model_materialization_reached",
            "tool_preparation_reached",
        ):
            self.assertTrue(terminal_v5[key], key)
        for key in (
            "docker_build_reached",
            "native_evidence_reached",
            "acr_reached",
            "stage_c_reached",
        ):
            self.assertFalse(terminal_v5[key], key)
        trivy_v5 = terminal_v5["trivy"]
        self.assertEqual(trivy_v5["repository"], "ghcr.io/aquasecurity/trivy-db:2")
        self.assertEqual(trivy_v5["target_mebibytes"], 103.39)
        self.assertEqual(trivy_v5["final_downloaded_mebibytes"], 8.61)
        self.assertEqual(trivy_v5["final_percent"], 8.33)
        self.assertEqual(trivy_v5["final_displayed_kibibytes_per_second"], 9.89)
        self.assertTrue(trivy_v5["download_was_progressing"])
        self.assertFalse(trivy_v5["zero_progress_proven"])
        self.assertTrue(trivy_v5["severe_slowness_observed"])
        self.assertEqual(trivy_v5["internal_timeout_seconds"], 900)
        self.assertEqual(trivy_v5["outer_timeout_seconds"], 1200)
        self.assertFalse(trivy_v5["outer_timeout_reached"])
        self.assertEqual(
            trivy_v5["timeout_semantics"],
            "absolute_command_context_budget_not_inactivity_timeout",
        )
        self.assertEqual(
            trivy_v5["terminal_error_class"],
            "context_deadline_exceeded_during_artifact_copy",
        )
        self.assertFalse(trivy_v5["partial_download_resume_available"])
        scope_v5 = v5["external_scope"]
        for key, value in (
            ("builder_start_count", 1),
            ("cloud_assistant_file_send_count", 8),
            ("cloud_assistant_execution_count", 1),
            ("stage_a_execution_count", 1),
            ("trivy_database_download_count", 1),
        ):
            self.assertEqual(scope_v5[key], value, key)
        for key in (
            "docker_build_count",
            "native_evidence_set_count",
            "acr_login_count",
            "acr_publication_count",
            "stage_c_execution_count",
            "production_database_connection_count",
            "production_database_write_count",
            "production_service_mutation_count",
            "public_traffic_mutation_count",
        ):
            self.assertEqual(scope_v5[key], 0, key)
        cleanup_v5 = v5["cleanup"]
        for key in (
            "target_images_absent",
            "task_root_absent",
            "remote_transfer_root_absent",
            "builder_stopped_in_saving_mode",
            "temporary_public_ipv4_released",
            "local_temporary_transfer_directories_absent_from_private_tmp",
            "local_temporary_transfer_directories_moved_to_trash",
            "local_trash_cleanup_recoverable",
        ):
            self.assertTrue(cleanup_v5[key], key)
        self.assertEqual(cleanup_v5["running_container_count"], 0)
        self.assertEqual(cleanup_v5["remote_transfer_chunk_count"], 0)
        self.assertEqual(cleanup_v5["local_temporary_transfer_directory_count"], 2)
        authorization_v5 = v5["authorization"]
        self.assertTrue(
            authorization_v5["main_cto_finite_bounded_internal_authority_applied"]
        )
        self.assertTrue(authorization_v5["exact_one_v5_external_execution_consumed"])
        self.assertEqual(authorization_v5["maximum_v5_external_execution_count"], 1)
        self.assertTrue(authorization_v5["v4_rerun_forbidden"])
        self.assertTrue(authorization_v5["automatic_retry_forbidden"])
        self.assertFalse(authorization_v5["manual_retry_performed"])
        self.assertTrue(authorization_v5["v5_rerun_forbidden"])
        self.assertFalse(authorization_v5["public_traffic_mutation_authorized"])
        self.assertFalse(
            authorization_v5["schema_or_business_data_mutation_authorized"]
        )
        self.assertFalse(authorization_v5["paid_ai_or_crawler_authorized"])
        self.assertTrue(authorization_v5["v17_rerun_forbidden"])
        self.assertTrue(authorization_v5["r17_forbidden"])
        self.assertTrue(authorization_v5["v18_forbidden"])
        self.assertFalse(v5["readiness"]["credit_added"])
        self.assertEqual(v5["readiness"]["internal_verified_count"], 19)
        self.assertEqual(v5["readiness"]["public_verified_count"], 19)
        v5_serialized = json.dumps(v5, ensure_ascii=False)
        self.assertNotRegex(v5_serialized, r"\b[ictf]-[a-z0-9]{8,}\b")
        self.assertNotRegex(
            v5_serialized,
            r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        )
        public_ecr = admin["admin_stage_a_public_ecr_transition"]
        self.assertEqual(
            public_ecr["result"],
            "TERMINAL_PUBLIC_ECR_DB_PASS_PYTHON_DEPENDENCY_READ_TIMEOUT_CLEAN",
        )
        probe = public_ecr["probe"]
        self.assertEqual(
            probe["repository"],
            "public.ecr.aws/aquasecurity/trivy-db:2",
        )
        self.assertEqual(probe["target_mebibytes"], 103.39)
        self.assertEqual(probe["elapsed_seconds"], 26)
        self.assertEqual(probe["exit_code"], 0)
        self.assertTrue(probe["freshness_validation_passed"])
        self.assertEqual(probe["database_byte_count"], 1223847936)
        self.assertEqual(
            probe["database_sha256"],
            "4f61ad6f60fe87055d2a9d43ab43e9da0f76a219f5aa6d59167e387cce2b5285",
        )
        self.assertEqual(
            probe["metadata_sha256"],
            "5f4a6c2cf1c0650a50f2c46d5c41849fd36ff37bc8b1b64268a1351ed7859d83",
        )
        for key in (
            "probe_root_absent",
            "builder_stopped_in_saving_mode",
            "temporary_public_ipv4_released",
        ):
            self.assertTrue(probe[key], key)
        for key in (
            "docker_build_count",
            "acr_action_count",
            "production_mutation_count",
        ):
            self.assertEqual(probe[key], 0, key)
        successor = public_ecr["successor"]
        self.assertEqual(
            successor["base_checkpoint_commit"],
            "f606f49cc88fa4e3993a2e7fb5d2dbba463bc55f",
        )
        self.assertEqual(
            successor["executor_path"],
            "deploy/production/admin_item20_stage_a_public_ecr.sh",
        )
        self.assertEqual(successor["executor_byte_count"], 31143)
        self.assertEqual(
            successor["executor_sha256"],
            "a7cf0f48e23171aef3774f2f6db2620f90ccbb8d35b48dadeb0b039a5ff99259",
        )
        self.assertEqual(
            successor["v5_executor_sha256"],
            "4f2e6c116694347cbfb748ac486f1ab391f9e346df155b50d45c6f158db3a249",
        )
        self.assertEqual(
            successor["repository_before"],
            "ghcr.io/aquasecurity/trivy-db:2",
        )
        self.assertEqual(
            successor["repository_after"],
            "public.ecr.aws/aquasecurity/trivy-db:2",
        )
        self.assertTrue(successor["namespace_isolated"])
        self.assertTrue(
            successor["source_build_image_and_evidence_contracts_unchanged"]
        )
        self.assertFalse(successor["custom_ledger_receipt_or_topology_added"])
        self.assertEqual(
            successor["local_gate"],
            "29/29 focused; production 137/137",
        )
        self.assertEqual(successor["external_execution_count"], 1)
        exact_head_ci = public_ecr["accepted_exact_head_ci"]
        self.assertEqual(
            exact_head_ci["head_sha"],
            "c3de9ed3030b5d581d398ceb494d2f5677e6a753",
        )
        self.assertEqual(exact_head_ci["push_run_id"], 30804908699)
        self.assertEqual(exact_head_ci["pull_request_run_id"], 30804912220)
        self.assertTrue(exact_head_ci["attempt_one_success"])
        self.assertEqual(exact_head_ci["rerun_count"], 0)
        terminal = public_ecr["terminal_execution"]
        self.assertEqual(
            terminal["source_commit"],
            "5335bdaed933b1f999b5f819c047ec50c11821ae",
        )
        self.assertEqual(terminal["execution_count"], 1)
        self.assertEqual(terminal["duration_seconds"], 1298)
        self.assertEqual(terminal["exit_code"], 1)
        self.assertEqual(terminal["phase"], "admin_build_scan")
        self.assertEqual(terminal["trivy_download_mebibytes"], 103.39)
        self.assertTrue(terminal["trivy_freshness_validation_passed"])
        self.assertEqual(terminal["dependency_host"], "files.pythonhosted.org")
        self.assertEqual(terminal["error_class"], "pip_urllib3_read_timeout")
        self.assertFalse(terminal["local_admin_image_produced"])
        self.assertEqual(terminal["accepted_native_evidence_file_count"], 0)
        for key in (
            "acr_action_count",
            "database_connection_count",
            "production_mutation_count",
        ):
            self.assertEqual(terminal[key], 0, key)
        self.assertTrue(terminal["authority_consumed"])
        cleanup = public_ecr["cleanup"]
        for key in (
            "target_images_absent",
            "task_root_absent",
            "remote_transfer_root_absent",
            "local_transfer_root_moved_to_trash",
            "builder_stopped_in_saving_mode",
            "temporary_public_ipv4_released",
        ):
            self.assertTrue(cleanup[key], key)
        self.assertEqual(cleanup["running_container_count"], 0)
        recovery = public_ecr["direct_recovery"]
        self.assertEqual(
            recovery["status"],
            "STAGE_B_SCHEME_ONE_AUTHORIZED_LOCAL_GATE_PASS_PENDING_EXACT_HEAD_CI",
        )
        self.assertEqual(
            recovery["c17_sha"],
            "7ee9a15425c38e8f0d5382cba488bd4a6ce92d6e",
        )
        self.assertEqual(recovery["activation"], "single_workflow_dispatch")
        self.assertEqual(recovery["configured_maximum_seconds"], 5700)
        self.assertEqual(
            recovery["local_complete_readiness_gate"],
            "136/136_once",
        )
        self.assertEqual(
            recovery["native_digest_source_required"],
            "authenticated_github_artifact_metadata",
        )
        self.assertTrue(recovery["dockerfile_and_requirements_bytes_unchanged"])
        self.assertFalse(recovery["custom_gate_version_or_control_layer_added"])
        checkpoint = recovery["accepted_recovery_checkpoint"]
        self.assertEqual(
            checkpoint["head_sha"],
            "18705620ddc0ba35d91a8d4424cde5cf07e1538d",
        )
        self.assertEqual(checkpoint["push_workflow_run_id"], 30815301049)
        self.assertEqual(
            checkpoint["pull_request_workflow_run_id"],
            30815303994,
        )
        self.assertTrue(checkpoint["attempt_one_success"])
        native = recovery["v17_native_acceptance"]
        self.assertEqual(native["workflow_run_id"], 30816912157)
        self.assertEqual(native["c17_sha"], recovery["c17_sha"])
        self.assertEqual(
            native["artifact_digest"],
            "sha256:742a01d2f4f1dc14cb6a9bf620591d1fc7288dbc64113ba0db9d223d6e6ee139",
        )
        self.assertTrue(native["fresh_builder_network_none_import_success"])
        self.assertEqual(native["workflow_dispatch_count"], 1)
        self.assertEqual(native["rerun_count"], 0)
        stage_a = recovery["stage_a_native_acceptance"]
        self.assertEqual(
            stage_a["status"],
            "SUCCESS_AND_TEMPORARY_INPUTS_CLEANED",
        )
        self.assertEqual(stage_a["execution_count"], 1)
        self.assertEqual(
            stage_a["release_commit"],
            "5335bdaed933b1f999b5f819c047ec50c11821ae",
        )
        self.assertEqual(stage_a["platform"], "linux/amd64")
        self.assertEqual(stage_a["native_evidence_file_count"], 11)
        self.assertTrue(
            stage_a["temporary_builder_iam_removed_after_three_input_sha_checks"]
        )
        self.assertTrue(
            stage_a["temporary_private_objects_and_bucket_removed_after_success"]
        )
        self.assertEqual(
            stage_a["registry_service_database_public_traffic_actions"],
            0,
        )
        stage_b = recovery["stage_b_private_publication"]
        self.assertEqual(stage_b["status"], "AUTHORIZED_NOT_EXECUTED")
        self.assertEqual(stage_b["repository"], "noteai/app")
        self.assertEqual(stage_b["tag"], "git-5335bda-amd64-admin-r1")
        self.assertTrue(stage_b["repository_private_normal_tag_immutable"])
        self.assertTrue(stage_b["target_tag_absent_at_preflight"])
        self.assertFalse(stage_b["public_registry_endpoint_enabled"])
        self.assertEqual(
            stage_b["executor_path"],
            "deploy/production/admin_item20_stage_b_private_acr.sh",
        )
        self.assertEqual(
            stage_b["executor_sha256"],
            "0342f9ebadda91a8131930170fbc9ee4d116b58286da1a3049b8f02bfb3fd624",
        )
        self.assertEqual(stage_b["publisher_focused_tests"], "6/6")
        self.assertEqual(stage_b["combined_focused_tests"], "12/12")
        self.assertEqual(
            stage_b["local_complete_readiness_gate"],
            "136/136_once",
        )
        self.assertEqual(stage_b["push_attempt_limit"], 1)
        self.assertTrue(stage_b["native_control_plane_readback_required"])
        self.assertFalse(
            stage_b["production_service_database_public_traffic_mutation_authorized"]
        )
        self.assertFalse(stage_b["custom_ledger_receipt_or_topology_added"])
        self.assertEqual(public_ecr["readiness"]["internal"], "19/29")
        self.assertEqual(public_ecr["readiness"]["public"], "19/38")
        self.assertFalse(public_ecr["readiness"]["credit_added"])
        public_ecr_serialized = json.dumps(public_ecr, ensure_ascii=False)
        self.assertNotRegex(
            public_ecr_serialized,
            r"\b[ictf]-[a-z0-9]{8,}\b",
        )
        self.assertNotRegex(
            public_ecr_serialized,
            r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        )
        self.assertIn(
            "completed the full 103.39 MiB transfer in 26 seconds",
            admin["blocker"],
        )
        self.assertIn("files.pythonhosted.org", admin["blocker"])
        self.assertIn("exact 5335 Admin AMD64 image", admin["blocker"])
        self.assertIn(
            "native control-plane digests agree",
            public_ecr["next_hard_condition"],
        )
        self.assertIn(
            "API-C/API-F health are restored",
            public_ecr["next_hard_condition"],
        )
        api_c = next(
            control
            for control in self.manifest["layers"][1]["controls"]
            if control["id"] == "api_c_current_release"
        )
        self.assertEqual(api_c["status"], "verified")
        self.assertEqual(
            api_c["evidence"],
            gate.API_C_EXPECTED_MANIFEST_EVIDENCE,
        )
        self.assertNotIn("blocker", api_c)
        self.assertNotIn("next_task", api_c)
        api_f = next(
            control
            for control in self.manifest["layers"][1]["controls"]
            if control["id"] == "api_f_current_release"
        )
        self.assertEqual(api_f["status"], "verified")
        self.assertEqual(
            api_f["evidence"],
            gate.API_F_EXPECTED_MANIFEST_EVIDENCE,
        )
        self.assertNotIn("blocker", api_f)
        self.assertNotIn("next_task", api_f)
        managed = next(
            control
            for control in self.manifest["layers"][1]["controls"]
            if control["id"] == "managed_secret_distribution"
        )
        schema = next(
            control
            for control in self.manifest["layers"][1]["controls"]
            if control["id"] == "production_schema_roles"
        )
        immutable = next(
            control
            for control in self.manifest["layers"][1]["controls"]
            if control["id"] == "immutable_release_candidate"
        )
        for ref in (
            "security/vex/b55f118-registry-publication-attestation.json",
            "security/vex/b55f118-registry-release-evidence.json",
            "security/vex/b55f118-registry-release.vex.cdx.json",
            "security/vex/b55f118-registry-release-review.json",
            "tools/verify_b55_registry_release_vex.py",
        ):
            self.assertIn({"kind": "path", "ref": ref}, immutable["evidence"])
        self.assertIn(
            {
                "kind": "path",
                "ref": (
                    "deploy/production/evidence/"
                    "production-schema-role-resume-authority-audit-20260728.json"
                ),
            },
            schema["evidence"],
        )
        self.assertIn(
            {
                "kind": "path",
                "ref": (
                    "deploy/production/evidence/"
                    "production-schema-authority-resolution-plan-20260728.json"
                ),
            },
            schema["evidence"],
        )
        self.assertIn(
            {
                "kind": "path",
                "ref": (
                    "deploy/production/evidence/"
                    "production-schema-roles-v4-rolled-back-20260728.json"
                ),
            },
            schema["evidence"],
        )
        self.assertIn(
            {
                "kind": "path",
                "ref": (
                    "deploy/production/evidence/"
                    "production-schema-role-provider-support-intake-20260728.json"
                ),
            },
            schema["evidence"],
        )
        self.assertIn(
            {
                "kind": "path",
                "ref": (
                    "deploy/production/evidence/"
                    "production-first-launch-role-risk-readonly-unknown-"
                    "20260728.json"
                ),
            },
            schema["evidence"],
        )
        self.assertIn(
            {
                "kind": "path",
                "ref": (
                    "deploy/production/evidence/"
                    "production-first-launch-role-risk-accepted-20260728.json"
                ),
            },
            schema["evidence"],
        )
        self.assertIn(
            {
                "kind": "path",
                "ref": (
                    "deploy/production/evidence/"
                    "production-schema-role-apply-rolled-back-20260728.json"
                ),
            },
            schema["evidence"],
        )
        self.assertIn(
            {
                "kind": "path",
                "ref": (
                    "deploy/production/evidence/"
                    "production-schema-privileged-owner-preflight-verified-"
                    "20260729.json"
                ),
            },
            schema["evidence"],
        )
        self.assertIn(
            {
                "kind": "path",
                "ref": (
                    "deploy/production/evidence/"
                    "production-schema-roles-v5-owner-committed-"
                    "20260729.json"
                ),
            },
            schema["evidence"],
        )
        self.assertEqual(schema["status"], "verified")
        self.assertNotIn("blocker", schema)
        self.assertNotIn("resume_condition", schema)
        self.assertEqual(len(schema["accepted_risks"]), 2)
        self.assertEqual(len(report["accepted_risks"]), 2)
        self.assertIn("production_schema_roles", managed["dependencies"])
        self.assertEqual(managed["status"], "verified")
        self.assertNotIn("blocker", managed)
        self.assertNotIn("next_task", managed)
        self.assertIn(
            {
                "kind": "path",
                "ref": (
                    "deploy/production/evidence/"
                    "production-managed-secret-distribution-verified-"
                    "20260729.json"
                ),
            },
            managed["evidence"],
        )
        self.assertEqual(
            actionable["legal_provider_approval"]["execution_class"],
            "professional_review",
        )
        self.assertNotIn("dns_cutover", actionable)

    def test_current_role_risk_incident_is_unknown_not_accepted(self):
        evidence_path = (
            ROOT
            / "deploy"
            / "production"
            / "evidence"
            / "production-first-launch-role-risk-readonly-unknown-20260728.json"
        )
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

        self.assertEqual(evidence["incident_class"], "CONNECTED_UNKNOWN")
        self.assertEqual(
            evidence["readonly_database_attempt"]["attempt_count"],
            1,
        )
        self.assertEqual(
            evidence["readonly_database_attempt"]["automatic_retry_count"],
            0,
        )
        self.assertEqual(
            evidence["readonly_database_attempt"]["database_outcome"],
            "UNKNOWN",
        )
        self.assertFalse(
            evidence["product_risk_decision"]["accepted_risk_activation"]
        )
        self.assertEqual(
            evidence["readiness"]["accepted_risk_entry_count"],
            0,
        )
        self.assertEqual(
            evidence["cleanup"]["api_c_task_directory_count"],
            0,
        )

    def test_privileged_owner_preflight_is_read_only_verified_and_clean(self):
        evidence_path = (
            ROOT
            / "deploy"
            / "production"
            / "evidence"
            / "production-schema-privileged-owner-preflight-verified-"
            "20260729.json"
        )
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

        self.assertEqual(evidence["status"], "VERIFIED_READ_ONLY_CLEAN")
        audit = evidence["single_database_audit"]
        self.assertEqual(audit["dispatch_count"], 1)
        self.assertEqual(audit["automatic_retry_count"], 0)
        self.assertEqual(audit["incident_class"], "CONNECTED_KNOWN")
        self.assertTrue(audit["transaction_read_only"])
        self.assertTrue(audit["transaction_rolled_back"])
        self.assertEqual(audit["database_write_count"], 0)
        self.assertTrue(audit["result_independently_validated"])
        contract = evidence["verified_contract"]
        self.assertEqual(contract["ledger_count"], 8)
        self.assertEqual(contract["table_count"], 30)
        self.assertEqual(contract["sequence_count"], 5)
        self.assertEqual(contract["new_runtime_role_count"], 0)
        self.assertEqual(contract["task_role_residue_count"], 0)
        cleanup = evidence["cleanup_readback"]
        self.assertEqual(
            (
                cleanup["accounts"],
                cleanup["super_accounts"],
                cleanup["task_accounts"],
            ),
            (3, 1, 0),
        )
        for key in (
            "task_root_count",
            "rsa_private_key_count",
            "ciphertext_count",
            "source_package_count",
            "result_file_count",
            "container_count",
            "cloud_shell_task_file_count",
            "cloud_shell_task_variable_count",
            "rds_public_endpoint_count",
            "public_api_node_count",
            "non_loopback_listener_count",
            "database_write_count",
        ):
            self.assertEqual(cleanup[key], 0, key)

    def test_fresh_role_risk_is_connected_known_and_accepted(self):
        evidence_path = (
            ROOT
            / "deploy"
            / "production"
            / "evidence"
            / "production-first-launch-role-risk-accepted-20260728.json"
        )
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

        self.assertEqual(evidence["incident_class"], "CONNECTED_KNOWN")
        self.assertEqual(
            evidence["database_observation"]["connection_count"],
            1,
        )
        self.assertEqual(
            evidence["database_observation"]["transaction_outcome"],
            "rolled_back",
        )
        self.assertEqual(
            evidence["database_observation"]["database_write_count"],
            0,
        )
        self.assertFalse(
            evidence["legacy_role_graph"]["inherit_option"]
        )
        self.assertEqual(
            evidence["legacy_role_graph"][
                "noteai_app_high_privilege_inheritance_count"
            ],
            0,
        )
        self.assertTrue(
            evidence["policy_assessment"]["accepted_risk_activation"]
        )
        self.assertFalse(
            evidence["policy_assessment"]["verified_fixed"]
        )

    def test_authority_audit_is_preconnect_and_preserves_retry_block(self):
        evidence_path = (
            ROOT
            / "deploy"
            / "production"
            / "evidence"
            / "production-schema-role-resume-authority-audit-20260728.json"
        )
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

        self.assertEqual(evidence["audit_incident_class"], "PRE_CONNECT")
        self.assertEqual(
            evidence["inherited_correction_incident_class"],
            "CONNECTED_KNOWN",
        )
        self.assertEqual(evidence["execution"]["database_connection_count"], 0)
        self.assertEqual(evidence["execution"]["database_transaction_count"], 0)
        self.assertEqual(evidence["execution"]["database_write_count"], 0)
        self.assertFalse(
            evidence["authority_discovery"]["database_retry_authorized"]
        )
        self.assertFalse(
            evidence["resume_boundary"]["database_action_allowed_now"]
        )
        self.assertIn(
            "CREATEROLE",
            evidence["resume_boundary"]["required_authority"],
        )
        self.assertIn(
            "Advice or permission alone",
            evidence["resume_boundary"]["provider_support_boundary"],
        )

    def test_authority_resolution_plan_is_offline_and_opens_only_v4(self):
        evidence_path = (
            ROOT
            / "deploy"
            / "production"
            / "evidence"
            / "production-schema-authority-resolution-plan-20260728.json"
        )
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

        self.assertEqual(
            evidence["status"],
            "REPOSITORY_OFFLINE_VERIFIED",
        )
        self.assertEqual(
            evidence["non_mutating_execution"]["database_connection_count"],
            0,
        )
        self.assertEqual(
            evidence["non_mutating_execution"]["cloud_mutation_count"],
            0,
        )
        self.assertEqual(
            evidence["next_incident"]["incident_id"],
            "PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-V4-001",
        )
        self.assertFalse(evidence["next_incident"]["same_database_action_retry"])
        self.assertEqual(
            evidence["next_incident"]["maximum_schema_transaction_count"],
            1,
        )
        self.assertEqual(
            evidence["next_incident"]["write_ceiling"][
                "accepted_risk_role_changes"
            ],
            0,
        )
        self.assertFalse(
            evidence["next_incident"]["provider_ticket_required"]
        )
        self.assertFalse(
            evidence["stage_safe_executor"]["migration_bytes_changed"]
        )
        self.assertEqual(
            evidence["stage_safe_executor"]["runner_modes"],
            ["prepare", "preflight", "apply", "outcome"],
        )
        self.assertEqual(
            evidence["stage_safe_executor"][
                "database_input_environment_count"
            ],
            0,
        )

    def test_provider_support_intake_stops_before_interactive_contact(self):
        evidence_path = (
            ROOT
            / "deploy"
            / "production"
            / "evidence"
            / "production-schema-role-provider-support-intake-20260728.json"
        )
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

        self.assertEqual(evidence["audit_incident_class"], "PRE_CONNECT")
        self.assertFalse(
            evidence["support_portal_observation"][
                "existing_support_contact_configured"
            ]
        )
        self.assertTrue(
            evidence["support_portal_observation"][
                "contact_verification_required"
            ]
        )
        self.assertEqual(evidence["actions"]["ticket_submit_click_count"], 0)
        self.assertFalse(evidence["actions"]["ticket_created"])
        self.assertEqual(evidence["actions"]["database_connection_count"], 0)
        self.assertEqual(evidence["actions"]["database_write_count"], 0)
        self.assertFalse(
            evidence["minimal_disclosure_incident"]["secret_value_present"]
        )
        self.assertFalse(
            evidence["minimal_disclosure_incident"][
                "persisted_to_repository"
            ]
        )
        self.assertTrue(evidence["cleanup"]["browser_tabs_finalized"])
        self.assertTrue(
            evidence["resume_boundary"][
                "product_owner_interactive_action_required"
            ]
        )

    def test_verified_control_requires_existing_evidence(self):
        broken = copy.deepcopy(self.manifest)
        broken["layers"][0]["controls"][0]["evidence"] = []

        with self.assertRaisesRegex(gate.ManifestError, "verified without evidence"):
            gate.validate_manifest(broken)

        broken = copy.deepcopy(self.manifest)
        broken["layers"][0]["controls"][0]["evidence"] = [
            {"kind": "path", "ref": "/tmp/not-allowed"}
        ]
        with self.assertRaisesRegex(gate.ManifestError, "missing path evidence"):
            gate.validate_manifest(broken)

    def test_verified_api_c_requires_exact_semantic_runtime_evidence(self):
        broken = copy.deepcopy(self.manifest)
        control = next(
            item
            for item in broken["layers"][1]["controls"]
            if item["id"] == "api_c_current_release"
        )
        control["evidence"] = list(reversed(control["evidence"]))
        with self.assertRaisesRegex(
            gate.ManifestError,
            "exact runtime evidence refs required",
        ):
            gate.validate_manifest(broken)

        with mock.patch.object(
            gate,
            "validate_api_c_current_release_evidence",
            return_value=["tampered runtime evidence"],
        ):
            with self.assertRaisesRegex(
                gate.ManifestError,
                "invalid runtime evidence",
            ):
                gate.validate_manifest(copy.deepcopy(self.manifest))

    def test_verified_api_f_requires_exact_semantic_runtime_evidence(self):
        broken = copy.deepcopy(self.manifest)
        control = next(
            item
            for item in broken["layers"][1]["controls"]
            if item["id"] == "api_f_current_release"
        )
        control["evidence"] = list(reversed(control["evidence"]))
        with self.assertRaisesRegex(
            gate.ManifestError,
            "exact runtime evidence refs required",
        ):
            gate.validate_manifest(broken)

        with mock.patch.object(
            gate,
            "validate_api_f_current_release_evidence",
            return_value=["tampered runtime evidence"],
        ):
            with self.assertRaisesRegex(
                gate.ManifestError,
                "invalid runtime evidence",
            ):
                gate.validate_manifest(copy.deepcopy(self.manifest))

    def test_nonverified_controls_require_blocker_and_task(self):
        broken = copy.deepcopy(self.manifest)
        control = next(
            item
            for item in broken["layers"][1]["controls"]
            if item["id"] == "backup_pitr_restore"
        )
        control["status"] = "unverified"
        control["evidence"] = []
        control["blocker"] = "terminal acceptance absent"
        control["next_task"] = "PROD-FIRST-LAUNCH-PITR-RESTORE-001"
        control.pop("blocker")
        with self.assertRaisesRegex(gate.ManifestError, "requires blocker"):
            gate.validate_manifest(broken)

        broken = copy.deepcopy(self.manifest)
        control = next(
            item
            for item in broken["layers"][1]["controls"]
            if item["id"] == "backup_pitr_restore"
        )
        control["status"] = "unverified"
        control["evidence"] = []
        control["blocker"] = "terminal acceptance absent"
        control["next_task"] = "PROD-FIRST-LAUNCH-PITR-RESTORE-001"
        control.pop("next_task")
        with self.assertRaisesRegex(gate.ManifestError, "requires next_task"):
            gate.validate_manifest(broken)

    def test_verified_admin_requires_final_semantic_runtime_evidence(self):
        broken = copy.deepcopy(self.manifest)
        control = next(
            item
            for item in broken["layers"][1]["controls"]
            if item["id"] == "admin_current_release"
        )
        control["evidence"] = [
            item
            for item in control["evidence"]
            if item.get("ref")
            != "tools/verify_admin_current_release_evidence.py"
        ]
        with self.assertRaisesRegex(
            gate.ManifestError,
            "final runtime evidence refs required",
        ):
            gate.validate_manifest(broken)

        with mock.patch.object(
            gate,
            "validate_admin_current_release_evidence",
            return_value=["tampered runtime evidence"],
        ):
            with self.assertRaisesRegex(
                gate.ManifestError,
                "invalid runtime evidence",
            ):
                gate.validate_manifest(copy.deepcopy(self.manifest))

    def test_verified_internal_smoke_requires_semantic_evidence(self):
        candidate = copy.deepcopy(self.manifest)
        control = next(
            item
            for item in candidate["layers"][1]["controls"]
            if item["id"] == "internal_zero_provider_smoke"
        )
        self.assertEqual(control["status"], "verified")
        self.assertEqual(
            {(row["kind"], row["ref"]) for row in control["evidence"]},
            {
                *(
                    ("path", ref)
                    for ref in item27_verifier.REQUIRED_MANIFEST_PATH_REFS
                ),
                *(
                    ("git", ref)
                    for ref in item27_verifier.REQUIRED_MANIFEST_GIT_REFS
                ),
            },
        )
        item26 = next(
            item
            for item in candidate["layers"][1]["controls"]
            if item["id"] == "backup_pitr_restore"
        )
        item26["status"] = "unverified"
        item26["evidence"] = []
        item26["blocker"] = "terminal acceptance absent"
        item26["next_task"] = "PROD-FIRST-LAUNCH-PITR-RESTORE-001"
        with mock.patch.object(gate, "_verify_path", return_value=True):
            with self.assertRaisesRegex(
                gate.ManifestError, "Item26 terminal verification required"
            ):
                gate.validate_manifest(candidate)

        item26["status"] = "verified"
        item26.pop("blocker")
        item26.pop("next_task")
        item26["evidence"] = [
            {
                "kind": "git",
                "ref": "f940106b9f7df0c23ea4a1e67063cfb35bf9927b",
            }
        ]
        with mock.patch.object(gate, "_verify_path", return_value=True):
            with self.assertRaisesRegex(
                gate.ManifestError,
                "backup_pitr_restore: invalid semantic evidence: "
                "original DoD evidence ref mismatch",
            ):
                gate.validate_manifest(candidate)

        item26_acceptance = "a" * 64
        with mock.patch.object(
            gate, "_verify_path", return_value=True
        ), mock.patch.object(
            gate,
            "validate_item26_terminal_evidence",
            return_value=([], item26_acceptance),
        ) as validate_item26, mock.patch.object(
            gate,
            "validate_internal_zero_provider_smoke_evidence",
            return_value=[],
        ) as validate:
            gate.validate_manifest(candidate)
            self.assertEqual(validate_item26.call_count, 2)
            validate.assert_called_once()
            args, kwargs = validate.call_args
            self.assertEqual(args, (control["evidence"],))
            self.assertEqual(kwargs["root"], gate.ROOT)
            self.assertRegex(
                kwargs["expected_item26_terminal_acceptance_sha256"],
                r"^[0-9a-f]{64}$",
            )
            self.assertEqual(
                kwargs["expected_item26_terminal_acceptance_sha256"],
                item26_acceptance,
            )
            self.assertEqual(
                kwargs["expected_readiness"]["internal_verified_before"], 26
            )
            self.assertEqual(
                kwargs["expected_readiness"]["internal_verified_after"], 27
            )
            self.assertEqual(
                kwargs["expected_readiness"]["complete_public_verified_before"],
                26,
            )

        with mock.patch.object(
            gate, "_verify_path", return_value=True
        ), mock.patch.object(
            gate,
            "validate_item26_terminal_evidence",
            return_value=([], item26_acceptance),
        ), mock.patch.object(
            gate,
            "validate_internal_zero_provider_smoke_evidence",
            return_value=["tampered Item27 result"],
        ):
            with self.assertRaisesRegex(
                gate.ManifestError, "invalid semantic evidence"
            ):
                gate.validate_manifest(candidate)

    def test_verified_item26_requires_direct_semantic_evidence(self):
        candidate = copy.deepcopy(self.manifest)
        control = next(
            item
            for item in candidate["layers"][1]["controls"]
            if item["id"] == "backup_pitr_restore"
        )
        control["evidence"] = [
            {
                "kind": "git",
                "ref": "f940106b9f7df0c23ea4a1e67063cfb35bf9927b",
            },
        ]
        with mock.patch.object(gate, "_verify_path", return_value=True):
            with self.assertRaisesRegex(
                gate.ManifestError,
                "backup_pitr_restore: invalid semantic evidence: "
                "original DoD evidence ref mismatch",
            ):
                gate.validate_manifest(candidate)

        tamper_cases = [
            (
                ("latest_reconciliation", "status"),
                "NOT_TERMINAL",
                "latest reconciliation status mismatch",
            ),
            (
                ("latest_reconciliation", "readiness_credit_added"),
                False,
                "latest reconciliation readiness credit mismatch",
            ),
            (
                (
                    "latest_reconciliation",
                    "original_dod_terminal_acceptance_20260823",
                    "capture",
                    "source_manifest_sha256",
                ),
                "0" * 64,
                "capture.source_manifest_sha256 mismatch",
            ),
            (
                (
                    "latest_reconciliation",
                    "original_dod_terminal_acceptance_20260823",
                    "capture",
                    "restored_manifest_semantic_sha256",
                ),
                "1" * 64,
                "capture.restored_manifest_semantic_sha256 mismatch",
            ),
            (
                (
                    "latest_reconciliation",
                    "original_dod_terminal_acceptance_20260823",
                    "capture",
                    "restored_manifest_file_sha256",
                ),
                "2" * 64,
                "capture.restored_manifest_file_sha256 mismatch",
            ),
            (
                (
                    "latest_reconciliation",
                    "original_dod_terminal_acceptance_20260823",
                    "capture",
                    "comparison",
                    "mismatch_codes",
                ),
                ["database_tables"],
                "capture.comparison.mismatch_codes mismatch",
            ),
            (
                (
                    "latest_reconciliation",
                    "original_dod_terminal_acceptance_20260823",
                    "capture",
                    "comparison",
                    "equal_fields",
                ),
                [],
                "capture.comparison.equal_fields mismatch",
            ),
            (
                (
                    "latest_reconciliation",
                    "original_dod_terminal_acceptance_20260823",
                    "capture",
                    "comparison",
                    "content_included",
                ),
                True,
                "capture.comparison.content_included mismatch",
            ),
            (
                (
                    "latest_reconciliation",
                    "original_dod_terminal_acceptance_20260823",
                    "capture",
                    "postgresql_major_version",
                ),
                15,
                "capture.postgresql_major_version mismatch",
            ),
            (
                (
                    "latest_reconciliation",
                    "original_dod_terminal_acceptance_20260823",
                    "capture",
                    "table_count",
                ),
                55,
                "capture.table_count mismatch",
            ),
            (
                (
                    "latest_reconciliation",
                    "original_dod_terminal_acceptance_20260823",
                    "capture",
                    "migration_count",
                ),
                16,
                "capture.migration_count mismatch",
            ),
            (
                (
                    "latest_reconciliation",
                    "original_dod_terminal_acceptance_20260823",
                    "capture",
                    "rls_table_count",
                ),
                18,
                "capture.rls_table_count mismatch",
            ),
            (
                (
                    "latest_reconciliation",
                    "original_dod_terminal_acceptance_20260823",
                    "capture",
                    "database_write_count",
                ),
                1,
                "capture.database_write_count mismatch",
            ),
            (
                (
                    "latest_reconciliation",
                    "original_dod_terminal_acceptance_20260823",
                    "capture",
                    "terminal_transaction",
                ),
                "COMMIT",
                "capture.terminal_transaction mismatch",
            ),
            (
                (
                    "latest_reconciliation",
                    "original_dod_terminal_acceptance_20260823",
                    "cleanup",
                    "active_clone_residue_count",
                ),
                1,
                "cleanup.active_clone_residue_count mismatch",
            ),
            (
                (
                    "latest_reconciliation",
                    "original_dod_terminal_acceptance_20260823",
                    "production_rds_control_plane_temporary_account_delete_count",
                ),
                0,
                "production_rds_control_plane_temporary_account_delete_count mismatch",
            ),
            (
                (
                    "latest_reconciliation",
                    "original_dod_terminal_acceptance_20260823",
                    "capture",
                    "exit_code",
                ),
                False,
                "capture.exit_code mismatch",
            ),
            (
                (
                    "latest_reconciliation",
                    "original_dod_terminal_acceptance_20260823",
                    "production_rds_control_plane_temporary_account_delete_count",
                ),
                True,
                "production_rds_control_plane_temporary_account_delete_count mismatch",
            ),
        ]
        for path, value, error in tamper_cases:
            with self.subTest(path=path):
                tampered = copy.deepcopy(self.manifest)
                target = next(
                    item
                    for item in tampered["layers"][1]["controls"]
                    if item["id"] == "backup_pitr_restore"
                )
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                expected_error = (
                    error
                    if len(path) == 2
                    else "original DoD terminal acceptance mismatch"
                )
                with self.assertRaisesRegex(gate.ManifestError, expected_error):
                    gate.validate_manifest(tampered)

        extra = copy.deepcopy(self.manifest)
        control = next(
            item
            for item in extra["layers"][1]["controls"]
            if item["id"] == "backup_pitr_restore"
        )
        control["latest_reconciliation"][
            "original_dod_terminal_acceptance_20260823"
        ]["unexpected"] = True
        with self.assertRaisesRegex(
            gate.ManifestError,
            "original DoD terminal acceptance mismatch",
        ):
            gate.validate_manifest(extra)

    def test_shared_gate_directly_invokes_item29_verifier_only_when_verified(self):
        candidate = copy.deepcopy(self.manifest)
        capacity = next(
            control
            for control in candidate["layers"][1]["controls"]
            if control["id"] == "capacity_100_jobs"
        )
        capacity["status"] = "unverified"
        capacity["evidence"] = []
        capacity["blocker"] = (
            "No managed 100-job test proves zero loss, duplicate provider "
            "call or overcharge."
        )
        capacity["next_task"] = "PROD-FIRST-LAUNCH-CAPACITY-100-001"
        with mock.patch.object(
            gate, "validate_capacity_100_jobs_evidence"
        ) as validate:
            gate.validate_manifest(candidate)
        validate.assert_not_called()

        candidate = copy.deepcopy(self.manifest)
        capacity = next(
            control
            for control in candidate["layers"][1]["controls"]
            if control["id"] == "capacity_100_jobs"
        )
        with (
            mock.patch.object(gate, "_verify_git_ref", return_value=True),
            mock.patch.object(gate, "_verify_path", return_value=True),
            mock.patch.object(
                gate,
                "validate_capacity_100_jobs_evidence",
                return_value=["direct verifier sentinel"],
            ) as validate,
        ):
            with self.assertRaisesRegex(
                gate.ManifestError, "direct verifier sentinel"
            ):
                gate.validate_manifest(candidate)
        validate.assert_called_once()
        args, kwargs = validate.call_args
        self.assertEqual(args[0], capacity["evidence"])
        self.assertEqual(kwargs["root"], gate.ROOT)
        self.assertEqual(kwargs["expected_readiness"]["internal_verified_after"], 29)

    def test_unknown_and_cyclic_dependencies_fail(self):
        broken = copy.deepcopy(self.manifest)
        broken["layers"][1]["controls"][1]["dependencies"] = ["does_not_exist"]
        with self.assertRaisesRegex(gate.ManifestError, "unknown dependency"):
            gate.validate_manifest(broken)

        broken = copy.deepcopy(self.manifest)
        first = broken["layers"][1]["controls"][1]
        second = broken["layers"][1]["controls"][2]
        first["dependencies"] = [second["id"]]
        second["dependencies"] = [first["id"]]
        with self.assertRaisesRegex(gate.ManifestError, "dependency cycle"):
            gate.validate_manifest(broken)

    def test_malformed_manifest_never_reports_readiness(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "manifest.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(gate.ManifestError, "cannot load"):
                gate.build_report(path)

    def test_manifest_contains_no_absolute_or_secret_evidence(self):
        serialized = json.dumps(self.manifest, ensure_ascii=False)

        self.assertNotIn("password", serialized.lower())
        self.assertNotIn("cookie", serialized.lower())
        for layer in self.manifest["layers"]:
            for control in layer["controls"]:
                for evidence in control["evidence"]:
                    if evidence["kind"] == "path":
                        self.assertFalse(Path(evidence["ref"]).is_absolute())

    def test_only_two_exact_zero_credit_accepted_risks_are_supported(self):
        candidate = copy.deepcopy(self.manifest)
        schema = next(
            control
            for control in candidate["layers"][1]["controls"]
            if control["id"] == "production_schema_roles"
        )
        evidence = [{
            "kind": "path",
            "ref": (
                "deploy/production/evidence/"
                "production-legacy-runtime-role-identity-20260728.json"
            ),
        }]
        common = {
            "status": "accepted_risk",
            "accepted_by": "product_owner",
            "decision_at_utc": "2026-07-28T00:00:00Z",
            "environment": "production",
            "scope": "Exact existing production finding only.",
            "prohibited_expansion": ["No new role or privilege."],
            "actual_effective_privileges": "Recorded by read-only evidence.",
            "compensating_controls": ["Private network and split secrets."],
            "owner": "CTO",
            "review_due": "first_public_launch_plus_30_days",
            "invalidates_on": ["Any role or option drift."],
            "remediation": "Optional provider-assisted post-launch repair.",
            "readiness_credit": 0,
            "migration_verified": False,
            "database_action_authorized": False,
            "not_verified_fixed": True,
            "source_evidence_sha256": (
                "88a0daf878a3b42109c59bd70d8c8820e0aa5e62d80f73aea4c18ef10e607ae0"
            ),
            "evidence": evidence,
        }
        schema["accepted_risks"] = [
            {
                **common,
                "id": (
                    "FIRST-LAUNCH-LEGACY-XHS-ADMIN-"
                    "MEMBERSHIP-20260728"
                ),
                "finding": {
                    "granted_role": "noteai_xhs",
                    "member_role": "noteai_admin",
                    "admin_option": True,
                    "inherit_option": False,
                    "set_option": False,
                },
            },
            {
                **common,
                "id": "FIRST-LAUNCH-LEGACY-APP-INHERIT-20260728",
                "finding": {
                    "role": "noteai_app",
                    "rolinherit": True,
                    "incoming_membership_count": 0,
                    "high_privilege_inheritance_count": 0,
                },
            },
        ]

        gate.validate_manifest(candidate)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "manifest.json"
            path.write_text(json.dumps(candidate), encoding="utf-8")
            report = gate.build_report(path)
        self.assertEqual(len(report["accepted_risks"]), 2)
        self.assertEqual(report["internal_deployment"]["verified"], 29)
        self.assertEqual(report["internal_deployment"]["total"], 29)

        broken = copy.deepcopy(candidate)
        broken["layers"][1]["controls"][2]["accepted_risks"][0][
            "readiness_credit"
        ] = 1
        with self.assertRaisesRegex(
            gate.ManifestError,
            "readiness credit must be zero",
        ):
            gate.validate_manifest(broken)

        broken = copy.deepcopy(candidate)
        broken["layers"][1]["controls"][2]["accepted_risks"][0][
            "finding"
        ]["admin_option"] = False
        with self.assertRaisesRegex(gate.ManifestError, "finding changed"):
            gate.validate_manifest(broken)


if __name__ == "__main__":
    unittest.main()
