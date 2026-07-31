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
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_bundle_v6 as v6  # noqa: E402
import verify_admin_dependency_cache_bundle_v7 as verifier  # noqa: E402


def _load_v6_fixture_module():
    fixture_path = (
        ROOT / "tests" / "test_admin_dependency_cache_bundle_verifier_v6.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_cache_bundle_v6_tests_v7",
        fixture_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load V6 cache-bundle fixtures")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V6_FIXTURES = _load_v6_fixture_module()
SOURCE_PROJECTION_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "admin_dependency_cache_buildkit_v0.31.2_"
    "incremental_vertex_projection.json"
)
SOURCE_PROJECTION = json.loads(
    SOURCE_PROJECTION_PATH.read_text(encoding="utf-8")
)


def _diagnostic(stderr: str) -> dict:
    lines = stderr.splitlines()
    if len(lines) != 1:
        raise AssertionError(f"unexpected diagnostic line count: {len(lines)}")
    prefix = "noteai_v7_progress_diagnostic="
    if not lines[0].startswith(prefix):
        raise AssertionError("missing V7 diagnostic prefix")
    return json.loads(lines[0][len(prefix) :])


class AdminDependencyCacheBundleVerifierV7Tests(unittest.TestCase):
    def _write_evidence(
        self,
        root: Path,
        *,
        dockerfile_kind: str = "prefix",
        cached: bool = True,
    ) -> tuple[Path, Path, list[str]]:
        fixture = (
            V6_FIXTURES.AdminDependencyCacheBundleVerifierV6Tests()
        )
        return fixture._write_evidence(
            root,
            dockerfile_kind=dockerfile_kind,
            cached=cached,
        )

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

    def _incrementalize(
        self,
        progress: Path,
        *,
        first_cached: bool = False,
        second_cached: bool = True,
    ) -> list[dict]:
        original = self._read_events(progress)
        base_vertices = original[0]["vertexes"]

        def update(
            vertex: dict,
            *,
            started: str | None = None,
            completed: str | None = None,
            cached: bool = False,
        ) -> dict:
            result = {
                "digest": vertex["digest"],
                "name": vertex["name"],
            }
            if started is not None:
                result["started"] = started
            if completed is not None:
                result["completed"] = completed
            if cached:
                result["cached"] = True
            return result

        events = [
            {
                "vertexes": [
                    update(vertex)
                    for vertex in base_vertices
                ]
            },
            {
                "vertexes": [
                    update(
                        vertex,
                        started="2026-07-31T00:00:05Z",
                        cached=first_cached,
                    )
                    for vertex in base_vertices
                ]
            },
            {
                "vertexes": [
                    update(
                        vertex,
                        started="2026-07-31T00:00:05Z",
                        completed="2026-07-31T00:00:20Z",
                        cached=first_cached,
                    )
                    for vertex in base_vertices
                ]
            },
            {
                "vertexes": [
                    update(
                        vertex,
                        started="2026-07-31T00:00:25Z",
                        cached=second_cached,
                    )
                    for vertex in base_vertices
                ]
            },
            {
                "vertexes": [
                    update(
                        vertex,
                        started="2026-07-31T00:00:25Z",
                        completed="2026-07-31T00:00:50Z",
                        cached=second_cached,
                    )
                    for vertex in base_vertices
                ]
            },
            *original[1:],
        ]
        self._write_events(progress, events)
        return events

    def test_source_projection_is_bound_and_not_runtime_evidence(self) -> None:
        self.assertEqual(
            hashlib.sha256(SOURCE_PROJECTION_PATH.read_bytes()).hexdigest(),
            "fb5c944a0006cb8e04f32e3ac98e949e27036b10077e4ce10bc0a6c8b4fb5de1",
        )
        self.assertEqual(
            SOURCE_PROJECTION["classification"],
            (
                "SOURCE_PROVEN_INCREMENTAL_VERTEX_CONTRACT_"
                "NOT_V6_RUNTIME_EVIDENCE"
            ),
        )
        self.assertFalse(
            SOURCE_PROJECTION["actual_v6_runtime_progress_retained"]
        )
        self.assertFalse(
            SOURCE_PROJECTION["runtime_conflicting_digest_reconstructed"]
        )
        self.assertTrue(
            SOURCE_PROJECTION["v7_contract"][
                "same_digest_multiple_lifecycle_intervals_valid"
            ]
        )
        self.assertTrue(
            SOURCE_PROJECTION["v7_contract"][
                "each_vertex_update_is_full_value_copy"
            ]
        )
        self.assertTrue(
            SOURCE_PROJECTION["v7_contract"][
                "inputs_exact_across_same_digest_updates"
            ]
        )
        self.assertIn(
            "1324-1334",
            SOURCE_PROJECTION["buildkit"]["sources"][0]["lines"],
        )
        self.assertEqual(
            SOURCE_PROJECTION["buildkit"]["commit"],
            "e42e1bfd389af7203238cce77b1f7dad447285e9",
        )

    def test_incremental_intervals_pass_both_targets_and_preserve_bytes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for dockerfile_kind in ("prefix", "full"):
                with self.subTest(dockerfile_kind=dockerfile_kind):
                    target = root / dockerfile_kind
                    target.mkdir()
                    metadata, progress, digests = self._write_evidence(
                        target,
                        dockerfile_kind=dockerfile_kind,
                    )
                    self._incrementalize(progress)
                    original = progress.read_bytes()
                    stderr = io.StringIO()
                    with contextlib.redirect_stderr(stderr):
                        summary = verifier.validate_build_evidence(
                            metadata,
                            progress,
                            dockerfile_kind=dockerfile_kind,
                            require_network_vertices_cached=True,
                        )
                    self.assertEqual(progress.read_bytes(), original)
                    self.assertEqual(
                        summary["progress_sha256"],
                        hashlib.sha256(original).hexdigest(),
                    )
                    self.assertEqual(
                        [item["vertex"] for item in summary["network_vertices"]],
                        digests,
                    )
                    self.assertNotIn("v6_rawjson_diagnostic", summary)
                    diagnostic = summary["v7_rawjson_diagnostic"]
                    self.assertEqual(diagnostic["vertex_update_count"], 15)
                    self.assertEqual(
                        diagnostic["lifecycle_interval_count"],
                        6,
                    )
                    self.assertEqual(
                        diagnostic["repeated_vertex_digest_count"],
                        3,
                    )
                    self.assertEqual(
                        diagnostic["maximum_intervals_per_digest"],
                        2,
                    )
                    self.assertEqual(
                        _diagnostic(stderr.getvalue())[
                            "diagnostic_sha256"
                        ],
                        diagnostic["diagnostic_sha256"],
                    )

    def test_v6_still_rejects_same_stream_that_v7_accepts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            metadata, progress, _ = self._write_evidence(Path(temporary))
            self._incrementalize(progress)
            with contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(v6.V6BundleError) as raised:
                v6.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(
                raised.exception.failure_code,
                "RAWJSON_VERTEX_CONFLICT",
            )
            with contextlib.redirect_stderr(io.StringIO()):
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )

    def test_latest_interval_controls_replay_cache_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, progress, _ = self._write_evidence(root)
            self._incrementalize(
                progress,
                first_cached=False,
                second_cached=True,
            )
            with contextlib.redirect_stderr(io.StringIO()):
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )

            metadata, progress, _ = self._write_evidence(root)
            self._incrementalize(
                progress,
                first_cached=True,
                second_cached=False,
            )
            with contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(verifier.V7BundleError) as raised:
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(
                raised.exception.failure_code,
                "NETWORK_VERTEX_NOT_CACHED",
            )

    def test_idempotent_overlapping_and_out_of_order_intervals_pass(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            metadata, progress, _ = self._write_evidence(Path(temporary))
            events = self._incrementalize(progress)
            events.insert(2, json.loads(json.dumps(events[1])))
            events.insert(4, json.loads(json.dumps(events[2])))
            for vertex in events[2]["vertexes"]:
                vertex["completed"] = "2026-07-31T00:00:40Z"
            for vertex in events[3]["vertexes"]:
                vertex["completed"] = "2026-07-31T00:00:40Z"
            reordered = [
                events[0],
                events[4],
                events[5],
                events[1],
                events[2],
                events[3],
                *events[6:],
            ]
            self._write_events(progress, reordered)
            with contextlib.redirect_stderr(io.StringIO()):
                summary = verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(
                summary["v7_rawjson_diagnostic"][
                    "maximum_intervals_per_digest"
                ],
                2,
            )

    def test_interval_regression_and_conflicts_fail_closed(self) -> None:
        cases = (
            ("terminal_to_open", "RAWJSON_VERTEX_INTERVAL_REGRESSION"),
            (
                "terminal_then_batch_open_terminal",
                "RAWJSON_VERTEX_INTERVAL_REGRESSION",
            ),
            ("completion_conflict", "RAWJSON_VERTEX_INTERVAL_CONFLICT"),
            ("cached_conflict", "RAWJSON_VERTEX_INTERVAL_CONFLICT"),
            ("completion_without_start", "RAWJSON_LIFECYCLE_INVALID"),
            ("completion_before_start", "RAWJSON_LIFECYCLE_INVALID"),
            (
                "nanosecond_completion_before_start",
                "RAWJSON_LIFECYCLE_INVALID",
            ),
            ("cached_announcement", "RAWJSON_VERTEX_ANNOUNCEMENT_INVALID"),
            (
                "open_to_announcement",
                "RAWJSON_VERTEX_INTERVAL_REGRESSION",
            ),
            (
                "terminal_to_announcement",
                "RAWJSON_VERTEX_INTERVAL_REGRESSION",
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, (case, expected_code) in enumerate(cases):
                with self.subTest(case=case):
                    target = root / str(index)
                    target.mkdir()
                    metadata, progress, _ = self._write_evidence(target)
                    events = self._incrementalize(progress)
                    vertex = events[1]["vertexes"][0]
                    if case == "terminal_to_open":
                        events.insert(
                            3,
                            json.loads(json.dumps(events[1])),
                        )
                    elif case == "terminal_then_batch_open_terminal":
                        events.insert(
                            3,
                            {
                                "vertexes": [
                                    json.loads(
                                        json.dumps(
                                            events[1]["vertexes"][0]
                                        )
                                    ),
                                    json.loads(
                                        json.dumps(
                                            events[2]["vertexes"][0]
                                        )
                                    ),
                                ]
                            },
                        )
                    elif case == "completion_conflict":
                        conflict = json.loads(json.dumps(events[2]))
                        conflict["vertexes"][0]["completed"] = (
                            "2026-07-31T00:00:21Z"
                        )
                        events.insert(3, conflict)
                    elif case == "cached_conflict":
                        conflict = json.loads(json.dumps(events[1]))
                        conflict["vertexes"][0]["cached"] = True
                        events.insert(2, conflict)
                    elif case == "completion_without_start":
                        vertex.pop("started")
                        vertex["completed"] = "2026-07-31T00:00:10Z"
                    elif case == "completion_before_start":
                        vertex["completed"] = "2026-07-31T00:00:04Z"
                    elif case == "nanosecond_completion_before_start":
                        vertex["started"] = (
                            "2026-07-31T00:00:05.000000900Z"
                        )
                        vertex["completed"] = (
                            "2026-07-31T00:00:05.000000100Z"
                        )
                    elif case == "open_to_announcement":
                        events.insert(
                            2,
                            {
                                "vertexes": [
                                    {
                                        "digest": vertex["digest"],
                                        "name": vertex["name"],
                                    }
                                ]
                            },
                        )
                    elif case == "terminal_to_announcement":
                        events.insert(
                            3,
                            {
                                "vertexes": [
                                    {
                                        "digest": vertex["digest"],
                                        "name": vertex["name"],
                                    }
                                ]
                            },
                        )
                    else:
                        events[0]["vertexes"][0]["cached"] = True
                    self._write_events(progress, events)
                    with contextlib.redirect_stderr(
                        io.StringIO()
                    ), self.assertRaises(verifier.V7BundleError) as raised:
                        verifier.validate_build_evidence(
                            metadata,
                            progress,
                            dockerfile_kind="prefix",
                            require_network_vertices_cached=True,
                        )
                    self.assertEqual(
                        raised.exception.failure_code,
                        expected_code,
                    )

    def test_all_bound_intervals_must_complete_inside_build_window(self) -> None:
        cases = (
            ("incomplete", "NETWORK_VERTEX_INTERVAL_INCOMPLETE"),
            ("outside", "NETWORK_VERTEX_LIFECYCLE_OUTSIDE_BUILD"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, (case, expected_code) in enumerate(cases):
                target = root / str(index)
                target.mkdir()
                metadata, progress, _ = self._write_evidence(target)
                events = self._incrementalize(progress)
                if case == "incomplete":
                    events[2]["vertexes"] = events[2]["vertexes"][1:]
                else:
                    events[1]["vertexes"][0]["started"] = (
                        "2026-07-30T23:59:59Z"
                    )
                    events[2]["vertexes"][0]["started"] = (
                        "2026-07-30T23:59:59Z"
                    )
                self._write_events(progress, events)
                with contextlib.redirect_stderr(
                    io.StringIO()
                ), self.assertRaises(verifier.V7BundleError) as raised:
                    verifier.validate_build_evidence(
                        metadata,
                        progress,
                        dockerfile_kind="prefix",
                        require_network_vertices_cached=True,
                    )
                self.assertEqual(raised.exception.failure_code, expected_code)

    def test_inputs_and_progress_group_are_full_copy_stable(
        self,
    ) -> None:
        cases = (
            ("stable", None),
            ("input_drift", "RAWJSON_VERTEX_INPUT_CONFLICT"),
            ("input_omission", "RAWJSON_VERTEX_INPUT_CONFLICT"),
            (
                "progress_group_drift",
                "RAWJSON_VERTEX_PROGRESS_GROUP_CONFLICT",
            ),
            (
                "progress_group_omission",
                "RAWJSON_VERTEX_PROGRESS_GROUP_CONFLICT",
            ),
            (
                "progress_group_schema",
                "RAWJSON_VERTEX_PROGRESS_GROUP_INVALID",
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, (case, expected_code) in enumerate(cases):
                with self.subTest(case=case):
                    target = root / str(index)
                    target.mkdir()
                    metadata, progress, digests = self._write_evidence(
                        target
                    )
                    events = self._incrementalize(progress)
                    for event in events[:5]:
                        vertex = event["vertexes"][0]
                        vertex["inputs"] = [digests[1]]
                        vertex["progressGroup"] = {
                            "id": "group-1",
                            "name": "dependency",
                            "weak": False,
                        }
                    if case == "input_drift":
                        events[2]["vertexes"][0]["inputs"] = [digests[2]]
                    elif case == "input_omission":
                        events[2]["vertexes"][0].pop("inputs")
                    elif case == "progress_group_drift":
                        events[2]["vertexes"][0]["progressGroup"]["id"] = (
                            "group-2"
                        )
                    elif case == "progress_group_omission":
                        events[2]["vertexes"][0].pop("progressGroup")
                    elif case == "progress_group_schema":
                        events[2]["vertexes"][0]["progressGroup"][
                            "unexpected"
                        ] = True
                    self._write_events(progress, events)
                    if expected_code is None:
                        with contextlib.redirect_stderr(io.StringIO()):
                            verifier.validate_build_evidence(
                                metadata,
                                progress,
                                dockerfile_kind="prefix",
                                require_network_vertices_cached=True,
                            )
                    else:
                        with contextlib.redirect_stderr(
                            io.StringIO()
                        ), self.assertRaises(
                            verifier.V7BundleError
                        ) as raised:
                            verifier.validate_build_evidence(
                                metadata,
                                progress,
                                dockerfile_kind="prefix",
                                require_network_vertices_cached=True,
                            )
                        self.assertEqual(
                            raised.exception.failure_code,
                            expected_code,
                        )

    def test_nanosecond_interval_identity_and_window_are_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            distinct = root / "distinct"
            distinct.mkdir()
            metadata, progress, _ = self._write_evidence(distinct)
            events = self._incrementalize(progress)
            for event in events[3:5]:
                vertex = event["vertexes"][0]
                vertex["started"] = (
                    "2026-07-31T00:00:25.123456100Z"
                )
                vertex.pop("cached", None)
            latest_open = json.loads(
                json.dumps(events[3]["vertexes"][0])
            )
            latest_open["started"] = (
                "2026-07-31T00:00:25.123456900Z"
            )
            latest_open["cached"] = True
            latest_open.pop("completed", None)
            latest_terminal = json.loads(json.dumps(latest_open))
            latest_terminal["completed"] = (
                "2026-07-31T00:00:55.000000001Z"
            )
            events.extend(
                [
                    {"vertexes": [latest_open]},
                    {"vertexes": [latest_terminal]},
                ]
            )
            self._write_events(progress, events)
            with contextlib.redirect_stderr(io.StringIO()):
                summary = verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            diagnostic = summary["v7_rawjson_diagnostic"]
            self.assertEqual(diagnostic["lifecycle_interval_count"], 7)
            self.assertEqual(
                diagnostic["maximum_intervals_per_digest"],
                3,
            )

            equivalent = root / "equivalent"
            equivalent.mkdir()
            metadata, progress, _ = self._write_evidence(equivalent)
            events = self._incrementalize(progress)
            duplicate = json.loads(
                json.dumps(events[4]["vertexes"][0])
            )
            duplicate["started"] = "2026-07-31T08:00:25+08:00"
            duplicate["completed"] = "2026-07-31T08:00:50+08:00"
            events.insert(5, {"vertexes": [duplicate]})
            self._write_events(progress, events)
            with contextlib.redirect_stderr(io.StringIO()):
                summary = verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(
                summary["v7_rawjson_diagnostic"][
                    "lifecycle_interval_count"
                ],
                6,
            )

            outside = root / "outside"
            outside.mkdir()
            metadata, progress, _ = self._write_evidence(outside)
            payload = json.loads(metadata.read_text(encoding="utf-8"))
            payload["buildx.build.provenance"]["metadata"][
                "buildFinishedOn"
            ] = "2026-07-31T00:01:00Z"
            metadata.write_text(
                json.dumps(payload, separators=(",", ":")),
                encoding="utf-8",
            )
            events = self._incrementalize(progress)
            events[4]["vertexes"][0]["completed"] = (
                "2026-07-31T00:01:00.000000100Z"
            )
            self._write_events(progress, events)
            with contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(verifier.V7BundleError) as raised:
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(
                raised.exception.failure_code,
                "NETWORK_VERTEX_LIFECYCLE_OUTSIDE_BUILD",
            )

    def test_name_changes_do_not_replace_structural_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, progress, _ = self._write_evidence(root)
            events = self._incrementalize(progress)
            events[1]["vertexes"][0]["name"] = "display name changed"
            events[2]["vertexes"][0]["name"] = "display name changed again"
            self._write_events(progress, events)
            with contextlib.redirect_stderr(io.StringIO()):
                summary = verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(
                summary["network_vertices"][0]["name_classification"],
                "exact",
            )

            events[0]["vertexes"][1]["name"] = (
                str(verifier.ROLE_SPECS[0]["marker"])
            )
            self._write_events(progress, events)
            with contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(verifier.V7BundleError) as raised:
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(
                raised.exception.failure_code,
                "NETWORK_VERTEX_DUPLICATE",
            )

    def test_orphan_and_invalid_base64_remain_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, progress, digests = self._write_evidence(root)
            events = self._incrementalize(progress)
            events.append(
                {
                    "logs": [
                        {
                            "vertex": digests[0],
                            "stream": 1,
                            "data": "not-base64!",
                            "timestamp": "2026-07-31T00:00:30Z",
                        }
                    ]
                }
            )
            self._write_events(progress, events)
            with contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(verifier.V7BundleError) as raised:
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(
                raised.exception.failure_code,
                "RAWJSON_LOG_BASE64_INVALID",
            )

            events[-1]["logs"][0]["data"] = ""
            events[-1]["logs"][0]["vertex"] = "sha256:" + ("f" * 64)
            self._write_events(progress, events)
            with contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(verifier.V7BundleError) as raised:
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(
                raised.exception.failure_code,
                "RAWJSON_ORPHAN_REFERENCE",
            )

    def test_status_lifecycle_uses_exact_nanoseconds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            metadata, progress, digests = self._write_evidence(
                Path(temporary)
            )
            events = self._incrementalize(progress)
            events.append(
                {
                    "statuses": [
                        {
                            "id": "status-1",
                            "vertex": digests[0],
                            "current": 1,
                            "timestamp": (
                                "2026-07-31T00:00:30.000000500Z"
                            ),
                            "started": (
                                "2026-07-31T00:00:30.000000900Z"
                            ),
                            "completed": (
                                "2026-07-31T00:00:30.000000100Z"
                            ),
                        }
                    ]
                }
            )
            self._write_events(progress, events)
            with contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(verifier.V7BundleError) as raised:
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(
                raised.exception.failure_code,
                "RAWJSON_LIFECYCLE_INVALID",
            )

    def test_dispatch_restores_after_success_failure_and_body_exception(
        self,
    ) -> None:
        frozen = {
            name: getattr(verifier._v6, name)
            for name in (
                "_initial_diagnostic",
                "_emit_diagnostic",
                "_strict_progress",
                "_provenance_build_window",
                "_validate_roles_and_logs",
                "validate_build_evidence",
            )
        }
        with tempfile.TemporaryDirectory() as temporary:
            metadata, progress, _ = self._write_evidence(Path(temporary))
            with contextlib.redirect_stderr(io.StringIO()):
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            for name, expected in frozen.items():
                self.assertIs(getattr(verifier._v6, name), expected)

            progress.write_text("{}\n", encoding="utf-8")
            with contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(verifier.V7BundleError):
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            for name, expected in frozen.items():
                self.assertIs(getattr(verifier._v6, name), expected)

        with self.assertRaisesRegex(RuntimeError, "body sentinel"):
            with verifier._patched_v6_incremental_contract():
                raise RuntimeError("body sentinel")
        for name, expected in frozen.items():
            self.assertIs(getattr(verifier._v6, name), expected)

    def test_diagnostic_is_bounded_and_does_not_expose_name_or_path(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, progress, _ = self._write_evidence(root)
            events = self._incrementalize(progress)
            sentinel = "PRIVATE_VERTEX_SENTINEL_53d1"
            events[1]["vertexes"][0]["name"] = sentinel
            events[3]["vertexes"][0]["cached"] = False
            self._write_events(progress, events)
            captured = io.StringIO()
            with contextlib.redirect_stderr(
                captured
            ), self.assertRaises(verifier.V7BundleError):
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            diagnostic = _diagnostic(captured.getvalue())
            self.assertEqual(diagnostic["verdict"], "fail")
            self.assertNotIn(sentinel, captured.getvalue())
            self.assertNotIn(str(progress), captured.getvalue())

    def test_copied_v7_v6_v3_v2_cli_chain_rejects_v6_drift_and_links(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, progress, _ = self._write_evidence(root)
            self._incrementalize(progress)
            copies = {
                "v7": root / "trusted-v7.py",
                "v6": root / "trusted-v6.py",
                "v3": root / "trusted-v3.py",
                "v2": root / "trusted-v2.py",
            }
            shutil.copyfile(Path(verifier.__file__), copies["v7"])
            shutil.copyfile(Path(v6.__file__), copies["v6"])
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
                    "NOTEAI_V6_BUNDLE_VERIFIER_PATH": str(copies["v6"]),
                    "NOTEAI_V3_BUNDLE_VERIFIER_PATH": str(copies["v3"]),
                    "NOTEAI_BASE_BUNDLE_VERIFIER_PATH": str(copies["v2"]),
                }
            )
            output = root / "summary.json"
            command = [
                sys.executable,
                str(copies["v7"]),
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
            result = subprocess.run(
                command,
                env=environment,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(
                "v7_rawjson_diagnostic",
                json.loads(output.read_text(encoding="utf-8")),
            )

            with copies["v6"].open("ab") as handle:
                handle.write(b"\n")
            output.unlink()
            result = subprocess.run(
                command,
                env=environment,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("frozen V6 bundle verifier hash drift", result.stderr)
            self.assertFalse(output.exists())

            shutil.copyfile(Path(v6.__file__), copies["v6"])
            hardlink = root / "trusted-v6-hardlink.py"
            os.link(copies["v6"], hardlink)
            result = subprocess.run(
                command,
                env=environment,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "frozen V6 bundle verifier file contract changed",
                result.stderr,
            )
            hardlink.unlink()

            copies["v6"].unlink()
            copies["v6"].symlink_to(Path(v6.__file__))
            result = subprocess.run(
                command,
                env=environment,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "frozen V6 bundle verifier file contract changed",
                result.stderr,
            )


if __name__ == "__main__":
    unittest.main()
