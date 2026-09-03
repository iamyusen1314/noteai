from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_v10_failure_evidence as verifier  # noqa: E402


class AdminDependencyCacheV10FailureEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence = verifier.load_strict()

    def test_exact_evidence_and_frozen_git_pass(self) -> None:
        self.assertEqual(verifier.verify(self.evidence), [])

    def test_terminal_outcome_mutations_fail_closed(self) -> None:
        mutations = (
            ("git", "control_commit", "0" * 40),
            ("git", "inert_checkpoint_commit", "0" * 40),
            ("git", "inert_remote_receipt_commit", "0" * 40),
            ("git", "request_sha256", "0" * 64),
            ("github_run", "run_id", 1),
            ("github_run", "job_id", 1),
            ("github_run", "attempt", 2),
            ("github_run", "conclusion", "success"),
            ("github_run", "workflow_run_count_global", 2),
            ("github_run", "workflow_inventory_fully_paginated", False),
            ("github_run", "rerun_count", 1),
            ("step_outcome", "dependency_cache_export", "failure"),
            ("step_outcome", "fresh_consumer_portability", "success"),
            ("step_outcome", "transient_docker_cleanup", "failure"),
            ("step_outcome", "artifact_upload", "success"),
            (
                "failure",
                "fresh_consumer_import_role_interval_projection_completed",
                True,
            ),
            ("failure", "fresh_consumer_import_v9_delegate_reached", True),
            ("failure", "cacheless_replay_reached", True),
            ("failure", "failed_role_digest_retained", True),
            ("failure", "observer_details_retained", True),
            ("failure", "producer_terminal_pip_hypothesis", "DISPROVED"),
            ("failure", "underlying_root_cause", "invented"),
            ("failure", "primary_root_cause_determined", True),
            ("cleanup", "producer_builder_absent", "fail"),
            ("cleanup", "images_parity", "fail"),
            ("cleanup", "cleanup_effective", False),
            ("provider_artifact", "api_total_count", 1),
            ("native_job_log", "byte_count", 1),
            ("control_head_ci", "push_ci_conclusion", "failure"),
            ("control_head_ci", "pull_request_ci_conclusion", "success"),
            ("control_head_ci", "lineage_aware_history_fix_required", False),
            ("execution_scope", "admin_acr_push_count_in_authorized_chain", 1),
            ("execution_scope", "production_database_write_count", 1),
            ("authorization_outcome", "github_v10_one_shot_run_consumed", False),
            ("authorization_outcome", "v10_attempt_may_not_be_rerun", False),
            ("authorization_outcome", "append_only_successor_required", False),
            ("readiness", "credit_added", True),
        )
        for section, key, value in mutations:
            with self.subTest(section=section, key=key):
                broken = copy.deepcopy(self.evidence)
                broken[section][key] = value
                self.assertIn(
                    "V10 failure evidence semantics changed",
                    verifier.verify(broken, verify_git_state=False),
                )

    def test_diagnostic_mutations_fail_closed(self) -> None:
        cases = (
            ("producer_v9_diagnostic", "progress_sha256", "0" * 64),
            ("producer_v10_diagnostic", "verdict", "fail"),
            ("producer_v10_diagnostic", "role_binding_completed", False),
            ("import_v10_diagnostic", "failure_code", "NONE"),
            ("import_v10_diagnostic", "observer_binding_completed", False),
            ("import_v10_diagnostic", "v10_root_cause_status", "NO_FAILURE"),
        )
        for name, key, value in cases:
            with self.subTest(name=name, key=key):
                broken = copy.deepcopy(self.evidence)
                broken["failure"][name][key] = value
                broken["failure"][name]["diagnostic_sha256"] = (
                    verifier.diagnostic_payload_sha256(
                        broken["failure"][name]
                    )
                )
                self.assertIn(
                    "V10 failure evidence semantics changed",
                    verifier.verify(broken, verify_git_state=False),
                )

    def test_derived_hashes_and_extra_fields_fail_closed(self) -> None:
        for name in (
            "producer_v9_diagnostic",
            "producer_v10_diagnostic",
            "import_v10_diagnostic",
        ):
            with self.subTest(name=name):
                broken = copy.deepcopy(self.evidence)
                broken["failure"][name]["projection_test_mutation"] = True
                self.assertIn(
                    f"V10 {name.replace('_', ' ')} hash does not derive",
                    verifier.verify(broken, verify_git_state=False),
                )

        broken = copy.deepcopy(self.evidence)
        broken["cleanup"]["compact_log_payload_sha256"] = "0" * 64
        self.assertIn(
            "V10 cleanup compact payload hash does not derive",
            verifier.verify(broken, verify_git_state=False),
        )

        broken = copy.deepcopy(self.evidence)
        broken["unexpected"] = "must not be accepted"
        errors = verifier.verify(broken, verify_git_state=False)
        self.assertIn("V10 failure evidence root key set changed", errors)
        self.assertIn("V10 failure evidence semantics changed", errors)

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

    def test_parent_history_and_historical_tree_drift_fail_closed(self) -> None:
        with mock.patch.object(
            verifier,
            "_commit_parents",
            side_effect=lambda commit: (
                ["0" * 40]
                if commit == verifier.CONTROL_COMMIT
                else {
                    verifier.INERT_CHECKPOINT_COMMIT: [
                        verifier.V9_TERMINAL_RECEIPT_COMMIT
                    ],
                    verifier.INERT_RECEIPT_COMMIT: [
                        verifier.INERT_CHECKPOINT_COMMIT
                    ],
                }[commit]
            ),
        ), mock.patch.object(
            verifier,
            "_true_additions",
            return_value=[verifier.CONTROL_COMMIT],
        ):
            self.assertIn(
                "V10 controller parent binding changed",
                verifier.verify_frozen_git(),
            )

        with mock.patch.object(
            verifier,
            "_true_additions",
            return_value=[verifier.CONTROL_COMMIT, "0" * 40],
        ):
            self.assertIn(
                "V10 request true-addition history changed",
                verifier.verify_frozen_git(),
            )

        original_lineage = verifier._lineage_path_changes

        def tamper_legacy_lineage(anchor: str, paths: tuple[Path, ...]):
            if anchor == verifier.V9_TERMINAL_RECEIPT_COMMIT:
                return ["0" * 40]
            return original_lineage(anchor, paths)

        with mock.patch.object(
            verifier,
            "_lineage_path_changes",
            side_effect=tamper_legacy_lineage,
        ):
            self.assertIn(
                "V2-V9 frozen authority changed after terminal receipt",
                verifier.verify_frozen_git(),
            )

        original_bytes = verifier._git_bytes
        path = next(iter(verifier.ACTIVATION_HISTORICAL_PATHS))
        target = ("show", f"{verifier.CONTROL_COMMIT}:{path.as_posix()}")

        def tamper_tree(*args: str) -> bytes:
            if args == target:
                return b"tampered\n"
            return original_bytes(*args)

        with mock.patch.object(verifier, "_git_bytes", side_effect=tamper_tree):
            self.assertTrue(
                any(
                    "activation authority hash changed" in error
                    for error in verifier.verify_frozen_git()
                )
            )

    def test_synthetic_merge_candidate_is_not_a_true_addition(self) -> None:
        control = verifier.CONTROL_COMMIT
        parent = verifier.DIRECT_PARENT_COMMIT
        merge = "6" * 40
        base = "5" * 40
        request_entry = "100644 blob 1\trequest"

        def git_text(*args: str) -> str:
            if args and args[0] == "log":
                return f"{merge}\n{control}"
            if args == ("rev-list", "--parents", "-n", "1", merge):
                return f"{merge} {base} {control}"
            if args == ("rev-list", "--parents", "-n", "1", control):
                return f"{control} {parent}"
            if args[:2] == ("ls-tree", merge):
                return request_entry
            if args[:2] == ("ls-tree", control):
                return request_entry
            if args[:2] in (("ls-tree", base), ("ls-tree", parent)):
                return ""
            raise AssertionError(args)

        with mock.patch.object(verifier, "_git_text", side_effect=git_text):
            self.assertEqual(verifier._true_additions(verifier.REQUEST_PATH), [control])

    def test_mode_worktree_and_evidence_file_drift_fail_closed(self) -> None:
        original_mode = verifier._regular_blob_mode

        def tamper_mode(commit: str, path: Path) -> bool:
            if commit == "HEAD" and path == verifier.REQUEST_PATH:
                return False
            return original_mode(commit, path)

        with mock.patch.object(
            verifier,
            "_regular_blob_mode",
            side_effect=tamper_mode,
        ):
            self.assertIn(
                "V10 request retained mode changed",
                verifier.verify_frozen_git(),
            )

        frozen_path = next(iter(verifier.FROZEN_INERT_PATHS))
        local_target = verifier.ROOT / frozen_path
        original_read_bytes = Path.read_bytes

        def tamper_worktree(target: Path) -> bytes:
            if target == local_target:
                return b"tampered worktree\n"
            return original_read_bytes(target)

        with mock.patch.object(Path, "read_bytes", tamper_worktree):
            self.assertTrue(
                any(
                    "inert worktree file hash changed" in error
                    for error in verifier.verify_frozen_git()
                )
            )

        with mock.patch.object(verifier, "EVIDENCE_FILE_SHA256", "0" * 64):
            self.assertIn(
                "V10 failure evidence file bytes changed",
                verifier.verify(self.evidence, verify_git_state=False),
            )

    def test_strict_json_rejects_duplicates_and_nonfinite_numbers(self) -> None:
        for payload in (
            b'{"x":1,"x":2}\n',
            b'{"x":NaN}\n',
            b'{"x":Infinity}\n',
        ):
            with self.subTest(payload=payload):
                with tempfile.TemporaryDirectory() as temporary:
                    target = Path(temporary) / "evidence.json"
                    target.write_bytes(payload)
                    with self.assertRaises(ValueError):
                        verifier.load_strict(target)


if __name__ == "__main__":
    unittest.main()
