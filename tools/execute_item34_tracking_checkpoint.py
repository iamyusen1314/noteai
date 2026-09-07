#!/usr/bin/env python3
"""Fail-closed orchestration for the bounded Item34 24-hour checkpoint.

The module deliberately has no production database, network, Docker, or
Secret access.  A production wrapper supplies four narrow callables: fresh
readback, the managed gate transition, one worker invocation, and the exact
target schedule write.  This keeps the outer safety rules testable without
creating a second Tracking implementation.
"""

from __future__ import annotations

import hashlib
import re
import sys
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any


CANONICAL_NOTE_ID = "6a7954010000000026034707"
CANONICAL_URL = (
    "https://www.xiaohongshu.com/explore/6a7954010000000026034707"
)
OBJECT_IDENTITY_SHA256 = (
    "6128a4717577754309f3ccd6c0ce532560e3a37f2b716a75239100062eadaa55"
)
OBSERVATION_STARTED_AT = "2026-09-04T22:30:38+08:00"
CHECKPOINT_24H_DUE_AT = "2026-09-05T22:30:38+08:00"
CHECKPOINT_3D_DUE_AT = "2026-09-07T22:30:38+08:00"
WORKER_ARGV = (
    "python",
    "crawler_worker.py",
    "--once",
    "--limit",
    "1",
)

SNAPSHOT_SCHEMA = "noteai.item34.tracking_checkpoint_snapshot.v1"
TRANSITION_SCHEMA = "noteai.item34.managed_transition.v1"
RECEIPT_SCHEMA = "noteai.item34.tracking_checkpoint_receipt.v1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TRACK_ID_MAX = 128
_FRESHNESS = timedelta(minutes=5)
_POST_READBACK_WINDOW = timedelta(minutes=30)


class Item34CheckpointError(RuntimeError):
    """Stable failure code that never includes callback output."""

    def __init__(self, code: str):
        self.code = str(code)
        super().__init__(self.code)


def _dict(value: Any, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Item34CheckpointError(code)
    return value


def _exact_keys(value: Mapping[str, Any], keys: set[str], code: str) -> None:
    if set(value) != keys:
        raise Item34CheckpointError(code)


def _clock(value: Any, code: str) -> datetime:
    if not isinstance(value, str) or value != value.strip() or not value:
        raise Item34CheckpointError(code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise Item34CheckpointError(code) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise Item34CheckpointError(code)
    return parsed.astimezone(timezone.utc)


def _trusted_now(clock: Callable[[], datetime]) -> datetime:
    try:
        value = clock()
    except Exception:
        raise Item34CheckpointError("execution_clock") from None
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise Item34CheckpointError("execution_clock")
    return value.astimezone(timezone.utc)


def _canonical_uuid(value: Any, code: str) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or len(value) > _TRACK_ID_MAX
        or not value.isascii()
    ):
        raise Item34CheckpointError(code)
    try:
        parsed = str(uuid.UUID(value))
    except ValueError:
        raise Item34CheckpointError(code) from None
    if parsed != value:
        raise Item34CheckpointError(code)
    return value


def _canonical_track_id(value: Any) -> str:
    return _canonical_uuid(value, "track_identity")


def _attempt_identity_sha256(value: Any) -> str:
    attempt_id = _canonical_uuid(value, "provider_attempt_identity")
    return hashlib.sha256(
        f"noteai-item34-tracking-attempt-row-v1:{attempt_id}".encode("ascii")
    ).hexdigest()


def _sha256(value: Any, code: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise Item34CheckpointError(code)
    return value


def _nonnegative_int(value: Any, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise Item34CheckpointError(code)
    return value


def _validate_production_config(
    value: Any,
) -> tuple[bool, bool, bool, str | None]:
    config = _dict(value, "production_config")
    _exact_keys(
        config,
        {
            "crawler_enabled",
            "collection_suspended",
            "crawler_config_present",
            "crawler_config_sha256",
            "runtime_role",
            "adapter",
        },
        "production_config",
    )
    if type(config["crawler_enabled"]) is not bool:
        raise Item34CheckpointError("production_config")
    if type(config["collection_suspended"]) is not bool:
        raise Item34CheckpointError("production_config")
    if type(config["crawler_config_present"]) is not bool:
        raise Item34CheckpointError("production_config")
    config_digest = config["crawler_config_sha256"]
    if config["crawler_config_present"]:
        _sha256(config_digest, "production_config")
    elif config_digest is not None or config["crawler_enabled"]:
        raise Item34CheckpointError("production_config")
    if config["runtime_role"] != "xhs-http":
        raise Item34CheckpointError("production_config")
    if config["adapter"] != "spider_xhs_http":
        raise Item34CheckpointError("production_config")
    return (
        bool(config["crawler_enabled"]),
        bool(config["collection_suspended"]),
        bool(config["crawler_config_present"]),
        config_digest,
    )


def _validate_runtime_state(value: Any) -> None:
    state = _dict(value, "runtime_state")
    _exact_keys(
        state,
        {
            "unit_active_state",
            "unit_sub_state",
            "unit_file_state",
            "task_container_count",
        },
        "runtime_state",
    )
    _nonnegative_int(state["task_container_count"], "runtime_state")
    if state != {
        "unit_active_state": "inactive",
        "unit_sub_state": "dead",
        "unit_file_state": "disabled",
        "task_container_count": 0,
    }:
        raise Item34CheckpointError("runtime_not_quiescent")


def _validate_due(value: Any, track_id: str, *, expected_count: int) -> None:
    due = _dict(value, "global_due")
    _exact_keys(due, {"count", "rows"}, "global_due")
    if (
        type(due["count"]) is not int
        or due["count"] != expected_count
        or not isinstance(due["rows"], list)
    ):
        raise Item34CheckpointError("global_due")
    if len(due["rows"]) != expected_count:
        raise Item34CheckpointError("global_due")
    if expected_count == 0:
        return
    row = _dict(due["rows"][0], "global_due")
    _exact_keys(row, {"track_id", "note_id", "stage"}, "global_due")
    if (
        row["track_id"] != track_id
        or row["note_id"] != CANONICAL_NOTE_ID
        or row["stage"] != "24h"
    ):
        raise Item34CheckpointError("global_due_binding")


def _validate_metrics(value: Any, *, populated: bool) -> None:
    metrics = _dict(value, "target_metrics")
    _exact_keys(metrics, {"likes", "saves", "comments"}, "target_metrics")
    for key in ("likes", "saves", "comments"):
        metric = metrics[key]
        if populated:
            _nonnegative_int(metric, "target_metrics")
        elif metric is not None:
            raise Item34CheckpointError("target_metrics")


def _validate_target(
    value: Any,
    track_id: str,
    *,
    phase: str,
    now: datetime,
) -> None:
    target = _dict(value, "target")
    _exact_keys(
        target,
        {
            "track_id",
            "note_id",
            "canonical_url",
            "object_identity_sha256",
            "status",
            "next_check_at",
            "check_24h_at",
            "check_7d_at",
            "claim_present",
            "active_attempt_present",
            "training_eligible",
            "score_window",
            "metrics",
        },
        "target",
    )
    if (
        target["track_id"] != track_id
        or target["note_id"] != CANONICAL_NOTE_ID
        or target["canonical_url"] != CANONICAL_URL
        or target["object_identity_sha256"] != OBJECT_IDENTITY_SHA256
        or type(target["claim_present"]) is not bool
        or type(target["active_attempt_present"]) is not bool
        or target["training_eligible"] is not False
        or target["score_window"] is not None
    ):
        raise Item34CheckpointError("target_binding")
    if target["claim_present"] or target["active_attempt_present"]:
        raise Item34CheckpointError("target_active_attempt")

    if phase == "pre":
        if (
            target["status"] != "pending"
            or target["check_24h_at"] is not None
            or target["check_7d_at"] is not None
        ):
            raise Item34CheckpointError("target_pre_state")
        if target["next_check_at"] != CHECKPOINT_24H_DUE_AT:
            raise Item34CheckpointError("target_pre_schedule")
        _validate_metrics(target["metrics"], populated=False)
        return

    if (
        target["status"] != "checking_7d"
        or target["next_check_at"] != CHECKPOINT_3D_DUE_AT
        or target["check_7d_at"] is not None
    ):
        raise Item34CheckpointError("target_post_state")
    check_24h = _clock(target["check_24h_at"], "target_post_clock")
    if (
        check_24h < _clock(CHECKPOINT_24H_DUE_AT, "checkpoint_clock")
        or check_24h > now + _POST_READBACK_WINDOW
    ):
        raise Item34CheckpointError("checkpoint_24h_early")
    _validate_metrics(target["metrics"], populated=True)


def _validate_attempts(
    value: Any,
    track_id: str,
    *,
    phase: str,
) -> str | None:
    attempts = _dict(value, "attempts")
    _exact_keys(
        attempts,
        {
            "target_count_24h",
            "target_count_7d",
            "global_started_count",
            "target_unknown_count",
            "global_unknown_count",
            "rows",
        },
        "attempts",
    )
    count_24h = _nonnegative_int(attempts["target_count_24h"], "attempts")
    count_7d = _nonnegative_int(attempts["target_count_7d"], "attempts")
    started = _nonnegative_int(attempts["global_started_count"], "attempts")
    target_unknown = _nonnegative_int(
        attempts["target_unknown_count"], "attempts"
    )
    global_unknown = _nonnegative_int(
        attempts["global_unknown_count"], "attempts"
    )
    rows = attempts["rows"]
    if not isinstance(rows, list):
        raise Item34CheckpointError("attempts")
    if phase == "pre":
        if (
            count_24h != 0
            or count_7d != 0
            or started != 0
            or target_unknown != 0
            or global_unknown != 0
            or rows
        ):
            raise Item34CheckpointError("prior_provider_attempt")
        return None
    if (
        count_24h != 1
        or count_7d != 0
        or started != 0
        or target_unknown != 0
        or global_unknown != 0
        or len(rows) != 1
    ):
        raise Item34CheckpointError("post_provider_attempt")
    row = _dict(rows[0], "post_provider_attempt")
    _exact_keys(
        row,
        {
            "track_id",
            "note_id",
            "stage",
            "status",
            "run_id",
            "attempt_id",
            "admitted_at",
            "completed_at",
        },
        "post_provider_attempt",
    )
    if (
        row["track_id"] != track_id
        or row["note_id"] != CANONICAL_NOTE_ID
        or row["stage"] != "24h"
        or row["status"] != "succeeded"
    ):
        raise Item34CheckpointError("post_provider_attempt_binding")
    run_id = _canonical_track_id(row["run_id"])
    _attempt_identity_sha256(row["attempt_id"])
    admitted = _clock(row["admitted_at"], "post_provider_attempt_clock")
    completed = _clock(row["completed_at"], "post_provider_attempt_clock")
    if completed < admitted:
        raise Item34CheckpointError("post_provider_attempt_clock")
    return run_id


def _snapshot_common(
    value: Any,
    track_id: str,
    *,
    phase: str,
    now: datetime,
) -> tuple[
    Mapping[str, Any],
    datetime,
    tuple[bool, bool, bool, str | None],
    str,
    str | None,
]:
    snapshot = _dict(value, f"{phase}_snapshot")
    keys = {
        "schema",
        "observed_at",
        "observation_started_at",
        "production_config",
        "runtime_state",
        "global_due",
        "target",
        "attempts",
        "non_target_tracked_notes_sha256",
    }
    if phase == "post":
        keys |= {"run", "write_audit"}
    _exact_keys(snapshot, keys, f"{phase}_snapshot")
    if (
        snapshot["schema"] != SNAPSHOT_SCHEMA
        or snapshot["observation_started_at"] != OBSERVATION_STARTED_AT
    ):
        raise Item34CheckpointError(f"{phase}_snapshot_binding")
    observed = _clock(snapshot["observed_at"], f"{phase}_snapshot_clock")
    config = _validate_production_config(snapshot["production_config"])
    _validate_runtime_state(snapshot["runtime_state"])
    digest = _sha256(
        snapshot["non_target_tracked_notes_sha256"],
        "non_target_state_digest",
    )
    _validate_due(
        snapshot["global_due"],
        track_id,
        expected_count=1 if phase == "pre" else 0,
    )
    _validate_target(snapshot["target"], track_id, phase=phase, now=now)
    run_id = _validate_attempts(snapshot["attempts"], track_id, phase=phase)
    return snapshot, observed, config, digest, run_id


def _validate_preflight(
    value: Any,
    track_id: str,
    *,
    now: datetime,
    require_ready_config: bool,
) -> tuple[
    Mapping[str, Any],
    tuple[bool, bool, bool, str | None],
    str,
]:
    snapshot, observed, config, digest, _ = _snapshot_common(
        value,
        track_id,
        phase="pre",
        now=now,
    )
    if abs(now - observed) > _FRESHNESS:
        raise Item34CheckpointError("preflight_stale")
    if require_ready_config and (not config[0] or config[1]):
        raise Item34CheckpointError("managed_transition_required")
    return snapshot, config, digest


def _validate_worker_receipt(value: Any) -> None:
    receipt = _dict(value, "worker_receipt")
    _exact_keys(
        receipt,
        {"exit_code", "invocation_count", "automatic_retry_count", "result"},
        "worker_receipt",
    )
    result = _dict(receipt["result"], "worker_result")
    _exact_keys(
        result,
        {"claimed", "attempted", "collected", "failed", "released", "total"},
        "worker_result",
    )
    for key in ("exit_code", "invocation_count", "automatic_retry_count"):
        _nonnegative_int(receipt[key], "worker_result")
    for key in (
        "claimed",
        "attempted",
        "collected",
        "failed",
        "released",
        "total",
    ):
        _nonnegative_int(result[key], "worker_result")
    if (
        receipt["exit_code"] != 0
        or receipt["invocation_count"] != 1
        or receipt["automatic_retry_count"] != 0
        or result
        != {
            "claimed": 1,
            "attempted": 1,
            "collected": 1,
            "failed": 0,
            "released": 0,
            "total": 1,
        }
    ):
        raise Item34CheckpointError("worker_result")


def _validate_schedule_receipt(value: Any, track_id: str) -> None:
    receipt = _dict(value, "schedule_receipt")
    _exact_keys(
        receipt,
        {
            "track_id",
            "next_check_at",
            "target_rows_mutated",
            "other_tracked_notes_row_mutations",
        },
        "schedule_receipt",
    )
    _nonnegative_int(receipt["target_rows_mutated"], "schedule_receipt")
    _nonnegative_int(
        receipt["other_tracked_notes_row_mutations"], "schedule_receipt"
    )
    if (
        receipt["track_id"] != track_id
        or receipt["next_check_at"] != CHECKPOINT_3D_DUE_AT
        or receipt["target_rows_mutated"] != 1
        or receipt["other_tracked_notes_row_mutations"] != 0
    ):
        raise Item34CheckpointError("schedule_write")


def _validate_postflight(
    value: Any,
    track_id: str,
    *,
    now: datetime,
    pre_observed_at: datetime,
    pre_non_target_digest: str,
    transition_used: bool,
) -> tuple[datetime, str]:
    snapshot, observed, config, digest, attempt_run_id = _snapshot_common(
        value,
        track_id,
        phase="post",
        now=now,
    )
    if (
        observed < pre_observed_at
        or observed > now + _POST_READBACK_WINDOW
        or observed >= _clock(CHECKPOINT_3D_DUE_AT, "checkpoint_clock")
        or not config[0]
        or config[1]
    ):
        raise Item34CheckpointError("post_snapshot_state")
    if digest != pre_non_target_digest:
        raise Item34CheckpointError("other_tracking_rows_changed")
    target_check = _clock(
        snapshot["target"]["check_24h_at"], "target_post_clock"
    )
    attempt_row = snapshot["attempts"]["rows"][0]
    admitted = _clock(
        attempt_row["admitted_at"], "post_provider_attempt_clock"
    )
    completed = _clock(
        attempt_row["completed_at"], "post_provider_attempt_clock"
    )
    if (
        admitted < pre_observed_at
        or completed > observed
        or target_check < pre_observed_at
        or target_check > observed
        or target_check != completed
    ):
        raise Item34CheckpointError("post_snapshot_clock")

    run = _dict(snapshot["run"], "post_run")
    _exact_keys(
        run,
        {
            "run_id",
            "worker_argv",
            "worker_invocation_count",
            "automatic_retry_count",
            "attempted",
            "collected",
            "failed",
        },
        "post_run",
    )
    for key in (
        "worker_invocation_count",
        "automatic_retry_count",
        "attempted",
        "collected",
        "failed",
    ):
        _nonnegative_int(run[key], "post_run")
    if (
        run["run_id"] != attempt_run_id
        or run["worker_argv"] != list(WORKER_ARGV)
        or run["worker_invocation_count"] != 1
        or run["automatic_retry_count"] != 0
        or run["attempted"] != 1
        or run["collected"] != 1
        or run["failed"] != 0
    ):
        raise Item34CheckpointError("post_run")

    audit = _dict(snapshot["write_audit"], "write_audit")
    _exact_keys(
        audit,
        {
            "target_tracked_notes_distinct_rows",
            "other_tracked_notes_row_mutations",
            "tracking_provider_attempts_inserted",
            "crawler_events_inserted",
            "system_settings_row_mutations",
            "other_system_settings_row_mutations",
            "out_of_contract_row_mutations",
        },
        "write_audit",
    )
    for value in audit.values():
        _nonnegative_int(value, "write_audit")
    if audit != {
        "target_tracked_notes_distinct_rows": 1,
        "other_tracked_notes_row_mutations": 0,
        "tracking_provider_attempts_inserted": 1,
        "crawler_events_inserted": 1,
        "system_settings_row_mutations": 1 if transition_used else 0,
        "other_system_settings_row_mutations": 0,
        "out_of_contract_row_mutations": 0,
    }:
        raise Item34CheckpointError("write_audit")
    return observed, str(attempt_run_id)


def _validate_transition_authorization(
    value: Any,
    initial_config: tuple[bool, bool, bool, str | None],
    *,
    action: str = "item34_single_24h_checkpoint",
) -> Mapping[str, Any]:
    authorization = _dict(value, "managed_transition_authorization")
    _exact_keys(
        authorization,
        {
            "schema",
            "transition_id",
            "action",
            "restore_required",
            "worker_argv",
            "expected_original_config_present",
            "expected_original_config_sha256",
            "expected_active_config_sha256",
        },
        "managed_transition_authorization",
    )
    if (
        authorization["schema"] != TRANSITION_SCHEMA
        or authorization["action"] != action
        or authorization["restore_required"] is not True
        or authorization["worker_argv"] != list(WORKER_ARGV)
        or authorization["expected_original_config_present"]
        is not initial_config[2]
        or authorization["expected_original_config_sha256"]
        != initial_config[3]
    ):
        raise Item34CheckpointError("managed_transition_authorization")
    _sha256(authorization["transition_id"], "managed_transition_authorization")
    _sha256(
        authorization["expected_active_config_sha256"],
        "managed_transition_authorization",
    )
    return authorization


def _validate_transition_result(
    value: Any,
    authorization: Mapping[str, Any],
    *,
    phase: str,
    expected_before: tuple[bool, bool, bool, str | None],
    expected_after: tuple[bool, bool, bool, str | None],
) -> Mapping[str, Any]:
    result = _dict(value, "managed_transition")
    _exact_keys(
        result,
        {
            "transition_id",
            "phase",
            "crawler_enabled",
            "collection_suspended",
            "before_config_present",
            "before_config_sha256",
            "after_config_present",
            "after_config_sha256",
            "configuration_mutations",
            "other_configuration_mutations",
        },
        "managed_transition",
    )
    if (
        result["transition_id"] != authorization["transition_id"]
        or result["phase"] != phase
        or result["crawler_enabled"] is not expected_after[0]
        or result["collection_suspended"] is not expected_after[1]
        or result["before_config_present"] is not expected_before[2]
        or result["before_config_sha256"] != expected_before[3]
        or result["after_config_present"] is not expected_after[2]
        or result["after_config_sha256"] != expected_after[3]
        or type(result["configuration_mutations"]) is not int
        or type(result["other_configuration_mutations"]) is not int
        or result["configuration_mutations"] != 1
        or result["other_configuration_mutations"] != 0
    ):
        raise Item34CheckpointError("managed_transition")
    return result


def execute_24h_checkpoint(
    *,
    expected_track_id: str,
    read_preflight: Callable[[], Mapping[str, Any]],
    run_worker: Callable[[tuple[str, ...]], Mapping[str, Any]],
    schedule_3d: Callable[[str, str], Mapping[str, Any]],
    read_postflight: Callable[[], Mapping[str, Any]],
    clock: Callable[[], datetime],
    transition_authorization: Mapping[str, Any] | None = None,
    transition_config: Callable[[str, Mapping[str, Any]], Mapping[str, Any]]
    | None = None,
    read_transition_state: Callable[[], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute one 24h call and prove the target alone is scheduled for 72h.

    The supplied worker callback is invoked exactly once.  Any exception or
    non-exact receipt is terminal for this invocation; this function contains
    no retry path.
    """

    track_id = _canonical_track_id(expected_track_id)
    execution_time = _trusted_now(clock)
    due_24h = _clock(CHECKPOINT_24H_DUE_AT, "checkpoint_clock")
    due_3d = _clock(CHECKPOINT_3D_DUE_AT, "checkpoint_clock")
    if execution_time < due_24h:
        raise Item34CheckpointError("checkpoint_24h_not_due")
    if execution_time >= due_3d:
        raise Item34CheckpointError("checkpoint_24h_window_closed")

    try:
        initial_raw = read_preflight()
    except Exception:
        raise Item34CheckpointError("preflight_read") from None
    initial, initial_config, initial_digest = _validate_preflight(
        initial_raw,
        track_id,
        now=execution_time,
        require_ready_config=False,
    )

    transition_used = not initial_config[0] or initial_config[1]
    authorization: Mapping[str, Any] | None = None
    restore_result: Mapping[str, Any] | None = None
    if transition_used:
        if (
            transition_authorization is None
            or transition_config is None
            or read_transition_state is None
        ):
            raise Item34CheckpointError("managed_transition_required")
        authorization = _validate_transition_authorization(
            transition_authorization,
            initial_config,
        )

    try:
        if transition_used:
            assert authorization is not None
            assert transition_config is not None
            try:
                activation = transition_config("activate", authorization)
            except Exception:
                raise Item34CheckpointError(
                    "managed_transition_activate"
                ) from None
            _validate_transition_result(
                activation,
                authorization,
                phase="activate",
                expected_before=initial_config,
                expected_after=(
                    True,
                    False,
                    True,
                    authorization["expected_active_config_sha256"],
                ),
            )
            try:
                active_raw = read_preflight()
            except Exception:
                raise Item34CheckpointError("preflight_read") from None
            active, active_config, active_digest = _validate_preflight(
                active_raw,
                track_id,
                now=execution_time,
                require_ready_config=True,
            )
            expected_active_config = (
                True,
                False,
                True,
                authorization["expected_active_config_sha256"],
            )
            if active_config != expected_active_config:
                raise Item34CheckpointError("managed_transition_scope")
            for key in ("runtime_state", "global_due", "target", "attempts"):
                if active[key] != initial[key]:
                    raise Item34CheckpointError("managed_transition_scope")
            if active_digest != initial_digest:
                raise Item34CheckpointError("managed_transition_scope")
            preflight = active
        else:
            _validate_preflight(
                initial,
                track_id,
                now=execution_time,
                require_ready_config=True,
            )
            preflight = initial

        dispatch_time = _trusted_now(clock)
        if dispatch_time < due_24h:
            raise Item34CheckpointError("checkpoint_24h_not_due")
        if dispatch_time >= due_3d:
            raise Item34CheckpointError("checkpoint_24h_window_closed")

        try:
            worker_receipt = run_worker(WORKER_ARGV)
        except Exception:
            raise Item34CheckpointError("worker_outcome_unknown") from None
        _validate_worker_receipt(worker_receipt)

        try:
            schedule_receipt = schedule_3d(track_id, CHECKPOINT_3D_DUE_AT)
        except Exception:
            raise Item34CheckpointError("schedule_write_unknown") from None
        _validate_schedule_receipt(schedule_receipt, track_id)

        try:
            post_raw = read_postflight()
        except Exception:
            raise Item34CheckpointError("postflight_read") from None
        post_observed, run_id = _validate_postflight(
            post_raw,
            track_id,
            now=dispatch_time,
            pre_observed_at=_clock(
                preflight["observed_at"], "pre_snapshot_clock"
            ),
            pre_non_target_digest=initial_digest,
            transition_used=transition_used,
        )
    finally:
        primary_error = sys.exc_info()[1]
        if transition_used and authorization is not None:
            try:
                restored = transition_config("restore", authorization)  # type: ignore[misc]
                restore_result = _validate_transition_result(
                    restored,
                    authorization,
                    phase="restore",
                    expected_before=(
                        True,
                        False,
                        True,
                        authorization["expected_active_config_sha256"],
                    ),
                    expected_after=initial_config,
                )
                restored_config = _validate_production_config(
                    read_transition_state()
                )
                if restored_config != initial_config:
                    raise Item34CheckpointError("managed_transition_restore")
            except Exception:
                if isinstance(primary_error, Item34CheckpointError):
                    raise Item34CheckpointError(
                        f"{primary_error.code}_restore_failed"
                    ) from None
                raise Item34CheckpointError(
                    "managed_transition_restore"
                ) from None

    return {
        "schema": RECEIPT_SCHEMA,
        "item": 34,
        "checkpoint": "24h",
        "status": "VERIFIED",
        "readiness_credit": False,
        "note_id": CANONICAL_NOTE_ID,
        "object_identity_sha256": OBJECT_IDENTITY_SHA256,
        "track_identity_sha256": hashlib.sha256(
            f"noteai-item34-tracking-row-v1:{track_id}".encode("ascii")
        ).hexdigest(),
        "observation_started_at": OBSERVATION_STARTED_AT,
        "checkpoint_observed_at": post_observed.isoformat(),
        "next_checkpoint_at": CHECKPOINT_3D_DUE_AT,
        "run_identity_sha256": hashlib.sha256(
            f"noteai-item34-tracking-run-v1:{run_id}".encode("ascii")
        ).hexdigest(),
        "attempt_identity_sha256": _attempt_identity_sha256(
            post_raw["attempts"]["rows"][0]["attempt_id"]
        ),
        "canonical_stage": "24h",
        "persisted_stage": "24h",
        "admitted_at": post_raw["attempts"]["rows"][0]["admitted_at"],
        "completed_at": post_raw["attempts"]["rows"][0]["completed_at"],
        "metrics": dict(post_raw["target"]["metrics"]),
        "worker_argv": list(WORKER_ARGV),
        "worker_invocation_count": 1,
        "provider_calls": 1,
        "automatic_retry_count": 0,
        "attempt_count_24h": 1,
        "attempt_count_7d": 0,
        "other_tracked_notes_row_mutations": 0,
        "managed_transition": {
            "used": transition_used,
            "restored": (not transition_used) or restore_result is not None,
            "configuration_row_mutations": 2 if transition_used else 0,
        },
        "crawler_events_inserted": 1,
        "outcome_unknown_count": 0,
        "runtime_quiescent": True,
        "secret_values_recorded": False,
    }


def _validate_3d_target(
    value: Any,
    track_id: str,
    *,
    phase: str,
    now: datetime,
) -> tuple[datetime, datetime | None, Mapping[str, Any]]:
    target = _dict(value, "target")
    _exact_keys(
        target,
        {
            "track_id",
            "note_id",
            "canonical_url",
            "object_identity_sha256",
            "status",
            "next_check_at",
            "check_24h_at",
            "check_7d_at",
            "claim_present",
            "active_attempt_present",
            "training_eligible",
            "score_window",
            "metrics",
        },
        "target",
    )
    if (
        target["track_id"] != track_id
        or target["note_id"] != CANONICAL_NOTE_ID
        or target["canonical_url"] != CANONICAL_URL
        or target["object_identity_sha256"] != OBJECT_IDENTITY_SHA256
        or target["next_check_at"] != CHECKPOINT_3D_DUE_AT
        or target["claim_present"] is not False
        or target["active_attempt_present"] is not False
    ):
        raise Item34CheckpointError("target_binding")
    check_24h = _clock(target["check_24h_at"], "target_24h_clock")
    if not (
        _clock(CHECKPOINT_24H_DUE_AT, "checkpoint_clock")
        <= check_24h
        < _clock(CHECKPOINT_3D_DUE_AT, "checkpoint_clock")
    ):
        raise Item34CheckpointError("target_24h_clock")
    _validate_metrics(target["metrics"], populated=True)
    if phase == "pre":
        if (
            target["status"] != "checking_7d"
            or target["check_7d_at"] is not None
            or target["training_eligible"] is not False
            or target["score_window"] is not None
        ):
            raise Item34CheckpointError("target_pre_state")
        return check_24h, None, target["metrics"]
    if (
        target["status"] != "complete"
        or target["training_eligible"] is not False
        or target["score_window"] != "3d"
    ):
        raise Item34CheckpointError("target_post_state")
    check_3d = _clock(target["check_7d_at"], "target_3d_clock")
    if check_3d < _clock(CHECKPOINT_3D_DUE_AT, "checkpoint_clock") or check_3d > now + _POST_READBACK_WINDOW:
        raise Item34CheckpointError("target_3d_clock")
    return check_24h, check_3d, target["metrics"]


def _validate_3d_attempts(
    value: Any,
    track_id: str,
    *,
    phase: str,
) -> tuple[Mapping[str, Any], Mapping[str, Any] | None]:
    attempts = _dict(value, "attempts")
    _exact_keys(
        attempts,
        {
            "target_count_24h",
            "target_count_7d",
            "global_started_count",
            "target_unknown_count",
            "global_unknown_count",
            "rows",
        },
        "attempts",
    )
    expected_7d = 0 if phase == "pre" else 1
    if (
        _nonnegative_int(attempts["target_count_24h"], "attempts") != 1
        or _nonnegative_int(attempts["target_count_7d"], "attempts") != expected_7d
        or _nonnegative_int(attempts["global_started_count"], "attempts") != 0
        or _nonnegative_int(attempts["target_unknown_count"], "attempts") != 0
        or _nonnegative_int(attempts["global_unknown_count"], "attempts") != 0
        or not isinstance(attempts["rows"], list)
        or len(attempts["rows"]) != 1 + expected_7d
    ):
        raise Item34CheckpointError("provider_attempt_ledger")
    by_stage: dict[str, Mapping[str, Any]] = {}
    for value_row in attempts["rows"]:
        row = _dict(value_row, "provider_attempt_ledger")
        _exact_keys(
            row,
            {
                "track_id",
                "note_id",
                "stage",
                "status",
                "run_id",
                "attempt_id",
                "admitted_at",
                "completed_at",
            },
            "provider_attempt_ledger",
        )
        stage = row["stage"]
        if (
            stage not in {"24h", "7d"}
            or stage in by_stage
            or row["track_id"] != track_id
            or row["note_id"] != CANONICAL_NOTE_ID
            or row["status"] != "succeeded"
        ):
            raise Item34CheckpointError("provider_attempt_binding")
        _canonical_track_id(row["run_id"])
        _attempt_identity_sha256(row["attempt_id"])
        admitted = _clock(row["admitted_at"], "provider_attempt_clock")
        completed = _clock(row["completed_at"], "provider_attempt_clock")
        floor = _clock(
            CHECKPOINT_24H_DUE_AT if stage == "24h" else CHECKPOINT_3D_DUE_AT,
            "checkpoint_clock",
        )
        if admitted < floor or completed < admitted:
            raise Item34CheckpointError("provider_attempt_clock")
        if stage == "24h" and completed >= _clock(CHECKPOINT_3D_DUE_AT, "checkpoint_clock"):
            raise Item34CheckpointError("provider_attempt_clock")
        by_stage[stage] = row
    if set(by_stage) != ({"24h"} if phase == "pre" else {"24h", "7d"}):
        raise Item34CheckpointError("provider_attempt_ledger")
    return by_stage["24h"], by_stage.get("7d")


def _validate_3d_snapshot(
    value: Any,
    track_id: str,
    *,
    phase: str,
    now: datetime,
    transition_used: bool = False,
) -> tuple[Mapping[str, Any], datetime, tuple[bool, bool, bool, str | None], str, Mapping[str, Any], Mapping[str, Any] | None]:
    snapshot = _dict(value, f"3d_{phase}_snapshot")
    keys = {
        "schema",
        "observed_at",
        "observation_started_at",
        "production_config",
        "runtime_state",
        "global_due",
        "target",
        "attempts",
        "non_target_tracked_notes_sha256",
    }
    if phase == "post":
        keys |= {"run", "write_audit", "terminal_effects"}
    _exact_keys(snapshot, keys, f"3d_{phase}_snapshot")
    if snapshot["schema"] != SNAPSHOT_SCHEMA or snapshot["observation_started_at"] != OBSERVATION_STARTED_AT:
        raise Item34CheckpointError(f"3d_{phase}_snapshot_binding")
    observed = _clock(snapshot["observed_at"], f"3d_{phase}_snapshot_clock")
    config = _validate_production_config(snapshot["production_config"])
    _validate_runtime_state(snapshot["runtime_state"])
    due = _dict(snapshot["global_due"], "global_due")
    _exact_keys(due, {"count", "rows"}, "global_due")
    expected_due = 1 if phase == "pre" else 0
    if due["count"] != expected_due or not isinstance(due["rows"], list) or len(due["rows"]) != expected_due:
        raise Item34CheckpointError("global_due")
    if expected_due:
        row = _dict(due["rows"][0], "global_due")
        if row != {"track_id": track_id, "note_id": CANONICAL_NOTE_ID, "stage": "7d"}:
            raise Item34CheckpointError("global_due_binding")
    _validate_3d_target(snapshot["target"], track_id, phase=phase, now=now)
    prior, current = _validate_3d_attempts(snapshot["attempts"], track_id, phase=phase)
    digest = _sha256(snapshot["non_target_tracked_notes_sha256"], "non_target_state_digest")
    if phase == "pre":
        return snapshot, observed, config, digest, prior, current

    run = _dict(snapshot["run"], "post_run")
    _exact_keys(
        run,
        {"run_id", "worker_argv", "worker_invocation_count", "automatic_retry_count", "attempted", "collected", "failed"},
        "post_run",
    )
    if current is None or run != {
        "run_id": current["run_id"],
        "worker_argv": list(WORKER_ARGV),
        "worker_invocation_count": 1,
        "automatic_retry_count": 0,
        "attempted": 1,
        "collected": 1,
        "failed": 0,
    }:
        raise Item34CheckpointError("post_run")
    audit = _dict(snapshot["write_audit"], "write_audit")
    expected_audit = {
        "target_tracked_notes_distinct_rows": 1,
        "other_tracked_notes_row_mutations": 0,
        "tracking_provider_attempts_inserted": 1,
        "crawler_events_inserted": 1,
        "growth_records_inserted": 1,
        "user_memories_inserted": 1,
        "system_settings_row_mutations": 1 if transition_used else 0,
        "other_system_settings_row_mutations": 0,
        "out_of_contract_row_mutations": 0,
    }
    _exact_keys(audit, set(expected_audit), "write_audit")
    for item in audit.values():
        _nonnegative_int(item, "write_audit")
    if audit != expected_audit:
        raise Item34CheckpointError("write_audit")
    effects = _dict(snapshot["terminal_effects"], "terminal_effects")
    _exact_keys(
        effects,
        {
            "growth_record_count",
            "user_memory_count",
            "training_eligible",
            "score_window",
            "growth_action",
            "memory_window",
            "memory_content_sha256",
            "ledger_sha256",
        },
        "terminal_effects",
    )
    if (
        _nonnegative_int(effects["growth_record_count"], "terminal_effects") != 1
        or _nonnegative_int(effects["user_memory_count"], "terminal_effects") != 1
        or effects["training_eligible"] is not False
        or effects["score_window"] != "3d"
        or effects["growth_action"] != "url_crawl_3d"
        or effects["memory_window"] != "3d"
    ):
        raise Item34CheckpointError("terminal_effects")
    _sha256(effects["memory_content_sha256"], "terminal_effects")
    _sha256(effects["ledger_sha256"], "terminal_effects")
    return snapshot, observed, config, digest, prior, current


def execute_3d_checkpoint(
    *,
    expected_track_id: str,
    read_preflight: Callable[[], Mapping[str, Any]],
    run_worker: Callable[[tuple[str, ...]], Mapping[str, Any]],
    read_postflight: Callable[[], Mapping[str, Any]],
    clock: Callable[[], datetime],
    transition_authorization: Mapping[str, Any] | None = None,
    transition_config: Callable[[str, Mapping[str, Any]], Mapping[str, Any]] | None = None,
    read_transition_state: Callable[[], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute the single real 72-hour call; no retry path exists."""

    track_id = _canonical_track_id(expected_track_id)
    execution_time = _trusted_now(clock)
    due_3d = _clock(CHECKPOINT_3D_DUE_AT, "checkpoint_clock")
    if execution_time < due_3d:
        raise Item34CheckpointError("checkpoint_3d_not_due")
    try:
        initial_raw = read_preflight()
    except Exception:
        raise Item34CheckpointError("preflight_read") from None
    initial, pre_observed, initial_config, initial_digest, prior_attempt, _ = _validate_3d_snapshot(
        initial_raw, track_id, phase="pre", now=execution_time
    )
    if abs(execution_time - pre_observed) > _FRESHNESS:
        raise Item34CheckpointError("preflight_stale")
    transition_used = not initial_config[0] or initial_config[1]
    authorization: Mapping[str, Any] | None = None
    restore_result: Mapping[str, Any] | None = None
    if transition_used:
        if transition_authorization is None or transition_config is None or read_transition_state is None:
            raise Item34CheckpointError("managed_transition_required")
        authorization = _validate_transition_authorization(
            transition_authorization,
            initial_config,
            action="item34_single_3d_checkpoint",
        )
    try:
        if transition_used:
            assert authorization is not None and transition_config is not None
            try:
                activated = transition_config("activate", authorization)
            except Exception:
                raise Item34CheckpointError("managed_transition_activate") from None
            _validate_transition_result(
                activated,
                authorization,
                phase="activate",
                expected_before=initial_config,
                expected_after=(True, False, True, authorization["expected_active_config_sha256"]),
            )
            try:
                active_raw = read_preflight()
            except Exception:
                raise Item34CheckpointError("preflight_read") from None
            active, active_observed, active_config, active_digest, active_prior, _ = _validate_3d_snapshot(
                active_raw, track_id, phase="pre", now=execution_time
            )
            if (
                active_config != (True, False, True, authorization["expected_active_config_sha256"])
                or active_digest != initial_digest
                or active_prior != prior_attempt
                or active["target"] != initial["target"]
                or active["global_due"] != initial["global_due"]
                or active["runtime_state"] != initial["runtime_state"]
                or abs(execution_time - active_observed) > _FRESHNESS
            ):
                raise Item34CheckpointError("managed_transition_scope")
        elif not initial_config[0] or initial_config[1]:
            raise Item34CheckpointError("managed_transition_required")

        dispatch_time = _trusted_now(clock)
        if dispatch_time < due_3d:
            raise Item34CheckpointError("checkpoint_3d_not_due")
        try:
            worker_receipt = run_worker(WORKER_ARGV)
        except Exception:
            raise Item34CheckpointError("worker_outcome_unknown") from None
        _validate_worker_receipt(worker_receipt)
        try:
            post_raw = read_postflight()
        except Exception:
            raise Item34CheckpointError("postflight_read") from None
        post, post_observed, post_config, post_digest, post_prior, current_attempt = _validate_3d_snapshot(
            post_raw,
            track_id,
            phase="post",
            now=dispatch_time,
            transition_used=transition_used,
        )
        if (
            post_observed < pre_observed
            or post_observed > dispatch_time + _POST_READBACK_WINDOW
            or post_config[0] is not True
            or post_config[1] is not False
            or post_digest != initial_digest
            or post_prior != prior_attempt
            or current_attempt is None
        ):
            raise Item34CheckpointError("post_snapshot_state")
        check_3d = _clock(post["target"]["check_7d_at"], "target_3d_clock")
        admitted = _clock(current_attempt["admitted_at"], "provider_attempt_clock")
        completed = _clock(current_attempt["completed_at"], "provider_attempt_clock")
        if admitted < pre_observed or completed > post_observed or check_3d != completed:
            raise Item34CheckpointError("post_snapshot_clock")
    finally:
        primary_error = sys.exc_info()[1]
        if transition_used and authorization is not None:
            try:
                restored = transition_config("restore", authorization)  # type: ignore[misc]
                restore_result = _validate_transition_result(
                    restored,
                    authorization,
                    phase="restore",
                    expected_before=(True, False, True, authorization["expected_active_config_sha256"]),
                    expected_after=initial_config,
                )
                if _validate_production_config(read_transition_state()) != initial_config:  # type: ignore[misc]
                    raise Item34CheckpointError("managed_transition_restore")
            except Exception:
                if isinstance(primary_error, Item34CheckpointError):
                    raise Item34CheckpointError(
                        f"{primary_error.code}_restore_failed"
                    ) from None
                raise Item34CheckpointError("managed_transition_restore") from None

    assert current_attempt is not None
    run_id = str(current_attempt["run_id"])
    return {
        "schema": RECEIPT_SCHEMA,
        "item": 34,
        "checkpoint": "3d",
        "status": "VERIFIED",
        "readiness_credit": False,
        "note_id": CANONICAL_NOTE_ID,
        "object_identity_sha256": OBJECT_IDENTITY_SHA256,
        "track_identity_sha256": hashlib.sha256(f"noteai-item34-tracking-row-v1:{track_id}".encode("ascii")).hexdigest(),
        "observation_started_at": OBSERVATION_STARTED_AT,
        "checkpoint_observed_at": post_observed.isoformat(),
        "run_identity_sha256": hashlib.sha256(f"noteai-item34-tracking-run-v1:{run_id}".encode("ascii")).hexdigest(),
        "attempt_identity_sha256": _attempt_identity_sha256(
            current_attempt["attempt_id"]
        ),
        "canonical_stage": "3d",
        "persisted_stage": "7d",
        "admitted_at": current_attempt["admitted_at"],
        "completed_at": current_attempt["completed_at"],
        "worker_argv": list(WORKER_ARGV),
        "worker_invocation_count": 1,
        "provider_calls": 1,
        "automatic_retry_count": 0,
        "attempt_count_24h": 1,
        "attempt_count_7d": 1,
        "other_tracked_notes_row_mutations": 0,
        "metrics": dict(post["target"]["metrics"]),
        "managed_transition": {
            "used": transition_used,
            "restored": (not transition_used) or restore_result is not None,
            "configuration_row_mutations": 2 if transition_used else 0,
        },
        "crawler_events_inserted": 1,
        "growth_records_inserted": 1,
        "user_memories_inserted": 1,
        "outcome_unknown_count": 0,
        "runtime_quiescent": True,
        "training_eligible": False,
        "score_window": "3d",
        "growth_action": "url_crawl_3d",
        "memory_window": "3d",
        "memory_content_sha256": post["terminal_effects"][
            "memory_content_sha256"
        ],
        "terminal_effects_ledger_sha256": post["terminal_effects"]["ledger_sha256"],
        "secret_values_recorded": False,
    }


__all__ = [
    "CANONICAL_NOTE_ID",
    "CANONICAL_URL",
    "OBJECT_IDENTITY_SHA256",
    "OBSERVATION_STARTED_AT",
    "CHECKPOINT_24H_DUE_AT",
    "CHECKPOINT_3D_DUE_AT",
    "WORKER_ARGV",
    "Item34CheckpointError",
    "execute_24h_checkpoint",
    "execute_3d_checkpoint",
]
