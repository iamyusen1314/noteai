import copy
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_current_release_evidence as verifier  # noqa: E402


class AdminCurrentReleaseEvidenceTests(unittest.TestCase):
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
            self.evidence["readiness"]["internal_verified_after"], 20
        )
        self.assertFalse(
            self.evidence["final_acceptance"]["public_launch_authorized"]
        )

    def test_rejects_source_or_runtime_drift(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["source_binding"]["config_image_id"] = "sha256:" + "0" * 64
        self.assertHasError(evidence, "source identity mismatch")

        evidence = copy.deepcopy(self.evidence)
        evidence["implementation"]["runtime_sha256"] = "0" * 64
        self.assertHasError(evidence, "implementation binding mismatch")

        evidence = copy.deepcopy(self.evidence)
        evidence["dependency_evidence"][
            "api_f_current_release_sha256"
        ] = "0" * 64
        self.assertHasError(evidence, "dependency evidence mismatch")

    def test_rejects_mode_deletion_reordering_or_retry(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["ordered_modes"].pop(2)
        self.assertHasError(evidence, "mode order mismatch")

        evidence = copy.deepcopy(self.evidence)
        evidence["ordered_modes"][0], evidence["ordered_modes"][1] = (
            evidence["ordered_modes"][1],
            evidence["ordered_modes"][0],
        )
        self.assertHasError(evidence, "mode order mismatch")

        evidence = copy.deepcopy(self.evidence)
        evidence["ordered_modes"][3]["automatic_retry_count"] = 1
        self.assertHasError(evidence, "session-open: terminal result mismatch")

    def test_rejects_acl_session_or_cleanup_drift(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["ordered_modes"][2]["table_mismatch_count"] = 1
        self.assertHasError(evidence, "acl-audit: acceptance mismatch")

        evidence = copy.deepcopy(self.evidence)
        evidence["ordered_modes"][3]["database_business_write_count"] = 1
        self.assertHasError(evidence, "session-open: acceptance mismatch")

        evidence = copy.deepcopy(self.evidence)
        evidence["ordered_modes"][8]["canary_container_count"] = 1
        self.assertHasError(evidence, "cleanup: acceptance mismatch")

        evidence = copy.deepcopy(self.evidence)
        evidence["final_temp_cleanup"]["v4_stage_root_count"] = 1
        self.assertHasError(evidence, "final temporary cleanup mismatch")

    def test_rejects_peer_postcheck_or_readiness_drift(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["independent_postchecks"]["api_f"]["loopback_only"] = False
        self.assertHasError(evidence, "API-F independent postcheck mismatch")

        evidence = copy.deepcopy(self.evidence)
        evidence["readiness"]["internal_verified_after"] = 21
        self.assertHasError(evidence, "readiness transition mismatch")

    def test_stage_b_dependency_is_fail_closed(self):
        broken = copy.deepcopy(
            json.loads(verifier.STAGE_B_PATH.read_text(encoding="utf-8"))
        )
        broken["exact_one_publication"]["published_count"] = 0
        with mock.patch.object(verifier, "_load", return_value=broken):
            errors = verifier.validate_document(self.evidence)
        self.assertIn("Stage B publication dependency mismatch", errors)


if __name__ == "__main__":
    unittest.main()
