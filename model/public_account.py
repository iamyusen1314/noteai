"""The explicitly limited public account release, using the existing auth store."""
from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

from starlette.responses import JSONResponse

CONTRACT_VERSION = "account-access-2026-09-12"
PRODUCT_CONTRACT_VERSION = "free-product-2026-09-12"


def product_enabled() -> bool:
    value = os.environ.get("NOTEAI_PUBLIC_PRODUCT", "0")
    if value not in {"0", "1"}:
        raise RuntimeError("invalid public product mode")
    return value == "1"


def contract_version() -> str:
    return PRODUCT_CONTRACT_VERSION if product_enabled() else CONTRACT_VERSION
ALLOWED_ROUTES = frozenset({
    ("GET", "/health/live"),
    ("GET", "/public/status"),
    ("GET", "/legal/contracts"),
    ("GET", "/auth/me"),
    ("POST", "/auth/verification/request"),
    ("POST", "/auth/register/otp"),
    ("POST", "/auth/login/otp"),
    ("POST", "/auth/logout"),
})


def enabled() -> bool:
    value = os.environ.get("NOTEAI_PUBLIC_ACCOUNT_ONLY", "0")
    if value not in {"0", "1"}:
        raise RuntimeError("invalid public account release mode")
    return value == "1" or product_enabled()


def service_status() -> dict:
    from account_security import sms_available
    import public_product
    from sms_delivery import configuration
    try:
        sms_sign_name = configuration().sign_name
    except ValueError:
        sms_sign_name = ""
    return {
        "release": "free_product" if product_enabled() else "website_and_accounts",
        "registration_open": sms_available(),
        "sms_sign_name": sms_sign_name,
        "payment_open": False,
        "ai_open": public_product.available(),
        "media_open": public_product.media_enabled(),
        "free_monthly_credits": 12,
        "fast_chat_credits": 1 if product_enabled() else 0,
        "tracking_open": False,
        "suppliers": public_product.public_services() if product_enabled() else [],
        "contract_version": contract_version(),
        "support_phone": "18988528731",
        "support_email": "ecfine@163.com",
    }


class PublicAccountBoundary:
    """Deny unopened routes before dependencies or business handlers can run."""

    def __init__(self, app):
        self.app = app
        import asyncio
        self.media_slots = asyncio.Semaphore(1)

    async def __call__(self, scope, receive, send):
        if not enabled() or scope["type"] == "lifespan":
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 1008})
        if scope["type"] != "http":
            return
        original_send = send

        async def private_send(message):
            if message["type"] == "http.response.start":
                message = dict(message)
                message["headers"] = [
                    (k, v) for k, v in message.get("headers", [])
                    if k.lower() not in {b"cache-control", b"pragma"}
                ] + [(b"cache-control", b"no-store"), (b"pragma", b"no-cache")]
            await original_send(message)

        send = private_send
        method, path = scope["method"], scope["path"]
        headers = {k.lower(): v for k, v in scope.get("headers", [])}

        async def reject(status, detail):
            await JSONResponse({"detail": detail}, status_code=status)(scope, receive, send)

        import public_product
        if scope.get("raw_path", path.encode()) != path.encode():
            return await reject(404, "本阶段未开放此功能")
        if (method, path) == ("POST", "/payments/wechat/callback") and public_product.wechat_configured(callback=True):
            # Provider callbacks have no browser identity. The fixed local
            # Payment runtime validates raw signature/body/merchant/order.
            return await self.app(scope, receive, send)
        allowed = (method, path) in ALLOWED_ROUTES or (
            product_enabled() and public_product.allowed_route(method, path)
        )
        if not allowed or scope.get("raw_path", path.encode()) != path.encode():
            return await reject(404, "本阶段未开放此功能")
        if method == "POST":
            origins = {v for v in os.environ.get("NOTEAI_PUBLIC_ORIGINS", "").split(",") if v}
            origin = headers.get(b"origin", b"").decode("latin1")
            # Public browser writes must originate from the actual HTTPS website.
            if not origin or origin not in origins or urlsplit(origin).scheme != "https":
                return await reject(403, "请求来源无效")
            content_type = headers.get(b"content-type", b"").split(b";", 1)[0].strip()
            media_upload = public_product.media_enabled() and path in public_product.MEDIA_UPLOAD_ROUTES
            media_json = public_product.media_enabled() and path in public_product.MEDIA_PAYLOAD_ROUTES
            authenticated = None
            if media_upload or media_json:
                from fastapi import HTTPException
                try:
                    authenticated = await public_product.authenticated_user(scope)
                except HTTPException as exc:
                    return await reject(exc.status_code, exc.detail)
            if media_upload:
                if content_type != b"multipart/form-data":
                    return await reject(415, "请上传原始素材文件")
                maximum = (100 if path == "/upload-video" else 10) * 1024 * 1024 + 65536
                consumed = 0
                async def upload_receive():
                    nonlocal consumed
                    message = await receive()
                    consumed += len(message.get("body", b""))
                    if consumed > maximum:
                        raise HTTPException(413, "上传文件超过允许大小")
                    return message
                async with self.media_slots:
                    return await public_product.dispatch(self.app, scope, upload_receive, send, b"", authenticated=authenticated)
            if headers.get(b"content-type", b"").split(b";", 1)[0].strip() != b"application/json":
                return await reject(415, "请求格式必须为JSON")
            if media_json:
                request_id = headers.get(b"x-request-id", b"")
                if path in public_product.PAID_ROUTES and not re.fullmatch(rb"[A-Za-z0-9_-]{8,100}", request_id):
                    return await reject(400, "请提供有效请求标识，避免重复处理")

            async def dispatch_json():
                body = bytearray()
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    body.extend(message.get("body", b""))
                    if len(body) > (128 * 1024 * 1024 if media_json else (65536 if product_enabled() and not path.startswith("/auth/") else 8192)):
                        return await reject(413, "请求过大")
                    if not message.get("more_body", False):
                        break
                delivered = False

                async def bounded_receive():
                    nonlocal delivered
                    if not delivered:
                        delivered = True
                        return {"type": "http.request", "body": bytes(body), "more_body": False}
                    return await receive()

                if product_enabled():
                    return await public_product.dispatch(self.app, scope, bounded_receive, send, bytes(body), authenticated=authenticated)
                return await self.app(scope, bounded_receive, send)

            if media_json:
                # Acquire before accumulating/decoding large image JSON, not
                # only when the eventual provider call reaches admission.
                async with self.media_slots:
                    return await dispatch_json()
            return await dispatch_json()
        if product_enabled():
            return await public_product.dispatch(self.app, scope, receive, send, b"")
        return await self.app(scope, receive, send)


def validate_startup(storage) -> None:
    if os.environ.get("NOTEAI_DEPLOYMENT_STAGE") == "production":
        if not storage.using_postgres():
            raise RuntimeError("public accounts require PostgreSQL in production")
        if os.environ.get("NOTEAI_OTP_MODE", "disabled") not in {"disabled", "aliyun_sms", "aliyun_pnvs"}:
            raise RuntimeError("production public accounts reject mock OTP")
        origins = os.environ.get("NOTEAI_PUBLIC_ORIGINS", "").split(",")
        if not origins or any(v not in {"https://noteaipro.com", "https://www.noteaipro.com"} for v in origins):
            raise RuntimeError("public account origins must match the approved domain")
        state = storage.fetchone("SELECT current_user AS role, current_setting('default_transaction_read_only') AS readonly")
        if state["role"] != "noteai_app" or state["readonly"] != "off":
            raise RuntimeError("public account role or transaction configuration is invalid")
    for table in ("users", "user_sessions", "user_contract_acceptances", "auth_verification_challenges",
                  "auth_sms_budget", "auth_sms_deliveries"):
        storage.fetchone(f"SELECT 1 FROM {table} LIMIT 0")
    if os.environ.get("NOTEAI_OTP_MODE") in {"aliyun_sms", "aliyun_pnvs"}:
        from sms_delivery import configuration
        configuration()
