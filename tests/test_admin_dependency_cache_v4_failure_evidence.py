from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_v4_failure_evidence as verifier  # noqa: E402


class AdminDependencyCacheV4FailureEvidenceTests(unittest.TestCase):
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
            ("runner", "image_version", "20260720.247.2"),
            ("runner", "runtime_image_matched_recovery_basis_version", True),
            ("step_outcome", "dependency_cache_export", "success"),
            ("failure", "actual_environment_payload_retained", True),
            ("failure", "actual_environment", {"fabricated": "payload"}),
            ("failure", "dynamic_github_event_payload_observed", True),
            ("failure", "primary_root_cause_determined", False),
            ("failure", "portable_archive_generation_reached", True),
            ("cleanup", "builder_removal_outcome", "PASS"),
            ("cleanup", "docker_parity_outcome", "PASS"),
            ("cleanup", "task_owned_root_removal_outcome", "PASS"),
            ("cleanup", "cleanup_root_cause_determined", True),
            ("cleanup", "persistent_residue_zero_claimed", True),
            ("provider_artifact", "api_total_count", 1),
            ("provider_artifact", "authenticated_download_count", 1),
            ("execution_scope", "conditional_cloud_builder_start_count", 1),
            ("execution_scope", "admin_acr_push_count", 1),
            ("authorization_outcome", "github_v4_one_shot_run_consumed", False),
            ("authorization_outcome", "v4_attempt_may_not_be_rerun", False),
            ("readiness", "credit_added", True),
        )
        for section, key, value in mutations:
            with self.subTest(section=section, key=key):
                broken = copy.deepcopy(self.evidence)
                broken[section][key] = value
                self.assertIn(
                    "V4 failure evidence semantics changed",
                    verifier.verify(broken, verify_git_state=False),
                )

    def test_ci_and_step_mutations_fail_closed(self) -> None:
        broken = copy.deepcopy(self.evidence)
        broken["ordinary_ci"][0]["test_count"] = 1243
        self.assertTrue(verifier.verify(broken, verify_git_state=False))

        broken = copy.deepcopy(self.evidence)
        broken["step_outcome"]["unexpected"] = "success"
        self.assertTrue(verifier.verify(broken, verify_git_state=False))

    def test_nested_extra_field_is_rejected(self) -> None:
        broken = copy.deepcopy(self.evidence)
        broken["cleanup"]["unexpected"] = "must not be accepted"
        self.assertIn(
            "V4 failure evidence semantics changed",
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
            if path.name == "admin-dependency-cache-export-v4.yml"
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
