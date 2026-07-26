"""Allowlisted observability helpers for secrets and user-controlled text."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


_SENSITIVE_KEY_FRAGMENTS = (
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
    "prompt",
    "body",
    "content",
    "reasoning",
    "thinking",
    "url",
    "email",
    "phone",
)
_CRAWLER_ALLOWED_KEYS = {
    "action",
    "ts",
    "status",
    "stage",
    "attempt",
    "attempt_count",
    "processed",
    "success",
    "failed",
    "pending",
    "duration_ms",
    "error_code",
    "exit_reason",
}
_LOG_EVENT_CODES = {
    "auth",
    "billing",
    "chat",
    "crawler",
    "database",
    "generate",
    "kimi_chat",
    "kimi_stream_gen",
    "kimi_video_understand",
    "model_artifacts",
    "moonshot_http",
    "moonshot_network",
    "provider",
    "score_lift",
    "service_log",
    "training",
    "video_file",
}
_SAFE_FAILURE_FACTS = {
    "attempt",
    "duration_ms",
    "exit_code",
    "http_status",
    "item_count",
    "phase",
    "provider",
    "status",
}


def stable_error_code(exc: BaseException) -> str:
    name = re.sub(r"[^a-z0-9]+", "_", type(exc).__name__.lower()).strip("_")
    return name or "operation_error"


def redact_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)bearer\s+[a-z0-9._~+/=-]+", "Bearer [REDACTED]", text)
    text = re.sub(r"(?i)(cookie|password|secret|token|api[_-]?key)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", text)
    text = re.sub(
        r'(?i)(["\'](?:cookie|password|secret|token|api[_-]?key)["\']\s*:\s*)'
        r'(["\']).*?\2',
        r'\1"[REDACTED]"',
        text,
    )
    text = re.sub(r"data:[^;,]+;base64,[A-Za-z0-9+/=]+", "data:[REDACTED]", text)
    text = re.sub(r"https?://[^\s]+", "[URL_REDACTED]", text)
    text = re.sub(r"\b1[3-9]\d{9}\b", "[PHONE_REDACTED]", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[EMAIL_REDACTED]", text)
    return text[:500]


def sanitize_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if any(fragment in normalized for fragment in _SENSITIVE_KEY_FRAGMENTS):
                continue
            safe[str(key)] = sanitize_mapping(item)
        return safe
    if isinstance(value, list):
        return [sanitize_mapping(item) for item in value[:100]]
    if isinstance(value, tuple):
        return [sanitize_mapping(item) for item in value[:100]]
    if isinstance(value, str):
        return redact_text(value)
    return value


def sanitize_crawler_event(event: Any) -> dict[str, Any]:
    if not isinstance(event, dict):
        return {"action": "malformed_event"}
    result = {
        key: (
            redact_text(event[key])[:120]
            if isinstance(event[key], str)
            else event[key]
        )
        for key in _CRAWLER_ALLOWED_KEYS
        if key in event and not isinstance(event[key], (dict, list, tuple))
    }
    result["action"] = str(result.get("action") or "crawler_event")[:80]
    if event.get("error") and not result.get("error_code"):
        result["error_code"] = "crawler_operation_failed"
    return result


def safe_failure_event(
    event_code: str,
    exc: BaseException | None = None,
    **facts: Any,
) -> dict[str, Any]:
    normalized = re.sub(
        r"[^a-z0-9_]+",
        "_",
        str(event_code or "operation_failed").strip().lower(),
    ).strip("_")[:64]
    result: dict[str, Any] = {
        "event_code": normalized or "operation_failed",
        "error_code": stable_error_code(exc) if exc else "operation_failed",
    }
    for key, value in facts.items():
        if key not in _SAFE_FAILURE_FACTS:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[key] = value
    return result


def summarize_process_output(value: bytes | str | None) -> dict[str, Any]:
    raw = (
        value
        if isinstance(value, bytes)
        else str(value or "").encode("utf-8", errors="replace")
    )
    return {
        "byte_count": len(raw),
        "line_count": len(raw.splitlines()),
        "output_hash": hashlib.sha256(raw).hexdigest()[:16],
        "raw_text_included": False,
    }


def summarize_log_lines(path: Path, lines: int) -> dict[str, Any]:
    capped = max(1, min(int(lines or 100), 500))
    raw_lines = path.read_text(errors="replace").splitlines()[-capped:]
    events: list[dict[str, str]] = []
    counts = {"error": 0, "warning": 0, "info": 0}
    for raw in raw_lines:
        lowered = raw.lower()
        level = "error" if ("error" in lowered or "failed" in lowered) else (
            "warning" if ("warn" in lowered or "retry" in lowered) else "info"
        )
        counts[level] += 1
        marker = re.search(r"\[([A-Za-z0-9_.:-]{1,64})\]", raw)
        candidate = (
            marker.group(1).lower().replace(":", "_").replace("-", "_")
            if marker
            else "service_log"
        )
        event_code = candidate if candidate in _LOG_EVENT_CODES else "service_log"
        events.append({
            "level": level,
            "event_code": event_code,
            "line_hash": hashlib.sha256(
                f"{level}:{event_code}".encode("utf-8")
            ).hexdigest()[:12],
        })
    return {
        "source": path.name,
        "line_count": len(raw_lines),
        "counts": counts,
        "events": events,
        "raw_text_included": False,
    }


def sanitize_json_text(value: str) -> str:
    try:
        return json.dumps(sanitize_mapping(json.loads(value)), ensure_ascii=False)
    except (TypeError, ValueError, json.JSONDecodeError):
        return json.dumps({"event_code": "unparseable_payload"}, ensure_ascii=False)
