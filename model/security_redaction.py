"""Allowlisted observability helpers for secrets and user-controlled text."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
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
    "attempted",
    "claimed",
    "limit",
    "processed",
    "provider_calls",
    "released",
    "run_id",
    "success",
    "failed",
    "pending",
    "duration_ms",
    "error_code",
    "exit_reason",
    "track_ref",
    "write_count",
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
    diagnostics = sanitize_xhs_response_diagnostics(event.get("response_diagnostics"))
    if diagnostics:
        result["response_diagnostics"] = diagnostics
    return result


# Fixed concepts only: upstream messages and arbitrary string codes are never
# copied into logs, even when they contain an unrecognized credential format.
_XHS_MESSAGE_MARKERS = {
    "login": ("login", "登录", "未登陆", "session expired"),
    "challenge": ("captcha", "challenge", "验证码", "滑块", "人机验证", "安全验证"),
    "risk": ("risk control", "风控", "账号异常"),
    "access_restricted": ("access denied", "forbidden", "访问受限", "无权限", "禁止访问"),
    "rate_limit": ("too many", "rate limit", "cooldown", "频繁", "访问过快"),
    "signature": ("invalid signature", "signature error", "签名错误", "签名无效"),
    "invalid_parameter": ("invalid param", "参数错误", "参数异常", "参数无效"),
    "not_found": ("not found", "不存在", "已删除"),
    "server_error": ("server error", "service unavailable", "系统错误", "系统异常", "服务异常"),
}


def xhs_response_diagnostics(status: int, payload: Any, *, json_decoded: bool = True) -> dict[str, Any]:
    """Project response metadata without retaining body, messages or headers."""
    result: dict[str, Any] = {"http_status": status, "payload_kind": "non_json"}
    if json_decoded:
        result["payload_kind"] = (
            "object" if isinstance(payload, dict) else
            "array" if isinstance(payload, list) else "scalar"
        )
    if isinstance(payload, dict) and json_decoded:
        success = payload.get("success")
        result["success_state"] = (
            "true" if success is True else "false" if success is False else
            "absent" if "success" not in payload else "other"
        )
        for prefix, obj in (("business", payload), ("nested_business", payload.get("data"))):
            if not isinstance(obj, dict):
                continue
            code = obj.get("code")
            numeric = (
                type(code) is int and abs(code) <= 999999999 or
                isinstance(code, str) and re.fullmatch(r"-?[0-9]{1,9}", code) is not None
            )
            result[prefix + "_code_kind"] = (
                "absent" if "code" not in obj else "null" if code is None else
                "integer" if numeric and type(code) is int else
                "numeric_string" if numeric else "omitted"
            )
            if numeric:
                result[prefix + "_code"] = code
        objects = [payload]
        if isinstance(payload.get("data"), dict):
            objects.append(payload["data"])
        messages = [obj[key][:1000].lower() for obj in objects
                    for key in ("msg", "message") if isinstance(obj.get(key), str)]
        result["message_present"] = bool(messages)
        result["message_tags"] = sorted(
            tag for tag, markers in _XHS_MESSAGE_MARKERS.items()
            if any(marker in message for marker in markers for message in messages)
        )
    return sanitize_xhs_response_diagnostics(result)


def sanitize_xhs_response_diagnostics(value: Any) -> dict[str, Any]:
    """Recheck even exception-supplied metadata at each persistence boundary."""
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    status = value.get("http_status")
    if type(status) is int and 100 <= status <= 599:
        result["http_status"] = status
    for key, choices in (
        ("payload_kind", {"non_json", "object", "array", "scalar"}),
        ("success_state", {"true", "false", "absent", "other"}),
        ("business_code_kind", {"absent", "null", "integer", "numeric_string", "omitted"}),
        ("nested_business_code_kind", {"absent", "null", "integer", "numeric_string", "omitted"}),
    ):
        item = value.get(key)
        if isinstance(item, str) and item in choices:
            result[key] = item
    for key in ("business_code", "nested_business_code"):
        item = value.get(key)
        if type(item) is int and abs(item) <= 999999999:
            result[key] = item
        elif isinstance(item, str) and re.fullmatch(r"-?[0-9]{1,9}", item):
            result[key] = item
    if type(value.get("message_present")) is bool:
        result["message_present"] = value["message_present"]
    if isinstance(value.get("message_tags"), list):
        result["message_tags"] = sorted({tag for tag in value["message_tags"]
                                         if isinstance(tag, str) and tag in _XHS_MESSAGE_MARKERS})
    return result


def sanitize_xhs_http_event(value: Any) -> dict[str, Any]:
    """Strict fixed projection for physical HTTP observations, never raw headers."""
    if not isinstance(value, dict):
        return {}
    phase, kind, sequence, at = (value.get(k) for k in ("phase", "request_kind", "sequence", "at"))
    if phase not in {"dispatch", "response", "unknown"} or kind not in {"dsl", "session", "detail"}:
        return {}
    if type(sequence) is not int or not 1 <= sequence <= 3:
        return {}
    if not isinstance(at, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+\+00:00", at):
        return {}
    result = {"phase": phase, "request_kind": kind, "sequence": sequence, "at": at}
    for key in ("request_body_bytes", "response_bytes"):
        item = value.get(key)
        if type(item) is int and 0 <= item <= 2 * 1024 * 1024:
            result[key] = item
    if phase == "response":
        result["response_diagnostics"] = sanitize_xhs_response_diagnostics(value.get("response_diagnostics"))
    return result


_TRENDS_REQUEST_KINDS = frozenset({
    "dsl", "session", "homefeed", "search_recommend", "search_notes",
})
_TRENDS_FAILURE_CODES = frozenset({
    "login_required", "login_or_challenge_required", "server_session_logged_out",
    "challenge", "cooldown", "access_restricted", "collection_suspended",
    "runtime_role_not_allowed", "adapter_not_selected", "collection_safety_unavailable",
    "remote_http_error", "remote_schema_error", "remote_business_error",
    "remote_non_json", "remote_response_too_large", "network_error",
    "signer_unavailable", "signer_failed", "signer_invalid_response",
    "operation_not_allowed", "invalid_session_signing_state",
    "trends_provider_admission_failed", "trends_provider_finalize_failed",
    "trends_v5_budget_required", "signer_input_limit", "session_identity_unproven",
    "signing_context_expired",
})


def sanitize_trends_http_event(value: Any) -> dict[str, Any]:
    """Trends-only physical observations; keep the Tracking three-call shape intact."""
    if not isinstance(value, dict):
        return {}
    phase, kind, sequence = (value.get(k) for k in ("phase", "request_kind", "sequence"))
    if (not isinstance(phase, str) or phase not in {"dispatch", "response", "unknown"}
            or not isinstance(kind, str) or kind not in _TRENDS_REQUEST_KINDS
            or type(sequence) is not int or not 1 <= sequence <= 36):
        return {}
    # Reuse the existing strict timestamp/size/response projection without
    # widening the separate owned-note observer's allowed operations or budget.
    projected = sanitize_xhs_http_event({**value, "request_kind": "session", "sequence": 1})
    if projected:
        try:
            if datetime.fromisoformat(projected["at"]).utcoffset() != timezone.utc.utcoffset(None):
                return {}
        except ValueError:
            return {}
        projected.update(request_kind=kind, sequence=sequence)
    return projected


def sanitize_trends_failure(value: Any) -> dict[str, Any]:
    """Fixed adapter classification plus response facts; never exception text."""
    if not isinstance(value, dict):
        return {}
    code = value.get("error_code")
    stage = value.get("stage")
    return {
        "error_code": code if isinstance(code, str) and code in _TRENDS_FAILURE_CODES else "adapter_failure_unknown",
        "stage": stage if isinstance(stage, str) and stage in _TRENDS_REQUEST_KINDS else "preflight",
        "response_diagnostics": sanitize_xhs_response_diagnostics(value.get("response_diagnostics")),
    }


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
