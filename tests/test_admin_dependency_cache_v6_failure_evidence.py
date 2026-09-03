from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_v6_failure_evidence as verifier  # noqa: E402


class AdminDependencyCacheV6FailureEvidenceTests(unittest.TestCase):
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
            ("runner", "buildkit_source_commit", "0" * 40),
            ("runner", "client_token_disabled", False),
            ("step_outcome", "dependency_cache_export", "success"),
            ("step_outcome", "transient_docker_cleanup", "failure"),
            ("failure", "build_command_completed", False),
            ("failure", "raw_progress_retained", True),
            ("failure", "same_digest_repeated_update_observed", False),
            ("failure", "exact_repeated_digest", "sha256:" + "0" * 64),
            ("failure", "exact_conflicting_field", "started"),
            ("failure", "actual_total_vertex_digest_count", 0),
            ("failure", "actual_role_binding_results_retained", True),
            ("failure", "actual_name_drift_claimed", True),
            ("failure", "zero_network_read_claimed", True),
            ("failure", "primary_root_cause_determined", False),
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
            ("provider_artifact", "api_total_count", 1),
            ("provider_artifact", "authenticated_download_count", 1),
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
            ("authorization_outcome", "github_v6_one_shot_run_consumed", False),
            ("authorization_outcome", "v6_attempt_may_not_be_rerun", False),
            ("readiness", "credit_added", True),
        )
        for section, key, value in mutations:
            with self.subTest(section=section, key=key):
                broken = copy.deepcopy(self.evidence)
                broken[section][key] = value
                self.assertIn(
                    "V6 failure evidence semantics changed",
                    verifier.verify(broken, verify_git_state=False),
                )

    def test_prefix_diagnostic_is_not_promoted_to_full_runtime_truth(self) -> None:
        for key, value in (
            ("diagnostic_fields_are_complete_runtime_results", True),
            ("exact_conflicting_field_status", "OBSERVED"),
            ("actual_total_vertex_digest_count_status", "OBSERVED"),
            ("actual_network_output_result_retained", True),
            (
                "role_marker_or_provenance_duplicate_classification_status",
                "OBSERVED_DUPLICATE",
            ),
        ):
            with self.subTest(key=key):
                broken = copy.deepcopy(self.evidence)
                broken["failure"][key] = value
                self.assertTrue(
                    verifier.verify(broken, verify_git_state=False)
                )

    def test_source_contract_and_unknown_field_are_both_locked(self) -> None:
        broken = copy.deepcopy(self.evidence)
        broken["failure"]["source_proven_contract"][
            "same_digest_multiple_lifecycle_intervals_are_valid"
        ] = False
        self.assertTrue(verifier.verify(broken, verify_git_state=False))

        broken = copy.deepcopy(self.evidence)
        broken["failure"]["source_proven_contract"][
            "v6_observed_exact_conflict_field_determined"
        ] = True
        self.assertTrue(verifier.verify(broken, verify_git_state=False))

        broken = copy.deepcopy(self.evidence)
        broken["failure"]["source_proven_contract"]["source_coordinates"][0][
            "git_blob_sha1"
        ] = "0" * 40
        self.assertTrue(verifier.verify(broken, verify_git_state=False))

    def test_diagnostic_cleanup_and_extra_field_mutations_fail_closed(self) -> None:
        broken = copy.deepcopy(self.evidence)
        broken["failure"]["diagnostic"]["progress_bytes"] += 1
        self.assertIn(
            "V6 diagnostic hash does not derive",
            verifier.verify(broken, verify_git_state=False),
        )

        broken = copy.deepcopy(self.evidence)
        broken["cleanup"]["compact_log_payload_sha256"] = "0" * 64
        self.assertIn(
            "V6 cleanup compact payload hash does not derive",
            verifier.verify(broken, verify_git_state=False),
        )

        broken = copy.deepcopy(self.evidence)
        broken["cleanup"]["producer_builder_absent"] = "fail"
        self.assertIn(
            "V6 cleanup compact payload hash does not derive",
            verifier.verify(broken, verify_git_state=False),
        )

        broken = copy.deepcopy(self.evidence)
        broken["failure"]["unexpected"] = "must not be accepted"
        self.assertIn(
            "V6 failure evidence semantics changed",
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

    def test_parent_control_and_current_tree_drift_fail_closed(self) -> None:
        original = verifier._git_bytes
        workflow = next(
            path
            for path in verifier.FROZEN_PATHS
            if path.name == "admin-dependency-cache-export-v6.yml"
        )
        for commit in (
            verifier.DIRECT_PARENT_COMMIT,
            verifier.CONTROL_COMMIT,
        ):
            with self.subTest(commit=commit):
                target = ("show", f"{commit}:{workflow.as_posix()}")

                def tamper(*args: str) -> bytes:
                    if args == target:
                        return b"tampered historical bytes\n"
                    return original(*args)

                with mock.patch.object(
                    verifier,
                    "_git_bytes",
                    side_effect=tamper,
                ):
                    self.assertTrue(
                        any(
                            "tree file hash changed" in error
                            for error in verifier.verify_frozen_git()
                        )
                    )

        with mock.patch.object(
            Path,
            "read_bytes",
            return_value=b"tampered evidence\n",
        ):
            self.assertIn(
                "V6 failure evidence file bytes changed",
                verifier.verify(self.evidence, verify_git_state=False),
            )

        original_text = verifier._git_text
        receipt_parent_target = (
            "rev-list",
            "--parents",
            "-n",
            "1",
            verifier.DIRECT_PARENT_COMMIT,
        )

        def tamper_receipt_parent(*args: str) -> str:
            if args == receipt_parent_target:
                return (
                    f"{verifier.DIRECT_PARENT_COMMIT} "
                    f"{'0' * 40}"
                )
            return original_text(*args)

        with mock.patch.object(
            verifier,
            "_git_text",
            side_effect=tamper_receipt_parent,
        ):
            self.assertIn(
                "V6 inert remote receipt parent binding changed",
                verifier.verify_frozen_git(),
            )

        head_mode_target = (
            "ls-tree",
            "HEAD",
            "--",
            workflow.as_posix(),
        )

        def tamper_head_mode(*args: str) -> str:
            if args == head_mode_target:
                return (
                    "100755 blob "
                    "0000000000000000000000000000000000000000\t"
                    f"{workflow.as_posix()}"
                )
            return original_text(*args)

        with mock.patch.object(
            verifier,
            "_git_text",
            side_effect=tamper_head_mode,
        ):
            self.assertTrue(
                any(
                    "frozen V6 file mode changed" in error
                    for error in verifier.verify_frozen_git()
                )
            )

    def test_duplicate_and_non_finite_json_are_rejected(self) -> None:
        raw = verifier.EVIDENCE_PATH.read_text(encoding="utf-8")
        duplicate = raw.replace(
            '  "task":',
            '  "schema_version": "duplicate",\n  "task":',
            1,
        )
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            json.loads(
                duplicate,
                object_pairs_hook=verifier.reject_duplicate_pairs,
                parse_constant=verifier.reject_constant,
                parse_float=verifier.parse_float,
            )
        with self.assertRaisesRegex(ValueError, "non-finite JSON"):
            verifier.parse_float("1e999")


if __name__ == "__main__":
    unittest.main()
