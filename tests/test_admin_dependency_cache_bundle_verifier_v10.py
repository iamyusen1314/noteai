from __future__ import annotations

import base64
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
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_bundle_v10 as verifier  # noqa: E402


def _load_v9_fixture_module():
    fixture_path = (
        ROOT / "tests" / "test_admin_dependency_cache_bundle_verifier_v9.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_cache_bundle_v9_tests_v10",
        fixture_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load V9 cache-bundle fixtures")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V9_FIXTURES = _load_v9_fixture_module()
SOURCE_PROJECTION_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "admin_dependency_cache_buildkit_v0.31.2_"
    "cache_observer_projection.json"
)
SOURCE_PROJECTION = json.loads(
    SOURCE_PROJECTION_PATH.read_text(encoding="utf-8")
)


def _diagnostic(stderr: str) -> dict:
    prefix = "noteai_v10_progress_diagnostic="
    matches = [
        line[len(prefix) :]
        for line in stderr.splitlines()
        if line.startswith(prefix)
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"unexpected V10 diagnostic line count: {len(matches)}"
        )
    return json.loads(matches[0])


class AdminDependencyCacheBundleVerifierV10Tests(unittest.TestCase):
    def _fixture(self):
        return V9_FIXTURES.AdminDependencyCacheBundleVerifierV9Tests()

    @staticmethod
    def _read_metadata(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_metadata(path: Path, payload: dict) -> None:
        path.write_text(
            json.dumps(payload, separators=(",", ":")),
            encoding="utf-8",
        )

    @staticmethod
    def _read_events(path: Path) -> list[dict]:
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    @staticmethod
    def _write_events(path: Path, events: list[dict]) -> None:
        path.write_text(
            "".join(
                json.dumps(event, separators=(",", ":")) + "\n"
                for event in events
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _location(line: int) -> dict:
        return {
            "locations": [
                {
                    "ranges": [
                        {
                            "start": {"line": line},
                            "end": {"line": line},
                        }
                    ]
                }
            ]
        }

    @staticmethod
    def _set_all_role_intervals(
        events: list[dict],
        *,
        cached: bool,
    ) -> None:
        for event in events:
            for vertex in event.get("vertexes", []):
                if "started" not in vertex:
                    vertex.pop("cached", None)
                elif cached:
                    vertex["cached"] = True
                else:
                    vertex.pop("cached", None)

    @staticmethod
    def _derived_dockerfile() -> bytes:
        lines = (ROOT / "Dockerfile").read_bytes().splitlines(keepends=True)
        return b"".join(lines[:80]) + verifier.OBSERVER_SUFFIX

    def _write_observer_evidence(
        self,
        root: Path,
    ) -> tuple[Path, Path, list[str], str]:
        metadata, progress, digests = self._fixture()._write_evidence(root)
        payload = self._read_metadata(metadata)
        provenance = payload["buildx.build.provenance"]
        build_config = provenance["buildConfig"]
        source = provenance["metadata"][
            "https://mobyproject.org/buildkit@v1#metadata"
        ]["source"]
        observer_digest = "sha256:" + ("4" * 64)
        build_config["llbDefinition"].append(
            {
                "id": "step6",
                "inputs": ["step5:0"],
                "op": {
                    "Op": {"exec": {"network": 2}},
                    "platform": {"Architecture": "amd64", "OS": "linux"},
                },
            }
        )
        build_config["digestMapping"][observer_digest] = "step6"
        source["locations"]["step6"] = self._location(83)
        source["infos"][0]["data"] = base64.b64encode(
            self._derived_dockerfile()
        ).decode("ascii")
        provenance["invocation"]["parameters"]["args"][
            "target"
        ] = verifier.OBSERVER_TARGET
        self._write_metadata(metadata, payload)

        events = self._read_events(progress)
        self._set_all_role_intervals(events, cached=True)
        observer_updates = (
            {
                "digest": observer_digest,
                "name": "RUN observer",
                "inputs": [digests[2]],
            },
            {
                "digest": observer_digest,
                "name": "RUN observer",
                "started": "2026-07-31T00:00:06Z",
            },
            {
                "digest": observer_digest,
                "name": "RUN observer",
                "started": "2026-07-31T00:00:06Z",
                "completed": "2026-07-31T00:00:19Z",
            },
        )
        for event, update in zip(events[:3], observer_updates):
            event["vertexes"].append(update)
        events.append(
            {
                "logs": [
                    {
                        "vertex": observer_digest,
                        "stream": 1,
                        "data": base64.b64encode(
                            verifier.OBSERVER_MARKER[:11]
                        ).decode("ascii"),
                        "timestamp": "2026-07-31T00:00:10Z",
                    }
                ]
            }
        )
        events.append(
            {
                "logs": [
                    {
                        "vertex": observer_digest,
                        "stream": 1,
                        "data": base64.b64encode(
                            verifier.OBSERVER_MARKER[11:]
                        ).decode("ascii"),
                        "timestamp": "2026-07-31T00:00:11Z",
                    }
                ]
            }
        )
        self._write_events(progress, events)
        return metadata, progress, digests, observer_digest

    def _write_full_evidence(
        self,
        root: Path,
    ) -> tuple[Path, Path, list[str], str]:
        metadata, progress, digests = self._fixture()._write_evidence(
            root,
            dockerfile_kind="full",
        )
        payload = self._read_metadata(metadata)
        provenance = payload["buildx.build.provenance"]
        build_config = provenance["buildConfig"]
        source = provenance["metadata"][
            "https://mobyproject.org/buildkit@v1#metadata"
        ]["source"]
        witness_digest = "sha256:" + ("5" * 64)
        build_config["llbDefinition"].append(
            {
                "id": "step6",
                "inputs": ["step5:0", "step2:0"],
                "op": {
                    "Op": {"file": {}},
                    "platform": {"Architecture": "amd64", "OS": "linux"},
                },
            }
        )
        build_config["llbDefinition"].append(
            {
                "id": "step7",
                "inputs": ["step6:0"],
                "op": {
                    "Op": {"exec": {}},
                    "platform": {"Architecture": "amd64", "OS": "linux"},
                },
            }
        )
        build_config["digestMapping"][witness_digest] = "step7"
        source["locations"]["step6"] = {}
        source["locations"]["step7"] = self._location(93)
        self._write_metadata(metadata, payload)

        events = self._read_events(progress)
        self._set_all_role_intervals(events, cached=True)
        witness_updates = (
            {
                "digest": witness_digest,
                "name": "RUN mkdir -p data",
                "inputs": [digests[2]],
            },
            {
                "digest": witness_digest,
                "name": "RUN mkdir -p data",
                "started": "2026-07-31T00:00:07Z",
            },
            {
                "digest": witness_digest,
                "name": "RUN mkdir -p data",
                "started": "2026-07-31T00:00:07Z",
                "completed": "2026-07-31T00:00:18Z",
            },
        )
        for event, update in zip(events[:3], witness_updates):
            event["vertexes"].append(update)
        self._write_events(progress, events)
        return metadata, progress, digests, witness_digest

    def test_source_projection_and_observer_bytes_are_hash_bound(self) -> None:
        self.assertEqual(
            hashlib.sha256(SOURCE_PROJECTION_PATH.read_bytes()).hexdigest(),
            "f743084bb704d0fd6858510d81ebe6479ac0c6baae982b353715c328bc6fcd27",
        )
        self.assertEqual(
            SOURCE_PROJECTION["classification"],
            (
                "SOURCE_PROVEN_CACHE_OBSERVER_CHILD_CONTRACT_"
                "NOT_V9_RUNTIME_EVIDENCE"
            ),
        )
        self.assertFalse(
            SOURCE_PROJECTION["actual_v9_runtime_metadata_retained"]
        )
        self.assertFalse(
            SOURCE_PROJECTION["runtime_v9_cache_miss_cause_reconstructed"]
        )
        self.assertEqual(
            SOURCE_PROJECTION["historical_v9_root_cause_status"],
            "UNKNOWN_NOT_RETAINED",
        )
        self.assertEqual(
            hashlib.sha256(verifier.OBSERVER_SUFFIX).hexdigest(),
            verifier.OBSERVER_SUFFIX_SHA256,
        )
        derived = self._derived_dockerfile()
        self.assertEqual(len(derived), verifier.OBSERVER_DOCKERFILE_BYTES)
        self.assertEqual(
            hashlib.sha256(derived).hexdigest(),
            verifier.OBSERVER_DOCKERFILE_SHA256,
        )

    def test_observer_prefix_passes_and_preserves_original_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            metadata, progress, _digests, _observer = (
                self._write_observer_evidence(Path(temporary))
            )
            original_metadata = metadata.read_bytes()
            original_progress = progress.read_bytes()
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                summary = verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(metadata.read_bytes(), original_metadata)
            self.assertEqual(progress.read_bytes(), original_progress)
            self.assertEqual(
                summary["metadata_sha256"],
                hashlib.sha256(original_metadata).hexdigest(),
            )
            self.assertEqual(
                summary["dockerfile_sha256"],
                verifier.OBSERVER_DOCKERFILE_SHA256,
            )
            self.assertNotIn("v9_rawjson_diagnostic", summary)
            diagnostic = summary["v10_rawjson_diagnostic"]
            self.assertEqual(diagnostic["projection_kind"], "observer-prefix")
            self.assertEqual(diagnostic["verdict"], "pass")
            self.assertTrue(diagnostic["observer_binding_completed"])
            self.assertEqual(
                diagnostic["observer"]["network_mode"],
                "NONE",
            )
            self.assertEqual(
                diagnostic["observer"]["marker_occurrence_count"],
                1,
            )
            self.assertTrue(
                all(
                    item["cached_interval_count"] == item["interval_count"]
                    for item in diagnostic["role_intervals"]
                )
            )
            self.assertEqual(_diagnostic(stderr.getvalue()), diagnostic)

    def test_producer_prefix_remains_exact_and_uncached(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            metadata, progress, _ = self._fixture()._write_evidence(
                Path(temporary),
                cached=False,
                second_cached=False,
            )
            events = self._read_events(progress)
            self._set_all_role_intervals(events, cached=False)
            self._write_events(progress, events)
            with contextlib.redirect_stderr(io.StringIO()):
                summary = verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=False,
                )
            diagnostic = summary["v10_rawjson_diagnostic"]
            self.assertEqual(diagnostic["projection_kind"], "producer-prefix")
            self.assertTrue(
                all(
                    item["noncached_interval_count"] == item["interval_count"]
                    for item in diagnostic["role_intervals"]
                )
            )

    def test_projection_target_and_cache_mode_matrix_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            producer = root / "producer"
            producer.mkdir()
            metadata, progress, _ = self._fixture()._write_evidence(producer)
            events = self._read_events(progress)
            self._set_all_role_intervals(events, cached=True)
            self._write_events(progress, events)
            with contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(verifier.V10BundleError) as raised:
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(
                raised.exception.failure_code,
                "PRODUCER_CACHE_MODE_INVALID",
            )

            observer = root / "observer"
            observer.mkdir()
            metadata, progress, _digests, _observer_digest = (
                self._write_observer_evidence(observer)
            )
            with contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(verifier.V10BundleError) as raised:
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=False,
                )
            self.assertEqual(
                raised.exception.failure_code,
                "OBSERVER_CACHE_MODE_INVALID",
            )

            full = root / "full"
            full.mkdir()
            metadata, progress, _digests, _witness = (
                self._write_full_evidence(full)
            )
            with contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(verifier.V10BundleError) as raised:
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="full",
                    require_network_vertices_cached=False,
                )
            self.assertEqual(
                raised.exception.failure_code,
                "FULL_REPLAY_CACHE_MODE_INVALID",
            )

    def test_full_replay_requires_uncached_post_pip_witness(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            metadata, progress, _digests, witness = self._write_full_evidence(
                Path(temporary)
            )
            with contextlib.redirect_stderr(io.StringIO()):
                summary = verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="full",
                    require_network_vertices_cached=True,
                )
            diagnostic = summary["v10_rawjson_diagnostic"]
            self.assertEqual(
                diagnostic["projection_kind"],
                "full-runtime-common",
            )
            self.assertTrue(
                diagnostic["full_post_pip_witness"]["runtime_pip_ancestor"]
            )
            self.assertFalse(
                diagnostic["full_post_pip_witness"]["runtime_pip_terminal"]
            )
            self.assertGreater(
                diagnostic["full_post_pip_witness"]["ancestry_path_length"],
                1,
            )

            events = self._read_events(progress)
            for event in events:
                for vertex in event.get("vertexes", []):
                    if vertex.get("digest") == witness and "started" in vertex:
                        vertex["cached"] = True
            self._write_events(progress, events)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), self.assertRaises(
                verifier.V10BundleError
            ) as raised:
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="full",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(
                raised.exception.failure_code,
                "PRODUCER_NETWORK_VERTEX_CACHED",
            )

    def test_observer_and_cache_predicates_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = (
                (
                    "network-host",
                    lambda payload, events, digests, observer: payload[
                        "buildx.build.provenance"
                    ]["buildConfig"]["llbDefinition"][6]["op"]["Op"][
                        "exec"
                    ].__setitem__("network", 1),
                    "OBSERVER_NETWORK_OR_SECRET_INVALID",
                ),
                (
                    "wrong-parent",
                    lambda payload, events, digests, observer: payload[
                        "buildx.build.provenance"
                    ]["buildConfig"]["llbDefinition"][6].__setitem__(
                        "inputs", ["step4:0"]
                    ),
                    "OBSERVER_PROVENANCE_BINDING_INVALID",
                ),
                (
                    "observer-cached",
                    lambda payload, events, digests, observer: [
                        vertex.__setitem__("cached", True)
                        for event in events
                        for vertex in event.get("vertexes", [])
                        if vertex.get("digest") == observer
                        and "started" in vertex
                    ],
                    "PRODUCER_NETWORK_VERTEX_CACHED",
                ),
                (
                    "pip-not-cached",
                    lambda payload, events, digests, observer: [
                        vertex.pop("cached", None)
                        for event in events
                        for vertex in event.get("vertexes", [])
                        if vertex.get("digest") == digests[2]
                        and "started" in vertex
                    ],
                    "NETWORK_VERTEX_NOT_CACHED",
                ),
            )
            for label, mutate, expected in cases:
                with self.subTest(label=label):
                    target = root / label
                    target.mkdir()
                    metadata, progress, digests, observer = (
                        self._write_observer_evidence(target)
                    )
                    payload = self._read_metadata(metadata)
                    events = self._read_events(progress)
                    mutate(payload, events, digests, observer)
                    self._write_metadata(metadata, payload)
                    self._write_events(progress, events)
                    stderr = io.StringIO()
                    with contextlib.redirect_stderr(
                        stderr
                    ), self.assertRaises(verifier.V10BundleError) as raised:
                        verifier.validate_build_evidence(
                            metadata,
                            progress,
                            dockerfile_kind="prefix",
                            require_network_vertices_cached=True,
                        )
                    self.assertEqual(raised.exception.failure_code, expected)
                    self.assertEqual(
                        _diagnostic(stderr.getvalue())["failure_code"],
                        expected,
                    )

    def test_marker_and_progress_parent_are_digest_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for label in ("missing-marker", "wrong-digest", "wrong-input"):
                with self.subTest(label=label):
                    target = root / label
                    target.mkdir()
                    metadata, progress, digests, observer = (
                        self._write_observer_evidence(target)
                    )
                    events = self._read_events(progress)
                    if label == "missing-marker":
                        events = [event for event in events if "logs" not in event]
                    elif label == "wrong-digest":
                        for event in events:
                            for log in event.get("logs", []):
                                log["vertex"] = digests[0]
                    else:
                        for event in events:
                            for vertex in event.get("vertexes", []):
                                if vertex.get("digest") == observer and "inputs" in vertex:
                                    vertex["inputs"] = [digests[1]]
                    self._write_events(progress, events)
                    expected = (
                        "OBSERVER_PROGRESS_INPUT_INVALID"
                        if label == "wrong-input"
                        else (
                            "OBSERVER_MARKER_MISBOUND"
                            if label == "wrong-digest"
                            else "OBSERVER_MARKER_INVALID"
                        )
                    )
                    with contextlib.redirect_stderr(
                        io.StringIO()
                    ), self.assertRaises(verifier.V10BundleError) as raised:
                        verifier.validate_build_evidence(
                            metadata,
                            progress,
                            dockerfile_kind="prefix",
                            require_network_vertices_cached=True,
                        )
                    self.assertEqual(raised.exception.failure_code, expected)

    def test_full_witness_parent_and_presence_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for label in ("wrong-parent", "missing-progress"):
                with self.subTest(label=label):
                    target = root / label
                    target.mkdir()
                    metadata, progress, _digests, witness = (
                        self._write_full_evidence(target)
                    )
                    if label == "wrong-parent":
                        payload = self._read_metadata(metadata)
                        payload["buildx.build.provenance"]["buildConfig"][
                            "llbDefinition"
                        ][-1]["inputs"] = ["step4:0"]
                        self._write_metadata(metadata, payload)
                    else:
                        events = self._read_events(progress)
                        for event in events:
                            event["vertexes"] = [
                                vertex
                                for vertex in event.get("vertexes", [])
                                if vertex.get("digest") != witness
                            ]
                        self._write_events(progress, events)
                    expected = (
                        "FULL_WITNESS_NOT_POST_PIP"
                        if label == "wrong-parent"
                        else "FULL_WITNESS_PROGRESS_VERTEX_MISSING"
                    )
                    with contextlib.redirect_stderr(
                        io.StringIO()
                    ), self.assertRaises(verifier.V10BundleError) as raised:
                        verifier.validate_build_evidence(
                            metadata,
                            progress,
                            dockerfile_kind="full",
                            require_network_vertices_cached=True,
                        )
                    self.assertEqual(raised.exception.failure_code, expected)

    def test_dispatch_restores_and_preexisting_tamper_is_rejected(self) -> None:
        frozen = verifier._v9._validate_build_evidence
        with tempfile.TemporaryDirectory() as temporary:
            metadata, progress, _digests, _observer = (
                self._write_observer_evidence(Path(temporary))
            )
            with contextlib.redirect_stderr(io.StringIO()):
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertIs(verifier._v9._validate_build_evidence, frozen)
            with self.assertRaisesRegex(RuntimeError, "body sentinel"):
                with verifier._patched_v9_observer_contract():
                    raise RuntimeError("body sentinel")
            self.assertIs(verifier._v9._validate_build_evidence, frozen)

        target = verifier._v9._v7
        original = target._strict_progress
        target._strict_progress = lambda *args, **kwargs: ({}, [], {}, set(), [])
        try:
            with self.assertRaises(verifier.V10BundleError) as raised:
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
        finally:
            target._strict_progress = original

    def test_failure_diagnostic_is_unique_and_never_reports_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, progress, _ = self._fixture()._write_evidence(
                root,
                cached=False,
                second_cached=False,
            )
            events = self._read_events(progress)
            self._set_all_role_intervals(events, cached=False)
            self._write_events(progress, events)
            frozen_delegate = verifier._delegate_v9

            def mutate_after_delegate(*args, **kwargs):
                summary = frozen_delegate(*args, **kwargs)
                metadata.write_bytes(metadata.read_bytes() + b" ")
                return summary

            stderr = io.StringIO()
            with mock.patch.object(
                verifier,
                "_delegate_v9",
                side_effect=mutate_after_delegate,
            ), contextlib.redirect_stderr(stderr), self.assertRaises(
                verifier.V10BundleError
            ) as raised:
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=False,
                )
            self.assertEqual(
                raised.exception.failure_code,
                "ORIGINAL_EVIDENCE_CHANGED",
            )
            diagnostic = _diagnostic(stderr.getvalue())
            self.assertEqual(
                diagnostic["failure_code"],
                "ORIGINAL_EVIDENCE_CHANGED",
            )
            self.assertEqual(diagnostic["verdict"], "fail")

    def test_base_parser_failures_emit_one_bounded_v10_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            malformed = root / "malformed"
            malformed.mkdir()
            metadata, progress, _digests, _observer = (
                self._write_observer_evidence(malformed)
            )
            metadata.write_bytes(b"{")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), self.assertRaises(
                verifier.V10BundleError
            ) as raised:
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(
                raised.exception.failure_code,
                "V10_EVIDENCE_INVALID",
            )
            diagnostic = _diagnostic(stderr.getvalue())
            self.assertEqual(
                diagnostic["failure_code"],
                "V10_EVIDENCE_INVALID",
            )
            self.assertEqual(diagnostic["verdict"], "fail")

            bad_digest = root / "bad-digest"
            bad_digest.mkdir()
            metadata, progress, _digests, _observer = (
                self._write_observer_evidence(bad_digest)
            )
            events = self._read_events(progress)
            events[0]["vertexes"][0]["digest"] = "not-a-digest"
            self._write_events(progress, events)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), self.assertRaises(
                verifier.V10BundleError
            ) as raised:
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
            diagnostic = _diagnostic(stderr.getvalue())
            self.assertEqual(
                diagnostic["failure_code"],
                "RAWJSON_DIGEST_INVALID",
            )
            self.assertEqual(diagnostic["verdict"], "fail")

    def test_frozen_v9_rejection_retains_its_failure_origin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            metadata, progress, _digests, _observer = (
                self._write_observer_evidence(Path(temporary))
            )
            payload = self._read_metadata(metadata)
            payload["buildx.build.provenance"]["invocation"]["environment"][
                "dockerfileVersion"
            ] = "9.9.9"
            self._write_metadata(metadata, payload)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), self.assertRaises(
                verifier.V10BundleError
            ) as raised:
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(
                raised.exception.failure_code,
                "FROZEN_V9_EVIDENCE_INVALID",
            )
            diagnostic = _diagnostic(stderr.getvalue())
            self.assertEqual(
                diagnostic["v10_root_cause_status"],
                "FROZEN_V9_REJECTION",
            )
            self.assertEqual(
                diagnostic["failure_code"],
                "FROZEN_V9_EVIDENCE_INVALID",
            )
            self.assertEqual(diagnostic["verdict"], "fail")

    def test_unexpected_parser_failure_emits_one_bounded_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            metadata, progress, _digests, _observer = (
                self._write_observer_evidence(Path(temporary))
            )
            stderr = io.StringIO()
            with mock.patch.object(
                verifier,
                "_metadata_parts",
                side_effect=RecursionError("untrusted nesting"),
            ), contextlib.redirect_stderr(stderr), self.assertRaises(
                verifier.V10BundleError
            ) as raised:
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(
                raised.exception.failure_code,
                "V10_UNEXPECTED_FAILURE",
            )
            diagnostic = _diagnostic(stderr.getvalue())
            self.assertEqual(
                diagnostic["v10_root_cause_status"],
                "V10_UNEXPECTED_FAILURE",
            )
            self.assertEqual(
                diagnostic["failure_code"],
                "V10_UNEXPECTED_FAILURE",
            )
            self.assertEqual(diagnostic["verdict"], "fail")

    def test_final_entrypoint_installs_and_restores_v10_chain(self) -> None:
        frozen = verifier._v9._validate_build_evidence

        def fake_final(*args, **kwargs):
            self.assertIs(
                verifier._v9._validate_build_evidence,
                verifier._chain_validate_build_evidence,
            )
            return {"sentinel": True}

        with mock.patch.object(
            verifier,
            "_FROZEN_V9_VALIDATE_FINAL",
            side_effect=fake_final,
        ):
            self.assertEqual(verifier.validate_final(), {"sentinel": True})
        self.assertIs(verifier._v9._validate_build_evidence, frozen)

    def test_exact_nested_final_patch_stack_executes_observer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            metadata, progress, _digests, _observer = (
                self._write_observer_evidence(Path(temporary))
            )
            base = verifier._v6._v3._base
            with verifier._patched_v9_observer_contract():
                with verifier._v9._patched_v8_input_omission_contract():
                    with verifier._v8._patched_v7_empty_location_contract():
                        with verifier._v7._patched_v6_incremental_contract():
                            with verifier._v6._patched_base_validator():
                                self.assertIs(
                                    base.validate_build_evidence,
                                    verifier._chain_validate_build_evidence,
                                )
                                with contextlib.redirect_stderr(io.StringIO()):
                                    summary = base.validate_build_evidence(
                                        metadata,
                                        progress,
                                        dockerfile_kind="prefix",
                                        require_network_vertices_cached=True,
                                    )
            self.assertEqual(
                summary["v10_rawjson_diagnostic"]["projection_kind"],
                "observer-prefix",
            )
            verifier._assert_frozen_dispatch()

    def test_copied_v10_cli_accepts_exact_three_projection_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copied: dict[str, Path] = {}
            sources = {
                "v10": Path(verifier.__file__),
                "v9": Path(verifier._v9.__file__),
                "v8": Path(verifier._v8.__file__),
                "v7": Path(verifier._v7.__file__),
                "v6": Path(verifier._v6.__file__),
                "v3": Path(verifier._v6._v3.__file__),
                "base": Path(verifier._v6._v3._base.__file__),
            }
            for label, source in sources.items():
                target = root / f"trusted-{label}.py"
                shutil.copyfile(source, target)
                copied[label] = target
            environment = os.environ.copy()
            environment.update(
                {
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "NOTEAI_V9_BUNDLE_VERIFIER_PATH": str(copied["v9"]),
                    "NOTEAI_V8_BUNDLE_VERIFIER_PATH": str(copied["v8"]),
                    "NOTEAI_V7_BUNDLE_VERIFIER_PATH": str(copied["v7"]),
                    "NOTEAI_V6_BUNDLE_VERIFIER_PATH": str(copied["v6"]),
                    "NOTEAI_V3_BUNDLE_VERIFIER_PATH": str(copied["v3"]),
                    "NOTEAI_BASE_BUNDLE_VERIFIER_PATH": str(copied["base"]),
                }
            )

            cases: list[tuple[str, Path, Path, bool, str]] = []
            producer = root / "producer-cli"
            producer.mkdir()
            metadata, progress, _ = self._fixture()._write_evidence(
                producer,
                cached=False,
                second_cached=False,
            )
            events = self._read_events(progress)
            self._set_all_role_intervals(events, cached=False)
            self._write_events(progress, events)
            cases.append(
                ("producer", metadata, progress, False, "producer-prefix")
            )

            observer = root / "observer-cli"
            observer.mkdir()
            metadata, progress, _digests, _observer = (
                self._write_observer_evidence(observer)
            )
            cases.append(
                ("observer", metadata, progress, True, "observer-prefix")
            )

            full = root / "full-cli"
            full.mkdir()
            metadata, progress, _digests, _witness = self._write_full_evidence(full)
            cases.append(
                ("full", metadata, progress, True, "full-runtime-common")
            )

            for label, metadata, progress, cached, projection in cases:
                with self.subTest(label=label):
                    output = root / f"{label}-summary.json"
                    command = [
                        sys.executable,
                        str(copied["v10"]),
                        "verify-build",
                        "--metadata",
                        str(metadata),
                        "--progress",
                        str(progress),
                        "--dockerfile",
                        "full" if label == "full" else "prefix",
                        "--output",
                        str(output),
                    ]
                    if cached:
                        command.append("--require-network-cached")
                    completed = subprocess.run(
                        command,
                        env=environment,
                        check=False,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    self.assertEqual(
                        completed.returncode,
                        0,
                        completed.stdout + completed.stderr,
                    )
                    payload = json.loads(output.read_text(encoding="utf-8"))
                    self.assertEqual(
                        payload["v10_rawjson_diagnostic"]["projection_kind"],
                        projection,
                    )
                    self.assertEqual(
                        completed.stderr.count(
                            "noteai_v10_progress_diagnostic="
                        ),
                        1,
                    )

    def test_copied_v9_file_guard_rejects_hash_drift_and_hardlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            v10_copy = root / "trusted-v10.py"
            v9_copy = root / "trusted-v9.py"
            shutil.copyfile(Path(verifier.__file__), v10_copy)
            shutil.copyfile(Path(verifier._v9.__file__), v9_copy)
            self.assertEqual(
                hashlib.sha256(v9_copy.read_bytes()).hexdigest(),
                verifier.V9_VERIFIER_SHA256,
            )
            with v9_copy.open("ab") as handle:
                handle.write(b"\n")
            self.assertNotEqual(
                hashlib.sha256(v9_copy.read_bytes()).hexdigest(),
                verifier.V9_VERIFIER_SHA256,
            )
            with mock.patch.dict(
                os.environ,
                {"NOTEAI_V9_BUNDLE_VERIFIER_PATH": str(v9_copy)},
            ), self.assertRaisesRegex(RuntimeError, "hash drift"):
                verifier._load_v9_verifier()
            shutil.copyfile(Path(verifier._v9.__file__), v9_copy)
            hardlink = root / "trusted-v9-hardlink.py"
            hardlink.hardlink_to(v9_copy)
            self.assertEqual(v9_copy.stat().st_nlink, 2)
            with mock.patch.dict(
                os.environ,
                {"NOTEAI_V9_BUNDLE_VERIFIER_PATH": str(hardlink)},
            ), self.assertRaisesRegex(RuntimeError, "file contract changed"):
                verifier._load_v9_verifier()


if __name__ == "__main__":
    unittest.main()
