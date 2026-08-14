import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import verify_capacity_100_jobs_evidence as verifier
from tests.test_build_item29_capacity_100_evidence_v1 import (
    BuildItem29EvidenceTests,
)


class Item29CapacityReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        BuildItem29EvidenceTests.setUpClass()
        fixture = BuildItem29EvidenceTests()
        cls.receipt = fixture.build()

    def test_default_item28_dependency_blocks_before_credit(self):
        controls = {
            "internal_failure_rollback": {
                "status": "verified",
                "evidence": [],
            }
        }
        errors, dependency = verifier.validate_item28_dependency(controls)
        self.assertTrue(errors)
        self.assertIsNone(dependency)
        self.assertIn("not finalized", errors[0])

    def test_default_terminal_authority_blocks_shape_correct_manifest_refs(self):
        entries = [
            {"kind": "path", "ref": ref}
            for ref in verifier.REQUIRED_MANIFEST_PATH_REFS
        ]
        errors = verifier.validate_manifest_evidence(
            entries,
            expected_item28_dependency=copy.deepcopy(
                verifier.EXPECTED_ITEM28_DEPENDENCY
            ),
            expected_readiness=verifier.DEFAULT_READINESS,
        )
        self.assertTrue(errors)
        self.assertIn("terminal evidence authority is not finalized", errors[0])

    def test_versioned_dependency_can_be_mechanically_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root, dependency, controls = self._item28_fixture(Path(directory))
            with mock.patch.object(
                verifier, "EXPECTED_ITEM28_DEPENDENCY", dependency
            ):
                errors, accepted = verifier.validate_item28_dependency(
                    controls, root=root
                )
            self.assertEqual(errors, [])
            self.assertEqual(accepted, dependency)

    def test_item28_skeleton_receipt_and_evidence_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root, dependency, controls = self._item28_fixture(
                Path(directory), skeleton=True
            )
            with mock.patch.object(
                verifier, "EXPECTED_ITEM28_DEPENDENCY", dependency
            ):
                errors, accepted = verifier.validate_item28_dependency(
                    controls, root=root
                )
            self.assertTrue(errors)
            self.assertIsNone(accepted)
            self.assertIn("strict Item28 receipt schema", errors[0])

    @staticmethod
    def _item28_fixture(root, *, skeleton=False):
        source_revision = "a" * 40
        acceptance = "9" * 64
        receipt_value = {
            "schema_version": 1,
            "schema": verifier.ITEM28_RECEIPT_SCHEMA,
            "task_id": verifier.ITEM28_TASK_ID,
            "action": "api_f_rollback",
            "status": "PROVIDER_TERMINAL_VERIFIED",
            "observed_at_utc": "2026-08-14T00:00:00Z",
            "source_revision": source_revision,
            "source_binding": {},
            "predecessors": {},
            "raw_closure": {},
            "request": {},
            "pre_dispatch": {},
            "terminal_readback": {},
            "result": {},
            "result_binding": {},
            "execution_boundary": {},
        }
        evidence_value = {
            "schema_version": 1,
            "schema": verifier.ITEM28_EVIDENCE_SCHEMA,
            "task_id": verifier.ITEM28_TASK_ID,
            "status": "PASS",
            "source_revision": source_revision,
            "predecessors": {},
            "provider_receipt": {
                "terminal_acceptance_sha256": acceptance,
            },
            "rehearsal": {},
            "final_runtime_state": {},
            "mutation_counters": {},
            "cost_and_data_boundary": {},
            "readiness": verifier.ITEM28_READINESS,
        }
        if skeleton:
            receipt_value = {
                "schema": verifier.ITEM28_RECEIPT_SCHEMA,
                "task_id": verifier.ITEM28_TASK_ID,
                "status": "PROVIDER_TERMINAL_VERIFIED",
                "source_revision": source_revision,
            }
            evidence_value = {
                "schema": verifier.ITEM28_EVIDENCE_SCHEMA,
                "task_id": verifier.ITEM28_TASK_ID,
                "status": "PASS",
                "source_revision": source_revision,
            }
        receipt_raw = verifier._canonical(receipt_value)
        evidence_raw = verifier._canonical(evidence_value)
        checkpoint_value = {
            "schema": verifier.ITEM28_CHECKPOINT_SCHEMA,
            "task_id": verifier.ITEM28_TASK_ID,
            "status": "EXACT_HEAD_CI_ACCEPTED",
            "source_revision": source_revision,
            "evidence_file_sha256": verifier._sha(evidence_raw),
            "evidence_semantic_sha256": verifier._semantic(evidence_value),
            "receipt_file_sha256": verifier._sha(receipt_raw),
            "receipt_semantic_sha256": verifier._semantic(receipt_value),
            "automatic_retry_allowed": False,
            "readiness_credit_added": True,
        }
        refs = {
            "verifier": "tools/item28-verifier.py",
            "evidence": "deploy/production/evidence/item28.json",
            "receipt": "deploy/production/evidence/item28-receipt.json",
            "checkpoint": "deploy/production/evidence/item28-checkpoint.json",
        }
        item28_source_refs = {
            refs["verifier"], refs["evidence"], refs["receipt"],
            refs["checkpoint"], "deploy/production/internal_failure_rollback.py",
            "tools/render_item28_internal_failure_rollback_request_v1.py",
            "tools/validate_item28_internal_failure_rollback_result_v1.py",
            "tools/build_item28_internal_failure_rollback_evidence_v1.py",
        }
        module_source = f'''\
TASK_ID = {verifier.ITEM28_TASK_ID!r}
RECEIPT_SCHEMA = {verifier.ITEM28_RECEIPT_SCHEMA!r}
EVIDENCE_SCHEMA = {verifier.ITEM28_EVIDENCE_SCHEMA!r}
CHECKPOINT_SCHEMA = {verifier.ITEM28_CHECKPOINT_SCHEMA!r}
VERIFIER_REF = {refs["verifier"]!r}
EVIDENCE_REF = {refs["evidence"]!r}
RECEIPT_REF = {refs["receipt"]!r}
TERMINAL_CHECKPOINT_REF = {refs["checkpoint"]!r}
EXPECTED_SOURCE_REVISION = {source_revision!r}
EXPECTED_EVIDENCE_FILE_SHA256 = {verifier._sha(evidence_raw)!r}
EXPECTED_RECEIPT_FILE_SHA256 = {verifier._sha(receipt_raw)!r}
EXPECTED_TERMINAL_CHECKPOINT_FILE_SHA256 = {verifier._sha(verifier._canonical(checkpoint_value))!r}
DEFAULT_READINESS = {verifier.ITEM28_READINESS!r}
REQUIRED_REFS = {item28_source_refs!r}
REQUIRED_RECEIPT_KEYS = {verifier.ITEM28_RECEIPT_KEYS!r}
REQUIRED_EVIDENCE_KEYS = {verifier.ITEM28_EVIDENCE_KEYS!r}

def validate_predecessor_evidence(controls_by_id, *, root):
    return [], {{"item25": "1" * 64, "item26": "2" * 64, "item27": "3" * 64}}

def validate_manifest_evidence(entries, *, root, expected_predecessors, expected_readiness):
    path_refs = {{row.get("ref") for row in entries if row.get("kind") == "path"}}
    git_refs = [row.get("ref") for row in entries if row.get("kind") == "git"]
    return [] if path_refs == REQUIRED_REFS and git_refs == [EXPECTED_SOURCE_REVISION] else ["strict manifest"]

def validate_receipt(value, *, expected_predecessors, root):
    if type(value) is not dict or set(value) != REQUIRED_RECEIPT_KEYS:
        return ["strict receipt"], None
    return [], {acceptance!r}

def validate_evidence(value, receipt, *, expected_predecessors, expected_readiness, root):
    return [] if type(value) is dict and set(value) == REQUIRED_EVIDENCE_KEYS else ["strict evidence"]
'''.encode("ascii")
        artifacts = {
            refs["verifier"]: module_source,
            refs["evidence"]: evidence_raw,
            refs["receipt"]: receipt_raw,
            refs["checkpoint"]: verifier._canonical(checkpoint_value),
        }
        for relative, raw in artifacts.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        dependency = {
            "schema": verifier.DEPENDENCY_SCHEMA,
            "authority_root": "",
            "verifier_path": refs["verifier"],
            "verifier_sha256": verifier._sha(module_source),
            "evidence_path": refs["evidence"],
            "evidence_sha256": verifier._sha(evidence_raw),
            "receipt_path": refs["receipt"],
            "receipt_sha256": verifier._sha(receipt_raw),
            "checkpoint_path": refs["checkpoint"],
            "checkpoint_sha256": verifier._sha(
                verifier._canonical(checkpoint_value)
            ),
            "terminal_acceptance_sha256": acceptance,
        }
        dependency["authority_root"] = verifier._item28_authority_root(dependency)
        controls = {
            "internal_failure_rollback": {
                "status": "verified",
                "evidence": [
                    *(
                        {"kind": "path", "ref": ref}
                        for ref in sorted(item28_source_refs)
                    ),
                    {"kind": "git", "ref": source_revision},
                ],
            }
        }
        return root, dependency, controls

    def test_receipt_semantics_reject_count_drift(self):
        with mock.patch.object(verifier, "EXPECTED_SOURCE_REVISION", "a" * 40):
            errors, acceptance = verifier.validate_receipt(
                copy.deepcopy(self.receipt),
                expected_item28_dependency=self.receipt["item28_dependency"],
            )
            self.assertEqual(errors, [])
            self.assertIsNotNone(acceptance)

            changed = copy.deepcopy(self.receipt)
            changed["result"]["runtime_projection"]["usage_record_count"] = 99
            errors, acceptance = verifier.validate_receipt(
                changed,
                expected_item28_dependency=self.receipt["item28_dependency"],
            )
            self.assertTrue(errors)
            self.assertIsNone(acceptance)

    def test_receipt_numeric_bool_float_and_string_aliases_are_rejected(self):
        attacks = (
            ("bool", lambda value: value.__setitem__("schema_version", True)),
            ("float", lambda value: value["execution_boundary"].__setitem__(
                "wrapper_host_temp_file_count", 4.0
            )),
            ("string", lambda value: value["terminal_readback"].__setitem__(
                "repeat_count", "1"
            )),
        )
        with mock.patch.object(verifier, "EXPECTED_SOURCE_REVISION", "a" * 40):
            for label, mutate in attacks:
                with self.subTest(alias=label):
                    changed = copy.deepcopy(self.receipt)
                    mutate(changed)
                    errors, acceptance = verifier.validate_receipt(
                        changed,
                        expected_item28_dependency=changed["item28_dependency"],
                    )
                    self.assertTrue(errors)
                    self.assertIsNone(acceptance)

    def _evidence_fixture(self):
        result = self.receipt["result"]
        runtime = result["runtime_projection"]
        accounting_keys = (
            "settlement_completed_count", "settlement_refunded_count",
            "settlement_needs_manual_count", "charge_applied_count",
            "complete_applied_count", "usage_record_count",
            "expected_credits_milli", "actual_credits_milli",
            "overcharge_credits_milli", "payment_record_delta_count",
            "cash_balance_delta_milli",
        )
        cleanup_keys = (
            "ready_request_object_residue_count",
            "ready_result_object_residue_count", "primary_user_residue_count",
            "admission_residue_count", "idempotency_residue_count",
            "pseudonymous_operation_audit_count",
            "pseudonymous_provider_attempt_audit_count",
            "pseudonymous_usage_audit_count",
        )
        return {
            "schema_version": 1,
            "schema": verifier.EVIDENCE_SCHEMA,
            "task_id": verifier.TASK_ID,
            "status": "PASS",
            "source_revision": "a" * 40,
            "item28_dependency": copy.deepcopy(
                self.receipt["item28_dependency"]
            ),
            "provider_receipt": {
                "path": verifier.RECEIPT_REF,
                "file_sha256": verifier.EXPECTED_RECEIPT_FILE_SHA256,
                "semantic_sha256": verifier.EXPECTED_RECEIPT_SEMANTIC_SHA256,
                "terminal_acceptance_sha256": (
                    verifier.terminal_acceptance_sha256(self.receipt)
                ),
            },
            "external_authority": {"binding": "test"},
            "capacity": {
                "operation_count": 100,
                "succeeded_count": 100,
                "lost_operation_count": 0,
                "claim_count": 102,
                "takeover_count": 2,
            },
            "headroom": copy.deepcopy(result["headroom"]),
            "admission": copy.deepcopy(result["admission"]),
            "routing_and_recovery": copy.deepcopy(
                result["routing_and_recovery"]
            ),
            "provider": copy.deepcopy(verifier.EXPECTED_PROVIDER),
            "accounting": {key: runtime[key] for key in accounting_keys},
            "cleanup": {key: runtime[key] for key in cleanup_keys},
            "execution_boundary": copy.deepcopy(result["execution_boundary"]),
            "readiness": copy.deepcopy(verifier.DEFAULT_READINESS),
        }

    def test_evidence_numeric_bool_float_and_string_aliases_are_rejected(self):
        authority_binding = {"binding": "test"}
        attacks = (
            ("bool", lambda value: value.__setitem__("schema_version", True)),
            ("float", lambda value: value["capacity"].__setitem__(
                "claim_count", 102.0
            )),
            ("string", lambda value: value["accounting"].__setitem__(
                "usage_record_count", "100"
            )),
        )
        with mock.patch.object(verifier, "EXPECTED_SOURCE_REVISION", "a" * 40):
            valid = self._evidence_fixture()
            self.assertEqual(
                verifier.validate_evidence(
                    valid, self.receipt,
                    expected_item28_dependency=self.receipt["item28_dependency"],
                    expected_readiness=verifier.DEFAULT_READINESS,
                    authority_binding=authority_binding,
                ),
                [],
            )
            for label, mutate in attacks:
                with self.subTest(alias=label):
                    changed = copy.deepcopy(valid)
                    mutate(changed)
                    errors = verifier.validate_evidence(
                        changed, self.receipt,
                        expected_item28_dependency=(
                            self.receipt["item28_dependency"]
                        ),
                        expected_readiness=verifier.DEFAULT_READINESS,
                        authority_binding=authority_binding,
                    )
                    self.assertTrue(errors)

    def test_final_readiness_projection_is_exact_29_of_29(self):
        self.assertEqual(
            verifier.DEFAULT_READINESS,
            {
                "internal_verified_before": 28,
                "internal_verified_after": 29,
                "internal_total": 29,
                "internal_percentage_after": 100,
                "complete_public_verified_before": 28,
                "complete_public_verified_after": 29,
                "complete_public_total": 38,
                "complete_public_percentage_after": 76,
                "next_task": "PROD-FIRST-LAUNCH-PROVIDER-CHAIN-001",
                "public_launch_authorized": False,
                "real_provider_chain_verified": False,
                "capacity_100_jobs_verified": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
