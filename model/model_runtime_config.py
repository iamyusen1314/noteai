"""Nonsecret configuration for the existing formal Claude and Kimi routes.

The API opts in per instance. Tracking's frozen runtime never opts in. Reads do
not call a provider; each opted-in dispatch reads the active database revision.
"""
import copy
import json
import os
from datetime import datetime, timezone

from fastapi import HTTPException

import admin_operations as operations
import db

TASKS = ("diagnosis", "content_gen", "arbitrate", "chat", "semantic")
MODEL = "kimi-k2.6"
HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-6"
MODELS = (MODEL, HAIKU, SONNET)
MODEL_LIMITS = {MODEL: {"min": 256, "max": 32768},
                HAIKU: {"min": 1025, "max": 16000},
                SONNET: {"min": 1025, "max": 16000}}


def defaults():
    return {task: {"model": SONNET if task in ("arbitrate", "chat") else HAIKU,
                   "enabled": True, "max_tokens": 16000} for task in TASKS}


def _key(scope):
    if scope not in ("production", "test"):
        raise HTTPException(422, "配置范围仅支持 production 或 test")
    return "admin_model_config" + ("_test" if scope == "test" else "")


def validate(config, *, existing=False):
    if not isinstance(config, dict) or set(config) != set(TASKS):
        raise HTTPException(422, "需完整提供现有五类业务路由")
    result = {}
    for task, value in config.items():
        if not isinstance(value, dict) or set(value) != {"model", "enabled", "max_tokens"}:
            raise HTTPException(422, "配置只能包含模型、启停与输出上限")
        if value["model"] not in MODELS or type(value["enabled"]) is not bool:
            raise HTTPException(422, "请选择已接入的 Claude Haiku、Claude Sonnet 或 Kimi K2.6")
        if type(value["max_tokens"]) is not int or not 256 <= value["max_tokens"] <= 32768:
            raise HTTPException(422, "输出上限须为 256–32768 的整数；实际请求还受对应业务和模型参数约束")
        limits = MODEL_LIMITS[value["model"]]
        if not existing and not limits["min"] <= value["max_tokens"] <= limits["max"]:
            raise HTTPException(422, f"{value['model']} 配置上限须为 {limits['min']}–{limits['max']}；Claude 须兼容思考步骤与现有 Gateway 上限")
        result[task] = dict(value)
    return result


def read(scope="production", tx=None):
    key = _key(scope)
    row = (tx.fetchone if tx else db.fetchone)("SELECT value_json FROM system_settings WHERE key=? AND is_secret=0", (key,))
    if not row:
        return {"revision": 0, "active_revision": 0, "active": defaults(), "draft": None,
                "previous": None, "scope": scope, "source": "existing_runtime_defaults"}
    try:
        result = json.loads(row["value_json"])
        validate(result["active"], existing=True)
        return result
    except (KeyError, TypeError, ValueError, HTTPException):
        raise HTTPException(503, "模型配置无效，需核对或恢复上一版本") from None


def view(scope="production"):
    state = read(scope)
    return {**state, "allowed_models": list(MODELS), "model_limits": copy.deepcopy(MODEL_LIMITS), "tasks": list(TASKS),
            "load_path": "API model_router → model_runtime_config.resolve → Claude Gateway / Kimi transport → usage ledger",
            "effect": "保存仅更新草稿；发布后此实例下一次模型请求读取，已在途请求使用原配置。test 不进入生产路由。",
            "instance_opt_in": os.environ.get("NOTEAI_MODEL_CONFIG_ENABLED") == "1"}


def change(action, scope, *, actor, request_id, reason, expected, config=None):
    key = _key(scope)
    if action not in ("draft", "activate", "restore"):
        raise HTTPException(422, "模型操作不存在")
    if action == "draft":
        config = validate(config)
    def update(tx):
        operations.locked(tx, key)
        before = read(scope, tx)
        if type(expected) is not int or before["revision"] != expected:
            raise HTTPException(409, "配置已变化，请重新加载并确认")
        after = copy.deepcopy(before)
        after.update(revision=before["revision"] + 1, source="managed_database",
                     updated_at=datetime.now(timezone.utc).isoformat(), actor=actor)
        if action == "draft":
            after["draft"] = config
        else:
            selected = before["draft"] if action == "activate" else before["previous"]
            if selected is None:
                raise HTTPException(409, "没有可发布草稿" if action == "activate" else "没有可恢复配置")
            after.update(active=validate(selected), previous=before["active"], draft=None,
                         active_revision=after["revision"])
        tx.execute("INSERT INTO system_settings(key,value_json,is_secret,updated_at) VALUES(?,?,0,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at WHERE system_settings.is_secret=0",
                   (key, operations.encode(after), after["updated_at"]))
        return before, after
    return operations.execute(actor=actor, request_id=request_id, action="model:" + action,
                              target=scope, reason=reason, payload={"expected": expected, "config": config}, callback=update)


def resolve(task, model, max_tokens, *, scope="production"):
    if os.environ.get("NOTEAI_MODEL_CONFIG_ENABLED") != "1":
        return model, max_tokens
    import public_product
    context = public_product._invocation.get()
    try:
        state = context.model_config if scope == "production" and context and context.model_config else read(scope)
    except HTTPException:
        if public_product.enabled():
            raise public_product.TrialProviderStopped("PUBLIC_MODEL_CONFIG_INVALID") from None
        raise
    config = state["active"][task if task in TASKS else "semantic"]
    if not config["enabled"]:
        if public_product.enabled():
            raise public_product.TrialProviderStopped("PUBLIC_MODEL_ROUTE_PAUSED")
        raise HTTPException(503, "此业务模型路由已由管理员暂停")
    return config["model"], min(max_tokens, config["max_tokens"])
