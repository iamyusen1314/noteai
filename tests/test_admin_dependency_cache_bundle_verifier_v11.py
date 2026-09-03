from __future__ import annotations

import base64
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_bundle_v11 as verifier  # noqa: E402


def _load_test_module(filename: str, name: str):
    path = ROOT / "tests" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load fixtures from {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V9_TESTS = _load_test_module(
    "test_admin_dependency_cache_bundle_verifier_v9.py",
    "_cache_bundle_v9_tests_v11",
)
V10_TESTS = _load_test_module(
    "test_admin_dependency_cache_bundle_verifier_v10.py",
    "_cache_bundle_v10_tests_v11",
)
SOURCE_PROJECTION_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "admin_dependency_cache_buildkit_v0.31.2_"
    "export_anchor_observer_projection.json"
)


def _diagnostic(stderr: str) -> dict:
    prefix = "noteai_v11_progress_diagnostic="
    matches = [
        json.loads(line[len(prefix) :])
        for line in stderr.splitlines()
        if line.startswith(prefix)
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"unexpected V11 diagnostic line count: {len(matches)}"
        )
    return matches[0]


class AdminDependencyCacheBundleVerifierV11Tests(unittest.TestCase):
    def _fixture(self):
        return V9_TESTS.AdminDependencyCacheBundleVerifierV9Tests()

    @staticmethod
    def _read_json(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
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
    def _set_role_cache(events: list[dict], *, cached: bool) -> None:
        for event in events:
            for vertex in event.get("vertexes", []):
                if "started" not in vertex:
                    vertex.pop("cached", None)
                elif cached:
                    vertex["cached"] = True
                else:
                    vertex.pop("cached", None)

    @staticmethod
    def _combined_dockerfile() -> bytes:
        lines = (ROOT / "Dockerfile").read_bytes().splitlines(keepends=True)
        return b"".join(lines[:80]) + verifier.COMBINED_SUFFIX

    def _write_evidence(
        self,
        root: Path,
        *,
        target: str,
        cached: bool,
    ) -> tuple[Path, Path, list[str], str]:
        root.mkdir(parents=True, exist_ok=True)
        metadata, progress, digests = self._fixture()._write_evidence(root)
        payload = self._read_json(metadata)
        provenance = payload["buildx.build.provenance"]
        build_config = provenance["buildConfig"]
        source = provenance["metadata"][
            "https://mobyproject.org/buildkit@v1#metadata"
        ]["source"]
        if target == verifier.EXPORT_TARGET:
            line = verifier.EXPORT_LINE
            marker = verifier.EXPORT_MARKER
            child_digest = "sha256:" + ("4" * 64)
        else:
            line = verifier.IMPORT_LINE
            marker = verifier.IMPORT_MARKER
            child_digest = "sha256:" + ("5" * 64)
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
        build_config["digestMapping"][child_digest] = "step6"
        source["locations"]["step6"] = self._location(line)
        source["infos"][0]["data"] = base64.b64encode(
            self._combined_dockerfile()
        ).decode("ascii")
        provenance["invocation"]["parameters"]["args"]["target"] = target
        self._write_json(metadata, payload)

        events = self._read_events(progress)
        self._set_role_cache(events, cached=cached)
        updates = (
            {
                "digest": child_digest,
                "name": f"RUN {target}",
                "inputs": [digests[2]],
            },
            {
                "digest": child_digest,
                "name": f"RUN {target}",
                "started": "2026-07-31T00:00:06Z",
            },
            {
                "digest": child_digest,
                "name": f"RUN {target}",
                "started": "2026-07-31T00:00:06Z",
                "completed": "2026-07-31T00:00:19Z",
            },
        )
        for event, update in zip(events[:3], updates):
            event["vertexes"].append(update)
        split = max(1, len(marker) // 2)
        for index, part in enumerate((marker[:split], marker[split:])):
            events.append(
                {
                    "logs": [
                        {
                            "vertex": child_digest,
                            "stream": 1,
                            "data": base64.b64encode(part).decode("ascii"),
                            "timestamp": f"2026-07-31T00:00:{10 + index:02d}Z",
                        }
                    ]
                }
            )
        self._write_events(progress, events)
        return metadata, progress, digests, child_digest

    def _producer_and_record(
        self,
        root: Path,
    ) -> tuple[dict, Path, Path]:
        metadata, progress, _digests, _child = self._write_evidence(
            root / "producer",
            target=verifier.EXPORT_TARGET,
            cached=False,
        )
        with contextlib.redirect_stderr(io.StringIO()):
            summary = verifier.validate_build_evidence(
                metadata,
                progress,
                dockerfile_kind="prefix",
                require_network_vertices_cached=False,
            )
        producer_path = root / "producer-summary.json"
        self._write_json(producer_path, summary)
        pip = next(
            item
            for item in summary["network_vertices"]
            if item["role"] == "runtime_pip"
        )
        record = {
            "schema_version": "noteai.admin-dependency-cache-record.v11",
            "cache_config_sha256": "a" * 64,
            "cache_config_bytes": 100,
            "record_count": 2,
            "anchor": {
                "index": 1,
                "digest": summary["anchor"]["vertex_digest"],
                "result_count": 1,
            },
            "runtime_pip": {
                "index": 0,
                "digest": pip["vertex_digest"],
                "result_count": 1,
            },
            "direct_path": {
                "input_group_count": 1,
                "identity_link_count": 1,
                "anchor_to_runtime_pip_link_index": 0,
                "selector": "",
            },
        }
        record_path = root / "cache-record.json"
        self._write_json(record_path, record)
        return summary, producer_path, record_path

    def _consumer(
        self,
        root: Path,
        *,
        cached: bool = True,
    ) -> tuple[Path, Path, Path, Path]:
        _summary, producer_path, record_path = self._producer_and_record(root)
        metadata, progress, _digests, _child = self._write_evidence(
            root / "consumer",
            target=verifier.IMPORT_TARGET,
            cached=cached,
        )
        return metadata, progress, producer_path, record_path

    def test_source_projection_and_combined_dockerfile_are_hash_bound(self) -> None:
        projection = self._read_json(SOURCE_PROJECTION_PATH)
        combined = self._combined_dockerfile()
        self.assertEqual(len(combined), verifier.COMBINED_DOCKERFILE_BYTES)
        self.assertEqual(
            combined.count(b"\n"),
            verifier.COMBINED_DOCKERFILE_LINES,
        )
        self.assertEqual(
            hashlib.sha256(combined).hexdigest(),
            verifier.COMBINED_DOCKERFILE_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(verifier.COMBINED_SUFFIX).hexdigest(),
            verifier.COMBINED_SUFFIX_SHA256,
        )
        self.assertEqual(
            projection["combined_dockerfile"]["derived_sha256"],
            verifier.COMBINED_DOCKERFILE_SHA256,
        )
        self.assertEqual(
            projection["historical_v10_root_cause_status"],
            "UNKNOWN_NOT_RETAINED",
        )
        self.assertEqual(
            projection["classification"],
            "SOURCE_REVIEWED_GRAPH_CONTRACT_AND_V11_IMPLEMENTATION_REVIEW_"
            "NOT_V10_RUNTIME_EVIDENCE",
        )
        self.assertFalse(projection["actual_v10_runtime_metadata_retained"])
        self.assertFalse(projection["actual_v10_runtime_progress_retained"])
        self.assertFalse(
            projection["actual_v10_runtime_role_digest_retained"]
        )
        self.assertEqual(
            projection["cache_config_claim_provenance"],
            "V11_IMPLEMENTATION_REVIEWED_NOT_SOURCE_PROVEN_BY_LISTED_"
            "BUILDKIT_FILES",
        )

    def test_producer_anchor_passes_with_three_uncached_roles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            metadata, progress, _digests, child = self._write_evidence(
                Path(temporary),
                target=verifier.EXPORT_TARGET,
                cached=False,
            )
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                summary = verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=False,
                )
            self.assertEqual(summary["target"], verifier.EXPORT_TARGET)
            self.assertEqual(summary["anchor"]["vertex_digest"], child)
            self.assertIsNone(summary["observer"])
            self.assertTrue(summary["other_sibling_absent"])
            self.assertTrue(
                all(
                    item["noncached_interval_count"]
                    == item["interval_count"]
                    and item["cached_interval_count"] == 0
                    for item in summary["network_vertices"]
                )
            )
            self.assertEqual(_diagnostic(stderr.getvalue())["verdict"], "pass")

    def test_consumer_observer_passes_and_classifies_same_digest_cached(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, progress, producer, record = self._consumer(root)
            pre_diagnostic = root / "pre-diagnostic.json"
            final_diagnostic = root / "final-diagnostic.json"
            retained_pair = root / "pair.json"
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                summary = verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                    producer_summary_path=producer,
                    cache_record_path=record,
                    pre_predicate_diagnostic_output_path=pre_diagnostic,
                    diagnostic_output_path=final_diagnostic,
                    pair_output_path=retained_pair,
                )
            self.assertEqual(summary["target"], verifier.IMPORT_TARGET)
            self.assertEqual(
                summary["pair"]["classification"],
                "SAME_DIGEST_CACHED",
            )
            self.assertEqual(
                summary["cache_record_projection"]["record_count"],
                2,
            )
            diagnostic = _diagnostic(stderr.getvalue())
            self.assertTrue(diagnostic["cached_predicates_enforced"])
            self.assertEqual(
                diagnostic["pair_classification"]["classification"],
                "SAME_DIGEST_CACHED",
            )
            retained_pre = self._read_json(pre_diagnostic)
            self.assertEqual(
                retained_pre["v11_boundary_status"],
                "PENDING_CACHE_PREDICATE",
            )
            self.assertEqual(self._read_json(final_diagnostic), diagnostic)
            self.assertEqual(
                retained_pre,
                verifier._expected_pre_predicate_diagnostic(diagnostic),
            )
            for mutation in ("extra-key", "wrong-hash", "role-vector"):
                with self.subTest(mutation=mutation):
                    altered = copy.deepcopy(retained_pre)
                    if mutation == "extra-key":
                        altered["unexpected"] = True
                    elif mutation == "wrong-hash":
                        altered["diagnostic_sha256"] = "0" * 64
                    else:
                        altered["role_intervals"][0]["interval_count"] += 1
                    with self.assertRaisesRegex(
                        verifier.V11BundleError,
                        "pre-predicate diagnostic changed",
                    ):
                        verifier._validate_pre_predicate_diagnostic(
                            altered,
                            diagnostic,
                        )
            self.assertEqual(
                self._read_json(retained_pair)["classification"],
                "SAME_DIGEST_CACHED",
            )

    def test_consumer_failure_retains_all_roles_and_pair_before_predicate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, progress, producer, record = self._consumer(
                root,
                cached=False,
            )
            original_metadata = metadata.read_bytes()
            original_progress = progress.read_bytes()
            pre_diagnostic = root / "pre-diagnostic.json"
            final_diagnostic = root / "final-diagnostic.json"
            retained_pair = root / "pair.json"
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), self.assertRaisesRegex(
                verifier.V11BundleError,
                "vertex was not cached",
            ):
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                    producer_summary_path=producer,
                    cache_record_path=record,
                    pre_predicate_diagnostic_output_path=pre_diagnostic,
                    diagnostic_output_path=final_diagnostic,
                    pair_output_path=retained_pair,
                )
            diagnostic = _diagnostic(stderr.getvalue())
            self.assertEqual(len(diagnostic["role_intervals"]), 3)
            self.assertEqual(len(diagnostic["role_log_projections"]), 3)
            self.assertEqual(
                diagnostic["pair_classification"]["classification"],
                "SAME_DIGEST_NONCACHED",
            )
            self.assertFalse(diagnostic["cached_predicates_enforced"])
            self.assertEqual(
                diagnostic["cache_record_projection"]["record_count"],
                2,
            )
            self.assertEqual(
                diagnostic["failure_code"],
                "NETWORK_VERTEX_NOT_CACHED",
            )
            self.assertEqual(
                self._read_json(pre_diagnostic)["v11_boundary_status"],
                "PENDING_CACHE_PREDICATE",
            )
            self.assertEqual(self._read_json(final_diagnostic), diagnostic)
            self.assertEqual(
                self._read_json(retained_pair)["classification"],
                "SAME_DIGEST_NONCACHED",
            )
            self.assertEqual(metadata.read_bytes(), original_metadata)
            self.assertEqual(progress.read_bytes(), original_progress)

    def test_consumer_digest_drift_is_classified_before_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, progress, producer, record = self._consumer(root)
            payload = self._read_json(producer)
            next(
                item
                for item in payload["network_vertices"]
                if item["role"] == "runtime_pip"
            )["vertex_digest"] = "sha256:" + ("9" * 64)
            self._write_json(producer, payload)
            cache = self._read_json(record)
            cache["runtime_pip"]["digest"] = "sha256:" + ("9" * 64)
            self._write_json(record, cache)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), self.assertRaisesRegex(
                verifier.V11BundleError,
                "digests differ",
            ):
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                    producer_summary_path=producer,
                    cache_record_path=record,
                )
            self.assertEqual(
                _diagnostic(stderr.getvalue())["pair_classification"][
                    "classification"
                ],
                "DIGEST_DRIFT",
            )

    def test_consumer_requires_producer_and_cache_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            metadata, progress, _digests, _child = self._write_evidence(
                Path(temporary),
                target=verifier.IMPORT_TARGET,
                cached=True,
            )
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaisesRegex(
                verifier.V11BundleError,
                "producer summary or cache record",
            ):
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )

    def test_target_and_cache_mode_matrix_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            producer_metadata, producer_progress, _d, _c = self._write_evidence(
                root / "producer",
                target=verifier.EXPORT_TARGET,
                cached=False,
            )
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(
                verifier.V11BundleError
            ):
                verifier.validate_build_evidence(
                    producer_metadata,
                    producer_progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            consumer_metadata, consumer_progress, producer, record = self._consumer(
                root / "consumer-case"
            )
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(
                verifier.V11BundleError
            ):
                verifier.validate_build_evidence(
                    consumer_metadata,
                    consumer_progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=False,
                    producer_summary_path=producer,
                    cache_record_path=record,
                )

    def test_child_network_parent_and_marker_fail_closed(self) -> None:
        mutations = ("network", "parent", "marker")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                metadata, progress, _digests, child = self._write_evidence(
                    root,
                    target=verifier.EXPORT_TARGET,
                    cached=False,
                )
                if mutation in {"network", "parent"}:
                    payload = self._read_json(metadata)
                    definition = payload["buildx.build.provenance"]["buildConfig"][
                        "llbDefinition"
                    ][-1]
                    if mutation == "network":
                        definition["op"]["Op"]["exec"]["network"] = 0
                    else:
                        definition["inputs"] = ["step4:0"]
                    self._write_json(metadata, payload)
                else:
                    events = self._read_events(progress)
                    for event in events:
                        for log in event.get("logs", []):
                            if log.get("vertex") == child:
                                log["data"] = base64.b64encode(b"changed").decode(
                                    "ascii"
                                )
                    self._write_events(progress, events)
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(
                    verifier.V11BundleError
                ):
                    verifier.validate_build_evidence(
                        metadata,
                        progress,
                        dockerfile_kind="prefix",
                        require_network_vertices_cached=False,
                    )

    def test_child_must_execute_exactly_once_uncached(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            metadata, progress, _digests, child = self._write_evidence(
                Path(temporary),
                target=verifier.EXPORT_TARGET,
                cached=False,
            )
            events = self._read_events(progress)
            for event in events:
                for vertex in event.get("vertexes", []):
                    if vertex.get("digest") == child and "started" in vertex:
                        vertex["cached"] = True
            self._write_events(progress, events)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaisesRegex(
                verifier.V11BundleError,
                "lifecycle changed",
            ):
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=False,
                )

    def test_unrequested_sibling_digest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            metadata, progress, _digests, _child = self._write_evidence(
                Path(temporary),
                target=verifier.EXPORT_TARGET,
                cached=False,
            )
            payload = self._read_json(metadata)
            provenance = payload["buildx.build.provenance"]
            config = provenance["buildConfig"]
            source = provenance["metadata"][
                "https://mobyproject.org/buildkit@v1#metadata"
            ]["source"]
            config["llbDefinition"].append(
                {
                    "id": "step7",
                    "inputs": ["step5:0"],
                    "op": {
                        "Op": {"exec": {"network": 2}},
                        "platform": {"Architecture": "amd64", "OS": "linux"},
                    },
                }
            )
            config["digestMapping"]["sha256:" + ("8" * 64)] = "step7"
            source["locations"]["step7"] = self._location(verifier.IMPORT_LINE)
            self._write_json(metadata, payload)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaisesRegex(
                verifier.V11BundleError,
                "sibling target",
            ):
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=False,
                )

    def test_unlocated_direct_child_is_rejected_as_a_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            metadata, progress, _digests, _child = self._write_evidence(
                Path(temporary),
                target=verifier.EXPORT_TARGET,
                cached=False,
            )
            payload = self._read_json(metadata)
            config = payload["buildx.build.provenance"]["buildConfig"]
            config["llbDefinition"].append(
                {
                    "id": "step7",
                    "inputs": ["step5:0"],
                    "op": {
                        "Op": {"exec": {"network": 2}},
                        "platform": {"Architecture": "amd64", "OS": "linux"},
                    },
                }
            )
            config["digestMapping"]["sha256:" + ("8" * 64)] = "step7"
            self._write_json(metadata, payload)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaisesRegex(
                verifier.V11BundleError,
                "sibling target",
            ):
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=False,
                )

    def test_frozen_prefix_delegate_rejects_provenance_envelope_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            metadata, progress, _digests, _child = self._write_evidence(
                Path(temporary),
                target=verifier.EXPORT_TARGET,
                cached=False,
            )
            payload = self._read_json(metadata)
            payload["buildx.build.provenance"]["buildType"] = (
                "https://example.invalid/tampered"
            )
            self._write_json(metadata, payload)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(
                verifier.V11BundleError
            ):
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=False,
                )

    def test_frozen_prefix_delegate_rejects_cached_package_network_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, progress, producer, record = self._consumer(root)
            events = self._read_events(progress)
            pip_digest = next(
                vertex["digest"]
                for event in events
                for vertex in event.get("vertexes", [])
                if str(vertex.get("name", "")).startswith("pip install")
            )
            events.append(
                {
                    "logs": [
                        {
                            "vertex": pip_digest,
                            "stream": 1,
                            "data": base64.b64encode(
                                b"Downloading forbidden-package\n"
                            ).decode("ascii"),
                            "timestamp": "2026-07-31T00:00:18Z",
                        }
                    ]
                }
            )
            self._write_events(progress, events)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(
                verifier.V11BundleError
            ) as raised:
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                    producer_summary_path=producer,
                    cache_record_path=record,
                )
            self.assertEqual(
                raised.exception.failure_code,
                "PACKAGE_NETWORK_OUTPUT_OBSERVED",
            )

    def test_combined_dockerfile_tamper_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            metadata, progress, _digests, _child = self._write_evidence(
                Path(temporary),
                target=verifier.EXPORT_TARGET,
                cached=False,
            )
            payload = self._read_json(metadata)
            source = payload["buildx.build.provenance"]["metadata"][
                "https://mobyproject.org/buildkit@v1#metadata"
            ]["source"]
            decoded = base64.b64decode(source["infos"][0]["data"])
            source["infos"][0]["data"] = base64.b64encode(
                decoded.replace(b"anchor-v11", b"anchor-v12")
            ).decode("ascii")
            self._write_json(metadata, payload)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaisesRegex(
                verifier.V11BundleError,
                "combined Dockerfile",
            ):
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=False,
                )

    def test_pair_classifier_has_exact_three_outcomes(self) -> None:
        producer = {
            "target": verifier.EXPORT_TARGET,
            "network_vertices": [
                {
                    "role": "runtime_pip",
                    "vertex_digest": "sha256:" + ("1" * 64),
                }
            ],
        }
        consumer = {
            "target": verifier.IMPORT_TARGET,
            "network_vertices": [
                {
                    "role": "runtime_pip",
                    "vertex_digest": "sha256:" + ("1" * 64),
                    "interval_count": 1,
                    "cached_interval_count": 1,
                    "noncached_interval_count": 0,
                }
            ],
        }
        self.assertEqual(
            verifier.classify_pair(producer, consumer)["classification"],
            "SAME_DIGEST_CACHED",
        )
        consumer["network_vertices"][0]["cached_interval_count"] = 0
        consumer["network_vertices"][0]["noncached_interval_count"] = 1
        self.assertEqual(
            verifier.classify_pair(producer, consumer)["classification"],
            "SAME_DIGEST_NONCACHED",
        )
        consumer["network_vertices"][0]["vertex_digest"] = (
            "sha256:" + ("2" * 64)
        )
        self.assertEqual(
            verifier.classify_pair(producer, consumer)["classification"],
            "DIGEST_DRIFT",
        )

    def _oci_cache(
        self,
        root: Path,
        producer: dict,
    ) -> tuple[Path, dict]:
        cache = root / "cache"
        blob_root = cache / "blobs" / "sha256"
        blob_root.mkdir(parents=True)
        (cache / "oci-layout").write_text(
            '{"imageLayoutVersion":"1.0.0"}',
            encoding="utf-8",
        )
        layer = b"layer"
        layer_digest = hashlib.sha256(layer).hexdigest()
        (blob_root / layer_digest).write_bytes(layer)
        pip = next(
            item
            for item in producer["network_vertices"]
            if item["role"] == "runtime_pip"
        )["vertex_digest"]
        config = {
            "layers": [
                {
                    "blob": "sha256:" + layer_digest,
                    "parent": -1,
                }
            ],
            "records": [
                {
                    "digest": pip,
                    "layers": [{"layer": 0}],
                    "inputs": [],
                },
                {
                    "digest": producer["anchor"]["vertex_digest"],
                    "layers": [{"layer": 0}],
                    "inputs": [[{"link": 0}]],
                },
            ],
        }
        config_bytes = json.dumps(config, separators=(",", ":")).encode()
        config_digest = hashlib.sha256(config_bytes).hexdigest()
        (blob_root / config_digest).write_bytes(config_bytes)
        manifest = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {
                "mediaType": "application/vnd.buildkit.cacheconfig.v0",
                "digest": "sha256:" + config_digest,
                "size": len(config_bytes),
            },
            "layers": [
                {
                    "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    "digest": "sha256:" + layer_digest,
                    "size": len(layer),
                }
            ],
        }
        manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode()
        manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
        (blob_root / manifest_digest).write_bytes(manifest_bytes)
        index = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [
                {
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "digest": "sha256:" + manifest_digest,
                    "size": len(manifest_bytes),
                }
            ],
        }
        (cache / "index.json").write_text(
            json.dumps(index, separators=(",", ":")),
            encoding="utf-8",
        )
        return cache, config

    def test_cache_record_binds_unique_result_bearing_direct_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            producer, producer_path, _record = self._producer_and_record(root)
            cache, _config = self._oci_cache(root, producer)
            summary = verifier.validate_cache_record(cache, producer_path)
            self.assertEqual(summary["record_count"], 2)
            self.assertEqual(summary["anchor"]["index"], 1)
            self.assertEqual(summary["runtime_pip"]["index"], 0)
            self.assertEqual(
                summary["direct_path"]["identity_link_count"],
                1,
            )
            self.assertEqual(set(summary), {
                "schema_version",
                "cache_config_sha256",
                "cache_config_bytes",
                "record_count",
                "anchor",
                "runtime_pip",
                "direct_path",
            })

    def test_cache_record_rejects_duplicate_missing_or_indirect_records(self) -> None:
        mutations = ("duplicate", "missing-result", "indirect")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                producer, producer_path, _record = self._producer_and_record(root)
                cache, config = self._oci_cache(root, producer)
                if mutation == "duplicate":
                    config["records"].append(dict(config["records"][1]))
                elif mutation == "missing-result":
                    config["records"][1].pop("layers")
                else:
                    config["records"][1]["inputs"] = [[{"link": 0}, {"link": 0}]]
                blob_root = cache / "blobs" / "sha256"
                index = self._read_json(cache / "index.json")
                manifest_digest = index["manifests"][0]["digest"].split(":", 1)[1]
                manifest_path = blob_root / manifest_digest
                manifest = self._read_json(manifest_path)
                old_config_digest = manifest["config"]["digest"].split(":", 1)[1]
                (blob_root / old_config_digest).unlink()
                config_bytes = json.dumps(config, separators=(",", ":")).encode()
                config_digest = hashlib.sha256(config_bytes).hexdigest()
                (blob_root / config_digest).write_bytes(config_bytes)
                manifest["config"]["digest"] = "sha256:" + config_digest
                manifest["config"]["size"] = len(config_bytes)
                manifest_path.unlink()
                manifest_bytes = json.dumps(
                    manifest,
                    separators=(",", ":"),
                ).encode()
                next_manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
                (blob_root / next_manifest_digest).write_bytes(manifest_bytes)
                index["manifests"][0]["digest"] = (
                    "sha256:" + next_manifest_digest
                )
                index["manifests"][0]["size"] = len(manifest_bytes)
                self._write_json(cache / "index.json", index)
                with self.assertRaises(
                    (
                        verifier.V11BundleError,
                        verifier._v10._v6._v3.BundleError,
                    )
                ):
                    verifier.validate_cache_record(cache, producer_path)

    def test_full_replay_is_delegated_directly_to_frozen_v10(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = V10_TESTS.AdminDependencyCacheBundleVerifierV10Tests()
            metadata, progress, _digests, _witness = fixture._write_full_evidence(
                Path(temporary)
            )
            with contextlib.redirect_stderr(io.StringIO()):
                summary = verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="full",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(
                summary["dockerfile_sha256"],
                verifier.FULL_DOCKERFILE_SHA256,
            )
            self.assertIn("v10_rawjson_diagnostic", summary)
            self.assertNotIn("v11_rawjson_diagnostic", summary)

    def test_frozen_v10_dispatch_rejection_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = V10_TESTS.AdminDependencyCacheBundleVerifierV10Tests()
            metadata, progress, _digests, _witness = fixture._write_full_evidence(
                Path(temporary)
            )
            with mock.patch.object(
                verifier._v10,
                "validate_build_evidence",
                side_effect=verifier._v10.V10BundleError(
                    "FROZEN_V10_TEST",
                    "frozen rejection",
                ),
            ), contextlib.redirect_stderr(io.StringIO()), self.assertRaisesRegex(
                verifier.V11BundleError,
                "frozen rejection",
            ):
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="full",
                    require_network_vertices_cached=True,
                )

    def test_cli_exposes_only_bounded_v11_commands(self) -> None:
        parser = verifier.build_parser()
        for arguments in (
            [
                "verify-build",
                "--metadata",
                "m",
                "--progress",
                "p",
                "--dockerfile",
                "prefix",
                "--pre-predicate-diagnostic-output",
                "pre.json",
                "--diagnostic-output",
                "final.json",
                "--pair-output",
                "pair.json",
            ],
            [
                "verify-cache-record",
                "--cache-dir",
                "c",
                "--producer-summary",
                "p",
            ],
            [
                "verify-pair",
                "--producer-summary",
                "p",
                "--consumer-summary",
                "c",
            ],
            ["verify-core", "--bundle", "b", "--extract-to", "e"],
            ["verify-final", "--bundle", "b", "--extract-to", "e"],
        ):
            with self.subTest(arguments=arguments):
                self.assertIn(
                    parser.parse_args(arguments).command,
                    {
                        "verify-build",
                        "verify-cache-record",
                        "verify-pair",
                        "verify-core",
                        "verify-final",
                    },
                )


if __name__ == "__main__":
    unittest.main()
