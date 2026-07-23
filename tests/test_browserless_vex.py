import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_browserless_vex as verifier  # noqa: E402


class BrowserlessVexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vex = json.loads(verifier.VEX_PATH.read_text(encoding="utf-8"))
        cls.evidence = json.loads(verifier.EVIDENCE_PATH.read_text(encoding="utf-8"))

    def test_exact_product_vex_authoring_bundle_passes(self):
        self.assertEqual(
            verifier.validate_documents(self.vex, self.evidence),
            [],
        )

    def test_rejects_application_revision_drift(self):
        vex = copy.deepcopy(self.vex)
        vex["metadata"]["component"]["version"] = "not-a635692"
        errors = verifier.validate_documents(vex, self.evidence)
        self.assertIn("VEX metadata component is not bound to a635692", errors)

    def test_rejects_missing_role_bom_link(self):
        vex = copy.deepcopy(self.vex)
        vulnerability = next(
            item
            for item in vex["vulnerabilities"]
            if item["id"] == "CVE-2026-53615"
        )
        vulnerability["affects"].pop()
        errors = verifier.validate_documents(vex, self.evidence)
        self.assertIn("CVE-2026-53615: exact SBOM BOM-Link set mismatch", errors)

    def test_rejects_waiver_semantics(self):
        vex = copy.deepcopy(self.vex)
        vex["vulnerabilities"][0]["analysis"]["response"] = ["will_not_fix"]
        errors = verifier.validate_documents(vex, self.evidence)
        self.assertTrue(
            any("must not claim a response/waiver" in error for error in errors),
            errors,
        )

    def test_rejects_local_image_id_as_registry_digest(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["roles"]["api"]["registry_digest"] = evidence["roles"]["api"]["local_image_id"]
        errors = verifier.validate_documents(self.vex, evidence)
        self.assertIn("api: registry digest must not equal local image ID", errors)

    def test_rejects_registry_digest_binding_drift(self):
        evidence = copy.deepcopy(self.evidence)
        vex = copy.deepcopy(self.vex)
        fake_digest = "sha256:" + ("0" * 64)
        evidence["roles"]["api"]["registry_digest"] = fake_digest
        evidence["roles"]["api"]["registry_reference"] = (
            f"{verifier.REGISTRY_REPOSITORY}@{fake_digest}"
        )
        api_component = next(
            item for item in vex["components"] if item["name"] == "api-runtime"
        )
        api_component["bom-ref"] = (
            "urn:noteai:container:api:" + fake_digest.replace(":", "-")
        )
        for prop in api_component["properties"]:
            if prop["name"] == "noteai:registry-digest":
                prop["value"] = fake_digest
            if prop["name"] == "noteai:registry-reference":
                prop["value"] = evidence["roles"]["api"]["registry_reference"]
        errors = verifier.validate_documents(vex, evidence)
        self.assertIn(
            "evidence.roles.api.registry_digest: immutable evidence mismatch",
            errors,
        )

    def test_rejects_coordinated_evidence_identity_tampering(self):
        evidence = copy.deepcopy(self.evidence)
        vex = copy.deepcopy(self.vex)
        fake_id = "sha256:" + ("0" * 64)
        evidence["roles"]["api"]["local_image_id"] = fake_id
        api_component = next(
            item for item in vex["components"] if item["name"] == "api-runtime"
        )
        for prop in api_component["properties"]:
            if prop["name"] == "noteai:local-image-id":
                prop["value"] = fake_id
        errors = verifier.validate_documents(vex, evidence)
        self.assertIn(
            "evidence.roles.api.local_image_id: immutable evidence mismatch",
            errors,
        )


if __name__ == "__main__":
    unittest.main()
