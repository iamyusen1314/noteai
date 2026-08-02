import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
TOOLS_DIR = ROOT / "tools"
sys.path.insert(0, str(MODEL_DIR))
sys.path.insert(0, str(TOOLS_DIR))

import artifact_loader  # noqa: E402
import fact_enrichment as facts  # noqa: E402
import production_readiness_gate as gate  # noqa: E402


class ProductionReadinessGateTests(unittest.TestCase):
    def setUp(self):
        # Most tests mutate an unrelated gate input. Keep one bounded V17
        # lifecycle snapshot for those cases; the dedicated integration test
        # below executes the real repository evaluator exactly once.
        self._v17_snapshot_patcher = mock.patch.object(
            gate,
            "evaluate_admin_dependency_cache_export_plan_v17",
            return_value=([], "PREPARED_V17_NOT_TRIGGERED", []),
        )
        self._v17_snapshot_patcher.start()
        self._v16_predecessor_patcher = mock.patch.object(
            gate,
            "validate_admin_dependency_cache_v16_predecessor",
            return_value=[],
        )
        self._v16_predecessor_patcher.start()
        self._v16_evidence_patcher = mock.patch.object(
            gate,
            "verify_admin_dependency_cache_v16_failure_evidence",
            return_value=[],
        )
        self._v16_evidence_patcher.start()
        self._v15_predecessor_patcher = mock.patch.object(
            gate,
            "validate_admin_dependency_cache_v15_predecessor",
            return_value=[],
        )
        self._v15_predecessor_patcher.start()
        self._v15_evidence_patcher = mock.patch.object(
            gate,
            "verify_admin_dependency_cache_v15_failure_evidence",
            return_value=[],
        )
        self._v15_evidence_patcher.start()

    def tearDown(self):
        if self._v17_snapshot_patcher is not None:
            self._v17_snapshot_patcher.stop()
        self._v16_predecessor_patcher.stop()
        self._v16_evidence_patcher.stop()
        self._v15_predecessor_patcher.stop()
        self._v15_evidence_patcher.stop()

    def _use_real_v17_evaluator(self):
        self._v17_snapshot_patcher.stop()
        self._v17_snapshot_patcher = None

    def test_current_repo_passes_production_readiness_gate(self):
        report = gate.build_report()

        self.assertTrue(report["passed"], report["failed_checks"])
        self.assertGreaterEqual(report["check_count"], 30)

    def test_current_v17_repository_lifecycle_is_validated_once(self):
        self._use_real_v17_evaluator()
        errors, state, terminal_errors = (
            gate.evaluate_admin_dependency_cache_export_plan_v17()
        )

        self.assertEqual(errors, [])
        self.assertEqual(terminal_errors, [])
        self.assertIn(
            state,
            {
                "PREPARED_V17_NOT_TRIGGERED",
                "V17_ARMED_OR_TRIGGERED_EXACT",
            },
        )

    def test_current_native_release_vex_is_part_of_repository_gate(self):
        checks = {item["name"]: item for item in gate.check_browserless_vex()}

        self.assertTrue(checks["exact_a635692_browserless_vex_bundle"]["passed"])
        self.assertTrue(
            checks["exact_b06671f_github_native_five_role_source_bundle"]["passed"]
        )
        self.assertTrue(
            checks["exact_b06671f_registry_native_five_role_vex_bundle"]["passed"]
        )
        self.assertTrue(
            checks["exact_b55f118_github_native_five_role_source_bundle"]["passed"]
        )
        self.assertTrue(
            checks["exact_b55f118_registry_native_five_role_vex_bundle"]["passed"]
        )
        self.assertTrue(
            checks["exact_5335bda_github_native_admin_only_source_bundle"]["passed"]
        )
        self.assertTrue(
            checks[
                "bounded_5335bda_admin_private_publication_attempt_clean"
            ]["passed"]
        )
        self.assertTrue(
            checks[
                "exact_5335bda_admin_dependency_cache_export_plan_fail_closed"
            ]["passed"]
        )
        self.assertTrue(
            checks[
                "exact_5335bda_admin_dependency_cache_v2_attempt1_failed_artifact0"
            ]["passed"]
        )
        self.assertTrue(
            checks[
                "exact_5335bda_admin_dependency_cache_v3_attempt1_failed_artifact0"
            ]["passed"]
        )
        self.assertTrue(
            checks[
                "exact_5335bda_admin_dependency_cache_v3_recovery_plan_fail_closed"
            ]["passed"]
        )
        self.assertTrue(
            checks[
                "exact_5335bda_admin_dependency_cache_v4_recovery_plan_fail_closed"
            ]["passed"]
        )
        self.assertTrue(
            checks[
                "exact_5335bda_admin_dependency_cache_v5_recovery_plan_fail_closed"
            ]["passed"]
        )
        self.assertTrue(
            checks[
                "exact_5335bda_admin_dependency_cache_v5_attempt1_failed_artifact0"
            ]["passed"]
        )
        self.assertTrue(
            checks[
                "exact_5335bda_admin_dependency_cache_v6_recovery_plan_fail_closed"
            ]["passed"]
        )
        self.assertTrue(
            checks[
                "exact_5335bda_admin_dependency_cache_v6_attempt1_failed_artifact0"
            ]["passed"]
        )
        self.assertTrue(
            checks[
                "exact_5335bda_admin_dependency_cache_v7_recovery_plan_fail_closed"
            ]["passed"]
        )
        self.assertTrue(
            checks[
                "exact_5335bda_admin_dependency_cache_v7_attempt1_failed_artifact0"
            ]["passed"]
        )
        self.assertTrue(
            checks[
                "exact_5335bda_admin_dependency_cache_v8_recovery_plan_fail_closed"
            ]["passed"]
        )
        self.assertTrue(
            checks[
                "exact_5335bda_admin_dependency_cache_v8_attempt1_failed_artifact0"
            ]["passed"]
        )
        self.assertTrue(
            checks[
                "exact_5335bda_admin_dependency_cache_v9_recovery_plan_fail_closed"
            ]["passed"]
        )
        self.assertTrue(
            checks[
                "exact_5335bda_admin_dependency_cache_v9_attempt1_failed_artifact0"
            ]["passed"]
        )
        self.assertTrue(
            checks[
                "exact_5335bda_admin_dependency_cache_v10_recovery_plan_fail_closed"
            ]["passed"]
        )
        self.assertTrue(
            checks[
                "exact_5335bda_admin_dependency_cache_v10_attempt1_failed_artifact0"
            ]["passed"]
        )
        self.assertTrue(
            checks[
                "exact_5335bda_admin_dependency_cache_v11_recovery_plan_fail_closed"
            ]["passed"]
        )
        self.assertTrue(
            checks[
                "exact_5335bda_admin_dependency_cache_v12_recovery_plan_fail_closed"
            ]["passed"]
        )
        self.assertTrue(
            checks[
                "exact_5335bda_admin_dependency_cache_v12_attempt1_failed_artifact0"
            ]["passed"]
        )
        self.assertTrue(
            checks[
                "exact_5335bda_admin_dependency_cache_v15_recovery_plan_fail_closed"
            ]["passed"]
        )
        self.assertTrue(
            checks[
                "exact_5335bda_admin_dependency_cache_v16_recovery_plan_fail_closed"
            ]["passed"]
        )
        self.assertTrue(
            checks[
                "exact_5335bda_admin_dependency_cache_v16_"
                "attempt1_failed_artifact0"
            ]["passed"]
        )

        with mock.patch.object(
            gate,
            "validate_5335_admin_native_release_vex_bundle",
            return_value=["tampered Admin native evidence"],
        ):
            report = gate.build_report()
        self.assertFalse(report["passed"])
        self.assertIn(
            "exact_5335bda_github_native_admin_only_source_bundle",
            {item["name"] for item in report["failed_checks"]},
        )

        with mock.patch.object(
            gate,
            "validate_admin_private_publication_attempt_evidence",
            return_value=["tampered Admin publication attempt evidence"],
        ):
            report = gate.build_report()
        self.assertFalse(report["passed"])
        self.assertIn(
            "bounded_5335bda_admin_private_publication_attempt_clean",
            {item["name"] for item in report["failed_checks"]},
        )

        with mock.patch.object(
            gate,
            "validate_admin_dependency_cache_export_plan",
            return_value=["tampered Admin dependency-cache export plan"],
        ):
            report = gate.build_report()
        self.assertFalse(report["passed"])
        self.assertIn(
            "exact_5335bda_admin_dependency_cache_export_plan_fail_closed",
            {item["name"] for item in report["failed_checks"]},
        )

        with mock.patch.object(
            gate,
            "verify_admin_dependency_cache_v2_failure_evidence",
            return_value=["tampered V2 failure evidence"],
        ):
            report = gate.build_report()
        self.assertFalse(report["passed"])
        self.assertIn(
            "exact_5335bda_admin_dependency_cache_v2_attempt1_failed_artifact0",
            {item["name"] for item in report["failed_checks"]},
        )

        with mock.patch.object(
            gate,
            "verify_admin_dependency_cache_v3_failure_evidence",
            return_value=["tampered V3 failure evidence"],
        ):
            report = gate.build_report()
        self.assertFalse(report["passed"])
        self.assertIn(
            "exact_5335bda_admin_dependency_cache_v3_attempt1_failed_artifact0",
            {item["name"] for item in report["failed_checks"]},
        )

        with mock.patch.object(
            gate,
            "verify_admin_dependency_cache_v4_failure_evidence",
            return_value=["tampered V4 failure evidence"],
        ):
            report = gate.build_report()
        self.assertFalse(report["passed"])
        self.assertIn(
            "exact_5335bda_admin_dependency_cache_v4_attempt1_failed_artifact0",
            {item["name"] for item in report["failed_checks"]},
        )

        with mock.patch.object(
            gate,
            "validate_admin_dependency_cache_export_plan_v3",
            return_value=["tampered V3 recovery plan"],
        ):
            report = gate.build_report()
        self.assertFalse(report["passed"])
        self.assertIn(
            "exact_5335bda_admin_dependency_cache_v3_recovery_plan_fail_closed",
            {item["name"] for item in report["failed_checks"]},
        )

        with mock.patch.object(
            gate,
            "validate_admin_dependency_cache_export_plan_v4",
            return_value=["tampered V4 recovery plan"],
        ):
            report = gate.build_report()
        self.assertFalse(report["passed"])
        self.assertIn(
            "exact_5335bda_admin_dependency_cache_v4_recovery_plan_fail_closed",
            {item["name"] for item in report["failed_checks"]},
        )

        with mock.patch.object(
            gate,
            "validate_admin_dependency_cache_export_plan_v5",
            return_value=["tampered V5 recovery plan"],
        ):
            report = gate.build_report()
        self.assertFalse(report["passed"])
        self.assertIn(
            "exact_5335bda_admin_dependency_cache_v5_recovery_plan_fail_closed",
            {item["name"] for item in report["failed_checks"]},
        )

        with mock.patch.object(
            gate,
            "validate_admin_dependency_cache_export_plan_v6",
            return_value=["tampered V6 recovery plan"],
        ):
            report = gate.build_report()
        self.assertFalse(report["passed"])
        self.assertIn(
            "exact_5335bda_admin_dependency_cache_v6_recovery_plan_fail_closed",
            {item["name"] for item in report["failed_checks"]},
        )

        with mock.patch.object(
            gate,
            "verify_admin_dependency_cache_v5_failure_evidence",
            return_value=["tampered V5 failure evidence"],
        ):
            report = gate.build_report()
        self.assertFalse(report["passed"])
        self.assertIn(
            "exact_5335bda_admin_dependency_cache_v5_attempt1_failed_artifact0",
            {item["name"] for item in report["failed_checks"]},
        )

        with mock.patch.object(
            gate,
            "verify_admin_dependency_cache_v6_failure_evidence",
            return_value=["tampered V6 failure evidence"],
        ):
            report = gate.build_report()
        self.assertFalse(report["passed"])
        self.assertIn(
            "exact_5335bda_admin_dependency_cache_v6_attempt1_failed_artifact0",
            {item["name"] for item in report["failed_checks"]},
        )

        with mock.patch.object(
            gate,
            "validate_admin_dependency_cache_export_plan_v7",
            return_value=["tampered V7 recovery plan"],
        ):
            report = gate.build_report()
        self.assertFalse(report["passed"])
        self.assertIn(
            "exact_5335bda_admin_dependency_cache_v7_recovery_plan_fail_closed",
            {item["name"] for item in report["failed_checks"]},
        )

        with mock.patch.object(
            gate,
            "verify_admin_dependency_cache_v7_failure_evidence",
            return_value=["tampered V7 failure evidence"],
        ):
            report = gate.build_report()
        self.assertFalse(report["passed"])
        self.assertIn(
            "exact_5335bda_admin_dependency_cache_v7_attempt1_failed_artifact0",
            {item["name"] for item in report["failed_checks"]},
        )

        with mock.patch.object(
            gate,
            "validate_admin_dependency_cache_export_plan_v8",
            return_value=["tampered V8 recovery plan"],
        ):
            report = gate.build_report()
        self.assertFalse(report["passed"])
        self.assertIn(
            "exact_5335bda_admin_dependency_cache_v8_recovery_plan_fail_closed",
            {item["name"] for item in report["failed_checks"]},
        )

        with mock.patch.object(
            gate,
            "verify_admin_dependency_cache_v8_failure_evidence",
            return_value=["tampered V8 failure evidence"],
        ):
            report = gate.build_report()
        self.assertFalse(report["passed"])
        self.assertIn(
            "exact_5335bda_admin_dependency_cache_v8_attempt1_failed_artifact0",
            {item["name"] for item in report["failed_checks"]},
        )

        with mock.patch.object(
            gate,
            "validate_admin_dependency_cache_export_plan_v9",
            return_value=["tampered V9 recovery plan"],
        ):
            report = gate.build_report()
        self.assertFalse(report["passed"])
        self.assertIn(
            "exact_5335bda_admin_dependency_cache_v9_recovery_plan_fail_closed",
            {item["name"] for item in report["failed_checks"]},
        )

        with mock.patch.object(
            gate,
            "verify_admin_dependency_cache_v9_failure_evidence",
            return_value=["tampered V9 failure evidence"],
        ):
            report = gate.build_report()
        self.assertFalse(report["passed"])
        self.assertIn(
            "exact_5335bda_admin_dependency_cache_v9_attempt1_failed_artifact0",
            {item["name"] for item in report["failed_checks"]},
        )

        with mock.patch.object(
            gate,
            "validate_admin_dependency_cache_export_plan_v10",
            return_value=["tampered V10 recovery plan"],
        ):
            report = gate.build_report()
        self.assertFalse(report["passed"])
        self.assertIn(
            "exact_5335bda_admin_dependency_cache_v10_recovery_plan_fail_closed",
            {item["name"] for item in report["failed_checks"]},
        )

        with mock.patch.object(
            gate,
            "verify_admin_dependency_cache_v10_failure_evidence",
            return_value=["tampered V10 failure evidence"],
        ):
            report = gate.build_report()
        self.assertFalse(report["passed"])
        self.assertIn(
            "exact_5335bda_admin_dependency_cache_v10_attempt1_failed_artifact0",
            {item["name"] for item in report["failed_checks"]},
        )

        with mock.patch.object(
            gate,
            "validate_v11_untriggered_supersession",
            return_value=["tampered V11 supersession"],
        ):
            report = gate.build_report()
        self.assertFalse(report["passed"])
        self.assertIn(
            "exact_5335bda_admin_dependency_cache_v11_recovery_plan_fail_closed",
            {item["name"] for item in report["failed_checks"]},
        )

        with mock.patch.object(
            gate,
            "validate_admin_dependency_cache_export_plan_v12",
            return_value=["tampered V12 recovery plan"],
        ):
            report = gate.build_report()
        self.assertFalse(report["passed"])
        self.assertIn(
            "exact_5335bda_admin_dependency_cache_v12_recovery_plan_fail_closed",
            {item["name"] for item in report["failed_checks"]},
        )

        with mock.patch.object(
            gate,
            "verify_admin_dependency_cache_v12_failure_evidence",
            return_value=["tampered V12 failure evidence"],
        ):
            report = gate.build_report()
        self.assertFalse(report["passed"])
        self.assertIn(
            "exact_5335bda_admin_dependency_cache_v12_attempt1_failed_artifact0",
            {item["name"] for item in report["failed_checks"]},
        )

        with mock.patch.object(
            gate,
            "validate_admin_dependency_cache_v16_predecessor",
            return_value=["tampered V16 terminal predecessor"],
        ):
            report = gate.build_report()
        self.assertFalse(report["passed"])
        self.assertIn(
            "exact_5335bda_admin_dependency_cache_v16_recovery_plan_fail_closed",
            {item["name"] for item in report["failed_checks"]},
        )

        with mock.patch.object(
            gate,
            "evaluate_admin_dependency_cache_export_plan_v17",
            return_value=(["tampered V17 recovery plan"], "INVALID", []),
        ):
            report = gate.build_report()
        self.assertFalse(report["passed"])
        self.assertIn(
            "exact_5335bda_admin_dependency_cache_v17_recovery_plan_fail_closed",
            {item["name"] for item in report["failed_checks"]},
        )

    def test_v15_terminal_evidence_is_fail_closed_in_repository_gate(self):
        with mock.patch.object(
            gate,
            "verify_admin_dependency_cache_v15_failure_evidence",
            return_value=["tampered V15 failure evidence"],
        ):
            checks = {
                item["name"]: item for item in gate.check_browserless_vex()
            }
        self.assertFalse(
            checks[
                "exact_5335bda_admin_dependency_cache_v15_"
                "attempt1_failed_artifact0"
            ]["passed"]
        )

    def test_v16_terminal_evidence_is_fail_closed_in_repository_gate(self):
        self.assertFalse(
            gate._v16_terminal_failure_evidence_accepted(
                "V16_TRIGGERED_ATTEMPT1_FAILED_"
                "TERMINAL_SUPERSESSION_EXACT",
                ["tampered V16 failure evidence"],
            )
        )
        self.assertIn(
            "tampered V16 failure evidence",
            gate._v16_terminal_failure_evidence_detail(
                "V16_TRIGGERED_ATTEMPT1_FAILED_"
                "TERMINAL_SUPERSESSION_EXACT",
                ["tampered V16 failure evidence"],
            ),
        )

    def test_v16_terminal_evidence_is_not_claimed_while_only_armed(self):
        state = "V16_ARMED_OR_TRIGGERED_EXACT"
        self.assertFalse(
            gate._v16_terminal_failure_evidence_accepted(state, [])
        )
        self.assertIn(
            "not active",
            gate._v16_terminal_failure_evidence_detail(state, []),
        )

    def test_v16_terminal_evidence_accepts_both_exact_terminal_states(self):
        for state in gate.V16_TERMINAL_FAILURE_STATES:
            with self.subTest(state=state):
                self.assertTrue(
                    gate._v16_terminal_failure_evidence_accepted(state, [])
                )
                self.assertIn(
                    "UNKNOWN_NOT_REACHED",
                    gate._v16_terminal_failure_evidence_detail(state, []),
                )

    def test_v4_gate_detail_reports_armed_state_without_claiming_absence(self):
        with (
            mock.patch.object(
                gate,
                "validate_admin_dependency_cache_export_plan_v4",
                return_value=[],
            ),
            mock.patch.object(
                gate,
                "admin_dependency_cache_plan_state_v4",
                return_value="V4_ARMED_OR_TRIGGERED_EXACT",
            ),
        ):
            checks = {item["name"]: item for item in gate.check_browserless_vex()}

        detail = checks[
            "exact_5335bda_admin_dependency_cache_v4_recovery_plan_fail_closed"
        ]["detail"]
        self.assertIn("state=V4_ARMED_OR_TRIGGERED_EXACT", detail)
        self.assertNotIn("activation absent", detail)

    def test_v5_gate_detail_reports_armed_state_without_claiming_absence(self):
        with (
            mock.patch.object(
                gate,
                "validate_admin_dependency_cache_export_plan_v5",
                return_value=[],
            ),
            mock.patch.object(
                gate,
                "admin_dependency_cache_plan_state_v5",
                return_value="V5_ARMED_OR_TRIGGERED_EXACT",
            ),
        ):
            checks = {item["name"]: item for item in gate.check_browserless_vex()}

        detail = checks[
            "exact_5335bda_admin_dependency_cache_v5_recovery_plan_fail_closed"
        ]["detail"]
        self.assertIn("state=V5_ARMED_OR_TRIGGERED_EXACT", detail)
        self.assertNotIn("activation absent", detail)

    def test_v6_gate_detail_reports_armed_state_without_claiming_absence(self):
        with (
            mock.patch.object(
                gate,
                "validate_admin_dependency_cache_export_plan_v6",
                return_value=[],
            ),
            mock.patch.object(
                gate,
                "admin_dependency_cache_plan_state_v6",
                return_value="V6_ARMED_OR_TRIGGERED_EXACT",
            ),
        ):
            checks = {item["name"]: item for item in gate.check_browserless_vex()}

        detail = checks[
            "exact_5335bda_admin_dependency_cache_v6_recovery_plan_fail_closed"
        ]["detail"]
        self.assertIn("state=V6_ARMED_OR_TRIGGERED_EXACT", detail)
        self.assertNotIn("activation absent", detail)

    def test_v7_gate_detail_reports_armed_state_without_claiming_absence(self):
        with (
            mock.patch.object(
                gate,
                "validate_admin_dependency_cache_export_plan_v7",
                return_value=[],
            ),
            mock.patch.object(
                gate,
                "admin_dependency_cache_plan_state_v7",
                return_value="V7_ARMED_OR_TRIGGERED_EXACT",
            ),
        ):
            checks = {item["name"]: item for item in gate.check_browserless_vex()}

        detail = checks[
            "exact_5335bda_admin_dependency_cache_v7_recovery_plan_fail_closed"
        ]["detail"]
        self.assertIn("state=V7_ARMED_OR_TRIGGERED_EXACT", detail)
        self.assertNotIn("activation absent", detail)

    def test_v8_gate_detail_reports_armed_state_without_claiming_absence(self):
        with (
            mock.patch.object(
                gate,
                "validate_admin_dependency_cache_export_plan_v8",
                return_value=[],
            ),
            mock.patch.object(
                gate,
                "admin_dependency_cache_plan_state_v8",
                return_value="V8_ARMED_OR_TRIGGERED_EXACT",
            ),
        ):
            checks = {item["name"]: item for item in gate.check_browserless_vex()}

        detail = checks[
            "exact_5335bda_admin_dependency_cache_v8_recovery_plan_fail_closed"
        ]["detail"]
        self.assertIn("state=V8_ARMED_OR_TRIGGERED_EXACT", detail)
        self.assertNotIn("activation absent", detail)

    def test_v9_gate_detail_reports_armed_state_without_claiming_absence(self):
        with (
            mock.patch.object(
                gate,
                "validate_admin_dependency_cache_export_plan_v9",
                return_value=[],
            ),
            mock.patch.object(
                gate,
                "admin_dependency_cache_plan_state_v9",
                return_value="V9_ARMED_OR_TRIGGERED_EXACT",
            ),
        ):
            checks = {item["name"]: item for item in gate.check_browserless_vex()}

        detail = checks[
            "exact_5335bda_admin_dependency_cache_v9_recovery_plan_fail_closed"
        ]["detail"]
        self.assertIn("state=V9_ARMED_OR_TRIGGERED_EXACT", detail)
        self.assertNotIn("activation absent", detail)

    def test_v9_gate_rejects_invalid_or_consumed_state(self):
        for state in ("INVALID", "V9_CONSUMED_OR_INVALID"):
            with self.subTest(state=state), mock.patch.object(
                gate,
                "validate_admin_dependency_cache_export_plan_v9",
                return_value=[],
            ), mock.patch.object(
                gate,
                "admin_dependency_cache_plan_state_v9",
                return_value=state,
            ):
                report = gate.build_report()
            self.assertFalse(report["passed"])
            failed = {item["name"] for item in report["failed_checks"]}
            self.assertIn(
                "exact_5335bda_admin_dependency_cache_v9_recovery_plan_fail_closed",
                failed,
            )

    def test_v10_gate_detail_reports_armed_state_without_claiming_absence(self):
        with (
            mock.patch.object(
                gate,
                "validate_admin_dependency_cache_export_plan_v10",
                return_value=[],
            ),
            mock.patch.object(
                gate,
                "admin_dependency_cache_plan_state_v10",
                return_value="V10_ARMED_OR_TRIGGERED_EXACT",
            ),
        ):
            checks = {item["name"]: item for item in gate.check_browserless_vex()}

        detail = checks[
            "exact_5335bda_admin_dependency_cache_v10_recovery_plan_fail_closed"
        ]["detail"]
        self.assertIn("state=V10_ARMED_OR_TRIGGERED_EXACT", detail)
        self.assertNotIn("activation absent", detail)

    def test_v10_gate_rejects_invalid_or_consumed_state(self):
        for state in ("INVALID", "V10_CONSUMED_OR_INVALID"):
            with self.subTest(state=state), mock.patch.object(
                gate,
                "validate_admin_dependency_cache_export_plan_v10",
                return_value=[],
            ), mock.patch.object(
                gate,
                "admin_dependency_cache_plan_state_v10",
                return_value=state,
            ):
                report = gate.build_report()
            self.assertFalse(report["passed"])
            failed = {item["name"] for item in report["failed_checks"]}
            self.assertIn(
                "exact_5335bda_admin_dependency_cache_v10_recovery_plan_fail_closed",
                failed,
            )

    def test_v11_gate_requires_exact_untriggered_supersession(self):
        with (
            mock.patch.object(
                gate,
                "validate_v11_untriggered_supersession",
                return_value=[],
            ),
            mock.patch.object(
                gate,
                "v11_untriggered_supersession_state",
                return_value="V11_UNTRIGGERED_SUPERSEDED_EXACT",
            ),
        ):
            checks = {item["name"]: item for item in gate.check_browserless_vex()}

        detail = checks[
            "exact_5335bda_admin_dependency_cache_v11_recovery_plan_fail_closed"
        ]["detail"]
        self.assertIn("state=V11_UNTRIGGERED_SUPERSEDED_EXACT", detail)
        self.assertIn("never triggered", detail)
        self.assertIn("superseded", detail)
        self.assertNotIn("completed", detail)
        self.assertNotIn("artifact created", detail)

    def test_v11_gate_rejects_every_non_superseded_state(self):
        for state in (
            "PREPARED_V11_NOT_TRIGGERED",
            "V11_ARMED_OR_TRIGGERED_EXACT",
            "V11_CONSUMED_OR_INVALID",
            "INVALID",
        ):
            with self.subTest(state=state), mock.patch.object(
                gate,
                "validate_v11_untriggered_supersession",
                return_value=[],
            ), mock.patch.object(
                gate,
                "v11_untriggered_supersession_state",
                return_value=state,
            ):
                report = gate.build_report()
            self.assertFalse(report["passed"])
            failed = {item["name"] for item in report["failed_checks"]}
            self.assertIn(
                "exact_5335bda_admin_dependency_cache_v11_recovery_plan_fail_closed",
                failed,
            )

    def test_v11_pending_supersession_requires_exact_v12_prepared_state(self):
        with (
            mock.patch.object(
                gate,
                "validate_v11_untriggered_supersession",
                return_value=[],
            ),
            mock.patch.object(
                gate,
                "v11_untriggered_supersession_state",
                return_value="V11_UNTRIGGERED_SUPERSESSION_PENDING",
            ),
            mock.patch.object(
                gate,
                "validate_admin_dependency_cache_export_plan_v12",
                return_value=[],
            ),
            mock.patch.object(
                gate,
                "admin_dependency_cache_plan_state_v12",
                return_value="PREPARED_V12_NOT_TRIGGERED",
            ),
        ):
            checks = {item["name"]: item for item in gate.check_browserless_vex()}
        self.assertTrue(
            checks[
                "exact_5335bda_admin_dependency_cache_v11_recovery_plan_fail_closed"
            ]["passed"]
        )

        with (
            mock.patch.object(
                gate,
                "validate_v11_untriggered_supersession",
                return_value=[],
            ),
            mock.patch.object(
                gate,
                "v11_untriggered_supersession_state",
                return_value="V11_UNTRIGGERED_SUPERSESSION_PENDING",
            ),
            mock.patch.object(
                gate,
                "validate_admin_dependency_cache_export_plan_v12",
                return_value=[],
            ),
            mock.patch.object(
                gate,
                "admin_dependency_cache_plan_state_v12",
                return_value="V12_ARMED_OR_TRIGGERED_EXACT",
            ),
        ):
            checks = {item["name"]: item for item in gate.check_browserless_vex()}
        self.assertFalse(
            checks[
                "exact_5335bda_admin_dependency_cache_v11_recovery_plan_fail_closed"
            ]["passed"]
        )

    def test_v12_gate_detail_reports_armed_state_without_claiming_absence(self):
        with (
            mock.patch.object(
                gate,
                "validate_admin_dependency_cache_export_plan_v12",
                return_value=[],
            ),
            mock.patch.object(
                gate,
                "admin_dependency_cache_plan_state_v12",
                return_value="V12_ARMED_OR_TRIGGERED_EXACT",
            ),
        ):
            checks = {item["name"]: item for item in gate.check_browserless_vex()}

        detail = checks[
            "exact_5335bda_admin_dependency_cache_v12_recovery_plan_fail_closed"
        ]["detail"]
        self.assertIn("state=V12_ARMED_OR_TRIGGERED_EXACT", detail)
        self.assertNotIn("active request is absent", detail)

    def test_v12_gate_rejects_invalid_or_consumed_state(self):
        for state in ("INVALID", "V12_CONSUMED_OR_INVALID"):
            with self.subTest(state=state), mock.patch.object(
                gate,
                "validate_admin_dependency_cache_export_plan_v12",
                return_value=[],
            ), mock.patch.object(
                gate,
                "admin_dependency_cache_plan_state_v12",
                return_value=state,
            ):
                report = gate.build_report()
            self.assertFalse(report["passed"])
            failed = {item["name"] for item in report["failed_checks"]}
            self.assertIn(
                "exact_5335bda_admin_dependency_cache_v12_recovery_plan_fail_closed",
                failed,
            )

    def test_v12_gate_accepts_versioned_terminal_states(self):
        for state in (
            "V12_TRIGGERED_ATTEMPT1_FAILED_TERMINAL_SUPERSESSION_EXACT",
            "V12_TRIGGERED_ATTEMPT1_FAILED_TERMINAL_RECEIPT_EXACT",
        ):
            with (
                self.subTest(state=state),
                mock.patch.object(
                    gate,
                    "validate_admin_dependency_cache_export_plan_v12",
                    return_value=[],
                ),
                mock.patch.object(
                    gate,
                    "admin_dependency_cache_plan_state_v12",
                    return_value=state,
                ),
            ):
                checks = {
                    item["name"]: item for item in gate.check_browserless_vex()
                }
            self.assertTrue(
                checks[
                    "exact_5335bda_admin_dependency_cache_v12_"
                    "recovery_plan_fail_closed"
                ]["passed"]
            )

    def test_v16_gate_requires_fixed_terminal_predecessor(self):
        check_name = (
            "exact_5335bda_admin_dependency_cache_v16_"
            "recovery_plan_fail_closed"
        )
        with mock.patch.object(
            gate,
            "validate_admin_dependency_cache_v16_predecessor",
            return_value=[],
        ):
            checks = {
                item["name"]: item for item in gate.check_browserless_vex()
            }
        self.assertTrue(checks[check_name]["passed"])

        with mock.patch.object(
            gate,
            "validate_admin_dependency_cache_v16_predecessor",
            return_value=["terminal receipt drift"],
        ):
            checks = {
                item["name"]: item for item in gate.check_browserless_vex()
            }
        self.assertFalse(checks[check_name]["passed"])

    def test_v17_gate_accepts_only_prepared_or_armed_states(self):
        check_name = (
            "exact_5335bda_admin_dependency_cache_v17_"
            "recovery_plan_fail_closed"
        )
        for state in ("PREPARED_V17_NOT_TRIGGERED", "V17_ARMED_OR_TRIGGERED_EXACT"):
            with (
                self.subTest(state=state),
                mock.patch.object(
                    gate,
                    "evaluate_admin_dependency_cache_export_plan_v17",
                    return_value=([], state, []),
                ),
            ):
                checks = {
                    item["name"]: item for item in gate.check_browserless_vex()
                }
            self.assertTrue(checks[check_name]["passed"])

        for state in ("INVALID", "V17_CONSUMED_OR_INVALID"):
            with (
                self.subTest(state=state),
                mock.patch.object(
                    gate,
                    "evaluate_admin_dependency_cache_export_plan_v17",
                    return_value=([], state, []),
                ),
            ):
                checks = {
                    item["name"]: item for item in gate.check_browserless_vex()
                }
            self.assertFalse(checks[check_name]["passed"])

    def test_api_c_runtime_evidence_is_fail_closed_in_repository_gate(self):
        checks = {
            item["name"]: item
            for item in gate.check_api_c_current_release_evidence()
        }
        self.assertTrue(
            checks["exact_api_c_b55_runtime_deployment_evidence"]["passed"]
        )

        with mock.patch.object(
            gate,
            "validate_api_c_current_release_evidence_bundle",
            return_value=["tampered runtime evidence"],
        ):
            report = gate.build_report()
        self.assertFalse(report["passed"])
        self.assertIn(
            "exact_api_c_b55_runtime_deployment_evidence",
            {item["name"] for item in report["failed_checks"]},
        )

    def test_api_f_runtime_evidence_is_fail_closed_in_repository_gate(self):
        checks = {
            item["name"]: item
            for item in gate.check_api_f_current_release_evidence()
        }
        self.assertTrue(
            checks["exact_api_f_b55_runtime_deployment_evidence"]["passed"]
        )

        with mock.patch.object(
            gate,
            "validate_api_f_current_release_evidence_bundle",
            return_value=["tampered runtime evidence"],
        ):
            report = gate.build_report()
        self.assertFalse(report["passed"])
        self.assertIn(
            "exact_api_f_b55_runtime_deployment_evidence",
            {item["name"] for item in report["failed_checks"]},
        )

    def test_ci_unit_test_environment_isolation_contract_is_exact(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertTrue(gate._ci_unit_test_contract_valid(workflow))

        mutations = {
            "missing-v13-exclusion": (
                "              ! -name 'test_admin_dependency_cache_export_plan_v13.py' \\\n",
                "",
            ),
            "missing-v14-exclusion": (
                "              ! -name 'test_admin_dependency_cache_export_plan_v14.py' \\\n",
                "",
            ),
            "missing-v16-exclusion": (
                "              ! -name 'test_admin_dependency_cache_export_plan_v16.py' \\\n",
                "",
            ),
            "wrong-isolated-target": (
                "              tests.test_admin_dependency_cache_export_plan_v13.AdminDependencyCacheExportPlanV13Tests.test_exact_checkpoint_receipt_and_activation_git_history\n",
                "              tests.test_admin_dependency_cache_export_plan_v13.AdminDependencyCacheExportPlanV13Tests.test_reviewed_authorities_validate_without_git_state\n",
            ),
            "topology-test-moved-to-ambient": (
                "            tests.test_admin_dependency_cache_export_plan_v13.AdminDependencyCacheExportPlanV13Tests.test_reviewed_authorities_validate_without_git_state \\\n",
                "            tests.test_admin_dependency_cache_export_plan_v13.AdminDependencyCacheExportPlanV13Tests.test_exact_checkpoint_receipt_and_activation_git_history \\\n",
            ),
            "ambient-command-moved": (
                '          python -m unittest "${ambient_test_files[@]}"\n',
                '          env python -m unittest "${ambient_test_files[@]}"\n',
            ),
            "historical-c14-drift": (
                "            e18d24a204c33127a95fe3035b7fce43bdb0b4f8\n",
                "            4df6a77e39f2488b852414bb0649babbb37eb98a\n",
            ),
            "historical-v14-target-drift": (
                "                tests/test_admin_dependency_cache_export_plan_v14.py\n",
                "                tests/test_admin_dependency_cache_export_plan_v13.py\n",
            ),
            "historical-tr16-drift": (
                "            751da973dd7136d792adfafa11e50f5e5e0bd689\n",
                "            4c2df3b19b4f5493adba78eed89c3a015d76972d\n",
            ),
            "timeout-budget-drift": (
                "    timeout-minutes: 25\n",
                "    timeout-minutes: 20\n",
            ),
            "trailing-ambient-v13-invocation": (
                "\n      - name: Quality gate\n",
                "\n          python -m unittest "
                "tests/test_admin_dependency_cache_export_plan_v13.py\n"
                "\n      - name: Quality gate\n",
            ),
        }
        for variable in (
            "GITHUB_ACTIONS",
            "GITHUB_SHA",
            "GITHUB_EVENT_NAME",
            "GITHUB_REF",
        ):
            mutations[f"missing-{variable.lower()}"] = (
                f"            -u {variable} \\\n",
                "",
            )

        for name, (before, after) in mutations.items():
            with self.subTest(name=name):
                self.assertIn(before, workflow)
                candidate = workflow.replace(before, after, 1)
                self.assertFalse(gate._ci_unit_test_contract_valid(candidate))

        self.assertFalse(
            gate._ci_unit_test_contract_valid(
                workflow + "\n" + gate.CI_UNIT_TEST_CONTRACT
            )
        )

    def test_production_roles_exclude_browser_dependencies_and_commands(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        api_requirements = (MODEL_DIR / "requirements-api.txt").read_text(encoding="utf-8")
        worker_requirements = (MODEL_DIR / "requirements-worker.txt").read_text(encoding="utf-8")
        api_stage = dockerfile.split("FROM runtime-common AS api-runtime", 1)[1].split(
            "FROM runtime-common AS admin-runtime", 1
        )[0]
        admin_stage = dockerfile.split("FROM runtime-common AS admin-runtime", 1)[1].split(
            "FROM runtime-common AS payment-runtime", 1
        )[0]
        payment_stage = dockerfile.split(
            "FROM runtime-common AS payment-runtime", 1
        )[1].split(
            "FROM runtime-common AS ai-worker-runtime", 1
        )[0]
        ai_worker_stage = dockerfile.split(
            "FROM runtime-common AS ai-worker-runtime", 1
        )[1].split(
            "FROM runtime-common AS xhs-http-runtime", 1
        )[0]
        xhs_stage = dockerfile.split("FROM runtime-common AS xhs-http-runtime", 1)[1].split(
            "FROM ${NOTEAI_RUNTIME_TARGET} AS noteai-runtime", 1
        )[0]

        self.assertIn("FROM runtime-common AS api-runtime", dockerfile)
        self.assertIn("FROM runtime-common AS admin-runtime", dockerfile)
        self.assertIn("FROM runtime-common AS payment-runtime", dockerfile)
        self.assertIn("FROM runtime-common AS ai-worker-runtime", dockerfile)
        self.assertIn("FROM runtime-common AS xhs-http-runtime", dockerfile)
        self.assertNotIn("FROM runtime-common AS worker-runtime", dockerfile)
        self.assertIn("FROM ${NOTEAI_RUNTIME_TARGET} AS noteai-runtime", dockerfile)
        self.assertIn('CMD ["/app/scripts/render_start_api.sh"]', api_stage)
        self.assertIn('CMD ["/app/scripts/render_start_admin.sh"]', admin_stage)
        self.assertIn(
            'CMD ["/app/scripts/render_start_payment.sh"]',
            payment_stage,
        )
        self.assertIn(
            'CMD ["python", "durable_ai_worker.py", "--once"]',
            ai_worker_stage,
        )
        self.assertIn('CMD ["/bin/false"]', xhs_stage)
        self.assertIn("NOTEAI_XHS_COLLECTION_SUSPENDED=1", xhs_stage)
        self.assertIn("HEALTHCHECK NONE", xhs_stage)
        for stage in (
            api_stage,
            admin_stage,
            payment_stage,
            ai_worker_stage,
            xhs_stage,
        ):
            self.assertNotIn("playwright", stage.lower())
            self.assertNotIn("chromium", stage.lower())
        for package in ("libgl1", "libglib2.0-0", "libsm6", "libxext6", "libxrender1"):
            self.assertNotIn(package, dockerfile)
        self.assertNotIn("playwright==", api_requirements)
        self.assertIn("playwright==1.56.0", worker_requirements)
        self.assertNotIn("python -m playwright install", dockerfile)
        self.assertNotIn("apt-get autoremove", dockerfile)
        self.assertIn("CRYPTO_JS_VERSION=4.2.0", dockerfile)
        for stage in (
            api_stage,
            admin_stage,
            payment_stage,
            ai_worker_stage,
            xhs_stage,
        ):
            self.assertIn("USER noteai", stage)
        self.assertIn("python -m pip uninstall -y setuptools wheel", dockerfile)
        self.assertIn("python -m pip check", dockerfile)
        self.assertNotIn("CMD curl", dockerfile)
        self.assertNotIn('"curl"', compose)
        self.assertEqual(compose.count("import http.client, sys"), 3)
        self.assertEqual(compose.count("target: api-runtime"), 1)
        self.assertEqual(compose.count("target: admin-runtime"), 1)
        self.assertEqual(compose.count("target: payment-runtime"), 1)
        self.assertEqual(compose.count("target: ai-worker-runtime"), 1)
        self.assertEqual(compose.count("target: xhs-http-runtime"), 2)
        self.assertEqual(compose.count("no-new-privileges:true"), 6)
        self.assertEqual(compose.count("privileged: false"), 6)
        self.assertEqual(compose.count('user: "999:999"'), 6)
        self.assertEqual(compose.count("read_only: true"), 6)
        self.assertEqual(compose.count("cap_drop:"), 6)
        self.assertNotIn("seccomp=", compose)

    def test_role_requirements_are_exactly_pinned_and_compatibility_is_recursive(self):
        api_lines = [
            line.strip()
            for line in (MODEL_DIR / "requirements-api.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        worker_lines = [
            line.strip()
            for line in (MODEL_DIR / "requirements-worker.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        compatibility_lines = [
            line.strip()
            for line in (MODEL_DIR / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

        self.assertTrue(api_lines)
        self.assertTrue(all(re.fullmatch(r"[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==[^\s]+", line) for line in api_lines))
        self.assertIn("pillow==12.3.0", api_lines)
        self.assertIn("cryptography==48.0.1", api_lines)
        self.assertFalse(any(line.lower().startswith("mlflow==") for line in api_lines))
        self.assertIn("alibabacloud-oss-v2==1.3.2", api_lines)
        self.assertIn("alibabacloud_credentials==1.0.10", api_lines)
        self.assertEqual(worker_lines, ["-r requirements-api.txt", "playwright==1.56.0"])
        self.assertEqual(compatibility_lines, ["-r requirements-api.txt"])

    def test_private_storage_and_restore_contract_is_fail_closed(self):
        source = (MODEL_DIR / "private_storage.py").read_text(encoding="utf-8")
        recovery = (
            MODEL_DIR / "storage_recovery_evidence.py"
        ).read_text(encoding="utf-8")
        migration = (
            MODEL_DIR
            / "migrations"
            / "postgres"
            / "0013_private_storage_recovery_contract.sql"
        ).read_text(encoding="utf-8")
        api_source = (MODEL_DIR / "api.py").read_text(encoding="utf-8")

        self.assertIn("forbid_overwrite=True", source)
        self.assertIn('type="ecs_ram_role"', source)
        self.assertIn("enable_imds_v2=True", source)
        self.assertIn("disable_imds_v1=True", source)
        self.assertIn("metadata_token_duration=60", source)
        self.assertIn("static OSS credentials are prohibited", source)
        self.assertIn("use_internal_endpoint = True", source)
        self.assertIn("CREATE TABLE IF NOT EXISTS private_media_refs", migration)
        self.assertIn("noteai_validate_operation_media_link_v1", migration)
        self.assertNotIn("GRANT ", migration.upper())
        self.assertNotIn("REVOKE ", migration.upper())
        self.assertIn("_stream_upload_to_temp", api_source)
        self.assertIn("_private_storage.load_media_bytes(", api_source)
        self.assertIn("\"row_values_included\": False", recovery)
        self.assertIn("\"object_keys_included\": False", recovery)
        self.assertIn("database_tables", recovery)
        self.assertIn("private_objects", recovery)

    def _run_entrypoint_guard(
        self,
        image_role,
        declared_role,
        command,
        *,
        marker_state="valid",
        check_pre_artifact=False,
        **extra_env,
    ):
        source = (ROOT / "scripts" / "docker_entrypoint.sh").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            marker = tmp_path / "noteai-runtime-role"
            if marker_state == "valid":
                marker.write_text(f"{image_role}\n", encoding="utf-8")
            elif marker_state == "empty":
                marker.write_text("\n", encoding="utf-8")
            elif marker_state == "unreadable":
                marker.write_text(f"{image_role}\n", encoding="utf-8")
                marker.chmod(0o000)
            elif marker_state == "read_failure":
                marker.write_text(image_role, encoding="utf-8")
            elif marker_state != "missing":
                raise AssertionError(f"unknown marker state: {marker_state}")
            artifact_sentinel = tmp_path / "artifact-loader-called"
            script = tmp_path / "docker_entrypoint.sh"
            script.write_text(
                source.replace(
                    "runtime_role_file=/etc/noteai-runtime-role",
                    f"runtime_role_file='{marker}'",
                ).replace(
                    "cd /app/model",
                    f"cd '{MODEL_DIR}'",
                ).replace(
                    "  python -m artifact_loader",
                    f"  printf '%s\\n' called > '{artifact_sentinel}'",
                ).replace(
                    'exec "$@"',
                    "exit 0",
                ),
                encoding="utf-8",
            )
            env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "NOTEAI_RUNTIME_ROLE": declared_role,
                "NOTEAI_SKIP_MODEL_ARTIFACT_CHECK": "0" if check_pre_artifact else "1",
                **extra_env,
            }
            result = subprocess.run(
                ["sh", str(script), *command],
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            return result, artifact_sentinel.exists()

    def test_runtime_role_guard_fails_closed_before_artifact_loading(self):
        cases = (
            ("missing", "api", "api"),
            ("unreadable", "api", "api"),
            ("empty", "api", "api"),
            ("read_failure", "api", "api"),
            ("valid", "api", "admin"),
            ("valid", "api", ""),
            ("valid", "invalid", "invalid"),
        )
        for marker_state, image_role, declared_role in cases:
            with self.subTest(
                marker_state=marker_state,
                image_role=image_role,
                declared_role=declared_role,
            ):
                result, artifact_called = self._run_entrypoint_guard(
                    image_role,
                    declared_role,
                    ["/app/scripts/render_start_api.sh"],
                    marker_state=marker_state,
                    check_pre_artifact=True,
                )

                self.assertEqual(result.returncode, 78, result.stderr)
                self.assertFalse(artifact_called, "artifact loader ran before role rejection")

    def test_runtime_role_allowlists_accept_only_current_service_contracts(self):
        allowed = {
            "api": (
                ["/app/scripts/render_start_api.sh"],
                ["python", "/app/scripts/render_predeploy.py"],
            ),
            "admin": (
                ["/app/scripts/render_start_admin.sh"],
                ["python", "-m", "uvicorn", "admin_server:admin_app", "--host", "0.0.0.0", "--port", "8001"],
            ),
            "payment": (
                ["/app/scripts/render_start_payment.sh"],
            ),
            "ai-worker": (
                ["python", "durable_ai_worker.py", "--healthcheck"],
                ["python", "durable_ai_worker.py", "--once"],
                ["python", "durable_ai_worker.py", "--recover-unstarted"],
                ["python", "durable_ai_worker.py", "--reconcile-stale"],
            ),
            "xhs-http": (
                ["/app/scripts/render_run_market_timing.sh"],
                ["/app/scripts/render_run_crawler.sh"],
                ["python", "market_timing_worker.py"],
                ["python", "market_timing_worker.py", "--once"],
                ["python", "market_timing_worker.py", "--daemon", "--interval", "60"],
                ["python", "market_timing_worker.py", "--healthcheck"],
                ["python", "market_timing_worker.py", "--acknowledge-unknown"],
                ["python", "market_timing_worker.py", "--clear-session-block"],
                ["python", "crawler_worker.py"],
                ["python", "crawler_worker.py", "--once"],
                ["python", "crawler_worker.py", "--healthcheck"],
                ["python", "crawler_worker.py", "--loop", "--interval-minutes", "60", "--limit", "50"],
                ["/bin/false"],
            ),
        }
        for role, commands in allowed.items():
            for command in commands:
                with self.subTest(role=role, command=command):
                    result, artifact_called = self._run_entrypoint_guard(
                        role,
                        role,
                        command,
                        **({
                            "NOTEAI_XHS_ACQUISITION_ADAPTER": "spider_xhs_http",
                            "NOTEAI_XHS_SERVICE": (
                                "tracking"
                                if any("crawler" in part for part in command)
                                else "trends"
                            ),
                        } if role == "xhs-http" else {}),
                    )

                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertFalse(artifact_called)

    def test_runtime_role_allowlists_reject_bypasses_before_artifact_loading(self):
        rejected = {
            "api": (
                [],
                ["python", "-m", "uvicorn", "api:app"],
                ["python", "api.py"],
                ["python", "-m", "crawler_worker"],
                ["python", "-m", "market_timing_worker"],
                ["python", "/app/model/crawler_worker.py"],
                ["python", "/app/model/market_timing_worker.py"],
                ["sh", "-c", "/app/scripts/render_start_api.sh"],
                ["/app/scripts/render_start_api.sh", "extra"],
                ["python", "/app/scripts/render_predeploy.py", "extra"],
                ["/app/scripts/render_run_crawler.sh"],
                ["python", "market_timing_worker.py", "--daemon", "--interval", "api:app"],
            ),
            "admin": (
                [],
                ["/app/scripts/render_start_api.sh"],
                ["/app/scripts/render_run_crawler.sh"],
                ["python", "/app/scripts/render_predeploy.py"],
                ["python", "crawler_worker.py"],
            ),
            "payment": (
                [],
                ["/app/scripts/render_start_api.sh"],
                ["/app/scripts/render_start_admin.sh"],
                ["python", "-m", "uvicorn", "payment_runtime:app"],
                ["/app/scripts/render_start_payment.sh", "extra"],
            ),
            "ai-worker": (
                [],
                ["/app/scripts/render_start_api.sh"],
                ["python", "api.py"],
                ["python", "durable_ai_worker.py"],
                ["python", "durable_ai_worker.py", "--once", "extra"],
                ["sh", "-c", "python durable_ai_worker.py --once"],
            ),
            "xhs-http": (
                [],
                ["/app/scripts/render_start_api.sh"],
                ["/app/scripts/render_start_admin.sh"],
                ["python", "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"],
                ["python", "api.py"],
                ["python", "/app/model/api.py"],
                ["python", "-m", "crawler_worker"],
                ["python", "/app/model/crawler_worker.py"],
                ["sh", "-c", "/app/scripts/render_run_crawler.sh"],
                ["/app/scripts/render_run_crawler.sh", "extra"],
                ["python", "/app/scripts/render_predeploy.py"],
                ["/bin/false", "extra"],
                ["python", "-c", "import api"],
                ["python", "crawler_worker.py", "--loop", "--interval-minutes", "api.py", "--limit", "50"],
                ["python", "crawler_worker.py", "--loop", "--interval-minutes", "60", "--limit", "api.py"],
            ),
        }
        for role, commands in rejected.items():
            for command in commands:
                with self.subTest(role=role, command=command):
                    result, artifact_called = self._run_entrypoint_guard(
                        role,
                        role,
                        command,
                        check_pre_artifact=True,
                        **({
                            "NOTEAI_XHS_ACQUISITION_ADAPTER": "spider_xhs_http",
                            "NOTEAI_XHS_SERVICE": "tracking",
                        } if role == "xhs-http" else {}),
                    )

                    self.assertEqual(result.returncode, 78, result.stderr)
                    self.assertFalse(artifact_called, "artifact loader ran before command rejection")

    def test_api_runtime_guard_rejects_scheduler_before_artifact_loading(self):
        result, artifact_called = self._run_entrypoint_guard(
            "api",
            "api",
            ["/app/scripts/render_start_api.sh"],
            check_pre_artifact=True,
            NOTEAI_API_STARTS_TREND_SCHEDULER="1",
        )

        self.assertEqual(result.returncode, 78, result.stderr)
        self.assertIn("trend scheduler", result.stderr)
        self.assertFalse(artifact_called)

    def test_ai_worker_unsuspend_requires_exact_processor_before_artifact_loading(self):
        result, artifact_called = self._run_entrypoint_guard(
            "ai-worker",
            "ai-worker",
            ["python", "durable_ai_worker.py", "--once"],
            check_pre_artifact=True,
            NOTEAI_DURABLE_AI_SUSPENDED="0",
        )
        self.assertEqual(result.returncode, 78, result.stderr)
        self.assertIn("exact production processor", result.stderr)
        self.assertFalse(artifact_called)

    def test_readiness_entrypoint_semantic_harness_accepts_current_contract(self):
        source = (ROOT / "scripts" / "docker_entrypoint.sh").read_text(encoding="utf-8")

        passed, detail = gate._check_entrypoint_runtime_contract(source)

        self.assertTrue(passed, detail)
        self.assertIn("allowed=22", detail)

    def test_readiness_entrypoint_semantic_harness_rejects_allowlist_backdoor(self):
        source = (ROOT / "scripts" / "docker_entrypoint.sh").read_text(encoding="utf-8")
        reject_gate = 'if [ "$command_allowed" -ne 1 ]; then'
        mutated = source.replace(
            reject_gate,
            f"command_allowed=1\n\n{reject_gate}",
            1,
        )
        self.assertNotEqual(source, mutated)

        passed, detail = gate._check_entrypoint_runtime_contract(mutated)

        self.assertFalse(passed, detail)
        self.assertIn("reject_contract_failed", detail)

    def test_cloud_runtime_gate_fails_with_fixed_code_when_meituan_cli_is_missing(self):
        with mock.patch.dict(os.environ, {
            "NOTEAI_CLOUD_RUNTIME": "1",
            "NOTEAI_FACT_SEARCH": "1",
            "NOTEAI_MEITUAN_TRAVEL_ENABLED": "1",
            "MEITUAN_AI_HUB_TOKEN": "",
            "MEITUAN_OPEN_TOKEN": "",
        }), mock.patch.object(facts, "_meituan_travel_cli_path", return_value="/missing/mttravel"), mock.patch.object(
            facts,
            "_meituan_travel_config_token",
            return_value="",
        ):
            checks = gate.check_optional_runtime_dependencies()

        self.assertFalse(checks[0]["passed"])
        self.assertEqual(checks[0]["detail"], "MEITUAN_TRAVEL_CLI_MISSING")

    def test_cloud_runtime_gate_fails_with_fixed_code_when_meituan_token_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "mttravel"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o700)
            with mock.patch.dict(os.environ, {
                "NOTEAI_CLOUD_RUNTIME": "1",
                "NOTEAI_FACT_SEARCH": "1",
                "NOTEAI_MEITUAN_TRAVEL_ENABLED": "1",
                "MEITUAN_AI_HUB_TOKEN": "",
                "MEITUAN_OPEN_TOKEN": "",
            }), mock.patch.object(facts, "_meituan_travel_cli_path", return_value=str(executable)), mock.patch.object(
                facts,
                "_meituan_travel_config_token",
                return_value="",
            ):
                checks = gate.check_optional_runtime_dependencies()

        self.assertFalse(checks[0]["passed"])
        self.assertEqual(checks[0]["detail"], "MEITUAN_TRAVEL_TOKEN_MISSING")

    def test_secret_scanner_flags_real_values_but_allows_placeholders(self):
        self.assertEqual(gate._line_has_secret_value("ANTHROPIC_API_KEY=test-key"), (False, ""))
        self.assertEqual(gate._line_has_secret_value("ADMIN_PASSWORD=${{ secrets.ADMIN_PASSWORD }}"), (False, ""))
        self.assertEqual(gate._line_has_secret_value("HARDENING_TOKENS = ("), (False, ""))
        self.assertEqual(
            gate._line_has_secret_value(
                'CLIENT_TOKEN_CONTROL = "BUILDKIT_NO_CLIENT_TOKEN"'
            ),
            (False, ""),
        )

        fake_key = "abcd1234" + "ef567890abcd1234ef567890"
        has_secret, name = gate._line_has_secret_value(f"AMAP_WEB_KEY={fake_key}")
        self.assertTrue(has_secret)
        self.assertEqual(name, "AMAP_WEB_KEY")
        self.assertEqual(
            gate._line_has_secret_value(
                f'CLIENT_TOKEN_CONTROL="{fake_key}"'
            ),
            (True, "CLIENT_TOKEN_CONTROL"),
        )
        client_control_name = "BUILDKIT_NO_CLIENT_" + "TOKEN"
        self.assertEqual(
            gate._line_has_secret_value(
                f'{client_control_name}: "unexpected"'
            ),
            (True, "BUILDKIT_NO_CLIENT_TOKEN"),
        )

    def test_human_model_release_manifest_hashes_match_all_declared_files(self):
        declared = gate._load_human_release_hashes(gate.HUMAN_MODEL_RELEASE_MANIFEST)

        self.assertGreaterEqual(len(declared), 8)
        self.assertEqual(gate._declared_sha256_mismatches(declared), [])

    def test_human_model_release_manifest_hash_mismatch_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "model" / "artifacts" / "evidence.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("{}", encoding="utf-8")

            mismatches = gate._declared_sha256_mismatches(
                {"model/artifacts/evidence.json": "0" * 64},
                root=root,
            )

        self.assertEqual(mismatches, ["model/artifacts/evidence.json"])

    def test_artifact_loader_cli_respects_required_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest = tmp_path / "manifest.json"
            manifest.write_text(json.dumps({
                "release": "test",
                "run_id": "missing",
                "artifacts": [{
                    "role": "quality_regressor",
                    "path": str(tmp_path / "missing.lgb"),
                    "sha256": "0" * 64,
                }],
            }), encoding="utf-8")

            old_env = os.environ.get("NOTEAI_MODEL_ARTIFACT_REQUIRED")
            old_argv = list(sys.argv)
            try:
                os.environ["NOTEAI_MODEL_ARTIFACT_REQUIRED"] = "1"
                sys.argv = ["artifact_loader", "--manifest", str(manifest)]
                with self.assertRaises(RuntimeError):
                    artifact_loader.main()
            finally:
                sys.argv = old_argv
                if old_env is None:
                    os.environ.pop("NOTEAI_MODEL_ARTIFACT_REQUIRED", None)
                else:
                    os.environ["NOTEAI_MODEL_ARTIFACT_REQUIRED"] = old_env


if __name__ == "__main__":
    unittest.main()
