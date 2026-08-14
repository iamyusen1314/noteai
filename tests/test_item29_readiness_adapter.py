import copy
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from item29_readiness_adapter import validate_capacity_control


class Item29ReadinessAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(
            (ROOT / "deploy/production/internal-deployment-readiness.json").read_text(
                encoding="utf-8"
            )
        )

    @staticmethod
    def controls(manifest):
        return {
            control["id"]: control
            for layer in manifest["layers"]
            for control in layer["controls"]
        }

    def test_current_unverified_control_is_inert(self):
        manifest = copy.deepcopy(self.manifest)
        errors = validate_capacity_control(manifest, self.controls(manifest))
        self.assertEqual(errors, [])

    def test_manifest_only_verified_flip_cannot_gain_credit(self):
        manifest = copy.deepcopy(self.manifest)
        controls = self.controls(manifest)
        controls["capacity_100_jobs"]["status"] = "verified"
        controls["capacity_100_jobs"]["evidence"] = []
        errors = validate_capacity_control(manifest, controls)
        self.assertTrue(errors)
        self.assertIn("Item28 dependency invalid", errors[0])


if __name__ == "__main__":
    unittest.main()
