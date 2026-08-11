#!/usr/bin/env python3
"""Bounded provider-free production acceptance admission and observation.

Run this controller only through the fixed C17 carrier with an exact API
database login and the existing private-storage environment. It creates one
synthetic account/job, observes only that deterministic namespace, and uses
the product's account-deletion path to erase the external payload and primary
account after terminal proof.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


CONTAINER_MODEL_DIR = Path("/app/model")
if CONTAINER_MODEL_DIR.is_dir():
    MODEL_DIR = CONTAINER_MODEL_DIR
else:
    MODEL_DIR = Path(__file__).resolve().parents[2] / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

import auth  # noqa: E402
import content_retention  # noqa: E402
import db  # noqa: E402
import durable_ai  # noqa: E402
import private_storage  # noqa: E402


TASK_ID = "PROD-FIRST-LAUNCH-DURABLE-AI-RUNTIME-001"
CONFIRM_ENV = "NOTEAI_DURABLE_AI_ACCEPTANCE_MUTATION_CONFIRM"
CARRIER_ENV = "NOTEAI_DURABLE_AI_ACCEPTANCE_CARRIER_ROLE"
CARRIER_ROLE = "ai-worker"
RUNTIME_ROLE_MARKER = Path("/etc/noteai-runtime-role")
PROVIDER_SECRET_NAMES = (
    "ANTHROPIC_API_KEY",
    "MOONSHOT_API_KEY",
    "KIMI_API_KEY",
    "AMAP_API_KEY",
    "AMAP_WEB_KEY",
    "BAIDU_MAP_AK",
    "TENCENT_MAP_KEY",
    "SERPAPI_API_KEY",
    "BING_SEARCH_API_KEY",
    "GOOGLE_API_KEY",
    "MEITUAN_AI_HUB_TOKEN",
    "MEITUAN_OPEN_TOKEN",
    "MEITUAN_SIGN_KEY",
    "MEITUAN_APP_AUTH_TOKEN",
    "MEITUAN_OPEN_APP_KEY",
    "MEITUAN_OPEN_APP_SECRET",
    "MEITUAN_OPEN_SIGN",
    "MEITUAN_OPEN_AES_KEY",
)
ADMISSION_NAMESPACE = uuid.UUID("c5098114-a6c5-4c9f-a527-565123d2e1bd")


class AcceptanceError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _canonical_nonce(value: str) -> str:
    raw = str(value or "")
    try:
        normalized = str(uuid.UUID(raw))
    except (ValueError, AttributeError) as exc:
        raise AcceptanceError("nonce_shape") from exc
    if raw != normalized:
        raise AcceptanceError("nonce_shape")
    return raw


def _canonical_operation_id(value: str) -> str:
    raw = str(value or "")
    try:
        normalized = str(uuid.UUID(raw))
    except (ValueError, AttributeError) as exc:
        raise AcceptanceError("operation_id_shape") from exc
    if raw != normalized:
        raise AcceptanceError("operation_id_shape")
    return raw


def _username(nonce: str) -> str:
    return f"naiacc_{uuid.UUID(nonce).hex[:24]}"


def _request_id(nonce: str) -> str:
    return f"durable-ai-acceptance-{uuid.UUID(nonce).hex}"


def _admission_request_id(operation_id: str) -> str:
    return str(
        uuid.uuid5(
            ADMISSION_NAMESPACE,
            f"{_canonical_operation_id(operation_id)}:admission",
        )
    )


def _deletion_request_id(operation_id: str) -> str:
    return str(
        uuid.uuid5(
            ADMISSION_NAMESPACE,
            f"{_canonical_operation_id(operation_id)}:account-deletion",
        )
    )


def _api_database_role_matches() -> bool:
    """Fail closed on the exact API login without widening Worker helpers."""
    try:
        row = db.fetchone(
            "SELECT session_user AS session_role,current_user AS database_role"
        )
    except Exception:
        return False
    return bool(
        row
        and str(row["session_role"]) == "noteai_app"
        and str(row["database_role"]) == "noteai_app"
    )


def _carrier_role_matches() -> bool:
    if os.environ.get(CARRIER_ENV) != CARRIER_ROLE:
        return False
    try:
        return RUNTIME_ROLE_MARKER.read_text(encoding="utf-8").strip() == CARRIER_ROLE
    except (OSError, UnicodeError):
        return False


def _require_context(*, mutate: bool) -> durable_ai.PayloadStore | None:
    if (
        os.environ.get("NOTEAI_DEPLOYMENT_STAGE") != "production"
        or os.environ.get("NOTEAI_RUNTIME_ROLE") != "api"
        or os.environ.get("NOTEAI_DURABLE_AI_ACCEPTANCE_MODE") != "1"
        or not db.using_postgres()
        or not _api_database_role_matches()
        or not _carrier_role_matches()
    ):
        raise AcceptanceError("runtime_boundary")
    if any(name in os.environ for name in PROVIDER_SECRET_NAMES):
        raise AcceptanceError("provider_secret_present")
    if not mutate:
        return None
    if os.environ.get(CONFIRM_ENV) != TASK_ID:
        raise AcceptanceError("confirmation_missing")
    try:
        configured = private_storage.configure_from_environment()
    except Exception as exc:
        raise AcceptanceError("private_storage") from exc
    if not configured:
        raise AcceptanceError("private_storage")
    return durable_ai.get_payload_store()


def _identity(nonce: str) -> tuple[str, str]:
    username = _username(nonce)
    row = db.fetchone(
        "SELECT id FROM users WHERE username=?",
        (username,),
    )
    if not row:
        raise AcceptanceError("synthetic_user_missing")
    user_id = str(row["id"])
    operation_id = durable_ai.operation_id_for(
        user_id,
        "analyze",
        _request_id(nonce),
    )
    return user_id, operation_id


def _admission_database_absent(user_id: str, operation_id: str) -> bool:
    row = db.fetchone(
        "SELECT "
        "(SELECT COUNT(*) FROM ai_operations WHERE id=?) AS operation_count,"
        "(SELECT COUNT(*) FROM ai_operation_admissions "
        " WHERE operation_id=?) AS admission_count,"
        "(SELECT COUNT(*) FROM idempotency_requests "
        " WHERE id=? OR user_id=?) AS idempotency_count,"
        "(SELECT COUNT(*) FROM ai_operation_settlements "
        " WHERE operation_id=?) AS settlement_count,"
        "(SELECT COUNT(*) FROM ai_payload_refs "
        " WHERE operation_id=?) AS payload_ref_count",
        (
            operation_id,
            operation_id,
            _admission_request_id(operation_id),
            user_id,
            operation_id,
            operation_id,
        ),
    )
    return bool(row) and all(int(value or 0) == 0 for value in dict(row).values())


def _ensure_admission_anchor(
    store: durable_ai.PayloadStore,
    *,
    user_id: str,
    operation_id: str,
) -> dict[str, Any]:
    """Pre-place and read back the deterministic request object.

    C17's later ``admit_job`` then observes ``created=False`` for the same
    object, so a database COMMIT acknowledgement loss cannot delete it.
    """
    payload = {"acceptance": "durable-ai-v1"}
    body, item_count = durable_ai.canonical_payload(payload)
    reference = store.put(
        operation_id=operation_id,
        user_id=user_id,
        purpose=durable_ai.RefPurpose.REQUEST,
        payload=body,
        item_count=item_count,
        ttl_seconds=durable_ai.REQUEST_TTL_SECONDS,
    )
    try:
        durable_ai._validate_reference(
            reference,
            operation_id=operation_id,
            subject_hash=reference.subject_hash,
            purpose=durable_ai.RefPurpose.REQUEST,
        )
        observed = store.get(reference, user_id=user_id)
    except BaseException as exc:
        raise AcceptanceError("admission_anchor") from exc
    if observed != body:
        raise AcceptanceError("admission_anchor")
    return {
        "anchor_created": bool(reference.created),
        "private_object_anchor_writes": int(bool(reference.created)),
        "private_object_anchor_reads": 1,
    }


def admit(nonce: str) -> dict[str, Any]:
    store = _require_context(mutate=True)
    username = _username(nonce)
    existing = db.fetchone("SELECT id FROM users WHERE username=?", (username,))
    if existing:
        user_id = str(existing["id"])
        operation_id = durable_ai.operation_id_for(
            user_id,
            "analyze",
            _request_id(nonce),
        )
        anchor = _ensure_admission_anchor(
            store,
            user_id=user_id,
            operation_id=operation_id,
        )
        try:
            resolved = resolve_admission(nonce)
        except AcceptanceError as exc:
            raise AcceptanceError("synthetic_namespace_unknown") from exc
        if resolved["status"] == "admission_resolved":
            return {
                **resolved,
                "status": "admitted",
                "read_only_recovery": True,
                **anchor,
            }
        if (
            resolved["status"] != "admission_absent"
            or resolved.get("user_present") is not True
            or not _admission_database_absent(user_id, operation_id)
        ):
            raise AcceptanceError("synthetic_namespace_unknown")
    else:
        password = f"{secrets.token_urlsafe(48)}Aa1!"
        user = auth.create_user(username, password)
        user_id = str(user["id"])
        operation_id = durable_ai.operation_id_for(
            user_id,
            "analyze",
            _request_id(nonce),
        )
        anchor = _ensure_admission_anchor(
            store,
            user_id=user_id,
            operation_id=operation_id,
        )
    result = durable_ai.admit_job(
        user_id=user_id,
        operation="analyze",
        request_id=_request_id(nonce),
        payload={"acceptance": "durable-ai-v1"},
        store=store,
    )
    if result.get("state") != "admitted":
        raise AcceptanceError("admission_state")
    operation_id = str(result["operation_id"])
    if operation_id != durable_ai.operation_id_for(
        user_id,
        "analyze",
        _request_id(nonce),
    ):
        raise AcceptanceError("operation_identity")
    return {
        "status": "admitted",
        "nonce": nonce,
        "user_id": user_id,
        "operation_id": operation_id,
        "billing_state": "charged",
        "provider_calls": 0,
        **anchor,
    }


def resolve_admission(nonce: str) -> dict[str, Any]:
    """Read back one fully committed admission after client-output loss."""
    _require_context(mutate=False)
    user = db.fetchone(
        "SELECT id FROM users WHERE username=?",
        (_username(nonce),),
    )
    if not user:
        return {
            "status": "admission_absent",
            "nonce": nonce,
            "user_present": False,
            "recoverable": True,
            "provider_calls": 0,
            "read_only": True,
        }
    user_id = str(user["id"])
    operation_id = durable_ai.operation_id_for(
        user_id,
        "analyze",
        _request_id(nonce),
    )
    row = db.fetchone(
        "SELECT o.status,o.provider_phase,o.claim_count,"
        "o.provider_attempt_count,a.idempotency_request_id,"
        "i.status AS idempotency_status,i.charge_applied,i.usage_created,"
        "s.billing_state,s.request_ref_id,r.state AS payload_state,"
        "r.purpose "
        "FROM ai_operations o "
        "JOIN ai_operation_admissions a ON a.operation_id=o.id "
        "JOIN idempotency_requests i ON i.id=a.idempotency_request_id "
        "JOIN ai_operation_settlements s ON s.operation_id=o.id "
        "JOIN ai_payload_refs r ON r.id=s.request_ref_id "
        "WHERE o.id=? AND i.user_id=?",
        (operation_id, user_id),
    )
    if not row:
        if _admission_database_absent(user_id, operation_id):
            return {
                "status": "admission_absent",
                "nonce": nonce,
                "user_present": True,
                "user_id": user_id,
                "operation_id": operation_id,
                "recoverable": True,
                "provider_calls": 0,
                "read_only": True,
            }
        raise AcceptanceError("admission_not_committed")
    accepted = (
        str(row["status"]) == "queued"
        and str(row["provider_phase"]) == "not_started"
        and int(row["claim_count"] or 0) == 0
        and int(row["provider_attempt_count"] or 0) == 0
        and str(row["idempotency_request_id"])
        == _admission_request_id(operation_id)
        and str(row["idempotency_status"]) == "running"
        and int(row["charge_applied"] or 0) == 1
        and int(row["usage_created"] or 0) == 1
        and str(row["billing_state"]) == "charged"
        and str(row["request_ref_id"])
        == durable_ai.payload_reference_id_for(operation_id, "request")
        and str(row["payload_state"]) == "ready"
        and str(row["purpose"]) == "request"
    )
    if not accepted:
        raise AcceptanceError("admission_resolve_contract")
    return {
        "status": "admission_resolved",
        "nonce": nonce,
        "user_id": user_id,
        "operation_id": operation_id,
        "billing_state": "charged",
        "provider_calls": 0,
        "read_only": True,
    }


def _snapshot(nonce: str) -> dict[str, Any]:
    _require_context(mutate=False)
    user_id, operation_id = _identity(nonce)
    status = durable_ai.status_for_user(user_id, operation_id)
    events = durable_ai.events_for_user(user_id, operation_id)
    operation = db.fetchone(
        "SELECT status,provider_phase,claim_count,provider_attempt_count,"
        "subject_hash "
        "FROM ai_operations WHERE id=?",
        (operation_id,),
    )
    refund = db.fetchone(
        "SELECT i.id AS idempotency_request_id,i.status AS idempotency_status,"
        "i.refund_applied,i.failure_code,i.usage_id,i.charge_source,"
        "i.monthly_credits_used,i.wallet_credits_used,"
        "u.source AS usage_source,u.credits_used AS usage_credits_used,"
        "sub.used_monthly_credits AS subscription_used_monthly_credits,"
        "s.request_ref_id "
        "FROM ai_operation_admissions a "
        "JOIN idempotency_requests i ON i.id=a.idempotency_request_id "
        "JOIN ai_operation_settlements s ON s.operation_id=a.operation_id "
        "JOIN usage_records u ON u.id=i.usage_id "
        "LEFT JOIN subscriptions sub ON sub.id=i.charged_subscription_id "
        "WHERE a.operation_id=?",
        (operation_id,),
    )
    if not status or events is None or not operation or not refund:
        raise AcceptanceError("acceptance_rows")
    event_types = [str(event["event_type"]) for event in events]
    claim_count = int(operation["claim_count"] or 0)
    claimed_event_count = event_types.count("claimed")
    return {
        "status": str(operation["status"]),
        "provider_phase": str(operation["provider_phase"]),
        "claim_count": claim_count,
        "provider_attempt_count": int(
            operation["provider_attempt_count"] or 0
        ),
        "subject_hash": str(operation["subject_hash"]),
        "billing_state": str(status["billing_state"]),
        # A Worker claim is possible only after the authoritative Outbox row
        # is delivered. The API role intentionally cannot select that row.
        "outbox_delivery_proven": (
            claim_count > 0 and claimed_event_count > 0
        ),
        "claimed_event_count": claimed_event_count,
        "takeover_event_count": event_types.count("lease_taken_over"),
        "progress_event_count": event_types.count("progress"),
        "idempotency_request_id": str(refund["idempotency_request_id"]),
        "idempotency_status": str(refund["idempotency_status"]),
        "refund_applied": int(refund["refund_applied"] or 0),
        "failure_code": str(refund["failure_code"] or ""),
        "usage_id": str(refund["usage_id"]),
        "charge_source": str(refund["charge_source"]),
        "monthly_credits_used": float(refund["monthly_credits_used"] or 0),
        "wallet_credits_used": float(refund["wallet_credits_used"] or 0),
        "usage_source": str(refund["usage_source"]),
        "usage_credits_used": float(refund["usage_credits_used"] or 0),
        "subscription_used_monthly_credits": float(
            refund["subscription_used_monthly_credits"] or 0
        ),
        "request_ref_id": str(refund["request_ref_id"]),
        "provider_calls": 0,
        "operation_id": operation_id,
        "user_id": user_id,
        "nonce": nonce,
    }


def observe(nonce: str, expected: str) -> dict[str, Any]:
    result = _snapshot(nonce)
    if expected == "hold":
        accepted = (
            result["status"] == "running"
            and result["provider_phase"] == "not_started"
            and result["claim_count"] == 1
            and result["provider_attempt_count"] == 0
            and result["billing_state"] == "charged"
            and result["outbox_delivery_proven"] is True
            and result["claimed_event_count"] == 1
            and result["takeover_event_count"] == 0
            and result["progress_event_count"] == 1
            and result["idempotency_status"] == "running"
            and result["refund_applied"] == 0
            and result["charge_source"] == "subscription"
            and result["monthly_credits_used"] > 0
            and result["wallet_credits_used"] == 0
            and result["usage_source"] == "subscription"
            and result["usage_credits_used"] > 0
            and result["subscription_used_monthly_credits"] > 0
        )
    else:
        accepted = (
            result["status"] == "failed"
            and result["provider_phase"] == "not_started"
            and result["claim_count"] == 2
            and result["provider_attempt_count"] == 0
            and result["billing_state"] == "refunded"
            and result["outbox_delivery_proven"] is True
            and result["claimed_event_count"] == 1
            and result["takeover_event_count"] == 1
            and result["progress_event_count"] == 2
            and result["idempotency_status"] == "failed"
            and result["refund_applied"] == 1
            and result["failure_code"] == "worker_failed"
            and result["usage_source"] == "refunded"
            and result["usage_credits_used"] == 0
            and result["subscription_used_monthly_credits"] == 0
        )
    if not accepted:
        raise AcceptanceError(f"{expected}_contract")
    return {**result, "acceptance": expected}


def _cleanup_evidence(
    terminal: dict[str, Any],
    deletion: dict[str, Any],
) -> dict[str, Any]:
    operation_id = terminal["operation_id"]
    counts = db.fetchone(
        "SELECT "
        "(SELECT COUNT(*) FROM users WHERE id=?) AS user_count,"
        "(SELECT COUNT(*) FROM ai_operation_admissions "
        " WHERE operation_id=?) AS admission_count,"
        "(SELECT COUNT(*) FROM idempotency_requests WHERE id=?) "
        "AS idempotency_count,"
        "(SELECT COUNT(*) FROM ai_payload_refs "
        " WHERE operation_id=? AND state='ready') AS ready_payload_count,"
        "(SELECT COUNT(*) FROM ai_payload_refs WHERE id=? "
        " AND operation_id=? AND purpose='request' AND state='deleted' "
        " AND deleted_at IS NOT NULL) AS deleted_request_payload_count",
        (
            terminal["user_id"],
            operation_id,
            terminal["idempotency_request_id"],
            operation_id,
            terminal["request_ref_id"],
            operation_id,
        ),
    )
    deletion_after = db.fetchone(
        "SELECT user_id,subject_ref,status,primary_deleted_at "
        "FROM account_deletion_requests WHERE id=?",
        (deletion["id"],),
    )
    usage = db.fetchone(
        "SELECT user_id,source,credits_used FROM usage_records WHERE id=?",
        (terminal["usage_id"],),
    )
    audit = db.fetchone(
        "SELECT subject_hash,status FROM ai_operations WHERE id=?",
        (operation_id,),
    )
    if not counts or not deletion_after or not usage or not audit:
        raise AcceptanceError("cleanup_rows")
    observed = {name: int(value or 0) for name, value in dict(counts).items()}
    subject_ref = str(deletion["subject_ref"])
    accepted = (
        observed["user_count"] == 0
        and observed["admission_count"] == 0
        and observed["idempotency_count"] == 0
        and observed["ready_payload_count"] == 0
        and observed["deleted_request_payload_count"] == 1
        and deletion_after["user_id"] is None
        and str(deletion_after["subject_ref"]) == subject_ref
        and str(deletion_after["status"]) == "backup_clear_pending"
        and deletion_after["primary_deleted_at"] is not None
        and str(usage["user_id"]) == subject_ref
        and str(usage["source"]) == "refunded"
        and float(usage["credits_used"] or 0) == 0
        and str(audit["subject_hash"]) == terminal["subject_hash"]
        and str(audit["status"]) == "failed"
    )
    if not accepted:
        raise AcceptanceError("cleanup_contract")
    return {
        "external_payload_residue_count": observed["ready_payload_count"],
        "primary_user_residue_count": observed["user_count"],
        "admission_residue_count": observed["admission_count"],
        "idempotency_residue_count": observed["idempotency_count"],
        "deleted_request_payload_count": observed[
            "deleted_request_payload_count"
        ],
        "deletion_request_status": "backup_clear_pending",
        "usage_subject_ref_match": True,
        "pseudonymous_audit_retained": True,
    }


def resolve_primary_deletion(
    nonce: str,
    operation_id: str,
) -> dict[str, Any]:
    """Prove the deterministic post-deletion state without another write."""
    _require_context(mutate=False)
    operation_id = _canonical_operation_id(operation_id)
    deletion_id = _deletion_request_id(operation_id)
    request_ref_id = durable_ai.payload_reference_id_for(
        operation_id,
        "request",
    )
    idempotency_request_id = _admission_request_id(operation_id)
    operation = db.fetchone(
        "SELECT o.status,o.provider_phase,o.claim_count,"
        "o.provider_attempt_count,o.subject_hash,s.billing_state,"
        "s.failure_code,s.request_ref_id,r.state AS request_ref_state,"
        "r.deleted_at "
        "FROM ai_operations o "
        "JOIN ai_operation_settlements s ON s.operation_id=o.id "
        "JOIN ai_payload_refs r ON r.id=s.request_ref_id "
        "WHERE o.id=?",
        (operation_id,),
    )
    deletion = db.fetchone(
        "SELECT id,user_id,subject_ref,status,primary_deleted_at "
        "FROM account_deletion_requests WHERE id=?",
        (deletion_id,),
    )
    counts = db.fetchone(
        "SELECT "
        "(SELECT COUNT(*) FROM users WHERE username=?) AS user_count,"
        "(SELECT COUNT(*) FROM ai_operation_admissions "
        " WHERE operation_id=?) AS admission_count,"
        "(SELECT COUNT(*) FROM idempotency_requests "
        " WHERE id=?) AS idempotency_count,"
        "(SELECT COUNT(*) FROM ai_payload_refs "
        " WHERE operation_id=? AND state='ready') AS ready_payload_count,"
        "(SELECT COUNT(*) FROM ai_payload_refs WHERE id=? "
        " AND operation_id=? AND purpose='request' AND state='deleted' "
        " AND deleted_at IS NOT NULL) AS deleted_request_payload_count",
        (
            _username(nonce),
            operation_id,
            idempotency_request_id,
            operation_id,
            request_ref_id,
            operation_id,
        ),
    )
    events = db.fetchone(
        "SELECT "
        "SUM(CASE WHEN event_type='claimed' THEN 1 ELSE 0 END) "
        "AS claimed_count,"
        "SUM(CASE WHEN event_type='lease_taken_over' THEN 1 ELSE 0 END) "
        "AS takeover_count,"
        "SUM(CASE WHEN event_type='progress' THEN 1 ELSE 0 END) "
        "AS progress_count "
        "FROM ai_operation_events WHERE operation_id=?",
        (operation_id,),
    )
    if not operation or not deletion or not counts or not events:
        raise AcceptanceError("deletion_resolve_rows")
    subject_ref = str(deletion["subject_ref"] or "")
    usage = db.fetchone(
        "SELECT COUNT(*) AS usage_count,"
        "MIN(source) AS usage_source,"
        "MIN(credits_used) AS min_credits_used,"
        "MAX(credits_used) AS max_credits_used "
        "FROM usage_records WHERE user_id=? AND operation='analyze'",
        (subject_ref,),
    )
    observed = {name: int(value or 0) for name, value in dict(counts).items()}
    accepted = (
        str(operation["status"]) == "failed"
        and str(operation["provider_phase"]) == "not_started"
        and int(operation["claim_count"] or 0) == 2
        and int(operation["provider_attempt_count"] or 0) == 0
        and re.fullmatch(r"[0-9a-f]{64}", str(operation["subject_hash"] or ""))
        is not None
        and str(operation["billing_state"]) == "refunded"
        and str(operation["failure_code"]) == "worker_failed"
        and str(operation["request_ref_id"]) == request_ref_id
        and str(operation["request_ref_state"]) == "deleted"
        and operation["deleted_at"] is not None
        and str(deletion["id"]) == deletion_id
        and deletion["user_id"] is None
        and re.fullmatch(r"deleted:[0-9a-f]{32}", subject_ref) is not None
        and str(deletion["status"]) == "backup_clear_pending"
        and deletion["primary_deleted_at"] is not None
        and all(value == 0 for name, value in observed.items() if name != "deleted_request_payload_count")
        and observed["deleted_request_payload_count"] == 1
        and int(events["claimed_count"] or 0) == 1
        and int(events["takeover_count"] or 0) == 1
        and int(events["progress_count"] or 0) == 2
        and usage is not None
        and int(usage["usage_count"] or 0) == 1
        and str(usage["usage_source"]) == "refunded"
        and float(usage["min_credits_used"] or 0) == 0
        and float(usage["max_credits_used"] or 0) == 0
    )
    if not accepted:
        raise AcceptanceError("deletion_resolve_contract")
    return {
        "status": "primary_deleted",
        "nonce": nonce,
        "operation_id": operation_id,
        "deletion_request_id": deletion_id,
        "external_payload_residue_count": observed["ready_payload_count"],
        "primary_user_residue_count": observed["user_count"],
        "admission_residue_count": observed["admission_count"],
        "idempotency_residue_count": observed["idempotency_count"],
        "deleted_request_payload_count": observed[
            "deleted_request_payload_count"
        ],
        "deletion_request_status": "backup_clear_pending",
        "usage_subject_ref_match": True,
        "pseudonymous_audit_retained": True,
        "read_only": True,
        "provider_calls": 0,
    }


def delete_primary(nonce: str, operation_id: str) -> dict[str, Any]:
    store = _require_context(mutate=True)
    terminal = observe(nonce, "terminal")
    operation_id = _canonical_operation_id(operation_id)
    if terminal["operation_id"] != operation_id:
        raise AcceptanceError("operation_identity")
    user_id = terminal["user_id"]
    now = datetime.now(timezone.utc)
    deletion_id = _deletion_request_id(operation_id)
    existing = db.fetchone(
        "SELECT * FROM account_deletion_requests WHERE id=?",
        (deletion_id,),
    )
    if existing:
        deletion = dict(existing)
        if (
            str(deletion.get("user_id") or "") != user_id
            or str(deletion.get("status") or "") != "requested"
        ):
            raise AcceptanceError("deletion_request_contract")
    else:
        with db.transaction(write=True) as tx:
            deletion = content_retention.request_account_deletion_with_storage(
                tx,
                user_id,
                now=now,
                request_id=deletion_id,
            )
        if str(deletion.get("id") or "") != deletion_id:
            raise AcceptanceError("deletion_request_contract")
    completed = content_retention.process_due_account_deletions(
        limit=1,
        now=now + timedelta(hours=25),
        payload_store=store,
        request_id=deletion_id,
    )
    if completed != [deletion_id]:
        raise AcceptanceError("primary_deletion")
    return resolve_primary_deletion(nonce, operation_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--admit", action="store_true")
    action.add_argument("--resolve-admit", action="store_true")
    action.add_argument("--observe", choices=("hold", "terminal"))
    action.add_argument("--delete-primary", action="store_true")
    action.add_argument("--resolve-delete", action="store_true")
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--operation-id")
    args = parser.parse_args(argv)
    try:
        nonce = _canonical_nonce(args.nonce)
        if args.admit:
            if args.operation_id is not None:
                raise AcceptanceError("unexpected_operation_id")
            result = admit(nonce)
        elif args.resolve_admit:
            if args.operation_id is not None:
                raise AcceptanceError("unexpected_operation_id")
            result = resolve_admission(nonce)
        elif args.observe:
            if args.operation_id is not None:
                raise AcceptanceError("unexpected_operation_id")
            result = observe(nonce, args.observe)
        elif args.delete_primary:
            result = delete_primary(
                nonce,
                _canonical_operation_id(args.operation_id or ""),
            )
        else:
            result = resolve_primary_deletion(
                nonce,
                _canonical_operation_id(args.operation_id or ""),
            )
    except AcceptanceError as exc:
        print(
            f"production_durable_ai_acceptance=FAIL code={exc.code}",
            file=sys.stderr,
        )
        return 1
    except BaseException:
        print(
            "production_durable_ai_acceptance=FAIL code=unexpected",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
