#!/usr/bin/env python3
"""Run frozen Item 26 renderers in one bounded local Linux container.

The caller owns the Colima lifecycle.  This controller never starts Colima,
never mounts the repository, never prints request/result bodies, and never
deletes the retained request, bundle, attempt receipt, result or metadata.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
from types import MappingProxyType
from typing import Callable, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
IMAGE = (
    "python@sha256:"
    "db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93"
)
PLATFORM = "linux/amd64"
DOCKER = "/opt/homebrew/bin/docker"
DOCKER_HOST = "unix:///Users/openclaw/.colima/default/docker.sock"
MAX_REQUEST_BYTES = 131072
MAX_RESULT_BYTES = 131072
MAX_STDERR_BYTES = 8192
TIMEOUT_SECONDS = 240
CONTAINER_USER = "65532:65532"
CONTAINER_NAME_PREFIX = "noteai-item26-render-v1-"
TOKEN = re.compile(r"^[0-9a-f]{32}$")
INSTANCE_ID = re.compile(r"^i-[a-z0-9]+$")
MODES = frozenset({
    "preflight", "keygen", "rewrap", "broker", "post_broker", "parent_probe",
})

# Every source admitted to a mode is byte- and SHA-256-bound before bundling.
_SOURCE_ROWS = (
    (
        "tools/render_item26_restored_ops_v1.py",
        38654,
        "260cc05f06bf2a2997903b0a593fa53a6f98d3d7a443252c3620b0fca33b33f2",
    ),
    (
        "tools/render_item26_restored_preflight_v1.py",
        13394,
        "2ab1bef07fb37f6af723c42d676e01af5e2a8602a4a9a2f5713d2f87e68baea7",
    ),
    (
        "tools/render_item26_restored_v1_transport.py",
        30274,
        "df6e84ccd8a0667527ea3f135a5b46cb5975cd50869a10d67698b148148706dc",
    ),
    (
        "tools/render_item26_v3_transport.py",
        41246,
        "6db210c6e04e98d022a25c9b4212ea98ed532f9287fb6be2ff69a54368ab4e92",
    ),
    (
        "tools/render_item26_restored_parent_probe_v1.py",
        16034,
        "80d2f2a877b085431575298e4064694d94f5364ae9cde97662d6d836904171fa",
    ),
    (
        ".codex/item26-restored-builder-keygen-v1.template.sh",
        10854,
        "969acad9a5d4f9f275f09e0b5303131a38cf7dc309149b0417388b1a611897cb",
    ),
    (
        ".codex/item26-restored-package-broker-v1.template.sh",
        26007,
        "4204e5c240138d77592e13b67044c3635139ec6d5307a19f3b538aed1c7eaaad",
    ),
    (
        ".codex/item26-password-rewrap.template.sh",
        34231,
        "6a8b36590f5d3f7972be25544dc2c90d68fae493d21d9fda209578780ff9bf61",
    ),
    (
        ".codex/item26-restored-builder-stage-v1.template.sh",
        10562,
        "babdbe7d6daad55db04d1247ec26741cc77925c1c8ba8ca20398bac9de0069e5",
    ),
    (
        ".codex/item26-restored-capture-v1.template.sh",
        46796,
        "297c7c2f3c94df49baa1103970233cf16c1bd560f17abf3fb4c7f13bca7b094a",
    ),
    (
        ".codex/item26-restored-capture-executor-v1.template.sh",
        13365,
        "a8bc036e11d6e7a5d3a9fafdc307f9ac5470b026db93bca9ca2c686dfb1bc9e6",
    ),
    (
        ".codex/item26-restored-api-c-preflight-v1.template.sh",
        22271,
        "31fddca026ea7adcc592781eec1aaed6019e45f3d204512ff9d015b9ded1033e",
    ),
    (
        ".codex/item26-restored-builder-preflight-v1.template.sh",
        16286,
        "690b01e8abb2822d7141130761177d321357771e075b501f08b3ee4025967137",
    ),
    (
        ".codex/item26-restored-parent-probe-api-c-v1.template.sh",
        8107,
        "38f455663d300ea16170c9c845def60d0686c6dd4186e2fd117065d070fae4d4",
    ),
)
SOURCE_IDENTITIES = MappingProxyType(
    {
        path: MappingProxyType({"bytes": size, "sha256": digest})
        for path, size, digest in _SOURCE_ROWS
    }
)
MODE_ENTRYPOINTS = MappingProxyType(
    {
        "preflight": "tools/render_item26_restored_preflight_v1.py",
        "keygen": "tools/render_item26_restored_ops_v1.py",
        "rewrap": "tools/render_item26_restored_ops_v1.py",
        "broker": "tools/render_item26_restored_ops_v1.py",
        "post_broker": "tools/render_item26_restored_ops_v1.py",
        "parent_probe": "tools/render_item26_restored_parent_probe_v1.py",
    }
)
_COMMON_OPS = frozenset({
    "tools/render_item26_restored_ops_v1.py",
    "tools/render_item26_restored_v1_transport.py",
    "tools/render_item26_v3_transport.py",
})
MODE_SOURCE_FILES = MappingProxyType({
    "preflight": frozenset({
        "tools/render_item26_restored_preflight_v1.py",
        "tools/render_item26_v3_transport.py",
        ".codex/item26-restored-api-c-preflight-v1.template.sh",
        ".codex/item26-restored-builder-preflight-v1.template.sh",
    }),
    "keygen": _COMMON_OPS | {".codex/item26-restored-builder-keygen-v1.template.sh"},
    "rewrap": _COMMON_OPS | {".codex/item26-password-rewrap.template.sh"},
    "broker": _COMMON_OPS | {".codex/item26-restored-package-broker-v1.template.sh"},
    "post_broker": _COMMON_OPS | {
        ".codex/item26-restored-builder-stage-v1.template.sh",
        ".codex/item26-restored-capture-v1.template.sh",
        ".codex/item26-restored-capture-executor-v1.template.sh",
    },
    "parent_probe": frozenset({
        "tools/render_item26_restored_parent_probe_v1.py",
        "tools/render_item26_v3_transport.py",
        ".codex/item26-restored-parent-probe-api-c-v1.template.sh",
    }),
})
RENDER_FAILURE_CODES = frozenset({
    "api_c_binding", "api_c_bindings", "api_c_residue", "api_c_syntax",
    "api_c_template", "broker_binding", "broker_bindings", "broker_create",
    "broker_create_mismatch", "broker_readback", "broker_residue", "broker_syntax",
    "broker_template", "builder_binding", "builder_bindings", "builder_ram_role",
    "builder_residue", "builder_syntax", "builder_template", "capture_artifact",
    "capture_envelope", "capture_render", "capture_summary", "command_limit",
    "contract", "duplicate", "gnu_gzip", "gnu_gzip_required", "gzip", "identity",
    "internal", "keygen_binding", "keygen_bindings", "keygen_residue",
    "keygen_result", "keygen_syntax", "keygen_template", "linux_required", "loader",
    "loader_contract", "loader_recipient", "loader_validator", "public_key",
    "recipient_reuse", "request", "request_contract", "restored_host", "rewrap",
    "rewrap_binding", "rewrap_bindings", "rewrap_residue", "rewrap_syntax",
    "rewrap_template", "sendfile_limit", "stage_binding", "stage_bindings",
    "stage_residue", "stage_syntax", "stage_template", "template_name", "validator",
})
PARENT_PROBE_RENDER_FAILURE_CODES = frozenset({
    "api_c_instance_id", "client_token", "command_base64", "command_binding",
    "command_contract", "command_limit", "command_roundtrip", "command_source",
    "command_source_syntax", "duplicate_json_key", "input_canonical",
    "input_contract", "input_json", "input_shape", "internal", "json", "gzip",
    "gnu_gzip_required", "linux_required", "loader", "loader_syntax", "plan_nonce",
    "request_binding", "request_contract", "request_types", "template",
    "template_syntax",
})


class BridgeError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _private_child_umask() -> None:
    os.umask(0o077)


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise BridgeError("duplicate_json_key")
        result[key] = value
    return result


def _parse_canonical(body: bytes, label: str, maximum: int) -> dict[str, object]:
    if (
        type(body) is not bytes
        or not 1 <= len(body) <= maximum
        or not body.endswith(b"\n")
        or b"\r" in body
        or b"\x00" in body
    ):
        raise BridgeError(label + "_shape")
    try:
        value = json.loads(body.decode("ascii"), object_pairs_hook=_no_duplicates)
    except BridgeError:
        raise
    except BaseException as exc:
        raise BridgeError(label + "_json") from exc
    if type(value) is not dict or _canonical(value) != body:
        raise BridgeError(label + "_canonical")
    return value


def _directory_metadata(path: Path, mode: int, *, owner: int | None = None) -> os.stat_result:
    try:
        before = path.lstat()
        descriptor = os.open(
            str(path),
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            opened = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after = path.lstat()
    except OSError as exc:
        raise BridgeError("directory_metadata") from exc
    identity = lambda row: (
        row.st_dev,
        row.st_ino,
        row.st_mode,
        row.st_uid,
        row.st_gid,
        row.st_nlink,
    )
    required_owner = os.getuid() if owner is None else owner
    if (
        not stat.S_ISDIR(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or identity(before) != identity(opened)
        or identity(opened) != identity(after)
        or stat.S_IMODE(before.st_mode) != mode
        or before.st_uid != required_owner
        or before.st_nlink < 2
    ):
        raise BridgeError("directory_metadata")
    return before


def _read_source(path: Path, expected: MappingProxyType) -> bytes:
    expected_size = expected["bytes"]
    expected_sha = expected["sha256"]
    if type(expected_size) is not int or type(expected_sha) is not str:
        raise BridgeError("source_identity_unfrozen")
    try:
        before = path.lstat()
        descriptor = os.open(
            str(path),
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            opened = os.fstat(descriptor)
            body = b""
            while len(body) <= expected_size:
                chunk = os.read(descriptor, min(65536, expected_size + 1 - len(body)))
                if not chunk:
                    break
                body += chunk
            closed = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after = path.lstat()
    except OSError as exc:
        raise BridgeError("source_read") from exc
    identity = lambda row: (
        row.st_dev,
        row.st_ino,
        row.st_mode,
        row.st_uid,
        row.st_gid,
        row.st_nlink,
        row.st_size,
        row.st_mtime_ns,
    )
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or before.st_nlink != 1
        or before.st_uid != os.getuid()
        or stat.S_IMODE(before.st_mode) not in (0o600, 0o644)
        or identity(before) != identity(opened)
        or identity(opened) != identity(closed)
        or identity(closed) != identity(after)
        or len(body) != expected_size
        or _sha256(body) != expected_sha
    ):
        raise BridgeError("source_identity")
    return body


def _source_snapshot(mode: str) -> dict[str, bytes]:
    try:
        selected = MODE_SOURCE_FILES[mode]
    except KeyError as exc:
        raise BridgeError("mode_sources") from exc
    before = REPOSITORY_ROOT.lstat()
    bodies = {
        relative: _read_source(REPOSITORY_ROOT / relative, identity)
        for relative, identity in SOURCE_IDENTITIES.items()
        if relative in selected
    }
    # A second independently opened/hash-checked pass prevents a bundle made
    # from a mixed multi-file repository snapshot.
    for relative in selected:
        expected = SOURCE_IDENTITIES[relative]
        if _read_source(REPOSITORY_ROOT / relative, expected) != bodies[relative]:
            raise BridgeError("source_snapshot_race")
    after = REPOSITORY_ROOT.lstat()
    identity = lambda row: (
        row.st_dev, row.st_ino, row.st_mode, row.st_uid, row.st_gid, row.st_mtime_ns,
    )
    if identity(before) != identity(after):
        raise BridgeError("source_snapshot_race")
    return bodies


def _read_regular(path: Path, maximum: int, label: str, *, allow_empty: bool = True) -> bytes:
    try:
        before = path.lstat()
        descriptor = os.open(
            str(path),
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            opened = os.fstat(descriptor)
            body = b""
            while len(body) <= maximum:
                chunk = os.read(descriptor, min(65536, maximum + 1 - len(body)))
                if not chunk:
                    break
                body += chunk
            closed = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after = path.lstat()
    except OSError as exc:
        raise BridgeError(label + "_read") from exc
    identity = lambda row: (
        row.st_dev,
        row.st_ino,
        row.st_mode,
        row.st_uid,
        row.st_gid,
        row.st_nlink,
        row.st_size,
        row.st_mtime_ns,
    )
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or before.st_nlink != 1
        or before.st_uid != os.getuid()
        or stat.S_IMODE(before.st_mode) != 0o600
        or identity(before) != identity(opened)
        or identity(opened) != identity(closed)
        or identity(closed) != identity(after)
        or not (0 if allow_empty else 1) <= len(body) <= maximum
    ):
        raise BridgeError(label + "_metadata")
    return body


def _create_exclusive(path: Path, body: bytes, mode: int = 0o600) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(str(path), flags, 0o600)
        try:
            os.fchmod(descriptor, mode)
            offset = 0
            while offset < len(body):
                written = os.write(descriptor, body[offset:])
                if not 1 <= written <= len(body) - offset:
                    raise BridgeError("exclusive_write")
                offset += written
            os.fsync(descriptor)
            metadata = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except BridgeError:
        raise
    except OSError as exc:
        raise BridgeError("exclusive_write") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != mode
        or metadata.st_size != len(body)
    ):
        raise BridgeError("exclusive_write")


def _open_exclusive(path: Path) -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(str(path), flags, 0o600)
        metadata = os.fstat(descriptor)
    except OSError as exc:
        raise BridgeError("exclusive_open") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size != 0
    ):
        os.close(descriptor)
        raise BridgeError("exclusive_open")
    return descriptor


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        str(path),
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _validate_request(path: Path, mode: str) -> bytes:
    body = _read_regular(path, MAX_REQUEST_BYTES, "request", allow_empty=False)
    value = _parse_canonical(body, "request", MAX_REQUEST_BYTES)
    if value.get("mode") != mode:
        raise BridgeError("request_mode")
    if mode == "parent_probe" and (
        set(value) != {"api_c_instance_id", "mode", "plan_nonce"}
        or type(value.get("api_c_instance_id")) is not str
        or INSTANCE_ID.fullmatch(value["api_c_instance_id"]) is None
        or type(value.get("plan_nonce")) is not str
        or TOKEN.fullmatch(value["plan_nonce"]) is None
    ):
        raise BridgeError("parent_probe_request_contract")
    return body


def _validate_result(body: bytes) -> None:
    _parse_canonical(body, "result", MAX_RESULT_BYTES)


def _known_renderer_failure(mode: str, returncode: object, stdout: bytes, stderr: bytes) -> bool:
    if type(returncode) is not int or returncode != 2 or stdout:
        return False
    if mode == "parent_probe":
        prefix = b"ITEM26_RESTORED_PARENT_PROBE_RENDER_FAILED:"
        allowed_codes = PARENT_PROBE_RENDER_FAILURE_CODES
    elif mode == "preflight":
        prefix = b"ITEM26_RESTORED_PREFLIGHT_RENDER_FAILED:"
        allowed_codes = RENDER_FAILURE_CODES
    else:
        prefix = b"ITEM26_RESTORED_OPS_RENDER_FAILED:"
        allowed_codes = RENDER_FAILURE_CODES
    if (
        not stderr.startswith(prefix)
        or not stderr.endswith(b"\n")
        or stderr.count(b"\n") != 1
        or b"\r" in stderr
        or b"\x00" in stderr
    ):
        return False
    try:
        code = stderr[len(prefix):-1].decode("ascii")
    except UnicodeError:
        return False
    return code in allowed_codes


def _source_manifest(source_bodies: dict[str, bytes]) -> bytes:
    return _canonical({
        "files": {
            relative: {"bytes": len(body), "sha256": _sha256(body)}
            for relative, body in source_bodies.items()
        },
        "schema_version": 1,
    })


def _build_bundle(
    private_root: Path,
    mode: str,
    source_bodies: dict[str, bytes],
    manifest_body: bytes,
) -> Path:
    bundle = private_root / (mode + ".source-bundle")
    try:
        bundle.mkdir(mode=0o755)
        os.chmod(bundle, 0o755)
    except FileExistsError:
        raise BridgeError("source_bundle_exists")
    for relative, body in source_bodies.items():
        target = bundle / relative
        target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        os.chmod(target.parent, 0o755)
        _create_exclusive(target, body, 0o444)
    _create_exclusive(bundle / "manifest.json", manifest_body, 0o444)
    for directory in sorted(
        {bundle, *(path.parent for path in bundle.rglob("*") if path.parent != bundle)},
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        _fsync_directory(directory)
    _fsync_directory(bundle)
    _fsync_directory(private_root)
    return bundle


def _verify_bundle(bundle: Path, manifest_body: bytes, mode: str) -> None:
    _directory_metadata(bundle, 0o755)
    manifest = _parse_canonical(manifest_body, "bundle_manifest", 16384)
    expected_files = manifest.get("files")
    if (
        set(manifest) != {"files", "schema_version"}
        or manifest.get("schema_version") != 1
        or type(expected_files) is not dict
        or set(expected_files) != set(MODE_SOURCE_FILES[mode])
    ):
        raise BridgeError("bundle_manifest")
    expected_paths = set(MODE_SOURCE_FILES[mode]) | {"manifest.json"}
    expected_directories = {str(Path(path).parent) for path in expected_paths}
    expected_directories.discard(".")
    observed = set()
    observed_directories = set()
    for root, directories, files in os.walk(bundle, topdown=True, followlinks=False):
        root_path = Path(root)
        for name in directories:
            path = root_path / name
            relative = str(path.relative_to(bundle))
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise BridgeError("bundle_inventory")
            _directory_metadata(path, 0o755)
            observed_directories.add(relative)
        for name in files:
            path = root_path / name
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise BridgeError("bundle_inventory")
            observed.add(str(path.relative_to(bundle)))
    if observed != expected_paths or observed_directories != expected_directories:
        raise BridgeError("bundle_inventory")
    for relative, row in expected_files.items():
        if (
            type(row) is not dict
            or set(row) != {"bytes", "sha256"}
            or type(row["bytes"]) is not int
            or not 1 <= row["bytes"] <= 262144
            or type(row["sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is None
        ):
            raise BridgeError("bundle_manifest")
        body = _read_mode_file(bundle / relative, row["bytes"], "bundle_source", 0o444)
        if row != {"bytes": len(body), "sha256": _sha256(body)}:
            raise BridgeError("bundle_source")
    on_disk = _read_mode_file(bundle / "manifest.json", 16384, "bundle_manifest", 0o444)
    if on_disk != manifest_body:
        raise BridgeError("bundle_manifest")


def _read_mode_file(path: Path, maximum: int, label: str, mode: int) -> bytes:
    try:
        before = path.lstat()
        descriptor = os.open(
            str(path),
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            opened = os.fstat(descriptor)
            body = b""
            while len(body) <= maximum:
                chunk = os.read(descriptor, min(65536, maximum + 1 - len(body)))
                if not chunk:
                    break
                body += chunk
            closed = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after = path.lstat()
    except OSError as exc:
        raise BridgeError(label) from exc
    stable = lambda row: (
        row.st_dev, row.st_ino, row.st_mode, row.st_uid, row.st_gid,
        row.st_nlink, row.st_size, row.st_mtime_ns,
    )
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or before.st_nlink != 1
        or before.st_uid != os.getuid()
        or stat.S_IMODE(before.st_mode) != mode
        or stable(before) != stable(opened)
        or stable(opened) != stable(closed)
        or stable(closed) != stable(after)
        or not 0 <= len(body) <= maximum
    ):
        raise BridgeError(label)
    return body


def _mode_paths(private_root: Path, mode: str, token: str) -> dict[str, Path]:
    return {
        "request": private_root / (token + ".request.json"),
        "attempt": private_root / (mode + ".attempt.json"),
        "result": private_root / (token + ".result.json"),
        "stderr": private_root / (token + ".stderr.bin"),
        "stdout": private_root / (token + ".stdout.bin"),
        "meta": private_root / (token + ".meta.json"),
        "cid": private_root / (token + ".cid"),
    }


def _docker_command(*, mode: str, token: str, bundle_path: Path, cidfile_path: Path) -> list[str]:
    if mode not in MODES or TOKEN.fullmatch(token) is None:
        raise BridgeError("arguments")
    return [
        DOCKER,
        "run",
        "--rm",
        "--interactive",
        "--pull",
        "never",
        "--platform",
        PLATFORM,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--memory",
        "384m",
        "--memory-swap",
        "384m",
        "--cpus",
        "1.0",
        "--pids-limit",
        "128",
        "--ipc",
        "private",
        "--user",
        CONTAINER_USER,
        "--workdir",
        "/work",
        "--env",
        "HOME=/nonexistent",
        "--env",
        "PYTHONHASHSEED=0",
        "--env",
        "LC_ALL=C",
        "--name",
        CONTAINER_NAME_PREFIX + token,
        "--label",
        "com.noteai.item26-render-token=" + token,
        "--cidfile",
        str(cidfile_path),
        "--mount",
        "type=bind,src={},dst=/work,readonly".format(bundle_path),
        "--entrypoint",
        "/usr/local/bin/python3",
        IMAGE,
        "-I",
        "-B",
        "/work/" + MODE_ENTRYPOINTS[mode],
    ]


def _inventory(
    run: Callable[..., subprocess.CompletedProcess[bytes]], token: str
) -> tuple[str, dict[str, tuple[str, str, str]]]:
    try:
        result = run(
            [
                DOCKER, "ps", "--all", "--no-trunc", "--format",
                '{{.ID}}|{{.Names}}|{{.Image}}|{{.Label "com.noteai.item26-render-token"}}',
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"DOCKER_HOST": DOCKER_HOST, "PATH": "/opt/homebrew/bin:/usr/bin:/bin", "LC_ALL": "C"},
            timeout=15,
            check=False,
            preexec_fn=_private_child_umask,
        )
    except BaseException:
        return "QUERY_UNKNOWN", {}
    if (
        result.returncode != 0
        or result.stderr
        or not isinstance(result.stdout, bytes)
        or len(result.stdout) > 1048576
    ):
        return "QUERY_UNKNOWN", {}
    rows: dict[str, tuple[str, str, str]] = {}
    try:
        text = result.stdout.decode("ascii")
        if text and not text.endswith("\n"):
            raise ValueError
        for line in text.splitlines():
            fields = line.split("|")
            if len(fields) != 4 or re.fullmatch(r"[0-9a-f]{64}", fields[0]) is None:
                raise ValueError
            label_value = fields[3]
            if label_value and TOKEN.fullmatch(label_value) is None:
                raise ValueError
            if fields[0] in rows:
                raise ValueError
            rows[fields[0]] = (fields[1], fields[2], label_value)
        if len(rows) > 4096:
            raise ValueError
    except (UnicodeError, ValueError):
        return "QUERY_UNKNOWN", {}
    return "OK", rows


def _safe_cleanup(
    *,
    run: Callable[..., subprocess.CompletedProcess[bytes]],
    token: str,
    cidfile_path: Path,
) -> str:
    """Prove absence or remove only the exact token/CID/name/image container."""
    inventory_state, rows = _inventory(run, token)
    if inventory_state != "OK":
        return inventory_state
    expected_name = CONTAINER_NAME_PREFIX + token
    matches = {
        cid for cid, (name, _image, label_value) in rows.items()
        if name == expected_name or label_value == token
    }
    if not matches:
        return "ABSENT_PROVEN"
    if len(matches) != 1:
        return "MULTIPLE_OR_INVALID"
    try:
        cid = _read_regular(cidfile_path, 128, "cid").decode("ascii").strip()
    except BaseException:
        return "CID_UNAVAILABLE"
    if re.fullmatch(r"[0-9a-f]{64}", cid) is None or matches != {cid}:
        return "CID_INVALID"
    name, image, label_value = rows[cid]
    if name != expected_name or image != IMAGE or label_value != token:
        return "IDENTITY_UNPROVEN"
    try:
        inspected = run(
            [
                DOCKER, "inspect", "--format",
                '{{.Id}}|{{.Name}}|{{.Config.Image}}|{{index .Config.Labels "com.noteai.item26-render-token"}}',
                cid,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"DOCKER_HOST": DOCKER_HOST, "PATH": "/opt/homebrew/bin:/usr/bin:/bin", "LC_ALL": "C"},
            timeout=15,
            check=False,
            preexec_fn=_private_child_umask,
        )
    except BaseException:
        return "IDENTITY_UNPROVEN"
    expected = "{}|/{}|{}|{}\n".format(
        cid, CONTAINER_NAME_PREFIX + token, IMAGE, token,
    ).encode("ascii")
    if inspected.returncode != 0 or inspected.stdout != expected or inspected.stderr:
        return "IDENTITY_UNPROVEN"
    try:
        result = run(
            [DOCKER, "rm", "--force", cid],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"DOCKER_HOST": DOCKER_HOST, "PATH": "/opt/homebrew/bin:/usr/bin:/bin", "LC_ALL": "C"},
            timeout=20,
            check=False,
            preexec_fn=_private_child_umask,
        )
    except BaseException:
        return "REMOVE_UNKNOWN"
    if result.returncode != 0:
        return "REMOVE_UNKNOWN"
    try:
        post_state, post_rows = _inventory(run, token)
    except BaseException:
        return "POST_REMOVE_UNKNOWN"
    post_matches = {
        row_cid for row_cid, (name, _image, label_value) in post_rows.items()
        if row_cid == cid or name == expected_name or label_value == token
    }
    return (
        "EXACT_REMOVED"
        if post_state == "OK" and not post_matches
        else "POST_REMOVE_UNKNOWN"
    )


def run_bridge(
    *,
    mode: str,
    private_root: Path,
    token: str,
    run: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> dict[str, object]:
    if mode not in MODES or TOKEN.fullmatch(token) is None:
        raise BridgeError("arguments")
    root_metadata = _directory_metadata(private_root, 0o700)
    paths = _mode_paths(private_root, mode, token)
    if paths["attempt"].exists() or paths["attempt"].is_symlink():
        raise BridgeError("mode_already_attempted")
    for label in ("result", "stderr", "stdout", "meta", "cid"):
        if paths[label].exists() or paths[label].is_symlink():
            raise BridgeError("output_exists")
    request = _validate_request(paths["request"], mode)
    source_bodies = _source_snapshot(mode)
    manifest = _source_manifest(source_bodies)
    attempt_time_ns = time.time_ns()
    attempt = {
        "attempt_time_ns": attempt_time_ns,
        "automatic_retry_allowed": False,
        "container_image": IMAGE,
        "container_platform": PLATFORM,
        "mode": mode,
        "request_bytes": len(request),
        "request_sha256": _sha256(request),
        "same_invocation_replay_allowed": False,
        "schema_version": 1,
        "source_bundle_manifest_sha256": _sha256(manifest),
        "token": token,
    }
    _create_exclusive(paths["attempt"], _canonical(attempt))
    _fsync_directory(private_root)
    bundle = _build_bundle(private_root, mode, source_bodies, manifest)
    _verify_bundle(bundle, manifest, mode)
    command = _docker_command(mode=mode, token=token, bundle_path=bundle, cidfile_path=paths["cid"])
    started_ns = time.time_ns()
    returncode: int | None = None
    stdout = b""
    stderr = b""
    cleanup_state = "NOT_CHECKED"
    outcome = "UNKNOWN"
    terminal_error = None
    try:
        completed = run(
            command,
            input=request,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"DOCKER_HOST": DOCKER_HOST, "PATH": "/opt/homebrew/bin:/usr/bin:/bin", "LC_ALL": "C"},
            timeout=TIMEOUT_SECONDS,
            check=False,
            preexec_fn=_private_child_umask,
        )
        returncode = completed.returncode
        stdout, stderr = completed.stdout, completed.stderr
        if not isinstance(stdout, bytes) or not isinstance(stderr, bytes):
            stdout, stderr = b"", b""
            terminal_error = "docker_stream_type"
        if len(stdout) > MAX_RESULT_BYTES or len(stderr) > MAX_STDERR_BYTES:
            stdout = stdout[:MAX_RESULT_BYTES]
            stderr = stderr[:MAX_STDERR_BYTES]
            terminal_error = "docker_stream_bound"
        if type(returncode) is not int:
            terminal_error = "docker_returncode"
        if returncode == 0 and not stderr and terminal_error is None:
            try:
                _validate_result(stdout)
            except BridgeError as exc:
                terminal_error = exc.code
            if terminal_error is None:
                outcome = "PASS"
        elif terminal_error is None and _known_renderer_failure(mode, returncode, stdout, stderr):
            outcome = "FAIL"
        elif terminal_error is None:
            terminal_error = "docker_returncode" if returncode != 2 else "docker_stream_contract"
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout if isinstance(exc.stdout, bytes) else b"")[:MAX_RESULT_BYTES]
        stderr = (exc.stderr if isinstance(exc.stderr, bytes) else b"")[:MAX_STDERR_BYTES]
        terminal_error = "timeout"
        outcome = "UNKNOWN"
    except BaseException:
        stdout, stderr = b"", b""
        terminal_error = "docker_invocation_unknown"
        outcome = "UNKNOWN"
    cleanup_state = _safe_cleanup(run=run, token=token, cidfile_path=paths["cid"])
    if outcome in {"PASS", "FAIL"} and cleanup_state not in {"ABSENT_PROVEN", "EXACT_REMOVED"}:
        outcome = "UNKNOWN"
        terminal_error = terminal_error or "residue_unknown"
    finished_ns = time.time_ns()
    current = _directory_metadata(private_root, 0o700)
    if (root_metadata.st_dev, root_metadata.st_ino) != (current.st_dev, current.st_ino):
        raise BridgeError("private_root_race")
    try:
        _verify_bundle(bundle, manifest, mode)
    except BridgeError:
        outcome = "UNKNOWN"
        terminal_error = terminal_error or "bundle_changed"
    retained_stdout = stdout if outcome != "PASS" else b""
    if retained_stdout:
        _create_exclusive(paths["stdout"], retained_stdout)
    if outcome == "PASS":
        _create_exclusive(paths["result"], stdout)
    _create_exclusive(paths["stderr"], stderr)
    meta = {
        "attempt_state": "EXACT_RETAINED",
        "automatic_retry_allowed": False,
        "bundle_state": "EXACT_RETAINED",
        "cleanup_state": cleanup_state,
        "container_image": IMAGE,
        "container_platform": PLATFORM,
        "finished_time_ns": finished_ns,
        "mode": mode,
        "outcome": outcome,
        "request_bytes": len(request),
        "request_sha256": _sha256(request),
        "residue_state": "ABSENT_PROVEN" if cleanup_state in {"ABSENT_PROVEN", "EXACT_REMOVED"} else "UNKNOWN",
        "result_bytes": len(stdout) if outcome == "PASS" else 0,
        "result_path_present": outcome == "PASS",
        "result_sha256": _sha256(stdout) if outcome == "PASS" else None,
        "result_verified": outcome == "PASS",
        "returncode": returncode,
        "same_invocation_replay_allowed": False,
        "schema_version": 1,
        "source_bundle_manifest_sha256": _sha256(manifest),
        "started_time_ns": started_ns,
        "stderr_bytes": len(stderr),
        "stderr_sha256": _sha256(stderr),
        "stdout_bytes": len(retained_stdout),
        "stdout_path_present": bool(retained_stdout),
        "stdout_sha256": _sha256(retained_stdout),
        "terminal_error": terminal_error,
        "token": token,
    }
    _create_exclusive(paths["meta"], _canonical(meta))
    _fsync_directory(private_root)
    return _summary(paths, meta)


def _summary(paths: dict[str, Path], meta: dict[str, object]) -> dict[str, object]:
    return {
        "cleanup_state": meta["cleanup_state"],
        "meta_path": str(paths["meta"]),
        "mode": meta["mode"],
        "outcome": meta["outcome"],
        "residue_state": meta["residue_state"],
        "result_path": str(paths["result"]) if meta["result_verified"] else None,
        "stderr_path": str(paths["stderr"]),
        "token": meta["token"],
    }


def _classify_bundle(private_root: Path, mode: str) -> tuple[str, bytes | None]:
    bundle = private_root / (mode + ".source-bundle")
    try:
        metadata = bundle.lstat()
    except FileNotFoundError:
        return "ABSENT", None
    except OSError:
        return "PARTIAL_OR_CHANGED", None
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        return "PARTIAL_OR_CHANGED", None
    try:
        manifest = _read_mode_file(bundle / "manifest.json", 16384, "bundle_manifest", 0o444)
        _verify_bundle(bundle, manifest, mode)
        return "EXACT_RETAINED", manifest
    except BridgeError:
        return "PARTIAL_OR_CHANGED", None


ATTEMPT_KEYS = frozenset({
    "attempt_time_ns", "automatic_retry_allowed", "container_image", "container_platform", "mode",
    "request_bytes", "request_sha256", "same_invocation_replay_allowed",
    "schema_version", "source_bundle_manifest_sha256", "token",
})
META_KEYS = frozenset({
    "attempt_state", "automatic_retry_allowed", "bundle_state", "cleanup_state",
    "container_image", "container_platform", "finished_time_ns", "mode", "outcome", "request_bytes",
    "request_sha256", "residue_state", "result_bytes", "result_path_present",
    "result_sha256", "result_verified", "returncode", "same_invocation_replay_allowed",
    "schema_version", "source_bundle_manifest_sha256", "started_time_ns",
    "stderr_bytes", "stderr_sha256", "stdout_bytes", "stdout_path_present",
    "stdout_sha256", "terminal_error", "token",
})
CLEANUP_STATES = frozenset({
    "ABSENT_PROVEN", "CID_INVALID", "CID_UNAVAILABLE", "EXACT_REMOVED",
    "IDENTITY_UNPROVEN", "MULTIPLE_OR_INVALID", "POST_REMOVE_UNKNOWN",
    "QUERY_UNKNOWN", "REMOVE_UNKNOWN",
})
TERMINAL_ERRORS = frozenset({
    "bundle_changed", "docker_invocation_unknown", "docker_returncode", "docker_stream_bound",
    "docker_stream_contract", "docker_stream_type", "duplicate_json_key",
    "recovered_incomplete", "residue_unknown", "result_canonical", "result_json",
    "result_shape", "timeout",
})


def _hash_value(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _validate_attempt(value: dict[str, object], mode: str, token: str, request: bytes) -> None:
    if (
        set(value) != ATTEMPT_KEYS
        or value["automatic_retry_allowed"] is not False
        or value["same_invocation_replay_allowed"] is not False
        or value["container_image"] != IMAGE
        or value["container_platform"] != PLATFORM
        or value["mode"] != mode
        or value["token"] != token
        or type(value["attempt_time_ns"]) is not int
        or value["attempt_time_ns"] <= 0
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or type(value["request_bytes"]) is not int
        or value["request_bytes"] != len(request)
        or value["request_sha256"] != _sha256(request)
        or not _hash_value(value["source_bundle_manifest_sha256"])
    ):
        raise BridgeError("readback_attempt")


def _validate_meta(
    value: dict[str, object], mode: str, token: str, request: bytes,
    manifest_sha: str,
) -> None:
    outcome = value.get("outcome")
    cleanup = value.get("cleanup_state")
    residue = value.get("residue_state")
    returncode = value.get("returncode")
    terminal_error = value.get("terminal_error")
    if (
        set(value) != META_KEYS
        or value["automatic_retry_allowed"] is not False
        or value["same_invocation_replay_allowed"] is not False
        or value["container_image"] != IMAGE
        or value["container_platform"] != PLATFORM
        or value["attempt_state"] not in {"EXACT_RETAINED", "PARTIAL_OR_CHANGED"}
        or value["bundle_state"] not in {"ABSENT", "EXACT_RETAINED", "PARTIAL_OR_CHANGED"}
        or value["mode"] != mode
        or value["token"] != token
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or type(value["request_bytes"]) is not int
        or value["request_bytes"] != len(request)
        or value["request_sha256"] != _sha256(request)
        or value["source_bundle_manifest_sha256"] != manifest_sha
        or outcome not in {"PASS", "FAIL", "UNKNOWN"}
        or cleanup not in CLEANUP_STATES
        or residue not in {"ABSENT_PROVEN", "UNKNOWN"}
        or type(value["started_time_ns"]) is not int
        or type(value["finished_time_ns"]) is not int
        or not 0 < value["started_time_ns"] <= value["finished_time_ns"]
        or (returncode is not None and type(returncode) is not int)
        or (terminal_error is not None and terminal_error not in TERMINAL_ERRORS)
        or type(value["result_path_present"]) is not bool
        or type(value["result_verified"]) is not bool
        or type(value["stdout_path_present"]) is not bool
        or any(type(value[key]) is not int or value[key] < 0 for key in (
            "result_bytes", "stderr_bytes", "stdout_bytes",
        ))
        or not all(_hash_value(value[key]) for key in ("stderr_sha256", "stdout_sha256"))
        or (value["result_sha256"] is not None and not _hash_value(value["result_sha256"]))
        or (residue == "ABSENT_PROVEN") != (cleanup in {"ABSENT_PROVEN", "EXACT_REMOVED"})
        or (outcome == "PASS") != value["result_verified"]
        or (outcome == "PASS" and not value["result_path_present"])
        or (not value["result_path_present"] and (
            value["result_bytes"] != 0 or value["result_sha256"] is not None
        ))
        or (value["result_path_present"] and outcome == "PASS" and (
            value["result_bytes"] < 1 or value["result_sha256"] is None
        ))
        or (value["result_path_present"] and outcome != "PASS" and (
            value["result_sha256"] is None
        ))
        or (outcome != "UNKNOWN" and (value["stdout_bytes"] > 0) != value["stdout_path_present"])
        or (outcome == "UNKNOWN" and not value["stdout_path_present"] and value["stdout_bytes"] != 0)
        or (outcome == "PASS" and (
            returncode != 0 or terminal_error is not None or residue != "ABSENT_PROVEN"
            or value["attempt_state"] != "EXACT_RETAINED"
            or value["bundle_state"] != "EXACT_RETAINED"
        ))
        or (outcome == "FAIL" and (returncode in (None, 0) or residue != "ABSENT_PROVEN"))
    ):
        raise BridgeError("readback_meta")


def readback(
    *,
    mode: str,
    private_root: Path,
    token: str,
    run: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> dict[str, object]:
    if mode not in MODES or TOKEN.fullmatch(token) is None:
        raise BridgeError("arguments")
    root_metadata = _directory_metadata(private_root, 0o700)
    paths = _mode_paths(private_root, mode, token)
    request = _validate_request(paths["request"], mode)
    attempt = _parse_canonical(_read_regular(paths["attempt"], 4096, "attempt"), "attempt", 4096)
    _validate_attempt(attempt, mode, token, request)
    bundle_state, manifest = _classify_bundle(private_root, mode)
    if (
        bundle_state == "EXACT_RETAINED"
        and manifest is not None
        and attempt["source_bundle_manifest_sha256"] != _sha256(manifest)
    ):
        bundle_state, manifest = "PARTIAL_OR_CHANGED", None
    if paths["meta"].exists() or paths["meta"].is_symlink():
        meta = _parse_canonical(_read_regular(paths["meta"], 8192, "meta"), "meta", 8192)
        if (
            meta.get("terminal_error") != "recovered_incomplete"
            and (manifest is None or attempt["source_bundle_manifest_sha256"] != _sha256(manifest))
        ):
            raise BridgeError("readback_binding")
        if meta.get("bundle_state") != bundle_state:
            raise BridgeError("readback_binding")
    else:
        cleanup_state = _safe_cleanup(run=run, token=token, cidfile_path=paths["cid"])
        now = time.time_ns()
        result_present = paths["result"].exists() and not paths["result"].is_symlink()
        result = b""
        if result_present:
            try:
                result = _read_regular(paths["result"], MAX_RESULT_BYTES, "result")
            except BridgeError:
                result_present = False
                result = b""
        stdout_present = paths["stdout"].exists() and not paths["stdout"].is_symlink()
        stdout = b""
        if stdout_present:
            try:
                stdout = _read_regular(paths["stdout"], MAX_RESULT_BYTES, "stdout")
            except BridgeError:
                stdout_present = False
                stdout = b""
        stderr = b""
        if paths["stderr"].exists() and not paths["stderr"].is_symlink():
            try:
                stderr = _read_regular(paths["stderr"], MAX_STDERR_BYTES, "stderr")
            except BridgeError:
                stderr = b""
        elif not paths["stderr"].exists() and not paths["stderr"].is_symlink():
            _create_exclusive(paths["stderr"], b"")
        else:
            raise BridgeError("readback_stderr")
        meta = {
            "attempt_state": "EXACT_RETAINED",
            "automatic_retry_allowed": False,
            "bundle_state": bundle_state,
            "cleanup_state": cleanup_state,
            "container_image": IMAGE,
            "container_platform": PLATFORM,
            "finished_time_ns": now,
            "mode": mode,
            "outcome": "UNKNOWN",
            "request_bytes": len(request),
            "request_sha256": _sha256(request),
            "residue_state": "ABSENT_PROVEN" if cleanup_state in {"ABSENT_PROVEN", "EXACT_REMOVED"} else "UNKNOWN",
            "result_bytes": len(result),
            "result_path_present": result_present,
            "result_sha256": _sha256(result) if result_present else None,
            "result_verified": False,
            "returncode": None,
            "same_invocation_replay_allowed": False,
            "schema_version": 1,
            "source_bundle_manifest_sha256": attempt["source_bundle_manifest_sha256"],
            "started_time_ns": attempt["attempt_time_ns"],
            "stderr_bytes": len(stderr),
            "stderr_sha256": _sha256(stderr),
            "stdout_bytes": len(stdout),
            "stdout_path_present": stdout_present,
            "stdout_sha256": _sha256(stdout),
            "terminal_error": "recovered_incomplete",
            "token": token,
        }
        current = _directory_metadata(private_root, 0o700)
        if (root_metadata.st_dev, root_metadata.st_ino) != (current.st_dev, current.st_ino):
            raise BridgeError("private_root_race")
        _create_exclusive(paths["meta"], _canonical(meta))
        _fsync_directory(private_root)
        current = _directory_metadata(private_root, 0o700)
        if (root_metadata.st_dev, root_metadata.st_ino) != (current.st_dev, current.st_ino):
            raise BridgeError("private_root_race")
    _validate_meta(
        meta,
        mode,
        token,
        request,
        attempt["source_bundle_manifest_sha256"],
    )
    if meta.get("result_path_present") is True:
        result = _read_regular(paths["result"], MAX_RESULT_BYTES, "result")
        if meta.get("result_verified") is True:
            _validate_result(result)
        if meta.get("result_bytes") != len(result) or meta.get("result_sha256") != _sha256(result):
            raise BridgeError("readback_result")
    elif paths["result"].exists() or paths["result"].is_symlink():
        raise BridgeError("readback_result")
    stderr = _read_regular(paths["stderr"], MAX_STDERR_BYTES, "stderr")
    if meta["stderr_bytes"] != len(stderr) or meta["stderr_sha256"] != _sha256(stderr):
        raise BridgeError("readback_stderr")
    if meta["stdout_path_present"]:
        stdout = _read_regular(paths["stdout"], MAX_RESULT_BYTES, "stdout")
        if meta["stdout_bytes"] != len(stdout) or meta["stdout_sha256"] != _sha256(stdout):
            raise BridgeError("readback_stdout")
    elif paths["stdout"].exists() or paths["stdout"].is_symlink():
        raise BridgeError("readback_stdout")
    current = _directory_metadata(private_root, 0o700)
    if (root_metadata.st_dev, root_metadata.st_ino) != (current.st_dev, current.st_ino):
        raise BridgeError("private_root_race")
    return _summary(paths, meta)


def _cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=("RUN", "READBACK"), required=True)
    parser.add_argument("--mode", choices=sorted(MODES), required=True)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--token", required=True)
    arguments = parser.parse_args(argv)
    try:
        if arguments.action == "RUN":
            summary = run_bridge(mode=arguments.mode, private_root=arguments.private_root, token=arguments.token)
        else:
            summary = readback(mode=arguments.mode, private_root=arguments.private_root, token=arguments.token)
    except BridgeError as exc:
        sys.stderr.write("ITEM26_RENDER_BRIDGE_REFUSED:" + exc.code + "\n")
        return 2
    except BaseException:
        sys.stderr.write("ITEM26_RENDER_BRIDGE_REFUSED:internal\n")
        return 2
    sys.stdout.buffer.write(_canonical(summary))
    return {"PASS": 0, "FAIL": 3, "UNKNOWN": 4}[summary["outcome"]]


def cli(argv: Sequence[str] | None = None) -> int:
    previous_umask = os.umask(0o077)
    try:
        return _cli(argv)
    finally:
        os.umask(previous_umask)


if __name__ == "__main__":
    raise SystemExit(cli())
