"""Persistent idempotency for paid AI request admission.

Only SHA-256 digests and fixed billing markers are stored. Raw request keys,
request bodies, prompts, model reasoning, and generated content are never
persisted here.

Phase-one boundary: this module prevents duplicate admission/charge/primary
usage for a live key and makes completion/refund owner-only and at-most-once.
It does not replay SSE/results, take over stale leases, or make every downstream
side effect exactly-once across arbitrary process crashes.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

import billing
import db
import ai_operations


IDEMPOTENCY_HEADER = "X-Request-ID"
IDEMPOTENCY_STATES = frozenset({"running", "completed", "failed"})
FAILURE_CODES = frozenset({
    "request_failed",
    "stream_cancelled",
    "stream_failed",
    "stream_incomplete",
})
_OPERATION_SUBJECT_DOMAIN = b"noteai:ai-operation:subject:v1\0"
_OWNER_OPERATION_FIELDS = (
    "operation_id",
    "operation_kind",
    "status",
    "provider_phase",
    "priority",
    "available_at",
    "claim_count",
    "provider_attempt_count",
    "event_sequence",
    "result_count",
    "created_at",
    "updated_at",
    "started_at",
    "terminal_at",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def payload_hash(payload: Any) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return _sha256(canonical)


def normalize_request_id(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if len(normalized) > 512:
        raise ValueError("request id is too long")
    return normalized


def _operation_subject_hash(user_id: str) -> str:
    return hashlib.sha256(
        _OPERATION_SUBJECT_DOMAIN + str(user_id).encode("utf-8")
    ).hexdigest()


def _existing_admission(
    tx: db.Transaction,
    *,
    idempotency_request_id: str,
) -> dict[str, Any] | None:
    lock = " FOR UPDATE" if tx.postgres else ""
    link = tx.fetchone(
        "SELECT operation_id FROM ai_operation_admissions "
        f"WHERE idempotency_request_id=?{lock}",
        (idempotency_request_id,),
    )
    if not link:
        return None
    operation = tx.fetchone(
        f"SELECT id,status FROM ai_operations WHERE id=?{lock}",
        (link["operation_id"],),
    )
    if not operation:
        raise RuntimeError("admitted operation row unavailable")
    return {
        "state": "existing",
        "operation_id": operation["id"],
        "status": operation["status"],
    }


def admit_operation(
    *,
    user_id: str,
    operation: str,
    request_id: str,
    payload: Any,
) -> dict[str, Any]:
    """Atomically bind one paid idempotency claim to one queued AI operation.

    This admission path is intentionally not wired to API routes. It stores no
    raw request content and does not activate billing's request-local usage
    context; a future worker must activate the persisted usage id explicitly.
    """
    normalized = normalize_request_id(request_id)
    if not normalized:
        raise ValueError("request id is required")
    key_digest = _sha256(normalized)
    body_digest = payload_hash(payload)
    lease_digest = _sha256(secrets.token_urlsafe(32))
    now = _now()
    try:
        lease_seconds = max(
            60,
            int(
                os.environ.get("NOTEAI_IDEMPOTENCY_LEASE_SECONDS", "1800")
                or 1800
            ),
        )
    except Exception:
        lease_seconds = 1800
    request_row_id = str(uuid.uuid4())
    operation_id = str(uuid.uuid4())
    now_iso = _iso(now)

    with db.transaction(write=True) as tx:
        user_lock = " FOR UPDATE" if tx.postgres else ""
        if not tx.fetchone(
            f"SELECT id FROM users WHERE id=?{user_lock}",
            (user_id,),
        ):
            raise HTTPException(status_code=401, detail="登录账号不存在或已失效")
        cursor = tx.execute(
            "INSERT INTO idempotency_requests("
            "id,user_id,operation,key_hash,payload_hash,status,lease_token_hash,"
            "lease_expires_at,created_at,updated_at) "
            "VALUES(?,?,?,?,?,'running',?,?,?,?) "
            "ON CONFLICT(user_id,operation,key_hash) DO NOTHING",
            (
                request_row_id,
                user_id,
                operation,
                key_digest,
                body_digest,
                lease_digest,
                _iso(now + timedelta(seconds=lease_seconds)),
                now_iso,
                now_iso,
            ),
        )
        inserted = int(getattr(cursor, "rowcount", 0) or 0) == 1
        row_lock = " FOR UPDATE" if tx.postgres else ""
        row = tx.fetchone(
            "SELECT * FROM idempotency_requests "
            f"WHERE user_id=? AND operation=? AND key_hash=?{row_lock}",
            (user_id, operation, key_digest),
        )
        if not row:
            raise RuntimeError("idempotency admission row unavailable")
        existing = dict(row)
        if not inserted:
            if str(existing.get("payload_hash") or "") != body_digest:
                return {"state": "conflict"}
            linked = _existing_admission(
                tx,
                idempotency_request_id=str(existing["id"]),
            )
            return linked or {"state": "legacy_unlinked"}

        ai_operations.enqueue_operation_in_transaction(
            tx,
            subject_hash=_operation_subject_hash(user_id),
            request_hash=body_digest,
            operation_kind=operation,
            operation_id=operation_id,
            now=now,
        )
        tx.execute(
            "INSERT INTO ai_operation_admissions("
            "operation_id,idempotency_request_id,created_at) VALUES(?,?,?)",
            (operation_id, request_row_id, now_iso),
        )
        charge = billing.check_and_deduct_in_transaction(tx, user_id, operation)
        tx.execute(
            "UPDATE idempotency_requests SET usage_id=?,charged_subscription_id=?,"
            "charged_period_start=?,charge_source=?,credits_used=?,"
            "monthly_credits_used=?,wallet_credits_used=?,usage_created=1,charge_applied=1,"
            "usage_created_at=?,charged_at=?,updated_at=? WHERE id=?",
            (
                charge.get("usage_id"),
                charge.get("subscription_id") or None,
                charge.get("subscription_period_start") or None,
                charge.get("source") or "",
                float(charge.get("credits_used") or 0),
                float(charge.get("monthly_credits_used") or 0),
                float(charge.get("wallet_credits_used") or 0),
                now_iso,
                now_iso,
                now_iso,
                request_row_id,
            ),
        )

    return {
        "state": "admitted",
        "operation_id": operation_id,
        "status": ai_operations.OperationStatus.QUEUED.value,
    }


def get_admitted_operation_for_user(
    user_id: str,
    operation_id: str,
) -> dict[str, Any] | None:
    """Return a fixed safe projection only when the linked claim belongs to user."""
    row = db.fetchone(
        "SELECT o.id AS operation_id,o.operation_kind,o.status,o.provider_phase,"
        "o.priority,o.available_at,o.claim_count,o.provider_attempt_count,"
        "o.event_sequence,o.result_count,o.created_at,o.updated_at,o.started_at,"
        "o.terminal_at FROM ai_operations o "
        "JOIN ai_operation_admissions a ON a.operation_id=o.id "
        "JOIN idempotency_requests i ON i.id=a.idempotency_request_id "
        "WHERE i.user_id=? AND o.id=?",
        (str(user_id or ""), str(operation_id or "")),
    )
    if not row:
        return None
    result = dict(row)
    return {field: result.get(field) for field in _OWNER_OPERATION_FIELDS}


def claim_and_charge(
    *,
    user_id: str,
    operation: str,
    request_id: str,
    payload: Any,
) -> dict[str, Any]:
    """Atomically claim a key and apply one paid charge + primary usage row."""
    normalized = normalize_request_id(request_id)
    if not normalized:
        raise ValueError("request id is required")
    key_digest = _sha256(normalized)
    body_digest = payload_hash(payload)
    lease_token = secrets.token_urlsafe(32)
    lease_digest = _sha256(lease_token)
    now = _now()
    try:
        lease_seconds = max(60, int(os.environ.get("NOTEAI_IDEMPOTENCY_LEASE_SECONDS", "1800") or 1800))
    except Exception:
        lease_seconds = 1800
    request_row_id = str(uuid.uuid4())

    with db.transaction(write=True) as tx:
        # Keep one global lock order for all subscription/billing mutations:
        # users row first, then idempotency/subscription/credit rows. In
        # PostgreSQL the idempotency FK insert otherwise takes a shared user
        # tuple lock that concurrent claims later try to upgrade, causing a
        # deadlock. SQLite is already serialized by BEGIN IMMEDIATE, but uses
        # the same existence check for identical semantics.
        user_lock = " FOR UPDATE" if tx.postgres else ""
        if not tx.fetchone(f"SELECT id FROM users WHERE id=?{user_lock}", (user_id,)):
            raise HTTPException(status_code=401, detail="登录账号不存在或已失效")
        cursor = tx.execute(
            "INSERT INTO idempotency_requests("
            "id,user_id,operation,key_hash,payload_hash,status,lease_token_hash,"
            "lease_expires_at,created_at,updated_at) "
            "VALUES(?,?,?,?,?,'running',?,?,?,?) "
            "ON CONFLICT(user_id,operation,key_hash) DO NOTHING",
            (
                request_row_id,
                user_id,
                operation,
                key_digest,
                body_digest,
                lease_digest,
                _iso(now + timedelta(seconds=lease_seconds)),
                _iso(now),
                _iso(now),
            ),
        )
        inserted = int(getattr(cursor, "rowcount", 0) or 0) == 1
        lock = " FOR UPDATE" if tx.postgres else ""
        row = tx.fetchone(
            "SELECT * FROM idempotency_requests "
            f"WHERE user_id=? AND operation=? AND key_hash=?{lock}",
            (user_id, operation, key_digest),
        )
        if not row:
            raise RuntimeError("idempotency claim row unavailable")
        existing = dict(row)
        if not inserted:
            if str(existing.get("payload_hash") or "") != body_digest:
                return {"state": "conflict"}
            status = str(existing.get("status") or "running")
            if status not in IDEMPOTENCY_STATES:
                status = "running"
            return {
                "state": "in_progress" if status == "running" else status,
                "failure_code": str(existing.get("failure_code") or "")
                if status == "failed" else "",
            }

        charge = billing.check_and_deduct_in_transaction(tx, user_id, operation)
        tx.execute(
            "UPDATE idempotency_requests SET usage_id=?,charged_subscription_id=?,"
            "charged_period_start=?,charge_source=?,credits_used=?,"
            "monthly_credits_used=?,wallet_credits_used=?,usage_created=1,charge_applied=1,"
            "usage_created_at=?,charged_at=?,updated_at=? WHERE id=?",
            (
                charge.get("usage_id"),
                charge.get("subscription_id") or None,
                charge.get("subscription_period_start") or None,
                charge.get("source") or "",
                float(charge.get("credits_used") or 0),
                float(charge.get("monthly_credits_used") or 0),
                float(charge.get("wallet_credits_used") or 0),
                _iso(now),
                _iso(now),
                _iso(now),
                request_row_id,
            ),
        )

    billing.activate_usage(charge.get("usage_id"))
    return {
        "state": "owner",
        "request_id": request_row_id,
        "user_id": user_id,
        "operation": operation,
        "key_hash": key_digest,
        "payload_hash": body_digest,
        "lease_token": lease_token,
        "charge": charge,
    }


def _owned_row(tx: db.Transaction, context: dict[str, Any]):
    lock = " FOR UPDATE" if tx.postgres else ""
    return tx.fetchone(
        f"SELECT * FROM idempotency_requests WHERE id=?{lock}",
        (context.get("request_id"),),
    )


def mark_completed(context: dict[str, Any] | None) -> bool:
    if not context or context.get("state") != "owner":
        return False
    lease_digest = _sha256(str(context.get("lease_token") or ""))
    now = _iso()
    with db.transaction(write=True) as tx:
        row = _owned_row(tx, context)
        if not row:
            return False
        current = dict(row)
        if current.get("status") == "completed" and current.get("complete_applied"):
            return False
        if current.get("status") != "running" or current.get("lease_token_hash") != lease_digest:
            return False
        tx.execute(
            "UPDATE idempotency_requests SET status='completed',complete_applied=1,"
            "completed_at=?,updated_at=? WHERE id=?",
            (now, now, context["request_id"]),
        )
    return True


def mark_failed_and_refund(
    context: dict[str, Any] | None,
    *,
    failure_code: str = "request_failed",
) -> bool:
    if not context or context.get("state") != "owner":
        return False
    safe_code = failure_code if failure_code in FAILURE_CODES else "request_failed"
    lease_digest = _sha256(str(context.get("lease_token") or ""))
    now = _iso()
    with db.transaction(write=True) as tx:
        row = _owned_row(tx, context)
        if not row:
            return False
        current = dict(row)
        if current.get("status") == "failed" and current.get("refund_applied"):
            return False
        if current.get("status") != "running" or current.get("lease_token_hash") != lease_digest:
            return False
        charge = {
            "usage_id": current.get("usage_id"),
            "subscription_id": current.get("charged_subscription_id"),
            "subscription_period_start": current.get("charged_period_start"),
            "source": current.get("charge_source") or "",
            "credits_used": float(current.get("credits_used") or 0),
            "monthly_credits_used": float(current.get("monthly_credits_used") or 0),
            "wallet_credits_used": float(current.get("wallet_credits_used") or 0),
        }
        if current.get("charge_applied") and not current.get("refund_applied"):
            billing.refund_operation_charge_in_transaction(
                tx,
                str(current.get("user_id") or ""),
                str(current.get("operation") or ""),
                charge,
                "AI 请求失败自动退回",
            )
        tx.execute(
            "UPDATE idempotency_requests SET status='failed',refund_applied=1,"
            "failure_code=?,refunded_at=?,failed_at=?,updated_at=? WHERE id=?",
            (safe_code, now, now, now, context["request_id"]),
        )
    return True
