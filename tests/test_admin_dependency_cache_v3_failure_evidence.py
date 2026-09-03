from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_v3_failure_evidence as verifier  # noqa: E402


class AdminDependencyCacheV3FailureEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence = verifier.load_strict()

    def test_exact_evidence_passes(self) -> None:
        self.assertEqual(verifier.verify(self.evidence), [])

    def test_outcome_mutations_fail_closed(self) -> None:
        mutations = (
            ("github_run", "attempt", 2),
            ("github_run", "conclusion", "success"),
            ("github_run", "rerun_count", 1),
            ("runner", "docker_buildx_version", "0.35.1"),
            ("failure", "actual_flags_payload_retained", True),
            ("cleanup", "post_removal_transient_validation", "UNKNOWN"),
            ("provider_artifact", "api_total_count", 1),
            ("provider_artifact", "authenticated_download_count", 1),
            (
                "conditional_builder_and_publication",
                "builder_authorization_activated",
                True,
            ),
            (
                "conditional_builder_and_publication",
                "admin_acr_push_count",
                1,
            ),
            ("authorization_outcome", "github_v3_one_shot_run_consumed", False),
            ("readiness", "credit_added", True),
        )
        for section, key, value in mutations:
            with self.subTest(section=section, key=key):
                broken = copy.deepcopy(self.evidence)
                broken[section][key] = value
                self.assertTrue(verifier.verify(broken))

    def test_flags_contract_is_exact_and_ordered(self) -> None:
        for replacement in (
            [],
            ["--allow-insecure-entitlement=security.insecure"],
            verifier.DEFAULT_FLAGS + ["--debug"],
            ["--debug"] + verifier.DEFAULT_FLAGS,
        ):
            with self.subTest(replacement=replacement):
                broken = copy.deepcopy(self.evidence)
                broken["failure"]["remediation_contract"][
                    "accept_exact_default_flags_only"
                ] = replacement
                self.assertIn(
                    "failure detail changed",
                    verifier.verify(broken),
                )

    def test_nested_extra_field_is_rejected(self) -> None:
        broken = copy.deepcopy(self.evidence)
        broken["cleanup"]["unexpected"] = "must not be accepted"
        self.assertIn("cleanup outcome changed", verifier.verify(broken))

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
