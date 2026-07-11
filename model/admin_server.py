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
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# 共享模块
import db
import admin_auth as _aauth
import billing as _billing
import runtime_settings as _settings

try:
    import xhs_acquisition as _xhs_acq
    _XHS_ACQ_AVAILABLE = True
except Exception:
    _xhs_acq = None
    _XHS_ACQ_AVAILABLE = False

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

    # ── 本月收入（模拟：订阅 × 当前套餐单价）──
    sub_revenue = sum(
        tier_dist.get(tier, 0) * int(cfg.get("price", 0))
        for tier, cfg in _billing.TIERS.items()
    )

    # ── 积分充值收入（仅 paid_rmb；管理员赠送 type=gift 不计收入）──
    topup_row = db.fetchone(
        "SELECT COALESCE(SUM(CASE WHEN paid_rmb>0 THEN paid_rmb ELSE amount*? END),0) as total "
        "FROM credit_transactions "
        "WHERE type='topup' AND recorded_at>=?", (_billing.CREDIT_VALUE, month_start,))
    credits_revenue = round(topup_row["total"] or 0, 2)

    total_revenue = round(sub_revenue + credits_revenue, 2)

    # ── 本月 API 成本 ──
    cost_row = db.fetchone(
        "SELECT COALESCE(SUM(cost_rmb),0) as total, "
        "COALESCE(SUM(tokens_in),0) as tokens_in, COALESCE(SUM(tokens_out),0) as tokens_out "
        "FROM usage_records WHERE recorded_at>=?",
        (month_start,))
    api_cost = round(cost_row["total"] or 0, 4)
    month_tokens_in = int(cost_row["tokens_in"] or 0)
    month_tokens_out = int(cost_row["tokens_out"] or 0)

    gross_profit = round(total_revenue - api_cost, 2)
    margin_pct   = round(gross_profit / total_revenue * 100, 1) if total_revenue > 0 else 0

    # ── MRR ──
    mrr = sub_revenue

    # ── 本月各操作用量 ──
    op_rows = db.fetchall(
        "SELECT operation, COUNT(*) as cnt, SUM(cost_rmb) as cost, "
        "SUM(tokens_in) as tokens_in, SUM(tokens_out) as tokens_out, SUM(model_calls) as model_calls "
        "FROM usage_records WHERE recorded_at>=? GROUP BY operation ORDER BY cost DESC",
        (month_start,))
    ops_summary = [{"op": r["operation"],
                    "label": _billing.OPERATIONS.get(r["operation"], {}).get("label", r["operation"]),
                    "count": r["cnt"],
                    "tokens_in": int(r["tokens_in"] or 0),
                    "tokens_out": int(r["tokens_out"] or 0),
                    "total_tokens": int((r["tokens_in"] or 0) + (r["tokens_out"] or 0)),
                    "model_calls": int(r["model_calls"] or 0),
                    "cost": round(r["cost"] or 0, 4)} for r in op_rows]

    # ── 系统状态 ──
    kimi_key   = os.environ.get("MOONSHOT_API_KEY", "")
    claude_key = os.environ.get("ANTHROPIC_API_KEY", "")
    model_files = tuple((Path(__file__).parent / "artifacts").glob("model_v04_*.lgb"))

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
            "tokens_in":       month_tokens_in,
            "tokens_out":      month_tokens_out,
            "total_tokens":    month_tokens_in + month_tokens_out,
            "gross_profit":    gross_profit,
            "margin_pct":      margin_pct,
            "mrr":             mrr,
        },
        "usage": {
            "month_total_cost": api_cost,
            "month_tokens_in":  month_tokens_in,
            "month_tokens_out": month_tokens_out,
            "month_total_tokens": month_tokens_in + month_tokens_out,
            "by_operation":     ops_summary,
        },
        "system": {
            "kimi_configured":   bool(kimi_key),
            "claude_configured": bool(claude_key),
            "model_exists":      bool(model_files),
            "model_size_mb":     round(sum(path.stat().st_size for path in model_files) / 1024**2, 2),
            "database_backend":  "postgresql" if db.using_postgres() else "sqlite",
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
            "SELECT COUNT(*) as cnt, COALESCE(SUM(cost_rmb),0) as cost, "
            "COALESCE(SUM(tokens_in),0) as tokens_in, COALESCE(SUM(tokens_out),0) as tokens_out "
            "FROM usage_records WHERE user_id=? AND recorded_at>=?",
            (r["id"], month_start))
        users_out.append({
            **dict(r),
            "phone_masked": _mask_phone_admin(r["phone"] or ""),
            "month_ops":    usage["cnt"],
            "month_cost":   round(usage["cost"] or 0, 4),
            "month_tokens": int((usage["tokens_in"] or 0) + (usage["tokens_out"] or 0)),
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
        "SELECT operation, COUNT(*) as cnt, SUM(cost_rmb) as cost, SUM(credits_used) as creds, "
        "SUM(tokens_in) as tokens_in, SUM(tokens_out) as tokens_out, SUM(model_calls) as model_calls "
        "FROM usage_records WHERE user_id=? AND recorded_at>=? GROUP BY operation",
        (user_id, month_start))

    recent_usage = db.fetchall(
        "SELECT operation,source,cost_rmb,credits_used,tokens_in,tokens_out,model_calls,model_names,cost_mode,recorded_at "
        "FROM usage_records WHERE user_id=? ORDER BY recorded_at DESC LIMIT 20",
        (user_id,))

    credit_txns = db.fetchall(
        "SELECT type,amount,balance_after,description,paid_rmb,package_id,payment_ref,recorded_at "
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
        new_bal = _billing.grant_credits(user_id, amount, f"管理员手动增加：{req.note}")
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
            "used_chat_rewrite=0,used_screenshot=0,used_monthly_credits=0 "
            "WHERE user_id=? AND is_active=1",
            (user_id,))
        return {"ok": True, "message": "本月积分已重置"}

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
    next_status = "checking_7d" if note["check_24h_at"] or note["status"] in ("checking_7d", "checking_24h", "complete") else "pending"
    db.execute(
        "UPDATE tracked_notes SET status=?,next_check_at=?,last_error_code=NULL,last_error=NULL WHERE id=?",
        (next_status, datetime.now(timezone.utc).isoformat(), note_id),
    )
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
    sub_revenue_est = sum(
        tier_dist.get(tier, 0) * int(cfg.get("price", 0))
        for tier, cfg in _billing.TIERS.items()
    )

    # 积分充值实际收入
    topup_rows = db.fetchall(
        "SELECT DATE(recorded_at) as day, SUM(amount) as credits_sum, "
        "SUM(CASE WHEN paid_rmb>0 THEN paid_rmb ELSE amount*? END) as rmb_sum "
        "FROM credit_transactions WHERE type='topup' AND recorded_at>=? GROUP BY day ORDER BY day",
        (_billing.CREDIT_VALUE, since,))

    # 积分消费量（每日）
    usage_cost_rows = db.fetchall(
        "SELECT DATE(recorded_at) as day, SUM(cost_rmb) as api_cost, "
        "SUM(tokens_in) as tokens_in, SUM(tokens_out) as tokens_out "
        "FROM usage_records WHERE recorded_at>=? GROUP BY day ORDER BY day",
        (since,))

    return {
        "tier_distribution": tier_dist,
        "sub_revenue_estimate": sub_revenue_est,
        "daily_topup": [{"day": r["day"], "credits": r["credits_sum"],
                          "rmb": round(r["rmb_sum"] or 0, 2)}
                        for r in topup_rows],
        "daily_api_cost": [{"day": r["day"], "cost": round(r["api_cost"] or 0, 4),
                            "tokens": int((r["tokens_in"] or 0) + (r["tokens_out"] or 0))}
                           for r in usage_cost_rows],
    }


def build_usage_stats_payload(days: int = 30) -> dict:
    """Build the admin usage payload from the same billing rows shown to users."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # 按操作类型汇总
    op_rows = db.fetchall(
        "SELECT operation, COUNT(*) as cnt, SUM(cost_rmb) as cost, "
        "SUM(tokens_in) as tokens_in, SUM(tokens_out) as tokens_out, SUM(model_calls) as model_calls "
        "FROM usage_records WHERE recorded_at>=? GROUP BY operation ORDER BY cost DESC",
        (since,))

    # Top10 用户（按成本）
    top_users = db.fetchall(
        "SELECT u.username, r.user_id, COUNT(*) as ops, SUM(r.cost_rmb) as cost, "
        "SUM(r.tokens_in) as tokens_in, SUM(r.tokens_out) as tokens_out "
        "FROM usage_records r JOIN users u ON r.user_id=u.id "
        "WHERE r.recorded_at>=? GROUP BY r.user_id ORDER BY cost DESC LIMIT 10",
        (since,))

    # 每日操作量
    daily = db.fetchall(
        "SELECT DATE(recorded_at) as day, COUNT(*) as ops, SUM(cost_rmb) as cost, "
        "SUM(tokens_in) as tokens_in, SUM(tokens_out) as tokens_out "
        "FROM usage_records WHERE recorded_at>=? GROUP BY day ORDER BY day",
        (since,))

    # 各来源分布（subscription / credits / free）
    source_rows = db.fetchall(
        "SELECT source, COUNT(*) as cnt, SUM(cost_rmb) as cost, "
        "SUM(tokens_in) as tokens_in, SUM(tokens_out) as tokens_out "
        "FROM usage_records WHERE recorded_at>=? GROUP BY source",
        (since,))

    return {
        "by_operation": [{"op": r["operation"],
                           "label": _billing.OPERATIONS.get(r["operation"], {}).get("label", r["operation"]),
                           "count": r["cnt"],
                           "tokens_in": int(r["tokens_in"] or 0),
                           "tokens_out": int(r["tokens_out"] or 0),
                           "total_tokens": int((r["tokens_in"] or 0) + (r["tokens_out"] or 0)),
                           "model_calls": int(r["model_calls"] or 0),
                           "cost": round(r["cost"] or 0, 4)} for r in op_rows],
        "top_users": [{"username": r["username"], "ops": r["ops"],
                       "tokens": int((r["tokens_in"] or 0) + (r["tokens_out"] or 0)),
                       "cost": round(r["cost"] or 0, 4)} for r in top_users],
        "daily_trend": [{"day": r["day"], "ops": r["ops"],
                         "tokens": int((r["tokens_in"] or 0) + (r["tokens_out"] or 0)),
                         "cost": round(r["cost"] or 0, 4)} for r in daily],
        "by_source": [{"source": r["source"], "count": r["cnt"],
                       "tokens": int((r["tokens_in"] or 0) + (r["tokens_out"] or 0)),
                       "cost": round(r["cost"] or 0, 4)} for r in source_rows],
    }


@admin_app.get("/admin/usage-stats")
async def admin_usage_stats(days: int = 30, admin: dict = Depends(_aauth.get_admin_user)):
    """用量分析。"""
    return build_usage_stats_payload(days)


# ══════════════════════════════════════════════════════════════════════════
# P4 Prompt 管理
# ══════════════════════════════════════════════════════════════════════════

def _load_prompts() -> dict:
    prompts = {}
    history = {}
    for row in db.fetchall(
        "SELECT key,label,module,content,version,updated_at FROM managed_prompts"
    ):
        prompts[row["key"]] = dict(row)
    for row in db.fetchall(
        "SELECT prompt_key,version,content,saved_at FROM prompt_history "
        "ORDER BY id ASC"
    ):
        history.setdefault(row["prompt_key"], []).append({
            "version": row["version"],
            "content": row["content"],
            "saved_at": row["saved_at"],
        })
    return {"prompts": prompts, "history": history}


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
    now = datetime.now(timezone.utc).isoformat()
    old_row = db.fetchone(
        "SELECT key,label,module,content,version,updated_at FROM managed_prompts WHERE key=?",
        (key,),
    )
    old = dict(old_row) if old_row else {}
    version = old.get("version", 0) + 1

    # 保存历史版本
    if old.get("content"):
        db.execute(
            "INSERT INTO prompt_history(prompt_key,version,content,saved_at) VALUES(?,?,?,?)",
            (key, old.get("version", 0), old["content"], old.get("updated_at", now)),
        )
    if old:
        db.execute(
            "UPDATE managed_prompts SET label=?,content=?,version=?,updated_at=? WHERE key=?",
            (req.label or old.get("label", key), req.content, version, now, key),
        )
    else:
        db.execute(
            "INSERT INTO managed_prompts(key,label,module,content,version,updated_at) "
            "VALUES(?,?,?,?,?,?)",
            (key, req.label or key, "", req.content, version, now),
        )
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
_MODEL_REGISTRY_KEY = "model_registry"

def _load_registry() -> dict:
    stored = _settings.get_json(_MODEL_REGISTRY_KEY)
    if isinstance(stored, dict) and stored.get("models"):
        return stored
    if _MODEL_REGISTRY_FILE.exists():
        registry = json.loads(_MODEL_REGISTRY_FILE.read_text(encoding="utf-8"))
        _settings.set_json(_MODEL_REGISTRY_KEY, registry)
        return registry
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
    _settings.set_json(_MODEL_REGISTRY_KEY, registry)
    return registry


def _save_registry(data: dict) -> None:
    _settings.set_json(_MODEL_REGISTRY_KEY, data)


def _guard_cloud_model_mutation() -> None:
    is_cloud = os.environ.get("NOTEAI_CLOUD_RUNTIME", "0").lower() in {"1", "true", "yes"}
    allowed = os.environ.get("NOTEAI_ENABLE_CLOUD_MODEL_MUTATION", "0").lower() in {"1", "true", "yes"}
    if is_cloud and not allowed:
        raise HTTPException(
            status_code=409,
            detail="云端模型发布/训练已锁定；请通过受审计的模型发布流程更新镜像",
        )


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
    _guard_cloud_model_mutation()
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
    _guard_cloud_model_mutation()
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
_CRAWLER_CONFIG_KEY = "crawler_config"
_XHS_COOKIES_KEY = "xhs_cookies"

def _load_crawler_config() -> dict:
    stored = _settings.get_json(_CRAWLER_CONFIG_KEY)
    if isinstance(stored, dict):
        return stored
    if _CRAWLER_CONFIG_FILE.exists():
        config = json.loads(_CRAWLER_CONFIG_FILE.read_text(encoding="utf-8"))
        _settings.set_json(_CRAWLER_CONFIG_KEY, config)
        return config
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
    cookie_content = _settings.get_json(_XHS_COOKIES_KEY, [])
    cookie_exists = bool(cookie_content)
    cookie_runtime_status = "not_configured"
    cookie_last_verified_at = None
    cookie_consecutive_failures = 0
    if cookie_exists:
        cookie_runtime_status = "pending_validation"
        if _XHS_ACQ_AVAILABLE and _xhs_acq is not None:
            recent = _xhs_acq.recent_health(limit=60, adapter="scheduler_a")
            run_ids = []
            for row in recent:
                run_id = row.get("run_id")
                if run_id and run_id not in run_ids:
                    run_ids.append(run_id)
            for run_id in run_ids:
                run_rows = [row for row in recent if row.get("run_id") == run_id]
                if any(row.get("profile_cookie_valid") and int(row.get("evidence_count") or 0) > 0 for row in run_rows):
                    cookie_last_verified_at = max(
                        (row.get("checked_at") or "") for row in run_rows
                    ) or None
                    break
                cookie_consecutive_failures += 1
            latest_rows = [row for row in recent if run_ids and row.get("run_id") == run_ids[0]]
            latest_errors = {str(row.get("error_code") or "") for row in latest_rows}
            if latest_errors & {"cookie_expired", "auth_cookie_missing", "cookie_not_configured"}:
                cookie_runtime_status = "needs_relogin"
            elif latest_rows and any(int(row.get("evidence_count") or 0) > 0 for row in latest_rows):
                cookie_runtime_status = "verified"
            elif latest_rows and all(int(row.get("evidence_count") or 0) == 0 for row in latest_rows):
                cookie_runtime_status = "needs_attention"

    # 爬虫采集数据统计
    crawl_stats = db.fetchone(
        "SELECT COUNT(*) as cnt FROM tracked_notes WHERE status='complete'"
    ) or {"cnt": 0}

    return {
        **config,
        "cookie_file_exists": cookie_exists,
        "cookie_count":       len(cookie_content) if isinstance(cookie_content, list) else 0,
        "cookie_runtime_status": cookie_runtime_status,
        "cookie_last_verified_at": cookie_last_verified_at,
        "cookie_consecutive_failures": cookie_consecutive_failures,
        "cookie_action_required": cookie_runtime_status in {"needs_relogin", "needs_attention"},
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

    _settings.set_json(_XHS_COOKIES_KEY, cookies, is_secret=True)

    config = _load_crawler_config()
    config["cookie_valid"] = True
    config["cookie_updated_at"] = datetime.now(timezone.utc).isoformat()
    _settings.set_json(_CRAWLER_CONFIG_KEY, config)

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
    _settings.set_json(_CRAWLER_CONFIG_KEY, config)
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
        _settings.set_json(_CRAWLER_CONFIG_KEY, config)
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


@admin_app.get("/admin/xhs/freshness")
async def admin_xhs_freshness(admin: dict = Depends(_aauth.get_admin_user)):
    if not _XHS_ACQ_AVAILABLE or _xhs_acq is None:
        raise HTTPException(status_code=503, detail="XHS acquisition ledger unavailable")
    return _xhs_acq.freshness_probe()


@admin_app.get("/admin/xhs/health")
async def admin_xhs_health(
    limit: int = 50,
    domain: str = "",
    adapter: str = "",
    admin: dict = Depends(_aauth.get_admin_user),
):
    if not _XHS_ACQ_AVAILABLE or _xhs_acq is None:
        raise HTTPException(status_code=503, detail="XHS acquisition ledger unavailable")
    return {
        "freshness": _xhs_acq.freshness_overview(),
        "sidecar": _xhs_acq.sidecar_status(),
        "health": _xhs_acq.recent_health(limit=limit, domain=domain, adapter=adapter),
    }


# ══════════════════════════════════════════════════════════════════════════
# P3 系统设置
# ══════════════════════════════════════════════════════════════════════════

@admin_app.get("/admin/settings")
async def admin_settings(admin: dict = Depends(_aauth.get_admin_user)):
    """返回当前套餐积分设置。"""
    # 提取每种操作的积分消耗
    credit_costs = {k: v["credits"] for k, v in _billing.OPERATIONS.items()}
    return {
        "tiers":        _billing.TIERS,
        "credit_value": _billing.CREDIT_VALUE,
        "credit_packages": _billing.list_credit_packages(),
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

@admin_app.get("/health/live")
async def admin_health_live():
    return {"status": "ok", "service": "noteai-admin"}


@admin_app.get("/health/ready")
async def admin_health_ready():
    checks = {
        "admin_credentials": {"ok": bool(os.environ.get("ADMIN_PASSWORD"))},
    }
    try:
        checks["database"] = db.database_health()
    except Exception as exc:
        checks["database"] = {"ok": False, "error": type(exc).__name__}
    ready = all(check.get("ok") for check in checks.values())
    payload = {
        "status": "ready" if ready else "not_ready",
        "service": "noteai-admin",
        "checks": checks,
    }
    return JSONResponse(payload, status_code=200 if ready else 503)


@admin_app.get("/admin/health")
async def admin_health():
    return await admin_health_ready()


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("ADMIN_PORT", 8001))
    uvicorn.run("admin_server:admin_app", host="127.0.0.1", port=port, reload=True)
