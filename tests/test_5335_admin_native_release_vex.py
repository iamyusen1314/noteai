import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_5335_admin_native_release_vex as verifier  # noqa: E402


class Admin5335NativeReleaseVexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = json.loads(verifier.EVIDENCE_PATH.read_text(encoding="utf-8"))
        cls.vex = json.loads(verifier.VEX_PATH.read_text(encoding="utf-8"))
        cls.review = json.loads(verifier.REVIEW_PATH.read_text(encoding="utf-8"))

    def test_exact_admin_only_bundle_passes(self):
        self.assertEqual(
            verifier.validate_documents(self.evidence, self.vex, self.review),
            [],
        )

    def test_exact_controller_and_eleven_file_contract_are_bound(self):
        self.assertEqual(set(self.evidence["roles"]), {"admin"})
        self.assertEqual(
            self.evidence["native_workflow"]["control_commit"],
            verifier.CONTROL_COMMIT,
        )
        self.assertEqual(
            self.evidence["native_workflow"]["request_sha256"],
            verifier.REQUEST_SHA256,
        )
        self.assertEqual(
            self.evidence["github_readonly_receipt"]["sha256"],
            verifier.GITHUB_RECEIPT_SHA256,
        )
        self.assertEqual(
            self.evidence["admin_control"]["workflow_sha256"],
            verifier.WORKFLOW_SHA256,
        )
        self.assertEqual(
            self.evidence["artifact_contract"]["file_sha256"],
            verifier.EXPECTED_ARTIFACT_SHA256,
        )
        self.assertEqual(self.evidence["artifact_contract"]["file_count"], 11)
        request = self.evidence["admin_control"]["request"]
        for authorization in (
            "registry_publication_authorized",
            "deployment_authorized",
            "database_authorized",
            "service_mutation_authorized",
            "public_traffic_authorized",
        ):
            self.assertIs(request[authorization], False)

    def test_release_delta_is_only_truthful_crawler_default(self):
        self.assertEqual(
            self.evidence["release_delta"]["image_context_changed_paths"],
            ["model/crawler_config.json"],
        )
        crawler = json.loads(
            verifier._git_blob(
                verifier.RELEASE_COMMIT,
                "model/crawler_config.json",
            )
        )
        self.assertIs(crawler["enabled"], False)
        self.assertIsNone(crawler["last_run"])

    def test_fresh_admin_identity_is_not_a_b55_identity(self):
        separation = self.evidence["historical_identity_separation"]
        self.assertTrue(separation["all_distinct_from_fresh"])
        self.assertFalse(separation["historical_registry_authorization_reused"])
        self.assertNotIn(
            separation["fresh_local_image_id"],
            separation["historical_b55_identities"].values(),
        )

    def test_single_role_vex_has_exact_bom_links(self):
        self.assertEqual(len(self.vex["components"]), 1)
        self.assertEqual(self.vex["components"][0]["name"], "admin-runtime")
        perl = next(
            item for item in self.vex["vulnerabilities"] if item["id"] == "CVE-2026-13221"
        )
        self.assertEqual(len(perl["affects"]), 1)
        util_linux = next(
            item for item in self.vex["vulnerabilities"] if item["id"] == "CVE-2026-53615"
        )
        self.assertEqual(len(util_linux["affects"]), 9)

    def test_rejects_controller_artifact_or_identity_tampering(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["admin_control"]["request_sha256"] = "0" * 64
        errors = verifier.validate_documents(evidence, self.vex, self.review)
        self.assertIn("Admin controller contract changed", errors)

        evidence = copy.deepcopy(self.evidence)
        evidence["artifact_contract"]["file_count"] = 43
        errors = verifier.validate_documents(evidence, self.vex, self.review)
        self.assertIn("Admin eleven-file artifact contract changed", errors)

        evidence = copy.deepcopy(self.evidence)
        evidence["github_readonly_receipt"]["run_id"] = 0
        errors = verifier.validate_documents(evidence, self.vex, self.review)
        self.assertIn("Admin GitHub read-only receipt changed", errors)

        evidence = copy.deepcopy(self.evidence)
        evidence["roles"]["admin"]["local_image_id"] = "sha256:" + ("1" * 64)
        errors = verifier.validate_documents(evidence, self.vex, self.review)
        self.assertIn("admin: immutable local image ID mismatch", errors)

    def test_rejects_any_mutation_authorization(self):
        for key in (
            "registry_publication_authorization",
            "deployment_authorization",
            "database_authorization",
            "service_mutation_authorization",
            "public_traffic_authorization",
        ):
            evidence = copy.deepcopy(self.evidence)
            evidence["decision"][key] = True
            errors = verifier.validate_documents(evidence, self.vex, self.review)
            self.assertIn(f"decision.{key} must remain false", errors)


if __name__ == "__main__":
    unittest.main()
