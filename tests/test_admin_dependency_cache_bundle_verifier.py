from __future__ import annotations

import gzip
import hashlib
import io
import json
import base64
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_bundle as verifier  # noqa: E402


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class AdminDependencyCacheBundleVerifierTests(unittest.TestCase):
    def test_duplicate_json_key_is_rejected(self) -> None:
        with self.assertRaisesRegex(verifier.BundleError, "duplicate JSON key"):
            verifier.strict_json_bytes(b'{"a": 1, "a": 2}', "payload")

    def test_non_finite_json_numbers_are_rejected(self) -> None:
        for value in (
            b'{"value": NaN}',
            b'{"value": Infinity}',
            b'{"value": -Infinity}',
            b'{"value": 1e999}',
            b'{"value": -1e999}',
        ):
            with self.subTest(value=value), self.assertRaisesRegex(
                verifier.BundleError,
                "non-finite JSON number",
            ):
                verifier.strict_json_bytes(value, "payload")

    def test_checksum_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            (bundle / "CORE_SHA256SUMS").write_text(
                f"{'0' * 64}  ./../escape\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(verifier.BundleError, "unsafe path"):
                verifier.validate_checksum_file(bundle, "CORE_SHA256SUMS", {"../escape"})

    def test_safe_tar_extract_accepts_only_root_owned_regular_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "cache.tar"
            payload = b"cache"
            with tarfile.open(archive_path, "w:") as archive:
                directory = tarfile.TarInfo("./blobs")
                directory.type = tarfile.DIRTYPE
                directory.mode = 0o700
                directory.uid = directory.gid = directory.mtime = 0
                archive.addfile(directory)
                file_info = tarfile.TarInfo("./blobs/item")
                file_info.size = len(payload)
                file_info.mode = 0o600
                file_info.uid = file_info.gid = file_info.mtime = 0
                archive.addfile(file_info, io.BytesIO(payload))
            destination = root / "extract"
            verifier.safe_extract_tar(
                archive_path,
                destination,
                archive_path.stat().st_size,
            )
            self.assertEqual((destination / "blobs" / "item").read_bytes(), payload)

    def test_safe_tar_extract_rejects_symlink_and_parent_traversal(self) -> None:
        for name, member_type in (
            ("./link", tarfile.SYMTYPE),
            ("../escape", tarfile.REGTYPE),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive_path = root / "cache.tar"
                with tarfile.open(archive_path, "w:") as archive:
                    item = tarfile.TarInfo(name)
                    item.type = member_type
                    item.mode = 0o600
                    item.uid = item.gid = item.mtime = 0
                    item.linkname = "./target"
                    archive.addfile(item, io.BytesIO(b"") if item.isreg() else None)
                with self.assertRaises(verifier.BundleError):
                    verifier.safe_extract_tar(
                        archive_path,
                        root / "extract",
                        archive_path.stat().st_size,
                    )

    def test_safe_tar_rejects_sparse_metadata_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "cache.tar"
            with tarfile.open(archive_path, "w:", format=tarfile.PAX_FORMAT) as archive:
                item = tarfile.TarInfo("./item")
                item.size = 1
                item.mode = 0o600
                item.uid = item.gid = item.mtime = 0
                item.pax_headers = {"GNU.sparse.size": "1"}
                archive.addfile(item, io.BytesIO(b"x"))
            destination = root / "extract"
            with self.assertRaisesRegex(verifier.BundleError, "sparse tar"):
                verifier.safe_extract_tar(
                    archive_path,
                    destination,
                    archive_path.stat().st_size,
                )
            self.assertFalse(destination.exists())

    def test_safe_tar_rejects_total_size_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "cache.tar"
            with tarfile.open(archive_path, "w:") as archive:
                item = tarfile.TarInfo("./item")
                item.size = 5
                item.mode = 0o600
                item.uid = item.gid = item.mtime = 0
                archive.addfile(item, io.BytesIO(b"12345"))
            destination = root / "extract"
            with mock.patch.object(verifier, "MAXIMUM_EXTRACTED_CACHE_BYTES", 4):
                with self.assertRaisesRegex(
                    verifier.BundleError,
                    "extracted bytes exceed",
                ):
                    verifier.safe_extract_tar(
                        archive_path,
                        destination,
                        archive_path.stat().st_size,
                    )
            self.assertFalse(destination.exists())

    def test_safe_tar_rejects_member_count_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "cache.tar"
            with tarfile.open(archive_path, "w:") as archive:
                for name in ("./first", "./second"):
                    item = tarfile.TarInfo(name)
                    item.size = 1
                    item.mode = 0o600
                    item.uid = item.gid = item.mtime = 0
                    archive.addfile(item, io.BytesIO(b"x"))
            destination = root / "extract"
            with mock.patch.object(verifier, "MAXIMUM_TAR_MEMBERS", 1):
                with self.assertRaisesRegex(
                    verifier.BundleError,
                    "member count exceeds",
                ):
                    verifier.safe_extract_tar(
                        archive_path,
                        destination,
                        archive_path.stat().st_size,
                    )
            self.assertFalse(destination.exists())

    def test_bounded_decompress_rejects_size_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compressed = root / "payload.gz"
            with gzip.open(compressed, "wb") as output:
                output.write(b"12345")
            with self.assertRaisesRegex(verifier.BundleError, "size changed"):
                verifier.bounded_decompress(compressed, root / "payload", 4)

    def _make_oci_cache(self, root: Path) -> dict:
        blob_root = root / "blobs" / "sha256"
        blob_root.mkdir(parents=True)
        layer_bytes = b"compressed-layer"
        layer_digest = digest(layer_bytes)
        (blob_root / layer_digest).write_bytes(layer_bytes)
        config_bytes = json.dumps(
            {
                "layers": [
                    {
                        "blob": "sha256:" + layer_digest,
                        "parent": -1,
                    }
                ],
                "records": [
                    {
                        "digest": "sha256:" + ("1" * 64),
                        "layers": [{"layer": 0}],
                        "inputs": [],
                    }
                ],
            },
            separators=(",", ":"),
        ).encode("utf-8")
        config_digest = digest(config_bytes)
        (blob_root / config_digest).write_bytes(config_bytes)
        manifest_payload = {
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
                    "size": len(layer_bytes),
                }
            ],
        }
        manifest_bytes = json.dumps(
            manifest_payload,
            separators=(",", ":"),
        ).encode("utf-8")
        manifest_digest = digest(manifest_bytes)
        (blob_root / manifest_digest).write_bytes(manifest_bytes)
        index_payload = {
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
        (root / "index.json").write_text(
            json.dumps(index_payload, separators=(",", ":")),
            encoding="utf-8",
        )
        (root / "oci-layout").write_text(
            '{"imageLayoutVersion":"1.0.0"}',
            encoding="utf-8",
        )
        names = sorted((layer_digest, config_digest, manifest_digest))
        return {
            "cache": {
                "manifest_digest": "sha256:" + manifest_digest,
                "cache_index_sha256": verifier.sha256_file(root / "index.json"),
                "oci_layout_sha256": verifier.sha256_file(root / "oci-layout"),
                "blob_count": len(names),
                "blob_bytes": sum((blob_root / name).stat().st_size for name in names),
                "blobs": [
                    {
                        "name": name,
                        "sha256": name,
                        "bytes": (blob_root / name).stat().st_size,
                    }
                    for name in names
                ],
            }
        }

    def test_oci_cache_requires_exact_descriptor_closure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            manifest = self._make_oci_cache(cache)
            verifier.validate_oci_cache(cache, manifest)
            extra = cache / "blobs" / "sha256" / ("f" * 64)
            extra.write_bytes(b"unreferenced")
            with self.assertRaisesRegex(verifier.BundleError, "closure changed"):
                verifier.validate_oci_cache(cache, manifest)

    def test_oci_cache_rejects_missing_cache_config_blob_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            manifest = self._make_oci_cache(cache)
            blob_root = cache / "blobs" / "sha256"
            index = json.loads((cache / "index.json").read_text(encoding="utf-8"))
            old_manifest_digest = index["manifests"][0]["digest"].removeprefix("sha256:")
            root_manifest = json.loads(
                (blob_root / old_manifest_digest).read_text(encoding="utf-8")
            )
            old_config_digest = root_manifest["config"]["digest"].removeprefix("sha256:")
            config = json.loads(
                (blob_root / old_config_digest).read_text(encoding="utf-8")
            )
            config["layers"][0]["blob"] = "sha256:" + ("e" * 64)
            config_bytes = json.dumps(config, separators=(",", ":")).encode("utf-8")
            new_config_digest = digest(config_bytes)
            (blob_root / new_config_digest).write_bytes(config_bytes)
            root_manifest["config"]["digest"] = "sha256:" + new_config_digest
            root_manifest["config"]["size"] = len(config_bytes)
            root_manifest_bytes = json.dumps(
                root_manifest,
                separators=(",", ":"),
            ).encode("utf-8")
            new_manifest_digest = digest(root_manifest_bytes)
            (blob_root / new_manifest_digest).write_bytes(root_manifest_bytes)
            index["manifests"][0]["digest"] = "sha256:" + new_manifest_digest
            index["manifests"][0]["size"] = len(root_manifest_bytes)
            (cache / "index.json").write_text(
                json.dumps(index, separators=(",", ":")),
                encoding="utf-8",
            )
            (blob_root / old_config_digest).unlink()
            (blob_root / old_manifest_digest).unlink()
            names = sorted(path.name for path in blob_root.iterdir())
            manifest["cache"].update(
                {
                    "manifest_digest": "sha256:" + new_manifest_digest,
                    "cache_index_sha256": verifier.sha256_file(cache / "index.json"),
                    "blob_count": len(names),
                    "blob_bytes": sum(
                        (blob_root / name).stat().st_size for name in names
                    ),
                    "blobs": [
                        {
                            "name": name,
                            "sha256": name,
                            "bytes": (blob_root / name).stat().st_size,
                        }
                        for name in names
                    ],
                }
            )
            with self.assertRaisesRegex(verifier.BundleError, "layer blob missing"):
                verifier.validate_oci_cache(cache, manifest)

    def test_cache_config_rejects_duplicate_root_layer_descriptors(self) -> None:
        layer_digest = "sha256:" + ("a" * 64)
        descriptor = {
            "digest": layer_digest,
            "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
            "size": 1,
        }
        config = {
            "layers": [{"blob": layer_digest, "parent": -1}],
            "records": [
                {
                    "digest": "sha256:" + ("1" * 64),
                    "layers": [{"layer": 0}],
                    "inputs": [],
                }
            ],
        }
        with self.assertRaisesRegex(verifier.BundleError, "descriptors repeat"):
            verifier.validate_cache_config(config, [descriptor, descriptor])

    def test_cache_config_rejects_unreachable_layer(self) -> None:
        first_digest = "sha256:" + ("a" * 64)
        second_digest = "sha256:" + ("b" * 64)
        descriptors = [
            {
                "digest": first_digest,
                "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                "size": 1,
            },
            {
                "digest": second_digest,
                "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                "size": 1,
            },
        ]
        config = {
            "layers": [
                {"blob": first_digest, "parent": -1},
                {"blob": second_digest, "parent": -1},
            ],
            "records": [
                {
                    "digest": "sha256:" + ("1" * 64),
                    "layers": [{"layer": 0}],
                    "inputs": [],
                }
            ],
        }
        with self.assertRaisesRegex(verifier.BundleError, "layer reachability"):
            verifier.validate_cache_config(config, descriptors)

    def test_cache_config_rejects_unreachable_record(self) -> None:
        layer_digest = "sha256:" + ("a" * 64)
        descriptors = [
            {
                "digest": layer_digest,
                "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                "size": 1,
            }
        ]
        config = {
            "layers": [{"blob": layer_digest, "parent": -1}],
            "records": [
                {
                    "digest": "sha256:" + ("1" * 64),
                    "layers": [{"layer": 0}],
                    "inputs": [],
                },
                {
                    "digest": "sha256:" + ("2" * 64),
                    "inputs": [],
                },
            ],
        }
        with self.assertRaisesRegex(verifier.BundleError, "record reachability"):
            verifier.validate_cache_config(config, descriptors)

    def test_chunk_inventory_requires_contiguous_name_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            (bundle / "chunks").mkdir()
            payload = b"chunk"
            relative = "chunks/admin-dependency-cache.tar.gz.part-0000"
            (bundle / relative).write_bytes(payload)
            manifest = {
                "archive": {
                    "chunk_count": 1,
                    "gzip_bytes": len(payload),
                    "gzip_sha256": digest(payload),
                    "chunks": [
                        {
                            "name": relative,
                            "sha256": digest(payload),
                            "bytes": len(payload),
                        }
                    ],
                }
            }
            verifier.validate_chunks(bundle, manifest, bundle / "joined.gz")
            manifest["archive"]["chunks"][0]["name"] = (
                "chunks/admin-dependency-cache.tar.gz.part-0001"
            )
            with self.assertRaisesRegex(verifier.BundleError, "not contiguous"):
                verifier.validate_chunks(bundle, manifest, bundle / "joined-2.gz")

    def _write_build_evidence(
        self,
        root: Path,
        *,
        dockerfile_kind: str,
    ) -> tuple[Path, Path]:
        dockerfile = (
            subprocess.run(
                ["git", "show", f"{verifier.RELEASE_COMMIT}:Dockerfile"],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
            ).stdout
        )
        if dockerfile_kind == "prefix":
            dockerfile = b"".join(dockerfile.splitlines(keepends=True)[:80])
            followpaths = verifier.PREFIX_CONTEXT_FOLLOWPATHS
            ranges = [
                {"start": {"line": 7}, "end": {"line": 7}},
                {"start": {"line": 80}, "end": {"line": 80}},
            ]
        else:
            followpaths = verifier.FULL_CONTEXT_FOLLOWPATHS
            ranges = [
                {"start": {"line": 7}, "end": {"line": 7}},
                {"start": {"line": 80}, "end": {"line": 80}},
                {"start": {"line": 83}, "end": {"line": 83}},
                {"start": {"line": 100}, "end": {"line": 100}},
            ]
        llb = [
            {
                "op": {
                    "Op": {
                        "source": {
                            "identifier": (
                                "docker-image://docker.io/library/"
                                "node:20-bookworm-slim@sha256:"
                                + verifier.NODE_INDEX
                            ),
                            "attrs": {"image.resolvemode": "pull"},
                        }
                    }
                }
            },
            {
                "op": {
                    "Op": {
                        "source": {
                            "identifier": (
                                "docker-image://docker.io/library/"
                                "python:3.11.15-slim-trixie@sha256:"
                                + verifier.PYTHON_INDEX
                            ),
                            "attrs": {"image.resolvemode": "pull"},
                        }
                    }
                }
            },
            {
                "op": {
                    "Op": {
                        "source": {
                            "identifier": "local://context",
                            "attrs": {
                                "local.followpaths": json.dumps(
                                    followpaths,
                                    separators=(",", ":"),
                                )
                            },
                        }
                    }
                }
            },
        ]
        metadata = {
            "buildx.build.provenance": {
                "buildType": "https://mobyproject.org/buildkit@v1",
                "invocation": {
                    "configSource": {"entryPoint": "Dockerfile"},
                    "parameters": {
                        "frontend": "dockerfile.v0",
                        "args": {
                            "build-arg:NOTEAI_OCI_CREATED": verifier.OCI_CREATED,
                            "build-arg:NOTEAI_OCI_REVISION": verifier.RELEASE_COMMIT,
                            "build-arg:NOTEAI_OCI_SOURCE": verifier.OCI_SOURCE,
                            "build-arg:NOTEAI_OCI_VERSION": verifier.OCI_VERSION,
                            "target": "runtime-common",
                        },
                    },
                    "environment": {"platform": "linux/amd64"},
                },
                "materials": [
                    {"digest": {"sha256": verifier.NODE_INDEX}},
                    {"digest": {"sha256": verifier.PYTHON_INDEX}},
                ],
                "buildConfig": {"llbDefinition": llb},
                "metadata": {
                    "https://mobyproject.org/buildkit@v1#metadata": {
                        "source": {
                            "locations": {
                                "step": {"locations": [{"ranges": ranges}]}
                            },
                            "infos": [
                                {
                                    "data": base64.b64encode(dockerfile).decode("ascii")
                                }
                            ],
                        }
                    },
                    "buildStartedOn": "2026-07-31T00:00:00Z",
                    "buildFinishedOn": "2026-07-31T00:01:00Z",
                },
            }
        }
        metadata_path = root / "metadata.json"
        progress_path = root / "progress.rawjson"
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        progress_path.write_text(
            "".join(
                json.dumps(
                    {
                        "id": f"vertex-{index}",
                        "name": marker,
                        "cached": True,
                        "completed": "2026-07-31T00:01:00Z",
                    }
                )
                + "\n"
                for index, marker in enumerate(verifier.NETWORK_VERTEX_MARKERS)
            ),
            encoding="utf-8",
        )
        return metadata_path, progress_path

    def test_prefix_and_full_build_evidence_use_distinct_source_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for dockerfile_kind in ("prefix", "full"):
                with self.subTest(dockerfile_kind=dockerfile_kind):
                    kind_root = root / dockerfile_kind
                    kind_root.mkdir()
                    metadata, progress = self._write_build_evidence(
                        kind_root,
                        dockerfile_kind=dockerfile_kind,
                    )
                    summary = verifier.validate_build_evidence(
                        metadata,
                        progress,
                        dockerfile_kind=dockerfile_kind,
                        require_network_vertices_cached=True,
                    )
                    self.assertEqual(summary["network_vertex_count"], 3)
                    self.assertEqual(summary["dockerfile_kind"], dockerfile_kind)


if __name__ == "__main__":
    unittest.main()
