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

    def test_current_schema_role_risk_is_accepted_but_schema_is_blocked(self):
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
            "PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-AUTHORITY-RESOLUTION-002",
        )
        self.assertEqual(
            actionable["production_schema_roles"]["execution_class"],
            "authenticated_production",
        )
        self.assertNotIn("managed_secret_distribution", actionable)
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
        self.assertIn("ACCEPTED_RISK", schema["blocker"])
        self.assertIn(
            "never retry that database action",
            schema["resume_condition"],
        )
        self.assertEqual(len(schema["accepted_risks"]), 2)
        self.assertEqual(len(report["accepted_risks"]), 2)
        self.assertIn("production_schema_roles", managed["dependencies"])
        self.assertEqual(
            managed["next_task"],
            "PROD-FIRST-LAUNCH-MANAGED-SECRETS-001",
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
        self.assertEqual(report["internal_deployment"]["verified"], 14)
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
