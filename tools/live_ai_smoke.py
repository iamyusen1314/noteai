#!/usr/bin/env python3
"""Controlled one-call live AI smoke test.

This script intentionally bypasses NoteAI's generation pipeline so a live
provider smoke cannot fan out into many model calls. It does not write to the
application database and never prints secrets or model content.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import anthropic
import httpx
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
MODEL_ENV = ROOT / "model" / ".env"

CLAUDE_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
KIMI_DEFAULT_MODEL = "kimi-k2.6"
KIMI_API_URL = "https://api.moonshot.cn/v1/chat/completions"

DEFAULT_PROMPT = (
    "Reply with exactly this Chinese phrase and nothing else: "
    "NoteAI live smoke ok"
)


def _redact_error(value: str) -> str:
    text = value or ""
    text = re.sub(r"Bearer\s+[A-Za-z0-9._\-]+", "Bearer [REDACTED]", text)
    text = re.sub(r"(api[_-]?key['\"]?\s*[:=]\s*)['\"]?[^'\"\s,}]+", r"\1[REDACTED]", text, flags=re.I)
    text = re.sub(r"(authorization['\"]?\s*[:=]\s*)['\"]?[^'\"\s,}]+", r"\1[REDACTED]", text, flags=re.I)
    return text[:500]


def _usage_value(usage: Any, key: str) -> int:
    if usage is None:
        return 0
    if isinstance(usage, dict):
        return int(usage.get(key, 0) or 0)
    return int(getattr(usage, key, 0) or 0)


def _pick_provider(requested: str) -> str:
    if requested != "auto":
        return requested
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude"
    if os.environ.get("MOONSHOT_API_KEY"):
        return "kimi"
    raise RuntimeError("No supported provider key is present")


def _call_claude(model: str, prompt: str, max_tokens: int, timeout: float) -> dict[str, Any]:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")

    client = anthropic.Anthropic(api_key=key, timeout=timeout, max_retries=0)
    t0 = time.monotonic()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system="You are a minimal connectivity smoke-test responder.",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    elapsed_ms = round((time.monotonic() - t0) * 1000)
    usage = getattr(response, "usage", None)
    content_chars = 0
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", "") == "text":
            content_chars += len(getattr(block, "text", "") or "")
    return {
        "provider": "claude",
        "model": model,
        "success": True,
        "elapsed_ms": elapsed_ms,
        "input_tokens": (
            _usage_value(usage, "input_tokens")
            + _usage_value(usage, "cache_creation_input_tokens")
            + _usage_value(usage, "cache_read_input_tokens")
        ),
        "output_tokens": _usage_value(usage, "output_tokens"),
        "content_chars": content_chars,
    }


def _call_kimi(model: str, prompt: str, max_tokens: int, timeout: float) -> dict[str, Any]:
    key = os.environ.get("MOONSHOT_API_KEY", "")
    if not key:
        raise RuntimeError("MOONSHOT_API_KEY is not configured")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a minimal connectivity smoke-test responder."},
            {"role": "user", "content": prompt},
        ],
        "thinking": {"type": "disabled"},
        "temperature": 0.6,
        "max_tokens": max_tokens,
    }
    t0 = time.monotonic()
    with httpx.Client(timeout=httpx.Timeout(timeout)) as client:
        response = client.post(
            KIMI_API_URL,
            json=payload,
            headers={"Authorization": f"Bearer {key}"},
        )
        response.raise_for_status()
        data = response.json()
    elapsed_ms = round((time.monotonic() - t0) * 1000)
    usage = data.get("usage") if isinstance(data, dict) else {}
    text = ""
    try:
        text = data["choices"][0]["message"]["content"] or ""
    except Exception:
        text = ""
    return {
        "provider": "kimi",
        "model": model,
        "success": True,
        "elapsed_ms": elapsed_ms,
        "input_tokens": _usage_value(usage, "prompt_tokens"),
        "output_tokens": _usage_value(usage, "completion_tokens"),
        "content_chars": len(text),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one controlled live AI provider smoke call.")
    parser.add_argument("--provider", choices=["auto", "claude", "kimi"], default="auto")
    parser.add_argument("--model", default="", help="Override provider model id.")
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.max_tokens < 1 or args.max_tokens > 256:
        print(json.dumps({"success": False, "error": "max_tokens must be between 1 and 256"}, ensure_ascii=False))
        return 2

    load_dotenv(MODEL_ENV)
    try:
        provider = _pick_provider(args.provider)
        model = args.model or (CLAUDE_DEFAULT_MODEL if provider == "claude" else KIMI_DEFAULT_MODEL)
        if provider == "claude":
            result = _call_claude(model, args.prompt, args.max_tokens, args.timeout)
        else:
            result = _call_kimi(model, args.prompt, args.max_tokens, args.timeout)
        result["calls"] = 1
        result["db_writes"] = False
        result["content_printed"] = False
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        provider = args.provider if args.provider != "auto" else "auto"
        result = {
            "provider": provider,
            "success": False,
            "calls": 1,
            "db_writes": False,
            "content_printed": False,
            "error_type": type(exc).__name__,
            "error_summary": _redact_error(str(exc)),
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
