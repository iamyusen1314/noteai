from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_v8_failure_evidence as verifier  # noqa: E402


class AdminDependencyCacheV8FailureEvidenceTests(unittest.TestCase):
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
            ("github_run", "workflow_run_count_for_branch", 2),
            ("github_run", "workflow_inventory_fully_paginated", False),
            ("github_run", "rerun_count", 1),
            ("runner", "client_token_disabled", False),
            ("step_outcome", "dependency_cache_export", "failure"),
            ("step_outcome", "fresh_consumer_portability", "success"),
            ("step_outcome", "transient_docker_cleanup", "failure"),
            ("step_outcome", "final_bundle_validation", "success"),
            ("step_outcome", "artifact_upload", "success"),
            ("failure", "producer_build_command_completed", False),
            ("failure", "producer_strict_verification_completed", False),
            ("failure", "portable_core_bundle_generation_completed", False),
            ("failure", "fresh_consumer_core_validation_completed", False),
            ("failure", "fresh_consumer_import_build_command_completed", False),
            (
                "failure",
                "fresh_consumer_import_strict_verification_completed",
                True,
            ),
            ("failure", "cacheless_replay_reached", True),
            ("failure", "portability_proof_generation_reached", True),
            ("failure", "final_bundle_validation_reached", True),
            ("failure", "raw_build_metadata_retained", True),
            ("failure", "raw_progress_retained", True),
            ("failure", "actual_input_transition_reconstructed", True),
            ("failure", "exact_conflicting_vertex_digest_retained", True),
            ("failure", "previous_input_vector_retained", True),
            ("failure", "current_input_vector_retained", True),
            ("failure", "complete_import_role_binding_results_retained", True),
            (
                "failure",
                "complete_import_package_network_output_result_retained",
                True,
            ),
            ("failure", "zero_import_package_network_output_claimed", True),
            ("failure", "import_network_vertices_cache_result_claimed", True),
            ("failure", "primary_root_cause_determined", True),
            ("failure", "root_cause_class", "invented"),
            ("cleanup", "producer_builder_absent", "fail"),
            ("cleanup", "consumer_builder_absent", "fail"),
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
            ("provider_artifact", "cross_provider_transfer_count", 1),
            ("control_head_ci", "exact_head_run_count", 2),
            ("control_head_ci", "push_ci_conclusion", "failure"),
            (
                "execution_scope",
                "conditional_cloud_builder_start_count_in_authorized_chain",
                1,
            ),
            ("execution_scope", "admin_acr_push_count_in_authorized_chain", 1),
            ("authorization_outcome", "github_v8_one_shot_run_consumed", False),
            ("authorization_outcome", "v8_attempt_may_not_be_rerun", False),
            ("authorization_outcome", "append_only_successor_required", False),
            ("readiness", "credit_added", True),
        )
        for section, key, value in mutations:
            with self.subTest(section=section, key=key):
                broken = copy.deepcopy(self.evidence)
                broken[section][key] = value
                self.assertIn(
                    "V8 failure evidence semantics changed",
                    verifier.verify(broken, verify_git_state=False),
                )

    def test_complete_and_prefix_diagnostic_semantics_are_locked(self) -> None:
        mutations = (
            ("producer_diagnostic_fields_are_complete_runtime_results", False),
            ("import_diagnostic_fields_are_complete_runtime_results", True),
            ("producer_diagnostic_occurrence_count", 1),
            ("producer_diagnostic_occurrences_identical", False),
        )
        for key, value in mutations:
            with self.subTest(key=key):
                broken = copy.deepcopy(self.evidence)
                broken["failure"][key] = value
                self.assertIn(
                    "V8 failure evidence semantics changed",
                    verifier.verify(broken, verify_git_state=False),
                )

        broken = copy.deepcopy(self.evidence)
        broken["failure"]["import_diagnostic_field_semantics"][
            "unreached_default_fields"
        ].remove("roles")
        self.assertIn(
            "V8 failure evidence semantics changed",
            verifier.verify(broken, verify_git_state=False),
        )

    def test_recomputed_diagnostic_mutation_still_fails_semantics(self) -> None:
        for name in ("producer_diagnostic", "import_diagnostic"):
            with self.subTest(name=name):
                broken = copy.deepcopy(self.evidence)
                broken["failure"][name]["progress_bytes"] += 1
                broken["failure"][name]["diagnostic_sha256"] = (
                    verifier.diagnostic_payload_sha256(
                        broken["failure"][name]
                    )
                )
                self.assertIn(
                    "V8 failure evidence semantics changed",
                    verifier.verify(broken, verify_git_state=False),
                )

    def test_derived_hashes_and_extra_field_fail_closed(self) -> None:
        for name in ("producer_diagnostic", "import_diagnostic"):
            with self.subTest(name=name):
                broken = copy.deepcopy(self.evidence)
                broken["failure"][name]["progress_bytes"] += 1
                self.assertIn(
                    f"V8 {name.replace('_', ' ')} hash does not derive",
                    verifier.verify(broken, verify_git_state=False),
                )

        broken = copy.deepcopy(self.evidence)
        broken["cleanup"]["compact_log_payload_sha256"] = "0" * 64
        self.assertIn(
            "V8 cleanup compact payload hash does not derive",
            verifier.verify(broken, verify_git_state=False),
        )

        broken = copy.deepcopy(self.evidence)
        broken["failure"]["unexpected"] = "must not be accepted"
        self.assertIn(
            "V8 failure evidence semantics changed",
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

        with mock.patch.object(verifier, "_git_text", side_effect=tamper_parent):
            self.assertIn(
                "V8 controller parent binding changed",
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

        with mock.patch.object(verifier, "_git_text", side_effect=tamper_history):
            self.assertIn(
                "V8 request addition history changed",
                verifier.verify_frozen_git(),
            )

        original_bytes = verifier._git_bytes
        workflow = next(
            path
            for path in verifier.FROZEN_PATHS
            if path.name == "admin-dependency-cache-export-v8.yml"
        )
        target = (
            "show",
            f"{verifier.DIRECT_PARENT_COMMIT}:{workflow.as_posix()}",
        )

        def tamper_tree(*args: str) -> bytes:
            if args == target:
                return b"tampered historical bytes\n"
            return original_bytes(*args)

        with mock.patch.object(verifier, "_git_bytes", side_effect=tamper_tree):
            self.assertTrue(
                any(
                    "parent tree file hash changed" in error
                    for error in verifier.verify_frozen_git()
                )
            )

    def test_receipt_delta_head_request_and_head_tree_drift_fail_closed(
        self,
    ) -> None:
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
                return f"{verifier.DIRECT_PARENT_COMMIT} {'0' * 40}"
            return original_text(*args)

        with mock.patch.object(
            verifier,
            "_git_text",
            side_effect=tamper_receipt_parent,
        ):
            self.assertIn(
                "V8 inert remote receipt parent binding changed",
                verifier.verify_frozen_git(),
            )

        delta_target = (
            "diff-tree",
            "--no-commit-id",
            "--no-renames",
            "--name-status",
            "-r",
            verifier.DIRECT_PARENT_COMMIT,
            verifier.CONTROL_COMMIT,
        )

        def tamper_delta(*args: str) -> str:
            if args == delta_target:
                return "M\tREADME.md"
            return original_text(*args)

        with mock.patch.object(verifier, "_git_text", side_effect=tamper_delta):
            self.assertIn(
                "V8 controller is no longer request-only",
                verifier.verify_frozen_git(),
            )

        request_mode_target = (
            "ls-tree",
            "HEAD",
            "--",
            verifier.REQUEST_PATH.as_posix(),
        )

        def tamper_request_mode(*args: str) -> str:
            if args == request_mode_target:
                return f"100755 blob {'0' * 40}\t{verifier.REQUEST_PATH.as_posix()}"
            return original_text(*args)

        with mock.patch.object(
            verifier,
            "_git_text",
            side_effect=tamper_request_mode,
        ):
            self.assertIn(
                "V8 request retained mode changed",
                verifier.verify_frozen_git(),
            )

        original_bytes = verifier._git_bytes
        head_request_target = (
            "show",
            f"HEAD:{verifier.REQUEST_PATH.as_posix()}",
        )

        def tamper_head_request(*args: str) -> bytes:
            if args == head_request_target:
                return b"tampered retained request\n"
            return original_bytes(*args)

        with mock.patch.object(
            verifier,
            "_git_bytes",
            side_effect=tamper_head_request,
        ):
            self.assertIn(
                "V8 request is not retained byte-exact at HEAD",
                verifier.verify_frozen_git(),
            )

        workflow = next(
            path
            for path in verifier.FROZEN_PATHS
            if path.name == "admin-dependency-cache-export-v8.yml"
        )
        head_tree_target = ("show", f"HEAD:{workflow.as_posix()}")

        def tamper_head_tree(*args: str) -> bytes:
            if args == head_tree_target:
                return b"tampered HEAD workflow\n"
            return original_bytes(*args)

        with mock.patch.object(
            verifier,
            "_git_bytes",
            side_effect=tamper_head_tree,
        ):
            self.assertTrue(
                any(
                    "HEAD frozen file hash changed" in error
                    for error in verifier.verify_frozen_git()
                )
            )

    def test_worktree_and_template_derivation_drift_fail_closed(self) -> None:
        workflow = next(
            path
            for path in verifier.FROZEN_PATHS
            if path.name == "admin-dependency-cache-export-v8.yml"
        )
        original_read_bytes = Path.read_bytes

        def tamper_worktree(path: Path) -> bytes:
            if path == verifier.ROOT / workflow:
                return b"tampered worktree workflow\n"
            return original_read_bytes(path)

        with mock.patch.object(Path, "read_bytes", new=tamper_worktree):
            self.assertIn(
                f"frozen V8 file hash changed: {workflow.as_posix()}",
                verifier.verify_frozen_git(),
            )

        original_bytes = verifier._git_bytes
        template_target = (
            "show",
            f"{verifier.DIRECT_PARENT_COMMIT}:"
            f"{verifier.TEMPLATE_PATH.as_posix()}",
        )
        template_reads = 0

        def tamper_template_placeholder(*args: str) -> bytes:
            nonlocal template_reads
            value = original_bytes(*args)
            if args == template_target:
                template_reads += 1
                if template_reads == 2:
                    return value.replace(
                        b"__DIRECT_PARENT_COMMIT__",
                        b"__MISSING_PARENT_MARKER__",
                    )
            return value

        with mock.patch.object(
            verifier,
            "_git_bytes",
            side_effect=tamper_template_placeholder,
        ):
            self.assertIn(
                "V8 frozen template placeholder count changed",
                verifier.verify_frozen_git(),
            )

        template_reads = 0

        def tamper_template_derivation(*args: str) -> bytes:
            nonlocal template_reads
            value = original_bytes(*args)
            if args == template_target:
                template_reads += 1
                if template_reads == 2:
                    return value + b"\n"
            return value

        with mock.patch.object(
            verifier,
            "_git_bytes",
            side_effect=tamper_template_derivation,
        ):
            self.assertIn(
                "V8 control request differs from its frozen template",
                verifier.verify_frozen_git(),
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
                "V8 failure evidence file bytes changed",
                verifier.verify(self.evidence, verify_git_state=False),
            )


if __name__ == "__main__":
    unittest.main()
