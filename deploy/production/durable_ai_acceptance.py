#!/usr/bin/env python3
"""Bounded provider-free production acceptance admission and observation.

Run this controller only in an exact API-role container with the existing
private-storage environment. It creates one synthetic account/job, observes
only that deterministic namespace, and uses the product's account-deletion
path to erase the external payload and primary account after terminal proof.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


REPOSITORY_MODEL_DIR = Path(__file__).resolve().parents[2] / "model"
MODEL_DIR = (
    Path("/app/model")
    if Path("/app/model").is_dir()
    else REPOSITORY_MODEL_DIR
)
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

import auth  # noqa: E402
import content_retention  # noqa: E402
import db  # noqa: E402
import durable_ai  # noqa: E402
import private_storage  # noqa: E402


TASK_ID = "PROD-FIRST-LAUNCH-DURABLE-AI-RUNTIME-001"
CONFIRM_ENV = "NOTEAI_DURABLE_AI_ACCEPTANCE_MUTATION_CONFIRM"
PROVIDER_SECRET_NAMES = (
    "ANTHROPIC_API_KEY",
    "MOONSHOT_API_KEY",
    "KIMI_API_KEY",
    "AMAP_API_KEY",
    "MEITUAN_AI_HUB_TOKEN",
    "MEITUAN_OPEN_TOKEN",
)


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


def _username(nonce: str) -> str:
    return f"naiacc_{uuid.UUID(nonce).hex[:24]}"


def _request_id(nonce: str) -> str:
    return f"durable-ai-acceptance-{uuid.UUID(nonce).hex}"


def _require_context(*, mutate: bool) -> durable_ai.PayloadStore | None:
    if (
        os.environ.get("NOTEAI_DEPLOYMENT_STAGE") != "production"
        or os.environ.get("NOTEAI_RUNTIME_ROLE") != "api"
        or os.environ.get("NOTEAI_DURABLE_AI_ACCEPTANCE_MODE") != "1"
        or not db.using_postgres()
        or not durable_ai.database_role_matches("noteai_app")
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


def admit(nonce: str) -> dict[str, Any]:
    store = _require_context(mutate=True)
    username = _username(nonce)
    if db.fetchone("SELECT id FROM users WHERE username=?", (username,)):
        raise AcceptanceError("synthetic_namespace_exists")
    password = f"{secrets.token_urlsafe(48)}Aa1!"
    user = auth.create_user(username, password)
    user_id = str(user["id"])
    try:
        result = durable_ai.admit_job(
            user_id=user_id,
            operation="analyze",
            request_id=_request_id(nonce),
            payload={"acceptance": "durable-ai-v1"},
            store=store,
        )
    except BaseException:
        with db.transaction(write=True) as tx:
            tx.execute("DELETE FROM users WHERE id=?", (user_id,))
        raise
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
    outbox = db.fetchone(
        "SELECT state FROM ai_operation_outbox WHERE operation_id=?",
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
    if not status or events is None or not operation or not outbox or not refund:
        raise AcceptanceError("acceptance_rows")
    event_types = [str(event["event_type"]) for event in events]
    return {
        "status": str(operation["status"]),
        "provider_phase": str(operation["provider_phase"]),
        "claim_count": int(operation["claim_count"] or 0),
        "provider_attempt_count": int(
            operation["provider_attempt_count"] or 0
        ),
        "subject_hash": str(operation["subject_hash"]),
        "billing_state": str(status["billing_state"]),
        "outbox_state": str(outbox["state"]),
        "claimed_event_count": event_types.count("claimed"),
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
            and result["outbox_state"] == "delivered"
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
            and result["outbox_state"] == "delivered"
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


def delete_primary(nonce: str) -> dict[str, Any]:
    store = _require_context(mutate=True)
    terminal = observe(nonce, "terminal")
    user_id = terminal["user_id"]
    now = datetime.now(timezone.utc)
    deletion = content_retention.request_account_deletion(user_id)
    completed = content_retention.process_due_account_deletions(
        limit=1,
        now=now + timedelta(hours=25),
        payload_store=store,
        request_id=str(deletion["id"]),
    )
    if completed != [str(deletion["id"])]:
        raise AcceptanceError("primary_deletion")
    evidence = _cleanup_evidence(terminal, deletion)
    return {
        "status": "primary_deleted",
        "operation_id": terminal["operation_id"],
        "provider_calls": 0,
        **evidence,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--admit", action="store_true")
    action.add_argument("--observe", choices=("hold", "terminal"))
    action.add_argument("--delete-primary", action="store_true")
    parser.add_argument("--nonce", required=True)
    args = parser.parse_args(argv)
    try:
        nonce = _canonical_nonce(args.nonce)
        if args.admit:
            result = admit(nonce)
        elif args.observe:
            result = observe(nonce, args.observe)
        else:
            result = delete_primary(nonce)
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
