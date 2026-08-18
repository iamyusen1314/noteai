import json
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import build_item26_manual_cost_stop_authority_root_v2 as builder  # noqa: E402
import verify_item26_manual_cost_stop_authority_v2 as authority  # noqa: E402
from tests.test_verify_item26_manual_cost_stop_authority_v2 import (  # noqa: E402
    SyntheticRsa3072Keys,
)


class ManualCostStopRootBuilderV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keys = SyntheticRsa3072Keys()

    @classmethod
    def tearDownClass(cls):
        cls.keys.cleanup()

    def test_builder_is_deterministic_and_contains_complete_public_pem(self):
        first = builder.build_authority_root(self.keys.public)
        second = builder.build_authority_root(dict(reversed(self.keys.public.items())))
        self.assertEqual(first, second)
        value = json.loads(first.decode("ascii"))
        self.assertEqual(authority.canonical_bytes(value), first)
        self.assertEqual(set(value["authorities"]), set(authority.ROLE_NAMES))
        for role in authority.ROLE_NAMES:
            with self.subTest(role=role):
                self.assertEqual(
                    value["authorities"][role]["public_key_pem"].encode("ascii"),
                    self.keys.public[role],
                )
                self.assertNotIn("PRIVATE KEY", value["authorities"][role]["public_key_pem"])

    def test_builder_rejects_missing_extra_and_non_bytes_key_inputs(self):
        missing = dict(self.keys.public)
        del missing["provider"]
        extra = {**self.keys.public, "legacy": b"not-a-key"}
        wrong_type = dict(self.keys.public)
        wrong_type["provider"] = "not-bytes"
        for value in (missing, extra, wrong_type):
            with self.subTest(keys=set(value)), self.assertRaises(ValueError):
                builder.build_authority_root(value)

    def test_command_entry_remains_install_disabled_before_key_or_path_processing(self):
        with mock.patch.object(
            authority,
            "public_key_row",
            side_effect=AssertionError("key processing must not start"),
        ), mock.patch.object(
            Path,
            "read_bytes",
            side_effect=AssertionError("file reads must not start"),
        ), self.assertRaisesRegex(ValueError, "install-disabled"):
            builder.main(["--private-key", "/should/not/be/read"])

    def test_root_is_not_action_authority_or_readiness_credit(self):
        value = json.loads(
            builder.build_authority_root(self.keys.public).decode("ascii")
        )
        self.assertFalse(value["authorizes_new_action"])
        self.assertFalse(value["readiness_credit_allowed"])
        self.assertTrue(value["post_action_readback_only"])
        self.assertEqual(
            value["fallback"],
            {
                "authority_v1_allowed": False,
                "collector_v1_allowed": False,
                "receipt_v2_allowed": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
