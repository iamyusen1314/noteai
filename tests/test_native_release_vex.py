import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_native_release_vex as verifier  # noqa: E402


class NativeReleaseVexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = json.loads(verifier.EVIDENCE_PATH.read_text(encoding="utf-8"))
        cls.vex = json.loads(verifier.VEX_PATH.read_text(encoding="utf-8"))
        cls.review = json.loads(verifier.REVIEW_PATH.read_text(encoding="utf-8"))

    def test_exact_native_release_bundle_passes(self):
        self.assertEqual(
            verifier.validate_documents(self.evidence, self.vex, self.review),
            [],
        )

    def test_all_five_roles_are_bound(self):
        self.assertEqual(set(self.evidence["roles"]), set(verifier.ROLES))
        perl = next(
            item for item in self.vex["vulnerabilities"] if item["id"] == "CVE-2026-13221"
        )
        self.assertEqual(len(perl["affects"]), 5)
        util_linux = next(
            item for item in self.vex["vulnerabilities"] if item["id"] == "CVE-2026-53615"
        )
        self.assertEqual(len(util_linux["affects"]), 45)

    def test_rejects_image_identity_tampering(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["roles"]["payment"]["local_image_id"] = "sha256:" + ("0" * 64)
        errors = verifier.validate_documents(evidence, self.vex, self.review)
        self.assertIn("CycloneDX VEX content differs from exact evidence", errors)
        self.assertIn("review record differs from exact evidence/VEX", errors)

    def test_rejects_registry_digest_claim(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["roles"]["api"]["registry_digest"] = "sha256:" + ("1" * 64)
        errors = verifier.validate_documents(evidence, self.vex, self.review)
        self.assertIn("api: local evidence must not claim a registry digest", errors)

    def test_rejects_raw_finding_suppression(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["scanner"]["vex_applied_to_raw_report"] = True
        errors = verifier.validate_documents(evidence, self.vex, self.review)
        self.assertIn("VEX must not be applied to canonical raw reports", errors)

        evidence = copy.deepcopy(self.evidence)
        evidence["roles"]["xhs-http"]["findings"]["critical"] = 0
        errors = verifier.validate_documents(evidence, self.vex, self.review)
        self.assertIn("xhs-http: exact finding counts changed", errors)

    def test_rejects_missing_bom_link(self):
        vex = copy.deepcopy(self.vex)
        vuln = next(
            item for item in vex["vulnerabilities"] if item["id"] == "CVE-2025-69720"
        )
        vuln["affects"].pop()
        errors = verifier.validate_documents(self.evidence, vex, self.review)
        self.assertIn("CycloneDX VEX content differs from exact evidence", errors)

    def test_rejects_waiver_or_deployment_semantics(self):
        vex = copy.deepcopy(self.vex)
        vex["vulnerabilities"][0]["analysis"]["response"] = ["will_not_fix"]
        errors = verifier.validate_documents(self.evidence, vex, self.review)
        self.assertTrue(any("must not claim a waiver" in item for item in errors))

        evidence = copy.deepcopy(self.evidence)
        evidence["decision"]["deployment_authorization"] = True
        errors = verifier.validate_documents(evidence, self.vex, self.review)
        self.assertIn("decision.deployment_authorization must remain false", errors)

    def test_release_dependency_and_training_environments_remain_separate(self):
        requirements = (ROOT / "model" / "requirements-api.txt").read_text(encoding="utf-8")
        self.assertIn("cryptography==50.0.0", requirements)
        self.assertNotIn("mlflow==", requirements.lower())


if __name__ == "__main__":
    unittest.main()
