"""
NoteAI Pro 后台管理服务器 — port 8001
完全独立于用户端 api.py（port 8000），共享数据库。

启动方式：
  python -m uvicorn admin_server:admin_app --host 127.0.0.1 --port 8001 --reload

功能模块：
  P1-B  管理员认证
  P2-A  Dashboard + 用户管理
  P2-B  URL 追踪管理
  P3    收入 & 用量统计
  P4    Prompt 管理
  P5    大模型管理
  P6    爬虫管理
"""

import os
import sys
import json
import uuid
import time
import asyncio
import subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# 共享模块
import db
import admin_auth as _aauth
import billing as _billing

# ── App ───────────────────────────────────────────────────────────────────
admin_app = FastAPI(
    title="NoteAI Pro 后台管理",
    description="运营管理 API — 需要管理员认证",
    version="1.0.0",
)

admin_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件（admin.html）
_STATIC_DIR = Path(__file__).parent
if (_STATIC_DIR / "admin.html").exists():
    @admin_app.get("/", response_class=HTMLResponse)
    async def admin_root():
        return HTMLResponse((_STATIC_DIR / "admin.html").read_text(encoding="utf-8"))


# ══════════════════════════════════════════════════════════════════════════
# 认证端点
# ══════════════════════════════════════════════════════════════════════════

class AdminLoginInput(BaseModel):
    username: str
    password: str

@admin_app.post("/admin/login")
async def admin_login(req: AdminLoginInput):
    token = _aauth.admin_login(req.username, req.password)
    return {"token": token, "username": req.username}

@admin_app.post("/admin/logout")
async def admin_logout_ep(admin: dict = Depends(_aauth.get_admin_user)):
    _aauth.admin_logout(admin["token"])
    return {"ok": True}

@admin_app.get("/admin/me")
async def admin_me(admin: dict = Depends(_aauth.get_admin_user)):
    return {"username": admin["username"], "logged_in_at": admin["created_at"]}


# ══════════════════════════════════════════════════════════════════════════
# P2-A Dashboard 总览
# ══════════════════════════════════════════════════════════════════════════

@admin_app.get("/admin/overview")
async def admin_overview(admin: dict = Depends(_aauth.get_admin_user)):
    """一次性返回 Dashboard 所需所有数据。"""
    now    = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    days7_start = (now - timedelta(days=7)).isoformat()

    # ── 用户规模 ──
    total_users  = db.fetchone("SELECT COUNT(*) as c FROM users")["c"]
    today_new    = db.fetchone("SELECT COUNT(*) as c FROM users WHERE created_at>=?", (today_start,))["c"]
    active_7d    = db.fetchone(
        "SELECT COUNT(DISTINCT user_id) as c FROM usage_records WHERE recorded_at>=?",
        (days7_start,))["c"]
    active_month = db.fetchone(
        "SELECT COUNT(DISTINCT user_id) as c FROM usage_records WHERE recorded_at>=?",
        (month_start,))["c"]

    # ── 套餐分布 ──
    tier_rows = db.fetchall(
        "SELECT tier, COUNT(*) as cnt FROM subscriptions WHERE is_active=1 GROUP BY tier")
    tier_dist = {r["tier"]: r["cnt"] for r in tier_rows}

    # ── 本月收入（模拟：订阅 × 单价）──
    pro_count      = tier_dist.get("pro", 0)
    pro_plus_count = tier_dist.get("pro_plus", 0)
    sub_revenue    = pro_count * 99 + pro_plus_count * 199

    # ── 积分充值收入（credit_transactions topup 本月）──
    topup_row = db.fetchone(
        "SELECT COALESCE(SUM(amount),0) as total FROM credit_transactions "
        "WHERE type='topup' AND recorded_at>=?", (month_start,))
    credits_revenue = round((topup_row["total"] or 0) * _billing.CREDIT_VALUE, 2)

    total_revenue = round(sub_revenue + credits_revenue, 2)

    # ── 本月 API 成本 ──
    cost_row = db.fetchone(
        "SELECT COALESCE(SUM(cost_rmb),0) as total FROM usage_records WHERE recorded_at>=?",
        (month_start,))
    api_cost = round(cost_row["total"] or 0, 4)

    gross_profit = round(total_revenue - api_cost, 2)
    margin_pct   = round(gross_profit / total_revenue * 100, 1) if total_revenue > 0 else 0

    # ── MRR ──
    mrr = pro_count * 99 + pro_plus_count * 199

    # ── 本月各操作用量 ──
    op_rows = db.fetchall(
        "SELECT operation, COUNT(*) as cnt, SUM(cost_rmb) as cost "
        "FROM usage_records WHERE recorded_at>=? GROUP BY operation ORDER BY cost DESC",
        (month_start,))
    ops_summary = [{"op": r["operation"],
                    "label": _billing.OPERATIONS.get(r["operation"], {}).get("label", r["operation"]),
                    "count": r["cnt"],
                    "cost": round(r["cost"] or 0, 4)} for r in op_rows]

    # ── 系统状态 ──
    kimi_key   = os.environ.get("MOONSHOT_API_KEY", "")
    claude_key = os.environ.get("ANTHROPIC_API_KEY", "")
    model_path = Path(__file__).parent / "artifacts" / "model_a_v0.3.lgb"
    db_path    = Path(__file__).parent / "data" / "noteai.db"

    return {
        "users": {
            "total": total_users,
            "today_new": today_new,
            "active_7d": active_7d,
            "active_month": active_month,
            "tier_distribution": tier_dist,
        },
        "finance": {
            "sub_revenue":     sub_revenue,
            "credits_revenue": credits_revenue,
            "total_revenue":   total_revenue,
            "api_cost":        api_cost,
            "gross_profit":    gross_profit,
            "margin_pct":      margin_pct,
            "mrr":             mrr,
        },
        "usage": {
            "month_total_cost": api_cost,
            "by_operation":     ops_summary,
        },
        "system": {
            "kimi_configured":   bool(kimi_key),
            "kimi_key_prefix":   kimi_key[:12] + "…" if kimi_key else "",
            "claude_configured": bool(claude_key),
            "claude_key_prefix": claude_key[:15] + "…" if claude_key else "",
            "model_exists":      model_path.exists(),
            "model_size_mb":     round(model_path.stat().st_size / 1024**2, 2) if model_path.exists() else 0,
            "db_size_mb":        round(db_path.stat().st_size / 1024**2, 2) if db_path.exists() else 0,
            "server_time":       now.isoformat(),
        },
    }


# ══════════════════════════════════════════════════════════════════════════
# P2-A 用户管理
# ══════════════════════════════════════════════════════════════════════════

@admin_app.get("/admin/users")
async def admin_users(
    page: int = 1, page_size: int = 20,
    search: str = "", tier: str = "",
    admin: dict = Depends(_aauth.get_admin_user)
):
    """用户列表（分页+搜索+套餐筛选）。"""
    offset = (page - 1) * page_size
    where_clauses, params = [], []

    if search:
        where_clauses.append("(u.username LIKE ? OR u.email LIKE ? OR u.phone LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like])
    if tier:
        where_clauses.append("s.tier=?")
        params.append(tier)

    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    total = db.fetchone(
        f"SELECT COUNT(*) as c FROM users u "
        f"LEFT JOIN subscriptions s ON u.id=s.user_id AND s.is_active=1 {where_sql}",
        tuple(params)
    )["c"]

    rows = db.fetchall(
        f"""SELECT u.id, u.username, u.email, u.phone, u.nickname,
                   u.avatar_emoji, u.created_at, u.last_login,
                   COALESCE(s.tier,'free') as tier,
                   COALESCE(s.expires_at,'') as expires_at,
                   COALESCE(cr.balance,0) as credits
            FROM users u
            LEFT JOIN subscriptions s ON u.id=s.user_id AND s.is_active=1
            LEFT JOIN credits cr ON u.id=cr.user_id
            {where_sql}
            ORDER BY u.created_at DESC
            LIMIT ? OFFSET ?""",
        tuple(params) + (page_size, offset)
    )

    # 本月用量次数
    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    users_out = []
    for r in rows:
        usage = db.fetchone(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(cost_rmb),0) as cost "
            "FROM usage_records WHERE user_id=? AND recorded_at>=?",
            (r["id"], month_start))
        users_out.append({
            **dict(r),
            "phone_masked": _mask_phone_admin(r["phone"] or ""),
            "month_ops":    usage["cnt"],
            "month_cost":   round(usage["cost"] or 0, 4),
        })

    return {"total": total, "page": page, "page_size": page_size, "users": users_out}


def _mask_phone_admin(phone: str) -> str:
    raw = phone.replace("+86", "")
    return raw[:3] + "****" + raw[-4:] if len(raw) == 11 else phone


@admin_app.get("/admin/users/{user_id}")
async def admin_user_detail(user_id: str, admin: dict = Depends(_aauth.get_admin_user)):
    """用户详情（不含笔记全文）。"""
    user = db.fetchone("SELECT * FROM users WHERE id=?", (user_id,))
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user = dict(user)
    user.pop("password_hash", None)
    user.pop("password_salt", None)
    user.pop("avatar_data", None)  # 不传图片数据

    sub = db.fetchone(
        "SELECT * FROM subscriptions WHERE user_id=? AND is_active=1", (user_id,))
    credits_row = db.fetchone("SELECT * FROM credits WHERE user_id=?", (user_id,))

    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    usage_rows = db.fetchall(
        "SELECT operation, COUNT(*) as cnt, SUM(cost_rmb) as cost, SUM(credits_used) as creds "
        "FROM usage_records WHERE user_id=? AND recorded_at>=? GROUP BY operation",
        (user_id, month_start))

    recent_usage = db.fetchall(
        "SELECT operation,source,cost_rmb,credits_used,recorded_at "
        "FROM usage_records WHERE user_id=? ORDER BY recorded_at DESC LIMIT 20",
        (user_id,))

    credit_txns = db.fetchall(
        "SELECT type,amount,balance_after,description,recorded_at "
        "FROM credit_transactions WHERE user_id=? ORDER BY recorded_at DESC LIMIT 20",
        (user_id,))

    # 笔记统计（不含全文）
    notes_stat = db.fetchone(
        "SELECT COUNT(*) as cnt, AVG(score) as avg_score, MAX(score) as max_score "
        "FROM notes WHERE user_id=?", (user_id,))

    return {
        "user":          {**user, "phone_masked": _mask_phone_admin(user.get("phone") or "")},
        "subscription":  dict(sub) if sub else {"tier": "free"},
        "credits":       dict(credits_row) if credits_row else {"balance": 0},
        "month_usage":   [dict(r) for r in usage_rows],
        "recent_usage":  [dict(r) for r in recent_usage],
        "credit_txns":   [dict(r) for r in credit_txns],
        "notes_stat":    dict(notes_stat) if notes_stat else {},
    }


class UserAdjustInput(BaseModel):
    action: str           # 'add_credits' | 'set_tier' | 'disable' | 'enable' | 'reset_quota'
    value:  Optional[str] = None   # tier name 或 credits 数量
    note:   str = ""

@admin_app.post("/admin/users/{user_id}/adjust")
async def admin_user_adjust(
    user_id: str, req: UserAdjustInput,
    admin: dict = Depends(_aauth.get_admin_user)
):
    user = db.fetchone("SELECT id,username FROM users WHERE id=?", (user_id,))
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if req.action == "add_credits":
        amount = float(req.value or "0")
        if amount <= 0:
            raise HTTPException(status_code=400, detail="积分数量必须大于0")
        new_bal = _billing.topup_credits(user_id, amount, f"管理员手动增加：{req.note}")
        return {"ok": True, "new_balance": new_bal}

    if req.action == "set_tier":
        tier = req.value
        if tier not in _billing.TIERS:
            raise HTTPException(status_code=400, detail=f"无效套餐: {tier}")
        _billing.upgrade_subscription(user_id, tier)
        return {"ok": True, "tier": tier}

    if req.action == "reset_quota":
        db.execute(
            "UPDATE subscriptions SET used_analyze=0,used_generate=0,"
            "used_chat_rewrite=0,used_screenshot=0 WHERE user_id=? AND is_active=1",
            (user_id,))
        return {"ok": True, "message": "配额已重置"}

    if req.action in ("disable", "enable"):
        # 简单实现：禁用用户会话
        if req.action == "disable":
            db.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))
            db.execute("UPDATE users SET last_login=? WHERE id=?",
                       (f"DISABLED:{datetime.now(timezone.utc).isoformat()}", user_id))
        return {"ok": True, "action": req.action}

    raise HTTPException(status_code=400, detail=f"未知操作: {req.action}")


# ══════════════════════════════════════════════════════════════════════════
# P2-B URL 追踪管理
# ══════════════════════════════════════════════════════════════════════════

@admin_app.get("/admin/tracked-notes")
async def admin_tracked_notes(
    status: str = "", page: int = 1, page_size: int = 20,
    admin: dict = Depends(_aauth.get_admin_user)
):
    """管理所有用户的追踪笔记。"""
    where = "WHERE status=?" if status else ""
    params = (status,) if status else ()
    total = db.fetchone(f"SELECT COUNT(*) as c FROM tracked_notes {where}", params)["c"]
    offset = (page - 1) * page_size
    rows = db.fetchall(
        f"SELECT t.*,u.username FROM tracked_notes t "
        f"JOIN users u ON t.user_id=u.id {where} "
        f"ORDER BY t.submitted_at DESC LIMIT ? OFFSET ?",
        params + (page_size, offset))
    return {"total": total, "notes": [dict(r) for r in rows]}


@admin_app.post("/admin/tracked-notes/{note_id}/trigger-check")
async def admin_trigger_check(note_id: str, admin: dict = Depends(_aauth.get_admin_user)):
    """手动触发某条追踪笔记的采集。"""
    note = db.fetchone("SELECT * FROM tracked_notes WHERE id=?", (note_id,))
    if not note:
        raise HTTPException(status_code=404, detail="追踪记录不存在")
    db.execute("UPDATE tracked_notes SET status='checking_24h' WHERE id=?", (note_id,))
    return {"ok": True, "message": "已加入采集队列"}


# ══════════════════════════════════════════════════════════════════════════
# P3 收入 & 用量统计
# ══════════════════════════════════════════════════════════════════════════

@admin_app.get("/admin/revenue")
async def admin_revenue(days: int = 30, admin: dict = Depends(_aauth.get_admin_user)):
    """收入统计（从今日起，订阅+积分）。"""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # 套餐人数 → 估算订阅收入
    tier_rows = db.fetchall(
        "SELECT tier, COUNT(*) as cnt FROM subscriptions WHERE is_active=1 GROUP BY tier")
    tier_dist = {r["tier"]: r["cnt"] for r in tier_rows}
    prices = {"pro": 99, "pro_plus": 199, "free": 0}
    sub_revenue_est = sum(tier_dist.get(t, 0) * prices.get(t, 0) for t in prices)

    # 积分充值实际收入
    topup_rows = db.fetchall(
        "SELECT DATE(recorded_at) as day, SUM(amount) as credits_sum "
        "FROM credit_transactions WHERE type='topup' AND recorded_at>=? GROUP BY day ORDER BY day",
        (since,))

    # 积分消费量（每日）
    usage_cost_rows = db.fetchall(
        "SELECT DATE(recorded_at) as day, SUM(cost_rmb) as api_cost "
        "FROM usage_records WHERE recorded_at>=? GROUP BY day ORDER BY day",
        (since,))

    return {
        "tier_distribution": tier_dist,
        "sub_revenue_estimate": sub_revenue_est,
        "daily_topup": [{"day": r["day"], "credits": r["credits_sum"],
                          "rmb": round((r["credits_sum"] or 0) * _billing.CREDIT_VALUE, 2)}
                        for r in topup_rows],
        "daily_api_cost": [{"day": r["day"], "cost": round(r["api_cost"] or 0, 4)}
                           for r in usage_cost_rows],
    }


@admin_app.get("/admin/usage-stats")
async def admin_usage_stats(days: int = 30, admin: dict = Depends(_aauth.get_admin_user)):
    """用量分析。"""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # 按操作类型汇总
    op_rows = db.fetchall(
        "SELECT operation, COUNT(*) as cnt, SUM(cost_rmb) as cost "
        "FROM usage_records WHERE recorded_at>=? GROUP BY operation ORDER BY cost DESC",
        (since,))

    # Top10 用户（按成本）
    top_users = db.fetchall(
        "SELECT u.username, r.user_id, COUNT(*) as ops, SUM(r.cost_rmb) as cost "
        "FROM usage_records r JOIN users u ON r.user_id=u.id "
        "WHERE r.recorded_at>=? GROUP BY r.user_id ORDER BY cost DESC LIMIT 10",
        (since,))

    # 每日操作量
    daily = db.fetchall(
        "SELECT DATE(recorded_at) as day, COUNT(*) as ops, SUM(cost_rmb) as cost "
        "FROM usage_records WHERE recorded_at>=? GROUP BY day ORDER BY day",
        (since,))

    # 各来源分布（subscription / credits / free）
    source_rows = db.fetchall(
        "SELECT source, COUNT(*) as cnt, SUM(cost_rmb) as cost "
        "FROM usage_records WHERE recorded_at>=? GROUP BY source",
        (since,))

    return {
        "by_operation": [{"op": r["operation"],
                           "label": _billing.OPERATIONS.get(r["operation"], {}).get("label", r["operation"]),
                           "count": r["cnt"],
                           "cost": round(r["cost"] or 0, 4)} for r in op_rows],
        "top_users": [{"username": r["username"], "ops": r["ops"],
                       "cost": round(r["cost"] or 0, 4)} for r in top_users],
        "daily_trend": [{"day": r["day"], "ops": r["ops"],
                         "cost": round(r["cost"] or 0, 4)} for r in daily],
        "by_source": [{"source": r["source"], "count": r["cnt"],
                       "cost": round(r["cost"] or 0, 4)} for r in source_rows],
    }


# ══════════════════════════════════════════════════════════════════════════
# P4 Prompt 管理
# ══════════════════════════════════════════════════════════════════════════

_PROMPTS_FILE = Path(__file__).parent / "prompts.json"

def _load_prompts() -> dict:
    if _PROMPTS_FILE.exists():
        return json.loads(_PROMPTS_FILE.read_text(encoding="utf-8"))
    return {"prompts": {}, "history": {}}

def _save_prompts(data: dict) -> None:
    _PROMPTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@admin_app.get("/admin/prompts")
async def admin_prompts_list(admin: dict = Depends(_aauth.get_admin_user)):
    """列出所有 Prompt 及元数据。"""
    data = _load_prompts()
    result = []
    for key, p in data.get("prompts", {}).items():
        result.append({
            "key":          key,
            "label":        p.get("label", key),
            "module":       p.get("module", ""),
            "version":      p.get("version", 1),
            "updated_at":   p.get("updated_at", ""),
            "preview":      (p.get("content", ""))[:100] + "…",
        })
    return {"prompts": result}


@admin_app.get("/admin/prompts/{key}")
async def admin_prompt_get(key: str, admin: dict = Depends(_aauth.get_admin_user)):
    data = _load_prompts()
    p = data["prompts"].get(key)
    if not p:
        raise HTTPException(status_code=404, detail=f"Prompt '{key}' 不存在")
    history = data.get("history", {}).get(key, [])
    return {**p, "key": key, "history": history[-10:]}


class PromptUpdateInput(BaseModel):
    content: str
    label:   str = ""

@admin_app.put("/admin/prompts/{key}")
async def admin_prompt_update(
    key: str, req: PromptUpdateInput,
    admin: dict = Depends(_aauth.get_admin_user)
):
    data = _load_prompts()
    now = datetime.now(timezone.utc).isoformat()
    old = data["prompts"].get(key, {})
    version = old.get("version", 0) + 1

    # 保存历史版本
    hist = data.setdefault("history", {}).setdefault(key, [])
    if old.get("content"):
        hist.append({"version": old.get("version", 0), "content": old["content"],
                     "saved_at": old.get("updated_at", now)})
    hist[:] = hist[-10:]  # 只保留最近10条

    data["prompts"][key] = {
        "key":        key,
        "label":      req.label or old.get("label", key),
        "module":     old.get("module", ""),
        "content":    req.content,
        "version":    version,
        "updated_at": now,
    }
    _save_prompts(data)
    return {"ok": True, "version": version, "updated_at": now}


@admin_app.post("/admin/prompts/{key}/rollback")
async def admin_prompt_rollback(
    key: str, body: dict,
    admin: dict = Depends(_aauth.get_admin_user)
):
    version = body.get("version")
    data = _load_prompts()
    hist = data.get("history", {}).get(key, [])
    target = next((h for h in hist if h["version"] == version), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"找不到版本 {version}")
    # 当前变为历史，历史版本变当前
    return await admin_prompt_update(key, PromptUpdateInput(content=target["content"]), admin)


# ══════════════════════════════════════════════════════════════════════════
# P5 大模型管理
# ══════════════════════════════════════════════════════════════════════════

_MODEL_REGISTRY_FILE = Path(__file__).parent / "model_registry.json"
_MODEL_DIR = Path(__file__).parent / "artifacts"

def _load_registry() -> dict:
    if _MODEL_REGISTRY_FILE.exists():
        return json.loads(_MODEL_REGISTRY_FILE.read_text(encoding="utf-8"))
    # 初始化：把当前 v0.3 纳入注册表
    registry = {
        "current": "v0.3",
        "models": {
            "v0.3": {
                "version":     "v0.3",
                "file":        "artifacts/model_a_v0.3.lgb",
                "features":    62,
                "rmse":        12.2987,
                "accuracy":    82.34,
                "train_rows":  101517,
                "trained_at":  "2026-05-05",
                "status":      "production",
                "description": "初始生产版本，62维特征，Kimi语义标注",
            }
        },
        "training_jobs": [],
    }
    _MODEL_REGISTRY_FILE.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    return registry


def _save_registry(data: dict) -> None:
    _MODEL_REGISTRY_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@admin_app.get("/admin/models")
async def admin_models_list(admin: dict = Depends(_aauth.get_admin_user)):
    registry = _load_registry()
    # 训练数据量
    try:
        import pandas as pd
        feat_path = _MODEL_DIR / "features.parquet"
        train_rows = len(pd.read_parquet(feat_path)) if feat_path.exists() else 0
    except Exception:
        train_rows = 0

    return {
        "current_version": registry["current"],
        "models":          list(registry["models"].values()),
        "training_data_rows": train_rows,
        "training_jobs":   registry.get("training_jobs", [])[-5:],
    }


@admin_app.post("/admin/models/{version}/deploy")
async def admin_model_deploy(version: str, admin: dict = Depends(_aauth.get_admin_user)):
    """部署指定版本为生产模型（热切换，api.py 下次请求自动加载）。"""
    registry = _load_registry()
    model_info = registry["models"].get(version)
    if not model_info:
        raise HTTPException(status_code=404, detail=f"版本 {version} 不存在")

    if model_info.get("family") == "v04_composite":
        train_report = Path(model_info.get("train_report") or "artifacts/model_v04_composite_train_report.json")
        if train_report.is_absolute():
            report_file = train_report
        elif train_report.parts and train_report.parts[0] == "artifacts":
            report_file = Path(__file__).parent / train_report
        else:
            report_file = _MODEL_DIR / train_report
        if not report_file.exists():
            raise HTTPException(status_code=404, detail=f"训练报告不存在: {model_info.get('train_report')}")
        report = json.loads(report_file.read_text(encoding="utf-8"))
        policy = report.get("training_policy") or {}
        gate = report.get("deployment_gate") or {}
        if policy.get("do_not_deploy") or not gate.get("passed"):
            raise HTTPException(status_code=409, detail="V0.4 composite 训练报告未通过部署门禁")

        registry["current"] = version
        for v, m in registry["models"].items():
            m["status"] = "production" if v == version else "archived"
        _save_registry(registry)
        return {"ok": True, "deployed": version, "file": str(report_file), "deployment_mode": "v04_composite_report"}

    raw_file = Path(model_info["file"])
    if raw_file.is_absolute():
        model_file = raw_file
    elif raw_file.parts and raw_file.parts[0] == "artifacts":
        model_file = Path(__file__).parent / raw_file
    else:
        model_file = _MODEL_DIR / raw_file
    if not model_file.exists():
        raise HTTPException(status_code=404, detail=f"模型文件不存在: {model_info['file']}")

    # 更新符号链接 model_a_current.lgb → 目标文件
    current_link = _MODEL_DIR / "model_a_current.lgb"
    if current_link.exists() or current_link.is_symlink():
        current_link.unlink()
    current_link.symlink_to(model_file.name)

    registry["current"] = version
    for v, m in registry["models"].items():
        m["status"] = "production" if v == version else "archived"
    _save_registry(registry)

    return {"ok": True, "deployed": version, "file": str(model_file)}


class TrainJobInput(BaseModel):
    description: str = "手动触发训练"
    max_rows:    int  = 0   # 0=全量

@admin_app.post("/admin/models/train")
async def admin_model_train(
    req: TrainJobInput,
    background_tasks: BackgroundTasks,
    admin: dict = Depends(_aauth.get_admin_user)
):
    """异步触发模型重训练。"""
    job_id = str(uuid.uuid4())[:8]
    registry = _load_registry()
    job = {
        "id":          job_id,
        "description": req.description,
        "status":      "queued",
        "started_at":  datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "new_version": None,
        "metrics":     None,
    }
    registry.setdefault("training_jobs", []).append(job)
    _save_registry(registry)

    background_tasks.add_task(_run_training_job, job_id, req.max_rows)
    return {"ok": True, "job_id": job_id, "message": "训练任务已加入队列"}


async def _run_training_job(job_id: str, max_rows: int) -> None:
    """后台执行训练脚本。"""
    registry = _load_registry()
    jobs = registry.get("training_jobs", [])
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        return
    job["status"] = "running"
    _save_registry(registry)
    try:
        train_script = Path(__file__).parent / "train_v03.py"
        env = {**os.environ}
        result = await asyncio.create_subprocess_exec(
            sys.executable, str(train_script),
            cwd=str(Path(__file__).parent),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(result.communicate(), timeout=3600)
        if result.returncode == 0:
            # 解析训练输出，找新版本号和指标
            output = stdout.decode(errors="ignore")
            new_version = f"v{len(registry['models']) + 1}.0"
            job["status"]      = "completed"
            job["new_version"] = new_version
            job["metrics"]     = {"output": output[-500:]}
            job["finished_at"] = datetime.now(timezone.utc).isoformat()
        else:
            job["status"]      = "failed"
            job["metrics"]     = {"error": stderr.decode(errors="ignore")[-500:]}
            job["finished_at"] = datetime.now(timezone.utc).isoformat()
    except asyncio.TimeoutError:
        job["status"]      = "failed"
        job["metrics"]     = {"error": "训练超时（>1小时）"}
        job["finished_at"] = datetime.now(timezone.utc).isoformat()
    except Exception as e:
        job["status"]      = "failed"
        job["metrics"]     = {"error": str(e)}
        job["finished_at"] = datetime.now(timezone.utc).isoformat()
    _save_registry(registry)


@admin_app.get("/admin/models/train/{job_id}")
async def admin_train_status(job_id: str, admin: dict = Depends(_aauth.get_admin_user)):
    registry = _load_registry()
    job = next((j for j in registry.get("training_jobs", []) if j["id"] == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="训练任务不存在")
    return job


# ══════════════════════════════════════════════════════════════════════════
# P6 爬虫管理
# ══════════════════════════════════════════════════════════════════════════

_CRAWLER_CONFIG_FILE = Path(__file__).parent / "crawler_config.json"

def _load_crawler_config() -> dict:
    if _CRAWLER_CONFIG_FILE.exists():
        return json.loads(_CRAWLER_CONFIG_FILE.read_text(encoding="utf-8"))
    return {
        "enabled": False,
        "cookie_valid": False,
        "last_run": None,
        "total_collected": 0,
        "daily_limit": 300,
        "schedule_hour": 3,
    }


@admin_app.get("/admin/crawler/status")
async def admin_crawler_status(admin: dict = Depends(_aauth.get_admin_user)):
    config = _load_crawler_config()
    xhs_cookie_file = Path(__file__).parent / "data" / "xhs_cookies.json"
    cookie_exists = xhs_cookie_file.exists()
    cookie_content = {}
    if cookie_exists:
        try:
            cookie_content = json.loads(xhs_cookie_file.read_text())
        except Exception:
            pass

    # 爬虫采集数据统计
    crawl_stats = db.fetchone(
        "SELECT COUNT(*) as cnt FROM tracked_notes WHERE status='complete'"
    ) or {"cnt": 0}

    return {
        **config,
        "cookie_file_exists": cookie_exists,
        "cookie_count":       len(cookie_content) if isinstance(cookie_content, list) else 0,
        "completed_tracks":   crawl_stats["cnt"],
    }


class CookieUpdateInput(BaseModel):
    cookies_json: str  # XiaoHongShu cookie JSON 字符串

@admin_app.post("/admin/crawler/update-cookie")
async def admin_update_cookie(
    req: CookieUpdateInput,
    admin: dict = Depends(_aauth.get_admin_user)
):
    """更新小红书 Cookie。"""
    try:
        cookies = json.loads(req.cookies_json)
        if not isinstance(cookies, (list, dict)):
            raise ValueError("Cookie 格式错误，需为 JSON 数组或对象")
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"JSON 解析失败: {e}")

    cookie_path = Path(__file__).parent / "data" / "xhs_cookies.json"
    cookie_path.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")

    config = _load_crawler_config()
    config["cookie_valid"] = True
    config["cookie_updated_at"] = datetime.now(timezone.utc).isoformat()
    _CRAWLER_CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"ok": True, "cookie_count": len(cookies) if isinstance(cookies, list) else 1}


@admin_app.post("/admin/crawler/toggle")
async def admin_crawler_toggle(
    body: dict,
    admin: dict = Depends(_aauth.get_admin_user)
):
    """启用/禁用爬虫。"""
    enabled = bool(body.get("enabled", False))
    config = _load_crawler_config()
    config["enabled"] = enabled
    _CRAWLER_CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "enabled": enabled}


@admin_app.post("/admin/crawler/run")
async def admin_crawler_run(
    body: dict,
    background_tasks: BackgroundTasks,
    admin: dict = Depends(_aauth.get_admin_user)
):
    """手动触发一轮爬虫采集（后台执行）。"""
    limit = int(body.get("limit", 50))
    background_tasks.add_task(_run_crawler_bg, limit)
    return {"ok": True, "message": f"爬虫已启动，最多采集 {limit} 条"}


async def _run_crawler_bg(limit: int) -> None:
    try:
        import crawler as _crawler
        result = await _crawler.run_collection_round(limit=limit)
        config = _load_crawler_config()
        config["last_run"] = datetime.now(timezone.utc).isoformat()
        config["total_collected"] = config.get("total_collected", 0) + result.get("collected", 0)
        _CRAWLER_CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[Admin] Crawler error: {e}")


@admin_app.get("/admin/crawler/logs")
async def admin_crawler_logs(
    limit: int = 50,
    admin: dict = Depends(_aauth.get_admin_user)
):
    try:
        import crawler as _crawler
        return {"logs": _crawler.get_crawler_logs(limit)}
    except Exception:
        return {"logs": []}


# ══════════════════════════════════════════════════════════════════════════
# P3 系统设置
# ══════════════════════════════════════════════════════════════════════════

@admin_app.get("/admin/settings")
async def admin_settings(admin: dict = Depends(_aauth.get_admin_user)):
    """返回当前套餐配额设置。"""
    # 提取每种操作的积分消耗
    credit_costs = {k: v["credits"] for k, v in _billing.OPERATIONS.items()}
    return {
        "tiers":        _billing.TIERS,
        "credit_value": _billing.CREDIT_VALUE,
        "credit_costs": credit_costs,
        "operations":   _billing.OPERATIONS,
    }


@admin_app.get("/admin/logs")
async def admin_logs(lines: int = 100, admin: dict = Depends(_aauth.get_admin_user)):
    """返回服务日志最后 N 行。"""
    log_files = ["/tmp/noteai_p1.log", "/tmp/noteai_bill.log", "/tmp/noteai_prod.log"]
    for f in log_files:
        lf = Path(f)
        if lf.exists():
            all_lines = lf.read_text(errors="replace").splitlines()
            return {"lines": all_lines[-lines:], "file": f}
    return {"lines": ["暂无日志文件"], "file": ""}


# ══════════════════════════════════════════════════════════════════════════
# 健康检查
# ══════════════════════════════════════════════════════════════════════════

@admin_app.get("/admin/health")
async def admin_health():
    return {"status": "ok", "service": "NoteAI Admin", "port": int(os.environ.get("ADMIN_PORT", 8001))}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("ADMIN_PORT", 8001))
    uvicorn.run("admin_server:admin_app", host="127.0.0.1", port=port, reload=True)
