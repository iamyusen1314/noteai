import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_registry_release_vex as verifier  # noqa: E402


class RegistryReleaseVexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = json.loads(verifier.EVIDENCE_PATH.read_text(encoding="utf-8"))
        cls.vex = json.loads(verifier.VEX_PATH.read_text(encoding="utf-8"))
        cls.review = json.loads(verifier.REVIEW_PATH.read_text(encoding="utf-8"))

    def test_exact_registry_bundle_passes(self):
        self.assertEqual(
            verifier.validate_documents(self.evidence, self.vex, self.review),
            [],
        )

    def test_five_roles_have_unique_registry_digests(self):
        roles = self.evidence["roles"]
        self.assertEqual(set(roles), set(verifier.ROLES))
        digests = {role["registry_digest"] for role in roles.values()}
        local_ids = {role["local_image_id"] for role in roles.values()}
        self.assertEqual(len(digests), 5)
        self.assertTrue(digests.isdisjoint(local_ids))

    def test_registry_and_github_builder_identities_remain_separate(self):
        source = verifier._expected_source()
        for role_name in verifier.ROLES:
            self.assertNotEqual(
                self.evidence["roles"][role_name]["local_image_id"],
                source["roles"][role_name]["local_image_id"],
            )

    def test_raw_findings_and_bom_links_remain_unsuppressed(self):
        for role in self.evidence["roles"].values():
            self.assertEqual(role["findings"], verifier.EXPECTED_FINDINGS)
            self.assertFalse(role["raw_gate_passed"])
        self.assertEqual(
            sum(len(item["affects"]) for item in self.vex["vulnerabilities"]),
            115,
        )

    def test_rejects_digest_or_cleanup_tampering(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["roles"]["admin"]["registry_digest"] = evidence["roles"]["api"][
            "registry_digest"
        ]
        errors = verifier.validate_documents(evidence, self.vex, self.review)
        self.assertIn("registry digests are not unique", errors)
        self.assertIn("registry evidence semantic hash mismatch", errors)

        evidence = copy.deepcopy(self.evidence)
        evidence["cleanup"]["publisher_role_exists"] = True
        errors = verifier.validate_documents(evidence, self.vex, self.review)
        self.assertIn("registry cleanup evidence mismatch", errors)

    def test_rejects_suppression_or_deployment_authorization(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["roles"]["xhs-http"]["findings"]["critical"] = 0
        errors = verifier.validate_documents(evidence, self.vex, self.review)
        self.assertIn("xhs-http: registry finding counts mismatch", errors)

        evidence = copy.deepcopy(self.evidence)
        evidence["decision"]["deployment_authorization"] = True
        errors = verifier.validate_documents(evidence, self.vex, self.review)
        self.assertIn(
            "registry decision.deployment_authorization must remain false",
            errors,
        )

    def test_rejects_vex_waiver_or_missing_bom_link(self):
        vex = copy.deepcopy(self.vex)
        vex["vulnerabilities"][0]["analysis"]["response"] = ["will_not_fix"]
        vex["vulnerabilities"][1]["affects"].pop()
        errors = verifier.validate_documents(self.evidence, vex, self.review)
        self.assertIn("registry VEX differs from exact evidence", errors)
        self.assertTrue(any("invalid registry VEX disposition" in item for item in errors))
        self.assertIn("registry VEX BOM-Link count mismatch", errors)

    def test_scope_records_publication_without_deployment_or_writes(self):
        decision = self.evidence["decision"]
        self.assertTrue(decision["acr_push_completed"])
        self.assertTrue(decision["control_plane_tag_digest_binding_verified"])
        self.assertTrue(decision["temporary_publication_access_cleaned"])
        self.assertFalse(decision["production_exception"])
        self.assertFalse(decision["deployment_authorization"])
        self.assertEqual(decision["provider_calls"], 0)
        self.assertEqual(decision["business_writes"], 0)
        self.assertEqual(decision["services_restarted_or_redeployed"], 0)


if __name__ == "__main__":
    unittest.main()
