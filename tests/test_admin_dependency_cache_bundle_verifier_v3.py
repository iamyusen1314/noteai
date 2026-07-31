from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_bundle_v3 as verifier  # noqa: E402


def _load_v2_fixture_module():
    path = ROOT / "tests" / "test_admin_dependency_cache_bundle_verifier.py"
    spec = importlib.util.spec_from_file_location("_cache_bundle_v2_tests", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load V2 cache-bundle fixtures")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V2_FIXTURES = _load_v2_fixture_module()
PLATFORM_PROJECTION_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "admin_dependency_cache_buildkit_v0.31.2_platform_projection.json"
)
PLATFORM_PROJECTION = json.loads(
    PLATFORM_PROJECTION_PATH.read_text(encoding="utf-8")
)


class AdminDependencyCacheBundleVerifierV3Tests(unittest.TestCase):
    def _write_evidence(
        self,
        root: Path,
        *,
        dockerfile_kind: str = "prefix",
    ) -> tuple[Path, Path]:
        fixture = V2_FIXTURES.AdminDependencyCacheBundleVerifierTests()
        metadata_path, progress_path = fixture._write_build_evidence(
            root,
            dockerfile_kind=dockerfile_kind,
        )
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        provenance = metadata["buildx.build.provenance"]
        provenance["invocation"]["environment"] = PLATFORM_PROJECTION[
            "expected_builder_environment"
        ]
        for item in provenance["buildConfig"]["llbDefinition"]:
            item["op"]["platform"] = PLATFORM_PROJECTION[
                "expected_llb_target_platform"
            ]
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        return metadata_path, progress_path

    def test_platform_projection_is_source_bound_and_truthfully_labeled(
        self,
    ) -> None:
        self.assertEqual(
            PLATFORM_PROJECTION["classification"],
            "SOURCE_PROJECTED_NOT_RETAINED_RUNTIME_METADATA",
        )
        self.assertFalse(PLATFORM_PROJECTION["actual_v2_metadata_retained"])
        self.assertEqual(
            PLATFORM_PROJECTION["source"],
            {
                "repository": "moby/buildkit",
                "tag": "v0.31.2",
                "tag_object": "37aba93910a245e9196ccf67f4afb55f18b39f81",
                "commit": "e42e1bfd389af7203238cce77b1f7dad447285e9",
            },
        )
        self.assertEqual(
            PLATFORM_PROJECTION["expected_builder_environment"],
            {
                "platform": "linux/amd64",
                "dockerfileVersion": "1.25.0",
            },
        )
        self.assertEqual(
            PLATFORM_PROJECTION["expected_llb_target_platform"],
            {"Architecture": "amd64", "OS": "linux"},
        )

    def test_reviewed_buildkit_v0312_shape_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            metadata, progress = self._write_evidence(Path(temporary))
            summary = verifier.validate_build_evidence(
                metadata,
                progress,
                dockerfile_kind="prefix",
                require_network_vertices_cached=True,
            )
            self.assertEqual(summary["builder_platform"], "linux/amd64")
            self.assertEqual(
                summary["dockerfile_frontend_version"],
                "1.25.0",
            )
            self.assertEqual(summary["target_platform"], "linux/amd64")
            self.assertEqual(summary["target_platform_vertex_count"], 3)
            self.assertEqual(summary["metadata_sha256"], verifier.sha256_file(metadata))

    def test_builder_environment_fails_closed(self) -> None:
        mutations = (
            {},
            {"platform": "linux/386", "dockerfileVersion": "1.25.0"},
            {"platform": "linux/arm64", "dockerfileVersion": "1.25.0"},
            {"platform": "linux/amd64/v2", "dockerfileVersion": "1.25.0"},
            {"platform": "linux/amd64/v3", "dockerfileVersion": "1.25.0"},
            {"platform": ["linux/amd64"], "dockerfileVersion": "1.25.0"},
            {
                "platform": "linux/amd64,linux/arm64",
                "dockerfileVersion": "1.25.0",
            },
            {"platform": "linux/amd64"},
            {"platform": "linux/amd64", "dockerfileVersion": "1.24.0"},
            {
                "platform": "linux/amd64",
                "dockerfileVersion": "1.25.0",
                "unexpected": True,
            },
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata_path, progress = self._write_evidence(root)
            original = json.loads(metadata_path.read_text(encoding="utf-8"))
            for index, environment in enumerate(mutations):
                with self.subTest(index=index, environment=environment):
                    broken = json.loads(json.dumps(original))
                    broken["buildx.build.provenance"]["invocation"][
                        "environment"
                    ] = environment
                    candidate = root / f"metadata-{index}.json"
                    candidate.write_text(json.dumps(broken), encoding="utf-8")
                    with self.assertRaisesRegex(
                        verifier.BundleError,
                        "builder environment changed",
                    ):
                        verifier.validate_build_evidence(
                            candidate,
                            progress,
                            dockerfile_kind="prefix",
                            require_network_vertices_cached=True,
                        )

    def test_target_platform_fails_closed(self) -> None:
        mutations = (
            {"Architecture": "386", "OS": "linux"},
            {"Architecture": "arm64", "OS": "linux"},
            {"Architecture": "amd64", "OS": "linux", "Variant": "v2"},
            {"Architecture": "amd64", "OS": "linux", "Variant": "v3"},
            {"Architecture": "amd64", "OS": "windows"},
            {"Architecture": "amd64", "OS": "linux", "OSVersion": "1"},
            {"Architecture": "amd64", "OS": "linux", "OSFeatures": []},
            ["linux/amd64"],
            "linux/amd64",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata_path, progress = self._write_evidence(root)
            original = json.loads(metadata_path.read_text(encoding="utf-8"))
            for index, platform in enumerate(mutations):
                with self.subTest(index=index, platform=platform):
                    broken = json.loads(json.dumps(original))
                    broken["buildx.build.provenance"]["buildConfig"][
                        "llbDefinition"
                    ][0]["op"]["platform"] = platform
                    candidate = root / f"target-{index}.json"
                    candidate.write_text(json.dumps(broken), encoding="utf-8")
                    with self.assertRaisesRegex(
                        verifier.BundleError,
                        "target platform changed",
                    ):
                        verifier.validate_build_evidence(
                            candidate,
                            progress,
                            dockerfile_kind="prefix",
                            require_network_vertices_cached=True,
                        )

    def test_target_platform_must_be_present(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata_path, progress = self._write_evidence(root)
            broken = json.loads(metadata_path.read_text(encoding="utf-8"))
            for item in broken["buildx.build.provenance"]["buildConfig"][
                "llbDefinition"
            ]:
                item["op"].pop("platform")
            metadata_path.write_text(json.dumps(broken), encoding="utf-8")
            with self.assertRaisesRegex(
                verifier.BundleError,
                "target platform evidence missing",
            ):
                verifier.validate_build_evidence(
                    metadata_path,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )

    def test_copied_wrapper_and_frozen_base_run_as_two_file_trust_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, progress = self._write_evidence(root)
            wrapper = root / "trusted-v3-wrapper.py"
            base = root / "trusted-v2-base.py"
            shutil.copyfile(Path(verifier.__file__), wrapper)
            shutil.copyfile(
                ROOT / "tools" / "verify_admin_dependency_cache_bundle.py",
                base,
            )
            environment = os.environ.copy()
            environment["NOTEAI_BASE_BUNDLE_VERIFIER_PATH"] = str(base)
            program = """
import importlib.util
import json
import sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("_copied_v3", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
summary = module.validate_build_evidence(
    Path(sys.argv[2]),
    Path(sys.argv[3]),
    dockerfile_kind="prefix",
    require_network_vertices_cached=True,
)
print(json.dumps({
    "builder_platform": summary["builder_platform"],
    "target_platform": summary["target_platform"],
}))
"""
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    program,
                    str(wrapper),
                    str(metadata),
                    str(progress),
                ],
                env=environment,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads(result.stdout),
                {
                    "builder_platform": "linux/amd64",
                    "target_platform": "linux/amd64",
                },
            )

    def test_copied_wrapper_rejects_missing_or_drifted_base(self) -> None:
        cases = ("missing", "drifted")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wrapper = root / "trusted-v3-wrapper.py"
            shutil.copyfile(Path(verifier.__file__), wrapper)
            for case in cases:
                with self.subTest(case=case):
                    base = root / f"{case}-base.py"
                    if case == "drifted":
                        shutil.copyfile(
                            (
                                ROOT
                                / "tools"
                                / "verify_admin_dependency_cache_bundle.py"
                            ),
                            base,
                        )
                        with base.open("ab") as handle:
                            handle.write(b"\n")
                    environment = os.environ.copy()
                    environment["NOTEAI_BASE_BUNDLE_VERIFIER_PATH"] = str(
                        base
                    )
                    result = subprocess.run(
                        [sys.executable, str(wrapper), "--help"],
                        env=environment,
                        check=False,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(
                        (
                            "frozen V2 bundle verifier is missing"
                            if case == "missing"
                            else "frozen V2 bundle verifier hash drift"
                        ),
                        result.stderr,
                    )


if __name__ == "__main__":
    unittest.main()
