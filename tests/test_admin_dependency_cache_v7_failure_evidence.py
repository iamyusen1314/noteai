from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_v7_failure_evidence as verifier  # noqa: E402


class AdminDependencyCacheV7FailureEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence = verifier.load_strict()

    def test_exact_evidence_and_frozen_git_pass(self) -> None:
        self.assertEqual(verifier.verify(self.evidence), [])

    def test_terminal_outcome_mutations_fail_closed(self) -> None:
        mutations = (
            ("git", "control_commit", "0" * 40),
            ("git", "direct_parent_commit", "0" * 40),
            ("git", "request_sha256", "0" * 64),
            ("github_run", "run_id", 1),
            ("github_run", "job_id", 1),
            ("github_run", "attempt", 2),
            ("github_run", "head_sha", "0" * 40),
            ("github_run", "conclusion", "success"),
            ("github_run", "workflow_run_count_global", 2),
            ("github_run", "workflow_inventory_fully_paginated", False),
            ("github_run", "rerun_count", 1),
            ("runner", "client_token_disabled", False),
            ("step_outcome", "dependency_cache_export", "success"),
            ("step_outcome", "fresh_consumer_portability", "success"),
            ("step_outcome", "transient_docker_cleanup", "failure"),
            ("failure", "build_command_completed", False),
            ("failure", "raw_build_metadata_retained", True),
            ("failure", "raw_progress_retained", True),
            ("failure", "failed_provenance_step_id", "step8"),
            ("failure", "structural_binding_validation_completed", True),
            ("failure", "actual_source_location_payload_retained", True),
            ("failure", "actual_source_location_shape_reconstructed", True),
            ("failure", "actual_role_binding_results_retained", True),
            (
                "failure",
                "actual_package_network_output_result_retained",
                True,
            ),
            ("failure", "zero_package_network_output_claimed", True),
            ("failure", "network_vertices_cache_result_claimed", True),
            ("failure", "primary_root_cause_determined", True),
            ("failure", "root_cause_class", "invented"),
            ("failure", "portable_archive_generation_reached", True),
            ("cleanup", "producer_builder_absent", "fail"),
            ("cleanup", "images_parity", "fail"),
            ("cleanup", "cleanup_effective", False),
            ("cleanup", "overall_pass", False),
            ("cleanup", "receipt_file_bytes_retained", True),
            (
                "cleanup",
                "enumerated_cleanup_scope_and_docker_parity_proven",
                False,
            ),
            ("cleanup", "all_runner_temp_task_paths_absent_proven", True),
            ("cleanup", "hosted_vm_physical_destruction_proven", True),
            ("provider_artifact", "api_total_count", 1),
            ("provider_artifact", "authenticated_download_count", 1),
            ("control_head_ci", "exact_head_run_count", 2),
            ("control_head_ci", "push_ci_conclusion", "failure"),
            (
                "execution_scope",
                "conditional_cloud_builder_start_count_in_authorized_chain",
                1,
            ),
            (
                "execution_scope",
                "external_network_read_status",
                "ZERO",
            ),
            ("execution_scope", "admin_acr_push_count_in_authorized_chain", 1),
            ("authorization_outcome", "github_v7_one_shot_run_consumed", False),
            ("authorization_outcome", "v7_attempt_may_not_be_rerun", False),
            ("readiness", "credit_added", True),
        )
        for section, key, value in mutations:
            with self.subTest(section=section, key=key):
                broken = copy.deepcopy(self.evidence)
                broken[section][key] = value
                self.assertIn(
                    "V7 failure evidence semantics changed",
                    verifier.verify(broken, verify_git_state=False),
                )

    def test_complete_progress_and_unreached_defaults_are_both_locked(self) -> None:
        broken = copy.deepcopy(self.evidence)
        broken["failure"]["diagnostic"]["vertex_update_count"] += 1
        broken["failure"]["diagnostic"]["diagnostic_sha256"] = (
            verifier.diagnostic_payload_sha256(
                broken["failure"]["diagnostic"]
            )
        )
        self.assertIn(
            "V7 failure evidence semantics changed",
            verifier.verify(broken, verify_git_state=False),
        )

        for key, value in (
            ("diagnostic_fields_are_complete_runtime_results", True),
            ("exact_rejected_location_predicate_status", "OBSERVED"),
            ("actual_role_binding_results_retained", True),
            ("actual_package_network_output_result_retained", True),
            ("zero_package_network_output_claimed", True),
            ("all_role_intervals_complete_in_window_claimed", True),
        ):
            with self.subTest(key=key):
                broken = copy.deepcopy(self.evidence)
                broken["failure"][key] = value
                self.assertTrue(
                    verifier.verify(broken, verify_git_state=False)
                )

    def test_diagnostic_cleanup_and_extra_field_mutations_fail_closed(self) -> None:
        broken = copy.deepcopy(self.evidence)
        broken["failure"]["diagnostic"]["progress_bytes"] += 1
        self.assertIn(
            "V7 diagnostic hash does not derive",
            verifier.verify(broken, verify_git_state=False),
        )

        broken = copy.deepcopy(self.evidence)
        broken["cleanup"]["compact_log_payload_sha256"] = "0" * 64
        self.assertIn(
            "V7 cleanup compact payload hash does not derive",
            verifier.verify(broken, verify_git_state=False),
        )

        broken = copy.deepcopy(self.evidence)
        broken["failure"]["unexpected"] = "must not be accepted"
        self.assertIn(
            "V7 failure evidence semantics changed",
            verifier.verify(broken, verify_git_state=False),
        )

    def test_file_and_semantic_hashes_are_distinct_and_exact(self) -> None:
        self.assertEqual(
            verifier.sha256_bytes(verifier.EVIDENCE_PATH.read_bytes()),
            verifier.EVIDENCE_FILE_SHA256,
        )
        self.assertEqual(
            verifier.semantic_sha256(self.evidence),
            verifier.EXPECTED_SEMANTIC_SHA256,
        )
        self.assertNotEqual(
            verifier.EVIDENCE_FILE_SHA256,
            verifier.EXPECTED_SEMANTIC_SHA256,
        )

    def test_parent_control_history_and_tree_drift_fail_closed(self) -> None:
        original_text = verifier._git_text
        parent_target = (
            "rev-list",
            "--parents",
            "-n",
            "1",
            verifier.CONTROL_COMMIT,
        )

        def tamper_parent(*args: str) -> str:
            if args == parent_target:
                return f"{verifier.CONTROL_COMMIT} {'0' * 40}"
            return original_text(*args)

        with mock.patch.object(
            verifier,
            "_git_text",
            side_effect=tamper_parent,
        ):
            self.assertIn(
                "V7 controller parent binding changed",
                verifier.verify_frozen_git(),
            )

        history_target = (
            "log",
            "--all",
            "--diff-filter=A",
            "--format=%H",
            "--",
            verifier.REQUEST_PATH.as_posix(),
        )

        def tamper_history(*args: str) -> str:
            if args == history_target:
                return f"{verifier.CONTROL_COMMIT}\n{'0' * 40}"
            return original_text(*args)

        with mock.patch.object(
            verifier,
            "_git_text",
            side_effect=tamper_history,
        ):
            self.assertIn(
                "V7 request addition history changed",
                verifier.verify_frozen_git(),
            )

        original_bytes = verifier._git_bytes
        workflow = next(
            path
            for path in verifier.FROZEN_PATHS
            if path.name == "admin-dependency-cache-export-v7.yml"
        )
        target = (
            "show",
            f"{verifier.DIRECT_PARENT_COMMIT}:{workflow.as_posix()}",
        )

        def tamper_tree(*args: str) -> bytes:
            if args == target:
                return b"tampered historical bytes\n"
            return original_bytes(*args)

        with mock.patch.object(
            verifier,
            "_git_bytes",
            side_effect=tamper_tree,
        ):
            self.assertTrue(
                any(
                    "parent tree file hash changed" in error
                    for error in verifier.verify_frozen_git()
                )
            )

    def test_strict_json_rejects_duplicates_and_nonfinite_numbers(self) -> None:
        for raw in (
            '{"schema_version":1,"schema_version":2}',
            '{"value":NaN}',
            '{"value":Infinity}',
        ):
            with self.subTest(raw=raw):
                with tempfile.TemporaryDirectory() as temporary:
                    path = Path(temporary) / "evidence.json"
                    path.write_text(raw, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        verifier.load_strict(path)

    def test_current_evidence_file_tamper_fails_closed(self) -> None:
        with mock.patch.object(
            Path,
            "read_bytes",
            return_value=b"tampered evidence\n",
        ):
            self.assertIn(
                "V7 failure evidence file bytes changed",
                verifier.verify(self.evidence, verify_git_state=False),
            )


if __name__ == "__main__":
    unittest.main()
