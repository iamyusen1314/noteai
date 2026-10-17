"""Schema31 explicit reservation and report-delivery settlement.

A v1 reservation occupies available credits, but never debits a wallet, records
customer consumption, or consumes paid FIFO positions before a saved result.
Every legacy spender/refund/Admin path must use the guards before activation.
Unmodified old images cannot run while a v1 reservation is outstanding.
"""
from __future__ import annotations

import secrets
import os
import uuid
import math
import json
from datetime import timedelta

from fastapi import HTTPException

import billing
import content_retention
import db
import idempotency


PREFIX = "reservation_v1:"
RELEASED_PREFIX = "reservation_released_v1:"
SOURCES = frozenset({"subscription", "credits", "mixed"})
ROUTES = frozenset({"/generate", "/generate/stream", "/analyze", "/analyze/stream"})


def ensure_request_id(scope):
    """One durable identity for a headerless accepted request, never body dedupe."""
    if not enabled() or scope.get("path") not in ROUTES:
        return
    headers = list(scope.get("headers", []))
    if any(key.lower() == b"x-request-id" and value.strip() for key, value in headers):
        return
    headers = [(key,value) for key,value in headers if key.lower() != b"x-request-id"]
    request_id = "server-" + uuid.uuid4().hex
    scope["headers"] = headers + [(b"x-request-id", request_id.encode("ascii"))]
    scope.setdefault("state", {})["postdelivery_request_id"] = request_id


def _money(value):
    amount = round(float(value or 0), 2)
    if not math.isfinite(amount) or amount < 0:
        raise ValueError("negative reservation amount")
    return amount


def _marker(source, tier):
    if source not in SOURCES or tier not in billing.TIERS:
        raise ValueError("invalid reservation source")
    return PREFIX + source + ":" + tier


def _version(row):
    marker = str(row.get("charge_source") or "")
    if not marker.startswith(PREFIX):
        return None
    parts = marker[len(PREFIX):].split(":")
    if len(parts) != 2 or parts[0] not in SOURCES or parts[1] not in billing.TIERS:
        raise ValueError("unrecognized reservation version")
    monthly, wallet, total = (_money(row.get(key)) for key in
        ("monthly_credits_used", "wallet_credits_used", "credits_used"))
    expected = "mixed" if monthly and wallet else "subscription" if monthly else "credits"
    if total <= 0 or round(monthly + wallet, 2) != total or parts[0] != expected:
        raise ValueError("reservation funding snapshot changed")
    return {"source": parts[0], "tier": parts[1]}


def _open_rows(tx, user_id=None):
    suffix = " AND user_id=?" if user_id is not None else ""
    rows = tx.fetchall("SELECT * FROM idempotency_requests WHERE SUBSTR(charge_source,1,?)=? "
        "AND charge_applied=1 AND complete_applied=0 AND refund_applied=0" + suffix,
        (len(PREFIX), PREFIX, *((user_id,) if user_id is not None else ())))
    for row in rows:
        _version(dict(row))  # Unknown policy text must not silently free funds.
    return rows


def _lock_wallet(tx, user_id):
    tx.execute("INSERT INTO credits(user_id,balance,total_purchased,total_used,updated_at) "
        "VALUES(?,0,0,0,?) ON CONFLICT(user_id) DO NOTHING", (user_id, billing._now()))
    return tx.fetchone("SELECT balance FROM credits WHERE user_id=?" +
                       (" FOR UPDATE" if tx.postgres else ""), (user_id,))


def availability_in_transaction(tx, user_id, subscription):
    """Caller holds the existing user fence and wallet/subscription locks."""
    wallet = tx.fetchone("SELECT balance FROM credits WHERE user_id=?", (user_id,))
    held = _open_rows(tx, user_id)
    held_wallet = _money(sum(float(row["wallet_credits_used"] or 0) for row in held))
    held_monthly = _money(sum(float(row["monthly_credits_used"] or 0) for row in held
        if row["charged_subscription_id"] == subscription["id"]
        and row["charged_period_start"] == subscription["period_start"]))
    gross_wallet = _money(wallet["balance"] if wallet else 0)
    gross_monthly = max(0, _money(billing.TIERS[subscription["tier"]]["monthly_credits"])
        - _money(subscription.get("used_monthly_credits")))
    return {"wallet_available": max(0, round(gross_wallet - held_wallet, 2)),
        "monthly_available": max(0, round(gross_monthly - held_monthly, 2)),
        "wallet_held": held_wallet, "monthly_held": held_monthly}


def reserve_claim(*, user_id, operation, request_id, payload, quote_version=None):
    """Create one explicit v1 reservation; no customer money is consumed here."""
    if operation not in {"generate", "analyze"}:
        raise ValueError("reservation supports existing generation/diagnosis only")
    normalized = idempotency.normalize_request_id(request_id)
    if not normalized:
        raise ValueError("durable request id required")
    key_hash, body_hash = idempotency._sha256(normalized), idempotency.payload_hash(payload)
    token, row_id = secrets.token_urlsafe(32), str(uuid.uuid4())
    now = idempotency._now()
    with db.transaction(write=True) as tx:
        content_retention.assert_user_writable_with_storage(tx, user_id)
        lock = " FOR UPDATE" if tx.postgres else ""
        existing = tx.fetchone("SELECT * FROM idempotency_requests WHERE user_id=? "
            "AND operation=? AND key_hash=?" + lock, (user_id, operation, key_hash))
        if existing:
            row = dict(existing)
            if row["payload_hash"] != body_hash:
                return {"state": "conflict"}
            return {"state": ("legacy_existing" if _version(row) is None else
                "in_progress" if row["status"] == "running" else row["status"]),
                "task_id": row["id"], "legacy_status":row["status"],
                "session_id": row["id"] if row["status"] == "waiting_for_input" else None,
                "failure_code": str(row.get("failure_code") or ""),
                "refund_status":idempotency._refund_status(row),
                "settlement_mode": "legacy" if _version(row) is None else "reservation_v1"}
        billing.assert_quote_version(quote_version)
        if tx.fetchone("SELECT user_id FROM payment_orders WHERE user_id=? "
                       "AND refund_status IN ('pending','needs_manual') LIMIT 1",(user_id,)):
            raise HTTPException(409, "原支付权益仍在退款结算，请先核实完成后再发起新任务")
        _lock_wallet(tx, user_id)
        sub = billing._require_feature_tx(tx, user_id, operation)
        available = availability_in_transaction(tx, user_id, sub)
        price = _money(billing.get_operation_costs()[operation]["credits"])
        monthly = min(price, available["monthly_available"])
        wallet = round(price - monthly, 2)
        if wallet > available["wallet_available"]:
            raise HTTPException(402, detail={"code": "QUOTA_EXCEEDED",
                "message": "可用积分不足；已有任务预留仍被保留。"})
        source = "mixed" if monthly and wallet else "subscription" if monthly else "credits"
        marker = _marker(source, sub["tier"])
        usage_id = billing._record_usage_tx(tx, user_id, operation, marker, 0)
        tx.execute("INSERT INTO idempotency_requests(id,user_id,operation,key_hash,payload_hash,"
            "status,lease_token_hash,lease_expires_at,usage_id,charged_subscription_id,charged_period_start,"
            "charge_source,credits_used,monthly_credits_used,wallet_credits_used,usage_created,charge_applied,"
            "usage_created_at,charged_at,created_at,updated_at) "
            "VALUES(?,?,?,?,?,'running',?,?,?,?,?,?,?,?,?,1,1,?,?,?,?)", (row_id,user_id,operation,
            key_hash,body_hash,idempotency._sha256(token),idempotency._iso(now+timedelta(seconds=1800)),
            usage_id,sub["id"],sub["period_start"],marker,price,monthly,wallet,
            idempotency._iso(now),None,idempotency._iso(now),idempotency._iso(now)))
    billing.activate_usage(usage_id)
    return {"state": "reservation_owner", "settlement_mode": "reservation_v1",
        "request_id": row_id,"user_id": user_id,"operation": operation,"key_hash": key_hash,
        "payload_hash": body_hash,"lease_token": token,"charge": {"usage_id": usage_id, "settlement_mode":"reservation_v1",
        "subscription_id": sub["id"],"subscription_period_start": sub["period_start"],
        "source": source,"credits_used": price,"monthly_credits_used": monthly,"wallet_credits_used": wallet}}


def _owned(tx, context):
    if context.get("state") != "reservation_owner" or context.get("settlement_mode") != "reservation_v1":
        raise ValueError("explicit reservation owner required")
    content_retention.assert_user_writable_with_storage(tx, context["user_id"])
    _lock_wallet(tx, context["user_id"])
    row = idempotency._owned_row(tx, context)
    row = dict(row) if row else None
    if (not row or _version(row) is None or any(row[k] != context.get(k)
            for k in ("user_id","operation","key_hash","payload_hash"))
            or row["lease_token_hash"] != idempotency._sha256(context.get("lease_token", ""))
            or row["usage_id"] != context["charge"]["usage_id"]):
        raise ValueError("original reservation identity changed")
    _assert_usage_state(tx, row)
    return row


def _assert_usage_state(tx, row):
    usage = tx.fetchone("SELECT source,credits_used FROM usage_records WHERE id=? AND user_id=? AND operation=?",
        (row["usage_id"], row["user_id"], row["operation"]))
    expected_source = (_version(row)["source"] if row["complete_applied"] else
        RELEASED_PREFIX + _version(row)["source"] if row["refund_applied"] else row["charge_source"])
    expected_credits = _money(row["credits_used"]) if row["complete_applied"] else 0
    if not usage or usage["source"] != expected_source or _money(usage["credits_used"]) != expected_credits:
        raise ValueError("original reservation usage state changed")


def _assert_calls_settled(tx, usage_id, *, require_success=True):
    calls = tx.fetchall("SELECT state,http_status,model_usage_record_id FROM public_trial_calls "
                        "WHERE usage_record_id=?", (usage_id,))
    if ((require_success and not any(call["http_status"] == 200 for call in calls))
            or any(call["state"] != "responded" or (call["http_status"] == 200
            and (not call["model_usage_record_id"] or not tx.fetchone(
                "SELECT id FROM model_usage_records WHERE id=? AND usage_record_id=?",
                (call["model_usage_record_id"],usage_id)))) for call in calls)):
        raise ValueError("original supplier accounting remains unconfirmed")


def _assert_saved(tx, row, result):
    if not isinstance(result, dict) or not result.get("saved_note_id"):
        raise ValueError("saved report identity required")
    note = tx.fetchone("SELECT id,title,body,source FROM notes WHERE id=? AND user_id=?",
                       (result["saved_note_id"],row["user_id"]))
    if not note or note["id"] != row["id"]:
        raise ValueError("original report not saved")
    if row["operation"] == "generate":
        if not note["title"] or not note["body"] or note["source"] != "generate" or result.get("quality_failed"):
            raise ValueError("original generation identity changed")
    elif result.get("diagnosis_id") != row["id"] or not tx.fetchone(
            "SELECT id FROM saved_diagnoses WHERE id=? AND user_id=? AND diagnosis_json<>''",
            (result["diagnosis_id"], row["user_id"])):
        raise ValueError("original diagnosis not saved")


def finalize_in_transaction(tx, context, result):
    """Finalize in the canonical report writer's existing short transaction."""
    row = _owned(tx, context)
    if row["status"] == "completed" and row["complete_applied"] and not row["refund_applied"]:
        return {"status": "committed", "credits_used": row["credits_used"]}
    expiry = idempotency._parse_lease_clock(row["lease_expires_at"])
    if (row["status"] != "running" or row["refund_applied"] or row["complete_applied"]
            or expiry is None or expiry <= idempotency._now()):
        raise ValueError("reservation is not a live original execution")
    wallet_backing = tx.fetchone("SELECT balance FROM credits WHERE user_id=?", (row["user_id"],))
    held_wallet = _money(sum(float(held["wallet_credits_used"] or 0)
                            for held in _open_rows(tx, row["user_id"])))
    if not wallet_backing or _money(wallet_backing["balance"]) < held_wallet:
        raise ValueError("original wallet reservations lost their backing")
    _assert_calls_settled(tx, row["usage_id"])
    _assert_saved(tx, row, result)
    source = _version(row)
    monthly, wallet = _money(row["monthly_credits_used"]), _money(row["wallet_credits_used"])
    sub = tx.fetchone("SELECT * FROM subscriptions WHERE id=? AND user_id=?" +
        (" FOR UPDATE" if tx.postgres else ""), (row["charged_subscription_id"],row["user_id"]))
    if not sub:
        raise ValueError("original subscription reservation unavailable")
    if monthly and sub["period_start"] == row["charged_period_start"]:
        tx.execute("UPDATE subscriptions SET used_monthly_credits=used_monthly_credits+? WHERE id=?",
                   (monthly,sub["id"]))
    elif monthly and not (source["tier"] == "free" and
            idempotency._parse_lease_clock(sub["period_start"]) >
            idempotency._parse_lease_clock(row["charged_period_start"])):
        raise ValueError("original subscription period changed")
    now = billing._now()
    if wallet:
        cursor = tx.execute("UPDATE credits SET balance=balance-?,total_used=total_used+?,updated_at=? "
            "WHERE user_id=? AND balance>=?", (wallet,wallet,now,row["user_id"],wallet))
        if cursor.rowcount != 1:
            raise ValueError("reserved wallet backing changed")
        balance = tx.fetchone("SELECT balance FROM credits WHERE user_id=?", (row["user_id"],))["balance"]
        tx.execute("INSERT INTO credit_transactions(id,user_id,type,amount,balance_after,description,recorded_at) "
            "VALUES(?,?,'usage',?,?,?,?)", (str(uuid.uuid4()),row["user_id"],-wallet,balance,
            "报告交付后确认消费",now))
        import payment_contract
        payment_contract.allocate_paid_credit_positions(tx,row["user_id"],row["usage_id"],wallet)
    tx.execute("UPDATE usage_records SET source=?,credits_used=? WHERE id=? AND user_id=?",
        (source["source"],row["credits_used"],row["usage_id"],row["user_id"]))
    tx.execute("UPDATE idempotency_requests SET status='completed',complete_applied=1,"
        "charged_at=?,completed_at=?,updated_at=? WHERE id=?", (now,now,now,row["id"]))
    return {"status": "committed", "credits_used": row["credits_used"], "result": result}


def finalize_saved_result(context, persist_result):
    """Local convenience wrapper; persist_result must use only the supplied tx."""
    with db.transaction(write=True) as tx:
        row = _owned(tx, context)
        if row["status"] == "completed" and row["complete_applied"] and not row["refund_applied"]:
            return {"status": "committed", "credits_used": row["credits_used"]}
        return finalize_in_transaction(tx, context, persist_result(tx))


def release_in_transaction(tx, context, *, original_execution_ended):
    if original_execution_ended is not True:
        raise ValueError('original execution has not ended')
    row = _owned(tx, context)
    return _release_row_in_transaction(tx, row)


def _release_row_in_transaction(tx, row):
    if row['status'] == 'failed' and row['refund_applied']:
        return {'status': 'released', 'credits_used': 0}
    if row['complete_applied'] or row['response_ref_json']:
        raise ValueError('original result may already exist')
    if row['failure_code'] == 'result_store_unknown':
        raise ValueError('original saved result requires reconciliation')
    if tx.fetchone('SELECT id FROM notes WHERE id=? AND user_id=?', (row['id'], row['user_id'])):
        raise ValueError('original note exists')
    if tx.fetchone('SELECT id FROM saved_diagnoses WHERE id=? AND user_id=?', (row['id'], row['user_id'])):
        raise ValueError('original diagnosis exists')
    session = tx.fetchone('SELECT note_id,generate_ctx_json FROM chat_sessions WHERE id=? AND user_id=?', (row['id'], row['user_id']))
    if session:
        import json
        task = json.loads(session['generate_ctx_json'] or '{}').get('task_continuation', {})
        if session['note_id'] or not isinstance(task, dict) or 'result' in task or (task.get('status') == 'completed'):
            raise ValueError('original session result may exist')
    if tx.fetchone('SELECT operation_id FROM ai_operation_admissions WHERE idempotency_request_id=?', (row['id'],)):
        raise ValueError('durable operation requires its original settlement')
    now = billing._now()
    tx.execute('UPDATE usage_records SET source=?,credits_used=0 WHERE id=? AND user_id=?', (RELEASED_PREFIX + _version(row)['source'], row['usage_id'], row['user_id']))
    tx.execute("UPDATE idempotency_requests SET status='failed',refund_applied=1,failure_code=CASE WHEN failure_code<>'' THEN failure_code ELSE 'request_failed' END,failed_at=COALESCE(failed_at,?),refunded_at=NULL,updated_at=? WHERE id=?", (now, now, row['id']))
    return {'status': 'released', 'credits_used': 0}


def reconcile_undelivered_reservation(user_id, request_id, *, expected_snapshot,
                                     expected_provider_calls, original_execution_ended):
    """Maintenance-only release after original work has provably ended.

    No lease timeout alone releases a hold. The caller supplies the complete
    original task snapshot and physical-call manifest read before this explicit
    action; every field is compared under the existing user fence. No provider
    record, fee, or UNKNOWN state changes, and no owner token is reconstructed.
    """
    fields = {"operation", "key_hash", "payload_hash", "usage_id", "lease_token_hash",
        "lease_expires_at", "charge_source", "credits_used", "monthly_credits_used",
        "wallet_credits_used", "charged_subscription_id", "charged_period_start",
        "status", "failure_code", "failed_at"}
    if (original_execution_ended is not True or not user_id or not request_id
            or not isinstance(expected_snapshot, dict) or set(expected_snapshot) != fields
            or not isinstance(expected_provider_calls, list)
            or not 0 <= len(expected_provider_calls) <= 64):
        raise ValueError("original reservation recovery proof is incomplete")
    call_fields = {"id", "state", "http_status", "model_usage_record_id"}
    manifest = {}
    for call in expected_provider_calls:
        if (not isinstance(call, dict) or set(call) != call_fields
                or not isinstance(call["id"], str) or not 1 <= len(call["id"]) <= 128
                or call["id"] in manifest):
            raise ValueError("original reservation call manifest is invalid")
        manifest[call["id"]] = call
    with db.transaction(write=True) as tx:
        content_retention.assert_user_writable_with_storage(tx, user_id)
        _lock_wallet(tx, user_id)
        lock = " FOR UPDATE" if tx.postgres else ""
        row = tx.fetchone("SELECT * FROM idempotency_requests WHERE id=? AND user_id=?" + lock,
                          (request_id, user_id))
        row = dict(row) if row else None
        if not row or _version(row) is None:
            raise ValueError("original reservation not found")
        # An already released readback is idempotent only for the same funding,
        # execution and usage identity. Its first failure timestamp is retained.
        already_released = bool(row["refund_applied"])
        mutable = {"status", "failure_code", "failed_at"} if already_released else set()
        if any(row[key] != value for key, value in expected_snapshot.items() if key not in mutable):
            raise ValueError("original reservation snapshot changed")
        expiry = idempotency._parse_lease_clock(row["lease_expires_at"])
        if (row["operation"] not in {"generate", "analyze"} or row["complete_applied"]
                or not row["charge_applied"] or row["status"] not in {"running", "failed"}
                or expiry is None or expiry > idempotency._now()
                or row["failure_code"] == "result_store_unknown"):
            raise ValueError("original reservation is not an expired undelivered execution")
        _assert_usage_state(tx, row)
        calls = tx.fetchall("SELECT id,user_id,state,http_status,model_usage_record_id FROM public_trial_calls "
                            "WHERE usage_record_id=? ORDER BY id" + lock, (row["usage_id"],))
        actual = {call["id"]: {key: call[key] for key in call_fields} for call in calls}
        if actual != manifest or any(call["user_id"] != user_id for call in calls):
            raise ValueError("original reservation call manifest changed")
        for call in calls:
            if call["model_usage_record_id"] and not tx.fetchone(
                    "SELECT id FROM model_usage_records WHERE id=? AND usage_record_id=?",
                    (call["model_usage_record_id"], row["usage_id"])):
                raise ValueError("original reservation model usage binding changed")
        return _release_row_in_transaction(tx, row)


def cancel_waiting_reservation(user_id, request_id):
    """Owner cancels an already paused, fully settled v1 task, never live work.

    Pause writes waiting only after joining its model calls. The user fence
    makes this mutually exclusive with the original continuation resume CAS.
    """
    with db.transaction(write=True) as tx:
        content_retention.assert_user_writable_with_storage(tx,user_id)
        _lock_wallet(tx,user_id)
        lock=" FOR UPDATE" if tx.postgres else ""
        row=tx.fetchone("SELECT * FROM idempotency_requests WHERE id=? AND user_id=?"+lock,
                       (request_id,user_id))
        row=dict(row) if row else None
        if not row or _version(row) is None or row["status"]!="waiting_for_input":
            return None
        import public_product
        if public_product.queue_status(user_id,row["key_hash"]).get("active") is not False:
            raise ValueError("original paused operation is still active")
        _assert_usage_state(tx,row)
        _assert_calls_settled(tx,row["usage_id"],require_success=False)
        session=tx.fetchone("SELECT note_id,generate_ctx_json FROM chat_sessions WHERE id=? AND user_id=?"+lock,
                            (request_id,user_id))
        context=json.loads(session["generate_ctx_json"] or "{}") if session else None
        import task_clarification
        task=context.get(task_clarification.KEY) if isinstance(context,dict) else None
        if (not session or session["note_id"] or not isinstance(task,dict)
                or task.get("status")!="waiting_for_input" or task.get("operation")!=row["operation"]
                or type(task.get("version")) is not int or task["version"]<1 or "result" in task):
            raise ValueError("original paused task identity changed")
        _release_row_in_transaction(tx,row)
        task.update(status="failed",version=task["version"]+1,cancelled=True)
        tx.execute("UPDATE chat_sessions SET generate_ctx_json=?,updated_at=? WHERE id=? AND user_id=?",
            (json.dumps(context,ensure_ascii=False,separators=(",",":")),billing._now(),request_id,user_id))
        return receipt_in_transaction(tx,user_id,request_id)


def release_undelivered(context, *, original_execution_ended):
    """Release customer hold only; supplier fees/UNKNOWN are never rewritten."""
    with db.transaction(write=True) as tx:
        return release_in_transaction(tx,context,original_execution_ended=original_execution_ended)


def fail_reservation(context, *, failure_code, original_execution_ended=False):
    with db.transaction(write=True) as tx:
        row = _owned(tx,context)
        if row["complete_applied"] or row["refund_applied"]:
            return False
        now=billing._now()
        tx.execute("UPDATE idempotency_requests SET status='failed',failure_code=CASE WHEN failure_code='' THEN ? ELSE failure_code END,"
            "failed_at=COALESCE(failed_at,?),updated_at=? WHERE id=?",
            (failure_code if failure_code in idempotency.FAILURE_CODES else "request_failed",now,now,row["id"]))
        if original_execution_ended:
            release_in_transaction(tx,context,original_execution_ended=True)
    return True


def confirm_completed(context):
    with db.transaction(write=False) as tx:
        row=tx.fetchone("SELECT * FROM idempotency_requests WHERE id=? AND user_id=?",
                       (context["request_id"],context["user_id"]))
        return bool(row and _version(dict(row)) and row["status"]=="completed"
            and row["complete_applied"] and not row["refund_applied"]
            and all(row[key] == context.get(key) for key in ("user_id","operation","key_hash","payload_hash"))
            and row["usage_id"] == context["charge"]["usage_id"]
            and row["lease_token_hash"]==idempotency._sha256(context["lease_token"]))


def assert_legacy_rollback_safe():
    with db.transaction(write=False) as tx:
        if _open_rows(tx):
            raise ValueError("legacy image cannot handle pending reservation_v1")


def assert_legacy_spend_safe(tx, user_id):
    if _open_rows(tx, user_id):
        raise ValueError("legacy spender must account for reservation_v1")


def assert_entitlement_mutation_safe(tx, user_id):
    """Payment/Admin-compatible projection; no idempotency permission expansion.

    Caller holds the existing canonical per-user financial advisory fence before
    order/position/subscription locks. Payment only reads its existing permitted
    usage projection; no new users/idempotency privilege is needed.
    """
    if tx.fetchone("SELECT source FROM usage_records WHERE user_id=? AND SUBSTR(source,1,?)=? LIMIT 1",
                   (user_id,len(PREFIX),PREFIX)):
        raise ValueError("outstanding reservation protects original entitlement")


def enabled():
    """New reservations are opt-in; existing reservation compatibility is always on."""
    return os.environ.get("NOTEAI_POSTDELIVERY_SETTLEMENT") == "1"


def is_context(context):
    return bool(context and context.get("settlement_mode") == "reservation_v1")


def wallet_available_in_transaction(tx, user_id):
    row = tx.fetchone("SELECT balance FROM credits WHERE user_id=?", (user_id,))
    held = _money(sum(float(item["wallet_credits_used"] or 0) for item in _open_rows(tx,user_id)))
    return max(0, round(_money(row["balance"] if row else 0) - held, 2))


def receipt(user_id, operation, charge, request_id=None):
    rows = db.fetchall("SELECT * FROM idempotency_requests WHERE user_id=? AND usage_id=? AND operation=?",
        (user_id,charge.get("usage_id"),operation))
    if len(rows) != 1 or _version(dict(rows[0])) is None:
        return None
    row = dict(rows[0])
    if request_id and request_id != row["id"]:
        raise ValueError("original reservation receipt identity changed")
    return _receipt_values(row)


def receipt_in_transaction(tx, user_id, request_id):
    row = tx.fetchone("SELECT * FROM idempotency_requests WHERE id=? AND user_id=?",(request_id,user_id))
    if not row or _version(dict(row)) is None:
        raise ValueError("original reservation receipt unavailable")
    return _receipt_values(dict(row))


def _receipt_values(row):
    committed, released = bool(row["complete_applied"]), bool(row["refund_applied"])
    held = not committed and not released
    return {"usage_id": row["usage_id"], "request_id": row["id"], "operation":row["operation"],
        "source":_version(row)["source"], "settlement_mode":"reservation_v1",
        "status":"committed" if committed else "released" if released else "reserved",
        "credits_used":float(row["credits_used"]) if committed else 0.0,
        "reserved_credits":float(row["credits_used"]) if held else 0.0,
        "monthly_credits_reserved":float(row["monthly_credits_used"]) if held else 0.0,
        "wallet_credits_reserved":float(row["wallet_credits_used"]) if held else 0.0,
        "monthly_credits_used":float(row["monthly_credits_used"]) if committed else 0.0,
        "wallet_credits_used":float(row["wallet_credits_used"]) if committed else 0.0,
        "released_credits":float(row["credits_used"]) if released else 0.0, "refunded_credits":0.0}
