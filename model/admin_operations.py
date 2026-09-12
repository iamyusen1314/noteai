"""Bounded owner operations committed with their result and idempotency key.

This is the operational record for the existing Admin, not a provider dispatcher.
Callbacks may only perform database work inside the supplied transaction.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException

import db


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def locked(tx, name):
    if tx.postgres:
        tx.execute("SELECT pg_advisory_xact_lock(hashtext(?))", ("admin:" + name,))


def execute(*, actor, request_id, action, target, reason, payload, callback):
    try:
        if str(uuid.UUID(request_id)) != request_id:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, "需要有效的操作编号") from None
    reason = str(reason or "").strip()
    if not 3 <= len(reason) <= 300:
        raise HTTPException(422, "请填写 3–300 字的操作原因")
    binding = fingerprint({"actor": actor, "action": action, "target": target,
                           "reason": reason, "payload": payload})
    with db.transaction(write=True) as tx:
        locked(tx, "request:" + request_id)
        previous = tx.fetchone("SELECT binding_hash,result_json FROM admin_operations WHERE id=?", (request_id,))
        if previous:
            if previous["binding_hash"] != binding:
                raise HTTPException(409, "操作编号已用于其他参数；请重新预览")
            stored = json.loads(previous["result_json"])
            if not stored["ok"]:
                raise HTTPException(stored["error"]["status"], stored["error"]["detail"])
            return {**stored, "replayed": True}
        tx.execute("SAVEPOINT admin_change")
        try:
            before, after = callback(tx)
            result = {"ok": True, "request_id": request_id, "action": action,
                      "target": target, "before": before, "after": after, "replayed": False}
        except HTTPException as exc:
            tx.execute("ROLLBACK TO SAVEPOINT admin_change")
            result = {"ok": False, "request_id": request_id, "action": action, "target": target,
                      "error": {"status": exc.status_code, "detail": exc.detail}, "replayed": False}
        except Exception as exc:
            logging.warning("admin_operation_failed request_id=%s action=%s error_type=%s",
                            request_id, action, type(exc).__name__)
            raise
        tx.execute("RELEASE SAVEPOINT admin_change")
        tx.execute(
            "INSERT INTO admin_operations(id,actor,action,target,reason,binding_hash,"
            "result_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (request_id, actor, action, target, reason, binding, encode(result),
             datetime.now(timezone.utc).isoformat()),
        )
    if not result["ok"]:
        raise HTTPException(result["error"]["status"], result["error"]["detail"])
    return result


def check_expected(before, expected):
    if not expected or fingerprint(before) != expected:
        raise HTTPException(409, "对象已变化，请重新预览后确认")
