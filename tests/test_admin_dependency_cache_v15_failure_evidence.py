from __future__ import annotations

import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_v15_failure_evidence as evidence  # noqa: E402


class AdminDependencyCacheV15FailureEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = evidence.load_strict()

    def test_exact_secret_free_evidence_passes_without_git(self) -> None:
        self.assertEqual(evidence.verify(self.payload, verify_git_state=False), [])
        self.assertEqual(
            evidence.semantic_sha256(self.payload),
            evidence.EXPECTED_SEMANTIC_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(evidence.EVIDENCE_PATH.read_bytes()).hexdigest(),
            evidence.EVIDENCE_FILE_SHA256,
        )

    def test_terminal_contract_has_exact_path_sets(self) -> None:
        self.assertEqual(len(evidence.TERMINAL_CHECKPOINT_FILES), 11)
        self.assertEqual(len(set(evidence.TERMINAL_CHECKPOINT_FILES)), 11)
        self.assertEqual(len(evidence.TERMINAL_ADDITION_FILES), 3)
        self.assertEqual(len(set(evidence.TERMINAL_ADDITION_FILES)), 3)
        self.assertEqual(len(evidence.RECEIPT_FILES), 4)
        self.assertEqual(len(set(evidence.RECEIPT_FILES)), 4)
        self.assertEqual(
            set(evidence.TERMINAL_IMMUTABLE_FILES),
            set(evidence.TERMINAL_ADDITION_FILES),
        )

    def test_each_terminal_boundary_mutation_fails_closed(self) -> None:
        cases = (
            ("run", ("github_run", "run_id"), 1),
            ("failure", ("failure", "failure_code"), "wrong"),
            ("pair", ("failure", "pair_classification"), "SAME_DIGEST_CACHED"),
            ("consumer", ("failure", "consumer_runtime_pip_cached"), True),
            ("structure", ("cache_structure", "record_count"), 18),
            ("cleanup", ("cleanup", "overall_pass"), False),
            ("ledger", ("run_ledger", "repository_unique_run_count"), 486),
            ("artifact", ("provider_artifact", "api_total_count"), 1),
            ("log", ("native_job_log", "line_count"), 3293),
            ("ci", ("control_head_ci", "push_ci_total_test_count"), 0),
            (
                "authorization",
                ("authorization_outcome", "v15_attempt_may_not_be_rerun"),
                False,
            ),
            ("readiness", ("readiness", "credit_added"), True),
        )
        for name, keys, value in cases:
            with self.subTest(name=name):
                candidate = copy.deepcopy(self.payload)
                target = candidate
                for key in keys[:-1]:
                    target = target[key]
                target[keys[-1]] = value
                self.assertTrue(
                    evidence.verify(candidate, verify_git_state=False)
                )

    def test_duplicate_keys_and_nonfinite_numbers_are_rejected(self) -> None:
        for name, payload in (
            ("duplicate", '{"schema_version": 1, "schema_version": 1}\n'),
            ("nan", '{"value": NaN}\n'),
            ("infinity", '{"value": Infinity}\n'),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "evidence.json"
                path.write_text(payload, encoding="utf-8")
                with self.assertRaises(ValueError):
                    evidence.load_strict(path)

    def test_exact_git_terminal_state_passes_after_checkpoint(self) -> None:
        checkpoint = evidence.terminal_checkpoint()
        errors = evidence.verify_frozen_git()
        if checkpoint is None:
            self.assertIn(
                "V15 terminal addition anchor is not exact",
                errors,
            )
            self.assertEqual(evidence.terminal_state(), "INVALID")
        else:
            self.assertEqual(errors, [])
            self.assertIn(
                evidence.terminal_state(),
                {
                    "V15_TRIGGERED_ATTEMPT1_FAILED_"
                    "TERMINAL_SUPERSESSION_EXACT",
                    "V15_TRIGGERED_ATTEMPT1_FAILED_TERMINAL_RECEIPT_EXACT",
                },
            )


if __name__ == "__main__":
    unittest.main()
