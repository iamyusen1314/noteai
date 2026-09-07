"""Fail-closed payment adapter bootstrap for an exact runtime role."""

from __future__ import annotations

import hashlib
import json
import os

import adapay_adapter
import direct_payment_gateways
import payment_contract


_TRANSPORT: adapay_adapter.HttpxAdapayTransport | None = None
_DIRECT_TRANSPORTS: dict[str, object] = {}
_DIRECT_PROVIDERS: dict[str, payment_contract.PaymentProvider] = {}
_DIRECT_PROVIDER_NAMES = {"wechatpay_direct", "alipay_direct"}


def _enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _pem_from_environment(name: str) -> str:
    return direct_payment_gateways.decode_pem_b64(os.environ.get(name, ""))


def configure_from_environment(*, required_role: str) -> bool:
    """Construct an adapter without making a provider request.

    Missing, malformed or cross-role configuration returns ``False`` and
    leaves the provider unavailable. Credential values are never returned or
    logged. Rotation requires a process restart; hot replacement is
    deliberately unsupported.
    """
    global _TRANSPORT
    if os.environ.get("NOTEAI_RUNTIME_ROLE", "").strip() != required_role:
        _reset()
        return False
    existing = payment_contract.provider()
    if isinstance(existing, adapay_adapter.AdapayAdapter):
        return True
    transport = adapay_adapter.HttpxAdapayTransport()
    try:
        adapter = adapay_adapter.AdapayAdapter(
            api_key=os.environ.get("NOTEAI_ADAPAY_API_KEY", ""),
            merchant_private_key_pem=os.environ.get(
                "NOTEAI_ADAPAY_MERCHANT_PRIVATE_KEY",
                "",
            ),
            adapay_public_key_pem=os.environ.get(
                "NOTEAI_ADAPAY_PUBLIC_KEY",
                "",
            ),
            app_id=os.environ.get("NOTEAI_ADAPAY_APP_ID", ""),
            prod_mode=_enabled("NOTEAI_ADAPAY_PROD_MODE"),
            pay_channel=os.environ.get("NOTEAI_ADAPAY_PAY_CHANNEL", ""),
            callback_url=os.environ.get(
                "NOTEAI_ADAPAY_CALLBACK_URL",
                "",
            ),
            checkout_hosts=os.environ.get(
                "NOTEAI_ADAPAY_CHECKOUT_HOSTS",
                "",
            ),
            bill_hosts=os.environ.get(
                "NOTEAI_ADAPAY_BILL_HOSTS",
                "",
            ),
            transport=transport,
        )
    except Exception:
        transport.close()
        _reset()
        return False
    payment_contract.configure_provider(adapter)
    _TRANSPORT = transport
    return True


def configured_app_id(provider_name: str) -> str:
    names = {
        "adapay": "NOTEAI_ADAPAY_APP_ID",
        "wechatpay_direct": "NOTEAI_WECHATPAY_APP_ID",
        "alipay_direct": "NOTEAI_ALIPAY_APP_ID",
    }
    env_name = names.get(str(provider_name or ""))
    return os.environ.get(env_name, "").strip() if env_name else ""


def configured_prod_mode(provider_name: str) -> bool:
    names = {
        "adapay": "NOTEAI_ADAPAY_PROD_MODE",
        "wechatpay_direct": "NOTEAI_WECHATPAY_PROD_MODE",
        "alipay_direct": "NOTEAI_ALIPAY_PROD_MODE",
    }
    env_name = names.get(str(provider_name or ""))
    return _enabled(env_name) if env_name else False


def callback_identity_sha256(provider_name: str) -> str:
    """Return one value-free hash for configuration shared by API/callback.

    Merchant request-signing keys and the WeChat API v3 decryption key are
    deliberately excluded because role separation requires them to differ.
    """
    selected = str(provider_name or "").strip()
    try:
        if selected == "wechatpay_direct":
            public_key = _pem_from_environment(
                "NOTEAI_WECHATPAY_PLATFORM_PUBLIC_KEY_B64"
            )
            fields = {
                "app_id": configured_app_id(selected),
                "callback_url": os.environ.get(
                    "NOTEAI_WECHATPAY_CALLBACK_URL", ""
                ).strip(),
                "merchant_id": os.environ.get(
                    "NOTEAI_WECHATPAY_MERCHANT_ID", ""
                ).strip(),
                "platform_public_key_sha256": hashlib.sha256(
                    public_key.encode("ascii")
                ).hexdigest(),
                "platform_verifier_id": os.environ.get(
                    "NOTEAI_WECHATPAY_PLATFORM_VERIFIER_ID", ""
                ).strip(),
                "prod_mode": configured_prod_mode(selected),
                "provider": selected,
            }
        elif selected == "alipay_direct":
            public_key = _pem_from_environment("NOTEAI_ALIPAY_PUBLIC_KEY_B64")
            fields = {
                "alipay_public_key_sha256": hashlib.sha256(
                    public_key.encode("ascii")
                ).hexdigest(),
                "app_id": configured_app_id(selected),
                "callback_url": os.environ.get(
                    "NOTEAI_ALIPAY_CALLBACK_URL", ""
                ).strip(),
                "prod_mode": configured_prod_mode(selected),
                "provider": selected,
                "seller_id": os.environ.get(
                    "NOTEAI_ALIPAY_SELLER_ID", ""
                ).strip(),
            }
        else:
            return ""
    except Exception:
        return ""
    if any(value in {"", False} for value in fields.values()):
        return ""
    canonical = json.dumps(
        fields,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def provider_from_environment(
    provider_name: str,
    *,
    required_role: str,
) -> payment_contract.PaymentProvider | None:
    """Build one selected provider without a request or credential output."""
    selected = str(provider_name or "").strip()
    if os.environ.get("NOTEAI_RUNTIME_ROLE", "").strip() != required_role:
        _reset()
        return None
    if selected == "adapay":
        return (
            payment_contract.provider()
            if configure_from_environment(required_role=required_role)
            else None
        )
    if selected not in _DIRECT_PROVIDER_NAMES:
        return None
    # The current direct transports use the providers' live-only origins.
    # Never construct or reuse them under a mock ledger identity.
    if not configured_prod_mode(selected):
        return None
    existing = _DIRECT_PROVIDERS.get(selected)
    if existing is not None:
        return existing

    transport = None
    try:
        if selected == "wechatpay_direct":
            transport = direct_payment_gateways.HttpxWeChatPayTransport(
                app_id=configured_app_id(selected),
                merchant_id=os.environ.get("NOTEAI_WECHATPAY_MERCHANT_ID", ""),
                merchant_certificate_serial=os.environ.get(
                    "NOTEAI_WECHATPAY_MERCHANT_CERTIFICATE_SERIAL",
                    "",
                ),
                merchant_private_key_pem=_pem_from_environment(
                    "NOTEAI_WECHATPAY_MERCHANT_PRIVATE_KEY_B64",
                ),
                platform_verifier_id=os.environ.get(
                    "NOTEAI_WECHATPAY_PLATFORM_VERIFIER_ID",
                    "",
                ),
                platform_public_key_pem=_pem_from_environment(
                    "NOTEAI_WECHATPAY_PLATFORM_PUBLIC_KEY_B64",
                ),
            )
            gateway = direct_payment_gateways.WeChatPayGateway(
                app_id=configured_app_id(selected),
                merchant_id=os.environ.get("NOTEAI_WECHATPAY_MERCHANT_ID", ""),
                platform_certificate_serial=os.environ.get(
                    "NOTEAI_WECHATPAY_PLATFORM_VERIFIER_ID",
                    "",
                ),
                platform_public_key_pem=_pem_from_environment(
                    "NOTEAI_WECHATPAY_PLATFORM_PUBLIC_KEY_B64",
                ),
                # The API role signs outbound requests but never decrypts
                # callbacks, so it must not receive the API v3 key.
                api_v3_key=None,
                callback_url=os.environ.get(
                    "NOTEAI_WECHATPAY_CALLBACK_URL",
                    "",
                ),
                prod_mode=configured_prod_mode(selected),
                transport=transport,
            )
        else:
            transport = direct_payment_gateways.HttpxAlipayTransport(
                app_id=configured_app_id(selected),
                merchant_private_key_pem=_pem_from_environment(
                    "NOTEAI_ALIPAY_MERCHANT_PRIVATE_KEY_B64",
                ),
                alipay_public_key_pem=_pem_from_environment(
                    "NOTEAI_ALIPAY_PUBLIC_KEY_B64",
                ),
            )
            gateway = direct_payment_gateways.AlipayGateway(
                app_id=configured_app_id(selected),
                seller_id=os.environ.get("NOTEAI_ALIPAY_SELLER_ID", ""),
                alipay_public_key_pem=_pem_from_environment(
                    "NOTEAI_ALIPAY_PUBLIC_KEY_B64",
                ),
                callback_url=os.environ.get(
                    "NOTEAI_ALIPAY_CALLBACK_URL",
                    "",
                ),
                prod_mode=configured_prod_mode(selected),
                transport=transport,
            )
    except Exception:
        if transport is not None and hasattr(transport, "close"):
            transport.close()
        return None
    _DIRECT_TRANSPORTS[selected] = transport
    _DIRECT_PROVIDERS[selected] = gateway
    return gateway


def _reset() -> None:
    global _TRANSPORT
    payment_contract.reset_provider()
    if _TRANSPORT is not None:
        _TRANSPORT.close()
    _TRANSPORT = None
    for transport in tuple(_DIRECT_TRANSPORTS.values()):
        if hasattr(transport, "close"):
            transport.close()
    _DIRECT_TRANSPORTS.clear()
    _DIRECT_PROVIDERS.clear()


reset_for_tests = _reset
close_configured_providers = _reset
