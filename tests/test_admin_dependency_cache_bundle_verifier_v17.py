from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_bundle_v17 as verifier  # noqa: E402


def _load_v11_tests():
    path = ROOT / "tests" / "test_admin_dependency_cache_bundle_verifier_v11.py"
    spec = importlib.util.spec_from_file_location("_v17_v11_fixtures", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load V11 cache fixtures")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V11_TESTS = _load_v11_tests()
SOURCE_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "admin_dependency_cache_v17_frontend_lifecycle_and_localstate_projection.json"
)


class AdminDependencyCacheBundleVerifierV17Tests(unittest.TestCase):
    def _fixture(self):
        return V11_TESTS.AdminDependencyCacheBundleVerifierV11Tests()

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
    def _write_command_envelope(path: Path, phase: str) -> None:
        path.write_text(
            json.dumps(
                {
                    "schema_version": (
                        "noteai.admin-dependency-cache-command-envelope.v17"
                    ),
                    "phase": phase,
                    "started": "2026-07-30T23:59:59.000000000Z",
                    "completed": "2026-07-31T00:01:01.000000000Z",
                },
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        path.chmod(0o600)

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

    def _write_git_evidence(
        self,
        root: Path,
        *,
        target: str,
        cached: bool,
    ) -> tuple[Path, Path, Path, str]:
        metadata, progress, digests, _child = self._fixture()._write_evidence(
            root,
            target=target,
            cached=cached,
        )
        payload = self._read_json(metadata)
        provenance = payload["buildx.build.provenance"]
        build_config = provenance["buildConfig"]
        llb = build_config["llbDefinition"]
        source = provenance["metadata"][
            "https://mobyproject.org/buildkit@v1#metadata"
        ]["source"]
        git_step = next(item for item in llb if item["id"] == "step2")
        git_step["op"]["Op"]["source"] = {
            "identifier": verifier.GIT_SOURCE_IDENTIFIER,
            "attrs": dict(verifier.GIT_SOURCE_ATTRS),
        }
        git_digest = "sha256:" + ("7" * 64)
        build_config["digestMapping"][git_digest] = "step2"
        copy_digest = "sha256:" + ("6" * 64)
        llb.append(
            {
                "id": "step7",
                "inputs": ["step4:0", "step2:0"],
                "op": {
                    "Op": {
                        "file": {
                            "actions": copy.deepcopy(
                                verifier.EXPECTED_COPY_ACTIONS
                            )
                        }
                    }
                },
            }
        )
        next(item for item in llb if item["id"] == "step5")["inputs"] = [
            "step7:0"
        ]
        build_config["digestMapping"][copy_digest] = "step7"
        source["locations"]["step7"] = self._location(
            verifier.REQUIREMENTS_COPY_LINE
        )
        self._write_json(metadata, payload)

        events = self._read_events(progress)
        updates = (
            {
                "digest": copy_digest,
                "name": "COPY requirements",
                "inputs": [digests[1], git_digest],
            },
            {
                "digest": copy_digest,
                "name": "COPY requirements",
                "started": "2026-07-31T00:00:05Z",
            },
            {
                "digest": copy_digest,
                "name": "COPY requirements",
                "started": "2026-07-31T00:00:05Z",
                "completed": "2026-07-31T00:00:18Z",
                **({"cached": True} if cached else {}),
            },
        )
        for event, update in zip(events[:3], updates):
            event["vertexes"].append(update)
        git_updates = (
            {
                "digest": git_digest,
                "name": "load git source",
            },
            {
                "digest": git_digest,
                "name": "load git source",
                "started": "2026-07-30T23:59:59.500000000Z",
            },
            {
                "digest": git_digest,
                "name": "load git source",
                "started": "2026-07-30T23:59:59.500000000Z",
                "completed": "2026-07-31T00:00:04Z",
            },
        )
        for event, update in zip(events[:3], git_updates):
            event["vertexes"].append(update)
        for event in events:
            for vertex in event.get("vertexes", []):
                if vertex.get("digest") == digests[2] and "started" not in vertex:
                    vertex["inputs"] = [copy_digest]
                    break
        self._write_events(progress, events)
        command_envelope = root / "command-envelope.json"
        phase = (
            "producer"
            if target == verifier._v13.EXPORT_TARGET
            else "import"
        )
        self._write_command_envelope(command_envelope, phase)
        return metadata, progress, command_envelope, copy_digest

    def test_source_fixture_binds_git_identity_contract(self) -> None:
        self.assertEqual(
            hashlib.sha256(SOURCE_FIXTURE.read_bytes()).hexdigest(),
            verifier.SOURCE_IDENTITY_FIXTURE_SHA256,
        )
        fixture = self._read_json(SOURCE_FIXTURE)
        self.assertEqual(
            fixture["classification"],
            "SOURCE_PROVEN_POLICY_NOT_V16_RUNTIME_EVIDENCE",
        )
        self.assertEqual(
            fixture["fixed_input"]["canonical_git_context_query"],
            verifier.GIT_CONTEXT_QUERY,
        )
        self.assertEqual(
            fixture["fixed_input"]["canonical_git_context_query_sha256"],
            hashlib.sha256(verifier.GIT_CONTEXT_QUERY.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(
            fixture["expected_local_state"]["allowed_keys"],
            ["DockerfilePath", "LocalPath", "Target"],
        )
        self.assertEqual(
            fixture["expected_local_state"]["dockerfile_path_policy"],
            "EXACT_STDIN_DASH_ONLY",
        )
        self.assertTrue(
            fixture["lifecycle_policy"][
                "git_start_before_provenance_start_allowed"
            ]
        )
        self.assertTrue(
            fixture["lifecycle_policy"][
                "network_exec_predicate_remains_frozen"
            ]
        )
        self.assertFalse(
            fixture["claims"][
                "source_review_proves_git_interval_runtime_order"
            ]
        )
        self.assertFalse(
            fixture["limitations"][
                "v17_external_run_has_occurred"
            ]
        )

    def test_producer_passes_original_git_identity_then_frozen_v13_projection(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, progress, envelope, copy_digest = self._write_git_evidence(
                root,
                target=verifier._v13.EXPORT_TARGET,
                cached=False,
            )
            original_metadata = metadata.read_bytes()
            original_progress = progress.read_bytes()
            identity_output = root / "identity.json"
            lifecycle_output = root / "git-lifecycle.json"
            with contextlib.redirect_stderr(io.StringIO()):
                summary = verifier.validate_build_evidence(
                    metadata,
                    progress,
                    envelope,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=False,
                    identity_output_path=identity_output,
                    lifecycle_diagnostic_output_path=lifecycle_output,
                )
            lifecycle = self._read_json(lifecycle_output)
            lifecycle_mode = stat.S_IMODE(lifecycle_output.stat().st_mode)
        self.assertEqual(
            summary["schema_version"],
            "noteai.admin-dependency-cache-build.v17",
        )
        self.assertEqual(
            summary["metadata_sha256"],
            hashlib.sha256(original_metadata).hexdigest(),
        )
        self.assertEqual(
            summary["progress_sha256"],
            hashlib.sha256(original_progress).hexdigest(),
        )
        self.assertEqual(
            summary["identity_chain"]["source"]["identifier"],
            verifier.GIT_SOURCE_IDENTIFIER,
        )
        self.assertEqual(
            summary["identity_chain"]["requirements_copy"][
                "vertex_digest"
            ],
            copy_digest,
        )
        self.assertEqual(
            summary["identity_chain"]["runtime_pip"][
                "direct_parent_step_id"
            ],
            "step7",
        )
        self.assertTrue(
            verifier.SHA256_RE.fullmatch(
                summary["legacy_compatibility_metadata_sha256"]
            )
        )
        self.assertTrue(
            verifier.SHA256_RE.fullmatch(
                summary["legacy_v13_verdict_sha256"]
            )
        )
        self.assertTrue(
            verifier.SHA256_RE.fullmatch(
                summary["legacy_v13_compatibility_projection_sha256"]
            )
        )
        self.assertTrue(
            summary["legacy_v13_execution_boundary"][
                "legacy_verdict_transformed_for_v17_summary"
            ]
        )
        self.assertTrue(lifecycle["predicate"]["passed"])
        self.assertLess(
            lifecycle["intervals"][0]["started"],
            lifecycle["provenance_window"]["started"],
        )
        self.assertEqual(lifecycle_mode, 0o600)

    def test_git_lifecycle_failures_leave_bounded_secret_free_diagnostic(
        self,
    ) -> None:
        cases = (
            ("missing", "GIT_SOURCE_COMPLETION_MISSING"),
            ("late", "GIT_SOURCE_COMPLETES_AFTER_PROVENANCE"),
            ("before-command", "GIT_SOURCE_OUTSIDE_COMMAND"),
        )
        for case, diagnostic_code in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                metadata, progress, envelope, _copy = self._write_git_evidence(
                    root,
                    target=verifier._v13.EXPORT_TARGET,
                    cached=False,
                )
                events = self._read_events(progress)
                for event in events:
                    for vertex in event.get("vertexes", []):
                        if vertex.get("digest") != "sha256:" + ("7" * 64):
                            continue
                        if case == "missing":
                            vertex.pop("completed", None)
                        elif case == "late" and "completed" in vertex:
                            vertex["completed"] = (
                                "2026-07-31T00:01:00.500000000Z"
                            )
                        elif case == "before-command" and "started" in vertex:
                            vertex["started"] = (
                                "2026-07-30T23:59:58.500000000Z"
                            )
                self._write_events(progress, events)
                diagnostic = root / "git-lifecycle.json"
                with contextlib.redirect_stderr(
                    io.StringIO()
                ), self.assertRaises(verifier.V17BundleError) as raised:
                    verifier._identity_projection(
                        metadata,
                        progress,
                        envelope,
                        dockerfile_kind="prefix",
                        require_cached=False,
                        lifecycle_diagnostic_output_path=diagnostic,
                    )
                self.assertEqual(
                    raised.exception.failure_code,
                    "NETWORK_VERTEX_LIFECYCLE_OUTSIDE_BUILD",
                )
                retained = diagnostic.read_bytes()
                payload = json.loads(retained)
                self.assertEqual(payload["failure_code"], diagnostic_code)
                self.assertLessEqual(len(retained), 16 * 1024)
                self.assertEqual(stat.S_IMODE(diagnostic.stat().st_mode), 0o600)
                self.assertEqual(diagnostic.stat().st_nlink, 1)
                self.assertNotIn(b"github.com", retained)
                self.assertNotIn(verifier.GIT_CONTEXT_QUERY.encode(), retained)

    def test_network_exec_lifecycle_remains_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, progress, envelope, _copy = self._write_git_evidence(
                root,
                target=verifier._v13.EXPORT_TARGET,
                cached=False,
            )
            events = self._read_events(progress)
            for event in events:
                for vertex in event.get("vertexes", []):
                    if (
                        isinstance(vertex.get("name"), str)
                        and vertex["name"].startswith("pip install")
                        and vertex.get("started")
                        == "2026-07-31T00:00:05Z"
                    ):
                        vertex["started"] = (
                            "2026-07-30T23:59:59.500000000Z"
                        )
            self._write_events(progress, events)
            diagnostic = root / "git-lifecycle.json"
            with contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(verifier.V17BundleError) as raised:
                verifier._identity_projection(
                    metadata,
                    progress,
                    envelope,
                    dockerfile_kind="prefix",
                    require_cached=False,
                    lifecycle_diagnostic_output_path=diagnostic,
                )
            self.assertEqual(
                raised.exception.failure_code,
                "NETWORK_VERTEX_LIFECYCLE_OUTSIDE_BUILD",
            )
            self.assertEqual(self._read_json(diagnostic)["verdict"], "pass")

    def test_lifecycle_reread_detects_progress_toctou(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, progress, envelope, _copy = self._write_git_evidence(
                root,
                target=verifier._v13.EXPORT_TARGET,
                cached=False,
            )
            original_regular_bytes = verifier._v13._regular_bytes
            progress_reads = 0

            def changed_progress(path, **kwargs):
                nonlocal progress_reads
                payload = original_regular_bytes(path, **kwargs)
                if Path(path) == progress:
                    progress_reads += 1
                    if progress_reads == 2:
                        return payload + b"\n"
                return payload

            diagnostic = root / "git-lifecycle.json"
            with mock.patch.object(
                verifier._v13,
                "_regular_bytes",
                side_effect=changed_progress,
            ), contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(verifier.V17BundleError) as raised:
                verifier._identity_projection(
                    metadata,
                    progress,
                    envelope,
                    dockerfile_kind="prefix",
                    require_cached=False,
                    lifecycle_diagnostic_output_path=diagnostic,
                )
            self.assertEqual(
                raised.exception.failure_code,
                "V17_EVIDENCE_CHANGED_DURING_VALIDATION",
            )
            self.assertTrue(diagnostic.is_file())

    def test_original_identity_rejects_local_source_and_copy_or_parent_drift(
        self,
    ) -> None:
        cases = (
            (
                lambda payload: payload["buildx.build.provenance"][
                    "buildConfig"
                ]["llbDefinition"][2]["op"]["Op"].__setitem__(
                    "source",
                    {
                        "identifier": "local://context",
                        "attrs": {"local.session": "forbidden"},
                    },
                ),
                "V17_LOCAL_MAIN_CONTEXT_PRESENT",
            ),
            (
                lambda payload: next(
                    item
                    for item in payload["buildx.build.provenance"][
                        "buildConfig"
                    ]["llbDefinition"]
                    if item["id"] == "step7"
                )["op"]["Op"]["file"]["actions"][0]["Action"]["copy"].__setitem__(
                    "src", "/model/other.txt"
                ),
                "V17_REQUIREMENTS_COPY_INVALID",
            ),
            (
                lambda payload: next(
                    item
                    for item in payload["buildx.build.provenance"][
                        "buildConfig"
                    ]["llbDefinition"]
                    if item["id"] == "step5"
                ).__setitem__("inputs", ["step4:0"]),
                "V17_RUNTIME_PIP_PARENT_INVALID",
            ),
            (
                lambda payload: next(
                    item
                    for item in payload["buildx.build.provenance"][
                        "buildConfig"
                    ]["llbDefinition"]
                    if item["id"] == "step7"
                )["op"].__setitem__(
                    "platform",
                    {"Architecture": "amd64", "OS": "linux"},
                ),
                "V17_REQUIREMENTS_COPY_INVALID",
            ),
            (
                lambda payload: next(
                    item
                    for item in payload["buildx.build.provenance"][
                        "buildConfig"
                    ]["llbDefinition"]
                    if item["id"] == "step5"
                )["op"]["platform"].__setitem__(
                    "Architecture",
                    "arm64",
                ),
                "PROVENANCE_ROLE_NOT_EXEC",
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, progress, envelope, _copy = self._write_git_evidence(
                root / "base",
                target=verifier._v13.EXPORT_TARGET,
                cached=False,
            )
            original = self._read_json(metadata)
            for index, (mutate, expected_code) in enumerate(cases):
                with self.subTest(index=index):
                    candidate = copy.deepcopy(original)
                    mutate(candidate)
                    path = root / f"candidate-{index}.json"
                    self._write_json(path, candidate)
                    with contextlib.redirect_stderr(
                        io.StringIO()
                    ), self.assertRaises(verifier.V17BundleError) as raised:
                        verifier._identity_projection(
                            path,
                            progress,
                            envelope,
                            dockerfile_kind="prefix",
                            require_cached=False,
                            lifecycle_diagnostic_output_path=(
                                root / f"git-lifecycle-{index}.json"
                            ),
                        )
                    self.assertEqual(
                        raised.exception.failure_code,
                        expected_code,
                    )

    def test_copy_interval_predicate_is_all_intervals_not_latest_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, progress, envelope, copy_digest = self._write_git_evidence(
                root,
                target=verifier._v13.IMPORT_TARGET,
                cached=True,
            )
            events = self._read_events(progress)
            for event in events:
                for vertex in event.get("vertexes", []):
                    if (
                        vertex.get("digest") == copy_digest
                        and "completed" in vertex
                    ):
                        vertex.pop("cached", None)
            self._write_events(progress, events)
            with contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(verifier.V17BundleError) as raised:
                verifier._identity_projection(
                    metadata,
                    progress,
                    envelope,
                    dockerfile_kind="prefix",
                    require_cached=True,
                    lifecycle_diagnostic_output_path=(
                        root / "git-lifecycle.json"
                    ),
                )
        self.assertEqual(
            raised.exception.failure_code,
            "V17_REQUIREMENTS_COPY_CACHE_PREDICATE_FAILED",
        )

    def test_progress_input_omission_is_nonbinding_but_explicit_drift_fails(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, progress, envelope, copy_digest = self._write_git_evidence(
                root,
                target=verifier._v13.EXPORT_TARGET,
                cached=False,
            )
            events = self._read_events(progress)
            for event in events:
                for vertex in event.get("vertexes", []):
                    if (
                        vertex.get("digest") == copy_digest
                        or vertex.get("inputs") == [copy_digest]
                    ):
                        vertex.pop("inputs", None)
            self._write_events(progress, events)
            identity, _roles = verifier._identity_projection(
                metadata,
                progress,
                envelope,
                dockerfile_kind="prefix",
                require_cached=False,
                lifecycle_diagnostic_output_path=(
                    root / "git-lifecycle-first.json"
                ),
            )
            self.assertTrue(
                identity["requirements_copy"][
                    "omission_only_is_nonbinding"
                ]
            )
            self.assertTrue(
                identity["runtime_pip"]["omission_only_is_nonbinding"]
            )

            drifted = self._read_events(progress)
            for event in drifted:
                for vertex in event.get("vertexes", []):
                    if vertex.get("digest") == copy_digest:
                        vertex["inputs"] = [
                            "sha256:" + ("f" * 64),
                            "sha256:" + ("e" * 64),
                        ]
                        break
                else:
                    continue
                break
            self._write_events(progress, drifted)
            with contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(verifier.V17BundleError) as raised:
                verifier._identity_projection(
                    metadata,
                    progress,
                    envelope,
                    dockerfile_kind="prefix",
                    require_cached=False,
                    lifecycle_diagnostic_output_path=(
                        root / "git-lifecycle-second.json"
                    ),
                )
        self.assertEqual(
            raised.exception.failure_code,
            "V17_PROGRESS_INPUT_INVALID",
        )

    def test_pair_requires_same_source_copy_pip_and_full_cache_predicates(
        self,
    ) -> None:
        def interval(cached: bool) -> dict:
            return {
                "interval_count": 1,
                "completed_interval_count": 1,
                "cached_interval_count": int(cached),
                "noncached_interval_count": int(not cached),
            }

        digests = {
            "source": "sha256:" + ("1" * 64),
            "requirements_copy": "sha256:" + ("2" * 64),
            "runtime_pip": "sha256:" + ("3" * 64),
        }

        def summary(*, producer: bool) -> dict:
            cached = not producer
            identity = {
                "source": {"vertex_digest": digests["source"]},
                "requirements_copy": {
                    "vertex_digest": digests["requirements_copy"],
                    "interval": interval(cached),
                },
                "runtime_pip": {
                    "vertex_digest": digests["runtime_pip"],
                    "interval": interval(cached),
                },
            }
            return {
                "schema_version": "noteai.admin-dependency-cache-build.v17",
                "target": (
                    verifier._v13.EXPORT_TARGET
                    if producer
                    else verifier._v13.IMPORT_TARGET
                ),
                "identity_chain": identity,
                "network_vertices": [interval(cached)],
            }

        producer = summary(producer=True)
        consumer = summary(producer=False)
        self.assertEqual(
            verifier.classify_pair(producer, consumer)["classification"],
            "SAME_SOURCE_COPY_PIP_DIGESTS_CACHED",
        )
        for label, expected in (
            ("source", "SOURCE_DIGEST_DRIFT"),
            ("requirements_copy", "REQUIREMENTS_COPY_DIGEST_DRIFT"),
            ("runtime_pip", "RUNTIME_PIP_DIGEST_DRIFT"),
        ):
            candidate = copy.deepcopy(consumer)
            candidate["identity_chain"][label]["vertex_digest"] = (
                "sha256:" + ("f" * 64)
            )
            self.assertEqual(
                verifier.classify_pair(producer, candidate)["classification"],
                expected,
            )
        noncached = copy.deepcopy(consumer)
        noncached["network_vertices"][0] = interval(False)
        self.assertEqual(
            verifier.classify_pair(producer, noncached)["classification"],
            "SAME_SOURCE_COPY_PIP_DIGESTS_NONCACHED",
        )

    def test_v17_cache_record_rebinds_actual_producer_summary_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, progress, envelope, _copy = self._write_git_evidence(
                root / "producer",
                target=verifier._v13.EXPORT_TARGET,
                cached=False,
            )
            with contextlib.redirect_stderr(io.StringIO()):
                producer = verifier.validate_build_evidence(
                    metadata,
                    progress,
                    envelope,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=False,
                    lifecycle_diagnostic_output_path=(
                        root / "producer" / "git-lifecycle.json"
                    ),
                )
            producer_path = root / "producer-summary.json"
            self._write_json(producer_path, producer)
            cache, _config = self._fixture()._oci_cache(root, producer)
            record = verifier.validate_cache_record(cache, producer_path)
            self.assertEqual(
                record["producer_summary_sha256"],
                hashlib.sha256(producer_path.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                record["schema_version"],
                "noteai.admin-dependency-cache-record.v13",
            )

    def test_v17_manifest_portability_and_final_contracts_are_versioned(
        self,
    ) -> None:
        source = (
            ROOT / "tools" / "verify_admin_dependency_cache_bundle_v17.py"
        ).read_text(encoding="utf-8")
        for function_name in (
            "validate_manifest",
            "validate_core",
            "validate_portability",
            "validate_final",
        ):
            self.assertIn(f"def {function_name}(", source)
        self.assertIn(
            '"noteai.admin-dependency-cache-portability.v17"',
            source,
        )
        self.assertIn(
            '"external_cache_removed_same_consumer_builder_replay"',
            source,
        )
        self.assertIn('"true_empty_cache_replay_claimed": False', source)
        self.assertIn(
            '"SAME_SOURCE_COPY_PIP_DIGESTS_CACHED"',
            source,
        )
        self.assertNotIn('"cacheless_replay"', source)

    def test_v17_source_is_thin_hash_frozen_v13_successor(self) -> None:
        source = (ROOT / "tools" / "verify_admin_dependency_cache_bundle_v17.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("V13_VERIFIER_SHA256", source)
        self.assertIn("_load_v13_verifier", source)
        self.assertNotIn("NOTEAI_V15", source)
        self.assertNotIn("cacheless_replay", source)
        self.assertIn(
            "external_cache_removed_same_consumer_builder_replay",
            source,
        )


if __name__ == "__main__":
    unittest.main()
