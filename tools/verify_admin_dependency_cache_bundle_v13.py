#!/usr/bin/env python3
"""Validate the source-backed V13 BuildKit cache export successor.

V13 keeps the exact V11 wire format, release prefix, full replay and sibling
targets.  Cache-config records are validated only as BuildKit's structural
cache-key DAG; runtime portability is accepted only from the fresh consumer's
SAME_DIGEST_CACHED progress evidence.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import copy
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import types
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


V10_VERIFIER_SHA256 = (
    "77c2410406448998c81d09b04d93d12d"
    "b1cb3a4a032a0b78d9fc25626014758f"
)
BASE_PREFIX_SHA256 = (
    "93fd024e5af678b7885bcab8e72d980a"
    "9f92cfc70de4f2fd2870284e25b8ec1e"
)
COMBINED_SUFFIX = (
    b"\nFROM runtime-common AS noteai-cache-export-anchor\n"
    b"RUN --network=none printf '%s\\n' noteai-cache-export-anchor-v11\n"
    b"\nFROM runtime-common AS noteai-cache-import-observer\n"
    b"RUN --network=none printf '%s\\n' noteai-cache-import-observer-v11\n"
)
COMBINED_SUFFIX_SHA256 = (
    "7b7a5a5877567f568f6a5ff6b00481e"
    "4cf92bcc24939231098a5f2623e5104c0"
)
COMBINED_DOCKERFILE_SHA256 = (
    "c665ac4356bec6751d44878a416bbaa27"
    "8a77df77754f5461ba0adb13f43c2a0"
)
COMBINED_DOCKERFILE_BYTES = 5191
COMBINED_DOCKERFILE_LINES = 86
EXPORT_TARGET = "noteai-cache-export-anchor"
EXPORT_LINE = 83
EXPORT_MARKER = b"noteai-cache-export-anchor-v11\n"
IMPORT_TARGET = "noteai-cache-import-observer"
IMPORT_LINE = 86
IMPORT_MARKER = b"noteai-cache-import-observer-v11\n"
FULL_TARGET = "runtime-common"
FULL_DOCKERFILE_SHA256 = (
    "ed6282c422dde6e49c33da877bccf735d"
    "fbb19e29a834930fb2a1a52ef21b447"
)
MAXIMUM_SOURCE_BYTES = 4_194_304
MAXIMUM_CACHE_CONFIG_BYTES = 16_777_216
CACHE_STRUCTURE_DIAGNOSTIC_MAXIMUM_BYTES = 8_192
CACHE_LAYER_COUNT_MAXIMUM = 4_096
CACHE_RECORD_COUNT_MAXIMUM = 4_096
CACHE_RECORD_LINK_COUNT_MAXIMUM = 262_144
CACHE_RECORD_DEPTH_MAXIMUM = 512
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _read_frozen_source(path: Path, *, label: str) -> bytes:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError(f"{label} is missing") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= MAXIMUM_SOURCE_BYTES
        ):
            raise RuntimeError(f"{label} file contract changed")
        chunks: list[bytes] = []
        observed = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            observed += len(chunk)
            if observed > MAXIMUM_SOURCE_BYTES:
                raise RuntimeError(f"{label} file contract changed")
        after = os.fstat(descriptor)
        if (
            (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            )
            or observed != before.st_size
        ):
            raise RuntimeError(f"{label} changed while reading")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _load_v10_verifier():
    configured = os.environ.get("NOTEAI_V10_BUNDLE_VERIFIER_PATH")
    configured_path = (
        Path(configured)
        if configured
        else Path(__file__).with_name(
            "verify_admin_dependency_cache_bundle_v10.py"
        )
    )
    if configured_path.is_symlink():
        raise RuntimeError("frozen V10 bundle verifier file contract changed")
    v10_path = configured_path.resolve()
    source = _read_frozen_source(
        v10_path,
        label="frozen V10 bundle verifier",
    )
    if hashlib.sha256(source).hexdigest() != V10_VERIFIER_SHA256:
        raise RuntimeError("frozen V10 bundle verifier hash drift")
    module_name = "_noteai_admin_dependency_cache_bundle_v10_for_v11"
    module = types.ModuleType(module_name)
    module.__file__ = str(v10_path)
    module.__package__ = ""
    sys.modules[module_name] = module
    try:
        exec(compile(source, str(v10_path), "exec"), module.__dict__)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


_v10 = _load_v10_verifier()
_base = _v10._v6._v3._base


class V11BundleError(_v10.V10BundleError):
    """A fixed-code V11 failure safe for a public workflow log."""


def _fail(failure_code: str, message: str) -> None:
    raise V11BundleError(failure_code, message)


def _require(
    condition: bool,
    failure_code: str,
    message: str,
) -> None:
    if not condition:
        _fail(failure_code, message)


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _strict_json_bytes(payload: bytes, label: str) -> Any:
    try:
        return _v10._v6._v3.strict_json_bytes(payload, label)
    except _v10._v6._v3.BundleError as exc:
        _fail(
            getattr(exc, "failure_code", "JSON_INVALID"),
            f"{label} changed",
        )


def _regular_bytes(
    path: Path,
    *,
    maximum_bytes: int,
    failure_code: str,
    label: str,
) -> bytes:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(Path(path), flags)
    except OSError as exc:
        raise V11BundleError(failure_code, f"cannot open {label}") from exc
    try:
        before = os.fstat(descriptor)
        _require(
            stat.S_ISREG(before.st_mode)
            and before.st_nlink == 1
            and 0 <= before.st_size <= maximum_bytes,
            failure_code,
            f"{label} file contract changed",
        )
        chunks: list[bytes] = []
        observed = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, maximum_bytes + 1))
            if not chunk:
                break
            observed += len(chunk)
            _require(
                observed <= maximum_bytes,
                failure_code,
                f"{label} size changed",
            )
            chunks.append(chunk)
        after = os.fstat(descriptor)
        _require(
            (
                before.st_dev,
                before.st_ino,
                before.st_mode,
                before.st_nlink,
                before.st_size,
                before.st_mtime_ns,
            )
            == (
                after.st_dev,
                after.st_ino,
                after.st_mode,
                after.st_nlink,
                after.st_size,
                after.st_mtime_ns,
            )
            and observed == before.st_size,
            failure_code,
            f"{label} changed while reading",
        )
        return b"".join(chunks)
    except OSError as exc:
        raise V11BundleError(failure_code, f"cannot read {label}") from exc
    finally:
        os.close(descriptor)


def _read_descriptor_blob(
    cache_root: Path,
    *,
    digest_hex: str,
    expected_size: int,
    maximum_bytes: int,
    failure_code: str,
    label: str,
) -> bytes:
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    file_flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptors: list[int] = []
    try:
        root_descriptor = os.open(cache_root, directory_flags)
        descriptors.append(root_descriptor)
        blobs_descriptor = os.open(
            "blobs",
            directory_flags,
            dir_fd=root_descriptor,
        )
        descriptors.append(blobs_descriptor)
        sha_descriptor = os.open(
            "sha256",
            directory_flags,
            dir_fd=blobs_descriptor,
        )
        descriptors.append(sha_descriptor)
        blob_descriptor = os.open(
            digest_hex,
            file_flags,
            dir_fd=sha_descriptor,
        )
        descriptors.append(blob_descriptor)
        for directory_descriptor in descriptors[:3]:
            _require(
                stat.S_ISDIR(os.fstat(directory_descriptor).st_mode),
                failure_code,
                f"{label} directory contract changed",
            )
        before = os.fstat(blob_descriptor)
        _require(
            stat.S_ISREG(before.st_mode)
            and before.st_nlink == 1
            and before.st_size == expected_size
            and 0 < before.st_size <= maximum_bytes,
            failure_code,
            f"{label} file contract changed",
        )
        chunks: list[bytes] = []
        observed = 0
        while True:
            chunk = os.read(blob_descriptor, min(1024 * 1024, maximum_bytes + 1))
            if not chunk:
                break
            observed += len(chunk)
            _require(
                observed <= maximum_bytes,
                failure_code,
                f"{label} size changed",
            )
            chunks.append(chunk)
        after = os.fstat(blob_descriptor)
        _require(
            (
                before.st_dev,
                before.st_ino,
                before.st_mode,
                before.st_nlink,
                before.st_size,
                before.st_mtime_ns,
            )
            == (
                after.st_dev,
                after.st_ino,
                after.st_mode,
                after.st_nlink,
                after.st_size,
                after.st_mtime_ns,
            )
            and observed == before.st_size,
            failure_code,
            f"{label} changed while reading",
        )
        payload = b"".join(chunks)
        _require(
            hashlib.sha256(payload).hexdigest() == digest_hex,
            failure_code,
            f"{label} digest changed",
        )
        return payload
    except OSError as exc:
        raise V11BundleError(failure_code, f"{label} file contract changed") from exc
    finally:
        for descriptor_number in reversed(descriptors):
            os.close(descriptor_number)


def _bounded_descriptor_bytes(
    cache_root: Path,
    descriptor: Any,
    *,
    maximum_bytes: int,
    failure_code: str,
    label: str,
) -> bytes:
    digest = descriptor.get("digest") if isinstance(descriptor, dict) else None
    size = descriptor.get("size") if isinstance(descriptor, dict) else None
    _require(
        isinstance(digest, str)
        and DIGEST_RE.fullmatch(digest) is not None
        and isinstance(size, int)
        and not isinstance(size, bool)
        and 0 < size <= maximum_bytes,
        failure_code,
        f"{label} descriptor changed",
    )
    return _read_descriptor_blob(
        cache_root,
        digest_hex=digest.removeprefix("sha256:"),
        expected_size=size,
        maximum_bytes=maximum_bytes,
        failure_code=failure_code,
        label=label,
    )


def _initial_diagnostic(
    metadata_bytes: bytes,
    progress_bytes: bytes,
    *,
    dockerfile_kind: str,
    require_network_vertices_cached: bool,
) -> dict[str, Any]:
    return {
        "schema_version": "noteai.admin-dependency-cache-v11-diagnostic.v1",
        "projection_kind": "unresolved",
        "metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
        "progress_sha256": hashlib.sha256(progress_bytes).hexdigest(),
        "dockerfile_kind": dockerfile_kind,
        "target": None,
        "network_cache_required": require_network_vertices_cached,
        "parse_completed": False,
        "role_binding_completed": False,
        "interval_projection_completed": False,
        "cached_predicates_enforced": False,
        "role_intervals": [],
        "role_log_projections": [],
        "anchor": None,
        "observer": None,
        "other_sibling_absent": False,
        "pair_classification": None,
        "cache_record_projection": None,
        "frozen_v10_delegate_diagnostic_sha256": None,
        "historical_v10_root_cause_status": "UNKNOWN_NOT_RETAINED",
        "v11_boundary_status": "UNSET",
        "failure_code": "UNSET",
        "verdict": "fail",
    }


def _bounded_diagnostic(diagnostic: dict[str, Any]) -> dict[str, Any]:
    bounded = dict(diagnostic)
    bounded["diagnostic_sha256"] = _canonical_sha256(bounded)
    return bounded


def _expected_pre_predicate_diagnostic(
    final_diagnostic: dict[str, Any],
) -> dict[str, Any]:
    expected = dict(final_diagnostic)
    expected.pop("diagnostic_sha256", None)
    expected["frozen_v10_delegate_diagnostic_sha256"] = None
    expected["cached_predicates_enforced"] = False
    expected["v11_boundary_status"] = "PENDING_CACHE_PREDICATE"
    expected["failure_code"] = "UNSET"
    expected["verdict"] = "fail"
    return _bounded_diagnostic(expected)


def _validate_pre_predicate_diagnostic(
    retained: dict[str, Any],
    final_diagnostic: dict[str, Any],
) -> None:
    _require(
        retained == _expected_pre_predicate_diagnostic(final_diagnostic),
        "V11_PORTABILITY_BINDING_INVALID",
        "V11 pre-predicate diagnostic changed",
    )


def _emit_diagnostic(diagnostic: dict[str, Any]) -> dict[str, Any]:
    bounded = _bounded_diagnostic(diagnostic)
    print(
        "noteai_v11_progress_diagnostic="
        + json.dumps(
            bounded,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        file=sys.stderr,
    )
    return bounded


def _decoded_dockerfile(source: dict[str, Any]) -> bytes:
    infos = source.get("infos")
    _require(
        isinstance(infos, list) and len(infos) == 1,
        "PROVENANCE_DOCKERFILE_INVALID",
        "Dockerfile source info changed",
    )
    encoded = infos[0].get("data") if isinstance(infos[0], dict) else None
    _require(
        isinstance(encoded, str),
        "PROVENANCE_DOCKERFILE_INVALID",
        "Dockerfile provenance bytes missing",
    )
    try:
        return base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise V11BundleError(
            "PROVENANCE_DOCKERFILE_INVALID",
            "Dockerfile provenance base64 invalid",
        ) from exc


def _combined_dockerfile(source: dict[str, Any]) -> bytes:
    decoded = _decoded_dockerfile(source)
    _require(
        len(decoded) == COMBINED_DOCKERFILE_BYTES
        and decoded.count(b"\n") == COMBINED_DOCKERFILE_LINES
        and hashlib.sha256(decoded).hexdigest() == COMBINED_DOCKERFILE_SHA256
        and decoded.endswith(COMBINED_SUFFIX)
        and hashlib.sha256(COMBINED_SUFFIX).hexdigest()
        == COMBINED_SUFFIX_SHA256,
        "V11_DOCKERFILE_INVALID",
        "V11 combined Dockerfile changed",
    )
    _require(
        hashlib.sha256(decoded[: -len(COMBINED_SUFFIX)]).hexdigest()
        == BASE_PREFIX_SHA256,
        "V11_DOCKERFILE_INVALID",
        "V11 release dependency prefix changed",
    )
    return decoded


@contextmanager
def _legacy_dependency_metadata(
    metadata: dict[str, Any],
    *,
    child_steps: tuple[str, ...],
) -> Iterator[Path]:
    legacy = copy.deepcopy(metadata)
    _provenance, args, _build_config, source = _v10._metadata_parts(legacy)
    decoded = _combined_dockerfile(source)
    args["target"] = FULL_TARGET
    source["infos"][0]["data"] = base64.b64encode(
        decoded[: -len(COMBINED_SUFFIX)]
    ).decode("ascii")
    locations = source.get("locations")
    _require(
        isinstance(locations, dict),
        "PROVENANCE_LOCATION_INVALID",
        "BuildKit source locations changed",
    )
    for step in child_steps:
        _require(
            step in locations,
            "PROVENANCE_LOCATION_INVALID",
            "V11 child source location missing",
        )
        locations[step] = {}
    payload = json.dumps(
        legacy,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    temporary_root = Path(tempfile.mkdtemp(prefix="noteai-v11-legacy-"))
    legacy_path = temporary_root / "metadata.json"
    try:
        _v10._v6._write_exclusive_regular(legacy_path, payload)
        _require(
            stat.S_IMODE(legacy_path.stat().st_mode) == 0o600,
            "V11_LEGACY_EVIDENCE_INVALID",
            "V11 legacy metadata mode changed",
        )
        yield legacy_path
    finally:
        try:
            shutil.rmtree(temporary_root)
        except OSError as exc:
            raise V11BundleError(
                "V11_LEGACY_EVIDENCE_CLEANUP_FAILED",
                "V11 legacy metadata cleanup failed",
            ) from exc
        _require(
            not temporary_root.exists() and not temporary_root.is_symlink(),
            "V11_LEGACY_EVIDENCE_CLEANUP_FAILED",
            "V11 legacy metadata cleanup incomplete",
        )


def _delegate_frozen_v10_prefix_chain(
    metadata: dict[str, Any],
    progress_path: Path,
    *,
    child_steps: tuple[str, ...],
    require_network_vertices_cached: bool,
) -> dict[str, Any]:
    with _legacy_dependency_metadata(
        metadata,
        child_steps=child_steps,
    ) as legacy_path, _v10._PATCH_LOCK:
        try:
            return _v10._delegate_v9(
                legacy_path,
                progress_path,
                dockerfile_kind="prefix",
                require_network_vertices_cached=(
                    require_network_vertices_cached
                ),
            )
        except _v10._FrozenV9Rejection as exc:
            raise V11BundleError(exc.failure_code, str(exc)) from None


def _optional_step_for_line(
    source: dict[str, Any],
    steps: dict[str, dict[str, Any]],
    line: int,
) -> str | None:
    locations = source.get("locations")
    _require(
        isinstance(locations, dict) and bool(locations),
        "PROVENANCE_LOCATION_INVALID",
        "BuildKit source locations missing",
    )
    matches: list[str] = []
    for step_id, location in locations.items():
        _require(
            isinstance(step_id, str) and step_id in steps,
            "PROVENANCE_LOCATION_INVALID",
            "BuildKit source location step changed",
        )
        if location != {} and line in _v10._location_starts(location, step_id):
            matches.append(step_id)
    _require(
        len(matches) <= 1,
        "PROVENANCE_ROLE_LOCATION_AMBIGUOUS",
        f"BuildKit source binding changed for line {line}",
    )
    return matches[0] if matches else None


def _collect_interval(
    *,
    role: str,
    line: int,
    step_id: str,
    digest: str,
    vertex: dict[str, Any],
    build_window: Any,
) -> dict[str, Any]:
    intervals = sorted(vertex["intervals"].items())
    _require(
        bool(intervals),
        "NETWORK_VERTEX_LIFECYCLE_INCOMPLETE",
        f"BuildKit {role} lifecycle missing",
    )
    projected: list[dict[str, Any]] = []
    for started_ns, interval in intervals:
        _require(
            interval["completed"] is not None
            and build_window.started_ns
            <= started_ns
            <= interval["completed_ns"]
            <= build_window.finished_ns,
            "NETWORK_VERTEX_LIFECYCLE_OUTSIDE_BUILD",
            f"BuildKit {role} lifecycle changed",
        )
        projected.append(
            {
                "started": interval["started_text"],
                "completed": interval["completed_text"],
                "cached": interval["cached"],
            }
        )
    return {
        "role": role,
        "line": line,
        "step_id": step_id,
        "vertex_digest": digest,
        "interval_count": len(projected),
        "completed_interval_count": len(projected),
        "cached_interval_count": sum(int(item["cached"]) for item in projected),
        "noncached_interval_count": sum(
            int(not item["cached"]) for item in projected
        ),
        "intervals": projected,
    }


def _log_projection(
    digest: str,
    log_streams: dict[tuple[str, int], bytearray],
) -> dict[str, Any]:
    streams = sorted(
        (
            stream,
            bytes(payload),
        )
        for (candidate, stream), payload in log_streams.items()
        if candidate == digest
    )
    return {
        "stream_count": len(streams),
        "decoded_bytes": sum(len(payload) for _stream, payload in streams),
        "streams": [
            {
                "stream": stream,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
            }
            for stream, payload in streams
        ],
    }


def _collect_roles(
    metadata: dict[str, Any],
    source: dict[str, Any],
    steps: dict[str, dict[str, Any]],
    step_to_digests: dict[str, list[str]],
    vertices: dict[str, dict[str, Any]],
    log_streams: dict[tuple[str, int], bytearray],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    build_window = _v10._v7._provenance_build_window(metadata)
    intervals: list[dict[str, Any]] = []
    logs: list[dict[str, Any]] = []
    for spec in _v10._v6.ROLE_SPECS:
        role = str(spec["role"])
        line = int(spec["line"])
        step_id = _v10._step_for_line(source, steps, line)
        step = steps[step_id]
        _require(
            isinstance(step["exec"], dict)
            and step["platform"] == {"Architecture": "amd64", "OS": "linux"},
            "PROVENANCE_ROLE_NOT_EXEC",
            f"BuildKit {role} structural binding changed",
        )
        digest = _v10._digest_for_step(
            step_to_digests,
            step_id,
            label=role,
        )
        _require(
            digest in vertices,
            "PROVENANCE_ROLE_VERTEX_MISSING",
            f"BuildKit {role} progress vertex missing",
        )
        intervals.append(
            _collect_interval(
                role=role,
                line=line,
                step_id=step_id,
                digest=digest,
                vertex=vertices[digest],
                build_window=build_window,
            )
        )
        logs.append({"role": role, **_log_projection(digest, log_streams)})
    return intervals, logs


def _progress_inputs(
    progress_bytes: bytes,
    *,
    child_digest: str,
    parent_digest: str,
    label: str,
) -> tuple[int, int]:
    explicit = 0
    omitted = 0
    for line_number, raw_line in enumerate(progress_bytes.splitlines(), start=1):
        if not raw_line.strip():
            continue
        event = _strict_json_bytes(
            raw_line,
            f"BuildKit rawjson line {line_number}",
        )
        vertexes = event.get("vertexes", []) if isinstance(event, dict) else []
        for vertex in vertexes:
            if isinstance(vertex, dict) and vertex.get("digest") == child_digest:
                if "inputs" not in vertex:
                    omitted += 1
                    continue
                _require(
                    vertex["inputs"] == [parent_digest],
                    "V11_CHILD_PROGRESS_INPUT_INVALID",
                    f"BuildKit {label} progress parent changed",
                )
                explicit += 1
    _require(
        explicit > 0,
        "V11_CHILD_PROGRESS_INPUT_MISSING",
        f"BuildKit {label} progress parent is unbound",
    )
    return explicit, omitted


def _child_projection(
    metadata: dict[str, Any],
    progress_bytes: bytes,
    source: dict[str, Any],
    steps: dict[str, dict[str, Any]],
    step_to_digests: dict[str, list[str]],
    vertices: dict[str, dict[str, Any]],
    log_streams: dict[tuple[str, int], bytearray],
    *,
    line: int,
    role: str,
    marker: bytes,
) -> dict[str, Any]:
    pip_step = _v10._step_for_line(source, steps, 76)
    child_step = _v10._step_for_line(source, steps, line)
    child = steps[child_step]
    _require(
        isinstance(child["exec"], dict)
        and child["platform"] == {"Architecture": "amd64", "OS": "linux"}
        and child["inputs"] == [(pip_step, 0)],
        "V11_CHILD_PROVENANCE_BINDING_INVALID",
        f"BuildKit {role} structural binding changed",
    )
    exec_op = child["exec"]
    _require(
        exec_op.get("network") == 2
        and exec_op.get("security", 0) == 0
        and not _v10._forbidden_exec_capability(exec_op),
        "V11_CHILD_NETWORK_OR_SECRET_INVALID",
        f"BuildKit {role} network or secret contract changed",
    )
    pip_digest = _v10._digest_for_step(
        step_to_digests,
        pip_step,
        label="runtime_pip",
    )
    child_digest = _v10._digest_for_step(
        step_to_digests,
        child_step,
        label=role,
    )
    _require(
        child_digest in vertices,
        "V11_CHILD_PROGRESS_VERTEX_MISSING",
        f"BuildKit {role} progress vertex missing",
    )
    explicit_inputs, omitted_inputs = _progress_inputs(
        progress_bytes,
        child_digest=child_digest,
        parent_digest=pip_digest,
        label=role,
    )
    interval = _collect_interval(
        role=role,
        line=line,
        step_id=child_step,
        digest=child_digest,
        vertex=vertices[child_digest],
        build_window=_v10._v7._provenance_build_window(metadata),
    )
    streams = {
        stream: bytes(payload)
        for (digest, stream), payload in log_streams.items()
        if digest == child_digest
    }
    _require(
        all(
            marker not in bytes(payload)
            for (digest, _stream), payload in log_streams.items()
            if digest != child_digest
        ),
        "V11_CHILD_MARKER_MISBOUND",
        f"BuildKit {role} marker is bound to another vertex",
    )
    _require(
        streams == {1: marker},
        "V11_CHILD_MARKER_INVALID",
        f"BuildKit {role} decoded marker changed",
    )
    return {
        "role": role,
        "line": line,
        "step_id": child_step,
        "vertex_digest": child_digest,
        "direct_parent_step_id": pip_step,
        "direct_parent_vertex_digest": pip_digest,
        "platform": "linux/amd64",
        "network_mode": "NONE",
        "network_enum": 2,
        "progress_explicit_input_update_count": explicit_inputs,
        "progress_omitted_input_update_count": omitted_inputs,
        "interval": interval,
        "log": _log_projection(child_digest, log_streams),
        "marker_occurrence_count": 1,
    }


def _prove_sibling_absent(
    source: dict[str, Any],
    steps: dict[str, dict[str, Any]],
    step_to_digests: dict[str, list[str]],
    vertices: dict[str, dict[str, Any]],
    log_streams: dict[tuple[str, int], bytearray],
    *,
    requested_child: dict[str, Any],
    other_line: int,
    other_marker: bytes,
) -> None:
    direct_children = sorted(
        step_id
        for step_id, step in steps.items()
        if step.get("inputs")
        == [(requested_child["direct_parent_step_id"], 0)]
    )
    _require(
        direct_children == [requested_child["step_id"]],
        "V11_SIBLING_TARGET_PRESENT",
        "unrequested V11 sibling target or child entered the solve graph",
    )
    other_step = _optional_step_for_line(source, steps, other_line)
    other_digests = (
        step_to_digests.get(other_step, []) if other_step is not None else []
    )
    _require(
        not other_digests
        and all(digest not in vertices for digest in other_digests)
        and all(
            other_marker not in bytes(payload)
            for payload in log_streams.values()
        ),
        "V11_SIBLING_TARGET_PRESENT",
        "unrequested V11 sibling target entered the solve",
    )


def _enforce_cache_predicates(
    role_intervals: list[dict[str, Any]],
    child: dict[str, Any],
    *,
    require_cached: bool,
) -> None:
    for projection in role_intervals:
        _require(
            projection["interval_count"] >= 1
            and projection["completed_interval_count"]
            == projection["interval_count"],
            "NETWORK_VERTEX_LIFECYCLE_INCOMPLETE",
            f"BuildKit {projection['role']} lifecycle changed",
        )
        expected = (
            projection["cached_interval_count"]
            == projection["interval_count"]
            and projection["noncached_interval_count"] == 0
            if require_cached
            else projection["cached_interval_count"] == 0
            and projection["noncached_interval_count"]
            == projection["interval_count"]
        )
        _require(
            expected,
            (
                "NETWORK_VERTEX_NOT_CACHED"
                if require_cached
                else "PRODUCER_NETWORK_VERTEX_CACHED"
            ),
            (
                f"BuildKit {projection['role']} vertex was not cached"
                if require_cached
                else f"BuildKit producer {projection['role']} vertex was cached"
            ),
        )
    child_interval = child["interval"]
    _require(
        child_interval["interval_count"] == 1
        and child_interval["completed_interval_count"] == 1
        and child_interval["cached_interval_count"] == 0
        and child_interval["noncached_interval_count"] == 1,
        "V11_CHILD_INTERVAL_INVALID",
        f"BuildKit {child['role']} lifecycle changed",
    )


CACHE_RECORD_SUMMARY_KEYS = frozenset(
    {
        "schema_version",
        "producer_summary_sha256",
        "cache_config_sha256",
        "cache_config_bytes",
        "root_layer_descriptor_count",
        "layer_count",
        "record_count",
        "result_bearing_record_count",
        "layer_result_count",
        "chained_result_count",
        "input_group_count",
        "link_count",
        "structural_validation",
    }
)
CACHE_RECORD_STRUCTURAL_VALIDATION = {
    "cache_config_validated": True,
    "record_and_layer_dag_validated": True,
    "record_and_layer_reachability_validated": True,
    "vertex_digest_binding_attempted": False,
    "direct_identity_path_claimed": False,
    "runtime_portability_proven": False,
}


def _validate_cache_record_summary(
    cache_record: Any,
    *,
    expected_producer_summary_sha256: str,
) -> dict[str, Any]:
    _require(
        isinstance(cache_record, dict)
        and set(cache_record) == CACHE_RECORD_SUMMARY_KEYS,
        "V13_CACHE_STRUCTURE_INVALID",
        "V13 cache structure summary keys changed",
    )
    _require(
        cache_record["schema_version"]
        == "noteai.admin-dependency-cache-record.v13"
        and cache_record["producer_summary_sha256"]
        == expected_producer_summary_sha256
        and SHA256_RE.fullmatch(cache_record["producer_summary_sha256"])
        is not None
        and isinstance(cache_record["cache_config_sha256"], str)
        and SHA256_RE.fullmatch(cache_record["cache_config_sha256"])
        is not None,
        "V13_CACHE_STRUCTURE_INVALID",
        "V13 cache structure digest binding changed",
    )
    integer_keys = (
        "cache_config_bytes",
        "root_layer_descriptor_count",
        "layer_count",
        "record_count",
        "result_bearing_record_count",
        "layer_result_count",
        "chained_result_count",
        "input_group_count",
        "link_count",
    )
    _require(
        all(
            isinstance(cache_record[key], int)
            and not isinstance(cache_record[key], bool)
            for key in integer_keys
        ),
        "V13_CACHE_STRUCTURE_INVALID",
        "V13 cache structure count type changed",
    )
    result_count = (
        cache_record["layer_result_count"]
        + cache_record["chained_result_count"]
    )
    _require(
        0 < cache_record["cache_config_bytes"] <= MAXIMUM_CACHE_CONFIG_BYTES
        and 0 < cache_record["layer_count"] <= CACHE_LAYER_COUNT_MAXIMUM
        and cache_record["root_layer_descriptor_count"]
        == cache_record["layer_count"]
        and 0 < cache_record["record_count"] <= CACHE_RECORD_COUNT_MAXIMUM
        and 0 < cache_record["result_bearing_record_count"]
        <= cache_record["record_count"]
        and cache_record["layer_result_count"] >= 0
        and cache_record["chained_result_count"] >= 0
        and result_count >= cache_record["result_bearing_record_count"]
        and 0 < cache_record["input_group_count"]
        <= cache_record["link_count"]
        <= CACHE_RECORD_LINK_COUNT_MAXIMUM
        and cache_record["structural_validation"]
        == CACHE_RECORD_STRUCTURAL_VALIDATION,
        "V13_CACHE_STRUCTURE_INVALID",
        "V13 cache structure count or verdict changed",
    )
    return cache_record


def validate_build_evidence(
    metadata_path: Path,
    progress_path: Path,
    *,
    dockerfile_kind: str,
    require_network_vertices_cached: bool,
    producer_summary_path: Path | None = None,
    cache_record_path: Path | None = None,
    expected_cache_record_sha256: str | None = None,
    pre_predicate_diagnostic_output_path: Path | None = None,
    diagnostic_output_path: Path | None = None,
    pair_output_path: Path | None = None,
) -> dict[str, Any]:
    metadata_path = Path(metadata_path)
    progress_path = Path(progress_path)
    metadata_bytes = _regular_bytes(
        metadata_path,
        maximum_bytes=_v10._v6.MAXIMUM_METADATA_BYTES,
        failure_code="METADATA_FILE_INVALID",
        label="BuildKit metadata",
    )
    progress_bytes = _regular_bytes(
        progress_path,
        maximum_bytes=_v10._v6.MAXIMUM_PROGRESS_BYTES,
        failure_code="RAWJSON_FILE_INVALID",
        label="BuildKit rawjson",
    )
    diagnostic = _initial_diagnostic(
        metadata_bytes,
        progress_bytes,
        dockerfile_kind=dockerfile_kind,
        require_network_vertices_cached=require_network_vertices_cached,
    )

    def retain_diagnostic(value: dict[str, Any]) -> dict[str, Any]:
        bounded = _bounded_diagnostic(value)
        if diagnostic_output_path is not None:
            _write_json(Path(diagnostic_output_path), bounded)
        return bounded

    try:
        if dockerfile_kind == "full":
            _require(
                require_network_vertices_cached,
                "FULL_REPLAY_CACHE_MODE_INVALID",
                "full replay must retain the imported dependency cache",
            )
            summary = _v10.validate_build_evidence(
                metadata_path,
                progress_path,
                dockerfile_kind="full",
                require_network_vertices_cached=True,
            )
            _require(
                summary["dockerfile_sha256"] == FULL_DOCKERFILE_SHA256,
                "FULL_DOCKERFILE_CHANGED",
                "full replay Dockerfile changed",
            )
            return summary

        _require(
            dockerfile_kind == "prefix",
            "DOCKERFILE_KIND_INVALID",
            "Dockerfile kind changed",
        )
        metadata = _strict_json_bytes(metadata_bytes, "BuildKit metadata")
        _require(
            isinstance(metadata, dict),
            "PROVENANCE_ROOT_INVALID",
            "BuildKit metadata root changed",
        )
        _provenance, args, build_config, source = _v10._metadata_parts(metadata)
        target = args.get("target")
        diagnostic["target"] = target
        _combined_dockerfile(source)
        ((vertices, _names, log_streams, _refs, _plain), _parse_diagnostic) = (
            _v10._strict_progress_view(
                progress_bytes,
                progress_path,
                dockerfile_kind="prefix",
                require_network_vertices_cached=require_network_vertices_cached,
            )
        )
        steps, step_to_digests = _v10._step_graph(build_config)
        diagnostic["parse_completed"] = True
        roles, role_logs = _collect_roles(
            metadata,
            source,
            steps,
            step_to_digests,
            vertices,
            log_streams,
        )
        diagnostic["role_binding_completed"] = True
        diagnostic["interval_projection_completed"] = True
        diagnostic["role_intervals"] = roles
        diagnostic["role_log_projections"] = role_logs

        if target == EXPORT_TARGET:
            _require(
                not require_network_vertices_cached,
                "V11_EXPORT_CACHE_MODE_INVALID",
                "V11 export anchor cannot be a cache replay",
            )
            diagnostic["projection_kind"] = "export-anchor-prefix"
            child = _child_projection(
                metadata,
                progress_bytes,
                source,
                steps,
                step_to_digests,
                vertices,
                log_streams,
                line=EXPORT_LINE,
                role="cache_export_anchor",
                marker=EXPORT_MARKER,
            )
            diagnostic["anchor"] = child
            _prove_sibling_absent(
                source,
                steps,
                step_to_digests,
                vertices,
                log_streams,
                requested_child=child,
                other_line=IMPORT_LINE,
                other_marker=IMPORT_MARKER,
            )
        elif target == IMPORT_TARGET:
            _require(
                require_network_vertices_cached,
                "V11_IMPORT_CACHE_MODE_INVALID",
                "V11 import observer requires a cache replay",
            )
            diagnostic["projection_kind"] = "import-observer-prefix"
            child = _child_projection(
                metadata,
                progress_bytes,
                source,
                steps,
                step_to_digests,
                vertices,
                log_streams,
                line=IMPORT_LINE,
                role="cache_import_observer",
                marker=IMPORT_MARKER,
            )
            diagnostic["observer"] = child
            _prove_sibling_absent(
                source,
                steps,
                step_to_digests,
                vertices,
                log_streams,
                requested_child=child,
                other_line=EXPORT_LINE,
                other_marker=EXPORT_MARKER,
            )
            _require(
                producer_summary_path is not None
                and cache_record_path is not None
                and isinstance(expected_cache_record_sha256, str)
                and SHA256_RE.fullmatch(expected_cache_record_sha256)
                is not None,
                "V11_PAIR_EVIDENCE_MISSING",
                "V13 producer summary or trusted cache record is missing",
            )
            producer, producer_summary_sha256 = _read_summary_with_sha256(
                Path(producer_summary_path),
                label="V11 producer summary",
            )
            cache_record, cache_record_sha256 = _read_summary_with_sha256(
                Path(cache_record_path),
                label="V11 cache record",
            )
            _require(
                cache_record_sha256 == expected_cache_record_sha256,
                "V13_CACHE_RECORD_TRUST_INVALID",
                "V13 cache record changed after core validation",
            )
            _validate_cache_record_summary(
                cache_record,
                expected_producer_summary_sha256=producer_summary_sha256,
            )
            pair = classify_pair(
                producer,
                {
                    "target": IMPORT_TARGET,
                    "network_vertices": roles,
                },
            )
            diagnostic["pair_classification"] = pair
            diagnostic["cache_record_projection"] = {
                "sha256": cache_record_sha256,
                "producer_summary_sha256": cache_record.get(
                    "producer_summary_sha256"
                ),
                "cache_config_sha256": cache_record.get(
                    "cache_config_sha256"
                ),
                "cache_config_bytes": cache_record.get(
                    "cache_config_bytes"
                ),
                "layer_count": cache_record.get("layer_count"),
                "record_count": cache_record.get("record_count"),
                "result_bearing_record_count": cache_record.get(
                    "result_bearing_record_count"
                ),
                "link_count": cache_record.get("link_count"),
                "structural_validation": cache_record.get(
                    "structural_validation"
                ),
            }
            if pair_output_path is not None:
                _write_json(Path(pair_output_path), pair)
            _require(
                pair["classification"] == "SAME_DIGEST_CACHED",
                "V13_PAIR_CACHE_PREDICATE_FAILED",
                "V13 fresh consumer did not prove SAME_DIGEST_CACHED",
            )
        else:
            _fail("V11_TARGET_INVALID", "V11 Dockerfile target changed")

        diagnostic["other_sibling_absent"] = True
        diagnostic["v11_boundary_status"] = "PENDING_CACHE_PREDICATE"
        if pre_predicate_diagnostic_output_path is not None:
            _write_json(
                Path(pre_predicate_diagnostic_output_path),
                _bounded_diagnostic(diagnostic),
            )
        _enforce_cache_predicates(
            roles,
            child,
            require_cached=require_network_vertices_cached,
        )
        child_steps = tuple(
            step
            for step in (
                _optional_step_for_line(source, steps, EXPORT_LINE),
                _optional_step_for_line(source, steps, IMPORT_LINE),
            )
            if step is not None
        )
        delegated = _delegate_frozen_v10_prefix_chain(
            metadata,
            progress_path,
            child_steps=child_steps,
            require_network_vertices_cached=(
                require_network_vertices_cached
            ),
        )
        delegated_diagnostic = delegated.get("v9_rawjson_diagnostic")
        _require(
            isinstance(delegated_diagnostic, dict)
            and SHA256_RE.fullmatch(
                str(delegated_diagnostic.get("diagnostic_sha256", ""))
            )
            is not None,
            "FROZEN_V10_DELEGATE_INVALID",
            "frozen V10 prefix delegate diagnostic changed",
        )
        diagnostic["frozen_v10_delegate_diagnostic_sha256"] = (
            delegated_diagnostic["diagnostic_sha256"]
        )
        _require(
            _regular_bytes(
                metadata_path,
                maximum_bytes=_v10._v6.MAXIMUM_METADATA_BYTES,
                failure_code="METADATA_FILE_INVALID",
                label="BuildKit metadata",
            )
            == metadata_bytes
            and _regular_bytes(
                progress_path,
                maximum_bytes=_v10._v6.MAXIMUM_PROGRESS_BYTES,
                failure_code="RAWJSON_FILE_INVALID",
                label="BuildKit rawjson",
            )
            == progress_bytes,
            "ORIGINAL_EVIDENCE_CHANGED",
            "original BuildKit evidence changed during validation",
        )
        diagnostic["cached_predicates_enforced"] = True
        diagnostic["v11_boundary_status"] = "NO_FAILURE"
        diagnostic["failure_code"] = "NONE"
        diagnostic["verdict"] = "pass"
        bounded = _emit_diagnostic(diagnostic)
        if diagnostic_output_path is not None:
            _write_json(Path(diagnostic_output_path), bounded)
        provenance_metadata = metadata["buildx.build.provenance"]["metadata"]
        started = provenance_metadata["buildStartedOn"]
        finished = provenance_metadata["buildFinishedOn"]
        duration = (
            _base.parse_time(finished, "buildFinishedOn")
            - _base.parse_time(started, "buildStartedOn")
        ).total_seconds()
        return {
            "schema_version": "noteai.admin-dependency-cache-build.v11",
            "metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
            "progress_sha256": hashlib.sha256(progress_bytes).hexdigest(),
            "dockerfile_sha256": COMBINED_DOCKERFILE_SHA256,
            "dockerfile_kind": "prefix",
            "target": target,
            "build_started_on": started,
            "build_finished_on": finished,
            "duration_seconds": duration,
            "network_vertex_count": len(roles),
            "network_vertices_cached": require_network_vertices_cached,
            "network_vertices": roles,
            "role_log_projections": role_logs,
            "anchor": diagnostic["anchor"],
            "observer": diagnostic["observer"],
            "other_sibling_absent": True,
            "pair": diagnostic["pair_classification"],
            "cache_record_projection": diagnostic[
                "cache_record_projection"
            ],
            "v11_rawjson_diagnostic": bounded,
        }
    except V11BundleError as exc:
        diagnostic["v11_boundary_status"] = "DETERMINED_BY_V11"
        diagnostic["failure_code"] = exc.failure_code
        diagnostic["verdict"] = "fail"
        retain_diagnostic(diagnostic)
        _emit_diagnostic(diagnostic)
        raise
    except _v10.V10BundleError as exc:
        diagnostic["v11_boundary_status"] = "FROZEN_V10_REJECTION"
        diagnostic["failure_code"] = exc.failure_code
        diagnostic["verdict"] = "fail"
        retain_diagnostic(diagnostic)
        _emit_diagnostic(diagnostic)
        raise V11BundleError(exc.failure_code, str(exc)) from None
    except _v10._v6._v3.BundleError as exc:
        code = getattr(exc, "failure_code", "V11_EVIDENCE_INVALID")
        diagnostic["v11_boundary_status"] = "DETERMINED_BY_V11"
        diagnostic["failure_code"] = code
        diagnostic["verdict"] = "fail"
        retain_diagnostic(diagnostic)
        _emit_diagnostic(diagnostic)
        raise V11BundleError(code, "V11 build evidence invalid") from None
    except OSError as exc:
        diagnostic["v11_boundary_status"] = "V11_IO_FAILURE"
        diagnostic["failure_code"] = "V11_IO_FAILED"
        diagnostic["verdict"] = "fail"
        retain_diagnostic(diagnostic)
        _emit_diagnostic(diagnostic)
        raise V11BundleError(
            "V11_IO_FAILED",
            "V11 evidence I/O failed",
        ) from exc
    except Exception:
        diagnostic["v11_boundary_status"] = "V11_UNEXPECTED_FAILURE"
        diagnostic["failure_code"] = "V11_UNEXPECTED_FAILURE"
        diagnostic["verdict"] = "fail"
        retain_diagnostic(diagnostic)
        _emit_diagnostic(diagnostic)
        raise V11BundleError(
            "V11_UNEXPECTED_FAILURE",
            "V11 evidence validation failed unexpectedly",
        ) from None


def _read_summary_with_sha256(
    path: Path,
    *,
    label: str,
) -> tuple[dict[str, Any], str]:
    payload_bytes = _regular_bytes(
        Path(path),
        maximum_bytes=2_097_152,
        failure_code="V11_SUMMARY_FILE_INVALID",
        label=label,
    )
    payload = _strict_json_bytes(payload_bytes, label)
    _require(
        isinstance(payload, dict),
        "V11_SUMMARY_INVALID",
        f"{label} root changed",
    )
    return payload, hashlib.sha256(payload_bytes).hexdigest()


def _read_summary(path: Path, *, label: str) -> dict[str, Any]:
    payload, _sha256 = _read_summary_with_sha256(path, label=label)
    return payload


def _result_count(record: dict[str, Any]) -> int:
    layers = record.get("layers", [])
    chains = record.get("chains", [])
    _require(
        isinstance(layers, list) and isinstance(chains, list),
        "CACHE_RECORD_RESULT_INVALID",
        "BuildKit cache record results changed",
    )
    return len(layers) + len(chains)


def _cache_structure_diagnostic(
    *,
    config: Any,
    root_layers: Any,
    config_sha256: str,
    config_bytes: int,
    producer_summary_sha256: str,
) -> dict[str, Any]:
    cache_layers = config.get("layers") if isinstance(config, dict) else None
    records = config.get("records") if isinstance(config, dict) else None
    root_layer_count = len(root_layers) if isinstance(root_layers, list) else None
    layer_count = len(cache_layers) if isinstance(cache_layers, list) else None
    record_count = len(records) if isinstance(records, list) else None
    result_bearing_record_count = None
    layer_result_count = None
    chained_result_count = None
    input_group_count = None
    link_count = None
    if isinstance(records, list):
        result_bearing_record_count = 0
        layer_result_count = 0
        chained_result_count = 0
        input_group_count = 0
        link_count = 0
        for record in records:
            if not isinstance(record, dict):
                continue
            layers = record.get("layers", [])
            chains = record.get("chains", [])
            inputs = record.get("inputs", [])
            if isinstance(layers, list):
                layer_result_count += len(layers)
            if isinstance(chains, list):
                chained_result_count += len(chains)
            if (
                isinstance(layers, list)
                and isinstance(chains, list)
                and (layers or chains)
            ):
                result_bearing_record_count += 1
            if isinstance(inputs, list):
                input_group_count += len(inputs)
                for group in inputs:
                    if isinstance(group, list):
                        link_count += len(group)
    diagnostic = {
        "schema_version": (
            "noteai.admin-dependency-cache-structure-diagnostic.v13"
        ),
        "validation_phase": "PENDING_STRUCTURAL_VALIDATION",
        "producer_summary_sha256": producer_summary_sha256,
        "cache_config_sha256": config_sha256,
        "cache_config_bytes": config_bytes,
        "root_layer_descriptor_count": root_layer_count,
        "layer_count": layer_count,
        "record_count": record_count,
        "result_bearing_record_count": result_bearing_record_count,
        "layer_result_count": layer_result_count,
        "chained_result_count": chained_result_count,
        "input_group_count": input_group_count,
        "link_count": link_count,
        "vertex_digest_binding_attempted": False,
        "direct_identity_path_claimed": False,
        "runtime_portability_proven": False,
        "structural_validation_completed": False,
    }
    encoded = json.dumps(
        diagnostic,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    _require(
        len(encoded) <= CACHE_STRUCTURE_DIAGNOSTIC_MAXIMUM_BYTES,
        "CACHE_STRUCTURE_DIAGNOSTIC_INVALID",
        "BuildKit cache structure diagnostic exceeded its bound",
    )
    print(
        "noteai_v13_cache_structure_diagnostic=" + encoded.decode("utf-8"),
        file=sys.stderr,
    )
    return diagnostic


def _preflight_cache_structure(
    config: Any,
    diagnostic: dict[str, Any],
) -> None:
    _require(
        isinstance(config, dict)
        and set(config) == {"layers", "records"}
        and isinstance(config["layers"], list)
        and isinstance(config["records"], list),
        "CACHE_RECORD_CONFIG_INVALID",
        "BuildKit cache config root changed",
    )
    records = config["records"]
    _require(
        0 < len(config["layers"]) <= CACHE_LAYER_COUNT_MAXIMUM,
        "CACHE_LAYER_COUNT_INVALID",
        "BuildKit cache layer count exceeds V13 bound",
    )
    _require(
        0 < len(records) <= CACHE_RECORD_COUNT_MAXIMUM,
        "CACHE_RECORD_COUNT_INVALID",
        "BuildKit cache record count exceeds V13 bound",
    )
    _require(
        isinstance(diagnostic.get("link_count"), int)
        and not isinstance(diagnostic.get("link_count"), bool)
        and diagnostic["link_count"] <= CACHE_RECORD_LINK_COUNT_MAXIMUM,
        "CACHE_RECORD_LINK_COUNT_INVALID",
        "BuildKit cache record link count exceeds V13 bound",
    )

    links: list[set[int]] = []
    incoming = [0] * len(records)
    for record_index, record in enumerate(records):
        _require(
            isinstance(record, dict),
            "CACHE_RECORD_GRAPH_INVALID",
            "BuildKit cache record graph changed",
        )
        inputs = record.get("inputs", [])
        _require(
            isinstance(inputs, list),
            "CACHE_RECORD_GRAPH_INVALID",
            "BuildKit cache record input graph changed",
        )
        record_links: set[int] = set()
        for group in inputs:
            _require(
                isinstance(group, list) and bool(group),
                "CACHE_RECORD_GRAPH_INVALID",
                "BuildKit cache record input group changed",
            )
            for item in group:
                link = item.get("link") if isinstance(item, dict) else None
                _require(
                    isinstance(link, int)
                    and not isinstance(link, bool)
                    and 0 <= link < len(records)
                    and link != record_index,
                    "CACHE_RECORD_GRAPH_INVALID",
                    "BuildKit cache record link changed",
                )
                record_links.add(link)
        links.append(record_links)
        for link in record_links:
            incoming[link] += 1

    ready = [index for index, count in enumerate(incoming) if count == 0]
    depth = [1] * len(records)
    processed = 0
    while ready:
        current = ready.pop()
        processed += 1
        _require(
            depth[current] <= CACHE_RECORD_DEPTH_MAXIMUM,
            "CACHE_RECORD_GRAPH_DEPTH_INVALID",
            "BuildKit cache record graph depth exceeds V13 bound",
        )
        for linked in links[current]:
            depth[linked] = max(depth[linked], depth[current] + 1)
            incoming[linked] -= 1
            if incoming[linked] == 0:
                ready.append(linked)
    _require(
        processed == len(records),
        "CACHE_RECORD_GRAPH_CYCLE_INVALID",
        "BuildKit cache record graph contains a cycle",
    )


def validate_cache_record(
    cache_root: Path,
    producer_summary_path: Path,
) -> dict[str, Any]:
    cache_root = Path(cache_root)
    producer_summary_path = Path(producer_summary_path)
    producer, producer_summary_sha256 = _read_summary_with_sha256(
        producer_summary_path,
        label="V13 producer summary",
    )
    _require(
        producer.get("schema_version")
        == "noteai.admin-dependency-cache-build.v11"
        and producer.get("target") == EXPORT_TARGET
        and producer.get("anchor") is not None
        and producer.get("observer") is None,
        "CACHE_RECORD_PRODUCER_INVALID",
        "V13 producer summary changed",
    )
    index_bytes = _regular_bytes(
        cache_root / "index.json",
        maximum_bytes=2_097_152,
        failure_code="CACHE_RECORD_INDEX_INVALID",
        label="OCI cache index",
    )
    index = _strict_json_bytes(index_bytes, "OCI cache index")
    descriptors = index.get("manifests") if isinstance(index, dict) else None
    _require(
        isinstance(descriptors, list) and len(descriptors) == 1,
        "CACHE_RECORD_INDEX_INVALID",
        "OCI cache root manifest count changed",
    )
    root_bytes = _bounded_descriptor_bytes(
        cache_root,
        descriptors[0],
        maximum_bytes=MAXIMUM_CACHE_CONFIG_BYTES,
        failure_code="CACHE_RECORD_INDEX_INVALID",
        label="OCI cache manifest",
    )
    _require(
        hashlib.sha256(root_bytes).hexdigest()
        == descriptors[0]["digest"].removeprefix("sha256:")
        and len(root_bytes) == descriptors[0]["size"],
        "CACHE_RECORD_INDEX_INVALID",
        "OCI cache manifest changed after descriptor validation",
    )
    root = _strict_json_bytes(root_bytes, "OCI cache manifest")
    config_descriptor = root.get("config") if isinstance(root, dict) else None
    _require(
        isinstance(config_descriptor, dict)
        and config_descriptor.get("mediaType")
        == "application/vnd.buildkit.cacheconfig.v0",
        "CACHE_RECORD_CONFIG_INVALID",
        "BuildKit cache config descriptor changed",
    )
    config_bytes = _bounded_descriptor_bytes(
        cache_root,
        config_descriptor,
        maximum_bytes=MAXIMUM_CACHE_CONFIG_BYTES,
        failure_code="CACHE_RECORD_CONFIG_INVALID",
        label="BuildKit cache config",
    )
    config_sha256 = hashlib.sha256(config_bytes).hexdigest()
    _require(
        0 < len(config_bytes) <= MAXIMUM_CACHE_CONFIG_BYTES
        and config_sha256
        == config_descriptor["digest"].removeprefix("sha256:")
        and len(config_bytes) == config_descriptor["size"],
        "CACHE_RECORD_CONFIG_INVALID",
        "BuildKit cache config changed after descriptor validation",
    )
    config = _strict_json_bytes(config_bytes, "BuildKit cache config")
    root_layers = root.get("layers")
    diagnostic = _cache_structure_diagnostic(
        config=config,
        root_layers=root_layers,
        config_sha256=config_sha256,
        config_bytes=len(config_bytes),
        producer_summary_sha256=producer_summary_sha256,
    )
    _require(
        isinstance(root_layers, list) and bool(root_layers),
        "CACHE_RECORD_CONFIG_INVALID",
        "BuildKit cache layer inventory missing",
    )
    _preflight_cache_structure(config, diagnostic)
    try:
        _base.validate_cache_config(config, root_layers)
    except RecursionError:
        _fail(
            "CACHE_RECORD_GRAPH_DEPTH_INVALID",
            "BuildKit cache record graph exceeded verifier depth",
        )
    records = config["records"]
    _require(
        diagnostic["result_bearing_record_count"] > 0
        and diagnostic["layer_result_count"]
        + diagnostic["chained_result_count"]
        > 0
        and diagnostic["link_count"] > 0,
        "CACHE_RECORD_STRUCTURE_EMPTY",
        "BuildKit cache structural result or link inventory missing",
    )
    diagnostic["structural_validation_completed"] = True
    summary = {
        "schema_version": "noteai.admin-dependency-cache-record.v13",
        "producer_summary_sha256": producer_summary_sha256,
        "cache_config_sha256": diagnostic["cache_config_sha256"],
        "cache_config_bytes": diagnostic["cache_config_bytes"],
        "root_layer_descriptor_count": diagnostic[
            "root_layer_descriptor_count"
        ],
        "layer_count": diagnostic["layer_count"],
        "record_count": diagnostic["record_count"],
        "result_bearing_record_count": diagnostic[
            "result_bearing_record_count"
        ],
        "layer_result_count": diagnostic["layer_result_count"],
        "chained_result_count": diagnostic["chained_result_count"],
        "input_group_count": diagnostic["input_group_count"],
        "link_count": diagnostic["link_count"],
        "structural_validation": dict(CACHE_RECORD_STRUCTURAL_VALIDATION),
    }
    return _validate_cache_record_summary(
        summary,
        expected_producer_summary_sha256=producer_summary_sha256,
    )


def classify_pair(
    producer_summary: dict[str, Any],
    consumer_summary: dict[str, Any],
) -> dict[str, Any]:
    def runtime_pip(summary: dict[str, Any], label: str) -> dict[str, Any]:
        roles = [
            item
            for item in summary.get("network_vertices", [])
            if isinstance(item, dict) and item.get("role") == "runtime_pip"
        ]
        _require(
            len(roles) == 1,
            "V11_PAIR_ROLE_INVALID",
            f"{label} runtime_pip binding changed",
        )
        role = roles[0]
        digest = role.get("vertex_digest")
        count_keys = (
            "interval_count",
            "completed_interval_count",
            "cached_interval_count",
            "noncached_interval_count",
        )
        _require(
            isinstance(digest, str)
            and DIGEST_RE.fullmatch(digest) is not None
            and all(
                isinstance(role.get(key), int)
                and not isinstance(role.get(key), bool)
                for key in count_keys
            )
            and role["interval_count"] > 0
            and role["completed_interval_count"] == role["interval_count"]
            and role["cached_interval_count"] >= 0
            and role["noncached_interval_count"] >= 0
            and role["cached_interval_count"]
            + role["noncached_interval_count"]
            == role["interval_count"],
            "V13_PAIR_ROLE_INVALID",
            f"{label} runtime_pip interval changed",
        )
        return role

    _require(
        producer_summary.get("target") == EXPORT_TARGET
        and consumer_summary.get("target") == IMPORT_TARGET,
        "V11_PAIR_TARGET_INVALID",
        "V11 producer or consumer target changed",
    )
    producer_pip = runtime_pip(producer_summary, "producer")
    consumer_pip = runtime_pip(consumer_summary, "consumer")
    producer_digest = producer_pip["vertex_digest"]
    consumer_digest = consumer_pip["vertex_digest"]
    consumer_cached = (
        consumer_pip["cached_interval_count"]
        == consumer_pip["interval_count"]
        and consumer_pip["noncached_interval_count"] == 0
    )
    if producer_digest != consumer_digest:
        classification = "DIGEST_DRIFT"
    elif consumer_cached:
        classification = "SAME_DIGEST_CACHED"
    else:
        classification = "SAME_DIGEST_NONCACHED"
    return {
        "schema_version": "noteai.admin-dependency-cache-pair.v11",
        "producer_runtime_pip_digest": producer_digest,
        "consumer_runtime_pip_digest": consumer_digest,
        "consumer_runtime_pip_cached": consumer_cached,
        "classification": classification,
        "historical_v10_root_cause_status": "UNKNOWN_NOT_RETAINED",
        "v11_boundary_status": "DETERMINED_BY_V11",
    }


def validate_pair(
    producer_summary_path: Path,
    consumer_summary_path: Path,
) -> dict[str, Any]:
    producer, producer_sha256 = _read_summary_with_sha256(
        producer_summary_path,
        label="V11 producer summary",
    )
    consumer, consumer_sha256 = _read_summary_with_sha256(
        consumer_summary_path,
        label="V11 consumer summary",
    )
    pair = classify_pair(producer, consumer)
    diagnostic = {
        **pair,
        "producer_summary_sha256": producer_sha256,
        "consumer_summary_sha256": consumer_sha256,
    }
    print(
        "noteai_v11_pair_diagnostic="
        + json.dumps(
            diagnostic,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        file=sys.stderr,
    )
    _require(
        pair["classification"] == "SAME_DIGEST_CACHED",
        "V13_PAIR_CACHE_PREDICATE_FAILED",
        "V13 producer/consumer runtime_pip pair did not prove a cache hit",
    )
    return pair


def _require_sha256(value: Any, label: str) -> None:
    _require(
        isinstance(value, str) and SHA256_RE.fullmatch(value) is not None,
        "V11_MANIFEST_INVALID",
        f"{label} is invalid",
    )


def _require_exact_dict(
    value: Any,
    keys: set[str],
    label: str,
    *,
    failure_code: str = "V11_MANIFEST_INVALID",
) -> dict[str, Any]:
    _require(
        isinstance(value, dict) and set(value) == keys,
        failure_code,
        f"{label} keys changed",
    )
    return value


def _require_positive_int(value: Any, label: str) -> None:
    _require(
        isinstance(value, int) and not isinstance(value, bool) and value > 0,
        "V11_MANIFEST_INVALID",
        f"{label} is invalid",
    )


def validate_manifest(bundle: Path) -> dict[str, Any]:
    manifest = _base.strict_json_file(bundle / "manifest.json")
    _require_exact_dict(
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
        "V11 manifest",
    )
    _require(
        manifest["schema_version"]
        == "noteai.admin-dependency-cache-export.v11"
        and manifest["task"] == "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001",
        "V11_MANIFEST_INVALID",
        "V11 manifest identity changed",
    )
    release = _require_exact_dict(
        manifest["release"],
        {
            "commit",
            "tree",
            "dockerfile_sha256",
            "dependency_prefix_lines",
            "first_application_copy_line",
            "dependency_prefix_sha256",
            "combined_dockerfile_sha256",
            "combined_dockerfile_lines",
            "minimal_context_files",
        },
        "manifest.release",
    )
    _require(
        release["commit"] == _base.RELEASE_COMMIT
        and release["tree"] == _base.RELEASE_TREE
        and release["dockerfile_sha256"] == FULL_DOCKERFILE_SHA256
        and release["dependency_prefix_lines"] == [1, 80]
        and release["first_application_copy_line"] == 83
        and release["dependency_prefix_sha256"] == BASE_PREFIX_SHA256
        and release["combined_dockerfile_sha256"]
        == COMBINED_DOCKERFILE_SHA256
        and release["combined_dockerfile_lines"]
        == COMBINED_DOCKERFILE_LINES,
        "V11_MANIFEST_INVALID",
        "V11 release binding changed",
    )
    minimal = release["minimal_context_files"]
    _require(
        minimal
        == [
            {
                "path": ".dockerignore",
                "sha256": _base.DOCKERIGNORE_SHA256,
            },
            {
                "path": "Dockerfile",
                "sha256": COMBINED_DOCKERFILE_SHA256,
            },
            {
                "path": "model/requirements-api.txt",
                "sha256": _base.REQUIREMENTS_API_SHA256,
            },
            {
                "path": "model/requirements.txt",
                "sha256": _base.REQUIREMENTS_SHA256,
            },
        ],
        "V11_MANIFEST_INVALID",
        "V11 minimal context binding changed",
    )
    build = _require_exact_dict(
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
    _require(
        build["runner_architecture"] == "x86_64"
        and build["platform"] == "linux/amd64"
        and build["target"] == EXPORT_TARGET
        and build["pull"] is True
        and build["output"] == "cacheonly"
        and build["cache_export"]
        == "type=local,mode=max,oci-mediatypes=true"
        and build["docker_engine_image_export_requested"] is False
        and build["registry_export_requested"] is False
        and build["transient_buildkit_sandboxes_expected"] is True
        and build["buildkit_driver"] == "docker-container",
        "V11_MANIFEST_INVALID",
        "V11 build contract changed",
    )
    _require(
        isinstance(build["buildx_client_version"], str)
        and bool(build["buildx_client_version"])
        and isinstance(build["buildkit_version"], str)
        and bool(build["buildkit_version"])
        and isinstance(build["buildkit_daemon_image_reference"], str)
        and re.fullmatch(
            r"(?:docker\.io/)?moby/buildkit@sha256:[0-9a-f]{64}",
            build["buildkit_daemon_image_reference"],
        )
        is not None
        and isinstance(build["buildkit_daemon_image_id"], str)
        and DIGEST_RE.fullmatch(build["buildkit_daemon_image_id"])
        is not None
        and isinstance(build["duration_seconds"], (int, float))
        and not isinstance(build["duration_seconds"], bool)
        and 0 <= build["duration_seconds"] <= 7_200
        and build["base_images"]
        == {
            "python": {
                "index": f"sha256:{_base.PYTHON_INDEX}",
                "linux_amd64": f"sha256:{_base.PYTHON_AMD64}",
            },
            "node": {
                "index": f"sha256:{_base.NODE_INDEX}",
                "linux_amd64": f"sha256:{_base.NODE_AMD64}",
            },
        },
        "V11_MANIFEST_INVALID",
        "V11 BuildKit identity changed",
    )
    for key in ("metadata_sha256", "progress_sha256"):
        _require_sha256(build[key], f"manifest.build.{key}")
    producer_summary = validate_build_evidence(
        bundle / "cache-build-metadata.json",
        bundle / "producer-build.rawjson",
        dockerfile_kind="prefix",
        require_network_vertices_cached=False,
    )
    retained_producer = _read_summary(
        bundle / "producer" / "cache-build-summary.json",
        label="V11 producer summary",
    )
    _require(
        producer_summary == retained_producer
        and producer_summary["metadata_sha256"] == build["metadata_sha256"]
        and producer_summary["progress_sha256"] == build["progress_sha256"]
        and producer_summary["duration_seconds"] == build["duration_seconds"],
        "V11_MANIFEST_INVALID",
        "V11 producer evidence binding changed",
    )
    cache = _require_exact_dict(
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
            "record_path",
            "record_provenance",
        },
        "manifest.cache",
    )
    _require(
        cache["type"] == "buildkit-local-oci-layout"
        and cache["mode"] == "max"
        and cache["compression"] == "gzip"
        and cache["compression_level"] == 1
        and cache["record_path"] == "producer/cache-record.json"
        and isinstance(cache["record_provenance"], dict)
        and isinstance(cache["manifest_digest"], str)
        and DIGEST_RE.fullmatch(cache["manifest_digest"]) is not None,
        "V11_MANIFEST_INVALID",
        "V11 cache record contract changed",
    )
    for key in (
        "cache_index_sha256",
        "oci_layout_sha256",
    ):
        _require_sha256(cache[key], f"manifest.cache.{key}")
    _require_positive_int(cache["blob_count"], "manifest.cache.blob_count")
    _require_positive_int(cache["blob_bytes"], "manifest.cache.blob_bytes")
    _require(
        cache["blob_bytes"] <= _base.MAXIMUM_BLOB_BYTES
        and isinstance(cache["blobs"], list)
        and len(cache["blobs"]) == cache["blob_count"]
        and len({item.get("name") for item in cache["blobs"]})
        == cache["blob_count"]
        and all(
            isinstance(item, dict)
            and set(item) == {"name", "sha256", "bytes"}
            and isinstance(item["name"], str)
            and SHA256_RE.fullmatch(item["name"]) is not None
            and item["sha256"] == item["name"]
            and isinstance(item["bytes"], int)
            and not isinstance(item["bytes"], bool)
            and item["bytes"] > 0
            for item in cache["blobs"]
        ),
        "V11_MANIFEST_INVALID",
        "V11 cache inventory changed",
    )
    archive = _require_exact_dict(
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
    _require_sha256(archive["raw_tar_sha256"], "raw archive hash")
    _require_sha256(archive["gzip_sha256"], "gzip archive hash")
    _require_positive_int(archive["raw_tar_bytes"], "raw archive bytes")
    _require_positive_int(archive["gzip_bytes"], "gzip archive bytes")
    _require_positive_int(archive["chunk_count"], "chunk count")
    _require(
        archive["format"] == "deterministic-tar-gzip"
        and archive["raw_tar_bytes"] <= _base.MAXIMUM_RAW_TAR_BYTES
        and archive["gzip_bytes"] <= _base.MAXIMUM_GZIP_BYTES
        and archive["raw_tar_bytes"] <= archive["gzip_bytes"] * 8
        and archive["chunk_bytes_limit"] == _base.CHUNK_BYTES
        and archive["chunk_count"] <= _base.MAXIMUM_CHUNK_COUNT
        and isinstance(archive["chunks"], list)
        and len(archive["chunks"]) == archive["chunk_count"]
        and archive["maximum_gzip_bytes"] == _base.MAXIMUM_GZIP_BYTES
        and archive["maximum_extracted_cache_bytes"]
        == _base.MAXIMUM_EXTRACTED_CACHE_BYTES
        and archive["artifact_input_maximum_bytes"]
        == _base.MAXIMUM_ARTIFACT_INPUT_BYTES
        and archive["artifact_provider_maximum_bytes"]
        == _base.MAXIMUM_PROVIDER_ARTIFACT_BYTES
        and archive["non_chunk_file_maximum_bytes"]
        == _base.MAXIMUM_NON_CHUNK_FILE_BYTES,
        "V11_MANIFEST_INVALID",
        "V11 archive contract changed",
    )
    expected_chunks = [
        f"chunks/admin-dependency-cache.tar.gz.part-{index:04d}"
        for index in range(archive["chunk_count"])
    ]
    _require(
        [item.get("name") for item in archive["chunks"]] == expected_chunks
        and all(
            isinstance(item, dict)
            and set(item) == {"name", "sha256", "bytes"}
            and SHA256_RE.fullmatch(item.get("sha256", "")) is not None
            and isinstance(item.get("bytes"), int)
            and not isinstance(item.get("bytes"), bool)
            and 0 < item["bytes"] <= _base.CHUNK_BYTES
            and (
                index == archive["chunk_count"] - 1
                or item["bytes"] == _base.CHUNK_BYTES
            )
            for index, item in enumerate(archive["chunks"])
        ),
        "V11_MANIFEST_INVALID",
        "V11 chunk inventory changed",
    )
    control = _require_exact_dict(
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
    _require(
        all(
            isinstance(control[key], str)
            and re.fullmatch(r"[0-9a-f]{40}", control[key]) is not None
            for key in ("plan_checkpoint_commit", "control_commit")
        )
        and isinstance(control["github_run_id"], str)
        and control["github_run_id"].isdigit()
        and int(control["github_run_id"]) > 0
        and control["github_run_attempt"] == 1
        and control["artifact_retention_days"] == 1
        and control["registry_digest"] is None
        and all(
            control[field] is False
            for field in (
                "application_or_model_source_inputs_supplied_to_export",
                "buildkit_credential_or_secret_inputs_supplied",
                "registry_publication_authorized",
                "deployment_authorized",
                "database_authorized",
                "service_mutation_authorized",
                "public_traffic_authorized",
            )
        ),
        "V11_MANIFEST_INVALID",
        "V11 bounded authorization changed",
    )
    for key in (
        "request_sha256",
        "workflow_sha256",
        "export_helper_sha256",
        "import_helper_sha256",
        "bundle_verifier_sha256",
    ):
        _require_sha256(control[key], f"manifest.control.{key}")
    _require(
        _base.sha256_file(
            bundle / "producer" / "export_admin_dependency_cache.sh"
        )
        == control["export_helper_sha256"]
        and _base.sha256_file(
            bundle / "builder" / "import_admin_dependency_cache.sh"
        )
        == control["import_helper_sha256"]
        and _base.sha256_file(
            bundle / "builder" / "verify_admin_dependency_cache_bundle.py"
        )
        == control["bundle_verifier_sha256"],
        "V11_MANIFEST_INVALID",
        "V11 bundled execution authority changed",
    )
    _require(
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
        "V11_MANIFEST_INVALID",
        "V11 next gate changed",
    )
    _base.validate_base_index(
        bundle / "python-base-index.json",
        _base.PYTHON_INDEX,
        _base.PYTHON_AMD64,
    )
    _base.validate_base_index(
        bundle / "node-base-index.json",
        _base.NODE_INDEX,
        _base.NODE_AMD64,
    )
    return manifest


def validate_core(
    bundle: Path,
    extract_to: Path,
    *,
    validation_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bundle = Path(bundle)
    extract_to = Path(extract_to)
    _require(bundle.is_dir(), "V11_BUNDLE_INVALID", "bundle directory missing")
    files = _base.relative_regular_files(bundle)
    _base.validate_bundle_size(bundle, files)
    final_additions = {
        "portability/import-build-metadata.json",
        "portability/import-build.rawjson",
        "portability/import-pre-predicate-diagnostic.json",
        "portability/import-diagnostic.json",
        "portability/import-summary.json",
        "portability/pair.json",
        "portability/replay-build-metadata.json",
        "portability/replay-build.rawjson",
        "portability/replay-summary.json",
        "portability/proof.json",
        "SHA256SUMS",
    }
    present_final = files & final_additions
    _require(
        not present_final or present_final == final_additions,
        "V11_BUNDLE_INVALID",
        "partial V11 portability evidence present",
    )
    core_scope = files - final_additions
    core_files = core_scope - {"CORE_SHA256SUMS"}
    manifest = validate_manifest(bundle)
    expected_core = {
        "manifest.json",
        "cache-build-metadata.json",
        "producer-build.rawjson",
        "python-base-index.json",
        "node-base-index.json",
        "cache-index.json",
        "oci-layout",
        "producer/export_admin_dependency_cache.sh",
        "producer/cache-build-summary.json",
        "producer/cache-record.json",
        "builder/import_admin_dependency_cache.sh",
        "builder/verify_admin_dependency_cache_bundle.py",
        *{item["name"] for item in manifest["archive"]["chunks"]},
    }
    _require(
        core_files == expected_core,
        "V11_BUNDLE_INVALID",
        "V11 core bundle file set changed",
    )
    _base.validate_checksum_file(
        bundle,
        "CORE_SHA256SUMS",
        core_files,
    )
    work = extract_to.parent / f".{extract_to.name}-archive-work"
    _require(
        not work.exists(),
        "V11_BUNDLE_INVALID",
        "archive work directory already exists",
    )
    work.mkdir(mode=0o700)
    gzip_path = work / "cache.tar.gz"
    raw_tar = work / "cache.tar"
    try:
        _base.validate_chunks(bundle, manifest, gzip_path)
        _base.bounded_decompress(
            gzip_path,
            raw_tar,
            manifest["archive"]["raw_tar_bytes"],
        )
        _require(
            _base.sha256_file(raw_tar)
            == manifest["archive"]["raw_tar_sha256"],
            "V11_ARCHIVE_INVALID",
            "raw archive hash changed",
        )
        _base.safe_extract_tar(
            raw_tar,
            extract_to,
            manifest["archive"]["raw_tar_bytes"],
        )
        _base.validate_oci_cache(extract_to, manifest)
        observed_record = validate_cache_record(
            extract_to,
            bundle / "producer" / "cache-build-summary.json",
        )
        retained_record_path = bundle / manifest["cache"]["record_path"]
        retained_record_bytes = _regular_bytes(
            retained_record_path,
            maximum_bytes=2_097_152,
            failure_code="V11_SUMMARY_FILE_INVALID",
            label="V13 cache record",
        )
        retained_record = _strict_json_bytes(
            retained_record_bytes,
            "V13 cache record",
        )
        _require(
            isinstance(retained_record, dict),
            "V11_SUMMARY_INVALID",
            "V13 cache record root changed",
        )
        _require(
            observed_record == retained_record
            and retained_record == manifest["cache"]["record_provenance"],
            "CACHE_RECORD_BINDING_INVALID",
            "V11 cache record provenance changed",
        )
        if validation_context is not None:
            _require(
                validation_context == {},
                "V13_CACHE_RECORD_TRUST_INVALID",
                "V13 core validation context was not empty",
            )
            validation_context["validated_cache_record_sha256"] = (
                hashlib.sha256(retained_record_bytes).hexdigest()
            )
    finally:
        import shutil

        shutil.rmtree(work, ignore_errors=True)
    return manifest


def validate_portability(
    bundle: Path,
    manifest: dict[str, Any],
    *,
    expected_cache_record_sha256: str,
) -> dict[str, Any]:
    portability = bundle / "portability"
    producer = _read_summary(
        bundle / "producer" / "cache-build-summary.json",
        label="V11 producer summary",
    )
    import_summary = validate_build_evidence(
        portability / "import-build-metadata.json",
        portability / "import-build.rawjson",
        dockerfile_kind="prefix",
        require_network_vertices_cached=True,
        producer_summary_path=(
            bundle / "producer" / "cache-build-summary.json"
        ),
        cache_record_path=bundle / "producer" / "cache-record.json",
        expected_cache_record_sha256=expected_cache_record_sha256,
    )
    replay_summary = validate_build_evidence(
        portability / "replay-build-metadata.json",
        portability / "replay-build.rawjson",
        dockerfile_kind="full",
        require_network_vertices_cached=True,
    )
    retained_import = _read_summary(
        portability / "import-summary.json",
        label="V11 retained import summary",
    )
    retained_replay = _read_summary(
        portability / "replay-summary.json",
        label="V11 retained replay summary",
    )
    retained_diagnostic = _read_summary(
        portability / "import-diagnostic.json",
        label="V11 retained import diagnostic",
    )
    retained_pre_predicate = _read_summary(
        portability / "import-pre-predicate-diagnostic.json",
        label="V11 retained pre-predicate diagnostic",
    )
    pair = validate_pair(
        bundle / "producer" / "cache-build-summary.json",
        portability / "import-summary.json",
    )
    retained_pair = _read_summary(
        portability / "pair.json",
        label="V11 retained pair",
    )
    proof = _read_summary(
        portability / "proof.json",
        label="V11 portability proof",
    )
    _require(
        retained_import == import_summary
        and retained_replay == replay_summary
        and retained_pair == pair,
        "V11_PORTABILITY_BINDING_INVALID",
        "V11 retained portability summaries changed",
    )
    _require(
        retained_diagnostic == import_summary["v11_rawjson_diagnostic"],
        "V11_PORTABILITY_BINDING_INVALID",
        "V11 retained import diagnostic changed",
    )
    _validate_pre_predicate_diagnostic(
        retained_pre_predicate,
        retained_diagnostic,
    )
    _require(
        set(proof)
        == {
            "schema_version",
            "task",
            "release_commit",
            "manifest_sha256",
            "core_sums_sha256",
            "producer",
            "consumer",
            "pair",
            "cache_record",
            "pre_predicate_diagnostic",
            "import_diagnostic",
            "import",
            "cacheless_replay",
            "controls",
        },
        "V11_PORTABILITY_INVALID",
        "V11 portability proof keys changed",
    )
    _require(
        proof.get("schema_version")
        == "noteai.admin-dependency-cache-portability.v11"
        and proof.get("task") == "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001"
        and proof.get("release_commit")
        == "5335bdaed933b1f999b5f819c047ec50c11821ae"
        and proof.get("manifest_sha256")
        == _base.sha256_file(bundle / "manifest.json")
        and proof.get("core_sums_sha256")
        == _base.sha256_file(bundle / "CORE_SHA256SUMS")
        and proof.get("pair") == pair
        and proof.get("cache_record")
        == manifest["cache"]["record_provenance"],
        "V11_PORTABILITY_INVALID",
        "V11 portability proof changed",
    )
    _require(
        proof.get("pre_predicate_diagnostic")
        == retained_pre_predicate
        and proof.get("import_diagnostic") == retained_diagnostic,
        "V11_PORTABILITY_INVALID",
        "V11 portability diagnostic binding changed",
    )
    producer_identity = _require_exact_dict(
        proof.get("producer"),
        {
            "builder_name",
            "driver",
            "buildkit_version",
            "buildkit_daemon_image_reference",
            "buildkit_daemon_image_id",
        },
        "portability producer",
        failure_code="V11_PORTABILITY_INVALID",
    )
    consumer_identity = _require_exact_dict(
        proof.get("consumer"),
        {
            "builder_name",
            "driver",
            "buildkit_version",
            "buildkit_daemon_image_reference",
            "buildkit_daemon_image_id",
        },
        "portability consumer",
        failure_code="V11_PORTABILITY_INVALID",
    )
    _require(
        isinstance(producer_identity["builder_name"], str)
        and bool(producer_identity["builder_name"])
        and isinstance(consumer_identity["builder_name"], str)
        and bool(consumer_identity["builder_name"])
        and producer_identity["builder_name"]
        != consumer_identity["builder_name"]
        and producer_identity["driver"]
        == consumer_identity["driver"]
        == "docker-container"
        and producer_identity["buildkit_version"]
        == consumer_identity["buildkit_version"]
        == manifest["build"]["buildkit_version"]
        and producer_identity["buildkit_daemon_image_reference"]
        == consumer_identity["buildkit_daemon_image_reference"]
        == manifest["build"]["buildkit_daemon_image_reference"]
        and producer_identity["buildkit_daemon_image_id"]
        == consumer_identity["buildkit_daemon_image_id"]
        == manifest["build"]["buildkit_daemon_image_id"],
        "V11_PORTABILITY_INVALID",
        "V11 producer/consumer BuildKit identity changed",
    )
    _require(
        proof.get("import")
        == import_summary | {"cache_from_local": True}
        and proof.get("cacheless_replay")
        == replay_summary
        | {
            "cache_from_local": False,
            "external_cache_removed_before_replay": True,
            "full_release_context_used": True,
        },
        "V11_PORTABILITY_INVALID",
        "V11 import or cacheless replay proof changed",
    )
    controls = proof.get("controls")
    _require(
        controls
        == {
            "github_run_attempt": 1,
            "image_or_registry_output_requested": False,
            "dependency_prefix_application_or_model_source_inputs_supplied": False,
            "full_replay_release_context_used": True,
            "buildkit_credential_or_secret_inputs_supplied": False,
            "upload_allowed_only_after_cleanup": True,
        },
        "V11_PORTABILITY_INVALID",
        "V11 portability controls changed",
    )
    return proof


def validate_final(
    bundle: Path,
    extract_to: Path,
    expected_sums_sha256: str | None,
) -> dict[str, Any]:
    bundle = Path(bundle)
    files = _base.relative_regular_files(bundle)
    artifact_input_bytes = _base.validate_bundle_size(bundle, files)
    expected_additions = {
        "portability/import-build-metadata.json",
        "portability/import-build.rawjson",
        "portability/import-pre-predicate-diagnostic.json",
        "portability/import-diagnostic.json",
        "portability/import-summary.json",
        "portability/pair.json",
        "portability/replay-build-metadata.json",
        "portability/replay-build.rawjson",
        "portability/replay-summary.json",
        "portability/proof.json",
        "SHA256SUMS",
    }
    _require(
        expected_additions <= files,
        "V11_BUNDLE_INVALID",
        "V11 portability evidence missing",
    )
    sums_sha256 = _base.validate_checksum_file(
        bundle,
        "SHA256SUMS",
        files - {"SHA256SUMS"},
    )
    if expected_sums_sha256 is not None:
        _require_sha256(expected_sums_sha256, "expected final sums hash")
        _require(
            sums_sha256 == expected_sums_sha256,
            "V11_FINAL_SUMS_INVALID",
            "final sums trust root changed",
        )
    validation_context: dict[str, Any] = {}
    manifest = validate_core(
        bundle,
        Path(extract_to),
        validation_context=validation_context,
    )
    validated_cache_record_sha256 = validation_context.get(
        "validated_cache_record_sha256"
    )
    _require(
        isinstance(validated_cache_record_sha256, str)
        and SHA256_RE.fullmatch(validated_cache_record_sha256) is not None,
        "V13_CACHE_RECORD_TRUST_INVALID",
        "V13 core validation did not capture the cache record",
    )
    proof = validate_portability(
        bundle,
        manifest,
        expected_cache_record_sha256=validated_cache_record_sha256,
    )
    return {
        "manifest_sha256": _base.sha256_file(bundle / "manifest.json"),
        "core_sums_sha256": _base.sha256_file(bundle / "CORE_SHA256SUMS"),
        "final_sums_sha256": sums_sha256,
        "portability_proof_sha256": _base.sha256_file(
            bundle / "portability" / "proof.json"
        ),
        "validated_cache_record_sha256": validated_cache_record_sha256,
        "control_commit": manifest["control"]["control_commit"],
        "request_sha256": manifest["control"]["request_sha256"],
        "github_run_id": manifest["control"]["github_run_id"],
        "github_run_attempt": manifest["control"]["github_run_attempt"],
        "producer_buildkit_version": manifest["build"]["buildkit_version"],
        "consumer_buildkit_version": proof["consumer"]["buildkit_version"],
        "pair_classification": proof["pair"]["classification"],
        "artifact_input_bytes": artifact_input_bytes,
        "artifact_input_maximum_bytes": _base.MAXIMUM_ARTIFACT_INPUT_BYTES,
        "artifact_provider_maximum_bytes": _base.MAXIMUM_PROVIDER_ARTIFACT_BYTES,
    }


def _write_json(path: Path | None, payload: dict[str, Any]) -> None:
    try:
        _base.write_json(Path(path).resolve() if path else None, payload)
    except _v10._v6._v3.BundleError as exc:
        _fail(
            getattr(exc, "failure_code", "V11_OUTPUT_INVALID"),
            "V11 output write failed",
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("verify-build")
    build.add_argument("--metadata", type=Path, required=True)
    build.add_argument("--progress", type=Path, required=True)
    build.add_argument("--dockerfile", choices=("prefix", "full"), required=True)
    build.add_argument("--require-network-cached", action="store_true")
    build.add_argument("--producer-summary", type=Path)
    build.add_argument("--cache-record", type=Path)
    build.add_argument("--expected-cache-record-sha256")
    build.add_argument("--pre-predicate-diagnostic-output", type=Path)
    build.add_argument("--diagnostic-output", type=Path)
    build.add_argument("--pair-output", type=Path)
    build.add_argument("--output", type=Path)
    record = subparsers.add_parser("verify-cache-record")
    record.add_argument("--cache-dir", type=Path, required=True)
    record.add_argument("--producer-summary", type=Path, required=True)
    record.add_argument("--output", type=Path)
    pair = subparsers.add_parser("verify-pair")
    pair.add_argument("--producer-summary", type=Path, required=True)
    pair.add_argument("--consumer-summary", type=Path, required=True)
    pair.add_argument("--output", type=Path)
    core = subparsers.add_parser("verify-core")
    core.add_argument("--bundle", type=Path, required=True)
    core.add_argument("--extract-to", type=Path, required=True)
    core.add_argument("--output", type=Path)
    final = subparsers.add_parser("verify-final")
    final.add_argument("--bundle", type=Path, required=True)
    final.add_argument("--extract-to", type=Path, required=True)
    final.add_argument("--expected-sums-sha256")
    final.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "verify-build":
            payload = validate_build_evidence(
                args.metadata.resolve(),
                args.progress.resolve(),
                dockerfile_kind=args.dockerfile,
                require_network_vertices_cached=args.require_network_cached,
                producer_summary_path=(
                    args.producer_summary.resolve()
                    if args.producer_summary
                    else None
                ),
                cache_record_path=(
                    args.cache_record.resolve()
                    if args.cache_record
                    else None
                ),
                expected_cache_record_sha256=(
                    args.expected_cache_record_sha256
                    if args.expected_cache_record_sha256
                    else None
                ),
                pre_predicate_diagnostic_output_path=(
                    args.pre_predicate_diagnostic_output.resolve()
                    if args.pre_predicate_diagnostic_output
                    else None
                ),
                diagnostic_output_path=(
                    args.diagnostic_output.resolve()
                    if args.diagnostic_output
                    else None
                ),
                pair_output_path=(
                    args.pair_output.resolve()
                    if args.pair_output
                    else None
                ),
            )
        elif args.command == "verify-cache-record":
            payload = validate_cache_record(
                args.cache_dir.resolve(),
                args.producer_summary.resolve(),
            )
        elif args.command == "verify-pair":
            payload = validate_pair(
                args.producer_summary.resolve(),
                args.consumer_summary.resolve(),
            )
        elif args.command == "verify-core":
            validation_context: dict[str, Any] = {}
            manifest = validate_core(
                args.bundle.resolve(),
                args.extract_to.resolve(),
                validation_context=validation_context,
            )
            validated_cache_record_sha256 = validation_context.get(
                "validated_cache_record_sha256"
            )
            _require(
                isinstance(validated_cache_record_sha256, str)
                and SHA256_RE.fullmatch(validated_cache_record_sha256)
                is not None,
                "V13_CACHE_RECORD_TRUST_INVALID",
                "V13 core validation did not capture the cache record",
            )
            payload = {
                "manifest_sha256": _base.sha256_file(
                    args.bundle / "manifest.json"
                ),
                "core_sums_sha256": _base.sha256_file(
                    args.bundle / "CORE_SHA256SUMS"
                ),
                "control_commit": manifest["control"]["control_commit"],
                "validated_cache_record_sha256": (
                    validated_cache_record_sha256
                ),
            }
        else:
            payload = validate_final(
                args.bundle.resolve(),
                args.extract_to.resolve(),
                args.expected_sums_sha256,
            )
        _write_json(args.output, payload)
    except (
        V11BundleError,
        _v10.V10BundleError,
        _v10._v6._v3.BundleError,
        OSError,
    ) as exc:
        print(f"FAIL: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
