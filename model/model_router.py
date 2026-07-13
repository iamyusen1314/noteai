"""
model_router.py — NoteAI Pro 统一模型路由层
任务类型 → 模型选择 → fallback 链 → retry → 日志

任务路由表：
  diagnosis   → Claude Haiku 4.5  (fallback: Kimi K2.6)
  content_gen → Claude Haiku 4.5  (fallback: Kimi K2.6)
  arbitrate   → Claude Sonnet 4.6 (fallback: Claude Haiku 4.5)
  chat        → Claude Sonnet 4.6 (fallback: Claude Haiku 4.5)
  semantic    → Claude Haiku 4.5  (fallback: Kimi K2.6)
  vision      → Kimi Vision only  (不经此路由)
"""

import asyncio
import concurrent.futures
import hashlib
import inspect
import ipaddress
import json
import math
import os
import re
import secrets
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Protocol
from urllib.parse import urlsplit

import anthropic
import httpcore
import httpx
import claude_gateway_protocol as _cgp

# ── 模型常量 ──────────────────────────────────────────────────────
CLAUDE_SONNET  = "claude-sonnet-4-6"
CLAUDE_HAIKU   = "claude-haiku-4-5-20251001"
KIMI_TEXT      = "kimi-k2.6"

KIMI_API_URL   = "https://api.moonshot.cn/v1/chat/completions"
KIMI_TIMEOUT   = httpx.Timeout(connect=10.0, read=180.0, write=20.0, pool=10.0)
KIMI_TIMEOUT_Q = httpx.Timeout(connect=10.0, read=40.0,  write=10.0, pool=10.0)

CLAUDE_CONCURRENCY = max(1, int(os.environ.get("NOTEAI_CLAUDE_CONCURRENCY", "2")))
KIMI_TEXT_CONCURRENCY = max(1, int(os.environ.get("NOTEAI_KIMI_TEXT_CONCURRENCY", "2")))
MODEL_RETRY_ATTEMPTS = max(1, int(os.environ.get("NOTEAI_MODEL_RETRY_ATTEMPTS", "3")))
MODEL_RETRY_BASE_DELAY = float(os.environ.get("NOTEAI_MODEL_RETRY_BASE_DELAY", "1.2"))
CLAUDE_FAST_TIMEOUT_SECONDS = float(os.environ.get("NOTEAI_CLAUDE_FAST_TIMEOUT_SECONDS", "55"))
CLAUDE_THINK_TIMEOUT_SECONDS = float(os.environ.get("NOTEAI_CLAUDE_THINK_TIMEOUT_SECONDS", "180"))
CLAUDE_GATEWAY_HTTP_TIMEOUT_SECONDS = 190.0
CLAUDE_GATEWAY_BUSINESS_TIMEOUT_SECONDS = 210.0
CLAUDE_GATEWAY_PROVIDER_DEADLINE_SECONDS = 180.0
CLAUDE_GATEWAY_HTTPCORE_VERSION = "1.0.9"

_SEMAPHORES: dict[tuple[str, int], asyncio.Semaphore] = {}


class _BoundedGatewayDNSExecutor(concurrent.futures.ThreadPoolExecutor):
    def __init__(self, *, max_workers: int, max_pending: int):
        super().__init__(
            max_workers=max_workers,
            thread_name_prefix="claude-gateway-dns",
        )
        self._submission_slots = threading.BoundedSemaphore(
            max_workers + max_pending
        )

    def submit(self, fn, /, *args, **kwargs):
        if not self._submission_slots.acquire(blocking=False):
            raise RuntimeError("gateway DNS executor saturated")
        try:
            future = super().submit(fn, *args, **kwargs)
        except BaseException:
            self._submission_slots.release()
            raise
        future.add_done_callback(lambda _future: self._submission_slots.release())
        return future


_GATEWAY_DNS_EXECUTOR = _BoundedGatewayDNSExecutor(
    max_workers=2,
    max_pending=2,
)

# ── 任务路由表 ─────────────────────────────────────────────────────
TASK_ROUTING: dict[str, dict] = {
    "diagnosis":   {"primary": CLAUDE_HAIKU,  "fallback": [KIMI_TEXT]},
    "content_gen": {"primary": CLAUDE_HAIKU,  "fallback": [KIMI_TEXT]},
    "arbitrate":   {"primary": CLAUDE_SONNET, "fallback": [CLAUDE_HAIKU]},
    "chat":        {"primary": CLAUDE_SONNET, "fallback": [CLAUDE_HAIKU]},
    "semantic":    {"primary": CLAUDE_HAIKU,  "fallback": [KIMI_TEXT]},
}


# ── Claude 异步客户端（单例） ─────────────────────────────────────
def _get_semaphore(name: str, limit: int) -> asyncio.Semaphore:
    loop_id = id(asyncio.get_running_loop())
    key = (name, loop_id)
    sem = _SEMAPHORES.get(key)
    if sem is None:
        sem = asyncio.Semaphore(limit)
        _SEMAPHORES[key] = sem
    return sem


def _status_code(exc: Exception) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    return response_status if isinstance(response_status, int) else None


def _is_retryable(exc: Exception) -> bool:
    status = _status_code(exc)
    if status in {408, 409, 425, 429, 500, 502, 503, 504}:
        return True
    if status in {400, 401, 403, 404}:
        return False
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, asyncio.TimeoutError)):
        return True
    msg = str(exc).lower()
    if "empty response" in msg or "rate limit" in msg or "overloaded" in msg:
        return True
    if "api_key" in msg or "authentication" in msg or "unauthorized" in msg:
        return False
    return False


def _usage_attr(usage, name: str) -> int:
    if not usage:
        return 0
    if isinstance(usage, dict):
        return int(usage.get(name, 0) or 0)
    return int(getattr(usage, name, 0) or 0)


def _usage_value(usage, name: str):
    if not usage:
        return None
    if isinstance(usage, dict):
        return usage.get(name)
    return getattr(usage, name, None)


def _extract_kimi_stream_usage(chunk) -> dict | None:
    """Read Kimi terminal usage from either supported streaming shape."""
    if not isinstance(chunk, dict):
        return None
    top_level = chunk.get("usage")
    if isinstance(top_level, dict) and top_level:
        return top_level
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return top_level if isinstance(top_level, dict) else None
    nested = choices[0].get("usage")
    if isinstance(nested, dict):
        return nested
    return top_level if isinstance(top_level, dict) else None


def _record_usage(provider: str, model: str, tokens_in: int = 0, tokens_out: int = 0, **kwargs) -> None:
    try:
        import billing

        billing.record_model_usage(
            provider, model, tokens_in=tokens_in, tokens_out=tokens_out, **kwargs
        )
    except Exception:
        pass


def _record_claude_usage(model: str, usage) -> None:
    if not usage:
        _record_usage("claude", model, usage_status="usage_missing")
        return
    cache_write = _usage_attr(usage, "cache_creation_input_tokens")
    cache_details = _usage_value(usage, "cache_creation")
    write_5m = _usage_attr(cache_details, "ephemeral_5m_input_tokens")
    write_1h = _usage_attr(cache_details, "ephemeral_1h_input_tokens")
    write_unknown = max(0, cache_write - write_5m - write_1h)
    usage_status = "cache_ttl_unknown" if write_unknown else "complete"
    _record_usage(
        "claude", model,
        _usage_attr(usage, "input_tokens"),
        _usage_attr(usage, "output_tokens"),
        cache_read_tokens=_usage_attr(usage, "cache_read_input_tokens"),
        cache_write_tokens=cache_write,
        cache_write_5m_tokens=write_5m,
        cache_write_1h_tokens=write_1h,
        cache_write_unknown_ttl_tokens=write_unknown,
        usage_status=usage_status,
    )


def _record_kimi_usage(model: str, usage: dict | None) -> None:
    if not usage:
        _record_usage("kimi", model, usage_status="usage_missing")
        return
    prompt_tokens = _usage_attr(usage, "prompt_tokens")
    tokens_out = _usage_attr(usage, "completion_tokens")
    if model == KIMI_TEXT:
        cached_marker = object()
        cached = usage.get("cached_tokens", cached_marker) if isinstance(usage, dict) else cached_marker
        if cached is cached_marker:
            details = _usage_value(usage, "prompt_tokens_details")
            if isinstance(details, dict) and "cached_tokens" in details:
                cached = details.get("cached_tokens")
            elif details is not None and hasattr(details, "cached_tokens"):
                cached = getattr(details, "cached_tokens")
        if cached is cached_marker:
            _record_usage(
                "kimi", model, tokens_out=tokens_out,
                unclassified_input_tokens=prompt_tokens,
                usage_status="cache_usage_missing",
            )
            return
        cache_read = max(0, int(cached or 0))
        if cache_read > prompt_tokens:
            _record_usage(
                "kimi", model, tokens_out=tokens_out,
                unclassified_input_tokens=prompt_tokens,
                usage_status="usage_incomplete",
            )
            return
        _record_usage(
            "kimi", model, prompt_tokens - cache_read, tokens_out,
            cache_read_tokens=cache_read,
        )
        return
    # The confirmed Moonshot vision model has no documented cache tier in the
    # adopted price card; do not invent or infer one from absent fields.
    _record_usage("kimi", model, prompt_tokens, tokens_out)


# ── Claude transport boundary ────────────────────────────────
@dataclass(frozen=True)
class ClaudeMessageRequest:
    model: str
    max_tokens: int
    messages: tuple[dict, ...]
    operation_id: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    system: str | None = None
    temperature: float | None = None
    thinking_budget: int | None = None


@dataclass(frozen=True)
class ClaudeMessageResult:
    text_blocks: tuple[str, ...]
    usage: dict[str, Any] | None = None


@dataclass(frozen=True)
class ClaudeStreamEvent:
    type: str
    text: str = ""
    usage: dict[str, Any] | None = None


class ClaudeTransport(Protocol):
    """SDK-independent Claude request/response/stream transport contract."""

    async def create_message(self, request: ClaudeMessageRequest) -> ClaudeMessageResult:
        ...

    def create_message_sync(self, request: ClaudeMessageRequest) -> ClaudeMessageResult:
        ...

    def stream_message(
        self,
        request: ClaudeMessageRequest,
    ) -> AsyncGenerator[ClaudeStreamEvent, None]:
        ...


def _local_claude_kwargs(request: ClaudeMessageRequest) -> dict:
    kwargs: dict = {
        "model": request.model,
        "max_tokens": request.max_tokens,
        "messages": list(request.messages),
    }
    if request.system is not None:
        kwargs["system"] = request.system
    if request.thinking_budget is not None:
        kwargs["thinking"] = {
            "type": "enabled",
            "budget_tokens": request.thinking_budget,
        }
    elif request.temperature is not None:
        kwargs["temperature"] = request.temperature
    return kwargs


def _normalized_claude_usage(usage) -> dict | None:
    if not usage:
        return None
    normalized = {
        "input_tokens": _usage_attr(usage, "input_tokens"),
        "output_tokens": _usage_attr(usage, "output_tokens"),
        "cache_read_input_tokens": _usage_attr(usage, "cache_read_input_tokens"),
        "cache_creation_input_tokens": _usage_attr(usage, "cache_creation_input_tokens"),
    }
    cache_creation = _usage_value(usage, "cache_creation")
    if cache_creation is not None:
        normalized["cache_creation"] = {
            "ephemeral_5m_input_tokens": _usage_attr(
                cache_creation, "ephemeral_5m_input_tokens"
            ),
            "ephemeral_1h_input_tokens": _usage_attr(
                cache_creation, "ephemeral_1h_input_tokens"
            ),
        }
    return normalized


class LocalAnthropicTransport:
    """Default transport preserving the existing direct Anthropic SDK behavior."""

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key
        self._async_client: anthropic.AsyncAnthropic | None = None
        self._sync_client: anthropic.Anthropic | None = None

    def _resolved_api_key(self) -> str:
        if self._api_key is not None:
            return self._api_key
        return os.environ.get("ANTHROPIC_API_KEY", "")

    def _get_async_client(self) -> anthropic.AsyncAnthropic:
        if self._async_client is None:
            self._async_client = anthropic.AsyncAnthropic(api_key=self._resolved_api_key())
        return self._async_client

    def _get_sync_client(self) -> anthropic.Anthropic:
        if self._sync_client is None:
            self._sync_client = anthropic.Anthropic(api_key=self._resolved_api_key())
        return self._sync_client

    @staticmethod
    def _result(response) -> ClaudeMessageResult:
        return ClaudeMessageResult(
            tuple(
                block.text
                for block in response.content
                if getattr(block, "type", None) == "text"
            ),
            _normalized_claude_usage(getattr(response, "usage", None)),
        )

    async def create_message(self, request: ClaudeMessageRequest) -> ClaudeMessageResult:
        try:
            client = self._get_async_client()
        except Exception:
            raise ClaudeGatewayError(
                "CLAUDE_LOCAL_NOT_CONFIGURED",
                503,
                fallback_safe=True,
            ) from None
        try:
            response = await client.messages.create(**_local_claude_kwargs(request))
            return self._result(response)
        except asyncio.CancelledError:
            raise ClaudeRequestCancelled(usage_audit_required=True) from None
        except ClaudeGatewayError:
            raise
        except Exception:
            raise ClaudeGatewayError(
                "CLAUDE_PROVIDER_ERROR",
                502,
                usage_audit_required=True,
            ) from None

    def create_message_sync(self, request: ClaudeMessageRequest) -> ClaudeMessageResult:
        try:
            client = self._get_sync_client()
        except Exception:
            raise ClaudeGatewayError(
                "CLAUDE_LOCAL_NOT_CONFIGURED",
                503,
                fallback_safe=True,
            ) from None
        try:
            response = client.messages.create(**_local_claude_kwargs(request))
            return self._result(response)
        except ClaudeGatewayError:
            raise
        except Exception:
            raise ClaudeGatewayError(
                "CLAUDE_PROVIDER_ERROR",
                502,
                usage_audit_required=True,
            ) from None

    async def stream_message(
        self,
        request: ClaudeMessageRequest,
    ) -> AsyncGenerator[ClaudeStreamEvent, None]:
        try:
            client = self._get_async_client()
        except Exception:
            raise ClaudeGatewayError(
                "CLAUDE_LOCAL_NOT_CONFIGURED",
                503,
                fallback_safe=True,
            ) from None
        try:
            async with client.messages.stream(
                **_local_claude_kwargs(request)
            ) as stream_ctx:
                async for event in stream_ctx:
                    if event.type != "content_block_delta":
                        continue
                    delta = event.delta
                    if delta.type == "thinking_delta":
                        yield ClaudeStreamEvent("thinking", text=delta.thinking)
                    elif delta.type == "text_delta":
                        yield ClaudeStreamEvent("content", text=delta.text)
                final_message = stream_ctx.get_final_message()
                if inspect.isawaitable(final_message):
                    final_message = await final_message
                yield ClaudeStreamEvent(
                    "usage",
                    usage=_normalized_claude_usage(getattr(final_message, "usage", None)),
                )
        except asyncio.CancelledError:
            raise ClaudeRequestCancelled(usage_audit_required=True) from None
        except ClaudeGatewayError:
            raise
        except Exception:
            raise ClaudeGatewayError(
                "CLAUDE_PROVIDER_ERROR",
                502,
                usage_audit_required=True,
            ) from None


# These responses are emitted before the Gateway invokes Anthropic. AUTH_REPLAY
# is intentionally absent because the earlier nonce claim may have reached it.
_PRE_PROVIDER_GATEWAY_CODES = frozenset({
    "AUTH_EXPIRED",
    "AUTH_HEADER_INVALID",
    "AUTH_CONTEXT_INVALID",
    "AUTH_INVALID",
    "AUTH_NONCE_INVALID",
    "AUTH_TIMESTAMP_INVALID",
    "CONCURRENCY_LIMIT",
    "CONTROL_PLANE_UNAVAILABLE",
    "CONTENT_LENGTH_INVALID",
    "CONTENT_LIMIT_EXCEEDED",
    "CONTENT_TYPE_UNSUPPORTED",
    "FORBIDDEN_HEADER",
    "GATEWAY_NOT_CONFIGURED",
    "GATEWAY_URL_INVALID",
    "IMAGES_DISABLED",
    "INVALID_JSON",
    "INVALID_REQUEST",
    "MODEL_NOT_ALLOWED",
    "PATH_INVALID",
    "PAYLOAD_TOO_LARGE",
    "PROTOCOL_VERSION_UNSUPPORTED",
    "QUERY_NOT_ALLOWED",
    "RATE_LIMIT",
    "REMOTE_IMAGE_NOT_ALLOWED",
    "REPLAY_STORE_INSTANCE_SCOPE",
    "TOKEN_LIMIT_EXCEEDED",
    "TRANSPORT_MODE_UNSUPPORTED",
})


class ClaudeRequestCancelled(asyncio.CancelledError):
    """Cancellation carrying only cost-audit state, never provider details."""

    def __init__(self, *, usage_audit_required: bool):
        self.usage_audit_required = bool(usage_audit_required)
        super().__init__()


class ClaudeGatewayError(RuntimeError):
    def __init__(
        self,
        code: str,
        status_code: int | None = None,
        *,
        usage_audit_required: bool = False,
        fallback_safe: bool = False,
    ):
        safe_code = code if re.fullmatch(r"[A-Z0-9_]{1,64}", str(code or "")) else "GATEWAY_ERROR"
        self.code = safe_code
        self.status_code = status_code
        self.usage_audit_required = bool(usage_audit_required)
        self.fallback_safe = bool(fallback_safe)
        super().__init__(f"claude gateway error: {safe_code}")


def _safe_failure_code(exc: BaseException) -> str:
    if isinstance(exc, ClaudeGatewayError):
        return exc.code
    if isinstance(exc, (asyncio.CancelledError, GeneratorExit)):
        return "CLAUDE_CANCELLED"
    return "CLAUDE_REQUEST_FAILED"


def _fixed_claude_error(exc: BaseException, code: str = "CLAUDE_OUTCOME_UNKNOWN") -> ClaudeGatewayError:
    if isinstance(exc, ClaudeGatewayError):
        return exc
    status_code = 504 if isinstance(exc, asyncio.TimeoutError) else 502
    return ClaudeGatewayError(code, status_code)


async def _close_async_iterator(iterator: Any) -> None:
    close = getattr(iterator, "aclose", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await result


_GATEWAY_AUTHORITY_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_GATEWAY_EPOCH_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _valid_gateway_authority(value: str | None) -> bool:
    authority = str(value or "")
    if (
        not authority
        or not authority.isascii()
        or authority != authority.lower()
        or authority.endswith(".")
        or authority.endswith(".local")
        or "%" in authority
        or ":" in authority
        or not _GATEWAY_AUTHORITY_PATTERN.fullmatch(authority)
    ):
        return False
    try:
        ipaddress.ip_address(authority)
        return False
    except ValueError:
        return True


def _valid_gateway_epoch(value: str | None) -> bool:
    raw = str(value or "")
    return bool(raw.isascii() and _GATEWAY_EPOCH_PATTERN.fullmatch(raw))


def _gateway_timeout_values() -> tuple[float, float, float]:
    names_defaults = (
        (
            "NOTEAI_CLAUDE_GATEWAY_PROVIDER_DEADLINE_SECONDS",
            CLAUDE_GATEWAY_PROVIDER_DEADLINE_SECONDS,
        ),
        (
            "NOTEAI_CLAUDE_GATEWAY_HTTP_TIMEOUT_SECONDS",
            CLAUDE_GATEWAY_HTTP_TIMEOUT_SECONDS,
        ),
        (
            "NOTEAI_CLAUDE_GATEWAY_BUSINESS_TIMEOUT_SECONDS",
            CLAUDE_GATEWAY_BUSINESS_TIMEOUT_SECONDS,
        ),
    )
    values = []
    for name, default in names_defaults:
        try:
            value = float(os.environ.get(name, str(default)) or default)
        except (TypeError, ValueError):
            value = float("nan")
        values.append(value)
    return tuple(values)


def _valid_gateway_timeout_contract() -> bool:
    provider, gateway_http, business = _gateway_timeout_values()
    return bool(
        all(math.isfinite(value) for value in (provider, gateway_http, business))
        and provider == CLAUDE_GATEWAY_PROVIDER_DEADLINE_SECONDS
        and gateway_http == CLAUDE_GATEWAY_HTTP_TIMEOUT_SECONDS
        and business == CLAUDE_GATEWAY_BUSINESS_TIMEOUT_SECONDS
        and provider < gateway_http < business
    )


def _gateway_readiness_timeout_seconds() -> float:
    try:
        value = float(
            os.environ.get("NOTEAI_CLAUDE_GATEWAY_READINESS_TIMEOUT_SECONDS", "3") or 3
        )
    except (TypeError, ValueError):
        value = 3.0
    return max(0.25, min(10.0, value))


def _valid_gateway_base_url(
    value: str | None,
    expected_authority: str | None = None,
) -> bool:
    raw = str(value or "")
    if not raw.isascii() or raw != raw.strip() or "%" in raw:
        return False
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except (TypeError, ValueError):
        return False
    authority = expected_authority if expected_authority is not None else parsed.hostname
    if not _valid_gateway_authority(authority):
        return False
    return bool(
        raw == f"https://{authority}"
        and parsed.scheme == "https"
        and parsed.netloc == authority
        and parsed.hostname == authority
        and parsed.username is None
        and parsed.password is None
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
        and port is None
    )


def _resolve_global_gateway_addresses(authority: str) -> tuple[str, ...]:
    if not _valid_gateway_authority(authority):
        raise ClaudeGatewayError("GATEWAY_AUTHORITY_INVALID", 503, fallback_safe=True)
    try:
        answers = socket.getaddrinfo(
            authority,
            443,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except OSError:
        raise ClaudeGatewayError(
            "GATEWAY_DNS_RESOLUTION_FAILED", 503, fallback_safe=True,
        ) from None
    addresses: list[str] = []
    for _family, _type, _proto, _canonname, sockaddr in answers:
        address = str(sockaddr[0])
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            raise ClaudeGatewayError(
                "GATEWAY_DNS_RESOLUTION_FAILED", 503, fallback_safe=True,
            ) from None
        if not _strict_global_unicast(parsed):
            raise ClaudeGatewayError(
                "GATEWAY_DNS_NOT_GLOBAL", 503, fallback_safe=True,
            )
        normalized = parsed.compressed
        if normalized not in addresses:
            addresses.append(normalized)
    if not addresses:
        raise ClaudeGatewayError(
            "GATEWAY_DNS_RESOLUTION_FAILED", 503, fallback_safe=True,
        )
    return tuple(addresses)


def _strict_global_unicast(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if (
        not address.is_global
        or address.is_multicast
        or address.is_unspecified
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_private
    ):
        return False
    if isinstance(address, ipaddress.IPv6Address):
        if (
            address.is_site_local
            or address.ipv4_mapped is not None
            or address.sixtofour is not None
            or address.teredo is not None
            or address in ipaddress.ip_network("64:ff9b::/96")
            or address in ipaddress.ip_network("64:ff9b:1::/48")
        ):
            return False
    return True


class _PinnedSyncBackend:
    def __init__(self, authority: str, address: str, backend: Any):
        self.authority = authority
        self.address = address
        self.backend = backend

    def connect_tcp(
        self, host, port, timeout=None, local_address=None, socket_options=None,
    ):
        if host != self.authority or port != 443:
            raise OSError("gateway connection target rejected")
        return self.backend.connect_tcp(
            self.address,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    def connect_unix_socket(self, *args, **kwargs):
        raise OSError("gateway unix socket rejected")


class _PinnedAsyncBackend:
    def __init__(self, authority: str, address: str, backend: Any):
        self.authority = authority
        self.address = address
        self.backend = backend

    async def connect_tcp(
        self, host, port, timeout=None, local_address=None, socket_options=None,
    ):
        if host != self.authority or port != 443:
            raise OSError("gateway connection target rejected")
        return await self.backend.connect_tcp(
            self.address,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(self, *args, **kwargs):
        raise OSError("gateway unix socket rejected")

    async def sleep(self, seconds: float) -> None:
        await self.backend.sleep(seconds)


def _pin_httpx_transport_backend(
    transport: Any,
    authority: str,
    address: str,
    *,
    async_mode: bool,
):
    try:
        if getattr(httpcore, "__version__", "") != CLAUDE_GATEWAY_HTTPCORE_VERSION:
            raise ValueError("unsupported httpcore")
        pool = getattr(transport, "_pool", None)
        backend = getattr(pool, "_network_backend", None)
        if pool is None or backend is None or not callable(getattr(backend, "connect_tcp", None)):
            raise ValueError("unsupported transport")
        pinned = (
            _PinnedAsyncBackend(authority, address, backend)
            if async_mode
            else _PinnedSyncBackend(authority, address, backend)
        )
        pool._network_backend = pinned
        if pool._network_backend is not pinned:
            raise ValueError("transport pin failed")
        return transport
    except ClaudeGatewayError:
        raise
    except Exception:
        raise ClaudeGatewayError(
            "GATEWAY_TRANSPORT_INCOMPATIBLE", 503, fallback_safe=True,
        ) from None


def _safe_gateway_http_error(
    exc: BaseException,
    *,
    usage_audit_required: bool = False,
) -> ClaudeGatewayError:
    if isinstance(exc, httpx.TimeoutException):
        return ClaudeGatewayError(
            "GATEWAY_TIMEOUT",
            504,
            usage_audit_required=usage_audit_required,
        )
    if isinstance(exc, httpx.NetworkError):
        return ClaudeGatewayError(
            "GATEWAY_NETWORK_ERROR",
            503,
            usage_audit_required=usage_audit_required,
        )
    if isinstance(exc, httpx.ProtocolError):
        return ClaudeGatewayError(
            "GATEWAY_PROTOCOL_ERROR",
            502,
            usage_audit_required=usage_audit_required,
        )
    return ClaudeGatewayError(
        "GATEWAY_HTTP_ERROR",
        502,
        usage_audit_required=usage_audit_required,
    )


class GatewayClaudeTransport:
    """Signed HTTP transport with no transport-layer automatic retries."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        authority: str | None = None,
        config_epoch: str | None = None,
        key_epoch: str | None = None,
        key_id: str | None = None,
        secret: str | None = None,
        timeout_seconds: float | None = None,
        http_transport: Any = None,
    ):
        self.base_url = (
            base_url if base_url is not None
            else os.environ.get("NOTEAI_CLAUDE_GATEWAY_URL", "")
        )
        configured_authority = os.environ.get("NOTEAI_CLAUDE_GATEWAY_AUTHORITY", "")
        if authority is not None:
            self.authority = authority
        elif configured_authority:
            self.authority = configured_authority
        elif base_url is not None:
            try:
                self.authority = urlsplit(base_url).hostname or ""
            except (TypeError, ValueError):
                self.authority = ""
        else:
            self.authority = ""
        self.config_epoch = (
            config_epoch if config_epoch is not None
            else os.environ.get("NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH", "")
        )
        self.key_epoch = (
            key_epoch if key_epoch is not None
            else os.environ.get("NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH", "")
        )
        self.key_id = (
            key_id if key_id is not None
            else os.environ.get("NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID", "")
        ).strip()
        self.secret = (
            secret if secret is not None
            else os.environ.get("NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET", "")
        )
        if timeout_seconds is None:
            try:
                timeout_seconds = float(
                    os.environ.get(
                        "NOTEAI_CLAUDE_GATEWAY_HTTP_TIMEOUT_SECONDS",
                        str(CLAUDE_GATEWAY_HTTP_TIMEOUT_SECONDS),
                    ) or CLAUDE_GATEWAY_HTTP_TIMEOUT_SECONDS
                )
            except (TypeError, ValueError):
                timeout_seconds = CLAUDE_GATEWAY_HTTP_TIMEOUT_SECONDS
        timeout_seconds = max(1.0, float(timeout_seconds))
        self.timeout = httpx.Timeout(
            connect=min(10.0, timeout_seconds),
            read=timeout_seconds,
            write=min(30.0, timeout_seconds),
            pool=min(10.0, timeout_seconds),
        )
        self.http_transport = http_transport

    def _require_config(self) -> None:
        if (
            not self.base_url
            or not self.authority
            or not self.config_epoch
            or not self.key_epoch
            or not self.key_id
            or not self.secret
        ):
            raise ClaudeGatewayError("GATEWAY_NOT_CONFIGURED", 503, fallback_safe=True)
        if not _valid_gateway_base_url(self.base_url, self.authority):
            raise ClaudeGatewayError("GATEWAY_URL_INVALID", 503, fallback_safe=True)
        if not _valid_gateway_epoch(self.config_epoch) or not _valid_gateway_epoch(self.key_epoch):
            raise ClaudeGatewayError("GATEWAY_EPOCH_INVALID", 503, fallback_safe=True)
        if not _valid_gateway_timeout_contract():
            raise ClaudeGatewayError(
                "GATEWAY_TIMEOUT_CONFIG_INVALID", 503, fallback_safe=True,
            )

    def _sync_http_transport(self):
        if self.http_transport is not None:
            return self.http_transport
        address = _resolve_global_gateway_addresses(self.authority)[0]
        transport = httpx.HTTPTransport(verify=True, trust_env=False, retries=0)
        return _pin_httpx_transport_backend(
            transport,
            self.authority,
            address,
            async_mode=False,
        )

    async def _async_http_transport(self):
        if self.http_transport is not None:
            return self.http_transport
        try:
            dns_future = asyncio.get_running_loop().run_in_executor(
                _GATEWAY_DNS_EXECUTOR,
                _resolve_global_gateway_addresses,
                self.authority,
            )
            addresses = await asyncio.shield(dns_future)
        except asyncio.CancelledError:
            raise
        except ClaudeGatewayError:
            raise
        except Exception:
            raise ClaudeGatewayError(
                "GATEWAY_DNS_RESOLUTION_FAILED", 503, fallback_safe=True,
            ) from None
        transport = httpx.AsyncHTTPTransport(verify=True, trust_env=False, retries=0)
        return _pin_httpx_transport_backend(
            transport,
            self.authority,
            addresses[0],
            async_mode=True,
        )

    @staticmethod
    def _body(request: ClaudeMessageRequest) -> bytes:
        if not _cgp.valid_operation_id(request.operation_id):
            raise ClaudeGatewayError("INVALID_REQUEST", 400, fallback_safe=True)
        return json.dumps({
            "operation_id": request.operation_id,
            "model": request.model,
            "max_tokens": request.max_tokens,
            "system": request.system,
            "messages": list(request.messages),
            "temperature": request.temperature,
            "thinking_budget": request.thinking_budget,
        }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def _headers(self, path: str, body: bytes) -> dict[str, str]:
        return _cgp.auth_headers(
            key_id=self.key_id,
            secret=self.secret,
            method="POST",
            path=path,
            authority=self.authority,
            config_epoch=self.config_epoch,
            key_epoch=self.key_epoch,
            body=body,
        )

    @staticmethod
    def _error_from_payload(payload: Any, status_code: int | None) -> ClaudeGatewayError:
        code = "GATEWAY_PROTOCOL_ERROR"
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict) and isinstance(error.get("code"), str):
                code = error["code"]
        fallback_safe = code in _PRE_PROVIDER_GATEWAY_CODES
        return ClaudeGatewayError(
            code,
            status_code,
            usage_audit_required=not fallback_safe,
            fallback_safe=fallback_safe,
        )

    @staticmethod
    def _require_response_media_type(response: httpx.Response, expected: str) -> None:
        values = response.headers.get_list("content-type")
        if len(values) != 1:
            raise ClaudeGatewayError("GATEWAY_PROTOCOL_ERROR", response.status_code)
        media_type = values[0].split(";", 1)[0].strip().lower()
        if media_type != expected:
            raise ClaudeGatewayError("GATEWAY_PROTOCOL_ERROR", response.status_code)

    @classmethod
    def _decode_result(cls, response: httpx.Response) -> ClaudeMessageResult:
        cls._require_response_media_type(response, "application/json")
        try:
            payload = response.json()
        except Exception as exc:
            raise ClaudeGatewayError("GATEWAY_PROTOCOL_ERROR", response.status_code) from exc
        if response.status_code != 200:
            raise cls._error_from_payload(payload, response.status_code)
        if not isinstance(payload, dict) or payload.get("protocol_version") != _cgp.PROTOCOL_VERSION:
            raise ClaudeGatewayError("GATEWAY_PROTOCOL_ERROR", response.status_code)
        blocks = payload.get("text_blocks")
        usage = payload.get("usage")
        if (
            not isinstance(blocks, list)
            or not all(isinstance(block, str) for block in blocks)
            or not _cgp.valid_usage_envelope(usage)
        ):
            raise ClaudeGatewayError("GATEWAY_PROTOCOL_ERROR", response.status_code)
        return ClaudeMessageResult(tuple(blocks), usage)

    async def create_message(self, request: ClaudeMessageRequest) -> ClaudeMessageResult:
        self._require_config()
        body = self._body(request)
        request_dispatched = False
        try:
            transport = await self._async_http_transport()
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=False,
                trust_env=False,
                transport=transport,
            ) as client:
                request_dispatched = True
                response = await client.post(
                    f"{self.base_url}{_cgp.MESSAGES_PATH}",
                    content=body,
                    headers=self._headers(_cgp.MESSAGES_PATH, body),
                )
        except asyncio.CancelledError:
            raise ClaudeRequestCancelled(
                usage_audit_required=request_dispatched,
            ) from None
        except httpx.HTTPError as exc:
            raise _safe_gateway_http_error(
                exc,
                usage_audit_required=request_dispatched,
            ) from None
        try:
            return self._decode_result(response)
        except ClaudeGatewayError as exc:
            if request_dispatched and not exc.fallback_safe:
                exc.usage_audit_required = True
            raise

    def create_message_sync(self, request: ClaudeMessageRequest) -> ClaudeMessageResult:
        self._require_config()
        body = self._body(request)
        request_dispatched = False
        try:
            transport = self._sync_http_transport()
            with httpx.Client(
                timeout=self.timeout,
                follow_redirects=False,
                trust_env=False,
                transport=transport,
            ) as client:
                request_dispatched = True
                response = client.post(
                    f"{self.base_url}{_cgp.MESSAGES_PATH}",
                    content=body,
                    headers=self._headers(_cgp.MESSAGES_PATH, body),
                )
        except httpx.HTTPError as exc:
            raise _safe_gateway_http_error(
                exc,
                usage_audit_required=request_dispatched,
            ) from None
        try:
            return self._decode_result(response)
        except ClaudeGatewayError as exc:
            if request_dispatched and not exc.fallback_safe:
                exc.usage_audit_required = True
            raise

    async def stream_message(
        self,
        request: ClaudeMessageRequest,
    ) -> AsyncGenerator[ClaudeStreamEvent, None]:
        self._require_config()
        body = self._body(request)
        terminal_seen = False
        usage_seen = False
        request_dispatched = False
        successful_response = False

        def stream_error(code: str, status_code: int = 502) -> ClaudeGatewayError:
            return ClaudeGatewayError(
                code,
                status_code,
                usage_audit_required=request_dispatched and not usage_seen,
            )

        try:
            transport = await self._async_http_transport()
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=False,
                trust_env=False,
                transport=transport,
            ) as client:
                request_dispatched = True
                async with client.stream(
                    "POST",
                    f"{self.base_url}{_cgp.STREAM_PATH}",
                    content=body,
                    headers=self._headers(_cgp.STREAM_PATH, body),
                ) as response:
                    if response.status_code != 200:
                        self._require_response_media_type(response, "application/json")
                        await response.aread()
                        try:
                            payload = response.json()
                        except Exception:
                            payload = None
                        raise self._error_from_payload(payload, response.status_code)
                    successful_response = True
                    self._require_response_media_type(response, "application/x-ndjson")
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            raise stream_error("GATEWAY_PROTOCOL_ERROR") from None
                        if not isinstance(event, dict) or event.get("protocol_version") != _cgp.PROTOCOL_VERSION:
                            raise stream_error("GATEWAY_PROTOCOL_ERROR")
                        if terminal_seen:
                            raise stream_error("GATEWAY_PROTOCOL_ERROR")
                        event_type = event.get("type")
                        if (
                            event_type == "content"
                            and isinstance(event.get("text"), str)
                            and not usage_seen
                        ):
                            yield ClaudeStreamEvent("content", text=event["text"])
                        elif event_type == "usage" and _cgp.valid_usage_envelope(event.get("usage")):
                            if event.get("usage") is None or usage_seen:
                                raise stream_error("GATEWAY_PROTOCOL_ERROR")
                            usage_seen = True
                            yield ClaudeStreamEvent("usage", usage=event["usage"])
                        elif event_type == "done":
                            if not usage_seen:
                                raise stream_error("GATEWAY_STREAM_USAGE_MISSING")
                            terminal_seen = True
                        elif event_type == "error":
                            error = self._error_from_payload(event, 502)
                            error.usage_audit_required = not usage_seen
                            error.fallback_safe = False
                            raise error
                        else:
                            raise stream_error("GATEWAY_PROTOCOL_ERROR")
        except asyncio.CancelledError:
            raise ClaudeRequestCancelled(
                usage_audit_required=request_dispatched and not usage_seen,
            ) from None
        except ClaudeGatewayError as exc:
            if successful_response:
                exc.fallback_safe = False
            if request_dispatched and not usage_seen and not exc.fallback_safe:
                exc.usage_audit_required = True
            raise
        except httpx.HTTPError as exc:
            raise _safe_gateway_http_error(
                exc,
                usage_audit_required=request_dispatched and not usage_seen,
            ) from None
        if not terminal_seen or not usage_seen:
            raise stream_error("GATEWAY_STREAM_INCOMPLETE")

    def probe_readiness(self) -> dict[str, Any]:
        self._require_config()
        challenge = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        headers = _cgp.auth_headers(
            key_id=self.key_id,
            secret=self.secret,
            method="GET",
            path=_cgp.READINESS_PATH,
            authority=self.authority,
            config_epoch=self.config_epoch,
            key_epoch=self.key_epoch,
            body=b"",
            nonce=nonce,
        )
        headers[_cgp.HEADER_READINESS_CHALLENGE] = challenge
        timeout_seconds = _gateway_readiness_timeout_seconds()
        timeout = httpx.Timeout(
            connect=timeout_seconds,
            read=timeout_seconds,
            write=timeout_seconds,
            pool=timeout_seconds,
        )
        try:
            transport = self._sync_http_transport()
            with httpx.Client(
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
                transport=transport,
            ) as client:
                response = client.request(
                    "GET",
                    f"{self.base_url}{_cgp.READINESS_PATH}",
                    content=b"",
                    headers=headers,
                )
        except ClaudeGatewayError:
            raise
        except httpx.TimeoutException:
            raise ClaudeGatewayError(
                "GATEWAY_READINESS_TIMEOUT", 503, fallback_safe=True,
            ) from None
        except httpx.HTTPError:
            raise ClaudeGatewayError(
                "GATEWAY_READINESS_NETWORK_ERROR", 503, fallback_safe=True,
            ) from None
        if response.status_code != 200:
            raise ClaudeGatewayError(
                "GATEWAY_READINESS_HTTP_ERROR", 503, fallback_safe=True,
            )
        try:
            self._require_response_media_type(response, "application/json")
            payload = response.json()
        except Exception:
            raise ClaudeGatewayError(
                "GATEWAY_READINESS_PROTOCOL_ERROR", 503, fallback_safe=True,
            ) from None
        expected_fields = {
            "protocol_version", "service", "status", "deployment_scope",
            "replay_store", "config_epoch", "key_epoch", "server_time",
            "challenge", "nonce", "attestation",
        }
        if not isinstance(payload, dict) or set(payload) != expected_fields:
            raise ClaudeGatewayError(
                "GATEWAY_READINESS_PROTOCOL_ERROR", 503, fallback_safe=True,
            )
        if not _cgp.verify_readiness_attestation(self.secret, payload):
            raise ClaudeGatewayError(
                "GATEWAY_READINESS_SIGNATURE_INVALID", 503, fallback_safe=True,
            )
        expected = {
            "protocol_version": _cgp.PROTOCOL_VERSION,
            "service": "noteai-claude-gateway",
            "status": "ready_multi_instance",
            "deployment_scope": "shared_control_plane",
            "replay_store": "dynamodb_shared_atomic",
            "config_epoch": self.config_epoch,
            "key_epoch": self.key_epoch,
            "challenge": challenge,
            "nonce": nonce,
        }
        if any(payload.get(field) != value for field, value in expected.items()):
            code = (
                "GATEWAY_READINESS_EPOCH_MISMATCH"
                if payload.get("config_epoch") != self.config_epoch
                or payload.get("key_epoch") != self.key_epoch
                else "GATEWAY_READINESS_MISMATCH"
            )
            raise ClaudeGatewayError(code, 503, fallback_safe=True)
        server_time = payload.get("server_time")
        try:
            max_skew = float(
                os.environ.get(
                    "NOTEAI_CLAUDE_GATEWAY_READINESS_MAX_CLOCK_SKEW_SECONDS", "30"
                ) or 30
            )
        except (TypeError, ValueError):
            max_skew = 30.0
        max_skew = max(1.0, min(300.0, max_skew))
        if (
            isinstance(server_time, bool)
            or not isinstance(server_time, int)
            or abs(int(time.time()) - server_time) > max_skew
        ):
            raise ClaudeGatewayError(
                "GATEWAY_READINESS_CLOCK_SKEW", 503, fallback_safe=True,
            )
        return {
            "remote_ready": True,
            "remote_error_code": None,
            "deployment_scope": payload["deployment_scope"],
            "replay_store": payload["replay_store"],
            "config_epoch": payload["config_epoch"],
            "key_epoch": payload["key_epoch"],
        }


_CLAUDE_TRANSPORT: ClaudeTransport | None = None
_GATEWAY_READINESS_CACHE_LOCK = threading.Lock()
_GATEWAY_READINESS_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="claude-gateway-readiness",
)
_GATEWAY_READINESS_CACHE: dict[str, Any] = {
    "key": None,
    "expires_at": 0.0,
    "value": None,
    "generation": 0,
    "inflight": None,
}


def claude_transport_mode() -> str:
    return os.environ.get("NOTEAI_CLAUDE_TRANSPORT", "local").strip().lower() or "local"


def _gateway_remote_readiness() -> dict[str, Any]:
    transport = GatewayClaudeTransport()
    cache_key = (
        transport.base_url,
        transport.authority,
        transport.config_epoch,
        transport.key_epoch,
        transport.key_id,
        hashlib.sha256(transport.secret.encode("utf-8")).hexdigest(),
    )
    now = time.monotonic()
    with _GATEWAY_READINESS_CACHE_LOCK:
        if (
            _GATEWAY_READINESS_CACHE["key"] == cache_key
            and now < float(_GATEWAY_READINESS_CACHE["expires_at"])
            and isinstance(_GATEWAY_READINESS_CACHE["value"], dict)
        ):
            return dict(_GATEWAY_READINESS_CACHE["value"])
        inflight = _GATEWAY_READINESS_CACHE.get("inflight")
        if isinstance(inflight, dict) and inflight["future"].done():
            _GATEWAY_READINESS_CACHE["inflight"] = None
            inflight = None
        if isinstance(inflight, dict):
            if inflight["key"] != cache_key:
                inflight["invalidated"] = True
                return {
                    "remote_ready": False,
                    "remote_error_code": "GATEWAY_READINESS_BUSY",
                }
            future = inflight["future"]
            generation = inflight["generation"]
        else:
            generation = int(_GATEWAY_READINESS_CACHE.get("generation", 0)) + 1
            future = _GATEWAY_READINESS_EXECUTOR.submit(transport.probe_readiness)
            _GATEWAY_READINESS_CACHE["generation"] = generation
            _GATEWAY_READINESS_CACHE["inflight"] = {
                "key": cache_key,
                "future": future,
                "generation": generation,
                "invalidated": False,
            }
    try:
        value = future.result(timeout=_gateway_readiness_timeout_seconds() + 0.25)
    except concurrent.futures.TimeoutError:
        with _GATEWAY_READINESS_CACHE_LOCK:
            current = _GATEWAY_READINESS_CACHE.get("inflight")
            if (
                isinstance(current, dict)
                and current.get("future") is future
                and current.get("generation") == generation
            ):
                current["invalidated"] = True
        return {
            "remote_ready": False,
            "remote_error_code": "GATEWAY_READINESS_TIMEOUT",
        }
    except ClaudeGatewayError as exc:
        value = {"remote_ready": False, "remote_error_code": exc.code}
    except Exception:
        value = {
            "remote_ready": False,
            "remote_error_code": "GATEWAY_READINESS_FAILED",
        }
    try:
        ttl_seconds = float(
            os.environ.get("NOTEAI_CLAUDE_GATEWAY_READINESS_CACHE_TTL_SECONDS", "5") or 5
        )
    except (TypeError, ValueError):
        ttl_seconds = 5.0
    ttl_seconds = max(0.0, min(30.0, ttl_seconds))
    with _GATEWAY_READINESS_CACHE_LOCK:
        current = _GATEWAY_READINESS_CACHE.get("inflight")
        if not (
            isinstance(current, dict)
            and current.get("future") is future
            and current.get("generation") == generation
            and current.get("key") == cache_key
        ):
            if (
                _GATEWAY_READINESS_CACHE.get("key") == cache_key
                and _GATEWAY_READINESS_CACHE.get("generation") == generation
                and isinstance(_GATEWAY_READINESS_CACHE.get("value"), dict)
                and time.monotonic() < float(_GATEWAY_READINESS_CACHE["expires_at"])
            ):
                return dict(_GATEWAY_READINESS_CACHE["value"])
            return {
                "remote_ready": False,
                "remote_error_code": "GATEWAY_READINESS_STALE",
            }
        if current.get("invalidated"):
            _GATEWAY_READINESS_CACHE["inflight"] = None
            return {
                "remote_ready": False,
                "remote_error_code": "GATEWAY_READINESS_TIMEOUT",
            }
        _GATEWAY_READINESS_CACHE.update({
            "key": cache_key,
            "expires_at": time.monotonic() + ttl_seconds,
            "value": dict(value),
            "generation": generation,
            "inflight": None,
        })
        return dict(value)


def claude_transport_readiness(*, require_remote: bool = False) -> dict[str, Any]:
    mode = claude_transport_mode()
    if mode == "local":
        configured = bool(os.environ.get("ANTHROPIC_API_KEY"))
    elif mode == "gateway":
        authority = os.environ.get("NOTEAI_CLAUDE_GATEWAY_AUTHORITY", "")
        configured = bool(
            _valid_gateway_base_url(
                os.environ.get("NOTEAI_CLAUDE_GATEWAY_URL", ""),
                authority,
            )
            and _valid_gateway_epoch(
                os.environ.get("NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH", "")
            )
            and _valid_gateway_epoch(
                os.environ.get("NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH", "")
            )
            and _valid_gateway_timeout_contract()
            and os.environ.get("NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID")
            and os.environ.get("NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET")
        )
    else:
        configured = False
    result: dict[str, Any] = {
        "mode": mode,
        "configured": configured,
        "supported": mode in {"local", "gateway"},
        "remote_checked": False,
        "remote_ready": None,
        "remote_error_code": None,
    }
    if mode == "gateway" and require_remote:
        result["remote_checked"] = True
        if configured:
            result.update(_gateway_remote_readiness())
        else:
            result.update({
                "remote_ready": False,
                "remote_error_code": "GATEWAY_READINESS_NOT_CONFIGURED",
            })
    return result


def get_claude_transport() -> ClaudeTransport:
    global _CLAUDE_TRANSPORT
    if _CLAUDE_TRANSPORT is None:
        mode = claude_transport_mode()
        if mode == "local":
            _CLAUDE_TRANSPORT = LocalAnthropicTransport()
        elif mode == "gateway":
            _CLAUDE_TRANSPORT = GatewayClaudeTransport()
        else:
            raise ClaudeGatewayError(
                "TRANSPORT_MODE_UNSUPPORTED",
                503,
                fallback_safe=True,
            )
    return _CLAUDE_TRANSPORT


def set_claude_transport(transport: ClaudeTransport | None) -> None:
    """Install a transport implementation; None restores the local default."""
    global _CLAUDE_TRANSPORT
    _CLAUDE_TRANSPORT = transport


def _claude_timeout_seconds(task: str, thinking: bool, max_tokens: int) -> float:
    if claude_transport_mode() == "gateway":
        _provider, _gateway_http, business = _gateway_timeout_values()
        return (
            business
            if _valid_gateway_timeout_contract()
            else CLAUDE_GATEWAY_BUSINESS_TIMEOUT_SECONDS
        )
    if thinking or max_tokens >= 4000:
        return CLAUDE_THINK_TIMEOUT_SECONDS
    if task == "semantic":
        return min(CLAUDE_FAST_TIMEOUT_SECONDS, 30.0)
    if task == "content_gen":
        return min(CLAUDE_FAST_TIMEOUT_SECONDS, 45.0)
    return CLAUDE_FAST_TIMEOUT_SECONDS


_GATEWAY_DEADLINE_ERROR_CODES = frozenset({
    "GATEWAY_PRE_DISPATCH_TIMEOUT",
    "MODEL_DEADLINE_EXCEEDED",
})


def _gateway_absolute_deadline(
    task: str,
    thinking: bool,
    max_tokens: int,
    models: list[str] | tuple[str, ...],
) -> float | None:
    if (
        claude_transport_mode() != "gateway"
        or not any(model.startswith("claude") for model in models)
    ):
        return None
    return (
        asyncio.get_running_loop().time()
        + _claude_timeout_seconds(task, thinking, max_tokens)
    )


def _gateway_deadline_error(
    *,
    pre_dispatch: bool = False,
    usage_audit_required: bool = False,
) -> ClaudeGatewayError:
    if usage_audit_required:
        return ClaudeGatewayError(
            "CLAUDE_OUTCOME_UNKNOWN",
            504,
            usage_audit_required=True,
        )
    return ClaudeGatewayError(
        "GATEWAY_PRE_DISPATCH_TIMEOUT" if pre_dispatch else "MODEL_DEADLINE_EXCEEDED",
        504,
    )


def _is_gateway_deadline_error(exc: BaseException) -> bool:
    return (
        isinstance(exc, ClaudeGatewayError)
        and exc.code in _GATEWAY_DEADLINE_ERROR_CODES
    )


def _discard_unstarted_awaitable(awaitable: Any) -> None:
    close = getattr(awaitable, "close", None)
    if callable(close):
        close()


def _require_gateway_deadline_remaining(
    deadline: float | None,
    *,
    pre_dispatch: bool = False,
) -> float | None:
    if deadline is None:
        return None
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        raise _gateway_deadline_error(pre_dispatch=pre_dispatch)
    return remaining


async def _await_with_gateway_deadline(
    awaitable: Any,
    deadline: float | None,
    *,
    pre_dispatch: bool = False,
    unstructured_cancel_usage_audit_required: bool = False,
    unstructured_cancel_usage_model: str | None = None,
):
    try:
        remaining = _require_gateway_deadline_remaining(
            deadline,
            pre_dispatch=pre_dispatch,
        )
    except BaseException:
        _discard_unstarted_awaitable(awaitable)
        raise
    if remaining is None:
        return await awaitable
    task = asyncio.ensure_future(awaitable)
    try:
        done, _pending = await asyncio.wait((task,), timeout=remaining)
    except asyncio.CancelledError as external_cancel:
        task.cancel()
        try:
            await task
        except ClaudeRequestCancelled:
            raise
        except BaseException:
            raise external_cancel
        raise external_cancel
    if task in done:
        return task.result()

    task.cancel()
    try:
        await task
    except ClaudeRequestCancelled as exc:
        raise _gateway_deadline_error(
            pre_dispatch=not exc.usage_audit_required,
            usage_audit_required=exc.usage_audit_required,
        ) from None
    except asyncio.CancelledError:
        if (
            unstructured_cancel_usage_audit_required
            and unstructured_cancel_usage_model
        ):
            _record_claude_usage(unstructured_cancel_usage_model, None)
        raise _gateway_deadline_error(
            pre_dispatch=pre_dispatch,
            usage_audit_required=unstructured_cancel_usage_audit_required,
        ) from None
    except Exception as exc:
        usage_audit_required = bool(
            getattr(exc, "usage_audit_required", False)
        )
        raise _gateway_deadline_error(
            pre_dispatch=pre_dispatch and not usage_audit_required,
            usage_audit_required=usage_audit_required,
        ) from None
    raise _gateway_deadline_error(
        pre_dispatch=pre_dispatch,
        usage_audit_required=unstructured_cancel_usage_audit_required,
    )


def _new_operation_id() -> str:
    return secrets.token_urlsafe(24)


async def _call_model_with_retries(
    task: str,
    model_id: str,
    system: str,
    user: str,
    thinking: bool,
    max_tokens: int,
    operation_id: str = "",
    absolute_deadline: float | None = None,
) -> str:
    operation_id = operation_id or _new_operation_id()
    attempts = MODEL_RETRY_ATTEMPTS
    for attempt in range(1, attempts + 1):
        try:
            t0 = time.monotonic()
            if model_id.startswith("claude"):
                sem = _get_semaphore("claude", CLAUDE_CONCURRENCY)
                if absolute_deadline is None:
                    async with sem:
                        result = await asyncio.wait_for(
                            _call_claude(
                                model_id, system, user, thinking, max_tokens,
                                operation_id=operation_id,
                            ),
                            timeout=_claude_timeout_seconds(task, thinking, max_tokens),
                        )
                else:
                    await _await_with_gateway_deadline(
                        sem.acquire(),
                        absolute_deadline,
                        pre_dispatch=True,
                    )
                    try:
                        result = await _await_with_gateway_deadline(
                            _call_claude(
                                model_id, system, user, thinking, max_tokens,
                                operation_id=operation_id,
                            ),
                            absolute_deadline,
                            unstructured_cancel_usage_audit_required=True,
                            unstructured_cancel_usage_model=model_id,
                        )
                    finally:
                        sem.release()
            else:
                sem = _get_semaphore("kimi_text", KIMI_TEXT_CONCURRENCY)
                if absolute_deadline is None:
                    async with sem:
                        result = await _call_kimi(
                            model_id, system, user, thinking, max_tokens,
                        )
                else:
                    await _await_with_gateway_deadline(
                        sem.acquire(),
                        absolute_deadline,
                        pre_dispatch=True,
                    )
                    try:
                        result = await _await_with_gateway_deadline(
                            _call_kimi(
                                model_id, system, user, thinking, max_tokens,
                            ),
                            absolute_deadline,
                        )
                    finally:
                        sem.release()
            elapsed = time.monotonic() - t0
            _log(f"task={task} model={model_id} attempt={attempt}/{attempts} elapsed={elapsed:.1f}s chars={len(result)}")
            if not result:
                raise ValueError("empty response")
            return result
        except Exception as exc:
            if _is_gateway_deadline_error(exc):
                raise
            is_claude = model_id.startswith("claude")
            retryable = (
                isinstance(exc, ClaudeGatewayError) and exc.fallback_safe
                if is_claude
                else _is_retryable(exc)
            )
            _log(
                f"task={task} model={model_id} attempt={attempt}/{attempts} "
                f"FAIL code={_safe_failure_code(exc)}"
            )
            if attempt >= attempts or not retryable:
                if is_claude:
                    raise _fixed_claude_error(exc) from None
                raise
            if absolute_deadline is None:
                await asyncio.sleep(MODEL_RETRY_BASE_DELAY * attempt)
            else:
                await _await_with_gateway_deadline(
                    asyncio.sleep(MODEL_RETRY_BASE_DELAY * attempt),
                    absolute_deadline,
                    pre_dispatch=True,
                )
    raise RuntimeError(f"[mr] retry loop exhausted for task={task} model={model_id}")


# ── Claude 非流式调用 ─────────────────────────────────────────────
async def _call_claude(
    model: str, system: str, user: str,
    thinking: bool = False, max_tokens: int = 1200,
    operation_id: str = "",
) -> str:
    operation_id = operation_id or _new_operation_id()
    thinking_budget = None
    if thinking:
        thinking_budget = max(min(max_tokens - 1000, 10000), 1024)
    try:
        result = await get_claude_transport().create_message(ClaudeMessageRequest(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=({"role": "user", "content": user},),
            operation_id=operation_id,
            temperature=None if thinking else 0.7,
            thinking_budget=thinking_budget,
        ))
    except BaseException as exc:
        if getattr(exc, "usage_audit_required", False):
            _record_claude_usage(model, None)
        raise
    _record_claude_usage(model, result.usage)
    return "".join(result.text_blocks).strip()


# ── Kimi 非流式调用 ───────────────────────────────────────────────
async def _call_kimi(
    model: str, system: str, user: str,
    thinking: bool = False, max_tokens: int = 1200,
) -> str:
    key = os.environ.get("MOONSHOT_API_KEY", "")
    payload: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "max_tokens": max_tokens,
        "thinking": {"type": "disabled"},
        "temperature": 0.6,
    }
    timeout = KIMI_TIMEOUT_Q
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            KIMI_API_URL, json=payload,
            headers={"Authorization": f"Bearer {key}"},
        )
        r.raise_for_status()
        data = r.json()
        _record_kimi_usage(model, data.get("usage") if isinstance(data, dict) else None)
        return data["choices"][0]["message"]["content"].strip()


# ── 统一非流式调用入口 ────────────────────────────────────────────
async def call(
    task: str, system: str, user: str,
    thinking: bool = False, max_tokens: int = 1200,
) -> str:
    """路由到对应模型；Claude 仅在确认未调用 provider 时走 fallback。"""
    routing = TASK_ROUTING.get(task, {"primary": KIMI_TEXT, "fallback": []})
    models_to_try = [routing["primary"]] + list(routing.get("fallback", []))
    absolute_deadline = _gateway_absolute_deadline(
        task,
        thinking,
        max_tokens,
        models_to_try,
    )
    operation_id = _new_operation_id()

    for model_id in models_to_try:
        try:
            _require_gateway_deadline_remaining(
                absolute_deadline,
                pre_dispatch=True,
            )
            return await _call_model_with_retries(
                task, model_id, system, user, thinking, max_tokens,
                operation_id=operation_id,
                absolute_deadline=absolute_deadline,
            )
        except Exception as exc:
            if _is_gateway_deadline_error(exc):
                raise
            if model_id.startswith("claude") and not (
                isinstance(exc, ClaudeGatewayError) and exc.fallback_safe
            ):
                _log(f"task={task} model={model_id} STOP code={_safe_failure_code(exc)}")
                raise _fixed_claude_error(exc) from None
            _log(f"task={task} model={model_id} FAIL code={_safe_failure_code(exc)} → fallback")
    raise RuntimeError(f"[mr] all models failed for task={task}")


# ── Claude 流式调用 ───────────────────────────────────────────────
async def _claude_transport_stream(
    model: str,
    request: ClaudeMessageRequest,
    absolute_deadline: float | None = None,
) -> AsyncGenerator[ClaudeStreamEvent, None]:
    usage_recorded = False
    provider_event_seen = False
    transport_iterator = get_claude_transport().stream_message(request).__aiter__()
    gateway_deadline = absolute_deadline
    if gateway_deadline is None and claude_transport_mode() == "gateway":
        gateway_deadline = (
            asyncio.get_running_loop().time()
            + _claude_timeout_seconds("stream", True, request.max_tokens)
        )
    try:
        while True:
            try:
                next_event = transport_iterator.__anext__()
                event = await _await_with_gateway_deadline(
                    next_event,
                    gateway_deadline,
                    unstructured_cancel_usage_audit_required=True,
                )
            except StopAsyncIteration:
                break
            provider_event_seen = True
            if event.type == "usage":
                _record_claude_usage(model, event.usage)
                usage_recorded = True
            yield event
    except BaseException as exc:
        fallback_safe = isinstance(exc, ClaudeGatewayError) and exc.fallback_safe
        if _is_gateway_deadline_error(exc):
            audit_required = bool(getattr(exc, "usage_audit_required", False))
        elif isinstance(exc, ClaudeRequestCancelled):
            audit_required = exc.usage_audit_required or provider_event_seen
        elif isinstance(exc, asyncio.CancelledError):
            audit_required = provider_event_seen
        else:
            audit_required = (
                getattr(exc, "usage_audit_required", False)
                or provider_event_seen
                or not fallback_safe
            )
        if audit_required and not usage_recorded:
            _record_claude_usage(model, None)
        raise
    finally:
        await _close_async_iterator(transport_iterator)


async def _stream_claude(
    model: str, system: str, user: str,
    thinking: bool = True, max_tokens: int = 16000,
    history: list[dict] | None = None,
    operation_id: str = "",
    absolute_deadline: float | None = None,
) -> AsyncGenerator[tuple[str, str], None]:
    """流式调用 Claude，yield ('thinking', text) 或 ('content', text)。"""
    messages = list(history or []) + [{"role": "user", "content": user}]
    operation_id = operation_id or _new_operation_id()
    thinking_budget = None
    if thinking:
        thinking_budget = max(min(max_tokens - 2000, 10000), 1024)
    request = ClaudeMessageRequest(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=tuple(messages),
        operation_id=operation_id,
        temperature=None if thinking else 0.7,
        thinking_budget=thinking_budget,
    )
    transport_stream = _claude_transport_stream(
        model,
        request,
        absolute_deadline=absolute_deadline,
    )
    try:
        async for event in transport_stream:
            if event.type in {"thinking", "content"}:
                yield (event.type, event.text)
    finally:
        await _close_async_iterator(transport_stream)


# ── Kimi 流式调用 ─────────────────────────────────────────────────
async def _stream_kimi(
    model: str, system: str, user: str,
    thinking: bool = False, max_tokens: int = 16000,
    history: list[dict] | None = None,
) -> AsyncGenerator[tuple[str, str], None]:
    """流式调用 Kimi，yield ('thinking', text) 或 ('content', text)。"""
    key = os.environ.get("MOONSHOT_API_KEY", "")
    messages = [{"role": "system", "content": system}]
    messages.extend(history or [])
    messages.append({"role": "user", "content": user})

    payload: dict = {
        "model": model,
        "messages": messages,
        "thinking": {"type": "enabled", "budget_tokens": min(max_tokens - 500, 12000)}
                    if thinking else {"type": "disabled"},
        "stream": True,
        "max_tokens": max_tokens,
    }
    if not thinking:
        payload["temperature"] = 0.6

    timeout = KIMI_TIMEOUT
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST", KIMI_API_URL, json=payload,
            headers={"Authorization": f"Bearer {key}"},
        ) as resp:
            resp.raise_for_status()
            final_usage = None
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[6:].strip()
                if raw == "[DONE]":
                    break
                try:
                    chunk = json.loads(raw)
                    chunk_usage = _extract_kimi_stream_usage(chunk)
                    if chunk_usage is not None:
                        final_usage = chunk_usage
                    delta = chunk["choices"][0].get("delta", {})
                    if delta.get("reasoning_content"):
                        yield ("thinking", delta["reasoning_content"])
                    if delta.get("content"):
                        yield ("content", delta["content"])
                except Exception:
                    continue
            _record_kimi_usage(model, final_usage)


# ── 统一流式调用入口 ──────────────────────────────────────────────
async def stream(
    task: str, system: str, user: str,
    thinking: bool = True, max_tokens: int = 16000,
    history: list[dict] | None = None,
) -> AsyncGenerator[tuple[str, str], None]:
    """路由到流式接口；Claude 仅在零输出且确认未调用 provider 时 fallback。
    yield: ('thinking', text) | ('content', text)
    """
    routing = TASK_ROUTING.get(task, {"primary": KIMI_TEXT, "fallback": []})
    primary  = routing["primary"]
    fallbacks = list(routing.get("fallback", []))
    absolute_deadline = _gateway_absolute_deadline(
        "stream",
        thinking,
        max_tokens,
        [primary, *fallbacks],
    )
    emitted = False
    operation_id = _new_operation_id()

    primary_stream = (
        _stream_claude(
            primary, system, user, thinking, max_tokens, history,
            operation_id=operation_id,
            absolute_deadline=absolute_deadline,
        )
        if primary.startswith("claude")
        else _stream_kimi(primary, system, user, thinking, max_tokens, history)
    )
    try:
        try:
            if primary.startswith("claude"):
                async for chunk in primary_stream:
                    emitted = True
                    yield chunk
            else:
                primary_iterator = primary_stream.__aiter__()
                while True:
                    try:
                        chunk = await _await_with_gateway_deadline(
                            primary_iterator.__anext__(),
                            absolute_deadline,
                        )
                    except StopAsyncIteration:
                        break
                    emitted = True
                    yield chunk
            return
        finally:
            await _close_async_iterator(primary_stream)
    except Exception as exc:
        if primary.startswith("claude"):
            if emitted:
                _log(f"stream task={task} model={primary} STOP code=CLAUDE_STREAM_PARTIAL")
                raise ClaudeGatewayError("CLAUDE_STREAM_PARTIAL", 502) from None
            if _is_gateway_deadline_error(exc):
                raise
            fallback_safe = isinstance(exc, ClaudeGatewayError) and exc.fallback_safe
            if not fallback_safe:
                _log(f"stream task={task} model={primary} STOP code={_safe_failure_code(exc)}")
                raise _fixed_claude_error(exc, "CLAUDE_STREAM_FAILED") from None
        elif _is_gateway_deadline_error(exc):
            raise
        _log(f"stream task={task} model={primary} FAIL code={_safe_failure_code(exc)} → fallback")

    # fallback: 依次尝试，降级为整块返回
    for fb_model in fallbacks:
        try:
            _require_gateway_deadline_remaining(
                absolute_deadline,
                pre_dispatch=True,
            )
            _log(f"stream task={task} fallback model={fb_model}")
            if fb_model.startswith("claude"):
                result = await _await_with_gateway_deadline(
                    _call_claude(
                        fb_model, system, user, thinking=False, max_tokens=max_tokens,
                        operation_id=operation_id,
                    ),
                    absolute_deadline,
                    unstructured_cancel_usage_audit_required=True,
                    unstructured_cancel_usage_model=fb_model,
                )
            else:
                result = await _await_with_gateway_deadline(
                    _call_kimi(
                        fb_model, system, user, thinking=False, max_tokens=max_tokens,
                    ),
                    absolute_deadline,
                )
            if result:
                yield ("content", result)
                return
        except Exception as exc2:
            if _is_gateway_deadline_error(exc2):
                raise
            _log(
                f"stream task={task} fallback model={fb_model} "
                f"FAIL code={_safe_failure_code(exc2)}"
            )
            if fb_model.startswith("claude") and not (
                isinstance(exc2, ClaudeGatewayError) and exc2.fallback_safe
            ):
                raise _fixed_claude_error(exc2) from None

    raise RuntimeError(f"[mr] all stream models failed for task={task}")


# ── 专用：Claude Sonnet 流式 chat（支持多轮历史） ─────────────────
async def stream_chat(
    system: str,
    history: list[dict],
    user_content,          # str 或 list（多模态）
    thinking: bool = True,
    max_tokens: int = 16000,
) -> AsyncGenerator[tuple[str, str], None]:
    """Chat 专用流式接口，直接透传 Kimi 兼容的 messages 列表。
    对于 Claude：Kimi messages 格式 (system/user/assistant) 可直接用。
    yield: ('thinking', text) | ('content', text)
    """
    absolute_deadline = _gateway_absolute_deadline(
        "stream",
        thinking,
        max_tokens,
        [CLAUDE_SONNET, CLAUDE_HAIKU],
    )
    # 过滤掉 system role（Claude 单独传 system 参数）
    claude_messages = [m for m in history if m.get("role") != "system"]
    # 处理含 reasoning_content 的 assistant 消息（Claude 不接受此字段）
    cleaned: list[dict] = []
    for m in claude_messages:
        if m["role"] == "assistant":
            content = m.get("content", "")
            if isinstance(content, str):
                cleaned.append({"role": "assistant", "content": content})
        else:
            cleaned.append(m)
    cleaned.append({"role": "user", "content": user_content})
    operation_id = _new_operation_id()

    thinking_budget = (
        max(min(max_tokens - 2000, 10000), 1024)
        if thinking else None
    )
    request = ClaudeMessageRequest(
        model=CLAUDE_SONNET,
        max_tokens=max_tokens,
        system=system,
        messages=tuple(cleaned),
        operation_id=operation_id,
        temperature=None if thinking else 0.7,
        thinking_budget=thinking_budget,
    )

    emitted = False
    transport_stream = _claude_transport_stream(
        CLAUDE_SONNET,
        request,
        absolute_deadline=absolute_deadline,
    )
    try:
        try:
            async for event in transport_stream:
                if event.type in {"thinking", "content"}:
                    emitted = True
                    yield (event.type, event.text)
        finally:
            await _close_async_iterator(transport_stream)
    except Exception as exc:
        if emitted:
            _log("stream_chat Sonnet STOP code=CLAUDE_STREAM_PARTIAL")
            raise ClaudeGatewayError("CLAUDE_STREAM_PARTIAL", 502) from None
        if _is_gateway_deadline_error(exc):
            raise
        if not (isinstance(exc, ClaudeGatewayError) and exc.fallback_safe):
            _log(f"stream_chat Sonnet STOP code={_safe_failure_code(exc)}")
            raise _fixed_claude_error(exc, "CLAUDE_STREAM_FAILED") from None
        # fallback to Haiku non-streaming
        _log(f"stream_chat Sonnet FAIL code={_safe_failure_code(exc)} → Haiku fallback")
        try:
            _require_gateway_deadline_remaining(
                absolute_deadline,
                pre_dispatch=True,
            )
            user_text = user_content if isinstance(user_content, str) else str(user_content)
            result = await _await_with_gateway_deadline(
                _call_claude(
                    CLAUDE_HAIKU, system, user_text,
                    thinking=False, max_tokens=min(max_tokens, 4096),
                    operation_id=operation_id,
                ),
                absolute_deadline,
                unstructured_cancel_usage_audit_required=True,
                unstructured_cancel_usage_model=CLAUDE_HAIKU,
            )
            if result:
                yield ("content", result)
        except Exception as exc2:
            _log(f"stream_chat Haiku STOP code={_safe_failure_code(exc2)}")
            raise _fixed_claude_error(exc2) from None


# ── Claude 同步入口（供线程池与遗留同步路径使用） ─────────
def call_claude_sync(
    *,
    model: str,
    messages: list[dict],
    max_tokens: int,
    system: str | None = None,
    temperature: float | None = None,
    thinking_budget: int | None = None,
    first_text_block: bool = False,
) -> str:
    operation_id = _new_operation_id()
    request = ClaudeMessageRequest(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=tuple(messages),
        operation_id=operation_id,
        temperature=temperature,
        thinking_budget=thinking_budget,
    )
    try:
        transport = get_claude_transport()
        if claude_transport_mode() == "gateway":
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                pass
            else:
                raise ClaudeGatewayError(
                    "GATEWAY_SYNC_CONTEXT_INVALID", 503, fallback_safe=True,
                )

            async def bounded_gateway_call() -> ClaudeMessageResult:
                deadline = (
                    asyncio.get_running_loop().time()
                    + _claude_timeout_seconds("sync", False, max_tokens)
                )
                return await _await_with_gateway_deadline(
                    transport.create_message(request),
                    deadline,
                    unstructured_cancel_usage_audit_required=True,
                )

            result = asyncio.run(bounded_gateway_call())
        else:
            result = transport.create_message_sync(request)
    except BaseException as exc:
        if getattr(exc, "usage_audit_required", False):
            _record_claude_usage(model, None)
        raise
    _record_claude_usage(model, result.usage)
    parts = result.text_blocks[:1] if first_text_block else result.text_blocks
    return "".join(parts).strip()


def call_semantic_sync(system: str, user: str, max_tokens: int = 300) -> str:
    """在线程池（asyncio.to_thread）中同步调用 Claude Haiku 做语义评分。"""
    return call_claude_sync(
        model=CLAUDE_HAIKU,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        temperature=0.3,
    )


# ── 日志 ──────────────────────────────────────────────────────────
def _log(msg: str) -> None:
    print(f"[mr] {msg}", file=sys.stderr, flush=True)
