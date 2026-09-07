"""Bounded live-payment operator for the short-lived Item31 canary role.

Each invocation performs at most one provider action. Provider payloads,
signatures, checkout data and credentials are never printed or persisted here.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

import db
import payment_adapter_runtime
import payment_contract


_PROVIDERS = {"wechatpay_direct", "alipay_direct"}
_ACTIONS = {
    "preflight",
    "query-payment",
    "submit-refund",
    "query-refund",
    "reconcile",
}
_REASONS = {
    "customer_request",
    "service_not_delivered",
    "duplicate_payment",
    "fraud_review",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_CANARY_AMOUNT_FEN = 1200
_MAX_ACTIVATION_WINDOW_SECONDS = 3600
_SYNTHETIC_ASSERTION = "ITEM31-SYNTHETIC-NO-REAL-USER"
_CANARY_USER_BINDING = "/etc/noteai-payment-canary-user-sha256"
_ACTION_LEDGER_DIRECTORY = "/var/lib/noteai/payment-canary-actions"
_SECRET_NAME_RE = re.compile(
    r"(?:PASSWORD|SECRET|TOKEN|COOKIES_JSON|COOKIE|CREDENTIALS?|"
    r"PRIVATE_KEY|PUBLIC_KEY|API_KEY|APP_KEY|WEB_KEY|MAP_KEY|ACCESS_KEY_ID|"
    r"SECRET_ACCESS_KEY|SIGN_KEY|AES_KEY|SIGN|AK)"
    r"(?:_B64)?$"
)
_PROVIDER_ALLOWED_SECRET_NAMES = {
    "wechatpay_direct": frozenset(
        {
            "DATABASE_URL",
            "NOTEAI_WECHATPAY_MERCHANT_PRIVATE_KEY_B64",
            "NOTEAI_WECHATPAY_PLATFORM_PUBLIC_KEY_B64",
        }
    ),
    "alipay_direct": frozenset(
        {
            "DATABASE_URL",
            "NOTEAI_ALIPAY_MERCHANT_PRIVATE_KEY_B64",
            "NOTEAI_ALIPAY_PUBLIC_KEY_B64",
        }
    ),
}


class PaymentCanaryError(RuntimeError):
    def __init__(self, code: str):
        self.code = str(code)
        super().__init__(self.code)


@dataclass(frozen=True)
class _ActionAdmission:
    descriptor: int
    directory_descriptor: int
    record: dict[str, Any]
    identity_sha256: str


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _write_exact(descriptor: int, value: bytes) -> None:
    view = memoryview(value)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short write")
        view = view[written:]


def _admit_action(activation: dict[str, Any]) -> _ActionAdmission:
    """Durably consume one semantic action before any provider request."""
    try:
        metadata = os.lstat(_ACTION_LEDGER_DIRECTORY)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or metadata.st_uid != os.geteuid()
            or metadata.st_gid != os.getegid()
        ):
            raise OSError("unsafe action directory")
        directory_descriptor = os.open(
            _ACTION_LEDGER_DIRECTORY,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(directory_descriptor)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) != 0o700
            or opened.st_uid != os.geteuid()
            or opened.st_gid != os.getegid()
            or opened.st_dev != metadata.st_dev
            or opened.st_ino != metadata.st_ino
        ):
            os.close(directory_descriptor)
            raise OSError("unsafe action directory")
    except OSError as exc:
        raise PaymentCanaryError("PAYMENT_CANARY_ACTION_LEDGER_INVALID") from exc
    activation_identity = _identity(
        activation["activation_id"],
        "payment-canary-activation-v1",
    )
    order_identity = _identity(
        activation["order_id"],
        "payment-order-v1",
    )
    subject_identity = _identity(
        activation["subject_hash"],
        "payment-canary-subject-v1",
    )
    semantic_identity = hashlib.sha256(
        _canonical_json(
            {
                "schema": "noteai.item31.payment_canary_action_identity.v1",
                "provider": activation["provider"],
                "action": activation["action"],
                "order_identity_sha256": order_identity,
                "bill_date": activation["bill_date"],
                "subject_identity_sha256": subject_identity,
                "amount_fen": activation["amount_fen"],
            }
        )
    ).hexdigest()
    filename = f"{semantic_identity}.json"
    record = {
        "schema": "noteai.item31.payment_canary_action.v1",
        "action_identity_sha256": semantic_identity,
        "activation_identity_sha256": activation_identity,
        "provider": activation["provider"],
        "action": activation["action"],
        "order_identity_sha256": order_identity,
        "bill_date": activation["bill_date"],
        "subject_identity_sha256": subject_identity,
        "amount_fen": activation["amount_fen"],
        "expires_at": activation["expires_at"],
        "state": "admitted",
        "result_sha256": None,
    }
    try:
        descriptor = os.open(
            filename,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory_descriptor,
        )
        os.fchmod(descriptor, 0o600)
        created = os.fstat(descriptor)
        if (
            not stat.S_ISREG(created.st_mode)
            or stat.S_IMODE(created.st_mode) != 0o600
            or created.st_uid != os.geteuid()
            or created.st_gid != os.getegid()
            or created.st_nlink != 1
        ):
            raise OSError("unsafe action file")
        _write_exact(descriptor, _canonical_json(record) + b"\n")
        os.fsync(descriptor)
        os.fsync(directory_descriptor)
    except FileExistsError as exc:
        os.close(directory_descriptor)
        raise PaymentCanaryError("PAYMENT_CANARY_ACTION_ALREADY_ADMITTED") from exc
    except Exception as exc:
        try:
            os.close(descriptor)
        except (OSError, UnboundLocalError):
            pass
        os.close(directory_descriptor)
        raise PaymentCanaryError("PAYMENT_CANARY_ACTION_LEDGER_INVALID") from exc
    return _ActionAdmission(
        descriptor=descriptor,
        directory_descriptor=directory_descriptor,
        record=record,
        identity_sha256=semantic_identity,
    )


def _seal_action(
    admission: _ActionAdmission,
    *,
    state: str,
    result: Any,
) -> None:
    if state not in {"completed", "sealed_unknown"}:
        raise PaymentCanaryError("PAYMENT_CANARY_ACTION_STATE_INVALID")
    terminal = {
        **admission.record,
        "state": state,
        "result_sha256": hashlib.sha256(_canonical_json(result)).hexdigest(),
    }
    try:
        os.lseek(admission.descriptor, 0, os.SEEK_SET)
        os.ftruncate(admission.descriptor, 0)
        _write_exact(admission.descriptor, _canonical_json(terminal) + b"\n")
        os.fsync(admission.descriptor)
        os.fsync(admission.directory_descriptor)
    except OSError as exc:
        raise PaymentCanaryError("PAYMENT_CANARY_ACTION_LEDGER_INVALID") from exc


def _close_action(admission: _ActionAdmission) -> None:
    for descriptor in (admission.descriptor, admission.directory_descriptor):
        try:
            os.close(descriptor)
        except OSError:
            pass


def _canonical_uuid(value: str, field: str) -> str:
    normalized = str(value or "").strip().lower()
    try:
        parsed = str(uuid.UUID(normalized))
    except (AttributeError, TypeError, ValueError) as exc:
        raise PaymentCanaryError(f"PAYMENT_CANARY_{field.upper()}_INVALID") from exc
    if parsed != normalized:
        raise PaymentCanaryError(f"PAYMENT_CANARY_{field.upper()}_INVALID")
    return normalized


def _provider_name(value: str) -> str:
    selected = str(value or "").strip()
    if selected not in _PROVIDERS:
        raise PaymentCanaryError("PAYMENT_CANARY_PROVIDER_INVALID")
    return selected


def _canonical_day(value: str) -> str:
    try:
        parsed = date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise PaymentCanaryError("PAYMENT_CANARY_BILL_DATE_INVALID") from exc
    if str(parsed) != str(value):
        raise PaymentCanaryError("PAYMENT_CANARY_BILL_DATE_INVALID")
    return str(parsed)


def _canonical_epoch(value: str, field: str) -> int:
    normalized = str(value or "").strip()
    if not normalized.isascii() or not normalized.isdigit():
        raise PaymentCanaryError(f"PAYMENT_CANARY_{field}_INVALID")
    parsed = int(normalized)
    if str(parsed) != normalized or not 946684800 <= parsed <= 4102444800:
        raise PaymentCanaryError(f"PAYMENT_CANARY_{field}_INVALID")
    return parsed


def _identity(value: str, domain: str) -> str:
    return hashlib.sha256(
        domain.encode("ascii") + b"\x00" + str(value).encode("ascii")
    ).hexdigest()


def _digest(domain: str, value: Any) -> str:
    return hashlib.sha256(
        domain.encode("ascii") + b"\x00" + _canonical_json(value)
    ).hexdigest()


def _refund_result_digest(
    result: payment_contract.ProviderRefundResult,
    provider_name: str,
) -> tuple[str, str | None]:
    provider_refund_id = str(result.provider_refund_id or "")
    provider_refund_identity_sha256 = (
        _identity(provider_refund_id, "payment-provider-refund-v1")
        if provider_refund_id
        else (
            _identity(
                str(result.merchant_refund_no),
                "noteai-item31-alipay-refund-out-request-no-v1",
            )
            if provider_name == "alipay_direct"
            else None
        )
    )
    projection = {
        "provider": provider_name,
        "status": str(result.status),
        "amount_fen": int(result.amount_fen),
        "currency": str(result.currency),
        "prod_mode": result.prod_mode,
        "response_verified": result.response_verified is True,
        "provider_created_at": result.provider_created_at,
        "provider_submitted_at": result.provider_submitted_at,
        "merchant_refund_identity_sha256": _identity(
            str(result.merchant_refund_no),
            "payment-provider-merchant-refund-v1",
        ),
        "merchant_order_identity_sha256": _identity(
            str(result.merchant_order_no),
            "payment-provider-merchant-order-v1",
        ),
        "provider_payment_identity_sha256": _identity(
            str(result.provider_payment_id),
            "payment-provider-payment-v1",
        ),
        "provider_refund_identity_sha256": provider_refund_identity_sha256,
        "application_identity_sha256": _identity(
            str(result.app_id),
            "payment-provider-application-v1",
        ),
    }
    return (
        _digest("noteai-item31-refund-verified-result-v1", projection),
        projection["provider_refund_identity_sha256"],
    )


def _bound_canary_user_id_sha256() -> str:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(_CANARY_USER_BINDING, flags)
    except OSError as exc:
        raise PaymentCanaryError("PAYMENT_CANARY_USER_BINDING_INVALID") from exc
    try:
        metadata = os.fstat(descriptor)
        raw = os.read(descriptor, 66)
    except OSError as exc:
        raise PaymentCanaryError("PAYMENT_CANARY_USER_BINDING_INVALID") from exc
    finally:
        os.close(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o444
        or metadata.st_nlink != 1
        or metadata.st_size != 65
        or len(raw) != 65
        or raw[-1:] != b"\n"
    ):
        raise PaymentCanaryError("PAYMENT_CANARY_USER_BINDING_INVALID")
    try:
        value = raw[:-1].decode("ascii")
    except UnicodeDecodeError as exc:
        raise PaymentCanaryError("PAYMENT_CANARY_USER_BINDING_INVALID") from exc
    if not _SHA256_RE.fullmatch(value):
        raise PaymentCanaryError("PAYMENT_CANARY_USER_BINDING_INVALID")
    return value


def _activation(action: str, provider_name: str, subject: str) -> dict[str, Any]:
    configured_action = os.environ.get("NOTEAI_PAYMENT_CANARY_ACTION", "").strip()
    configured_provider = os.environ.get(
        "NOTEAI_PAYMENT_CANARY_PROVIDER", ""
    ).strip()
    order_id = _canonical_uuid(
        os.environ.get("NOTEAI_PAYMENT_CANARY_ORDER_ID", ""),
        "order_id",
    )
    activation_id = _canonical_uuid(
        os.environ.get("NOTEAI_PAYMENT_CANARY_ACTIVATION_ID", ""),
        "activation_id",
    )
    user_id_sha256 = os.environ.get(
        "NOTEAI_PAYMENT_CANARY_USER_ID_SHA256", ""
    ).strip()
    subject_hash = os.environ.get(
        "NOTEAI_PAYMENT_CANARY_SUBJECT_HASH", ""
    ).strip()
    amount_text = os.environ.get("NOTEAI_PAYMENT_CANARY_AMOUNT_FEN", "").strip()
    if (
        configured_action != action
        or configured_provider != provider_name
        or not _SHA256_RE.fullmatch(user_id_sha256)
        or not _SHA256_RE.fullmatch(subject_hash)
        or not amount_text.isascii()
        or not amount_text.isdigit()
        or str(int(amount_text)) != amount_text
        or int(amount_text) != _MAX_CANARY_AMOUNT_FEN
        or os.environ.get("NOTEAI_PAYMENT_CANARY_SYNTHETIC_ASSERTION", "").strip()
        != _SYNTHETIC_ASSERTION
    ):
        raise PaymentCanaryError("PAYMENT_CANARY_ACTIVATION_INVALID")
    starts_at = _canonical_epoch(
        os.environ.get("NOTEAI_PAYMENT_CANARY_NOT_BEFORE_EPOCH", ""),
        "NOT_BEFORE_EPOCH",
    )
    expires_at = _canonical_epoch(
        os.environ.get("NOTEAI_PAYMENT_CANARY_EXPIRES_EPOCH", ""),
        "EXPIRES_EPOCH",
    )
    now_epoch = int(time.time())
    if (
        starts_at > now_epoch
        or now_epoch > expires_at
        or expires_at <= starts_at
        or expires_at - starts_at > _MAX_ACTIVATION_WINDOW_SECONDS
    ):
        raise PaymentCanaryError("PAYMENT_CANARY_ACTIVATION_WINDOW_INVALID")
    if action == "reconcile":
        bill_date = _canonical_day(subject)
        if bill_date != os.environ.get(
            "NOTEAI_PAYMENT_CANARY_BILL_DATE", ""
        ).strip():
            raise PaymentCanaryError("PAYMENT_CANARY_ACTIVATION_INVALID")
    else:
        bill_date = ""
        if _canonical_uuid(subject, "order_id") != order_id:
            raise PaymentCanaryError("PAYMENT_CANARY_ACTIVATION_INVALID")
    return {
        "action": action,
        "provider": provider_name,
        "order_id": order_id,
        "activation_id": activation_id,
        "user_id_sha256": user_id_sha256,
        "subject_hash": subject_hash,
        "amount_fen": int(amount_text),
        "bill_date": bill_date,
        "expires_at": expires_at,
    }


def _database_role_ok() -> bool:
    if not db.using_postgres():
        return False
    try:
        row = db.fetchone(
            "SELECT current_user AS current_role,session_user AS session_role,"
            "current_setting('transaction_read_only') AS transaction_read_only,"
            "current_setting('default_transaction_read_only') "
            "AS default_transaction_read_only"
        )
        schema = db.fetchone(
            "SELECT EXISTS(SELECT 1 FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='payment_refunds' "
            "AND column_name='provider_submitted_at') "
            "AS refund_column_present,"
            "has_column_privilege(current_user,'public.payment_refunds',"
            "'provider_submitted_at','UPDATE') AS refund_column_update,"
            "EXISTS(SELECT 1 FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='payment_events' "
            "AND column_name='duplicate_delivery_count') "
            "AS event_column_present,"
            "has_column_privilege(current_user,'public.payment_events',"
            "'duplicate_delivery_count','UPDATE') AS event_column_update"
        )
        privileges = db.fetchone(
            "SELECT "
            "has_table_privilege(current_user,'public.payment_orders','SELECT')"
            " AND has_table_privilege(current_user,'public.payment_refunds','SELECT')"
            " AND has_table_privilege(current_user,'public.payment_refunds','INSERT')"
            " AND has_table_privilege(current_user,'public.payment_events','SELECT')"
            " AND has_table_privilege(current_user,'public.payment_events','INSERT')"
            " AND has_table_privilege(current_user,'public.payment_cash_ledger','SELECT')"
            " AND has_table_privilege(current_user,'public.payment_cash_ledger','INSERT')"
            " AND has_table_privilege(current_user,'public.payment_entitlement_ledger','SELECT')"
            " AND has_table_privilege(current_user,'public.payment_entitlement_ledger','INSERT')"
            " AND has_table_privilege(current_user,'public.payment_credit_positions','SELECT')"
            " AND has_table_privilege(current_user,'public.payment_credit_positions','INSERT')"
            " AND has_table_privilege(current_user,'public.payment_credit_consumptions','SELECT')"
            " AND has_table_privilege(current_user,'public.payment_reconciliation_runs','SELECT')"
            " AND has_table_privilege(current_user,'public.payment_reconciliation_runs','INSERT')"
            " AND has_table_privilege(current_user,'public.payment_reconciliation_items','SELECT')"
            " AND has_table_privilege(current_user,'public.payment_reconciliation_items','INSERT')"
            " AND has_table_privilege(current_user,'public.payment_settlement_summaries','SELECT')"
            " AND has_table_privilege(current_user,'public.payment_settlement_summaries','INSERT')"
            " AND has_table_privilege(current_user,'public.subscriptions','INSERT')"
            " AND has_table_privilege(current_user,'public.credits','INSERT')"
            " AND has_table_privilege(current_user,'public.credit_transactions','INSERT')"
            " AND has_column_privilege(current_user,'public.users','id','SELECT')"
            " AND has_column_privilege(current_user,'public.users','deletion_requested_at','SELECT')"
            " AND has_column_privilege(current_user,'public.subscriptions','id','SELECT')"
            " AND has_column_privilege(current_user,'public.subscriptions','user_id','SELECT')"
            " AND has_column_privilege(current_user,'public.subscriptions','tier','SELECT')"
            " AND has_column_privilege(current_user,'public.subscriptions','started_at','SELECT')"
            " AND has_column_privilege(current_user,'public.subscriptions','is_active','SELECT')"
            " AND has_column_privilege(current_user,'public.subscriptions','is_active','UPDATE')"
            " AND has_column_privilege(current_user,'public.credits','user_id','SELECT')"
            " AND has_column_privilege(current_user,'public.credits','balance','SELECT')"
            " AND has_column_privilege(current_user,'public.credits','balance','UPDATE')"
            " AND has_column_privilege(current_user,'public.credits','total_purchased','SELECT')"
            " AND has_column_privilege(current_user,'public.credits','total_purchased','UPDATE')"
            " AND has_column_privilege(current_user,'public.credits','updated_at','UPDATE')"
            " AND has_column_privilege(current_user,'public.usage_records','user_id','SELECT')"
            " AND has_column_privilege(current_user,'public.usage_records','recorded_at','SELECT')"
            " AND has_column_privilege(current_user,'public.usage_records','credits_used','SELECT')"
            " AND has_column_privilege(current_user,'public.usage_records','source','SELECT')"
            " AND has_column_privilege(current_user,'public.payment_orders','provider_payment_id','UPDATE')"
            " AND has_column_privilege(current_user,'public.payment_orders','payment_status','UPDATE')"
            " AND has_column_privilege(current_user,'public.payment_orders','entitlement_status','UPDATE')"
            " AND has_column_privilege(current_user,'public.payment_orders','entitlement_ref','UPDATE')"
            " AND has_column_privilege(current_user,'public.payment_orders','refund_status','UPDATE')"
            " AND has_column_privilege(current_user,'public.payment_orders','refunded_fen','UPDATE')"
            " AND has_column_privilege(current_user,'public.payment_orders','refund_count','UPDATE')"
            " AND has_column_privilege(current_user,'public.payment_orders','updated_at','UPDATE')"
            " AND has_column_privilege(current_user,'public.payment_orders','succeeded_at','UPDATE')"
            " AND has_column_privilege(current_user,'public.payment_orders','terminal_at','UPDATE')"
            " AND has_column_privilege(current_user,'public.payment_refunds','provider_refund_id','UPDATE')"
            " AND has_column_privilege(current_user,'public.payment_refunds','provider_submitted_at','UPDATE')"
            " AND has_column_privilege(current_user,'public.payment_refunds','status','UPDATE')"
            " AND has_column_privilege(current_user,'public.payment_refunds','updated_at','UPDATE')"
            " AND has_column_privilege(current_user,'public.payment_refunds','terminal_at','UPDATE')"
            " AND has_column_privilege(current_user,'public.payment_events','processing_state','UPDATE')"
            " AND has_column_privilege(current_user,'public.payment_events','reason_code','UPDATE')"
            " AND has_column_privilege(current_user,'public.payment_events','order_id','UPDATE')"
            " AND has_column_privilege(current_user,'public.payment_events','refund_id','UPDATE')"
            " AND has_column_privilege(current_user,'public.payment_events','processed_at','UPDATE')"
            " AND has_column_privilege(current_user,'public.payment_credit_positions','user_id','UPDATE')"
            " AND has_column_privilege(current_user,'public.payment_credit_positions','remaining_milli','UPDATE')"
            " AND has_column_privilege(current_user,'public.payment_credit_positions','state','UPDATE')"
            " AND has_column_privilege(current_user,'public.payment_credit_positions','updated_at','UPDATE')"
            " AS required_privileges"
        )
    except Exception:
        return False
    return bool(
        row
        and schema
        and privileges
        and row["current_role"] == "noteai_payment"
        and row["session_role"] == "noteai_payment"
        and row["transaction_read_only"] == "off"
        and row["default_transaction_read_only"] == "off"
        and schema["refund_column_present"] is True
        and schema["refund_column_update"] is True
        and schema["event_column_present"] is True
        and schema["event_column_update"] is True
        and privileges["required_privileges"] is True
    )


def _provider_secret_scope_ok(provider_name: str) -> bool:
    selected = _provider_name(provider_name)
    allowed = _PROVIDER_ALLOWED_SECRET_NAMES[selected]
    present = {
        name
        for name, value in os.environ.items()
        if value
        and (
            name == "DATABASE_URL"
            or _SECRET_NAME_RE.search(name) is not None
            or name
            in {
                "NOTEAI_WECHATPAY_API_V3_KEY",
                "NOTEAI_ADAPAY_PUBLIC_KEY",
            }
        )
    }
    return present.issubset(allowed)


def _assert_runtime_context(provider_name: str) -> None:
    selected = _provider_name(provider_name)
    if (
        os.environ.get("NOTEAI_RUNTIME_ROLE", "").strip() != "payment-canary"
        or os.environ.get("NOTEAI_DEPLOYMENT_STAGE", "").strip().lower()
        != "production"
        or os.environ.get("NOTEAI_PAYMENT_CANARY_ENABLED", "").strip() != "1"
        or not payment_adapter_runtime.configured_prod_mode(selected)
        or not _database_role_ok()
        or not _provider_secret_scope_ok(selected)
    ):
        raise PaymentCanaryError("PAYMENT_CANARY_CONTEXT_INVALID")


def _gateway(provider_name: str):
    selected = _provider_name(provider_name)
    _assert_runtime_context(selected)
    identity = payment_adapter_runtime.callback_identity_sha256(selected)
    if not _SHA256_RE.fullmatch(identity):
        raise PaymentCanaryError("PAYMENT_CANARY_IDENTITY_INVALID")
    gateway = payment_adapter_runtime.provider_from_environment(
        selected,
        required_role="payment-canary",
    )
    if gateway is None:
        raise PaymentCanaryError("PAYMENT_CANARY_PROVIDER_UNAVAILABLE")
    return gateway, identity


def _order(
    order_id: str,
    provider_name: str,
    activation: dict[str, Any],
) -> dict[str, Any]:
    bound_user_id_sha256 = _bound_canary_user_id_sha256()
    row = db.fetchone(
        "SELECT * FROM payment_orders WHERE id=?",
        (_canonical_uuid(order_id, "order_id"),),
    )
    if (
        row is None
        or row["provider"] != provider_name
        or row["provider_mode"] != "live"
        or row["subject_hash"] != activation["subject_hash"]
        or int(row["amount_fen"]) != activation["amount_fen"]
        or not row["user_id"]
        or _identity(row["user_id"], "payment-canary-user-v1")
        != activation["user_id_sha256"]
        or activation["user_id_sha256"] != bound_user_id_sha256
    ):
        raise PaymentCanaryError("PAYMENT_CANARY_ORDER_MISMATCH")
    return dict(row)


def _refund_for_order(
    order: dict[str, Any],
    provider_name: str,
    activation: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    refund = db.fetchone(
        "SELECT * FROM payment_refunds WHERE order_id=?",
        (order["id"],),
    )
    if refund is None:
        raise PaymentCanaryError("PAYMENT_CANARY_REFUND_NOT_FOUND")
    verified_order = _order(str(refund["order_id"]), provider_name, activation)
    return dict(refund), verified_order


def _preflight(
    provider_name: str,
    identity: str,
    order: dict[str, Any],
    activation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "ok": True,
        "operation": "preflight",
        "provider": provider_name,
        "provider_mode": "live",
        "database_role": "verified",
        "callback_identity_sha256": identity,
        "activation_identity_sha256": _identity(
            activation["activation_id"], "payment-canary-activation-v1"
        ),
        "order_identity_sha256": _identity(order["id"], "payment-order-v1"),
        "synthetic_subject": "verified",
        "amount_fen": activation["amount_fen"],
        "provider_operation_count": 0,
        "automatic_retry_count": 0,
    }


def _query_payment(
    gateway: Any,
    provider_name: str,
    order: dict[str, Any],
    activation: dict[str, Any],
) -> dict[str, Any]:
    gateway.process_payment_query(
        payment_contract.ProviderPaymentLookup(
            merchant_order_no=str(order["merchant_order_no"]),
            provider_payment_id=str(order["provider_payment_id"] or ""),
            expected_amount_fen=int(order["amount_fen"]),
        )
    )
    readback = _order(str(order["id"]), provider_name, activation)
    return {
        "ok": True,
        "operation": "query-payment",
        "provider": provider_name,
        "order_identity_sha256": _identity(order["id"], "payment-order-v1"),
        "payment_status": str(readback["payment_status"]),
        "entitlement_status": str(readback["entitlement_status"]),
        "provider_operation_count": 1,
        "automatic_retry_count": 0,
    }


def _submit_refund(
    gateway: Any,
    provider_name: str,
    order: dict[str, Any],
    activation: dict[str, Any],
    reason_code: str,
) -> dict[str, Any]:
    reason = str(reason_code or "").strip()
    if reason not in _REASONS:
        raise PaymentCanaryError("PAYMENT_CANARY_REFUND_REASON_INVALID")
    prepared = payment_contract.prepare_full_refund(
        str(order["id"]),
        reason_code=reason,
    )
    refund = db.fetchone(
        "SELECT * FROM payment_refunds WHERE id=?",
        (prepared["id"],),
    )
    if refund is None or not payment_contract.admit_refund_submission(
        str(refund["id"])
    ):
        raise PaymentCanaryError("PAYMENT_CANARY_REFUND_ADMISSION_FAILED")
    provider_request = payment_contract.provider_refund_request(refund, order)
    request_sha256 = _digest(
        "noteai-item31-refund-provider-request-v1",
        provider_request,
    )
    try:
        result = gateway.create_refund(provider_request)
    except Exception as exc:
        raise PaymentCanaryError("PAYMENT_PROVIDER_OUTCOME_UNKNOWN") from exc
    try:
        payment_contract.mark_refund_submission(str(refund["id"]), result)
    except Exception as exc:
        raise PaymentCanaryError("PAYMENT_PROVIDER_RESPONSE_INVALID") from exc
    response_sha256, provider_refund_identity_sha256 = _refund_result_digest(
        result,
        provider_name,
    )
    readback, _order_row = _refund_for_order(order, provider_name, activation)
    return {
        "ok": True,
        "operation": "submit-refund",
        "provider": provider_name,
        "order_identity_sha256": _identity(order["id"], "payment-order-v1"),
        "refund_identity_sha256": _identity(refund["id"], "payment-refund-v1"),
        "provider_refund_identity_sha256": provider_refund_identity_sha256,
        "request_sha256": request_sha256,
        "response_sha256": response_sha256,
        "refund_status": str(readback["status"]),
        "provider_operation_count": 1,
        "automatic_retry_count": 0,
    }


def _query_refund(
    gateway: Any,
    provider_name: str,
    order: dict[str, Any],
    activation: dict[str, Any],
) -> dict[str, Any]:
    refund, order = _refund_for_order(order, provider_name, activation)
    gateway.process_refund_query(
        payment_contract.ProviderRefundLookup(
            merchant_refund_no=str(refund["merchant_refund_no"]),
            merchant_order_no=str(order["merchant_order_no"]),
            provider_payment_id=str(order["provider_payment_id"] or ""),
            provider_refund_id=str(refund["provider_refund_id"] or ""),
        )
    )
    readback, order_readback = _refund_for_order(order, provider_name, activation)
    return {
        "ok": True,
        "operation": "query-refund",
        "provider": provider_name,
        "refund_identity_sha256": _identity(refund["id"], "payment-refund-v1"),
        "refund_status": str(readback["status"]),
        "order_refund_status": str(order_readback["refund_status"]),
        "entitlement_status": str(order_readback["entitlement_status"]),
        "provider_operation_count": 1,
        "automatic_retry_count": 0,
    }


def _reconcile(gateway: Any, provider_name: str, bill_date: str) -> dict[str, Any]:
    canonical_day = _canonical_day(bill_date)
    source, rows = gateway.reconciliation_rows(canonical_day)
    result = payment_contract.reconcile_bill(
        canonical_day,
        source,
        rows,
        prod_mode=True,
        provider_name=provider_name,
    )
    return {
        "ok": result["status"] == "matched",
        "operation": "reconcile",
        "provider": provider_name,
        "bill_date": canonical_day,
        "status": str(result["status"]),
        "row_count": int(result["row_count"]),
        "discrepancy_count": int(result["discrepancy_count"]),
        "source_sha256": str(result["source_sha256"]),
        "provider_operation_count": 1,
        "automatic_retry_count": 0,
    }


def execute(argv: list[str]) -> dict[str, Any]:
    if len(argv) < 2:
        raise PaymentCanaryError("PAYMENT_CANARY_ARGUMENTS_INVALID")
    action = str(argv[0])
    provider_name = _provider_name(argv[1])
    if action not in _ACTIONS:
        raise PaymentCanaryError("PAYMENT_CANARY_ACTION_INVALID")
    valid_shape = (
        (action == "preflight" and len(argv) == 3)
        or (
            action in {"query-payment", "query-refund", "reconcile"}
            and len(argv) == 3
        )
        or (action == "submit-refund" and len(argv) == 4)
    )
    if not valid_shape:
        raise PaymentCanaryError("PAYMENT_CANARY_ARGUMENTS_INVALID")
    if action in {"preflight", "query-payment", "query-refund"}:
        _canonical_uuid(argv[2], "order_id")
    elif action == "reconcile":
        _canonical_day(argv[2])
    elif action == "submit-refund":
        _canonical_uuid(argv[2], "order_id")
        if str(argv[3] or "").strip() not in _REASONS:
            raise PaymentCanaryError("PAYMENT_CANARY_REFUND_REASON_INVALID")
    activation = _activation(action, provider_name, argv[2])
    _assert_runtime_context(provider_name)
    order = _order(activation["order_id"], provider_name, activation)
    gateway, identity = _gateway(provider_name)
    if action == "preflight":
        return _preflight(provider_name, identity, order, activation)
    admission = _admit_action(activation)
    try:
        if action == "query-payment":
            result = _query_payment(gateway, provider_name, order, activation)
        elif action == "query-refund":
            result = _query_refund(gateway, provider_name, order, activation)
        elif action == "reconcile":
            result = _reconcile(gateway, provider_name, argv[2])
        elif action == "submit-refund":
            result = _submit_refund(
                gateway,
                provider_name,
                order,
                activation,
                argv[3],
            )
        else:  # pragma: no cover - action validated before admission
            raise PaymentCanaryError("PAYMENT_CANARY_ACTION_INVALID")
    except Exception as exc:
        code = getattr(exc, "code", "PAYMENT_CANARY_INTERNAL_ERROR")
        try:
            _seal_action(
                admission,
                state="sealed_unknown",
                result={"code": str(code)},
            )
        finally:
            _close_action(admission)
        raise
    try:
        _seal_action(admission, state="completed", result=result)
    finally:
        _close_action(admission)
    return {**result, "action_admission_sha256": admission.identity_sha256}


def main() -> int:
    try:
        result = execute(sys.argv[1:])
        print(json.dumps(result, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
        return 0 if result.get("ok") is True else 1
    except (PaymentCanaryError, payment_contract.PaymentContractError) as exc:
        code = getattr(exc, "code", "PAYMENT_CANARY_REJECTED")
        print(json.dumps({"ok": False, "code": code}, separators=(",", ":")))
        return 1
    except Exception:
        print(
            json.dumps(
                {"ok": False, "code": "PAYMENT_CANARY_INTERNAL_ERROR"},
                separators=(",", ":"),
            )
        )
        return 1
    finally:
        payment_adapter_runtime.close_configured_providers()


if __name__ == "__main__":
    raise SystemExit(main())
