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
        self.assertEqual(report["internal_deployment"]["verified"], 19)
        self.assertEqual(report["internal_deployment"]["total"], 29)
        self.assertEqual(report["internal_deployment"]["percentage"], 66)
        self.assertFalse(report["internal_deployment"]["passed"])
        self.assertEqual(report["complete_public_launch"]["verified"], 19)
        self.assertEqual(report["complete_public_launch"]["total"], 38)
        self.assertEqual(report["complete_public_launch"]["percentage"], 50)
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
        self.assertEqual(
            actionable["admin_current_release"]["status"],
            "unverified",
        )
        self.assertEqual(
            actionable["admin_current_release"]["next_task"],
            "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001",
        )
        self.assertEqual(
            actionable["admin_current_release"]["execution_class"],
            "authenticated_production",
        )
        admin = next(
            control
            for control in self.manifest["layers"][1]["controls"]
            if control["id"] == "admin_current_release"
        )
        self.assertEqual(admin["status"], "unverified")
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
            ],
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
            if item["id"] == "admin_current_release"
        )
        control.pop("blocker")
        with self.assertRaisesRegex(gate.ManifestError, "requires blocker"):
            gate.validate_manifest(broken)

        broken = copy.deepcopy(self.manifest)
        control = next(
            item
            for item in broken["layers"][1]["controls"]
            if item["id"] == "admin_current_release"
        )
        control.pop("next_task")
        with self.assertRaisesRegex(gate.ManifestError, "requires next_task"):
            gate.validate_manifest(broken)

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
        self.assertEqual(report["internal_deployment"]["verified"], 19)
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
