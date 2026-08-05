from __future__ import annotations

import hashlib
import subprocess
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (
    ROOT / ".github" / "workflows" / "admin-dependency-cache-export-v17.yml"
)
RELEASE_SHA = "5335bdaed933b1f999b5f819c047ec50c11821ae"


class AdminDependencyCacheExportV17Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = WORKFLOW.read_text(encoding="utf-8")
        cls.workflow = yaml.load(cls.source, Loader=yaml.BaseLoader)

    def test_activation_is_one_native_manual_dispatch(self) -> None:
        self.assertEqual(self.workflow["on"], {"workflow_dispatch": ""})
        self.assertNotIn("push", self.workflow["on"])
        self.assertNotIn("pull_request", self.workflow["on"])
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        self.assertEqual(
            self.workflow["jobs"]["export-wheelhouse"]["timeout-minutes"],
            "120",
        )
        self.assertIn('test "${GITHUB_RUN_ATTEMPT}" = "1"', self.source)
        for obsolete in (
            ".github/release-requests/admin-5335bda-dependency-cache-v17.json",
            "admin-dependency-cache-export-request-v17.json",
            "verify_admin_dependency_cache_bundle_v17",
            "verify_admin_dependency_cache_transient_state_v17",
            "live-ledger",
            "receipt",
            "topology",
            "R17",
            "V18",
        ):
            self.assertNotIn(obsolete, self.source)

    def test_c17_release_and_dependency_inputs_stay_immutable(self) -> None:
        self.assertIn(
            "7ee9a15425c38e8f0d5382cba488bd4a6ce92d6e",
            self.source,
        )
        self.assertIn(
            "5335bdaed933b1f999b5f819c047ec50c11821ae",
            self.source,
        )
        self.assertIn(
            "38e574e56406ba3380acb78edbe784508cc537cd",
            self.source,
        )
        historical_dockerfile = subprocess.run(
            ["git", "show", f"{RELEASE_SHA}:Dockerfile"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
        historical_requirements = subprocess.run(
            ["git", "show", f"{RELEASE_SHA}:model/requirements-api.txt"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
        self.assertEqual(
            hashlib.sha256(historical_dockerfile).hexdigest(),
            "ed6282c422dde6e49c33da877bccf735dfbb19e29a834930fb2a1a52ef21b447",
        )
        self.assertEqual(
            hashlib.sha256(historical_requirements).hexdigest(),
            "0231c534fc2ca1ca503f5b29e19c503be995672cf20afd8203e207ffc8354ea9",
        )
        self.assertIn(
            "python:3.11.15-slim-trixie@sha256:"
            "db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93",
            self.source,
        )

    def test_download_uses_official_pypi_with_inactivity_timeout_and_retry(self) -> None:
        for expected in (
            "PIP_CONFIG_FILE=/dev/null",
            "PIP_DEFAULT_TIMEOUT=300",
            "PIP_INDEX_URL=https://pypi.org/simple",
            "PIP_RETRIES=4",
            "for attempt in 1 2",
            "download_all_with_retry",
            "--only-binary=:all:",
            "--dest /wheelhouse --no-deps --no-binary=:all:",
            "jieba==0.42.1",
            '"setuptools>=40.8.0"',
        ):
            self.assertIn(expected, self.source)
        self.assertEqual(self.source.count("jieba==0.42.1"), 3)
        for forbidden in (
            "--trusted-host",
            "--extra-index-url",
            "pypi.tuna",
            "mirrors.",
            "--no-cache-dir --dest",
        ):
            self.assertNotIn(forbidden, self.source)
        env = self.workflow["jobs"]["export-wheelhouse"]["env"]
        bounded_seconds = (
            int(env["NOTEAI_PULL_TIMEOUT_SECONDS"])
            + 2 * int(env["NOTEAI_DOWNLOAD_ATTEMPT_TIMEOUT_SECONDS"])
            + 2 * int(env["NOTEAI_BOOTSTRAP_TIMEOUT_SECONDS"])
            + 2 * int(env["NOTEAI_BUILD_TIMEOUT_SECONDS"])
        )
        self.assertEqual(bounded_seconds, 5700)
        self.assertLess(bounded_seconds, 120 * 60)
        self.assertGreaterEqual(120 * 60 - bounded_seconds, 15 * 60)

    def test_distinct_buildkit_builders_prove_offline_import(self) -> None:
        producer = "noteai-v17-wheelhouse-producer-${{ github.run_id }}"
        consumer = "noteai-v17-wheelhouse-consumer-${{ github.run_id }}"
        self.assertIn(producer, self.source)
        self.assertIn(consumer, self.source)
        self.assertNotEqual(producer, consumer)
        for expected in (
            "docker buildx create",
            "--no-cache",
            "--network=none",
            "--build-context \"wheelhouse=${artifact_root}/wheelhouse\"",
            "--no-index --find-links=/wheelhouse",
            "fresh_builder_import_success=true",
        ):
            self.assertIn(expected, self.source)
        self.assertIn(
            "moby/buildkit@sha256:"
            "2f5adac4ecd194d9f8c10b7b5d7bceb5186853db1b26e5abd3a657af0b7e26ec",
            self.source,
        )

    def test_acceptance_is_github_native_and_artifact_is_ephemeral(self) -> None:
        upload = next(
            step
            for step in self.workflow["jobs"]["export-wheelhouse"]["steps"]
            if step.get("id") == "upload"
        )
        self.assertEqual(upload["with"]["retention-days"], "1")
        self.assertEqual(upload["with"]["compression-level"], "0")
        self.assertEqual(upload["with"]["if-no-files-found"], "error")
        for expected in (
            "GITHUB_RUN_ID",
            "steps.upload.outputs.artifact-id",
            "steps.upload.outputs.artifact-digest",
            "NOTEAI_V17_NATIVE_ACCEPTANCE",
            "c17_sha=%s",
            "fresh_builder_import_success=true",
        ):
            self.assertIn(expected, self.source)


if __name__ == "__main__":
    unittest.main()
