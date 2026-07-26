"""Dedicated Adapay callback runtime.

This app intentionally contains no user, Admin or provider-submission route.
It is safe by default: callback processing is disabled, and a production
request is rejected unless the database session is the exact payment role.
"""

from __future__ import annotations

import logging
import os
from urllib.parse import parse_qsl

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

import db
import payment_contract


_LOGGER = logging.getLogger("noteai.payment")
_TRUE_VALUES = {"1", "true", "yes"}

app = FastAPI(
    title="NoteAI Payment Boundary",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def _enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUE_VALUES


def _production() -> bool:
    return (
        os.environ.get("NOTEAI_DEPLOYMENT_STAGE", "").strip().lower()
        == "production"
    )


def _runtime_role_ok() -> bool:
    return os.environ.get("NOTEAI_RUNTIME_ROLE", "").strip() == "payment"


def _callback_config_available() -> bool:
    return bool(
        os.environ.get("NOTEAI_ADAPAY_APP_ID", "").strip()
        and os.environ.get("NOTEAI_ADAPAY_PUBLIC_KEY", "").strip()
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
    checks: dict[str, dict[str, object]] = {
        "runtime_role": {"ok": _runtime_role_ok()},
        "callback_enabled": {
            "ok": _enabled("NOTEAI_PAYMENT_CALLBACK_ENABLED")
        },
        "callback_config": {"ok": _callback_config_available()},
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


@app.post("/payments/adapay/callback")
async def adapay_callback(request: Request):
    """Verify and settle one bounded callback through ``noteai_payment``."""
    if (
        not _runtime_role_ok()
        or not _enabled("NOTEAI_PAYMENT_CALLBACK_ENABLED")
        or not _callback_config_available()
        or not _database_role_ok()
    ):
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
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="PAYMENT_CALLBACK_LENGTH_INVALID",
            ) from None
        if (
            declared_length <= 0
            or declared_length > payment_contract.MAX_CALLBACK_DATA_BYTES * 2
        ):
            raise HTTPException(
                status_code=413,
                detail="PAYMENT_CALLBACK_SIZE_INVALID",
            )
    raw = await request.body()
    if (
        not raw
        or len(raw) > payment_contract.MAX_CALLBACK_DATA_BYTES * 2
    ):
        raise HTTPException(
            status_code=413,
            detail="PAYMENT_CALLBACK_SIZE_INVALID",
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
