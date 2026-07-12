"""
NoteAI Pro 计费模块 v2
- 覆盖所有 Kimi/Claude API 消耗操作
- user_id 强绑定：每条记录必须携带，绝不允许 None
- 设计原则：宁可记录过多，不能漏记一条
"""
import uuid
import contextvars
import os
import re
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
#  /score              → "score"          轻量语义评分 (≈¥0.011)
#  /diagnose           → "diagnose"       轻量内容诊断 (≈¥0.011)
#  /quick-diagnose     → (不记录，无API)
#  /analyze            → "analyze"        5-Agent全链路 (实测标准≈¥1.45)
#  /analyze extra_imgs → "extra_image"    每张附加图 Kimi Vision (≈¥0.016)
#  /analyze video      → "video_analyze"  _kimi_video_understand (≈¥0.09-0.21)
#  /generate/stream    → "generate"       P1-P4全流程 (标准预留≈¥1.28)
#  /chat/message fast  → "chat_fast"      快速对话 (标准预留≈¥0.17)
#  /chat/message think → "chat_rewrite"   深度重写/二修 (标准预留≈¥0.63)
#  /extract-screenshot → "screenshot"     Kimi Vision OCR (≈¥0.03-0.07)
#
OPERATIONS: dict[str, dict] = {
    "score": {
        "label":   "快速评分",
        "cost":    0.011,
        "credits": 0.0,      # 免费，不扣积分
        "free":    True,     # 不扣积分，但记录用量
    },
    "diagnose": {
        "label":   "内容诊断",
        "cost":    0.011,
        "credits": 0.0,
        "free":    True,
    },
    "analyze": {
        "label":   "AI深度诊断",
        "cost":    1.45,
        "credits": 6.0,
        "free":    False,
    },
    "extra_image": {
        "label":   "附加内容图（每张）",
        "cost":    0.016,
        "credits": 0.0,
        "free":    True,     # 附加图随 analyze 一起，不单独计费
    },
    "video_analyze": {
        "label":   "视频内容解析",
        "cost":    0.17,
        "credits": 0.0,
        "free":    True,     # 随 generate/analyze 计入，不单独扣积分
    },
    "generate": {
        "label":   "AI爆文生成",
        "cost":    1.28,
        "credits": 8.0,
        "free":    False,
    },
    "chat_fast": {
        "label":   "对话反馈",
        "cost":    0.17,
        "credits": 0.0,
        "free":    True,
    },
    "chat_rewrite": {
        "label":   "对话重写",
        "cost":    0.63,
        "credits": 3.0,
        "free":    False,
    },
    "screenshot": {
        "label":   "截图识别",
        "cost":    0.07,
        "credits": 0.5,
        "free":    False,
    },
}

# 套餐和充值统一使用“创作积分”口径。
# 月度套餐积分每个计费周期重置；充值积分进入钱包，长期有效。
CREDIT_VALUE = 0.30

CREDIT_PACKAGES: dict[str, dict] = {
    "starter": {
        "id": "starter",
        "label": "体验加油包",
        "credits": 30.0,
        "price_rmb": 12.0,
        "unit_price_rmb": 0.400,
        "recommended": False,
        "best_for": "临时补一次诊断、截图识别或少量对话优化",
    },
    "creator": {
        "id": "creator",
        "label": "创作者补给包",
        "credits": 100.0,
        "price_rmb": 39.0,
        "unit_price_rmb": 0.390,
        "recommended": True,
        "best_for": "10次以上深度诊断或多轮优化",
    },
    "growth": {
        "id": "growth",
        "label": "增长运营包",
        "credits": 300.0,
        "price_rmb": 109.0,
        "unit_price_rmb": 0.363,
        "recommended": False,
        "best_for": "稳定运营账号的月中加量",
    },
    "studio": {
        "id": "studio",
        "label": "工作室储备包",
        "credits": 800.0,
        "price_rmb": 279.0,
        "unit_price_rmb": 0.349,
        "recommended": False,
        "best_for": "团队/多账号高频生成与优化",
    },
}

# 当前请求/任务正在归集的 usage_records.id。
_ACTIVE_USAGE_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "noteai_active_usage_id",
    default=None,
)

# ─────────────────────────────────────────────────────────────
# ② 套餐定义：月度创作积分，不再限制单项次数
# ─────────────────────────────────────────────────────────────
QUOTA_OPS = ["analyze", "generate", "chat_rewrite", "screenshot"]

TIERS: dict[str, dict] = {
    "free": {
        "name":  "免费版",
        "price": 0,
        "monthly_credits": 12.0,
        "quotas": {},
        "features": ["12 月度积分", "7天笔记存档", "可体验AI诊断/截图识别"],
    },
    "pro": {
        "name":  "创作者版",
        "price": 99,
        "monthly_credits": 260.0,
        "quotas": {},
        "features": ["260 月度积分", "永久笔记存档", "AI记忆学习", "适合个人创作者"],
    },
    "growth": {
        "name":  "成长版",
        "price": 199,
        "monthly_credits": 560.0,
        "quotas": {},
        "features": ["560 月度积分", "创作者版全部权益", "适合稳定更新账号"],
    },
    "pro_plus": {
        "name":  "专业版",
        "price": 299,
        "monthly_credits": 900.0,
        "quotas": {},
        "features": ["900 月度积分", "优先响应", "适合小团队/稳定运营账号"],
    },
    "studio": {
        "name":  "工作室版",
        "price": 399,
        "monthly_credits": 1250.0,
        "quotas": {},
        "features": ["1250 月度积分", "团队高频运营", "专属客服"],
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


def _env_price(name: str) -> float:
    try:
        return max(0.0, float(os.environ.get(name, "0") or 0))
    except Exception:
        return 0.0


def _price_env_key(model: str, direction: str, currency: str = "RMB") -> str:
    normalized = re.sub(r"[^A-Z0-9]+", "_", str(model or "unknown").upper()).strip("_")
    return f"NOTEAI_MODEL_PRICE_{normalized}_{direction.upper()}_PER_1M_{currency.upper()}"


def _billing_usd_cny() -> float:
    return _env_price("NOTEAI_BILLING_USD_CNY") or _env_price("NOTEAI_PRICING_USD_CNY") or 7.0


_PRICE_VERSION = "official-2026-07-12"
_EXACT_MODEL_PRICES: dict[str, dict[str, float | str | None]] = {
    "claude-haiku-4-5-20251001": {
        "provider": "claude", "currency": "USD", "input": 1.0, "cache_read": 0.1,
        "cache_write_5m": 1.25, "cache_write_1h": 2.0, "output": 5.0,
    },
    "claude-sonnet-4-6": {
        "provider": "claude", "currency": "USD", "input": 3.0, "cache_read": 0.3,
        "cache_write_5m": 3.75, "cache_write_1h": 6.0, "output": 15.0,
    },
    "kimi-k2.6": {
        "provider": "kimi", "currency": "RMB", "input": 6.5, "cache_read": 1.1,
        "cache_write_5m": None, "cache_write_1h": None, "output": 27.0,
    },
    "moonshot-v1-32k-vision-preview": {
        "provider": "kimi", "currency": "RMB", "input": 5.0, "cache_read": None,
        "cache_write_5m": None, "cache_write_1h": None, "output": 20.0,
    },
}


def _exact_price(model: str, direction: str, currency: str, default: float | None) -> float | None:
    key = _price_env_key(model, direction, currency)
    raw = os.environ.get(key)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    # A configured zero is not a valid official catalogue price. Treat zero,
    # negative, and malformed overrides as missing so strict actual coverage
    # cannot be granted for a used dimension.
    return value if value > 0 else None


def _pricing_snapshot(provider: str, model: str) -> dict:
    """Resolve only product-confirmed exact model prices.

    Provider-wide variables remain supported by the old estimate helper, but
    are deliberately excluded here because they cannot prove a model-specific
    supplier cost.
    """
    base = _EXACT_MODEL_PRICES.get(str(model or ""))
    if base and str(provider or "").lower() != str(base.get("provider") or "").lower():
        base = None
    fx = _billing_usd_cny()
    version = os.environ.get("NOTEAI_MODEL_PRICE_VERSION", _PRICE_VERSION).strip() or _PRICE_VERSION
    if not base:
        return {
            "currency": "RMB", "usd_cny": fx, "price_version": version,
            "pricing_status": "unpriced", "input": None, "cache_read": None,
            "cache_write_5m": None, "cache_write_1h": None, "output": None,
        }
    currency = str(base["currency"])
    snapshot = {
        "currency": currency,
        "usd_cny": fx,
        "price_version": version,
        "pricing_status": "exact",
    }
    for dimension in ("input", "cache_read", "cache_write_5m", "cache_write_1h", "output"):
        snapshot[dimension] = _exact_price(
            model, dimension, currency, base.get(dimension) if isinstance(base.get(dimension), (int, float)) else None
        )
    if snapshot["input"] is None or snapshot["output"] is None:
        snapshot["pricing_status"] = "unpriced"
    return snapshot


def _token_price_per_1m_rmb(provider_key: str, model: str, direction: str) -> float:
    exact_rmb = _env_price(_price_env_key(model, direction, "RMB"))
    provider_rmb = _env_price(f"NOTEAI_MODEL_PRICE_{provider_key}_{direction.upper()}_PER_1M_RMB")
    if exact_rmb or provider_rmb:
        return exact_rmb or provider_rmb
    exact_usd = _env_price(_price_env_key(model, direction, "USD"))
    provider_usd = _env_price(f"NOTEAI_MODEL_PRICE_{provider_key}_{direction.upper()}_PER_1M_USD")
    usd_price = exact_usd or provider_usd
    return usd_price * _billing_usd_cny()


def _model_token_cost_rmb(provider: str, model: str, tokens_in: int, tokens_out: int) -> float:
    """Return RMB cost from token usage.

    Prices are intentionally env-configured because provider pricing changes and
    deployment may use different negotiated rates. When no price is configured,
    we still record tokens and keep the operation's estimated cost as fallback.
    """
    provider_key = re.sub(r"[^A-Z0-9]+", "_", str(provider or "unknown").upper()).strip("_")
    in_per_1m = _token_price_per_1m_rmb(provider_key, model, "INPUT")
    out_per_1m = _token_price_per_1m_rmb(provider_key, model, "OUTPUT")
    return round((max(0, tokens_in) / 1_000_000 * in_per_1m) + (max(0, tokens_out) / 1_000_000 * out_per_1m), 6)


def clear_active_usage() -> None:
    _ACTIVE_USAGE_ID.set(None)

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

    # 月初重置本周期消耗（统一strip时区再比较，避免 naive vs aware TypeError）
    if _strip_tz(sub["period_start"]) < _strip_tz(_month_start()):
        now = _now(); ms = _month_start()
        db.execute(
            "UPDATE subscriptions SET used_analyze=0,used_generate=0,"
            "used_chat_rewrite=0,used_screenshot=0,used_monthly_credits=0,period_start=? WHERE id=?",
            (ms, sub["id"])
        )
        sub.update(used_analyze=0, used_generate=0,
                   used_chat_rewrite=0, used_screenshot=0,
                   used_monthly_credits=0, period_start=ms)
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


def _get_subscription_tx(tx: db.Transaction, user_id: str) -> dict:
    lock = " FOR UPDATE" if tx.postgres else ""
    user_row = tx.fetchone(f"SELECT id FROM users WHERE id=?{lock}", (user_id,))
    if not user_row:
        raise HTTPException(status_code=401, detail="登录账号不存在或已失效")
    row = tx.fetchone(
        "SELECT * FROM subscriptions WHERE user_id=? AND is_active=1 "
        f"ORDER BY started_at DESC LIMIT 1{lock}",
        (user_id,),
    )
    if not row:
        sid = str(uuid.uuid4())
        tx.execute(
            "INSERT INTO subscriptions(id,user_id,tier,started_at,expires_at,is_active,"
            "used_analyze,used_generate,used_chat_rewrite,used_screenshot,period_start) "
            "VALUES(?,?,?,?,?,?,0,0,0,0,?)",
            (sid, user_id, "free", _now(), "2099-01-01T00:00:00+00:00", 1, _month_start()),
        )
        row = tx.fetchone(f"SELECT * FROM subscriptions WHERE id=?{lock}", (sid,))
    sub = dict(row)

    def _strip_tz(value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed

    if sub["tier"] != "free" and sub.get("expires_at"):
        try:
            if _strip_tz(sub["expires_at"]) < _strip_tz(_now()):
                tx.execute("UPDATE subscriptions SET tier='free',is_active=0 WHERE id=?", (sub["id"],))
                sid = str(uuid.uuid4())
                tx.execute(
                    "INSERT INTO subscriptions(id,user_id,tier,started_at,expires_at,is_active,"
                    "used_analyze,used_generate,used_chat_rewrite,used_screenshot,period_start) "
                    "VALUES(?,?,?,?,?,1,0,0,0,0,?)",
                    (sid, user_id, "free", _now(), "2099-01-01T00:00:00+00:00", _month_start()),
                )
                sub = dict(tx.fetchone(f"SELECT * FROM subscriptions WHERE id=?{lock}", (sid,)))
        except Exception:
            pass
    if _strip_tz(sub["period_start"]) < _strip_tz(_month_start()):
        month_start = _month_start()
        tx.execute(
            "UPDATE subscriptions SET used_analyze=0,used_generate=0,"
            "used_chat_rewrite=0,used_screenshot=0,used_monthly_credits=0,period_start=? WHERE id=?",
            (month_start, sub["id"]),
        )
        sub.update(
            used_analyze=0,
            used_generate=0,
            used_chat_rewrite=0,
            used_screenshot=0,
            used_monthly_credits=0,
            period_start=month_start,
        )
    return sub


def _record_usage_tx(
    tx: db.Transaction,
    user_id: str,
    operation: str,
    source: str,
    credits_used: float,
) -> str:
    op_info = OPERATIONS.get(operation, {})
    estimated_cost = float(op_info.get("cost", 0) or 0)
    usage_id = str(uuid.uuid4())
    tx.execute(
        "INSERT INTO usage_records(id,user_id,operation,tokens_in,tokens_out,"
        "cost_rmb,estimated_cost_rmb,actual_model_cost_rmb,model_calls,model_names,cost_mode,"
        "credits_used,source,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            usage_id, user_id, operation, 0, 0,
            round(estimated_cost, 5), round(estimated_cost, 5), 0.0, 0, "", "estimated",
            credits_used, source, _now(),
        ),
    )
    return usage_id


def _quota_error(
    operation: str,
    op: dict,
    tier_cfg: dict,
    monthly_limit: float,
    monthly_used: float,
    monthly_remaining: float,
    balance: float,
    cost: float,
) -> HTTPException:
    return HTTPException(
        status_code=402,
        detail={
            "code": "QUOTA_EXCEEDED",
            "message": (
                f"{op['label']}需要 {cost:.1f} 积分；本月套餐积分剩余 {monthly_remaining:.1f}，"
                f"充值积分余额 {balance:.1f}，仍不足以完成本次操作。"
            ),
            "operation": operation,
            "op_label": op["label"],
            "current_tier": tier_cfg["name"],
            "monthly_credits": monthly_limit,
            "monthly_credits_used": monthly_used,
            "monthly_credits_remaining": monthly_remaining,
            "credits_needed": cost,
            "credits_balance": round(balance, 2),
            "wallet_credits_needed": max(0.0, round(cost - monthly_remaining, 2)),
            "credit_policy": "优先扣本月套餐积分，不足部分扣充值积分；本月积分每月重置，充值积分长期有效。",
        },
    )


def check_and_deduct_in_transaction(
    tx: db.Transaction,
    user_id: Optional[str],
    operation: str,
) -> dict:
    """Charge and create the primary usage row inside the caller's transaction."""
    op = OPERATIONS.get(operation)
    if not op:
        raise ValueError(f"未知操作: {operation}")
    if op["free"] or op["credits"] == 0:
        usage_id = _record_usage_tx(tx, user_id, operation, "free", 0) if user_id else None
        return {"source": "free", "credits_used": 0, "usage_id": usage_id}

    uid = _assert_user(user_id, operation)
    sub = _get_subscription_tx(tx, uid)
    tier_cfg = TIERS[sub["tier"]]
    cost = round(float(op["credits"]), 2)
    monthly_limit = round(float(tier_cfg.get("monthly_credits", 0) or 0), 2)
    monthly_used = round(float(sub.get("used_monthly_credits") or 0), 2)
    monthly_remaining = round(max(0.0, monthly_limit - monthly_used), 2)

    tx.execute(
        "INSERT INTO credits(user_id,balance,total_purchased,total_used,updated_at) "
        "VALUES(?,0,0,0,?) ON CONFLICT(user_id) DO NOTHING",
        (uid, _now()),
    )
    lock = " FOR UPDATE" if tx.postgres else ""
    credit_row = tx.fetchone(f"SELECT balance FROM credits WHERE user_id=?{lock}", (uid,))
    balance = round(float(credit_row["balance"] if credit_row else 0), 2)

    monthly_charge = min(cost, monthly_remaining)
    wallet_charge = round(cost - monthly_charge, 2)
    if wallet_charge > balance:
        raise _quota_error(
            operation, op, tier_cfg, monthly_limit, monthly_used,
            monthly_remaining, balance, cost,
        )
    if monthly_charge > 0:
        tx.execute(
            "UPDATE subscriptions SET used_monthly_credits=used_monthly_credits+? WHERE id=?",
            (monthly_charge, sub["id"]),
        )
    if wallet_charge > 0:
        cursor = tx.execute(
            "UPDATE credits SET balance=balance-?,total_used=total_used+?,updated_at=? "
            "WHERE user_id=? AND balance>=?",
            (wallet_charge, wallet_charge, _now(), uid, wallet_charge),
        )
        if int(getattr(cursor, "rowcount", 0) or 0) != 1:
            raise _quota_error(
                operation, op, tier_cfg, monthly_limit, monthly_used,
                monthly_remaining, balance, cost,
            )
        new_balance = float(tx.fetchone("SELECT balance FROM credits WHERE user_id=?", (uid,))["balance"])
        tx.execute(
            "INSERT INTO credit_transactions(id,user_id,type,amount,balance_after,description,"
            "paid_rmb,package_id,payment_ref,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                str(uuid.uuid4()), uid, "usage", -wallet_charge, new_balance,
                f"{tier_cfg['name']}积分扣减：{op['label']}", 0.0, "", "", _now(),
            ),
        )
    source = (
        "mixed" if monthly_charge > 0 and wallet_charge > 0
        else "subscription" if monthly_charge > 0
        else "credits"
    )
    usage_id = _record_usage_tx(tx, uid, operation, source, cost)
    return {
        "source": source,
        "credits_used": cost,
        "monthly_credits_used": monthly_charge,
        "wallet_credits_used": wallet_charge,
        "usage_id": usage_id,
        "subscription_id": sub["id"],
        "subscription_period_start": sub.get("period_start") or "",
    }


def activate_usage(usage_id: str | None) -> None:
    _ACTIVE_USAGE_ID.set(usage_id or None)

def upgrade_subscription(user_id: str, tier: str) -> dict:
    _assert_user(user_id, "upgrade")
    if tier not in TIERS:
        raise ValueError(f"未知套餐: {tier}")
    with db.transaction(write=True) as tx:
        lock = " FOR UPDATE" if tx.postgres else ""
        if not tx.fetchone(f"SELECT id FROM users WHERE id=?{lock}", (user_id,)):
            raise HTTPException(status_code=401, detail="登录账号不存在或已失效")
        tx.execute("UPDATE subscriptions SET is_active=0 WHERE user_id=?", (user_id,))
        sid = str(uuid.uuid4())
        tx.execute(
            "INSERT INTO subscriptions(id,user_id,tier,started_at,expires_at,is_active,"
            "used_analyze,used_generate,used_chat_rewrite,used_screenshot,period_start) "
            "VALUES(?,?,?,?,?,1,0,0,0,0,?)",
            (sid, user_id, tier, _now(), _next_month(), _month_start()),
        )
    return get_subscription(user_id)

# ─────────────────────────────────────────────────────────────
# ⑤ 核心积分检查 & 扣减（付费操作专用）
# ─────────────────────────────────────────────────────────────

def check_and_deduct(user_id: Optional[str], operation: str) -> dict:
    """
    检查积分并扣减。
    - 付费操作必须有 user_id，否则 401。
    - 月度套餐积分优先扣。
    - 月度积分不足时，用充值积分补扣。
    - 积分不足：402 余额不足。
    返回 {"source":"subscription"|"credits"|"mixed"|"free", "credits_used":float}
    """
    op = OPERATIONS.get(operation)
    if not op:
        raise ValueError(f"未知操作: {operation}")

    # 免费操作：仅记录，不扣积分
    if op["free"] or op["credits"] == 0:
        if user_id:
            usage_id = _record_usage(user_id, operation, source="free", credits_used=0, force_active=True)
        else:
            usage_id = None
        return {"source": "free", "credits_used": 0, "usage_id": usage_id}

    # 付费操作：严格要求 user_id
    uid = _assert_user(user_id, operation)
    sub  = get_subscription(uid)
    tier = sub["tier"]
    cost = round(float(op["credits"]), 2)
    tier_cfg = TIERS[tier]
    monthly_limit = round(float(tier_cfg.get("monthly_credits", 0) or 0), 2)
    monthly_used = round(float(sub.get("used_monthly_credits") or 0), 2)
    monthly_remaining = round(max(0.0, monthly_limit - monthly_used), 2)
    bal_row = db.fetchone("SELECT balance FROM credits WHERE user_id=?", (uid,))
    balance = round(float(bal_row["balance"] if bal_row else 0.0), 2)

    def _mark_monthly(amount: float) -> None:
        if amount <= 0:
            return
        db.execute(
            "UPDATE subscriptions SET used_monthly_credits=used_monthly_credits+? "
            "WHERE id=?",
            (round(amount, 2), sub["id"]),
        )

    # 1) 月度套餐积分足够：只扣本月积分。
    if monthly_remaining >= cost:
        _mark_monthly(cost)
        usage_id = _record_usage(uid, operation, source="subscription", credits_used=cost, force_active=True)
        return {
            "source": "subscription",
            "credits_used": cost,
            "monthly_credits_used": cost,
            "wallet_credits_used": 0.0,
            "usage_id": usage_id,
        }

    # 2) 月度积分不足但还有部分余额：月度积分扣完，充值积分补差额。
    wallet_needed = round(cost - monthly_remaining, 2)
    if monthly_remaining > 0 and balance >= wallet_needed:
        _mark_monthly(monthly_remaining)
        _deduct_credits(uid, wallet_needed, f"{tier_cfg['name']}月度积分不足补扣：{op['label']}")
        usage_id = _record_usage(uid, operation, source="mixed", credits_used=cost, force_active=True)
        return {
            "source": "mixed",
            "credits_used": cost,
            "monthly_credits_used": monthly_remaining,
            "wallet_credits_used": wallet_needed,
            "usage_id": usage_id,
        }

    # 3) 月度积分为 0 或不足且充值积分能完整支付：只扣充值积分。
    if balance >= cost:
        _deduct_credits(uid, cost, f"{tier_cfg['name']}月度积分已用完：{op['label']}")
        usage_id = _record_usage(uid, operation, source="credits", credits_used=cost, force_active=True)
        return {
            "source": "credits",
            "credits_used": cost,
            "monthly_credits_used": 0.0,
            "wallet_credits_used": cost,
            "usage_id": usage_id,
        }

    raise HTTPException(
        status_code=402,
        detail={
            "code":            "QUOTA_EXCEEDED",
            "message":         (
                f"{op['label']}需要 {cost:.1f} 积分；本月套餐积分剩余 {monthly_remaining:.1f}，"
                f"充值积分余额 {balance:.1f}，仍不足以完成本次操作。"
            ),
            "operation":       operation,
            "op_label":        op["label"],
            "current_tier":    tier_cfg["name"],
            "monthly_credits": monthly_limit,
            "monthly_credits_used": monthly_used,
            "monthly_credits_remaining": monthly_remaining,
            "credits_needed":  cost,
            "credits_balance": round(balance, 2),
            "wallet_credits_needed": max(0.0, round(cost - monthly_remaining, 2)),
            "credit_policy":   "优先扣本月套餐积分，不足部分扣充值积分；本月积分每月重置，充值积分长期有效。",
        }
    )

# ─────────────────────────────────────────────────────────────
# ⑥ 免费操作用量记录（score/diagnose/chat_fast 等）
# ─────────────────────────────────────────────────────────────

def record_free_usage(user_id: Optional[str], operation: str,
                      tokens_in: int = 0, tokens_out: int = 0) -> None:
    """记录免费操作的 token 消耗（用于成本统计，不扣积分）。"""
    if not user_id:
        return   # 匿名用户免费操作不跟踪
    _record_usage(user_id, operation, source="free", credits_used=0,
                  tokens_in=tokens_in, tokens_out=tokens_out, force_active=True)


def record_auxiliary_usage(user_id: Optional[str], operation: str,
                           tokens_in: int = 0, tokens_out: int = 0) -> None:
    """记录同一主流程里的附加用量，但不接管后续模型 token 归属。"""
    if not user_id:
        return
    if not db.fetchone("SELECT id FROM users WHERE id=?", (user_id,)):
        return
    _record_usage(user_id, operation, source="free", credits_used=0,
                  tokens_in=tokens_in, tokens_out=tokens_out, force_active=False)

# ─────────────────────────────────────────────────────────────
# ⑦ 积分操作
# ─────────────────────────────────────────────────────────────

def list_credit_packages() -> list[dict]:
    """公开给前端的充值包，按小额到大额排序。"""
    return [dict(pkg) for pkg in CREDIT_PACKAGES.values()]


def get_credit_package(package_id: str) -> dict:
    pkg = CREDIT_PACKAGES.get(package_id)
    if not pkg:
        raise ValueError(f"未知积分包: {package_id}")
    return dict(pkg)


def topup_credits(
    user_id: str,
    amount: float,
    description: str = "充值",
    paid_rmb: float | None = None,
    package_id: str = "",
    payment_ref: str = "",
) -> float:
    """Paid credit top-up.

    `amount` is credited points. `paid_rmb` is real cash received and must be
    stored separately; otherwise discounted packages would corrupt revenue.
    """
    _assert_user(user_id, "topup")
    amount = round(float(amount), 2)
    if amount <= 0:
        raise ValueError("充值积分必须大于0")
    paid_value = round(float(paid_rmb if paid_rmb is not None else amount * CREDIT_VALUE), 2)
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
        "INSERT INTO credit_transactions(id,user_id,type,amount,balance_after,description,"
        "paid_rmb,package_id,payment_ref,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), user_id, "topup", amount, new_bal, description,
         paid_value, package_id, payment_ref, now)
    )
    return round(new_bal, 2)


def purchase_credit_package(user_id: str, package_id: str, payment_ref: str = "") -> dict:
    pkg = get_credit_package(package_id)
    balance = topup_credits(
        user_id=user_id,
        amount=float(pkg["credits"]),
        description=f"购买积分包：{pkg['label']}",
        paid_rmb=float(pkg["price_rmb"]),
        package_id=package_id,
        payment_ref=payment_ref,
    )
    return {"package": pkg, "new_balance": balance}


def grant_credits(user_id: str, amount: float, description: str = "管理员赠送") -> float:
    """Grant credits without counting them as paid top-up revenue."""
    _assert_user(user_id, "grant_credits")
    amount = round(float(amount), 2)
    if amount <= 0:
        raise ValueError("赠送积分必须大于0")
    now = _now()
    if db.fetchone("SELECT user_id FROM credits WHERE user_id=?", (user_id,)):
        db.execute(
            "UPDATE credits SET balance=balance+?,updated_at=? WHERE user_id=?",
            (amount, now, user_id)
        )
    else:
        db.execute(
            "INSERT INTO credits(user_id,balance,total_purchased,total_used,updated_at) VALUES(?,?,0,0,?)",
            (user_id, amount, now)
        )
    new_bal = db.fetchone("SELECT balance FROM credits WHERE user_id=?", (user_id,))["balance"]
    db.execute(
        "INSERT INTO credit_transactions(id,user_id,type,amount,balance_after,description,"
        "paid_rmb,package_id,payment_ref,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), user_id, "gift", amount, new_bal, description,
         0.0, "", "", now)
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
        "INSERT INTO credit_transactions(id,user_id,type,amount,balance_after,description,"
        "paid_rmb,package_id,payment_ref,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), user_id, "usage", -amount, new_bal, description,
         0.0, "", "", now)
    )
    return round(new_bal, 2)


def refund_operation_charge_in_transaction(
    tx: db.Transaction,
    user_id: str,
    operation: str,
    charge: dict | None,
    description: str,
) -> None:
    """Refund one charge inside the caller's short transaction."""
    if not charge:
        return
    uid = _assert_user(user_id, f"refund_{operation}")
    usage_id = charge.get("usage_id")
    source = charge.get("source")
    subscription_id = str(charge.get("subscription_id") or "")
    subscription_period_start = str(charge.get("subscription_period_start") or "")
    credits_used = float(charge.get("credits_used") or 0)
    monthly_used = float(charge.get("monthly_credits_used") or 0)
    wallet_used = float(charge.get("wallet_credits_used") or 0)
    if not monthly_used and source == "subscription":
        monthly_used = credits_used
    if not wallet_used and source == "credits":
        wallet_used = credits_used
    now = _now()

    if monthly_used > 0:
        amount = round(monthly_used, 2)
        if subscription_id and subscription_period_start:
            tx.execute(
                "UPDATE subscriptions SET used_monthly_credits="
                "CASE WHEN used_monthly_credits>? THEN used_monthly_credits-? ELSE 0 END "
                "WHERE id=? AND user_id=? AND period_start=?",
                (amount, amount, subscription_id, uid, subscription_period_start),
            )
    if wallet_used > 0:
        amount = round(wallet_used, 2)
        tx.execute(
            "INSERT INTO credits(user_id,balance,total_purchased,total_used,updated_at) "
            "VALUES(?,0,0,0,?) ON CONFLICT(user_id) DO NOTHING",
            (uid, now),
        )
        tx.execute(
            "UPDATE credits SET balance=balance+?,"
            "total_used=CASE WHEN total_used>? THEN total_used-? ELSE 0 END,updated_at=? "
            "WHERE user_id=?",
            (amount, amount, amount, now, uid),
        )
        new_balance = float(tx.fetchone("SELECT balance FROM credits WHERE user_id=?", (uid,))["balance"])
        tx.execute(
            "INSERT INTO credit_transactions(id,user_id,type,amount,balance_after,description,"
            "paid_rmb,package_id,payment_ref,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                str(uuid.uuid4()), uid, "refund", amount, new_balance, description,
                0.0, "", "", now,
            ),
        )
    if usage_id:
        tx.execute(
            "UPDATE usage_records SET source='refunded',credits_used=0 WHERE id=? AND user_id=?",
            (usage_id, uid),
        )


def refund_operation_charge(user_id: str, operation: str, charge: dict | None, description: str) -> None:
    """Undo user-facing quota/credit charge when a paid operation fails.

    The API may still have real model cost before the failure; that cost remains
    in `usage_records` for internal gross-margin accounting, but users should
    not lose quota or credits for a failed delivery.
    """
    if not charge:
        return
    uid = _assert_user(user_id, f"refund_{operation}")
    usage_id = charge.get("usage_id")
    source = charge.get("source")
    credits_used = float(charge.get("credits_used") or 0)
    now = _now()

    monthly_used = float(charge.get("monthly_credits_used") or 0)
    wallet_used = float(charge.get("wallet_credits_used") or 0)
    if not monthly_used and source == "subscription":
        monthly_used = credits_used
    if not wallet_used and source == "credits":
        wallet_used = credits_used

    if monthly_used > 0:
        monthly_used = round(monthly_used, 2)
        db.execute(
            "UPDATE subscriptions SET used_monthly_credits="
            "CASE WHEN used_monthly_credits>? THEN used_monthly_credits-? ELSE 0 END "
            "WHERE user_id=? AND is_active=1",
            (monthly_used, monthly_used, uid),
        )

    if wallet_used > 0:
        wallet_used = round(wallet_used, 2)
        if not db.fetchone("SELECT user_id FROM credits WHERE user_id=?", (uid,)):
            db.execute("INSERT INTO credits(user_id,balance,total_purchased,total_used,updated_at) VALUES(?,0,0,0,?)", (uid, now))
        db.execute(
            "UPDATE credits SET balance=balance+?,total_used=MAX(total_used-?,0),updated_at=? WHERE user_id=?",
            (wallet_used, wallet_used, now, uid),
        )
        new_bal = db.fetchone("SELECT balance FROM credits WHERE user_id=?", (uid,))["balance"]
        db.execute(
            "INSERT INTO credit_transactions(id,user_id,type,amount,balance_after,description,"
            "paid_rmb,package_id,payment_ref,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), uid, "refund", wallet_used, new_bal, description,
             0.0, "", "", now),
        )

    if usage_id:
        db.execute(
            "UPDATE usage_records SET source='refunded',credits_used=0 WHERE id=? AND user_id=?",
            (usage_id, uid),
        )


def get_credit_transactions(user_id: str, limit: int = 30) -> list[dict]:
    _assert_user(user_id, "get_transactions")
    rows = db.fetchall(
        "SELECT type,amount,balance_after,description,paid_rmb,package_id,payment_ref,recorded_at "
        "FROM credit_transactions "
        "WHERE user_id=? ORDER BY recorded_at DESC LIMIT ?",
        (user_id, limit)
    )
    return [dict(r) for r in rows]

# ─────────────────────────────────────────────────────────────
# ⑧ 用量记录（核心：每条记录强绑定 user_id）
# ─────────────────────────────────────────────────────────────

def _record_usage(user_id: str, operation: str, source: str,
                  credits_used: float,
                  tokens_in: int = 0, tokens_out: int = 0,
                  force_active: bool = False) -> str | None:
    """
    ★ 所有用量记录的唯一入口。
    user_id 不允许为 None 或空字符串，否则抛出内部错误（防止脏数据）。
    """
    if not user_id:
        # 内部错误：付费操作没有绑定用户，记录日志但不崩溃
        import logging
        logging.error(f"[BILLING] _record_usage called with empty user_id for op={operation}. Skipping.")
        return None
    op_info = OPERATIONS.get(operation, {})
    estimated_cost = float(op_info.get("cost", 0) or 0)
    usage_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO usage_records(id,user_id,operation,tokens_in,tokens_out,"
        "cost_rmb,estimated_cost_rmb,actual_model_cost_rmb,model_calls,model_names,cost_mode,"
        "credits_used,source,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (usage_id, user_id, operation, tokens_in, tokens_out,
         round(estimated_cost, 5), round(estimated_cost, 5), 0.0, 0, "", "estimated",
         credits_used, source, _now())
    )
    if force_active or _ACTIVE_USAGE_ID.get() is None:
        _ACTIVE_USAGE_ID.set(usage_id)
    return usage_id


def record_model_usage(
    provider: str,
    model: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_rmb: float | None = None,
    *,
    unclassified_input_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    cache_write_5m_tokens: int | None = None,
    cache_write_1h_tokens: int | None = None,
    cache_write_unknown_ttl_tokens: int = 0,
    usage_status: str = "complete",
) -> None:
    """Append one model-call audit row to the current operation.

    Only numeric usage, model identity, and pricing snapshots are stored. The
    model prompt, response, reasoning, and external request identifiers never
    cross this persistence boundary.
    """
    usage_id = _ACTIVE_USAGE_ID.get()
    if not usage_id:
        return
    _record_model_usage_for_usage_id(
        usage_id, provider, model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_rmb=cost_rmb,
        unclassified_input_tokens=unclassified_input_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        cache_write_5m_tokens=cache_write_5m_tokens,
        cache_write_1h_tokens=cache_write_1h_tokens,
        cache_write_unknown_ttl_tokens=cache_write_unknown_ttl_tokens,
        usage_status=usage_status,
    )


def _record_model_usage_for_usage_id(
    usage_id: str,
    provider: str,
    model: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_rmb: float | None = None,
    *,
    unclassified_input_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    cache_write_5m_tokens: int | None = None,
    cache_write_1h_tokens: int | None = None,
    cache_write_unknown_ttl_tokens: int = 0,
    usage_status: str = "complete",
) -> None:
    tokens_in = max(0, int(tokens_in or 0))
    tokens_out = max(0, int(tokens_out or 0))
    unclassified = max(0, int(unclassified_input_tokens or 0))
    cache_read = max(0, int(cache_read_tokens or 0))
    cache_write = max(0, int(cache_write_tokens or 0))
    write_5m = max(0, int(cache_write_5m_tokens or 0))
    write_1h = max(0, int(cache_write_1h_tokens or 0))
    write_unknown = max(0, int(cache_write_unknown_ttl_tokens or 0))
    if cache_write and write_5m + write_1h + write_unknown != cache_write:
        write_unknown = max(0, cache_write - write_5m - write_1h)
        usage_status = "cache_ttl_unknown"
    if unclassified and usage_status == "complete":
        usage_status = "usage_incomplete"
    if usage_status not in {
        "complete", "usage_missing", "usage_incomplete",
        "cache_usage_missing", "cache_ttl_unknown",
    }:
        usage_status = "usage_incomplete"

    pricing = _pricing_snapshot(provider, model)
    pricing_status = str(pricing["pricing_status"])
    currency = str(pricing["currency"])
    fx = float(pricing["usd_cny"])
    currency_factor = fx if currency == "USD" else 1.0

    def dimension_cost(tokens: int, price) -> float:
        if not tokens or price is None:
            return 0.0
        return tokens / 1_000_000 * float(price) * currency_factor

    known_cost = sum((
        dimension_cost(tokens_in, pricing["input"]),
        dimension_cost(cache_read, pricing["cache_read"]),
        dimension_cost(write_5m, pricing["cache_write_5m"]),
        dimension_cost(write_1h, pricing["cache_write_1h"]),
        dimension_cost(tokens_out, pricing["output"]),
    ))
    required_prices = (
        (tokens_in, pricing["input"]),
        (cache_read, pricing["cache_read"]),
        (write_5m, pricing["cache_write_5m"]),
        (write_1h, pricing["cache_write_1h"]),
        (tokens_out, pricing["output"]),
    )
    if any(tokens and price is None for tokens, price in required_prices):
        pricing_status = "unpriced"
    if cost_rmb is not None:
        # Legacy callers may provide a provider-computed amount. Preserve it as
        # known supplier spend, but never promote it to strict model pricing.
        known_cost = max(0.0, float(cost_rmb))
        pricing_status = "manual"
    known_cost = round(known_cost, 9)

    with db.transaction(write=True) as tx:
        lock = " FOR UPDATE" if tx.postgres else ""
        parent = tx.fetchone(
            f"SELECT id,estimated_cost_rmb FROM usage_records WHERE id=?{lock}",
            (usage_id,),
        )
        if not parent:
            return
        tx.execute(
            "INSERT INTO model_usage_records("
            "id,usage_record_id,provider,model,input_tokens,unclassified_input_tokens,"
            "cache_read_input_tokens,cache_write_input_tokens,cache_write_5m_tokens,"
            "cache_write_1h_tokens,cache_write_unknown_ttl_tokens,output_tokens,"
            "input_price_per_1m,cache_read_price_per_1m,cache_write_5m_price_per_1m,"
            "cache_write_1h_price_per_1m,output_price_per_1m,price_currency,usd_cny,"
            "price_version,known_cost_rmb,pricing_status,usage_status,recorded_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(uuid.uuid4()), usage_id, str(provider or "unknown"), str(model or "unknown"),
                tokens_in, unclassified, cache_read, cache_write, write_5m, write_1h,
                write_unknown, tokens_out, pricing["input"], pricing["cache_read"],
                pricing["cache_write_5m"], pricing["cache_write_1h"], pricing["output"],
                currency, fx, pricing["price_version"], known_cost, pricing_status,
                usage_status, _now(),
            ),
        )
        totals = tx.fetchone(
            "SELECT COUNT(*) AS calls, "
            "COALESCE(SUM(input_tokens+unclassified_input_tokens+cache_read_input_tokens+cache_write_input_tokens),0) AS tokens_in, "
            "COALESCE(SUM(output_tokens),0) AS tokens_out, "
            "COALESCE(SUM(known_cost_rmb),0) AS known_cost, "
            "COALESCE(SUM(CASE WHEN pricing_status='exact' THEN 0 ELSE 1 END),0) AS pricing_gaps, "
            "COALESCE(SUM(CASE WHEN usage_status='complete' THEN 0 ELSE 1 END),0) AS usage_gaps, "
            "COALESCE(SUM(CASE WHEN pricing_status='exact' THEN 1 ELSE 0 END),0) AS exact_calls "
            "FROM model_usage_records WHERE usage_record_id=?",
            (usage_id,),
        )
        name_rows = tx.fetchall(
            "SELECT provider,model FROM model_usage_records WHERE usage_record_id=? "
            "GROUP BY provider,model ORDER BY provider,model",
            (usage_id,),
        )
        if int(totals["usage_gaps"] or 0):
            mode = "usage_incomplete"
        elif int(totals["pricing_gaps"] or 0):
            mode = (
                "partial"
                if int(totals["exact_calls"] or 0) or float(totals["known_cost"] or 0) > 0
                else "unpriced"
            )
        else:
            mode = "actual"
        actual_cost = round(float(totals["known_cost"] or 0), 9)
        estimated_cost = float(parent["estimated_cost_rmb"] or 0)
        reported_cost = actual_cost if mode == "actual" or actual_cost > 0 else estimated_cost
        model_names = ",".join(
            f"{row['provider']}:{row['model']}" for row in name_rows
        )
        tx.execute(
            "UPDATE usage_records SET tokens_in=?,tokens_out=?,actual_model_cost_rmb=?,"
            "model_calls=?,model_names=?,cost_mode=?,cost_rmb=? WHERE id=?",
            (
                int(totals["tokens_in"] or 0), int(totals["tokens_out"] or 0), actual_cost,
                int(totals["calls"] or 0), model_names, mode, round(reported_cost, 9), usage_id,
            ),
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
    balance   = round(float(creds_row["balance"] if creds_row else 0.0), 2)
    monthly_limit = round(float(tier_cfg.get("monthly_credits", 0) or 0), 2)
    monthly_used = round(float(sub.get("used_monthly_credits") or 0), 2)
    monthly_remaining = round(max(0.0, monthly_limit - monthly_used), 2)

    operation_costs = {}
    for op in QUOTA_OPS:
        credits = float(OPERATIONS[op]["credits"] or 0)
        operation_costs[op] = {
            "label": OPERATIONS[op]["label"],
            "credits": credits,
            "max_with_monthly": int(monthly_limit // credits) if credits > 0 else 0,
            "max_with_remaining": int(monthly_remaining // credits) if credits > 0 else 0,
        }

    examples = [
        f"AI深度诊断最多 {operation_costs['analyze']['max_with_monthly']} 次",
        f"AI爆文生成最多 {operation_costs['generate']['max_with_monthly']} 次",
        f"对话深度重写最多 {operation_costs['chat_rewrite']['max_with_monthly']} 轮",
        f"截图识别最多 {operation_costs['screenshot']['max_with_monthly']} 张",
    ]
    return {
        "tier":            tier,
        "tier_name":       tier_cfg["name"],
        "price":           tier_cfg["price"],
        "expires_at":      sub["expires_at"],
        "monthly_credits": monthly_limit,
        "monthly_credits_used": monthly_used,
        "monthly_credits_remaining": monthly_remaining,
        "monthly_credits_pct": 0 if monthly_limit <= 0 else min(100, round(monthly_used / monthly_limit * 100)),
        "credits_balance": balance,
        "wallet_credits_balance": balance,
        "total_available_credits": round(monthly_remaining + balance, 2),
        "period_start":    sub["period_start"],
        "operation_costs": operation_costs,
        "usage_examples":  examples,
        "credit_policy":   "优先扣本月套餐积分，不足部分扣充值积分；本月积分每月重置，充值积分长期有效。",
        "quotas":          {},
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
        "SUM(tokens_in) as total_tokens_in, SUM(tokens_out) as total_tokens_out, "
        "SUM(cost_rmb) as total_cost, SUM(credits_used) as total_credits, "
        "SUM(actual_model_cost_rmb) as actual_model_cost, SUM(model_calls) as model_calls "
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
            "tokens_in":     int(r["total_tokens_in"] or 0),
            "tokens_out":    int(r["total_tokens_out"] or 0),
            "total_tokens":  int((r["total_tokens_in"] or 0) + (r["total_tokens_out"] or 0)),
            "cost_rmb":      round(r["total_cost"]    or 0, 4),
            "actual_model_cost_rmb": round(r["actual_model_cost"] or 0, 4),
            "model_calls":   int(r["model_calls"] or 0),
            "credits_used":  round(r["total_credits"]  or 0, 2),
            "is_free":       info.get("free", False),
        }

    total_cost    = sum(v["cost_rmb"]     for v in by_op.values())
    total_credits = sum(v["credits_used"] for v in by_op.values())
    total_tokens_in = sum(v["tokens_in"] for v in by_op.values())
    total_tokens_out = sum(v["tokens_out"] for v in by_op.values())

    # 明细（最近50条）
    detail_rows = db.fetchall(
        "SELECT operation,source,credits_used,cost_rmb,tokens_in,tokens_out,model_calls,model_names,cost_mode,recorded_at,"
        "(SELECT COUNT(*) FROM model_usage_records m WHERE m.usage_record_id=usage_records.id) AS model_detail_count "
        "FROM usage_records WHERE user_id=? AND recorded_at>=? "
        "ORDER BY recorded_at DESC LIMIT 50",
        (user_id, since)
    )
    details = []
    for r in detail_rows:
        op   = r["operation"]
        info = OPERATIONS.get(op, {})
        display_mode = r["cost_mode"] or "estimated"
        if int(r["model_detail_count"] or 0) == 0 and display_mode == "actual":
            display_mode = "legacy_unverifiable_actual"
        details.append({
            "operation":   op,
            "label":       info.get("label", op),
            "source":      r["source"],
            "credits_used": r["credits_used"],
            "cost_rmb":    r["cost_rmb"],
            "tokens_in":   int(r["tokens_in"] or 0),
            "tokens_out":  int(r["tokens_out"] or 0),
            "total_tokens": int((r["tokens_in"] or 0) + (r["tokens_out"] or 0)),
            "model_calls": int(r["model_calls"] or 0),
            "model_names": r["model_names"] or "",
            "cost_mode":   display_mode,
            "model_detail_count": int(r["model_detail_count"] or 0),
            "recorded_at": r["recorded_at"],
        })

    return {
        "period_days":      days,
        "total_api_cost":   round(total_cost, 4),
        "total_tokens_in":  int(total_tokens_in),
        "total_tokens_out": int(total_tokens_out),
        "total_tokens":     int(total_tokens_in + total_tokens_out),
        "total_credits":    round(total_credits, 2),
        "by_operation":     by_op,
        "recent_records":   details,
    }


# 初始化
db.init_db()
