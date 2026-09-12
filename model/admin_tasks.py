"""Owner controls for original ordinary durable jobs, without dispatching them."""
from datetime import datetime, timedelta, timezone
import uuid

from fastapi import HTTPException

import admin_operations as operations
import db


def _clock(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("task clock has no timezone")
    return parsed.astimezone(timezone.utc)


def snapshot(tx, operation_id, *, lock=False):
    try:
        if str(uuid.UUID(operation_id)) != operation_id:
            raise ValueError()
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(422, "任务编号无效") from None
    if lock and tx.postgres:
        tx.execute("SELECT public.noteai_admin_lock_task(?)", (operation_id,))
    row = tx.fetchone(
        "SELECT o.id,o.operation_kind,o.status,o.provider_phase,o.operator_paused,o.admin_control_scope,"
        "o.priority,o.available_at,o.lease_fence,o.lease_expires_at,o.updated_at,o.provider_attempt_count,"
        "b.state AS outbox_state,b.attempt_count AS dispatch_attempts,b.lease_fence AS dispatch_fence,"
        "b.lease_expires_at AS dispatch_lease_expires_at,b.updated_at AS dispatch_updated_at,"
        "s.billing_state,s.result_ref_id,s.settled_at,i.status AS admission_state,i.refund_applied,i.complete_applied,"
        "CASE WHEN u.id IS NOT NULL AND u.deletion_requested_at IS NULL THEN 1 ELSE 0 END AS account_writable,"
        "r.state AS request_state,r.expires_at AS request_expires_at,"
        "CASE WHEN r.operation_id=o.id AND r.subject_hash=o.subject_hash AND r.purpose='request' THEN 1 ELSE 0 END AS request_matches,"
        "(SELECT COUNT(*) FROM ai_provider_attempts p WHERE p.operation_id=o.id) AS provider_attempt_rows "
        "FROM ai_operations o LEFT JOIN ai_operation_outbox b ON b.operation_id=o.id "
        "LEFT JOIN ai_operation_settlements s ON s.operation_id=o.id "
        "LEFT JOIN ai_operation_admissions a ON a.operation_id=o.id "
        "LEFT JOIN idempotency_requests i ON i.id=a.idempotency_request_id "
        "LEFT JOIN users u ON u.id=i.user_id LEFT JOIN ai_payload_refs r ON r.id=s.request_ref_id "
        "WHERE o.id=?", (operation_id,))
    if not row:
        raise HTTPException(404, "任务不存在")
    return dict(row)


def eligible(state, now=None):
    now = now or datetime.now(timezone.utc)
    if state["admin_control_scope"] != "ordinary":
        return [], "历史或验收任务受保护，不能通过普通任务管理重放"
    if state["status"] not in ("queued", "running") or state["provider_phase"] != "not_started" or state["provider_attempt_count"] or state["provider_attempt_rows"]:
        return [], "已完成、已发请求或结果未知；保留原结果，不提供盲目重试"
    if not (state["account_writable"] and state["billing_state"] == "charged" and not state["result_ref_id"] and not state["settled_at"]
            and state["admission_state"] == "running" and not state["refund_applied"] and not state["complete_applied"]):
        return [], "账户、计费或 admission 状态不支持继续执行"
    try:
        if not (state["request_matches"] and state["request_state"] == "ready" and _clock(state["request_expires_at"]) > now):
            return [], "原请求引用已失效或绑定不符；不能直接重试"
        lease = _clock(state["lease_expires_at"])
        if lease and lease > now:
            return [], "任务已有执行租约；等待原执行结果，不重复派发"
    except (TypeError, ValueError):
        return [], "原任务时钟不完整，须先核对"
    if state["status"] == "queued" and state["outbox_state"] in ("pending", "delivered"):
        return ["resume" if state["operator_paused"] else "pause", "schedule"], "暂停保留数据和原 UUID；已在途的通知可能完成，但 worker 不会认领暂停任务"
    if (state["status"] == "running" and not state["operator_paused"] and lease and lease <= now
            and state["outbox_state"] == "delivered" and state["dispatch_attempts"] < 20):
        return ["retry"], "仅恢复未发供应商请求的原任务通知；保留原 UUID、计费与次数，正常 worker 后续认领"
    return [], "当前状态没有可安全执行的普通管理动作"


def detail(operation_id):
    with db.transaction() as tx:
        state = snapshot(tx, operation_id)
    actions, notice = eligible(state)
    return {"task": state, "allowed_actions": actions, "notice": notice,
            "expected": operations.fingerprint(state)}


def list_tasks(limit=40):
    rows = db.fetchall("SELECT id,operation_kind,status,provider_phase,operator_paused,admin_control_scope,priority,available_at,lease_expires_at,provider_attempt_count,updated_at FROM ai_operations ORDER BY created_at DESC,id LIMIT ?", (min(100, max(1, limit)),))
    return {"available": True, "source": "ai_operations / outbox / settlements", "tasks": [dict(x) for x in rows],
            "notice": "仅普通 durable 业务任务可操作。Trends 行业采集及 Item34 观察不由此入口调度。"}


def change(operation_id, action, *, actor, request_id, reason, expected, priority=None, available_at=None):
    if action not in ("pause", "resume", "schedule", "retry"):
        raise HTTPException(422, "任务操作不存在")
    if action == "schedule":
        try:
            clock = _clock(available_at)
            if type(priority) is not int or not 0 <= priority <= 9 or clock is None:
                raise ValueError()
        except (TypeError, ValueError):
            raise HTTPException(422, "优先级须为 0–9；执行时间须在当前至 30 天内并带时区") from None
        available_at = clock.isoformat()
    def update(tx):
        before = snapshot(tx, operation_id, lock=True)
        operations.check_expected(before, expected)
        actions, notice = eligible(before)
        if action not in actions:
            raise HTTPException(409, notice)
        if action == "schedule":
            now = datetime.now(timezone.utc)
            if not now <= clock <= now + timedelta(days=30):
                raise HTTPException(422, "新的执行时间须在当前至 30 天内")
        stamp = datetime.now(timezone.utc).isoformat()
        if action in ("pause", "resume"):
            tx.execute("UPDATE ai_operations SET operator_paused=?,updated_at=? WHERE id=?", (int(action == "pause"), stamp, operation_id))
        elif action == "schedule":
            tx.execute("UPDATE ai_operations SET priority=?,available_at=?,updated_at=? WHERE id=?", (priority, available_at, stamp, operation_id))
            tx.execute("UPDATE ai_operation_outbox SET available_at=?,updated_at=? WHERE operation_id=?", (available_at, stamp, operation_id))
        else:
            tx.execute("UPDATE ai_operation_outbox SET state='pending',available_at=?,lease_owner_hash=NULL,lease_expires_at=NULL,delivered_at=NULL,updated_at=? WHERE operation_id=? AND state='delivered'", (stamp, stamp, operation_id))
        return before, snapshot(tx, operation_id)
    return operations.execute(actor=actor, request_id=request_id, action="task:" + action, target=operation_id,
        reason=reason, payload={"expected": expected, "priority": priority, "available_at": available_at}, callback=update)
