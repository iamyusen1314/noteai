#!/usr/bin/env python3
"""Accept source-proven omitted vertex inputs over the frozen V8 chain.

BuildKit v0.31.2 emits incremental rawjson vertex values. Structural values
may carry ordered nonempty inputs while same-digest lifecycle values may omit
that JSON member. V9 treats only an absent member as nonbinding. It does not
reconstruct V8 runtime vectors, rewrite evidence, infer a leaf from omission,
or broaden any frozen location, lifecycle, role, log, cache, archive, trust,
cleanup, or authorization rule.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


V8_VERIFIER_SHA256 = (
    "b07f9dee54862969fe90ef438c357a34"
    "45a9fe9574b69a9f87440e3ed9920300"
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


def _load_v8_verifier():
    configured = os.environ.get("NOTEAI_V8_BUNDLE_VERIFIER_PATH")
    configured_path = (
        Path(configured)
        if configured
        else Path(__file__).with_name(
            "verify_admin_dependency_cache_bundle_v8.py"
        )
    )
    if configured_path.is_symlink():
        raise RuntimeError("frozen V8 bundle verifier file contract changed")
    v8_path = configured_path.resolve()
    v8_source = _read_frozen_source(
        v8_path,
        label="frozen V8 bundle verifier",
    )
    if hashlib.sha256(v8_source).hexdigest() != V8_VERIFIER_SHA256:
        raise RuntimeError("frozen V8 bundle verifier hash drift")

    module_name = "_noteai_admin_dependency_cache_bundle_v8_for_v9"
    module = types.ModuleType(module_name)
    module.__file__ = str(v8_path)
    module.__package__ = ""
    sys.modules[module_name] = module
    try:
        exec(
            compile(v8_source, str(v8_path), "exec"),
            module.__dict__,
        )
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


_v8 = _load_v8_verifier()
_v7 = _v8._v7
_v6 = _v8._v6
_FROZEN_V8_INITIAL_DIAGNOSTIC = _v8._initial_diagnostic
_FROZEN_V8_EMIT_DIAGNOSTIC = _v8._emit_diagnostic
_FROZEN_V8_INTERNAL_VALIDATE_BUILD_EVIDENCE = (
    _v8._validate_build_evidence
)
_FROZEN_V7_STRICT_PROGRESS = _v7._strict_progress
_FROZEN_V8_VALIDATE_BUILD_EVIDENCE = _v8.validate_build_evidence
_FROZEN_V8_VALIDATE_CORE = _v8.validate_core
_FROZEN_V8_VALIDATE_FINAL = _v8.validate_final
_FROZEN_V8_MAIN = _v8.main

MAXIMUM_VERTEX_UPDATES = _v7.MAXIMUM_VERTEX_UPDATES
MAXIMUM_VERTEX_DIGESTS = _v7.MAXIMUM_VERTEX_DIGESTS
MAXIMUM_INPUTS_PER_DIGEST = _v7.MAXIMUM_INPUTS_PER_DIGEST
MAXIMUM_NAME_BYTES = _v7.MAXIMUM_NAME_BYTES
MAXIMUM_NAMES_PER_DIGEST = _v7.MAXIMUM_NAMES_PER_DIGEST
MAXIMUM_INTERVALS_PER_DIGEST = _v7.MAXIMUM_INTERVALS_PER_DIGEST
_progress_group = _v7._progress_group
_exact_optional_time = _v7._exact_optional_time
_canonical_vertex = _v7._canonical_vertex
_FROZEN_INITIAL_DIAGNOSTIC = _v7._FROZEN_INITIAL_DIAGNOSTIC
_FROZEN_STRICT_PROGRESS = _v7._FROZEN_STRICT_PROGRESS
_FROZEN_V8_MODULE = _v8
_FROZEN_V7_MODULE = _v7
_FROZEN_V6_MODULE = _v6
_FROZEN_V3_MODULE = _v6._v3
_FROZEN_V2_MODULE = _FROZEN_V3_MODULE._base
_FROZEN_CHAIN_PATCH_LOCK = _v6._PATCH_LOCK


def _frozen_module_globals(module: types.ModuleType):
    return tuple(sorted(module.__dict__.items(), key=lambda item: item[0]))


_FROZEN_CHAIN_GLOBALS = tuple(
    (module, _frozen_module_globals(module))
    for module in (
        _FROZEN_V8_MODULE,
        _FROZEN_V7_MODULE,
        _FROZEN_V6_MODULE,
        _FROZEN_V3_MODULE,
        _FROZEN_V2_MODULE,
    )
)


class V9BundleError(_v8.V8BundleError):
    """A fixed-code V9 failure safe for a public workflow log."""


def _fail(failure_code: str, message: str) -> None:
    raise V9BundleError(failure_code, message)


def _require(
    condition: bool,
    failure_code: str,
    message: str,
) -> None:
    if not condition:
        _fail(failure_code, message)


def _assert_frozen_dispatch() -> None:
    _require(
        _v8 is _FROZEN_V8_MODULE
        and _v7 is _FROZEN_V7_MODULE
        and _v6 is _FROZEN_V6_MODULE
        and _v6._v3 is _FROZEN_V3_MODULE
        and _FROZEN_V3_MODULE._base is _FROZEN_V2_MODULE,
        "FROZEN_V8_DISPATCH_CHANGED",
        "frozen V8 validator dispatch changed",
    )
    for module, expected_globals in _FROZEN_CHAIN_GLOBALS:
        current_globals = module.__dict__
        _require(
            tuple(sorted(current_globals))
            == tuple(name for name, _expected in expected_globals),
            "FROZEN_V8_DISPATCH_CHANGED",
            "frozen V8 validator dispatch changed",
        )
        for name, expected in expected_globals:
            _require(
                current_globals[name] is expected,
                "FROZEN_V8_DISPATCH_CHANGED",
                "frozen V8 validator dispatch changed",
            )


def _initial_diagnostic(
    progress_path: Path,
    *,
    dockerfile_kind: str,
    require_network_vertices_cached: bool,
) -> dict[str, Any]:
    diagnostic = _FROZEN_V8_INITIAL_DIAGNOSTIC(
        progress_path,
        dockerfile_kind=dockerfile_kind,
        require_network_vertices_cached=require_network_vertices_cached,
    )
    diagnostic["schema_version"] = (
        "noteai.admin-dependency-cache-v9-diagnostic.v1"
    )
    diagnostic["input_omitted_update_count"] = 0
    diagnostic["input_explicit_nonempty_update_count"] = 0
    diagnostic["input_bound_vertex_digest_count"] = 0
    diagnostic["input_omission_only_vertex_digest_count"] = 0
    diagnostic["input_mixed_presence_vertex_digest_count"] = 0
    return diagnostic


def _emit_diagnostic(diagnostic: dict[str, Any]) -> dict[str, Any]:
    bounded = dict(diagnostic)
    bounded["diagnostic_sha256"] = _v6._canonical_sha256(bounded)
    print(
        "noteai_v9_progress_diagnostic="
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


def _bind_vertex_inputs(
    vertex: dict[str, Any],
    state: dict[str, Any],
    diagnostic: dict[str, Any],
) -> None:
    if "inputs" not in vertex:
        diagnostic["input_omitted_update_count"] += 1
        if not state["input_omission_seen"]:
            state["input_omission_seen"] = True
            if state["inputs"] is None:
                diagnostic[
                    "input_omission_only_vertex_digest_count"
                ] += 1
            elif not state["input_mixed_counted"]:
                state["input_mixed_counted"] = True
                diagnostic[
                    "input_mixed_presence_vertex_digest_count"
                ] += 1
        return

    inputs = vertex["inputs"]
    _require(
        isinstance(inputs, list)
        and bool(inputs)
        and len(inputs) <= MAXIMUM_INPUTS_PER_DIGEST,
        "RAWJSON_VERTEX_INPUT_INVALID",
        "BuildKit vertex inputs changed",
    )
    input_vector = tuple(
        _v6._canonical_digest(
            raw_input,
            "BuildKit vertex input",
        )
        for raw_input in inputs
    )
    diagnostic["input_explicit_nonempty_update_count"] += 1
    if state["inputs"] is None:
        state["inputs"] = input_vector
        state["input_explicit_seen"] = True
        diagnostic["input_bound_vertex_digest_count"] += 1
        if state["input_omission_seen"]:
            diagnostic[
                "input_omission_only_vertex_digest_count"
            ] -= 1
            if not state["input_mixed_counted"]:
                state["input_mixed_counted"] = True
                diagnostic[
                    "input_mixed_presence_vertex_digest_count"
                ] += 1
        return

    if not state["input_explicit_seen"]:
        state["input_explicit_seen"] = True
    _require(
        state["inputs"] == input_vector,
        "RAWJSON_VERTEX_INPUT_CONFLICT",
        "BuildKit vertex inputs conflict",
    )


def _strict_progress(
    progress_bytes: bytes,
    diagnostic: dict[str, Any],
):
    diagnostic["progress_bytes"] = len(progress_bytes)
    diagnostic["progress_sha256"] = hashlib.sha256(
        progress_bytes
    ).hexdigest()
    states: dict[str, dict[str, Any]] = {}
    retained_non_vertex_events: list[dict[str, Any]] = []
    vertex_update_count = 0

    for line_number, raw_line in enumerate(
        progress_bytes.splitlines(keepends=True),
        start=1,
    ):
        _require(
            line_number <= _v6.MAXIMUM_PROGRESS_LINES,
            "RAWJSON_LINE_LIMIT_EXCEEDED",
            "BuildKit rawjson line limit changed",
        )
        if not raw_line.strip():
            continue
        diagnostic["nonblank_line_count"] += 1
        event = _v6._v3.strict_json_bytes(
            raw_line,
            f"BuildKit rawjson line {line_number}",
        )
        _require(
            isinstance(event, dict)
            and bool(event)
            and set(event) <= _v6.TOP_LEVEL_KEYS,
            "RAWJSON_TOP_LEVEL_INVALID",
            "BuildKit rawjson top-level schema changed",
        )
        for key, values in event.items():
            _require(
                isinstance(values, list) and bool(values),
                "RAWJSON_ARRAY_INVALID",
                f"BuildKit rawjson {key} changed",
            )

        event_intervals: dict[tuple[str, int], dict[str, Any]] = {}
        for raw_vertex in event.get("vertexes", []):
            vertex_update_count += 1
            _require(
                vertex_update_count <= MAXIMUM_VERTEX_UPDATES,
                "RAWJSON_VERTEX_LIMIT_EXCEEDED",
                "BuildKit vertex update limit changed",
            )
            vertex = _v6._validate_item_keys(
                raw_vertex,
                _v6.VERTEX_KEYS,
                "BuildKit vertex",
            )
            digest = _v6._canonical_digest(
                vertex.get("digest"),
                "BuildKit vertex",
            )
            if digest not in states:
                _require(
                    len(states) < MAXIMUM_VERTEX_DIGESTS,
                    "RAWJSON_VERTEX_LIMIT_EXCEEDED",
                    "BuildKit vertex digest limit changed",
                )
                states[digest] = {
                    "inputs": None,
                    "input_omission_seen": False,
                    "input_explicit_seen": False,
                    "input_mixed_counted": False,
                    "progress_group": None,
                    "progress_group_bound": False,
                    "names": set(),
                    "name_order": [],
                    "intervals": {},
                    "update_count": 0,
                }
            state = states[digest]
            state["update_count"] += 1

            _bind_vertex_inputs(vertex, state, diagnostic)

            name = vertex.get("name")
            _require(
                name is None
                or (
                    isinstance(name, str)
                    and len(name.encode("utf-8"))
                    <= MAXIMUM_NAME_BYTES
                ),
                "RAWJSON_VERTEX_NAME_INVALID",
                "BuildKit vertex name changed",
            )
            if isinstance(name, str) and name not in state["names"]:
                _require(
                    len(state["names"]) < MAXIMUM_NAMES_PER_DIGEST,
                    "RAWJSON_VERTEX_NAME_LIMIT_EXCEEDED",
                    "BuildKit vertex name limit changed",
                )
                state["names"].add(name)
                state["name_order"].append(name)

            progress_group = _progress_group(
                vertex.get("progressGroup")
            )
            if not state["progress_group_bound"]:
                state["progress_group"] = progress_group
                state["progress_group_bound"] = True
            _require(
                state["progress_group"] == progress_group,
                "RAWJSON_VERTEX_PROGRESS_GROUP_CONFLICT",
                "BuildKit vertex progress group conflict",
            )

            cached = vertex.get("cached", False)
            _require(
                isinstance(cached, bool),
                "RAWJSON_VERTEX_CACHED_INVALID",
                "BuildKit vertex cached state changed",
            )
            started = _exact_optional_time(
                vertex.get("started"),
                "BuildKit vertex start",
            )
            completed = _exact_optional_time(
                vertex.get("completed"),
                "BuildKit vertex completion",
            )
            _require(
                started is not None or completed is None,
                "RAWJSON_LIFECYCLE_INVALID",
                "BuildKit vertex completion lacks a start",
            )
            _require(
                started is None
                or completed is None
                or completed[1] >= started[1],
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
            if started is None:
                _require(
                    not cached,
                    "RAWJSON_VERTEX_ANNOUNCEMENT_INVALID",
                    "BuildKit vertex announcement changed",
                )
                _require(
                    not state["intervals"],
                    "RAWJSON_VERTEX_INTERVAL_REGRESSION",
                    "BuildKit vertex interval regressed",
                )
                diagnostic["vertex_update_count"] += 1
                continue

            started_at, started_ns, started_text = started
            batch = event_intervals.setdefault(
                (digest, started_ns),
                {
                    "started": started_at,
                    "started_text": started_text,
                    "cached_values": set(),
                    "completion_values": set(),
                    "completions": {},
                    "saw_open": False,
                },
            )
            batch["cached_values"].add(cached)
            if completed is None:
                batch["saw_open"] = True
            else:
                completed_at, completed_ns, completed_text = completed
                batch["completion_values"].add(completed_ns)
                batch["completions"][completed_ns] = (
                    completed_at,
                    completed_text,
                )
            diagnostic["vertex_update_count"] += 1

        for raw_status in event.get("statuses", []):
            status = _v6._validate_item_keys(
                raw_status,
                _v6.STATUS_KEYS,
                "BuildKit status",
            )
            _exact_optional_time(
                status.get("timestamp"),
                "BuildKit status timestamp",
            )
            status_started = _exact_optional_time(
                status.get("started"),
                "BuildKit status start",
            )
            status_completed = _exact_optional_time(
                status.get("completed"),
                "BuildKit status completion",
            )
            _require(
                status_started is None
                or status_completed is None
                or status_completed[1] >= status_started[1],
                "RAWJSON_LIFECYCLE_INVALID",
                "BuildKit status lifecycle changed",
            )

        for (digest, started_ns), batch in event_intervals.items():
            _require(
                len(batch["cached_values"]) == 1,
                "RAWJSON_VERTEX_INTERVAL_CONFLICT",
                "BuildKit vertex interval cached state conflicts",
            )
            _require(
                len(batch["completion_values"]) <= 1,
                "RAWJSON_VERTEX_INTERVAL_CONFLICT",
                "BuildKit vertex interval completion conflicts",
            )
            cached = next(iter(batch["cached_values"]))
            completed_ns = (
                next(iter(batch["completion_values"]))
                if batch["completion_values"]
                else None
            )
            completed_at, completed_text = (
                batch["completions"][completed_ns]
                if completed_ns is not None
                else (None, None)
            )
            intervals = states[digest]["intervals"]
            current = intervals.get(started_ns)
            if current is None:
                _require(
                    len(intervals) < MAXIMUM_INTERVALS_PER_DIGEST,
                    "RAWJSON_VERTEX_INTERVAL_LIMIT_EXCEEDED",
                    "BuildKit vertex interval limit changed",
                )
                intervals[started_ns] = {
                    "started": batch["started"],
                    "started_text": batch["started_text"],
                    "completed": completed_at,
                    "completed_ns": completed_ns,
                    "completed_text": completed_text,
                    "cached": cached,
                }
                continue
            _require(
                current["cached"] is cached,
                "RAWJSON_VERTEX_INTERVAL_CONFLICT",
                "BuildKit vertex interval cached state conflicts",
            )
            if current["completed"] is not None:
                _require(
                    not batch["saw_open"],
                    "RAWJSON_VERTEX_INTERVAL_REGRESSION",
                    "BuildKit vertex interval regressed",
                )
                _require(
                    completed_ns == current["completed_ns"],
                    (
                        "RAWJSON_VERTEX_INTERVAL_REGRESSION"
                        if completed_ns is None
                        else "RAWJSON_VERTEX_INTERVAL_CONFLICT"
                    ),
                    (
                        "BuildKit vertex interval regressed"
                        if completed_ns is None
                        else "BuildKit vertex interval completion conflicts"
                    ),
                )
            elif completed_at is not None:
                current["completed"] = completed_at
                current["completed_ns"] = completed_ns
                current["completed_text"] = completed_text

        retained = {
            key: value
            for key, value in event.items()
            if key != "vertexes"
        }
        if retained:
            retained_non_vertex_events.append(retained)

    _require(
        diagnostic["nonblank_line_count"] > 0 and bool(states),
        "RAWJSON_EMPTY",
        "BuildKit rawjson vertex evidence is empty",
    )
    canonical_event = {
        "vertexes": [
            _canonical_vertex(digest, states[digest])
            for digest in sorted(states)
        ]
    }
    normalized_events = [
        canonical_event,
        *retained_non_vertex_events,
    ]
    normalized_bytes = b"".join(
        json.dumps(
            event,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
        for event in normalized_events
    )
    inner_diagnostic = _FROZEN_INITIAL_DIAGNOSTIC(
        Path("producer-build.rawjson"),
        dockerfile_kind=str(diagnostic["dockerfile_kind"]),
        require_network_vertices_cached=bool(
            diagnostic["network_cache_required"]
        ),
    )
    (
        vertices,
        _canonical_names,
        log_streams,
        referenced_vertices,
        plain_text_fragments,
    ) = _FROZEN_STRICT_PROGRESS(
        normalized_bytes,
        inner_diagnostic,
    )

    named_vertices: list[tuple[str, str]] = []
    for digest in sorted(states):
        state = states[digest]
        intervals = state["intervals"]
        vertices[digest]["intervals"] = dict(intervals)
        vertices[digest]["names"] = set(state["names"])
        for name in state["name_order"]:
            named_vertices.append((digest, name))
            plain_text_fragments.append(name.encode("utf-8"))

    for key in (
        "status_count",
        "log_count",
        "warning_count",
        "decoded_log_record_count",
        "decoded_log_byte_count",
        "decoded_warning_byte_count",
    ):
        diagnostic[key] = inner_diagnostic[key]
    interval_counts = [
        len(state["intervals"])
        for state in states.values()
    ]
    diagnostic["unique_vertex_digest_count"] = len(states)
    diagnostic["lifecycle_interval_count"] = sum(interval_counts)
    diagnostic["repeated_vertex_digest_count"] = sum(
        1
        for state in states.values()
        if state["update_count"] > 1
    )
    diagnostic["maximum_intervals_per_digest"] = max(
        interval_counts,
        default=0,
    )
    return (
        vertices,
        named_vertices,
        log_streams,
        referenced_vertices,
        plain_text_fragments,
    )


def _validate_build_evidence(*args: Any, **kwargs: Any):
    try:
        summary = _FROZEN_V8_INTERNAL_VALIDATE_BUILD_EVIDENCE(
            *args,
            **kwargs,
        )
    except _v8.V8BundleError as exc:
        raise V9BundleError(
            exc.failure_code,
            str(exc),
        ) from None
    diagnostic = summary.pop("v8_rawjson_diagnostic")
    summary["v9_rawjson_diagnostic"] = diagnostic
    return summary


@contextmanager
def _patched_v8_input_omission_contract() -> Iterator[None]:
    with _FROZEN_CHAIN_PATCH_LOCK:
        _assert_frozen_dispatch()
        frozen = (
            (
                _v8,
                "_initial_diagnostic",
                _FROZEN_V8_INITIAL_DIAGNOSTIC,
            ),
            (_v8, "_emit_diagnostic", _FROZEN_V8_EMIT_DIAGNOSTIC),
            (
                _v8,
                "_validate_build_evidence",
                _FROZEN_V8_INTERNAL_VALIDATE_BUILD_EVIDENCE,
            ),
            (_v7, "_strict_progress", _FROZEN_V7_STRICT_PROGRESS),
        )
        for target, name, expected in frozen:
            _require(
                getattr(target, name) is expected,
                "FROZEN_V8_DISPATCH_CHANGED",
                "frozen V8 validator dispatch changed",
            )
        replacements = (
            (_v8, "_initial_diagnostic", _initial_diagnostic),
            (_v8, "_emit_diagnostic", _emit_diagnostic),
            (_v8, "_validate_build_evidence", _validate_build_evidence),
            (_v7, "_strict_progress", _strict_progress),
        )
        for target, name, replacement in replacements:
            setattr(target, name, replacement)
        try:
            yield
        finally:
            for target, name, expected in frozen:
                setattr(target, name, expected)
            for target, name, expected in frozen:
                _require(
                    getattr(target, name) is expected,
                    "FROZEN_V8_DISPATCH_RESTORE_FAILED",
                    "frozen V8 validator dispatch restore failed",
                )
            _assert_frozen_dispatch()


def __getattr__(name: str):
    return getattr(_v8, name)


def validate_build_evidence(*args: Any, **kwargs: Any):
    with _patched_v8_input_omission_contract():
        return _FROZEN_V8_VALIDATE_BUILD_EVIDENCE(*args, **kwargs)


def validate_core(*args: Any, **kwargs: Any):
    with _patched_v8_input_omission_contract():
        return _FROZEN_V8_VALIDATE_CORE(*args, **kwargs)


def validate_final(*args: Any, **kwargs: Any):
    with _patched_v8_input_omission_contract():
        return _FROZEN_V8_VALIDATE_FINAL(*args, **kwargs)


def main() -> int:
    with _patched_v8_input_omission_contract():
        return _FROZEN_V8_MAIN()


if __name__ == "__main__":
    raise SystemExit(main())
