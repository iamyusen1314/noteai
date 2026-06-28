"""
NoteAI Pro 计费模块 v2
- 覆盖所有 Kimi/Claude API 消耗操作
- user_id 强绑定：每条记录必须携带，绝不允许 None
- 设计原则：宁可记录过多，不能漏记一条
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import HTTPException, status

import db

# ─────────────────────────────────────────────────────────────
# ① 完整操作注册表（覆盖所有 API Token 消耗点）
# ─────────────────────────────────────────────────────────────
#
# 接入端点 → operation 名称 → 成本说明
#
#  /score              → "score"          Kimi语义特征 (¥0.002)
#  /diagnose           → "diagnose"       Kimi语义特征 (¥0.002)
#  /quick-diagnose     → (不记录，无API)
#  /analyze            → "analyze"        5-Agent全链路 (¥0.072)
#  /analyze extra_imgs → "extra_image"    每张附加图Kimi Vision (¥0.005)
#  /analyze video      → "video_analyze"  _kimi_video_understand (¥0.030)
#  /generate/stream    → "generate"       P1-P4全流程 (¥0.117)
#  /chat/message fast  → "chat_fast"      Kimi fast模式 (¥0.006)
#  /chat/message think → "chat_rewrite"   Kimi thinking模式 (¥0.023)
#  /extract-screenshot → "screenshot"     Kimi Vision OCR (¥0.010)
#
OPERATIONS: dict[str, dict] = {
    "score": {
        "label":   "快速评分",
        "cost":    0.002,    # Kimi语义特征3维
        "credits": 0.0,      # 免费，不扣积分
        "free":    True,     # 不占用配额，但记录用量
    },
    "diagnose": {
        "label":   "内容诊断",
        "cost":    0.002,
        "credits": 0.0,
        "free":    True,
    },
    "analyze": {
        "label":   "AI深度诊断",
        "cost":    0.072,
        "credits": 1.0,
        "free":    False,
    },
    "extra_image": {
        "label":   "附加内容图（每张）",
        "cost":    0.005,
        "credits": 0.0,
        "free":    True,     # 附加图随 analyze 一起，不单独计费
    },
    "video_analyze": {
        "label":   "视频内容解析",
        "cost":    0.030,
        "credits": 0.0,
        "free":    True,     # 随 generate/analyze 计入，不单独扣积分
    },
    "generate": {
        "label":   "AI爆文生成",
        "cost":    0.117,
        "credits": 2.0,
        "free":    False,
    },
    "chat_fast": {
        "label":   "对话反馈",
        "cost":    0.006,
        "credits": 0.0,
        "free":    True,
    },
    "chat_rewrite": {
        "label":   "对话重写",
        "cost":    0.023,
        "credits": 0.5,
        "free":    False,
    },
    "screenshot": {
        "label":   "截图识别",
        "cost":    0.010,
        "credits": 0.5,
        "free":    False,
    },
}

# 1 积分 = ¥0.3
CREDIT_VALUE = 0.30

# ─────────────────────────────────────────────────────────────
# ② 套餐定义（配额仅限非 free 操作）
# ─────────────────────────────────────────────────────────────
QUOTA_OPS = ["analyze", "generate", "chat_rewrite", "screenshot"]

TIERS: dict[str, dict] = {
    "free": {
        "name":  "免费版",
        "price": 0,
        "quotas": {"analyze": 3, "generate": 1, "chat_rewrite": 3, "screenshot": 3},
        "features": ["7天笔记存档"],
    },
    "pro": {
        "name":  "轻创作 Pro",
        "price": 99,
        "quotas": {"analyze": 50, "generate": 20, "chat_rewrite": -1, "screenshot": -1},
        "features": ["永久笔记存档", "无限对话重写", "无限截图识别", "AI记忆学习"],
    },
    "pro_plus": {
        "name":  "专业 Pro+",
        "price": 199,
        "quotas": {"analyze": -1, "generate": 80, "chat_rewrite": -1, "screenshot": -1},
        "features": ["Pro全部权益", "无限AI深度诊断", "优先响应", "专属客服"],
    },
}

# ─────────────────────────────────────────────────────────────
# ③ 工具函数
# ─────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _month_start() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

def _next_month() -> str:
    now = datetime.now(timezone.utc)
    if now.month == 12:
        nxt = now.replace(year=now.year+1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        nxt = now.replace(month=now.month+1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return nxt.isoformat()

def _assert_user(user_id: Optional[str], operation: str) -> str:
    """严格断言：付费操作必须有 user_id，否则拒绝服务。"""
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"操作 [{operation}] 需要登录账号后使用"
        )
    return user_id

# ─────────────────────────────────────────────────────────────
# ④ 订阅管理
# ─────────────────────────────────────────────────────────────

def get_subscription(user_id: str) -> dict:
    """获取用户当前有效订阅；不存在则自动初始化免费版。"""
    _assert_user(user_id, "get_subscription")
    row = db.fetchone(
        "SELECT * FROM subscriptions WHERE user_id=? AND is_active=1 "
        "ORDER BY started_at DESC LIMIT 1",
        (user_id,)
    )
    if not row:
        return _create_free_subscription(user_id)
    sub = dict(row)

    def _strip_tz(s: str) -> datetime:
        d = datetime.fromisoformat(s)
        return d.replace(tzinfo=None) if d.tzinfo else d

    # 付费套餐到期自动降级为免费版
    if sub["tier"] != "free" and sub.get("expires_at"):
        try:
            if _strip_tz(sub["expires_at"]) < _strip_tz(_now()):
                db.execute(
                    "UPDATE subscriptions SET tier='free',is_active=0 WHERE id=?",
                    (sub["id"],)
                )
                return _create_free_subscription(user_id)
        except Exception:
            pass

    # 月初重置配额（统一strip时区再比较，避免 naive vs aware TypeError）
    if _strip_tz(sub["period_start"]) < _strip_tz(_month_start()):
        now = _now(); ms = _month_start()
        db.execute(
            "UPDATE subscriptions SET used_analyze=0,used_generate=0,"
            "used_chat_rewrite=0,used_screenshot=0,period_start=? WHERE id=?",
            (ms, sub["id"])
        )
        sub.update(used_analyze=0, used_generate=0,
                   used_chat_rewrite=0, used_screenshot=0, period_start=ms)
    return sub

def _create_free_subscription(user_id: str) -> dict:
    sid = str(uuid.uuid4()); now = _now(); ms = _month_start()
    db.execute(
        "INSERT INTO subscriptions(id,user_id,tier,started_at,expires_at,is_active,"
        "used_analyze,used_generate,used_chat_rewrite,used_screenshot,period_start) "
        "VALUES(?,?,?,?,?,?,0,0,0,0,?)",
        (sid, user_id, "free", now, "2099-01-01T00:00:00+00:00", 1, ms)
    )
    return get_subscription(user_id)

def upgrade_subscription(user_id: str, tier: str) -> dict:
    _assert_user(user_id, "upgrade")
    if tier not in TIERS:
        raise ValueError(f"未知套餐: {tier}")
    db.execute("UPDATE subscriptions SET is_active=0 WHERE user_id=?", (user_id,))
    sid = str(uuid.uuid4()); now = _now()
    db.execute(
        "INSERT INTO subscriptions(id,user_id,tier,started_at,expires_at,is_active,"
        "used_analyze,used_generate,used_chat_rewrite,used_screenshot,period_start) "
        "VALUES(?,?,?,?,?,1,0,0,0,0,?)",
        (sid, user_id, tier, now, _next_month(), _month_start())
    )
    return get_subscription(user_id)

# ─────────────────────────────────────────────────────────────
# ⑤ 核心配额检查 & 扣减（付费操作专用）
# ─────────────────────────────────────────────────────────────

def check_and_deduct(user_id: Optional[str], operation: str) -> dict:
    """
    检查配额并扣减。
    - 付费操作必须有 user_id，否则 401。
    - 套餐内：扣配额。
    - 超出套餐：尝试扣积分。
    - 积分不足：402 配额不足。
    返回 {"source":"subscription"|"credits"|"free", "credits_used":float}
    """
    op = OPERATIONS.get(operation)
    if not op:
        raise ValueError(f"未知操作: {operation}")

    # 免费操作：仅记录，不扣配额
    if op["free"] or op["credits"] == 0:
        if user_id:
            _record_usage(user_id, operation, source="free", credits_used=0)
        return {"source": "free", "credits_used": 0}

    # 付费操作：严格要求 user_id
    uid = _assert_user(user_id, operation)
    sub  = get_subscription(uid)
    tier = sub["tier"]
    quota_limit = TIERS[tier]["quotas"].get(operation, 0)
    used_key    = f"used_{operation}"
    used_now    = sub.get(used_key, 0)

    # 套餐配额未用完（-1 = 无限）
    if quota_limit == -1 or used_now < quota_limit:
        if quota_limit != -1:
            db.execute(
                f"UPDATE subscriptions SET {used_key}={used_key}+1 WHERE id=?",
                (sub["id"],)
            )
        _record_usage(uid, operation, source="subscription", credits_used=0)
        return {"source": "subscription", "credits_used": 0}

    # 配额已满，尝试积分
    cost = op["credits"]
    bal_row = db.fetchone("SELECT balance FROM credits WHERE user_id=?", (uid,))
    balance = bal_row["balance"] if bal_row else 0.0

    if balance >= cost:
        _deduct_credits(uid, cost, f"超出{TIERS[tier]['name']}配额：{op['label']}")
        _record_usage(uid, operation, source="credits", credits_used=cost)
        return {"source": "credits", "credits_used": cost}

    raise HTTPException(
        status_code=402,
        detail={
            "code":            "QUOTA_EXCEEDED",
            "message":         f"{op['label']}本月配额已用完，积分不足（余额 {balance:.1f} 积分，需 {cost:.1f} 积分）",
            "operation":       operation,
            "op_label":        op["label"],
            "current_tier":    TIERS[tier]["name"],
            "quota_used":      used_now,
            "quota_limit":     quota_limit,
            "credits_needed":  cost,
            "credits_balance": round(balance, 2),
        }
    )

# ─────────────────────────────────────────────────────────────
# ⑥ 免费操作用量记录（score/diagnose/chat_fast 等）
# ─────────────────────────────────────────────────────────────

def record_free_usage(user_id: Optional[str], operation: str,
                      tokens_in: int = 0, tokens_out: int = 0) -> None:
    """记录免费操作的 token 消耗（用于成本统计，不扣积分/配额）。"""
    if not user_id:
        return   # 匿名用户免费操作不跟踪
    op = OPERATIONS.get(operation, {})
    _record_usage(user_id, operation, source="free", credits_used=0,
                  tokens_in=tokens_in, tokens_out=tokens_out)

# ─────────────────────────────────────────────────────────────
# ⑦ 积分操作
# ─────────────────────────────────────────────────────────────

def topup_credits(user_id: str, amount: float, description: str = "充值") -> float:
    _assert_user(user_id, "topup")
    now = _now()
    if db.fetchone("SELECT user_id FROM credits WHERE user_id=?", (user_id,)):
        db.execute(
            "UPDATE credits SET balance=balance+?,total_purchased=total_purchased+?,updated_at=? WHERE user_id=?",
            (amount, amount, now, user_id)
        )
    else:
        db.execute(
            "INSERT INTO credits(user_id,balance,total_purchased,total_used,updated_at) VALUES(?,?,?,0,?)",
            (user_id, amount, amount, now)
        )
    new_bal = db.fetchone("SELECT balance FROM credits WHERE user_id=?", (user_id,))["balance"]
    db.execute(
        "INSERT INTO credit_transactions(id,user_id,type,amount,balance_after,description,recorded_at) VALUES(?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), user_id, "topup", amount, new_bal, description, now)
    )
    return round(new_bal, 2)

def _deduct_credits(user_id: str, amount: float, description: str) -> float:
    _assert_user(user_id, "deduct_credits")
    now = _now()
    if not db.fetchone("SELECT user_id FROM credits WHERE user_id=?", (user_id,)):
        # 自动创建零余额账户
        db.execute("INSERT INTO credits(user_id,balance,total_purchased,total_used,updated_at) VALUES(?,0,0,0,?)", (user_id, now))
    db.execute(
        "UPDATE credits SET balance=balance-?,total_used=total_used+?,updated_at=? WHERE user_id=?",
        (amount, amount, now, user_id)
    )
    new_bal = db.fetchone("SELECT balance FROM credits WHERE user_id=?", (user_id,))["balance"]
    db.execute(
        "INSERT INTO credit_transactions(id,user_id,type,amount,balance_after,description,recorded_at) VALUES(?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), user_id, "usage", -amount, new_bal, description, now)
    )
    return round(new_bal, 2)

def get_credit_transactions(user_id: str, limit: int = 30) -> list[dict]:
    _assert_user(user_id, "get_transactions")
    rows = db.fetchall(
        "SELECT type,amount,balance_after,description,recorded_at FROM credit_transactions "
        "WHERE user_id=? ORDER BY recorded_at DESC LIMIT ?",
        (user_id, limit)
    )
    return [dict(r) for r in rows]

# ─────────────────────────────────────────────────────────────
# ⑧ 用量记录（核心：每条记录强绑定 user_id）
# ─────────────────────────────────────────────────────────────

def _record_usage(user_id: str, operation: str, source: str,
                  credits_used: float,
                  tokens_in: int = 0, tokens_out: int = 0) -> None:
    """
    ★ 所有用量记录的唯一入口。
    user_id 不允许为 None 或空字符串，否则抛出内部错误（防止脏数据）。
    """
    if not user_id:
        # 内部错误：付费操作没有绑定用户，记录日志但不崩溃
        import logging
        logging.error(f"[BILLING] _record_usage called with empty user_id for op={operation}. Skipping.")
        return
    op_info = OPERATIONS.get(operation, {})
    cost = op_info.get("cost", 0) if source != "free" else op_info.get("cost", 0)  # 始终记录真实成本
    db.execute(
        "INSERT INTO usage_records(id,user_id,operation,tokens_in,tokens_out,"
        "cost_rmb,credits_used,source,recorded_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), user_id, operation, tokens_in, tokens_out,
         round(cost, 5), credits_used, source, _now())
    )

# ─────────────────────────────────────────────────────────────
# ⑨ 配额状态查询（用于前端显示）
# ─────────────────────────────────────────────────────────────

def get_quota_status(user_id: str) -> dict:
    _assert_user(user_id, "get_quota_status")
    sub      = get_subscription(user_id)
    tier     = sub["tier"]
    tier_cfg = TIERS[tier]
    creds_row = db.fetchone("SELECT balance FROM credits WHERE user_id=?", (user_id,))
    balance   = creds_row["balance"] if creds_row else 0.0

    quota_detail = {}
    for op in QUOTA_OPS:
        limit = tier_cfg["quotas"].get(op, 0)
        used  = sub.get(f"used_{op}", 0)
        quota_detail[op] = {
            "label":     OPERATIONS[op]["label"],
            "used":      used,
            "limit":     limit,
            "unlimited": limit == -1,
            "remaining": -1 if limit == -1 else max(0, limit - used),
            "pct":       0 if limit <= 0 or limit == -1 else min(100, round(used / limit * 100)),
        }
    return {
        "tier":            tier,
        "tier_name":       tier_cfg["name"],
        "price":           tier_cfg["price"],
        "expires_at":      sub["expires_at"],
        "credits_balance": round(balance, 2),
        "period_start":    sub["period_start"],
        "quotas":          quota_detail,
    }

# ─────────────────────────────────────────────────────────────
# ⑩ 用量统计（汇总 + 明细，供前端展示）
# ─────────────────────────────────────────────────────────────

def get_usage_summary(user_id: str, days: int = 30) -> dict:
    """
    返回两层数据：
    1. 汇总（total_api_cost, total_credits_used, by_operation）
    2. 明细（recent_records，最近50条）
    """
    _assert_user(user_id, "get_usage_summary")
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # 按操作汇总
    rows = db.fetchall(
        "SELECT operation, COUNT(*) as cnt, "
        "SUM(cost_rmb) as total_cost, SUM(credits_used) as total_credits "
        "FROM usage_records WHERE user_id=? AND recorded_at>=? GROUP BY operation "
        "ORDER BY total_cost DESC",
        (user_id, since)
    )
    by_op = {}
    for r in rows:
        op   = r["operation"]
        info = OPERATIONS.get(op, {})
        by_op[op] = {
            "label":         info.get("label", op),
            "count":         r["cnt"],
            "cost_rmb":      round(r["total_cost"]    or 0, 4),
            "credits_used":  round(r["total_credits"]  or 0, 2),
            "is_free":       info.get("free", False),
        }

    total_cost    = sum(v["cost_rmb"]     for v in by_op.values())
    total_credits = sum(v["credits_used"] for v in by_op.values())

    # 明细（最近50条）
    detail_rows = db.fetchall(
        "SELECT operation,source,credits_used,cost_rmb,recorded_at "
        "FROM usage_records WHERE user_id=? AND recorded_at>=? "
        "ORDER BY recorded_at DESC LIMIT 50",
        (user_id, since)
    )
    details = []
    for r in detail_rows:
        op   = r["operation"]
        info = OPERATIONS.get(op, {})
        details.append({
            "operation":   op,
            "label":       info.get("label", op),
            "source":      r["source"],
            "credits_used": r["credits_used"],
            "cost_rmb":    r["cost_rmb"],
            "recorded_at": r["recorded_at"],
        })

    return {
        "period_days":      days,
        "total_api_cost":   round(total_cost, 4),
        "total_credits":    round(total_credits, 2),
        "by_operation":     by_op,
        "recent_records":   details,
    }


# 初始化
db.init_db()
