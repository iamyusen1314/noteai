"""Bounded owner-triggered JSAPI recovery on the existing API/Payment split.

Only API performs outbound merchant-signed requests. Payment independently
authenticates the original provider receipt before changing the existing ledger.
Neither local time nor a close acknowledgement permits a replacement order.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hmac
import json
import re

import httpx

import db
import payment_contract as payment


COOLDOWN_SECONDS = 15
RECEIPT_BYTES = 96 * 1024
RELAY_TARGET = "http://127.0.0.1:8002/internal/payments/wechat/query-receipt"
_UUID = re.compile(r"^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$")


class ReconciliationError(RuntimeError):
    def __init__(self, code, status=503, retry_after=None):
        self.code, self.status, self.retry_after = code, status, retry_after
        super().__init__(code)


def _admit(user_id, order_id, app_id, clock):
    if not isinstance(order_id, str) or not _UUID.fullmatch(order_id):
        raise ReconciliationError("PAYMENT_ORDER_NOT_FOUND", 404)
    epoch = int(clock.timestamp())
    with db.transaction(write=True) as tx:
        try:
            payment._payment_user_fence(tx, user_id)
        except (ValueError, payment.PaymentContractError):
            raise ReconciliationError("PAYMENT_ACCOUNT_NOT_WRITABLE", 403) from None
        row = tx.fetchone(
            "SELECT * FROM payment_orders WHERE id=? AND user_id=?"
            + (" FOR UPDATE" if tx.postgres else ""), (order_id, user_id))
        if row is None:
            raise ReconciliationError("PAYMENT_ORDER_NOT_FOUND", 404)
        if (row["provider"] != "wechatpay_direct" or row["provider_mode"] != "live"
                or row["wechat_jsapi_payer_hash"] is None
                or not hmac.compare_digest(str(row["app_id_hash"]),
                    payment._app_id_hash(app_id, "wechatpay_direct"))):
            raise ReconciliationError("PAYMENT_JSAPI_ORDER_REQUIRED", 409)
        if row["payment_status"] in {"succeeded", "failed", "closed"}:
            return dict(row), False
        if row["payment_status"] != "pending" or row["refund_status"] != "none":
            raise ReconciliationError("PAYMENT_ORDER_REQUIRES_REVIEW", 409)
        last = row["wechat_jsapi_last_query_at"]
        if last is not None and epoch < int(last) + COOLDOWN_SECONDS:
            raise ReconciliationError("PAYMENT_QUERY_COOLDOWN", 429,
                                      int(last) + COOLDOWN_SECONDS - epoch)
        tx.execute("UPDATE payment_orders SET wechat_jsapi_last_query_at=? "
                   "WHERE id=? AND user_id=?", (epoch, order_id, user_id))
        return dict(row), True


def relay_receipt(user_id, order_id, receipt):
    # Fixed same-netns loopback target, no authentication secret or provider
    # private key is shared. Payment verifies the WeChat signature itself.
    body = json.dumps({"user_id": user_id, "order_id": order_id, "receipt": receipt},
                      separators=(",", ":"), allow_nan=False).encode()
    if len(body) > RECEIPT_BYTES:
        raise ReconciliationError("PAYMENT_QUERY_RECEIPT_INVALID")
    try:
        with httpx.Client(timeout=httpx.Timeout(connect=2, read=10, write=5, pool=2),
                          follow_redirects=False, trust_env=False) as client:
            with client.stream("POST", RELAY_TARGET, content=body,
                               headers={"Content-Type": "application/json"}) as response:
                raw = bytearray()
                for chunk in response.iter_bytes():
                    if len(raw) + len(chunk) > 8192:
                        raise ValueError
                    raw.extend(chunk)
                if (str(response.url) != RELAY_TARGET or response.status_code != 200
                        or response.headers.get("content-type", "").split(";", 1)[0] != "application/json"):
                    raise ValueError
                result = json.loads(raw)
        if not isinstance(result, dict) or result.get("ok") is not True or result.get("code"):
            raise ValueError
    except Exception:
        raise ReconciliationError("PAYMENT_QUERY_RESULT_UNCONFIRMED") from None


def reconcile(*, user_id, order_id, app_id, provider, close_unpaid=False,
              relay=None, now=None):
    if type(close_unpaid) is not bool:
        raise ReconciliationError("PAYMENT_QUERY_REQUEST_INVALID", 400)
    clock = now or datetime.now(timezone.utc)
    row, admitted = _admit(user_id, order_id, app_id, clock)
    if not admitted:
        return {"order": payment.get_order_for_user(order_id, user_id)}
    lookup = payment.ProviderPaymentLookup(
        merchant_order_no=row["merchant_order_no"],
        provider_payment_id=row["provider_payment_id"] or "",
        expected_amount_fen=int(row["amount_fen"]))
    deliver = relay or relay_receipt
    try:
        receipt = provider.export_payment_query_receipt(lookup)
        deliver(user_id, order_id, receipt)
        updated = payment.get_order_for_user(order_id, user_id)
        if updated is None:
            raise ReconciliationError("PAYMENT_ORDER_NOT_FOUND", 404)
        if close_unpaid and updated["payment_status"] == "pending":
            # Export already verifies this response in API. The independent
            # Payment verification above must succeed before a close is sent.
            raw = base64.b64decode(receipt["body_b64"], validate=True)
            if len(raw) > 64 * 1024:
                raise ValueError
            data = json.loads(raw)
            if (data.get("trade_state") == "NOTPAY"
                    and data.get("trade_type", "") in {"", "JSAPI"}
                    and not data.get("transaction_id") and not data.get("success_time")):
                provider.close_unpaid_payment(lookup)
                # A close 204 is never the local terminal proof. Re-query once;
                # any timeout or still-NOTPAY result keeps the original order.
                deliver(user_id, order_id, provider.export_payment_query_receipt(lookup))
                updated = payment.get_order_for_user(order_id, user_id)
        if updated is None:
            raise ReconciliationError("PAYMENT_ORDER_NOT_FOUND", 404)
        return {"order": updated}
    except ReconciliationError:
        raise
    except Exception:
        # Admission remains consumed across disconnects and unknown closes;
        # this path never calls create_payment or infers a local failure.
        raise ReconciliationError("PAYMENT_QUERY_RESULT_UNCONFIRMED") from None
