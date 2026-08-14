import copy
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from validate_item29_capacity_100_result_v1 import validate_executor_result
from tests.test_capacity_100_jobs import FakeRuntime, ITEM28, PLAN_NONCE, capacity


class ValidateItem29CapacityResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = capacity.run_rehearsal(
            FakeRuntime(),
            plan_nonce=PLAN_NONCE,
            item28_dependency=ITEM28,
        )

    def test_accepts_exact_result(self):
        errors, binding = validate_executor_result(copy.deepcopy(self.result))
        self.assertEqual(errors, [])
        self.assertIsNotNone(binding)
        self.assertEqual(binding["admission_count"], 100)
        self.assertEqual(binding["takeover_count"], 2)

    def test_rejects_relaxed_count_type_extra_and_item28_authority(self):
        mutations = []
        relaxed = copy.deepcopy(self.result)
        relaxed["runtime_projection"]["claim_count"] = 101
        mutations.append(relaxed)
        type_alias = copy.deepcopy(self.result)
        type_alias["provider"]["fake_call_count"] = 100.0
        mutations.append(type_alias)
        extra = copy.deepcopy(self.result)
        extra["provider"]["unexpected"] = 0
        mutations.append(extra)
        dependency = copy.deepcopy(self.result)
        dependency["item28_dependency"]["evidence_sha256"] = ""
        mutations.append(dependency)
        for value in mutations:
            with self.subTest(value=value):
                errors, binding = validate_executor_result(value)
                self.assertTrue(errors)
                self.assertIsNone(binding)

    def test_rejects_raw_operation_or_client_token(self):
        for key in ("operation_id", "ClientToken"):
            value = copy.deepcopy(self.result)
            value[key] = "private"
            errors, binding = validate_executor_result(value)
            self.assertTrue(errors)
            self.assertIsNone(binding)


if __name__ == "__main__":
    unittest.main()
