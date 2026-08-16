from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import verify_item26_manual_cost_stop_authority_v1 as authority  # noqa: E402


class ManualCostStopAuthorityTests(unittest.TestCase):
    def test_source_checkpoint_is_not_action_authority(self):
        self.assertEqual(authority.EXPECTED_AUTHORITY_ROOT_FILE_SHA256, "")
        self.assertFalse(authority.AUTHORITY_IMPLEMENTED)
        errors, binding = authority.validate_authority_bundle(
            expected_authority_root_file_sha256="",
            root=ROOT,
        )
        self.assertEqual(
            errors,
            ["manual cost-stop authority is not finalized"],
        )
        self.assertIsNone(binding)

    def test_arbitrary_root_hash_does_not_activate_stub(self):
        errors, binding = authority.validate_authority_bundle(
            expected_authority_root_file_sha256="1" * 64,
            root=ROOT,
        )
        self.assertEqual(
            errors,
            ["manual cost-stop authority is not finalized"],
        )
        self.assertIsNone(binding)


if __name__ == "__main__":
    unittest.main()
