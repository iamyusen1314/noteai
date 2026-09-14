"""Dedicated payment callback runtime.

This app intentionally contains no user, Admin or provider-submission route.
It is safe by default: callback processing is disabled, and a production
request is rejected unless the database session is the exact payment role.
"""

from __future__ import annotations

import json
import logging
import os
import re
from urllib.parse import parse_qsl

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

import db
import direct_payment_gateways
import payment_adapter_runtime
import payment_contract


# Use the existing server handler/level. A standalone logger's INFO records
# disappear under Uvicorn's default configuration, including callback digests.
_LOGGER = logging.getLogger("uvicorn.error.payment")
_TRUE_VALUES = {"1", "true", "yes"}
_CALLBACK_PROVIDERS = {"adapay", "wechatpay_direct", "alipay_direct"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DIRECT_CALLBACK_SCHEMES = {
    "wechatpay_direct": "WECHATPAY2-SHA256-RSA2048",
    "alipay_direct": "RSA2",
}
_DIRECT_CALLBACK_EVENT_TYPES = {
    "payment.succeeded",
    "payment.failed",
    "refund.succeeded",
    "refund.failed",
}

app = FastAPI(
    title="NoteAI Payment Boundary",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.on_event("startup")
async def startup():
    if (os.environ.get("NOTEAI_ITEM31_DML_BINDING_FILE") or os.environ.get("NOTEAI_ITEM31_DML_BINDING_SHA256")
            or os.environ.get("NOTEAI_PAYMENT_CANARY_ENABLED", "") not in {"", "0"}):
        import collect_item31_canary_dml
        runtime = collect_item31_canary_dml.configured_runtime("payment", db)
        app.state.item31_canary_runtime = runtime
        app.state.item31_canary_callback_resolver = runtime.scope


@app.on_event("shutdown")
async def shutdown():
    runtime = getattr(app.state, "item31_canary_runtime", None)
    if runtime is not None:
        runtime.close()


def _enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUE_VALUES


def _production() -> bool:
    return (
        os.environ.get("NOTEAI_DEPLOYMENT_STAGE", "").strip().lower()
        == "production"
    )


def _runtime_role_ok() -> bool:
    return os.environ.get("NOTEAI_RUNTIME_ROLE", "").strip() == "payment"


class _CallbackOnlyTransport:
    """No-network transport used only to construct callback authenticators."""

    def request(self, _provider_name, _operation, _payload):
        raise payment_contract.PaymentProviderUnavailable()

    def reconciliation(self, _provider_name, _bill_date):
        raise payment_contract.PaymentProviderUnavailable()


_CALLBACK_ONLY_TRANSPORT = _CallbackOnlyTransport()


def _configured_callback_providers() -> frozenset[str]:
    raw = os.environ.get("NOTEAI_PAYMENT_CALLBACK_PROVIDERS", "").strip()
    if not raw:
        return frozenset({"adapay"}) if (
            os.environ.get("NOTEAI_ADAPAY_APP_ID", "").strip()
            or os.environ.get("NOTEAI_ADAPAY_PUBLIC_KEY", "").strip()
        ) else frozenset()
    values = [value.strip() for value in raw.split(",")]
    if (
        any(not value for value in values)
        or len(values) != len(set(values))
        or any(value not in _CALLBACK_PROVIDERS for value in values)
    ):
        return frozenset()
    return frozenset(values)


def _direct_callback_gateway(provider_name: str):
    mode_name = {
        "wechatpay_direct": "NOTEAI_WECHATPAY_PROD_MODE",
        "alipay_direct": "NOTEAI_ALIPAY_PROD_MODE",
    }.get(provider_name)
    if mode_name is None or not _enabled(mode_name):
        raise payment_contract.PaymentProviderUnavailable()
    if provider_name == "wechatpay_direct":
        return direct_payment_gateways.WeChatPayGateway(
            app_id=os.environ.get("NOTEAI_WECHATPAY_APP_ID", ""),
            merchant_id=os.environ.get("NOTEAI_WECHATPAY_MERCHANT_ID", ""),
            platform_certificate_serial=os.environ.get(
                "NOTEAI_WECHATPAY_PLATFORM_VERIFIER_ID",
                "",
            ),
            platform_public_key_pem=direct_payment_gateways.decode_pem_b64(
                os.environ.get("NOTEAI_WECHATPAY_PLATFORM_PUBLIC_KEY_B64", ""),
            ),
            api_v3_key=os.environ.get(
                "NOTEAI_WECHATPAY_API_V3_KEY",
                "",
            ).encode("utf-8"),
            callback_url=os.environ.get(
                "NOTEAI_WECHATPAY_CALLBACK_URL",
                "",
            ),
            prod_mode=_enabled("NOTEAI_WECHATPAY_PROD_MODE"),
            transport=_CALLBACK_ONLY_TRANSPORT,
        )
    if provider_name == "alipay_direct":
        return direct_payment_gateways.AlipayGateway(
            app_id=os.environ.get("NOTEAI_ALIPAY_APP_ID", ""),
            seller_id=os.environ.get("NOTEAI_ALIPAY_SELLER_ID", ""),
            alipay_public_key_pem=direct_payment_gateways.decode_pem_b64(
                os.environ.get("NOTEAI_ALIPAY_PUBLIC_KEY_B64", ""),
            ),
            callback_url=os.environ.get("NOTEAI_ALIPAY_CALLBACK_URL", ""),
            prod_mode=_enabled("NOTEAI_ALIPAY_PROD_MODE"),
            transport=_CALLBACK_ONLY_TRANSPORT,
        )
    raise payment_contract.PaymentProviderUnavailable()


def _provider_callback_config_available(provider_name: str) -> bool:
    try:
        if provider_name == "adapay":
            return bool(
                os.environ.get("NOTEAI_ADAPAY_APP_ID", "").strip()
                and os.environ.get("NOTEAI_ADAPAY_PUBLIC_KEY", "").strip()
            )
        _direct_callback_gateway(provider_name)
        return True
    except Exception:
        return False


def _callback_config_available() -> bool:
    providers = _configured_callback_providers()
    return bool(providers) and all(
        _provider_callback_config_available(provider_name)
        for provider_name in providers
    )


def _production_callback_activation_valid() -> bool:
    providers = _configured_callback_providers()
    direct_modes = {
        "wechatpay_direct": "NOTEAI_WECHATPAY_PROD_MODE",
        "alipay_direct": "NOTEAI_ALIPAY_PROD_MODE",
    }
    if any(
        not _enabled(direct_modes[provider_name])
        for provider_name in providers & direct_modes.keys()
    ):
        return False
    if not _production():
        return True
    return bool(providers) and providers <= frozenset(direct_modes)


def _callback_available(provider_name: str) -> bool:
    return (
        _runtime_role_ok()
        and _enabled("NOTEAI_PAYMENT_CALLBACK_ENABLED")
        and provider_name in _configured_callback_providers()
        and _production_callback_activation_valid()
        and _provider_callback_config_available(provider_name)
        and _database_role_ok()
    )


def _database_role_ok() -> bool:
    if not _production():
        return True
    if not db.using_postgres():
        return False
    try:
        row = db.fetchone("SELECT current_user AS role_name")
    except Exception:
        return False
    return bool(row and row["role_name"] == "noteai_payment")


def _ready_payload() -> tuple[dict, int]:
    direct_providers = _configured_callback_providers() & {
        "wechatpay_direct",
        "alipay_direct",
    }
    callback_identities = {
        provider_name: payment_adapter_runtime.callback_identity_sha256(
            provider_name
        )
        for provider_name in sorted(direct_providers)
    }
    checks: dict[str, dict[str, object]] = {
        "runtime_role": {"ok": _runtime_role_ok()},
        "callback_enabled": {
            "ok": _enabled("NOTEAI_PAYMENT_CALLBACK_ENABLED")
        },
        "callback_config": {"ok": _callback_config_available()},
        "production_activation": {
            "ok": _production_callback_activation_valid()
        },
        "callback_identity": {
            "ok": all(callback_identities.values())
        },
    }
    try:
        checks["database"] = db.database_health()
    except Exception as exc:
        checks["database"] = {
            "ok": False,
            "error": type(exc).__name__,
        }
    checks["database_role"] = {"ok": _database_role_ok()}
    ready = all(check.get("ok") is True for check in checks.values())
    return (
        {
            "status": "ready" if ready else "not_ready",
            "service": "noteai-payment",
            "checks": checks,
            "callback_identity_sha256": callback_identities,
        },
        200 if ready else 503,
    )


@app.get("/health/live")
async def health_live():
    return {"status": "ok", "service": "noteai-payment"}


@app.get("/health/ready")
async def health_ready():
    payload, status_code = _ready_payload()
    return JSONResponse(payload, status_code=status_code)


async def _bounded_callback_body(request: Request, *, max_bytes: int) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="PAYMENT_CALLBACK_LENGTH_INVALID",
            ) from None
        if declared_length <= 0 or declared_length > max_bytes:
            raise HTTPException(
                status_code=413,
                detail="PAYMENT_CALLBACK_SIZE_INVALID",
            )
    chunks = bytearray()
    async for chunk in request.stream():
        if not chunk:
            continue
        if len(chunks) + len(chunk) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail="PAYMENT_CALLBACK_SIZE_INVALID",
            )
        chunks.extend(chunk)
    if not chunks:
        raise HTTPException(
            status_code=413,
            detail="PAYMENT_CALLBACK_SIZE_INVALID",
        )
    return bytes(chunks)


@app.post("/payments/adapay/callback")
async def adapay_callback(request: Request):
    """Verify and settle one bounded callback through ``noteai_payment``."""
    if not _callback_available("adapay"):
        raise HTTPException(
            status_code=503,
            detail="PAYMENT_CALLBACK_UNAVAILABLE",
        )
    content_type = request.headers.get("content-type", "").split(";", 1)[0]
    if content_type.strip().lower() != "application/x-www-form-urlencoded":
        raise HTTPException(
            status_code=415,
            detail="PAYMENT_CALLBACK_CONTENT_TYPE_INVALID",
        )
    raw = await _bounded_callback_body(
        request,
        max_bytes=payment_contract.MAX_CALLBACK_DATA_BYTES * 2,
    )
    try:
        pairs = parse_qsl(
            raw.decode("ascii"),
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
            max_num_fields=2,
        )
    except (UnicodeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail="PAYMENT_CALLBACK_FORM_INVALID",
        ) from None
    if (
        len(pairs) != 2
        or {key for key, _value in pairs} != {"data", "sign"}
        or len({key for key, _value in pairs}) != 2
    ):
        raise HTTPException(
            status_code=400,
            detail="PAYMENT_CALLBACK_FORM_INVALID",
        )
    form = dict(pairs)
    try:
        result = payment_contract.process_signed_callback(
            form["data"],
            form["sign"],
            os.environ["NOTEAI_ADAPAY_PUBLIC_KEY"],
            expected_app_id=os.environ["NOTEAI_ADAPAY_APP_ID"],
            expected_prod_mode=_enabled("NOTEAI_ADAPAY_PROD_MODE"),
        )
    except payment_contract.PaymentContractError as exc:
        _LOGGER.warning(
            "payment_callback_rejected code=%s",
            exc.code,
        )
        raise HTTPException(
            status_code=(
                401
                if exc.code == "PAYMENT_CALLBACK_SIGNATURE_INVALID"
                else 400
            ),
            detail=exc.code,
        ) from None
    if result.get("code"):
        _LOGGER.warning(
            "payment_callback_manual code=%s",
            str(result["code"]),
        )
    return {
        "ok": True,
        "accepted": bool(result.get("ok") or result.get("code")),
    }


async def _direct_callback_body(
    request: Request,
    *,
    content_type: str,
) -> bytes:
    actual_type = request.headers.get("content-type", "").split(";", 1)[0]
    if actual_type.strip().lower() != content_type:
        raise HTTPException(
            status_code=415,
            detail="PAYMENT_CALLBACK_CONTENT_TYPE_INVALID",
        )
    return await _bounded_callback_body(
        request,
        max_bytes=payment_contract.MAX_CALLBACK_DATA_BYTES,
    )


def _direct_callback_error(exc: payment_contract.PaymentContractError) -> None:
    _LOGGER.warning("payment_callback_rejected code=%s", exc.code)
    raise HTTPException(
        status_code=(401 if "SIGNATURE" in exc.code else 400),
        detail=exc.code,
    ) from None


def _log_direct_callback_audit(result: object) -> bool:
    """Log one strictly allowlisted digest record without affecting ACKs."""
    try:
        if not isinstance(result, dict):
            return False
        audit = result.get("callback_audit")
        expected = {
            "schema",
            "provider",
            "event_type",
            "callback_identity_sha256",
            "callback_payload_sha256",
            "signature_input_sha256",
            "signature_scheme",
        }
        if not isinstance(audit, dict) or set(audit) not in (
                expected, expected | {"event_semantic_sha256"}):
            return False
        provider = audit.get("provider")
        if (
            audit.get("schema") != "noteai.item31.direct_callback_digest.v1"
            or provider not in _DIRECT_CALLBACK_SCHEMES
            or audit.get("signature_scheme")
            != _DIRECT_CALLBACK_SCHEMES[provider]
            or audit.get("event_type") not in _DIRECT_CALLBACK_EVENT_TYPES
            or any(
                _SHA256_RE.fullmatch(str(audit.get(field) or "")) is None
                for field in (
                    "callback_identity_sha256",
                    "callback_payload_sha256",
                    "signature_input_sha256",
                )
            )
        ):
            return False
        if "event_semantic_sha256" in audit and (
                provider != "wechatpay_direct" or
                _SHA256_RE.fullmatch(str(audit["event_semantic_sha256"] or "")) is None):
            return False
        record = {
            field: audit[field]
            for field in (
                "schema",
                "provider",
                "event_type",
                "callback_identity_sha256",
                "callback_payload_sha256",
                "signature_input_sha256",
                "signature_scheme",
            )
        }
        record["callback_result"] = (
            "SUCCEEDED"
            if result.get("ok") is True and not result.get("code")
            else "NEEDS_MANUAL"
        )
        record["duplicate_delivery"] = result.get("duplicate") is True
        if "event_semantic_sha256" in audit:
            record["event_semantic_sha256"] = audit["event_semantic_sha256"]
        encoded = json.dumps(
            record,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        _LOGGER.info("payment_callback_audit %s", encoded)
        return True
    except Exception:
        return False


def _canary_callback_options(request: Request) -> dict:
    resolver = getattr(request.app.state, "item31_canary_callback_resolver", None)
    if resolver is None:
        return {}
    if not callable(resolver):
        raise HTTPException(status_code=503, detail="PAYMENT_CANARY_SCOPE_INVALID")
    return {"transaction_resolver": resolver}


@app.post("/payments/wechat/callback")
async def wechatpay_callback(request: Request):
    """Authenticate one WeChat Pay API v3 notification and acknowledge it."""
    if not _callback_available("wechatpay_direct"):
        raise HTTPException(
            status_code=503,
            detail="PAYMENT_CALLBACK_UNAVAILABLE",
        )
    options = _canary_callback_options(request)
    with payment_contract.canary_action(options.get("transaction_resolver")):
        raw = await _direct_callback_body(request, content_type="application/json")
        provider_headers: dict[str, str] = {}
        for raw_key, raw_value in request.headers.raw:
            key = raw_key.decode("latin-1").lower()
            if not key.startswith("wechatpay-"):
                continue
            if key in provider_headers:
                raise HTTPException(
                    status_code=400,
                    detail="PAYMENT_CALLBACK_HEADER_INVALID",
                )
            provider_headers[key] = raw_value.decode("latin-1")
        try:
            result = _direct_callback_gateway("wechatpay_direct").process_callback(
                raw,
                provider_headers,
                **options,
            )
        except payment_contract.PaymentContractError as exc:
            _direct_callback_error(exc)
        _log_direct_callback_audit(result)
        if result.get("code"):
            _LOGGER.warning("payment_callback_manual code=%s", str(result["code"]))
        runtime = getattr(request.app.state, "item31_canary_runtime", None)
        if runtime is not None and runtime.reserve_wechat_ack_failure(result):
            _LOGGER.info("item31_wechat_ack_fault_reserved")
            raise HTTPException(status_code=503, detail="PAYMENT_CANARY_ACK_DELIVERY_TEST")
        return {"code": "SUCCESS", "message": "成功"}


@app.post("/payments/alipay/callback", response_class=PlainTextResponse)
async def alipay_callback(request: Request):
    """Authenticate one Alipay RSA2 notification and acknowledge it."""
    if not _callback_available("alipay_direct"):
        raise HTTPException(
            status_code=503,
            detail="PAYMENT_CALLBACK_UNAVAILABLE",
        )
    options = _canary_callback_options(request)
    with payment_contract.canary_action(options.get("transaction_resolver")):
        raw = await _direct_callback_body(
            request,
            content_type="application/x-www-form-urlencoded",
        )
        try:
            result = _direct_callback_gateway("alipay_direct").process_callback(raw, **options)
        except payment_contract.PaymentContractError as exc:
            _direct_callback_error(exc)
        _log_direct_callback_audit(result)
        if result.get("code"):
            _LOGGER.warning("payment_callback_manual code=%s", str(result["code"]))
        return PlainTextResponse("success", media_type="text/plain")
