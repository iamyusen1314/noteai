"""Durable, content-free state transitions for queued AI operations.

This module deliberately stores only opaque identifiers, SHA-256 digests,
fixed enums, counters, fences, and timestamps. It does not persist request or
response content and it never calls an AI provider, API route, or billing code.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

import db


class OperationKind(str, Enum):
    ANALYZE = "analyze"
    GENERATE = "generate"
    CHAT_REWRITE = "chat_rewrite"


class OperationStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    OUTCOME_UNKNOWN = "outcome_unknown"
    CANCELLED = "cancelled"


class ProviderPhase(str, Enum):
    NOT_STARTED = "not_started"
    STARTED = "provider_started"
    TERMINAL = "provider_terminal"


class Provider(str, Enum):
    CLAUDE = "claude"
    KIMI = "kimi"


class EventType(str, Enum):
    ENQUEUED = "enqueued"
    CLAIMED = "claimed"
    LEASE_TAKEN_OVER = "lease_taken_over"
    PROGRESS = "progress"
    PROVIDER_STARTED = "provider_started"
    PROVIDER_TERMINAL = "provider_terminal"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    OUTCOME_UNKNOWN = "outcome_unknown"
    CANCELLED = "cancelled"


class AttemptState(str, Enum):
    STARTED = "provider_started"
    SUCCEEDED = "provider_succeeded"
    FAILED = "provider_failed"
    OUTCOME_UNKNOWN = "outcome_unknown"


TERMINAL_OPERATION_STATUSES = frozenset({
    OperationStatus.SUCCEEDED.value,
    OperationStatus.FAILED.value,
    OperationStatus.OUTCOME_UNKNOWN.value,
    OperationStatus.CANCELLED.value,
})

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class OperationLease:
    operation_id: str
    owner_token: str = field(repr=False)
    fence: int
    expires_at: str


@dataclass(frozen=True)
class ProviderAttempt:
    attempt_id: str
    operation_id: str
    attempt_number: int
    fence: int
    provider: str
    state: str


def sha256_digest(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else str(value).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return current.astimezone(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return _now(value).isoformat()


def _enum_value(value: str | Enum, enum_type: type[Enum], label: str) -> str:
    raw = value.value if isinstance(value, Enum) else str(value or "")
    allowed = {item.value for item in enum_type}
    if raw not in allowed:
        raise ValueError(f"invalid {label}")
    return raw


def _digest(value: str | None, label: str, *, optional: bool = False) -> str | None:
    raw = str(value or "").strip().lower()
    if optional and not raw:
        return None
    if not _SHA256_RE.fullmatch(raw):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return raw


def _count(value: int, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a non-negative integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a non-negative integer") from exc
    if normalized < 0 or normalized != value:
        raise ValueError(f"{label} must be a non-negative integer")
    return normalized


def _priority(value: int) -> int:
    normalized = _count(value, "priority")
    if normalized > 9:
        raise ValueError("priority must be between 0 and 9")
    return normalized


def _lease_seconds(value: int) -> int:
    normalized = _count(value, "lease_seconds")
    if normalized < 1 or normalized > 86400:
        raise ValueError("lease_seconds must be between 1 and 86400")
    return normalized


def _reap_limit(value: int) -> int:
    normalized = _count(value, "reap_limit")
    if normalized < 1 or normalized > 100:
        raise ValueError("reap_limit must be between 1 and 100")
    return normalized


def _operation_id(value: str | None) -> str:
    raw = str(value or uuid.uuid4()).strip()
    try:
        parsed = uuid.UUID(raw)
    except (ValueError, AttributeError) as exc:
        raise ValueError("operation id must be a canonical UUID") from exc
    if str(parsed) != raw:
        raise ValueError("invalid operation id")
    return raw


def _lock_suffix(tx: db.Transaction, *, skip_locked: bool = False) -> str:
    if not tx.postgres:
        return ""
    return " FOR UPDATE SKIP LOCKED" if skip_locked else " FOR UPDATE"


def _row_for_update(tx: db.Transaction, operation_id: str):
    return tx.fetchone(
        f"SELECT * FROM ai_operations WHERE id=?{_lock_suffix(tx)}",
        (operation_id,),
    )


def _lease_matches(row: dict[str, Any], lease: OperationLease, now_iso: str) -> bool:
    return bool(
        row.get("status") == OperationStatus.RUNNING.value
        and int(row.get("lease_fence") or 0) == int(lease.fence)
        and row.get("lease_owner_hash") == sha256_digest(lease.owner_token)
        and str(row.get("lease_expires_at") or "") > now_iso
    )


def _append_event_tx(
    tx: db.Transaction,
    row: dict[str, Any],
    event_type: str | EventType,
    recorded_at: str,
    *,
    provider: str | Provider | None = None,
    detail_hash: str | None = None,
    item_count: int = 0,
) -> int:
    event = _enum_value(event_type, EventType, "event type")
    provider_value = (
        _enum_value(provider, Provider, "provider") if provider is not None else None
    )
    detail = _digest(detail_hash, "detail_hash", optional=True)
    count = _count(item_count, "item_count")
    status = _enum_value(row.get("status"), OperationStatus, "operation status")
    sequence = int(row.get("event_sequence") or 0) + 1
    tx.execute(
        "INSERT INTO ai_operation_events("
        "id,operation_id,sequence,event_type,operation_status,fence,provider,"
        "detail_hash,item_count,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            str(uuid.uuid4()),
            row["id"],
            sequence,
            event,
            status,
            int(row.get("lease_fence") or 0),
            provider_value,
            detail,
            count,
            recorded_at,
        ),
    )
    tx.execute(
        "UPDATE ai_operations SET event_sequence=?,updated_at=? WHERE id=?",
        (sequence, recorded_at, row["id"]),
    )
    row["event_sequence"] = sequence
    row["updated_at"] = recorded_at
    return sequence


def enqueue_operation_in_transaction(
    tx: db.Transaction,
    *,
    subject_hash: str,
    request_hash: str,
    operation_kind: str | OperationKind,
    operation_id: str | None = None,
    priority: int = 0,
    available_at: datetime | None = None,
    now: datetime | None = None,
) -> str:
    """Create one queued operation and its first event in the caller's transaction."""
    op_id = _operation_id(operation_id)
    subject = _digest(subject_hash, "subject_hash")
    request = _digest(request_hash, "request_hash")
    kind = _enum_value(operation_kind, OperationKind, "operation kind")
    normalized_priority = _priority(priority)
    now_iso = _iso(now)
    available_iso = _iso(available_at or _now(now))
    tx.execute(
        "INSERT INTO ai_operations("
        "id,subject_hash,request_hash,operation_kind,status,provider_phase,"
        "priority,available_at,created_at,updated_at) "
        "VALUES(?,?,?,?,'queued','not_started',?,?,?,?)",
        (
            op_id,
            subject,
            request,
            kind,
            normalized_priority,
            available_iso,
            now_iso,
            now_iso,
        ),
    )
    row = _row_for_update(tx, op_id)
    if not row:
        raise RuntimeError("queued operation row unavailable")
    _append_event_tx(tx, dict(row), EventType.ENQUEUED, now_iso)
    return op_id


def enqueue_operation(
    *,
    subject_hash: str,
    request_hash: str,
    operation_kind: str | OperationKind,
    operation_id: str | None = None,
    priority: int = 0,
    available_at: datetime | None = None,
    now: datetime | None = None,
) -> str:
    with db.transaction(write=True) as tx:
        return enqueue_operation_in_transaction(
            tx,
            subject_hash=subject_hash,
            request_hash=request_hash,
            operation_kind=operation_kind,
            operation_id=operation_id,
            priority=priority,
            available_at=available_at,
            now=now,
        )


def _claimable_lane_row(
    tx: db.Transaction,
    now_iso: str,
    *,
    priority_lane: bool,
):
    priority_predicate = "priority>0" if priority_lane else "priority=0"
    return tx.fetchone(
        "SELECT * FROM ai_operations WHERE "
        "((status='queued' AND available_at<=?) OR "
        "(status='running' AND provider_phase='not_started' "
        "AND lease_expires_at IS NOT NULL AND lease_expires_at<=?)) "
        f"AND {priority_predicate} "
        "ORDER BY created_at,id LIMIT 1"
        f"{_lock_suffix(tx, skip_locked=True)}",
        (now_iso, now_iso),
    )


def _claimable_row(tx: db.Transaction, now_iso: str):
    """Select with a durable 3:1 priority/standard dispatch ceiling.

    A priority-only backlog advances the streak to three, so a standard job
    arriving later receives the next slot. FIFO is preserved inside each lane.
    The singleton dispatch row serializes this decision on PostgreSQL; SQLite
    writers are already serialized by ``BEGIN IMMEDIATE``.
    """
    state_lock = _lock_suffix(tx)
    state = tx.fetchone(
        f"SELECT priority_streak FROM ai_dispatch_state "
        f"WHERE service_key='durable_ai'{state_lock}"
    )
    if not state:
        tx.execute(
            "INSERT INTO ai_dispatch_state(service_key,priority_streak,updated_at) "
            "VALUES('durable_ai',0,?) ON CONFLICT(service_key) DO NOTHING",
            (now_iso,),
        )
        state = tx.fetchone(
            f"SELECT priority_streak FROM ai_dispatch_state "
            f"WHERE service_key='durable_ai'{state_lock}"
        )
    state_data = dict(state) if state else {}
    streak = min(3, max(0, int(state_data.get("priority_streak") or 0)))
    priority_candidate = _claimable_lane_row(tx, now_iso, priority_lane=True)
    standard_candidate = _claimable_lane_row(tx, now_iso, priority_lane=False)
    priority_row = dict(priority_candidate) if priority_candidate else None
    standard_row = dict(standard_candidate) if standard_candidate else None
    if priority_row and standard_row:
        selected = standard_row if streak >= 3 else priority_row
    else:
        selected = priority_row or standard_row
    if not selected:
        return None
    next_streak = min(3, streak + 1) if int(selected.get("priority") or 0) > 0 else 0
    tx.execute(
        "UPDATE ai_dispatch_state SET priority_streak=?,updated_at=? "
        "WHERE service_key='durable_ai'",
        (next_streak, now_iso),
    )
    return selected


def _unsafe_stale_row(tx: db.Transaction, now_iso: str):
    return tx.fetchone(
        "SELECT * FROM ai_operations WHERE status='running' "
        "AND provider_phase<>'not_started' AND lease_expires_at IS NOT NULL "
        "AND lease_expires_at<=? ORDER BY lease_expires_at,id LIMIT 1"
        f"{_lock_suffix(tx, skip_locked=True)}",
        (now_iso,),
    )


def _quarantine_stale_started_tx(
    tx: db.Transaction,
    row: dict[str, Any],
    now_iso: str,
) -> None:
    attempt = tx.fetchone(
        "SELECT * FROM ai_provider_attempts WHERE operation_id=? "
        "ORDER BY attempt_number DESC LIMIT 1"
        f"{_lock_suffix(tx)}",
        (row["id"],),
    )
    provider = None
    if attempt:
        attempt_data = dict(attempt)
        provider = attempt_data.get("provider")
        if attempt_data.get("state") == AttemptState.STARTED.value:
            tx.execute(
                "UPDATE ai_provider_attempts SET state='outcome_unknown',"
                "updated_at=?,terminal_at=? WHERE id=? AND state='provider_started'",
                (now_iso, now_iso, attempt_data["id"]),
            )
    tx.execute(
        "UPDATE ai_operations SET status='outcome_unknown',provider_phase='provider_terminal',"
        "lease_owner_hash=NULL,lease_expires_at=NULL,terminal_at=?,updated_at=? WHERE id=?",
        (now_iso, now_iso, row["id"]),
    )
    row["status"] = OperationStatus.OUTCOME_UNKNOWN.value
    row["provider_phase"] = ProviderPhase.TERMINAL.value
    row["lease_owner_hash"] = None
    row["lease_expires_at"] = None
    _append_event_tx(
        tx,
        row,
        EventType.OUTCOME_UNKNOWN,
        now_iso,
        provider=provider,
    )


def quarantine_stale_started_in_transaction(
    tx: db.Transaction,
    row: dict[str, Any],
    *,
    now_iso: str,
) -> None:
    """Public transaction hook for settlement-aware durable reconciliation."""
    _quarantine_stale_started_tx(tx, row, now_iso)


def _reap_stale_provider_outcomes_tx(
    tx: db.Transaction,
    now_iso: str,
    limit: int,
) -> int:
    reaped = 0
    for _index in range(limit):
        stale = _unsafe_stale_row(tx, now_iso)
        if not stale:
            break
        _quarantine_stale_started_tx(tx, dict(stale), now_iso)
        reaped += 1
    return reaped


def reap_stale_provider_outcomes(
    *,
    limit: int = 1,
    now: datetime | None = None,
) -> int:
    bounded_limit = _reap_limit(limit)
    now_iso = _iso(now)
    with db.transaction(write=True) as tx:
        return _reap_stale_provider_outcomes_tx(tx, now_iso, bounded_limit)


def claim_next_operation(
    *,
    lease_seconds: int,
    owner_token: str | None = None,
    reap_limit: int = 1,
    now: datetime | None = None,
) -> OperationLease | None:
    seconds = _lease_seconds(lease_seconds)
    bounded_reap_limit = _reap_limit(reap_limit)
    token = str(owner_token or secrets.token_urlsafe(32))
    if len(token) < 16 or len(token) > 512:
        raise ValueError("owner token length is invalid")
    now_value = _now(now)
    now_iso = _iso(now_value)
    expires_iso = _iso(now_value + timedelta(seconds=seconds))
    owner_hash = sha256_digest(token)
    with db.transaction(write=True) as tx:
        _reap_stale_provider_outcomes_tx(tx, now_iso, bounded_reap_limit)
        row = _claimable_row(tx, now_iso)
        if not row:
            return None
        return _take_operation_lease_tx(
            tx,
            dict(row),
            token=token,
            owner_hash=owner_hash,
            now_iso=now_iso,
            expires_iso=expires_iso,
        )


def _take_operation_lease_tx(
    tx: db.Transaction,
    current: dict[str, Any],
    *,
    token: str,
    owner_hash: str,
    now_iso: str,
    expires_iso: str,
) -> OperationLease:
    takeover = current.get("status") == OperationStatus.RUNNING.value
    fence = int(current.get("lease_fence") or 0) + 1
    tx.execute(
        "UPDATE ai_operations SET status='running',lease_owner_hash=?,lease_fence=?,"
        "lease_expires_at=?,heartbeat_at=?,claim_count=claim_count+1,"
        "started_at=COALESCE(started_at,?),updated_at=? WHERE id=?",
        (
            owner_hash,
            fence,
            expires_iso,
            now_iso,
            now_iso,
            now_iso,
            current["id"],
        ),
    )
    current.update({
        "status": OperationStatus.RUNNING.value,
        "lease_owner_hash": owner_hash,
        "lease_fence": fence,
        "lease_expires_at": expires_iso,
        "heartbeat_at": now_iso,
    })
    _append_event_tx(
        tx,
        current,
        EventType.LEASE_TAKEN_OVER if takeover else EventType.CLAIMED,
        now_iso,
    )
    return OperationLease(current["id"], token, fence, expires_iso)


def claim_operation_in_transaction(
    tx: db.Transaction,
    operation_id: str,
    *,
    lease_seconds: int,
    owner_token: str | None = None,
    now: datetime | None = None,
) -> OperationLease | None:
    """Claim one operation while the caller owns the surrounding transaction."""
    op_id = _operation_id(operation_id)
    seconds = _lease_seconds(lease_seconds)
    token = str(owner_token or secrets.token_urlsafe(32))
    if len(token) < 16 or len(token) > 512:
        raise ValueError("owner token length is invalid")
    now_value = _now(now)
    now_iso = _iso(now_value)
    expires_iso = _iso(now_value + timedelta(seconds=seconds))
    row = _row_for_update(tx, op_id)
    if not row:
        return None
    current = dict(row)
    claimable = (
        current.get("status") == OperationStatus.QUEUED.value
        and str(current.get("available_at") or "") <= now_iso
    ) or (
        current.get("status") == OperationStatus.RUNNING.value
        and current.get("provider_phase") == ProviderPhase.NOT_STARTED.value
        and str(current.get("lease_expires_at") or "") <= now_iso
    )
    if not claimable:
        return None
    return _take_operation_lease_tx(
        tx,
        current,
        token=token,
        owner_hash=sha256_digest(token),
        now_iso=now_iso,
        expires_iso=expires_iso,
    )


def claim_operation(
    operation_id: str,
    *,
    lease_seconds: int,
    owner_token: str | None = None,
    now: datetime | None = None,
) -> OperationLease | None:
    """Claim one content-free operation id."""
    with db.transaction(write=True) as tx:
        return claim_operation_in_transaction(
            tx,
            operation_id,
            lease_seconds=lease_seconds,
            owner_token=owner_token,
            now=now,
        )


def heartbeat_operation(
    lease: OperationLease,
    *,
    lease_seconds: int,
    now: datetime | None = None,
) -> OperationLease | None:
    seconds = _lease_seconds(lease_seconds)
    now_value = _now(now)
    now_iso = _iso(now_value)
    expires_iso = _iso(now_value + timedelta(seconds=seconds))
    with db.transaction(write=True) as tx:
        row = _row_for_update(tx, lease.operation_id)
        if not row or not _lease_matches(dict(row), lease, now_iso):
            return None
        tx.execute(
            "UPDATE ai_operations SET lease_expires_at=?,heartbeat_at=?,updated_at=? "
            "WHERE id=?",
            (expires_iso, now_iso, now_iso, lease.operation_id),
        )
    return OperationLease(lease.operation_id, lease.owner_token, lease.fence, expires_iso)


def append_progress_event(
    lease: OperationLease,
    *,
    detail_hash: str | None = None,
    item_count: int = 0,
    now: datetime | None = None,
) -> bool:
    detail = _digest(detail_hash, "detail_hash", optional=True)
    count = _count(item_count, "item_count")
    now_iso = _iso(now)
    with db.transaction(write=True) as tx:
        row = _row_for_update(tx, lease.operation_id)
        if not row:
            return False
        current = dict(row)
        if not _lease_matches(current, lease, now_iso):
            return False
        _append_event_tx(
            tx,
            current,
            EventType.PROGRESS,
            now_iso,
            detail_hash=detail,
            item_count=count,
        )
    return True


def begin_provider_attempt(
    lease: OperationLease,
    *,
    provider: str | Provider,
    request_hash: str,
    model_hash: str,
    input_count: int = 0,
    now: datetime | None = None,
) -> ProviderAttempt | None:
    now_iso = _iso(now)
    with db.transaction(write=True) as tx:
        return begin_provider_attempt_in_transaction(
            tx,
            lease,
            provider=provider,
            request_hash=request_hash,
            model_hash=model_hash,
            input_count=input_count,
            now_iso=now_iso,
        )


def begin_provider_attempt_in_transaction(
    tx: db.Transaction,
    lease: OperationLease,
    *,
    provider: str | Provider,
    request_hash: str,
    model_hash: str,
    input_count: int = 0,
    now_iso: str,
) -> ProviderAttempt | None:
    """Fence a provider attempt inside a caller-held user transaction."""
    provider_value = _enum_value(provider, Provider, "provider")
    request = _digest(request_hash, "request_hash")
    model = _digest(model_hash, "model_hash")
    inputs = _count(input_count, "input_count")
    row = _row_for_update(tx, lease.operation_id)
    if not row:
        return None
    current = dict(row)
    phase = current.get("provider_phase")
    if (
        not _lease_matches(current, lease, now_iso)
        or phase not in {
            ProviderPhase.NOT_STARTED.value,
            ProviderPhase.TERMINAL.value,
        }
    ):
        return None
    if phase == ProviderPhase.TERMINAL.value:
        latest = tx.fetchone(
            "SELECT state FROM ai_provider_attempts WHERE operation_id=? "
            "ORDER BY attempt_number DESC LIMIT 1"
            f"{_lock_suffix(tx)}",
            (lease.operation_id,),
        )
        if not latest or latest["state"] not in {
            AttemptState.SUCCEEDED.value,
            AttemptState.FAILED.value,
        }:
            return None
    attempt_number = int(current.get("provider_attempt_count") or 0) + 1
    attempt_id = str(uuid.uuid4())
    tx.execute(
        "INSERT INTO ai_provider_attempts("
        "id,operation_id,attempt_number,fence,provider,state,request_hash,model_hash,"
        "input_count,output_count,started_at,updated_at) "
        "VALUES(?,?,?,?,?,'provider_started',?,?,?,0,?,?)",
        (
            attempt_id,
            lease.operation_id,
            attempt_number,
            lease.fence,
            provider_value,
            request,
            model,
            inputs,
            now_iso,
            now_iso,
        ),
    )
    tx.execute(
        "UPDATE ai_operations SET provider_phase='provider_started',"
        "provider_attempt_count=?,updated_at=? WHERE id=?",
        (attempt_number, now_iso, lease.operation_id),
    )
    current["provider_phase"] = ProviderPhase.STARTED.value
    current["provider_attempt_count"] = attempt_number
    _append_event_tx(
        tx,
        current,
        EventType.PROVIDER_STARTED,
        now_iso,
        provider=provider_value,
        detail_hash=model,
        item_count=inputs,
    )
    return ProviderAttempt(
        attempt_id,
        lease.operation_id,
        attempt_number,
        lease.fence,
        provider_value,
        AttemptState.STARTED.value,
    )


def finish_provider_attempt(
    lease: OperationLease,
    attempt: ProviderAttempt,
    *,
    state: str | AttemptState,
    response_hash: str | None = None,
    output_count: int = 0,
    now: datetime | None = None,
) -> bool:
    target = _enum_value(state, AttemptState, "attempt state")
    if target == AttemptState.STARTED.value:
        raise ValueError("provider attempt is already started")
    response = _digest(response_hash, "response_hash", optional=True)
    outputs = _count(output_count, "output_count")
    if target == AttemptState.SUCCEEDED.value and response is None:
        raise ValueError("successful provider attempt requires response_hash")
    now_iso = _iso(now)
    with db.transaction(write=True) as tx:
        row = _row_for_update(tx, lease.operation_id)
        if not row:
            return False
        current = dict(row)
        if not _lease_matches(current, lease, now_iso):
            return False
        lock = _lock_suffix(tx)
        attempt_row = tx.fetchone(
            f"SELECT * FROM ai_provider_attempts WHERE id=?{lock}",
            (attempt.attempt_id,),
        )
        if not attempt_row:
            return False
        stored = dict(attempt_row)
        if not (
            stored.get("operation_id") == lease.operation_id
            and int(stored.get("fence") or 0) == lease.fence
            and stored.get("state") == AttemptState.STARTED.value
            and current.get("provider_phase") == ProviderPhase.STARTED.value
            and int(current.get("provider_attempt_count") or 0)
            == int(stored.get("attempt_number") or 0)
            and attempt.operation_id == lease.operation_id
            and attempt.fence == lease.fence
            and attempt.attempt_number == int(stored.get("attempt_number") or 0)
            and attempt.provider == stored.get("provider")
        ):
            return False
        tx.execute(
            "UPDATE ai_provider_attempts SET state=?,response_hash=?,output_count=?,"
            "updated_at=?,terminal_at=? WHERE id=? AND state='provider_started'",
            (target, response, outputs, now_iso, now_iso, attempt.attempt_id),
        )
        if target == AttemptState.OUTCOME_UNKNOWN.value:
            tx.execute(
                "UPDATE ai_operations SET status='outcome_unknown',"
                "provider_phase='provider_terminal',lease_owner_hash=NULL,"
                "lease_expires_at=NULL,terminal_at=?,updated_at=? WHERE id=?",
                (now_iso, now_iso, lease.operation_id),
            )
            current["status"] = OperationStatus.OUTCOME_UNKNOWN.value
            current["provider_phase"] = ProviderPhase.TERMINAL.value
            current["lease_owner_hash"] = None
            current["lease_expires_at"] = None
            event = EventType.OUTCOME_UNKNOWN
        else:
            tx.execute(
                "UPDATE ai_operations SET provider_phase='provider_terminal',updated_at=? "
                "WHERE id=?",
                (now_iso, lease.operation_id),
            )
            current["provider_phase"] = ProviderPhase.TERMINAL.value
            event = EventType.PROVIDER_TERMINAL
        _append_event_tx(
            tx,
            current,
            event,
            now_iso,
            provider=stored.get("provider"),
            detail_hash=response,
            item_count=outputs,
        )
    return True


def finish_operation(
    lease: OperationLease,
    *,
    status: str | OperationStatus,
    result_hash: str | None = None,
    result_count: int = 0,
    now: datetime | None = None,
) -> bool:
    now_iso = _iso(now)
    with db.transaction(write=True) as tx:
        return finish_operation_in_transaction(
            tx,
            lease,
            status=status,
            result_hash=result_hash,
            result_count=result_count,
            now_iso=now_iso,
        )


def finish_operation_in_transaction(
    tx: db.Transaction,
    lease: OperationLease,
    *,
    status: str | OperationStatus,
    result_hash: str | None = None,
    result_count: int = 0,
    now_iso: str,
) -> bool:
    """Apply a fenced terminal transition inside the caller's transaction."""
    target = _enum_value(status, OperationStatus, "operation status")
    allowed = {
        OperationStatus.SUCCEEDED.value,
        OperationStatus.FAILED.value,
        OperationStatus.CANCELLED.value,
    }
    if target not in allowed:
        raise ValueError("invalid worker terminal status")
    result = _digest(result_hash, "result_hash", optional=True)
    count = _count(result_count, "result_count")
    if target == OperationStatus.SUCCEEDED.value and result is None:
        raise ValueError("successful operation requires result_hash")
    if target != OperationStatus.SUCCEEDED.value and (result is not None or count != 0):
        raise ValueError("non-success terminal state cannot store result metadata")
    row = _row_for_update(tx, lease.operation_id)
    if not row:
        return False
    current = dict(row)
    if not _lease_matches(current, lease, now_iso):
        return False
    attempt = tx.fetchone(
        "SELECT * FROM ai_provider_attempts WHERE operation_id=? "
        "ORDER BY attempt_number DESC LIMIT 1"
        f"{_lock_suffix(tx)}",
        (lease.operation_id,),
    )
    attempt_state = dict(attempt).get("state") if attempt else None
    phase = current.get("provider_phase")
    if target == OperationStatus.SUCCEEDED.value and not (
        phase == ProviderPhase.TERMINAL.value
        and attempt_state == AttemptState.SUCCEEDED.value
    ):
        return False
    if target == OperationStatus.FAILED.value and not (
        phase == ProviderPhase.NOT_STARTED.value
        or (
            phase == ProviderPhase.TERMINAL.value
            and attempt_state == AttemptState.FAILED.value
        )
    ):
        return False
    if target == OperationStatus.CANCELLED.value and phase != ProviderPhase.NOT_STARTED.value:
        return False
    tx.execute(
        "UPDATE ai_operations SET status=?,result_hash=?,result_count=?,"
        "lease_owner_hash=NULL,lease_expires_at=NULL,terminal_at=?,updated_at=? "
        "WHERE id=?",
        (target, result, count, now_iso, now_iso, lease.operation_id),
    )
    current.update({
        "status": target,
        "result_hash": result,
        "result_count": count,
        "lease_owner_hash": None,
        "lease_expires_at": None,
    })
    _append_event_tx(
        tx,
        current,
        EventType(target),
        now_iso,
        detail_hash=result,
        item_count=count,
    )
    return True


def mark_operation_outcome_unknown_in_transaction(
    tx: db.Transaction,
    lease: OperationLease,
    *,
    now_iso: str,
) -> bool:
    """Quarantine a live lease after an externally ambiguous side effect."""
    row = _row_for_update(tx, lease.operation_id)
    if not row:
        return False
    current = dict(row)
    if not _lease_matches(current, lease, now_iso):
        return False
    attempt = tx.fetchone(
        "SELECT * FROM ai_provider_attempts WHERE operation_id=? "
        "ORDER BY attempt_number DESC LIMIT 1"
        f"{_lock_suffix(tx)}",
        (lease.operation_id,),
    )
    provider = None
    if attempt:
        attempt_data = dict(attempt)
        provider = attempt_data.get("provider")
        if attempt_data.get("state") == AttemptState.STARTED.value:
            tx.execute(
                "UPDATE ai_provider_attempts SET state='outcome_unknown',"
                "updated_at=?,terminal_at=? WHERE id=? AND state='provider_started'",
                (now_iso, now_iso, attempt_data["id"]),
            )
    if current.get("provider_phase") == ProviderPhase.NOT_STARTED.value:
        return False
    tx.execute(
        "UPDATE ai_operations SET status='outcome_unknown',"
        "provider_phase='provider_terminal',lease_owner_hash=NULL,"
        "lease_expires_at=NULL,terminal_at=?,updated_at=? WHERE id=?",
        (now_iso, now_iso, lease.operation_id),
    )
    current.update({
        "status": OperationStatus.OUTCOME_UNKNOWN.value,
        "provider_phase": ProviderPhase.TERMINAL.value,
        "lease_owner_hash": None,
        "lease_expires_at": None,
    })
    _append_event_tx(
        tx,
        current,
        EventType.OUTCOME_UNKNOWN,
        now_iso,
        provider=provider,
    )
    return True


def mark_operation_outcome_unknown(
    lease: OperationLease,
    *,
    now: datetime | None = None,
) -> bool:
    now_iso = _iso(now)
    with db.transaction(write=True) as tx:
        return mark_operation_outcome_unknown_in_transaction(
            tx,
            lease,
            now_iso=now_iso,
        )


def cancel_queued_operation(
    operation_id: str,
    *,
    now: datetime | None = None,
) -> bool:
    op_id = _operation_id(operation_id)
    now_iso = _iso(now)
    with db.transaction(write=True) as tx:
        row = _row_for_update(tx, op_id)
        if not row or row["status"] != OperationStatus.QUEUED.value:
            return False
        current = dict(row)
        tx.execute(
            "UPDATE ai_operations SET status='cancelled',terminal_at=?,updated_at=? "
            "WHERE id=? AND status='queued'",
            (now_iso, now_iso, op_id),
        )
        current["status"] = OperationStatus.CANCELLED.value
        _append_event_tx(tx, current, EventType.CANCELLED, now_iso)
    return True


def cancel_unstarted_operation_in_transaction(
    tx: db.Transaction,
    operation_id: str,
    *,
    now_iso: str,
) -> bool:
    """Cancel queued/provider-free work under the caller-held user fence."""
    op_id = _operation_id(operation_id)
    row = _row_for_update(tx, op_id)
    if not row:
        return False
    current = dict(row)
    if not (
        current.get("status") == OperationStatus.QUEUED.value
        or (
            current.get("status") == OperationStatus.RUNNING.value
            and current.get("provider_phase") == ProviderPhase.NOT_STARTED.value
        )
    ):
        return False
    fence = int(current.get("lease_fence") or 0) + 1
    tx.execute(
        "UPDATE ai_operations SET status='cancelled',lease_fence=?,"
        "lease_owner_hash=NULL,lease_expires_at=NULL,terminal_at=?,updated_at=? "
        "WHERE id=?",
        (fence, now_iso, now_iso, op_id),
    )
    current.update({
        "status": OperationStatus.CANCELLED.value,
        "lease_fence": fence,
        "lease_owner_hash": None,
        "lease_expires_at": None,
    })
    _append_event_tx(tx, current, EventType.CANCELLED, now_iso)
    return True


def get_operation(operation_id: str) -> dict[str, Any] | None:
    op_id = _operation_id(operation_id)
    row = db.fetchone(
        "SELECT id,subject_hash,request_hash,operation_kind,status,provider_phase,"
        "priority,available_at,lease_fence,lease_expires_at,heartbeat_at,claim_count,"
        "provider_attempt_count,event_sequence,result_hash,result_count,created_at,"
        "updated_at,started_at,terminal_at FROM ai_operations WHERE id=?",
        (op_id,),
    )
    return dict(row) if row else None


def list_events(operation_id: str, *, after_sequence: int = 0) -> list[dict[str, Any]]:
    op_id = _operation_id(operation_id)
    after = _count(after_sequence, "after_sequence")
    return [
        dict(row)
        for row in db.fetchall(
            "SELECT id,operation_id,sequence,event_type,operation_status,fence,"
            "provider,detail_hash,item_count,recorded_at FROM ai_operation_events "
            "WHERE operation_id=? AND sequence>? ORDER BY sequence",
            (op_id, after),
        )
    ]


def list_provider_attempts(operation_id: str) -> list[dict[str, Any]]:
    op_id = _operation_id(operation_id)
    return [
        dict(row)
        for row in db.fetchall(
            "SELECT id,operation_id,attempt_number,fence,provider,state,request_hash,"
            "model_hash,response_hash,input_count,output_count,started_at,updated_at,"
            "terminal_at FROM ai_provider_attempts WHERE operation_id=? "
            "ORDER BY attempt_number",
            (op_id,),
        )
    ]
