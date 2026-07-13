"""Minimal single-instance Claude Gateway for the Render Singapore hop."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
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
    HEADER_KEY_ID,
    HEADER_NONCE,
    HEADER_PROTOCOL_VERSION,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    MESSAGES_PATH,
    PROTOCOL_VERSION,
    STREAM_PATH,
    signature,
    valid_usage_envelope,
)


logger = logging.getLogger("noteai.claude_gateway")
app = FastAPI(
    title="NoteAI Claude Gateway",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

_NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_.~-]{16,128}$")


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


def _preflight_timeout_seconds() -> float:
    try:
        value = float(
            os.environ.get("NOTEAI_CLAUDE_GATEWAY_PREFLIGHT_TIMEOUT_SECONDS", "175")
            or 175
        )
    except (TypeError, ValueError):
        value = 175.0
    return max(1.0, min(300.0, value))


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


async def _authenticate(request: Request, body: bytes, expected_path: str) -> None:
    if request.url.query:
        raise GatewayRejection("QUERY_NOT_ALLOWED", 400)
    if request.url.path != expected_path:
        raise GatewayRejection("PATH_INVALID", 400)
    content_types = request.headers.getlist("content-type")
    if content_types != ["application/json"]:
        raise GatewayRejection("CONTENT_TYPE_UNSUPPORTED", 415)
    if any(request.headers.getlist(name) for name in ("authorization", "cookie", "content-encoding")):
        raise GatewayRejection("FORBIDDEN_HEADER", 400)

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
        configured_secret,
        request.method,
        expected_path,
        key_id,
        protocol_version,
        "application/json",
        timestamp_text,
        nonce,
        body,
    )
    if not secrets.compare_digest(supplied_signature, expected):
        raise GatewayRejection("AUTH_INVALID", 401)
    now = time.time()
    if not await _NONCES.claim(key_id, nonce, max(now, float(timestamp)) + skew):
        raise GatewayRejection("AUTH_REPLAY", 409)
    if not await _RATE_LIMITER.allow(key_id):
        raise GatewayRejection("RATE_LIMIT", 429)


def _validate_payload(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise GatewayRejection("INVALID_REQUEST", 422)
    allowed_fields = {
        "model", "max_tokens", "system", "messages", "temperature", "thinking_budget",
    }
    if set(raw) - allowed_fields:
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
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
        "system": system,
        "temperature": float(temperature) if temperature is not None else None,
        "thinking_budget": thinking_budget,
    }


async def _read_and_validate(request: Request, expected_path: str) -> dict[str, Any]:
    if _configured_instance_count() != 1:
        raise GatewayRejection("REPLAY_STORE_INSTANCE_SCOPE", 503)
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
    await _authenticate(request, body, expected_path)
    try:
        raw = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GatewayRejection("INVALID_JSON", 400) from exc
    return _validate_payload(raw)


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


@app.get("/health/live")
async def health_live():
    return {"status": "ok", "service": "noteai-claude-gateway"}


@app.get("/health/ready")
async def health_ready():
    configured = bool(
        os.environ.get("ANTHROPIC_API_KEY")
        and _configured_hmac_keys()
    )
    single_instance = _configured_instance_count() == 1
    ready = configured and single_instance
    payload = {
        "status": "ready_single_instance" if ready else "not_ready",
        "service": "noteai-claude-gateway",
        "protocol_version": PROTOCOL_VERSION,
        "deployment_scope": "single_instance_only",
        "replay_store": "memory_instance_scope",
        "multi_instance_production_ready": False,
        "checks": {
            "configured": configured,
            "instance_count_is_one": single_instance,
        },
    }
    return JSONResponse(payload, status_code=200 if ready else 503)


@app.post(MESSAGES_PATH)
async def create_message(request: Request):
    payload = await _read_and_validate(request, MESSAGES_PATH)
    if not await _LIMITER.try_acquire():
        raise GatewayRejection("CONCURRENCY_LIMIT", 429)
    started = time.monotonic()
    try:
        text_blocks, usage = await _PROVIDER.create(payload)
        if (
            not isinstance(text_blocks, list)
            or not all(isinstance(block, str) for block in text_blocks)
            or not valid_usage_envelope(usage)
        ):
            raise ValueError("invalid provider response")
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
    except Exception as exc:
        code, status_code = _provider_error(exc)
        logger.warning("gateway_provider_error code=%s model=%s stream=false", code, payload["model"])
        return JSONResponse(_error_payload(code), status_code=status_code)
    finally:
        await _LIMITER.release()


@app.post(STREAM_PATH)
async def stream_message(request: Request):
    payload = await _read_and_validate(request, STREAM_PATH)
    limiter = _LIMITER
    if not await limiter.try_acquire():
        raise GatewayRejection("CONCURRENCY_LIMIT", 429)

    started = time.monotonic()
    usage_seen = False
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

    async def cleanup_resources() -> None:
        await close_provider()
        await limiter.release()

    cleanup = _AsyncCleanupOnce(cleanup_resources)

    async def next_public_event() -> dict[str, Any]:
        nonlocal usage_seen
        while True:
            event = await provider_iterator.__anext__()
            event_type = event.get("type") if isinstance(event, dict) else None
            if event_type == "thinking":
                await asyncio.sleep(0)
                continue
            if event_type == "content" and isinstance(event.get("text"), str):
                return {"type": "content", "text": event["text"]}
            if (
                event_type == "usage"
                and event.get("usage") is not None
                and valid_usage_envelope(event.get("usage"))
            ):
                if usage_seen:
                    raise ValueError("duplicate provider usage")
                usage_seen = True
                return {"type": "usage", "usage": event["usage"]}
            raise ValueError("invalid provider stream event")

    try:
        first_event = await asyncio.wait_for(
            next_public_event(),
            timeout=_preflight_timeout_seconds(),
        )
    except (asyncio.CancelledError, GeneratorExit):
        await cleanup.run()
        raise
    except BaseException as exc:
        code, status_code = _provider_error(exc)
        logger.warning(
            "gateway_provider_error code=%s model=%s stream=true phase=preflight",
            code,
            payload["model"],
        )
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
                raise ValueError("provider usage missing")
            yield _ndjson({"protocol_version": PROTOCOL_VERSION, "type": "done"})
            logger.info(
                "gateway_complete code=OK model=%s stream=true elapsed_ms=%d",
                payload["model"],
                int((time.monotonic() - started) * 1000),
            )
        except BaseException as exc:
            if isinstance(exc, (asyncio.CancelledError, GeneratorExit)):
                raise
            code, _status_code = _provider_error(exc)
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
