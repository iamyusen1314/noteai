#!/usr/bin/env python3
"""Strengthen the frozen V9 cache proof with an uncached observer child.

V10 keeps the producer prefix and the full replay byte-for-byte unchanged.
Only the fresh-consumer prefix appends a zero-network observer whose direct
parent is the runtime_pip LLB step.  The observer must execute uncached and
emit one digest-bound marker; every dependency role must still be cached.
"""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import types
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


V9_VERIFIER_SHA256 = (
    "a69103e899dc74b4d34e4837e29f4028"
    "4be9b252281fed262a2dd1afee3d6032"
)
BASE_PREFIX_SHA256 = (
    "93fd024e5af678b7885bcab8e72d980a"
    "9f92cfc70de4f2fd2870284e25b8ec1e"
)
OBSERVER_SUFFIX = (
    b"\nFROM runtime-common AS noteai-cache-observer\n"
    b"RUN --network=none printf '%s\\n' noteai-cache-observer-v10\n"
)
OBSERVER_SUFFIX_SHA256 = (
    "7cdfa59482f73d3274bc6080468671aeb"
    "42f5e45f5b6c868d52f13e8ee7c5266"
)
OBSERVER_DOCKERFILE_SHA256 = (
    "8a2692fb460557e0159bc9e000364b51"
    "5ce80aaf08eeeb186bf4930ce6357068"
)
OBSERVER_DOCKERFILE_BYTES = 5062
OBSERVER_DOCKERFILE_LINES = 83
OBSERVER_TARGET = "noteai-cache-observer"
OBSERVER_LINE = 83
OBSERVER_MARKER = b"noteai-cache-observer-v10\n"
FULL_WITNESS_LINE = 93


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


def _load_v9_verifier():
    configured = os.environ.get("NOTEAI_V9_BUNDLE_VERIFIER_PATH")
    configured_path = (
        Path(configured)
        if configured
        else Path(__file__).with_name(
            "verify_admin_dependency_cache_bundle_v9.py"
        )
    )
    if configured_path.is_symlink():
        raise RuntimeError("frozen V9 bundle verifier file contract changed")
    v9_path = configured_path.resolve()
    source = _read_frozen_source(
        v9_path,
        label="frozen V9 bundle verifier",
    )
    if hashlib.sha256(source).hexdigest() != V9_VERIFIER_SHA256:
        raise RuntimeError("frozen V9 bundle verifier hash drift")
    module_name = "_noteai_admin_dependency_cache_bundle_v9_for_v10"
    module = types.ModuleType(module_name)
    module.__file__ = str(v9_path)
    module.__package__ = ""
    sys.modules[module_name] = module
    try:
        exec(compile(source, str(v9_path), "exec"), module.__dict__)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


_v9 = _load_v9_verifier()
_v8 = _v9._v8
_v7 = _v9._v7
_v6 = _v9._v6
_FROZEN_V9_INTERNAL_VALIDATE_BUILD_EVIDENCE = _v9._validate_build_evidence
_FROZEN_V9_VALIDATE_BUILD_EVIDENCE = _v9.validate_build_evidence
_FROZEN_V9_VALIDATE_CORE = _v9.validate_core
_FROZEN_V9_VALIDATE_FINAL = _v9.validate_final
_FROZEN_V9_MAIN = _v9.main
_FROZEN_V9_GLOBALS = tuple(
    sorted(_v9.__dict__.items(), key=lambda item: item[0])
)
_PATCH_LOCK = _v6._PATCH_LOCK


class V10BundleError(_v9.V9BundleError):
    """A fixed-code V10 failure safe for a public workflow log."""


class _FrozenV9Rejection(Exception):
    """A private marker that preserves the frozen delegate as failure origin."""

    def __init__(self, failure_code: str, message: str):
        super().__init__(message)
        self.failure_code = failure_code


def _fail(failure_code: str, message: str) -> None:
    raise V10BundleError(failure_code, message)


def _require(
    condition: bool,
    failure_code: str,
    message: str,
) -> None:
    if not condition:
        _fail(failure_code, message)


def _assert_frozen_dispatch() -> None:
    try:
        _v9._assert_frozen_dispatch()
    except _v9.V9BundleError as exc:
        raise V10BundleError(exc.failure_code, str(exc)) from None
    current = _v9.__dict__
    _require(
        tuple(sorted(current))
        == tuple(name for name, _value in _FROZEN_V9_GLOBALS),
        "FROZEN_V9_DISPATCH_CHANGED",
        "frozen V9 validator dispatch changed",
    )
    for name, expected in _FROZEN_V9_GLOBALS:
        _require(
            current[name] is expected,
            "FROZEN_V9_DISPATCH_CHANGED",
            "frozen V9 validator dispatch changed",
        )


def _assert_expected_nested_dispatch() -> None:
    """Accept only the exact V9→V2 patch stack used by validate_final."""

    def assert_globals(
        module: types.ModuleType,
        frozen_globals: tuple[tuple[str, Any], ...],
        replacements: dict[str, Any],
    ) -> None:
        current = module.__dict__
        _require(
            tuple(sorted(current))
            == tuple(name for name, _expected in frozen_globals),
            "FROZEN_V9_NESTED_DISPATCH_CHANGED",
            "frozen V9 nested validator dispatch changed",
        )
        for name, frozen in frozen_globals:
            expected = replacements.get(name, frozen)
            _require(
                current[name] is expected,
                "FROZEN_V9_NESTED_DISPATCH_CHANGED",
                "frozen V9 nested validator dispatch changed",
            )

    _require(
        _v9._v8 is _v8
        and _v9._v7 is _v7
        and _v9._v6 is _v6
        and _v6._v3 is _v9._FROZEN_V3_MODULE
        and _v6._v3._base is _v9._FROZEN_V2_MODULE,
        "FROZEN_V9_NESTED_DISPATCH_CHANGED",
        "frozen V9 nested validator module chain changed",
    )
    assert_globals(
        _v9,
        _FROZEN_V9_GLOBALS,
        {},
    )
    nested_replacements: dict[types.ModuleType, dict[str, Any]] = {
        _v8: {
            "_initial_diagnostic": _v9._initial_diagnostic,
            "_emit_diagnostic": _v9._emit_diagnostic,
            "_validate_build_evidence": _chain_validate_build_evidence,
        },
        _v7: {
            "_initial_diagnostic": _v9._initial_diagnostic,
            "_emit_diagnostic": _v9._emit_diagnostic,
            "_strict_progress": _v9._strict_progress,
            "_validate_build_evidence": _chain_validate_build_evidence,
        },
        _v6: {
            "_range_projection": _v8._range_projection,
            "_initial_diagnostic": _v9._initial_diagnostic,
            "_emit_diagnostic": _v9._emit_diagnostic,
            "_strict_progress": _v9._strict_progress,
            "_provenance_build_window": _v7._provenance_build_window,
            "_validate_roles_and_logs": _v7._validate_roles_and_logs,
            "validate_build_evidence": _chain_validate_build_evidence,
        },
        _v6._v3._base: {
            "validate_build_evidence": _chain_validate_build_evidence,
        },
    }
    for module, frozen_globals in _v9._FROZEN_CHAIN_GLOBALS:
        assert_globals(
            module,
            frozen_globals,
            nested_replacements.get(module, {}),
        )


def _canonical_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _initial_diagnostic(
    metadata_bytes: bytes,
    progress_bytes: bytes,
    *,
    dockerfile_kind: str,
    require_network_vertices_cached: bool,
) -> dict[str, Any]:
    return {
        "schema_version": "noteai.admin-dependency-cache-v10-diagnostic.v1",
        "projection_kind": "unresolved",
        "metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
        "progress_sha256": hashlib.sha256(progress_bytes).hexdigest(),
        "dockerfile_kind": dockerfile_kind,
        "network_cache_required": require_network_vertices_cached,
        "parse_completed": False,
        "role_binding_completed": False,
        "interval_projection_completed": False,
        "role_intervals": [],
        "observer_required": False,
        "observer_binding_completed": False,
        "observer": None,
        "full_post_pip_witness": None,
        "v9_diagnostic_sha256": None,
        "historical_v9_root_cause_status": "UNKNOWN_NOT_RETAINED",
        "v10_root_cause_status": "UNSET",
        "failure_code": "UNSET",
        "verdict": "fail",
    }


def _emit_diagnostic(diagnostic: dict[str, Any]) -> dict[str, Any]:
    bounded = dict(diagnostic)
    bounded["diagnostic_sha256"] = _canonical_sha256(bounded)
    print(
        "noteai_v10_progress_diagnostic="
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


def _metadata_parts(metadata: dict[str, Any]):
    provenance = metadata.get("buildx.build.provenance")
    _require(
        isinstance(provenance, dict),
        "PROVENANCE_ROOT_INVALID",
        "BuildKit provenance missing",
    )
    invocation = provenance.get("invocation")
    parameters = invocation.get("parameters") if isinstance(invocation, dict) else None
    args = parameters.get("args") if isinstance(parameters, dict) else None
    build_config = provenance.get("buildConfig")
    _require(
        isinstance(args, dict) and isinstance(build_config, dict),
        "PROVENANCE_BUILD_CONFIG_INVALID",
        "BuildKit invocation or max provenance changed",
    )
    provenance_metadata = provenance.get("metadata")
    source_metadata = (
        provenance_metadata.get(
            "https://mobyproject.org/buildkit@v1#metadata"
        )
        if isinstance(provenance_metadata, dict)
        else None
    )
    source = source_metadata.get("source") if isinstance(source_metadata, dict) else None
    _require(
        isinstance(source, dict),
        "PROVENANCE_LOCATION_INVALID",
        "BuildKit source metadata changed",
    )
    return provenance, args, build_config, source


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
        raise V10BundleError(
            "PROVENANCE_DOCKERFILE_INVALID",
            "Dockerfile provenance base64 invalid",
        ) from exc


def _step_graph(build_config: dict[str, Any]):
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
            and _v6.STEP_RE.fullmatch(step_id) is not None
            and step_id not in steps,
            "PROVENANCE_STEP_INVALID",
            "BuildKit LLB step id changed",
        )
        op = item.get("op")
        union = op.get("Op") if isinstance(op, dict) else None
        raw_inputs = item.get("inputs", [])
        _require(
            isinstance(op, dict)
            and isinstance(union, dict)
            and isinstance(raw_inputs, list),
            "PROVENANCE_STEP_INVALID",
            "BuildKit LLB step changed",
        )
        inputs: list[tuple[str, int]] = []
        for raw_input in raw_inputs:
            _require(
                isinstance(raw_input, str)
                and raw_input.count(":") == 1,
                "PROVENANCE_STEP_INPUT_INVALID",
                "BuildKit LLB input changed",
            )
            parent, raw_index = raw_input.split(":", 1)
            _require(
                _v6.STEP_RE.fullmatch(parent) is not None
                and raw_index.isdigit(),
                "PROVENANCE_STEP_INPUT_INVALID",
                "BuildKit LLB input changed",
            )
            inputs.append((parent, int(raw_index)))
        steps[step_id] = {
            "item": item,
            "op": op,
            "union": union,
            "exec": union.get("exec") if set(union) == {"exec"} else None,
            "platform": op.get("platform"),
            "inputs": inputs,
        }
    for step in steps.values():
        _require(
            all(parent in steps for parent, _index in step["inputs"]),
            "PROVENANCE_STEP_INPUT_INVALID",
            "BuildKit LLB input references an unknown step",
        )

    step_to_digests: dict[str, list[str]] = {}
    seen_digests: set[str] = set()
    for raw_digest, raw_step in digest_mapping.items():
        digest = _v6._canonical_digest(
            raw_digest,
            "BuildKit digest mapping",
        )
        _require(
            digest not in seen_digests
            and isinstance(raw_step, str)
            and raw_step in steps,
            "PROVENANCE_DIGEST_MAPPING_INVALID",
            "BuildKit digest mapping changed",
        )
        seen_digests.add(digest)
        step_to_digests.setdefault(raw_step, []).append(digest)
    return steps, step_to_digests


def _location_starts(location: Any, step_id: str) -> set[int]:
    try:
        return set(_v6._range_projection(location, step_id)["starts"])
    except _v6.V6BundleError as exc:
        raise V10BundleError(exc.failure_code, str(exc)) from None


def _step_for_line(
    source: dict[str, Any],
    steps: dict[str, dict[str, Any]],
    line: int,
) -> str:
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
        if location == {}:
            continue
        if line in _location_starts(location, step_id):
            matches.append(step_id)
    _require(
        len(matches) == 1,
        "PROVENANCE_ROLE_LOCATION_AMBIGUOUS",
        f"BuildKit source binding changed for line {line}",
    )
    return matches[0]


def _digest_for_step(
    step_to_digests: dict[str, list[str]],
    step_id: str,
    *,
    label: str,
) -> str:
    digests = step_to_digests.get(step_id, [])
    _require(
        len(digests) == 1,
        "PROVENANCE_ROLE_DIGEST_AMBIGUOUS",
        f"BuildKit {label} digest binding changed",
    )
    return digests[0]


def _strict_progress_view(
    progress_bytes: bytes,
    progress_path: Path,
    *,
    dockerfile_kind: str,
    require_network_vertices_cached: bool,
):
    diagnostic = _v9._initial_diagnostic(
        progress_path,
        dockerfile_kind=dockerfile_kind,
        require_network_vertices_cached=require_network_vertices_cached,
    )
    try:
        return _v9._strict_progress(progress_bytes, diagnostic), diagnostic
    except _v9.V9BundleError as exc:
        raise V10BundleError(exc.failure_code, str(exc)) from None


def _interval_summary(
    *,
    role: str,
    line: int,
    step_id: str,
    digest: str,
    vertex: dict[str, Any],
    require_cached: bool,
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
        _require(
            interval["cached"] is require_cached,
            (
                "NETWORK_VERTEX_NOT_CACHED"
                if require_cached
                else "PRODUCER_NETWORK_VERTEX_CACHED"
            ),
            (
                f"BuildKit {role} vertex was not cached"
                if require_cached
                else f"BuildKit producer {role} vertex was cached"
            ),
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
        "noncached_interval_count": sum(int(not item["cached"]) for item in projected),
        "intervals": projected,
    }


def _role_interval_projection(
    metadata: dict[str, Any],
    source: dict[str, Any],
    steps: dict[str, dict[str, Any]],
    step_to_digests: dict[str, list[str]],
    vertices: dict[str, dict[str, Any]],
    *,
    require_cached: bool,
) -> list[dict[str, Any]]:
    build_window = _v7._provenance_build_window(metadata)
    results: list[dict[str, Any]] = []
    for spec in _v6.ROLE_SPECS:
        step_id = _step_for_line(source, steps, int(spec["line"]))
        step = steps[step_id]
        _require(
            isinstance(step["exec"], dict)
            and step["platform"] == {"Architecture": "amd64", "OS": "linux"},
            "PROVENANCE_ROLE_NOT_EXEC",
            f"BuildKit {spec['role']} structural binding changed",
        )
        digest = _digest_for_step(
            step_to_digests,
            step_id,
            label=str(spec["role"]),
        )
        _require(
            digest in vertices,
            "PROVENANCE_ROLE_VERTEX_MISSING",
            f"BuildKit {spec['role']} progress vertex missing",
        )
        results.append(
            _interval_summary(
                role=str(spec["role"]),
                line=int(spec["line"]),
                step_id=step_id,
                digest=digest,
                vertex=vertices[digest],
                require_cached=require_cached,
                build_window=build_window,
            )
        )
    return results


def _forbidden_exec_capability(value: Any, *, parent_key: str = "") -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = key.lower()
            if lowered in {"secretenv", "secret_env", "ssh"} and child not in (None, [], {}):
                return True
            if lowered in {"mounttype", "mount_type"} and isinstance(child, str) and child.upper() in {"SECRET", "SSH"}:
                return True
            if _forbidden_exec_capability(child, parent_key=lowered):
                return True
        return False
    if isinstance(value, list):
        return any(_forbidden_exec_capability(item, parent_key=parent_key) for item in value)
    return False


def _observer_progress_inputs(
    progress_bytes: bytes,
    *,
    observer_digest: str,
    pip_digest: str,
) -> tuple[int, int]:
    explicit = 0
    omitted = 0
    for line_number, raw_line in enumerate(progress_bytes.splitlines(), start=1):
        if not raw_line.strip():
            continue
        event = _v6._v3.strict_json_bytes(
            raw_line,
            f"BuildKit rawjson line {line_number}",
        )
        for vertex in event.get("vertexes", []) if isinstance(event, dict) else []:
            if isinstance(vertex, dict) and vertex.get("digest") == observer_digest:
                if "inputs" not in vertex:
                    omitted += 1
                    continue
                _require(
                    vertex["inputs"] == [pip_digest],
                    "OBSERVER_PROGRESS_INPUT_INVALID",
                    "BuildKit observer progress parent changed",
                )
                explicit += 1
    _require(
        explicit > 0,
        "OBSERVER_PROGRESS_INPUT_MISSING",
        "BuildKit observer progress parent is unbound",
    )
    return explicit, omitted


def _observer_validation(
    metadata: dict[str, Any],
    progress_bytes: bytes,
    source: dict[str, Any],
    steps: dict[str, dict[str, Any]],
    step_to_digests: dict[str, list[str]],
    vertices: dict[str, dict[str, Any]],
    log_streams: dict[tuple[str, int], bytearray],
) -> tuple[dict[str, Any], str, bytes]:
    decoded = _decoded_dockerfile(source)
    _require(
        len(decoded) == OBSERVER_DOCKERFILE_BYTES
        and decoded.count(b"\n") == OBSERVER_DOCKERFILE_LINES
        and hashlib.sha256(decoded).hexdigest() == OBSERVER_DOCKERFILE_SHA256
        and decoded.endswith(OBSERVER_SUFFIX)
        and hashlib.sha256(OBSERVER_SUFFIX).hexdigest() == OBSERVER_SUFFIX_SHA256,
        "OBSERVER_DOCKERFILE_INVALID",
        "consumer observer Dockerfile changed",
    )
    base_prefix = decoded[: -len(OBSERVER_SUFFIX)]
    _require(
        hashlib.sha256(base_prefix).hexdigest() == BASE_PREFIX_SHA256,
        "OBSERVER_DOCKERFILE_INVALID",
        "consumer observer base prefix changed",
    )
    pip_step = _step_for_line(source, steps, 76)
    observer_step = _step_for_line(source, steps, OBSERVER_LINE)
    observer = steps[observer_step]
    _require(
        isinstance(observer["exec"], dict)
        and observer["platform"] == {"Architecture": "amd64", "OS": "linux"}
        and observer["inputs"] == [(pip_step, 0)],
        "OBSERVER_PROVENANCE_BINDING_INVALID",
        "BuildKit observer structural binding changed",
    )
    exec_op = observer["exec"]
    _require(
        exec_op.get("network") == 2
        and exec_op.get("security", 0) == 0
        and not _forbidden_exec_capability(exec_op),
        "OBSERVER_NETWORK_OR_SECRET_INVALID",
        "BuildKit observer network or secret contract changed",
    )
    pip_digest = _digest_for_step(step_to_digests, pip_step, label="runtime_pip")
    observer_digest = _digest_for_step(
        step_to_digests,
        observer_step,
        label="observer",
    )
    _require(
        observer_digest in vertices,
        "OBSERVER_PROGRESS_VERTEX_MISSING",
        "BuildKit observer progress vertex missing",
    )
    explicit_inputs, omitted_inputs = _observer_progress_inputs(
        progress_bytes,
        observer_digest=observer_digest,
        pip_digest=pip_digest,
    )
    build_window = _v7._provenance_build_window(metadata)
    observer_interval = _interval_summary(
        role="cache_observer",
        line=OBSERVER_LINE,
        step_id=observer_step,
        digest=observer_digest,
        vertex=vertices[observer_digest],
        require_cached=False,
        build_window=build_window,
    )
    _require(
        observer_interval["interval_count"] == 1,
        "OBSERVER_INTERVAL_INVALID",
        "BuildKit observer lifecycle changed",
    )
    observer_streams = {
        stream: bytes(payload)
        for (digest, stream), payload in log_streams.items()
        if digest == observer_digest
    }
    _require(
        all(
            OBSERVER_MARKER not in bytes(payload)
            for (digest, _stream), payload in log_streams.items()
            if digest != observer_digest
        ),
        "OBSERVER_MARKER_MISBOUND",
        "BuildKit observer marker is bound to another vertex",
    )
    _require(
        observer_streams == {1: OBSERVER_MARKER},
        "OBSERVER_MARKER_INVALID",
        "BuildKit observer decoded marker changed",
    )
    return (
        {
            "line": OBSERVER_LINE,
            "step_id": observer_step,
            "vertex_digest": observer_digest,
            "direct_parent_step_id": pip_step,
            "direct_parent_vertex_digest": pip_digest,
            "platform": "linux/amd64",
            "network_mode": "NONE",
            "network_enum": 2,
            "progress_explicit_input_update_count": explicit_inputs,
            "progress_omitted_input_update_count": omitted_inputs,
            "interval": observer_interval,
            "decoded_log_stream_count": 1,
            "decoded_log_bytes": len(OBSERVER_MARKER),
            "marker_occurrence_count": 1,
        },
        observer_step,
        base_prefix,
    )


def _full_witness_validation(
    metadata: dict[str, Any],
    source: dict[str, Any],
    steps: dict[str, dict[str, Any]],
    step_to_digests: dict[str, list[str]],
    vertices: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    pip_step = _step_for_line(source, steps, 76)
    witness_step = _step_for_line(source, steps, FULL_WITNESS_LINE)
    witness = steps[witness_step]
    _require(
        isinstance(witness["exec"], dict)
        and witness["platform"] == {"Architecture": "amd64", "OS": "linux"},
        "FULL_WITNESS_PROVENANCE_INVALID",
        "BuildKit full replay witness changed",
    )
    visiting: set[str] = set()
    visited: set[str] = set()

    def reaches_pip(step_id: str) -> tuple[bool, int]:
        if step_id == pip_step:
            return True, 0
        _require(
            step_id not in visiting,
            "PROVENANCE_STEP_CYCLE",
            "BuildKit LLB graph contains a cycle",
        )
        if step_id in visited:
            return False, 0
        visiting.add(step_id)
        best = -1
        for parent, _index in steps[step_id]["inputs"]:
            found, distance = reaches_pip(parent)
            if found:
                best = max(best, distance + 1)
        visiting.remove(step_id)
        visited.add(step_id)
        return (best >= 0, max(best, 0))

    found, distance = reaches_pip(witness_step)
    _require(
        found and distance > 0,
        "FULL_WITNESS_NOT_POST_PIP",
        "BuildKit full replay witness is not a runtime_pip descendant",
    )
    witness_digest = _digest_for_step(
        step_to_digests,
        witness_step,
        label="full replay witness",
    )
    _require(
        witness_digest in vertices,
        "FULL_WITNESS_PROGRESS_VERTEX_MISSING",
        "BuildKit full replay witness progress vertex missing",
    )
    interval = _interval_summary(
        role="full_post_pip_witness",
        line=FULL_WITNESS_LINE,
        step_id=witness_step,
        digest=witness_digest,
        vertex=vertices[witness_digest],
        require_cached=False,
        build_window=_v7._provenance_build_window(metadata),
    )
    _require(
        interval["interval_count"] == 1,
        "FULL_WITNESS_INTERVAL_INVALID",
        "BuildKit full replay witness lifecycle changed",
    )
    return {
        "line": FULL_WITNESS_LINE,
        "step_id": witness_step,
        "vertex_digest": witness_digest,
        "runtime_pip_step_id": pip_step,
        "runtime_pip_ancestor": True,
        "ancestry_path_length": distance,
        "interval": interval,
        "runtime_pip_terminal": False,
    }


@contextmanager
def _legacy_observer_metadata(
    metadata: dict[str, Any],
    *,
    observer_step: str,
    base_prefix: bytes,
) -> Iterator[Path]:
    legacy = copy.deepcopy(metadata)
    _provenance, args, _build_config, source = _metadata_parts(legacy)
    args["target"] = "runtime-common"
    source["infos"][0]["data"] = base64.b64encode(base_prefix).decode("ascii")
    source["locations"][observer_step] = {}
    payload = json.dumps(
        legacy,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    temporary_root = Path(tempfile.mkdtemp(prefix="noteai-v10-legacy-"))
    legacy_path = temporary_root / "metadata.json"
    try:
        _v6._write_exclusive_regular(legacy_path, payload)
        _require(
            stat.S_IMODE(legacy_path.stat().st_mode) == 0o600,
            "LEGACY_EVIDENCE_FILE_INVALID",
            "V10 legacy metadata mode changed",
        )
        yield legacy_path
    finally:
        try:
            shutil.rmtree(temporary_root)
        except OSError as exc:
            raise V10BundleError(
                "LEGACY_EVIDENCE_CLEANUP_FAILED",
                "V10 legacy metadata cleanup failed",
            ) from exc
        _require(
            not temporary_root.exists() and not temporary_root.is_symlink(),
            "LEGACY_EVIDENCE_CLEANUP_FAILED",
            "V10 legacy metadata cleanup incomplete",
        )


@contextmanager
def _frozen_v9_internal_for_delegate() -> Iterator[None]:
    current = _v9._validate_build_evidence
    if current is _chain_validate_build_evidence:
        _v9._validate_build_evidence = _FROZEN_V9_INTERNAL_VALIDATE_BUILD_EVIDENCE
    else:
        _require(
            current is _FROZEN_V9_INTERNAL_VALIDATE_BUILD_EVIDENCE,
            "FROZEN_V9_DISPATCH_CHANGED",
            "frozen V9 validator dispatch changed",
        )
    try:
        yield
    finally:
        _v9._validate_build_evidence = current


def _delegate_v9(*args: Any, **kwargs: Any) -> dict[str, Any]:
    with _frozen_v9_internal_for_delegate():
        _assert_frozen_dispatch()
        try:
            return _FROZEN_V9_VALIDATE_BUILD_EVIDENCE(*args, **kwargs)
        except _v6._v3.BundleError as exc:
            failure_code = getattr(
                exc,
                "failure_code",
                "FROZEN_V9_EVIDENCE_INVALID",
            )
            raise _FrozenV9Rejection(
                failure_code,
                "frozen V9 build evidence invalid",
            ) from None


def _delegate_v9_nested(*args: Any, **kwargs: Any) -> dict[str, Any]:
    _assert_expected_nested_dispatch()
    try:
        return _FROZEN_V9_INTERNAL_VALIDATE_BUILD_EVIDENCE(*args, **kwargs)
    except _v6._v3.BundleError as exc:
        failure_code = getattr(
            exc,
            "failure_code",
            "FROZEN_V9_EVIDENCE_INVALID",
        )
        raise _FrozenV9Rejection(
            failure_code,
            "frozen V9 build evidence invalid",
        ) from None


def _validate_build_evidence_impl(
    metadata_path: Path,
    progress_path: Path,
    *,
    dockerfile_kind: str,
    require_network_vertices_cached: bool,
    nested_dispatch: bool = False,
) -> dict[str, Any]:
    metadata_path = Path(metadata_path)
    progress_path = Path(progress_path)
    assert_dispatch = (
        _assert_expected_nested_dispatch
        if nested_dispatch
        else _assert_frozen_dispatch
    )
    assert_dispatch()
    metadata_bytes = _v6._read_regular_bytes(
        metadata_path,
        maximum_bytes=_v6.MAXIMUM_METADATA_BYTES,
        failure_code="METADATA_FILE_INVALID",
        label="BuildKit metadata",
    )
    progress_bytes = _v6._read_regular_bytes(
        progress_path,
        maximum_bytes=_v6.MAXIMUM_PROGRESS_BYTES,
        failure_code="RAWJSON_FILE_INVALID",
        label="BuildKit rawjson",
    )
    diagnostic = _initial_diagnostic(
        metadata_bytes,
        progress_bytes,
        dockerfile_kind=dockerfile_kind,
        require_network_vertices_cached=require_network_vertices_cached,
    )
    try:
        assert_dispatch()
        _require(
            dockerfile_kind in {"prefix", "full"},
            "DOCKERFILE_KIND_INVALID",
            "Dockerfile kind changed",
        )
        metadata = _v6._v3.strict_json_bytes(
            metadata_bytes,
            "BuildKit metadata",
        )
        _require(
            isinstance(metadata, dict),
            "PROVENANCE_ROOT_INVALID",
            "BuildKit metadata root changed",
        )
        _provenance, args, build_config, source = _metadata_parts(metadata)
        target = args.get("target")
        decoded = _decoded_dockerfile(source)
        ((vertices, _names, log_streams, _refs, _plain), parse_diagnostic) = (
            _strict_progress_view(
                progress_bytes,
                progress_path,
                dockerfile_kind=dockerfile_kind,
                require_network_vertices_cached=require_network_vertices_cached,
            )
        )
        steps, step_to_digests = _step_graph(build_config)
        diagnostic["parse_completed"] = True

        observer: dict[str, Any] | None = None
        witness: dict[str, Any] | None = None
        legacy_path: Path | None = None
        observer_step = ""
        base_prefix = b""
        if dockerfile_kind == "prefix" and target == OBSERVER_TARGET:
            diagnostic["projection_kind"] = "observer-prefix"
            diagnostic["observer_required"] = True
            _require(
                require_network_vertices_cached,
                "OBSERVER_CACHE_MODE_INVALID",
                "observer prefix is only valid for a cache replay",
            )
            observer, observer_step, base_prefix = _observer_validation(
                metadata,
                progress_bytes,
                source,
                steps,
                step_to_digests,
                vertices,
                log_streams,
            )
            diagnostic["observer_binding_completed"] = True
        elif dockerfile_kind == "prefix" and target == "runtime-common":
            diagnostic["projection_kind"] = "producer-prefix"
            _require(
                not require_network_vertices_cached,
                "PRODUCER_CACHE_MODE_INVALID",
                "producer prefix cannot satisfy a cache replay",
            )
            _require(
                hashlib.sha256(decoded).hexdigest() == BASE_PREFIX_SHA256,
                "PRODUCER_PREFIX_CHANGED",
                "producer dependency prefix changed",
            )
        elif dockerfile_kind == "full" and target == "runtime-common":
            diagnostic["projection_kind"] = "full-runtime-common"
            _require(
                require_network_vertices_cached,
                "FULL_REPLAY_CACHE_MODE_INVALID",
                "full replay must retain the imported dependency cache",
            )
            witness = _full_witness_validation(
                metadata,
                source,
                steps,
                step_to_digests,
                vertices,
            )
        else:
            _fail(
                "V10_TARGET_INVALID",
                "V10 Dockerfile target changed",
            )

        role_intervals = _role_interval_projection(
            metadata,
            source,
            steps,
            step_to_digests,
            vertices,
            require_cached=require_network_vertices_cached,
        )
        diagnostic["role_binding_completed"] = True
        diagnostic["interval_projection_completed"] = True
        diagnostic["role_intervals"] = role_intervals
        diagnostic["observer"] = observer
        diagnostic["full_post_pip_witness"] = witness

        if observer is not None:
            with _legacy_observer_metadata(
                metadata,
                observer_step=observer_step,
                base_prefix=base_prefix,
            ) as legacy_path:
                delegate = _delegate_v9_nested if nested_dispatch else _delegate_v9
                summary = delegate(
                    legacy_path,
                    progress_path,
                    dockerfile_kind="prefix",
                    require_network_vertices_cached=True,
                )
            summary["metadata_sha256"] = hashlib.sha256(metadata_bytes).hexdigest()
            summary["dockerfile_sha256"] = OBSERVER_DOCKERFILE_SHA256
        else:
            delegate = _delegate_v9_nested if nested_dispatch else _delegate_v9
            summary = delegate(
                metadata_path,
                progress_path,
                dockerfile_kind=dockerfile_kind,
                require_network_vertices_cached=require_network_vertices_cached,
            )
        v9_diagnostic = summary.pop("v9_rawjson_diagnostic")
        diagnostic["v9_diagnostic_sha256"] = v9_diagnostic["diagnostic_sha256"]
        _require(
            _v6._read_regular_bytes(
                metadata_path,
                maximum_bytes=_v6.MAXIMUM_METADATA_BYTES,
                failure_code="METADATA_FILE_INVALID",
                label="BuildKit metadata",
            )
            == metadata_bytes
            and _v6._read_regular_bytes(
                progress_path,
                maximum_bytes=_v6.MAXIMUM_PROGRESS_BYTES,
                failure_code="RAWJSON_FILE_INVALID",
                label="BuildKit rawjson",
            )
            == progress_bytes,
            "ORIGINAL_EVIDENCE_CHANGED",
            "original BuildKit evidence changed during validation",
        )
        assert_dispatch()
        diagnostic["v10_root_cause_status"] = "NO_FAILURE"
        diagnostic["failure_code"] = "NONE"
        diagnostic["verdict"] = "pass"
        bounded = _emit_diagnostic(diagnostic)
        summary["v10_rawjson_diagnostic"] = bounded
        return summary
    except _FrozenV9Rejection as exc:
        diagnostic["v10_root_cause_status"] = "FROZEN_V9_REJECTION"
        diagnostic["failure_code"] = exc.failure_code
        diagnostic["verdict"] = "fail"
        _emit_diagnostic(diagnostic)
        raise V10BundleError(exc.failure_code, str(exc)) from None
    except V10BundleError as exc:
        diagnostic["v10_root_cause_status"] = "DETERMINED_BY_V10"
        diagnostic["failure_code"] = exc.failure_code
        diagnostic["verdict"] = "fail"
        _emit_diagnostic(diagnostic)
        raise
    except _v9.V9BundleError as exc:
        diagnostic["v10_root_cause_status"] = "FROZEN_V9_REJECTION"
        diagnostic["failure_code"] = exc.failure_code
        diagnostic["verdict"] = "fail"
        _emit_diagnostic(diagnostic)
        raise V10BundleError(exc.failure_code, str(exc)) from None
    except _v6._v3.BundleError as exc:
        failure_code = getattr(exc, "failure_code", "V10_EVIDENCE_INVALID")
        diagnostic["v10_root_cause_status"] = "DETERMINED_BY_V10"
        diagnostic["failure_code"] = failure_code
        diagnostic["verdict"] = "fail"
        _emit_diagnostic(diagnostic)
        raise V10BundleError(
            failure_code,
            "V10 build evidence invalid",
        ) from None
    except OSError as exc:
        diagnostic["v10_root_cause_status"] = "V10_IO_FAILURE"
        diagnostic["failure_code"] = "V10_IO_FAILED"
        diagnostic["verdict"] = "fail"
        _emit_diagnostic(diagnostic)
        raise V10BundleError("V10_IO_FAILED", "V10 evidence I/O failed") from exc
    except Exception:
        diagnostic["v10_root_cause_status"] = "V10_UNEXPECTED_FAILURE"
        diagnostic["failure_code"] = "V10_UNEXPECTED_FAILURE"
        diagnostic["verdict"] = "fail"
        _emit_diagnostic(diagnostic)
        raise V10BundleError(
            "V10_UNEXPECTED_FAILURE",
            "V10 evidence validation failed unexpectedly",
        ) from None


def _chain_validate_build_evidence(*args: Any, **kwargs: Any):
    with _frozen_v9_internal_for_delegate():
        return _validate_build_evidence_impl(
            *args,
            nested_dispatch=True,
            **kwargs,
        )


@contextmanager
def _patched_v9_observer_contract() -> Iterator[None]:
    with _PATCH_LOCK:
        _assert_frozen_dispatch()
        _require(
            _v9._validate_build_evidence
            is _FROZEN_V9_INTERNAL_VALIDATE_BUILD_EVIDENCE,
            "FROZEN_V9_DISPATCH_CHANGED",
            "frozen V9 validator dispatch changed",
        )
        _v9._validate_build_evidence = _chain_validate_build_evidence
        try:
            yield
        finally:
            _v9._validate_build_evidence = (
                _FROZEN_V9_INTERNAL_VALIDATE_BUILD_EVIDENCE
            )
            _assert_frozen_dispatch()


def __getattr__(name: str):
    return getattr(_v9, name)


def validate_build_evidence(*args: Any, **kwargs: Any):
    with _PATCH_LOCK:
        return _validate_build_evidence_impl(*args, **kwargs)


def validate_core(*args: Any, **kwargs: Any):
    with _PATCH_LOCK:
        _assert_frozen_dispatch()
        return _FROZEN_V9_VALIDATE_CORE(*args, **kwargs)


def validate_final(*args: Any, **kwargs: Any):
    with _patched_v9_observer_contract():
        return _FROZEN_V9_VALIDATE_FINAL(*args, **kwargs)


def main() -> int:
    args = _v9.build_parser().parse_args()
    try:
        if args.command == "verify-core":
            manifest = validate_core(
                args.bundle.resolve(),
                args.extract_to.resolve(),
            )
            payload = {
                "manifest_sha256": _v9.sha256_file(
                    args.bundle / "manifest.json"
                ),
                "core_sums_sha256": _v9.sha256_file(
                    args.bundle / "CORE_SHA256SUMS"
                ),
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
        _v9.write_json(args.output.resolve() if args.output else None, payload)
    except (_v6._v3.BundleError, OSError) as exc:
        print(f"FAIL: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
