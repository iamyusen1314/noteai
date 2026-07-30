#!/usr/bin/env python3
"""Verify the authenticated GitHub artifact download and target transfer."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any


REPOSITORY = "iamyusen1314/noteai"
ARTIFACT_NAME = "admin-dependency-prefix-cache-5335bda-v2"
RELEASE_COMMIT = "5335bdaed933b1f999b5f819c047ec50c11821ae"
MAXIMUM_ARTIFACT_INPUT_BYTES = 4_026_531_840
MAXIMUM_PROVIDER_ARTIFACT_BYTES = 4_294_967_296
MAXIMUM_NON_CHUNK_FILE_BYTES = 134_217_728
MAXIMUM_CHUNK_FILE_BYTES = 268_435_456
MAXIMUM_ZIP_MEMBERS = 100
TRANSPORT_PART_BYTES = 268_435_456
MAXIMUM_TRANSPORT_PARTS = 16
TRANSPORT_PART_RE = re.compile(r"^artifact\.zip\.part-(\d{4})$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class DownloadError(ValueError):
    """The provider download or transferred receipt violated its contract."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DownloadError(message)


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
            raise DownloadError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_non_finite_json_constant(value: str) -> None:
    raise DownloadError(f"non-finite JSON number: {value}")


def parse_finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise DownloadError(f"non-finite JSON number: {value}")
    return parsed


def strict_json_file(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_object_pairs,
            parse_constant=reject_non_finite_json_constant,
            parse_float=parse_finite_json_float,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DownloadError(f"cannot read strict JSON {path}: {exc}") from exc


def parse_time(value: Any, label: str) -> datetime:
    require(isinstance(value, str), f"{label} missing")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DownloadError(f"{label} invalid") from exc


def safe_extract_provider_zip(zip_path: Path, extract_to: Path) -> None:
    require(zip_path.is_file(), "provider artifact ZIP missing")
    require(
        0 < zip_path.stat().st_size <= MAXIMUM_PROVIDER_ARTIFACT_BYTES,
        "provider artifact ZIP size invalid",
    )
    require(not extract_to.exists(), "provider bundle extraction target already exists")
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            members = archive.infolist()
            require(
                0 < len(members) <= MAXIMUM_ZIP_MEMBERS,
                "provider ZIP member count invalid",
            )
            names: set[str] = set()
            regular_bytes = 0
            normalized_members: list[tuple[zipfile.ZipInfo, str]] = []
            for member in members:
                require(not (member.flag_bits & 0x1), "encrypted ZIP member rejected")
                require(
                    member.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                    "unsupported ZIP compression",
                )
                pure = PurePosixPath(member.filename)
                require(
                    not pure.is_absolute()
                    and ".." not in pure.parts
                    and "." not in pure.parts,
                    f"unsafe provider ZIP path: {member.filename}",
                )
                normalized = pure.as_posix().rstrip("/")
                require(normalized and normalized not in names, "duplicate ZIP member")
                names.add(normalized)
                unix_mode = (member.external_attr >> 16) & 0xFFFF
                if unix_mode:
                    require(
                        stat.S_ISREG(unix_mode) or stat.S_ISDIR(unix_mode),
                        "unsupported ZIP filesystem object",
                    )
                if member.is_dir():
                    normalized_members.append((member, normalized))
                    continue
                limit = (
                    MAXIMUM_CHUNK_FILE_BYTES
                    if normalized.startswith("chunks/")
                    else MAXIMUM_NON_CHUNK_FILE_BYTES
                )
                require(
                    0 <= member.file_size <= limit,
                    f"provider ZIP member exceeds limit: {normalized}",
                )
                regular_bytes += member.file_size
                require(
                    regular_bytes <= MAXIMUM_ARTIFACT_INPUT_BYTES,
                    "provider ZIP uncompressed bytes exceed reviewed limit",
                )
                normalized_members.append((member, normalized))

            extract_to.mkdir(mode=0o700, parents=True)
            written = 0
            for member, normalized in sorted(
                normalized_members,
                key=lambda item: (len(PurePosixPath(item[1]).parts), item[1]),
            ):
                if member.is_dir():
                    (extract_to / normalized).mkdir(
                        mode=0o700,
                        parents=True,
                        exist_ok=False,
                    )
            for member, normalized in normalized_members:
                destination = extract_to / normalized
                if member.is_dir():
                    continue
                destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                remaining = member.file_size
                with archive.open(member, "r") as source, destination.open("xb") as output:
                    while remaining:
                        chunk = source.read(min(1024 * 1024, remaining))
                        require(chunk, f"truncated ZIP member: {normalized}")
                        require(
                            written + len(chunk) <= MAXIMUM_ARTIFACT_INPUT_BYTES,
                            "provider ZIP extraction exceeds reviewed limit",
                        )
                        output.write(chunk)
                        written += len(chunk)
                        remaining -= len(chunk)
                os.chmod(destination, 0o600)
            require(written == regular_bytes, "provider ZIP byte total changed")
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise DownloadError(f"provider ZIP extraction failed: {exc}") from exc


def split_provider_zip(zip_path: Path, transport_dir: Path) -> dict[str, Any]:
    require(not transport_dir.exists(), "provider transport directory already exists")
    transport_dir.mkdir(mode=0o700, parents=True)
    parts: list[dict[str, Any]] = []
    with zip_path.open("rb") as source:
        for index in range(MAXIMUM_TRANSPORT_PARTS):
            payload = source.read(TRANSPORT_PART_BYTES)
            if not payload:
                break
            name = f"artifact.zip.part-{index:04d}"
            path = transport_dir / name
            path.write_bytes(payload)
            os.chmod(path, 0o600)
            parts.append(
                {
                    "name": name,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "bytes": len(payload),
                }
            )
        require(not source.read(1), "provider ZIP exceeds transport part limit")
    require(parts, "provider ZIP transport parts missing")
    require(
        sum(item["bytes"] for item in parts) == zip_path.stat().st_size,
        "provider ZIP transport byte total changed",
    )
    return {
        "part_bytes_limit": TRANSPORT_PART_BYTES,
        "part_count": len(parts),
        "parts": parts,
    }


def reassemble_provider_zip(
    transport_dir: Path,
    transport: Any,
    output_zip: Path,
) -> None:
    require(transport_dir.is_dir(), "provider transport directory missing")
    require(not output_zip.exists(), "provider ZIP assembly target already exists")
    require(isinstance(transport, dict), "provider transport receipt missing")
    require(
        set(transport) == {"part_bytes_limit", "part_count", "parts"},
        "provider transport receipt keys changed",
    )
    require(
        transport["part_bytes_limit"] == TRANSPORT_PART_BYTES,
        "provider transport part limit changed",
    )
    part_count = transport["part_count"]
    parts = transport["parts"]
    require(
        isinstance(part_count, int)
        and not isinstance(part_count, bool)
        and 0 < part_count <= MAXIMUM_TRANSPORT_PARTS,
        "provider transport part count invalid",
    )
    require(
        isinstance(parts, list) and len(parts) == part_count,
        "provider transport part inventory changed",
    )
    actual_files: set[str] = set()
    for path in transport_dir.iterdir():
        path_stat = path.lstat()
        require(
            stat.S_ISREG(path_stat.st_mode) and path_stat.st_nlink == 1,
            "provider transport contains unsupported filesystem object",
        )
        actual_files.add(path.name)
    expected_files = {
        f"artifact.zip.part-{index:04d}" for index in range(part_count)
    }
    require(actual_files == expected_files, "provider transport file set changed")
    total_bytes = 0
    with output_zip.open("xb") as output:
        for index, item in enumerate(parts):
            require(isinstance(item, dict), "provider transport part changed")
            require(
                set(item) == {"name", "sha256", "bytes"},
                "provider transport part keys changed",
            )
            expected_name = f"artifact.zip.part-{index:04d}"
            require(item["name"] == expected_name, "provider transport order changed")
            require(
                TRANSPORT_PART_RE.fullmatch(item["name"]) is not None,
                "provider transport part name invalid",
            )
            require(
                isinstance(item["sha256"], str)
                and SHA256_RE.fullmatch(item["sha256"]),
                "provider transport part hash invalid",
            )
            require(
                isinstance(item["bytes"], int)
                and not isinstance(item["bytes"], bool)
                and 0 < item["bytes"] <= TRANSPORT_PART_BYTES,
                "provider transport part size invalid",
            )
            if index < part_count - 1:
                require(
                    item["bytes"] == TRANSPORT_PART_BYTES,
                    "non-final provider transport part size changed",
                )
            path = transport_dir / item["name"]
            require(path.stat().st_size == item["bytes"], "transport part size changed")
            require(sha256_file(path) == item["sha256"], "transport part hash changed")
            total_bytes += item["bytes"]
            require(
                total_bytes <= MAXIMUM_PROVIDER_ARTIFACT_BYTES,
                "assembled provider ZIP exceeds reviewed limit",
            )
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    output.write(chunk)


def validate_provider_metadata_preflight(
    metadata_path: Path,
    *,
    expected_control_commit: str,
    expected_artifact_id: int | None,
) -> dict[str, Any]:
    metadata = strict_json_file(metadata_path)
    require(isinstance(metadata, dict), "provider metadata root changed")
    artifact_id = metadata.get("id")
    require(
        isinstance(artifact_id, int)
        and not isinstance(artifact_id, bool)
        and artifact_id > 0,
        "provider artifact id invalid",
    )
    if expected_artifact_id is not None:
        require(artifact_id == expected_artifact_id, "provider artifact id changed")
    require(metadata.get("name") == ARTIFACT_NAME, "provider artifact name changed")
    require(metadata.get("expired") is False, "provider artifact is expired")
    size = metadata.get("size_in_bytes")
    require(
        isinstance(size, int)
        and not isinstance(size, bool)
        and 0 < size <= MAXIMUM_PROVIDER_ARTIFACT_BYTES,
        "provider artifact size invalid",
    )
    digest = metadata.get("digest")
    require(
        isinstance(digest, str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", digest),
        "provider artifact digest missing",
    )
    api_url = (
        f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{artifact_id}"
    )
    require(metadata.get("url") == api_url, "provider artifact API identity changed")
    require(
        metadata.get("archive_download_url") == f"{api_url}/zip",
        "provider artifact download identity changed",
    )
    created = parse_time(metadata.get("created_at"), "provider artifact created_at")
    expires = parse_time(metadata.get("expires_at"), "provider artifact expires_at")
    require(
        created < expires and (expires - created).total_seconds() <= 172_800,
        "provider artifact retention exceeds reviewed window",
    )
    workflow_run = metadata.get("workflow_run")
    require(isinstance(workflow_run, dict), "provider workflow run missing")
    run_id = workflow_run.get("id")
    require(
        isinstance(run_id, int)
        and not isinstance(run_id, bool)
        and run_id > 0,
        "provider workflow run id invalid",
    )
    require(
        workflow_run.get("head_sha") == expected_control_commit,
        "provider workflow control commit changed",
    )
    return {
        "artifact_id": artifact_id,
        "artifact_name": ARTIFACT_NAME,
        "artifact_digest": digest,
        "artifact_size_bytes": size,
        "run_id": run_id,
        "control_commit": expected_control_commit,
        "created_at": metadata["created_at"],
        "expires_at": metadata["expires_at"],
        "provider_metadata_sha256": sha256_file(metadata_path),
        "provider_zip_sha256": digest.removeprefix("sha256:"),
    }


def validate_provider_preflight_summary(
    provider: Any,
    *,
    expected_control_commit: str,
    expected_artifact_id: int | None,
) -> dict[str, Any]:
    require(isinstance(provider, dict), "provider preflight root changed")
    require(
        set(provider)
        == {
            "artifact_id",
            "artifact_name",
            "artifact_digest",
            "artifact_size_bytes",
            "run_id",
            "control_commit",
            "created_at",
            "expires_at",
            "provider_metadata_sha256",
            "provider_zip_sha256",
        },
        "provider preflight keys changed",
    )
    artifact_id = provider["artifact_id"]
    require(
        isinstance(artifact_id, int)
        and not isinstance(artifact_id, bool)
        and artifact_id > 0,
        "provider preflight artifact id invalid",
    )
    if expected_artifact_id is not None:
        require(
            artifact_id == expected_artifact_id,
            "provider preflight artifact id changed",
        )
    require(
        provider["artifact_name"] == ARTIFACT_NAME,
        "provider preflight artifact name changed",
    )
    size = provider["artifact_size_bytes"]
    require(
        isinstance(size, int)
        and not isinstance(size, bool)
        and 0 < size <= MAXIMUM_PROVIDER_ARTIFACT_BYTES,
        "provider preflight artifact size invalid",
    )
    digest = provider["artifact_digest"]
    require(
        isinstance(digest, str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", digest),
        "provider preflight artifact digest invalid",
    )
    require(
        provider["provider_zip_sha256"] == digest.removeprefix("sha256:"),
        "provider preflight ZIP digest binding changed",
    )
    require(
        isinstance(provider["provider_metadata_sha256"], str)
        and SHA256_RE.fullmatch(provider["provider_metadata_sha256"]) is not None,
        "provider preflight metadata digest invalid",
    )
    require(
        isinstance(provider["run_id"], int)
        and not isinstance(provider["run_id"], bool)
        and provider["run_id"] > 0,
        "provider preflight run id invalid",
    )
    require(
        provider["control_commit"] == expected_control_commit,
        "provider preflight control commit changed",
    )
    created = parse_time(provider["created_at"], "provider preflight created_at")
    expires = parse_time(provider["expires_at"], "provider preflight expires_at")
    require(
        created < expires and (expires - created).total_seconds() <= 172_800,
        "provider preflight retention changed",
    )
    return provider


def validate_downloaded_provider_zip(
    provider: dict[str, Any],
    zip_path: Path,
) -> None:
    require(zip_path.is_file(), "provider artifact ZIP missing")
    require(
        zip_path.stat().st_size == provider["artifact_size_bytes"],
        "provider artifact ZIP size changed",
    )
    require(
        sha256_file(zip_path) == provider["provider_zip_sha256"],
        "provider artifact digest changed",
    )


def validate_provider_metadata(
    metadata_path: Path,
    zip_path: Path,
    *,
    expected_control_commit: str,
    expected_artifact_id: int | None,
) -> dict[str, Any]:
    provider = validate_provider_metadata_preflight(
        metadata_path,
        expected_control_commit=expected_control_commit,
        expected_artifact_id=expected_artifact_id,
    )
    validate_downloaded_provider_zip(provider, zip_path)
    return provider


def receive_provider_zip(
    source,
    output_zip: Path,
    *,
    expected_bytes: int,
    expected_sha256: str,
) -> None:
    require(
        isinstance(expected_bytes, int)
        and not isinstance(expected_bytes, bool)
        and 0 < expected_bytes <= MAXIMUM_PROVIDER_ARTIFACT_BYTES,
        "provider receive size invalid",
    )
    require(
        isinstance(expected_sha256, str)
        and SHA256_RE.fullmatch(expected_sha256) is not None,
        "provider receive digest invalid",
    )
    require(not output_zip.exists(), "provider receive target already exists")
    digest = hashlib.sha256()
    received = 0
    try:
        with output_zip.open("xb") as output:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                require(
                    received + len(chunk) <= expected_bytes,
                    "provider receive exceeds declared size",
                )
                require(
                    received + len(chunk) <= MAXIMUM_PROVIDER_ARTIFACT_BYTES,
                    "provider receive exceeds reviewed limit",
                )
                output.write(chunk)
                digest.update(chunk)
                received += len(chunk)
        require(received == expected_bytes, "provider receive size changed")
        require(
            digest.hexdigest() == expected_sha256,
            "provider receive digest changed",
        )
    except (DownloadError, OSError):
        output_zip.unlink(missing_ok=True)
        raise


def receive_provider_zip_from_preflight(args: argparse.Namespace) -> None:
    provider = validate_provider_preflight_summary(
        strict_json_file(args.preflight),
        expected_control_commit=args.control_commit,
        expected_artifact_id=args.artifact_id,
    )
    receive_provider_zip(
        sys.stdin.buffer,
        args.output,
        expected_bytes=provider["artifact_size_bytes"],
        expected_sha256=provider["provider_zip_sha256"],
    )


def run_bundle_verifier(
    *,
    bundle_verifier: Path,
    expected_bundle_verifier_sha256: str,
    bundle: Path,
    expected_sums_sha256: str | None,
) -> dict[str, Any]:
    require(
        SHA256_RE.fullmatch(expected_bundle_verifier_sha256) is not None,
        "bundle verifier trust root invalid",
    )
    require(
        sha256_file(bundle_verifier) == expected_bundle_verifier_sha256,
        "bundle verifier trust root changed",
    )
    with tempfile.TemporaryDirectory() as temporary:
        temporary_root = Path(temporary)
        command = [
            "python3",
            str(bundle_verifier),
            "verify-final",
            "--bundle",
            str(bundle),
            "--extract-to",
            str(temporary_root / "cache"),
            "--output",
            str(temporary_root / "validation.json"),
        ]
        if expected_sums_sha256 is not None:
            command.extend(["--expected-sums-sha256", expected_sums_sha256])
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        require(result.returncode == 0, "trusted bundle validation failed")
        validation = strict_json_file(temporary_root / "validation.json")
    require(isinstance(validation, dict), "bundle validation output changed")
    return validation


def write_json(path: Path, payload: dict[str, Any]) -> None:
    require(not path.exists(), "provider JSON output already exists")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o600)


def verify_download(args: argparse.Namespace) -> dict[str, Any]:
    require(COMMIT_RE.fullmatch(args.control_commit) is not None, "control commit invalid")
    require(SHA256_RE.fullmatch(args.request_sha256) is not None, "request hash invalid")
    provider = validate_provider_metadata_preflight(
        args.metadata,
        expected_control_commit=args.control_commit,
        expected_artifact_id=args.artifact_id,
    )
    validate_downloaded_provider_zip(provider, args.zip)
    safe_extract_provider_zip(args.zip, args.bundle)
    bundle = run_bundle_verifier(
        bundle_verifier=args.bundle_verifier,
        expected_bundle_verifier_sha256=args.bundle_verifier_sha256,
        bundle=args.bundle,
        expected_sums_sha256=None,
    )
    require(bundle.get("control_commit") == args.control_commit, "bundle control changed")
    require(bundle.get("request_sha256") == args.request_sha256, "bundle request changed")
    require(bundle.get("github_run_id") == str(provider["run_id"]), "bundle run id changed")
    transport = split_provider_zip(args.zip, args.transport_dir)
    return {
        "schema_version": "noteai.admin-dependency-cache-provider-receipt.v1",
        "task": "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001",
        "repository": REPOSITORY,
        "release_commit": RELEASE_COMMIT,
        "authenticated_provider_api": True,
        "artifact": provider,
        "transport": transport,
        "bundle": {
            "manifest_sha256": bundle["manifest_sha256"],
            "final_sums_sha256": bundle["final_sums_sha256"],
            "control_commit": bundle["control_commit"],
            "request_sha256": bundle["request_sha256"],
        },
    }


def verify_transfer(args: argparse.Namespace) -> dict[str, Any]:
    require(
        SHA256_RE.fullmatch(args.expected_receipt_sha256) is not None,
        "receipt trust root invalid",
    )
    require(
        sha256_file(args.receipt) == args.expected_receipt_sha256,
        "provider receipt trust root changed",
    )
    receipt = strict_json_file(args.receipt)
    require(
        isinstance(receipt, dict)
        and set(receipt)
        == {
            "schema_version",
            "task",
            "repository",
            "release_commit",
            "authenticated_provider_api",
            "artifact",
            "transport",
            "bundle",
        }
        and receipt.get("schema_version")
        == "noteai.admin-dependency-cache-provider-receipt.v1"
        and receipt.get("task") == "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001"
        and receipt.get("repository") == REPOSITORY
        and receipt.get("release_commit") == RELEASE_COMMIT
        and receipt.get("authenticated_provider_api") is True,
        "provider receipt contract changed",
    )
    artifact = receipt.get("artifact")
    transport = receipt.get("transport")
    bundle_receipt = receipt.get("bundle")
    require(isinstance(artifact, dict), "provider receipt artifact missing")
    require(
        set(artifact)
        == {
            "artifact_id",
            "artifact_name",
            "artifact_digest",
            "artifact_size_bytes",
            "run_id",
            "control_commit",
            "created_at",
            "expires_at",
            "provider_metadata_sha256",
            "provider_zip_sha256",
        },
        "provider receipt artifact keys changed",
    )
    require(isinstance(bundle_receipt, dict), "provider receipt bundle missing")
    require(
        set(bundle_receipt)
        == {
            "manifest_sha256",
            "final_sums_sha256",
            "control_commit",
            "request_sha256",
        },
        "provider receipt bundle keys changed",
    )
    require(
        artifact.get("artifact_name") == ARTIFACT_NAME,
        "provider receipt artifact name changed",
    )
    require(
        isinstance(artifact.get("artifact_id"), int)
        and not isinstance(artifact.get("artifact_id"), bool)
        and artifact["artifact_id"] > 0,
        "provider receipt artifact id invalid",
    )
    require(
        isinstance(artifact.get("run_id"), int)
        and not isinstance(artifact.get("run_id"), bool)
        and artifact["run_id"] > 0,
        "provider receipt run id invalid",
    )
    require(
        isinstance(artifact.get("artifact_digest"), str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", artifact["artifact_digest"]),
        "provider receipt artifact digest invalid",
    )
    require(
        artifact.get("provider_zip_sha256")
        == artifact["artifact_digest"].removeprefix("sha256:"),
        "provider receipt ZIP hash binding changed",
    )
    require(
        isinstance(artifact.get("provider_metadata_sha256"), str)
        and SHA256_RE.fullmatch(artifact["provider_metadata_sha256"]),
        "provider receipt metadata hash invalid",
    )
    require(
        isinstance(artifact.get("artifact_size_bytes"), int)
        and not isinstance(artifact.get("artifact_size_bytes"), bool)
        and 0
        < artifact["artifact_size_bytes"]
        <= MAXIMUM_PROVIDER_ARTIFACT_BYTES,
        "provider receipt artifact size invalid",
    )
    created = parse_time(artifact.get("created_at"), "receipt artifact created_at")
    expires = parse_time(artifact.get("expires_at"), "receipt artifact expires_at")
    require(
        created < expires and (expires - created).total_seconds() <= 172_800,
        "provider receipt retention changed",
    )
    require(
        artifact.get("control_commit") == bundle_receipt.get("control_commit"),
        "provider receipt control binding changed",
    )
    with tempfile.TemporaryDirectory() as temporary:
        assembled_zip = Path(temporary) / "artifact.zip"
        reassemble_provider_zip(args.transport_dir, transport, assembled_zip)
        require(
            artifact.get("artifact_digest")
            == f"sha256:{sha256_file(assembled_zip)}",
            "transferred provider ZIP digest changed",
        )
        require(
            artifact.get("artifact_size_bytes") == assembled_zip.stat().st_size,
            "transferred provider ZIP size changed",
        )
        safe_extract_provider_zip(assembled_zip, args.bundle)
        validation = run_bundle_verifier(
            bundle_verifier=args.bundle_verifier,
            expected_bundle_verifier_sha256=args.bundle_verifier_sha256,
            bundle=args.bundle,
            expected_sums_sha256=bundle_receipt.get("final_sums_sha256"),
        )
    for field in ("manifest_sha256", "final_sums_sha256", "control_commit", "request_sha256"):
        require(
            validation.get(field) == bundle_receipt.get(field),
            f"transferred bundle receipt binding changed: {field}",
        )
    require(
        validation.get("github_run_id") == str(artifact["run_id"]),
        "transferred bundle run binding changed",
    )
    return validation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight = subparsers.add_parser("preflight-metadata")
    preflight.add_argument("--metadata", type=Path, required=True)
    preflight.add_argument("--control-commit", required=True)
    preflight.add_argument("--artifact-id", type=int)
    preflight.add_argument("--output", type=Path, required=True)

    receive = subparsers.add_parser("receive-zip")
    receive.add_argument("--preflight", type=Path, required=True)
    receive.add_argument("--control-commit", required=True)
    receive.add_argument("--artifact-id", type=int)
    receive.add_argument("--output", type=Path, required=True)

    download = subparsers.add_parser("verify-download")
    download.add_argument("--metadata", type=Path, required=True)
    download.add_argument("--zip", type=Path, required=True)
    download.add_argument("--transport-dir", type=Path, required=True)
    download.add_argument("--bundle", type=Path, required=True)
    download.add_argument("--bundle-verifier", type=Path, required=True)
    download.add_argument("--bundle-verifier-sha256", required=True)
    download.add_argument("--control-commit", required=True)
    download.add_argument("--request-sha256", required=True)
    download.add_argument("--artifact-id", type=int)
    download.add_argument("--receipt", type=Path, required=True)

    transfer = subparsers.add_parser("verify-transfer")
    transfer.add_argument("--receipt", type=Path, required=True)
    transfer.add_argument("--expected-receipt-sha256", required=True)
    transfer.add_argument("--transport-dir", type=Path, required=True)
    transfer.add_argument("--bundle", type=Path, required=True)
    transfer.add_argument("--bundle-verifier", type=Path, required=True)
    transfer.add_argument("--bundle-verifier-sha256", required=True)
    transfer.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "preflight-metadata":
            require(
                COMMIT_RE.fullmatch(args.control_commit) is not None,
                "control commit invalid",
            )
            write_json(
                args.output,
                validate_provider_metadata_preflight(
                    args.metadata,
                    expected_control_commit=args.control_commit,
                    expected_artifact_id=args.artifact_id,
                ),
            )
        elif args.command == "receive-zip":
            require(
                COMMIT_RE.fullmatch(args.control_commit) is not None,
                "control commit invalid",
            )
            receive_provider_zip_from_preflight(args)
        elif args.command == "verify-download":
            write_json(args.receipt, verify_download(args))
        else:
            write_json(args.output, verify_transfer(args))
    except (DownloadError, OSError) as exc:
        print(f"FAIL: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
