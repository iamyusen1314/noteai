"""Nonsecret, revisioned settings for the approved first cover release.

The feature starts disabled. An account evidence reference is a required
configuration record, never a substitute for the actual provider verification.
No read here calls a provider or installs schema.
"""
from __future__ import annotations

import copy
import os
from datetime import datetime, timezone

from fastapi import HTTPException

import admin_operations as operations
import ark_media
import cover_policy
import db


MODEL_ID = "doubao-seedream-5-0-pro-260628"
BUDGET_ID = "noteai-xhs-cover-20261019-acceptance"
BUDGET_MILLI_CNY = 100_000
FORMAL_BUDGET_ID = "noteai-cover-formal-v1"
MAX_ACCEPTANCE_JOBS = 6
MAX_ACCEPTANCE_CALLS = 18
RETENTION_SECONDS = 90 * 24 * 60 * 60
UNKNOWN_SECONDS = 30 * 60


def defaults():
    return {"enabled": False, "execution_scope": "acceptance", "account_verified": False, "account_evidence_ref": "",
            "model_id": MODEL_ID, "design_model": ark_media.MODEL,
            "width": 1776, "height": 2368, "credits": 8,
            "retention_seconds": RETENTION_SECONDS, "max_physical_calls": 3,
            "max_image_calls": 1, "text_max_tokens": 2048,
            "unknown_release_seconds": UNKNOWN_SECONDS}


def _key(scope):
    if scope not in {"production", "test"}:
        raise HTTPException(422, "封面配置范围无效")
    return "noteai_cover_config_v1" + ("_test" if scope == "test" else "")


def validate(config):
    base = defaults()
    if not isinstance(config, dict) or set(config) != set(base):
        raise HTTPException(422, "请完整提供首版封面配置")
    for key, expected in base.items():
        if key in {"enabled", "account_verified"}:
            if type(config[key]) is not bool:
                raise HTTPException(422, "封面启停与账号核验须为布尔值")
        elif key == "execution_scope":
            if not isinstance(config[key], str) or config[key] not in {"acceptance", "formal"}:
                raise HTTPException(422, "请选择验收或正式权益计量范围")
        elif key == "account_evidence_ref":
            value = config[key]
            if (not isinstance(value, str) or value != value.strip() or len(value) > 300
                    or any(ord(c) < 32 for c in value) or "?" in value or "Bearer " in value):
                raise HTTPException(422, "请只填写不含凭据的账号核验证据编号")
        elif type(config[key]) is not type(expected) or config[key] != expected:
            raise HTTPException(422, "本次首版型号、尺寸、积分和保存策略须遵循已确认方案")
    if config["enabled"] and (not config["account_verified"] or not config["account_evidence_ref"]):
        raise HTTPException(409, "启用前须记录固定型号的账号权限与价格核验证据")
    return copy.deepcopy(config)


def read(scope="production", tx=None):
    row = (tx or db).fetchone("SELECT value_json FROM system_settings WHERE key=? AND is_secret=0", (_key(scope),))
    if not row:
        return {"scope": scope, "revision": 0, "active_revision": 0,
                "active": defaults(), "draft": None, "previous": None, "source": "disabled_defaults"}
    import json
    try:
        state = json.loads(row["value_json"])
        validate(state["active"])
        if state.get("draft") is not None:
            validate(state["draft"])
        return state
    except (ValueError, TypeError, KeyError, HTTPException):
        raise HTTPException(503, "封面配置需要核实或恢复") from None


def view(scope="production"):
    state = read(scope)
    acceptance = state["active"]["execution_scope"] == "acceptance"
    return {**state, "instance_opt_in": os.environ.get("NOTEAI_COVER_WORKER_ENABLED") == "1",
            "credential_configured": ark_media.configured(),
            "budget": {"id": BUDGET_ID if acceptance else FORMAL_BUDGET_ID,
                       "scope": "acceptance" if acceptance else "formal",
                       "limit_cny": 100 if acceptance else None,
                       "max_jobs": MAX_ACCEPTANCE_JOBS if acceptance else None,
                       "max_calls": MAX_ACCEPTANCE_CALLS if acceptance else None,
                       "automatic_paid_retries": 0},
            "effect": "发布配置影响新封面任务；在途任务使用已冻结策略，关闭新提交后保留旧成品读取和免费排字。"}


def change(action, scope, *, actor, request_id, reason, expected, config=None):
    key = _key(scope)
    if action not in {"draft", "activate", "restore"}:
        raise HTTPException(422, "封面配置操作不存在")
    if action == "draft":
        config = validate(config)

    def update(tx):
        operations.locked(tx, key)
        reserved = tx.fetchone("SELECT is_secret FROM system_settings WHERE key=?", (key,))
        if reserved and reserved["is_secret"]:
            raise HTTPException(409, "封面配置键被保留，请由集成人员核实")
        before = read(scope, tx)
        if type(expected) is not int or before["revision"] != expected:
            raise HTTPException(409, "封面配置已变化，请重新读取")
        after = copy.deepcopy(before)
        after.update(revision=before["revision"] + 1, source="managed_database", actor=actor,
                     updated_at=datetime.now(timezone.utc).isoformat())
        if action == "draft":
            after["draft"] = config
        else:
            selected = before["draft"] if action == "activate" else before["previous"]
            if selected is None:
                raise HTTPException(409, "没有可发布或恢复的封面配置")
            after.update(active=validate(selected), previous=before["active"], draft=None,
                         active_revision=after["revision"])
        tx.execute("INSERT INTO system_settings(key,value_json,is_secret,updated_at) VALUES(?,?,0,?) "
                   "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at "
                   "WHERE system_settings.is_secret=0", (key, operations.encode(after), after["updated_at"]))
        return before, after

    return operations.execute(actor=actor, request_id=request_id, reason=reason, action="cover:" + action,
        target=scope, payload={"expected": expected, "config": config}, callback=update)


def policy_snapshot(config=None):
    """Freeze the approved route and a catalogue estimate, not an actual bill."""
    selected = validate(config or read()["active"])
    policy = {"enabled": selected["enabled"], "operation": "cover_generate", "provider": "seedream",
        "model_id": selected["model_id"], "width": selected["width"], "height": selected["height"],
        "credits": "8", "retention_seconds": RETENTION_SECONDS, "max_physical_calls": 3,
        "provider_budget": "100.00", "budget_currency": "CNY",
        "image_pricing": {"mode": "seedream_pro_pixel_tier", "currency": "CNY",
            "version": "ark-public-20261019-not-account-bill", "output_le_2610000": "0.30",
            "output_gt_2610000": "0.60", "extra_input": "0.02"}}
    cover_policy.validate_policy(policy, supported_models={"seedream": {MODEL_ID}})
    return {**policy, "execution_scope": selected["execution_scope"],
            "budget_id": BUDGET_ID if selected["execution_scope"] == "acceptance" else FORMAL_BUDGET_ID, "design_model": selected["design_model"],
            "text_max_tokens": selected["text_max_tokens"], "unknown_release_seconds": UNKNOWN_SECONDS,
            "price_status": "public_estimate", "account_evidence_ref": selected["account_evidence_ref"]}


def readiness():
    try:
        config = read()["active"]
        if not config["enabled"]:
            return False, "封面功能尚未开放"
        if os.environ.get("NOTEAI_COVER_WORKER_ENABLED") != "1":
            return False, "封面执行服务尚未启用"
        if not ark_media.configured():
            return False, "封面模型尚未配置"
        import private_storage
        if not private_storage.object_backend_configured():
            return False, "封面存储尚未就绪"
        budget_id = BUDGET_ID if config["execution_scope"] == "acceptance" else FORMAL_BUDGET_ID
        budget = db.fetchone("SELECT * FROM public_trial_budget WHERE id=?", (budget_id,))
        expected_limit = BUDGET_MILLI_CNY if config["execution_scope"] == "acceptance" else 0
        if (not budget or not budget["enabled"] or budget["limit_milli_cny"] != expected_limit
                or budget["policy_mode"] != "owner_metered"):
            return False, "封面独立费用记录尚未就绪"
        if config["execution_scope"] == "acceptance" and budget["reserved_milli_cny"] >= BUDGET_MILLI_CNY:
            return False, "本次封面验收预算已占用，请等待核对"
        db.fetchone("SELECT id FROM cover_jobs LIMIT 1")
        return True, ""
    except Exception:
        return False, "封面配置或存储状态需要核实"


def cost_view():
    """Content-free image totals, kept separate from the existing token audit."""
    try:
        with db.transaction(write=False) as tx:
            rows = tx.fetchall("SELECT provider,model_id,currency,price_version,width,height,"
                "COUNT(model_id) image_calls,SUM(input_images) input_images,SUM(output_images) output_images,"
                "SUM(COALESCE(billed_images,0)) known_billed_images,"
                "SUM(CASE WHEN billed_images IS NULL THEN 1 ELSE 0 END) quantity_unknown_calls,"
                "SUM(CASE WHEN actual_cost IS NULL THEN 1 ELSE 0 END) bill_unknown_calls,"
                "SUM(CASE WHEN state='unknown' THEN 1 ELSE 0 END) outcome_unknown_calls,"
                "SUM(CAST(estimated_cost AS NUMERIC)) estimated_cost,"
                "SUM(CASE WHEN actual_cost IS NOT NULL THEN CAST(actual_cost AS NUMERIC) ELSE 0 END) known_billed_cost "
                "FROM cover_image_usage GROUP BY provider,model_id,currency,price_version,width,height")
            states = tx.fetchall("SELECT status,COUNT(status) n FROM cover_jobs GROUP BY status")
        return {"status": "readable", "jobs": {r["status"]: r["n"] for r in states},
            "images": [{**dict(r), "estimated_cost": float(r["estimated_cost"] or 0),
                "known_billed_cost": float(r["known_billed_cost"] or 0),
                "actual_total_cost": None if r["bill_unknown_calls"] else float(r["known_billed_cost"] or 0)} for r in rows],
            "basis": "按张费用估算与供应商账单分开；设计和质检Token成本在原模型成本审计中。"}
    except Exception:
        return {"status": "unavailable", "jobs": None, "images": None,
                "basis": "封面计量表或读取权限未就绪；不能将未读取的用量或费用当作0。"}
