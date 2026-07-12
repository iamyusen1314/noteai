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
import json
import os
import sys
import time
from typing import AsyncGenerator

import anthropic
import httpx

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
_claude_client: anthropic.AsyncAnthropic | None = None

def _get_claude() -> anthropic.AsyncAnthropic:
    global _claude_client
    if _claude_client is None:
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        _claude_client = anthropic.AsyncAnthropic(api_key=key)
    return _claude_client


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
    client = _get_claude()
    kwargs: dict = {
        "model":    model,
        "max_tokens": max_tokens,
        "system":   system,
        "messages": [{"role": "user", "content": user}],
    }
    if thinking:
        budget = min(max_tokens - 1000, 10000)
        budget = max(budget, 1024)
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
    else:
        kwargs["temperature"] = 0.7

    response = await client.messages.create(**kwargs)
    _record_claude_usage(model, getattr(response, "usage", None))
    parts: list[str] = []
    for block in response.content:
        if block.type == "text":
            parts.append(block.text)
    return "".join(parts).strip()


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
async def _stream_claude(
    model: str, system: str, user: str,
    thinking: bool = True, max_tokens: int = 16000,
    history: list[dict] | None = None,
) -> AsyncGenerator[tuple[str, str], None]:
    """流式调用 Claude，yield ('thinking', text) 或 ('content', text)。"""
    client = _get_claude()
    messages = list(history or []) + [{"role": "user", "content": user}]
    kwargs: dict = {
        "model":    model,
        "max_tokens": max_tokens,
        "system":   system,
        "messages": messages,
    }
    if thinking:
        budget = min(max_tokens - 2000, 10000)
        budget = max(budget, 1024)
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
    else:
        kwargs["temperature"] = 0.7

    async with client.messages.stream(**kwargs) as stream_ctx:
        async for event in stream_ctx:
            if event.type == "content_block_delta":
                delta = event.delta
                if delta.type == "thinking_delta":
                    yield ("thinking", delta.thinking)
                elif delta.type == "text_delta":
                    yield ("content", delta.text)
        try:
            final_message = stream_ctx.get_final_message()
            if inspect.isawaitable(final_message):
                final_message = await final_message
            _record_claude_usage(model, getattr(final_message, "usage", None))
        except Exception:
            pass


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
    client = _get_claude()
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

    kwargs: dict = {
        "model":    CLAUDE_SONNET,
        "max_tokens": max_tokens,
        "system":   system,
        "messages": cleaned,
    }
    if thinking:
        budget = min(max_tokens - 2000, 10000)
        budget = max(budget, 1024)
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
    else:
        kwargs["temperature"] = 0.7

    try:
        async with client.messages.stream(**kwargs) as stream_ctx:
            async for event in stream_ctx:
                if event.type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "thinking_delta":
                        yield ("thinking", delta.thinking)
                    elif delta.type == "text_delta":
                        yield ("content", delta.text)
            try:
                final_message = stream_ctx.get_final_message()
                if inspect.isawaitable(final_message):
                    final_message = await final_message
                _record_claude_usage(CLAUDE_SONNET, getattr(final_message, "usage", None))
            except Exception:
                pass
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


# ── semantic 专用（同步包装，供 asyncio.to_thread 调用） ─────────
def call_semantic_sync(system: str, user: str, max_tokens: int = 300) -> str:
    """在线程池（asyncio.to_thread）中同步调用 Claude Haiku 做语义评分。
    使用同步客户端避免 asyncio.run 在子线程中嵌套事件循环的问题。
    """
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    client = anthropic.Anthropic(api_key=key)
    response = client.messages.create(
        model=CLAUDE_HAIKU,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        temperature=0.3,
    )
    _record_claude_usage(CLAUDE_HAIKU, getattr(response, "usage", None))
    parts = [block.text for block in response.content if block.type == "text"]
    return "".join(parts).strip()


# ── 日志 ──────────────────────────────────────────────────────────
def _log(msg: str) -> None:
    print(f"[mr] {msg}", file=sys.stderr, flush=True)
