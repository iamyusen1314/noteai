from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_bundle_v13 as verifier  # noqa: E402


def _load_v11_tests():
    path = ROOT / "tests" / "test_admin_dependency_cache_bundle_verifier_v11.py"
    spec = importlib.util.spec_from_file_location("_v13_v11_fixtures", path)
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
    / "admin_dependency_cache_buildkit_v0.31.2_"
    "cache_record_identity_domains_projection.json"
)


class AdminDependencyCacheBundleVerifierV13Tests(unittest.TestCase):
    def _v11_fixture(self):
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

    def _replace_cache_config(
        self,
        cache: Path,
        config: dict,
    ) -> None:
        blob_root = cache / "blobs" / "sha256"
        index = self._read_json(cache / "index.json")
        old_manifest_digest = index["manifests"][0]["digest"].split(":", 1)[1]
        old_manifest_path = blob_root / old_manifest_digest
        manifest = self._read_json(old_manifest_path)
        old_config_digest = manifest["config"]["digest"].split(":", 1)[1]
        (blob_root / old_config_digest).unlink()
        config_bytes = json.dumps(config, separators=(",", ":")).encode()
        config_digest = hashlib.sha256(config_bytes).hexdigest()
        (blob_root / config_digest).write_bytes(config_bytes)
        manifest["config"]["digest"] = "sha256:" + config_digest
        manifest["config"]["size"] = len(config_bytes)
        old_manifest_path.unlink()
        manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode()
        manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
        (blob_root / manifest_digest).write_bytes(manifest_bytes)
        index["manifests"][0]["digest"] = "sha256:" + manifest_digest
        index["manifests"][0]["size"] = len(manifest_bytes)
        self._write_json(cache / "index.json", index)

    def _structural_fixture(
        self,
        root: Path,
        *,
        distinct_identity_domains: bool = True,
    ) -> tuple[dict, Path, Path, dict]:
        fixture = self._v11_fixture()
        producer, producer_path, _legacy_record = fixture._producer_and_record(
            root
        )
        cache, config = fixture._oci_cache(root, producer)
        if distinct_identity_domains:
            config["records"][0]["digest"] = "sha256:" + ("a" * 64)
            config["records"][1]["digest"] = "sha256:" + ("b" * 64)
            self.assertNotEqual(
                config["records"][0]["digest"],
                next(
                    item["vertex_digest"]
                    for item in producer["network_vertices"]
                    if item["role"] == "runtime_pip"
                ),
            )
            self.assertNotEqual(
                config["records"][1]["digest"],
                producer["anchor"]["vertex_digest"],
            )
            self._replace_cache_config(cache, config)
        return producer, producer_path, cache, config

    def test_source_fixture_binds_six_distinct_identity_domain_sources(self):
        self.assertEqual(
            hashlib.sha256(SOURCE_FIXTURE.read_bytes()).hexdigest(),
            "176fd702836a46ab30584aa3b0d0072c6c2a31ea8eda6c306d3d7cdfd87d6b66",
        )
        payload = self._read_json(SOURCE_FIXTURE)
        self.assertEqual(
            payload["classification"],
            "SOURCE_PROVEN_DISTINCT_CACHE_KEY_AND_LLB_VERTEX_IDENTITY_DOMAINS",
        )
        self.assertEqual(
            payload["commit"],
            "e42e1bfd389af7203238cce77b1f7dad447285e9",
        )
        self.assertEqual(len(payload["sources"]), 6)
        self.assertEqual(
            [source["path"] for source in payload["sources"]],
            [
                "solver/cachekey.go",
                "solver/cachemanager.go",
                "solver/exporter.go",
                "cache/remotecache/v1/chains.go",
                "cache/remotecache/v1/utils.go",
                "cache/remotecache/v1/types/spec.go",
            ],
        )
        self.assertEqual(
            payload["tag_object"],
            "37aba93910a245e9196ccf67f4afb55f18b39f81",
        )
        self.assertFalse(
            payload["claims"][
                "record_digest_equals_progress_vertex_digest_is_source_supported"
            ]
        )
        self.assertFalse(
            payload["claims"]["source_review_is_runtime_cache_portability_evidence"]
        )
        self.assertEqual(
            payload["v13_contract"]["runtime_portability_acceptance"],
            "FRESH_CONSUMER_SAME_DIGEST_CACHED_ONLY",
        )
        self.assertEqual(
            payload["v13_contract"]["record_graph_depth_maximum"],
            verifier.CACHE_RECORD_DEPTH_MAXIMUM,
        )

    def test_cross_domain_record_digests_pass_structural_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            producer, producer_path, cache, config = self._structural_fixture(
                root
            )
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                summary = verifier.validate_cache_record(cache, producer_path)
        self.assertEqual(
            summary["schema_version"],
            "noteai.admin-dependency-cache-record.v13",
        )
        self.assertEqual(summary["layer_count"], 1)
        self.assertEqual(summary["record_count"], 2)
        self.assertEqual(summary["result_bearing_record_count"], 2)
        self.assertEqual(summary["layer_result_count"], 2)
        self.assertEqual(summary["chained_result_count"], 0)
        self.assertEqual(summary["input_group_count"], 1)
        self.assertEqual(summary["link_count"], 1)
        record_digests = {record["digest"] for record in config["records"]}
        progress_digests = {
            item["vertex_digest"] for item in producer["network_vertices"]
        }
        progress_digests.add(producer["anchor"]["vertex_digest"])
        self.assertTrue(record_digests.isdisjoint(progress_digests))
        self.assertEqual(
            summary["structural_validation"],
            {
                "cache_config_validated": True,
                "record_and_layer_dag_validated": True,
                "record_and_layer_reachability_validated": True,
                "vertex_digest_binding_attempted": False,
                "direct_identity_path_claimed": False,
                "runtime_portability_proven": False,
            },
        )
        diagnostic_lines = [
            line
            for line in stderr.getvalue().splitlines()
            if line.startswith("noteai_v13_cache_structure_diagnostic=")
        ]
        self.assertEqual(len(diagnostic_lines), 1)
        self.assertLessEqual(
            len(diagnostic_lines[0].encode("utf-8")),
            verifier.CACHE_STRUCTURE_DIAGNOSTIC_MAXIMUM_BYTES + 64,
        )
        diagnostic = json.loads(diagnostic_lines[0].split("=", 1)[1])
        self.assertEqual(
            diagnostic["validation_phase"],
            "PENDING_STRUCTURAL_VALIDATION",
        )
        self.assertFalse(diagnostic["structural_validation_completed"])
        self.assertFalse(diagnostic["vertex_digest_binding_attempted"])

    def test_accidental_digest_equality_does_not_change_structure_verdict(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _producer, producer_path, cache, _config = self._structural_fixture(
                root,
                distinct_identity_domains=False,
            )
            with contextlib.redirect_stderr(io.StringIO()):
                summary = verifier.validate_cache_record(cache, producer_path)
        self.assertTrue(
            summary["structural_validation"]["cache_config_validated"]
        )
        self.assertFalse(
            summary["structural_validation"]["vertex_digest_binding_attempted"]
        )

    def test_cache_config_hash_and_structure_share_one_byte_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _producer, producer_path, cache, config = self._structural_fixture(
                root
            )
            index = self._read_json(cache / "index.json")
            manifest_digest = index["manifests"][0]["digest"].split(":", 1)[1]
            manifest = self._read_json(
                cache / "blobs" / "sha256" / manifest_digest
            )
            config_path = (
                cache
                / "blobs"
                / "sha256"
                / manifest["config"]["digest"].split(":", 1)[1]
            )
            expected_config_sha256 = hashlib.sha256(
                config_path.read_bytes()
            ).hexdigest()
            forged = copy.deepcopy(config)
            forged["records"].append(
                {
                    "digest": "sha256:" + ("f" * 64),
                    "layers": [{"layer": 0}],
                    "inputs": [[{"link": 1}]],
                }
            )
            original_strict_json_file = verifier._base.strict_json_file

            def spoof_second_open(path):
                if Path(path) == config_path:
                    return forged
                return original_strict_json_file(path)

            with (
                mock.patch.object(
                    verifier._base,
                    "strict_json_file",
                    side_effect=spoof_second_open,
                ),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                summary = verifier.validate_cache_record(cache, producer_path)
        self.assertEqual(summary["record_count"], 2)
        self.assertEqual(
            summary["cache_config_sha256"],
            expected_config_sha256,
        )

    def test_cache_record_authorities_each_use_one_bounded_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _producer, producer_path, cache, _config = self._structural_fixture(
                root
            )
            index_path = cache / "index.json"
            index = self._read_json(index_path)
            root_path = (
                cache
                / "blobs"
                / "sha256"
                / index["manifests"][0]["digest"].split(":", 1)[1]
            )
            manifest = self._read_json(root_path)
            config_path = (
                cache
                / "blobs"
                / "sha256"
                / manifest["config"]["digest"].split(":", 1)[1]
            )
            observed: dict[Path, int] = {}
            descriptor_reads: dict[str, int] = {}
            original_regular_bytes = verifier._regular_bytes
            original_descriptor_blob = verifier._read_descriptor_blob

            def counted(path, **kwargs):
                candidate = Path(path)
                observed[candidate] = observed.get(candidate, 0) + 1
                return original_regular_bytes(candidate, **kwargs)

            def counted_descriptor(cache_root, **kwargs):
                label = kwargs["label"]
                descriptor_reads[label] = descriptor_reads.get(label, 0) + 1
                return original_descriptor_blob(cache_root, **kwargs)

            with (
                mock.patch.object(
                    verifier,
                    "_regular_bytes",
                    side_effect=counted,
                ),
                mock.patch.object(
                    verifier,
                    "_read_descriptor_blob",
                    side_effect=counted_descriptor,
                ),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                verifier.validate_cache_record(cache, producer_path)
        self.assertEqual(
            {
                producer_path: observed.get(producer_path),
                index_path: observed.get(index_path),
            },
            {
                producer_path: 1,
                index_path: 1,
            },
        )
        self.assertEqual(
            descriptor_reads,
            {
                "OCI cache manifest": 1,
                "BuildKit cache config": 1,
            },
        )

    def test_descriptor_size_bounds_precede_blob_reads(self):
        for target in ("root", "config"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _producer, producer_path, cache, _config = (
                    self._structural_fixture(root)
                )
                index_path = cache / "index.json"
                index = self._read_json(index_path)
                root_digest = index["manifests"][0]["digest"].split(":", 1)[1]
                root_path = cache / "blobs" / "sha256" / root_digest
                if target == "root":
                    index["manifests"][0]["size"] = (
                        verifier.MAXIMUM_CACHE_CONFIG_BYTES + 1
                    )
                    self._write_json(index_path, index)
                    forbidden_path = root_path
                    expected_code = "CACHE_RECORD_INDEX_INVALID"
                else:
                    manifest = self._read_json(root_path)
                    config_digest = manifest["config"]["digest"].split(":", 1)[1]
                    forbidden_path = cache / "blobs" / "sha256" / config_digest
                    manifest["config"]["size"] = (
                        verifier.MAXIMUM_CACHE_CONFIG_BYTES + 1
                    )
                    root_bytes = json.dumps(
                        manifest,
                        separators=(",", ":"),
                    ).encode()
                    new_root_digest = hashlib.sha256(root_bytes).hexdigest()
                    new_root_path = cache / "blobs" / "sha256" / new_root_digest
                    new_root_path.write_bytes(root_bytes)
                    index["manifests"][0]["digest"] = "sha256:" + new_root_digest
                    index["manifests"][0]["size"] = len(root_bytes)
                    self._write_json(index_path, index)
                    expected_code = "CACHE_RECORD_CONFIG_INVALID"
                original_descriptor_blob = verifier._read_descriptor_blob

                def reject_forbidden(cache_root, **kwargs):
                    candidate = (
                        Path(cache_root)
                        / "blobs"
                        / "sha256"
                        / kwargs["digest_hex"]
                    )
                    if candidate == forbidden_path:
                        self.fail("oversized descriptor blob was read")
                    return original_descriptor_blob(cache_root, **kwargs)

                with (
                    mock.patch.object(
                        verifier,
                        "_read_descriptor_blob",
                        side_effect=reject_forbidden,
                    ),
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(verifier.V11BundleError) as raised,
                ):
                    verifier.validate_cache_record(cache, producer_path)
                self.assertEqual(raised.exception.failure_code, expected_code)

    def test_descriptor_path_chain_rejects_symlink_and_hardlink(self):
        for mutation in ("blobs-symlink", "root-hardlink"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _producer, producer_path, cache, _config = (
                    self._structural_fixture(root)
                )
                index = self._read_json(cache / "index.json")
                root_digest = index["manifests"][0]["digest"].split(":", 1)[1]
                root_path = cache / "blobs" / "sha256" / root_digest
                if mutation == "blobs-symlink":
                    external = root / "external-blobs"
                    (cache / "blobs").rename(external)
                    (cache / "blobs").symlink_to(
                        external,
                        target_is_directory=True,
                    )
                else:
                    (root / "root-hardlink").hardlink_to(root_path)
                with (
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(verifier.V11BundleError) as raised,
                ):
                    verifier.validate_cache_record(cache, producer_path)
                self.assertEqual(
                    raised.exception.failure_code,
                    "CACHE_RECORD_INDEX_INVALID",
                )

    def test_descriptor_fifo_is_rejected_without_waiting_for_writer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _producer, producer_path, cache, _config = self._structural_fixture(
                root
            )
            index = self._read_json(cache / "index.json")
            root_digest = index["manifests"][0]["digest"].split(":", 1)[1]
            root_path = cache / "blobs" / "sha256" / root_digest
            root_path.unlink()
            os.mkfifo(root_path, mode=0o600)
            with (
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(verifier.V11BundleError) as raised,
            ):
                verifier.validate_cache_record(cache, producer_path)
        self.assertEqual(
            raised.exception.failure_code,
            "CACHE_RECORD_INDEX_INVALID",
        )

    def test_regular_authority_fifo_is_rejected_without_waiting_for_writer(self):
        for target in ("producer", "index"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _producer, producer_path, cache, _config = (
                    self._structural_fixture(root)
                )
                fifo = producer_path if target == "producer" else cache / "index.json"
                fifo.unlink()
                os.mkfifo(fifo, mode=0o600)
                with (
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(verifier.V11BundleError) as raised,
                ):
                    verifier.validate_cache_record(cache, producer_path)
                self.assertEqual(
                    raised.exception.failure_code,
                    (
                        "V11_SUMMARY_FILE_INVALID"
                        if target == "producer"
                        else "CACHE_RECORD_INDEX_INVALID"
                    ),
                )

    def test_descriptor_identity_rejects_bool_and_path_traversal(self):
        for descriptor in (
            {"digest": "sha256:" + ("1" * 64), "size": True},
            {"digest": "sha256:../../outside", "size": 1},
        ):
            with (
                self.subTest(descriptor=descriptor),
                mock.patch.object(
                    verifier,
                    "_read_descriptor_blob",
                    side_effect=AssertionError("descriptor bytes were read"),
                ),
                self.assertRaises(verifier.V11BundleError) as raised,
            ):
                verifier._bounded_descriptor_bytes(
                    Path("unused"),
                    descriptor,
                    maximum_bytes=verifier.MAXIMUM_CACHE_CONFIG_BYTES,
                    failure_code="CACHE_RECORD_INDEX_INVALID",
                    label="test descriptor",
                )
            self.assertEqual(
                raised.exception.failure_code,
                "CACHE_RECORD_INDEX_INVALID",
            )

    def test_pair_hashes_and_parses_each_summary_from_one_read(self):
        producer = {
            "target": verifier.EXPORT_TARGET,
            "network_vertices": [{
                "role": "runtime_pip",
                "vertex_digest": "sha256:" + ("1" * 64),
                "interval_count": 1,
                "completed_interval_count": 1,
                "cached_interval_count": 0,
                "noncached_interval_count": 1,
            }],
        }
        consumer = copy.deepcopy(producer)
        consumer["target"] = verifier.IMPORT_TARGET
        consumer["network_vertices"][0].update(
            cached_interval_count=1,
            noncached_interval_count=0,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            producer_path = root / "producer.json"
            consumer_path = root / "consumer.json"
            self._write_json(producer_path, producer)
            self._write_json(consumer_path, consumer)
            observed: dict[Path, int] = {}
            original_regular_bytes = verifier._regular_bytes

            def counted(path, **kwargs):
                candidate = Path(path)
                observed[candidate] = observed.get(candidate, 0) + 1
                return original_regular_bytes(candidate, **kwargs)

            with (
                mock.patch.object(
                    verifier,
                    "_regular_bytes",
                    side_effect=counted,
                ),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                result = verifier.validate_pair(producer_path, consumer_path)
        self.assertEqual(result["classification"], "SAME_DIGEST_CACHED")
        self.assertEqual(observed, {producer_path: 1, consumer_path: 1})

    def test_structural_mutations_fail_closed_and_retain_bounded_diagnostic(self):
        for mutation in (
            "empty-records",
            "bad-link",
            "record-cycle",
            "missing-result",
            "missing-link",
            "layer-cycle",
            "unreachable-layer",
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _producer, producer_path, cache, config = self._structural_fixture(
                    root
                )
                if mutation == "empty-records":
                    config["records"] = []
                elif mutation == "bad-link":
                    config["records"][1]["inputs"] = [[{"link": 99}]]
                elif mutation == "record-cycle":
                    config["records"][0]["inputs"] = [[{"link": 1}]]
                elif mutation == "missing-result":
                    config["records"][0].pop("layers")
                    config["records"][1].pop("layers")
                elif mutation == "missing-link":
                    config["records"][1]["inputs"] = []
                elif mutation == "layer-cycle":
                    config["layers"][0]["parent"] = 0
                else:
                    layer_digest = config["layers"][0]["blob"]
                    config["layers"].append(
                        {"blob": layer_digest, "parent": -1}
                    )
                self._replace_cache_config(cache, config)
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr), self.assertRaises(
                    (
                        verifier.V11BundleError,
                        verifier._v10._v6._v3.BundleError,
                    )
                ):
                    verifier.validate_cache_record(cache, producer_path)
                lines = [
                    line
                    for line in stderr.getvalue().splitlines()
                    if line.startswith(
                        "noteai_v13_cache_structure_diagnostic="
                    )
                ]
                self.assertEqual(len(lines), 1)
                self.assertLessEqual(
                    len(lines[0].encode("utf-8")),
                    verifier.CACHE_STRUCTURE_DIAGNOSTIC_MAXIMUM_BYTES + 64,
                )

    def test_record_count_above_bound_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _producer, producer_path, cache, config = self._structural_fixture(
                root
            )
            config["records"] = [
                {
                    "digest": "sha256:" + f"{index:064x}",
                    "layers": [{"layer": 0}],
                    "inputs": (
                        [[{"link": 1}]] if index == 0 else []
                    ),
                }
                for index in range(4097)
            ]
            self._replace_cache_config(cache, config)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaisesRegex(
                verifier.V11BundleError,
                "record count",
            ):
                verifier.validate_cache_record(cache, producer_path)

    def test_deep_record_graph_fails_with_fixed_v13_code(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _producer, producer_path, cache, config = self._structural_fixture(
                root
            )
            record_count = 1_200
            config["records"] = [
                {
                    "digest": "sha256:" + f"{index:064x}",
                    "layers": ([{"layer": 0}] if index == 0 else []),
                    "inputs": (
                        [[{"link": index + 1}]]
                        if index + 1 < record_count
                        else []
                    ),
                }
                for index in range(record_count)
            ]
            self._replace_cache_config(cache, config)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(
                verifier.V11BundleError
            ) as raised:
                verifier.validate_cache_record(cache, producer_path)
        self.assertEqual(
            raised.exception.failure_code,
            "CACHE_RECORD_GRAPH_DEPTH_INVALID",
        )

    def test_fresh_consumer_requires_exact_same_digest_cached(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = self._v11_fixture()
            producer, producer_path, cache, _config = self._structural_fixture(
                root
            )
            record_path = root / "cache-record-v13.json"
            with contextlib.redirect_stderr(io.StringIO()):
                record = verifier.validate_cache_record(cache, producer_path)
            self._write_json(record_path, record)
            metadata, progress, _digests, _child = fixture._write_evidence(
                root / "consumer",
                target=verifier.IMPORT_TARGET,
                cached=True,
            )
            with contextlib.redirect_stderr(io.StringIO()):
                summary = verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                    producer_summary_path=producer_path,
                    cache_record_path=record_path,
                    expected_cache_record_sha256=hashlib.sha256(
                        record_path.read_bytes()
                    ).hexdigest(),
                )
            self.assertEqual(
                summary["pair"]["classification"],
                "SAME_DIGEST_CACHED",
            )
            self.assertEqual(
                summary["cache_record_projection"]["record_count"],
                record["record_count"],
            )

    def test_fresh_consumer_rejects_forged_cache_record_summaries(self):
        for mutation in (
            "missing-sha",
            "missing-count",
            "extra-key",
            "bool-count",
            "root-layer-mismatch",
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fixture = self._v11_fixture()
                _producer, producer_path, cache, _config = (
                    self._structural_fixture(root)
                )
                with contextlib.redirect_stderr(io.StringIO()):
                    record = verifier.validate_cache_record(
                        cache,
                        producer_path,
                    )
                if mutation == "missing-sha":
                    record.pop("cache_config_sha256")
                elif mutation == "missing-count":
                    record.pop("input_group_count")
                elif mutation == "extra-key":
                    record["unreviewed"] = True
                elif mutation == "bool-count":
                    record["record_count"] = True
                else:
                    record["root_layer_descriptor_count"] += 1
                record_path = root / "cache-record-v13.json"
                self._write_json(record_path, record)
                metadata, progress, _digests, _child = fixture._write_evidence(
                    root / "consumer",
                    target=verifier.IMPORT_TARGET,
                    cached=True,
                )
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(
                    verifier.V11BundleError
                ) as raised:
                    verifier.validate_build_evidence(
                        metadata,
                        progress,
                        dockerfile_kind="prefix",
                        require_network_vertices_cached=True,
                        producer_summary_path=producer_path,
                        cache_record_path=record_path,
                        expected_cache_record_sha256=hashlib.sha256(
                            record_path.read_bytes()
                        ).hexdigest(),
                    )
                self.assertEqual(
                    raised.exception.failure_code,
                    "V13_CACHE_STRUCTURE_INVALID",
                )

    def test_fresh_consumer_binds_core_validated_cache_record_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = self._v11_fixture()
            _producer, producer_path, cache, _config = self._structural_fixture(
                root
            )
            with contextlib.redirect_stderr(io.StringIO()):
                record = verifier.validate_cache_record(cache, producer_path)
            record_path = root / "cache-record-v13.json"
            self._write_json(record_path, record)
            trusted_sha256 = hashlib.sha256(record_path.read_bytes()).hexdigest()
            record["cache_config_sha256"] = "0" * 64
            self._write_json(record_path, record)
            metadata, progress, _digests, _child = fixture._write_evidence(
                root / "consumer",
                target=verifier.IMPORT_TARGET,
                cached=True,
            )
            original_sha256_file = verifier._base.sha256_file

            def spoof_second_open(path):
                if Path(path) == record_path:
                    return trusted_sha256
                return original_sha256_file(path)

            with (
                mock.patch.object(
                    verifier._base,
                    "sha256_file",
                    side_effect=spoof_second_open,
                ),
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(verifier.V11BundleError) as raised,
            ):
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                    producer_summary_path=producer_path,
                    cache_record_path=record_path,
                    expected_cache_record_sha256=trusted_sha256,
                )
        self.assertEqual(
            raised.exception.failure_code,
            "V13_CACHE_RECORD_TRUST_INVALID",
        )

    def test_fresh_consumer_hashes_same_producer_bytes_it_parses(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = self._v11_fixture()
            producer, producer_path, cache, _config = self._structural_fixture(
                root
            )
            trusted_producer_sha256 = hashlib.sha256(
                producer_path.read_bytes()
            ).hexdigest()
            with contextlib.redirect_stderr(io.StringIO()):
                record = verifier.validate_cache_record(cache, producer_path)
            record_path = root / "cache-record-v13.json"
            self._write_json(record_path, record)
            trusted_record_sha256 = hashlib.sha256(
                record_path.read_bytes()
            ).hexdigest()
            producer["duration_seconds"] += 1
            self._write_json(producer_path, producer)
            metadata, progress, _digests, _child = fixture._write_evidence(
                root / "consumer",
                target=verifier.IMPORT_TARGET,
                cached=True,
            )
            original_sha256_file = verifier._base.sha256_file

            def spoof_second_open(path):
                if Path(path) == producer_path:
                    return trusted_producer_sha256
                return original_sha256_file(path)

            with (
                mock.patch.object(
                    verifier._base,
                    "sha256_file",
                    side_effect=spoof_second_open,
                ),
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(verifier.V11BundleError) as raised,
            ):
                verifier.validate_build_evidence(
                    metadata,
                    progress,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                    producer_summary_path=producer_path,
                    cache_record_path=record_path,
                    expected_cache_record_sha256=trusted_record_sha256,
                )
        self.assertEqual(
            raised.exception.failure_code,
            "V13_CACHE_STRUCTURE_INVALID",
        )

    def test_real_consumer_path_rejects_noncached_and_digest_drift(self):
        for mutation in ("noncached", "digest-drift"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fixture = self._v11_fixture()
                producer, producer_path, cache, _config = (
                    self._structural_fixture(root)
                )
                with contextlib.redirect_stderr(io.StringIO()):
                    record = verifier.validate_cache_record(
                        cache,
                        producer_path,
                    )
                if mutation == "digest-drift":
                    runtime_pip = next(
                        item
                        for item in producer["network_vertices"]
                        if item["role"] == "runtime_pip"
                    )
                    runtime_pip["vertex_digest"] = "sha256:" + ("e" * 64)
                    self._write_json(producer_path, producer)
                    record["producer_summary_sha256"] = hashlib.sha256(
                        producer_path.read_bytes()
                    ).hexdigest()
                record_path = root / "cache-record-v13.json"
                self._write_json(record_path, record)
                metadata, progress, _digests, _child = fixture._write_evidence(
                    root / "consumer",
                    target=verifier.IMPORT_TARGET,
                    cached=mutation != "noncached",
                )
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(
                    verifier.V11BundleError
                ) as raised:
                    verifier.validate_build_evidence(
                        metadata,
                        progress,
                        dockerfile_kind="prefix",
                        require_network_vertices_cached=True,
                        producer_summary_path=producer_path,
                        cache_record_path=record_path,
                        expected_cache_record_sha256=hashlib.sha256(
                            record_path.read_bytes()
                        ).hexdigest(),
                    )
                self.assertEqual(
                    raised.exception.failure_code,
                    "V13_PAIR_CACHE_PREDICATE_FAILED",
                )

    def test_pair_validator_rejects_noncached_and_digest_drift(self):
        producer = {
            "target": verifier.EXPORT_TARGET,
            "network_vertices": [
                {
                    "role": "runtime_pip",
                    "vertex_digest": "sha256:" + ("1" * 64),
                    "interval_count": 1,
                    "completed_interval_count": 1,
                    "cached_interval_count": 0,
                    "noncached_interval_count": 1,
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
                    "completed_interval_count": 1,
                    "cached_interval_count": 1,
                    "noncached_interval_count": 0,
                }
            ],
        }
        self.assertEqual(
            verifier.classify_pair(producer, consumer)["classification"],
            "SAME_DIGEST_CACHED",
        )
        for name, mutate, classification in (
            (
                "noncached",
                lambda value: value["network_vertices"][0].update(
                    cached_interval_count=0,
                    noncached_interval_count=1,
                ),
                "SAME_DIGEST_NONCACHED",
            ),
            (
                "drift",
                lambda value: value["network_vertices"][0].update(
                    vertex_digest="sha256:" + ("2" * 64)
                ),
                "DIGEST_DRIFT",
            ),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                candidate = copy.deepcopy(consumer)
                mutate(candidate)
                self.assertEqual(
                    verifier.classify_pair(producer, candidate)[
                        "classification"
                    ],
                    classification,
                )
                producer_path = Path(temporary) / "producer.json"
                consumer_path = Path(temporary) / "consumer.json"
                self._write_json(producer_path, producer)
                self._write_json(consumer_path, candidate)
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(
                    verifier.V11BundleError
                ):
                    verifier.validate_pair(producer_path, consumer_path)

        invalid_bool = copy.deepcopy(consumer)
        invalid_bool["network_vertices"][0]["interval_count"] = True
        with self.assertRaises(verifier.V11BundleError) as raised:
            verifier.classify_pair(producer, invalid_bool)
        self.assertEqual(
            raised.exception.failure_code,
            "V13_PAIR_ROLE_INVALID",
        )

    def test_old_cross_domain_identity_contract_is_absent(self):
        source = Path(verifier.__file__).read_text(encoding="utf-8")
        for forbidden in (
            "CACHE_RECORD_DIGEST_BINDING_INVALID",
            "CACHE_RECORD_DIRECT_PATH_INVALID",
            "anchor_to_runtime_pip_link_index",
            "identity_link_count",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn(
            'pair["classification"] == "SAME_DIGEST_CACHED"',
            source,
        )


if __name__ == "__main__":
    unittest.main()
