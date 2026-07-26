"""Provider-isolated, integer-money payment and reconciliation contract.

This module contains no network adapter and selects no provider by environment.
Production entry points therefore fail closed until a separately reviewed
adapter is injected. Callback bodies are verified before any database write
and are never persisted.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

import billing
import content_retention
import db


CONTRACT_VERSION = "adapay-v1-2026-07-26"
CATALOG_VERSION = "first-launch-v1-2026-07-26"
MAX_CALLBACK_DATA_BYTES = 32 * 1024
MAX_SIGNATURE_BYTES = 1024
MAX_RECONCILIATION_ROWS = 10000
MAX_RECONCILIATION_SOURCE_BYTES = 32 * 1024 * 1024

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}$"
)
_OPAQUE_REF_RE = re.compile(r"^[A-Za-z0-9_:-]{1,128}$")
_APP_ID_RE = re.compile(r"^[A-Za-z0-9_:-]{3,64}$")
_IDEMPOTENCY_RE = re.compile(r"^[\x21-\x7e]{8,128}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MONEY_RE = re.compile(r"^(0|[1-9][0-9]{0,10})\.[0-9]{2}$")

CATALOG: dict[tuple[str, str], dict[str, Any]] = {
    ("subscription", "pro"): {
        "amount_fen": 9900,
        "entitlement_milli": 260000,
        "duration_days": 30,
    },
    ("subscription", "growth"): {
        "amount_fen": 19900,
        "entitlement_milli": 560000,
        "duration_days": 30,
    },
    ("subscription", "pro_plus"): {
        "amount_fen": 29900,
        "entitlement_milli": 900000,
        "duration_days": 30,
    },
    ("subscription", "studio"): {
        "amount_fen": 39900,
        "entitlement_milli": 1250000,
        "duration_days": 30,
    },
    ("credit_package", "starter"): {
        "amount_fen": 1200,
        "entitlement_milli": 30000,
        "duration_days": 0,
    },
    ("credit_package", "creator"): {
        "amount_fen": 3900,
        "entitlement_milli": 100000,
        "duration_days": 0,
    },
    ("credit_package", "growth"): {
        "amount_fen": 10900,
        "entitlement_milli": 300000,
        "duration_days": 0,
    },
    ("credit_package", "studio"): {
        "amount_fen": 27900,
        "entitlement_milli": 800000,
        "duration_days": 0,
    },
}

PAYMENT_EVENT_TYPES = frozenset(
    {
        "payment.succeeded",
        "payment.failed",
        "payment.close.succeeded",
        "payment.close.failed",
        "refund.succeeded",
        "refund.failed",
    }
)


class PaymentContractError(RuntimeError):
    """Stable error with no provider payload or user content."""

    def __init__(self, code: str):
        self.code = str(code)
        super().__init__(self.code)


class PaymentProviderUnavailable(PaymentContractError):
    def __init__(self):
        super().__init__("PAYMENT_PROVIDER_UNAVAILABLE")


@dataclass(frozen=True)
class ProviderPaymentResult:
    merchant_order_no: str
    provider_payment_id: str
    status: str
    amount_fen: int
    app_id: str
    prod_mode: bool
    response_verified: bool
    checkout_token: str = ""


@dataclass(frozen=True)
class ProviderRefundResult:
    merchant_refund_no: str
    provider_refund_id: str
    status: str
    amount_fen: int
    response_verified: bool


class PaymentProvider(ABC):
    """Injected provider boundary; implementations own all network behavior."""

    @abstractmethod
    def create_payment(self, order: dict[str, Any]) -> ProviderPaymentResult:
        raise NotImplementedError

    @abstractmethod
    def query_payment(self, provider_payment_id: str) -> ProviderPaymentResult:
        raise NotImplementedError

    @abstractmethod
    def create_refund(self, refund: dict[str, Any]) -> ProviderRefundResult:
        raise NotImplementedError

    @abstractmethod
    def query_refund(self, provider_refund_id: str) -> ProviderRefundResult:
        raise NotImplementedError

    @abstractmethod
    def reconciliation_rows(
        self,
        bill_date: str,
    ) -> tuple[bytes, Iterable[dict[str, Any]]]:
        raise NotImplementedError


class UnavailablePaymentProvider(PaymentProvider):
    def _fail(self):
        raise PaymentProviderUnavailable()

    def create_payment(self, _order):
        return self._fail()

    def query_payment(self, _provider_payment_id):
        return self._fail()

    def create_refund(self, _refund):
        return self._fail()

    def query_refund(self, _provider_refund_id):
        return self._fail()

    def reconciliation_rows(self, _bill_date):
        return self._fail()


_PROVIDER: PaymentProvider = UnavailablePaymentProvider()


def configure_provider(provider: PaymentProvider) -> None:
    """Inject an explicitly constructed adapter; environment never selects it."""
    if not isinstance(provider, PaymentProvider):
        raise TypeError("provider must implement PaymentProvider")
    global _PROVIDER
    _PROVIDER = provider


def reset_provider() -> None:
    global _PROVIDER
    _PROVIDER = UnavailablePaymentProvider()


def provider() -> PaymentProvider:
    return _PROVIDER


def provider_payment_request(row: Any) -> dict[str, Any]:
    """Return the only order fields an injected provider adapter may receive."""
    return {
        "merchant_order_no": str(row["merchant_order_no"]),
        "amount_fen": int(row["amount_fen"]),
        "currency": str(row["currency"]),
        "product_kind": str(row["product_kind"]),
        "product_id": str(row["product_id"]),
        "provider_mode": str(row["provider_mode"]),
    }


def provider_refund_request(refund: Any, order: Any) -> dict[str, Any]:
    """Return the minimized full-refund request; never include an account id."""
    return {
        "merchant_refund_no": str(refund["merchant_refund_no"]),
        "merchant_order_no": str(order["merchant_order_no"]),
        "provider_payment_id": str(order["provider_payment_id"]),
        "amount_fen": int(refund["amount_fen"]),
        "currency": str(refund["currency"]),
        "provider_mode": str(order["provider_mode"]),
        "reason_code": str(refund["reason_code"]),
    }


@dataclass(frozen=True)
class CallbackEvent:
    provider_event_id: str
    event_type: str
    created_time: int
    prod_mode: bool
    app_id: str
    data: dict[str, Any]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).astimezone(timezone.utc).isoformat()


def _uuid(value: str, field: str = "id") -> str:
    normalized = str(value or "").strip().lower()
    if not _UUID_RE.fullmatch(normalized):
        raise PaymentContractError(f"PAYMENT_INVALID_{field.upper()}")
    return normalized


def _opaque_ref(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not _OPAQUE_REF_RE.fullmatch(normalized):
        raise PaymentContractError(f"PAYMENT_INVALID_{field.upper()}")
    return normalized


def _app_id(value: Any) -> str:
    normalized = str(value or "").strip()
    if not _APP_ID_RE.fullmatch(normalized):
        raise PaymentContractError("PAYMENT_INVALID_APP_ID")
    return normalized


def _hash(domain: str, value: str | bytes) -> str:
    body = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(domain.encode("ascii") + b"\0" + body).hexdigest()


def _subject_hash(user_id: str) -> str:
    return _hash("noteai-payment-subject-v1", user_id)


def _app_id_hash(app_id: str) -> str:
    return _hash("noteai-adapay-app-v1", app_id)


def _lock_financial_subject(
    tx: db.Transaction,
    user_id: str | None,
) -> None:
    """Take the canonical user fence before lower-level payment row locks."""
    if not user_id:
        return
    try:
        content_retention.lock_user_write_fence_with_storage(
            tx,
            str(user_id),
            allow_deletion_requested=True,
        )
    except ValueError:
        # A completed deletion can remove the user while preserving immutable
        # financial rows. The callback must still record cash truth and route
        # entitlement handling to manual review.
        return


def _credits(milli: int) -> float:
    return round(int(milli) / 1000, 3)


def _fen_to_rmb(fen: int) -> float:
    return round(int(fen) / 100, 2)


def _catalog_item(product_kind: str, product_id: str) -> dict[str, Any]:
    kind = str(product_kind or "").strip()
    item_id = str(product_id or "").strip()
    item = CATALOG.get((kind, item_id))
    if item is None:
        raise PaymentContractError("PAYMENT_UNKNOWN_PRODUCT")
    return {
        "product_kind": kind,
        "product_id": item_id,
        **item,
    }


def assert_catalog_matches_billing() -> None:
    """Fail if visible pricing drifts from the immutable payment catalogue."""
    for (kind, item_id), item in CATALOG.items():
        if kind == "subscription":
            visible = billing.TIERS.get(item_id)
            if (
                visible is None
                or int(visible["price"] * 100) != item["amount_fen"]
                or int(visible["monthly_credits"] * 1000)
                != item["entitlement_milli"]
            ):
                raise PaymentContractError("PAYMENT_CATALOG_DRIFT")
        else:
            visible = billing.CREDIT_PACKAGES.get(item_id)
            if (
                visible is None
                or int(round(visible["price_rmb"] * 100))
                != item["amount_fen"]
                or int(round(visible["credits"] * 1000))
                != item["entitlement_milli"]
            ):
                raise PaymentContractError("PAYMENT_CATALOG_DRIFT")


def _read_der_length(data: bytes, offset: int) -> tuple[int, int]:
    if offset >= len(data):
        raise ValueError("DER length missing")
    first = data[offset]
    offset += 1
    if first < 0x80:
        return first, offset
    count = first & 0x7F
    if count == 0 or count > 4 or offset + count > len(data):
        raise ValueError("DER length invalid")
    if data[offset] == 0:
        raise ValueError("DER length noncanonical")
    length = int.from_bytes(data[offset : offset + count], "big")
    if length < 0x80:
        raise ValueError("DER length noncanonical")
    return length, offset + count


def _read_der_tlv(
    data: bytes,
    offset: int,
    expected_tag: int | None = None,
) -> tuple[int, bytes, int]:
    if offset >= len(data):
        raise ValueError("DER value missing")
    tag = data[offset]
    length, body_start = _read_der_length(data, offset + 1)
    end = body_start + length
    if end > len(data):
        raise ValueError("DER value truncated")
    if expected_tag is not None and tag != expected_tag:
        raise ValueError("DER tag invalid")
    return tag, data[body_start:end], end


def _der_integer(body: bytes) -> int:
    if not body or body[0] & 0x80:
        raise ValueError("DER integer invalid")
    if len(body) > 1 and body[0] == 0 and body[1] < 0x80:
        raise ValueError("DER integer noncanonical")
    return int.from_bytes(body, "big")


def _rsa_public_numbers(public_key_pem: str) -> tuple[int, int]:
    text = str(public_key_pem or "").strip()
    match = re.fullmatch(
        r"-----BEGIN (PUBLIC KEY|RSA PUBLIC KEY)-----\s+"
        r"([A-Za-z0-9+/=\s]+)"
        r"-----END \1-----",
        text,
    )
    if not match:
        raise ValueError("public key PEM invalid")
    try:
        der = base64.b64decode(
            re.sub(r"\s+", "", match.group(2)),
            validate=True,
        )
    except (ValueError, binascii.Error) as exc:
        raise ValueError("public key PEM invalid") from exc
    _tag, root, end = _read_der_tlv(der, 0, 0x30)
    if end != len(der):
        raise ValueError("public key DER trailing data")
    if match.group(1) == "PUBLIC KEY":
        _alg_tag, _algorithm, offset = _read_der_tlv(root, 0, 0x30)
        if _algorithm != bytes.fromhex("06092a864886f70d0101010500"):
            raise ValueError("public key algorithm invalid")
        _bit_tag, bit_string, offset = _read_der_tlv(root, offset, 0x03)
        if offset != len(root) or not bit_string or bit_string[0] != 0:
            raise ValueError("public key SPKI invalid")
        _key_tag, key_body, key_end = _read_der_tlv(bit_string[1:], 0, 0x30)
        if key_end != len(bit_string) - 1:
            raise ValueError("public key SPKI trailing data")
    else:
        key_body = root
    _n_tag, n_body, offset = _read_der_tlv(key_body, 0, 0x02)
    _e_tag, e_body, offset = _read_der_tlv(key_body, offset, 0x02)
    if offset != len(key_body):
        raise ValueError("public key RSA trailing data")
    modulus = _der_integer(n_body)
    exponent = _der_integer(e_body)
    if not (1024 <= modulus.bit_length() <= 4096):
        raise ValueError("public key RSA size invalid")
    if exponent < 3 or exponent % 2 == 0:
        raise ValueError("public key RSA exponent invalid")
    return modulus, exponent


def verify_adapay_signature(
    data: str | bytes,
    signature_b64: str,
    public_key_pem: str,
) -> bool:
    """Verify Adapay SHA1withRSA/PKCS#1 v1.5 over the exact callback data."""
    body = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    if not body or len(body) > MAX_CALLBACK_DATA_BYTES:
        return False
    signature_text = str(signature_b64 or "").strip()
    if not signature_text or len(signature_text) > MAX_SIGNATURE_BYTES * 2:
        return False
    try:
        signature = base64.b64decode(signature_text, validate=True)
        modulus, exponent = _rsa_public_numbers(public_key_pem)
    except (ValueError, binascii.Error):
        return False
    key_bytes = (modulus.bit_length() + 7) // 8
    if len(signature) != key_bytes:
        return False
    signature_integer = int.from_bytes(signature, "big")
    if signature_integer >= modulus:
        return False
    encoded = pow(signature_integer, exponent, modulus).to_bytes(
        key_bytes,
        "big",
    )
    digest_info = (
        bytes.fromhex("3021300906052b0e03021a05000414")
        + hashlib.sha1(body).digest()
    )
    padding_length = key_bytes - len(digest_info) - 3
    if padding_length < 8:
        return False
    expected = b"\x00\x01" + b"\xff" * padding_length + b"\x00" + digest_info
    return hmac.compare_digest(encoded, expected)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PaymentContractError("PAYMENT_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def parse_callback_event(data: str | bytes) -> CallbackEvent:
    body = data.decode("utf-8") if isinstance(data, bytes) else str(data or "")
    if not body or len(body.encode("utf-8")) > MAX_CALLBACK_DATA_BYTES:
        raise PaymentContractError("PAYMENT_CALLBACK_SIZE_INVALID")
    try:
        raw = json.loads(body, object_pairs_hook=_unique_object)
    except PaymentContractError:
        raise
    except (TypeError, ValueError, UnicodeError) as exc:
        raise PaymentContractError("PAYMENT_CALLBACK_JSON_INVALID") from exc
    if not isinstance(raw, dict):
        raise PaymentContractError("PAYMENT_CALLBACK_JSON_INVALID")
    event_id = _opaque_ref(raw.get("id"), "event_id")
    event_type = str(raw.get("type") or "").strip()
    if len(event_type) < 3 or len(event_type) > 64:
        raise PaymentContractError("PAYMENT_INVALID_EVENT_TYPE")
    created = raw.get("created_time")
    if isinstance(created, bool):
        raise PaymentContractError("PAYMENT_INVALID_EVENT_CLOCK")
    try:
        created_time = int(str(created))
    except (TypeError, ValueError) as exc:
        raise PaymentContractError("PAYMENT_INVALID_EVENT_CLOCK") from exc
    if created_time < 946684800 or created_time > 4102444800:
        raise PaymentContractError("PAYMENT_INVALID_EVENT_CLOCK")
    prod_raw = raw.get("prod_mode")
    if (
        prod_raw is True
        or prod_raw in ("true", "True", "1")
        or (type(prod_raw) is int and prod_raw == 1)
    ):
        prod_mode = True
    elif (
        prod_raw is False
        or prod_raw in ("false", "False", "0")
        or (type(prod_raw) is int and prod_raw == 0)
    ):
        prod_mode = False
    else:
        raise PaymentContractError("PAYMENT_INVALID_PROVIDER_MODE")
    app_id = _app_id(raw.get("app_id"))
    event_data = raw.get("data")
    if isinstance(event_data, str):
        try:
            event_data = json.loads(
                event_data,
                object_pairs_hook=_unique_object,
            )
        except PaymentContractError:
            raise
        except (TypeError, ValueError) as exc:
            raise PaymentContractError("PAYMENT_EVENT_DATA_INVALID") from exc
    if not isinstance(event_data, dict):
        raise PaymentContractError("PAYMENT_EVENT_DATA_INVALID")
    return CallbackEvent(
        provider_event_id=event_id,
        event_type=event_type,
        created_time=created_time,
        prod_mode=prod_mode,
        app_id=app_id,
        data=event_data,
    )


def _money_fen(value: Any, field: str) -> int:
    normalized = str(value or "").strip()
    if not _MONEY_RE.fullmatch(normalized):
        raise PaymentContractError(f"PAYMENT_INVALID_{field.upper()}")
    whole, decimal = normalized.split(".", 1)
    fen = int(whole) * 100 + int(decimal)
    if fen <= 0 or fen > 100_000_000:
        raise PaymentContractError(f"PAYMENT_INVALID_{field.upper()}")
    return fen


def _event_payment(event: CallbackEvent) -> dict[str, Any]:
    payload = event.data
    return {
        "merchant_order_no": _opaque_ref(
            payload.get("order_no"),
            "merchant_order_no",
        ),
        "provider_payment_id": _opaque_ref(
            payload.get("payment_id") or payload.get("id"),
            "provider_payment_id",
        ),
        "amount_fen": _money_fen(payload.get("pay_amt"), "pay_amt"),
    }


def _event_refund(event: CallbackEvent) -> dict[str, Any]:
    payload = event.data
    return {
        "merchant_refund_no": _opaque_ref(
            payload.get("refund_order_no"),
            "merchant_refund_no",
        ),
        "provider_refund_id": _opaque_ref(
            payload.get("refund_id") or payload.get("id"),
            "provider_refund_id",
        ),
        "provider_payment_id": _opaque_ref(
            payload.get("payment_id"),
            "provider_payment_id",
        ),
        "amount_fen": _money_fen(payload.get("refund_amt"), "refund_amt"),
    }


def create_order(
    user_id: str,
    product_kind: str,
    product_id: str,
    *,
    idempotency_key: str,
    app_id: str,
    prod_mode: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create one local intent; no provider request is made."""
    assert_catalog_matches_billing()
    item = _catalog_item(product_kind, product_id)
    key = str(idempotency_key or "")
    if not _IDEMPOTENCY_RE.fullmatch(key):
        raise PaymentContractError("PAYMENT_IDEMPOTENCY_KEY_INVALID")
    uid = str(user_id or "").strip()
    if not uid:
        raise PaymentContractError("PAYMENT_USER_REQUIRED")
    expected_app = _app_id(app_id)
    key_hash = _hash("noteai-payment-idempotency-v1", key)
    payload_hash = _hash(
        "noteai-payment-order-payload-v1",
        "|".join(
            (
                uid,
                item["product_kind"],
                item["product_id"],
                str(item["amount_fen"]),
                expected_app,
                "live" if prod_mode else "mock",
            )
        ),
    )
    created = _iso(now)
    order_id = str(uuid.uuid4())
    merchant_order_no = "NA_" + order_id.replace("-", "")
    with db.transaction(write=True) as tx:
        try:
            content_retention.assert_user_writable_with_storage(tx, uid)
        except ValueError as exc:
            raise PaymentContractError("PAYMENT_ACCOUNT_NOT_WRITABLE") from exc
        existing = tx.fetchone(
            "SELECT * FROM payment_orders WHERE user_id=? "
            "AND idempotency_key_hash=?",
            (uid, key_hash),
        )
        if existing is not None:
            if existing["request_hash"] != payload_hash:
                raise PaymentContractError("PAYMENT_IDEMPOTENCY_CONFLICT")
            return _public_order(existing)
        if item["product_kind"] == "subscription":
            paid = tx.fetchone(
                "SELECT id,expires_at FROM subscriptions "
                "WHERE user_id=? AND is_active=1 "
                "AND tier<>'free' LIMIT 1"
                + (" FOR UPDATE" if tx.postgres else ""),
                (uid,),
            )
            if paid is not None:
                try:
                    expires = datetime.fromisoformat(
                        str(paid["expires_at"]).replace("Z", "+00:00")
                    )
                    if expires.tzinfo is None:
                        expires = expires.replace(tzinfo=timezone.utc)
                    expired = expires.astimezone(
                        timezone.utc
                    ) <= datetime.fromisoformat(created)
                except (TypeError, ValueError):
                    expired = False
                if not expired:
                    raise PaymentContractError(
                        "PAYMENT_ACTIVE_SUBSCRIPTION_REQUIRES_MANUAL"
                    )
                tx.execute(
                    "UPDATE subscriptions SET is_active=0 "
                    "WHERE id=? AND is_active=1",
                    (paid["id"],),
                )
        tx.execute(
            "INSERT INTO payment_orders("
            "id,user_id,subject_hash,product_kind,product_id,catalog_version,"
            "amount_fen,currency,provider,provider_mode,merchant_order_no,"
            "app_id_hash,idempotency_key_hash,request_hash,payment_status,"
            "entitlement_status,refund_status,refunded_fen,refund_count,"
            "created_at,updated_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
            "'created','pending','none',0,0,?,?)",
            (
                order_id,
                uid,
                _subject_hash(uid),
                item["product_kind"],
                item["product_id"],
                CATALOG_VERSION,
                item["amount_fen"],
                "CNY",
                "adapay",
                "live" if prod_mode else "mock",
                merchant_order_no,
                _app_id_hash(expected_app),
                key_hash,
                payload_hash,
                created,
                created,
            ),
        )
        row = tx.fetchone("SELECT * FROM payment_orders WHERE id=?", (order_id,))
    return _public_order(row)


def _public_order(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "product_kind": row["product_kind"],
        "product_id": row["product_id"],
        "amount_fen": int(row["amount_fen"]),
        "currency": row["currency"],
        "provider_mode": row["provider_mode"],
        "payment_status": row["payment_status"],
        "entitlement_status": row["entitlement_status"],
        "refund_status": row["refund_status"],
        "refunded_fen": int(row["refunded_fen"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_order_for_user(order_id: str, user_id: str) -> dict[str, Any] | None:
    normalized = _uuid(order_id, "order_id")
    row = db.fetchone(
        "SELECT * FROM payment_orders WHERE id=? AND user_id=?",
        (normalized, str(user_id or "")),
    )
    return _public_order(row) if row is not None else None


def list_orders_for_user(user_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    bounded = max(1, min(int(limit), 50))
    rows = db.fetchall(
        "SELECT * FROM payment_orders WHERE user_id=? "
        "ORDER BY created_at DESC LIMIT ?",
        (str(user_id or ""), bounded),
    )
    return [_public_order(row) for row in rows]


def admit_payment_submission(
    order_id: str,
    *,
    now: datetime | None = None,
) -> bool:
    """Atomically reserve the sole provider-submission attempt for an order."""
    normalized = _uuid(order_id, "order_id")
    clock = _iso(now)
    with db.transaction(write=True) as tx:
        row = tx.fetchone(
            "SELECT id FROM payment_orders WHERE id=?"
            + (" FOR UPDATE" if tx.postgres else ""),
            (normalized,),
        )
        if row is None:
            raise PaymentContractError("PAYMENT_ORDER_NOT_FOUND")
        cursor = tx.execute(
            "UPDATE payment_orders SET payment_status='pending',updated_at=? "
            "WHERE id=? AND payment_status='created' "
            "AND provider_payment_id IS NULL",
            (clock, normalized),
        )
        admitted = int(getattr(cursor, "rowcount", 0) or 0) == 1
    return admitted


def mark_payment_submission(
    order_id: str,
    result: ProviderPaymentResult,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Record a verified synchronous response; never grant entitlement."""
    normalized = _uuid(order_id, "order_id")
    if not result.response_verified:
        raise PaymentContractError("PAYMENT_PROVIDER_RESPONSE_UNVERIFIED")
    provider_payment_id = _opaque_ref(
        result.provider_payment_id,
        "provider_payment_id",
    )
    created = _iso(now)
    mismatch = False
    with db.transaction(write=True) as tx:
        row = tx.fetchone(
            "SELECT * FROM payment_orders WHERE id=?"
            + (" FOR UPDATE" if tx.postgres else ""),
            (normalized,),
        )
        if row is None:
            raise PaymentContractError("PAYMENT_ORDER_NOT_FOUND")
        expected = (
            result.merchant_order_no == row["merchant_order_no"]
            and int(result.amount_fen) == int(row["amount_fen"])
            and _app_id_hash(_app_id(result.app_id)) == row["app_id_hash"]
            and bool(result.prod_mode) == (row["provider_mode"] == "live")
            and (
                not row["provider_payment_id"]
                or result.provider_payment_id == row["provider_payment_id"]
            )
        )
        if not expected or result.status not in {"pending", "succeeded"}:
            tx.execute(
                "UPDATE payment_orders SET payment_status='needs_manual',"
                "updated_at=?,terminal_at=? WHERE id=? "
                "AND payment_status IN ('created','pending')",
                (created, created, normalized),
            )
            mismatch = True
        else:
            tx.execute(
                "UPDATE payment_orders SET provider_payment_id=?,"
                "payment_status='pending',updated_at=? WHERE id=? "
                "AND payment_status IN ('created','pending') "
                "AND provider_payment_id IS NULL",
                (provider_payment_id, created, normalized),
            )
        updated = tx.fetchone("SELECT * FROM payment_orders WHERE id=?", (normalized,))
    if mismatch:
        raise PaymentContractError("PAYMENT_PROVIDER_RESPONSE_MISMATCH")
    return _public_order(updated)


def mark_payment_submission_unknown(
    order_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized = _uuid(order_id, "order_id")
    clock = _iso(now)
    with db.transaction(write=True) as tx:
        tx.execute(
            "UPDATE payment_orders SET payment_status='needs_manual',"
            "updated_at=?,terminal_at=? WHERE id=? "
            "AND payment_status IN ('created','pending')",
            (clock, clock, normalized),
        )
        row = tx.fetchone("SELECT * FROM payment_orders WHERE id=?", (normalized,))
    if row is None:
        raise PaymentContractError("PAYMENT_ORDER_NOT_FOUND")
    return _public_order(row)


def _insert_cash(
    tx: db.Transaction,
    *,
    order_id: str,
    refund_id: str | None,
    entry_type: str,
    amount_fen: int,
    source_event_id: str,
    clock: str,
) -> bool:
    cursor = tx.execute(
        "INSERT INTO payment_cash_ledger("
        "id,order_id,refund_id,entry_type,amount_fen,currency,"
        "source_event_id,recorded_at"
        ") VALUES(?,?,?,?,?,'CNY',?,?) ON CONFLICT DO NOTHING",
        (
            str(uuid.uuid4()),
            order_id,
            refund_id,
            entry_type,
            amount_fen,
            source_event_id,
            clock,
        ),
    )
    return int(getattr(cursor, "rowcount", 0) or 0) == 1


def _apply_credit_entitlement(
    tx: db.Transaction,
    row: Any,
    event_row_id: str,
    clock: str,
) -> str:
    user_id = row["user_id"]
    if not user_id:
        raise PaymentContractError("PAYMENT_ENTITLEMENT_ACCOUNT_MISSING")
    item = _catalog_item(row["product_kind"], row["product_id"])
    milli = int(item["entitlement_milli"])
    amount = _credits(milli)
    content_retention.assert_user_writable_with_storage(tx, user_id)
    tx.execute(
        "INSERT INTO credits(user_id,balance,total_purchased,total_used,updated_at) "
        "VALUES(?,0,0,0,?) ON CONFLICT(user_id) DO NOTHING",
        (user_id, clock),
    )
    tx.execute(
        "UPDATE credits SET balance=balance+?,"
        "total_purchased=total_purchased+?,updated_at=? WHERE user_id=?",
        (amount, amount, clock, user_id),
    )
    balance = float(
        tx.fetchone(
            "SELECT balance FROM credits WHERE user_id=?",
            (user_id,),
        )["balance"]
    )
    tx.execute(
        "INSERT INTO credit_transactions("
        "id,user_id,type,amount,balance_after,description,paid_rmb,"
        "package_id,payment_ref,recorded_at"
        ") VALUES(?,?,'topup',?,?,?, ?,?,?,?)",
        (
            str(uuid.uuid4()),
            user_id,
            amount,
            balance,
            "支付确认：积分包",
            _fen_to_rmb(int(row["amount_fen"])),
            row["product_id"],
            row["id"],
            clock,
        ),
    )
    tx.execute(
        "INSERT INTO payment_credit_positions("
        "order_id,user_id,subject_hash,granted_milli,remaining_milli,state,"
        "created_at,updated_at"
        ") VALUES(?,?,?,?,?,'active',?,?)",
        (
            row["id"],
            user_id,
            row["subject_hash"],
            milli,
            milli,
            clock,
            clock,
        ),
    )
    ledger_id = str(uuid.uuid4())
    tx.execute(
        "INSERT INTO payment_entitlement_ledger("
        "id,order_id,refund_id,entry_type,product_kind,product_id,"
        "quantity_milli,subscription_id,source_event_id,recorded_at"
        ") VALUES(?,?,NULL,'credit_grant',?,?,?,NULL,?,?)",
        (
            ledger_id,
            row["id"],
            row["product_kind"],
            row["product_id"],
            milli,
            event_row_id,
            clock,
        ),
    )
    return ledger_id


def _apply_subscription_entitlement(
    tx: db.Transaction,
    row: Any,
    event_row_id: str,
    clock: str,
) -> str:
    user_id = row["user_id"]
    if not user_id:
        raise PaymentContractError("PAYMENT_ENTITLEMENT_ACCOUNT_MISSING")
    content_retention.assert_user_writable_with_storage(tx, user_id)
    paid = tx.fetchone(
        "SELECT id FROM subscriptions WHERE user_id=? AND is_active=1 "
        "AND tier<>'free' LIMIT 1"
        + (" FOR UPDATE" if tx.postgres else ""),
        (user_id,),
    )
    if paid is not None:
        raise PaymentContractError("PAYMENT_ACTIVE_SUBSCRIPTION_CONFLICT")
    item = _catalog_item(row["product_kind"], row["product_id"])
    started = datetime.fromisoformat(clock)
    expires = started + timedelta(days=int(item["duration_days"]))
    subscription_id = str(uuid.uuid4())
    tx.execute(
        "UPDATE subscriptions SET is_active=0 WHERE user_id=? AND is_active=1",
        (user_id,),
    )
    tx.execute(
        "INSERT INTO subscriptions("
        "id,user_id,tier,started_at,expires_at,is_active,used_analyze,"
        "used_generate,used_chat_rewrite,used_screenshot,"
        "used_monthly_credits,period_start"
        ") VALUES(?,?,?,?,?,1,0,0,0,0,0,?)",
        (
            subscription_id,
            user_id,
            row["product_id"],
            clock,
            _iso(expires),
            clock,
        ),
    )
    ledger_id = str(uuid.uuid4())
    tx.execute(
        "INSERT INTO payment_entitlement_ledger("
        "id,order_id,refund_id,entry_type,product_kind,product_id,"
        "quantity_milli,subscription_id,source_event_id,recorded_at"
        ") VALUES(?,?,NULL,'subscription_grant',?,?,?,?,?,?)",
        (
            ledger_id,
            row["id"],
            row["product_kind"],
            row["product_id"],
            int(item["entitlement_milli"]),
            subscription_id,
            event_row_id,
            clock,
        ),
    )
    return ledger_id


def _record_event(
    tx: db.Transaction,
    event: CallbackEvent,
    raw_data: bytes,
    signature: str,
    clock: str,
) -> tuple[str, bool]:
    event_hash = _hash(
        "noteai-adapay-event-id-v1",
        event.provider_event_id,
    )
    payload_sha256 = hashlib.sha256(raw_data).hexdigest()
    signature_sha256 = hashlib.sha256(signature.encode("ascii")).hexdigest()
    app_id_hash = _app_id_hash(event.app_id)
    existing = tx.fetchone(
        "SELECT id,event_type,payload_sha256,signature_sha256,app_id_hash,"
        "prod_mode,provider_created_at FROM payment_events "
        "WHERE provider_event_id_hash=?",
        (event_hash,),
    )
    if existing is not None:
        if (
            existing["event_type"] != event.event_type
            or existing["payload_sha256"] != payload_sha256
            or existing["signature_sha256"] != signature_sha256
            or existing["app_id_hash"] != app_id_hash
            or int(existing["prod_mode"]) != (1 if event.prod_mode else 0)
            or int(existing["provider_created_at"]) != event.created_time
        ):
            raise PaymentContractError("PAYMENT_EVENT_ID_COLLISION")
        return str(existing["id"]), True
    event_row_id = str(uuid.uuid4())
    tx.execute(
        "INSERT INTO payment_events("
        "id,provider_event_id_hash,event_type,payload_sha256,"
        "signature_sha256,app_id_hash,prod_mode,provider_created_at,"
        "processing_state,reason_code,received_at"
        ") VALUES(?,?,?,?,?,?,?,?, 'accepted','pending',?)",
        (
            event_row_id,
            event_hash,
            event.event_type,
            payload_sha256,
            signature_sha256,
            app_id_hash,
            1 if event.prod_mode else 0,
            event.created_time,
            clock,
        ),
    )
    return event_row_id, False


def _finish_event(
    tx: db.Transaction,
    event_row_id: str,
    *,
    state: str,
    reason: str,
    order_id: str | None,
    refund_id: str | None,
    clock: str,
) -> None:
    tx.execute(
        "UPDATE payment_events SET processing_state=?,reason_code=?,"
        "order_id=?,refund_id=?,processed_at=? WHERE id=? "
        "AND processing_state='accepted'",
        (state, reason, order_id, refund_id, clock, event_row_id),
    )


def process_signed_callback(
    data: str | bytes,
    signature_b64: str,
    public_key_pem: str,
    *,
    expected_app_id: str,
    expected_prod_mode: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Verify and atomically apply one callback without persisting raw input."""
    raw_data = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    if not verify_adapay_signature(raw_data, signature_b64, public_key_pem):
        raise PaymentContractError("PAYMENT_CALLBACK_SIGNATURE_INVALID")
    event = parse_callback_event(raw_data)
    expected_app = _app_id(expected_app_id)
    clock = _iso(now)
    with db.transaction(write=True) as tx:
        event_row_id, duplicate = _record_event(
            tx,
            event,
            raw_data,
            signature_b64,
            clock,
        )
        if duplicate:
            return {
                "ok": True,
                "duplicate": True,
                "event_id": event_row_id,
            }
        if (
            event.app_id != expected_app
            or event.prod_mode is not bool(expected_prod_mode)
        ):
            _finish_event(
                tx,
                event_row_id,
                state="needs_manual",
                reason="environment_mismatch",
                order_id=None,
                refund_id=None,
                clock=clock,
            )
            return {
                "ok": False,
                "duplicate": False,
                "code": "PAYMENT_CALLBACK_ENVIRONMENT_MISMATCH",
            }
        if event.event_type not in PAYMENT_EVENT_TYPES:
            _finish_event(
                tx,
                event_row_id,
                state="ignored",
                reason="unsupported_event",
                order_id=None,
                refund_id=None,
                clock=clock,
            )
            return {
                "ok": True,
                "duplicate": False,
                "ignored": True,
            }
        if event.event_type.startswith("payment."):
            return _process_payment_event(
                tx,
                event,
                event_row_id,
                clock,
            )
        return _process_refund_event(
            tx,
            event,
            event_row_id,
            clock,
        )


def _process_payment_event(
    tx: db.Transaction,
    event: CallbackEvent,
    event_row_id: str,
    clock: str,
) -> dict[str, Any]:
    payload = _event_payment(event)
    candidate = tx.fetchone(
        "SELECT user_id FROM payment_orders WHERE merchant_order_no=?",
        (payload["merchant_order_no"],),
    )
    if candidate is not None:
        _lock_financial_subject(tx, candidate["user_id"])
    row = tx.fetchone(
        "SELECT * FROM payment_orders WHERE merchant_order_no=?"
        + (" FOR UPDATE" if tx.postgres else ""),
        (payload["merchant_order_no"],),
    )
    if row is None:
        _finish_event(
            tx,
            event_row_id,
            state="needs_manual",
            reason="order_not_found",
            order_id=None,
            refund_id=None,
            clock=clock,
        )
        return {"ok": False, "code": "PAYMENT_ORDER_NOT_FOUND"}
    order_id = str(row["id"])
    matches = (
        int(payload["amount_fen"]) == int(row["amount_fen"])
        and _app_id_hash(event.app_id) == row["app_id_hash"]
        and event.prod_mode == (row["provider_mode"] == "live")
        and (
            not row["provider_payment_id"]
            or row["provider_payment_id"] == payload["provider_payment_id"]
        )
    )
    if not matches:
        if event.event_type == "payment.succeeded":
            _insert_cash(
                tx,
                order_id=order_id,
                refund_id=None,
                entry_type="payment_received_unmatched",
                amount_fen=int(payload["amount_fen"]),
                source_event_id=event_row_id,
                clock=clock,
            )
        tx.execute(
            "UPDATE payment_orders SET payment_status='needs_manual',"
            "updated_at=?,terminal_at=? WHERE id=?",
            (clock, clock, order_id),
        )
        _finish_event(
            tx,
            event_row_id,
            state="needs_manual",
            reason="order_mismatch",
            order_id=order_id,
            refund_id=None,
            clock=clock,
        )
        return {"ok": False, "code": "PAYMENT_ORDER_MISMATCH"}
    if event.event_type == "payment.succeeded":
        if row["payment_status"] == "succeeded":
            _finish_event(
                tx,
                event_row_id,
                state="processed",
                reason="already_succeeded",
                order_id=order_id,
                refund_id=None,
                clock=clock,
            )
            return {"ok": True, "duplicate": False, "already_terminal": True}
        if row["payment_status"] in {"failed", "closed", "needs_manual"}:
            _insert_cash(
                tx,
                order_id=order_id,
                refund_id=None,
                entry_type="payment_received_unmatched",
                amount_fen=int(payload["amount_fen"]),
                source_event_id=event_row_id,
                clock=clock,
            )
            tx.execute(
                "UPDATE payment_orders SET payment_status='needs_manual',"
                "updated_at=?,terminal_at=? WHERE id=?",
                (clock, clock, order_id),
            )
            _finish_event(
                tx,
                event_row_id,
                state="needs_manual",
                reason="contradictory_terminal",
                order_id=order_id,
                refund_id=None,
                clock=clock,
            )
            return {"ok": False, "code": "PAYMENT_CONTRADICTORY_TERMINAL"}
        cash_inserted = _insert_cash(
            tx,
            order_id=order_id,
            refund_id=None,
            entry_type="payment_received",
            amount_fen=int(row["amount_fen"]),
            source_event_id=event_row_id,
            clock=clock,
        )
        if not cash_inserted:
            tx.execute(
                "UPDATE payment_orders SET payment_status='needs_manual',"
                "updated_at=?,terminal_at=? WHERE id=?",
                (clock, clock, order_id),
            )
            _finish_event(
                tx,
                event_row_id,
                state="needs_manual",
                reason="cash_ledger_conflict",
                order_id=order_id,
                refund_id=None,
                clock=clock,
            )
            return {"ok": False, "code": "PAYMENT_CASH_LEDGER_CONFLICT"}
        tx.execute("SAVEPOINT payment_entitlement_apply")
        try:
            entitlement_id = (
                _apply_credit_entitlement(tx, row, event_row_id, clock)
                if row["product_kind"] == "credit_package"
                else _apply_subscription_entitlement(
                    tx,
                    row,
                    event_row_id,
                    clock,
                )
            )
        except Exception:
            tx.execute("ROLLBACK TO SAVEPOINT payment_entitlement_apply")
            tx.execute("RELEASE SAVEPOINT payment_entitlement_apply")
            tx.execute(
                "UPDATE payment_orders SET provider_payment_id=?,"
                "payment_status='succeeded',entitlement_status='needs_manual',"
                "updated_at=?,succeeded_at=?,terminal_at=? WHERE id=?",
                (
                    payload["provider_payment_id"],
                    clock,
                    clock,
                    clock,
                    order_id,
                ),
            )
            _finish_event(
                tx,
                event_row_id,
                state="needs_manual",
                reason="entitlement_conflict",
                order_id=order_id,
                refund_id=None,
                clock=clock,
            )
            return {"ok": False, "code": "PAYMENT_ENTITLEMENT_NEEDS_MANUAL"}
        tx.execute("RELEASE SAVEPOINT payment_entitlement_apply")
        tx.execute(
            "UPDATE payment_orders SET provider_payment_id=?,"
            "payment_status='succeeded',entitlement_status='applied',"
            "entitlement_ref=?,updated_at=?,succeeded_at=?,terminal_at=? "
            "WHERE id=?",
            (
                payload["provider_payment_id"],
                entitlement_id,
                clock,
                clock,
                clock,
                order_id,
            ),
        )
        _finish_event(
            tx,
            event_row_id,
            state="processed",
            reason="payment_applied",
            order_id=order_id,
            refund_id=None,
            clock=clock,
        )
        return {"ok": True, "duplicate": False, "order_id": order_id}
    if event.event_type == "payment.close.failed":
        if row["payment_status"] not in {"succeeded", "failed", "closed"}:
            tx.execute(
                "UPDATE payment_orders SET payment_status='needs_manual',"
                "updated_at=?,terminal_at=? WHERE id=?",
                (clock, clock, order_id),
            )
        _finish_event(
            tx,
            event_row_id,
            state="needs_manual",
            reason="close_failed",
            order_id=order_id,
            refund_id=None,
            clock=clock,
        )
        return {"ok": False, "code": "PAYMENT_CLOSE_NEEDS_MANUAL"}
    terminal = "failed" if event.event_type == "payment.failed" else "closed"
    if row["payment_status"] == "succeeded":
        _finish_event(
            tx,
            event_row_id,
            state="ignored",
            reason="stale_after_success",
            order_id=order_id,
            refund_id=None,
            clock=clock,
        )
        return {"ok": True, "ignored": True}
    if row["payment_status"] not in {"needs_manual"}:
        tx.execute(
            "UPDATE payment_orders SET provider_payment_id=?,"
            "payment_status=?,updated_at=?,terminal_at=? WHERE id=?",
            (
                payload["provider_payment_id"],
                terminal,
                clock,
                clock,
                order_id,
            ),
        )
    _finish_event(
        tx,
        event_row_id,
        state="processed",
        reason=f"payment_{terminal}",
        order_id=order_id,
        refund_id=None,
        clock=clock,
    )
    return {"ok": True, "order_id": order_id}


def allocate_paid_credit_positions(
    tx: db.Transaction,
    user_id: str,
    usage_id: str,
    amount_credits: float,
    *,
    now: datetime | None = None,
) -> int:
    """Allocate wallet consumption FIFO; return tracked milli-credits used."""
    milli = int(round(float(amount_credits) * 1000))
    if milli <= 0:
        return 0
    if not _UUID_RE.fullmatch(str(usage_id or "").lower()):
        raise PaymentContractError("PAYMENT_INVALID_USAGE_ID")
    remaining = milli
    clock = _iso(now)
    rows = tx.fetchall(
        "SELECT * FROM payment_credit_positions WHERE user_id=? "
        "AND state='active' AND remaining_milli>0 "
        "ORDER BY created_at,order_id"
        + (" FOR UPDATE" if tx.postgres else ""),
        (user_id,),
    )
    for row in rows:
        if remaining <= 0:
            break
        amount = min(remaining, int(row["remaining_milli"]))
        new_remaining = int(row["remaining_milli"]) - amount
        state = "consumed" if new_remaining == 0 else "active"
        tx.execute(
            "UPDATE payment_credit_positions SET remaining_milli=?,state=?,"
            "updated_at=? WHERE order_id=? AND remaining_milli=?",
            (
                new_remaining,
                state,
                clock,
                row["order_id"],
                int(row["remaining_milli"]),
            ),
        )
        tx.execute(
            "INSERT INTO payment_credit_consumptions("
            "id,order_id,usage_id,amount_milli,state,created_at,updated_at"
            ") VALUES(?,?,?,?,'consumed',?,?)",
            (
                str(uuid.uuid4()),
                row["order_id"],
                usage_id,
                amount,
                clock,
                clock,
            ),
        )
        remaining -= amount
    return milli - remaining


def restore_paid_credit_positions(
    tx: db.Transaction,
    user_id: str,
    usage_id: str,
    *,
    now: datetime | None = None,
) -> int:
    """Restore only allocations made for the exact refunded usage."""
    clock = _iso(now)
    rows = tx.fetchall(
        "SELECT c.id,c.order_id,c.amount_milli,p.remaining_milli,p.granted_milli "
        "FROM payment_credit_consumptions c "
        "JOIN payment_credit_positions p ON p.order_id=c.order_id "
        "WHERE c.usage_id=? AND c.state='consumed' AND p.user_id=? "
        "ORDER BY c.created_at,c.id"
        + (" FOR UPDATE OF c,p" if tx.postgres else ""),
        (usage_id, user_id),
    )
    restored = 0
    for row in rows:
        new_remaining = int(row["remaining_milli"]) + int(row["amount_milli"])
        if new_remaining > int(row["granted_milli"]):
            raise PaymentContractError("PAYMENT_CREDIT_POSITION_OVERFLOW")
        tx.execute(
            "UPDATE payment_credit_positions SET remaining_milli=?,state='active',"
            "updated_at=? WHERE order_id=?",
            (new_remaining, clock, row["order_id"]),
        )
        tx.execute(
            "UPDATE payment_credit_consumptions SET state='restored',"
            "updated_at=? WHERE id=? AND state='consumed'",
            (clock, row["id"]),
        )
        restored += int(row["amount_milli"])
    return restored


def prepare_full_refund(
    order_id: str,
    *,
    reason_code: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create one locally eligible full-refund intent; no provider call."""
    normalized = _uuid(order_id, "order_id")
    reason = str(reason_code or "").strip()
    if reason not in {
        "customer_request",
        "service_not_delivered",
        "duplicate_payment",
        "fraud_review",
    }:
        raise PaymentContractError("PAYMENT_REFUND_REASON_INVALID")
    clock = _iso(now)
    refund_id = str(uuid.uuid4())
    merchant_refund_no = "NR_" + refund_id.replace("-", "")
    with db.transaction(write=True) as tx:
        row = tx.fetchone(
            "SELECT * FROM payment_orders WHERE id=?"
            + (" FOR UPDATE" if tx.postgres else ""),
            (normalized,),
        )
        if row is None:
            raise PaymentContractError("PAYMENT_ORDER_NOT_FOUND")
        if (
            row["payment_status"] != "succeeded"
            or row["entitlement_status"] != "applied"
            or row["refund_status"] != "none"
            or int(row["refunded_fen"]) != 0
        ):
            raise PaymentContractError("PAYMENT_REFUND_NOT_ELIGIBLE")
        if row["product_kind"] == "credit_package":
            position = tx.fetchone(
                "SELECT granted_milli,remaining_milli,state "
                "FROM payment_credit_positions WHERE order_id=?"
                + (" FOR UPDATE" if tx.postgres else ""),
                (normalized,),
            )
            eligible = (
                position is not None
                and int(position["remaining_milli"])
                == int(position["granted_milli"])
                and position["state"] == "active"
            )
        else:
            entitlement = tx.fetchone(
                "SELECT subscription_id FROM payment_entitlement_ledger "
                "WHERE order_id=? AND entry_type='subscription_grant'",
                (normalized,),
            )
            subscription_id = (
                entitlement["subscription_id"] if entitlement else None
            )
            subscription = tx.fetchone(
                "SELECT started_at,is_active FROM subscriptions WHERE id=? "
                "AND user_id=?"
                + (" FOR UPDATE" if tx.postgres else ""),
                (subscription_id, row["user_id"]),
            )
            used = tx.fetchone(
                "SELECT COUNT(*) AS c FROM usage_records "
                "WHERE user_id=? AND recorded_at>=? AND credits_used>0 "
                "AND source IN ('subscription','mixed')",
                (
                    row["user_id"],
                    subscription["started_at"] if subscription else clock,
                ),
            )
            eligible = (
                subscription is not None
                and int(subscription["is_active"]) == 1
                and int(used["c"] or 0) == 0
            )
        if not eligible:
            raise PaymentContractError("PAYMENT_REFUND_ENTITLEMENT_USED")
        tx.execute(
            "INSERT INTO payment_refunds("
            "id,order_id,merchant_refund_no,amount_fen,currency,status,"
            "reason_code,created_at,updated_at"
            ") VALUES(?,?,?,?,'CNY','requested',?,?,?)",
            (
                refund_id,
                normalized,
                merchant_refund_no,
                int(row["amount_fen"]),
                reason,
                clock,
                clock,
            ),
        )
        tx.execute(
            "UPDATE payment_orders SET refund_status='pending',"
            "refund_count=refund_count+1,updated_at=? WHERE id=?",
            (clock, normalized),
        )
        result = tx.fetchone(
            "SELECT * FROM payment_refunds WHERE id=?",
            (refund_id,),
        )
    return {
        "id": result["id"],
        "order_id": result["order_id"],
        "amount_fen": int(result["amount_fen"]),
        "status": result["status"],
        "reason_code": result["reason_code"],
        "created_at": result["created_at"],
    }


def mark_refund_submission(
    refund_id: str,
    result: ProviderRefundResult,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized = _uuid(refund_id, "refund_id")
    if not result.response_verified:
        raise PaymentContractError("PAYMENT_PROVIDER_RESPONSE_UNVERIFIED")
    provider_refund_id = _opaque_ref(
        result.provider_refund_id,
        "provider_refund_id",
    )
    clock = _iso(now)
    mismatch = False
    with db.transaction(write=True) as tx:
        row = tx.fetchone(
            "SELECT * FROM payment_refunds WHERE id=?"
            + (" FOR UPDATE" if tx.postgres else ""),
            (normalized,),
        )
        if row is None:
            raise PaymentContractError("PAYMENT_REFUND_NOT_FOUND")
        if (
            result.merchant_refund_no != row["merchant_refund_no"]
            or int(result.amount_fen) != int(row["amount_fen"])
            or (
                row["provider_refund_id"]
                and result.provider_refund_id != row["provider_refund_id"]
            )
            or result.status not in {"pending", "succeeded"}
        ):
            tx.execute(
                "UPDATE payment_refunds SET status='needs_manual',"
                "updated_at=?,terminal_at=? WHERE id=? "
                "AND status IN ('requested','pending')",
                (clock, clock, normalized),
            )
            tx.execute(
                "UPDATE payment_orders SET refund_status='needs_manual',"
                "updated_at=? WHERE id=?",
                (clock, row["order_id"]),
            )
            mismatch = True
        else:
            tx.execute(
                "UPDATE payment_refunds SET provider_refund_id=?,status='pending',"
                "updated_at=? WHERE id=? "
                "AND status IN ('requested','pending') "
                "AND provider_refund_id IS NULL",
                (provider_refund_id, clock, normalized),
            )
        updated = tx.fetchone(
            "SELECT * FROM payment_refunds WHERE id=?",
            (normalized,),
        )
    if mismatch:
        raise PaymentContractError("PAYMENT_PROVIDER_RESPONSE_MISMATCH")
    return {
        "id": updated["id"],
        "order_id": updated["order_id"],
        "amount_fen": int(updated["amount_fen"]),
        "status": updated["status"],
    }


def admit_refund_submission(
    refund_id: str,
    *,
    now: datetime | None = None,
) -> bool:
    """Atomically reserve the sole provider-submission attempt for a refund."""
    normalized = _uuid(refund_id, "refund_id")
    clock = _iso(now)
    with db.transaction(write=True) as tx:
        row = tx.fetchone(
            "SELECT id FROM payment_refunds WHERE id=?"
            + (" FOR UPDATE" if tx.postgres else ""),
            (normalized,),
        )
        if row is None:
            raise PaymentContractError("PAYMENT_REFUND_NOT_FOUND")
        cursor = tx.execute(
            "UPDATE payment_refunds SET status='pending',updated_at=? "
            "WHERE id=? AND status='requested' AND provider_refund_id IS NULL",
            (clock, normalized),
        )
        admitted = int(getattr(cursor, "rowcount", 0) or 0) == 1
    return admitted


def _reverse_credit_entitlement(
    tx: db.Transaction,
    order: Any,
    refund: Any,
    event_row_id: str,
    clock: str,
) -> None:
    position = tx.fetchone(
        "SELECT * FROM payment_credit_positions WHERE order_id=?"
        + (" FOR UPDATE" if tx.postgres else ""),
        (order["id"],),
    )
    if (
        position is None
        or int(position["remaining_milli"]) != int(position["granted_milli"])
        or position["state"] != "active"
    ):
        raise PaymentContractError("PAYMENT_REFUND_ENTITLEMENT_USED")
    user_id = position["user_id"]
    if user_id:
        amount = _credits(int(position["granted_milli"]))
        cursor = tx.execute(
            "UPDATE credits SET balance=balance-?,"
            "total_purchased=CASE WHEN total_purchased>=? "
            "THEN total_purchased-? ELSE 0 END,updated_at=? "
            "WHERE user_id=? AND balance>=?",
            (amount, amount, amount, clock, user_id, amount),
        )
        if int(getattr(cursor, "rowcount", 0) or 0) != 1:
            raise PaymentContractError("PAYMENT_REFUND_BALANCE_CONFLICT")
        balance = float(
            tx.fetchone(
                "SELECT balance FROM credits WHERE user_id=?",
                (user_id,),
            )["balance"]
        )
        tx.execute(
            "INSERT INTO credit_transactions("
            "id,user_id,type,amount,balance_after,description,paid_rmb,"
            "package_id,payment_ref,recorded_at"
            ") VALUES(?,?,'payment_refund',?,?,?,?,?,?,?)",
            (
                str(uuid.uuid4()),
                user_id,
                -amount,
                balance,
                "支付退款：积分包撤销",
                -_fen_to_rmb(int(refund["amount_fen"])),
                order["product_id"],
                order["id"],
                clock,
            ),
        )
    tx.execute(
        "UPDATE payment_credit_positions SET remaining_milli=0,state='reversed',"
        "updated_at=? WHERE order_id=?",
        (clock, order["id"]),
    )
    tx.execute(
        "INSERT INTO payment_entitlement_ledger("
        "id,order_id,refund_id,entry_type,product_kind,product_id,"
        "quantity_milli,subscription_id,source_event_id,recorded_at"
        ") VALUES(?,?,?,'credit_reversal',?,?,?,NULL,?,?)",
        (
            str(uuid.uuid4()),
            order["id"],
            refund["id"],
            order["product_kind"],
            order["product_id"],
            -int(position["granted_milli"]),
            event_row_id,
            clock,
        ),
    )


def _reverse_subscription_entitlement(
    tx: db.Transaction,
    order: Any,
    refund: Any,
    event_row_id: str,
    clock: str,
) -> None:
    entitlement = tx.fetchone(
        "SELECT subscription_id,quantity_milli "
        "FROM payment_entitlement_ledger WHERE order_id=? "
        "AND entry_type='subscription_grant'",
        (order["id"],),
    )
    subscription_id = entitlement["subscription_id"] if entitlement else None
    if order["user_id"]:
        subscription = tx.fetchone(
            "SELECT * FROM subscriptions WHERE id=? AND user_id=?"
            + (" FOR UPDATE" if tx.postgres else ""),
            (subscription_id, order["user_id"]),
        )
        used = tx.fetchone(
            "SELECT COUNT(*) AS c FROM usage_records "
            "WHERE user_id=? AND recorded_at>=? AND credits_used>0 "
            "AND source IN ('subscription','mixed')",
            (
                order["user_id"],
                subscription["started_at"] if subscription else clock,
            ),
        )
        if (
            subscription is None
            or int(subscription["is_active"]) != 1
            or int(used["c"] or 0) != 0
        ):
            raise PaymentContractError("PAYMENT_REFUND_ENTITLEMENT_USED")
        tx.execute(
            "UPDATE subscriptions SET is_active=0 WHERE id=?",
            (subscription_id,),
        )
        free_id = str(uuid.uuid4())
        tx.execute(
            "INSERT INTO subscriptions("
            "id,user_id,tier,started_at,expires_at,is_active,used_analyze,"
            "used_generate,used_chat_rewrite,used_screenshot,"
            "used_monthly_credits,period_start"
            ") VALUES(?,?,'free',?,'2099-01-01T00:00:00+00:00',"
            "1,0,0,0,0,0,?)",
            (
                free_id,
                order["user_id"],
                clock,
                clock,
            ),
        )
    tx.execute(
        "INSERT INTO payment_entitlement_ledger("
        "id,order_id,refund_id,entry_type,product_kind,product_id,"
        "quantity_milli,subscription_id,source_event_id,recorded_at"
        ") VALUES(?,?,?,'subscription_reversal',?,?,?,?,?,?)",
        (
            str(uuid.uuid4()),
            order["id"],
            refund["id"],
            order["product_kind"],
            order["product_id"],
            -int(entitlement["quantity_milli"]),
            subscription_id,
            event_row_id,
            clock,
        ),
    )


def _process_refund_event(
    tx: db.Transaction,
    event: CallbackEvent,
    event_row_id: str,
    clock: str,
) -> dict[str, Any]:
    payload = _event_refund(event)
    candidate = tx.fetchone(
        "SELECT o.user_id FROM payment_refunds r "
        "JOIN payment_orders o ON o.id=r.order_id "
        "WHERE r.merchant_refund_no=?",
        (payload["merchant_refund_no"],),
    )
    if candidate is not None:
        _lock_financial_subject(tx, candidate["user_id"])
    refund = tx.fetchone(
        "SELECT * FROM payment_refunds WHERE merchant_refund_no=?"
        + (" FOR UPDATE" if tx.postgres else ""),
        (payload["merchant_refund_no"],),
    )
    if refund is None:
        _finish_event(
            tx,
            event_row_id,
            state="needs_manual",
            reason="refund_not_found",
            order_id=None,
            refund_id=None,
            clock=clock,
        )
        return {"ok": False, "code": "PAYMENT_REFUND_NOT_FOUND"}
    order = tx.fetchone(
        "SELECT * FROM payment_orders WHERE id=?"
        + (" FOR UPDATE" if tx.postgres else ""),
        (refund["order_id"],),
    )
    matches = (
        order is not None
        and int(payload["amount_fen"]) == int(refund["amount_fen"])
        and (
            not refund["provider_refund_id"]
            or refund["provider_refund_id"] == payload["provider_refund_id"]
        )
        and (
            not order["provider_payment_id"]
            or order["provider_payment_id"] == payload["provider_payment_id"]
        )
    )
    if not matches:
        if event.event_type == "refund.succeeded" and order is not None:
            _insert_cash(
                tx,
                order_id=order["id"],
                refund_id=refund["id"],
                entry_type="refund_paid_unmatched",
                amount_fen=-int(payload["amount_fen"]),
                source_event_id=event_row_id,
                clock=clock,
            )
        tx.execute(
            "UPDATE payment_refunds SET status='needs_manual',updated_at=?,"
            "terminal_at=? WHERE id=?",
            (clock, clock, refund["id"]),
        )
        if order is not None:
            tx.execute(
                "UPDATE payment_orders SET refund_status='needs_manual',"
                "updated_at=? WHERE id=?",
                (clock, order["id"]),
            )
        _finish_event(
            tx,
            event_row_id,
            state="needs_manual",
            reason="refund_mismatch",
            order_id=order["id"] if order else None,
            refund_id=refund["id"],
            clock=clock,
        )
        return {"ok": False, "code": "PAYMENT_REFUND_MISMATCH"}
    if event.event_type == "refund.failed":
        if refund["status"] == "succeeded":
            _finish_event(
                tx,
                event_row_id,
                state="ignored",
                reason="stale_after_success",
                order_id=order["id"],
                refund_id=refund["id"],
                clock=clock,
            )
            return {"ok": True, "ignored": True}
        if refund["status"] != "needs_manual":
            tx.execute(
                "UPDATE payment_refunds SET provider_refund_id=?,status='failed',"
                "updated_at=?,terminal_at=? WHERE id=?",
                (
                    payload["provider_refund_id"],
                    clock,
                    clock,
                    refund["id"],
                ),
            )
            tx.execute(
                "UPDATE payment_orders SET refund_status='needs_manual',updated_at=? "
                "WHERE id=? AND refunded_fen=0",
                (clock, order["id"]),
            )
        _finish_event(
            tx,
            event_row_id,
            state="processed",
            reason="refund_failed",
            order_id=order["id"],
            refund_id=refund["id"],
            clock=clock,
        )
        return {"ok": True, "order_id": order["id"]}
    if refund["status"] == "succeeded":
        _finish_event(
            tx,
            event_row_id,
            state="processed",
            reason="already_succeeded",
            order_id=order["id"],
            refund_id=refund["id"],
            clock=clock,
        )
        return {"ok": True, "already_terminal": True}
    if refund["status"] in {"failed", "needs_manual"}:
        _insert_cash(
            tx,
            order_id=order["id"],
            refund_id=refund["id"],
            entry_type="refund_paid_unmatched",
            amount_fen=-int(refund["amount_fen"]),
            source_event_id=event_row_id,
            clock=clock,
        )
        tx.execute(
            "UPDATE payment_refunds SET provider_refund_id="
            "COALESCE(provider_refund_id,?),status='needs_manual',"
            "updated_at=?,terminal_at=? WHERE id=?",
            (
                payload["provider_refund_id"],
                clock,
                clock,
                refund["id"],
            ),
        )
        tx.execute(
            "UPDATE payment_orders SET refund_status='needs_manual',"
            "entitlement_status='needs_manual',updated_at=? WHERE id=?",
            (clock, order["id"]),
        )
        _finish_event(
            tx,
            event_row_id,
            state="needs_manual",
            reason="contradictory_refund_terminal",
            order_id=order["id"],
            refund_id=refund["id"],
            clock=clock,
        )
        return {"ok": False, "code": "PAYMENT_REFUND_CONTRADICTORY_TERMINAL"}
    cash_inserted = _insert_cash(
        tx,
        order_id=order["id"],
        refund_id=refund["id"],
        entry_type="refund_paid",
        amount_fen=-int(refund["amount_fen"]),
        source_event_id=event_row_id,
        clock=clock,
    )
    if not cash_inserted:
        tx.execute(
            "UPDATE payment_refunds SET provider_refund_id="
            "COALESCE(provider_refund_id,?),status='needs_manual',"
            "updated_at=?,terminal_at=? WHERE id=?",
            (
                payload["provider_refund_id"],
                clock,
                clock,
                refund["id"],
            ),
        )
        tx.execute(
            "UPDATE payment_orders SET refund_status='needs_manual',"
            "entitlement_status='needs_manual',"
            "refunded_fen=CASE WHEN refunded_fen=0 THEN ? "
            "ELSE refunded_fen END,updated_at=? WHERE id=?",
            (int(refund["amount_fen"]), clock, order["id"]),
        )
        _finish_event(
            tx,
            event_row_id,
            state="needs_manual",
            reason="cash_ledger_conflict",
            order_id=order["id"],
            refund_id=refund["id"],
            clock=clock,
        )
        return {"ok": False, "code": "PAYMENT_REFUND_CASH_LEDGER_CONFLICT"}
    tx.execute("SAVEPOINT payment_entitlement_reverse")
    try:
        if order["product_kind"] == "credit_package":
            _reverse_credit_entitlement(
                tx,
                order,
                refund,
                event_row_id,
                clock,
            )
        else:
            _reverse_subscription_entitlement(
                tx,
                order,
                refund,
                event_row_id,
                clock,
            )
    except Exception:
        tx.execute("ROLLBACK TO SAVEPOINT payment_entitlement_reverse")
        tx.execute("RELEASE SAVEPOINT payment_entitlement_reverse")
        tx.execute(
            "UPDATE payment_refunds SET provider_refund_id=?,"
            "status='needs_manual',updated_at=?,terminal_at=? WHERE id=?",
            (
                payload["provider_refund_id"],
                clock,
                clock,
                refund["id"],
            ),
        )
        tx.execute(
            "UPDATE payment_orders SET refund_status='needs_manual',"
            "entitlement_status='needs_manual',"
            "refunded_fen=refunded_fen+?,updated_at=? WHERE id=?",
            (int(refund["amount_fen"]), clock, order["id"]),
        )
        _finish_event(
            tx,
            event_row_id,
            state="needs_manual",
            reason="refund_entitlement_conflict",
            order_id=order["id"],
            refund_id=refund["id"],
            clock=clock,
        )
        return {"ok": False, "code": "PAYMENT_REFUND_NEEDS_MANUAL"}
    tx.execute("RELEASE SAVEPOINT payment_entitlement_reverse")
    tx.execute(
        "UPDATE payment_refunds SET provider_refund_id=?,status='succeeded',"
        "updated_at=?,terminal_at=? WHERE id=?",
        (
            payload["provider_refund_id"],
            clock,
            clock,
            refund["id"],
        ),
    )
    tx.execute(
        "UPDATE payment_orders SET refund_status='refunded',"
        "entitlement_status='reversed',refunded_fen=refunded_fen+?,"
        "updated_at=? WHERE id=?",
        (int(refund["amount_fen"]), clock, order["id"]),
    )
    _finish_event(
        tx,
        event_row_id,
        state="processed",
        reason="refund_applied",
        order_id=order["id"],
        refund_id=refund["id"],
        clock=clock,
    )
    return {"ok": True, "order_id": order["id"], "refund_id": refund["id"]}


def reconcile_bill(
    bill_date: str,
    source_bytes: bytes,
    rows: Iterable[dict[str, Any]],
    *,
    prod_mode: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compare a bounded canonical provider bill without persisting raw rows."""
    try:
        day = date.fromisoformat(str(bill_date))
    except ValueError as exc:
        raise PaymentContractError("PAYMENT_BILL_DATE_INVALID") from exc
    source = bytes(source_bytes)
    if not source or len(source) > MAX_RECONCILIATION_SOURCE_BYTES:
        raise PaymentContractError("PAYMENT_BILL_SOURCE_INVALID")
    canonical: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in rows:
        if len(canonical) >= MAX_RECONCILIATION_ROWS:
            raise PaymentContractError("PAYMENT_BILL_ROW_LIMIT")
        if not isinstance(raw, dict):
            raise PaymentContractError("PAYMENT_BILL_ROW_INVALID")
        kind = str(raw.get("kind") or "")
        if kind not in {"payment", "refund"}:
            raise PaymentContractError("PAYMENT_BILL_ROW_INVALID")
        reference = _opaque_ref(raw.get("reference"), "bill_reference")
        key = (kind, reference)
        if key in seen:
            raise PaymentContractError("PAYMENT_BILL_DUPLICATE_REFERENCE")
        seen.add(key)
        amount_fen = int(raw.get("amount_fen") or 0)
        if amount_fen <= 0 or amount_fen > 100_000_000:
            raise PaymentContractError("PAYMENT_BILL_AMOUNT_INVALID")
        status = str(raw.get("status") or "")
        if status not in {"succeeded", "failed", "pending", "closed"}:
            raise PaymentContractError("PAYMENT_BILL_STATUS_INVALID")
        canonical.append(
            {
                "kind": kind,
                "reference": reference,
                "amount_fen": amount_fen,
                "status": status,
            }
        )
    clock = _iso(now)
    run_id = str(uuid.uuid4())
    source_sha256 = hashlib.sha256(source).hexdigest()
    mode = "live" if prod_mode else "mock"
    payment_total = sum(
        row["amount_fen"]
        for row in canonical
        if row["kind"] == "payment" and row["status"] == "succeeded"
    )
    refund_total = sum(
        row["amount_fen"]
        for row in canonical
        if row["kind"] == "refund" and row["status"] == "succeeded"
    )
    discrepancies: list[dict[str, Any]] = []
    with db.transaction(write=True) as tx:
        existing = tx.fetchone(
            "SELECT * FROM payment_reconciliation_runs "
            "WHERE provider='adapay' AND provider_mode=? AND bill_date=? "
            "AND source_sha256=?",
            (mode, day.isoformat(), source_sha256),
        )
        if existing is not None:
            return {
                "id": existing["id"],
                "bill_date": str(existing["bill_date"]),
                "source_sha256": existing["source_sha256"],
                "row_count": int(existing["row_count"]),
                "payment_total_fen": int(existing["payment_total_fen"]),
                "refund_total_fen": int(existing["refund_total_fen"]),
                "discrepancy_count": int(existing["discrepancy_count"]),
                "status": existing["status"],
            }
        local_payments = tx.fetchall(
            "SELECT o.merchant_order_no AS reference,l.amount_fen "
            "FROM payment_cash_ledger l "
            "JOIN payment_orders o ON o.id=l.order_id "
            "WHERE l.entry_type='payment_received' "
            "AND substr(l.recorded_at,1,10)=? AND o.provider_mode=?",
            (day.isoformat(), mode),
        )
        local_refunds = tx.fetchall(
            "SELECT r.merchant_refund_no AS reference,-l.amount_fen AS amount_fen "
            "FROM payment_cash_ledger l "
            "JOIN payment_refunds r ON r.id=l.refund_id "
            "JOIN payment_orders o ON o.id=l.order_id "
            "WHERE l.entry_type='refund_paid' "
            "AND substr(l.recorded_at,1,10)=? AND o.provider_mode=?",
            (day.isoformat(), mode),
        )
        local = {
            ("payment", str(row["reference"])): int(row["amount_fen"])
            for row in local_payments
        }
        local.update(
            {
                ("refund", str(row["reference"])): int(row["amount_fen"])
                for row in local_refunds
            }
        )
        provider = {
            (row["kind"], row["reference"]): row
            for row in canonical
            if row["status"] == "succeeded"
        }
        for key in sorted(set(local) | set(provider)):
            local_amount = local.get(key)
            provider_row = provider.get(key)
            provider_amount = (
                int(provider_row["amount_fen"])
                if provider_row is not None
                else None
            )
            if local_amount is None:
                issue = "missing_local"
            elif provider_amount is None:
                issue = "missing_provider"
            elif local_amount != provider_amount:
                issue = "amount_mismatch"
            else:
                continue
            discrepancies.append(
                {
                    "kind": key[0],
                    "reference_hash": _hash(
                        "noteai-payment-reconcile-ref-v1",
                        key[1],
                    ),
                    "issue_code": issue,
                    "local_fen": local_amount,
                    "provider_fen": provider_amount,
                }
            )
        tx.execute(
            "INSERT INTO payment_reconciliation_runs("
            "id,provider,provider_mode,bill_date,source_sha256,row_count,"
            "payment_total_fen,refund_total_fen,discrepancy_count,status,"
            "created_at,completed_at"
            ") VALUES(?,'adapay',?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                mode,
                day.isoformat(),
                source_sha256,
                len(canonical),
                payment_total,
                refund_total,
                len(discrepancies),
                "matched" if not discrepancies else "discrepancies",
                clock,
                clock,
            ),
        )
        for discrepancy in discrepancies:
            tx.execute(
                "INSERT INTO payment_reconciliation_items("
                "id,run_id,entry_kind,reference_hash,issue_code,"
                "local_fen,provider_fen,resolution_state,created_at"
                ") VALUES(?,?,?,?,?,?,?,'open',?)",
                (
                    str(uuid.uuid4()),
                    run_id,
                    discrepancy["kind"],
                    discrepancy["reference_hash"],
                    discrepancy["issue_code"],
                    discrepancy["local_fen"],
                    discrepancy["provider_fen"],
                    clock,
                ),
            )
    return {
        "id": run_id,
        "bill_date": day.isoformat(),
        "source_sha256": source_sha256,
        "row_count": len(canonical),
        "payment_total_fen": payment_total,
        "refund_total_fen": refund_total,
        "discrepancy_count": len(discrepancies),
        "status": "matched" if not discrepancies else "discrepancies",
    }


def record_settlement_summary(
    settlement_date: str,
    *,
    source_sha256: str,
    gross_fen: int,
    refund_fen: int,
    fee_fen: int,
    net_fen: int,
    prod_mode: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    try:
        day = date.fromisoformat(str(settlement_date))
    except ValueError as exc:
        raise PaymentContractError("PAYMENT_SETTLEMENT_DATE_INVALID") from exc
    digest = str(source_sha256 or "").lower()
    if not _SHA256_RE.fullmatch(digest):
        raise PaymentContractError("PAYMENT_SETTLEMENT_SOURCE_INVALID")
    values = tuple(int(value) for value in (gross_fen, refund_fen, fee_fen, net_fen))
    if any(value < 0 or value > 10_000_000_000 for value in values):
        raise PaymentContractError("PAYMENT_SETTLEMENT_AMOUNT_INVALID")
    if values[0] - values[1] - values[2] != values[3]:
        raise PaymentContractError("PAYMENT_SETTLEMENT_EQUATION_INVALID")
    settlement_id = str(uuid.uuid4())
    clock = _iso(now)
    db.execute(
        "INSERT INTO payment_settlement_summaries("
        "id,provider,provider_mode,settlement_date,source_sha256,gross_fen,"
        "refund_fen,fee_fen,net_fen,status,created_at"
        ") VALUES(?,'adapay',?,?,?,?,?,?,?,'verified',?)",
        (
            settlement_id,
            "live" if prod_mode else "mock",
            day.isoformat(),
            digest,
            values[0],
            values[1],
            values[2],
            values[3],
            clock,
        ),
    )
    return {
        "id": settlement_id,
        "settlement_date": day.isoformat(),
        "gross_fen": values[0],
        "refund_fen": values[1],
        "fee_fen": values[2],
        "net_fen": values[3],
        "status": "verified",
    }


def finance_summary(*, since: str) -> dict[str, int]:
    """Return confirmed cash only; no active-plan or legacy inference."""
    row = db.fetchone(
        "SELECT "
        "COALESCE(SUM(CASE WHEN entry_type='payment_received' "
        "THEN amount_fen ELSE 0 END),0) AS received_fen,"
        "COALESCE(SUM(CASE WHEN entry_type='refund_paid' "
        "THEN -amount_fen ELSE 0 END),0) AS refunded_fen,"
        "COALESCE(SUM(CASE WHEN entry_type IN "
        "('payment_received','refund_paid') THEN amount_fen ELSE 0 END),0) "
        "AS net_fen,"
        "COALESCE(SUM(CASE WHEN entry_type IN "
        "('payment_received_unmatched','refund_paid_unmatched') "
        "THEN ABS(amount_fen) ELSE 0 END),0) AS unmatched_fen "
        "FROM payment_cash_ledger WHERE recorded_at>=?",
        (since,),
    )
    return {
        "received_fen": int(row["received_fen"] or 0),
        "refunded_fen": int(row["refunded_fen"] or 0),
        "net_fen": int(row["net_fen"] or 0),
        "unmatched_fen": int(row["unmatched_fen"] or 0),
    }
