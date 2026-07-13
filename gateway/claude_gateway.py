"""Minimal single-instance Claude Gateway for the Render Singapore hop."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import math
import os
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Awaitable, Callable

import anthropic
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from claude_gateway_protocol import (
    ALLOWED_MODELS,
    HEADER_AUTHORITY,
    HEADER_CONFIG_EPOCH,
    HEADER_KEY_ID,
    HEADER_KEY_EPOCH,
    HEADER_NONCE,
    HEADER_PROTOCOL_VERSION,
    HEADER_READINESS_CHALLENGE,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    MESSAGES_PATH,
    PROTOCOL_VERSION,
    READINESS_PATH,
    STREAM_PATH,
    readiness_attestation,
    signature,
    valid_operation_id,
    valid_usage_envelope,
)
from control_store import ControlStoreUnavailable, Lease, OperationState


logger = logging.getLogger("noteai.claude_gateway")
app = FastAPI(
    title="NoteAI Claude Gateway",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

_NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_.~-]{16,128}$")
_READINESS_CHALLENGE_PATTERN = re.compile(r"^[A-Za-z0-9_.~-]{16,128}$")
_AUTHORITY_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_EPOCH_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _max_body_bytes() -> int:
    return _int_env("NOTEAI_CLAUDE_GATEWAY_MAX_BODY_BYTES", 8 * 1024 * 1024, 1024, 16 * 1024 * 1024)


def _max_tokens() -> int:
    return _int_env("NOTEAI_CLAUDE_GATEWAY_MAX_TOKENS", 16000, 1024, 64000)


def _timestamp_skew_seconds() -> int:
    return _int_env("NOTEAI_CLAUDE_GATEWAY_TIMESTAMP_SKEW_SECONDS", 300, 30, 900)


def _configured_instance_count() -> int:
    return _int_env("NOTEAI_CLAUDE_GATEWAY_INSTANCE_COUNT", 1, 1, 100)


def _control_mode() -> str:
    return os.environ.get(
        "NOTEAI_CLAUDE_GATEWAY_CONTROL_MODE", "memory"
    ).strip().lower() or "memory"


def _stable_principal_id() -> str:
    return os.environ.get("NOTEAI_CLAUDE_GATEWAY_PRINCIPAL_ID", "").strip()


def _gateway_authority() -> str:
    value = os.environ.get("NOTEAI_CLAUDE_GATEWAY_AUTHORITY", "")
    if (
        not value
        or not value.isascii()
        or value != value.lower()
        or value.endswith(".")
        or value.endswith(".local")
        or "%" in value
        or ":" in value
        or not _AUTHORITY_PATTERN.fullmatch(value)
    ):
        return ""
    return value


def _gateway_config_epoch() -> str:
    value = os.environ.get("NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH", "")
    return value if value.isascii() and _EPOCH_PATTERN.fullmatch(value) else ""


def _gateway_key_epoch() -> str:
    value = os.environ.get("NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH", "")
    return value if value.isascii() and _EPOCH_PATTERN.fullmatch(value) else ""


def _dynamodb_identity_environment_valid() -> bool:
    static_names = (
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    )
    return bool(
        not any(os.environ.get(name, "").strip() for name in static_names)
        and os.environ.get("AWS_ROLE_ARN", "").strip()
        and os.environ.get("AWS_WEB_IDENTITY_TOKEN_FILE", "").strip()
        and os.environ.get("AWS_EC2_METADATA_DISABLED", "").strip().lower() == "true"
    )


def _float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _now_epoch() -> int:
    return int(time.time())


def _provider_deadline_seconds() -> float:
    return _float_env(
        "NOTEAI_CLAUDE_GATEWAY_PROVIDER_DEADLINE_SECONDS", 180.0, 1.0, 600.0,
    )


def _lease_seconds() -> int:
    margin = _int_env("NOTEAI_CLAUDE_GATEWAY_LEASE_MARGIN_SECONDS", 30, 5, 120)
    configured = _int_env("NOTEAI_CLAUDE_GATEWAY_LEASE_SECONDS", 240, 5, 900)
    return max(configured, int(math.ceil(_provider_deadline_seconds())) + margin)


def _terminal_retention_seconds() -> int:
    return _int_env(
        "NOTEAI_CLAUDE_GATEWAY_TERMINAL_RETENTION_SECONDS",
        30 * 24 * 60 * 60,
        24 * 60 * 60,
        90 * 24 * 60 * 60,
    )


def _preflight_timeout_seconds() -> float:
    try:
        value = float(
            os.environ.get("NOTEAI_CLAUDE_GATEWAY_PREFLIGHT_TIMEOUT_SECONDS", "175")
            or 175
        )
    except (TypeError, ValueError):
        value = 175.0
    return max(1.0, min(300.0, value))


def _provider_timeout_contract_valid() -> bool:
    return bool(
        _provider_deadline_seconds() == 180.0
        and _preflight_timeout_seconds() == 175.0
        and _preflight_timeout_seconds() < _provider_deadline_seconds()
    )


def _configured_hmac_keys() -> dict[str, str] | None:
    current_id = os.environ.get("NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID", "").strip()
    current_secret = os.environ.get("NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET", "")
    previous_id = os.environ.get("NOTEAI_CLAUDE_GATEWAY_PREVIOUS_HMAC_KEY_ID", "").strip()
    previous_secret = os.environ.get("NOTEAI_CLAUDE_GATEWAY_PREVIOUS_HMAC_SECRET", "")
    if not current_id or not current_secret:
        return None
    if bool(previous_id) != bool(previous_secret):
        return None
    if previous_id and previous_id == current_id:
        return None
    keys = {current_id: current_secret}
    if previous_id:
        keys[previous_id] = previous_secret
    return keys


@dataclass(frozen=True)
class GatewayRejection(Exception):
    code: str
    status_code: int


def _error_payload(code: str) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "error": {"code": code, "message": "request rejected"},
    }


@app.exception_handler(GatewayRejection)
async def _gateway_rejection_handler(_request: Request, exc: GatewayRejection):
    logger.warning("gateway_reject code=%s", exc.code)
    return JSONResponse(_error_payload(exc.code), status_code=exc.status_code)


class InMemoryNonceStore:
    """Replay protection scoped to one process instance only."""

    def __init__(self):
        self._nonces: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def claim(self, key_id: str, nonce: str, expires_at: float) -> bool:
        cache_key = f"{key_id}:{nonce}"
        now = time.time()
        async with self._lock:
            expired = [key for key, expiry in self._nonces.items() if expiry <= now]
            for key in expired:
                self._nonces.pop(key, None)
            if cache_key in self._nonces:
                return False
            self._nonces[cache_key] = expires_at
            return True


class ConcurrencyLimiter:
    def __init__(self, limit: int):
        self.limit = max(1, int(limit))
        self.active = 0
        self._lock = asyncio.Lock()

    async def try_acquire(self) -> bool:
        async with self._lock:
            if self.active >= self.limit:
                return False
            self.active += 1
            return True

    async def release(self) -> None:
        async with self._lock:
            self.active = max(0, self.active - 1)


class InMemoryRateLimiter:
    """Bounded per-key fixed-window rate limit, scoped to one instance."""

    def __init__(self, limit: int, window_seconds: int = 60):
        self.limit = max(1, int(limit))
        self.window_seconds = max(1, int(window_seconds))
        self._requests: dict[str, list[float]] = {}
        self._lock = asyncio.Lock()

    async def allow(self, key_id: str) -> bool:
        now = time.time()
        cutoff = now - self.window_seconds
        async with self._lock:
            recent = [stamp for stamp in self._requests.get(key_id, []) if stamp > cutoff]
            if len(recent) >= self.limit:
                self._requests[key_id] = recent
                return False
            recent.append(now)
            self._requests[key_id] = recent
            return True


_NONCES = InMemoryNonceStore()
_LIMITER = ConcurrencyLimiter(
    _int_env("NOTEAI_CLAUDE_GATEWAY_CONCURRENCY", 2, 1, 32)
)
_RATE_LIMITER = InMemoryRateLimiter(
    _int_env("NOTEAI_CLAUDE_GATEWAY_REQUESTS_PER_MINUTE", 30, 1, 600)
)
_CONTROL_STORE = None


def _get_control_store():
    global _CONTROL_STORE
    if _CONTROL_STORE is None:
        try:
            from dynamodb_control_store import DynamoDBControlStore

            _CONTROL_STORE = DynamoDBControlStore.from_env()
        except Exception:
            raise ControlStoreUnavailable("control store unavailable") from None
    return _CONTROL_STORE


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


def _normalized_usage(usage) -> dict[str, Any] | None:
    if not usage:
        return None
    result: dict[str, Any] = {
        "input_tokens": _usage_attr(usage, "input_tokens"),
        "output_tokens": _usage_attr(usage, "output_tokens"),
        "cache_read_input_tokens": _usage_attr(usage, "cache_read_input_tokens"),
        "cache_creation_input_tokens": _usage_attr(usage, "cache_creation_input_tokens"),
    }
    cache_creation = _usage_value(usage, "cache_creation")
    if cache_creation is not None:
        result["cache_creation"] = {
            "ephemeral_5m_input_tokens": _usage_attr(cache_creation, "ephemeral_5m_input_tokens"),
            "ephemeral_1h_input_tokens": _usage_attr(cache_creation, "ephemeral_1h_input_tokens"),
        }
    if not valid_usage_envelope(result):
        raise ValueError("invalid provider usage")
    return result


def _provider_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": payload["model"],
        "max_tokens": payload["max_tokens"],
        "messages": payload["messages"],
    }
    if payload.get("system") is not None:
        kwargs["system"] = payload["system"]
    if payload.get("thinking_budget") is not None:
        kwargs["thinking"] = {
            "type": "enabled",
            "budget_tokens": payload["thinking_budget"],
        }
    elif payload.get("temperature") is not None:
        kwargs["temperature"] = payload["temperature"]
    return kwargs


class AnthropicProvider:
    def __init__(self):
        self._client: anthropic.AsyncAnthropic | None = None

    def _get_client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(
                api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
                timeout=_provider_deadline_seconds(),
                max_retries=0,
            )
        return self._client

    async def create(self, payload: dict[str, Any]) -> tuple[list[str], dict[str, Any] | None]:
        response = await self._get_client().messages.create(**_provider_kwargs(payload))
        text_blocks = [
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text"
        ]
        return text_blocks, _normalized_usage(getattr(response, "usage", None))

    async def stream(self, payload: dict[str, Any]) -> AsyncGenerator[dict[str, Any], None]:
        async with self._get_client().messages.stream(**_provider_kwargs(payload)) as stream_ctx:
            async for event in stream_ctx:
                if event.type != "content_block_delta":
                    continue
                delta = event.delta
                # Provider thinking/reasoning is intentionally discarded here.
                if delta.type == "text_delta" and delta.text:
                    yield {"type": "content", "text": delta.text}
            try:
                final_message = stream_ctx.get_final_message()
                if inspect.isawaitable(final_message):
                    final_message = await final_message
                usage = _normalized_usage(getattr(final_message, "usage", None))
                if usage is not None:
                    yield {"type": "usage", "usage": usage}
            except Exception:
                pass


_PROVIDER = AnthropicProvider()


def _provider_error(exc: BaseException) -> tuple[str, int]:
    status = getattr(exc, "status_code", None)
    if isinstance(exc, (anthropic.APITimeoutError, httpx.TimeoutException, asyncio.TimeoutError)):
        return "PROVIDER_TIMEOUT", 504
    if status in {401, 403}:
        return "PROVIDER_AUTH", 502
    if status == 429:
        return "PROVIDER_RATE_LIMIT", 429
    if status in {408, 425, 500, 502, 503, 504}:
        return "PROVIDER_UNAVAILABLE", 503
    return "PROVIDER_ERROR", 502


def _contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


def _single_header(request: Request, name: str) -> str:
    values = request.headers.getlist(name)
    if len(values) != 1 or not values[0]:
        raise GatewayRejection("AUTH_HEADER_INVALID", 401)
    return values[0]


async def _authenticate(
    request: Request,
    body: bytes,
    expected_path: str,
    *,
    consume_replay_and_rate: bool = True,
) -> str:
    if request.url.query:
        raise GatewayRejection("QUERY_NOT_ALLOWED", 400)
    if request.url.path != expected_path:
        raise GatewayRejection("PATH_INVALID", 400)
    content_types = request.headers.getlist("content-type")
    if content_types != ["application/json"]:
        raise GatewayRejection("CONTENT_TYPE_UNSUPPORTED", 415)
    if any(request.headers.getlist(name) for name in ("authorization", "cookie", "content-encoding")):
        raise GatewayRejection("FORBIDDEN_HEADER", 400)

    authority = _gateway_authority()
    config_epoch = _gateway_config_epoch()
    key_epoch = _gateway_key_epoch()
    if not authority or not config_epoch or not key_epoch:
        raise GatewayRejection("GATEWAY_NOT_CONFIGURED", 503)
    if _single_header(request, "host") != authority:
        raise GatewayRejection("AUTH_CONTEXT_INVALID", 401)
    if (
        _single_header(request, HEADER_AUTHORITY) != authority
        or _single_header(request, HEADER_CONFIG_EPOCH) != config_epoch
        or _single_header(request, HEADER_KEY_EPOCH) != key_epoch
    ):
        raise GatewayRejection("AUTH_CONTEXT_INVALID", 401)

    protocol_version = _single_header(request, HEADER_PROTOCOL_VERSION)
    if protocol_version != PROTOCOL_VERSION:
        raise GatewayRejection("PROTOCOL_VERSION_UNSUPPORTED", 400)
    key_id = _single_header(request, HEADER_KEY_ID)
    timestamp_text = _single_header(request, HEADER_TIMESTAMP)
    nonce = _single_header(request, HEADER_NONCE)
    supplied_signature = _single_header(request, HEADER_SIGNATURE)

    configured_keys = _configured_hmac_keys()
    if not configured_keys:
        raise GatewayRejection("GATEWAY_NOT_CONFIGURED", 503)
    configured_secret = configured_keys.get(key_id)
    if configured_secret is None:
        raise GatewayRejection("AUTH_INVALID", 401)
    if not _NONCE_PATTERN.fullmatch(nonce):
        raise GatewayRejection("AUTH_NONCE_INVALID", 401)
    try:
        timestamp = int(timestamp_text)
    except ValueError as exc:
        raise GatewayRejection("AUTH_TIMESTAMP_INVALID", 401) from exc
    skew = _timestamp_skew_seconds()
    if abs(int(time.time()) - timestamp) > skew:
        raise GatewayRejection("AUTH_EXPIRED", 401)

    expected = signature(
        secret=configured_secret,
        method=request.method,
        path=expected_path,
        key_id=key_id,
        protocol_version=protocol_version,
        content_type="application/json",
        timestamp=timestamp_text,
        nonce=nonce,
        body=body,
        authority=authority,
        config_epoch=config_epoch,
        key_epoch=key_epoch,
    )
    if not secrets.compare_digest(supplied_signature, expected):
        raise GatewayRejection("AUTH_INVALID", 401)
    if not consume_replay_and_rate:
        return key_id
    now = time.time()
    now_epoch = int(now)
    mode = _control_mode()
    if mode == "memory":
        if not await _NONCES.claim(
            key_id, nonce, max(now_epoch, timestamp) + skew,
        ):
            raise GatewayRejection("AUTH_REPLAY", 409)
        if not await _RATE_LIMITER.allow(key_id):
            raise GatewayRejection("RATE_LIMIT", 429)
        return key_id
    if mode != "dynamodb":
        raise GatewayRejection("GATEWAY_NOT_CONFIGURED", 503)
    principal_id = _stable_principal_id()
    if not principal_id or not _dynamodb_identity_environment_valid():
        raise GatewayRejection("GATEWAY_NOT_CONFIGURED", 503)
    try:
        store = _get_control_store()
        if getattr(store, "credential_method", "") != "assume-role-with-web-identity":
            raise ControlStoreUnavailable("control store unavailable")
        # Cover the full validity interval for timestamps near the allowed
        # future-skew boundary; TTL cleanup never defines replay validity.
        if not await store.claim_nonce(
            principal_id,
            nonce,
            now_epoch,
            max(now_epoch, timestamp) + skew,
        ):
            raise GatewayRejection("AUTH_REPLAY", 409)
        if not await store.admit_rate(
            principal_id,
            now,
            _int_env("NOTEAI_CLAUDE_GATEWAY_REQUESTS_PER_MINUTE", 30, 1, 600),
            60,
        ):
            raise GatewayRejection("RATE_LIMIT", 429)
    except GatewayRejection:
        raise
    except ControlStoreUnavailable:
        raise GatewayRejection("CONTROL_PLANE_UNAVAILABLE", 503) from None
    return principal_id


def _validate_payload(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise GatewayRejection("INVALID_REQUEST", 422)
    allowed_fields = {
        "operation_id", "model", "max_tokens", "system", "messages", "temperature",
        "thinking_budget",
    }
    if set(raw) - allowed_fields:
        raise GatewayRejection("INVALID_REQUEST", 422)
    operation_id = raw.get("operation_id")
    if not valid_operation_id(operation_id):
        raise GatewayRejection("INVALID_REQUEST", 422)
    model = raw.get("model")
    if model not in ALLOWED_MODELS:
        raise GatewayRejection("MODEL_NOT_ALLOWED", 422)
    max_tokens = raw.get("max_tokens")
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= _max_tokens():
        raise GatewayRejection("TOKEN_LIMIT_EXCEEDED", 422)
    messages = raw.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 50:
        raise GatewayRejection("INVALID_REQUEST", 422)
    for message in messages:
        if (
            not isinstance(message, dict)
            or set(message) != {"role", "content"}
            or message.get("role") not in {"user", "assistant"}
        ):
            raise GatewayRejection("INVALID_REQUEST", 422)
        content = message.get("content")
        if not isinstance(content, (str, list)):
            raise GatewayRejection("INVALID_REQUEST", 422)
        if isinstance(content, str) and len(content) > 2_000_000:
            raise GatewayRejection("CONTENT_LIMIT_EXCEEDED", 422)
        if isinstance(content, list):
            if not 1 <= len(content) <= 100:
                raise GatewayRejection("CONTENT_LIMIT_EXCEEDED", 422)
            for block in content:
                if not isinstance(block, dict) or _contains_key(block, "url"):
                    raise GatewayRejection("REMOTE_IMAGE_NOT_ALLOWED", 422)
                if set(block) != {"type", "text"}:
                    raise GatewayRejection("IMAGES_DISABLED", 422)
                if block.get("type") != "text" or not isinstance(block.get("text"), str):
                    raise GatewayRejection("INVALID_REQUEST", 422)
                if len(block["text"]) > 2_000_000:
                    raise GatewayRejection("CONTENT_LIMIT_EXCEEDED", 422)
    system = raw.get("system")
    if system is not None and not isinstance(system, str):
        raise GatewayRejection("INVALID_REQUEST", 422)
    if isinstance(system, str) and len(system) > 500_000:
        raise GatewayRejection("CONTENT_LIMIT_EXCEEDED", 422)
    temperature = raw.get("temperature")
    if temperature is not None and (
        isinstance(temperature, bool)
        or not isinstance(temperature, (int, float))
        or not 0 <= float(temperature) <= 1
    ):
        raise GatewayRejection("INVALID_REQUEST", 422)
    thinking_budget = raw.get("thinking_budget")
    if thinking_budget is not None and (
        isinstance(thinking_budget, bool)
        or not isinstance(thinking_budget, int)
        or thinking_budget < 1024
        or thinking_budget >= max_tokens
    ):
        raise GatewayRejection("TOKEN_LIMIT_EXCEEDED", 422)
    if thinking_budget is not None and temperature is not None:
        raise GatewayRejection("INVALID_REQUEST", 422)
    return {
        "operation_id": operation_id,
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
        "system": system,
        "temperature": float(temperature) if temperature is not None else None,
        "thinking_budget": thinking_budget,
    }


async def _read_and_validate(request: Request, expected_path: str) -> dict[str, Any]:
    mode = _control_mode()
    if mode == "memory" and _configured_instance_count() != 1:
        raise GatewayRejection("REPLAY_STORE_INSTANCE_SCOPE", 503)
    if mode not in {"memory", "dynamodb"}:
        raise GatewayRejection("GATEWAY_NOT_CONFIGURED", 503)
    content_lengths = request.headers.getlist("content-length")
    if len(content_lengths) > 1:
        raise GatewayRejection("CONTENT_LENGTH_INVALID", 400)
    if content_lengths:
        try:
            content_length = int(content_lengths[0])
            if content_length < 0:
                raise GatewayRejection("CONTENT_LENGTH_INVALID", 400)
            if content_length > _max_body_bytes():
                raise GatewayRejection("PAYLOAD_TOO_LARGE", 413)
        except ValueError as exc:
            raise GatewayRejection("CONTENT_LENGTH_INVALID", 400) from exc
    collected = bytearray()
    async for chunk in request.stream():
        if not chunk:
            continue
        if len(collected) + len(chunk) > _max_body_bytes():
            raise GatewayRejection("PAYLOAD_TOO_LARGE", 413)
        collected.extend(chunk)
    body = bytes(collected)
    principal_id = await _authenticate(request, body, expected_path)
    try:
        raw = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GatewayRejection("INVALID_JSON", 400) from exc
    payload = _validate_payload(raw)
    payload["_principal_id"] = principal_id
    return payload


def _ndjson(event: dict[str, Any]) -> bytes:
    return (json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


class _AsyncCleanupOnce:
    def __init__(self, cleanup: Callable[[], Awaitable[None]]):
        self._cleanup = cleanup
        self._complete = False
        self._lock = asyncio.Lock()

    async def run(self) -> None:
        async with self._lock:
            if self._complete:
                return
            await self._cleanup()
            self._complete = True


class _ManagedBodyIterator:
    def __init__(self, source, cleanup: _AsyncCleanupOnce):
        self._source = source.__aiter__()
        self._cleanup = cleanup

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return await self._source.__anext__()
        except StopAsyncIteration:
            await self._cleanup.run()
            raise
        except BaseException:
            await self._cleanup.run()
            raise

    async def aclose(self) -> None:
        try:
            close = getattr(self._source, "aclose", None)
            if close is not None:
                result = close()
                if inspect.isawaitable(result):
                    await result
        finally:
            await self._cleanup.run()


class _ManagedStreamingResponse(StreamingResponse):
    def __init__(self, content, cleanup: _AsyncCleanupOnce, **kwargs):
        super().__init__(content, **kwargs)
        self._cleanup = cleanup

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self._cleanup.run()


class _SharedDispatch:
    """One durable provider dispatch guarded by a renewable fenced lease."""

    def __init__(self, store, payload: dict[str, Any], lease: Lease):
        self.store = store
        self.payload = payload
        self.operation_id = payload["operation_id"]
        self.lease = lease
        self.provider_started = False
        self.begin_attempted = False
        self.finalized = False
        self.lost = asyncio.Event()
        self.provider_deadline_at = 0.0
        self._heartbeat_task: asyncio.Task | None = None

    @classmethod
    async def prepare(cls, payload: dict[str, Any]) -> "_SharedDispatch":
        store = _get_control_store()
        now_epoch = _now_epoch()
        dispatch = None
        begin_attempted = False
        try:
            lease = await store.acquire_lease(
                payload["operation_id"],
                _int_env("NOTEAI_CLAUDE_GATEWAY_CONCURRENCY", 2, 1, 32),
                now_epoch,
                _lease_seconds(),
            )
            if lease is None:
                raise GatewayRejection("CONCURRENCY_LIMIT", 429)
            dispatch = cls(store, payload, lease)
            claim = await store.claim_operation(
                payload["_principal_id"],
                payload["operation_id"],
            )
            if claim.state != OperationState.CLAIMED:
                await dispatch._release_before_provider()
                raise GatewayRejection("OPERATION_ALREADY_DISPATCHED", 409)
            safe_payload = {
                key: value for key, value in payload.items() if not key.startswith("_")
            }
            dispatch_hash = hashlib.sha256(
                json.dumps(
                    safe_payload, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            dispatch.begin_attempted = True
            begin_attempted = True
            begin_now_epoch = _now_epoch()
            started = await store.begin_provider(
                payload["operation_id"], lease, dispatch_hash,
                payload["model"], begin_now_epoch,
            )
            if not started:
                await dispatch._release_before_provider()
                raise GatewayRejection("OPERATION_ALREADY_DISPATCHED", 409)
            dispatch.provider_started = True
            dispatch.provider_deadline_at = (
                time.monotonic() + _provider_deadline_seconds()
            )
            dispatch._heartbeat_task = asyncio.create_task(dispatch._heartbeat())
            return dispatch
        except GatewayRejection:
            raise
        except ControlStoreUnavailable:
            if not begin_attempted:
                if dispatch is not None:
                    await dispatch._release_before_provider()
                raise GatewayRejection("CONTROL_PLANE_UNAVAILABLE", 503) from None
            raise GatewayRejection("CONTROL_PLANE_OUTCOME_UNKNOWN", 503) from None

    async def _release_before_provider(self) -> None:
        try:
            await self.store.release_lease(self.lease)
        except ControlStoreUnavailable:
            pass

    async def _heartbeat(self) -> None:
        interval = max(0.1, _lease_seconds() / 3)
        try:
            while True:
                await asyncio.sleep(interval)
                renewed = await self.store.renew_lease(
                    self.lease, _now_epoch(), _lease_seconds(),
                )
                if renewed is None:
                    self.lost.set()
                    return
                self.lease = renewed
        except (ControlStoreUnavailable, asyncio.CancelledError):
            if not self.finalized:
                self.lost.set()

    async def await_provider(self, awaitable):
        provider_task = asyncio.ensure_future(awaitable)
        lost_task = asyncio.create_task(self.lost.wait())
        try:
            remaining = max(0.0, self.provider_deadline_at - time.monotonic())
            done, _pending = await asyncio.wait(
                {provider_task, lost_task},
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
        except BaseException:
            provider_task.cancel()
            lost_task.cancel()
            try:
                await provider_task
            except BaseException:
                pass
            try:
                await lost_task
            except BaseException:
                pass
            raise
        if not done:
            provider_task.cancel()
            lost_task.cancel()
            for task in (provider_task, lost_task):
                try:
                    await task
                except BaseException:
                    pass
            raise asyncio.TimeoutError("provider deadline exceeded")
        if lost_task in done and self.lost.is_set():
            provider_task.cancel()
            try:
                await provider_task
            except BaseException:
                pass
            raise GatewayRejection("CONTROL_PLANE_OUTCOME_UNKNOWN", 503)
        lost_task.cancel()
        try:
            await lost_task
        except BaseException:
            pass
        return await provider_task

    async def finish(
        self,
        state: OperationState,
        *,
        usage: dict[str, Any] | None = None,
        error_code: str = "",
    ) -> None:
        if self.finalized:
            return
        self.finalized = True
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except BaseException:
                pass
        try:
            finished = await self.store.finish_operation(
                self.operation_id,
                self.lease,
                state,
                _now_epoch(),
                retention_seconds=_terminal_retention_seconds(),
                usage=usage,
                error_code=error_code,
            )
        except ControlStoreUnavailable:
            raise GatewayRejection("CONTROL_PLANE_OUTCOME_UNKNOWN", 503) from None
        if not finished:
            raise GatewayRejection("CONTROL_PLANE_OUTCOME_UNKNOWN", 503)


@app.get(READINESS_PATH)
async def signed_remote_readiness(request: Request):
    body = await request.body()
    if body:
        raise GatewayRejection("INVALID_REQUEST", 400)
    key_id = await _authenticate(
        request,
        body,
        READINESS_PATH,
        consume_replay_and_rate=False,
    )
    challenge = _single_header(request, HEADER_READINESS_CHALLENGE)
    if not _READINESS_CHALLENGE_PATTERN.fullmatch(challenge):
        raise GatewayRejection("INVALID_REQUEST", 400)
    if _control_mode() != "dynamodb":
        raise GatewayRejection("GATEWAY_NOT_READY", 503)
    configured = bool(
        os.environ.get("ANTHROPIC_API_KEY")
        and _configured_hmac_keys()
        and _gateway_authority()
        and _gateway_config_epoch()
        and _gateway_key_epoch()
        and _provider_timeout_contract_valid()
    )
    store_configured = bool(
        _stable_principal_id()
        and os.environ.get("NOTEAI_CLAUDE_GATEWAY_DDB_TABLE", "").strip()
        and os.environ.get("NOTEAI_CLAUDE_GATEWAY_DDB_REGION", "ap-southeast-1").strip()
        and _dynamodb_identity_environment_valid()
    )
    store_ready = False
    if store_configured:
        try:
            store = _get_control_store()
            store_ready = bool(
                getattr(store, "credential_method", "")
                == "assume-role-with-web-identity"
                and await store.health()
            )
        except ControlStoreUnavailable:
            store_ready = False
    if not configured or not store_configured or not store_ready:
        raise GatewayRejection("GATEWAY_NOT_READY", 503)
    configured_keys = _configured_hmac_keys() or {}
    secret = configured_keys.get(key_id)
    if secret is None:
        raise GatewayRejection("AUTH_INVALID", 401)
    payload = {
        "protocol_version": PROTOCOL_VERSION,
        "service": "noteai-claude-gateway",
        "status": "ready_multi_instance",
        "deployment_scope": "shared_control_plane",
        "replay_store": "dynamodb_shared_atomic",
        "config_epoch": _gateway_config_epoch(),
        "key_epoch": _gateway_key_epoch(),
        "server_time": int(time.time()),
        "challenge": challenge,
        "nonce": _single_header(request, HEADER_NONCE),
    }
    payload["attestation"] = readiness_attestation(secret, payload)
    return JSONResponse(payload, status_code=200)


@app.get("/health/live")
async def health_live():
    return {"status": "ok", "service": "noteai-claude-gateway"}


@app.get("/health/ready")
async def health_ready():
    configured = bool(
        os.environ.get("ANTHROPIC_API_KEY")
        and _configured_hmac_keys()
        and _gateway_authority()
        and _gateway_config_epoch()
        and _gateway_key_epoch()
        and _provider_timeout_contract_valid()
    )
    mode = _control_mode()
    single_instance = _configured_instance_count() == 1
    if mode == "memory":
        ready = configured and single_instance
        status = "ready_single_instance" if ready else "not_ready"
        deployment_scope = "single_instance_only"
        replay_store = "memory_instance_scope"
        multi_ready = False
        checks = {
            "configured": configured,
            "instance_count_is_one": single_instance,
        }
    elif mode == "dynamodb":
        store_configured = bool(
            _stable_principal_id()
            and os.environ.get("NOTEAI_CLAUDE_GATEWAY_DDB_TABLE", "").strip()
            and os.environ.get("NOTEAI_CLAUDE_GATEWAY_DDB_REGION", "ap-southeast-1").strip()
            and _dynamodb_identity_environment_valid()
        )
        store_ready = False
        if store_configured:
            try:
                store = _get_control_store()
                store_ready = bool(
                    getattr(store, "credential_method", "")
                    == "assume-role-with-web-identity"
                    and await store.health()
                )
            except ControlStoreUnavailable:
                store_ready = False
        ready = configured and store_configured and store_ready
        status = "ready_multi_instance" if ready else "not_ready"
        deployment_scope = "shared_control_plane"
        replay_store = "dynamodb_shared_atomic"
        multi_ready = ready
        checks = {
            "configured": configured,
            "control_store_configured": store_configured,
            "control_store_ready": store_ready,
        }
    else:
        ready = False
        status = "not_ready"
        deployment_scope = "invalid"
        replay_store = "invalid"
        multi_ready = False
        checks = {"configured": configured, "control_mode_supported": False}
    payload = {
        "status": status,
        "service": "noteai-claude-gateway",
        "protocol_version": PROTOCOL_VERSION,
        "deployment_scope": deployment_scope,
        "replay_store": replay_store,
        "multi_instance_production_ready": multi_ready,
        "checks": checks,
    }
    return JSONResponse(payload, status_code=200 if ready else 503)


@app.post(MESSAGES_PATH)
async def create_message(request: Request):
    payload = await _read_and_validate(request, MESSAGES_PATH)
    shared = None
    limiter_acquired = False
    if _control_mode() == "dynamodb":
        shared = await _SharedDispatch.prepare(payload)
    else:
        if not await _LIMITER.try_acquire():
            raise GatewayRejection("CONCURRENCY_LIMIT", 429)
        limiter_acquired = True
    started = time.monotonic()
    try:
        provider_call = _PROVIDER.create(payload)
        text_blocks, usage = (
            await shared.await_provider(provider_call)
            if shared is not None else await provider_call
        )
        if (
            not isinstance(text_blocks, list)
            or not all(isinstance(block, str) for block in text_blocks)
            or not valid_usage_envelope(usage)
        ):
            raise ValueError("invalid provider response")
        if shared is not None:
            if usage is None:
                await shared.finish(
                    OperationState.AMBIGUOUS, error_code="PROVIDER_USAGE_MISSING",
                )
                raise GatewayRejection("CONTROL_PLANE_OUTCOME_UNKNOWN", 503)
            await shared.finish(OperationState.TERMINAL_USAGE, usage=usage)
        logger.info(
            "gateway_complete code=OK model=%s stream=false elapsed_ms=%d",
            payload["model"],
            int((time.monotonic() - started) * 1000),
        )
        return {
            "protocol_version": PROTOCOL_VERSION,
            "text_blocks": text_blocks,
            "usage": usage,
        }
    except (asyncio.CancelledError, GeneratorExit):
        if shared is not None and not shared.finalized:
            await shared.finish(OperationState.CANCELLED, error_code="CANCELLED")
        raise
    except GatewayRejection:
        if shared is not None and not shared.finalized:
            await shared.finish(
                OperationState.AMBIGUOUS,
                error_code="CONTROL_PLANE_OUTCOME_UNKNOWN",
            )
        raise
    except Exception as exc:
        code, status_code = _provider_error(exc)
        if shared is not None and not shared.finalized:
            await shared.finish(OperationState.AMBIGUOUS, error_code=code)
        logger.warning("gateway_provider_error code=%s model=%s stream=false", code, payload["model"])
        return JSONResponse(_error_payload(code), status_code=status_code)
    finally:
        if limiter_acquired:
            await _LIMITER.release()


@app.post(STREAM_PATH)
async def stream_message(request: Request):
    payload = await _read_and_validate(request, STREAM_PATH)
    limiter = _LIMITER
    shared = None
    limiter_acquired = False
    if _control_mode() == "dynamodb":
        shared = await _SharedDispatch.prepare(payload)
    else:
        if not await limiter.try_acquire():
            raise GatewayRejection("CONCURRENCY_LIMIT", 429)
        limiter_acquired = True

    started = time.monotonic()
    usage_seen = False
    final_usage = None
    public_content_seen = False
    provider = _PROVIDER
    provider_stream = provider.stream(payload)
    provider_iterator = provider_stream.__aiter__()

    async def close_provider() -> None:
        close = getattr(provider_iterator, "aclose", None)
        if close is None:
            return
        try:
            result = close()
            if inspect.isawaitable(result):
                await result
        except (Exception, asyncio.CancelledError, GeneratorExit):
            pass

    async def finish_stream(default_state: OperationState, error_code: str) -> None:
        if shared is None or shared.finalized:
            return
        if usage_seen and final_usage is not None:
            await shared.finish(OperationState.TERMINAL_USAGE, usage=final_usage)
            return
        state = OperationState.PARTIAL if public_content_seen else default_state
        await shared.finish(state, error_code=error_code)

    async def cleanup_resources() -> None:
        await close_provider()
        if shared is not None and not shared.finalized:
            try:
                await finish_stream(OperationState.CANCELLED, "STREAM_CLOSED")
            except GatewayRejection:
                logger.warning(
                    "gateway_control_error code=CONTROL_PLANE_OUTCOME_UNKNOWN stream=true"
                )
        if limiter_acquired:
            await limiter.release()

    cleanup = _AsyncCleanupOnce(cleanup_resources)

    async def next_public_event() -> dict[str, Any]:
        nonlocal usage_seen, final_usage, public_content_seen
        while True:
            next_event = provider_iterator.__anext__()
            event = (
                await shared.await_provider(next_event)
                if shared is not None else await next_event
            )
            event_type = event.get("type") if isinstance(event, dict) else None
            if event_type == "thinking":
                await asyncio.sleep(0)
                continue
            if event_type == "content" and isinstance(event.get("text"), str):
                public_content_seen = True
                return {"type": "content", "text": event["text"]}
            if (
                event_type == "usage"
                and event.get("usage") is not None
                and valid_usage_envelope(event.get("usage"))
            ):
                if usage_seen:
                    raise ValueError("duplicate provider usage")
                usage_seen = True
                final_usage = event["usage"]
                return {"type": "usage", "usage": event["usage"]}
            raise ValueError("invalid provider stream event")

    try:
        first_event = await asyncio.wait_for(
            next_public_event(),
            timeout=_preflight_timeout_seconds(),
        )
    except (asyncio.CancelledError, GeneratorExit):
        await finish_stream(OperationState.CANCELLED, "CANCELLED")
        await cleanup.run()
        raise
    except GatewayRejection:
        if shared is not None and not shared.finalized:
            await shared.finish(OperationState.AMBIGUOUS, error_code="CONTROL_PLANE_OUTCOME_UNKNOWN")
        await cleanup.run()
        raise
    except BaseException as exc:
        code, status_code = _provider_error(exc)
        logger.warning(
            "gateway_provider_error code=%s model=%s stream=true phase=preflight",
            code,
            payload["model"],
        )
        if shared is not None and not shared.finalized:
            await shared.finish(OperationState.AMBIGUOUS, error_code=code)
        await cleanup.run()
        return JSONResponse(_error_payload(code), status_code=status_code)

    async def generate():
        try:
            yield _ndjson({"protocol_version": PROTOCOL_VERSION, **first_event})
            while True:
                try:
                    public_event = await next_public_event()
                except StopAsyncIteration:
                    break
                yield _ndjson({"protocol_version": PROTOCOL_VERSION, **public_event})
            if not usage_seen:
                if shared is not None and not shared.finalized:
                    await shared.finish(
                        OperationState.AMBIGUOUS,
                        error_code="PROVIDER_USAGE_MISSING",
                    )
                raise ValueError("provider usage missing")
            if shared is not None:
                await shared.finish(OperationState.TERMINAL_USAGE, usage=final_usage)
            yield _ndjson({"protocol_version": PROTOCOL_VERSION, "type": "done"})
            logger.info(
                "gateway_complete code=OK model=%s stream=true elapsed_ms=%d",
                payload["model"],
                int((time.monotonic() - started) * 1000),
            )
        except BaseException as exc:
            if isinstance(exc, (asyncio.CancelledError, GeneratorExit)):
                await finish_stream(OperationState.CANCELLED, "CANCELLED")
                raise
            if isinstance(exc, GatewayRejection):
                code = exc.code
            else:
                code, _status_code = _provider_error(exc)
            if shared is not None and not shared.finalized:
                await finish_stream(OperationState.AMBIGUOUS, code)
            logger.warning("gateway_provider_error code=%s model=%s stream=true", code, payload["model"])
            yield _ndjson({
                "protocol_version": PROTOCOL_VERSION,
                "type": "error",
                "error": {"code": code, "message": "provider request failed"},
            })
        finally:
            await cleanup.run()

    return _ManagedStreamingResponse(
        _ManagedBodyIterator(generate(), cleanup),
        cleanup,
        media_type="application/x-ndjson",
    )
