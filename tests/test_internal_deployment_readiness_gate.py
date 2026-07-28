import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


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
        self.assertEqual(report["internal_deployment"]["verified"], 14)
        self.assertEqual(report["internal_deployment"]["total"], 29)
        self.assertEqual(report["internal_deployment"]["percentage"], 48)
        self.assertFalse(report["internal_deployment"]["passed"])
        self.assertEqual(report["complete_public_launch"]["verified"], 14)
        self.assertEqual(report["complete_public_launch"]["total"], 38)
        self.assertEqual(report["complete_public_launch"]["percentage"], 37)
        self.assertFalse(report["complete_public_launch"]["passed"])

    def test_current_schema_role_correction_is_blocked_fail_closed(self):
        report = gate.build_report()
        actionable = {item["id"]: item for item in report["actionable"]}

        self.assertEqual(
            [item["id"] for item in report["blocked"]],
            ["production_schema_roles"],
        )
        self.assertNotIn("immutable_release_candidate", actionable)
        self.assertNotIn("production_readonly_preflight", actionable)
        self.assertIsNone(report["next_safe_task"])
        self.assertEqual(
            actionable["production_schema_roles"]["status"],
            "blocked",
        )
        self.assertEqual(
            actionable["production_schema_roles"]["next_task"],
            "PROD-FIRST-LAUNCH-LEGACY-RUNTIME-ROLE-CORRECTION-001",
        )
        self.assertEqual(
            actionable["production_schema_roles"]["execution_class"],
            "authenticated_production",
        )
        self.assertEqual(
            actionable["managed_secret_distribution"]["next_task"],
            "PROD-FIRST-LAUNCH-MANAGED-SECRETS-001",
        )
        self.assertEqual(
            actionable["legal_provider_approval"]["execution_class"],
            "professional_review",
        )
        self.assertNotIn("dns_cutover", actionable)

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

    def test_nonverified_controls_require_blocker_and_task(self):
        broken = copy.deepcopy(self.manifest)
        control = broken["layers"][1]["controls"][2]
        control.pop("blocker")
        with self.assertRaisesRegex(gate.ManifestError, "requires blocker"):
            gate.validate_manifest(broken)

        broken = copy.deepcopy(self.manifest)
        control = broken["layers"][1]["controls"][2]
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


if __name__ == "__main__":
    unittest.main()
