"""Strict Adapay wire adapter with injected, non-retrying transport.

The implementation follows Adapay's documented endpoints and the exact
request/response signing behavior of the official Python SDK, but it does not
use that SDK.  The official package keeps credentials in process-global
mutable state and may log request parameters and signatures.  This adapter
keeps credentials on one instance, never logs provider material and accepts a
transport explicitly so offline tests cannot accidentally use the network.
"""

from __future__ import annotations

import base64
import csv
import io
import ipaddress
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import PurePosixPath
from typing import Any, Mapping, Protocol
from urllib.parse import urlencode, urlsplit

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

import payment_contract


API_BASE_URL = "https://api.adapay.tech"
SDK_VERSION_HEADER = "python_v1.3.4"
MAX_PROVIDER_RESPONSE_BYTES = 64 * 1024
MAX_BILL_ARCHIVE_BYTES = payment_contract.MAX_RECONCILIATION_SOURCE_BYTES
MAX_BILL_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_BILL_FILES = 8
MAX_ZIP_RATIO = 100
ALLOWED_QR_CHANNELS = frozenset({"alipay_qr", "union_qr"})

_ASCII_CREDENTIAL_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_APP_ID_RE = re.compile(r"^[A-Za-z0-9_:-]{3,64}$")
_OPAQUE_RE = re.compile(r"^[A-Za-z0-9_:-]{1,128}$")
_PAY_CHANNEL_RE = re.compile(r"^[a-z][a-z0-9_]{1,19}$")
_MONEY_RE = re.compile(r"^(0|[1-9][0-9]{0,10})\.[0-9]{2}$")

_CHARGE_HEADER = (
    "交易时间",
    "app_id",
    "支付ID",
    "商户订单号",
    "交易类型",
    "交易金额",
    "手续费金额",
    "货币种类",
    "交易状态",
    "第三方订单号",
    "支付完成时间",
)
_REFUND_HEADER = (
    "交易时间",
    "app_id",
    "退款ID",
    "支付ID",
    "商户退款订单号",
    "商户支付订单号",
    "交易类型",
    "退款金额",
    "手续费金额",
    "货币种类",
    "退款状态",
)
_STATUS_MAP = {
    "I": "pending",
    "P": "pending",
    "F": "failed",
    "S": "succeeded",
}


class AdapayAdapterError(payment_contract.PaymentContractError):
    """Stable adapter failure without provider payload or credential text."""


@dataclass(frozen=True, repr=False)
class AdapayHttpRequest:
    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes = b""

    def __repr__(self) -> str:
        return (
            "AdapayHttpRequest("
            f"method={self.method!r},body_bytes={len(self.body)}"
            ")"
        )


@dataclass(frozen=True, repr=False)
class AdapayHttpResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes
    final_url: str

    def __repr__(self) -> str:
        return (
            "AdapayHttpResponse("
            f"status_code={self.status_code},body_bytes={len(self.body)},"
            "final_url_redacted=True"
            ")"
        )


class AdapayTransport(Protocol):
    def send(self, request: AdapayHttpRequest) -> AdapayHttpResponse:
        """Send one signed API request exactly once."""

    def download(
        self,
        url: str,
        *,
        max_bytes: int,
    ) -> AdapayHttpResponse:
        """Download one already validated bill URL exactly once."""


class HttpxAdapayTransport:
    """Bounded production transport. It never follows redirects or retries."""

    def __init__(self, client: httpx.Client | None = None):
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

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        max_bytes: int,
    ) -> AdapayHttpResponse:
        try:
            with self._client.stream(
                method,
                url,
                headers=dict(headers),
                content=body or None,
            ) as response:
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise AdapayAdapterError(
                            "PAYMENT_PROVIDER_RESPONSE_TOO_LARGE"
                        )
                    chunks.append(chunk)
                return AdapayHttpResponse(
                    status_code=int(response.status_code),
                    headers={
                        str(key).lower(): str(value)
                        for key, value in response.headers.items()
                    },
                    body=b"".join(chunks),
                    final_url=str(response.url),
                )
        except AdapayAdapterError:
            raise
        except httpx.HTTPError as exc:
            raise AdapayAdapterError(
                "PAYMENT_PROVIDER_TRANSPORT_ERROR"
            ) from exc

    def send(self, request: AdapayHttpRequest) -> AdapayHttpResponse:
        return self._request(
            request.method,
            request.url,
            headers=request.headers,
            body=request.body,
            max_bytes=MAX_PROVIDER_RESPONSE_BYTES,
        )

    def download(
        self,
        url: str,
        *,
        max_bytes: int,
    ) -> AdapayHttpResponse:
        return self._request(
            "GET",
            url,
            headers={
                "accept": "application/zip,application/octet-stream",
                "user-agent": "NoteAI-Adapay/1",
            },
            body=b"",
            max_bytes=max_bytes,
        )

    def close(self) -> None:
        if self._owned:
            self._client.close()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AdapayAdapterError("PAYMENT_PROVIDER_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _json_object(raw: str | bytes, *, code: str) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        value = json.loads(text, object_pairs_hook=_unique_object)
    except AdapayAdapterError:
        raise
    except (TypeError, UnicodeError, ValueError) as exc:
        raise AdapayAdapterError(code) from exc
    if not isinstance(value, dict):
        raise AdapayAdapterError(code)
    return value


def _opaque(value: Any, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not _OPAQUE_RE.fullmatch(normalized):
        raise AdapayAdapterError(f"PAYMENT_PROVIDER_{field.upper()}_INVALID")
    return normalized


def _app_id(value: Any) -> str:
    normalized = str(value or "").strip()
    if not _APP_ID_RE.fullmatch(normalized):
        raise AdapayAdapterError("PAYMENT_PROVIDER_APP_ID_INVALID")
    return normalized


def _mode(value: Any) -> bool:
    if value is True or type(value) is int and value == 1:
        return True
    if value is False or type(value) is int and value == 0:
        return False
    if isinstance(value, str):
        if value in {"true", "True", "1"}:
            return True
        if value in {"false", "False", "0"}:
            return False
    raise AdapayAdapterError("PAYMENT_PROVIDER_MODE_INVALID")


def _money_fen(value: Any) -> int:
    text = str(value or "").strip()
    if not _MONEY_RE.fullmatch(text):
        raise AdapayAdapterError("PAYMENT_PROVIDER_AMOUNT_INVALID")
    whole, fraction = text.split(".", 1)
    amount = int(whole) * 100 + int(fraction)
    if amount <= 0 or amount > 100_000_000:
        raise AdapayAdapterError("PAYMENT_PROVIDER_AMOUNT_INVALID")
    return amount


def _fen_text(value: Any) -> str:
    if isinstance(value, bool):
        raise AdapayAdapterError("PAYMENT_PROVIDER_AMOUNT_INVALID")
    try:
        amount = int(value)
    except (TypeError, ValueError) as exc:
        raise AdapayAdapterError("PAYMENT_PROVIDER_AMOUNT_INVALID") from exc
    if amount <= 0 or amount > 100_000_000:
        raise AdapayAdapterError("PAYMENT_PROVIDER_AMOUNT_INVALID")
    return f"{amount // 100}.{amount % 100:02d}"


def _validated_https_url(
    value: Any,
    *,
    allowed_hosts: frozenset[str] | None,
    allow_query: bool,
    code: str,
) -> str:
    text = str(value or "")
    if not text or text != text.strip() or len(text.encode("utf-8")) > 2048:
        raise AdapayAdapterError(code)
    try:
        parsed = urlsplit(text)
        port = parsed.port
    except ValueError as exc:
        raise AdapayAdapterError(code) from exc
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.fragment
        or (not allow_query and parsed.query)
        or (allowed_hosts is not None and host not in allowed_hosts)
    ):
        raise AdapayAdapterError(code)
    return text


def _host_set(values: Any, *, field: str) -> frozenset[str]:
    if isinstance(values, str):
        items = values.split(",")
    else:
        try:
            items = list(values)
        except TypeError as exc:
            raise AdapayAdapterError(
                f"PAYMENT_PROVIDER_{field.upper()}_INVALID"
            ) from exc
    result: set[str] = set()
    for raw in items:
        text = str(raw or "")
        if text != text.strip():
            raise AdapayAdapterError(
                f"PAYMENT_PROVIDER_{field.upper()}_INVALID"
            )
        host = text.lower()
        try:
            parsed = urlsplit(f"https://{host}")
            port = parsed.port
        except ValueError as exc:
            raise AdapayAdapterError(
                f"PAYMENT_PROVIDER_{field.upper()}_INVALID"
            ) from exc
        if (
            not host
            or parsed.hostname != host
            or port is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise AdapayAdapterError(
                f"PAYMENT_PROVIDER_{field.upper()}_INVALID"
            )
        result.add(host)
    if not result or len(result) > 8:
        raise AdapayAdapterError(
            f"PAYMENT_PROVIDER_{field.upper()}_INVALID"
        )
    return frozenset(result)


class AdapayAdapter(payment_contract.PaymentProvider):
    """One immutable Adapay configuration and one injected transport."""

    def __init__(
        self,
        *,
        api_key: str,
        merchant_private_key_pem: str,
        adapay_public_key_pem: str,
        app_id: str,
        prod_mode: bool,
        pay_channel: str,
        callback_url: str,
        checkout_hosts: tuple[str, ...] | list[str] | str,
        bill_hosts: tuple[str, ...] | list[str] | str,
        transport: AdapayTransport,
    ):
        if not _ASCII_CREDENTIAL_RE.fullmatch(str(api_key or "")):
            raise AdapayAdapterError("PAYMENT_PROVIDER_API_KEY_INVALID")
        if not hasattr(transport, "send") or not hasattr(transport, "download"):
            raise AdapayAdapterError("PAYMENT_PROVIDER_TRANSPORT_INVALID")
        try:
            private_key = serialization.load_pem_private_key(
                str(merchant_private_key_pem or "").encode("ascii"),
                password=None,
            )
            public_key = serialization.load_pem_public_key(
                str(adapay_public_key_pem or "").encode("ascii"),
            )
        except (TypeError, UnicodeError, ValueError) as exc:
            raise AdapayAdapterError(
                "PAYMENT_PROVIDER_KEY_INVALID"
            ) from exc
        if (
            not isinstance(private_key, rsa.RSAPrivateKey)
            or not isinstance(public_key, rsa.RSAPublicKey)
            or private_key.key_size < 2048
            or private_key.key_size > 4096
            or public_key.key_size < 2048
            or public_key.key_size > 4096
        ):
            raise AdapayAdapterError("PAYMENT_PROVIDER_KEY_INVALID")
        channel = str(pay_channel or "")
        if (
            not _PAY_CHANNEL_RE.fullmatch(channel)
            or channel not in ALLOWED_QR_CHANNELS
        ):
            raise AdapayAdapterError("PAYMENT_PROVIDER_CHANNEL_INVALID")
        self._api_key = str(api_key)
        self._private_key = private_key
        self._public_key_pem = str(adapay_public_key_pem)
        self._app_id = _app_id(app_id)
        self._prod_mode = bool(prod_mode)
        self._pay_channel = channel
        self._checkout_hosts = _host_set(
            checkout_hosts,
            field="checkout_hosts",
        )
        self._bill_hosts = _host_set(bill_hosts, field="bill_hosts")
        self._callback_url = _validated_https_url(
            callback_url,
            allowed_hosts=None,
            allow_query=False,
            code="PAYMENT_PROVIDER_CALLBACK_URL_INVALID",
        )
        self._transport = transport

    def __repr__(self) -> str:
        return (
            "AdapayAdapter("
            f"app_id={self._app_id!r},prod_mode={self._prod_mode},"
            f"pay_channel={self._pay_channel!r})"
        )

    def _sign(self, text: str) -> str:
        try:
            signature = self._private_key.sign(
                text.encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA1(),
            )
        except Exception as exc:
            raise AdapayAdapterError(
                "PAYMENT_PROVIDER_REQUEST_SIGNING_FAILED"
            ) from exc
        return base64.b64encode(signature).decode("ascii")

    def _request(
        self,
        method: str,
        path: str,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        if method not in {"GET", "POST"} or not path.startswith("/v1/"):
            raise AdapayAdapterError("PAYMENT_PROVIDER_REQUEST_INVALID")
        base_url = API_BASE_URL + path
        if method == "POST":
            body_text = json.dumps(dict(params))
            signed_text = base_url + body_text
            url = base_url
            body = body_text.encode("utf-8")
        else:
            pairs = sorted((str(key), str(value)) for key, value in params.items())
            plain_query = "&".join(f"{key}={value}" for key, value in pairs)
            signed_text = base_url + plain_query
            url = base_url + ("?" + urlencode(pairs) if pairs else "")
            body = b""
        headers = {
            "accept": "application/json",
            "authorization": self._api_key,
            "sdk_version": SDK_VERSION_HEADER,
            "signature": self._sign(signed_text),
        }
        if method == "POST":
            headers["content-type"] = "application/json"
        request = AdapayHttpRequest(
            method=method,
            url=url,
            headers=headers,
            body=body,
        )
        response = self._transport.send(request)
        if response.final_url != url:
            raise AdapayAdapterError("PAYMENT_PROVIDER_REDIRECT_REJECTED")
        content_type = str(
            response.headers.get("content-type", "")
        ).split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise AdapayAdapterError(
                "PAYMENT_PROVIDER_CONTENT_TYPE_INVALID"
            )
        if (
            response.status_code < 200
            or response.status_code >= 300
            or not response.body
            or len(response.body) > MAX_PROVIDER_RESPONSE_BYTES
        ):
            raise AdapayAdapterError("PAYMENT_PROVIDER_RESPONSE_INVALID")
        envelope = _json_object(
            response.body,
            code="PAYMENT_PROVIDER_RESPONSE_INVALID",
        )
        data = envelope.get("data")
        signature = envelope.get("signature")
        if not isinstance(data, str) or not isinstance(signature, str):
            raise AdapayAdapterError(
                "PAYMENT_PROVIDER_RESPONSE_UNSIGNED"
            )
        if not payment_contract.verify_adapay_signature(
            data,
            signature,
            self._public_key_pem,
        ):
            raise AdapayAdapterError(
                "PAYMENT_PROVIDER_RESPONSE_SIGNATURE_INVALID"
            )
        return _json_object(
            data,
            code="PAYMENT_PROVIDER_DATA_INVALID",
        )

    def _validate_order(self, order: dict[str, Any]) -> dict[str, Any]:
        expected_keys = {
            "merchant_order_no",
            "amount_fen",
            "currency",
            "product_kind",
            "product_id",
            "provider_mode",
            "device_ip",
        }
        if not isinstance(order, dict) or set(order) != expected_keys:
            raise AdapayAdapterError("PAYMENT_PROVIDER_ORDER_INVALID")
        if order["currency"] != "CNY":
            raise AdapayAdapterError("PAYMENT_PROVIDER_CURRENCY_INVALID")
        expected_mode = "live" if self._prod_mode else "mock"
        if order["provider_mode"] != expected_mode:
            raise AdapayAdapterError("PAYMENT_PROVIDER_MODE_INVALID")
        kind = str(order["product_kind"] or "")
        product_id = str(order["product_id"] or "")
        if (
            kind not in {"subscription", "credit_package"}
            or not re.fullmatch(r"[a-z][a-z0-9_]{1,31}", product_id)
        ):
            raise AdapayAdapterError("PAYMENT_PROVIDER_PRODUCT_INVALID")
        try:
            device_ip = ipaddress.ip_address(str(order["device_ip"] or ""))
        except ValueError as exc:
            raise AdapayAdapterError(
                "PAYMENT_PROVIDER_DEVICE_IP_INVALID"
            ) from exc
        if not device_ip.is_global:
            raise AdapayAdapterError("PAYMENT_PROVIDER_DEVICE_IP_INVALID")
        return {
            "merchant_order_no": _opaque(
                order["merchant_order_no"],
                field="merchant_order_no",
            ),
            "amount_text": _fen_text(order["amount_fen"]),
            "amount_fen": int(order["amount_fen"]),
            "product_kind": kind,
            "product_id": product_id,
            "device_ip": str(device_ip),
        }

    def _payment_result(
        self,
        data: dict[str, Any],
        *,
        include_checkout: bool,
    ) -> payment_contract.ProviderPaymentResult:
        payment_id = _opaque(data.get("id"), field="payment_id")
        merchant_order_no = _opaque(
            data.get("order_no"),
            field="merchant_order_no",
        )
        amount_fen = _money_fen(data.get("pay_amt"))
        status = str(data.get("status") or "")
        if status not in {"pending", "succeeded", "failed"}:
            raise AdapayAdapterError("PAYMENT_PROVIDER_STATUS_INVALID")
        app_id = _app_id(data.get("app_id", self._app_id))
        prod_mode = _mode(data.get("prod_mode", self._prod_mode))
        channel = str(data.get("pay_channel", self._pay_channel))
        if (
            app_id != self._app_id
            or prod_mode is not self._prod_mode
            or channel != self._pay_channel
        ):
            raise AdapayAdapterError("PAYMENT_PROVIDER_RESPONSE_MISMATCH")
        checkout = ""
        if include_checkout:
            expend = data.get("expend")
            if not isinstance(expend, dict):
                raise AdapayAdapterError(
                    "PAYMENT_PROVIDER_CHECKOUT_INVALID"
                )
            checkout_url = _validated_https_url(
                expend.get("qrcode_url"),
                allowed_hosts=self._checkout_hosts,
                allow_query=True,
                code="PAYMENT_PROVIDER_CHECKOUT_INVALID",
            )
            checkout = json.dumps(
                {
                    "kind": "qr_url",
                    "channel": self._pay_channel,
                    "url": checkout_url,
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
        return payment_contract.ProviderPaymentResult(
            merchant_order_no=merchant_order_no,
            provider_payment_id=payment_id,
            status=status,
            amount_fen=amount_fen,
            app_id=app_id,
            prod_mode=prod_mode,
            response_verified=True,
            checkout_token=checkout,
        )

    def create_payment(
        self,
        order: dict[str, Any],
    ) -> payment_contract.ProviderPaymentResult:
        validated = self._validate_order(order)
        title = (
            "NoteAI Pro 30-day subscription"
            if validated["product_kind"] == "subscription"
            else "NoteAI Pro credit package"
        )
        data = self._request(
            "POST",
            "/v1/payments",
            {
                "order_no": validated["merchant_order_no"],
                "app_id": self._app_id,
                "pay_channel": self._pay_channel,
                "pay_amt": validated["amount_text"],
                "goods_title": title,
                "goods_desc": (
                    "NoteAI Pro fixed catalogue "
                    + validated["product_id"]
                ),
                "currency": "cny",
                "device_info": {
                    "device_type": "4",
                    "device_ip": validated["device_ip"],
                },
                "notify_url": self._callback_url,
            },
        )
        result = self._payment_result(data, include_checkout=True)
        if (
            result.merchant_order_no != validated["merchant_order_no"]
            or result.amount_fen != validated["amount_fen"]
        ):
            raise AdapayAdapterError("PAYMENT_PROVIDER_RESPONSE_MISMATCH")
        return result

    def query_payment(
        self,
        provider_payment_id: str,
    ) -> payment_contract.ProviderPaymentResult:
        payment_id = _opaque(provider_payment_id, field="payment_id")
        data = self._request(
            "GET",
            f"/v1/payments/{payment_id}",
            {},
        )
        result = self._payment_result(data, include_checkout=False)
        if result.provider_payment_id != payment_id:
            raise AdapayAdapterError("PAYMENT_PROVIDER_RESPONSE_MISMATCH")
        return result

    def _validate_refund(self, refund: dict[str, Any]) -> dict[str, Any]:
        expected_keys = {
            "merchant_refund_no",
            "merchant_order_no",
            "provider_payment_id",
            "amount_fen",
            "currency",
            "provider_mode",
            "reason_code",
        }
        if not isinstance(refund, dict) or set(refund) != expected_keys:
            raise AdapayAdapterError("PAYMENT_PROVIDER_REFUND_INVALID")
        if refund["currency"] != "CNY":
            raise AdapayAdapterError("PAYMENT_PROVIDER_CURRENCY_INVALID")
        expected_mode = "live" if self._prod_mode else "mock"
        if refund["provider_mode"] != expected_mode:
            raise AdapayAdapterError("PAYMENT_PROVIDER_MODE_INVALID")
        reason_code = str(refund["reason_code"] or "")
        reasons = {
            "customer_request": "customer request",
            "service_not_delivered": "service not delivered",
            "duplicate_payment": "duplicate payment",
            "fraud_review": "fraud review",
        }
        if reason_code not in reasons:
            raise AdapayAdapterError(
                "PAYMENT_PROVIDER_REFUND_REASON_INVALID"
            )
        return {
            "merchant_refund_no": _opaque(
                refund["merchant_refund_no"],
                field="merchant_refund_no",
            ),
            "merchant_order_no": _opaque(
                refund["merchant_order_no"],
                field="merchant_order_no",
            ),
            "provider_payment_id": _opaque(
                refund["provider_payment_id"],
                field="payment_id",
            ),
            "amount_text": _fen_text(refund["amount_fen"]),
            "amount_fen": int(refund["amount_fen"]),
            "reason": reasons[reason_code],
        }

    def create_refund(
        self,
        refund: dict[str, Any],
    ) -> payment_contract.ProviderRefundResult:
        validated = self._validate_refund(refund)
        data = self._request(
            "POST",
            (
                f"/v1/payments/{validated['provider_payment_id']}"
                "/refunds"
            ),
            {
                "refund_order_no": validated["merchant_refund_no"],
                "refund_amt": validated["amount_text"],
                "reason": validated["reason"],
                "notify_url": self._callback_url,
                "fail_fast": "N",
            },
        )
        provider_refund_id = _opaque(data.get("id"), field="refund_id")
        payment_id = _opaque(data.get("payment_id"), field="payment_id")
        amount_fen = _money_fen(data.get("refund_amt"))
        status = str(data.get("status") or "")
        if (
            payment_id != validated["provider_payment_id"]
            or amount_fen != validated["amount_fen"]
            or status not in {"pending", "succeeded"}
        ):
            raise AdapayAdapterError("PAYMENT_PROVIDER_RESPONSE_MISMATCH")
        # Official documentation states synchronous success means accepted;
        # only callback/query evidence may make the refund terminal.
        return payment_contract.ProviderRefundResult(
            merchant_refund_no=validated["merchant_refund_no"],
            provider_refund_id=provider_refund_id,
            status="pending",
            amount_fen=amount_fen,
            response_verified=True,
        )

    def query_refund(
        self,
        provider_refund_id: str,
    ) -> payment_contract.ProviderRefundResult:
        refund_id = _opaque(provider_refund_id, field="refund_id")
        data = self._request(
            "GET",
            "/v1/payments/refunds",
            {"refund_id": refund_id},
        )
        if _mode(data.get("prod_mode")) is not self._prod_mode:
            raise AdapayAdapterError("PAYMENT_PROVIDER_RESPONSE_MISMATCH")
        if data.get("status") != "succeeded":
            raise AdapayAdapterError("PAYMENT_PROVIDER_STATUS_INVALID")
        rows = data.get("refunds")
        if not isinstance(rows, list) or len(rows) != 1:
            raise AdapayAdapterError("PAYMENT_PROVIDER_REFUND_QUERY_INVALID")
        row = rows[0]
        if not isinstance(row, dict):
            raise AdapayAdapterError("PAYMENT_PROVIDER_REFUND_QUERY_INVALID")
        returned_id = _opaque(row.get("refund_id"), field="refund_id")
        if returned_id != refund_id:
            raise AdapayAdapterError("PAYMENT_PROVIDER_RESPONSE_MISMATCH")
        trans_status = str(row.get("trans_status") or "")
        if trans_status not in _STATUS_MAP:
            raise AdapayAdapterError("PAYMENT_PROVIDER_STATUS_INVALID")
        return payment_contract.ProviderRefundResult(
            merchant_refund_no=_opaque(
                row.get("refund_order_no"),
                field="merchant_refund_no",
            ),
            provider_refund_id=returned_id,
            status=_STATUS_MAP[trans_status],
            amount_fen=_money_fen(row.get("refund_amt")),
            response_verified=True,
        )

    def reconciliation_rows(
        self,
        bill_date: str,
    ) -> tuple[bytes, tuple[dict[str, Any], ...]]:
        try:
            parsed_date = date.fromisoformat(str(bill_date))
            if str(parsed_date) != str(bill_date):
                raise ValueError
            compact_date = parsed_date.strftime("%Y%m%d")
        except (TypeError, ValueError) as exc:
            raise AdapayAdapterError(
                "PAYMENT_PROVIDER_BILL_DATE_INVALID"
            ) from exc
        data = self._request(
            "POST",
            "/v1/bill/download",
            {"bill_date": compact_date},
        )
        if (
            data.get("status") != "succeeded"
            or _mode(data.get("prod_mode")) is not self._prod_mode
        ):
            raise AdapayAdapterError("PAYMENT_PROVIDER_BILL_UNAVAILABLE")
        bill_url = _validated_https_url(
            data.get("bill_download_url"),
            allowed_hosts=self._bill_hosts,
            allow_query=True,
            code="PAYMENT_PROVIDER_BILL_URL_INVALID",
        )
        response = self._transport.download(
            bill_url,
            max_bytes=MAX_BILL_ARCHIVE_BYTES,
        )
        if response.final_url != bill_url:
            raise AdapayAdapterError("PAYMENT_PROVIDER_REDIRECT_REJECTED")
        content_type = str(
            response.headers.get("content-type", "")
        ).split(";", 1)[0].strip().lower()
        if content_type not in {
            "application/zip",
            "application/octet-stream",
            "binary/octet-stream",
        }:
            raise AdapayAdapterError(
                "PAYMENT_PROVIDER_BILL_CONTENT_TYPE_INVALID"
            )
        source = bytes(response.body)
        if (
            response.status_code < 200
            or response.status_code >= 300
            or not source
            or len(source) > MAX_BILL_ARCHIVE_BYTES
        ):
            raise AdapayAdapterError(
                "PAYMENT_PROVIDER_BILL_ARCHIVE_INVALID"
            )
        rows = self._parse_bill_archive(source)
        return source, rows

    def _parse_bill_archive(
        self,
        source: bytes,
    ) -> tuple[dict[str, Any], ...]:
        try:
            archive = zipfile.ZipFile(io.BytesIO(source), "r")
        except (OSError, zipfile.BadZipFile) as exc:
            raise AdapayAdapterError(
                "PAYMENT_PROVIDER_BILL_ARCHIVE_INVALID"
            ) from exc
        with archive:
            infos = archive.infolist()
            if not infos or len(infos) > MAX_BILL_FILES:
                raise AdapayAdapterError(
                    "PAYMENT_PROVIDER_BILL_ARCHIVE_INVALID"
                )
            total_size = 0
            relevant: list[tuple[str, zipfile.ZipInfo]] = []
            seen_kinds: set[str] = set()
            for info in infos:
                path = PurePosixPath(info.filename)
                mode = (info.external_attr >> 16) & 0o170000
                if (
                    info.is_dir()
                    or len(info.filename.encode("utf-8")) > 255
                    or path.name != info.filename
                    or "\\" in info.filename
                    or info.flag_bits & 0x1
                    or mode == 0o120000
                    or info.file_size < 0
                    or info.compress_size < 0
                ):
                    raise AdapayAdapterError(
                        "PAYMENT_PROVIDER_BILL_ARCHIVE_INVALID"
                    )
                total_size += int(info.file_size)
                if total_size > MAX_BILL_UNCOMPRESSED_BYTES:
                    raise AdapayAdapterError(
                        "PAYMENT_PROVIDER_BILL_ARCHIVE_INVALID"
                    )
                if (
                    info.file_size > 0
                    and (
                        info.compress_size <= 0
                        or info.file_size
                        > max(info.compress_size, 1) * MAX_ZIP_RATIO
                    )
                ):
                    raise AdapayAdapterError(
                        "PAYMENT_PROVIDER_BILL_ARCHIVE_INVALID"
                    )
                kind = ""
                if info.filename.startswith("Charge") and info.filename.endswith(
                    ".csv"
                ):
                    kind = "payment"
                elif info.filename.startswith(
                    "Refund"
                ) and info.filename.endswith(".csv"):
                    kind = "refund"
                if kind:
                    if kind in seen_kinds:
                        raise AdapayAdapterError(
                            "PAYMENT_PROVIDER_BILL_ARCHIVE_INVALID"
                        )
                    seen_kinds.add(kind)
                    relevant.append((kind, info))
            if not relevant:
                raise AdapayAdapterError(
                    "PAYMENT_PROVIDER_BILL_ARCHIVE_INVALID"
                )
            output: list[dict[str, Any]] = []
            for kind, info in relevant:
                try:
                    raw = archive.read(info)
                    text = raw.decode("utf-8-sig")
                except (RuntimeError, UnicodeError, zipfile.BadZipFile) as exc:
                    raise AdapayAdapterError(
                        "PAYMENT_PROVIDER_BILL_CSV_INVALID"
                    ) from exc
                lines = [
                    line
                    for line in text.splitlines()
                    if line and not line.startswith("#")
                ]
                if not lines:
                    raise AdapayAdapterError(
                        "PAYMENT_PROVIDER_BILL_CSV_INVALID"
                    )
                reader = csv.DictReader(lines)
                expected_header = (
                    _CHARGE_HEADER if kind == "payment" else _REFUND_HEADER
                )
                if tuple(reader.fieldnames or ()) != expected_header:
                    raise AdapayAdapterError(
                        "PAYMENT_PROVIDER_BILL_CSV_INVALID"
                    )
                for row in reader:
                    if (
                        None in row
                        or any(value is None for value in row.values())
                        or len(output)
                        >= payment_contract.MAX_RECONCILIATION_ROWS
                    ):
                        raise AdapayAdapterError(
                            "PAYMENT_PROVIDER_BILL_CSV_INVALID"
                        )
                    if row["app_id"] != self._app_id:
                        raise AdapayAdapterError(
                            "PAYMENT_PROVIDER_BILL_APP_MISMATCH"
                        )
                    if row["货币种类"] != "cny":
                        raise AdapayAdapterError(
                            "PAYMENT_PROVIDER_BILL_CURRENCY_INVALID"
                        )
                    raw_status = (
                        row["交易状态"]
                        if kind == "payment"
                        else row["退款状态"]
                    )
                    if raw_status not in _STATUS_MAP:
                        raise AdapayAdapterError(
                            "PAYMENT_PROVIDER_BILL_STATUS_INVALID"
                        )
                    output.append(
                        {
                            "kind": kind,
                            "reference": _opaque(
                                (
                                    row["商户订单号"]
                                    if kind == "payment"
                                    else row["商户退款订单号"]
                                ),
                                field="bill_reference",
                            ),
                            "amount_fen": _money_fen(
                                (
                                    row["交易金额"]
                                    if kind == "payment"
                                    else row["退款金额"]
                                )
                            ),
                            "status": _STATUS_MAP[raw_status],
                        }
                    )
            return tuple(output)
