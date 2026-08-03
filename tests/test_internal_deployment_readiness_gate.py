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
