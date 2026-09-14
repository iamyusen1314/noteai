"""Merchant clarification within existing chat sessions and paid task claims.

Private material/results stay in chat storage. The payment ledger keeps only its
original identity and state. This is not a second task queue or a second charge.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import os
import re
import secrets
import sys
from datetime import timedelta

from fastapi import HTTPException

import billing
import content_retention
import db
import idempotency


execution = contextvars.ContextVar("merchant_clarification", default=None)
KEY = "task_continuation"

QUESTION_CONTRACT = """
【自然澄清，沿用本次商家信息】
先充分使用原文、完整素材观察和本次商家已回答的信息。仅当真实缺失或
冲突会影响关键文案时提出问题。保留原任务要求的XML输出结构，并在末尾始终
附加 <clarifications>JSON数组</clarifications>；无须提问时也必须写成
<clarifications>[]</clarifications>，不要把整份回复改成裸JSON。最多3问，每问结构：
{"field":"稳定的英文字段名","question":"指出具体不确定点的商家用语问题",
 "source_quote":"引发问题的原素材短句（必须原样引用）","object":"具体门店/套餐对象",
 "time_range":"原文明确的适用时间，未知留空","required":false,"options":["可选的简短回答"]}
已有答案、选择不写或暂不确定的同一问题不要重复询问。普通润色、程序解析
错误、外部查询失败和没有必要写入的细节不能交给用户排错。不要笼统索取价格、
地址等整套资料，不向用户说“事实校验失败/证据不足”。不能为了填满问题而提问。
未澄清的内容不要先写成事实。商家回答是本次确认，不是外部独立核验或永久记忆。
"""


class WaitingForInput(Exception):
    def __init__(self, event):
        self.event = event
        super().__init__("waiting_for_input")


def enabled():
    return os.environ.get("NOTEAI_TASK_CLARIFICATION_ENABLED") == "1"


def question_contract():
    return QUESTION_CONTRACT if execution.get() else ""


def questions_from_opinions(opinions, source, merchant="", answered=()):
    """Only source-anchored questions from the existing content expert call."""
    answered_ids = {item["question_id"] for item in answered}
    questions = []
    statuses = []
    for opinion in opinions:
        if opinion.get("role") != "内容专家":
            continue
        tag = re.search(r"<clarifications>\s*(.*?)\s*</clarifications>",
                        str(opinion.get("raw") or ""), re.S | re.I)
        try:
            payload = (tag.group(1) if tag else str(opinion.get("raw") or "")).strip()
            # Formatting wrappers are not a missing merchant fact.
            fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", payload, re.S | re.I)
            items = json.loads(fenced.group(1) if fenced else payload)
            if isinstance(items, dict) and set(items) in ({"questions"}, {"clarifications"}):
                items = next(iter(items.values()))
        except (ValueError, TypeError):
            statuses.append("invalid_question_json" if tag else "no_question_tag")
            continue  # Malformed model metadata must not invent a user question.
        if not isinstance(items, list):
            statuses.append("invalid_question_list")
            continue
        if not items:
            statuses.append("no_question_needed")
        for item in items[:3]:
            if not isinstance(item, dict):
                statuses.append("invalid_question_fields")
                continue
            field = item.get("field")
            quote = item.get("source_quote")
            question = item.get("question")
            obj = str(item.get("object") or "").strip()
            if (not isinstance(field, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", field)
                    or not isinstance(quote, str) or not 2 <= len(quote) <= 300 or quote not in source
                    or not isinstance(question, str) or not 4 <= len(question) <= 250
                    or any(term in question for term in ("事实校验", "证据不足", "HTTP", "解析失败"))
                    or (obj and obj not in source)):
                statuses.append("source_quote_mismatch" if isinstance(quote, str) and quote not in source
                                else "object_mismatch" if obj and obj not in source
                                else "invalid_question_fields")
                continue
            qid = hashlib.sha256((merchant + "\0" + obj + "\0" + field).encode()).hexdigest()[:24]
            if qid in answered_ids or any(q["question_id"] == qid for q in questions):
                statuses.append("already_answered_or_duplicate")
                continue
            time_range = str(item.get("time_range") or "").strip()
            if time_range and time_range not in source:
                time_range = ""
            options = item.get("options")
            if not isinstance(options, list):
                options = []
            questions.append({"question_id": qid, "field": field, "question": question,
                "source_quote": quote, "merchant": merchant, "object": obj,
                "time_range": time_range, "required": item.get("required") is True,
                "options": [v for v in options if isinstance(v, str) and 0 < len(v) <= 80][:3]})
    if execution.get():
        # Only fixed reason codes/counts; no question, quote, prompt or response text.
        print(json.dumps({"event_code": "clarification_parse", "phase": "existing_content_expert",
            "status": ",".join(sorted(set(statuses))) or ("questions_ready" if questions else "no_valid_question"),
            "item_count": len(questions)}),
            file=sys.stderr, flush=True)
    return questions[:3]


def _settled_calls(tx, usage_id):
    if tx.fetchone("SELECT id FROM public_trial_calls WHERE usage_record_id=? AND "
                   "(state IN ('dispatched','unknown') OR (state='responded' AND http_status=200 "
                   "AND model_usage_record_id IS NULL)) LIMIT 1", (usage_id,)):
        raise HTTPException(409, "原任务还有结果需要核实，暂未再次调用模型")


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _load(tx, user_id, session_id, lock=False):
    suffix = " FOR UPDATE" if lock and tx.postgres else ""
    row = tx.fetchone("SELECT * FROM chat_sessions WHERE id=? AND user_id=?" + suffix, (session_id, user_id))
    if not row:
        return None, None
    ctx = json.loads(row["generate_ctx_json"] or "{}")
    return dict(row), ctx.get(KEY)


def public_state(row, task):
    # Never expose prepared inputs, expert raw responses, leases or internal prompts.
    return {"type": "clarification_required", "session_id": row["id"],
        "operation": task["operation"], "status": task["status"], "version": task["version"],
        "domain": row["domain"], "questions": task["questions"], "answers": task.get("answers", []),
        "message": "素材和已完成的分析已保留。补充下面的信息后，我会接着完成这篇笔记。",
        "completed_steps": task.get("completed_steps", []), "result": task.get("result"),
        "pending_confirmation": pending_confirmation(task), "charged_again": False}


def pending_confirmation(task):
    latest = {a["question_id"]: a for a in task.get("answers", [])}
    return [q["question"] for q in task["questions"] if q["required"]
            and latest.get(q["question_id"], {}).get("status") in {None, "unknown"}]


def read(user_id, session_id):
    with db.transaction(write=False) as tx:
        row, task = _load(tx, user_id, session_id)
        if not task:
            raise HTTPException(404, "任务不存在或不属于当前账号")
        if row.get("note_id") and content_retention.status("note", row["note_id"], user_id, tx)["state"] != "active":
            raise HTTPException(404, "原笔记已删除或已到保存期限")
        claim = tx.fetchone("SELECT status FROM idempotency_requests WHERE id=? AND user_id=?", (session_id, user_id))
        if not claim:
            raise HTTPException(409, "原任务记录需要核实")
        task["status"] = claim["status"]
        return public_state(row, task)


def pause(prepared, opinions, *, source, merchant="", completed_steps=()):
    context = execution.get()
    if not context:
        return
    claim = context["claim"]
    questions = questions_from_opinions(opinions, source, merchant)
    if not questions:
        return
    task = {"schema": 1, "operation": claim["operation"], "status": "waiting_for_input",
            "version": 1, "prepared": prepared, "questions": questions, "answers": [],
            "completed_steps": list(completed_steps)}
    encoded = _json({KEY: task})
    if len(encoded.encode()) > 2_000_000:
        raise HTTPException(422, "本次素材分析过长，无法安全保存接续内容")
    now = idempotency._iso()
    with db.transaction(write=True) as tx:
        content_retention.assert_user_writable_with_storage(tx, claim["user_id"])
        row = idempotency._owned_row(tx, claim)
        if (not row or row["user_id"] != claim["user_id"] or row["status"] != "running"
                or row["lease_token_hash"] != idempotency._sha256(claim["lease_token"])
                or row["usage_id"] != claim["charge"]["usage_id"]
                or row["refund_applied"] or row["complete_applied"]):
            raise HTTPException(409, "原任务状态已更新，请读取原任务")
        _settled_calls(tx, row["usage_id"])
        # Same server-generated UUID; no client-selected link or unchecked upsert.
        tx.execute("INSERT INTO chat_sessions(id,user_id,domain,local_time,messages_json,user_prefs_json,"
                   "iteration_count,generate_ctx_json,created_at,updated_at) VALUES(?,?,?,?,?,?,0,?,?,?)",
                   (row["id"], row["user_id"], prepared["domain"], prepared.get("local_time", ""),
                    "[]", "{}", encoded, now, now))
        tx.execute("UPDATE idempotency_requests SET status='waiting_for_input',updated_at=? WHERE id=?", (now, row["id"]))
    raise WaitingForInput(public_state({"id": claim["request_id"], "domain": prepared["domain"]}, task))


def _answer_update(task, answers):
    if not isinstance(answers, list) or not 1 <= len(answers) <= 3:
        raise HTTPException(422, "请回答问题，或选择暂不确定、不写这项")
    questions = {q["question_id"]: q for q in task["questions"]}
    updated, seen = [], set()
    for answer in answers:
        if not isinstance(answer, dict):
            raise HTTPException(422, "回答格式不正确，请在原问题中填写")
        qid, status = answer.get("question_id"), answer.get("status")
        if qid not in questions or qid in seen or status not in {"confirmed", "omitted", "unknown"}:
            raise HTTPException(422, "回答与当前问题不匹配，请读取原任务")
        seen.add(qid)
        value = str(answer.get("answer") or "").strip()
        if len(value) > 4000 or (status == "confirmed" and not value):
            raise HTTPException(422, "请填写完整回答（最多4000字），也可以选择不写")
        q = questions[qid]
        updated.append({"question_id": qid, "status": status,
            "field": q["field"], "question": q["question"],
            "answer": value if status == "confirmed" else "", "source": "merchant_confirmation",
            "merchant": q["merchant"], "object": q["object"], "time_range": q["time_range"],
            "confirmed_at": idempotency._iso(), "revision": task["version"] + 1})
    effective = {a["question_id"] for a in task.get("answers", [])} | seen
    if effective != set(questions):
        raise HTTPException(422, "还有问题未处理；可以选择暂不确定或不写这项")
    return updated


def resume(user_id, session_id, version, answers):
    """One answer batch owns the original task. No new credit/usage allocation."""
    token = secrets.token_urlsafe(32)
    with db.transaction(write=True) as tx:
        content_retention.assert_user_writable_with_storage(tx, user_id)
        current = tx.fetchone("SELECT * FROM idempotency_requests WHERE id=? AND user_id=?"
                             + (" FOR UPDATE" if tx.postgres else ""), (session_id, user_id))
        row, task = _load(tx, user_id, session_id, lock=True)
        if not current or not task:
            raise HTTPException(404, "任务不存在或不属于当前账号")
        if current["status"] != "waiting_for_input" or task["version"] != version:
            raise HTTPException(409, "回答或任务状态已更新，请先读取原任务；无需再次提交")
        _settled_calls(tx, current["usage_id"])
        task["answers"].extend(_answer_update(task, answers))
        task["version"] += 1
        task["status"] = "running"
        task["answer_hash"] = idempotency.payload_hash(answers)
        now = idempotency._now()
        tx.execute("UPDATE chat_sessions SET generate_ctx_json=?,updated_at=? WHERE id=? AND user_id=?",
                   (_json({KEY: task}), idempotency._iso(now), session_id, user_id))
        tx.execute("UPDATE idempotency_requests SET status='running',lease_token_hash=?,lease_expires_at=?,updated_at=? WHERE id=?",
                   (idempotency._sha256(token), idempotency._iso(now + timedelta(minutes=30)), idempotency._iso(now), session_id))
    charge = {"usage_id": current["usage_id"], "subscription_id": current["charged_subscription_id"],
              "subscription_period_start": current["charged_period_start"], "source": current["charge_source"],
              **{k: current[k] for k in ("credits_used", "monthly_credits_used", "wallet_credits_used")}}
    billing.activate_usage(current["usage_id"])
    claim = {"state": "owner", "request_id": session_id, "lease_token": token, "charge": charge,
             **{k: current[k] for k in ("user_id", "operation", "key_hash", "payload_hash")}}
    return claim, task


def answer_context(task):
    latest = {a["question_id"]: a for a in task["answers"]}
    lines = ["【本次商家确认；仅适用于本任务，不是外部独立核验或长期偏好】",
             "本段对相同对象的旧口径有优先权；旧专家草稿是待修正建议，不是事实。"]
    for q in task["questions"]:
        a = latest.get(q["question_id"])
        if not a:
            continue
        scope = f"门店：{a['merchant'] or '本任务对象'}；套餐/对象：{a['object'] or '本次内容'}；时间：{a['time_range'] or '仅本次，未声明长期有效'}"
        action = a["answer"] if a["status"] == "confirmed" else (
            "用户选择不写此项；所有标题、方案及后续优化都不得写入此项，也不能换种说法暗示。"
            if a["status"] == "omitted" else "用户暂不确定；不再重复问，本次不写成事实。核心卖点相关部分待确认，其余继续完成。")
        lines.append(f"- {scope}\n问题：{q['question']}\n当前回答：{action}")
    return "\n".join(lines)


def save_result(claim, result):
    """Persist the resumed result before announcing completion; CAS old leases out."""
    with db.transaction(write=True) as tx:
        content_retention.assert_user_writable_with_storage(tx, claim["user_id"])
        current = idempotency._owned_row(tx, claim)
        row, task = _load(tx, claim["user_id"], claim["request_id"], lock=True)
        if not task or not current or current["status"] != "running" or current["lease_token_hash"] != idempotency._sha256(claim["lease_token"]):
            raise HTTPException(409, "任务结果状态需要核实")
        _settled_calls(tx, current["usage_id"])
        now = idempotency._iso()
        if task["operation"] == "generate":
            title, body = result.get("note_title"), result.get("note_body")
            if not title or not body or result.get("quality_failed"):
                raise HTTPException(422, "接续结果还未完成，不能保存为空笔记")
            tx.execute("INSERT INTO notes(id,user_id,title,body,domain,score,grade,source,version,created_at) "
                       "VALUES(?,?,?,?,?,?,?,'generate',1,?)", (row["id"], claim["user_id"], title, body,
                        row["domain"], result.get("ces_percentile"), result.get("grade", ""), now))
            content_retention._record_content_with_storage(tx, "note", row["id"], claim["user_id"], created_at=now)
            result.update({"saved_note_id": row["id"], "saved_note_version": 1})
        task["result"] = result
        task["status"] = "completed"
        saved_note_id = result.get("saved_note_id")
        if not saved_note_id or not tx.fetchone("SELECT id FROM notes WHERE id=? AND user_id=?", (saved_note_id, claim["user_id"])):
            raise HTTPException(409, "原笔记保存状态需要核实")
        tx.execute("UPDATE chat_sessions SET note_id=?,generate_ctx_json=?,updated_at=? WHERE id=? AND user_id=?",
                   (saved_note_id, _json({KEY: task}), now, row["id"], claim["user_id"]))
        tx.execute("UPDATE idempotency_requests SET status='completed',complete_applied=1,completed_at=?,updated_at=? WHERE id=?",
                   (now, now, row["id"]))
