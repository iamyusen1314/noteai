from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_v5_failure_evidence as verifier  # noqa: E402


class AdminDependencyCacheV5FailureEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence = verifier.load_strict()

    def test_exact_evidence_and_frozen_git_pass(self) -> None:
        self.assertEqual(verifier.verify(self.evidence), [])

    def test_terminal_outcome_mutations_fail_closed(self) -> None:
        mutations = (
            ("git", "control_commit", "0" * 40),
            ("git", "request_sha256", "0" * 64),
            ("github_run", "run_id", 1),
            ("github_run", "job_id", 1),
            ("github_run", "attempt", 2),
            ("github_run", "head_sha", "0" * 40),
            ("github_run", "conclusion", "success"),
            ("github_run", "workflow_inventory_fully_paginated", False),
            ("runner", "image_version", "20260726.254.1"),
            ("runner", "runtime_image_matched_recovery_basis_version", True),
            ("runner", "github_actions_provenance_dropins", "PRESENT"),
            ("runner", "client_token_disabled", False),
            ("step_outcome", "dependency_cache_export", "success"),
            ("step_outcome", "transient_docker_cleanup", "failure"),
            ("failure", "build_command_completed", False),
            ("failure", "raw_progress_retained", True),
            ("failure", "frozen_top_level_parser_match_count", 1),
            ("failure", "actual_nested_network_vertex_match_count", 1),
            ("failure", "actual_vertex_names_retained", True),
            ("failure", "actual_nested_name_drift_claimed", True),
            ("failure", "primary_root_cause_determined", False),
            ("failure", "portable_archive_generation_reached", True),
            ("cleanup", "producer_builder_absent", "fail"),
            ("cleanup", "images_parity", "fail"),
            ("cleanup", "cleanup_effective", False),
            ("cleanup", "overall_pass", False),
            ("cleanup", "receipt_file_bytes_retained", True),
            ("provider_artifact", "api_total_count", 1),
            ("provider_artifact", "authenticated_download_count", 1),
            (
                "execution_scope",
                "conditional_cloud_builder_start_count_in_authorized_chain",
                1,
            ),
            ("execution_scope", "admin_acr_push_count_in_authorized_chain", 1),
            ("authorization_outcome", "github_v5_one_shot_run_consumed", False),
            ("authorization_outcome", "v5_attempt_may_not_be_rerun", False),
            ("readiness", "credit_added", True),
        )
        for section, key, value in mutations:
            with self.subTest(section=section, key=key):
                broken = copy.deepcopy(self.evidence)
                broken[section][key] = value
                self.assertIn(
                    "V5 failure evidence semantics changed",
                    verifier.verify(broken, verify_git_state=False),
                )

    def test_source_root_cause_and_unknown_runtime_are_both_locked(self) -> None:
        broken = copy.deepcopy(self.evidence)
        broken["failure"]["source_proven_incompatibility"][
            "frozen_verifier_vertex_map_is_deterministically_empty"
        ] = False
        self.assertTrue(verifier.verify(broken, verify_git_state=False))

        broken = copy.deepcopy(self.evidence)
        broken["failure"]["actual_nested_network_vertex_match_count_status"] = (
            "OBSERVED"
        )
        self.assertTrue(verifier.verify(broken, verify_git_state=False))

        broken = copy.deepcopy(self.evidence)
        broken["failure"]["adjacent_source_proven_replay_issue"][
            "reached_by_v5"
        ] = True
        self.assertTrue(verifier.verify(broken, verify_git_state=False))

        with mock.patch.object(
            verifier,
            "SOURCE_PROJECTION_PATH",
            verifier.EVIDENCE_PATH,
        ):
            self.assertIn(
                "V5 rawjson source projection hash changed",
                verifier.verify(self.evidence, verify_git_state=False),
            )

    def test_ci_cleanup_and_extra_field_mutations_fail_closed(self) -> None:
        broken = copy.deepcopy(self.evidence)
        broken["ordinary_ci"][0]["test_count"] = 1296
        self.assertTrue(verifier.verify(broken, verify_git_state=False))

        broken = copy.deepcopy(self.evidence)
        broken["cleanup"]["compact_log_payload_sha256"] = "0" * 64
        self.assertIn(
            "V5 cleanup compact payload hash does not derive",
            verifier.verify(broken, verify_git_state=False),
        )

        broken = copy.deepcopy(self.evidence)
        broken["cleanup"]["producer_builder_absent"] = "fail"
        self.assertIn(
            "V5 cleanup compact payload hash does not derive",
            verifier.verify(broken, verify_git_state=False),
        )

        broken = copy.deepcopy(self.evidence)
        broken["failure"]["unexpected"] = "must not be accepted"
        self.assertIn(
            "V5 failure evidence semantics changed",
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

    def test_plan_and_control_tree_hash_drift_fails_closed(self) -> None:
        original = verifier._git_bytes
        workflow = next(
            path
            for path in verifier.FROZEN_PATHS
            if path.name == "admin-dependency-cache-export-v5.yml"
        )
        for commit in (
            verifier.PLAN_CHECKPOINT_COMMIT,
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
