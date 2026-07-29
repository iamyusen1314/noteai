import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_b55_native_release_vex as verifier  # noqa: E402


class B55NativeReleaseVexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = json.loads(verifier.EVIDENCE_PATH.read_text(encoding="utf-8"))
        cls.vex = json.loads(verifier.VEX_PATH.read_text(encoding="utf-8"))
        cls.review = json.loads(verifier.REVIEW_PATH.read_text(encoding="utf-8"))

    def test_exact_bundle_passes(self):
        self.assertEqual(
            verifier.validate_documents(self.evidence, self.vex, self.review),
            [],
        )

    def test_release_delta_is_narrow_and_exact(self):
        self.assertEqual(
            self.evidence["release_delta"]["image_context_changed_paths"],
            list(verifier.EXPECTED_IMAGE_CONTEXT_DELTA),
        )
        self.assertFalse(self.evidence["decision"]["deployment_authorization"])
        self.assertFalse(self.evidence["decision"]["registry_access_performed"])

    def test_rejects_delta_or_raw_row_tampering(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["release_delta"]["image_context_changed_paths"].append("model/api.py")
        errors = verifier.validate_documents(evidence, self.vex, self.review)
        self.assertIn("release image-context delta changed", errors)

        evidence = copy.deepcopy(self.evidence)
        evidence["vulnerability_rows_per_role"][0]["severity"] = "UNKNOWN"
        errors = verifier.validate_documents(evidence, self.vex, self.review)
        self.assertIn(
            "unsuppressed vulnerability rows differ from predecessor",
            errors,
        )


if __name__ == "__main__":
    unittest.main()
