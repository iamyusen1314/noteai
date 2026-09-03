#!/usr/bin/env python3
"""Fail-closed validation for the exact-5335 Admin dependency cache bundle."""

from __future__ import annotations

import argparse
import base64
import binascii
import gzip
import hashlib
import json
import math
import os
import re
import shutil
import stat
import tarfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any


RELEASE_COMMIT = "5335bdaed933b1f999b5f819c047ec50c11821ae"
RELEASE_TREE = "38e574e56406ba3380acb78edbe784508cc537cd"
DOCKERFILE_SHA256 = (
    "ed6282c422dde6e49c33da877bccf735dfbb19e29a834930fb2a1a52ef21b447"
)
PREFIX_DOCKERFILE_SHA256 = (
    "93fd024e5af678b7885bcab8e72d980a9f92cfc70de4f2fd2870284e25b8ec1e"
)
DOCKERIGNORE_SHA256 = (
    "d327ca46e4800b2af3c073c7e40bac93e0a042fec016fe6b798a5bd6944d3149"
)
REQUIREMENTS_SHA256 = (
    "1ef4150536e98b8057069981b1aadb469ca12f0f30f188a291af2f31e238724a"
)
REQUIREMENTS_API_SHA256 = (
    "0231c534fc2ca1ca503f5b29e19c503be995672cf20afd8203e207ffc8354ea9"
)
PYTHON_INDEX = "db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93"
PYTHON_AMD64 = "00af38ae2ed311628970782e8a2d7f014d8909dbc63cb97bc0a158187f4db045"
NODE_INDEX = "2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0"
NODE_AMD64 = "3d0f05455dea2c82e2f76e7e2543964c30f6b7d673fc1a83286736d44fe4c41c"
OCI_SOURCE = "https://github.com/iamyusen1314/noteai"
OCI_VERSION = "git-5335bda-amd64-r1"
OCI_CREATED = "2026-07-30T13:29:02Z"
CHUNK_BYTES = 268_435_456
MAXIMUM_GZIP_BYTES = 3_758_096_384
MAXIMUM_RAW_TAR_BYTES = 5_368_709_120
MAXIMUM_BLOB_BYTES = 4_294_967_296
MAXIMUM_EXTRACTED_CACHE_BYTES = 4_311_744_512
MAXIMUM_ARTIFACT_INPUT_BYTES = 4_026_531_840
MAXIMUM_PROVIDER_ARTIFACT_BYTES = 4_294_967_296
MAXIMUM_NON_CHUNK_FILE_BYTES = 134_217_728
MAXIMUM_CHUNK_COUNT = 14
MAXIMUM_TAR_MEMBERS = 100_000
NETWORK_VERTEX_MARKERS = (
    'npm pack "@meituan-travel/travel-cli@',
    "apt-get update && apt-get install",
    "pip install --no-cache-dir",
)
PREFIX_CONTEXT_FOLLOWPATHS = [
    "model/requirements-api.txt",
    "model/requirements.txt",
]
FULL_CONTEXT_FOLLOWPATHS = [
    "NoteAI_Pro_Demo_Framer.html",
    "model",
    "model/requirements-api.txt",
    "model/requirements.txt",
    "scripts/docker_entrypoint.sh",
    "scripts/migrate_managed_prompts_v04.py",
    "scripts/migrate_sqlite_to_postgres.py",
    "scripts/render_predeploy.py",
    "scripts/render_run_crawler.sh",
    "scripts/render_run_market_timing.sh",
    "scripts/render_start_admin.sh",
    "scripts/render_start_api.sh",
    "scripts/render_start_payment.sh",
]
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
CHUNK_RE = re.compile(r"^chunks/admin-dependency-cache\.tar\.gz\.part-(\d{4})$")
PACKAGE_NETWORK_RE = re.compile(
    r"(Downloading |Collecting |Get:\d+ https?://|"
    r"registry\.npmjs\.org|pypi\.org|deb\.debian\.org)",
    re.IGNORECASE,
)


class BundleError(ValueError):
    """The bundle or build evidence violated the reviewed contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reject_duplicate_object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BundleError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_non_finite_json_constant(value: str) -> None:
    raise BundleError(f"non-finite JSON number: {value}")


def parse_finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise BundleError(f"non-finite JSON number: {value}")
    return parsed


def strict_json_bytes(value: bytes, label: str) -> Any:
    try:
        return json.loads(
            value.decode("utf-8"),
            object_pairs_hook=reject_duplicate_object_pairs,
            parse_constant=reject_non_finite_json_constant,
            parse_float=parse_finite_json_float,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleError(f"{label} is not strict UTF-8 JSON: {exc}") from exc


def strict_json_file(path: Path) -> Any:
    try:
        return strict_json_bytes(path.read_bytes(), str(path))
    except OSError as exc:
        raise BundleError(f"cannot read {path}: {exc}") from exc


def require(condition: bool, message: str) -> None:
    if not condition:
        raise BundleError(message)


def require_exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    require(set(value) == expected, f"{label} keys changed")
    return value


def require_sha256(value: Any, label: str) -> str:
    require(isinstance(value, str) and SHA256_RE.fullmatch(value), f"{label} invalid")
    return value


def require_commit(value: Any, label: str) -> str:
    require(isinstance(value, str) and COMMIT_RE.fullmatch(value), f"{label} invalid")
    return value


def relative_regular_files(root: Path) -> set[str]:
    files: set[str] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        path_stat = path.lstat()
        require(
            stat.S_ISREG(path_stat.st_mode) or stat.S_ISDIR(path_stat.st_mode),
            f"bundle contains unsupported filesystem object: {relative}",
        )
        if stat.S_ISREG(path_stat.st_mode):
            require(path_stat.st_nlink == 1, f"bundle file is hard-linked: {relative}")
            files.add(relative)
    return files


def validate_bundle_size(bundle: Path, files: set[str]) -> int:
    total_bytes = 0
    for relative in files:
        size = (bundle / relative).stat().st_size
        require(size >= 0, f"bundle file size invalid: {relative}")
        if not relative.startswith("chunks/"):
            require(
                size <= MAXIMUM_NON_CHUNK_FILE_BYTES,
                f"non-chunk bundle file exceeds limit: {relative}",
            )
        total_bytes += size
        require(
            total_bytes <= MAXIMUM_ARTIFACT_INPUT_BYTES,
            "artifact input exceeds reviewed limit",
        )
    return total_bytes


def validate_checksum_file(
    bundle: Path,
    checksum_name: str,
    expected_files: set[str],
) -> str:
    checksum_path = bundle / checksum_name
    require(checksum_path.is_file(), f"{checksum_name} missing")
    entries: dict[str, str] = {}
    for line_number, line in enumerate(
        checksum_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        match = re.fullmatch(r"([0-9a-f]{64})  \./(.+)", line)
        require(match is not None, f"{checksum_name}:{line_number} malformed")
        digest, relative = match.groups()
        pure = PurePosixPath(relative)
        require(
            not pure.is_absolute() and ".." not in pure.parts and "." not in pure.parts,
            f"{checksum_name} has unsafe path: {relative}",
        )
        require(relative not in entries, f"{checksum_name} repeats {relative}")
        entries[relative] = digest
    require(set(entries) == expected_files, f"{checksum_name} file set changed")
    for relative, expected in entries.items():
        path = bundle / relative
        require(path.is_file(), f"checksummed file missing: {relative}")
        require(sha256_file(path) == expected, f"checksum mismatch: {relative}")
    return sha256_file(checksum_path)


def validate_base_index(path: Path, expected_index: str, expected_child: str) -> None:
    require(sha256_file(path) == expected_index, f"{path.name} digest changed")
    payload = strict_json_file(path)
    require_exact_keys(payload, {"schemaVersion", "mediaType", "manifests"}, path.name)
    require(payload["schemaVersion"] == 2, f"{path.name} schema changed")
    require(
        payload["mediaType"] == "application/vnd.oci.image.index.v1+json",
        f"{path.name} media type changed",
    )
    manifests = payload["manifests"]
    require(isinstance(manifests, list) and manifests, f"{path.name} manifests missing")
    amd64 = [
        item
        for item in manifests
        if isinstance(item, dict)
        and (item.get("platform") or {}).get("os") == "linux"
        and (item.get("platform") or {}).get("architecture") == "amd64"
        and not (item.get("platform") or {}).get("variant")
    ]
    require(len(amd64) == 1, f"{path.name} linux/amd64 child count changed")
    require(
        amd64[0].get("digest") == f"sha256:{expected_child}",
        f"{path.name} linux/amd64 child changed",
    )


def parse_time(value: Any, label: str) -> datetime:
    require(isinstance(value, str), f"{label} missing")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BundleError(f"{label} invalid") from exc


def validate_build_evidence(
    metadata_path: Path,
    progress_path: Path,
    *,
    dockerfile_kind: str,
    require_network_vertices_cached: bool,
) -> dict[str, Any]:
    require(dockerfile_kind in ("prefix", "full"), "Dockerfile kind changed")
    if dockerfile_kind == "prefix":
        dockerfile_sha256 = PREFIX_DOCKERFILE_SHA256
        expected_followpaths = PREFIX_CONTEXT_FOLLOWPATHS
        maximum_source_line = 80
        required_source_lines = {7, 80}
    else:
        dockerfile_sha256 = DOCKERFILE_SHA256
        expected_followpaths = FULL_CONTEXT_FOLLOWPATHS
        maximum_source_line = 100
        required_source_lines = {7, 80, 83, 100}
    metadata = strict_json_file(metadata_path)
    require(isinstance(metadata, dict), "build metadata root changed")
    provenance = metadata.get("buildx.build.provenance")
    require(isinstance(provenance, dict), "BuildKit provenance missing")
    require(
        provenance.get("buildType") == "https://mobyproject.org/buildkit@v1",
        "BuildKit provenance type changed",
    )
    invocation = provenance.get("invocation")
    require(isinstance(invocation, dict), "BuildKit invocation missing")
    require(
        invocation.get("configSource") == {"entryPoint": "Dockerfile"},
        "Dockerfile entry point changed",
    )
    parameters = invocation.get("parameters")
    require(isinstance(parameters, dict), "BuildKit invocation parameters missing")
    require(
        parameters.get("frontend") == "dockerfile.v0",
        "Dockerfile frontend changed",
    )
    require(
        parameters.get("args")
        == {
            "build-arg:NOTEAI_OCI_CREATED": OCI_CREATED,
            "build-arg:NOTEAI_OCI_REVISION": RELEASE_COMMIT,
            "build-arg:NOTEAI_OCI_SOURCE": OCI_SOURCE,
            "build-arg:NOTEAI_OCI_VERSION": OCI_VERSION,
            "target": "runtime-common",
        },
        "BuildKit target or OCI arguments changed",
    )
    require(
        invocation.get("environment") == {"platform": "linux/amd64"},
        "BuildKit platform changed",
    )
    materials = provenance.get("materials")
    require(isinstance(materials, list), "BuildKit materials missing")
    material_digests = {
        item.get("digest", {}).get("sha256")
        for item in materials
        if isinstance(item, dict)
    }
    require(
        material_digests == {NODE_INDEX, PYTHON_INDEX},
        "BuildKit base material set changed",
    )
    build_config = provenance.get("buildConfig")
    require(isinstance(build_config, dict), "BuildKit max provenance missing")
    llb = build_config.get("llbDefinition")
    require(isinstance(llb, list) and llb, "BuildKit LLB definition missing")
    image_sources: dict[str, str] = {}
    context_followpaths: list[list[str]] = []
    for item in llb:
        source = (((item.get("op") or {}).get("Op") or {}).get("source") or {})
        identifier = source.get("identifier")
        attrs = source.get("attrs") or {}
        if isinstance(identifier, str) and identifier.startswith("docker-image://"):
            image_sources[identifier] = attrs.get("image.resolvemode")
        if identifier == "local://context":
            raw_followpaths = attrs.get("local.followpaths")
            require(isinstance(raw_followpaths, str), "context followpaths missing")
            followpaths = strict_json_bytes(
                raw_followpaths.encode("utf-8"),
                "context followpaths",
            )
            require(isinstance(followpaths, list), "context followpaths changed")
            context_followpaths.append(sorted(followpaths))
    require(
        image_sources
        == {
            (
                "docker-image://docker.io/library/node:20-bookworm-slim@sha256:"
                f"{NODE_INDEX}"
            ): "pull",
            (
                "docker-image://docker.io/library/python:3.11.15-slim-trixie@"
                f"sha256:{PYTHON_INDEX}"
            ): "pull",
        },
        "BuildKit pinned base or pull resolution changed",
    )
    require(
        context_followpaths == [expected_followpaths],
        "BuildKit local context scope changed",
    )
    source_metadata = ((provenance.get("metadata") or {}).get(
        "https://mobyproject.org/buildkit@v1#metadata"
    ))
    require(isinstance(source_metadata, dict), "BuildKit source metadata missing")
    source = source_metadata.get("source")
    require(isinstance(source, dict), "BuildKit source locations missing")
    locations = source.get("locations")
    require(isinstance(locations, dict) and locations, "Dockerfile locations missing")
    seen_lines: set[int] = set()
    for location in locations.values():
        for location_group in (location or {}).get("locations", []):
            for line_range in location_group.get("ranges", []):
                start = (line_range.get("start") or {}).get("line")
                end = (line_range.get("end") or {}).get("line")
                require(
                    isinstance(start, int)
                    and isinstance(end, int)
                    and 1 <= start <= end <= maximum_source_line,
                    f"BuildKit used a Dockerfile line after {dockerfile_kind} target",
                )
                seen_lines.update(range(start, end + 1))
    require(
        required_source_lines <= seen_lines,
        f"Dockerfile {dockerfile_kind} source range incomplete",
    )
    infos = source.get("infos")
    require(isinstance(infos, list) and len(infos) == 1, "Dockerfile source info changed")
    dockerfile_data = infos[0].get("data")
    require(isinstance(dockerfile_data, str), "Dockerfile provenance bytes missing")
    try:
        decoded_dockerfile = base64.b64decode(dockerfile_data, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise BundleError("Dockerfile provenance base64 invalid") from exc
    require(
        hashlib.sha256(decoded_dockerfile).hexdigest() == dockerfile_sha256,
        "Dockerfile provenance bytes changed",
    )
    build_metadata = provenance.get("metadata")
    require(isinstance(build_metadata, dict), "BuildKit timing metadata missing")
    started = parse_time(build_metadata.get("buildStartedOn"), "buildStartedOn")
    finished = parse_time(build_metadata.get("buildFinishedOn"), "buildFinishedOn")
    duration_seconds = (finished - started).total_seconds()
    require(0 <= duration_seconds <= 7_200, "BuildKit duration invalid")

    progress_events: list[dict[str, Any]] = []
    try:
        with progress_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                event = strict_json_bytes(
                    line.encode("utf-8"),
                    f"{progress_path}:{line_number}",
                )
                require(isinstance(event, dict), "BuildKit progress event changed")
                progress_events.append(event)
    except OSError as exc:
        raise BundleError(f"cannot read BuildKit progress: {exc}") from exc
    require(progress_events, "BuildKit progress is empty")
    combined_progress = "\n".join(
        json.dumps(event, sort_keys=True, ensure_ascii=False)
        for event in progress_events
    )
    if require_network_vertices_cached:
        require(
            PACKAGE_NETWORK_RE.search(combined_progress) is None,
            "package-network output appeared during cache replay",
        )
    vertices: dict[str, dict[str, Any]] = {}
    for event in progress_events:
        vertex_id = event.get("vertex") or event.get("id")
        if not isinstance(vertex_id, str):
            continue
        aggregate = vertices.setdefault(
            vertex_id,
            {"names": set(), "cached": False, "completed": False},
        )
        if isinstance(event.get("name"), str):
            aggregate["names"].add(event["name"])
        if event.get("cached") is True:
            aggregate["cached"] = True
        if event.get("completed"):
            aggregate["completed"] = True
    cached_vertices: list[dict[str, str]] = []
    for marker in NETWORK_VERTEX_MARKERS:
        matches = [
            (vertex_id, value)
            for vertex_id, value in vertices.items()
            if any(marker in name for name in value["names"])
        ]
        require(len(matches) == 1, f"network vertex match changed: {marker}")
        vertex_id, value = matches[0]
        require(value["completed"], f"network vertex incomplete: {marker}")
        if require_network_vertices_cached:
            require(value["cached"], f"network vertex was not cached: {marker}")
        cached_vertices.append({"marker": marker, "vertex": vertex_id})
    return {
        "metadata_sha256": sha256_file(metadata_path),
        "progress_sha256": sha256_file(progress_path),
        "dockerfile_sha256": dockerfile_sha256,
        "dockerfile_kind": dockerfile_kind,
        "build_started_on": build_metadata["buildStartedOn"],
        "build_finished_on": build_metadata["buildFinishedOn"],
        "duration_seconds": duration_seconds,
        "network_vertex_count": len(cached_vertices),
        "network_vertices_cached": require_network_vertices_cached,
        "network_vertices": cached_vertices,
    }


def validate_manifest(bundle: Path) -> dict[str, Any]:
    manifest = strict_json_file(bundle / "manifest.json")
    require_exact_keys(
        manifest,
        {
            "schema_version",
            "task",
            "release",
            "build",
            "cache",
            "archive",
            "control",
            "next_gate",
        },
        "manifest",
    )
    require(
        manifest["schema_version"] == "noteai.admin-dependency-cache-export.v2",
        "manifest schema changed",
    )
    require(
        manifest["task"] == "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001",
        "manifest task changed",
    )
    release = require_exact_keys(
        manifest["release"],
        {
            "commit",
            "tree",
            "dockerfile_sha256",
            "dependency_prefix_lines",
            "first_application_copy_line",
            "dependency_prefix_sha256",
            "minimal_context_files",
        },
        "manifest.release",
    )
    require(release["commit"] == RELEASE_COMMIT, "release commit changed")
    require(release["tree"] == RELEASE_TREE, "release tree changed")
    require(release["dockerfile_sha256"] == DOCKERFILE_SHA256, "Dockerfile changed")
    require(release["dependency_prefix_lines"] == [1, 80], "prefix lines changed")
    require(release["first_application_copy_line"] == 83, "application COPY changed")
    require(
        release["dependency_prefix_sha256"] == PREFIX_DOCKERFILE_SHA256,
        "prefix Dockerfile changed",
    )
    require(
        release["minimal_context_files"]
        == [
            {"path": ".dockerignore", "sha256": DOCKERIGNORE_SHA256},
            {"path": "Dockerfile", "sha256": PREFIX_DOCKERFILE_SHA256},
            {
                "path": "model/requirements-api.txt",
                "sha256": REQUIREMENTS_API_SHA256,
            },
            {"path": "model/requirements.txt", "sha256": REQUIREMENTS_SHA256},
        ],
        "minimal context inventory changed",
    )
    build = require_exact_keys(
        manifest["build"],
        {
            "runner_architecture",
            "platform",
            "target",
            "pull",
            "output",
            "cache_export",
            "docker_engine_image_export_requested",
            "registry_export_requested",
            "transient_buildkit_sandboxes_expected",
            "buildx_client_version",
            "buildkit_driver",
            "buildkit_version",
            "buildkit_daemon_image_reference",
            "buildkit_daemon_image_id",
            "metadata_sha256",
            "progress_sha256",
            "duration_seconds",
            "base_images",
        },
        "manifest.build",
    )
    require(
        {
            "runner_architecture": build["runner_architecture"],
            "platform": build["platform"],
            "target": build["target"],
            "pull": build["pull"],
            "output": build["output"],
            "cache_export": build["cache_export"],
            "docker_engine_image_export_requested": build[
                "docker_engine_image_export_requested"
            ],
            "registry_export_requested": build["registry_export_requested"],
            "transient_buildkit_sandboxes_expected": build[
                "transient_buildkit_sandboxes_expected"
            ],
            "buildkit_driver": build["buildkit_driver"],
        }
        == {
            "runner_architecture": "x86_64",
            "platform": "linux/amd64",
            "target": "runtime-common",
            "pull": True,
            "output": "cacheonly",
            "cache_export": "type=local,mode=max,oci-mediatypes=true",
            "docker_engine_image_export_requested": False,
            "registry_export_requested": False,
            "transient_buildkit_sandboxes_expected": True,
            "buildkit_driver": "docker-container",
        },
        "build execution contract changed",
    )
    require(
        isinstance(build["buildx_client_version"], str)
        and build["buildx_client_version"],
        "Buildx client version missing",
    )
    require(
        isinstance(build["buildkit_version"], str) and build["buildkit_version"],
        "BuildKit daemon version missing",
    )
    require(
        isinstance(build["buildkit_daemon_image_reference"], str)
        and re.fullmatch(
            r"(?:docker\.io/)?moby/buildkit@sha256:[0-9a-f]{64}",
            build["buildkit_daemon_image_reference"],
        ),
        "BuildKit daemon image reference invalid",
    )
    require(
        isinstance(build["buildkit_daemon_image_id"], str)
        and re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            build["buildkit_daemon_image_id"],
        ),
        "BuildKit daemon image id invalid",
    )
    require_sha256(build["metadata_sha256"], "build metadata hash")
    require_sha256(build["progress_sha256"], "build progress hash")
    require(
        isinstance(build["duration_seconds"], (int, float))
        and 0 <= build["duration_seconds"] <= 7_200,
        "producer build duration invalid",
    )
    require(
        build["base_images"]
        == {
            "python": {
                "index": f"sha256:{PYTHON_INDEX}",
                "linux_amd64": f"sha256:{PYTHON_AMD64}",
            },
            "node": {
                "index": f"sha256:{NODE_INDEX}",
                "linux_amd64": f"sha256:{NODE_AMD64}",
            },
        },
        "base image identity changed",
    )
    producer_summary = validate_build_evidence(
        bundle / "cache-build-metadata.json",
        bundle / "producer-build.rawjson",
        dockerfile_kind="prefix",
        require_network_vertices_cached=False,
    )
    require(
        producer_summary["metadata_sha256"] == build["metadata_sha256"],
        "producer metadata binding changed",
    )
    require(
        producer_summary["progress_sha256"] == build["progress_sha256"],
        "producer progress binding changed",
    )
    require(
        producer_summary["duration_seconds"] == build["duration_seconds"],
        "producer duration binding changed",
    )

    cache = require_exact_keys(
        manifest["cache"],
        {
            "type",
            "mode",
            "compression",
            "compression_level",
            "cache_index_sha256",
            "oci_layout_sha256",
            "manifest_digest",
            "blob_count",
            "blob_bytes",
            "blobs",
        },
        "manifest.cache",
    )
    require(cache["type"] == "buildkit-local-oci-layout", "cache type changed")
    require(cache["mode"] == "max", "cache mode changed")
    require(cache["compression"] == "gzip", "cache compression changed")
    require(cache["compression_level"] == 1, "cache compression level changed")
    require_sha256(cache["cache_index_sha256"], "cache index hash")
    require_sha256(cache["oci_layout_sha256"], "OCI layout hash")
    require(
        isinstance(cache["manifest_digest"], str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", cache["manifest_digest"]),
        "cache manifest digest invalid",
    )
    require(
        isinstance(cache["blob_count"], int) and cache["blob_count"] > 0,
        "cache blob count invalid",
    )
    require(
        isinstance(cache["blob_bytes"], int)
        and 0 < cache["blob_bytes"] <= MAXIMUM_BLOB_BYTES,
        "cache blob bytes invalid",
    )
    require(
        isinstance(cache["blobs"], list)
        and len(cache["blobs"]) == cache["blob_count"],
        "cache blob inventory changed",
    )
    require(
        len({item.get("name") for item in cache["blobs"]})
        == cache["blob_count"],
        "cache blob inventory has duplicate names",
    )

    archive = require_exact_keys(
        manifest["archive"],
        {
            "format",
            "raw_tar_sha256",
            "raw_tar_bytes",
            "gzip_sha256",
            "gzip_bytes",
            "chunk_bytes_limit",
            "chunk_count",
            "chunks",
            "maximum_gzip_bytes",
            "maximum_extracted_cache_bytes",
            "artifact_input_maximum_bytes",
            "artifact_provider_maximum_bytes",
            "non_chunk_file_maximum_bytes",
        },
        "manifest.archive",
    )
    require(archive["format"] == "deterministic-tar-gzip", "archive format changed")
    require_sha256(archive["raw_tar_sha256"], "raw tar hash")
    require_sha256(archive["gzip_sha256"], "gzip hash")
    require(
        isinstance(archive["raw_tar_bytes"], int)
        and 0 < archive["raw_tar_bytes"] <= MAXIMUM_RAW_TAR_BYTES,
        "raw tar bytes invalid",
    )
    require(
        isinstance(archive["gzip_bytes"], int)
        and 0 < archive["gzip_bytes"] <= MAXIMUM_GZIP_BYTES,
        "gzip bytes invalid",
    )
    require(
        archive["maximum_gzip_bytes"] == MAXIMUM_GZIP_BYTES
        and archive["maximum_extracted_cache_bytes"]
        == MAXIMUM_EXTRACTED_CACHE_BYTES
        and archive["artifact_input_maximum_bytes"]
        == MAXIMUM_ARTIFACT_INPUT_BYTES
        and archive["artifact_provider_maximum_bytes"]
        == MAXIMUM_PROVIDER_ARTIFACT_BYTES
        and archive["non_chunk_file_maximum_bytes"]
        == MAXIMUM_NON_CHUNK_FILE_BYTES,
        "artifact size limits changed",
    )
    require(
        archive["raw_tar_bytes"] <= archive["gzip_bytes"] * 8,
        "archive expansion ratio exceeded",
    )
    require(archive["chunk_bytes_limit"] == CHUNK_BYTES, "chunk limit changed")
    require(
        isinstance(archive["chunk_count"], int)
        and 0 < archive["chunk_count"] <= MAXIMUM_CHUNK_COUNT,
        "chunk count invalid",
    )
    require(
        isinstance(archive["chunks"], list)
        and len(archive["chunks"]) == archive["chunk_count"],
        "chunk inventory changed",
    )

    control = require_exact_keys(
        manifest["control"],
        {
            "plan_checkpoint_commit",
            "control_commit",
            "request_sha256",
            "workflow_sha256",
            "export_helper_sha256",
            "import_helper_sha256",
            "bundle_verifier_sha256",
            "github_run_id",
            "github_run_attempt",
            "artifact_retention_days",
            "application_or_model_source_inputs_supplied_to_export",
            "buildkit_credential_or_secret_inputs_supplied",
            "registry_digest",
            "registry_publication_authorized",
            "deployment_authorized",
            "database_authorized",
            "service_mutation_authorized",
            "public_traffic_authorized",
        },
        "manifest.control",
    )
    require_commit(control["plan_checkpoint_commit"], "plan checkpoint")
    require_commit(control["control_commit"], "control commit")
    require_sha256(control["request_sha256"], "request hash")
    require_sha256(control["workflow_sha256"], "workflow hash")
    require_sha256(control["export_helper_sha256"], "export helper hash")
    require_sha256(control["import_helper_sha256"], "import helper hash")
    require_sha256(control["bundle_verifier_sha256"], "bundle verifier hash")
    require(
        isinstance(control["github_run_id"], str)
        and control["github_run_id"].isdigit()
        and int(control["github_run_id"]) > 0,
        "GitHub run id invalid",
    )
    require(control["github_run_attempt"] == 1, "GitHub rerun is not authorized")
    require(control["artifact_retention_days"] == 1, "artifact retention changed")
    for field in (
        "application_or_model_source_inputs_supplied_to_export",
        "buildkit_credential_or_secret_inputs_supplied",
        "registry_publication_authorized",
        "deployment_authorized",
        "database_authorized",
        "service_mutation_authorized",
        "public_traffic_authorized",
    ):
        require(control[field] is False, f"control authorization changed: {field}")
    require(control["registry_digest"] is None, "registry digest must remain null")
    require(
        sha256_file(bundle / "producer" / "export_admin_dependency_cache.sh")
        == control["export_helper_sha256"],
        "bundled export helper changed",
    )
    require(
        sha256_file(bundle / "builder" / "import_admin_dependency_cache.sh")
        == control["import_helper_sha256"],
        "bundled import helper changed",
    )
    require(
        sha256_file(
            bundle / "builder" / "verify_admin_dependency_cache_bundle.py"
        )
        == control["bundle_verifier_sha256"],
        "bundled verifier changed",
    )
    require(
        manifest["next_gate"]
        == {
            "provider_artifact_digest_acceptance_required": True,
            "authenticated_download_verification_required": True,
            "target_builder_import_required": True,
            "target_builder_cacheless_full_context_prefix_replay_required": True,
            "canonical_admin_build_same_builder_environment_required": True,
            "exact_buildkit_daemon_image_required": True,
            "canonical_admin_build_required": True,
            "fresh_scan_and_sbom_required": True,
            "private_publication_authorized": False,
        },
        "next gate changed",
    )
    validate_base_index(
        bundle / "python-base-index.json",
        PYTHON_INDEX,
        PYTHON_AMD64,
    )
    validate_base_index(bundle / "node-base-index.json", NODE_INDEX, NODE_AMD64)
    return manifest


def validate_chunks(bundle: Path, manifest: dict[str, Any], gzip_path: Path) -> None:
    archive = manifest["archive"]
    expected_names = [
        f"chunks/admin-dependency-cache.tar.gz.part-{index:04d}"
        for index in range(archive["chunk_count"])
    ]
    actual_names = [item.get("name") for item in archive["chunks"]]
    require(actual_names == expected_names, "chunk names are not contiguous")
    total_bytes = 0
    with gzip_path.open("wb") as output:
        for index, item in enumerate(archive["chunks"]):
            require_exact_keys(item, {"name", "sha256", "bytes"}, "chunk")
            relative = item["name"]
            require(CHUNK_RE.fullmatch(relative) is not None, "chunk name invalid")
            require_sha256(item["sha256"], "chunk hash")
            require(isinstance(item["bytes"], int) and item["bytes"] > 0, "chunk size")
            if index < archive["chunk_count"] - 1:
                require(item["bytes"] == CHUNK_BYTES, "non-final chunk size changed")
            else:
                require(item["bytes"] <= CHUNK_BYTES, "final chunk too large")
            path = bundle / relative
            require(path.is_file(), f"chunk missing: {relative}")
            require(path.stat().st_size == item["bytes"], f"chunk size changed: {relative}")
            require(sha256_file(path) == item["sha256"], f"chunk hash changed: {relative}")
            total_bytes += item["bytes"]
            with path.open("rb") as handle:
                shutil.copyfileobj(handle, output, length=1024 * 1024)
    require(total_bytes == archive["gzip_bytes"], "gzip byte total changed")
    require(gzip_path.stat().st_size == archive["gzip_bytes"], "gzip size changed")
    require(sha256_file(gzip_path) == archive["gzip_sha256"], "gzip hash changed")


def bounded_decompress(gzip_path: Path, raw_tar: Path, expected_bytes: int) -> None:
    written = 0
    try:
        with gzip.open(gzip_path, "rb") as source, raw_tar.open("wb") as output:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                require(
                    written <= MAXIMUM_RAW_TAR_BYTES,
                    "raw archive exceeds extraction limit",
                )
                output.write(chunk)
    except (OSError, EOFError) as exc:
        raise BundleError(f"gzip decompression failed: {exc}") from exc
    require(written == expected_bytes, "raw archive size changed")


def safe_extract_tar(raw_tar: Path, extract_to: Path, expected_bytes: int) -> None:
    require(not extract_to.exists(), "cache extraction directory already exists")
    try:
        with tarfile.open(raw_tar, "r:") as archive:
            members: list[tarfile.TarInfo] = []
            for member in archive:
                require(
                    len(members) < MAXIMUM_TAR_MEMBERS,
                    "tar member count exceeds reviewed limit",
                )
                members.append(member)
            require(members, "tar archive is empty")
            seen: set[str] = set()
            directories: set[str] = set()
            required_directories: set[str] = set()
            regular_bytes = 0
            normalized_members: list[tuple[tarfile.TarInfo, str]] = []
            for member in members:
                name = member.name
                pure = PurePosixPath(name)
                require(not pure.is_absolute(), f"absolute tar path: {name}")
                require(".." not in pure.parts, f"parent traversal tar path: {name}")
                normalized = pure.as_posix().removeprefix("./")
                if normalized in ("", "."):
                    normalized = "."
                require(normalized not in seen, f"duplicate tar member: {normalized}")
                seen.add(normalized)
                require(member.uid == 0 and member.gid == 0, "tar owner changed")
                require(member.mtime == 0, "tar timestamp changed")
                sparse_headers = {
                    key
                    for key in member.pax_headers
                    if "gnu.sparse" in key.lower()
                    or key.lower() == "schily.realsize"
                }
                require(not member.sparse, f"sparse tar member rejected: {name}")
                require(
                    not sparse_headers,
                    f"sparse tar metadata rejected: {name}",
                )
                if member.isdir():
                    require(member.mode == 0o700, f"tar directory mode changed: {name}")
                    directories.add(normalized)
                    normalized_members.append((member, normalized))
                    continue
                require(member.isreg(), f"unsupported tar member type: {name}")
                require(normalized != ".", "tar root must be a directory")
                require(member.mode == 0o600, f"tar file mode changed: {name}")
                require(
                    0 <= member.size <= MAXIMUM_BLOB_BYTES,
                    f"tar member size exceeds reviewed limit: {name}",
                )
                regular_bytes += member.size
                require(
                    regular_bytes <= MAXIMUM_EXTRACTED_CACHE_BYTES,
                    "tar extracted bytes exceed reviewed limit",
                )
                normalized_members.append((member, normalized))
            for _, normalized in normalized_members:
                pure = PurePosixPath(normalized)
                parent_parts = pure.parts[:-1]
                for length in range(1, len(parent_parts) + 1):
                    required_directories.add(
                        PurePosixPath(*parent_parts[:length]).as_posix()
                    )
            require(
                all(
                    parent not in seen or parent in directories
                    for parent in required_directories
                ),
                "tar path topology changed",
            )

            require(
                regular_bytes <= expected_bytes,
                "tar regular bytes exceed declared raw archive",
            )
            extract_to.mkdir(mode=0o700, parents=True)
            written_bytes = 0
            for member, normalized in normalized_members:
                name = member.name
                if member.isdir():
                    if normalized != ".":
                        destination = extract_to / normalized
                        destination.mkdir(mode=0o700, parents=True, exist_ok=False)
                    continue
                destination = extract_to / normalized
                destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                source = archive.extractfile(member)
                require(source is not None, f"cannot read tar member: {name}")
                with source, destination.open("xb") as output:
                    remaining = member.size
                    while remaining:
                        chunk = source.read(min(1024 * 1024, remaining))
                        require(chunk, f"truncated tar member: {name}")
                        require(
                            written_bytes + len(chunk)
                            <= MAXIMUM_EXTRACTED_CACHE_BYTES,
                            "tar write exceeds reviewed extraction limit",
                        )
                        output.write(chunk)
                        written_bytes += len(chunk)
                        remaining -= len(chunk)
                os.chmod(destination, 0o600)
            require(
                written_bytes == regular_bytes,
                "extracted cache byte total changed",
            )
    except (tarfile.TarError, OSError) as exc:
        raise BundleError(f"safe tar extraction failed: {exc}") from exc
    actual_bytes = sum(
        path.stat().st_size for path in extract_to.rglob("*") if path.is_file()
    )
    require(actual_bytes == regular_bytes, "extracted cache size invalid")


def descriptor_blob(cache_root: Path, descriptor: Any, label: str) -> Path:
    require(isinstance(descriptor, dict), f"{label} descriptor changed")
    digest = descriptor.get("digest")
    size = descriptor.get("size")
    require(
        isinstance(digest, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", digest),
        f"{label} digest invalid",
    )
    require(isinstance(size, int) and size > 0, f"{label} size invalid")
    path = cache_root / "blobs" / "sha256" / digest.removeprefix("sha256:")
    require(path.is_file(), f"{label} blob missing")
    require(path.stat().st_size == size, f"{label} blob size changed")
    require(sha256_file(path) == digest.removeprefix("sha256:"), f"{label} hash changed")
    return path


def validate_cache_config(
    config_payload: Any,
    root_layers: list[dict[str, Any]],
) -> None:
    config = require_exact_keys(
        config_payload,
        {"layers", "records"},
        "BuildKit cache config",
    )
    cache_layers = config["layers"]
    records = config["records"]
    require(
        isinstance(cache_layers, list) and cache_layers,
        "BuildKit cache layer inventory missing",
    )
    require(
        isinstance(records, list) and records,
        "BuildKit cache record inventory missing",
    )
    root_layer_digests = [layer.get("digest") for layer in root_layers]
    require(
        len(root_layer_digests) == len(set(root_layer_digests)),
        "OCI cache root layer descriptors repeat",
    )
    root_descriptors = {
        layer["digest"]: layer
        for layer in root_layers
    }
    cache_layer_digests: list[str] = []
    cache_layer_parents: list[int] = []
    for index_number, layer in enumerate(cache_layers):
        require(isinstance(layer, dict), "BuildKit cache layer changed")
        require(
            set(layer) <= {"blob", "parent", "annotations"}
            and "blob" in layer,
            "BuildKit cache layer keys changed",
        )
        blob = layer["blob"]
        require(
            isinstance(blob, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", blob),
            "BuildKit cache layer blob invalid",
        )
        require(blob in root_descriptors, "BuildKit cache layer blob missing")
        cache_layer_digests.append(blob)
        parent = layer.get("parent", 0)
        require(
            isinstance(parent, int)
            and not isinstance(parent, bool)
            and -1 <= parent < len(cache_layers)
            and parent != index_number,
            "BuildKit cache layer parent invalid",
        )
        cache_layer_parents.append(parent)
        annotations = layer.get("annotations")
        if annotations is not None:
            require(isinstance(annotations, dict), "cache layer annotations changed")
            require(
                set(annotations)
                <= {"mediaType", "diffID", "size", "createdAt"},
                "cache layer annotation keys changed",
            )
            if "mediaType" in annotations:
                require(
                    annotations["mediaType"]
                    == root_descriptors[blob]["mediaType"],
                    "cache layer media type binding changed",
                )
            if "diffID" in annotations:
                require(
                    isinstance(annotations["diffID"], str)
                    and re.fullmatch(
                        r"sha256:[0-9a-f]{64}",
                        annotations["diffID"],
                    ),
                    "cache layer diffID invalid",
                )
            if "size" in annotations:
                require(
                    annotations["size"] == root_descriptors[blob]["size"],
                    "cache layer size binding changed",
                )
            if "createdAt" in annotations:
                parse_time(
                    annotations["createdAt"],
                    f"cache layer {index_number} createdAt",
                )
    require(
        set(cache_layer_digests) == set(root_descriptors)
        and len(cache_layer_digests) == len(set(cache_layer_digests)),
        "BuildKit cache layer closure changed",
    )
    for start in range(len(cache_layer_parents)):
        seen: set[int] = set()
        current = start
        while current != -1:
            require(current not in seen, "BuildKit cache layer parent cycle")
            seen.add(current)
            current = cache_layer_parents[current]

    record_links: list[set[int]] = []
    record_layer_indexes: list[set[int]] = []
    result_bearing_records: set[int] = set()
    for record_index, record in enumerate(records):
        require(isinstance(record, dict), "BuildKit cache record changed")
        require(
            set(record) <= {"layers", "chains", "digest", "inputs"}
            and "digest" in record,
            "BuildKit cache record keys changed",
        )
        require(
            isinstance(record["digest"], str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", record["digest"]),
            "BuildKit cache record digest invalid",
        )
        results = record.get("layers", [])
        chains = record.get("chains", [])
        require(isinstance(results, list), "BuildKit cache results changed")
        require(isinstance(chains, list), "BuildKit cache chains changed")
        referenced_layers: set[int] = set()
        if results or chains:
            result_bearing_records.add(record_index)
        for result_index, result in enumerate(results):
            require(isinstance(result, dict), "BuildKit cache result changed")
            result = require_exact_keys(
                result,
                {"layer"} | ({"createdAt"} if "createdAt" in result else set()),
                f"BuildKit cache result {record_index}:{result_index}",
            )
            layer_index = result["layer"]
            require(
                isinstance(layer_index, int)
                and not isinstance(layer_index, bool)
                and 0 <= layer_index < len(cache_layers),
                "BuildKit cache result layer invalid",
            )
            referenced_layers.add(layer_index)
            if "createdAt" in result:
                parse_time(
                    result["createdAt"],
                    f"cache result {record_index}:{result_index} createdAt",
                )
        for chain_index, chain in enumerate(chains):
            require(isinstance(chain, dict), "BuildKit cache chain changed")
            chain = require_exact_keys(
                chain,
                {"layers"} | ({"createdAt"} if "createdAt" in chain else set()),
                f"BuildKit cache chain {record_index}:{chain_index}",
            )
            layer_indexes = chain["layers"]
            require(
                isinstance(layer_indexes, list) and layer_indexes,
                "BuildKit cache chain layers missing",
            )
            require(
                all(
                    isinstance(layer_index, int)
                    and not isinstance(layer_index, bool)
                    and 0 <= layer_index < len(cache_layers)
                    for layer_index in layer_indexes
                ),
                "BuildKit cache chain layer invalid",
            )
            referenced_layers.update(layer_indexes)
            if "createdAt" in chain:
                parse_time(
                    chain["createdAt"],
                    f"cache chain {record_index}:{chain_index} createdAt",
                )
        links: set[int] = set()
        inputs = record.get("inputs", [])
        require(isinstance(inputs, list), "BuildKit cache inputs changed")
        for input_index, input_group in enumerate(inputs):
            require(
                isinstance(input_group, list) and input_group,
                "BuildKit cache input group empty",
            )
            for link_index, cache_input in enumerate(input_group):
                require(isinstance(cache_input, dict), "BuildKit cache input changed")
                require(
                    set(cache_input) <= {"selector", "link"}
                    and "link" in cache_input,
                    "BuildKit cache input keys changed",
                )
                link = cache_input["link"]
                require(
                    isinstance(link, int)
                    and not isinstance(link, bool)
                    and 0 <= link < len(records)
                    and link != record_index,
                    "BuildKit cache record link invalid",
                )
                selector = cache_input.get("selector")
                if selector is not None:
                    require(
                        isinstance(selector, str),
                        "BuildKit cache selector changed",
                    )
                links.add(link)
        record_links.append(links)
        record_layer_indexes.append(referenced_layers)
    for start in range(len(record_links)):
        visited: set[int] = set()
        active: set[int] = set()

        def visit(record_index: int) -> None:
            if record_index in visited:
                return
            require(record_index not in active, "BuildKit cache record link cycle")
            active.add(record_index)
            for linked in record_links[record_index]:
                visit(linked)
            active.remove(record_index)
            visited.add(record_index)

        visit(start)
    require(
        result_bearing_records,
        "BuildKit cache result-bearing record missing",
    )
    reachable_records: set[int] = set()

    def follow_record(record_index: int) -> None:
        if record_index in reachable_records:
            return
        reachable_records.add(record_index)
        for linked in record_links[record_index]:
            follow_record(linked)

    for record_index in result_bearing_records:
        follow_record(record_index)
    require(
        reachable_records == set(range(len(records))),
        "BuildKit cache record reachability changed",
    )

    reachable_layers: set[int] = set()
    for record_index in reachable_records:
        reachable_layers.update(record_layer_indexes[record_index])
    for layer_index in tuple(reachable_layers):
        current = cache_layer_parents[layer_index]
        while current != -1:
            reachable_layers.add(current)
            current = cache_layer_parents[current]
    require(
        reachable_layers == set(range(len(cache_layers))),
        "BuildKit cache layer reachability changed",
    )


def validate_oci_cache(cache_root: Path, manifest: dict[str, Any]) -> None:
    layout = strict_json_file(cache_root / "oci-layout")
    require(layout == {"imageLayoutVersion": "1.0.0"}, "OCI layout changed")
    index = strict_json_file(cache_root / "index.json")
    require(
        set(index)
        in (
            {"schemaVersion", "manifests"},
            {"schemaVersion", "mediaType", "manifests"},
        ),
        "OCI index keys changed",
    )
    require(index["schemaVersion"] == 2, "OCI index schema changed")
    if "mediaType" in index:
        require(
            index["mediaType"] == "application/vnd.oci.image.index.v1+json",
            "OCI index media type changed",
        )
    descriptors = index["manifests"]
    require(isinstance(descriptors, list) and len(descriptors) == 1, "OCI manifest count")
    root_descriptor = descriptors[0]
    require(
        root_descriptor.get("mediaType")
        == "application/vnd.oci.image.manifest.v1+json",
        "OCI cache manifest media type changed",
    )
    root_path = descriptor_blob(cache_root, root_descriptor, "OCI cache manifest")
    root_manifest = strict_json_file(root_path)
    require(
        set(root_manifest) in (
            {"schemaVersion", "mediaType", "config", "layers"},
            {"schemaVersion", "config", "layers"},
        ),
        "OCI cache manifest keys changed",
    )
    require(root_manifest["schemaVersion"] == 2, "OCI cache manifest schema changed")
    if "mediaType" in root_manifest:
        require(
            root_manifest["mediaType"] == "application/vnd.oci.image.manifest.v1+json",
            "OCI cache embedded media type changed",
        )
    config = root_manifest["config"]
    require(
        config.get("mediaType") == "application/vnd.buildkit.cacheconfig.v0",
        "BuildKit cache config media type changed",
    )
    config_path = descriptor_blob(cache_root, config, "BuildKit cache config")
    config_payload = strict_json_file(config_path)
    layers = root_manifest["layers"]
    require(isinstance(layers, list) and layers, "OCI cache layers missing")
    referenced = {
        root_descriptor["digest"].removeprefix("sha256:"),
        config["digest"].removeprefix("sha256:"),
    }
    for index_number, layer in enumerate(layers):
        require(
            layer.get("mediaType") == "application/vnd.oci.image.layer.v1.tar+gzip",
            "OCI cache layer media type changed",
        )
        descriptor_blob(cache_root, layer, f"OCI cache layer {index_number}")
        referenced.add(layer["digest"].removeprefix("sha256:"))
    validate_cache_config(config_payload, layers)
    blob_root = cache_root / "blobs" / "sha256"
    blob_paths = list(blob_root.iterdir())
    require(
        all(path.is_file() and SHA256_RE.fullmatch(path.name) for path in blob_paths),
        "OCI blob directory contains an unsupported entry",
    )
    actual_blobs = {path.name for path in blob_paths}
    require(actual_blobs == referenced, "OCI cache blob closure changed")
    cache_manifest = manifest["cache"]
    require(
        root_descriptor["digest"] == cache_manifest["manifest_digest"],
        "cache manifest digest binding changed",
    )
    require(
        sha256_file(cache_root / "index.json") == cache_manifest["cache_index_sha256"],
        "cache index binding changed",
    )
    require(
        sha256_file(cache_root / "oci-layout") == cache_manifest["oci_layout_sha256"],
        "OCI layout binding changed",
    )
    inventory = cache_manifest["blobs"]
    require(
        {
            item.get("name"): (item.get("sha256"), item.get("bytes"))
            for item in inventory
        }
        == {
            name: (
                name,
                (blob_root / name).stat().st_size,
            )
            for name in sorted(actual_blobs)
        },
        "cache blob inventory binding changed",
    )
    require(
        sum((blob_root / name).stat().st_size for name in actual_blobs)
        == cache_manifest["blob_bytes"],
        "cache blob byte total changed",
    )


def validate_core(bundle: Path, extract_to: Path) -> dict[str, Any]:
    require(bundle.is_dir(), "bundle directory missing")
    files = relative_regular_files(bundle)
    validate_bundle_size(bundle, files)
    final_additions = {
        "portability/import-build-metadata.json",
        "portability/import-build.rawjson",
        "portability/replay-build-metadata.json",
        "portability/replay-build.rawjson",
        "portability/proof.json",
        "SHA256SUMS",
    }
    present_final_additions = files & final_additions
    require(
        not present_final_additions
        or present_final_additions == final_additions,
        "partial portability evidence present",
    )
    core_scope = files - final_additions
    core_files = core_scope - {"CORE_SHA256SUMS"}
    manifest = validate_manifest(bundle)
    expected_core_files = {
        "manifest.json",
        "cache-build-metadata.json",
        "producer-build.rawjson",
        "python-base-index.json",
        "node-base-index.json",
        "cache-index.json",
        "oci-layout",
        "producer/export_admin_dependency_cache.sh",
        "builder/import_admin_dependency_cache.sh",
        "builder/verify_admin_dependency_cache_bundle.py",
        *{item["name"] for item in manifest["archive"]["chunks"]},
    }
    require(core_files == expected_core_files, "core bundle file set changed")
    validate_checksum_file(bundle, "CORE_SHA256SUMS", core_files)
    chunk_files = {name for name in core_files if name.startswith("chunks/")}
    require(
        chunk_files == {item["name"] for item in manifest["archive"]["chunks"]},
        "core chunk file set changed",
    )
    work = extract_to.parent / f".{extract_to.name}-archive-work"
    require(not work.exists(), "archive work directory already exists")
    work.mkdir(mode=0o700)
    gzip_path = work / "cache.tar.gz"
    raw_tar = work / "cache.tar"
    try:
        validate_chunks(bundle, manifest, gzip_path)
        bounded_decompress(
            gzip_path,
            raw_tar,
            manifest["archive"]["raw_tar_bytes"],
        )
        require(
            sha256_file(raw_tar) == manifest["archive"]["raw_tar_sha256"],
            "raw archive hash changed",
        )
        safe_extract_tar(
            raw_tar,
            extract_to,
            manifest["archive"]["raw_tar_bytes"],
        )
        validate_oci_cache(extract_to, manifest)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return manifest


def validate_portability(bundle: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    proof = strict_json_file(bundle / "portability" / "proof.json")
    require_exact_keys(
        proof,
        {
            "schema_version",
            "task",
            "release_commit",
            "manifest_sha256",
            "core_sums_sha256",
            "producer",
            "consumer",
            "import",
            "cacheless_replay",
            "controls",
        },
        "portability proof",
    )
    require(
        proof["schema_version"] == "noteai.admin-dependency-cache-portability.v1",
        "portability schema changed",
    )
    require(proof["task"] == manifest["task"], "portability task changed")
    require(proof["release_commit"] == RELEASE_COMMIT, "portability release changed")
    require(
        proof["manifest_sha256"] == sha256_file(bundle / "manifest.json"),
        "portability manifest binding changed",
    )
    require(
        proof["core_sums_sha256"] == sha256_file(bundle / "CORE_SHA256SUMS"),
        "portability core-sums binding changed",
    )
    producer = require_exact_keys(
        proof["producer"],
        {
            "builder_name",
            "driver",
            "buildkit_version",
            "buildkit_daemon_image_reference",
            "buildkit_daemon_image_id",
        },
        "portability producer",
    )
    consumer = require_exact_keys(
        proof["consumer"],
        {
            "builder_name",
            "driver",
            "buildkit_version",
            "buildkit_daemon_image_reference",
            "buildkit_daemon_image_id",
        },
        "portability consumer",
    )
    require(producer["builder_name"] != consumer["builder_name"], "consumer not fresh")
    require(
        producer["driver"] == consumer["driver"] == "docker-container",
        "portability builder driver changed",
    )
    require(
        producer["buildkit_version"]
        == consumer["buildkit_version"]
        == manifest["build"]["buildkit_version"],
        "producer/consumer BuildKit versions differ",
    )
    require(
        producer["buildkit_daemon_image_reference"]
        == consumer["buildkit_daemon_image_reference"]
        == manifest["build"]["buildkit_daemon_image_reference"],
        "producer/consumer BuildKit image references differ",
    )
    require(
        producer["buildkit_daemon_image_id"]
        == consumer["buildkit_daemon_image_id"]
        == manifest["build"]["buildkit_daemon_image_id"],
        "producer/consumer BuildKit image ids differ",
    )
    import_summary = validate_build_evidence(
        bundle / "portability" / "import-build-metadata.json",
        bundle / "portability" / "import-build.rawjson",
        dockerfile_kind="prefix",
        require_network_vertices_cached=True,
    )
    replay_summary = validate_build_evidence(
        bundle / "portability" / "replay-build-metadata.json",
        bundle / "portability" / "replay-build.rawjson",
        dockerfile_kind="full",
        require_network_vertices_cached=True,
    )
    require(proof["import"] == import_summary | {"cache_from_local": True}, "import proof")
    require(
        proof["cacheless_replay"]
        == replay_summary
        | {
            "cache_from_local": False,
            "external_cache_removed_before_replay": True,
            "full_release_context_used": True,
        },
        "cacheless replay proof changed",
    )
    require(
        proof["controls"]
        == {
            "github_run_attempt": 1,
            "image_or_registry_output_requested": False,
            "dependency_prefix_application_or_model_source_inputs_supplied": False,
            "full_replay_release_context_used": True,
            "buildkit_credential_or_secret_inputs_supplied": False,
            "upload_allowed_only_after_cleanup": True,
        },
        "portability controls changed",
    )
    return proof


def validate_final(
    bundle: Path,
    extract_to: Path,
    expected_sums_sha256: str | None,
) -> dict[str, Any]:
    files = relative_regular_files(bundle)
    artifact_input_bytes = validate_bundle_size(bundle, files)
    expected_final_additions = {
        "portability/import-build-metadata.json",
        "portability/import-build.rawjson",
        "portability/replay-build-metadata.json",
        "portability/replay-build.rawjson",
        "portability/proof.json",
        "SHA256SUMS",
    }
    require(expected_final_additions <= files, "portability evidence missing")
    final_files = files - {"SHA256SUMS"}
    sums_sha256 = validate_checksum_file(bundle, "SHA256SUMS", final_files)
    if expected_sums_sha256 is not None:
        require_sha256(expected_sums_sha256, "expected final sums hash")
        require(sums_sha256 == expected_sums_sha256, "final sums trust root changed")
    core_extract = extract_to
    manifest = validate_core(bundle, core_extract)
    proof = validate_portability(bundle, manifest)
    return {
        "manifest_sha256": sha256_file(bundle / "manifest.json"),
        "core_sums_sha256": sha256_file(bundle / "CORE_SHA256SUMS"),
        "final_sums_sha256": sums_sha256,
        "portability_proof_sha256": sha256_file(
            bundle / "portability" / "proof.json"
        ),
        "control_commit": manifest["control"]["control_commit"],
        "request_sha256": manifest["control"]["request_sha256"],
        "github_run_id": manifest["control"]["github_run_id"],
        "github_run_attempt": manifest["control"]["github_run_attempt"],
        "producer_buildkit_version": manifest["build"]["buildkit_version"],
        "consumer_buildkit_version": proof["consumer"]["buildkit_version"],
        "artifact_input_bytes": artifact_input_bytes,
        "artifact_input_maximum_bytes": MAXIMUM_ARTIFACT_INPUT_BYTES,
        "artifact_provider_maximum_bytes": MAXIMUM_PROVIDER_ARTIFACT_BYTES,
    }


def write_json(path: Path | None, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path is None:
        print(text, end="")
        return
    require(not path.exists(), f"output already exists: {path}")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o600)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    core = subparsers.add_parser("verify-core")
    core.add_argument("--bundle", type=Path, required=True)
    core.add_argument("--extract-to", type=Path, required=True)
    core.add_argument("--output", type=Path)

    final = subparsers.add_parser("verify-final")
    final.add_argument("--bundle", type=Path, required=True)
    final.add_argument("--extract-to", type=Path, required=True)
    final.add_argument("--expected-sums-sha256")
    final.add_argument("--output", type=Path)

    build = subparsers.add_parser("verify-build")
    build.add_argument("--metadata", type=Path, required=True)
    build.add_argument("--progress", type=Path, required=True)
    build.add_argument(
        "--dockerfile",
        choices=("prefix", "full"),
        required=True,
    )
    build.add_argument("--require-network-cached", action="store_true")
    build.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "verify-core":
            manifest = validate_core(args.bundle.resolve(), args.extract_to.resolve())
            payload = {
                "manifest_sha256": sha256_file(args.bundle / "manifest.json"),
                "core_sums_sha256": sha256_file(args.bundle / "CORE_SHA256SUMS"),
                "control_commit": manifest["control"]["control_commit"],
            }
        elif args.command == "verify-final":
            payload = validate_final(
                args.bundle.resolve(),
                args.extract_to.resolve(),
                args.expected_sums_sha256,
            )
        else:
            payload = validate_build_evidence(
                args.metadata.resolve(),
                args.progress.resolve(),
                dockerfile_kind=args.dockerfile,
                require_network_vertices_cached=args.require_network_cached,
            )
        write_json(args.output.resolve() if args.output else None, payload)
    except (BundleError, OSError) as exc:
        print(f"FAIL: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
