import copy
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import internal_deployment_readiness_gate as gate  # noqa: E402
import verify_internal_failure_rollback_evidence as verifier  # noqa: E402


class Item28ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.manifest = gate.load_manifest()

    def control(self, manifest, control_id):
        return next(
            control
            for layer in manifest["layers"]
            for control in layer["controls"]
            if control["id"] == control_id
        )

    def verify_control(self, manifest, control_id, evidence=None):
        control = self.control(manifest, control_id)
        control["status"] = "verified"
        control.pop("blocker", None)
        control.pop("next_task", None)
        control.pop("resume_condition", None)
        control["evidence"] = evidence or [
            {"kind": "path", "ref": "tests/item28-placeholder.json"}
        ]
        return control

    def test_current_manifest_is_27_of_29(self):
        report = gate.build_report()
        self.assertEqual(report["internal_deployment"]["verified"], 27)
        self.assertEqual(report["internal_deployment"]["total"], 29)
        self.assertFalse(report["internal_deployment"]["passed"])

    def test_item28_default_terminal_roots_are_empty_and_block(self):
        roots = verifier.predecessor_authority_roots()
        self.assertEqual(set(roots), {"item25", "item26", "item27"})
        self.assertTrue(all(not value for row in roots.values() for value in row.values()))

        candidate = copy.deepcopy(self.manifest)
        self.verify_control(candidate, "internal_failure_rollback")
        with mock.patch.object(gate, "_verify_path", return_value=True):
            with self.assertRaisesRegex(
                gate.ManifestError,
                "predecessor semantic evidence invalid: item25 terminal authority root is not finalized",
            ):
                gate.validate_manifest(candidate)

    def terminal_candidate(self):
        candidate = copy.deepcopy(self.manifest)
        self.verify_control(candidate, "backup_pitr_restore")
        self.verify_control(candidate, "internal_zero_provider_smoke")
        rollback = self.verify_control(
            candidate,
            "internal_failure_rollback",
            evidence=[
                {"kind": "path", "ref": ref}
                for ref in sorted(verifier.REQUIRED_MANIFEST_PATH_REFS)
            ],
        )
        return candidate, rollback

    def test_verified_item28_requires_exact_semantic_evidence(self):
        candidate, rollback = self.terminal_candidate()
        predecessor_hashes = {
            "item25": "a" * 64,
            "item26": "b" * 64,
            "item27": "c" * 64,
        }
        with mock.patch.object(
            gate, "_verify_path", return_value=True
        ), mock.patch.object(
            gate, "validate_item26_terminal_evidence",
            return_value=([], predecessor_hashes["item26"]),
        ), mock.patch.object(
            gate, "validate_internal_zero_provider_smoke_evidence",
            return_value=[],
        ), mock.patch.object(
            gate, "validate_item28_predecessor_evidence",
            return_value=([], predecessor_hashes),
        ), mock.patch.object(
            gate, "validate_internal_failure_rollback_evidence",
            return_value=[],
        ) as validate:
            gate.validate_manifest(candidate)

        validate.assert_called_once()
        args, kwargs = validate.call_args
        self.assertEqual(args, (rollback["evidence"],))
        self.assertEqual(kwargs["expected_predecessors"], predecessor_hashes)
        self.assertEqual(kwargs["expected_readiness"], verifier.DEFAULT_READINESS)
        self.assertEqual(kwargs["expected_readiness"]["internal_verified_after"], 28)
        self.assertEqual(kwargs["expected_readiness"]["next_task"], "PROD-FIRST-LAUNCH-CAPACITY-100-001")

    def test_tampered_item28_semantics_never_receive_credit(self):
        candidate, _rollback = self.terminal_candidate()
        hashes = {"item25": "a" * 64, "item26": "b" * 64, "item27": "c" * 64}
        with mock.patch.object(
            gate, "_verify_path", return_value=True
        ), mock.patch.object(
            gate, "validate_item26_terminal_evidence",
            return_value=([], hashes["item26"]),
        ), mock.patch.object(
            gate, "validate_internal_zero_provider_smoke_evidence",
            return_value=[],
        ), mock.patch.object(
            gate, "validate_item28_predecessor_evidence",
            return_value=([], hashes),
        ), mock.patch.object(
            gate, "validate_internal_failure_rollback_evidence",
            return_value=["guardian rollback count drift"],
        ):
            with self.assertRaisesRegex(
                gate.ManifestError,
                "invalid semantic evidence: guardian rollback count drift",
            ):
                gate.validate_manifest(candidate)

    def test_item29_downstream_state_does_not_retroactively_break_item28(self):
        candidate, _rollback = self.terminal_candidate()
        self.verify_control(candidate, "capacity_100_jobs")
        hashes = {"item25": "a" * 64, "item26": "b" * 64, "item27": "c" * 64}
        with mock.patch.object(
            gate, "_verify_path", return_value=True
        ), mock.patch.object(
            gate, "validate_item26_terminal_evidence",
            return_value=([], hashes["item26"]),
        ), mock.patch.object(
            gate, "validate_internal_zero_provider_smoke_evidence",
            return_value=[],
        ), mock.patch.object(
            gate, "validate_item28_predecessor_evidence",
            return_value=([], hashes),
        ), mock.patch.object(
            gate, "validate_internal_failure_rollback_evidence",
            return_value=[],
        ), mock.patch.object(
            gate, "validate_capacity_control",
            return_value=[],
        ):
            gate.validate_manifest(candidate)


if __name__ == "__main__":
    unittest.main()
