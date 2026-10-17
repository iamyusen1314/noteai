"""Single-user noncash adjustments using NoteAI subscriptions and credit ledger."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException

import admin_operations as operations
import billing
import db


def snapshot(tx, user_id, *, lock=False):
    suffix = " FOR UPDATE" if lock and tx.postgres else ""
    if lock and tx.postgres:
        tx.execute("SELECT public.noteai_admin_lock_user(?)", (user_id,))
    user = tx.fetchone("SELECT id,username,deletion_requested_at FROM users WHERE id=?", (user_id,))
    if not user:
        raise HTTPException(404, "用户不存在")
    if user["deletion_requested_at"]:
        raise HTTPException(409, "该账号已进入删除流程")
    sub = tx.fetchone("SELECT * FROM subscriptions WHERE user_id=? AND is_active=1 ORDER BY started_at DESC LIMIT 1" + suffix, (user_id,))
    wallet = tx.fetchone("SELECT balance FROM credits WHERE user_id=?" + suffix, (user_id,))
    paid = tx.fetchone("SELECT COALESCE(SUM(remaining_milli),0) AS remaining FROM payment_credit_positions WHERE user_id=? AND state='active'", (user_id,))
    noncash = tx.fetchone("SELECT COALESCE(SUM(CASE WHEN type='gift' THEN amount WHEN type='usage' AND amount<0 THEN amount ELSE 0 END),0) AS remaining FROM credit_transactions WHERE user_id=?", (user_id,))
    import postdelivery
    reserved = tx.fetchone("SELECT source FROM usage_records WHERE user_id=? AND SUBSTR(source,1,?)=? LIMIT 1",
                          (user_id,len(postdelivery.PREFIX),postdelivery.PREFIX))
    s = dict(sub) if sub else {}
    return {"user_id": user_id, "username": user["username"], "subscription_id": s.get("id"),
            "tier": s.get("tier"), "expires_at": s.get("expires_at"),
            "period_start": s.get("period_start"), "used_monthly_credits": float(s.get("used_monthly_credits") or 0) if sub else None,
            "wallet_balance": float(wallet["balance"] or 0) if wallet else 0,
            "paid_wallet_reserved": float(paid["remaining"] or 0) / 1000,
            "noncash_recoverable": max(0, float(noncash["remaining"] or 0)),
            "has_credit_reservations": bool(reserved),
            "features": json.loads(s.get("feature_overrides_json") or "{}"),
            "entitlement_source": s.get("entitlement_source", "existing" if sub else "not_initialized")}


def validate(payload):
    action = payload.get("action")
    source = payload.get("source")
    if source not in ("trial", "gift", "compensation"):
        raise HTTPException(422, "请选择试用、免费赠送或运营补偿；此处不发放付费订单")
    if action == "adjust_credits":
        try:
            amount = Decimal(str(payload.get("amount")))
            if not amount.is_finite() or amount == 0 or abs(amount) > 10000 or amount != amount.quantize(Decimal("0.01")):
                raise ValueError()
        except (InvalidOperation, ValueError, TypeError):
            raise HTTPException(422, "积分调整须为非零数字，最多两位小数，单次不超过 10000") from None
        return {"action": action, "source": source, "amount": float(amount)}
    if action == "set_membership":
        tier = payload.get("tier")
        if tier not in billing.TIERS:
            raise HTTPException(422, "套餐不存在")
        if tier == "free":
            return {"action": action, "source": source, "tier": tier,
                    "expires_at": "2099-01-01T00:00:00+00:00"}
        try:
            end = datetime.fromisoformat(str(payload.get("expires_at")).replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            if end.tzinfo is None or not now < end <= now + timedelta(days=3660):
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(422, "请输入带时区的有效截止时间，最长十年") from None
        return {"action": action, "source": source, "tier": tier,
                "expires_at": end.astimezone(timezone.utc).isoformat()}
    if action == "set_features":
        features = payload.get("features")
        if not isinstance(features, dict) or not features or any(k not in billing.OPERATIONS or type(v) is not bool for k, v in features.items()):
            raise HTTPException(422, "功能权限仅接受已有业务操作及启用/停用值")
        return {"action": action, "source": source, "features": features}
    raise HTTPException(422, "不支持的权益操作")


def proposed(before, payload):
    after = {**before, "features": dict(before["features"])}
    if before.get("has_credit_reservations") and (payload["action"] == "set_membership"
            or (payload["action"] == "adjust_credits" and payload["amount"] < 0)):
        raise HTTPException(409, "该账号有任务积分预留，请先完成或释放原任务后再扣回或更改会员")
    if payload["action"] != "adjust_credits" and not before["subscription_id"]:
        raise HTTPException(409, "账号没有有效订阅；可调整独立钱包，会员及功能权限需先完成正常账户权益初始化")
    if payload["action"] == "adjust_credits":
        if payload["amount"] < 0 and -payload["amount"] > before["noncash_recoverable"]:
            raise HTTPException(409, "没有足够可确认未消费的赠送积分；不能扣减付费或来源不明的余额")
        after["wallet_balance"] = round(before["wallet_balance"] + payload["amount"], 2)
        if after["wallet_balance"] < before["paid_wallet_reserved"]:
            raise HTTPException(409, "只能扣回尚未使用的非付费积分；不能动用付费积分或形成负数")
        after["noncash_recoverable"] = max(0, before["noncash_recoverable"] + payload["amount"])
    elif payload["action"] == "set_membership":
        after.update(tier=payload["tier"], expires_at=payload["expires_at"], entitlement_source=payload["source"])
    else:
        after["features"].update(payload["features"])
    return after


def preview(user_id, payload):
    payload = validate(payload)
    with db.transaction() as tx:
        before = snapshot(tx, user_id)
    return {"before": before, "after": proposed(before, payload),
            "expected": operations.fingerprint(before), "payload": payload,
            "notice": "不产生支付订单或现金流水；同等权益使用相同正式业务链，仍受服务开放范围、积分与供应商限流约束。会员调整保留本周期已用额度。"}


def apply(user_id, payload, *, actor, request_id, reason, expected):
    payload = validate(payload)
    def change(tx):
        before = snapshot(tx, user_id, lock=True)
        operations.check_expected(before, expected)
        after = proposed(before, payload)
        now = datetime.now(timezone.utc).isoformat()
        if payload["action"] == "adjust_credits":
            tx.execute("INSERT INTO credits(user_id,balance,updated_at) VALUES(?,0,?) ON CONFLICT(user_id) DO NOTHING", (user_id, now))
            tx.execute("UPDATE credits SET balance=?,updated_at=? WHERE user_id=?", (after["wallet_balance"], now, user_id))
            tx.execute("INSERT INTO credit_transactions(id,user_id,type,amount,balance_after,description,recorded_at) VALUES(?,?,?,?,?,?,?)",
                       (request_id, user_id, "gift", payload["amount"], after["wallet_balance"],
                        f"{payload['source']} / {actor} / {reason}", now))
        elif payload["action"] == "set_membership":
            tx.execute("UPDATE subscriptions SET tier=?,expires_at=?,entitlement_source=? WHERE id=?",
                       (after["tier"], after["expires_at"], payload["source"], before["subscription_id"]))
        else:
            tx.execute("UPDATE subscriptions SET feature_overrides_json=? WHERE id=?", (operations.encode(after["features"]), before["subscription_id"]))
        return before, snapshot(tx, user_id)
    return operations.execute(actor=actor, request_id=request_id, action="entitlement:" + payload["action"],
                              target=user_id, reason=reason, payload={**payload, "expected": expected}, callback=change)
