import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_cad5ce3_native_release_vex as verifier  # noqa: E402


class Cad5ce3NativeReleaseVexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = json.loads(
            verifier.EVIDENCE_PATH.read_text(encoding="utf-8")
        )
        cls.vex = json.loads(verifier.VEX_PATH.read_text(encoding="utf-8"))
        cls.review = json.loads(verifier.REVIEW_PATH.read_text(encoding="utf-8"))

    def test_exact_successor_bundle_passes(self):
        self.assertEqual(
            verifier.validate_documents(self.evidence, self.vex, self.review),
            [],
        )
        self.assertEqual(
            self.review["evidence_semantic_sha256"],
            verifier.EXPECTED_EVIDENCE_SEMANTIC_SHA256,
        )
        self.assertEqual(
            self.review["vex_semantic_sha256"],
            verifier.EXPECTED_VEX_SEMANTIC_SHA256,
        )

    def test_native_run_and_artifact_archive_are_exact(self):
        workflow = self.evidence["native_workflow"]
        self.assertEqual(workflow["run_id"], 31017791512)
        self.assertEqual(workflow["job_id"], 92346323999)
        self.assertEqual(workflow["attempt"], 1)
        self.assertEqual(workflow["artifact"], verifier.EXPECTED_ARTIFACT_BINDING)
        self.assertEqual(
            workflow["artifact"]["archive_digest_kind"],
            "github_actions_artifact_archive_sha256",
        )

    def test_five_local_images_and_zero_cryptography_findings_are_bound(self):
        self.assertEqual(set(self.evidence["roles"]), set(verifier.ROLES))
        for role in verifier.ROLES:
            role_data = self.evidence["roles"][role]
            self.assertIsNone(role_data["registry_digest"])
            self.assertEqual(
                role_data["findings"],
                verifier.EXPECTED_FINDINGS,
            )
        self.assertEqual(len(self.evidence["vulnerability_rows_per_role"]), 23)
        self.assertNotIn(
            "cryptography",
            {row["package"] for row in self.evidence["vulnerability_rows_per_role"]},
        )

    def test_cyclonedx_binds_only_twelve_debian_dispositions(self):
        self.assertEqual(len(self.vex["vulnerabilities"]), 12)
        self.assertEqual(
            sum(len(item["affects"]) for item in self.vex["vulnerabilities"]),
            115,
        )
        self.assertEqual(
            {item["analysis"]["state"] for item in self.vex["vulnerabilities"]},
            {"not_affected"},
        )
        self.assertFalse(
            any("response" in item["analysis"] for item in self.vex["vulnerabilities"])
        )

    def test_rejects_artifact_or_image_identity_tampering(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["native_workflow"]["artifact"]["archive_digest"] = (
            "sha256:" + ("0" * 64)
        )
        errors = verifier.validate_documents(evidence, self.vex, self.review)
        self.assertIn("GitHub native artifact binding changed", errors)
        self.assertIn("review record differs from exact evidence/VEX", errors)

        evidence = copy.deepcopy(self.evidence)
        evidence["roles"]["ai-worker"]["local_image_id"] = "sha256:" + ("1" * 64)
        errors = verifier.validate_documents(evidence, self.vex, self.review)
        self.assertIn("ai-worker: immutable local image ID mismatch", errors)
        self.assertIn("CycloneDX VEX content differs from exact evidence", errors)

        evidence = copy.deepcopy(self.evidence)
        evidence["roles"]["api"]["raw_reports"]["secret_sha256"] = "0" * 64
        errors = verifier.validate_documents(evidence, self.vex, self.review)
        self.assertIn("api: immutable Secret report hash mismatch", errors)

    def test_rejects_suppression_registry_or_dependency_drift(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["scanner"]["vex_applied_to_raw_report"] = True
        errors = verifier.validate_documents(evidence, self.vex, self.review)
        self.assertIn("VEX must not be applied to canonical raw reports", errors)

        evidence = copy.deepcopy(self.evidence)
        evidence["roles"]["api"]["registry_digest"] = "sha256:" + ("2" * 64)
        errors = verifier.validate_documents(evidence, self.vex, self.review)
        self.assertIn("api: local evidence must not claim a registry digest", errors)

        evidence = copy.deepcopy(self.evidence)
        evidence["roles"]["payment"]["findings"]["cryptography_version"] = "48.0.1"
        errors = verifier.validate_documents(evidence, self.vex, self.review)
        self.assertIn("payment: exact finding counts changed", errors)

    def test_release_delta_is_only_the_security_dependency_pin(self):
        delta = self.evidence["release_delta"]
        self.assertEqual(
            delta["prior_application_revision"],
            "0149888d16468c8e8ea055e62ce0aa5d56a28971",
        )
        self.assertEqual(
            delta["image_context_changed_paths"],
            ["model/requirements-api.txt"],
        )
        self.assertNotEqual(
            delta["prior_blob_sha256"]["model/requirements-api.txt"],
            delta["release_blob_sha256"]["model/requirements-api.txt"],
        )

    def test_exact_durable_ai_systemd_contract_is_bound(self):
        verifier._validate_durable_ai_systemd_contract()
        source_hashes = self.evidence["source_constraints"]["release_blob_sha256"]
        self.assertEqual(
            set(verifier.DURABLE_AI_SYSTEMD_PATHS),
            set(source_hashes) & set(verifier.DURABLE_AI_SYSTEMD_PATHS),
        )


if __name__ == "__main__":
    unittest.main()
