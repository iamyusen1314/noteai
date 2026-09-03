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

import verify_admin_dependency_cache_bundle_v6 as verifier  # noqa: E402


def _load_v3_fixture_module():
    path = ROOT / "tests" / "test_admin_dependency_cache_bundle_verifier_v3.py"
    spec = importlib.util.spec_from_file_location("_cache_bundle_v3_tests_v6", path)
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
    / "admin_dependency_cache_buildkit_v0.31.2_solvestatus_structural_projection.json"
)
SOURCE_PROJECTION = json.loads(
    SOURCE_PROJECTION_PATH.read_text(encoding="utf-8")
)


def _diagnostic(stderr: str) -> dict:
    lines = stderr.splitlines()
    if len(lines) != 1:
        raise AssertionError(f"unexpected diagnostic line count: {len(lines)}")
    prefix = "noteai_v6_progress_diagnostic="
    if not lines[0].startswith(prefix):
        raise AssertionError("missing V6 diagnostic prefix")
    return json.loads(lines[0][len(prefix) :])


class AdminDependencyCacheBundleVerifierV6Tests(unittest.TestCase):
    def _write_evidence(
        self,
        root: Path,
        *,
        dockerfile_kind: str = "prefix",
        cached: bool = True,
        names: list[str] | None = None,
        logs: dict[int, list[bytes]] | None = None,
    ) -> tuple[Path, Path, list[str]]:
        fixture = V3_FIXTURES.AdminDependencyCacheBundleVerifierV3Tests()
        metadata_path, progress_path = fixture._write_evidence(
            root,
            dockerfile_kind=dockerfile_kind,
        )
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        provenance = metadata["buildx.build.provenance"]
        build_config = provenance["buildConfig"]
        llb = build_config["llbDefinition"]
        platform = {"Architecture": "amd64", "OS": "linux"}
        for index, item in enumerate(llb):
            item["id"] = f"step{index}"
        for index in range(3):
            llb.append(
                {
                    "id": f"step{index + 3}",
                    "op": {
                        "Op": {"exec": {}},
                        "platform": platform,
                    },
                }
            )
        digests = [f"sha256:{index + 1:064x}" for index in range(3)]
        build_config["digestMapping"] = {
            digest: f"step{index + 3}"
            for index, digest in enumerate(digests)
        }
        source = provenance["metadata"][
            "https://mobyproject.org/buildkit@v1#metadata"
        ]["source"]
        base_lines = [7, 80]
        if dockerfile_kind == "full":
            base_lines.extend([83, 100])

        def location(*lines: int) -> dict:
            return {
                "locations": [
                    {
                        "ranges": [
                            {
                                "start": {"line": line},
                                "end": {"line": line},
                            }
                            for line in lines
                        ]
                    }
                ]
            }

        source["locations"] = {
            "step2": location(*base_lines),
            "step3": location(14),
            "step4": location(63),
            "step5": location(76),
        }
        metadata_path.write_text(
            json.dumps(metadata, separators=(",", ":")),
            encoding="utf-8",
        )

        selected_names = names or [
            str(spec["marker"])
            for spec in verifier.ROLE_SPECS
        ]
        events: list[dict] = [
            {
                "vertexes": [
                    {
                        "digest": digest,
                        "name": selected_names[index],
                        "started": "2026-07-31T00:00:00Z",
                        "completed": "2026-07-31T00:01:00Z",
                        "cached": cached,
                    }
                    for index, digest in enumerate(digests)
                ]
            }
        ]
        for index, chunks in (logs or {}).items():
            for chunk in chunks:
                events.append(
                    {
                        "logs": [
                            {
                                "vertex": digests[index],
                                "stream": 1,
                                "data": base64.b64encode(chunk).decode("ascii"),
                                "timestamp": "2026-07-31T00:00:30Z",
                            }
                        ]
                    }
                )
        progress_path.write_text(
            "".join(
                json.dumps(event, separators=(",", ":")) + "\n"
                for event in events
            ),
            encoding="utf-8",
        )
        return metadata_path, progress_path, digests

    def test_source_projection_is_truthfully_labeled_and_bound(self) -> None:
        self.assertEqual(
            SOURCE_PROJECTION["classification"],
            "SOURCE_PROVEN_SCHEMA_CONTRACT_NOT_V5_RUNTIME_EVIDENCE",
        )
        self.assertFalse(SOURCE_PROJECTION["actual_v5_runtime_metadata_retained"])
        self.assertFalse(SOURCE_PROJECTION["actual_v5_runtime_progress_retained"])
        self.assertEqual(
            SOURCE_PROJECTION["v6_binding_contract"]["ordered_chain"],
            [
                "SolveStatus.vertexes[].digest",
                "buildConfig.digestMapping[digest]",
                "llbDefinition[].id",
                "llbDefinition[].op.Op.exec",
                "metadata.source.locations[step-id]",
            ],
        )
        self.assertEqual(
            [
                role["dockerfile_run_start_line"]
                for role in SOURCE_PROJECTION["v6_binding_contract"][
                    "dependency_roles"
                ]
            ],
            [14, 63, 76],
        )

    def test_nested_rawjson_and_structural_binding_pass_for_both_targets(
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
                    original_progress = progress.read_bytes()
                    error = io.StringIO()
                    with contextlib.redirect_stderr(error):
                        summary = verifier.validate_build_evidence(
                            metadata,
                            progress,
                            dockerfile_kind=dockerfile_kind,
                            require_network_vertices_cached=True,
                        )
                    self.assertEqual(
                        summary["progress_sha256"],
                        hashlib.sha256(original_progress).hexdigest(),
                    )
                    self.assertEqual(summary["network_vertex_count"], 3)
                    self.assertTrue(summary["network_vertices_cached"])
                    self.assertEqual(
                        [item["vertex"] for item in summary["network_vertices"]],
                        digests,
                    )
                    self.assertEqual(
                        [
                            item["name_classification"]
                            for item in summary["network_vertices"]
                        ],
                        ["exact", "exact", "exact"],
                    )
                    diagnostic = summary["v6_rawjson_diagnostic"]
                    self.assertEqual(diagnostic["verdict"], "pass")
                    self.assertEqual(diagnostic["failure_code"], "NONE")
                    self.assertEqual(diagnostic["unique_vertex_digest_count"], 3)
                    self.assertIn(
                        "noteai_v6_progress_diagnostic=",
                        error.getvalue(),
                    )
                    self.assertEqual(progress.read_bytes(), original_progress)

    def test_decoded_logs_are_joined_across_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            metadata, progress, _ = self._write_evidence(
                Path(temporary),
                cached=False,
                logs={0: [b"Collec", b"ting package from pypi.org\n"]},
            )
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                summary = verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=False,
                )
            diagnostic = summary["v6_rawjson_diagnostic"]
            self.assertTrue(diagnostic["package_network_output_observed"])
            self.assertEqual(diagnostic["decoded_log_record_count"], 2)

            with contextlib.redirect_stderr(io.StringIO()), self.assertRaisesRegex(
                verifier.V6BundleError,
                "package-network output appeared",
            ) as raised:
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(
                raised.exception.failure_code,
                "PACKAGE_NETWORK_OUTPUT_OBSERVED",
            )

    def test_name_drift_requires_and_uses_structural_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            metadata, progress, _ = self._write_evidence(
                Path(temporary),
                names=[
                    "[prefix 4/6] RUN dependency one",
                    "[prefix 5/6] RUN dependency two",
                    "[prefix 6/6] RUN dependency three",
                ],
            )
            with contextlib.redirect_stderr(io.StringIO()):
                summary = verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(
                [
                    item["name_classification"]
                    for item in summary["network_vertices"]
                ],
                ["name_drift", "name_drift", "name_drift"],
            )

            payload = json.loads(metadata.read_text(encoding="utf-8"))
            payload["buildx.build.provenance"]["buildConfig"][
                "digestMapping"
            ].pop(next(iter(
                payload["buildx.build.provenance"]["buildConfig"][
                    "digestMapping"
                ]
            )))
            metadata.write_text(json.dumps(payload), encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaisesRegex(
                verifier.V6BundleError,
                "digest binding changed",
            ):
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )

    def test_duplicate_or_mismatched_name_identity_fails_closed(self) -> None:
        cases = (
            [
                verifier.ROLE_SPECS[0]["marker"],
                verifier.ROLE_SPECS[0]["marker"],
                verifier.ROLE_SPECS[2]["marker"],
            ],
            [
                verifier.ROLE_SPECS[1]["marker"],
                verifier.ROLE_SPECS[0]["marker"],
                verifier.ROLE_SPECS[2]["marker"],
            ],
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, names in enumerate(cases):
                with self.subTest(index=index):
                    target = root / str(index)
                    target.mkdir()
                    metadata, progress, _ = self._write_evidence(
                        target,
                        names=[str(name) for name in names],
                    )
                    with contextlib.redirect_stderr(
                        io.StringIO()
                    ), self.assertRaises(verifier.V6BundleError):
                        verifier.validate_build_evidence(
                            metadata,
                            progress,
                            dockerfile_kind="prefix",
                            require_network_vertices_cached=True,
                        )

    def test_flat_status_id_invalid_base64_and_uncached_replay_fail_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, progress, digests = self._write_evidence(root)
            cases = (
                (
                    [{"id": digests[0], "name": verifier.ROLE_SPECS[0]["marker"]}],
                    "RAWJSON_TOP_LEVEL_INVALID",
                ),
                (
                    [
                        {
                            "statuses": [
                                {
                                    "id": digests[0],
                                    "vertex": digests[0],
                                    "current": 0,
                                    "timestamp": "2026-07-31T00:00:30Z",
                                }
                            ]
                        }
                    ],
                    "RAWJSON_EMPTY",
                ),
                (
                    [
                        {
                            "vertexes": [
                                {
                                    "digest": digest,
                                    "name": verifier.ROLE_SPECS[index]["marker"],
                                    "completed": "2026-07-31T00:01:00Z",
                                    "cached": True,
                                }
                                for index, digest in enumerate(digests)
                            ],
                            "logs": [
                                {
                                    "vertex": digests[0],
                                    "stream": 1,
                                    "data": "not-base64!",
                                    "timestamp": "2026-07-31T00:00:30Z",
                                }
                            ],
                        }
                    ],
                    "RAWJSON_LOG_BASE64_INVALID",
                ),
            )
            for index, (events, expected_code) in enumerate(cases):
                with self.subTest(index=index):
                    progress.write_text(
                        "".join(
                            json.dumps(event, separators=(",", ":")) + "\n"
                            for event in events
                        ),
                        encoding="utf-8",
                    )
                    with contextlib.redirect_stderr(
                        io.StringIO()
                    ), self.assertRaises(verifier.V6BundleError) as raised:
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

            metadata, progress, _ = self._write_evidence(root, cached=False)
            with contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(verifier.V6BundleError) as raised:
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

    def test_hardlinked_input_and_leaky_diagnostic_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, progress, _ = self._write_evidence(root)
            progress_link = root / "progress-hardlink.rawjson"
            os.link(progress, progress_link)
            with contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(verifier.V6BundleError) as raised:
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(raised.exception.failure_code, "RAWJSON_FILE_INVALID")
            progress_link.unlink()

            sentinel = "RAW_PRIVATE_SENTINEL_9f61"
            events = [
                json.loads(line)
                for line in progress.read_text(encoding="utf-8").splitlines()
            ]
            events[0]["vertexes"][0]["name"] = sentinel
            progress.write_text(
                "".join(
                    json.dumps(event, separators=(",", ":")) + "\n"
                    for event in events
                ),
                encoding="utf-8",
            )
            captured = io.StringIO()
            with contextlib.redirect_stderr(captured):
                summary = verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(
                summary["network_vertices"][0]["name_classification"],
                "name_drift",
            )
            self.assertNotIn(sentinel, captured.getvalue())
            self.assertNotIn(str(progress), captured.getvalue())

    def test_legacy_view_is_private_removed_and_dispatch_is_restored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, progress, _ = self._write_evidence(root)
            legacy_root = root / "legacy"

            def controlled_mkdtemp(*, prefix: str) -> str:
                self.assertEqual(prefix, "noteai-v6-evidence-")
                legacy_root.mkdir(mode=0o700)
                return str(legacy_root)

            with mock.patch.object(
                verifier.tempfile,
                "mkdtemp",
                side_effect=controlled_mkdtemp,
            ), contextlib.redirect_stderr(io.StringIO()):
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertFalse(legacy_root.exists())
            self.assertIs(
                verifier._v3._base.validate_build_evidence,
                verifier._frozen_v3_validate_build_evidence,
            )
            with verifier._patched_base_validator():
                self.assertIs(
                    verifier._v3._base.validate_build_evidence,
                    verifier.validate_build_evidence,
                )
            self.assertIs(
                verifier._v3._base.validate_build_evidence,
                verifier._frozen_v3_validate_build_evidence,
            )

    def test_structural_binding_fails_closed_on_each_identity_edge(self) -> None:
        def mutate_cross_line(payload: dict, _digests: list[str]) -> None:
            ranges = payload["buildx.build.provenance"]["metadata"][
                "https://mobyproject.org/buildkit@v1#metadata"
            ]["source"]["locations"]["step3"]["locations"][0]["ranges"]
            ranges[0] = {
                "start": {"line": 13},
                "end": {"line": 14},
            }

        def mutate_ambiguous_location(
            payload: dict,
            _digests: list[str],
        ) -> None:
            locations = payload["buildx.build.provenance"]["metadata"][
                "https://mobyproject.org/buildkit@v1#metadata"
            ]["source"]["locations"]
            locations["step4"]["locations"][0]["ranges"].append(
                {
                    "start": {"line": 14},
                    "end": {"line": 14},
                }
            )

        def mutate_non_exec(payload: dict, _digests: list[str]) -> None:
            llb = payload["buildx.build.provenance"]["buildConfig"][
                "llbDefinition"
            ]
            llb[3]["op"]["Op"] = {"source": {}}

        def mutate_union(payload: dict, _digests: list[str]) -> None:
            llb = payload["buildx.build.provenance"]["buildConfig"][
                "llbDefinition"
            ]
            llb[3]["op"]["Op"]["source"] = {}

        def mutate_platform(payload: dict, _digests: list[str]) -> None:
            llb = payload["buildx.build.provenance"]["buildConfig"][
                "llbDefinition"
            ]
            llb[3]["op"]["platform"] = {
                "Architecture": "arm64",
                "OS": "linux",
            }

        def mutate_two_digests(
            payload: dict,
            _digests: list[str],
        ) -> None:
            payload["buildx.build.provenance"]["buildConfig"][
                "digestMapping"
            ]["sha256:" + ("9" * 64)] = "step3"

        def mutate_missing_vertex(
            payload: dict,
            digests: list[str],
        ) -> None:
            mapping = payload["buildx.build.provenance"]["buildConfig"][
                "digestMapping"
            ]
            del mapping[digests[0]]
            mapping["sha256:" + ("8" * 64)] = "step3"

        def mutate_metadata_type(
            payload: dict,
            _digests: list[str],
        ) -> None:
            payload["buildx.build.provenance"]["metadata"] = "invalid"

        cases = (
            (
                mutate_cross_line,
                "PROVENANCE_ROLE_LOCATION_AMBIGUOUS",
            ),
            (
                mutate_ambiguous_location,
                "PROVENANCE_ROLE_LOCATION_AMBIGUOUS",
            ),
            (mutate_non_exec, "PROVENANCE_ROLE_NOT_EXEC"),
            (mutate_union, "PROVENANCE_ROLE_NOT_EXEC"),
            (mutate_platform, "PROVENANCE_ROLE_PLATFORM_INVALID"),
            (mutate_two_digests, "PROVENANCE_ROLE_DIGEST_AMBIGUOUS"),
            (mutate_missing_vertex, "PROVENANCE_ROLE_VERTEX_MISSING"),
            (mutate_metadata_type, "PROVENANCE_LOCATION_INVALID"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, (mutator, expected_code) in enumerate(cases):
                with self.subTest(index=index, expected_code=expected_code):
                    target = root / str(index)
                    target.mkdir()
                    metadata, progress, digests = self._write_evidence(target)
                    payload = json.loads(
                        metadata.read_text(encoding="utf-8")
                    )
                    mutator(payload, digests)
                    metadata.write_text(
                        json.dumps(payload, separators=(",", ":")),
                        encoding="utf-8",
                    )
                    with contextlib.redirect_stderr(
                        io.StringIO()
                    ), self.assertRaises(verifier.V6BundleError) as raised:
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

    def test_orphan_lifecycle_and_diagnostic_roles_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, progress, digests = self._write_evidence(root)
            events = [
                json.loads(line)
                for line in progress.read_text(encoding="utf-8").splitlines()
            ]
            events.append(
                {
                    "statuses": [
                        {
                            "id": digests[0],
                            "vertex": "sha256:" + ("f" * 64),
                            "current": 1,
                            "timestamp": "2026-07-31T00:00:30Z",
                        }
                    ]
                }
            )
            progress.write_text(
                "".join(
                    json.dumps(event, separators=(",", ":")) + "\n"
                    for event in events
                ),
                encoding="utf-8",
            )
            with contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(verifier.V6BundleError) as raised:
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

            lifecycle_cases = (
                (
                    lambda vertex: vertex.pop("completed"),
                    "NETWORK_VERTEX_INCOMPLETE",
                ),
                (
                    lambda vertex: vertex.pop("started"),
                    "NETWORK_VERTEX_LIFECYCLE_INCOMPLETE",
                ),
                (
                    lambda vertex: vertex.__setitem__("completed", "yes"),
                    "RAWJSON_LIFECYCLE_INVALID",
                ),
                (
                    lambda vertex: vertex.__setitem__(
                        "completed",
                        "2026-07-31T00:02:00Z",
                    ),
                    "NETWORK_VERTEX_LIFECYCLE_OUTSIDE_BUILD",
                ),
            )
            for index, (mutator, expected_code) in enumerate(
                lifecycle_cases
            ):
                with self.subTest(index=index, expected_code=expected_code):
                    metadata, progress, _ = self._write_evidence(root)
                    events = [
                        json.loads(line)
                        for line in progress.read_text(
                            encoding="utf-8"
                        ).splitlines()
                    ]
                    mutator(events[0]["vertexes"][0])
                    progress.write_text(
                        "".join(
                            json.dumps(event, separators=(",", ":")) + "\n"
                            for event in events
                        ),
                        encoding="utf-8",
                    )
                    captured = io.StringIO()
                    with contextlib.redirect_stderr(
                        captured
                    ), self.assertRaises(verifier.V6BundleError) as raised:
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
                    diagnostic = _diagnostic(captured.getvalue())
                    if expected_code.startswith("NETWORK_VERTEX_"):
                        self.assertNotIn(
                            "unresolved",
                            {
                                role["classification"]
                                for role in diagnostic["roles"]
                            },
                        )

            malformed_times = (
                "2026-07-31 00:00:30Z",
                "20260731T000030Z",
                "2026-W31-4T00:00:30Z",
                "2026-07-31T00:00:30,5Z",
                "2026-07-31T00:00:30+08:00:00",
            )
            for index, malformed in enumerate(malformed_times):
                with self.subTest(
                    malformed_index=index,
                    malformed=malformed,
                ):
                    metadata, progress, _ = self._write_evidence(root)
                    events = [
                        json.loads(line)
                        for line in progress.read_text(
                            encoding="utf-8"
                        ).splitlines()
                    ]
                    events[0]["vertexes"][0]["completed"] = malformed
                    progress.write_text(
                        "".join(
                            json.dumps(event, separators=(",", ":")) + "\n"
                            for event in events
                        ),
                        encoding="utf-8",
                    )
                    with contextlib.redirect_stderr(
                        io.StringIO()
                    ), self.assertRaises(verifier.V6BundleError) as raised:
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

    def test_frozen_summary_and_original_evidence_are_bound(self) -> None:
        original_frozen = verifier._frozen_v3_validate_build_evidence
        cases = (
            (
                lambda summary: summary.__setitem__(
                    "progress_sha256",
                    "0" * 64,
                ),
                "FROZEN_V3_PROGRESS_HASH_CHANGED",
            ),
            (
                lambda summary: summary.__setitem__(
                    "metadata_sha256",
                    "0" * 64,
                ),
                "FROZEN_V3_METADATA_HASH_CHANGED",
            ),
            (
                lambda summary: summary.__setitem__(
                    "network_vertices",
                    [],
                ),
                "FROZEN_V3_NETWORK_SUMMARY_CHANGED",
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, (mutator, expected_code) in enumerate(cases):
                with self.subTest(index=index, expected_code=expected_code):
                    target = root / str(index)
                    target.mkdir()
                    metadata, progress, _ = self._write_evidence(target)

                    def changed_summary(*args, **kwargs):
                        summary = original_frozen(*args, **kwargs)
                        mutator(summary)
                        return summary

                    with mock.patch.object(
                        verifier,
                        "_frozen_v3_validate_build_evidence",
                        side_effect=changed_summary,
                    ), contextlib.redirect_stderr(
                        io.StringIO()
                    ), self.assertRaises(verifier.V6BundleError) as raised:
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

            metadata, progress, _ = self._write_evidence(root)

            def mutate_original(*args, **kwargs):
                summary = original_frozen(*args, **kwargs)
                progress.write_bytes(progress.read_bytes() + b"\n")
                return summary

            with mock.patch.object(
                verifier,
                "_frozen_v3_validate_build_evidence",
                side_effect=mutate_original,
            ), contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(verifier.V6BundleError) as raised:
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(
                raised.exception.failure_code,
                "ORIGINAL_EVIDENCE_CHANGED",
            )

    def test_cleanup_and_dispatch_restore_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, progress, _ = self._write_evidence(root)
            legacy_root = root / "legacy-failure"

            def controlled_mkdtemp(*, prefix: str) -> str:
                self.assertEqual(prefix, "noteai-v6-evidence-")
                legacy_root.mkdir(mode=0o700)
                return str(legacy_root)

            def reject_after_permissions(
                metadata_path: Path,
                progress_path: Path,
                **_kwargs,
            ):
                for path in (metadata_path, progress_path):
                    state = os.lstat(path)
                    self.assertEqual(state.st_nlink, 1)
                    self.assertEqual(state.st_mode & 0o777, 0o600)
                raise verifier._v3.BundleError("private sentinel")

            captured = io.StringIO()
            with mock.patch.object(
                verifier.tempfile,
                "mkdtemp",
                side_effect=controlled_mkdtemp,
            ), mock.patch.object(
                verifier,
                "_frozen_v3_validate_build_evidence",
                side_effect=reject_after_permissions,
            ), contextlib.redirect_stderr(
                captured
            ), self.assertRaisesRegex(
                verifier._v3.BundleError,
                "^frozen V3 evidence validation failed$",
            ):
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertFalse(legacy_root.exists())
            self.assertNotIn("private sentinel", captured.getvalue())

            with self.assertRaisesRegex(RuntimeError, "body failed"):
                with verifier._patched_base_validator():
                    raise RuntimeError("body failed")
            self.assertIs(
                verifier._v3._base.validate_build_evidence,
                verifier._frozen_v3_validate_build_evidence,
            )

            metadata, progress, _ = self._write_evidence(root)
            leaked_root: Path | None = None
            real_mkdtemp = tempfile.mkdtemp

            def capture_mkdtemp(*, prefix: str) -> str:
                nonlocal leaked_root
                leaked_root = Path(
                    real_mkdtemp(
                        prefix=prefix,
                        dir=root,
                    )
                )
                return str(leaked_root)

            with mock.patch.object(
                verifier.tempfile,
                "mkdtemp",
                side_effect=capture_mkdtemp,
            ), mock.patch.object(
                verifier.shutil,
                "rmtree",
                side_effect=OSError("cleanup sentinel"),
            ), contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(verifier.V6BundleError) as raised:
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(
                raised.exception.failure_code,
                "LEGACY_EVIDENCE_CLEANUP_FAILED",
            )
            self.assertIsNotNone(leaked_root)
            shutil.rmtree(leaked_root)

            metadata, progress, _ = self._write_evidence(root)
            symlink = root / "progress-symlink.rawjson"
            symlink.symlink_to(progress.name)
            with contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(verifier.V6BundleError) as raised:
                verifier.validate_build_evidence(
                    metadata,
                    symlink,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            self.assertEqual(raised.exception.failure_code, "RAWJSON_FILE_INVALID")

    def test_cli_failure_diagnostic_is_bounded_and_secret_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, progress, _ = self._write_evidence(root)
            sentinel = "CLI_PRIVATE_SENTINEL_82bd"
            events = [
                json.loads(line)
                for line in progress.read_text(encoding="utf-8").splitlines()
            ]
            events[0]["vertexes"][0]["name"] = sentinel
            events.append(
                {
                    "logs": [
                        {
                            "vertex": events[0]["vertexes"][0]["digest"],
                            "stream": 1,
                            "data": sentinel,
                            "timestamp": "2026-07-31T00:00:30Z",
                        }
                    ]
                }
            )
            progress.write_text(
                "".join(
                    json.dumps(event, separators=(",", ":")) + "\n"
                    for event in events
                ),
                encoding="utf-8",
            )
            output = root / "must-not-exist.json"
            environment = os.environ.copy()
            environment["NOTEAI_V3_BUNDLE_VERIFIER_PATH"] = str(
                ROOT
                / "tools"
                / "verify_admin_dependency_cache_bundle_v3.py"
            )
            environment["NOTEAI_BASE_BUNDLE_VERIFIER_PATH"] = str(
                ROOT / "tools" / "verify_admin_dependency_cache_bundle.py"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(
                        ROOT
                        / "tools"
                        / "verify_admin_dependency_cache_bundle_v6.py"
                    ),
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
                ],
                env=environment,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(
                result.stdout,
                "FAIL: BuildKit log data base64 invalid\n",
            )
            diagnostic = _diagnostic(result.stderr)
            self.assertEqual(
                diagnostic["failure_code"],
                "RAWJSON_LOG_BASE64_INVALID",
            )
            self.assertNotIn(sentinel, result.stdout + result.stderr)
            self.assertNotIn(str(progress), result.stdout + result.stderr)
            self.assertFalse(output.exists())

    def test_copied_v6_v3_v2_cli_trust_chain_passes_and_rejects_drift(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, progress, _ = self._write_evidence(root)
            v6_copy = root / "trusted-v6.py"
            v3_copy = root / "trusted-v3.py"
            v2_copy = root / "trusted-v2.py"
            shutil.copyfile(Path(verifier.__file__), v6_copy)
            shutil.copyfile(
                ROOT / "tools" / "verify_admin_dependency_cache_bundle_v3.py",
                v3_copy,
            )
            shutil.copyfile(
                ROOT / "tools" / "verify_admin_dependency_cache_bundle.py",
                v2_copy,
            )
            environment = os.environ.copy()
            environment["NOTEAI_V3_BUNDLE_VERIFIER_PATH"] = str(v3_copy)
            environment["NOTEAI_BASE_BUNDLE_VERIFIER_PATH"] = str(v2_copy)
            output = root / "summary.json"
            command = [
                sys.executable,
                str(v6_copy),
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
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8"))[
                    "network_vertex_count"
                ],
                3,
            )
            with v2_copy.open("ab") as handle:
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
            self.assertIn(
                "frozen V2 bundle verifier hash drift",
                result.stderr,
            )
            self.assertFalse(output.exists())
            shutil.copyfile(
                ROOT / "tools" / "verify_admin_dependency_cache_bundle.py",
                v2_copy,
            )
            with v3_copy.open("ab") as handle:
                handle.write(b"\n")
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
                "frozen V3 bundle verifier hash drift",
                result.stderr,
            )
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
