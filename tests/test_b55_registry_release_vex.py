import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_b55_registry_release_vex as verifier  # noqa: E402


class B55RegistryReleaseVexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.attestation = json.loads(
            verifier.ATTESTATION_PATH.read_text(encoding="utf-8")
        )
        cls.evidence = json.loads(verifier.EVIDENCE_PATH.read_text(encoding="utf-8"))
        cls.vex = json.loads(verifier.VEX_PATH.read_text(encoding="utf-8"))
        cls.review = json.loads(verifier.REVIEW_PATH.read_text(encoding="utf-8"))

    def test_exact_publication_attestation_passes(self):
        self.assertEqual(verifier.validate_attestation(self.attestation), [])
        self.assertEqual(
            self.evidence["publication_attestation_binding"],
            verifier._attestation_binding(),
        )

    def test_exact_registry_bundle_passes(self):
        self.assertEqual(
            verifier.validate_documents(self.evidence, self.vex, self.review),
            [],
        )

    def test_exact_tags_and_three_way_digest_bindings(self):
        roles = self.evidence["roles"]
        self.assertEqual(set(roles), set(verifier.ROLES))
        digests = set()
        local_ids = set()
        for role_name in verifier.ROLES:
            role = roles[role_name]
            self.assertEqual(role["tag"], verifier.EXPECTED_TAGS[role_name])
            self.assertEqual(
                {
                    role["push_digest"],
                    role["manifest_digest"],
                    role["control_plane_digest"],
                    role["registry_digest"],
                },
                {role["registry_digest"]},
            )
            self.assertEqual(role["config_digest"], role["local_image_id"])
            self.assertEqual(role["push"]["invocations"], 1)
            self.assertEqual(role["push"]["manual_retries"], 0)
            digests.add(role["registry_digest"])
            local_ids.add(role["local_image_id"])
        self.assertEqual(len(digests), 5)
        self.assertEqual(len(local_ids), 5)
        self.assertTrue(digests.isdisjoint(local_ids))

    def test_raw_findings_and_bom_links_remain_unsuppressed(self):
        for role in self.evidence["roles"].values():
            self.assertEqual(role["findings"], verifier.EXPECTED_FINDINGS)
            self.assertFalse(role["raw_gate_passed"])
        self.assertEqual(
            sum(len(item["affects"]) for item in self.vex["vulnerabilities"]),
            115,
        )

    def test_rejects_tag_or_digest_tampering(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["roles"]["api"]["tag"] = "git-b55f118-amd64-admin-r1"
        errors = verifier.validate_documents(evidence, self.vex, self.review)
        self.assertIn("api: exact immutable tag mismatch", errors)
        self.assertIn("b55 registry evidence semantic hash mismatch", errors)

        evidence = copy.deepcopy(self.evidence)
        evidence["roles"]["admin"]["control_plane_digest"] = evidence["roles"][
            "api"
        ]["registry_digest"]
        errors = verifier.validate_documents(evidence, self.vex, self.review)
        self.assertIn("admin: three-way registry digest mismatch", errors)

    def test_rejects_retry_cleanup_or_deployment_authorization(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["roles"]["payment"]["push"]["manual_retries"] = 1
        errors = verifier.validate_documents(evidence, self.vex, self.review)
        self.assertIn("payment: push invocation evidence mismatch", errors)

        evidence = copy.deepcopy(self.evidence)
        evidence["cleanup"]["publisher_role_exists"] = True
        errors = verifier.validate_documents(evidence, self.vex, self.review)
        self.assertIn("b55 registry cleanup evidence mismatch", errors)

        evidence = copy.deepcopy(self.evidence)
        evidence["decision"]["deployment_authorization"] = True
        errors = verifier.validate_documents(evidence, self.vex, self.review)
        self.assertIn(
            "b55 registry decision.deployment_authorization must remain false",
            errors,
        )

    def test_retention_is_secret_free_and_canary_remains_separate(self):
        retained = self.evidence["retained_publication_evidence"]
        self.assertEqual(retained, verifier.EXPECTED_RETAINED_EVIDENCE)
        self.assertEqual(retained["category"], "registry_publication_files")
        self.assertEqual(retained["forbidden_credential_matches"], 0)
        self.assertTrue(
            self.evidence["decision"][
                "production_private_registry_path_restored"
            ]
        )
        self.assertFalse(self.evidence["decision"]["api_c_canary_completed"])
        self.assertFalse(self.evidence["decision"]["deployment_authorization"])

    def test_rejects_independent_digest_observation_tampering(self):
        attestation = copy.deepcopy(self.attestation)
        attestation["roles"]["api"]["observed_config_digest"] = attestation[
            "roles"
        ]["admin"]["observed_config_digest"]
        errors = verifier.validate_attestation(attestation)
        self.assertIn("api: independent config digest mismatch", errors)
        self.assertIn("api: independent digest observations diverge", errors)

        attestation = copy.deepcopy(self.attestation)
        attestation["roles"]["api"]["observed_push_digest"] = attestation["roles"][
            "admin"
        ]["observed_push_digest"]
        errors = verifier.validate_attestation(attestation)
        self.assertIn("api: independent push digest mismatch", errors)
        self.assertIn("api: independent digest observations diverge", errors)

        attestation = copy.deepcopy(self.attestation)
        attestation["roles"]["api"]["observed_manifest_digest"] = attestation[
            "roles"
        ]["admin"]["observed_manifest_digest"]
        errors = verifier.validate_attestation(attestation)
        self.assertIn("api: independent manifest digest mismatch", errors)
        self.assertIn("api: independent digest observations diverge", errors)

    def test_rejects_stage_a_trivy_retention_or_canary_tampering(self):
        attestation = copy.deepcopy(self.attestation)
        attestation["stage_a"]["raw_file_count"] = 42
        self.assertIn(
            "b55 publication attestation Stage A binding mismatch",
            verifier.validate_attestation(attestation),
        )

        attestation = copy.deepcopy(self.attestation)
        attestation["scanner_cache"]["database_sha256"] = "0" * 64
        self.assertIn(
            "b55 publication attestation Trivy cache mismatch",
            verifier.validate_attestation(attestation),
        )

        attestation = copy.deepcopy(self.attestation)
        attestation["retained_publication_evidence"]["file_count"] = 18
        self.assertIn(
            "b55 publication attestation retention mismatch",
            verifier.validate_attestation(attestation),
        )

        attestation = copy.deepcopy(self.attestation)
        attestation["scope"]["api_c_canary_completed"] = True
        self.assertIn(
            "b55 publication attestation scope mismatch",
            verifier.validate_attestation(attestation),
        )

    def test_rejects_vex_waiver_or_missing_bom_link(self):
        vex = copy.deepcopy(self.vex)
        vex["vulnerabilities"][0]["analysis"]["response"] = ["will_not_fix"]
        vex["vulnerabilities"][1]["affects"].pop()
        errors = verifier.validate_documents(self.evidence, vex, self.review)
        self.assertIn("b55 registry VEX differs from exact evidence", errors)
        self.assertTrue(
            any("invalid b55 registry VEX disposition" in item for item in errors)
        )
        self.assertIn("b55 registry VEX BOM-Link count mismatch", errors)


if __name__ == "__main__":
    unittest.main()
