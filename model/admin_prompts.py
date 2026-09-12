"""Manage the real Prompt sources; draft writes never change runtime prompts."""
import json
from datetime import datetime, timezone

from fastapi import HTTPException

import admin_operations as operations
import db
import prompt_baselines


def catalog():
    baseline = prompt_baselines.load_current_baseline()
    rows = {row["key"]: dict(row) for row in db.fetchall("SELECT key,label,module,content,version,updated_at FROM managed_prompts")}
    result = []
    for key in sorted(set(rows) | set(baseline)):
        p = rows.get(key) or {**baseline[key], "version": 0, "updated_at": None}
        active = key in rows and bool(p["content"])
        source = "managed_database" if active else "empty_runtime_fallback" if key in rows else "baseline_not_published"
        result.append({**p, "key": key, "source": source,
                       "runtime_loaded": active, "editable": key in baseline,
                       "runtime_path": "API prompt_manager.get → prompt_composer → business request",
                       "baseline_id": prompt_baselines.BASELINE_ID})
    return result


def detail(key):
    p = next((x for x in catalog() if x["key"] == key), None)
    if p is None:
        raise HTTPException(404, "Prompt 不存在")
    row = db.fetchone("SELECT value_json FROM system_settings WHERE key=? AND is_secret=0", ("admin_prompt_draft:" + key,))
    history = [dict(x) for x in db.fetchall("SELECT version,content,saved_at FROM prompt_history WHERE prompt_key=? ORDER BY id DESC LIMIT 10", (key,))]
    return {**p, "draft": json.loads(row["value_json"]) if row else None, "history": history}


def draft(key, content, *, actor, request_id, reason, expected_version, expected_draft_id=None):
    if key not in prompt_baselines.PROMPT_KEYS or not isinstance(content, str) or not 1 <= len(content) <= 60000 or "\x00" in content:
        raise HTTPException(422, "仅可编辑现有 Prompt，正文须为 1–60000 字")
    def change(tx):
        operations.locked(tx, "prompt:" + key)
        row = tx.fetchone("SELECT version FROM managed_prompts WHERE key=?", (key,))
        version = row["version"] if row else 0
        if version != expected_version:
            raise HTTPException(409, "正式版本已变化，请重新加载")
        setting = "admin_prompt_draft:" + key
        old = tx.fetchone("SELECT value_json FROM system_settings WHERE key=? AND is_secret=0", (setting,))
        before = json.loads(old["value_json"]) if old else None
        if (before.get("draft_id") if before else None) != expected_draft_id:
            raise HTTPException(409, "草稿已被其他操作更新，请重新加载")
        after = {"content": content, "base_version": version, "actor": actor,
                 "saved_at": datetime.now(timezone.utc).isoformat(), "draft_id": request_id}
        tx.execute("INSERT INTO system_settings(key,value_json,is_secret,updated_at) VALUES(?,?,0,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at WHERE system_settings.is_secret=0",
                   (setting, operations.encode(after), after["saved_at"]))
        # Full Prompt text stays in the existing private config/history tables.
        return {"draft_id": before.get("draft_id") if before else None}, {"draft_id": request_id, "base_version": version, "published": False}
    return operations.execute(actor=actor, request_id=request_id, action="prompt:draft", target=key, reason=reason,
                              payload={"content_sha256": operations.fingerprint(content), "expected_version": expected_version, "expected_draft_id": expected_draft_id}, callback=change)


def publish(key, *, actor, request_id, reason, draft_id, expected_version, rollback_version=None):
    if key not in prompt_baselines.PROMPT_KEYS:
        raise HTTPException(422, "该 Prompt 不属于现有业务路径")
    def change(tx):
        operations.locked(tx, "prompt:" + key)
        suffix = " FOR UPDATE" if tx.postgres else ""
        old = tx.fetchone("SELECT key,label,module,content,version,updated_at FROM managed_prompts WHERE key=?" + suffix, (key,))
        old = dict(old) if old else None
        version = old["version"] if old else 0
        if version != expected_version:
            raise HTTPException(409, "正式版本已变化，请重新加载")
        if rollback_version is None:
            row = tx.fetchone("SELECT value_json FROM system_settings WHERE key=? AND is_secret=0", ("admin_prompt_draft:" + key,))
            d = json.loads(row["value_json"]) if row else {}
            if d.get("draft_id") != draft_id or d.get("base_version") != version:
                raise HTTPException(409, "草稿已变化，请重新加载并确认")
            content = d["content"]
        else:
            history = tx.fetchone("SELECT content FROM prompt_history WHERE prompt_key=? AND version=? ORDER BY id DESC LIMIT 1", (key, rollback_version))
            if not history:
                raise HTTPException(404, "历史修订不存在")
            content = history["content"]
        now = datetime.now(timezone.utc).isoformat()
        baseline = prompt_baselines.load_current_baseline()[key]
        if old:
            tx.execute("INSERT INTO prompt_history(prompt_key,version,content,saved_at) VALUES(?,?,?,?)", (key, version, old["content"], old["updated_at"]))
            tx.execute("UPDATE managed_prompts SET content=?,version=?,updated_at=? WHERE key=?", (content, version + 1, now, key))
        else:
            tx.execute("INSERT INTO managed_prompts(key,label,module,content,version,updated_at) VALUES(?,?,?,?,?,?)", (key, baseline["label"], baseline["module"], content, 1, now))
            # Revision zero records the original empty fallback. Restoration
            # keeps history and returns get(key, fallback) to that same behavior.
            tx.execute("INSERT INTO prompt_history(prompt_key,version,content,saved_at) VALUES(?,0,'',?)", (key, now))
        return {"version": version}, {"version": version + 1, "published": True, "content_sha256": prompt_baselines.content_sha256(content), "runtime_cache_seconds": 10}
    return operations.execute(actor=actor, request_id=request_id, action="prompt:publish" if rollback_version is None else "prompt:restore", target=key, reason=reason,
                              payload={"draft_id": draft_id, "expected_version": expected_version, "rollback_version": rollback_version}, callback=change)
