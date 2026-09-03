from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_v9_failure_evidence as verifier  # noqa: E402


class AdminDependencyCacheV9FailureEvidenceTests(unittest.TestCase):
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
            ("github_run", "conclusion", "success"),
            ("github_run", "workflow_run_count_global", 2),
            ("github_run", "workflow_inventory_fully_paginated", False),
            ("github_run", "rerun_count", 1),
            ("step_outcome", "dependency_cache_export", "failure"),
            ("step_outcome", "fresh_consumer_portability", "success"),
            ("step_outcome", "transient_docker_cleanup", "failure"),
            ("step_outcome", "artifact_upload", "success"),
            ("failure", "fresh_consumer_import_rawjson_parsing_completed", False),
            ("failure", "fresh_consumer_import_strict_verification_completed", True),
            ("failure", "cacheless_replay_reached", True),
            ("failure", "input_mixed_presence_contract_exercised", False),
            ("failure", "exact_failed_role_retained", False),
            ("failure", "exact_vertex_digest_retained", True),
            ("failure", "per_role_interval_sequence_retained", True),
            ("failure", "selected_interval_identity_retained", True),
            ("failure", "primary_root_cause_determined", True),
            ("failure", "root_cause_class", "invented"),
            ("cleanup", "producer_builder_absent", "fail"),
            ("cleanup", "images_parity", "fail"),
            ("cleanup", "cleanup_effective", False),
            ("provider_artifact", "api_total_count", 1),
            ("control_head_ci", "push_ci_conclusion", "success"),
            ("control_head_ci", "push_ci_failure_count", 0),
            ("control_head_ci", "exact_head_run_count", 2),
            ("control_head_ci", "terminal_checkpoint_ci_required_to_pass", False),
            ("execution_scope", "admin_acr_push_count_in_authorized_chain", 1),
            ("execution_scope", "production_database_write_count", 1),
            ("authorization_outcome", "github_v9_one_shot_run_consumed", False),
            ("authorization_outcome", "v9_attempt_may_not_be_rerun", False),
            ("authorization_outcome", "append_only_successor_required", False),
            ("readiness", "credit_added", True),
        )
        for section, key, value in mutations:
            with self.subTest(section=section, key=key):
                broken = copy.deepcopy(self.evidence)
                broken[section][key] = value
                self.assertIn(
                    "V9 failure evidence semantics changed",
                    verifier.verify(broken, verify_git_state=False),
                )

    def test_diagnostic_role_and_counter_mutations_fail_closed(self) -> None:
        mutations = (
            ("failure_code", "NONE"),
            ("input_mixed_presence_vertex_digest_count", 0),
            ("progress_sha256", "0" * 64),
            ("package_network_output_observed", True),
            ("verdict", "pass"),
        )
        for key, value in mutations:
            with self.subTest(key=key):
                broken = copy.deepcopy(self.evidence)
                broken["failure"]["import_diagnostic"][key] = value
                broken["failure"]["import_diagnostic"][
                    "diagnostic_sha256"
                ] = verifier.diagnostic_payload_sha256(
                    broken["failure"]["import_diagnostic"]
                )
                self.assertIn(
                    "V9 failure evidence semantics changed",
                    verifier.verify(broken, verify_git_state=False),
                )

        for role_index, cached_count in ((0, 0), (1, 0), (2, 1)):
            with self.subTest(role_index=role_index):
                broken = copy.deepcopy(self.evidence)
                broken["failure"]["import_diagnostic"]["roles"][role_index][
                    "cached_count"
                ] = cached_count
                broken["failure"]["import_diagnostic"][
                    "diagnostic_sha256"
                ] = verifier.diagnostic_payload_sha256(
                    broken["failure"]["import_diagnostic"]
                )
                self.assertIn(
                    "V9 failure evidence semantics changed",
                    verifier.verify(broken, verify_git_state=False),
                )

    def test_derived_hashes_and_extra_fields_fail_closed(self) -> None:
        for name in ("producer_diagnostic", "import_diagnostic"):
            with self.subTest(name=name):
                broken = copy.deepcopy(self.evidence)
                broken["failure"][name]["progress_bytes"] += 1
                self.assertIn(
                    f"V9 {name.replace('_', ' ')} hash does not derive",
                    verifier.verify(broken, verify_git_state=False),
                )

        broken = copy.deepcopy(self.evidence)
        broken["cleanup"]["compact_log_payload_sha256"] = "0" * 64
        self.assertIn(
            "V9 cleanup compact payload hash does not derive",
            verifier.verify(broken, verify_git_state=False),
        )

        broken = copy.deepcopy(self.evidence)
        broken["failure"]["unexpected"] = "must not be accepted"
        self.assertIn(
            "V9 failure evidence semantics changed",
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

    def test_parent_history_and_tree_drift_fail_closed(self) -> None:
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
                "V9 controller parent binding changed",
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
                "V9 request addition history changed",
                verifier.verify_frozen_git(),
            )

        original_bytes = verifier._git_bytes
        workflow = next(
            item for item in verifier.FROZEN_PATHS if item.suffix == ".yml"
        )
        tree_target = (
            "show",
            f"{verifier.DIRECT_PARENT_COMMIT}:{workflow.as_posix()}",
        )

        def tamper_tree(*args: str) -> bytes:
            if args == tree_target:
                return b"tampered\n"
            return original_bytes(*args)

        with mock.patch.object(verifier, "_git_bytes", side_effect=tamper_tree):
            self.assertTrue(
                any(
                    "parent tree file hash changed" in error
                    for error in verifier.verify_frozen_git()
                )
            )

    def test_request_delta_mode_and_template_drift_fail_closed(self) -> None:
        original_text = verifier._git_text
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
                "V9 controller is no longer request-only",
                verifier.verify_frozen_git(),
            )

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
                "V9 request retained mode changed",
                verifier.verify_frozen_git(),
            )

        original_bytes = verifier._git_bytes
        template_target = (
            "show",
            f"{verifier.DIRECT_PARENT_COMMIT}:{verifier.TEMPLATE_PATH.as_posix()}",
        )

        def tamper_template(*args: str) -> bytes:
            if args == template_target:
                return b"{}\n"
            return original_bytes(*args)

        with mock.patch.object(
            verifier,
            "_git_bytes",
            side_effect=tamper_template,
        ):
            errors = verifier.verify_frozen_git()
        self.assertIn("V9 frozen template placeholder count changed", errors)
        self.assertIn("V9 control request differs from its frozen template", errors)

    def test_receipt_head_and_worktree_drift_fail_closed(self) -> None:
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
                "V9 inert remote receipt parent binding changed",
                verifier.verify_frozen_git(),
            )

        original_bytes = verifier._git_bytes
        request_target = (
            "show",
            f"HEAD:{verifier.REQUEST_PATH.as_posix()}",
        )

        def tamper_head_request(*args: str) -> bytes:
            if args == request_target:
                return b"tampered request\n"
            return original_bytes(*args)

        with mock.patch.object(
            verifier,
            "_git_bytes",
            side_effect=tamper_head_request,
        ):
            self.assertIn(
                "V9 request is not retained byte-exact at HEAD",
                verifier.verify_frozen_git(),
            )

        frozen_path = next(iter(verifier.FROZEN_PATHS))
        head_target = ("show", f"HEAD:{frozen_path.as_posix()}")

        def tamper_head_frozen(*args: str) -> bytes:
            if args == head_target:
                return b"tampered frozen HEAD\n"
            return original_bytes(*args)

        with mock.patch.object(
            verifier,
            "_git_bytes",
            side_effect=tamper_head_frozen,
        ):
            self.assertTrue(
                any(
                    "V9 HEAD frozen file hash changed" in error
                    for error in verifier.verify_frozen_git()
                )
            )

        original_path_read_bytes = Path.read_bytes
        local_target = verifier.ROOT / frozen_path

        def tamper_worktree(target: Path) -> bytes:
            if target == local_target:
                return b"tampered worktree\n"
            return original_path_read_bytes(target)

        with mock.patch.object(Path, "read_bytes", tamper_worktree):
            self.assertTrue(
                any(
                    "frozen V9 file hash changed" in error
                    for error in verifier.verify_frozen_git()
                )
            )

        with mock.patch.object(
            verifier,
            "EVIDENCE_FILE_SHA256",
            "0" * 64,
        ):
            self.assertIn(
                "V9 failure evidence file bytes changed",
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
