from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_bundle_v7 as v7  # noqa: E402
import verify_admin_dependency_cache_bundle_v8 as verifier  # noqa: E402


def _load_v7_fixture_module():
    fixture_path = (
        ROOT / "tests" / "test_admin_dependency_cache_bundle_verifier_v7.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_cache_bundle_v7_tests_v8",
        fixture_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load V7 cache-bundle fixtures")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V7_FIXTURES = _load_v7_fixture_module()
SOURCE_PROJECTION_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "admin_dependency_cache_buildkit_v0.31.2_"
    "empty_source_location_projection.json"
)
SOURCE_PROJECTION = json.loads(
    SOURCE_PROJECTION_PATH.read_text(encoding="utf-8")
)


def _diagnostic(stderr: str) -> dict:
    lines = stderr.splitlines()
    if len(lines) != 1:
        raise AssertionError(f"unexpected diagnostic line count: {len(lines)}")
    prefix = "noteai_v8_progress_diagnostic="
    if not lines[0].startswith(prefix):
        raise AssertionError("missing V8 diagnostic prefix")
    return json.loads(lines[0][len(prefix) :])


class AdminDependencyCacheBundleVerifierV8Tests(unittest.TestCase):
    def _fixture(self):
        return V7_FIXTURES.AdminDependencyCacheBundleVerifierV7Tests()

    def _write_evidence(
        self,
        root: Path,
        *,
        dockerfile_kind: str = "prefix",
        cached: bool = True,
        incremental: bool = True,
        second_cached: bool = True,
    ) -> tuple[Path, Path, list[str]]:
        fixture = self._fixture()
        metadata, progress, digests = fixture._write_evidence(
            root,
            dockerfile_kind=dockerfile_kind,
            cached=cached,
        )
        if incremental:
            fixture._incrementalize(
                progress,
                second_cached=second_cached,
            )
        return metadata, progress, digests

    @staticmethod
    def _metadata_payload(metadata: Path) -> dict:
        return json.loads(metadata.read_text(encoding="utf-8"))

    @staticmethod
    def _locations(payload: dict) -> dict:
        return payload["buildx.build.provenance"]["metadata"][
            "https://mobyproject.org/buildkit@v1#metadata"
        ]["source"]["locations"]

    @staticmethod
    def _write_metadata(metadata: Path, payload: dict) -> None:
        metadata.write_text(
            json.dumps(payload, separators=(",", ":")),
            encoding="utf-8",
        )

    def _add_empty_locations(
        self,
        metadata: Path,
        *,
        step_ids: tuple[str, ...] = ("step0",),
        before_populated: bool = False,
    ) -> None:
        payload = self._metadata_payload(metadata)
        locations = self._locations(payload)
        if before_populated:
            payload["buildx.build.provenance"]["metadata"][
                "https://mobyproject.org/buildkit@v1#metadata"
            ]["source"]["locations"] = {
                **{step_id: {} for step_id in step_ids},
                **locations,
            }
        else:
            for step_id in step_ids:
                locations[step_id] = {}
        self._write_metadata(metadata, payload)

    def test_source_projection_is_bound_and_never_runtime_evidence(self) -> None:
        self.assertEqual(
            hashlib.sha256(SOURCE_PROJECTION_PATH.read_bytes()).hexdigest(),
            "b5f5e806b7e822b536a850eca8861bb7b6f8934832d7bdb4e898e698d7f20eeb",
        )
        self.assertEqual(
            SOURCE_PROJECTION["classification"],
            (
                "SOURCE_PROVEN_EMPTY_SOURCE_LOCATION_CONTRACT_"
                "NOT_V7_RUNTIME_EVIDENCE"
            ),
        )
        self.assertFalse(
            SOURCE_PROJECTION["actual_v7_runtime_metadata_retained"]
        )
        self.assertFalse(
            SOURCE_PROJECTION["actual_v7_step9_payload_retained"]
        )
        self.assertFalse(
            SOURCE_PROJECTION["runtime_step9_shape_reconstructed"]
        )
        self.assertEqual(
            SOURCE_PROJECTION["buildkit"]["commit"],
            "e42e1bfd389af7203238cce77b1f7dad447285e9",
        )
        expected_sources = {
            "client/llb/state.go": (
                "370012c88c1c9c5676af132e86d9ff7b0b66852d",
                "dffe65648a394476d9f3a87f6e33a9f23d1f935e59f9ef7022aee526fba29bc4",
            ),
            "client/llb/sourcemap.go": (
                "4e3be2b499362d3cfb43066b57f8b6a227759b16",
                "587e7919f584b3fb9fcb38c788309ea91f4e0d0295ba14bc6e027ee7e6d5955c",
            ),
            "solver/llbsolver/provenance/buildconfig.go": (
                "7e92990c88f2a31ac4c3f4d9807e199745da03d5",
                "31fb4454bf21b3d38e76038fc2b19e5064117d4a06387233fe91ccba9f55e67e",
            ),
            "solver/llbsolver/provenance/types/types.go": (
                "e5b5f3741c0cb4002b435a583ca625b479fd1ea1",
                "adca3c54d6c4ea58347d8e014074f30a638ecb3451986245d9a5b8bdff78c698",
            ),
            "solver/pb/ops.proto": (
                "c58fc6126f04005ceb08711ab8fe71d17b050fb3",
                "309d9735d15cd945372a0dade3672cea19f94b61b6d0c05cf22856c608ff2a9c",
            ),
            "solver/pb/ops.pb.go": (
                "5f487cc3bc501a97c10f0d138266280025453f3a",
                "10466c5d72f8affdd8c29dfabf9ca4b1b27ecef20d05c940cb41ee5cd6e8b069",
            ),
        }
        self.assertEqual(
            {
                source["path"]: (
                    source["git_blob_sha1"],
                    source["sha256"],
                )
                for source in SOURCE_PROJECTION["buildkit"]["sources"]
            },
            expected_sources,
        )
        self.assertEqual(
            SOURCE_PROJECTION["v8_contract"],
            {
                "exact_empty_wrapper_allowed_as_nonbinding": True,
                "empty_wrapper_cannot_satisfy_dependency_role": True,
                "populated_location_delegated_to_frozen_v7": True,
                "null_empty_array_unknown_keys_rejected": True,
                "source_index_contract_not_broadened": True,
                "v7_runtime_payload_claimed": False,
            },
        )

    def test_exact_empty_locations_pass_for_both_targets_and_orders(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for dockerfile_kind in ("prefix", "full"):
                for before_populated in (False, True):
                    with self.subTest(
                        dockerfile_kind=dockerfile_kind,
                        before_populated=before_populated,
                    ):
                        target = (
                            root
                            / f"{dockerfile_kind}-{int(before_populated)}"
                        )
                        target.mkdir()
                        metadata, progress, digests = self._write_evidence(
                            target,
                            dockerfile_kind=dockerfile_kind,
                        )
                        self._add_empty_locations(
                            metadata,
                            step_ids=("step0", "step1"),
                            before_populated=before_populated,
                        )
                        original_metadata = metadata.read_bytes()
                        original_progress = progress.read_bytes()
                        stderr = io.StringIO()
                        with contextlib.redirect_stderr(stderr):
                            summary = verifier.validate_build_evidence(
                                metadata,
                                progress,
                                dockerfile_kind=dockerfile_kind,
                                require_network_vertices_cached=True,
                            )
                        self.assertEqual(
                            [item["vertex"] for item in summary["network_vertices"]],
                            digests,
                        )
                        self.assertTrue(summary["network_vertices_cached"])
                        self.assertIn("v8_rawjson_diagnostic", summary)
                        self.assertNotIn("v7_rawjson_diagnostic", summary)
                        diagnostic = summary["v8_rawjson_diagnostic"]
                        self.assertEqual(
                            diagnostic["schema_version"],
                            "noteai.admin-dependency-cache-v8-diagnostic.v1",
                        )
                        self.assertEqual(diagnostic["verdict"], "pass")
                        self.assertEqual(
                            _diagnostic(stderr.getvalue()),
                            diagnostic,
                        )
                        self.assertEqual(metadata.read_bytes(), original_metadata)
                        self.assertEqual(progress.read_bytes(), original_progress)

    def test_empty_locations_preserve_incremental_cache_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            uncached = root / "uncached"
            uncached.mkdir()
            metadata, progress, _ = self._write_evidence(
                uncached,
                cached=False,
                second_cached=False,
            )
            self._add_empty_locations(metadata)
            with contextlib.redirect_stderr(io.StringIO()):
                summary = verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=False,
                )
            self.assertFalse(summary["network_vertices_cached"])
            self.assertEqual(
                summary["v8_rawjson_diagnostic"][
                    "lifecycle_interval_count"
                ],
                6,
            )

            replay = root / "replay"
            replay.mkdir()
            metadata, progress, _ = self._write_evidence(replay)
            self._add_empty_locations(metadata)
            with contextlib.redirect_stderr(io.StringIO()):
                summary = verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertTrue(summary["network_vertices_cached"])
            self.assertEqual(
                summary["v8_rawjson_diagnostic"][
                    "lifecycle_interval_count"
                ],
                6,
            )

    def test_empty_role_location_cannot_satisfy_dependency_role(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            metadata, progress, _ = self._write_evidence(Path(temporary))
            payload = self._metadata_payload(metadata)
            self._locations(payload)["step3"] = {}
            self._write_metadata(metadata, payload)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(
                stderr
            ), self.assertRaises(verifier.V8BundleError) as raised:
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(
                raised.exception.failure_code,
                "PROVENANCE_ROLE_LOCATION_AMBIGUOUS",
            )
            diagnostic = _diagnostic(stderr.getvalue())
            self.assertEqual(
                diagnostic["schema_version"],
                "noteai.admin-dependency-cache-v8-diagnostic.v1",
            )
            self.assertEqual(
                diagnostic["failure_code"],
                "PROVENANCE_ROLE_LOCATION_AMBIGUOUS",
            )

    def test_unknown_step_and_malformed_empty_shapes_fail_closed(self) -> None:
        cases = (
            ("step999", {}, "PROVENANCE_LOCATION_INVALID"),
            ("step0", None, "PROVENANCE_LOCATION_INVALID"),
            ("step0", [], "PROVENANCE_LOCATION_INVALID"),
            ("step0", {"locations": []}, "PROVENANCE_LOCATION_INVALID"),
            ("step0", {"locations": None}, "PROVENANCE_LOCATION_INVALID"),
            ("step0", {"unexpected": True}, "PROVENANCE_LOCATION_INVALID"),
            (
                "step0",
                {"locations": [{}]},
                "PROVENANCE_LOCATION_INVALID",
            ),
            (
                "step0",
                {
                    "locations": [
                        {
                            "ranges": [
                                {
                                    "start": {"line": 7},
                                    "end": {"line": 7},
                                }
                            ],
                            "sourceIndex": 0,
                        }
                    ]
                },
                "PROVENANCE_LOCATION_INVALID",
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, (step_id, value, expected) in enumerate(cases):
                with self.subTest(index=index, value=value):
                    target = root / str(index)
                    target.mkdir()
                    metadata, progress, _ = self._write_evidence(target)
                    payload = self._metadata_payload(metadata)
                    self._locations(payload)[step_id] = value
                    self._write_metadata(metadata, payload)
                    with contextlib.redirect_stderr(
                        io.StringIO()
                    ), self.assertRaises(verifier.V8BundleError) as raised:
                        verifier.validate_build_evidence(
                            metadata,
                            progress,
                            dockerfile_kind="prefix",
                            require_network_vertices_cached=True,
                        )
                    self.assertEqual(
                        raised.exception.failure_code,
                        expected,
                    )

    def test_populated_location_structural_failures_remain_frozen(self) -> None:
        mutations = (
            (
                "non_exec",
                "PROVENANCE_ROLE_NOT_EXEC",
            ),
            (
                "wrong_platform",
                "PROVENANCE_ROLE_PLATFORM_INVALID",
            ),
            (
                "digest_ambiguous",
                "PROVENANCE_ROLE_DIGEST_AMBIGUOUS",
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for mutation, expected in mutations:
                with self.subTest(mutation=mutation):
                    target = root / mutation
                    target.mkdir()
                    metadata, progress, _ = self._write_evidence(target)
                    self._add_empty_locations(metadata)
                    payload = self._metadata_payload(metadata)
                    build_config = payload["buildx.build.provenance"][
                        "buildConfig"
                    ]
                    if mutation == "non_exec":
                        build_config["llbDefinition"][3]["op"]["Op"] = {
                            "source": {}
                        }
                    elif mutation == "wrong_platform":
                        build_config["llbDefinition"][3]["op"][
                            "platform"
                        ]["Architecture"] = "arm64"
                    else:
                        build_config["digestMapping"][
                            "sha256:" + ("f" * 64)
                        ] = "step3"
                    self._write_metadata(metadata, payload)
                    with contextlib.redirect_stderr(
                        io.StringIO()
                    ), self.assertRaises(verifier.V8BundleError) as raised:
                        verifier.validate_build_evidence(
                            metadata,
                            progress,
                            dockerfile_kind="prefix",
                            require_network_vertices_cached=True,
                        )
                    self.assertEqual(
                        raised.exception.failure_code,
                        expected,
                    )

    def test_dispatch_restores_after_success_failure_body_and_threads(
        self,
    ) -> None:
        frozen = [
            (target, name, getattr(target, name))
            for target, name in (
                (verifier._v6, "_range_projection"),
                (verifier._v7, "_initial_diagnostic"),
                (verifier._v7, "_emit_diagnostic"),
                (verifier._v7, "_validate_build_evidence"),
            )
        ]

        def assert_restored() -> None:
            for target, name, expected in frozen:
                self.assertIs(getattr(target, name), expected)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            success = root / "success"
            success.mkdir()
            metadata, progress, _ = self._write_evidence(success)
            self._add_empty_locations(metadata)
            with contextlib.redirect_stderr(io.StringIO()):
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            assert_restored()

            failure = root / "failure"
            failure.mkdir()
            metadata, progress, _ = self._write_evidence(failure)
            payload = self._metadata_payload(metadata)
            self._locations(payload)["step3"] = {}
            self._write_metadata(metadata, payload)
            with contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(verifier.V8BundleError):
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            assert_restored()

            targets = []
            for index in range(2):
                target = root / f"thread-{index}"
                target.mkdir()
                item_metadata, item_progress, _ = self._write_evidence(
                    target
                )
                self._add_empty_locations(item_metadata)
                targets.append((item_metadata, item_progress))

            def validate(item: tuple[Path, Path]) -> bool:
                result = verifier.validate_build_evidence(
                    item[0],
                    item[1],
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
                return bool(result["network_vertices_cached"])

            with contextlib.redirect_stderr(io.StringIO()):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    self.assertEqual(
                        list(executor.map(validate, targets)),
                        [True, True],
                    )
            assert_restored()

        with self.assertRaisesRegex(RuntimeError, "body sentinel"):
            with verifier._patched_v7_empty_location_contract():
                raise RuntimeError("body sentinel")
        assert_restored()

    def test_copied_v8_v7_v6_v3_v2_cli_chain_and_v7_file_guards(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "evidence"
            evidence.mkdir()
            metadata, progress, _ = self._write_evidence(evidence)
            self._add_empty_locations(metadata)
            copies = {
                "v8": root / "trusted-v8.py",
                "v7": root / "trusted-v7.py",
                "v6": root / "trusted-v6.py",
                "v3": root / "trusted-v3.py",
                "v2": root / "trusted-v2.py",
            }
            shutil.copyfile(Path(verifier.__file__), copies["v8"])
            shutil.copyfile(Path(v7.__file__), copies["v7"])
            shutil.copyfile(
                ROOT / "tools" / "verify_admin_dependency_cache_bundle_v6.py",
                copies["v6"],
            )
            shutil.copyfile(
                ROOT / "tools" / "verify_admin_dependency_cache_bundle_v3.py",
                copies["v3"],
            )
            shutil.copyfile(
                ROOT / "tools" / "verify_admin_dependency_cache_bundle.py",
                copies["v2"],
            )
            environment = os.environ.copy()
            environment.update(
                {
                    "NOTEAI_V7_BUNDLE_VERIFIER_PATH": str(copies["v7"]),
                    "NOTEAI_V6_BUNDLE_VERIFIER_PATH": str(copies["v6"]),
                    "NOTEAI_V3_BUNDLE_VERIFIER_PATH": str(copies["v3"]),
                    "NOTEAI_BASE_BUNDLE_VERIFIER_PATH": str(copies["v2"]),
                }
            )
            output = root / "summary.json"
            command = [
                sys.executable,
                str(copies["v8"]),
                "verify-build",
                "--metadata",
                str(metadata),
                "--progress",
                str(progress),
                "--dockerfile",
                "prefix",
                "--require-network-cached",
                "--output",
                str(output),
            ]

            def run() -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    command,
                    env=environment,
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )

            result = run()
            self.assertEqual(
                result.returncode,
                0,
                result.stdout + result.stderr,
            )
            summary = json.loads(output.read_text(encoding="utf-8"))
            self.assertIn("v8_rawjson_diagnostic", summary)

            with copies["v7"].open("ab") as handle:
                handle.write(b"\n")
            output.unlink()
            result = run()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "frozen V7 bundle verifier hash drift",
                result.stderr,
            )
            self.assertFalse(output.exists())

            shutil.copyfile(Path(v7.__file__), copies["v7"])
            hardlink = root / "trusted-v7-hardlink.py"
            os.link(copies["v7"], hardlink)
            result = run()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "frozen V7 bundle verifier file contract changed",
                result.stderr,
            )
            hardlink.unlink()

            copies["v7"].unlink()
            copies["v7"].symlink_to(Path(v7.__file__))
            result = run()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "frozen V7 bundle verifier file contract changed",
                result.stderr,
            )


if __name__ == "__main__":
    unittest.main()
