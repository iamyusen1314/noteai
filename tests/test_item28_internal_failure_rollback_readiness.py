import copy
import unittest
from unittest import mock
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import internal_deployment_readiness_gate as gate  # noqa: E402
import verify_internal_failure_rollback_evidence as verifier  # noqa: E402


class Item28ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.manifest = gate.load_manifest()
        self.evidence = verifier.load_evidence(verifier.EVIDENCE_PATH)

    def control(self, manifest, control_id):
        return next(
            control
            for layer in manifest["layers"]
            for control in layer["controls"]
            if control["id"] == control_id
        )

    def accepted(self, value):
        value["terminal_acceptance_sha256"] = (
            verifier.terminal_acceptance_sha256(value)
        )
        return value

    def test_current_manifest_is_28_of_29(self):
        report = gate.build_report()
        self.assertEqual(report["internal_deployment"]["verified"], 28)
        self.assertEqual(report["internal_deployment"]["total"], 29)
        self.assertFalse(report["internal_deployment"]["passed"])

    def test_tracked_direct_evidence_is_valid_without_receipt_or_checkpoint(self):
        rollback = self.control(self.manifest, "internal_failure_rollback")
        refs = {row["ref"] for row in rollback["evidence"]}

        self.assertEqual(rollback["status"], "verified")
        self.assertEqual(
            refs,
            {
                *verifier.REQUIRED_MANIFEST_PATH_REFS,
                verifier.EXECUTION_SOURCE_REVISION,
            },
        )
        self.assertFalse(any("receipt" in ref or "checkpoint" in ref for ref in refs))
        self.assertEqual(
            verifier.validate_manifest_evidence(
                rollback["evidence"],
                expected_readiness=verifier.DEFAULT_READINESS,
            ),
            [],
        )

    def test_historical_unknown_cannot_be_rewritten_as_pass(self):
        changed = copy.deepcopy(self.evidence)
        changed["rehearsal"]["result"]["status"] = "PASS"
        self.accepted(changed)

        self.assertIn(
            "rehearsal history mismatch",
            verifier.validate_document(changed),
        )

    def test_systemd_recovery_and_guardian_runtime_zero_are_both_required(self):
        attacks = (
            lambda value: value["reconciliation"]["systemd"].__setitem__(
                "nrestarts", 0
            ),
            lambda value: value["reconciliation"]["guardian_result"].__setitem__(
                "runtime_start_count", 1
            ),
            lambda value: value["cleanup"]["result"].__setitem__(
                "managed_systemd_restart_count", 0
            ),
        )
        for mutate in attacks:
            with self.subTest(mutate=mutate):
                changed = copy.deepcopy(self.evidence)
                mutate(changed)
                self.accepted(changed)
                self.assertTrue(verifier.validate_document(changed))

    def test_cleanup_residue_and_stopcharging_are_required(self):
        attacks = (
            lambda value: value["cleanup"]["result"].__setitem__(
                "volatile_residue_count", 1
            ),
            lambda value: value["final_runtime_state"]["worker_f"].__setitem__(
                "billing", "Running"
            ),
            lambda value: value["cost_and_data_boundary"]["deleted_material"].__setitem__(
                "user_data_delete_count", 1
            ),
        )
        for mutate in attacks:
            with self.subTest(mutate=mutate):
                changed = copy.deepcopy(self.evidence)
                mutate(changed)
                self.accepted(changed)
                self.assertTrue(verifier.validate_document(changed))

    def test_gate_accepts_tracked_item28_semantics(self):
        gate.validate_manifest(copy.deepcopy(self.manifest))

    def test_missing_direct_evidence_ref_never_receives_credit(self):
        changed = copy.deepcopy(self.manifest)
        rollback = self.control(changed, "internal_failure_rollback")
        rollback["evidence"] = rollback["evidence"][:-1]

        with self.assertRaisesRegex(
            gate.ManifestError, "exact direct evidence refs required"
        ):
            gate.validate_manifest(changed)

    def test_item29_state_does_not_retroactively_break_item28(self):
        changed = copy.deepcopy(self.manifest)
        capacity = self.control(changed, "capacity_100_jobs")
        capacity["status"] = "verified"
        capacity.pop("blocker", None)
        capacity.pop("next_task", None)
        capacity["evidence"] = [
            {"kind": "path", "ref": "tests/item29-placeholder.json"}
        ]

        with mock.patch.object(
            gate, "_verify_path", return_value=True
        ), mock.patch.object(gate, "validate_capacity_control", return_value=[]):
            gate.validate_manifest(changed)


if __name__ == "__main__":
    unittest.main()
