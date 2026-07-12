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
import inspect
import ipaddress
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Protocol
from urllib.parse import urlsplit

import anthropic
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

_SEMAPHORES: dict[tuple[str, int], asyncio.Semaphore] = {}

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
        response = await self._get_async_client().messages.create(
            **_local_claude_kwargs(request)
        )
        return self._result(response)

    def create_message_sync(self, request: ClaudeMessageRequest) -> ClaudeMessageResult:
        response = self._get_sync_client().messages.create(
            **_local_claude_kwargs(request)
        )
        return self._result(response)

    async def stream_message(
        self,
        request: ClaudeMessageRequest,
    ) -> AsyncGenerator[ClaudeStreamEvent, None]:
        async with self._get_async_client().messages.stream(
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
            try:
                final_message = stream_ctx.get_final_message()
                if inspect.isawaitable(final_message):
                    final_message = await final_message
                yield ClaudeStreamEvent(
                    "usage",
                    usage=_normalized_claude_usage(getattr(final_message, "usage", None)),
                )
            except Exception:
                pass


class ClaudeGatewayError(RuntimeError):
    def __init__(
        self,
        code: str,
        status_code: int | None = None,
        *,
        usage_audit_required: bool = False,
    ):
        safe_code = code if re.fullmatch(r"[A-Z0-9_]{1,64}", str(code or "")) else "GATEWAY_ERROR"
        self.code = safe_code
        self.status_code = status_code
        self.usage_audit_required = bool(usage_audit_required)
        super().__init__(f"claude gateway error: {safe_code}")


def _valid_gateway_base_url(value: str | None) -> bool:
    raw = str(value or "").strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except (TypeError, ValueError):
        return False
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or port not in {None, 443}
        or hostname == "localhost"
        or hostname.endswith(".local")
    ):
        return False
    try:
        ipaddress.ip_address(hostname)
        return False
    except ValueError:
        return True


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
        key_id: str | None = None,
        secret: str | None = None,
        timeout_seconds: float | None = None,
        http_transport: Any = None,
    ):
        self.base_url = (
            base_url if base_url is not None
            else os.environ.get("NOTEAI_CLAUDE_GATEWAY_URL", "")
        ).strip().rstrip("/")
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
                    os.environ.get("NOTEAI_CLAUDE_GATEWAY_HTTP_TIMEOUT_SECONDS", "190") or 190
                )
            except (TypeError, ValueError):
                timeout_seconds = 190.0
        timeout_seconds = max(1.0, float(timeout_seconds))
        self.timeout = httpx.Timeout(
            connect=min(10.0, timeout_seconds),
            read=timeout_seconds,
            write=min(30.0, timeout_seconds),
            pool=min(10.0, timeout_seconds),
        )
        self.http_transport = http_transport

    def _require_config(self) -> None:
        if not self.base_url or not self.key_id or not self.secret:
            raise ClaudeGatewayError("GATEWAY_NOT_CONFIGURED", 503)
        if not _valid_gateway_base_url(self.base_url):
            raise ClaudeGatewayError("GATEWAY_URL_INVALID", 503)

    @staticmethod
    def _body(request: ClaudeMessageRequest) -> bytes:
        return json.dumps({
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
            body=body,
        )

    @staticmethod
    def _error_from_payload(payload: Any, status_code: int | None) -> ClaudeGatewayError:
        code = "GATEWAY_ERROR"
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict) and isinstance(error.get("code"), str):
                code = error["code"]
        return ClaudeGatewayError(code, status_code)

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
        if response.status_code >= 400:
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
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=False,
                transport=self.http_transport,
            ) as client:
                response = await client.post(
                    f"{self.base_url}{_cgp.MESSAGES_PATH}",
                    content=body,
                    headers=self._headers(_cgp.MESSAGES_PATH, body),
                )
        except ClaudeGatewayError:
            raise
        except httpx.HTTPError as exc:
            raise _safe_gateway_http_error(exc) from None
        return self._decode_result(response)

    def create_message_sync(self, request: ClaudeMessageRequest) -> ClaudeMessageResult:
        self._require_config()
        body = self._body(request)
        try:
            with httpx.Client(
                timeout=self.timeout,
                follow_redirects=False,
                transport=self.http_transport,
            ) as client:
                response = client.post(
                    f"{self.base_url}{_cgp.MESSAGES_PATH}",
                    content=body,
                    headers=self._headers(_cgp.MESSAGES_PATH, body),
                )
        except ClaudeGatewayError:
            raise
        except httpx.HTTPError as exc:
            raise _safe_gateway_http_error(exc) from None
        return self._decode_result(response)

    async def stream_message(
        self,
        request: ClaudeMessageRequest,
    ) -> AsyncGenerator[ClaudeStreamEvent, None]:
        self._require_config()
        body = self._body(request)
        terminal_seen = False
        usage_seen = False
        response_started = False

        def stream_error(code: str, status_code: int = 502) -> ClaudeGatewayError:
            return ClaudeGatewayError(
                code,
                status_code,
                usage_audit_required=response_started and not usage_seen,
            )

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=False,
                transport=self.http_transport,
            ) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}{_cgp.STREAM_PATH}",
                    content=body,
                    headers=self._headers(_cgp.STREAM_PATH, body),
                ) as response:
                    if response.status_code >= 400:
                        self._require_response_media_type(response, "application/json")
                        await response.aread()
                        try:
                            payload = response.json()
                        except Exception:
                            payload = None
                        raise self._error_from_payload(payload, response.status_code)
                    self._require_response_media_type(response, "application/x-ndjson")
                    response_started = True
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
                            raise error
                        else:
                            raise stream_error("GATEWAY_PROTOCOL_ERROR")
        except ClaudeGatewayError:
            raise
        except httpx.HTTPError as exc:
            raise _safe_gateway_http_error(
                exc,
                usage_audit_required=response_started and not usage_seen,
            ) from None
        if not terminal_seen or not usage_seen:
            raise stream_error("GATEWAY_STREAM_INCOMPLETE")


_CLAUDE_TRANSPORT: ClaudeTransport | None = None


def claude_transport_mode() -> str:
    return os.environ.get("NOTEAI_CLAUDE_TRANSPORT", "local").strip().lower() or "local"


def claude_transport_readiness() -> dict[str, Any]:
    mode = claude_transport_mode()
    if mode == "local":
        configured = bool(os.environ.get("ANTHROPIC_API_KEY"))
    elif mode == "gateway":
        configured = bool(
            _valid_gateway_base_url(os.environ.get("NOTEAI_CLAUDE_GATEWAY_URL", ""))
            and os.environ.get("NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID")
            and os.environ.get("NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET")
        )
    else:
        configured = False
    return {"mode": mode, "configured": configured, "supported": mode in {"local", "gateway"}}


def get_claude_transport() -> ClaudeTransport:
    global _CLAUDE_TRANSPORT
    if _CLAUDE_TRANSPORT is None:
        mode = claude_transport_mode()
        if mode == "local":
            _CLAUDE_TRANSPORT = LocalAnthropicTransport()
        elif mode == "gateway":
            _CLAUDE_TRANSPORT = GatewayClaudeTransport()
        else:
            raise ClaudeGatewayError("TRANSPORT_MODE_UNSUPPORTED", 503)
    return _CLAUDE_TRANSPORT


def set_claude_transport(transport: ClaudeTransport | None) -> None:
    """Install a transport implementation; None restores the local default."""
    global _CLAUDE_TRANSPORT
    _CLAUDE_TRANSPORT = transport


def _claude_timeout_seconds(task: str, thinking: bool, max_tokens: int) -> float:
    if thinking or max_tokens >= 4000:
        return CLAUDE_THINK_TIMEOUT_SECONDS
    if task == "semantic":
        return min(CLAUDE_FAST_TIMEOUT_SECONDS, 30.0)
    if task == "content_gen":
        return min(CLAUDE_FAST_TIMEOUT_SECONDS, 45.0)
    return CLAUDE_FAST_TIMEOUT_SECONDS


async def _call_model_with_retries(
    task: str,
    model_id: str,
    system: str,
    user: str,
    thinking: bool,
    max_tokens: int,
) -> str:
    attempts = MODEL_RETRY_ATTEMPTS
    last_err: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            t0 = time.monotonic()
            if model_id.startswith("claude"):
                sem = _get_semaphore("claude", CLAUDE_CONCURRENCY)
                async with sem:
                    result = await asyncio.wait_for(
                        _call_claude(model_id, system, user, thinking, max_tokens),
                        timeout=_claude_timeout_seconds(task, thinking, max_tokens),
                    )
            else:
                sem = _get_semaphore("kimi_text", KIMI_TEXT_CONCURRENCY)
                async with sem:
                    result = await _call_kimi(model_id, system, user, thinking, max_tokens)
            elapsed = time.monotonic() - t0
            _log(f"task={task} model={model_id} attempt={attempt}/{attempts} elapsed={elapsed:.1f}s chars={len(result)}")
            if not result:
                raise ValueError("empty response")
            return result
        except Exception as exc:
            last_err = exc
            retryable = _is_retryable(exc)
            _log(f"task={task} model={model_id} attempt={attempt}/{attempts} FAIL: {exc}")
            if attempt >= attempts or not retryable:
                raise
            await asyncio.sleep(MODEL_RETRY_BASE_DELAY * attempt)
    raise RuntimeError(f"[mr] retry loop exhausted for task={task} model={model_id}: {last_err}")


# ── Claude 非流式调用 ─────────────────────────────────────────────
async def _call_claude(
    model: str, system: str, user: str,
    thinking: bool = False, max_tokens: int = 1200,
) -> str:
    thinking_budget = None
    if thinking:
        thinking_budget = max(min(max_tokens - 1000, 10000), 1024)
    result = await get_claude_transport().create_message(ClaudeMessageRequest(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=({"role": "user", "content": user},),
        temperature=None if thinking else 0.7,
        thinking_budget=thinking_budget,
    ))
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
    """路由到对应模型，失败时走 fallback 链。返回文本字符串。"""
    routing = TASK_ROUTING.get(task, {"primary": KIMI_TEXT, "fallback": []})
    models_to_try = [routing["primary"]] + list(routing.get("fallback", []))

    last_err: Exception | None = None
    for model_id in models_to_try:
        try:
            return await _call_model_with_retries(task, model_id, system, user, thinking, max_tokens)
        except Exception as exc:
            _log(f"task={task} model={model_id} FAIL: {exc} → fallback")
            last_err = exc

    raise RuntimeError(f"[mr] all models failed for task={task}: {last_err}")


# ── Claude 流式调用 ───────────────────────────────────────────────
async def _claude_transport_stream(
    model: str,
    request: ClaudeMessageRequest,
) -> AsyncGenerator[ClaudeStreamEvent, None]:
    usage_recorded = False
    try:
        async for event in get_claude_transport().stream_message(request):
            if event.type == "usage":
                _record_claude_usage(model, event.usage)
                usage_recorded = True
            yield event
    except BaseException as exc:
        if (
            isinstance(exc, ClaudeGatewayError)
            and exc.usage_audit_required
            and not usage_recorded
        ):
            _record_claude_usage(model, None)
        raise


async def _stream_claude(
    model: str, system: str, user: str,
    thinking: bool = True, max_tokens: int = 16000,
    history: list[dict] | None = None,
) -> AsyncGenerator[tuple[str, str], None]:
    """流式调用 Claude，yield ('thinking', text) 或 ('content', text)。"""
    messages = list(history or []) + [{"role": "user", "content": user}]
    thinking_budget = None
    if thinking:
        thinking_budget = max(min(max_tokens - 2000, 10000), 1024)
    request = ClaudeMessageRequest(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=tuple(messages),
        temperature=None if thinking else 0.7,
        thinking_budget=thinking_budget,
    )
    async for event in _claude_transport_stream(model, request):
        if event.type in {"thinking", "content"}:
            yield (event.type, event.text)


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
    """路由到对应模型的流式接口。失败时 fallback 为非流式调用并整体 yield。
    yield: ('thinking', text) | ('content', text)
    """
    routing = TASK_ROUTING.get(task, {"primary": KIMI_TEXT, "fallback": []})
    primary  = routing["primary"]
    fallbacks = list(routing.get("fallback", []))

    try:
        if primary.startswith("claude"):
            async for chunk in _stream_claude(primary, system, user, thinking, max_tokens, history):
                yield chunk
        else:
            async for chunk in _stream_kimi(primary, system, user, thinking, max_tokens, history):
                yield chunk
        return
    except Exception as exc:
        _log(f"stream task={task} model={primary} FAIL: {exc} → fallback")

    # fallback: 依次尝试，降级为整块返回
    for fb_model in fallbacks:
        try:
            _log(f"stream task={task} fallback model={fb_model}")
            if fb_model.startswith("claude"):
                result = await _call_claude(fb_model, system, user, thinking=False, max_tokens=max_tokens)
            else:
                result = await _call_kimi(fb_model, system, user, thinking=False, max_tokens=max_tokens)
            if result:
                yield ("content", result)
                return
        except Exception as exc2:
            _log(f"stream task={task} fallback model={fb_model} FAIL: {exc2}")

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

    thinking_budget = (
        max(min(max_tokens - 2000, 10000), 1024)
        if thinking else None
    )
    request = ClaudeMessageRequest(
        model=CLAUDE_SONNET,
        max_tokens=max_tokens,
        system=system,
        messages=tuple(cleaned),
        temperature=None if thinking else 0.7,
        thinking_budget=thinking_budget,
    )

    try:
        async for event in _claude_transport_stream(CLAUDE_SONNET, request):
            if event.type in {"thinking", "content"}:
                yield (event.type, event.text)
    except Exception as exc:
        # fallback to Haiku non-streaming
        _log(f"stream_chat Sonnet FAIL: {exc} → Haiku fallback")
        try:
            user_text = user_content if isinstance(user_content, str) else str(user_content)
            result = await _call_claude(
                CLAUDE_HAIKU, system, user_text,
                thinking=False, max_tokens=min(max_tokens, 4096),
            )
            if result:
                yield ("content", result)
        except Exception as exc2:
            raise RuntimeError(f"[mr] stream_chat all failed: {exc2}") from exc2


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
    result = get_claude_transport().create_message_sync(ClaudeMessageRequest(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=tuple(messages),
        temperature=temperature,
        thinking_budget=thinking_budget,
    ))
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
