"""Direct WeChat Pay and Alipay gateways over an injected signed transport.

The gateways contain provider-specific request/response mapping and callback
authentication.  They never select credentials from the environment, retry a
request, log provider material or create a second billing state machine.  A
production transport must perform the provider request signing and response
authentication before returning ``VerifiedDirectResponse``/``VerifiedDirectBill``.
"""

from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import io
import json
import math
import re
import secrets
import time
import zipfile
import zlib
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable, Mapping, Protocol
from urllib.parse import parse_qsl, quote, urlencode, urlsplit
from zoneinfo import ZoneInfo

import httpx
from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import payment_contract


MAX_DIRECT_RESPONSE_BYTES = 64 * 1024
MAX_DIRECT_REQUEST_SECONDS = 30.0
MAX_CHECKOUT_VALUE_BYTES = 4096
MAX_CALLBACK_AGE_SECONDS = 300
MAX_PEM_BYTES = 12 * 1024
MAX_PEM_B64_BYTES = ((MAX_PEM_BYTES + 2) // 3) * 4
WECHATPAY_API_ORIGIN = "https://api.mch.weixin.qq.com"
ALIPAY_GATEWAY_URL = "https://openapi.alipay.com/gateway.do"
WECHATPAY_CALLBACK_URL = "https://api.noteaipro.cn/payments/wechat/callback"
ALIPAY_CALLBACK_URL = "https://api.noteaipro.cn/payments/alipay/callback"

_APP_ID_RE = re.compile(r"^[A-Za-z0-9_:-]{3,64}$")
_OPAQUE_RE = re.compile(r"^[A-Za-z0-9_:-]{1,128}$")
_WECHAT_MERCHANT_RE = re.compile(r"^[0-9]{6,32}$")
_WECHAT_SERIAL_RE = re.compile(r"^[A-Fa-f0-9]{16,64}$")
_WECHAT_PUBLIC_KEY_ID_RE = re.compile(r"^PUB_KEY_ID_[A-Za-z0-9_-]{8,128}$")
_ALIPAY_SELLER_RE = re.compile(r"^[0-9]{16}$")
_ALIPAY_AMOUNT_RE = re.compile(r"^(?:0|[1-9][0-9]{0,8})\.[0-9]{2}$")
_WECHAT_BILL_AMOUNT_RE = re.compile(r"^(?:0|[1-9][0-9]{0,10})\.[0-9]{2}$")
_WECHAT_BILL_COUNT_RE = re.compile(r"^(?:0|[1-9][0-9]{0,4})$")
_SHA1_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_NONCE_RE = re.compile(r"^[\x21-\x7e]{1,64}$")

_WECHAT_TRADE_BILL_HOSTS = frozenset(
    {"api.mch.weixin.qq.com", "api2.mch.weixin.qq.com"}
)
_WECHAT_TRADE_BILL_DETAIL_HEADER = (
    "交易时间",
    "公众账号ID",
    "商户号",
    "特约商户号",
    "设备号",
    "微信订单号",
    "商户订单号",
    "用户标识",
    "交易类型",
    "交易状态",
    "付款银行",
    "货币种类",
    "应结订单金额",
    "代金券金额",
    "微信退款单号",
    "商户退款单号",
    "退款金额",
    "充值券退款金额",
    "退款类型",
    "退款状态",
    "商品名称",
    "商户数据包",
    "手续费",
    "费率",
    "订单金额",
    "申请退款金额",
    "费率备注",
)
_WECHAT_TRADE_BILL_SUMMARY_HEADER = (
    "总交易单数",
    "应结订单总金额",
    "退款总金额",
    "充值券退款总金额",
    "手续费总金额",
    "订单总金额",
    "申请退款总金额",
)
_ALIPAY_TRADE_BILL_HOSTS = frozenset({"dwbillcenter.alipay.com"})
_ALIPAY_TRADE_BILL_REQUIRED_HEADERS = frozenset(
    {
        "商户订单号",
        "业务类型",
        "完成时间",
        "订单金额（元）",
        "退款批次号/请求号",
    }
)


class DirectPaymentGatewayError(payment_contract.PaymentContractError):
    """Stable direct-provider error without raw provider content."""


@dataclass(frozen=True, repr=False)
class VerifiedDirectResponse:
    provider_name: str
    body: Mapping[str, Any]
    raw_body: bytes
    signature: str
    verified_at: int
    response_verified: bool

    def __repr__(self) -> str:
        return (
            "VerifiedDirectResponse("
            f"provider_name={self.provider_name!r},"
            f"verified_at={self.verified_at!r},"
            f"response_verified={self.response_verified!r},"
            "body_redacted=True,raw_body_redacted=True,signature_redacted=True)"
        )


@dataclass(frozen=True, repr=False)
class VerifiedDirectBill:
    provider_name: str
    bill_date: str
    source_bytes: bytes
    rows: Iterable[Mapping[str, Any]]
    authentication_mode: str

    def __repr__(self) -> str:
        return (
            "VerifiedDirectBill("
            f"provider_name={self.provider_name!r},bill_date={self.bill_date!r},"
            "source_bytes_redacted=True,rows_redacted=True,"
            f"authentication_mode={self.authentication_mode!r})"
        )


@dataclass(frozen=True, repr=False)
class AuthenticatedDirectCallback:
    event: payment_contract.CallbackEvent
    raw_body: bytes
    signature: str
    signature_input_sha256: str

    def __repr__(self) -> str:
        return (
            "AuthenticatedDirectCallback("
            f"provider_name={self.event.provider_name!r},"
            f"event_type={self.event.event_type!r},raw_body_redacted=True,"
            "signature_redacted=True,signature_input_redacted=True)"
        )


def _callback_audit(
    callback: AuthenticatedDirectCallback,
    *,
    signature_scheme: str,
) -> dict[str, str]:
    event = callback.event
    identity = hashlib.sha256(
        f"noteai-{event.provider_name}-event-id-v1".encode("ascii")
        + b"\0"
        + event.provider_event_id.encode("utf-8")
    ).hexdigest()
    return {
        "schema": "noteai.item31.direct_callback_digest.v1",
        "provider": event.provider_name,
        "event_type": event.event_type,
        "callback_identity_sha256": identity,
        "callback_payload_sha256": hashlib.sha256(callback.raw_body).hexdigest(),
        "signature_input_sha256": callback.signature_input_sha256,
        "signature_scheme": signature_scheme,
    }


class DirectPaymentTransport(Protocol):
    """One-attempt signed wire transport configured for direct providers."""

    def request(
        self,
        provider_name: str,
        operation: str,
        payload: Mapping[str, Any],
    ) -> VerifiedDirectResponse:
        """Return one authenticated response and its exact signed JSON bytes."""

    def reconciliation(
        self,
        provider_name: str,
        bill_date: str,
    ) -> VerifiedDirectBill:
        """Fetch and authenticate one provider reconciliation source."""


def _fail(code: str) -> DirectPaymentGatewayError:
    return DirectPaymentGatewayError(code)


def _opaque(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not _OPAQUE_RE.fullmatch(normalized):
        raise _fail(f"PAYMENT_PROVIDER_{field.upper()}_INVALID")
    return normalized


def _app_id(value: Any) -> str:
    normalized = str(value or "").strip()
    if not _APP_ID_RE.fullmatch(normalized):
        raise _fail("PAYMENT_PROVIDER_APP_ID_INVALID")
    return normalized


def _positive_fen(value: Any, field: str = "amount") -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _fail(f"PAYMENT_PROVIDER_{field.upper()}_INVALID")
    if value <= 0 or value > 100_000_000:
        raise _fail(f"PAYMENT_PROVIDER_{field.upper()}_INVALID")
    return value


def _nonnegative_fen(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _fail(f"PAYMENT_PROVIDER_{field.upper()}_INVALID")
    if value < 0 or value > 100_000_000:
        raise _fail(f"PAYMENT_PROVIDER_{field.upper()}_INVALID")
    return value


def _fen_from_decimal(value: Any, field: str = "amount") -> int:
    if not isinstance(value, str) or not _ALIPAY_AMOUNT_RE.fullmatch(value):
        raise _fail(f"PAYMENT_PROVIDER_{field.upper()}_INVALID")
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise _fail(f"PAYMENT_PROVIDER_{field.upper()}_INVALID") from exc
    if not amount.is_finite() or amount.as_tuple().exponent < -2:
        raise _fail(f"PAYMENT_PROVIDER_{field.upper()}_INVALID")
    fen = amount * 100
    if fen != fen.to_integral_value():
        raise _fail(f"PAYMENT_PROVIDER_{field.upper()}_INVALID")
    return _positive_fen(int(fen), field)


def _fen_text(value: int) -> str:
    amount = _positive_fen(value)
    return f"{amount // 100}.{amount % 100:02d}"


def _wechat_bill_fen(value: Any) -> int:
    if not isinstance(value, str) or not _WECHAT_BILL_AMOUNT_RE.fullmatch(value):
        raise _fail("PAYMENT_PROVIDER_BILL_AMOUNT_INVALID")
    try:
        amount = Decimal(value) * 100
    except (InvalidOperation, ValueError) as exc:
        raise _fail("PAYMENT_PROVIDER_BILL_AMOUNT_INVALID") from exc
    if not amount.is_finite() or amount != amount.to_integral_value():
        raise _fail("PAYMENT_PROVIDER_BILL_AMOUNT_INVALID")
    fen = int(amount)
    if fen < 0 or fen > 999_999_999_999:
        raise _fail("PAYMENT_PROVIDER_BILL_AMOUNT_INVALID")
    return fen


def _wechat_bill_values(row: list[str], expected_length: int) -> tuple[str, ...]:
    if len(row) != expected_length or any(
        not isinstance(value, str) or not value.startswith("`") for value in row
    ):
        raise _fail("PAYMENT_PROVIDER_BILL_SCHEMA_INVALID")
    return tuple(value[1:] for value in row)


def _parse_wechat_trade_bill(
    source: bytes,
    *,
    expected_bill_date: str,
    expected_app_id: str,
    expected_merchant_id: str,
) -> tuple[dict[str, Any], ...]:
    try:
        bill_day = date.fromisoformat(str(expected_bill_date))
    except (TypeError, ValueError) as exc:
        raise _fail("PAYMENT_PROVIDER_BILL_DATE_INVALID") from exc
    app_id = _app_id(expected_app_id)
    merchant_id = str(expected_merchant_id or "").strip()
    if (
        str(bill_day) != str(expected_bill_date)
        or not _WECHAT_MERCHANT_RE.fullmatch(merchant_id)
    ):
        raise _fail("PAYMENT_PROVIDER_BILL_IDENTITY_INVALID")
    try:
        text = source.decode("utf-8-sig")
    except UnicodeError as exc:
        raise _fail("PAYMENT_PROVIDER_BILL_SCHEMA_INVALID") from exc
    if not text or "\x00" in text:
        raise _fail("PAYMENT_PROVIDER_BILL_SCHEMA_INVALID")
    try:
        parsed_rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except (csv.Error, UnicodeError) as exc:
        raise _fail("PAYMENT_PROVIDER_BILL_SCHEMA_INVALID") from exc
    while parsed_rows and not parsed_rows[-1]:
        parsed_rows.pop()
    if not parsed_rows or tuple(parsed_rows[0]) != _WECHAT_TRADE_BILL_DETAIL_HEADER:
        raise _fail("PAYMENT_PROVIDER_BILL_SCHEMA_INVALID")

    canonical: list[dict[str, Any]] = []
    order_total_fen = 0
    refund_application_total_fen = 0
    index = 1
    while index < len(parsed_rows):
        row = parsed_rows[index]
        if tuple(row) == _WECHAT_TRADE_BILL_SUMMARY_HEADER:
            break
        if not row:
            while index < len(parsed_rows) and not parsed_rows[index]:
                index += 1
            break
        values = _wechat_bill_values(
            row,
            len(_WECHAT_TRADE_BILL_DETAIL_HEADER),
        )
        if len(canonical) >= payment_contract.MAX_RECONCILIATION_ROWS:
            raise _fail("PAYMENT_PROVIDER_BILL_ROW_LIMIT")
        try:
            transaction_time = datetime.strptime(
                values[0],
                "%Y-%m-%d %H:%M:%S",
            )
        except ValueError as exc:
            raise _fail("PAYMENT_PROVIDER_BILL_DATE_INVALID") from exc
        if transaction_time.date() != bill_day:
            raise _fail("PAYMENT_PROVIDER_BILL_DATE_MISMATCH")
        if values[1] != app_id or values[2] != merchant_id:
            raise _fail("PAYMENT_PROVIDER_BILL_IDENTITY_MISMATCH")
        if values[11] != "CNY":
            raise _fail("PAYMENT_PROVIDER_BILL_CURRENCY_INVALID")
        order_fen = _wechat_bill_fen(values[24])
        refund_application_fen = _wechat_bill_fen(values[25])
        order_total_fen += order_fen
        refund_application_total_fen += refund_application_fen
        transaction_state = values[9]
        if transaction_state == "SUCCESS":
            reference = _opaque(values[6], "bill_reference")
            if order_fen <= 0 or refund_application_fen != 0:
                raise _fail("PAYMENT_PROVIDER_BILL_ROW_INVALID")
            canonical.append(
                {
                    "kind": "payment",
                    "reference": reference,
                    "amount_fen": order_fen,
                    "status": "succeeded",
                }
            )
        elif transaction_state == "REFUND":
            reference = _opaque(values[15], "bill_reference")
            if order_fen != 0 or refund_application_fen <= 0:
                raise _fail("PAYMENT_PROVIDER_BILL_ROW_INVALID")
            refund_status = {
                "SUCCESS": "succeeded",
                "PROCESSING": "pending",
                "FAIL": "failed",
            }.get(values[19])
            if values[19] == "CHANGE":
                raise _fail("PAYMENT_PROVIDER_BILL_REFUND_REQUIRES_MANUAL")
            if refund_status is None:
                raise _fail("PAYMENT_PROVIDER_BILL_ROW_INVALID")
            canonical.append(
                {
                    "kind": "refund",
                    "reference": reference,
                    "amount_fen": refund_application_fen,
                    "status": refund_status,
                }
            )
        else:
            raise _fail("PAYMENT_PROVIDER_BILL_ROW_INVALID")
        index += 1

    if (
        index >= len(parsed_rows)
        or tuple(parsed_rows[index]) != _WECHAT_TRADE_BILL_SUMMARY_HEADER
    ):
        raise _fail("PAYMENT_PROVIDER_BILL_SCHEMA_INVALID")
    index += 1
    if index >= len(parsed_rows):
        raise _fail("PAYMENT_PROVIDER_BILL_SCHEMA_INVALID")
    summary = _wechat_bill_values(
        parsed_rows[index],
        len(_WECHAT_TRADE_BILL_SUMMARY_HEADER),
    )
    index += 1
    while index < len(parsed_rows) and not parsed_rows[index]:
        index += 1
    if index != len(parsed_rows) or not _WECHAT_BILL_COUNT_RE.fullmatch(summary[0]):
        raise _fail("PAYMENT_PROVIDER_BILL_SCHEMA_INVALID")
    if (
        int(summary[0]) != len(canonical)
        or _wechat_bill_fen(summary[5]) != order_total_fen
        or _wechat_bill_fen(summary[6]) != refund_application_total_fen
    ):
        raise _fail("PAYMENT_PROVIDER_BILL_SUMMARY_MISMATCH")
    return tuple(canonical)


def _alipay_bill_fen(value: Any) -> int:
    normalized = str(value or "").strip()
    if not re.fullmatch(r"-?(?:0|[1-9][0-9]{0,8})\.[0-9]{2}", normalized):
        raise _fail("PAYMENT_PROVIDER_BILL_AMOUNT_INVALID")
    try:
        amount = Decimal(normalized) * 100
    except (InvalidOperation, ValueError) as exc:
        raise _fail("PAYMENT_PROVIDER_BILL_AMOUNT_INVALID") from exc
    if not amount.is_finite() or amount != amount.to_integral_value():
        raise _fail("PAYMENT_PROVIDER_BILL_AMOUNT_INVALID")
    fen = abs(int(amount))
    if fen <= 0 or fen > 100_000_000:
        raise _fail("PAYMENT_PROVIDER_BILL_AMOUNT_INVALID")
    return fen


def _parse_alipay_trade_bill_zip(
    source: bytes,
    *,
    expected_bill_date: str,
) -> tuple[dict[str, Any], ...]:
    try:
        bill_day = date.fromisoformat(str(expected_bill_date))
    except (TypeError, ValueError) as exc:
        raise _fail("PAYMENT_PROVIDER_BILL_DATE_INVALID") from exc
    if str(bill_day) != str(expected_bill_date):
        raise _fail("PAYMENT_PROVIDER_BILL_DATE_INVALID")
    if (
        not isinstance(source, bytes)
        or not source
        or len(source) > payment_contract.MAX_RECONCILIATION_SOURCE_BYTES
    ):
        raise _fail("PAYMENT_PROVIDER_BILL_SOURCE_INVALID")
    try:
        archive = zipfile.ZipFile(io.BytesIO(source), mode="r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise _fail("PAYMENT_PROVIDER_BILL_ARCHIVE_INVALID") from exc
    with archive:
        members = archive.infolist()
        if not 1 <= len(members) <= 2:
            raise _fail("PAYMENT_PROVIDER_BILL_ARCHIVE_INVALID")
        total_size = 0
        detail_members: list[zipfile.ZipInfo] = []
        for member in members:
            parts = member.filename.split("/")
            mode = (member.external_attr >> 16) & 0o170000
            total_size += int(member.file_size)
            if (
                member.is_dir()
                or member.flag_bits & 0x1
                or member.filename.startswith("/")
                or "\\" in member.filename
                or any(part in {"", ".", ".."} for part in parts)
                or len(parts) != 1
                or mode not in {0, 0o100000}
                or not member.filename.lower().endswith(".csv")
                or int(member.file_size) <= 0
                or total_size > payment_contract.MAX_RECONCILIATION_SOURCE_BYTES
            ):
                raise _fail("PAYMENT_PROVIDER_BILL_ARCHIVE_INVALID")
            if "业务明细" in member.filename:
                detail_members.append(member)
            elif "业务汇总" not in member.filename:
                raise _fail("PAYMENT_PROVIDER_BILL_ARCHIVE_INVALID")
        if len(detail_members) != 1:
            raise _fail("PAYMENT_PROVIDER_BILL_ARCHIVE_INVALID")
        try:
            if archive.testzip() is not None:
                raise _fail("PAYMENT_PROVIDER_BILL_ARCHIVE_INVALID")
            detail_source = archive.read(detail_members[0])
        except DirectPaymentGatewayError:
            raise
        except (OSError, RuntimeError, zipfile.BadZipFile, zlib.error) as exc:
            raise _fail("PAYMENT_PROVIDER_BILL_ARCHIVE_INVALID") from exc
    text = ""
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = detail_source.decode(encoding)
            break
        except UnicodeError:
            continue
    if not text or "\x00" in text:
        raise _fail("PAYMENT_PROVIDER_BILL_SCHEMA_INVALID")
    try:
        parsed_rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except (csv.Error, UnicodeError) as exc:
        raise _fail("PAYMENT_PROVIDER_BILL_SCHEMA_INVALID") from exc
    header: list[str] | None = None
    header_index = -1
    for index, row in enumerate(parsed_rows):
        normalized = [value.strip().lstrip("\ufeff") for value in row]
        if not normalized or not any(normalized):
            continue
        if normalized[0].startswith("#"):
            continue
        if _ALIPAY_TRADE_BILL_REQUIRED_HEADERS.issubset(normalized):
            if len(normalized) != len(set(normalized)):
                raise _fail("PAYMENT_PROVIDER_BILL_SCHEMA_INVALID")
            header = normalized
            header_index = index
            break
        raise _fail("PAYMENT_PROVIDER_BILL_SCHEMA_INVALID")
    if header is None:
        raise _fail("PAYMENT_PROVIDER_BILL_SCHEMA_INVALID")
    positions = {name: header.index(name) for name in _ALIPAY_TRADE_BILL_REQUIRED_HEADERS}
    canonical: list[dict[str, Any]] = []
    for row in parsed_rows[header_index + 1 :]:
        values = [value.strip() for value in row]
        if not values or not any(values) or values[0].startswith("#"):
            continue
        if len(values) != len(header):
            raise _fail("PAYMENT_PROVIDER_BILL_SCHEMA_INVALID")
        if len(canonical) >= payment_contract.MAX_RECONCILIATION_ROWS:
            raise _fail("PAYMENT_PROVIDER_BILL_ROW_LIMIT")
        business_type = values[positions["业务类型"]]
        try:
            completed_at = datetime.strptime(
                values[positions["完成时间"]],
                "%Y-%m-%d %H:%M:%S",
            )
        except ValueError as exc:
            raise _fail("PAYMENT_PROVIDER_BILL_DATE_INVALID") from exc
        if completed_at.date() != bill_day:
            raise _fail("PAYMENT_PROVIDER_BILL_DATE_MISMATCH")
        amount_fen = _alipay_bill_fen(values[positions["订单金额（元）"]])
        if business_type == "交易":
            reference = _opaque(
                values[positions["商户订单号"]],
                "bill_reference",
            )
            kind = "payment"
        elif business_type == "退款":
            reference = _opaque(
                values[positions["退款批次号/请求号"]],
                "bill_reference",
            )
            kind = "refund"
        else:
            raise _fail("PAYMENT_PROVIDER_BILL_ROW_INVALID")
        canonical.append(
            {
                "kind": kind,
                "reference": reference,
                "amount_fen": amount_fen,
                "status": "succeeded",
            }
        )
    return tuple(canonical)


def _https_url(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    try:
        parsed = urlsplit(normalized)
    except ValueError as exc:
        raise _fail(f"PAYMENT_PROVIDER_{field.upper()}_INVALID") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or len(normalized.encode("utf-8")) > MAX_CHECKOUT_VALUE_BYTES
    ):
        raise _fail(f"PAYMENT_PROVIDER_{field.upper()}_INVALID")
    return normalized


def _direct_callback_url(value: Any, provider_name: str) -> str:
    expected = {
        "wechatpay_direct": WECHATPAY_CALLBACK_URL,
        "alipay_direct": ALIPAY_CALLBACK_URL,
    }.get(provider_name)
    normalized = _https_url(value, "callback_url")
    if expected is None or normalized != expected:
        raise _fail("PAYMENT_PROVIDER_CALLBACK_URL_INVALID")
    return normalized


def _strict_bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise _fail(f"PAYMENT_PROVIDER_{field.upper()}_INVALID")
    return value


def _wechat_verifier_id(value: Any) -> str:
    normalized = str(value or "").strip()
    if _WECHAT_SERIAL_RE.fullmatch(normalized):
        return normalized.upper()
    if _WECHAT_PUBLIC_KEY_ID_RE.fullmatch(normalized):
        return normalized
    raise _fail("PAYMENT_PROVIDER_CERTIFICATE_SERIAL_INVALID")


def decode_pem_b64(value: Any) -> str:
    """Decode one canonical, single-line Base64 PEM without logging it."""
    if not isinstance(value, str) or not value or len(value) > MAX_PEM_B64_BYTES:
        raise _fail("PAYMENT_PROVIDER_KEY_INVALID")
    if any(character.isspace() for character in value):
        raise _fail("PAYMENT_PROVIDER_KEY_INVALID")
    try:
        raw = base64.b64decode(value, validate=True)
        if (
            not raw
            or len(raw) > MAX_PEM_BYTES
            or base64.b64encode(raw).decode("ascii") != value
        ):
            raise ValueError
        return raw.decode("ascii")
    except (UnicodeError, ValueError, binascii.Error) as exc:
        raise _fail("PAYMENT_PROVIDER_KEY_INVALID") from exc


def _rsa_public_key(value: str) -> rsa.RSAPublicKey:
    try:
        key = serialization.load_pem_public_key(str(value or "").encode("ascii"))
    except (TypeError, UnicodeError, ValueError) as exc:
        raise _fail("PAYMENT_PROVIDER_KEY_INVALID") from exc
    if not isinstance(key, rsa.RSAPublicKey) or not 2048 <= key.key_size <= 4096:
        raise _fail("PAYMENT_PROVIDER_KEY_INVALID")
    return key


def _rsa_private_key(value: str) -> rsa.RSAPrivateKey:
    try:
        key = serialization.load_pem_private_key(
            str(value or "").encode("ascii"),
            password=None,
        )
    except (TypeError, UnicodeError, ValueError) as exc:
        raise _fail("PAYMENT_PROVIDER_KEY_INVALID") from exc
    if not isinstance(key, rsa.RSAPrivateKey) or not 2048 <= key.key_size <= 4096:
        raise _fail("PAYMENT_PROVIDER_KEY_INVALID")
    return key


def _unique_json(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _fail("PAYMENT_CALLBACK_DUPLICATE_FIELD")
        result[key] = value
    return result


def _json_object(raw: bytes, code: str) -> dict[str, Any]:
    if not raw or len(raw) > payment_contract.MAX_CALLBACK_DATA_BYTES:
        raise _fail(code)
    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_json)
    except DirectPaymentGatewayError:
        raise
    except (UnicodeError, ValueError) as exc:
        raise _fail(code) from exc
    if not isinstance(parsed, dict):
        raise _fail(code)
    return parsed


def _verified_response(
    response: VerifiedDirectResponse,
    provider_name: str,
) -> tuple[dict[str, Any], bytes, str, int]:
    if (
        not isinstance(response, VerifiedDirectResponse)
        or response.provider_name != provider_name
        or response.response_verified is not True
        or not isinstance(response.body, Mapping)
        or not isinstance(response.raw_body, (bytes, bytearray))
        or not isinstance(response.signature, str)
        or not response.signature
        or len(response.signature) > payment_contract.MAX_SIGNATURE_BYTES * 2
        or isinstance(response.verified_at, bool)
        or not isinstance(response.verified_at, int)
        or not 946684800 <= response.verified_at <= 4102444800
    ):
        raise _fail("PAYMENT_PROVIDER_RESPONSE_UNVERIFIED")
    raw_body = bytes(response.raw_body)
    if not raw_body or len(raw_body) > MAX_DIRECT_RESPONSE_BYTES:
        raise _fail("PAYMENT_PROVIDER_RESPONSE_INVALID")
    try:
        response.signature.encode("ascii")
        encoded = json.dumps(
            response.body,
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, UnicodeError, ValueError) as exc:
        raise _fail("PAYMENT_PROVIDER_RESPONSE_INVALID") from exc
    if not encoded or len(encoded) > MAX_DIRECT_RESPONSE_BYTES:
        raise _fail("PAYMENT_PROVIDER_RESPONSE_INVALID")
    body = dict(response.body)
    if _json_object(raw_body, "PAYMENT_PROVIDER_RESPONSE_INVALID") != body:
        raise _fail("PAYMENT_PROVIDER_RESPONSE_MISMATCH")
    return body, raw_body, response.signature, response.verified_at


def _verified_body(
    response: VerifiedDirectResponse,
    provider_name: str,
) -> dict[str, Any]:
    return _verified_response(response, provider_name)[0]


def _validate_order(
    order: dict[str, Any],
    *,
    provider_name: str,
    prod_mode: bool,
) -> dict[str, Any]:
    expected = {
        "merchant_order_no",
        "amount_fen",
        "currency",
        "product_kind",
        "product_id",
        "provider_mode",
        "provider_name",
        "device_ip",
    }
    if not isinstance(order, dict) or set(order) != expected:
        raise _fail("PAYMENT_PROVIDER_ORDER_INVALID")
    if order.get("provider_name") != provider_name:
        raise _fail("PAYMENT_PROVIDER_IDENTITY_INVALID")
    if order.get("provider_mode") != ("live" if prod_mode else "mock"):
        raise _fail("PAYMENT_PROVIDER_MODE_INVALID")
    if order.get("currency") != "CNY":
        raise _fail("PAYMENT_PROVIDER_CURRENCY_INVALID")
    if order.get("product_kind") not in {"subscription", "credit_package"}:
        raise _fail("PAYMENT_PROVIDER_PRODUCT_INVALID")
    product_id = str(order.get("product_id") or "")
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,31}", product_id):
        raise _fail("PAYMENT_PROVIDER_PRODUCT_INVALID")
    if not isinstance(order.get("device_ip"), str):
        raise _fail("PAYMENT_PROVIDER_ORDER_INVALID")
    return {
        "merchant_order_no": _opaque(order.get("merchant_order_no"), "order_no"),
        "amount_fen": _positive_fen(order.get("amount_fen")),
        "product_id": product_id,
        "product_kind": order["product_kind"],
    }


def _validate_refund(
    refund: dict[str, Any],
    *,
    provider_name: str,
    prod_mode: bool,
) -> dict[str, Any]:
    expected = {
        "merchant_refund_no",
        "merchant_order_no",
        "provider_payment_id",
        "amount_fen",
        "currency",
        "provider_mode",
        "provider_name",
        "reason_code",
    }
    if not isinstance(refund, dict) or set(refund) != expected:
        raise _fail("PAYMENT_PROVIDER_REFUND_INVALID")
    if refund.get("provider_name") != provider_name:
        raise _fail("PAYMENT_PROVIDER_IDENTITY_INVALID")
    if refund.get("provider_mode") != ("live" if prod_mode else "mock"):
        raise _fail("PAYMENT_PROVIDER_MODE_INVALID")
    if refund.get("currency") != "CNY":
        raise _fail("PAYMENT_PROVIDER_CURRENCY_INVALID")
    reasons = {
        "customer_request": "customer request",
        "service_not_delivered": "service not delivered",
        "duplicate_payment": "duplicate payment",
        "fraud_review": "fraud review",
    }
    if refund.get("reason_code") not in reasons:
        raise _fail("PAYMENT_PROVIDER_REFUND_REASON_INVALID")
    return {
        "merchant_refund_no": _opaque(refund.get("merchant_refund_no"), "refund_no"),
        "merchant_order_no": _opaque(refund.get("merchant_order_no"), "order_no"),
        "provider_payment_id": _opaque(refund.get("provider_payment_id"), "payment_id"),
        "amount_fen": _positive_fen(refund.get("amount_fen")),
        "reason": reasons[str(refund["reason_code"])],
    }


def _bill(
    transport: DirectPaymentTransport,
    *,
    provider_name: str,
    bill_date: str,
) -> tuple[bytes, tuple[dict[str, Any], ...]]:
    try:
        parsed = date.fromisoformat(str(bill_date))
    except (TypeError, ValueError) as exc:
        raise _fail("PAYMENT_PROVIDER_BILL_DATE_INVALID") from exc
    if str(parsed) != str(bill_date):
        raise _fail("PAYMENT_PROVIDER_BILL_DATE_INVALID")
    result = transport.reconciliation(provider_name, str(parsed))
    expected_authentication_mode = {
        "wechatpay_direct": "provider_sha1",
        "alipay_direct": "signed_locator_tls_exact_url",
    }.get(provider_name)
    if (
        not isinstance(result, VerifiedDirectBill)
        or result.provider_name != provider_name
        or result.bill_date != str(parsed)
        or result.authentication_mode != expected_authentication_mode
    ):
        raise _fail("PAYMENT_PROVIDER_BILL_UNVERIFIED")
    if not isinstance(result.source_bytes, (bytes, bytearray)):
        raise _fail("PAYMENT_PROVIDER_BILL_SOURCE_INVALID")
    source = bytes(result.source_bytes)
    if not source or len(source) > payment_contract.MAX_RECONCILIATION_SOURCE_BYTES:
        raise _fail("PAYMENT_PROVIDER_BILL_SOURCE_INVALID")
    rows_buffer: list[dict[str, Any]] = []
    try:
        for raw_row in result.rows:
            if len(rows_buffer) >= payment_contract.MAX_RECONCILIATION_ROWS:
                raise _fail("PAYMENT_PROVIDER_BILL_ROW_LIMIT")
            if not isinstance(raw_row, Mapping):
                raise _fail("PAYMENT_PROVIDER_BILL_ROW_INVALID")
            rows_buffer.append(dict(raw_row))
    except DirectPaymentGatewayError:
        raise
    except (TypeError, ValueError) as exc:
        raise _fail("PAYMENT_PROVIDER_BILL_ROW_INVALID") from exc
    rows = tuple(rows_buffer)
    for row in rows:
        if set(row) != {"kind", "reference", "amount_fen", "status"}:
            raise _fail("PAYMENT_PROVIDER_BILL_ROW_INVALID")
        if row["kind"] not in {"payment", "refund"}:
            raise _fail("PAYMENT_PROVIDER_BILL_ROW_INVALID")
        _opaque(row["reference"], "bill_reference")
        _positive_fen(row["amount_fen"], "bill_amount")
        if row["status"] not in {"succeeded", "failed", "pending", "closed"}:
            raise _fail("PAYMENT_PROVIDER_BILL_ROW_INVALID")
    return source, rows


def _process_verified_payment_query(
    result: payment_contract.ProviderPaymentResult,
    raw_body: bytes,
    signature: str,
    verified_at: int,
    *,
    expected_app_id: str,
    expected_provider_name: str,
    expected_prod_mode: bool,
    now: datetime | None,
) -> dict[str, Any]:
    provider_created_at = result.provider_created_at
    if result.status == "succeeded":
        if (
            isinstance(provider_created_at, bool)
            or not isinstance(provider_created_at, int)
            or not 946684800 <= provider_created_at <= 4102444800
        ):
            raise _fail("PAYMENT_INVALID_EVENT_CLOCK")
    elif provider_created_at is not None:
        raise _fail("PAYMENT_INVALID_EVENT_CLOCK")
    if result.status == "pending":
        payment_contract.mark_payment_query_submission(result, now=now)
    if result.status == "pending":
        return {"ok": True, "pending": True}
    if result.status not in {"succeeded", "failed"}:
        raise _fail("PAYMENT_PROVIDER_STATUS_INVALID")
    payment_id = (
        _opaque(result.provider_payment_id, "payment_id")
        if result.provider_payment_id
        else None
    )
    if result.status == "succeeded" and payment_id is None:
        raise _fail("PAYMENT_PROVIDER_PAYMENT_ID_INVALID")
    receipt_identity = hashlib.sha256(
        expected_provider_name.encode("ascii")
        + b"\x00"
        + raw_body
        + b"\x00"
        + signature.encode("ascii")
        + b"\x00"
        + str(verified_at).encode("ascii")
    ).hexdigest()
    event = payment_contract.CallbackEvent(
        provider_event_id=f"payment_query_{receipt_identity}",
        event_type=(
            "payment.succeeded" if result.status == "succeeded" else "payment.failed"
        ),
        created_time=(
            int(provider_created_at)
            if result.status == "succeeded"
            else verified_at
        ),
        prod_mode=expected_prod_mode,
        app_id=expected_app_id,
        data={
            "order_no": result.merchant_order_no,
            "payment_id": payment_id,
            "pay_amt": _fen_text(result.amount_fen),
        },
        provider_name=expected_provider_name,
    )
    return payment_contract.process_authenticated_callback(
        event,
        raw_body,
        signature,
        expected_app_id=expected_app_id,
        expected_provider_name=expected_provider_name,
        expected_prod_mode=expected_prod_mode,
        now=now,
    )


def _process_verified_refund_query(
    result: payment_contract.ProviderRefundResult,
    raw_body: bytes,
    signature: str,
    verified_at: int,
    *,
    expected_app_id: str,
    expected_provider_name: str,
    expected_prod_mode: bool,
    now: datetime | None,
) -> dict[str, Any]:
    if result.provider_submitted_at is not None and result.status == "pending":
        payment_contract.mark_refund_query_submission(result, now=now)
    if result.status == "pending":
        return {"ok": True, "pending": True}
    if result.status not in {"succeeded", "failed"}:
        raise _fail("PAYMENT_PROVIDER_STATUS_INVALID")
    receipt_identity = hashlib.sha256(
        expected_provider_name.encode("ascii")
        + b"\x00"
        + raw_body
        + b"\x00"
        + signature.encode("ascii")
        + b"\x00"
        + str(verified_at).encode("ascii")
    ).hexdigest()
    data = {
        "refund_order_no": result.merchant_refund_no,
        "payment_id": result.provider_payment_id,
        "refund_amt": _fen_text(result.amount_fen),
    }
    if result.provider_submitted_at is not None:
        data["provider_submitted_at"] = result.provider_submitted_at
    if result.provider_refund_id:
        data["refund_id"] = result.provider_refund_id
    provider_created_at = result.provider_created_at
    if result.status == "succeeded":
        if (
            isinstance(provider_created_at, bool)
            or not isinstance(provider_created_at, int)
            or not 946684800 <= provider_created_at <= 4102444800
        ):
            raise _fail("PAYMENT_INVALID_EVENT_CLOCK")
    elif provider_created_at is not None:
        raise _fail("PAYMENT_INVALID_EVENT_CLOCK")
    event = payment_contract.CallbackEvent(
        provider_event_id=f"refund_query_{receipt_identity}",
        event_type=(
            "refund.succeeded" if result.status == "succeeded" else "refund.failed"
        ),
        created_time=(
            int(provider_created_at)
            if result.status == "succeeded"
            else verified_at
        ),
        prod_mode=expected_prod_mode,
        app_id=expected_app_id,
        data=data,
        provider_name=expected_provider_name,
    )
    return payment_contract.process_authenticated_callback(
        event,
        raw_body,
        signature,
        expected_app_id=expected_app_id,
        expected_provider_name=expected_provider_name,
        expected_prod_mode=expected_prod_mode,
        now=now,
    )


def _monotonic_value(clock: Callable[[], float]) -> float:
    try:
        value = clock()
    except Exception as exc:
        raise _fail("PAYMENT_PROVIDER_CLOCK_INVALID") from exc
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _fail("PAYMENT_PROVIDER_CLOCK_INVALID")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise _fail("PAYMENT_PROVIDER_CLOCK_INVALID")
    return normalized


def _http_response_bytes(
    response: httpx.Response,
    *,
    deadline: float,
    monotonic_clock: Callable[[], float],
    max_bytes: int = MAX_DIRECT_RESPONSE_BYTES,
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        if _monotonic_value(monotonic_clock) > deadline:
            raise _fail("PAYMENT_PROVIDER_TIMEOUT")
        total += len(chunk)
        if total > max_bytes:
            raise _fail("PAYMENT_PROVIDER_RESPONSE_TOO_LARGE")
        chunks.append(chunk)
    if _monotonic_value(monotonic_clock) > deadline:
        raise _fail("PAYMENT_PROVIDER_TIMEOUT")
    raw = b"".join(chunks)
    if not raw:
        raise _fail("PAYMENT_PROVIDER_RESPONSE_INVALID")
    return raw


def _http_json_content_type(response: httpx.Response) -> bool:
    content_type = response.headers.get("content-type", "").split(";", 1)[0]
    return content_type.strip().lower() == "application/json"


def _http_alipay_json_content_type(response: httpx.Response) -> bool:
    content_type = response.headers.get("content-type", "").split(";", 1)[0]
    return content_type.strip().lower() in {"application/json", "text/html"}


def _clock_epoch(clock: Callable[[], datetime]) -> tuple[datetime, int]:
    current = clock()
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise _fail("PAYMENT_PROVIDER_CLOCK_INVALID")
    normalized = current.astimezone(timezone.utc)
    epoch = int(normalized.timestamp())
    if not 946684800 <= epoch <= 4102444800:
        raise _fail("PAYMENT_PROVIDER_CLOCK_INVALID")
    return normalized, epoch


class HttpxWeChatPayTransport:
    """Single-attempt API v3 transport with request signing and response verify."""

    def __init__(
        self,
        *,
        app_id: str,
        merchant_id: str,
        merchant_certificate_serial: str,
        merchant_private_key_pem: str,
        platform_verifier_id: str,
        platform_public_key_pem: str,
        client: httpx.Client | None = None,
        clock: Callable[[], datetime] | None = None,
        nonce_factory: Callable[[], str] | None = None,
        monotonic_clock: Callable[[], float] | None = None,
    ):
        app = _app_id(app_id)
        merchant = str(merchant_id or "").strip()
        merchant_serial = str(merchant_certificate_serial or "").strip()
        if not _WECHAT_MERCHANT_RE.fullmatch(merchant):
            raise _fail("PAYMENT_PROVIDER_MERCHANT_ID_INVALID")
        if not _WECHAT_SERIAL_RE.fullmatch(merchant_serial):
            raise _fail("PAYMENT_PROVIDER_CERTIFICATE_SERIAL_INVALID")
        self._app_id = app
        self._merchant_id = merchant
        self._merchant_serial = merchant_serial.upper()
        self._merchant_private_key = _rsa_private_key(merchant_private_key_pem)
        self._platform_verifier_id = _wechat_verifier_id(platform_verifier_id)
        self._platform_public_key = _rsa_public_key(platform_public_key_pem)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._nonce_factory = nonce_factory or (lambda: secrets.token_hex(16))
        self._monotonic_clock = monotonic_clock or time.monotonic
        self._owned = client is None
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(connect=3.0, read=10.0, write=5.0, pool=3.0),
            limits=httpx.Limits(
                max_connections=4,
                max_keepalive_connections=2,
                keepalive_expiry=15.0,
            ),
            follow_redirects=False,
            trust_env=False,
            verify=True,
        )

    def __repr__(self) -> str:
        return "HttpxWeChatPayTransport(configuration_redacted=True)"

    def _signed_headers(
        self,
        method: str,
        path_query: str,
        body: bytes,
        *,
        include_platform_verifier: bool,
    ) -> tuple[dict[str, str], int]:
        _current, timestamp = _clock_epoch(self._clock)
        nonce = str(self._nonce_factory() or "")
        if not _NONCE_RE.fullmatch(nonce):
            raise _fail("PAYMENT_PROVIDER_NONCE_INVALID")
        try:
            prefix = (
                f"{method}\n{path_query}\n{timestamp}\n{nonce}\n"
            ).encode("ascii")
        except UnicodeError as exc:
            raise _fail("PAYMENT_PROVIDER_REQUEST_INVALID") from exc
        message = prefix + body + b"\n"
        signature = base64.b64encode(
            self._merchant_private_key.sign(
                message,
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        ).decode("ascii")
        headers = {
            "accept": "application/json",
            "authorization": (
                "WECHATPAY2-SHA256-RSA2048 "
                f'mchid="{self._merchant_id}",nonce_str="{nonce}",'
                f'timestamp="{timestamp}",serial_no="{self._merchant_serial}",'
                f'signature="{signature}"'
            ),
            "user-agent": "NoteAI-WeChatPay/1",
        }
        if include_platform_verifier:
            # This selects the configured platform certificate/public-key
            # identity for the provider's signed response. It is distinct
            # from the merchant certificate serial in Authorization.
            headers["wechatpay-serial"] = self._platform_verifier_id
        if method == "POST":
            headers["content-type"] = "application/json"
        return headers, timestamp

    def _wire_request(
        self,
        operation: str,
        payload: Mapping[str, Any],
    ) -> tuple[str, str, bytes]:
        item = dict(payload)
        if operation == "native.create":
            return "POST", "/v3/pay/transactions/native", json.dumps(
                item,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        if operation == "refund.create":
            return "POST", "/v3/refund/domestic/refunds", json.dumps(
                item,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        if operation == "native.query_by_out_trade_no":
            if set(item) != {"out_trade_no", "mchid"}:
                raise _fail("PAYMENT_PROVIDER_REQUEST_INVALID")
            order_no = _opaque(item["out_trade_no"], "order_no")
            if str(item["mchid"] or "") != self._merchant_id:
                raise _fail("PAYMENT_PROVIDER_REQUEST_INVALID")
            query = urlencode({"mchid": self._merchant_id}, quote_via=quote)
            return (
                "GET",
                f"/v3/pay/transactions/out-trade-no/{quote(order_no, safe='')}?{query}",
                b"",
            )
        if operation == "refund.query_by_out_refund_no":
            if set(item) != {"out_refund_no"}:
                raise _fail("PAYMENT_PROVIDER_REQUEST_INVALID")
            refund_no = _opaque(item["out_refund_no"], "refund_no")
            return (
                "GET",
                f"/v3/refund/domestic/refunds/{quote(refund_no, safe='')}",
                b"",
            )
        if operation == "tradebill.locate":
            if set(item) != {"bill_date", "bill_type"}:
                raise _fail("PAYMENT_PROVIDER_REQUEST_INVALID")
            try:
                parsed_day = date.fromisoformat(str(item["bill_date"]))
            except (TypeError, ValueError) as exc:
                raise _fail("PAYMENT_PROVIDER_BILL_DATE_INVALID") from exc
            if (
                str(parsed_day) != str(item["bill_date"])
                or item["bill_type"] != "ALL"
            ):
                raise _fail("PAYMENT_PROVIDER_REQUEST_INVALID")
            query = urlencode(
                (("bill_date", str(parsed_day)), ("bill_type", "ALL")),
                quote_via=quote,
            )
            return "GET", f"/v3/bill/tradebill?{query}", b""
        raise _fail("PAYMENT_PROVIDER_OPERATION_INVALID")

    def request(
        self,
        provider_name: str,
        operation: str,
        payload: Mapping[str, Any],
        *,
        _deadline: float | None = None,
    ) -> VerifiedDirectResponse:
        if provider_name != "wechatpay_direct" or not isinstance(payload, Mapping):
            raise _fail("PAYMENT_PROVIDER_IDENTITY_INVALID")
        started = _monotonic_value(self._monotonic_clock)
        if _deadline is None:
            deadline = started + MAX_DIRECT_REQUEST_SECONDS
        elif (
            isinstance(_deadline, bool)
            or not isinstance(_deadline, (int, float))
            or not math.isfinite(float(_deadline))
            or float(_deadline) < started
            or float(_deadline) > started + MAX_DIRECT_REQUEST_SECONDS
        ):
            raise _fail("PAYMENT_PROVIDER_TIMEOUT")
        else:
            deadline = float(_deadline)
        try:
            method, path_query, body = self._wire_request(operation, payload)
        except DirectPaymentGatewayError:
            raise
        except (TypeError, UnicodeError, ValueError) as exc:
            raise _fail("PAYMENT_PROVIDER_REQUEST_INVALID") from exc
        headers, timestamp = self._signed_headers(
            method,
            path_query,
            body,
            include_platform_verifier=True,
        )
        url = WECHATPAY_API_ORIGIN + path_query
        try:
            with self._client.stream(
                method,
                url,
                headers=headers,
                content=body or None,
            ) as response:
                raw = _http_response_bytes(
                    response,
                    deadline=deadline,
                    monotonic_clock=self._monotonic_clock,
                )
                final_url = str(response.url)
                status_code = int(response.status_code)
                response_headers: dict[str, str] = {}
                for key, value in response.headers.multi_items():
                    normalized = str(key).lower()
                    if normalized.startswith("wechatpay-"):
                        if normalized in response_headers:
                            raise _fail("PAYMENT_PROVIDER_RESPONSE_HEADER_INVALID")
                        response_headers[normalized] = str(value)
                media_type_ok = _http_json_content_type(response)
        except DirectPaymentGatewayError:
            raise
        except httpx.HTTPError as exc:
            raise _fail("PAYMENT_PROVIDER_TRANSPORT_ERROR") from exc
        if final_url != url or not media_type_ok:
            raise _fail("PAYMENT_PROVIDER_RESPONSE_INVALID")
        response_timestamp = response_headers.get("wechatpay-timestamp", "")
        response_nonce = response_headers.get("wechatpay-nonce", "")
        response_signature = response_headers.get("wechatpay-signature", "")
        response_serial = response_headers.get("wechatpay-serial", "")
        signature_type = response_headers.get("wechatpay-signature-type")
        try:
            response_epoch = int(response_timestamp)
            normalized_serial = _wechat_verifier_id(response_serial)
            decoded_signature = base64.b64decode(
                response_signature,
                validate=True,
            )
        except (DirectPaymentGatewayError, TypeError, ValueError, binascii.Error) as exc:
            raise _fail("PAYMENT_PROVIDER_RESPONSE_HEADER_INVALID") from exc
        if (
            normalized_serial != self._platform_verifier_id
            or signature_type not in {None, "WECHATPAY2-SHA256-RSA2048"}
            or not _NONCE_RE.fullmatch(response_nonce)
            or abs(timestamp - response_epoch) > MAX_CALLBACK_AGE_SECONDS
            or not response_signature
            or len(response_signature) > payment_contract.MAX_SIGNATURE_BYTES * 2
        ):
            raise _fail("PAYMENT_PROVIDER_RESPONSE_HEADER_INVALID")
        try:
            self._platform_public_key.verify(
                decoded_signature,
                f"{response_timestamp}\n{response_nonce}\n".encode("ascii")
                + raw
                + b"\n",
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except InvalidSignature as exc:
            raise _fail("PAYMENT_PROVIDER_RESPONSE_UNVERIFIED") from exc
        parsed = _json_object(raw, "PAYMENT_PROVIDER_RESPONSE_INVALID")
        if not 200 <= status_code < 300:
            raise _fail("PAYMENT_PROVIDER_REQUEST_REJECTED")
        return VerifiedDirectResponse(
            provider_name="wechatpay_direct",
            body=parsed,
            raw_body=raw,
            signature=response_signature,
            verified_at=response_epoch,
            response_verified=True,
        )

    def _download_trade_bill(self, download_url: str, *, deadline: float) -> bytes:
        try:
            parsed = urlsplit(download_url)
            port = parsed.port
        except ValueError as exc:
            raise _fail("PAYMENT_PROVIDER_BILL_URL_INVALID") from exc
        if (
            parsed.scheme != "https"
            or parsed.hostname not in _WECHAT_TRADE_BILL_HOSTS
            or parsed.netloc != parsed.hostname
            or port is not None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or parsed.path != "/v3/billdownload/file"
            or not parsed.query
            or len(download_url.encode("utf-8")) > 2048
        ):
            raise _fail("PAYMENT_PROVIDER_BILL_URL_INVALID")
        try:
            query = parse_qsl(
                parsed.query,
                keep_blank_values=True,
                strict_parsing=True,
            )
            canonical_url = str(httpx.URL(download_url))
            path_query = parsed.path + "?" + parsed.query
            path_query.encode("ascii")
        except (UnicodeError, ValueError) as exc:
            raise _fail("PAYMENT_PROVIDER_BILL_URL_INVALID") from exc
        if (
            canonical_url != download_url
            or len(query) != 1
            or query[0][0] != "token"
            or not query[0][1]
        ):
            raise _fail("PAYMENT_PROVIDER_BILL_URL_INVALID")
        if _monotonic_value(self._monotonic_clock) > deadline:
            raise _fail("PAYMENT_PROVIDER_TIMEOUT")
        headers, _timestamp = self._signed_headers(
            "GET",
            path_query,
            b"",
            include_platform_verifier=False,
        )
        headers["accept"] = "application/octet-stream"
        headers["accept-encoding"] = "identity"
        try:
            with self._client.stream(
                "GET",
                download_url,
                headers=headers,
            ) as response:
                content_encoding = response.headers.get(
                    "content-encoding",
                    "",
                ).strip().lower()
                if content_encoding not in {"", "identity"}:
                    raise _fail("PAYMENT_PROVIDER_BILL_DOWNLOAD_REJECTED")
                raw = _http_response_bytes(
                    response,
                    deadline=deadline,
                    monotonic_clock=self._monotonic_clock,
                    max_bytes=payment_contract.MAX_RECONCILIATION_SOURCE_BYTES,
                )
                final_url = str(response.url)
                status_code = int(response.status_code)
        except DirectPaymentGatewayError:
            raise
        except httpx.HTTPError as exc:
            raise _fail("PAYMENT_PROVIDER_TRANSPORT_ERROR") from exc
        if (
            final_url != download_url
            or status_code != 200
        ):
            raise _fail("PAYMENT_PROVIDER_BILL_DOWNLOAD_REJECTED")
        return raw

    def reconciliation(self, provider_name: str, bill_date: str) -> VerifiedDirectBill:
        if provider_name != "wechatpay_direct":
            raise _fail("PAYMENT_PROVIDER_IDENTITY_INVALID")
        try:
            parsed_day = date.fromisoformat(str(bill_date))
        except (TypeError, ValueError) as exc:
            raise _fail("PAYMENT_PROVIDER_BILL_DATE_INVALID") from exc
        if str(parsed_day) != str(bill_date):
            raise _fail("PAYMENT_PROVIDER_BILL_DATE_INVALID")
        deadline = (
            _monotonic_value(self._monotonic_clock)
            + MAX_DIRECT_REQUEST_SECONDS
        )
        locator = self.request(
            "wechatpay_direct",
            "tradebill.locate",
            {"bill_date": str(parsed_day), "bill_type": "ALL"},
            _deadline=deadline,
        )
        if set(locator.body) != {"hash_type", "hash_value", "download_url"}:
            raise _fail("PAYMENT_PROVIDER_BILL_LOCATOR_INVALID")
        hash_value = locator.body.get("hash_value")
        download_url = locator.body.get("download_url")
        if (
            locator.body.get("hash_type") != "SHA1"
            or not isinstance(hash_value, str)
            or not _SHA1_RE.fullmatch(hash_value)
            or not isinstance(download_url, str)
        ):
            raise _fail("PAYMENT_PROVIDER_BILL_LOCATOR_INVALID")
        source = self._download_trade_bill(download_url, deadline=deadline)
        actual_sha1 = hashlib.sha1(source).hexdigest()
        if not secrets.compare_digest(actual_sha1, hash_value.lower()):
            raise _fail("PAYMENT_PROVIDER_BILL_DIGEST_MISMATCH")
        rows = _parse_wechat_trade_bill(
            source,
            expected_bill_date=str(parsed_day),
            expected_app_id=self._app_id,
            expected_merchant_id=self._merchant_id,
        )
        return VerifiedDirectBill(
            provider_name="wechatpay_direct",
            bill_date=str(parsed_day),
            source_bytes=source,
            rows=rows,
            authentication_mode="provider_sha1",
        )

    def close(self) -> None:
        if self._owned:
            self._client.close()


def _top_level_json_value(raw: bytes, key_name: str) -> bytes:
    try:
        text = raw.decode("utf-8")
        decoder = json.JSONDecoder(object_pairs_hook=_unique_json)
        index = 0
        length = len(text)

        def skip_space(position: int) -> int:
            while position < length and text[position].isspace():
                position += 1
            return position

        index = skip_space(index)
        if index >= length or text[index] != "{":
            raise ValueError
        index += 1
        found: bytes | None = None
        while True:
            index = skip_space(index)
            if index < length and text[index] == "}":
                index += 1
                break
            parsed_key, index = decoder.raw_decode(text, index)
            if not isinstance(parsed_key, str):
                raise ValueError
            index = skip_space(index)
            if index >= length or text[index] != ":":
                raise ValueError
            value_start = skip_space(index + 1)
            _parsed_value, value_end = decoder.raw_decode(text, value_start)
            if parsed_key == key_name:
                if found is not None:
                    raise ValueError
                found = text[value_start:value_end].encode("utf-8")
            index = skip_space(value_end)
            if index < length and text[index] == ",":
                index += 1
                continue
            if index < length and text[index] == "}":
                index += 1
                break
            raise ValueError
        if skip_space(index) != length or found is None:
            raise ValueError
        return found
    except (DirectPaymentGatewayError, TypeError, UnicodeError, ValueError) as exc:
        raise _fail("PAYMENT_PROVIDER_RESPONSE_INVALID") from exc


class HttpxAlipayTransport:
    """Single-attempt RSA2 gateway transport with exact response-node verify."""

    _METHODS = {
        "trade.precreate": "alipay.trade.precreate",
        "trade.query": "alipay.trade.query",
        "trade.refund": "alipay.trade.refund",
        "trade.fastpay.refund.query": "alipay.trade.fastpay.refund.query",
        "bill.downloadurl.query": (
            "alipay.data.dataservice.bill.downloadurl.query"
        ),
    }

    def __init__(
        self,
        *,
        app_id: str,
        merchant_private_key_pem: str,
        alipay_public_key_pem: str,
        client: httpx.Client | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], float] | None = None,
    ):
        self._app_id = _app_id(app_id)
        self._merchant_private_key = _rsa_private_key(merchant_private_key_pem)
        self._alipay_public_key = _rsa_public_key(alipay_public_key_pem)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._monotonic_clock = monotonic_clock or time.monotonic
        self._owned = client is None
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(connect=3.0, read=10.0, write=5.0, pool=3.0),
            limits=httpx.Limits(
                max_connections=4,
                max_keepalive_connections=2,
                keepalive_expiry=15.0,
            ),
            follow_redirects=False,
            trust_env=False,
            verify=True,
        )

    def __repr__(self) -> str:
        return "HttpxAlipayTransport(configuration_redacted=True)"

    def request(
        self,
        provider_name: str,
        operation: str,
        payload: Mapping[str, Any],
        *,
        _deadline: float | None = None,
    ) -> VerifiedDirectResponse:
        if provider_name != "alipay_direct" or not isinstance(payload, Mapping):
            raise _fail("PAYMENT_PROVIDER_IDENTITY_INVALID")
        method_name = self._METHODS.get(operation)
        if method_name is None:
            raise _fail("PAYMENT_PROVIDER_OPERATION_INVALID")
        biz_payload = dict(payload)
        notify_url = ""
        if operation == "trade.precreate":
            notify_url = _https_url(
                biz_payload.pop("notify_url", ""),
                "callback_url",
            )
        started = _monotonic_value(self._monotonic_clock)
        if _deadline is None:
            deadline = started + MAX_DIRECT_REQUEST_SECONDS
        elif (
            isinstance(_deadline, bool)
            or not isinstance(_deadline, (int, float))
            or not math.isfinite(float(_deadline))
            or float(_deadline) < started
            or float(_deadline) > started + MAX_DIRECT_REQUEST_SECONDS
        ):
            raise _fail("PAYMENT_PROVIDER_TIMEOUT")
        else:
            deadline = float(_deadline)
        current, verified_at = _clock_epoch(self._clock)
        try:
            biz_content = json.dumps(
                biz_payload,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError) as exc:
            raise _fail("PAYMENT_PROVIDER_REQUEST_INVALID") from exc
        params = {
            "app_id": self._app_id,
            "biz_content": biz_content,
            "charset": "utf-8",
            "format": "JSON",
            "method": method_name,
            "sign_type": "RSA2",
            "timestamp": current.astimezone(ZoneInfo("Asia/Shanghai")).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "version": "1.0",
        }
        if notify_url:
            params["notify_url"] = notify_url
        sign_source = "&".join(
            f"{key}={params[key]}" for key in sorted(params) if params[key] != ""
        )
        signature = base64.b64encode(
            self._merchant_private_key.sign(
                sign_source.encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        ).decode("ascii")
        form = urlencode({**params, "sign": signature}).encode("ascii")
        try:
            with self._client.stream(
                "POST",
                ALIPAY_GATEWAY_URL,
                headers={
                    "accept": "application/json",
                    "content-type": "application/x-www-form-urlencoded",
                    "user-agent": "NoteAI-Alipay/1",
                },
                content=form,
            ) as response:
                raw = _http_response_bytes(
                    response,
                    deadline=deadline,
                    monotonic_clock=self._monotonic_clock,
                )
                final_url = str(response.url)
                status_code = int(response.status_code)
                media_type_ok = _http_alipay_json_content_type(response)
        except DirectPaymentGatewayError:
            raise
        except httpx.HTTPError as exc:
            raise _fail("PAYMENT_PROVIDER_TRANSPORT_ERROR") from exc
        if (
            final_url != ALIPAY_GATEWAY_URL
            or status_code != 200
            or not media_type_ok
        ):
            raise _fail("PAYMENT_PROVIDER_RESPONSE_INVALID")
        outer = _json_object(raw, "PAYMENT_PROVIDER_RESPONSE_INVALID")
        response_key = method_name.replace(".", "_") + "_response"
        if response_key not in outer:
            response_key = "error_response" if "error_response" in outer else ""
        response_signature = outer.get("sign")
        if (
            not response_key
            or not isinstance(response_signature, str)
            or not response_signature
            or len(response_signature) > payment_contract.MAX_SIGNATURE_BYTES * 2
        ):
            raise _fail("PAYMENT_PROVIDER_RESPONSE_UNVERIFIED")
        signed_node = _top_level_json_value(raw, response_key)
        try:
            decoded_signature = base64.b64decode(response_signature, validate=True)
            self._alipay_public_key.verify(
                decoded_signature,
                signed_node,
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except (InvalidSignature, ValueError, binascii.Error) as exc:
            raise _fail("PAYMENT_PROVIDER_RESPONSE_UNVERIFIED") from exc
        body = _json_object(signed_node, "PAYMENT_PROVIDER_RESPONSE_INVALID")
        if response_key == "error_response" or str(body.get("code") or "") != "10000":
            raise _fail("PAYMENT_PROVIDER_REQUEST_REJECTED")
        return VerifiedDirectResponse(
            provider_name="alipay_direct",
            body=body,
            raw_body=signed_node,
            signature=response_signature,
            verified_at=verified_at,
            response_verified=True,
        )

    def _download_trade_bill(self, download_url: str, *, deadline: float) -> bytes:
        try:
            parsed = urlsplit(download_url)
            port = parsed.port
        except ValueError as exc:
            raise _fail("PAYMENT_PROVIDER_BILL_URL_INVALID") from exc
        hostname = str(parsed.hostname or "").lower()
        if (
            parsed.scheme != "https"
            or hostname not in _ALIPAY_TRADE_BILL_HOSTS
            or parsed.netloc.lower() != hostname
            or port is not None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or not parsed.path.startswith("/")
            or ".." in parsed.path.split("/")
            or not parsed.query
            or len(download_url.encode("utf-8")) > 4096
        ):
            raise _fail("PAYMENT_PROVIDER_BILL_URL_INVALID")
        try:
            canonical_url = str(httpx.URL(download_url))
        except (UnicodeError, ValueError) as exc:
            raise _fail("PAYMENT_PROVIDER_BILL_URL_INVALID") from exc
        if canonical_url != download_url:
            raise _fail("PAYMENT_PROVIDER_BILL_URL_INVALID")
        if _monotonic_value(self._monotonic_clock) > deadline:
            raise _fail("PAYMENT_PROVIDER_TIMEOUT")
        try:
            with self._client.stream(
                "GET",
                download_url,
                headers={
                    "accept": "application/zip,application/octet-stream",
                    "accept-encoding": "identity",
                    "user-agent": "NoteAI-Alipay/1",
                },
            ) as response:
                content_encoding = response.headers.get(
                    "content-encoding",
                    "",
                ).strip().lower()
                media_type = response.headers.get("content-type", "").split(
                    ";",
                    1,
                )[0].strip().lower()
                if (
                    content_encoding not in {"", "identity"}
                    or media_type
                    not in {
                        "application/zip",
                        "application/octet-stream",
                        "application/x-zip-compressed",
                    }
                ):
                    raise _fail("PAYMENT_PROVIDER_BILL_DOWNLOAD_REJECTED")
                raw = _http_response_bytes(
                    response,
                    deadline=deadline,
                    monotonic_clock=self._monotonic_clock,
                    max_bytes=payment_contract.MAX_RECONCILIATION_SOURCE_BYTES,
                )
                final_url = str(response.url)
                status_code = int(response.status_code)
        except DirectPaymentGatewayError:
            raise
        except httpx.HTTPError as exc:
            raise _fail("PAYMENT_PROVIDER_TRANSPORT_ERROR") from exc
        if final_url != download_url or status_code != 200:
            raise _fail("PAYMENT_PROVIDER_BILL_DOWNLOAD_REJECTED")
        return raw

    def reconciliation(self, provider_name: str, bill_date: str) -> VerifiedDirectBill:
        if provider_name != "alipay_direct":
            raise _fail("PAYMENT_PROVIDER_IDENTITY_INVALID")
        try:
            parsed_day = date.fromisoformat(str(bill_date))
        except (TypeError, ValueError) as exc:
            raise _fail("PAYMENT_PROVIDER_BILL_DATE_INVALID") from exc
        if str(parsed_day) != str(bill_date):
            raise _fail("PAYMENT_PROVIDER_BILL_DATE_INVALID")
        deadline = (
            _monotonic_value(self._monotonic_clock)
            + MAX_DIRECT_REQUEST_SECONDS
        )
        locator = self.request(
            "alipay_direct",
            "bill.downloadurl.query",
            {"bill_type": "trade", "bill_date": str(parsed_day)},
            _deadline=deadline,
        )
        locator_keys = set(locator.body)
        required_locator_keys = {"code", "msg", "bill_download_url"}
        allowed_locator_keys = required_locator_keys | {"sub_code", "sub_msg"}
        if (
            not required_locator_keys.issubset(locator_keys)
            or not locator_keys.issubset(allowed_locator_keys)
            or not isinstance(locator.body.get("bill_download_url"), str)
        ):
            raise _fail("PAYMENT_PROVIDER_BILL_LOCATOR_INVALID")
        source = self._download_trade_bill(
            str(locator.body["bill_download_url"]),
            deadline=deadline,
        )
        rows = _parse_alipay_trade_bill_zip(
            source,
            expected_bill_date=str(parsed_day),
        )
        return VerifiedDirectBill(
            provider_name="alipay_direct",
            bill_date=str(parsed_day),
            source_bytes=source,
            rows=rows,
            authentication_mode="signed_locator_tls_exact_url",
        )

    def close(self) -> None:
        if self._owned:
            self._client.close()


class WeChatPayGateway(payment_contract.PaymentProvider):
    """WeChat Pay API v3 Native gateway with authenticated notifications."""

    provider_name = "wechatpay_direct"

    def __init__(
        self,
        *,
        app_id: str,
        merchant_id: str,
        platform_certificate_serial: str,
        platform_public_key_pem: str,
        api_v3_key: bytes | None,
        callback_url: str,
        prod_mode: bool,
        transport: DirectPaymentTransport,
    ):
        merchant = str(merchant_id or "").strip()
        serial = _wechat_verifier_id(platform_certificate_serial)
        if not _WECHAT_MERCHANT_RE.fullmatch(merchant):
            raise _fail("PAYMENT_PROVIDER_MERCHANT_ID_INVALID")
        key = None
        if api_v3_key is not None:
            if not isinstance(api_v3_key, (bytes, bytearray)):
                raise _fail("PAYMENT_PROVIDER_API_V3_KEY_INVALID")
            key = bytes(api_v3_key)
            if len(key) != 32:
                raise _fail("PAYMENT_PROVIDER_API_V3_KEY_INVALID")
        if not hasattr(transport, "request") or not hasattr(transport, "reconciliation"):
            raise _fail("PAYMENT_PROVIDER_TRANSPORT_INVALID")
        self._app_id = _app_id(app_id)
        self._merchant_id = merchant
        self._platform_serial = serial
        self._platform_public_key = _rsa_public_key(platform_public_key_pem)
        self._api_v3_key = key
        self._callback_url = _direct_callback_url(callback_url, self.provider_name)
        self._prod_mode = _strict_bool(prod_mode, "mode")
        if not self._prod_mode:
            raise _fail("PAYMENT_PROVIDER_MODE_INVALID")
        self._transport = transport

    def __repr__(self) -> str:
        return "WeChatPayGateway(configuration_redacted=True)"

    def _request(self, operation: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        return _verified_body(
            self._transport.request(self.provider_name, operation, payload),
            self.provider_name,
        )

    def _request_with_receipt(
        self,
        operation: str,
        payload: Mapping[str, Any],
    ) -> tuple[dict[str, Any], bytes, str, int]:
        return _verified_response(
            self._transport.request(self.provider_name, operation, payload),
            self.provider_name,
        )

    def create_payment(self, order: dict[str, Any]) -> payment_contract.ProviderPaymentResult:
        item = _validate_order(
            order,
            provider_name=self.provider_name,
            prod_mode=self._prod_mode,
        )
        body = self._request(
            "native.create",
            {
                "appid": self._app_id,
                "mchid": self._merchant_id,
                "description": f"NoteAI Pro {item['product_id']}",
                "out_trade_no": item["merchant_order_no"],
                "notify_url": self._callback_url,
                "amount": {"total": item["amount_fen"], "currency": "CNY"},
            },
        )
        code_url = str(body.get("code_url") or "").strip()
        if (
            not code_url.startswith("weixin://wxpay/bizpayurl?")
            or len(code_url.encode("utf-8")) > MAX_CHECKOUT_VALUE_BYTES
        ):
            raise _fail("PAYMENT_PROVIDER_CHECKOUT_INVALID")
        checkout = json.dumps(
            {"channel": "wechatpay_native", "kind": "qr_text", "value": code_url},
            separators=(",", ":"),
            sort_keys=True,
        )
        return payment_contract.ProviderPaymentResult(
            merchant_order_no=item["merchant_order_no"],
            provider_payment_id=None,
            status="pending",
            amount_fen=item["amount_fen"],
            app_id=self._app_id,
            prod_mode=self._prod_mode,
            response_verified=True,
            checkout_token=checkout,
            provider_name=self.provider_name,
            currency="CNY",
        )

    def query_payment(
        self,
        lookup: payment_contract.ProviderPaymentLookup | str,
    ) -> payment_contract.ProviderPaymentResult:
        return self._query_payment_with_receipt(lookup)[0]

    def _query_payment_with_receipt(
        self,
        lookup: payment_contract.ProviderPaymentLookup | str,
    ) -> tuple[payment_contract.ProviderPaymentResult, bytes, str, int]:
        expected_payment_id = (
            str(lookup.provider_payment_id or "")
            if isinstance(lookup, payment_contract.ProviderPaymentLookup)
            else ""
        )
        merchant_order_no = _opaque(
            lookup.merchant_order_no if isinstance(lookup, payment_contract.ProviderPaymentLookup) else lookup,
            "order_no",
        )
        body, raw_body, signature, verified_at = self._request_with_receipt(
            "native.query_by_out_trade_no",
            {"out_trade_no": merchant_order_no, "mchid": self._merchant_id},
        )
        state_map = {
            "SUCCESS": "succeeded",
            "NOTPAY": "pending",
            "USERPAYING": "pending",
            "CLOSED": "failed",
            "REVOKED": "failed",
            "PAYERROR": "failed",
        }
        amount = body.get("amount")
        state = str(body.get("trade_state") or "")
        recognized_states = set(state_map) | {"REFUND"}
        if (
            body.get("appid") != self._app_id
            or str(body.get("mchid") or "") != self._merchant_id
            or body.get("out_trade_no") != merchant_order_no
            or state not in recognized_states
        ):
            raise _fail("PAYMENT_PROVIDER_RESPONSE_MISMATCH")
        expected_amount_fen = (
            lookup.expected_amount_fen
            if isinstance(lookup, payment_contract.ProviderPaymentLookup)
            else None
        )
        if state in {"SUCCESS", "REFUND"}:
            if (
                not isinstance(amount, Mapping)
                or "total" not in amount
                or amount.get("currency") != "CNY"
            ):
                raise _fail("PAYMENT_PROVIDER_RESPONSE_MISMATCH")
            amount_fen = _positive_fen(amount.get("total"))
        else:
            if expected_amount_fen is None:
                raise _fail("PAYMENT_PROVIDER_RESPONSE_MISMATCH")
            canonical_amount_fen = _positive_fen(expected_amount_fen)
            if amount is None:
                amount_fen = canonical_amount_fen
            elif not isinstance(amount, Mapping):
                raise _fail("PAYMENT_PROVIDER_RESPONSE_MISMATCH")
            else:
                if "currency" in amount and amount.get("currency") != "CNY":
                    raise _fail("PAYMENT_PROVIDER_RESPONSE_MISMATCH")
                if "total" in amount:
                    amount_fen = _positive_fen(amount.get("total"))
                    if state != "SUCCESS" and amount_fen != canonical_amount_fen:
                        raise _fail("PAYMENT_PROVIDER_RESPONSE_MISMATCH")
                else:
                    amount_fen = canonical_amount_fen
        payment_id = str(body.get("transaction_id") or "").strip()
        if state in {"SUCCESS", "REFUND"} or payment_id:
            payment_id = _opaque(payment_id, "payment_id")
        if expected_payment_id and state not in {"SUCCESS", "REFUND"} and payment_id != _opaque(
            expected_payment_id,
            "payment_id",
        ):
            raise _fail("PAYMENT_PROVIDER_RESPONSE_MISMATCH")
        if state == "REFUND":
            raise _fail("PAYMENT_PROVIDER_REFUND_RECONCILIATION_REQUIRED")
        try:
            provider_created_at = (
                _iso_to_epoch(body.get("success_time"))
                if state == "SUCCESS"
                else None
            )
        except DirectPaymentGatewayError as exc:
            raise _fail("PAYMENT_PROVIDER_RESPONSE_MISMATCH") from exc
        return (
            payment_contract.ProviderPaymentResult(
                merchant_order_no=merchant_order_no,
                provider_payment_id=payment_id or None,
                status=state_map[state],
                amount_fen=amount_fen,
                app_id=self._app_id,
                prod_mode=self._prod_mode,
                response_verified=True,
                provider_name=self.provider_name,
                currency="CNY",
                provider_created_at=provider_created_at,
            ),
            raw_body,
            signature,
            verified_at,
        )

    def process_payment_query(
        self,
        lookup: payment_contract.ProviderPaymentLookup,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        result, raw_body, signature, verified_at = (
            self._query_payment_with_receipt(lookup)
        )
        return _process_verified_payment_query(
            result,
            raw_body,
            signature,
            verified_at,
            expected_app_id=self._app_id,
            expected_provider_name=self.provider_name,
            expected_prod_mode=self._prod_mode,
            now=now,
        )

    def create_refund(self, refund: dict[str, Any]) -> payment_contract.ProviderRefundResult:
        item = _validate_refund(
            refund,
            provider_name=self.provider_name,
            prod_mode=self._prod_mode,
        )
        body, _raw_body, _signature, _verified_at = self._request_with_receipt(
            "refund.create",
            {
                "out_refund_no": item["merchant_refund_no"],
                "out_trade_no": item["merchant_order_no"],
                "reason": item["reason"],
                "notify_url": self._callback_url,
                "amount": {
                    "refund": item["amount_fen"],
                    "total": item["amount_fen"],
                    "currency": "CNY",
                },
            },
        )
        return self._refund_result(body, item)

    def query_refund(
        self,
        lookup: payment_contract.ProviderRefundLookup | str,
    ) -> payment_contract.ProviderRefundResult:
        return self._query_refund_with_receipt(lookup)[0]

    def _query_refund_with_receipt(
        self,
        lookup: payment_contract.ProviderRefundLookup | str,
    ) -> tuple[payment_contract.ProviderRefundResult, bytes, str, int]:
        if not isinstance(lookup, payment_contract.ProviderRefundLookup):
            raise _fail("PAYMENT_PROVIDER_REFUND_LOOKUP_INVALID")
        item = {
            "merchant_refund_no": _opaque(lookup.merchant_refund_no, "refund_no"),
            "merchant_order_no": _opaque(lookup.merchant_order_no, "order_no"),
            "provider_payment_id": str(lookup.provider_payment_id or ""),
            "provider_refund_id": str(lookup.provider_refund_id or ""),
            "amount_fen": None,
        }
        body, raw_body, signature, verified_at = self._request_with_receipt(
            "refund.query_by_out_refund_no",
            {"out_refund_no": item["merchant_refund_no"]},
        )
        return (
            self._refund_result(body, item),
            raw_body,
            signature,
            verified_at,
        )

    def process_refund_query(
        self,
        lookup: payment_contract.ProviderRefundLookup,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        result, raw_body, signature, verified_at = (
            self._query_refund_with_receipt(lookup)
        )
        return _process_verified_refund_query(
            result,
            raw_body,
            signature,
            verified_at,
            expected_app_id=self._app_id,
            expected_provider_name=self.provider_name,
            expected_prod_mode=self._prod_mode,
            now=now,
        )

    def _refund_result(
        self,
        body: Mapping[str, Any],
        expected: Mapping[str, Any],
    ) -> payment_contract.ProviderRefundResult:
        status_map = {
            "SUCCESS": "succeeded",
            "PROCESSING": "pending",
            "CLOSED": "failed",
            "ABNORMAL": "failed",
        }
        status = str(body.get("status") or "")
        amount = body.get("amount")
        merchant_order_no = _opaque(body.get("out_trade_no"), "order_no")
        payment_id = _opaque(body.get("transaction_id"), "payment_id")
        if (
            status not in status_map
            or body.get("out_refund_no") != expected["merchant_refund_no"]
            or expected.get("merchant_order_no") not in {"", merchant_order_no}
            or (
                status != "SUCCESS"
                and expected.get("provider_payment_id") not in {"", payment_id}
            )
            or (
                status != "SUCCESS"
                and expected.get("provider_refund_id")
                not in {None, "", str(body.get("refund_id") or "")}
            )
            or not isinstance(amount, Mapping)
            or amount.get("currency") != "CNY"
        ):
            raise _fail("PAYMENT_PROVIDER_RESPONSE_MISMATCH")
        try:
            provider_submitted_at = _iso_to_epoch(body.get("create_time"))
            provider_created_at = (
                _iso_to_epoch(body.get("success_time"))
                if status == "SUCCESS"
                else None
            )
        except DirectPaymentGatewayError as exc:
            raise _fail("PAYMENT_PROVIDER_RESPONSE_MISMATCH") from exc
        amount_fen = _positive_fen(amount.get("refund"))
        total_fen = _positive_fen(amount.get("total"))
        if status != "SUCCESS" and (
            total_fen != amount_fen
            or expected.get("amount_fen") not in {None, amount_fen}
        ):
            raise _fail("PAYMENT_PROVIDER_RESPONSE_MISMATCH")
        return payment_contract.ProviderRefundResult(
            merchant_refund_no=str(expected["merchant_refund_no"]),
            provider_refund_id=_opaque(body.get("refund_id"), "refund_id"),
            status=status_map[status],
            amount_fen=amount_fen,
            response_verified=True,
            merchant_order_no=merchant_order_no,
            provider_payment_id=payment_id,
            provider_name=self.provider_name,
            app_id=self._app_id,
            prod_mode=self._prod_mode,
            currency="CNY",
            provider_submitted_at=provider_submitted_at,
            provider_created_at=provider_created_at,
        )

    def reconciliation_rows(self, bill_date: str) -> tuple[bytes, tuple[dict[str, Any], ...]]:
        return _bill(self._transport, provider_name=self.provider_name, bill_date=bill_date)

    def authenticate_callback(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
        *,
        now: datetime | None = None,
    ) -> AuthenticatedDirectCallback:
        if self._api_v3_key is None:
            raise _fail("PAYMENT_CALLBACK_CONFIGURATION_INVALID")
        if not isinstance(raw_body, (bytes, bytearray)):
            raise _fail("PAYMENT_CALLBACK_SIZE_INVALID")
        raw = bytes(raw_body)
        if not raw or len(raw) > payment_contract.MAX_CALLBACK_DATA_BYTES:
            raise _fail("PAYMENT_CALLBACK_SIZE_INVALID")
        lowered: dict[str, str] = {}
        for key, value in headers.items():
            normalized = str(key).lower()
            if normalized in lowered:
                raise _fail("PAYMENT_CALLBACK_HEADER_INVALID")
            lowered[normalized] = str(value)
        timestamp_text = lowered.get("wechatpay-timestamp", "")
        nonce = lowered.get("wechatpay-nonce", "")
        signature = lowered.get("wechatpay-signature", "")
        try:
            serial = _wechat_verifier_id(lowered.get("wechatpay-serial"))
        except DirectPaymentGatewayError as exc:
            raise _fail("PAYMENT_CALLBACK_HEADER_INVALID") from exc
        signature_type = lowered.get("wechatpay-signature-type")
        try:
            timestamp = int(timestamp_text)
        except (TypeError, ValueError) as exc:
            raise _fail("PAYMENT_CALLBACK_HEADER_INVALID") from exc
        current = int((now or datetime.now(timezone.utc)).timestamp())
        if (
            serial != self._platform_serial
            or signature_type
            not in {None, "WECHATPAY2-SHA256-RSA2048"}
            or not _NONCE_RE.fullmatch(nonce)
            or abs(current - timestamp) > MAX_CALLBACK_AGE_SECONDS
            or not signature
            or len(signature) > payment_contract.MAX_SIGNATURE_BYTES * 2
        ):
            raise _fail("PAYMENT_CALLBACK_HEADER_INVALID")
        signature_input = (
            f"{timestamp_text}\n{nonce}\n".encode("ascii") + raw + b"\n"
        )
        try:
            decoded_signature = base64.b64decode(signature, validate=True)
            self._platform_public_key.verify(
                decoded_signature,
                signature_input,
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except (InvalidSignature, ValueError, binascii.Error) as exc:
            raise _fail("PAYMENT_CALLBACK_SIGNATURE_INVALID") from exc
        outer = _json_object(raw, "PAYMENT_CALLBACK_JSON_INVALID")
        resource = outer.get("resource")
        if not isinstance(resource, dict) or resource.get("algorithm") != "AEAD_AES_256_GCM":
            raise _fail("PAYMENT_CALLBACK_RESOURCE_INVALID")
        resource_nonce = str(resource.get("nonce") or "")
        associated = str(resource.get("associated_data") or "")
        try:
            ciphertext = base64.b64decode(str(resource.get("ciphertext") or ""), validate=True)
            plaintext = AESGCM(self._api_v3_key).decrypt(
                resource_nonce.encode("utf-8"),
                ciphertext,
                associated.encode("utf-8"),
            )
        except (InvalidTag, ValueError, binascii.Error) as exc:
            raise _fail("PAYMENT_CALLBACK_RESOURCE_INVALID") from exc
        provider = _json_object(plaintext, "PAYMENT_CALLBACK_RESOURCE_INVALID")
        outer_type = str(outer.get("event_type") or "")
        type_map = {
            "TRANSACTION.SUCCESS": "payment.succeeded",
            "TRANSACTION.CLOSED": "payment.failed",
            "REFUND.SUCCESS": "refund.succeeded",
            "REFUND.ABNORMAL": "refund.failed",
            "REFUND.CLOSED": "refund.failed",
        }
        if outer_type not in type_map:
            raise _fail("PAYMENT_CALLBACK_EVENT_TYPE_INVALID")
        event_type = type_map[outer_type]
        notification_created_time = _iso_to_epoch(outer.get("create_time"))
        if event_type.startswith("payment."):
            amount = provider.get("amount")
            expected_trade_states = {
                "TRANSACTION.SUCCESS": {"SUCCESS"},
                "TRANSACTION.CLOSED": {"CLOSED", "REVOKED", "PAYERROR"},
            }
            if (
                provider.get("appid") != self._app_id
                or str(provider.get("mchid") or "") != self._merchant_id
                or provider.get("trade_state")
                not in expected_trade_states.get(outer_type, set())
                or not isinstance(amount, Mapping)
                or amount.get("currency") != "CNY"
            ):
                raise _fail("PAYMENT_CALLBACK_BINDING_INVALID")
            raw_payment_id = str(provider.get("transaction_id") or "").strip()
            payment_id = (
                _opaque(raw_payment_id, "payment_id")
                if raw_payment_id
                else None
            )
            if event_type == "payment.succeeded" and payment_id is None:
                raise _fail("PAYMENT_CALLBACK_BINDING_INVALID")
            data = {
                "order_no": _opaque(provider.get("out_trade_no"), "order_no"),
                "payment_id": payment_id,
                "pay_amt": _fen_text(_positive_fen(amount.get("total"))),
            }
            created_time = (
                _iso_to_epoch(provider.get("success_time"))
                if event_type == "payment.succeeded"
                else notification_created_time
            )
        else:
            amount = provider.get("amount")
            expected_refund_states = {
                "REFUND.SUCCESS": "SUCCESS",
                "REFUND.ABNORMAL": "ABNORMAL",
                "REFUND.CLOSED": "CLOSED",
            }
            if (
                str(provider.get("mchid") or "") != self._merchant_id
                or provider.get("refund_status")
                != expected_refund_states.get(outer_type)
                or not isinstance(amount, Mapping)
                or set(amount)
                != {"total", "refund", "payer_total", "payer_refund"}
            ):
                raise _fail("PAYMENT_CALLBACK_BINDING_INVALID")
            total_fen = _positive_fen(amount.get("total"))
            refund_fen = _positive_fen(amount.get("refund"))
            payer_total_fen = _nonnegative_fen(
                amount.get("payer_total"),
                "payer_total",
            )
            payer_refund_fen = _nonnegative_fen(
                amount.get("payer_refund"),
                "payer_refund",
            )
            if (
                total_fen != refund_fen
                or payer_total_fen > total_fen
                or payer_refund_fen > refund_fen
                or total_fen - payer_total_fen
                != refund_fen - payer_refund_fen
            ):
                raise _fail("PAYMENT_CALLBACK_BINDING_INVALID")
            data = {
                "refund_order_no": _opaque(provider.get("out_refund_no"), "refund_no"),
                "refund_id": _opaque(provider.get("refund_id"), "refund_id"),
                "payment_id": _opaque(provider.get("transaction_id"), "payment_id"),
                "refund_amt": _fen_text(refund_fen),
            }
            created_time = (
                _iso_to_epoch(provider.get("success_time"))
                if event_type == "refund.succeeded"
                else notification_created_time
            )
        return AuthenticatedDirectCallback(
            event=payment_contract.CallbackEvent(
                provider_event_id=_opaque(outer.get("id"), "event_id"),
                event_type=event_type,
                created_time=created_time,
                prod_mode=self._prod_mode,
                app_id=self._app_id,
                data=data,
                provider_name=self.provider_name,
            ),
            raw_body=raw,
            signature=signature,
            signature_input_sha256=hashlib.sha256(signature_input).hexdigest(),
        )

    def process_callback(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        callback = self.authenticate_callback(raw_body, headers, now=now)
        result = payment_contract.process_authenticated_callback(
            callback.event,
            callback.raw_body,
            callback.signature,
            expected_app_id=self._app_id,
            expected_provider_name=self.provider_name,
            expected_prod_mode=self._prod_mode,
            now=now,
        )
        return {
            **result,
            "callback_audit": _callback_audit(
                callback,
                signature_scheme="WECHATPAY2-SHA256-RSA2048",
            ),
        }


class AlipayGateway(payment_contract.PaymentProvider):
    """Alipay direct trade gateway with RSA2 callback verification."""

    provider_name = "alipay_direct"

    def __init__(
        self,
        *,
        app_id: str,
        seller_id: str,
        alipay_public_key_pem: str,
        callback_url: str,
        prod_mode: bool,
        transport: DirectPaymentTransport,
    ):
        if not hasattr(transport, "request") or not hasattr(transport, "reconciliation"):
            raise _fail("PAYMENT_PROVIDER_TRANSPORT_INVALID")
        seller = str(seller_id or "").strip()
        if not _ALIPAY_SELLER_RE.fullmatch(seller):
            raise _fail("PAYMENT_PROVIDER_SELLER_ID_INVALID")
        self._app_id = _app_id(app_id)
        self._seller_id = seller
        self._public_key = _rsa_public_key(alipay_public_key_pem)
        self._callback_url = _direct_callback_url(callback_url, self.provider_name)
        self._prod_mode = _strict_bool(prod_mode, "mode")
        if not self._prod_mode:
            raise _fail("PAYMENT_PROVIDER_MODE_INVALID")
        self._transport = transport

    def __repr__(self) -> str:
        return "AlipayGateway(configuration_redacted=True)"

    def _request(self, operation: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        return _verified_body(
            self._transport.request(self.provider_name, operation, payload),
            self.provider_name,
        )

    def _request_with_receipt(
        self,
        operation: str,
        payload: Mapping[str, Any],
    ) -> tuple[dict[str, Any], bytes, str, int]:
        return _verified_response(
            self._transport.request(self.provider_name, operation, payload),
            self.provider_name,
        )

    def create_payment(self, order: dict[str, Any]) -> payment_contract.ProviderPaymentResult:
        item = _validate_order(
            order,
            provider_name=self.provider_name,
            prod_mode=self._prod_mode,
        )
        body = self._request(
            "trade.precreate",
            {
                "out_trade_no": item["merchant_order_no"],
                "total_amount": _fen_text(item["amount_fen"]),
                "subject": f"NoteAI Pro {item['product_id']}",
                "notify_url": self._callback_url,
            },
        )
        if body.get("out_trade_no") != item["merchant_order_no"]:
            raise _fail("PAYMENT_PROVIDER_RESPONSE_MISMATCH")
        checkout_url = _https_url(body.get("qr_code"), "checkout")
        parsed_checkout = urlsplit(checkout_url)
        try:
            checkout_port = parsed_checkout.port
        except ValueError as exc:
            raise _fail("PAYMENT_PROVIDER_CHECKOUT_INVALID") from exc
        if (
            parsed_checkout.hostname != "qr.alipay.com"
            or checkout_port not in {None, 443}
        ):
            raise _fail("PAYMENT_PROVIDER_CHECKOUT_INVALID")
        checkout = json.dumps(
            {"channel": "alipay_precreate", "kind": "qr_url", "url": checkout_url},
            separators=(",", ":"),
            sort_keys=True,
        )
        return payment_contract.ProviderPaymentResult(
            merchant_order_no=item["merchant_order_no"],
            provider_payment_id=None,
            status="pending",
            amount_fen=item["amount_fen"],
            app_id=self._app_id,
            prod_mode=self._prod_mode,
            response_verified=True,
            checkout_token=checkout,
            provider_name=self.provider_name,
            currency="CNY",
        )

    def query_payment(
        self,
        lookup: payment_contract.ProviderPaymentLookup | str,
    ) -> payment_contract.ProviderPaymentResult:
        return self._query_payment_with_receipt(lookup)[0]

    def _query_payment_with_receipt(
        self,
        lookup: payment_contract.ProviderPaymentLookup | str,
    ) -> tuple[payment_contract.ProviderPaymentResult, bytes, str, int]:
        expected_payment_id = (
            str(lookup.provider_payment_id or "")
            if isinstance(lookup, payment_contract.ProviderPaymentLookup)
            else ""
        )
        merchant_order_no = _opaque(
            lookup.merchant_order_no if isinstance(lookup, payment_contract.ProviderPaymentLookup) else lookup,
            "order_no",
        )
        body, raw_body, signature, verified_at = self._request_with_receipt(
            "trade.query",
            {"out_trade_no": merchant_order_no},
        )
        status_map = {
            "WAIT_BUYER_PAY": "pending",
            "TRADE_SUCCESS": "succeeded",
            "TRADE_FINISHED": "succeeded",
        }
        status = str(body.get("trade_status") or "")
        if status == "TRADE_CLOSED":
            raise _fail("PAYMENT_PROVIDER_REFUND_RECONCILIATION_REQUIRED")
        if body.get("out_trade_no") != merchant_order_no or status not in status_map:
            raise _fail("PAYMENT_PROVIDER_RESPONSE_MISMATCH")
        payment_id = str(body.get("trade_no") or "").strip()
        if status != "WAIT_BUYER_PAY" or payment_id:
            payment_id = _opaque(payment_id, "payment_id")
        if expected_payment_id and status not in {"TRADE_SUCCESS", "TRADE_FINISHED"} and payment_id != _opaque(
            expected_payment_id,
            "payment_id",
        ):
            raise _fail("PAYMENT_PROVIDER_RESPONSE_MISMATCH")
        amount_fen = _fen_from_decimal(body.get("total_amount"))
        try:
            provider_created_at = (
                _alipay_time_to_epoch(body.get("send_pay_date"))
                if status in {"TRADE_SUCCESS", "TRADE_FINISHED"}
                else None
            )
        except DirectPaymentGatewayError as exc:
            raise _fail("PAYMENT_PROVIDER_RESPONSE_MISMATCH") from exc
        return (
            payment_contract.ProviderPaymentResult(
                merchant_order_no=merchant_order_no,
                provider_payment_id=payment_id or None,
                status=status_map[status],
                amount_fen=amount_fen,
                app_id=self._app_id,
                prod_mode=self._prod_mode,
                response_verified=True,
                provider_name=self.provider_name,
                currency="CNY",
                provider_created_at=provider_created_at,
            ),
            raw_body,
            signature,
            verified_at,
        )

    def process_payment_query(
        self,
        lookup: payment_contract.ProviderPaymentLookup,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        result, raw_body, signature, verified_at = (
            self._query_payment_with_receipt(lookup)
        )
        return _process_verified_payment_query(
            result,
            raw_body,
            signature,
            verified_at,
            expected_app_id=self._app_id,
            expected_provider_name=self.provider_name,
            expected_prod_mode=self._prod_mode,
            now=now,
        )

    def create_refund(self, refund: dict[str, Any]) -> payment_contract.ProviderRefundResult:
        item = _validate_refund(
            refund,
            provider_name=self.provider_name,
            prod_mode=self._prod_mode,
        )
        body, _raw_body, _signature, _verified_at = self._request_with_receipt(
            "trade.refund",
            {
                "out_trade_no": item["merchant_order_no"],
                "out_request_no": item["merchant_refund_no"],
                "refund_amount": _fen_text(item["amount_fen"]),
                "refund_reason": item["reason"],
            },
        )
        return self._refund_submission_result(body, item)

    def query_refund(
        self,
        lookup: payment_contract.ProviderRefundLookup | str,
    ) -> payment_contract.ProviderRefundResult:
        return self._query_refund_with_receipt(lookup)[0]

    def _query_refund_with_receipt(
        self,
        lookup: payment_contract.ProviderRefundLookup | str,
    ) -> tuple[payment_contract.ProviderRefundResult, bytes, str, int]:
        if not isinstance(lookup, payment_contract.ProviderRefundLookup):
            raise _fail("PAYMENT_PROVIDER_REFUND_LOOKUP_INVALID")
        item = {
            "merchant_refund_no": _opaque(lookup.merchant_refund_no, "refund_no"),
            "merchant_order_no": _opaque(lookup.merchant_order_no, "order_no"),
            "provider_payment_id": str(lookup.provider_payment_id or ""),
            "amount_fen": None,
        }
        body, raw_body, signature, verified_at = self._request_with_receipt(
            "trade.fastpay.refund.query",
            {
                "out_trade_no": item["merchant_order_no"],
                "out_request_no": item["merchant_refund_no"],
                "query_options": ["gmt_refund_pay"],
            },
        )
        return (
            self._refund_query_result(body, item),
            raw_body,
            signature,
            verified_at,
        )

    def process_refund_query(
        self,
        lookup: payment_contract.ProviderRefundLookup,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        result, raw_body, signature, verified_at = (
            self._query_refund_with_receipt(lookup)
        )
        return _process_verified_refund_query(
            result,
            raw_body,
            signature,
            verified_at,
            expected_app_id=self._app_id,
            expected_provider_name=self.provider_name,
            expected_prod_mode=self._prod_mode,
            now=now,
        )

    def _refund_submission_result(
        self,
        body: Mapping[str, Any],
        expected: Mapping[str, Any],
    ) -> payment_contract.ProviderRefundResult:
        merchant_order_no = _opaque(body.get("out_trade_no"), "order_no")
        payment_id = _opaque(body.get("trade_no"), "payment_id")
        if str(body.get("fund_change") or "") not in {"Y", "N"}:
            raise _fail("PAYMENT_PROVIDER_STATUS_INVALID")
        amount_fen = _fen_from_decimal(body.get("refund_fee"), "refund_amount")
        if (
            merchant_order_no != expected["merchant_order_no"]
            or expected.get("provider_payment_id") not in {"", payment_id}
            or amount_fen != expected["amount_fen"]
        ):
            raise _fail("PAYMENT_PROVIDER_RESPONSE_MISMATCH")
        return payment_contract.ProviderRefundResult(
            merchant_refund_no=str(expected["merchant_refund_no"]),
            provider_refund_id=None,
            status="pending",
            amount_fen=amount_fen,
            response_verified=True,
            merchant_order_no=merchant_order_no,
            provider_payment_id=payment_id,
            provider_name=self.provider_name,
            app_id=self._app_id,
            prod_mode=self._prod_mode,
            currency="CNY",
        )

    def _refund_query_result(
        self,
        body: Mapping[str, Any],
        expected: Mapping[str, Any],
    ) -> payment_contract.ProviderRefundResult:
        merchant_order_no = _opaque(body.get("out_trade_no"), "order_no")
        merchant_refund_no = _opaque(body.get("out_request_no"), "refund_no")
        payment_id = _opaque(body.get("trade_no"), "payment_id")
        amount_fen = _fen_from_decimal(body.get("refund_amount"), "refund_amount")
        try:
            provider_created_at = _alipay_time_to_epoch(
                body.get("gmt_refund_pay")
            )
        except DirectPaymentGatewayError as exc:
            raise _fail("PAYMENT_PROVIDER_RESPONSE_MISMATCH") from exc
        if (
            body.get("refund_status") != "REFUND_SUCCESS"
            or merchant_order_no != expected["merchant_order_no"]
            or merchant_refund_no != expected["merchant_refund_no"]
            or expected.get("provider_refund_id") not in {None, ""}
        ):
            raise _fail("PAYMENT_PROVIDER_RESPONSE_MISMATCH")
        return payment_contract.ProviderRefundResult(
            merchant_refund_no=merchant_refund_no,
            provider_refund_id=None,
            status="succeeded",
            amount_fen=amount_fen,
            response_verified=True,
            merchant_order_no=merchant_order_no,
            provider_payment_id=payment_id,
            provider_name=self.provider_name,
            app_id=self._app_id,
            prod_mode=self._prod_mode,
            currency="CNY",
            provider_created_at=provider_created_at,
        )

    def reconciliation_rows(self, bill_date: str) -> tuple[bytes, tuple[dict[str, Any], ...]]:
        return _bill(self._transport, provider_name=self.provider_name, bill_date=bill_date)

    def authenticate_callback(
        self,
        raw_body: bytes,
    ) -> AuthenticatedDirectCallback:
        if not isinstance(raw_body, (bytes, bytearray)):
            raise _fail("PAYMENT_CALLBACK_SIZE_INVALID")
        raw = bytes(raw_body)
        if not raw or len(raw) > payment_contract.MAX_CALLBACK_DATA_BYTES:
            raise _fail("PAYMENT_CALLBACK_SIZE_INVALID")
        try:
            text = raw.decode("utf-8")
            pairs = parse_qsl(text, keep_blank_values=True, strict_parsing=True)
        except (UnicodeError, ValueError) as exc:
            raise _fail("PAYMENT_CALLBACK_FORM_INVALID") from exc
        fields: dict[str, str] = {}
        for key, value in pairs:
            if key in fields:
                raise _fail("PAYMENT_CALLBACK_DUPLICATE_FIELD")
            fields[key] = value
        signature = fields.get("sign", "")
        if (
            fields.get("sign_type") != "RSA2"
            or not signature
            or len(signature) > payment_contract.MAX_SIGNATURE_BYTES * 2
        ):
            raise _fail("PAYMENT_CALLBACK_SIGNATURE_INVALID")
        content = "&".join(
            f"{key}={fields[key]}"
            for key in sorted(fields)
            if key not in {"sign", "sign_type"} and fields[key] != ""
        )
        signature_input = content.encode("utf-8")
        try:
            decoded_signature = base64.b64decode(signature, validate=True)
            self._public_key.verify(
                decoded_signature,
                signature_input,
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except (InvalidSignature, ValueError, binascii.Error) as exc:
            raise _fail("PAYMENT_CALLBACK_SIGNATURE_INVALID") from exc
        if (
            fields.get("app_id") != self._app_id
            or fields.get("seller_id") != self._seller_id
            or fields.get("notify_type") != "trade_status_sync"
            or fields.get("currency") not in {None, "CNY"}
        ):
            raise _fail("PAYMENT_CALLBACK_BINDING_INVALID")
        trade_status = fields.get("trade_status", "")
        type_map = {
            "TRADE_SUCCESS": "payment.succeeded",
            "TRADE_FINISHED": "payment.succeeded",
        }
        if trade_status == "TRADE_CLOSED":
            raise _fail("PAYMENT_PROVIDER_REFUND_RECONCILIATION_REQUIRED")
        if trade_status not in type_map:
            raise _fail("PAYMENT_CALLBACK_EVENT_TYPE_INVALID")
        notification_created_time = _alipay_time_to_epoch(
            fields.get("notify_time")
        )
        event = payment_contract.CallbackEvent(
            provider_event_id=_opaque(fields.get("notify_id"), "event_id"),
            event_type=type_map[trade_status],
            created_time=(
                _alipay_time_to_epoch(fields.get("gmt_payment"))
                if type_map[trade_status] == "payment.succeeded"
                else notification_created_time
            ),
            prod_mode=self._prod_mode,
            app_id=self._app_id,
            data={
                "order_no": _opaque(fields.get("out_trade_no"), "order_no"),
                "payment_id": _opaque(fields.get("trade_no"), "payment_id"),
                "pay_amt": _fen_text(_fen_from_decimal(fields.get("total_amount"))),
            },
            provider_name=self.provider_name,
        )
        return AuthenticatedDirectCallback(
            event=event,
            raw_body=raw,
            signature=signature,
            signature_input_sha256=hashlib.sha256(signature_input).hexdigest(),
        )

    def process_callback(self, raw_body: bytes, *, now: datetime | None = None) -> dict[str, Any]:
        callback = self.authenticate_callback(raw_body)
        result = payment_contract.process_authenticated_callback(
            callback.event,
            callback.raw_body,
            callback.signature,
            expected_app_id=self._app_id,
            expected_provider_name=self.provider_name,
            expected_prod_mode=self._prod_mode,
            now=now,
        )
        return {
            **result,
            "callback_audit": _callback_audit(
                callback,
                signature_scheme="RSA2",
            ),
        }


def _iso_to_epoch(value: Any) -> int:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T"
            r"[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?"
            r"(?:Z|[+-](?:(?:0[0-9]|1[0-3]):[0-5][0-9]|14:00))",
            value,
        )
    ):
        raise _fail("PAYMENT_INVALID_EVENT_CLOCK")
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except (TypeError, ValueError) as exc:
        raise _fail("PAYMENT_INVALID_EVENT_CLOCK") from exc
    if parsed.tzinfo is None:
        raise _fail("PAYMENT_INVALID_EVENT_CLOCK")
    epoch = int(parsed.timestamp())
    if not 946684800 <= epoch <= 4102444800:
        raise _fail("PAYMENT_INVALID_EVENT_CLOCK")
    return epoch


def _alipay_time_to_epoch(value: Any) -> int:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2} "
            r"[0-9]{2}:[0-9]{2}:[0-9]{2}",
            value,
        )
    ):
        raise _fail("PAYMENT_INVALID_EVENT_CLOCK")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=ZoneInfo("Asia/Shanghai")
        )
    except (TypeError, ValueError) as exc:
        raise _fail("PAYMENT_INVALID_EVENT_CLOCK") from exc
    return _iso_to_epoch(parsed.isoformat())
