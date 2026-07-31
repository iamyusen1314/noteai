from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_bundle_v3 as verifier  # noqa: E402


def _load_v3_fixture_module():
    path = ROOT / "tests" / "test_admin_dependency_cache_bundle_verifier_v3.py"
    spec = importlib.util.spec_from_file_location("_cache_bundle_v3_tests", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load V3 cache-bundle fixtures")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V3_FIXTURES = _load_v3_fixture_module()
SOURCE_PROJECTION_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "admin_dependency_cache_buildx_v0.35.0_provenance_gha_disabled_projection.json"
)
SOURCE_PROJECTION = json.loads(
    SOURCE_PROJECTION_PATH.read_text(encoding="utf-8")
)


class AdminDependencyCacheBundleVerifierV5Tests(unittest.TestCase):
    def _write_evidence(self, root: Path) -> tuple[Path, Path]:
        fixture = V3_FIXTURES.AdminDependencyCacheBundleVerifierV3Tests()
        return fixture._write_evidence(root)

    def test_source_projection_is_truthfully_labeled(self) -> None:
        self.assertEqual(
            SOURCE_PROJECTION["classification"],
            "SOURCE_PROVEN_CONFIGURATION_CONTRACT_NOT_V5_RUNTIME_EVIDENCE",
        )
        self.assertFalse(
            SOURCE_PROJECTION["actual_v5_runtime_metadata_retained"]
        )
        self.assertEqual(
            SOURCE_PROJECTION["buildx"]["docker_container_factory"][
                "approved_driver_option"
            ],
            {"provenance-add-gha": "false"},
        )
        self.assertEqual(
            SOURCE_PROJECTION["v5_expected_configuration"][
                "pre_build_direct_json_file_count"
            ],
            0,
        )
        self.assertEqual(
            SOURCE_PROJECTION["v5_expected_configuration"][
                "post_build_environment_projection"
            ],
            {
                "platform": "linux/amd64",
                "dockerfileVersion": "1.25.0",
            },
        )

    def test_all_github_or_unknown_environment_keys_fail_closed(self) -> None:
        cases = (
            {
                "platform": "linux/amd64",
                "dockerfileVersion": "1.25.0",
                "github_event_name": "push",
            },
            {
                "platform": "linux/amd64",
                "dockerfileVersion": "1.25.0",
                "github_event_payload": {"dummy": {"nested": True}},
            },
            {
                "platform": "linux/amd64",
                "dockerfileVersion": "1.25.0",
                "github_event_name": "push",
                "github_event_payload": {"dummy": ["nested"]},
            },
            {
                "platform": "linux/amd64",
                "dockerfileVersion": "1.25.0",
                "unknown": None,
            },
            {
                "platform": "linux/amd64",
                "dockerfileVersion": "1.25.0",
                "github_event_payload": [],
            },
            {
                "platform": "linux/amd64",
                "dockerfileVersion": "1.25.0",
                "github_event_payload": "dummy",
            },
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata_path, progress = self._write_evidence(root)
            original = json.loads(metadata_path.read_text(encoding="utf-8"))
            for index, environment in enumerate(cases):
                with self.subTest(index=index):
                    candidate_payload = json.loads(json.dumps(original))
                    candidate_payload["buildx.build.provenance"]["invocation"][
                        "environment"
                    ] = environment
                    candidate = root / f"metadata-{index}.json"
                    candidate.write_text(
                        json.dumps(candidate_payload),
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(
                        verifier.BundleError,
                        "^BuildKit builder environment changed$",
                    ):
                        verifier.validate_build_evidence(
                            candidate,
                            progress,
                            dockerfile_kind="prefix",
                            require_network_vertices_cached=True,
                        )

    def test_cli_failure_is_generic_and_does_not_write_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata_path, progress = self._write_evidence(root)
            sentinel = "DUMMY_EVENT_SENTINEL_f17a"
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            payload["buildx.build.provenance"]["invocation"]["environment"] = {
                "platform": "linux/amd64",
                "dockerfileVersion": "1.25.0",
                "github_event_name": "push",
                "github_event_payload": {
                    "dummy": {
                        "sentinel": sentinel,
                    }
                },
            }
            metadata_path.write_text(json.dumps(payload), encoding="utf-8")
            output = root / "must-not-exist.json"
            environment = dict(os.environ)
            environment["NOTEAI_BASE_BUNDLE_VERIFIER_PATH"] = str(
                ROOT / "tools" / "verify_admin_dependency_cache_bundle.py"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(
                        ROOT
                        / "tools"
                        / "verify_admin_dependency_cache_bundle_v3.py"
                    ),
                    "verify-build",
                    "--metadata",
                    str(metadata_path),
                    "--progress",
                    str(progress),
                    "--dockerfile",
                    "prefix",
                    "--require-network-cached",
                    "--output",
                    str(output),
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(
                result.stdout,
                "FAIL: BuildKit builder environment changed\n",
            )
            self.assertEqual(result.stderr, "")
            self.assertNotIn(sentinel, result.stdout + result.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
