#!/usr/bin/env python3
"""Verify incremental BuildKit vertex updates over the frozen V6/V3/V2 chain.

BuildKit identifies a vertex by digest but may emit multiple lifecycle
intervals for that digest. V7 validates and normalizes that incremental
stream in memory, then delegates every structural provenance, decoded-log,
network-output, legacy-view and archive check to the hash-pinned V6 chain.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import types
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator


V6_VERIFIER_SHA256 = (
    "86d93114e804bf6a51fdb160651d6a20"
    "c555f107b88020e0f8d811d0f0d358e5"
)
MAXIMUM_VERTEX_UPDATES = 1_000_000
MAXIMUM_VERTEX_DIGESTS = 100_000
MAXIMUM_INTERVALS_PER_DIGEST = 1_024
MAXIMUM_NAMES_PER_DIGEST = 256
MAXIMUM_NAME_BYTES = 32_768
MAXIMUM_INPUTS_PER_DIGEST = 4_096
PROGRESS_GROUP_KEYS = {"id", "name", "weak"}


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


def _load_v6_verifier():
    configured = os.environ.get("NOTEAI_V6_BUNDLE_VERIFIER_PATH")
    configured_path = (
        Path(configured)
        if configured
        else Path(__file__).with_name(
            "verify_admin_dependency_cache_bundle_v6.py"
        )
    )
    if configured_path.is_symlink():
        raise RuntimeError("frozen V6 bundle verifier file contract changed")
    v6_path = configured_path.resolve()
    v6_source = _read_frozen_source(
        v6_path,
        label="frozen V6 bundle verifier",
    )
    if hashlib.sha256(v6_source).hexdigest() != V6_VERIFIER_SHA256:
        raise RuntimeError("frozen V6 bundle verifier hash drift")

    module_name = "_noteai_admin_dependency_cache_bundle_v6"
    module = types.ModuleType(module_name)
    module.__file__ = str(v6_path)
    module.__package__ = ""
    sys.modules[module_name] = module
    try:
        exec(
            compile(v6_source, str(v6_path), "exec"),
            module.__dict__,
        )
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


_v6 = _load_v6_verifier()
_FROZEN_INITIAL_DIAGNOSTIC = _v6._initial_diagnostic
_FROZEN_EMIT_DIAGNOSTIC = _v6._emit_diagnostic
_FROZEN_STRICT_PROGRESS = _v6._strict_progress
_FROZEN_VALIDATE_ROLES_AND_LOGS = _v6._validate_roles_and_logs
_FROZEN_VALIDATE_BUILD_EVIDENCE = _v6.validate_build_evidence
_FROZEN_PROVENANCE_BUILD_WINDOW = _v6._provenance_build_window


class V7BundleError(_v6.V6BundleError):
    """A fixed-code V7 failure safe for a public workflow log."""


class _ExactBuildWindow:
    __slots__ = ("started", "finished", "started_ns", "finished_ns")

    def __init__(
        self,
        *,
        started: datetime,
        finished: datetime,
        started_ns: int,
        finished_ns: int,
    ) -> None:
        self.started = started
        self.finished = finished
        self.started_ns = started_ns
        self.finished_ns = finished_ns

    def __getitem__(self, index: int) -> datetime:
        return (self.started, self.finished)[index]


def _fail(failure_code: str, message: str) -> None:
    raise V7BundleError(failure_code, message)


def _require(
    condition: bool,
    failure_code: str,
    message: str,
) -> None:
    if not condition:
        _fail(failure_code, message)


def _exact_optional_time(
    value: Any,
    label: str,
    *,
    failure_code: str = "RAWJSON_LIFECYCLE_INVALID",
) -> tuple[datetime, int, str] | None:
    if value is None:
        return None
    parsed = _v6._parse_optional_time(
        value,
        label,
        failure_code=failure_code,
    )
    _require(
        parsed is not None and isinstance(value, str),
        failure_code,
        f"{label} lifecycle changed",
    )
    if value.endswith("Z"):
        timestamp = value[:-1]
        offset_seconds = 0
    else:
        timestamp = value[:-6]
        raw_offset = value[-6:]
        direction = 1 if raw_offset[0] == "+" else -1
        offset_seconds = direction * (
            int(raw_offset[1:3]) * 3_600
            + int(raw_offset[4:6]) * 60
        )
    if "." in timestamp:
        whole_text, fraction_text = timestamp.rsplit(".", 1)
    else:
        whole_text, fraction_text = timestamp, ""
    try:
        whole = datetime.strptime(
            whole_text,
            "%Y-%m-%dT%H:%M:%S",
        )
    except ValueError as exc:
        raise V7BundleError(
            failure_code,
            f"{label} lifecycle changed",
        ) from exc
    epoch_date = datetime(1970, 1, 1)
    local_seconds = (
        (whole.date() - epoch_date.date()).days * 86_400
        + whole.hour * 3_600
        + whole.minute * 60
        + whole.second
    )
    fraction_ns = int((fraction_text + ("0" * 9))[:9])
    epoch_ns = (
        (local_seconds - offset_seconds) * 1_000_000_000
        + fraction_ns
    )
    return parsed, epoch_ns, value


def _initial_diagnostic(
    progress_path: Path,
    *,
    dockerfile_kind: str,
    require_network_vertices_cached: bool,
) -> dict[str, Any]:
    diagnostic = _FROZEN_INITIAL_DIAGNOSTIC(
        progress_path,
        dockerfile_kind=dockerfile_kind,
        require_network_vertices_cached=require_network_vertices_cached,
    )
    diagnostic["schema_version"] = (
        "noteai.admin-dependency-cache-v7-diagnostic.v1"
    )
    diagnostic["lifecycle_interval_count"] = 0
    diagnostic["repeated_vertex_digest_count"] = 0
    diagnostic["maximum_intervals_per_digest"] = 0
    return diagnostic


def _emit_diagnostic(diagnostic: dict[str, Any]) -> dict[str, Any]:
    bounded = dict(diagnostic)
    bounded["diagnostic_sha256"] = _v6._canonical_sha256(bounded)
    print(
        "noteai_v7_progress_diagnostic="
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


def _progress_group(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    _require(
        isinstance(value, dict)
        and set(value) <= PROGRESS_GROUP_KEYS,
        "RAWJSON_VERTEX_PROGRESS_GROUP_INVALID",
        "BuildKit vertex progress group changed",
    )
    if "id" in value:
        _require(
            isinstance(value["id"], str)
            and len(value["id"].encode("utf-8")) <= MAXIMUM_NAME_BYTES,
            "RAWJSON_VERTEX_PROGRESS_GROUP_INVALID",
            "BuildKit vertex progress group changed",
        )
    if "name" in value:
        _require(
            isinstance(value["name"], str)
            and len(value["name"].encode("utf-8"))
            <= MAXIMUM_NAME_BYTES,
            "RAWJSON_VERTEX_PROGRESS_GROUP_INVALID",
            "BuildKit vertex progress group changed",
        )
    if "weak" in value:
        _require(
            isinstance(value["weak"], bool),
            "RAWJSON_VERTEX_PROGRESS_GROUP_INVALID",
            "BuildKit vertex progress group changed",
        )
    return dict(value)


def _canonical_vertex(
    digest: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    vertex: dict[str, Any] = {"digest": digest}
    if state["inputs"]:
        vertex["inputs"] = list(state["inputs"])
    if state["name_order"]:
        vertex["name"] = state["name_order"][-1]
    if state["progress_group"] is not None:
        vertex["progressGroup"] = state["progress_group"]
    intervals: dict[int, dict[str, Any]] = state["intervals"]
    if intervals:
        latest_started_ns = max(intervals)
        latest = intervals[latest_started_ns]
        vertex["started"] = latest["started_text"]
        if latest["completed"] is not None:
            vertex["completed"] = latest["completed_text"]
        if latest["cached"]:
            vertex["cached"] = True
    return vertex


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
                    "progress_group": None,
                    "progress_group_bound": False,
                    "names": set(),
                    "name_order": [],
                    "intervals": {},
                    "update_count": 0,
                }
            state = states[digest]
            state["update_count"] += 1

            inputs = vertex.get("inputs", [])
            _require(
                isinstance(inputs, list)
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
            if state["inputs"] is None:
                state["inputs"] = input_vector
            _require(
                state["inputs"] == input_vector,
                "RAWJSON_VERTEX_INPUT_CONFLICT",
                "BuildKit vertex inputs conflict",
            )

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
    for binding in bindings:
        vertex = vertices[binding["vertex"]]
        intervals: dict[int, dict[str, Any]] = vertex.get(
            "intervals",
            {},
        )
        _require(
            bool(intervals),
            "NETWORK_VERTEX_LIFECYCLE_INCOMPLETE",
            f"BuildKit {binding['role']} lifecycle incomplete",
        )
        _require(
            isinstance(build_window, _ExactBuildWindow),
            "PROVENANCE_LIFECYCLE_INVALID",
            "BuildKit timing metadata changed",
        )
        for started_ns, interval in intervals.items():
            completed_at = interval["completed"]
            completed_ns = interval["completed_ns"]
            _require(
                completed_at is not None and completed_ns is not None,
                "NETWORK_VERTEX_INTERVAL_INCOMPLETE",
                f"BuildKit {binding['role']} interval incomplete",
            )
            _require(
                build_window.started_ns
                <= started_ns
                <= completed_ns
                <= build_window.finished_ns,
                "NETWORK_VERTEX_LIFECYCLE_OUTSIDE_BUILD",
                f"BuildKit {binding['role']} lifecycle changed",
            )
        latest_started_ns = max(intervals)
        latest = intervals[latest_started_ns]
        _require(
            vertex["started_values"] == {latest["started"]}
            and vertex["completion_values"]
            == {latest["completed"]}
            and vertex["completed"] is True
            and vertex["cached"] is latest["cached"],
            "NETWORK_VERTEX_INTERVAL_PROJECTION_INVALID",
            f"BuildKit {binding['role']} interval projection changed",
        )
    return _FROZEN_VALIDATE_ROLES_AND_LOGS(
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


def _provenance_build_window(
    metadata: dict[str, Any],
) -> _ExactBuildWindow:
    started, finished = _FROZEN_PROVENANCE_BUILD_WINDOW(metadata)
    provenance = metadata["buildx.build.provenance"]
    provenance_metadata = provenance["metadata"]
    exact_started = _exact_optional_time(
        provenance_metadata.get("buildStartedOn"),
        "BuildKit build start",
        failure_code="PROVENANCE_LIFECYCLE_INVALID",
    )
    exact_finished = _exact_optional_time(
        provenance_metadata.get("buildFinishedOn"),
        "BuildKit build finish",
        failure_code="PROVENANCE_LIFECYCLE_INVALID",
    )
    _require(
        exact_started is not None
        and exact_finished is not None
        and exact_started[1] <= exact_finished[1]
        and exact_finished[1] - exact_started[1]
        <= 7_200 * 1_000_000_000,
        "PROVENANCE_LIFECYCLE_INVALID",
        "BuildKit build lifecycle changed",
    )
    return _ExactBuildWindow(
        started=started,
        finished=finished,
        started_ns=exact_started[1],
        finished_ns=exact_finished[1],
    )


def _validate_build_evidence(*args: Any, **kwargs: Any):
    try:
        summary = _FROZEN_VALIDATE_BUILD_EVIDENCE(*args, **kwargs)
    except _v6.V6BundleError as exc:
        raise V7BundleError(
            exc.failure_code,
            str(exc),
        ) from None
    diagnostic = summary.pop("v6_rawjson_diagnostic")
    summary["v7_rawjson_diagnostic"] = diagnostic
    return summary


@contextmanager
def _patched_v6_incremental_contract() -> Iterator[None]:
    with _v6._PATCH_LOCK:
        frozen = {
            "_initial_diagnostic": _FROZEN_INITIAL_DIAGNOSTIC,
            "_emit_diagnostic": _FROZEN_EMIT_DIAGNOSTIC,
            "_strict_progress": _FROZEN_STRICT_PROGRESS,
            "_provenance_build_window": (
                _FROZEN_PROVENANCE_BUILD_WINDOW
            ),
            "_validate_roles_and_logs": (
                _FROZEN_VALIDATE_ROLES_AND_LOGS
            ),
            "validate_build_evidence": (
                _FROZEN_VALIDATE_BUILD_EVIDENCE
            ),
        }
        for name, expected in frozen.items():
            _require(
                getattr(_v6, name) is expected,
                "FROZEN_V6_DISPATCH_CHANGED",
                "frozen V6 validator dispatch changed",
            )
        replacements = {
            "_initial_diagnostic": _initial_diagnostic,
            "_emit_diagnostic": _emit_diagnostic,
            "_strict_progress": _strict_progress,
            "_provenance_build_window": _provenance_build_window,
            "_validate_roles_and_logs": _validate_roles_and_logs,
            "validate_build_evidence": _validate_build_evidence,
        }
        for name, replacement in replacements.items():
            setattr(_v6, name, replacement)
        try:
            yield
        finally:
            for name, expected in frozen.items():
                setattr(_v6, name, expected)
            for name, expected in frozen.items():
                _require(
                    getattr(_v6, name) is expected,
                    "FROZEN_V6_DISPATCH_RESTORE_FAILED",
                    "frozen V6 validator dispatch restore failed",
                )


def __getattr__(name: str):
    return getattr(_v6, name)


def validate_build_evidence(*args: Any, **kwargs: Any):
    with _patched_v6_incremental_contract():
        return _v6.validate_build_evidence(*args, **kwargs)


def validate_core(*args: Any, **kwargs: Any):
    with _patched_v6_incremental_contract():
        return _v6.validate_core(*args, **kwargs)


def validate_final(*args: Any, **kwargs: Any):
    with _patched_v6_incremental_contract():
        return _v6.validate_final(*args, **kwargs)


def main() -> int:
    with _patched_v6_incremental_contract():
        return _v6.main()


if __name__ == "__main__":
    raise SystemExit(main())
