"""Fail-closed Adapay adapter bootstrap for an exact runtime role."""

from __future__ import annotations

import os

import adapay_adapter
import payment_contract


_TRANSPORT: adapay_adapter.HttpxAdapayTransport | None = None


def _enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def configure_from_environment(*, required_role: str) -> bool:
    """Construct an adapter without making a provider request.

    Missing, malformed or cross-role configuration returns ``False`` and
    leaves the provider unavailable. Credential values are never returned or
    logged. Rotation requires a process restart; hot replacement is
    deliberately unsupported.
    """
    global _TRANSPORT
    if os.environ.get("NOTEAI_RUNTIME_ROLE", "").strip() != required_role:
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
        return False
    payment_contract.configure_provider(adapter)
    _TRANSPORT = transport
    return True


def reset_for_tests() -> None:
    global _TRANSPORT
    payment_contract.reset_provider()
    if _TRANSPORT is not None:
        _TRANSPORT.close()
    _TRANSPORT = None
