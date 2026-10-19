"""Owner-bound cover jobs using the existing reservation_v1 financial fence.

Importing or reading this module never creates tables. The feature increment is
applied explicitly by tests or the integration owner. No provider is called here.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import HTTPException

import billing
import content_retention
import cover_sources
import db
import idempotency
import postdelivery
import private_storage

OPERATION = "cover_generate"
MODEL_ID = "doubao-seedream-5-0-pro-260628"
WIDTH, HEIGHT = 1776, 2368
RETENTION_SECONDS = 90 * 86400
HOLD_SECONDS = 1800
BUDGET_ID = "noteai-xhs-cover-20261019-acceptance"
FORMAL_BUDGET_ID = "noteai-cover-formal-v1"
MAX_ACCEPTANCE_JOBS = 6
FEATURE_SQL = Path(__file__).parent / "migrations/features/noteai_xhs_cover_20261019_0001.sql"
STAGES = frozenset({"queued", "design", "image", "qc", "saving", "completed", "failed", "outcome_unknown"})


def _now(value=None):
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("UTC-aware clock required")
    return value.astimezone(timezone.utc)


def _json(value, *, maximum=262144):
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError("invalid cover snapshot") from None
    if len(encoded.encode()) > maximum:
        raise ValueError("cover snapshot too large")
    return encoded


def _sha(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def _decimal(value, *, nonnegative=True):
    if value is None or isinstance(value, bool):
        raise ValueError("explicit decimal cost required")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("invalid decimal cost") from None
    if not result.is_finite() or (nonnegative and result < 0):
        raise ValueError("invalid decimal cost")
    return result


def _lock(tx):
    return " FOR UPDATE" if tx.postgres else ""


def init_sqlite_schema():
    """Explicit local/test initialization only; never called by reads/admission."""
    if db.using_postgres():
        raise ValueError("feature migration belongs to the integration owner")
    connection = db.get_conn()
    try:
        with connection:
            connection.executescript(FEATURE_SQL.read_text().split("-- PostgreSQL-only integration tail.", 1)[0])
            connection.execute("INSERT INTO public_trial_budget(id,limit_milli_cny,reserved_milli_cny,enabled,policy_mode) "
                "VALUES('noteai-xhs-cover-20261019-acceptance',100000,0,1,'owner_metered') ON CONFLICT(id) DO NOTHING")
            connection.execute("INSERT INTO public_trial_budget(id,limit_milli_cny,reserved_milli_cny,enabled,policy_mode) "
                "VALUES('noteai-cover-formal-v1',0,0,1,'owner_metered') ON CONFLICT(id) DO NOTHING")
    finally:
        connection.close()


def _policy(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get("enabled") is not True:
        raise HTTPException(503, "封面功能尚未启用")
    if (snapshot.get("budget_id") not in {BUDGET_ID,FORMAL_BUDGET_ID} or snapshot.get("operation") != OPERATION or snapshot.get("model_id") != MODEL_ID
            or snapshot.get("provider") not in {"doubao", "ark", "volcengine_ark", "seedream"}
            or snapshot.get("width") != WIDTH or snapshot.get("height") != HEIGHT
            or _decimal(snapshot.get("credits")) != Decimal(8)
            or snapshot.get("retention_seconds") != RETENTION_SECONDS
            or type(snapshot.get("max_physical_calls")) is not int
            or not 1 <= snapshot["max_physical_calls"] <= 3
            or snapshot.get("max_image_calls", 1) != 1):
        raise ValueError("cover policy differs from the approved fixed contract")
    # An explicitly configured operational budget is not a newly approved user
    # product price. Its value is retained, rather than invented in this module.
    if snapshot.get("provider_budget") is not None and _decimal(snapshot["provider_budget"]) <= 0:
        raise ValueError("invalid configured cover budget")
    _json(snapshot)
    return snapshot


def policy_quote_version(policy_snapshot):
    policy = _policy(policy_snapshot)
    return _sha(_json({"operation": OPERATION, "credits": "8", "policy": policy,
        "charge_timing": "after_saved_cover", "unknown_release_seconds": HOLD_SECONDS}))[:24]


def quote_for_user(user_id, *, policy_snapshot):
    quote = billing.get_operation_quote(user_id, OPERATION)
    if _decimal(quote["credits"]) != Decimal(8):
        raise HTTPException(503,"封面报价配置需要核实")
    quote.update(quote_version=policy_quote_version(policy_snapshot),
        charge_timing="after_saved_cover", failure_policy="no_usable_delivery_no_charge",
        retry_policy="same_request_id_no_second_charge", retention_seconds=RETENTION_SECONDS,
        unknown_release_seconds=HOLD_SECONDS, width=WIDTH, height=HEIGHT,
        model_id=MODEL_ID)
    return quote


def _authorize_report(tx, user_id, report_type, report_id):
    if report_type == "analyze":
        row = tx.fetchone("SELECT id FROM saved_diagnoses WHERE id=? AND user_id=? AND diagnosis_json<>''",
                          (report_id, user_id))
        visible = row and content_retention.status("diagnosis", report_id, user_id, tx)["state"] == "active"
    elif report_type == "generate":
        row = tx.fetchone("SELECT c.note_id,c.generate_ctx_json FROM chat_sessions c "
            "JOIN idempotency_requests r ON r.id=c.id AND r.user_id=c.user_id "
            "JOIN notes n ON n.id=c.note_id AND n.user_id=c.user_id "
            "WHERE c.id=? AND c.user_id=? AND r.operation='generate' AND r.status='completed' "
            "AND r.complete_applied=1 AND n.source='generate'", (report_id, user_id))
        visible = False
        if row:
            try:
                task = json.loads(row["generate_ctx_json"] or "{}").get("task_continuation", {})
                result = task.get("result", {})
                visible = (task.get("operation") == "generate" and task.get("status") == "completed"
                    and result.get("saved_note_id") == row["note_id"]
                    and isinstance(result.get("note_title"), str) and isinstance(result.get("note_body"), str)
                    and content_retention.status("note", row["note_id"], user_id, tx)["state"] == "active")
            except (TypeError, ValueError, AttributeError):
                pass
    else:
        visible = False
    if not visible:
        raise HTTPException(404, "报告不存在或已到保存期限")


def _safe_input(snapshot):
    if not isinstance(snapshot, dict) or not snapshot:
        raise ValueError("frozen report input required")
    forbidden = {"prepared", "messages", "api_key", "authorization", "image_base64", "cover_image", "cover_images"}
    def inspect(value, depth=0):
        if depth > 12:
            raise ValueError("cover input too deeply nested")
        if isinstance(value, dict):
            if forbidden.intersection(value):
                raise ValueError("raw transport fields are not cover input")
            for item in value.values():
                inspect(item, depth + 1)
        elif isinstance(value, (list, tuple)):
            if len(value) > 200:
                raise ValueError("cover input list too large")
            for item in value:
                inspect(item, depth + 1)
        elif not isinstance(value, (str, int, float, bool, type(None))):
            raise ValueError("invalid frozen cover input")
    inspect(snapshot)
    _json(snapshot)
    return snapshot


def _projection(row, claim=None):
    item = dict(row)
    receipt = postdelivery._receipt_values(dict(claim)) if claim else None
    return {"job_id": item["id"], "request_id": item["client_request_id"], "report_type": item["report_type"],
        "report_id": item["report_id"], "status": item["status"], "stage": item["stage"],
        "created_at": item["created_at"], "expires_at": item["expires_at"],
        "has_final": bool(item["final_media_ref"] and item["status"] == "completed"
            and item["expires_at"] and item["expires_at"] > _now().isoformat()),
        "layout": _public_layout(json.loads(item["layout_json"] or "{}")), "asset_revision": item["asset_revision"],
        "billing": receipt, "failure_code": item["failure_code"]}


def get_job(user_id, job_id):
    row = db.fetchone("SELECT * FROM cover_jobs WHERE id=? AND user_id=?", (job_id, user_id))
    if not row:
        return None
    claim = db.fetchone("SELECT * FROM idempotency_requests WHERE id=? AND user_id=?", (job_id, user_id))
    return _projection(row, claim)


def list_report_jobs(user_id, report_type, report_id):
    with db.transaction(write=False) as tx:
        rows = tx.fetchall("SELECT * FROM cover_jobs WHERE user_id=? AND report_type=? AND report_id=? "
            "ORDER BY created_at DESC,id DESC", (user_id, report_type, report_id))
        if not rows:
            _authorize_report(tx, user_id, report_type, report_id)
        # Retained cover artifacts have their own approved 90-day lifecycle.
        # Existing owner rows remain discoverable without reading an expired or
        # deleted report's body. This never authorizes a new submit for it.
        return [_projection(row, tx.fetchone("SELECT * FROM idempotency_requests WHERE id=?", (row["id"],))) for row in rows]


def list_user_jobs(user_id, *, limit=100, now=None):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise HTTPException(422,"封面列表数量无效")
    clock = _now(now)
    rows = db.fetchall("SELECT * FROM cover_jobs WHERE user_id=? AND ((status='completed' AND expires_at>?) "
        "OR (status IN ('queued','running','saving','outcome_unknown') AND created_at>=?)) "
        "ORDER BY created_at DESC,id DESC LIMIT ?",(user_id,clock.isoformat(),
        (clock-timedelta(seconds=RETENTION_SECONDS)).isoformat(),limit))
    return [_projection(row,db.fetchone("SELECT * FROM idempotency_requests WHERE id=? AND user_id=?",(row["id"],user_id))) for row in rows]


def submit_job(*, user_id, report_type, report_id, request_id, source_refs, input_snapshot,
               policy_snapshot, quote_version=None, now=None):
    """Freeze one owner report/material/policy and its hold in one transaction."""
    clock = _now(now)
    refs = cover_sources.normalize_source_refs(source_refs)
    if not refs:
        raise HTTPException(422, "请先补传至少一张真实图片")
    _safe_input(input_snapshot)
    _policy(policy_snapshot)
    request_key = idempotency.normalize_request_id(request_id)
    if not request_key:
        raise HTTPException(422, "封面任务需要稳定的请求编号")
    payload = {"report_type": report_type, "report_id": report_id, "source_refs": refs,
               "input": input_snapshot, "policy": policy_snapshot}
    digest = idempotency.payload_hash(payload)
    key_hash = idempotency._sha256(request_key)
    with db.transaction(write=True) as tx:
        content_retention.assert_user_writable_with_storage(tx, user_id)
        previous = tx.fetchone("SELECT i.id,i.payload_hash FROM idempotency_requests i "
            "WHERE i.user_id=? AND i.operation=? AND i.key_hash=?" + _lock(tx), (user_id, OPERATION, key_hash))
        if previous:
            if previous["payload_hash"] != digest:
                raise HTTPException(409, "原请求编号已绑定不同的封面内容")
            old = tx.fetchone("SELECT * FROM cover_jobs WHERE id=? AND user_id=?", (previous["id"], user_id))
            if not old:
                raise HTTPException(409, "原封面任务需要核实，不能重复创建")
            result = _projection(old, tx.fetchone("SELECT * FROM idempotency_requests WHERE id=?", (old["id"],)))
            return {**result, "created": False}
        _authorize_report(tx, user_id, report_type, report_id)
    # Verify actual bytes outside the short financial transaction. The second
    # fence below locks and compares the exact source descriptors again.
    manifest = []
    for ref_id in refs:
        ref, body = private_storage.load_media_bytes(ref_id, user_id=user_id, purpose="image", now=clock)
        manifest.append({"media_ref": ref.id, "sha256": _sha(body), "size_bytes": len(body)})
    with db.transaction(write=True) as tx:
        content_retention.assert_user_writable_with_storage(tx, user_id)
        _authorize_report(tx, user_id, report_type, report_id)
        locked = private_storage.lock_ready_media_refs(tx, user_id, refs, now=clock)
        if any(ref.purpose != "image" or ref.content_sha256 != item["sha256"] or ref.size_bytes != item["size_bytes"]
               for ref, item in zip(locked, manifest)):
            raise ValueError("original cover source changed")
        budget_id = policy_snapshot["budget_id"]
        budget = tx.fetchone("SELECT * FROM public_trial_budget WHERE id=?"+_lock(tx),(budget_id,))
        expected_limit = 100000 if budget_id == BUDGET_ID else 0
        if not budget or not budget["enabled"] or budget["limit_milli_cny"] != expected_limit or budget["policy_mode"] != "owner_metered":
            raise HTTPException(503,"封面独立计量范围尚未就绪")
        count = tx.fetchone("SELECT count(*) AS n FROM cover_jobs WHERE budget_id=?",(budget_id,))
        # The shared budget row serializes the six-sample bound across users.
        # An already admitted key must still be readable when this bound is full.
        original = tx.fetchone("SELECT id FROM idempotency_requests WHERE user_id=? AND operation=? AND key_hash=?",(user_id,OPERATION,key_hash))
        if budget_id == BUDGET_ID and count["n"] >= MAX_ACCEPTANCE_JOBS and not original:
            raise HTTPException(429,"本次封面验收样本已达上限，请等待核对")
        expected_quote = policy_quote_version(policy_snapshot)
        context = postdelivery.reserve_claim_in_transaction(tx, user_id=user_id, operation=OPERATION,
            request_id=request_key, payload=payload, quote_version=quote_version, cover_quote_version=expected_quote)
        if context["state"] == "conflict":
            raise HTTPException(409, "原请求编号已绑定不同的封面内容")
        if context["state"] != "reservation_owner":
            old = tx.fetchone("SELECT * FROM cover_jobs WHERE id=? AND user_id=?", (context["task_id"], user_id))
            if not old:
                raise HTTPException(409, "原封面任务需要核实")
            return {**_projection(old, tx.fetchone("SELECT * FROM idempotency_requests WHERE id=?", (old["id"],))), "created": False}
        if _decimal(context["charge"]["credits_used"]) != Decimal(8):
            raise ValueError("original eight-credit cover quote changed")
        job_id = context["request_id"]
        tx.execute("INSERT INTO cover_jobs(id,user_id,report_type,report_id,client_request_id,budget_id,usage_id,payload_hash,input_json,"
            "source_manifest_json,policy_json,quote_version,status,stage,deadline_at,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'queued','queued',?,?,?)", (job_id,user_id,report_type,report_id,request_key,budget_id,
            context["charge"]["usage_id"],digest,_json(input_snapshot),_json(manifest),_json(policy_snapshot),
            expected_quote,(clock+timedelta(seconds=HOLD_SECONDS)).isoformat(),clock.isoformat(),clock.isoformat()))
        tx.execute("UPDATE idempotency_requests SET lease_expires_at=? WHERE id=?", ((clock+timedelta(seconds=HOLD_SECONDS)).isoformat(),job_id))
        row = tx.fetchone("SELECT * FROM cover_jobs WHERE id=?", (job_id,))
        claim = tx.fetchone("SELECT * FROM idempotency_requests WHERE id=?", (job_id,))
        return {**_projection(row, claim), "created": True}


def _owner_row(tx, claim, *, now=None, allow_completed=False):
    clock = _now(now).isoformat()
    content_retention.assert_user_writable_with_storage(tx, claim["user_id"])
    row = tx.fetchone("SELECT * FROM cover_jobs WHERE id=? AND user_id=?" + _lock(tx), (claim["request_id"], claim["user_id"]))
    if not row or row["lease_fence"] != claim.get("cover_fence") or row["lease_token_hash"] != _sha(claim.get("lease_token", "")):
        raise ValueError("original cover worker lease changed")
    if allow_completed and row["status"] == "completed":
        return dict(row)
    if row["status"] not in {"running", "saving"} or not row["lease_expires_at"] or row["lease_expires_at"] <= clock or row["deadline_at"] <= clock:
        raise ValueError("cover worker lease is not live")
    return dict(row)


def _context(row, financial, token):
    source = postdelivery._version(dict(financial))
    return {"state": "reservation_owner", "settlement_mode": "reservation_v1", "request_id":row["id"],
        "user_id":row["user_id"], "operation":OPERATION, "key_hash":financial["key_hash"],
        "payload_hash":financial["payload_hash"], "lease_token":token, "cover_fence":row["lease_fence"],
        "input_snapshot":json.loads(row["input_json"]), "source_manifest":json.loads(row["source_manifest_json"]),
        "policy_snapshot":json.loads(row["policy_json"]), "report_type":row["report_type"], "report_id":row["report_id"],
        "charge":{"usage_id":row["usage_id"], "settlement_mode":"reservation_v1", "source":source["source"],
            "credits_used":financial["credits_used"], "monthly_credits_used":financial["monthly_credits_used"],
            "wallet_credits_used":financial["wallet_credits_used"], "subscription_id":financial["charged_subscription_id"],
            "subscription_period_start":financial["charged_period_start"]}}


def claim_job(job_id, *, lease_seconds=300, now=None):
    clock = _now(now)
    if type(lease_seconds) is not int or not 1 <= lease_seconds <= 300:
        raise ValueError("bounded cover lease required")
    preliminary = db.fetchone("SELECT user_id FROM cover_jobs WHERE id=?", (job_id,))
    if not preliminary:
        return None
    with db.transaction(write=True) as tx:
        try:
            content_retention.assert_user_writable_with_storage(tx, preliminary["user_id"])
        except ValueError:
            return None
        row = tx.fetchone("SELECT * FROM cover_jobs WHERE id=?" + _lock(tx), (job_id,))
        if (row["status"] != "queued" or row["deadline_at"] <= clock.isoformat()
                or json.loads(row["call_intents_json"])
                or tx.fetchone("SELECT id FROM public_trial_calls WHERE usage_record_id=? LIMIT 1", (row["usage_id"],))):
            return None
        token = secrets.token_urlsafe(32)
        expiry = min(clock+timedelta(seconds=lease_seconds), datetime.fromisoformat(row["deadline_at"]))
        tx.execute("UPDATE cover_jobs SET status='running',stage='design',lease_fence=lease_fence+1,"
            "lease_token_hash=?,lease_expires_at=?,updated_at=? WHERE id=?", (_sha(token),expiry.isoformat(),clock.isoformat(),job_id))
        tx.execute("UPDATE idempotency_requests SET lease_token_hash=? WHERE id=? AND complete_applied=0 AND refund_applied=0", (_sha(token),job_id))
        row = tx.fetchone("SELECT * FROM cover_jobs WHERE id=?", (job_id,))
        financial = tx.fetchone("SELECT * FROM idempotency_requests WHERE id=?", (job_id,))
        if financial["refund_applied"] or financial["complete_applied"]:
            raise ValueError("original cover reservation already settled")
        return _context(row, financial, token)


def mark_stage(claim, stage, *, now=None):
    if stage not in {"design", "image", "qc", "saving"}:
        raise ValueError("invalid running cover stage")
    clock = _now(now)
    with db.transaction(write=True) as tx:
        row = _owner_row(tx, claim, now=clock)
        expiry = min(clock+timedelta(seconds=300), datetime.fromisoformat(row["deadline_at"]))
        tx.execute("UPDATE cover_jobs SET stage=?,status=?,lease_expires_at=?,updated_at=? WHERE id=?",
            (stage,"saving" if stage=="saving" else "running",expiry.isoformat(),clock.isoformat(),row["id"]))
    return True


def before_text_call(claim, stage, call_id, *, now=None):
    """Persist one design/QC dispatch intent before invoking the original adapter."""
    if stage not in {"design", "qc"} or not isinstance(call_id,str) or not call_id:
        raise ValueError("invalid cover text/vision call intent")
    clock = _now(now)
    with db.transaction(write=True) as tx:
        row = _owner_row(tx,claim,now=clock)
        intents = json.loads(row["call_intents_json"])
        if stage in intents or call_id in intents.values():
            raise ValueError("original cover model step already admitted; never replay")
        calls = tx.fetchall("SELECT id FROM public_trial_calls WHERE usage_record_id=?",(row["usage_id"],))
        known_ids = set(intents.values()) | {call["id"] for call in calls}
        if len(known_ids | {call_id}) > json.loads(row["policy_json"])["max_physical_calls"]:
            raise ValueError("cover task call limit exceeded")
        intents[stage] = call_id
        tx.execute("UPDATE cover_jobs SET call_intents_json=?,stage=?,updated_at=? WHERE id=?",(_json(intents),stage,clock.isoformat(),row["id"]))
    return True


def heartbeat_job(claim, *, now=None):
    clock = _now(now)
    with db.transaction(write=True) as tx:
        row = _owner_row(tx,claim,now=clock)
        expiry = min(clock+timedelta(seconds=300),datetime.fromisoformat(row["deadline_at"]))
        tx.execute("UPDATE cover_jobs SET lease_expires_at=?,updated_at=? WHERE id=?",(expiry.isoformat(),clock.isoformat(),row["id"]))
    return True


def begin_image_call(claim, *, call_id, provider, model_id, input_images, width, height,
                     pricing_snapshot, estimated_cost, currency="CNY", price_version, now=None):
    if (currency != "CNY" or model_id != MODEL_ID or width != WIDTH or height != HEIGHT or type(input_images) is not int
            or not 1 <= input_images <= 9 or not isinstance(provider,str) or not provider
            or not isinstance(price_version,str) or not price_version):
        raise ValueError("invalid fixed cover image call")
    estimate = str(_decimal(estimated_cost))
    pricing = _json(pricing_snapshot)
    clock = _now(now)
    with db.transaction(write=True) as tx:
        row = _owner_row(tx, claim, now=clock)
        physical = tx.fetchone("SELECT * FROM public_trial_calls WHERE id=?" + _lock(tx), (call_id,))
        if not physical or physical["user_id"] != row["user_id"] or physical["usage_record_id"] != row["usage_id"] or physical["state"] != "dispatched":
            raise ValueError("original image call requires its shared physical admission")
        prior = tx.fetchone("SELECT * FROM cover_image_usage WHERE job_id=?", (row["id"],))
        if prior:
            if prior["id"] == call_id:
                raise ValueError("image call already dispatched; never replay")
            raise ValueError("one paid image call per cover task")
        tx.execute("INSERT INTO cover_image_usage(id,job_id,usage_id,provider,model_id,state,input_images,width,height,"
            "pricing_json,estimated_cost,currency,price_version,cost_status,created_at) "
            "VALUES(?,?,?,?,?,'dispatched',?,?,?,?,?,?,?,'estimated',?)", (call_id,row["id"],row["usage_id"],provider,
            model_id,input_images,width,height,pricing,estimate,currency,price_version,clock.isoformat()))
        refresh_usage_in_transaction(tx,row["usage_id"])
    return True


def finish_image_call(claim, call_id, *, status, output_images=0, billed_images=None, actual_cost=None,
                      evidence_ref=None, response_hash=None, http_status=None, provider_request_id=None, now=None):
    if status not in {"responded", "failed", "unknown"} or type(output_images) is not int or not 0 <= output_images <= 1:
        raise ValueError("invalid image call outcome")
    if billed_images is not None and (type(billed_images) is not int or not 0 <= billed_images <= 1):
        raise ValueError("invalid billed image count")
    if provider_request_id is not None and (not isinstance(provider_request_id,str)
            or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}",provider_request_id)):
        raise ValueError("invalid supplier request reference")
    actual = None if actual_cost is None else str(_decimal(actual_cost))
    if actual is not None and not evidence_ref:
        raise ValueError("supplier bill evidence required for actual image cost")
    cost_status = "billed" if actual is not None else "unknown" if status=="unknown" or billed_images is None else "estimated"
    values = (status,output_images,billed_images,actual,cost_status,_sha(str(evidence_ref)) if evidence_ref else None,response_hash,http_status,provider_request_id)
    clock = _now(now)
    with db.transaction(write=True) as tx:
        # A timed-out original call may still provide its receipt. Keep supplier
        # evidence after customer release; this path never charges the customer.
        content_retention.assert_user_writable_with_storage(tx, claim["user_id"])
        row = tx.fetchone("SELECT * FROM cover_image_usage WHERE id=? AND job_id=?" + _lock(tx), (call_id,claim["request_id"]))
        job = tx.fetchone("SELECT user_id FROM cover_jobs WHERE id=?", (claim["request_id"],))
        if not row or not job or job["user_id"] != claim["user_id"]:
            raise ValueError("original image cost identity missing")
        old = tuple(row[key] for key in ("state","output_images","billed_images","actual_cost","cost_status","evidence_ref_hash","response_hash","http_status","provider_request_id"))
        if row["state"] != "dispatched":
            if old == values:
                return False
            raise ValueError("original physical image result already recorded")
        tx.execute("UPDATE cover_image_usage SET state=?,output_images=?,billed_images=?,actual_cost=?,cost_status=?,"
            "evidence_ref_hash=?,response_hash=?,http_status=?,provider_request_id=?,completed_at=? WHERE id=?", (*values,clock.isoformat(),call_id))
        refresh_usage_in_transaction(tx,row["usage_id"])
    return True


def image_usage_summary_in_transaction(tx,usage_id):
    rows = tx.fetchall("SELECT provider,model_id,state,input_images,output_images,billed_images,width,height,"
        "estimated_cost,actual_cost,currency,price_version,cost_status FROM cover_image_usage WHERE usage_id=? ORDER BY created_at,id",(usage_id,))
    estimates = sum((_decimal(row["estimated_cost"]) for row in rows),Decimal(0))
    known = sum((_decimal(row["actual_cost"]) for row in rows if row["actual_cost"] is not None and row["currency"]=="CNY"),Decimal(0))
    complete = all(row["cost_status"]=="billed" and row["actual_cost"] is not None and row["currency"]=="CNY" for row in rows)
    calls = [{**dict(row),"pixel_count":row["width"]*row["height"]} for row in rows]
    return {"physical_calls":len(rows),"estimated_cost_rmb":float(estimates),"known_billed_cost_rmb":float(known),
        "actual_cost_rmb":float(known) if complete else None,"cost_status":"actual" if complete else "partial", "calls":calls}


def refresh_usage_in_transaction(tx,usage_id):
    """Recompute only this cover parent without treating an image estimate as a bill.

    All callers hold the original user financial fence. This helper uses the
    supplied short transaction, never starts a nested transaction or provider.
    """
    parent = tx.fetchone("SELECT id,operation FROM usage_records WHERE id=?"+_lock(tx),(usage_id,))
    if not parent or parent["operation"] != OPERATION:
        return
    models = tx.fetchall("SELECT * FROM model_usage_records WHERE usage_record_id=?",(usage_id,))
    images = tx.fetchall("SELECT * FROM cover_image_usage WHERE usage_id=?",(usage_id,))
    physical = tx.fetchall("SELECT id,state,http_status,model_usage_record_id FROM public_trial_calls WHERE usage_record_id=?",(usage_id,))
    job = tx.fetchone("SELECT status FROM cover_jobs WHERE usage_id=?",(usage_id,))
    token_cost = sum((_decimal(row["known_cost_rmb"]) for row in models),Decimal(0))
    image_cost = sum((_decimal(row["actual_cost"]) for row in images if row["actual_cost"] is not None and row["currency"]=="CNY"),Decimal(0))
    image_estimate = sum((_decimal(row["estimated_cost"]) for row in images),Decimal(0))
    known_cost = token_cost+image_cost
    incomplete = any(row["usage_status"] != "complete" for row in models) or any(row["state"] != "responded" or row["http_status"] != 200 for row in physical)
    # Image quantities can be confirmed while the account bill is still unknown.
    gaps = any(row["pricing_status"] != "exact" for row in models) or any(row["cost_status"] != "billed" or row["actual_cost"] is None or row["currency"] != "CNY" for row in images)
    if incomplete:
        mode = "usage_incomplete"
    elif gaps or not job or job["status"] != "completed":
        mode = "partial" if models or images else "estimated"
    else:
        mode = "actual" if models or images else "estimated"
    names = sorted({row["provider"]+":"+row["model"] for row in models} | {row["provider"]+":"+row["model_id"] for row in images})
    tx.execute("UPDATE usage_records SET actual_model_cost_rmb=?,estimated_cost_rmb=?,cost_rmb=?,model_calls=?,model_names=?,cost_mode=? WHERE id=?",
        (float(known_cost),float(token_cost+image_estimate),float(known_cost),max(len(physical),len(models)+len(images)),",".join(names),mode,usage_id))


def reconcile_image_cost(user_id,job_id,call_id,*,actual_cost,evidence_ref,billed_images=None,currency=None,now=None):
    """Attach one original supplier bill without replaying or charging the user.

    This records externally verified evidence supplied by the authenticated
    owner/operator boundary. It does not fetch or independently authenticate a
    bill. Original response states, UNKNOWN history and customer release remain.
    """
    amount = str(_decimal(actual_cost))
    if not isinstance(evidence_ref,str) or not evidence_ref.strip() or len(evidence_ref)>500:
        raise ValueError("bounded supplier billing evidence reference required")
    if billed_images is not None and (type(billed_images) is not int or not 0<=billed_images<=1):
        raise ValueError("invalid original billed image count")
    evidence_hash = _sha(evidence_ref)
    with db.transaction(write=True) as tx:
        content_retention.assert_user_writable_with_storage(tx,user_id)
        job = tx.fetchone("SELECT user_id,usage_id FROM cover_jobs WHERE id=? AND user_id=?"+_lock(tx),(job_id,user_id))
        row = tx.fetchone("SELECT * FROM cover_image_usage WHERE id=? AND job_id=?"+_lock(tx),(call_id,job_id))
        if not job or not row or row["usage_id"] != job["usage_id"]:
            raise HTTPException(404,"原图片调用不存在")
        if row["state"] == "dispatched":
            raise HTTPException(409,"原图片调用仍在等待终态，请先核查原请求")
        if currency is not None and currency != row["currency"]:
            raise HTTPException(409,"原图片调用账单币种不一致")
        if billed_images is not None and row["billed_images"] is not None and billed_images != row["billed_images"]:
            raise HTTPException(409,"原图片调用已有不同的计费张数证据")
        if row["actual_cost"] is not None:
            if _decimal(row["actual_cost"]) == _decimal(amount) and row["evidence_ref_hash"] == evidence_hash:
                return False
            raise HTTPException(409,"原图片调用已有不同的实际成本证据")
        tx.execute("UPDATE cover_image_usage SET actual_cost=?,cost_status='billed',evidence_ref_hash=?,"
            "billed_images=COALESCE(billed_images,?),cost_reconciled_at=? WHERE id=?",
            (amount,evidence_hash,billed_images,_now(now).isoformat(),call_id))
        refresh_usage_in_transaction(tx,row["usage_id"])
    return True


def _verified_image(user_id, reference_id, *, now=None, layout=None):
    from PIL import Image
    reference, body = private_storage.load_media_bytes(reference_id, user_id=user_id, purpose="image", now=now)
    try:
        with Image.open(io.BytesIO(body)) as image:
            image.verify()
        with Image.open(io.BytesIO(body)) as image:
            if image.size != (WIDTH, HEIGHT):
                raise ValueError("cover output dimensions changed")
    except (OSError, SyntaxError):
        raise ValueError("saved cover image is invalid") from None
    if layout is not None:
        import cover_renderer
        cover_renderer.validate_artifact(body,layout)
    return reference


def _layout(value):
    import cover_renderer
    safe = cover_renderer.validate_plan(value)
    metadata = {"width","height","renderer_version","font_id","font_sha256","source_sha256",
        "photo_pixels","crop_pixels","rendered_lines","text_pixels","runtime_version","design_model","qc_model",
        "image_model","selected_source_ref","input_source_hashes"}
    if set(value)-set(safe)-metadata:
        raise ValueError("unrecognized cover layout metadata")
    result = {**safe, **{key:value[key] for key in metadata if key in value}}
    if (result.get("width") != WIDTH or result.get("height") != HEIGHT
            or result.get("renderer_version") != cover_renderer.RENDERER_VERSION
            or result.get("font_sha256") != cover_renderer.FONT_SHA256):
        raise ValueError("saved renderer contract changed")
    return _json(result,maximum=32768)


def _public_layout(value):
    if not value:
        return {}
    box = value.get("text_bbox",[0,0,1,0.25])
    photo = value.get("photo_bbox",[0,0,1,1])
    height = box[3]-box[1]
    options = []
    for label,y0 in (("top",.035),("bottom",.965-height)):
        candidate = [box[0],y0,box[2],y0+height]
        valid = 0<=candidate[0]<candidate[2]<=1 and 0<=candidate[1]<candidate[3]<=1
        intersects = candidate[0]<photo[2] and photo[0]<candidate[2] and candidate[1]<photo[3] and photo[1]<candidate[3]
        if valid and not intersects:
            options.append(label)
    return {"text":value.get("text", ""),"position":"top" if (box[1]+box[3])/2 < .5 else "bottom",
        "position_options":options,"lines":value.get("rendered_lines",value.get("text", "").splitlines())}


def get_layout(user_id,job_id):
    asset_reference(user_id,job_id)
    row = db.fetchone("SELECT layout_json FROM cover_jobs WHERE id=? AND user_id=?",(job_id,user_id))
    return json.loads(row["layout_json"])


def image_call_settled(tx, call_id):
    """Image quantity/pricing evidence can be known while its bill is unknown."""
    row = tx.fetchone("SELECT m.*,p.state AS physical_state,p.http_status AS physical_http,p.usage_record_id "
        "FROM cover_image_usage m JOIN public_trial_calls p ON p.id=m.id WHERE m.id=?",(call_id,))
    return bool(row and row["state"] == "responded" and row["physical_state"] == "responded"
        and row["http_status"] == 200 and row["physical_http"] == 200 and row["usage_record_id"] == row["usage_id"]
        and row["model_id"] == MODEL_ID and row["width"] == WIDTH and row["height"] == HEIGHT
        and 1 <= row["input_images"] <= 9 and row["output_images"] == 1 and row["billed_images"] == 1
        and row["price_version"] and row["pricing_json"])


def assert_calls_settled_in_transaction(tx, usage_id, *, require_success=True):
    calls = tx.fetchall("SELECT * FROM public_trial_calls WHERE usage_record_id=?", (usage_id,))
    if (require_success and not any(c["http_status"] == 200 for c in calls)) or any(c["state"] != "responded" for c in calls):
        raise ValueError("original cover supplier outcome remains unconfirmed")
    for call in calls:
        if call["http_status"] != 200:
            continue
        image = tx.fetchone("SELECT * FROM cover_image_usage WHERE id=? AND usage_id=?", (call["id"],usage_id))
        if image:
            if not image_call_settled(tx,call["id"]):
                raise ValueError("original image result remains unconfirmed")
        elif not call["model_usage_record_id"] or not tx.fetchone("SELECT id FROM model_usage_records WHERE id=? AND usage_record_id=?", (call["model_usage_record_id"],usage_id)):
            raise ValueError("original cover text/vision accounting remains unconfirmed")
    job = tx.fetchone("SELECT id,policy_json,call_intents_json,layout_json FROM cover_jobs WHERE usage_id=?", (usage_id,))
    if not job or len(calls) > json.loads(job["policy_json"])["max_physical_calls"]:
        raise ValueError("cover physical call budget changed")
    if require_success:
        intents = json.loads(job["call_intents_json"])
        if set(intents) != {"design","qc"} or len(set(intents.values())) != 2:
            raise ValueError("original design and quality calls are required")
        call_by_id = {call["id"]:call for call in calls}
        for call_id in intents.values():
            original = call_by_id.get(call_id)
            if not original or original["http_status"] != 200 or not original["model_usage_record_id"]:
                raise ValueError("original design or quality outcome is unconfirmed")
        image_rows = tx.fetchall("SELECT id FROM cover_image_usage WHERE usage_id=?",(usage_id,))
        expected = set(intents.values()) | {image["id"] for image in image_rows}
        route = json.loads(job["layout_json"] or "{}").get("route")
        if (set(call_by_id) != expected or (route == "seedream_background" and len(image_rows) != 1)
                or (route == "photo" and image_rows) or route not in {"photo","seedream_background"}):
            raise ValueError("cover production path differs from its original call manifest")


def assert_saved_in_transaction(tx, financial, result):
    if not isinstance(result,dict) or result.get("cover_job_id") != financial["id"]:
        raise ValueError("saved cover identity required")
    job = tx.fetchone("SELECT * FROM cover_jobs WHERE id=? AND user_id=?", (financial["id"],financial["user_id"]))
    if not job or job["status"] != "saving" or not job["final_media_ref"] or not job["base_media_ref"] or not job["qc_json"]:
        raise ValueError("usable cover has not been saved")
    qc = json.loads(job["qc_json"])
    if qc.get("passed") is not True or not tx.fetchone("SELECT revision FROM cover_asset_revisions WHERE job_id=? AND revision=1 AND media_ref=?", (job["id"],job["final_media_ref"])):
        raise ValueError("cover did not pass quality and durable revision checks")
    for reference_id in (job["final_media_ref"],job["base_media_ref"]):
        reference = tx.fetchone("SELECT * FROM private_media_refs WHERE id=? AND subject_hash=?", (reference_id,idempotency.operation_subject_hash(financial["user_id"])))
        if not reference or reference["state"] != "ready" or reference["purpose"] != "image" or reference["expires_at"] < job["expires_at"]:
            raise ValueError("saved cover ownership or retention changed")


def complete_job(claim, *, final_media_ref, base_media_ref, layout, qc_passed, qc_snapshot=None,
                 design_snapshot=None, now=None):
    existing = get_job(claim["user_id"],claim["request_id"])
    if existing and existing["status"] == "completed":
        return existing
    if qc_passed is not True:
        raise ValueError("a usable cover must pass quality checks")
    clock = _now(now)
    layout_json = _layout(layout)
    final = _verified_image(claim["user_id"],final_media_ref,now=clock,layout=layout)
    base = _verified_image(claim["user_id"],base_media_ref,now=clock)
    expires_at = min(final.expires_at,base.expires_at)
    if datetime.fromisoformat(expires_at) < clock+timedelta(seconds=RETENTION_SECONDS-60):
        raise ValueError("cover assets do not satisfy the approved 90-day retention")
    qc = {**(qc_snapshot or {}),"passed":True}
    with db.transaction(write=True) as tx:
        row = _owner_row(tx,claim,now=clock,allow_completed=True)
        if row["status"] == "completed":
            return _projection(row,tx.fetchone("SELECT * FROM idempotency_requests WHERE id=?",(row["id"],)))
        sources = {item["media_ref"]:item["sha256"] for item in json.loads(row["source_manifest_json"])}
        if layout.get("source_ref") not in sources or layout.get("source_sha256") != sources[layout["source_ref"]]:
            raise ValueError("saved cover layout no longer matches an original source")
        references = private_storage.lock_ready_media_refs(tx,claim["user_id"],list(dict.fromkeys([final.id,base.id])),now=clock)
        expected = {final.id:final.content_sha256,base.id:base.content_sha256}
        if any(ref.content_sha256 != expected[ref.id] for ref in references):
            raise ValueError("original verified asset changed")
        tx.execute("UPDATE cover_jobs SET status='saving',stage='saving',final_media_ref=?,base_media_ref=?,"
            "layout_json=?,qc_json=?,design_json=?,asset_revision=1,expires_at=?,updated_at=? WHERE id=?",
            (final.id,base.id,layout_json,_json(qc),_json(design_snapshot or {}),expires_at,clock.isoformat(),row["id"]))
        tx.execute("INSERT INTO cover_asset_revisions(job_id,revision,media_ref,layout_json,expires_at,created_at) VALUES(?,1,?,?,?,?)",
            (row["id"],final.id,layout_json,expires_at,clock.isoformat()))
        postdelivery.finalize_in_transaction(tx,claim,{"cover_job_id":row["id"]})
        tx.execute("UPDATE cover_jobs SET status='completed',stage='completed',completed_at=?,updated_at=?,failure_code='' WHERE id=?", (clock.isoformat(),clock.isoformat(),row["id"]))
        refresh_usage_in_transaction(tx,row["usage_id"])
        return _projection(tx.fetchone("SELECT * FROM cover_jobs WHERE id=?",(row["id"],)),tx.fetchone("SELECT * FROM idempotency_requests WHERE id=?",(row["id"],)))


def update_adjusted_asset(user_id,job_id,*,final_media_ref,layout,expected_revision,now=None):
    clock = _now(now)
    reference = _verified_image(user_id,final_media_ref,now=clock,layout=layout)
    layout_json = _layout(layout)
    with db.transaction(write=True) as tx:
        content_retention.assert_user_writable_with_storage(tx,user_id)
        row = tx.fetchone("SELECT * FROM cover_jobs WHERE id=? AND user_id=?"+_lock(tx),(job_id,user_id))
        if not row or row["status"] != "completed" or not row["expires_at"] or row["expires_at"] <= clock.isoformat():
            raise HTTPException(404,"可调整的封面不存在或已过期")
        if type(expected_revision) is not int or row["asset_revision"] != expected_revision:
            raise HTTPException(409,"封面已有新的文字调整，请重新打开后继续")
        if reference.expires_at < row["expires_at"]:
            raise ValueError("adjusted asset must retain the original expiry")
        previous_layout = json.loads(row["layout_json"])
        protected = {"route","source_ref","source_sha256","crop","subject_bbox","photo_bbox", "photo_pixels","crop_pixels",
            "background_color","text_color","panel_color","align","renderer_version","font_id","font_sha256","width","height",
            "runtime_version","design_model","qc_model","image_model","selected_source_ref","input_source_hashes"}
        if any(layout.get(key) != previous_layout.get(key) for key in protected):
            raise ValueError("free text export cannot replace the original photo or design")
        private_storage.lock_ready_media_refs(tx,user_id,[reference.id],now=clock)
        revision = expected_revision+1
        tx.execute("INSERT INTO cover_asset_revisions(job_id,revision,media_ref,layout_json,expires_at,created_at) VALUES(?,?,?,?,?,?)",
            (job_id,revision,reference.id,layout_json,row["expires_at"],clock.isoformat()))
        tx.execute("UPDATE cover_jobs SET final_media_ref=?,layout_json=?,asset_revision=?,updated_at=? WHERE id=?",
            (reference.id,layout_json,revision,clock.isoformat(),job_id))
        return _projection(tx.fetchone("SELECT * FROM cover_jobs WHERE id=?",(job_id,)),tx.fetchone("SELECT * FROM idempotency_requests WHERE id=?",(job_id,)))


def asset_reference(user_id,job_id,*,revision=None,base=False,now=None):
    row = db.fetchone("SELECT * FROM cover_jobs WHERE id=? AND user_id=?",(job_id,user_id))
    if not row or row["status"] != "completed" or not row["expires_at"] or row["expires_at"] <= _now(now).isoformat():
        raise HTTPException(404,"封面不存在或已到保存期限")
    if base:
        return row["base_media_ref"]
    if revision is None:
        return row["final_media_ref"]
    old = db.fetchone("SELECT media_ref FROM cover_asset_revisions WHERE job_id=? AND revision=?",(job_id,revision))
    if not old:
        raise HTTPException(404,"封面版本不存在")
    return old["media_ref"]


def _release_row(tx,row,*,now):
    financial = tx.fetchone("SELECT * FROM idempotency_requests WHERE id=?"+_lock(tx),(row["id"],))
    if financial["complete_applied"] or row["status"] == "completed":
        return False
    if financial["refund_applied"]:
        return False
    postdelivery._assert_usage_state(tx,dict(financial))
    postdelivery._release_row_in_transaction(tx,dict(financial))
    tx.execute("UPDATE cover_jobs SET lease_fence=lease_fence+1,lease_token_hash=NULL,lease_expires_at=NULL,updated_at=? WHERE id=?",(now,row["id"]))
    return True


def fail_job(claim,*,failure_code,outcome_unknown=False,now=None):
    if not isinstance(failure_code,str) or not failure_code or len(failure_code)>100:
        raise ValueError("fixed cover failure code required")
    clock = _now(now)
    with db.transaction(write=True) as tx:
        row = _owner_row(tx,claim,now=clock,allow_completed=True)
        if row["status"] == "completed":
            return False
        unresolved = tx.fetchone("SELECT id FROM public_trial_calls WHERE usage_record_id=? AND state IN ('dispatched','unknown') LIMIT 1",(row["usage_id"],))
        outcome_unknown = outcome_unknown or bool(unresolved)
        status = "outcome_unknown" if outcome_unknown else "failed"
        tx.execute("UPDATE cover_jobs SET status=?,stage=?,failure_code=?,unknown_at=?,updated_at=? WHERE id=?",
            (status,status,failure_code,clock.isoformat() if outcome_unknown else None,clock.isoformat(),row["id"]))
        tx.execute("UPDATE idempotency_requests SET failure_code=?,updated_at=? WHERE id=?",(failure_code,clock.isoformat(),row["id"]))
        if not outcome_unknown:
            _release_row(tx,dict(row),now=clock.isoformat())
        refresh_usage_in_transaction(tx,row["usage_id"])
        return True


def release_expired_unknowns(user_id=None,*,now=None):
    clock = _now(now).isoformat()
    parameters = (clock,user_id) if user_id is not None else (clock,)
    rows = db.fetchall("SELECT j.id,j.user_id FROM cover_jobs j JOIN idempotency_requests i ON i.id=j.id "
        "WHERE j.status IN ('queued','running','saving','outcome_unknown') AND j.deadline_at<=? "
        "AND i.refund_applied=0 AND i.complete_applied=0"+(" AND j.user_id=?" if user_id is not None else ""),parameters)
    released = 0
    for item in rows:
        with db.transaction(write=True) as tx:
            try:
                content_retention.assert_user_writable_with_storage(tx,item["user_id"])
            except ValueError:
                # Preserve this account's original hold/history for its deletion
                # reconciliation; do not write new business state against it.
                continue
            row = tx.fetchone("SELECT * FROM cover_jobs WHERE id=?"+_lock(tx),(item["id"],))
            if row["status"] == "completed" or row["deadline_at"]>clock:
                continue
            calls = tx.fetchall("SELECT id,state FROM public_trial_calls WHERE usage_record_id=?",(row["usage_id"],))
            unknown = bool(calls) or bool(json.loads(row["call_intents_json"])) or row["status"]=="outcome_unknown"
            status = "outcome_unknown" if unknown else "failed"
            tx.execute("UPDATE cover_jobs SET status=?,stage=?,failure_code=CASE WHEN failure_code='' THEN ? ELSE failure_code END,"
                "unknown_at=CASE WHEN ?=1 THEN COALESCE(unknown_at,?) ELSE unknown_at END,updated_at=? WHERE id=?",
                (status,status,"cover_deadline_unknown" if unknown else "cover_queue_expired",int(unknown),clock,clock,row["id"]))
            if _release_row(tx,dict(row),now=clock):
                released += 1
    return released


def recover_jobs(*,now=None):
    """Resume only original provider-free work; quarantine dispatched leftovers."""
    clock = _now(now)
    candidates = db.fetchall("SELECT id,user_id FROM cover_jobs WHERE status IN ('running','saving') AND lease_expires_at<=?",(clock.isoformat(),))
    resumable = []
    for item in candidates:
        with db.transaction(write=True) as tx:
            try:
                content_retention.assert_user_writable_with_storage(tx,item["user_id"])
            except ValueError:
                # Preserve this account's original hold/history for its deletion
                # reconciliation; do not write new business state against it.
                continue
            row = tx.fetchone("SELECT * FROM cover_jobs WHERE id=?"+_lock(tx),(item["id"],))
            if row["status"] not in {"running","saving"} or row["lease_expires_at"]>clock.isoformat():
                continue
            dispatched = bool(json.loads(row["call_intents_json"])) or tx.fetchone("SELECT id FROM public_trial_calls WHERE usage_record_id=? LIMIT 1",(row["usage_id"],))
            target = "outcome_unknown" if dispatched else "queued"
            tx.execute("UPDATE cover_jobs SET status=?,stage=?,lease_fence=lease_fence+1,lease_token_hash=NULL,lease_expires_at=NULL,"
                "unknown_at=?,failure_code=?,updated_at=? WHERE id=?",(target,target,clock.isoformat() if dispatched else None,
                "cover_worker_unknown" if dispatched else "",clock.isoformat(),row["id"]))
            if not dispatched and row["deadline_at"]>clock.isoformat():
                resumable.append(row["id"])
    release_expired_unknowns(now=clock)
    return resumable
