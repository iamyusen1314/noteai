import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_api_c_current_release_evidence as verifier  # noqa: E402


class ApiCCurrentReleaseEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = json.loads(
            verifier.EVIDENCE_PATH.read_text(encoding="utf-8")
        )

    def assertHasError(self, evidence, expected):
        errors = verifier.validate_document(evidence)
        self.assertTrue(
            any(expected in error for error in errors),
            f"{expected!r} missing from {errors}",
        )

    def test_exact_evidence_passes(self):
        self.assertEqual(verifier.validate_document(self.evidence), [])
        self.assertEqual(
            verifier.semantic_sha256(self.evidence),
            verifier.EXPECTED_SEMANTIC_SHA256,
        )
        self.assertFalse(
            self.evidence["source_binding"]["stage_b_decision_preserved"][
                "deployment_authorization"
            ]
        )
        self.assertFalse(
            self.evidence["readiness"]["public_launch_authorized"]
        )
        self.assertFalse(
            self.evidence["readiness"][
                "full_system_failure_rollback_verified"
            ]
        )

    def test_rejects_revision_manifest_or_local_image_drift(self):
        cases = (
            ("application_revision", "0" * 40),
            ("registry_manifest_digest", "sha256:" + "0" * 64),
            ("config_image_id", "sha256:" + "1" * 64),
        )
        for field, value in cases:
            with self.subTest(field=field):
                evidence = copy.deepcopy(self.evidence)
                evidence["source_binding"][field] = value
                self.assertHasError(evidence, "source identity mismatch")

    def test_rejects_attempt_deletion_reordering_or_result_rewrite(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["attempt_history"].pop(0)
        self.assertHasError(evidence, "attempt history order mismatch")

        evidence = copy.deepcopy(self.evidence)
        evidence["attempt_history"][2], evidence["attempt_history"][3] = (
            evidence["attempt_history"][3],
            evidence["attempt_history"][2],
        )
        self.assertHasError(evidence, "attempt history order mismatch")

        evidence = copy.deepcopy(self.evidence)
        evidence["attempt_history"][4]["result"] = "PASS"
        self.assertHasError(evidence, "attempt result history mismatch")

    def test_rejects_missing_rollback_or_canary_count_rewrite(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["attempt_history"][4]["rollback_result"] = "FAILED"
        self.assertHasError(
            evidence,
            "mutating failed attempt missing successful rollback",
        )

        evidence = copy.deepcopy(self.evidence)
        evidence["attempt_aggregates"]["canary_start_count"] = 2
        self.assertHasError(evidence, "attempt aggregate mismatch")

        evidence = copy.deepcopy(self.evidence)
        evidence["canary_acceptance"]["generation_count"] = 2
        self.assertHasError(evidence, "canary acceptance mismatch")

    def test_rejects_non_independent_or_failed_postcheck(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["independent_postcheck"]["separate_read_only_dispatch"] = False
        self.assertHasError(evidence, "independent postcheck mismatch")

        evidence = copy.deepcopy(self.evidence)
        evidence["independent_postcheck"][
            "final_assertion_failure_count"
        ] = 1
        self.assertHasError(evidence, "independent postcheck mismatch")

    def test_rejects_connected_unknown_or_database_write(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["attempt_history"][10]["incident_class"] = "CONNECTED_UNKNOWN"
        self.assertHasError(evidence, "connected unknown attempt forbidden")

        evidence = copy.deepcopy(self.evidence)
        evidence["database_runtime_postcheck"]["database_write_count"] = 1
        self.assertHasError(evidence, "database postcheck mismatch")

    def test_rejects_cleanup_admin_or_api_f_regression(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["cleanup"]["canary_container_count"] = 1
        self.assertHasError(evidence, "final cleanup residue mismatch")

        evidence = copy.deepcopy(self.evidence)
        evidence["final_non_regression"]["api_c_admin"][
            "container_identity_unchanged"
        ] = False
        self.assertHasError(evidence, "Admin non-regression mismatch")

        evidence = copy.deepcopy(self.evidence)
        evidence["final_non_regression"]["api_f_api"][
            "unit_sha256_after"
        ] = "0" * 64
        self.assertHasError(evidence, "API-F non-regression mismatch")

    def test_rejects_object_provider_or_public_mutation(self):
        for field in (
            "object_write_count",
            "provider_call_count",
            "public_traffic_change_count",
        ):
            with self.subTest(field=field):
                evidence = copy.deepcopy(self.evidence)
                evidence["mutation_counters"][field] = 1
                self.assertHasError(
                    evidence,
                    "mutation counters must remain zero",
                )

    def test_rejects_stage_b_authorization_or_binding_rewrite(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["source_binding"]["stage_b_decision_preserved"][
            "deployment_authorization"
        ] = True
        self.assertHasError(
            evidence,
            "Stage B decision preservation mismatch",
        )

        evidence = copy.deepcopy(self.evidence)
        evidence["source_binding"]["registry_bundle"][0]["sha256"] = "0" * 64
        self.assertHasError(evidence, "registry bundle binding mismatch")


if __name__ == "__main__":
    unittest.main()
