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
import content_retention


IDEMPOTENCY_HEADER = "X-Request-ID"
IDEMPOTENCY_STATES = frozenset({"running", "waiting_for_input", "completed", "failed"})
FAILURE_CODES = frozenset({
    "lease_expired",
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
    "operator_paused",
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


def operation_subject_hash(user_id: str) -> str:
    """Return the stable, domain-separated storage subject for one user."""
    return _operation_subject_hash(user_id)


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
        try:
            content_retention.assert_user_writable_with_storage(tx, user_id)
        except ValueError:
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
        "o.priority,o.operator_paused,o.available_at,o.claim_count,o.provider_attempt_count,"
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
    included_ocr_ids: tuple[str, ...] = (),
    quote_version: str | None = None,
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
        try:
            content_retention.assert_user_writable_with_storage(tx, user_id)
        except ValueError:
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
                "session_id": existing["id"] if status == "waiting_for_input" or operation == 'screenshot' else None,
                "failure_code": str(existing.get("failure_code") or "")
                if status == "failed" else "",
            }

        # Existing keys are resolved first: a later price change must not
        # hide the original charge or admit a second request. New claims check
        # the server quote before any debit; a mismatch rolls back the insert.
        billing.assert_quote_version(quote_version)
        if included_ocr_ids:
            if operation != 'screenshot' or not 1 <= len(included_ocr_ids) <= 9 or len(set(included_ocr_ids)) != len(included_ocr_ids):
                raise ValueError('invalid included OCR sources')
            supplied = payload.get('ocr_results', []) if isinstance(payload, dict) else []
            results = {result.get('ocr_request_id'): result for result in supplied if isinstance(result, dict)}
            if len(results) != len(included_ocr_ids) or set(results) != set(included_ocr_ids):
                raise HTTPException(409, '截图结果与原识别请求不匹配')
            fresh_sources = []
            for source_id in sorted(included_ocr_ids):
                source = tx.fetchone("SELECT id,ocr_result_hash,ocr_merge_key_hash FROM idempotency_requests WHERE user_id=? AND operation='screenshot' AND key_hash=? AND status='completed' AND complete_applied=1 AND refund_applied=0" + lock, (user_id, _sha256(source_id)))
                if not source or not source['ocr_result_hash'] or source['ocr_result_hash'] != payload_hash(results[source_id]):
                    raise HTTPException(409, '请先完成本人每张截图的原识别请求')
                if not source['ocr_merge_key_hash']:
                    fresh_sources.append(source['id'])
            # Appending a newly charged screenshot may extend the original
            # batch; arbitrary regrouping of only consumed results may not.
            if not fresh_sources:
                raise HTTPException(409, '这些截图已用于原合并请求，请读取原结果，不重复处理')
            for source_row_id in fresh_sources:
                tx.execute("UPDATE idempotency_requests SET ocr_merge_key_hash=? WHERE id=? AND ocr_merge_key_hash IS NULL", (key_digest, source_row_id))
            billing._require_feature_tx(tx, user_id, operation)
            charge = {'usage_id': billing._record_usage_tx(tx, user_id, operation, 'free', 0),
                      'source':'free', 'credits_used':0}
        else:
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


def _parse_lease_clock(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _fail_running_request_in_transaction(
    tx: db.Transaction,
    current: dict[str, Any],
    *,
    failure_code: str,
    now_iso: str,
) -> None:
    if current.get('failure_code') == 'result_store_unknown':
        raise ResultRecoveryRequired('MEDIA_RESULT_RECOVERY_REQUIRED')
    assert_media_calls_settled(tx, current)
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
        (
            failure_code,
            now_iso,
            now_iso,
            now_iso,
            current["id"],
        ),
    )


def settle_expired_requests_for_account_deletion_with_storage(
    tx: db.Transaction,
    user_id: str,
    *,
    now: datetime | None = None,
) -> int:
    """Settle expired claims under the caller-held user deletion fence."""
    current_time = now or _now()
    now_iso = _iso(current_time)
    lock = " FOR UPDATE" if tx.postgres else ""
    rows = tx.fetchall(
        "SELECT * FROM idempotency_requests "
        "WHERE user_id=? AND status IN ('running','waiting_for_input') ORDER BY created_at,id" + lock,
        (user_id,),
    )
    settled = 0
    for row in rows:
        current = dict(row)
        if current["status"] == "waiting_for_input":
            import task_clarification
            try:
                task_clarification._settled_calls(tx, current["usage_id"])
            except HTTPException:
                raise ValueError("原任务结果还需核实，请稍后再删除账号") from None
            _fail_running_request_in_transaction(tx, current, failure_code="cancelled_waiting",
                                                 now_iso=now_iso)
            settled += 1
            continue
        lease_expires_at = _parse_lease_clock(current.get("lease_expires_at"))
        if lease_expires_at is None or lease_expires_at > current_time:
            raise ValueError("有正在处理的请求，请等待完成后重试删除")
        admission = tx.fetchone(
            "SELECT operation_id FROM ai_operation_admissions "
            f"WHERE idempotency_request_id=?{lock}",
            (current["id"],),
        )
        if admission:
            operation = tx.fetchone(
                f"SELECT status FROM ai_operations WHERE id=?{lock}",
                (admission["operation_id"],),
            )
            if not operation or operation["status"] in {
                "queued",
                "running",
                "outcome_unknown",
            }:
                raise ValueError("有正在处理的请求，请等待完成后重试删除")
            if operation["status"] == "succeeded":
                tx.execute(
                    "UPDATE idempotency_requests SET status='completed',"
                    "complete_applied=1,completed_at=?,updated_at=? WHERE id=?",
                    (now_iso, now_iso, current["id"]),
                )
                settled += 1
                continue
        _fail_running_request_in_transaction(
            tx,
            current,
            failure_code="lease_expired",
            now_iso=now_iso,
        )
        settled += 1
    return settled


def mark_completed(
    context: dict[str, Any] | None, *, confirm_existing: bool = False, ocr_result: dict | None = None,
    response_reference=None,
) -> bool:
    if not context or context.get("state") != "owner":
        return False
    lease_digest = _sha256(str(context.get("lease_token") or ""))
    now = _iso()
    with db.transaction(write=True) as tx:
        try:
            content_retention.assert_user_writable_with_storage(
                tx,
                str(context.get("user_id") or ""),
            )
        except ValueError:
            return False
        row = _owned_row(tx, context)
        if not row:
            return False
        current = dict(row)
        if confirm_existing and (
            any(current.get(key) != context.get(key) for key in (
                "user_id", "operation", "key_hash", "payload_hash",
            ))
            or current.get("lease_token_hash") != lease_digest
            or current.get("usage_id") != (context.get("charge") or {}).get("usage_id")
        ):
            return False
        if current.get("status") == "completed" and current.get("complete_applied"):
            return bool(confirm_existing and not current.get("refund_applied") and
                        (ocr_result is None or current.get('ocr_result_hash') == payload_hash(ocr_result)) and
                        (response_reference is None or current.get('response_ref_json') ==
                         response_reference_json(response_reference, current)))
        if current.get("status") != "running" or current.get("lease_token_hash") != lease_digest:
            return False
        if ocr_result is not None and current['operation'] != 'screenshot':
            raise ValueError('OCR result requires original screenshot admission')
        extra = ',ocr_result_hash=?' if ocr_result is not None else ''
        response_values = ()
        if response_reference is not None:
            assert_media_calls_settled(tx, current)
            extra += ',response_ref_json=?'
            response_values = (response_reference_json(response_reference, current),)
        tx.execute("UPDATE idempotency_requests SET status='completed',complete_applied=1,failure_code='',"
                   "completed_at=?,updated_at=?" + extra + " WHERE id=?",
                   (now, now, *((payload_hash(ocr_result),) if ocr_result is not None else ()),
                    *response_values, context['request_id']))
    return True


class ResultRecoveryRequired(RuntimeError):
    """The original media call/result must be reconciled, never repeated."""


def assert_media_calls_settled(tx, current):
    if current.get('operation') == 'screenshot' and tx.fetchone(
        "SELECT id FROM public_trial_calls WHERE usage_record_id=? AND "
        "(state IN ('dispatched','unknown') OR (state='responded' AND http_status=200 "
        "AND model_usage_record_id IS NULL)) LIMIT 1", (current.get('usage_id'),),
    ):
        raise ResultRecoveryRequired('MEDIA_CALL_RESULT_UNCONFIRMED')


def response_reference_json(reference, current):
    """Only opaque metadata belongs in the original request ledger."""
    import durable_ai
    from dataclasses import asdict
    if not isinstance(reference, durable_ai.PayloadReference):
        raise ValueError('invalid response reference')
    values = asdict(reference)
    values.pop('created')
    if (current['operation'] != 'screenshot' or reference.operation_id != current['id']
            or reference.subject_hash != operation_subject_hash(current['user_id'])
            or reference.id != durable_ai.payload_reference_id_for(current['id'], 'result')
            or reference.purpose != 'result' or reference.schema_version != 1
            or reference.state not in ('ready', 'deleted', 'expired')
            or reference.encryption_mode != 'provider_managed'
            or any(type(values[name]) is not int for name in ('size_bytes', 'item_count', 'schema_version'))
            or not 0 < reference.size_bytes <= 1024 * 1024 or reference.item_count != 1):
        raise ValueError('response reference binding mismatch')
    for name in ('subject_hash', 'object_key_hash', 'content_sha256', 'key_epoch_hash'):
        value = values[name]
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('invalid response reference hash')
    clocks = {}
    for name in ('created_at', 'ready_at', 'expires_at'):
        clock = datetime.fromisoformat(values[name])
        if clock.tzinfo is None:
            raise ValueError('response reference clock missing timezone')
        clocks[name] = clock
    if not clocks['created_at'] <= clocks['ready_at'] < clocks['expires_at']:
        raise ValueError('response reference clocks out of order')
    if reference.state == 'ready' and reference.deleted_at is not None:
        raise ValueError('ready response cannot be deleted')
    if reference.state != 'ready' and not reference.deleted_at:
        raise ValueError('response cleanup clock missing')
    if reference.deleted_at is not None:
        deleted = datetime.fromisoformat(reference.deleted_at)
        if deleted.tzinfo is None or deleted < clocks['ready_at']:
            raise ValueError('invalid response cleanup clock')
    return json.dumps(values, sort_keys=True, separators=(',', ':'), allow_nan=False)


def response_reference_from_row(row):
    import durable_ai
    current = dict(row)
    raw = current.get('response_ref_json')
    if not isinstance(raw, str) or len(raw) > 4096:
        raise ValueError('invalid response metadata')
    values = json.loads(raw)
    fields = set(durable_ai.PayloadReference.__dataclass_fields__) - {'created'}
    if not isinstance(values, dict) or set(values) != fields:
        raise ValueError('invalid response metadata fields')
    reference = durable_ai.PayloadReference(**values, created=False)
    if response_reference_json(reference, current) != raw:
        raise ValueError('noncanonical response metadata')
    return reference


def complete_media_response(context, result, *, kind, source_ids=(), ocr_result=None, store=None):
    """Persist the original successful result, then atomically complete its claim.

    A missing commit acknowledgement never deletes an object or refunds a
    successful physical call. The original owner read can confirm that commit.
    """
    import durable_ai
    if not context or context.get('state') != 'owner' or context['operation'] != 'screenshot':
        raise ValueError('original screenshot claim required')
    if kind not in ('screenshot_extract', 'screenshot_merge') or not isinstance(result, dict):
        raise ValueError('invalid media result kind')
    if any(k in result for k in ('_image_bytes', 'image_base64', 'authorization', 'cookie', 'token')):
        raise ValueError('raw media or credentials cannot enter response payload')
    body = json.dumps({'schema_version': 1, 'kind': kind, 'claim_id': context['request_id'],
        'operation': context['operation'], 'request_payload_hash': context['payload_hash'],
        'source_ids': list(source_ids), 'result': result}, ensure_ascii=False,
        sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(body) > 1024 * 1024:
        raise ValueError('media result too large')
    selected = store or durable_ai.get_payload_store()
    try:
        with db.transaction(write=True) as tx:
            content_retention.assert_user_writable_with_storage(tx, context['user_id'])
            row = _owned_row(tx, context)
            current = dict(row or {})
            if (any(current.get(k) != context.get(k) for k in ('user_id','operation','key_hash','payload_hash'))
                    or current.get('lease_token_hash') != _sha256(context['lease_token'])
                    or current.get('refund_applied') or current.get('status') not in ('running','completed')):
                raise ResultRecoveryRequired('MEDIA_RESULT_BINDING_UNCONFIRMED')
            assert_media_calls_settled(tx, current)
            if current['status'] == 'running':
                # A storage/commit outage is not a refundable provider failure.
                # Keep this marker through lease expiry until original reconcile.
                tx.execute("UPDATE idempotency_requests SET failure_code='result_store_unknown' WHERE id=?", (current['id'],))
        reference = selected.put(operation_id=context['request_id'], user_id=context['user_id'],
            purpose='result', payload=body, item_count=1, ttl_seconds=durable_ai.RESULT_TTL_SECONDS)
        if not mark_completed(context, confirm_existing=True, ocr_result=ocr_result,
                              response_reference=reference):
            raise ResultRecoveryRequired('MEDIA_RESULT_COMMIT_UNCONFIRMED')
    except Exception:
        # Reconcile one original commit; no second put, inference or charge.
        try:
            row = db.fetchone('SELECT * FROM idempotency_requests WHERE id=? AND user_id=?',
                              (context['request_id'], context['user_id']))
            if (row and row['status'] == 'completed' and row['complete_applied'] and not row['refund_applied']
                    and row['payload_hash'] == context['payload_hash']
                    and (ocr_result is None or row['ocr_result_hash'] == payload_hash(ocr_result))
                    and selected.get(response_reference_from_row(row), user_id=context['user_id']) == body):
                return result
        except Exception:
            pass
        raise ResultRecoveryRequired('MEDIA_RESULT_RECOVERY_REQUIRED') from None
    return result


def read_media_response(user_id, claim_id, *, store=None):
    import durable_ai
    row = db.fetchone("SELECT * FROM idempotency_requests WHERE id=? AND user_id=? AND operation='screenshot'",
                      (claim_id, user_id))
    if not row:
        return None
    current = dict(row)
    reply = {'session_id': current['id'], 'kind': 'media', 'status': current['status'],
             'result_available': False, 'result': None}
    if current['failure_code'] == 'result_store_unknown':
        reply['result_state'] = 'recovery_required'
    if current['status'] == 'completed' and current['response_ref_json']:
        reference = response_reference_from_row(current)
        if reference.state != 'ready' or datetime.fromisoformat(reference.expires_at) <= _now():
            reply['result_state'] = 'expired_or_deleted'
            return reply
        payload = json.loads((store or durable_ai.get_payload_store()).get(reference, user_id=user_id))
        if (payload.get('claim_id') != current['id'] or payload.get('request_payload_hash') != current['payload_hash']
                or payload.get('operation') != 'screenshot' or payload.get('schema_version') != 1
                or payload.get('kind') not in ('screenshot_extract', 'screenshot_merge')):
            raise ResultRecoveryRequired('MEDIA_RESULT_BINDING_MISMATCH')
        reply.update(kind=payload['kind'], result_available=True, result=payload['result'])
    return reply


def has_ready_user_responses(tx, user_id):
    state = "response_ref_json::jsonb->>'state'" if tx.postgres else "json_extract(response_ref_json,'$.state')"
    return bool(tx.fetchone("SELECT 1 FROM idempotency_requests WHERE user_id=? "
                            f"AND response_ref_json IS NOT NULL AND {state}='ready' LIMIT 1", (user_id,)))


def delete_user_responses(user_id, *, store=None, now=None):
    import durable_ai
    from dataclasses import replace
    selected = store or durable_ai.get_payload_store()
    rows = db.fetchall('SELECT * FROM idempotency_requests WHERE user_id=? AND response_ref_json IS NOT NULL', (user_id,))
    for row in rows:
        current = dict(row)
        reference = response_reference_from_row(current)
        if reference.state != 'ready':
            continue
        if not selected.delete(reference, user_id=user_id):
            raise durable_ai.PayloadUnavailable('MEDIA_RESPONSE_DELETE_UNCONFIRMED')
        with db.transaction(write=True) as tx:
            content_retention.lock_user_write_fence_with_storage(tx, user_id, allow_deletion_requested=True)
            tx.execute('UPDATE idempotency_requests SET response_ref_json=? WHERE id=? AND user_id=? AND response_ref_json=?',
                (response_reference_json(replace(reference, state='deleted', deleted_at=_iso(now)), current),
                 current['id'], user_id, current['response_ref_json']))


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
        try:
            content_retention.assert_user_writable_with_storage(
                tx,
                str(context.get("user_id") or ""),
            )
        except ValueError:
            return False
        row = _owned_row(tx, context)
        if not row:
            return False
        current = dict(row)
        if current.get("status") == "failed" and current.get("refund_applied"):
            return False
        if current.get("status") != "running" or current.get("lease_token_hash") != lease_digest:
            return False
        assert_media_calls_settled(tx, current)
        _fail_running_request_in_transaction(
            tx,
            current,
            failure_code=safe_code,
            now_iso=now,
        )
    return True
