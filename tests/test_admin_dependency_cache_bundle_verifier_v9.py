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

import verify_admin_dependency_cache_bundle_v9 as verifier  # noqa: E402


def _load_v8_fixture_module():
    fixture_path = (
        ROOT / "tests" / "test_admin_dependency_cache_bundle_verifier_v8.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_cache_bundle_v8_tests_v9",
        fixture_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load V8 cache-bundle fixtures")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V8_FIXTURES = _load_v8_fixture_module()
SOURCE_PROJECTION_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "admin_dependency_cache_buildkit_v0.31.2_"
    "vertex_input_omission_projection.json"
)
SOURCE_PROJECTION = json.loads(
    SOURCE_PROJECTION_PATH.read_text(encoding="utf-8")
)


def _diagnostic(stderr: str) -> dict:
    lines = stderr.splitlines()
    if len(lines) != 1:
        raise AssertionError(f"unexpected diagnostic line count: {len(lines)}")
    prefix = "noteai_v9_progress_diagnostic="
    if not lines[0].startswith(prefix):
        raise AssertionError("missing V9 diagnostic prefix")
    return json.loads(lines[0][len(prefix) :])


class AdminDependencyCacheBundleVerifierV9Tests(unittest.TestCase):
    def _fixture(self):
        return V8_FIXTURES.AdminDependencyCacheBundleVerifierV8Tests()

    def _write_evidence(
        self,
        root: Path,
        *,
        dockerfile_kind: str = "prefix",
        cached: bool = True,
        second_cached: bool = True,
    ) -> tuple[Path, Path, list[str]]:
        fixture = self._fixture()
        metadata, progress, digests = fixture._write_evidence(
            root,
            dockerfile_kind=dockerfile_kind,
            cached=cached,
            second_cached=second_cached,
        )
        fixture._add_empty_locations(metadata)
        return metadata, progress, digests

    @staticmethod
    def _read_events(progress: Path) -> list[dict]:
        return [
            json.loads(line)
            for line in progress.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    @staticmethod
    def _write_events(progress: Path, events: list[dict]) -> None:
        progress.write_text(
            "".join(
                json.dumps(
                    event,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
                for event in events
            ),
            encoding="utf-8",
        )

    def _set_inputs(
        self,
        progress: Path,
        *,
        event_index: int,
        value,
        vertex_index: int = 0,
    ) -> None:
        events = self._read_events(progress)
        events[event_index]["vertexes"][vertex_index]["inputs"] = value
        self._write_events(progress, events)

    def test_source_projection_is_hash_bound_and_not_runtime_evidence(
        self,
    ) -> None:
        self.assertEqual(
            hashlib.sha256(SOURCE_PROJECTION_PATH.read_bytes()).hexdigest(),
            "3738f1b5bea4490c063cee7749fe39134b0f63005201496ac74aa1d125efb9fd",
        )
        self.assertEqual(
            SOURCE_PROJECTION["classification"],
            (
                "SOURCE_PROVEN_OMITTED_VERTEX_INPUTS_COMPATIBILITY_"
                "CONTRACT_NOT_V8_RUNTIME_EVIDENCE"
            ),
        )
        for field in (
            "actual_v8_runtime_metadata_retained",
            "actual_v8_runtime_progress_retained",
            "actual_v8_conflicting_digest_retained",
            "actual_v8_previous_input_vector_retained",
            "actual_v8_current_input_vector_retained",
            "runtime_conflicting_digest_reconstructed",
            "runtime_prior_input_vector_reconstructed",
            "runtime_current_input_vector_reconstructed",
            "runtime_input_transition_reconstructed",
        ):
            self.assertFalse(SOURCE_PROJECTION[field], field)
        self.assertEqual(
            SOURCE_PROJECTION["buildkit"]["commit"],
            "e42e1bfd389af7203238cce77b1f7dad447285e9",
        )
        self.assertEqual(
            {
                item["path"]: item["git_blob_sha1"]
                for item in SOURCE_PROJECTION["buildkit"]["sources"]
            },
            {
                "solver/jobs.go": "297222b0535bd3c3eb294ef0dcf8f069c463620f",
                "solver/progress.go": "65d1802341d344814db30734206608371cee8f69",
                "util/progress/controller/controller.go": (
                    "3d9693d44cd754d3a1d7850600ff3df58d2e4fdc"
                ),
                "util/progress/progress.go": (
                    "2c2d517dba0a53424f8d91c93f0238ea78295882"
                ),
                "api/services/control/control.proto": (
                    "0c5cdb17e81b0831ddae9b43f394e588f602dece"
                ),
                "client/graph.go": "1000cd78f6202100893dab87300c4ecf22629449",
                "client/status.go": "92044e72a7c6e8e88756120a63490801b42beb8a",
                "control/control.go": "de0f4c931f57551a16cabf910ed7e089a62591ab",
            },
        )
        contract = SOURCE_PROJECTION["v9_contract"]
        self.assertTrue(
            contract["missing_inputs_member_allowed_as_nonbinding"]
        )
        self.assertTrue(
            contract["first_explicit_nonempty_ordered_vector_binds"]
        )
        self.assertTrue(
            contract["bound_vector_requires_exact_ordered_match"]
        )
        self.assertFalse(contract["explicit_empty_inputs_member_allowed"])
        self.assertFalse(contract["omission_only_proves_zero_inputs_or_leaf"])
        self.assertFalse(
            contract["union_append_last_write_or_ignore_recovery_allowed"]
        )
        self.assertFalse(
            contract["v8_runtime_input_transition_reconstructed"]
        )

    def test_mixed_presence_passes_in_both_orders_and_preserves_evidence(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for dockerfile_kind in ("prefix", "full"):
                for explicit_index in (0, 2):
                    with self.subTest(
                        dockerfile_kind=dockerfile_kind,
                        explicit_index=explicit_index,
                    ):
                        target = root / f"{dockerfile_kind}-{explicit_index}"
                        target.mkdir()
                        metadata, progress, digests = self._write_evidence(
                            target,
                            dockerfile_kind=dockerfile_kind,
                        )
                        self._set_inputs(
                            progress,
                            event_index=explicit_index,
                            value=[digests[1]],
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
                        self.assertNotIn("v8_rawjson_diagnostic", summary)
                        diagnostic = summary["v9_rawjson_diagnostic"]
                        self.assertEqual(
                            diagnostic["schema_version"],
                            "noteai.admin-dependency-cache-v9-diagnostic.v1",
                        )
                        self.assertEqual(diagnostic["verdict"], "pass")
                        self.assertEqual(
                            diagnostic[
                                "input_mixed_presence_vertex_digest_count"
                            ],
                            1,
                        )
                        self.assertEqual(
                            diagnostic["input_bound_vertex_digest_count"],
                            1,
                        )
                        self.assertGreater(
                            diagnostic["input_omitted_update_count"],
                            0,
                        )
                        self.assertEqual(
                            _diagnostic(stderr.getvalue()),
                            diagnostic,
                        )
                        self.assertEqual(metadata.read_bytes(), original_metadata)
                        self.assertEqual(progress.read_bytes(), original_progress)

                        with contextlib.redirect_stderr(
                            io.StringIO()
                        ), self.assertRaises(
                            verifier._v8.V8BundleError
                        ) as raised:
                            verifier._v8.validate_build_evidence(
                                metadata,
                                progress,
                                dockerfile_kind=dockerfile_kind,
                                require_network_vertices_cached=True,
                            )
                        self.assertEqual(
                            raised.exception.failure_code,
                            "RAWJSON_VERTEX_INPUT_CONFLICT",
                        )

    def test_omission_only_remains_unbound_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            metadata, progress, _ = self._write_evidence(Path(temporary))
            with contextlib.redirect_stderr(io.StringIO()):
                summary = verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            diagnostic = summary["v9_rawjson_diagnostic"]
            self.assertEqual(
                diagnostic["input_bound_vertex_digest_count"],
                0,
            )
            self.assertEqual(
                diagnostic["input_omission_only_vertex_digest_count"],
                diagnostic["unique_vertex_digest_count"],
            )
            self.assertEqual(
                diagnostic["input_mixed_presence_vertex_digest_count"],
                0,
            )
            self.assertGreater(
                diagnostic["input_omitted_update_count"],
                0,
            )

    def test_stable_nonempty_vectors_duplicates_and_limit_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for label, vector_builder in (
                ("single", lambda values: [values[1]]),
                ("duplicate", lambda values: [values[1], values[1]]),
                ("limit", lambda values: [values[1]] * 4096),
            ):
                with self.subTest(label=label):
                    target = root / label
                    target.mkdir()
                    metadata, progress, digests = self._write_evidence(target)
                    vector = vector_builder(digests)
                    events = self._read_events(progress)
                    events[0]["vertexes"][0]["inputs"] = vector
                    events[2]["vertexes"][0]["inputs"] = vector
                    self._write_events(progress, events)
                    with contextlib.redirect_stderr(io.StringIO()):
                        summary = verifier.validate_build_evidence(
                            metadata,
                            progress,
                            dockerfile_kind="prefix",
                            require_network_vertices_cached=True,
                        )
                    diagnostic = summary["v9_rawjson_diagnostic"]
                    self.assertEqual(
                        diagnostic["input_explicit_nonempty_update_count"],
                        2,
                    )
                    self.assertEqual(
                        diagnostic[
                            "input_mixed_presence_vertex_digest_count"
                        ],
                        1,
                    )

    def test_explicit_invalid_shapes_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = (
                ("empty", lambda values: []),
                ("null", lambda values: None),
                ("object", lambda values: {}),
                ("string", lambda values: "inputs"),
                ("number", lambda values: 1),
                ("boolean", lambda values: True),
                ("over-limit", lambda values: [values[1]] * 4097),
            )
            for label, value_builder in cases:
                with self.subTest(label=label):
                    target = root / label
                    target.mkdir()
                    metadata, progress, digests = self._write_evidence(target)
                    self._set_inputs(
                        progress,
                        event_index=0,
                        value=value_builder(digests),
                    )
                    stderr = io.StringIO()
                    with contextlib.redirect_stderr(
                        stderr
                    ), self.assertRaises(verifier.V9BundleError) as raised:
                        verifier.validate_build_evidence(
                            metadata,
                            progress,
                            dockerfile_kind="prefix",
                            require_network_vertices_cached=True,
                        )
                    self.assertEqual(
                        raised.exception.failure_code,
                        "RAWJSON_VERTEX_INPUT_INVALID",
                    )
                    self.assertEqual(
                        _diagnostic(stderr.getvalue())["failure_code"],
                        "RAWJSON_VERTEX_INPUT_INVALID",
                    )

            target = root / "bad-digest"
            target.mkdir()
            metadata, progress, _ = self._write_evidence(target)
            self._set_inputs(
                progress,
                event_index=0,
                value=["sha256:not-canonical"],
            )
            with contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(verifier.V9BundleError) as raised:
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(
                raised.exception.failure_code,
                "RAWJSON_DIGEST_INVALID",
            )

    def test_vector_drift_add_remove_and_reorder_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = (
                ("value", lambda d: ([d[1]], [d[2]])),
                ("add", lambda d: ([d[1]], [d[1], d[2]])),
                ("remove", lambda d: ([d[1], d[2]], [d[1]])),
                ("reorder", lambda d: ([d[1], d[2]], [d[2], d[1]])),
                (
                    "duplicate-count",
                    lambda d: ([d[1], d[1]], [d[1]]),
                ),
            )
            for label, vectors in cases:
                with self.subTest(label=label):
                    target = root / label
                    target.mkdir()
                    metadata, progress, digests = self._write_evidence(target)
                    first, second = vectors(digests)
                    events = self._read_events(progress)
                    events[0]["vertexes"][0]["inputs"] = first
                    events[2]["vertexes"][0]["inputs"] = second
                    self._write_events(progress, events)
                    stderr = io.StringIO()
                    with contextlib.redirect_stderr(
                        stderr
                    ), self.assertRaises(verifier.V9BundleError) as raised:
                        verifier.validate_build_evidence(
                            metadata,
                            progress,
                            dockerfile_kind="prefix",
                            require_network_vertices_cached=True,
                        )
                    self.assertEqual(
                        raised.exception.failure_code,
                        "RAWJSON_VERTEX_INPUT_CONFLICT",
                    )
                    emitted = _diagnostic(stderr.getvalue())
                    self.assertEqual(
                        emitted["failure_code"],
                        "RAWJSON_VERTEX_INPUT_CONFLICT",
                    )
                    for digest in digests:
                        self.assertNotIn(digest, stderr.getvalue())

    def test_frozen_progress_group_contract_is_not_broadened(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            metadata, progress, _ = self._write_evidence(Path(temporary))
            events = self._read_events(progress)
            events[2]["vertexes"][0]["progressGroup"] = {"id": "changed"}
            self._write_events(progress, events)
            with contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(verifier.V9BundleError) as raised:
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(
                raised.exception.failure_code,
                "RAWJSON_VERTEX_PROGRESS_GROUP_CONFLICT",
            )

    def test_dispatch_restores_after_success_failure_body_and_threads(
        self,
    ) -> None:
        frozen = [
            (target, name, getattr(target, name))
            for target, name in (
                (verifier._v8, "_initial_diagnostic"),
                (verifier._v8, "_emit_diagnostic"),
                (verifier._v8, "_validate_build_evidence"),
                (verifier._v7, "_strict_progress"),
            )
        ]

        def assert_restored() -> None:
            for target, name, expected in frozen:
                self.assertIs(getattr(target, name), expected)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            success = root / "success"
            success.mkdir()
            metadata, progress, digests = self._write_evidence(success)
            self._set_inputs(
                progress,
                event_index=0,
                value=[digests[1]],
            )
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
            self._set_inputs(progress, event_index=0, value=[])
            with contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(verifier.V9BundleError):
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
                targets.append(self._write_evidence(target)[:2])

            def validate_v9(item: tuple[Path, Path]) -> bool:
                result = verifier.validate_build_evidence(
                    item[0],
                    item[1],
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
                return bool(result["network_vertices_cached"])

            def validate_v8(item: tuple[Path, Path]) -> bool:
                result = verifier._v8.validate_build_evidence(
                    item[0],
                    item[1],
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
                return bool(result["network_vertices_cached"])

            with contextlib.redirect_stderr(io.StringIO()):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = (
                        executor.submit(validate_v9, targets[0]),
                        executor.submit(validate_v8, targets[1]),
                    )
                    self.assertEqual(
                        [future.result() for future in futures],
                        [True, True],
                    )
            assert_restored()

        with self.assertRaisesRegex(RuntimeError, "body sentinel"):
            with verifier._patched_v8_input_omission_contract():
                raise RuntimeError("body sentinel")
        assert_restored()

    def test_preexisting_dispatch_tamper_fails_closed(self) -> None:
        cases = (
            (verifier._v7, "_strict_progress"),
            (verifier._v8, "_FROZEN_V7_VALIDATE_BUILD_EVIDENCE"),
            (verifier._v7, "_FROZEN_VALIDATE_BUILD_EVIDENCE"),
            (verifier._v6, "validate_core"),
            (verifier._v6, "_frozen_v3_validate_build_evidence"),
            (verifier._v6, "_patched_base_validator"),
            (verifier._v6._v3, "_v2_validate_build_evidence"),
            (verifier._v6._v3._base, "strict_json_file"),
            (verifier._v6._v3._base, "validate_core"),
        )
        for module, name in cases:
            with self.subTest(module=module.__name__, name=name):
                frozen = getattr(module, name)
                setattr(module, name, lambda *args, **kwargs: {"forged": True})
                try:
                    with self.assertRaises(verifier.V9BundleError) as raised:
                        with verifier._patched_v8_input_omission_contract():
                            pass
                    self.assertEqual(
                        raised.exception.failure_code,
                        "FROZEN_V8_DISPATCH_CHANGED",
                    )
                finally:
                    setattr(module, name, frozen)

    def test_forged_v8_summary_dispatch_is_rejected_before_call(self) -> None:
        forged_calls: list[bool] = []

        def forged(*args, **kwargs):
            forged_calls.append(True)
            return {"forged": True}

        frozen = verifier._v8._FROZEN_V7_VALIDATE_BUILD_EVIDENCE
        verifier._v8._FROZEN_V7_VALIDATE_BUILD_EVIDENCE = forged
        try:
            with self.assertRaises(verifier.V9BundleError) as raised:
                verifier.validate_build_evidence(
                    Path("unused-metadata.json"),
                    Path("unused-progress.rawjson"),
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(
                raised.exception.failure_code,
                "FROZEN_V8_DISPATCH_CHANGED",
            )
            self.assertEqual(forged_calls, [])
        finally:
            verifier._v8._FROZEN_V7_VALIDATE_BUILD_EVIDENCE = frozen

    def test_forged_v6_to_v3_summary_is_rejected_before_call(self) -> None:
        forged_calls: list[bool] = []

        def forged(*args, **kwargs):
            forged_calls.append(True)
            return {"forged_v3_summary": True}

        frozen = verifier._v6._frozen_v3_validate_build_evidence
        verifier._v6._frozen_v3_validate_build_evidence = forged
        try:
            with self.assertRaises(verifier.V9BundleError) as raised:
                verifier.validate_build_evidence(
                    Path("unused-metadata.json"),
                    Path("unused-progress.rawjson"),
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(
                raised.exception.failure_code,
                "FROZEN_V8_DISPATCH_CHANGED",
            )
            self.assertEqual(forged_calls, [])
        finally:
            verifier._v6._frozen_v3_validate_build_evidence = frozen

    def test_copied_cli_chain_and_v8_file_guards(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "evidence"
            evidence.mkdir()
            metadata, progress, _ = self._write_evidence(evidence)
            copies = {
                "v9": root / "trusted-v9.py",
                "v8": root / "trusted-v8.py",
                "v7": root / "trusted-v7.py",
                "v6": root / "trusted-v6.py",
                "v3": root / "trusted-v3.py",
                "v2": root / "trusted-v2.py",
            }
            shutil.copyfile(Path(verifier.__file__), copies["v9"])
            shutil.copyfile(Path(verifier._v8.__file__), copies["v8"])
            shutil.copyfile(Path(verifier._v7.__file__), copies["v7"])
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
                    "NOTEAI_V8_BUNDLE_VERIFIER_PATH": str(copies["v8"]),
                    "NOTEAI_V7_BUNDLE_VERIFIER_PATH": str(copies["v7"]),
                    "NOTEAI_V6_BUNDLE_VERIFIER_PATH": str(copies["v6"]),
                    "NOTEAI_V3_BUNDLE_VERIFIER_PATH": str(copies["v3"]),
                    "NOTEAI_BASE_BUNDLE_VERIFIER_PATH": str(copies["v2"]),
                }
            )
            output = root / "summary.json"
            command = [
                sys.executable,
                str(copies["v9"]),
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
            self.assertIn("v9_rawjson_diagnostic", summary)

            with copies["v8"].open("ab") as handle:
                handle.write(b"\n")
            output.unlink()
            result = run()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "frozen V8 bundle verifier hash drift",
                result.stderr,
            )
            self.assertFalse(output.exists())

            shutil.copyfile(Path(verifier._v8.__file__), copies["v8"])
            hardlink = root / "trusted-v8-hardlink.py"
            os.link(copies["v8"], hardlink)
            result = run()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "frozen V8 bundle verifier file contract changed",
                result.stderr,
            )
            hardlink.unlink()

            copies["v8"].unlink()
            copies["v8"].symlink_to(Path(verifier._v8.__file__))
            result = run()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "frozen V8 bundle verifier file contract changed",
                result.stderr,
            )


if __name__ == "__main__":
    unittest.main()
