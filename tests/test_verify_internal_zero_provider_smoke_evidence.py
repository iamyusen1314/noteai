import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_internal_zero_provider_smoke_evidence as verifier  # noqa: E402


class InternalZeroProviderSmokeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.evidence = verifier.load_evidence(verifier.EVIDENCE_PATH)

    def resigned(self, payload):
        payload["terminal_acceptance_sha256"] = (
            verifier.terminal_acceptance_sha256(payload)
        )
        return payload

    def errors(self, payload):
        return verifier.validate_document(
            payload,
            expected_item26_terminal_acceptance_sha256=(
                verifier.ITEM26_TERMINAL_ACCEPTANCE_SHA256
            ),
            expected_readiness=verifier.DEFAULT_READINESS,
        )

    def test_tracked_evidence_passes(self):
        self.assertEqual(self.errors(self.evidence), [])
        self.assertEqual(verifier.validate_bundle(), [])

    def test_terminal_acceptance_is_recomputed(self):
        broken = copy.deepcopy(self.evidence)
        broken["terminal_acceptance_sha256"] = "f" * 64
        self.assertIn("terminal acceptance digest mismatch", self.errors(broken))

    def test_each_executor_result_is_revalidated(self):
        for index, action in enumerate(verifier.ACTION_ORDER):
            with self.subTest(action=action):
                broken = copy.deepcopy(self.evidence)
                broken["invocations"][index]["result"]["provider_call_count"] = 1
                errors = self.errors(self.resigned(broken))
                self.assertTrue(
                    any(action in error and "PASS result semantics" in error for error in errors),
                    errors,
                )

    def test_provider_terminal_commitments_are_exact(self):
        broken = copy.deepcopy(self.evidence)
        broken["invocations"][1]["command_content_sha256"] = "a" * 64
        self.assertIn(
            "api_f: provider commitment mismatch",
            self.errors(self.resigned(broken)),
        )

    def test_serial_order_is_required(self):
        broken = copy.deepcopy(self.evidence)
        broken["invocations"][2]["provider_start_time_utc"] = (
            "2026-08-23T15:07:00Z"
        )
        errors = self.errors(self.resigned(broken))
        self.assertIn("worker_c: provider commitment mismatch", errors)
        self.assertIn(
            "worker_c: provider terminal timestamps are not strictly ordered",
            errors,
        )

    def test_aggregate_is_derived_from_results(self):
        broken = copy.deepcopy(self.evidence)
        broken["aggregate"]["pass_count"] = 3
        self.assertIn("aggregate mismatch", self.errors(self.resigned(broken)))

    def test_item26_binding_is_exact(self):
        broken = copy.deepcopy(self.evidence)
        broken["source_binding"]["item26_terminal_acceptance_sha256"] = "a" * 64
        self.assertIn("source binding mismatch", self.errors(self.resigned(broken)))

    def test_api_c_is_reused_only_across_the_exact_parser_only_diff(self):
        source = self.evidence["source_binding"]
        self.assertTrue(source["api_c_reused_without_rerun"])
        self.assertEqual(
            source["api_c_reuse_changed_paths"],
            list(verifier.API_C_REUSE_CHANGED_PATHS),
        )
        broken = copy.deepcopy(self.evidence)
        broken["source_binding"]["api_c_reuse_changed_paths"].append("model/api.py")
        self.assertIn("source binding mismatch", self.errors(self.resigned(broken)))

    def test_capture_loss_is_disclosed_without_fabricated_receipts(self):
        recovery = self.evidence["capture_recovery"]
        self.assertTrue(recovery["cloudshell_expired_after_final_pass"])
        self.assertFalse(recovery["byte_identical_new_receipts_recoverable"])
        self.assertEqual(recovery["fabricated_receipt_count"], 0)
        self.assertNotIn("receipt", verifier.REQUIRED_MANIFEST_PATH_REFS)
        broken = copy.deepcopy(self.evidence)
        broken["capture_recovery"]["byte_identical_new_receipts_recoverable"] = True
        self.assertIn(
            "capture recovery disclosure mismatch",
            self.errors(self.resigned(broken)),
        )

    def test_cost_is_not_falsely_reported_as_zero(self):
        cost = self.evidence["cost_and_data_boundary"]
        self.assertEqual(cost["final_continuation_estimated_compute_cost_cny"], "0.034470")
        self.assertIsNone(cost["item27_total_actual_cost_cny"])
        self.assertEqual(cost["billing_status"], "PENDING_PROVIDER_SETTLEMENT")
        broken = copy.deepcopy(self.evidence)
        broken["cost_and_data_boundary"]["final_continuation_estimated_compute_cost_cny"] = "0"
        self.assertIn("cost/data boundary mismatch", self.errors(self.resigned(broken)))

    def test_all_temporary_resources_end_with_zero_residue(self):
        state = self.evidence["final_runtime_state"]
        for host in ("builder", "worker_c", "worker_f"):
            self.assertEqual(state[host], {
                "state": "Stopped", "billing": "StopCharging"
            })
        self.assertEqual(state["temporary_security_group_rule_count"], 0)
        self.assertEqual(state["temporary_peering_count"], 0)
        self.assertEqual(state["temporary_route_count"], 0)

    def manifest_entries(self):
        return [
            *(
                {"kind": "path", "ref": ref}
                for ref in sorted(verifier.REQUIRED_MANIFEST_PATH_REFS)
            ),
            *(
                {"kind": "git", "ref": ref}
                for ref in sorted(verifier.REQUIRED_MANIFEST_GIT_REFS)
            ),
        ]

    def test_manifest_accepts_only_the_original_dod_evidence_set(self):
        self.assertEqual(
            verifier.validate_manifest_evidence(
                self.manifest_entries(),
                expected_item26_terminal_acceptance_sha256=(
                    verifier.ITEM26_TERMINAL_ACCEPTANCE_SHA256
                ),
                expected_readiness=verifier.DEFAULT_READINESS,
            ),
            [],
        )
        broken = self.manifest_entries()
        broken.append({
            "kind": "path",
            "ref": "deploy/production/evidence/item27-extra-receipt.json",
        })
        self.assertEqual(
            verifier.validate_manifest_evidence(
                broken,
                expected_item26_terminal_acceptance_sha256=(
                    verifier.ITEM26_TERMINAL_ACCEPTANCE_SHA256
                ),
                expected_readiness=verifier.DEFAULT_READINESS,
            ),
            ["Item27 exact original-DoD evidence refs required"],
        )

    def test_manifest_requires_item26_terminal_digest(self):
        self.assertEqual(
            verifier.validate_manifest_evidence(
                self.manifest_entries(),
                expected_item26_terminal_acceptance_sha256="",
                expected_readiness=verifier.DEFAULT_READINESS,
            ),
            ["Item26 terminal acceptance digest is required"],
        )

    def test_duplicate_json_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"schema_version":1,"schema_version":1}\n')
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                verifier.load_evidence(path)

    def test_main_passes_for_the_tracked_readiness_row(self):
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", ["verify-item27"]), redirect_stdout(stdout):
            status = verifier.main()
        self.assertEqual(status, 0, stdout.getvalue())
        self.assertIn("internal_zero_provider_smoke_evidence=PASS", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
