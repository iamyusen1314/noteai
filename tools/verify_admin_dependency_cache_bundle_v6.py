#!/usr/bin/env python3
"""Verify V6 BuildKit evidence without weakening the frozen V3/V2 bundle.

Buildx rawjson is a stream of nested ``client.SolveStatus`` objects. V6
validates that original stream, binds the three dependency RUN operations
through max-provenance digest mappings and source locations, and scans
strictly decoded log bytes. Only after those checks pass does it construct a
private legacy progress view for the hash-pinned V3/V2 verifier.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import threading
import types
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator


V2_VERIFIER_SHA256 = (
    "bf526c29b213dc15d257cb9aedc52790"
    "aa1dc9cf1f82bba0e6e85e41db3edf38"
)
V3_VERIFIER_SHA256 = (
    "c2e318d5d9cbe196d8b9294277c85e1e"
    "e986ccb3e1970b3d25a31d28c8da0fef"
)
MAXIMUM_PROGRESS_BYTES = 268_435_456
MAXIMUM_METADATA_BYTES = 134_217_728
MAXIMUM_PROGRESS_LINES = 1_000_000
MAXIMUM_DECODED_LOG_BYTES = 134_217_728
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
STEP_RE = re.compile(r"^step(?:0|[1-9][0-9]*)$")
RFC3339_RE = re.compile(
    r"^[0-9]{4}-(?:0[1-9]|1[0-2])-"
    r"(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    r"(?:\.[0-9]{1,9})?"
    r"(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])$"
)
PACKAGE_NETWORK_BYTES_RE = re.compile(
    rb"(Downloading |Collecting |Get:\d+ https?://|"
    rb"registry\.npmjs\.org|pypi\.org|deb\.debian\.org)",
    re.IGNORECASE,
)
TOP_LEVEL_KEYS = {"vertexes", "statuses", "logs", "warnings"}
VERTEX_KEYS = {
    "digest",
    "inputs",
    "name",
    "started",
    "completed",
    "cached",
    "error",
    "progressGroup",
}
STATUS_KEYS = {
    "id",
    "vertex",
    "name",
    "total",
    "current",
    "timestamp",
    "started",
    "completed",
}
LOG_KEYS = {"vertex", "stream", "data", "timestamp"}
WARNING_KEYS = {
    "vertex",
    "level",
    "short",
    "detail",
    "url",
    "sourceInfo",
    "range",
}
ROLE_SPECS = (
    {
        "role": "meituan_npm_pack",
        "line": 14,
        "marker": 'npm pack "@meituan-travel/travel-cli@',
    },
    {
        "role": "runtime_apt",
        "line": 63,
        "marker": "apt-get update && apt-get install",
    },
    {
        "role": "runtime_pip",
        "line": 76,
        "marker": "pip install --no-cache-dir",
    },
)


def _read_frozen_source(path: Path, *, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError(f"{label} is missing") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= 4_194_304
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
            if observed > 4_194_304:
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


class _VerifiedBytesLoader:
    def __init__(self, source: bytes, path: Path):
        self._source = source
        self._path = path

    def create_module(self, spec):
        return None

    def exec_module(self, module) -> None:
        module.__file__ = str(self._path)
        exec(
            compile(self._source, str(self._path), "exec"),
            module.__dict__,
        )


def _load_v3_verifier():
    configured = os.environ.get("NOTEAI_V3_BUNDLE_VERIFIER_PATH")
    v3_path = (
        Path(configured).resolve()
        if configured
        else Path(__file__).resolve().with_name(
            "verify_admin_dependency_cache_bundle_v3.py"
        )
    )
    v3_source = _read_frozen_source(
        v3_path,
        label="frozen V3 bundle verifier",
    )
    if hashlib.sha256(v3_source).hexdigest() != V3_VERIFIER_SHA256:
        raise RuntimeError("frozen V3 bundle verifier hash drift")
    configured_base = os.environ.get("NOTEAI_BASE_BUNDLE_VERIFIER_PATH")
    base_path = (
        Path(configured_base).resolve()
        if configured_base
        else v3_path.with_name(
            "verify_admin_dependency_cache_bundle.py"
        )
    )
    base_source = _read_frozen_source(
        base_path,
        label="frozen V2 bundle verifier",
    )
    if hashlib.sha256(base_source).hexdigest() != V2_VERIFIER_SHA256:
        raise RuntimeError("frozen V2 bundle verifier hash drift")

    v3_name = "_noteai_admin_dependency_cache_bundle_v3"
    v2_name = "_noteai_admin_dependency_cache_bundle_v2"
    module = types.ModuleType(v3_name)
    module.__file__ = str(v3_path)
    module.__package__ = ""
    original_spec_from_file_location = (
        importlib.util.spec_from_file_location
    )

    def verified_spec_from_file_location(
        name: str,
        location: Any,
        *args: Any,
        **kwargs: Any,
    ):
        if name != v2_name:
            return original_spec_from_file_location(
                name,
                location,
                *args,
                **kwargs,
            )
        candidate = Path(location).resolve()
        if candidate != base_path:
            raise RuntimeError("frozen V2 bundle verifier path changed")
        loader = _VerifiedBytesLoader(base_source, base_path)
        return importlib.util.spec_from_loader(
            name,
            loader,
            origin=str(base_path),
        )

    sys.modules[v3_name] = module
    importlib.util.spec_from_file_location = (
        verified_spec_from_file_location
    )
    try:
        exec(
            compile(v3_source, str(v3_path), "exec"),
            module.__dict__,
        )
    except BaseException:
        sys.modules.pop(v3_name, None)
        raise
    finally:
        importlib.util.spec_from_file_location = (
            original_spec_from_file_location
        )
    return module


_v3 = _load_v3_verifier()
_frozen_v3_validate_build_evidence = _v3.validate_build_evidence
_PATCH_LOCK = threading.RLock()


class V6BundleError(_v3.BundleError):
    """A fixed-code V6 evidence failure safe for a public workflow log."""

    def __init__(self, failure_code: str, message: str):
        super().__init__(message)
        self.failure_code = failure_code


def _fail(failure_code: str, message: str) -> None:
    raise V6BundleError(failure_code, message)


def _require(
    condition: bool,
    failure_code: str,
    message: str,
) -> None:
    if not condition:
        _fail(failure_code, message)


def _canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_regular_bytes(
    path: Path,
    *,
    maximum_bytes: int,
    failure_code: str,
    label: str,
) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise V6BundleError(failure_code, f"cannot open {label}") from exc
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
                before.st_size,
                before.st_mtime_ns,
            )
            == (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            )
            and observed == before.st_size,
            failure_code,
            f"{label} changed while reading",
        )
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _initial_diagnostic(
    progress_path: Path,
    *,
    dockerfile_kind: str,
    require_network_vertices_cached: bool,
) -> dict[str, Any]:
    phase_by_name = {
        "producer-build.rawjson": "producer",
        "import-build.rawjson": "import",
        "replay-build.rawjson": "replay",
    }
    return {
        "schema_version": "noteai.admin-dependency-cache-v6-diagnostic.v1",
        "phase": phase_by_name.get(progress_path.name, dockerfile_kind),
        "dockerfile_kind": dockerfile_kind,
        "network_cache_required": require_network_vertices_cached,
        "progress_sha256": "",
        "progress_bytes": 0,
        "nonblank_line_count": 0,
        "vertex_update_count": 0,
        "unique_vertex_digest_count": 0,
        "status_count": 0,
        "log_count": 0,
        "warning_count": 0,
        "decoded_log_record_count": 0,
        "decoded_log_byte_count": 0,
        "decoded_warning_byte_count": 0,
        "package_network_output_observed": False,
        "roles": [
            {
                "role": spec["role"],
                "match_count": 0,
                "completed_count": 0,
                "cached_count": 0,
                "classification": "unresolved",
            }
            for spec in ROLE_SPECS
        ],
        "failure_code": "UNSET",
        "verdict": "fail",
    }


def _emit_diagnostic(diagnostic: dict[str, Any]) -> dict[str, Any]:
    bounded = dict(diagnostic)
    bounded["diagnostic_sha256"] = _canonical_sha256(bounded)
    print(
        "noteai_v6_progress_diagnostic="
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


def _canonical_digest(value: Any, label: str) -> str:
    _require(
        isinstance(value, str) and DIGEST_RE.fullmatch(value) is not None,
        "RAWJSON_DIGEST_INVALID",
        f"{label} digest invalid",
    )
    return value


def _validate_item_keys(
    item: Any,
    allowed: set[str],
    label: str,
) -> dict[str, Any]:
    _require(
        isinstance(item, dict) and set(item) <= allowed,
        "RAWJSON_ITEM_SCHEMA_INVALID",
        f"{label} schema changed",
    )
    return item


def _parse_optional_time(
    value: Any,
    label: str,
    *,
    failure_code: str = "RAWJSON_LIFECYCLE_INVALID",
) -> datetime | None:
    if value is None:
        return None
    _require(
        isinstance(value, str)
        and RFC3339_RE.fullmatch(value) is not None,
        failure_code,
        f"{label} lifecycle changed",
    )
    try:
        parse_value = (
            value[:-1] + "+00:00"
            if value.endswith("Z")
            else value
        )
        parsed = datetime.fromisoformat(parse_value)
    except ValueError as exc:
        raise V6BundleError(
            failure_code,
            f"{label} lifecycle changed",
        ) from exc
    _require(
        parsed.tzinfo is not None
        and parsed.utcoffset() is not None,
        failure_code,
        f"{label} lifecycle changed",
    )
    return parsed


def _strict_progress(
    progress_bytes: bytes,
    diagnostic: dict[str, Any],
) -> tuple[
    dict[str, dict[str, Any]],
    list[tuple[str, str]],
    dict[tuple[str, int], bytearray],
    set[str],
    list[bytes],
]:
    diagnostic["progress_bytes"] = len(progress_bytes)
    diagnostic["progress_sha256"] = hashlib.sha256(
        progress_bytes
    ).hexdigest()
    vertices: dict[str, dict[str, Any]] = {}
    named_vertices: list[tuple[str, str]] = []
    log_streams: dict[tuple[str, int], bytearray] = {}
    referenced_vertices: set[str] = set()
    plain_text_fragments: list[bytes] = []
    decoded_log_bytes = 0
    decoded_warning_bytes = 0
    for line_number, raw_line in enumerate(
        progress_bytes.splitlines(keepends=True),
        start=1,
    ):
        _require(
            line_number <= MAXIMUM_PROGRESS_LINES,
            "RAWJSON_LINE_LIMIT_EXCEEDED",
            "BuildKit rawjson line limit changed",
        )
        if not raw_line.strip():
            continue
        diagnostic["nonblank_line_count"] += 1
        event = _v3.strict_json_bytes(
            raw_line,
            f"BuildKit rawjson line {line_number}",
        )
        _require(
            isinstance(event, dict)
            and bool(event)
            and set(event) <= TOP_LEVEL_KEYS,
            "RAWJSON_TOP_LEVEL_INVALID",
            "BuildKit rawjson top-level schema changed",
        )
        for key, values in event.items():
            _require(
                isinstance(values, list) and bool(values),
                "RAWJSON_ARRAY_INVALID",
                f"BuildKit rawjson {key} changed",
            )

        for raw_vertex in event.get("vertexes", []):
            vertex = _validate_item_keys(
                raw_vertex,
                VERTEX_KEYS,
                "BuildKit vertex",
            )
            digest = _canonical_digest(
                vertex.get("digest"),
                "BuildKit vertex",
            )
            inputs = vertex.get("inputs", [])
            _require(
                isinstance(inputs, list),
                "RAWJSON_VERTEX_INPUT_INVALID",
                "BuildKit vertex inputs changed",
            )
            for raw_input in inputs:
                _canonical_digest(raw_input, "BuildKit vertex input")
            name = vertex.get("name")
            _require(
                name is None or isinstance(name, str),
                "RAWJSON_VERTEX_NAME_INVALID",
                "BuildKit vertex name changed",
            )
            if isinstance(name, str):
                named_vertices.append((digest, name))
                plain_text_fragments.append(name.encode("utf-8"))
            cached = vertex.get("cached", False)
            _require(
                isinstance(cached, bool),
                "RAWJSON_VERTEX_CACHED_INVALID",
                "BuildKit vertex cached state changed",
            )
            started_at = _parse_optional_time(
                vertex.get("started"),
                "BuildKit vertex start",
            )
            completed_at = _parse_optional_time(
                vertex.get("completed"),
                "BuildKit vertex completion",
            )
            _require(
                started_at is None
                or completed_at is None
                or completed_at >= started_at,
                "RAWJSON_LIFECYCLE_INVALID",
                "BuildKit vertex lifecycle changed",
            )
            error = vertex.get("error")
            _require(
                error is None or isinstance(error, str),
                "RAWJSON_VERTEX_ERROR_INVALID",
                "BuildKit vertex error changed",
            )
            _require(
                not error,
                "RAWJSON_VERTEX_ERROR_PRESENT",
                "BuildKit vertex reported an error",
            )
            _require(
                vertex.get("progressGroup") is None
                or isinstance(vertex["progressGroup"], dict),
                "RAWJSON_VERTEX_PROGRESS_GROUP_INVALID",
                "BuildKit vertex progress group changed",
            )
            aggregate = vertices.setdefault(
                digest,
                {
                    "names": set(),
                    "cached": False,
                    "completed": False,
                    "started_values": set(),
                    "completion_values": set(),
                },
            )
            if isinstance(name, str):
                aggregate["names"].add(name)
            if vertex.get("completed"):
                aggregate["completed"] = True
                aggregate["completion_values"].add(
                    completed_at
                )
            if vertex.get("started"):
                aggregate["started_values"].add(started_at)
            if cached:
                aggregate["cached"] = True
            _require(
                len(aggregate["names"]) <= 1
                and len(aggregate["started_values"]) <= 1
                and len(aggregate["completion_values"]) <= 1,
                "RAWJSON_VERTEX_CONFLICT",
                "BuildKit vertex updates conflict",
            )
            diagnostic["vertex_update_count"] += 1

        for raw_status in event.get("statuses", []):
            status = _validate_item_keys(
                raw_status,
                STATUS_KEYS,
                "BuildKit status",
            )
            _require(
                isinstance(status.get("id"), str)
                and bool(status["id"]),
                "RAWJSON_STATUS_ID_INVALID",
                "BuildKit status id changed",
            )
            parent = _canonical_digest(
                status.get("vertex"),
                "BuildKit status parent",
            )
            referenced_vertices.add(parent)
            status_name = status.get("name")
            _require(
                status_name is None or isinstance(status_name, str),
                "RAWJSON_STATUS_NAME_INVALID",
                "BuildKit status name changed",
            )
            if isinstance(status_name, str):
                plain_text_fragments.append(
                    status_name.encode("utf-8")
                )
            current = status.get("current")
            total = status.get("total")
            _require(
                isinstance(current, int)
                and not isinstance(current, bool)
                and (
                    total is None
                    or (
                        isinstance(total, int)
                        and not isinstance(total, bool)
                    )
                )
                and isinstance(status.get("timestamp"), str)
                and bool(status["timestamp"]),
                "RAWJSON_STATUS_VALUE_INVALID",
                "BuildKit status values changed",
            )
            _parse_optional_time(
                status.get("timestamp"),
                "BuildKit status timestamp",
            )
            status_started = _parse_optional_time(
                status.get("started"),
                "BuildKit status start",
            )
            status_completed = _parse_optional_time(
                status.get("completed"),
                "BuildKit status completion",
            )
            _require(
                status_started is None
                or status_completed is None
                or status_completed >= status_started,
                "RAWJSON_LIFECYCLE_INVALID",
                "BuildKit status lifecycle changed",
            )
            diagnostic["status_count"] += 1

        for raw_log in event.get("logs", []):
            log = _validate_item_keys(
                raw_log,
                LOG_KEYS,
                "BuildKit log",
            )
            parent = _canonical_digest(
                log.get("vertex"),
                "BuildKit log parent",
            )
            referenced_vertices.add(parent)
            stream = log.get("stream", 0)
            _require(
                isinstance(stream, int)
                and not isinstance(stream, bool)
                and 0 <= stream <= 2,
                "RAWJSON_LOG_STREAM_INVALID",
                "BuildKit log stream changed",
            )
            encoded = log.get("data")
            _require(
                isinstance(encoded, str)
                and isinstance(log.get("timestamp"), str)
                and bool(log["timestamp"]),
                "RAWJSON_LOG_DATA_INVALID",
                "BuildKit log data changed",
            )
            _parse_optional_time(
                log["timestamp"],
                "BuildKit log timestamp",
            )
            try:
                decoded = base64.b64decode(
                    encoded.encode("ascii"),
                    validate=True,
                )
            except (
                UnicodeEncodeError,
                ValueError,
                binascii.Error,
            ) as exc:
                raise V6BundleError(
                    "RAWJSON_LOG_BASE64_INVALID",
                    "BuildKit log data base64 invalid",
                ) from exc
            decoded_log_bytes += len(decoded)
            _require(
                (
                    decoded_log_bytes
                    + decoded_warning_bytes
                    <= MAXIMUM_DECODED_LOG_BYTES
                ),
                "RAWJSON_LOG_LIMIT_EXCEEDED",
                "BuildKit decoded log limit changed",
            )
            log_streams.setdefault(
                (parent, stream),
                bytearray(),
            ).extend(decoded)
            diagnostic["log_count"] += 1
            diagnostic["decoded_log_record_count"] += 1

        for raw_warning in event.get("warnings", []):
            warning = _validate_item_keys(
                raw_warning,
                WARNING_KEYS,
                "BuildKit warning",
            )
            if "vertex" in warning:
                referenced_vertices.add(
                    _canonical_digest(
                        warning["vertex"],
                        "BuildKit warning parent",
                    )
                )
            level = warning.get("level")
            _require(
                level is None
                or (
                    isinstance(level, int)
                    and not isinstance(level, bool)
                ),
                "RAWJSON_WARNING_INVALID",
                "BuildKit warning level changed",
            )
            short = warning.get("short")
            detail = warning.get("detail", [])
            url = warning.get("url")
            _require(
                (short is None or isinstance(short, str))
                and isinstance(detail, list)
                and all(isinstance(item, str) for item in detail)
                and (url is None or isinstance(url, str))
                and (
                    warning.get("sourceInfo") is None
                    or isinstance(warning["sourceInfo"], dict)
                )
                and (
                    warning.get("range") is None
                    or isinstance(warning["range"], list)
                ),
                "RAWJSON_WARNING_INVALID",
                "BuildKit warning payload changed",
            )
            encoded_warning_values = (
                ([] if short is None else [short]) + detail
            )
            for encoded_warning in encoded_warning_values:
                try:
                    decoded_warning = base64.b64decode(
                        encoded_warning.encode("ascii"),
                        validate=True,
                    )
                except (
                    UnicodeEncodeError,
                    ValueError,
                    binascii.Error,
                ) as exc:
                    raise V6BundleError(
                        "RAWJSON_WARNING_BASE64_INVALID",
                        "BuildKit warning base64 invalid",
                    ) from exc
                decoded_warning_bytes += len(decoded_warning)
                _require(
                    (
                        decoded_log_bytes
                        + decoded_warning_bytes
                        <= MAXIMUM_DECODED_LOG_BYTES
                    ),
                    "RAWJSON_LOG_LIMIT_EXCEEDED",
                    "BuildKit decoded log limit changed",
                )
                plain_text_fragments.append(decoded_warning)
            if isinstance(url, str):
                plain_text_fragments.append(url.encode("utf-8"))
            diagnostic["warning_count"] += 1

    _require(
        diagnostic["nonblank_line_count"] > 0 and bool(vertices),
        "RAWJSON_EMPTY",
        "BuildKit rawjson vertex evidence is empty",
    )
    _require(
        referenced_vertices <= set(vertices),
        "RAWJSON_ORPHAN_REFERENCE",
        "BuildKit rawjson references an unknown vertex",
    )
    diagnostic["unique_vertex_digest_count"] = len(vertices)
    diagnostic["decoded_log_byte_count"] = decoded_log_bytes
    diagnostic["decoded_warning_byte_count"] = (
        decoded_warning_bytes
    )
    return (
        vertices,
        named_vertices,
        log_streams,
        referenced_vertices,
        plain_text_fragments,
    )


def _range_projection(
    location: Any,
    step_id: str,
) -> dict[str, set[int]]:
    _require(
        isinstance(location, dict)
        and set(location) == {"locations"}
        and isinstance(location["locations"], list)
        and bool(location["locations"]),
        "PROVENANCE_LOCATION_INVALID",
        f"BuildKit source location changed for {step_id}",
    )
    lines: set[int] = set()
    starts: set[int] = set()
    for group in location["locations"]:
        _require(
            isinstance(group, dict)
            and set(group) == {"ranges"}
            and isinstance(group["ranges"], list)
            and bool(group["ranges"]),
            "PROVENANCE_LOCATION_INVALID",
            f"BuildKit source ranges changed for {step_id}",
        )
        for raw_range in group["ranges"]:
            _require(
                isinstance(raw_range, dict)
                and set(raw_range) == {"start", "end"},
                "PROVENANCE_LOCATION_INVALID",
                f"BuildKit source range changed for {step_id}",
            )
            start = raw_range["start"]
            end = raw_range["end"]
            _require(
                isinstance(start, dict)
                and isinstance(end, dict)
                and set(start) <= {"line", "character"}
                and set(end) <= {"line", "character"}
                and isinstance(start.get("line"), int)
                and not isinstance(start.get("line"), bool)
                and isinstance(end.get("line"), int)
                and not isinstance(end.get("line"), bool)
                and 1 <= start["line"] <= end["line"] <= 100,
                "PROVENANCE_LOCATION_INVALID",
                f"BuildKit source line changed for {step_id}",
            )
            starts.add(start["line"])
            lines.update(range(start["line"], end["line"] + 1))
    return {"lines": lines, "starts": starts}


def _structural_bindings(
    metadata: dict[str, Any],
    vertices: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    provenance = metadata.get("buildx.build.provenance")
    _require(
        isinstance(provenance, dict),
        "PROVENANCE_ROOT_INVALID",
        "BuildKit provenance missing",
    )
    build_config = provenance.get("buildConfig")
    _require(
        isinstance(build_config, dict),
        "PROVENANCE_BUILD_CONFIG_INVALID",
        "BuildKit max provenance missing",
    )
    llb = build_config.get("llbDefinition")
    digest_mapping = build_config.get("digestMapping")
    _require(
        isinstance(llb, list)
        and bool(llb)
        and isinstance(digest_mapping, dict)
        and bool(digest_mapping),
        "PROVENANCE_BUILD_CONFIG_INVALID",
        "BuildKit structural provenance missing",
    )

    steps: dict[str, dict[str, Any]] = {}
    for item in llb:
        _require(
            isinstance(item, dict)
            and set(item) <= {"id", "op", "inputs", "resourceUsage"},
            "PROVENANCE_STEP_INVALID",
            "BuildKit LLB step schema changed",
        )
        step_id = item.get("id")
        _require(
            isinstance(step_id, str)
            and STEP_RE.fullmatch(step_id) is not None
            and step_id not in steps,
            "PROVENANCE_STEP_INVALID",
            "BuildKit LLB step id changed",
        )
        op = item.get("op")
        _require(
            isinstance(op, dict),
            "PROVENANCE_STEP_INVALID",
            "BuildKit LLB step op changed",
        )
        op_union = op.get("Op")
        steps[step_id] = {
            "exec": (
                isinstance(op_union, dict)
                and set(op_union) == {"exec"}
                and isinstance(op_union.get("exec"), dict)
            ),
            "platform": op.get("platform"),
        }

    digest_to_step: dict[str, str] = {}
    step_to_digests: dict[str, list[str]] = {}
    for raw_digest, raw_step in digest_mapping.items():
        digest = _canonical_digest(
            raw_digest,
            "BuildKit digest mapping",
        )
        _require(
            isinstance(raw_step, str)
            and STEP_RE.fullmatch(raw_step) is not None
            and raw_step in steps,
            "PROVENANCE_DIGEST_MAPPING_INVALID",
            "BuildKit digest mapping changed",
        )
        digest_to_step[digest] = raw_step
        step_to_digests.setdefault(raw_step, []).append(digest)
    _require(
        len(digest_to_step) == len(digest_mapping),
        "PROVENANCE_DIGEST_MAPPING_INVALID",
        "BuildKit digest mapping is ambiguous",
    )

    provenance_metadata = provenance.get("metadata")
    _require(
        isinstance(provenance_metadata, dict),
        "PROVENANCE_LOCATION_INVALID",
        "BuildKit provenance metadata changed",
    )
    source_metadata = provenance_metadata.get(
        "https://mobyproject.org/buildkit@v1#metadata"
    )
    source = (
        source_metadata.get("source")
        if isinstance(source_metadata, dict)
        else None
    )
    locations = source.get("locations") if isinstance(source, dict) else None
    _require(
        isinstance(locations, dict) and bool(locations),
        "PROVENANCE_LOCATION_INVALID",
        "BuildKit source locations missing",
    )
    for step_id in locations:
        _require(
            isinstance(step_id, str) and step_id in steps,
            "PROVENANCE_LOCATION_INVALID",
            "BuildKit source location step changed",
        )

    step_ranges = {
        step_id: _range_projection(location, step_id)
        for step_id, location in locations.items()
    }
    bindings: list[dict[str, Any]] = []
    for spec in ROLE_SPECS:
        matching_steps = [
            step_id
            for step_id, projection in step_ranges.items()
            if spec["line"] in projection["starts"]
        ]
        _require(
            len(matching_steps) == 1,
            "PROVENANCE_ROLE_LOCATION_AMBIGUOUS",
            f"BuildKit {spec['role']} source binding changed",
        )
        step_id = matching_steps[0]
        _require(
            steps[step_id]["exec"],
            "PROVENANCE_ROLE_NOT_EXEC",
            f"BuildKit {spec['role']} is not an exec vertex",
        )
        _require(
            steps[step_id]["platform"]
            == {"Architecture": "amd64", "OS": "linux"},
            "PROVENANCE_ROLE_PLATFORM_INVALID",
            f"BuildKit {spec['role']} platform changed",
        )
        digests = step_to_digests.get(step_id, [])
        _require(
            len(digests) == 1,
            "PROVENANCE_ROLE_DIGEST_AMBIGUOUS",
            f"BuildKit {spec['role']} digest binding changed",
        )
        digest = digests[0]
        _require(
            digest in vertices,
            "PROVENANCE_ROLE_VERTEX_MISSING",
            f"BuildKit {spec['role']} progress vertex missing",
        )
        bindings.append(
            {
                "role": spec["role"],
                "line": spec["line"],
                "marker": spec["marker"],
                "step_id": step_id,
                "vertex": digest,
            }
        )
    _require(
        len({item["step_id"] for item in bindings}) == len(ROLE_SPECS)
        and len({item["vertex"] for item in bindings}) == len(ROLE_SPECS),
        "PROVENANCE_ROLE_BINDING_COLLISION",
        "BuildKit dependency role bindings collide",
    )
    return bindings


def _provenance_build_window(
    metadata: dict[str, Any],
) -> tuple[datetime, datetime]:
    provenance = metadata.get("buildx.build.provenance")
    _require(
        isinstance(provenance, dict),
        "PROVENANCE_LIFECYCLE_INVALID",
        "BuildKit provenance changed",
    )
    provenance_metadata = provenance.get("metadata")
    _require(
        isinstance(provenance_metadata, dict),
        "PROVENANCE_LIFECYCLE_INVALID",
        "BuildKit timing metadata changed",
    )
    started = _parse_optional_time(
        provenance_metadata.get("buildStartedOn"),
        "BuildKit build start",
        failure_code="PROVENANCE_LIFECYCLE_INVALID",
    )
    finished = _parse_optional_time(
        provenance_metadata.get("buildFinishedOn"),
        "BuildKit build finish",
        failure_code="PROVENANCE_LIFECYCLE_INVALID",
    )
    _require(
        started is not None
        and finished is not None
        and started <= finished
        and (finished - started).total_seconds() <= 7_200,
        "PROVENANCE_LIFECYCLE_INVALID",
        "BuildKit build lifecycle changed",
    )
    return started, finished


def _validate_roles_and_logs(
    bindings: list[dict[str, Any]],
    vertices: dict[str, dict[str, Any]],
    named_vertices: list[tuple[str, str]],
    log_streams: dict[tuple[str, int], bytearray],
    plain_text_fragments: list[bytes],
    *,
    require_network_vertices_cached: bool,
    build_window: tuple[datetime, datetime],
    diagnostic: dict[str, Any],
) -> list[dict[str, Any]]:
    package_network_observed = any(
        PACKAGE_NETWORK_BYTES_RE.search(bytes(stream)) is not None
        for stream in log_streams.values()
    ) or any(
        PACKAGE_NETWORK_BYTES_RE.search(fragment) is not None
        for fragment in plain_text_fragments
    )
    diagnostic["package_network_output_observed"] = (
        package_network_observed
    )
    if require_network_vertices_cached:
        _require(
            not package_network_observed,
            "PACKAGE_NETWORK_OUTPUT_OBSERVED",
            "package-network output appeared during cache replay",
        )

    evaluated_roles: list[dict[str, Any]] = []
    for binding in bindings:
        marker_digests = {
            digest
            for digest, name in named_vertices
            if binding["marker"] in name
        }
        if marker_digests == {binding["vertex"]}:
            classification = "exact"
        elif not marker_digests:
            classification = "name_drift"
        elif len(marker_digests) > 1:
            classification = "duplicate"
        else:
            classification = "mismatch"

        vertex = vertices[binding["vertex"]]
        completed_count = int(bool(vertex["completed"]))
        cached_count = int(bool(vertex["cached"]))
        evaluated_roles.append(
            {
                "binding": binding,
                "vertex": vertex,
                "role": binding["role"],
                "match_count": len(marker_digests),
                "completed_count": completed_count,
                "cached_count": cached_count,
                "classification": classification,
            }
        )
    diagnostic["roles"] = [
        {
            key: value
            for key, value in evaluated.items()
            if key not in {"binding", "vertex"}
        }
        for evaluated in evaluated_roles
    ]

    role_summaries: list[dict[str, Any]] = []
    for evaluated in evaluated_roles:
        binding = evaluated["binding"]
        vertex = evaluated["vertex"]
        classification = evaluated["classification"]
        _require(
            classification in {"exact", "name_drift"},
            (
                "NETWORK_VERTEX_DUPLICATE"
                if classification == "duplicate"
                else "NETWORK_VERTEX_MISMATCH"
            ),
            f"BuildKit {binding['role']} name classification changed",
        )
        _require(
            bool(vertex["completed"]),
            "NETWORK_VERTEX_INCOMPLETE",
            f"BuildKit {binding['role']} vertex incomplete",
        )
        started_values = vertex["started_values"]
        completed_values = vertex["completion_values"]
        _require(
            len(started_values) == 1
            and len(completed_values) == 1,
            "NETWORK_VERTEX_LIFECYCLE_INCOMPLETE",
            f"BuildKit {binding['role']} lifecycle incomplete",
        )
        started_at = next(iter(started_values))
        completed_at = next(iter(completed_values))
        _require(
            build_window[0]
            <= started_at
            <= completed_at
            <= build_window[1],
            "NETWORK_VERTEX_LIFECYCLE_OUTSIDE_BUILD",
            f"BuildKit {binding['role']} lifecycle changed",
        )
        if require_network_vertices_cached:
            _require(
                bool(vertex["cached"]),
                "NETWORK_VERTEX_NOT_CACHED",
                f"BuildKit {binding['role']} vertex was not cached",
            )
        role_summaries.append(
            {
                "role": binding["role"],
                "line": binding["line"],
                "step_id": binding["step_id"],
                "vertex": binding["vertex"],
                "name_classification": classification,
            }
        )
    return role_summaries


def _write_exclusive_regular(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        path,
        (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
        ),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    observed = _read_regular_bytes(
        path,
        maximum_bytes=len(payload),
        failure_code="LEGACY_EVIDENCE_VIEW_INVALID",
        label="V6 legacy evidence",
    )
    file_state = os.lstat(path)
    _require(
        observed == payload
        and stat.S_ISREG(file_state.st_mode)
        and stat.S_IMODE(file_state.st_mode) == 0o600
        and file_state.st_nlink == 1,
        "LEGACY_EVIDENCE_VIEW_INVALID",
        "V6 legacy evidence view is unsafe",
    )


@contextmanager
def _legacy_evidence_view(
    metadata_bytes: bytes,
    bindings: list[dict[str, Any]],
    vertices: dict[str, dict[str, Any]],
) -> Iterator[tuple[Path, Path, str, list[dict[str, str]]]]:
    temporary_root = Path(
        tempfile.mkdtemp(prefix="noteai-v6-evidence-")
    )
    try:
        os.chmod(temporary_root, 0o700)
        root_state = os.lstat(temporary_root)
        _require(
            stat.S_ISDIR(root_state.st_mode)
            and stat.S_IMODE(root_state.st_mode) == 0o700
            and root_state.st_nlink >= 1,
            "LEGACY_EVIDENCE_VIEW_INVALID",
            "V6 legacy evidence directory is unsafe",
        )
        metadata_path = temporary_root / "metadata.json"
        shim_path = temporary_root / "progress.rawjson"
        legacy_progress = bytearray()
        expected_network_vertices: list[dict[str, str]] = []
        for binding in bindings:
            vertex = vertices[binding["vertex"]]
            event = {
                "id": binding["vertex"],
                "name": binding["marker"],
                "cached": bool(vertex["cached"]),
                "completed": next(
                    iter(vertex["completion_values"])
                ).isoformat(),
            }
            legacy_progress.extend(
                json.dumps(
                    event,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                + b"\n"
            )
            expected_network_vertices.append(
                {
                    "marker": binding["marker"],
                    "vertex": binding["vertex"],
                }
            )
        legacy_progress_bytes = bytes(legacy_progress)
        _write_exclusive_regular(metadata_path, metadata_bytes)
        _write_exclusive_regular(shim_path, legacy_progress_bytes)
        yield (
            metadata_path,
            shim_path,
            hashlib.sha256(legacy_progress_bytes).hexdigest(),
            expected_network_vertices,
        )
    finally:
        try:
            shutil.rmtree(temporary_root)
        except OSError as exc:
            raise V6BundleError(
                "LEGACY_EVIDENCE_CLEANUP_FAILED",
                "V6 legacy evidence cleanup failed",
            ) from exc
        _require(
            not temporary_root.exists()
            and not temporary_root.is_symlink(),
            "LEGACY_EVIDENCE_CLEANUP_FAILED",
            "V6 legacy evidence cleanup incomplete",
        )


def validate_build_evidence(
    metadata_path: Path,
    progress_path: Path,
    *,
    dockerfile_kind: str,
    require_network_vertices_cached: bool,
) -> dict[str, Any]:
    metadata_path = Path(metadata_path)
    progress_path = Path(progress_path)
    diagnostic = _initial_diagnostic(
        progress_path,
        dockerfile_kind=dockerfile_kind,
        require_network_vertices_cached=require_network_vertices_cached,
    )
    try:
        _require(
            dockerfile_kind in {"prefix", "full"},
            "DOCKERFILE_KIND_INVALID",
            "Dockerfile kind changed",
        )
        metadata_bytes = _read_regular_bytes(
            metadata_path,
            maximum_bytes=MAXIMUM_METADATA_BYTES,
            failure_code="METADATA_FILE_INVALID",
            label="BuildKit metadata",
        )
        progress_bytes = _read_regular_bytes(
            progress_path,
            maximum_bytes=MAXIMUM_PROGRESS_BYTES,
            failure_code="RAWJSON_FILE_INVALID",
            label="BuildKit rawjson",
        )
        original_metadata_sha256 = hashlib.sha256(
            metadata_bytes
        ).hexdigest()
        original_progress_sha256 = hashlib.sha256(
            progress_bytes
        ).hexdigest()
        metadata = _v3.strict_json_bytes(
            metadata_bytes,
            "BuildKit metadata",
        )
        _require(
            isinstance(metadata, dict),
            "PROVENANCE_ROOT_INVALID",
            "BuildKit metadata root changed",
        )
        (
            vertices,
            named_vertices,
            log_streams,
            _referenced_vertices,
            plain_text_fragments,
        ) = _strict_progress(progress_bytes, diagnostic)
        bindings = _structural_bindings(metadata, vertices)
        build_window = _provenance_build_window(metadata)
        role_summaries = _validate_roles_and_logs(
            bindings,
            vertices,
            named_vertices,
            log_streams,
            plain_text_fragments,
            require_network_vertices_cached=(
                require_network_vertices_cached
            ),
            build_window=build_window,
            diagnostic=diagnostic,
        )
        with _legacy_evidence_view(
            metadata_bytes,
            bindings,
            vertices,
        ) as (
            legacy_metadata,
            legacy_progress,
            legacy_progress_sha256,
            expected_legacy_vertices,
        ):
            with _PATCH_LOCK:
                summary = _frozen_v3_validate_build_evidence(
                    legacy_metadata,
                    legacy_progress,
                    dockerfile_kind=dockerfile_kind,
                    require_network_vertices_cached=(
                        require_network_vertices_cached
                    ),
                )
        _require(
            isinstance(summary, dict)
            and summary.get("progress_sha256")
            == legacy_progress_sha256,
            "FROZEN_V3_PROGRESS_HASH_CHANGED",
            "frozen V3 progress hash changed",
        )
        _require(
            summary.get("metadata_sha256") == original_metadata_sha256,
            "FROZEN_V3_METADATA_HASH_CHANGED",
            "frozen V3 metadata hash changed",
        )
        _require(
            summary.get("network_vertex_count") == len(ROLE_SPECS)
            and summary.get("network_vertices_cached")
            is require_network_vertices_cached
            and summary.get("network_vertices")
            == expected_legacy_vertices,
            "FROZEN_V3_NETWORK_SUMMARY_CHANGED",
            "frozen V3 network summary changed",
        )
        _require(
            _read_regular_bytes(
                metadata_path,
                maximum_bytes=MAXIMUM_METADATA_BYTES,
                failure_code="METADATA_FILE_INVALID",
                label="BuildKit metadata",
            )
            == metadata_bytes
            and _read_regular_bytes(
                progress_path,
                maximum_bytes=MAXIMUM_PROGRESS_BYTES,
                failure_code="RAWJSON_FILE_INVALID",
                label="BuildKit rawjson",
            )
            == progress_bytes,
            "ORIGINAL_EVIDENCE_CHANGED",
            "original BuildKit evidence changed during validation",
        )
        summary["progress_sha256"] = original_progress_sha256
        summary["network_vertex_count"] = len(role_summaries)
        summary["network_vertices_cached"] = (
            require_network_vertices_cached
        )
        summary["network_vertices"] = role_summaries
        diagnostic["failure_code"] = "NONE"
        diagnostic["verdict"] = "pass"
        bounded_diagnostic = _emit_diagnostic(diagnostic)
        summary["v6_rawjson_diagnostic"] = bounded_diagnostic
        return summary
    except V6BundleError as exc:
        diagnostic["failure_code"] = exc.failure_code
        _emit_diagnostic(diagnostic)
        raise
    except _v3.BundleError:
        diagnostic["failure_code"] = "FROZEN_V3_VALIDATION_FAILED"
        _emit_diagnostic(diagnostic)
        raise _v3.BundleError(
            "frozen V3 evidence validation failed"
        ) from None
    except OSError as exc:
        diagnostic["failure_code"] = "V6_IO_FAILED"
        _emit_diagnostic(diagnostic)
        raise _v3.BundleError("V6 evidence I/O failed") from exc
    except Exception:
        diagnostic["failure_code"] = "V6_UNEXPECTED_FAILURE"
        _emit_diagnostic(diagnostic)
        raise _v3.BundleError(
            "V6 evidence validation failed"
        ) from None


@contextmanager
def _patched_base_validator() -> Iterator[None]:
    with _PATCH_LOCK:
        original = _v3._base.validate_build_evidence
        _require(
            original is _frozen_v3_validate_build_evidence,
            "FROZEN_V3_DISPATCH_CHANGED",
            "frozen V3 validator dispatch changed",
        )
        _v3._base.validate_build_evidence = validate_build_evidence
        try:
            yield
        finally:
            _v3._base.validate_build_evidence = original
            _require(
                _v3._base.validate_build_evidence is original,
                "FROZEN_V3_DISPATCH_RESTORE_FAILED",
                "frozen V3 validator dispatch restore failed",
            )


def __getattr__(name: str):
    return getattr(_v3, name)


def validate_core(*args: Any, **kwargs: Any):
    with _patched_base_validator():
        return _v3.validate_core(*args, **kwargs)


def validate_final(*args: Any, **kwargs: Any):
    with _patched_base_validator():
        return _v3.validate_final(*args, **kwargs)


def main() -> int:
    with _patched_base_validator():
        return _v3.main()


if __name__ == "__main__":
    raise SystemExit(main())
