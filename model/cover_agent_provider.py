"""One metered Ark chat call for the cover Skill host, never an Agent loop.

The caller owns the cover lease, durable intent and tool execution. This adapter
owns one shared physical permit, reservation, transport and usage receipt. Full
chat/tool JSON is returned in memory; prompts, reasoning and image bytes are not
persisted by this module. No provider retry, fallback or explicit cache is used.

Wire/pricing references (2026-10-22):
https://ark.volcengine.com/region:cn-beijing/docs/chat-api.md
https://ark.volcengine.com/region:cn-beijing/docs/deep-thinking.md
https://ark.volcengine.com/region:cn-beijing/docs/image-understanding.md
https://ark.volcengine.com/region:cn-beijing/docs/model-pricing.md
"""
from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, ROUND_CEILING
import io
import json
import logging
import math
import re
import sqlite3
import time

import httpx
from PIL import Image

import ark_media
import billing
import db
import model_router
import public_product


MODEL = "doubao-seed-2-1-pro-260915"
PRICE_VERSION = "ark-public-seed-2-1-pro-260915-2026-10-22"
MAX_INPUT_TOKENS = 131072
MAX_OUTPUT_TOKENS = 65536  # Includes reasoning, unlike Chat max_tokens.
QC_OUTPUT_TOKENS = 32768
COMPACTION_OUTPUT_TOKENS = 8192
SDK_CONTEXT_TOKENS = 262144
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
# Nonstream Pro thinking can exceed the shared media client's 240-second read.
# Keep a cover-only ceiling and leave room for connection/upload and settlement.
READ_TIMEOUT_SECONDS = 900
REQUEST_MARGIN_SECONDS = 140
_NAME = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_MODEL_NAME = re.compile(r"[A-Za-z0-9_.:-]{1,100}\Z")
_KEYS = {"model", "messages", "tools", "tool_choice", "parallel_tool_calls",
    "max_tokens", "max_completion_tokens", "thinking", "reasoning_effort",
    "stream", "temperature", "top_p", "presence_penalty", "frequency_penalty",
    "response_format", "seed", "service_tier"}
_INPUT_DIAGNOSTIC_KEYS = frozenset({"text_bytes", "image_count", "image_tokens",
    "message_count", "tool_count", "framing_tokens", "total_bound", "max_input_tokens"})
_TEXT_BREAKDOWN_KEYS = frozenset({"system_content_bytes", "user_content_bytes",
    "assistant_content_bytes", "reasoning_content_bytes", "encrypted_content_bytes",
    "tool_arguments_bytes", "tool_result_bytes", "tool_schema_bytes", "other_json_bytes"})
_OUTPUT_DIAGNOSTIC_KEYS = frozenset({"finish_reason", "completion_tokens",
    "max_completion_tokens", "reasoning_tokens"})
_OUTPUT_FINISH_REASONS = frozenset({"length", "content_filter", "stop", "tool_calls", "other", "missing"})
_RESERVATION_DIAGNOSTIC_KEYS = frozenset({"phase", "exception_type", "sqlite_errorcode",
    "os_errno", "call_id", "reserve_milli_cny"})
_RESERVATION_EXCEPTION_TYPES = frozenset({"OperationalError", "IntegrityError", "DatabaseError",
    "OSError", "RuntimeError", "OtherError"})
_HTTP_FAILURE_PROVIDER_CODES = frozenset({"AuthenticationError", "InvalidAccountStatus"})


def _http_failure_metadata(response):
    """Project only fixed categories and an existing official response identifier."""
    if type(response.status_code) is not int or not 100 <= response.status_code <= 599 or response.status_code == 200:
        raise ValueError("invalid HTTP failure metadata status")
    request_id = response.headers.get("x-request-id") or response.headers.get("x-tt-logid")
    if type(request_id) is not str or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", request_id):
        request_id = None
    result = {"event_code": "cover_agent_http_failure", "http_status": response.status_code,
        "body_kind": "non_json", "provider_code": "OTHER", "provider_request_id": request_id}
    if len(response.content) > 16 * 1024:
        result["body_kind"] = "too_large"
    else:
        try:
            value = json.loads(response.content)
            error = value.get("error") if type(value) is dict else None
            result["body_kind"] = "json_error" if type(error) is dict else "json_other"
            code = error.get("code") if type(error) is dict else None
            if type(code) is str and code in _HTTP_FAILURE_PROVIDER_CODES:
                result["provider_code"] = code
        except (ValueError, TypeError, RecursionError):
            pass
    return result


class CoverAgentProviderError(public_product.TrialProviderStopped):
    def __init__(self, code, *, outcome_unknown=False, call_id=None, input_diagnostics=None,
                 output_diagnostics=None, reservation_diagnostics=None):
        self.code = code
        self.outcome_unknown = bool(outcome_unknown)
        self.call_id = call_id
        self.input_diagnostics = validated_input_diagnostics(input_diagnostics)
        self.output_diagnostics = validated_output_diagnostics(output_diagnostics)
        self.reservation_diagnostics = None
        try:
            self.reservation_diagnostics = validated_reservation_diagnostics(reservation_diagnostics)
        except Exception:
            pass  # Optional diagnostics cannot replace the original provider stop.
        super().__init__(code)


def validated_reservation_diagnostics(value):
    """A fixed, content-free projection of a pre-transport reservation failure."""
    if (type(value) is not dict or any(type(key) is not str for key in value)
            or set(value) != _RESERVATION_DIAGNOSTIC_KEYS
            or type(value["phase"]) is not str or value["phase"] != "reservation"
            or type(value["exception_type"]) is not str
            or value["exception_type"] not in _RESERVATION_EXCEPTION_TYPES
            or type(value["call_id"]) is not str or not _NAME.fullmatch(value["call_id"])
            or type(value["reserve_milli_cny"]) is not int
            or not 0 <= value["reserve_milli_cny"] <= 10**9
            or any(item is not None and (type(item) is not int or not 0 <= item <= 65535)
                   for item in (value["sqlite_errorcode"], value["os_errno"]))):
        return None
    return dict(value)


def _reservation_diagnostics(error, call_id, reserve):
    try:
        if isinstance(error, sqlite3.OperationalError):
            kind = "OperationalError"
        elif isinstance(error, sqlite3.IntegrityError):
            kind = "IntegrityError"
        elif isinstance(error, sqlite3.DatabaseError):
            kind = "DatabaseError"
        elif isinstance(error, OSError):
            kind = "OSError"
        elif isinstance(error, RuntimeError):
            kind = "RuntimeError"
        else:
            kind = "OtherError"
        return validated_reservation_diagnostics({"phase": "reservation", "exception_type": kind,
            "sqlite_errorcode": getattr(error, "sqlite_errorcode", None)
                if isinstance(error, sqlite3.DatabaseError) else None,
            "os_errno": getattr(error, "errno", None) if isinstance(error, OSError) else None,
            "call_id": call_id, "reserve_milli_cny": reserve})
    except Exception:
        return None  # Reading a hostile exception attribute must not mask its original stop.


def validated_input_diagnostics(value):
    """Only bounded, internally consistent integers may survive error cleanup."""
    if (not isinstance(value, dict) or not _INPUT_DIAGNOSTIC_KEYS.issubset(value)
            or set(value) - _INPUT_DIAGNOSTIC_KEYS - {"text_breakdown"}
            or any(type(value[key]) is not int or not 0 <= value[key] < 2**63
                   for key in _INPUT_DIAGNOSTIC_KEYS)
            or not 1 <= value["message_count"] <= 128 or not 0 <= value["tool_count"] <= 128
            or value["max_input_tokens"] != MAX_INPUT_TOKENS
            or value["framing_tokens"] != 128 * (value["message_count"] + value["tool_count"]) + 1024
            or value["total_bound"] != value["text_bytes"] + value["image_tokens"] + value["framing_tokens"]
            or not 257 * value["image_count"] <= value["image_tokens"] <= 5376 * value["image_count"]):
        return None
    result = {key: value[key] for key in _INPUT_DIAGNOSTIC_KEYS}
    breakdown = validated_text_breakdown(value.get("text_breakdown"), value["text_bytes"])
    if breakdown is not None:
        result["text_breakdown"] = breakdown
    return result


def validated_text_breakdown(value, text_bytes):
    """Optional byte counts only; invalid detail cannot hide the original stop."""
    if (type(value) is not dict or set(value) != _TEXT_BREAKDOWN_KEYS
            or any(type(item) is not int or not 0 <= item < 2**63 for item in value.values())
            or sum(value.values()) != text_bytes):
        return None
    return dict(value)


def validated_output_diagnostics(value):
    """Keep only a fixed finish classification and non-secret token counts."""
    if (not isinstance(value, dict) or set(value) != _OUTPUT_DIAGNOSTIC_KEYS
            or not isinstance(value["finish_reason"], str) or value["finish_reason"] not in _OUTPUT_FINISH_REASONS
            or type(value["completion_tokens"]) is not int or not 0 <= value["completion_tokens"] < 2**63
            or type(value["max_completion_tokens"]) is not int
            or not 1 <= value["max_completion_tokens"] <= MAX_OUTPUT_TOKENS
            or (value["reasoning_tokens"] is not None and (type(value["reasoning_tokens"]) is not int
                or not 0 <= value["reasoning_tokens"] <= value["completion_tokens"]))):
        return None
    return dict(value)


def _output_diagnostics(data, body):
    usage = data.get("usage") if isinstance(data, dict) else None
    if not isinstance(usage, dict):
        return None
    choices = data.get("choices")
    finish = choices[0].get("finish_reason") if (isinstance(choices, list) and len(choices) == 1
        and isinstance(choices[0], dict)) else None
    finish = finish if isinstance(finish, str) and finish in _OUTPUT_FINISH_REASONS - {"other", "missing"} else (
        "missing" if finish is None else "other")
    details = usage.get("completion_tokens_details")
    reasoning = details.get("reasoning_tokens") if isinstance(details, dict) else None
    completion = usage.get("completion_tokens")
    if (type(reasoning) is not int or type(completion) is not int
            or not 0 <= reasoning <= completion):
        reasoning = None
    return validated_output_diagnostics({"finish_reason": finish, "completion_tokens": completion,
        "max_completion_tokens": body.get("max_completion_tokens"), "reasoning_tokens": reasoning})


def _text_breakdown(measured, text_bytes):
    # Partition disjoint JSON values, including their escaping/quotes. Image
    # URLs have already been blanked by the existing meter. The remainder owns
    # keys, separators, roles, tool IDs and request options, never their values.
    result = dict.fromkeys(_TEXT_BREAKDOWN_KEYS, 0)
    size = lambda value: len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())
    content_keys = {"system": "system_content_bytes", "developer": "system_content_bytes",
        "user": "user_content_bytes", "assistant": "assistant_content_bytes", "tool": "tool_result_bytes"}
    for message in measured["messages"]:
        if "content" in message:
            result[content_keys[message["role"]]] += size(message["content"])
        for field in ("reasoning_content", "encrypted_content"):
            if field in message:
                result[field + "_bytes"] += size(message[field])
        calls = message.get("tool_calls")
        for call in calls if isinstance(calls, list) else []:
            function = call.get("function") if isinstance(call, dict) else None
            if isinstance(function, dict) and "arguments" in function:
                result["tool_arguments_bytes"] += size(function["arguments"])
    if "tools" in measured:
        result["tool_schema_bytes"] = size(measured["tools"])
    result["other_json_bytes"] = text_bytes - sum(result.values())
    return validated_text_breakdown(result, text_bytes)


def _measure_input(body, image_tokens, image_count):
    """The existing admission arithmetic, without retaining any request content."""
    measured = deepcopy(body)
    for message in measured["messages"]:
        if isinstance(message.get("content"), list):
            for part in message["content"]:
                if part.get("type") == "image_url":
                    part["image_url"]["url"] = ""
    text_bytes = len(json.dumps(measured, ensure_ascii=False, separators=(",", ":")).encode())
    message_count, tool_count = len(body["messages"]), len(body.get("tools", []))
    framing = 128 * (message_count + tool_count) + 1024
    result = {"text_bytes": text_bytes, "image_count": image_count, "image_tokens": image_tokens,
        "message_count": message_count, "tool_count": tool_count, "framing_tokens": framing,
        "total_bound": text_bytes + image_tokens + framing, "max_input_tokens": MAX_INPUT_TOKENS}
    try:
        breakdown = _text_breakdown(measured, text_bytes)
    except Exception:
        breakdown = None  # Optional attribution must not change hard admission.
    if breakdown is not None:
        result["text_breakdown"] = breakdown
    return result


def pricing(prompt_tokens: int) -> dict:
    """Standard catalogue CNY/million, not the account's final supplier bill.

    Billing can price an unexpected over-bound response without losing its real
    usage. The smaller 128k admission bound is enforced separately below.
    """
    if type(prompt_tokens) is not int or not 0 <= prompt_tokens <= 1048576:
        raise ValueError("cover agent pricing input is outside the model context")
    return {"input": 6.0, "cache_read": 1.2, "output": 30.0,
            "audio_input": None, "audio_cache_read": None}


def estimate(max_completion_tokens=MAX_OUTPUT_TOKENS) -> dict:
    if type(max_completion_tokens) is not int or not 1 <= max_completion_tokens <= MAX_OUTPUT_TOKENS:
        raise ValueError("cover agent estimate output bound is invalid")
    amount = (Decimal(MAX_INPUT_TOKENS) * Decimal("6")
        + Decimal(max_completion_tokens) * Decimal("30")) / Decimal(1000000)
    return {"provider": "doubao", "model_id": MODEL, "currency": "CNY",
        "input_token_bound": MAX_INPUT_TOKENS, "output_token_bound": max_completion_tokens,
        "estimated_cost": str(amount), "actual_cost": None,
        "price_version": PRICE_VERSION, "cost_status": "upper_estimate"}


def _invalid(code="COVER_AGENT_INPUT_INVALID"):
    raise CoverAgentProviderError(code)


def _image_tokens(image):
    if (not isinstance(image, dict) or set(image) - {"url", "detail", "image_pixel_limit"}
            or image.get("detail", "high") not in {"low", "high", "xhigh"}):
        _invalid("COVER_AGENT_IMAGE_INVALID")
    value = image.get("url")
    if not isinstance(value, str) or not value.startswith("data:image/"):
        _invalid("COVER_AGENT_IMAGE_INLINE_REQUIRED")
    try:
        prefix, encoded = value.split(",", 1)
        if prefix not in {"data:image/png;base64", "data:image/jpeg;base64", "data:image/webp;base64"}:
            raise ValueError()
        if len(encoded) > math.ceil(ark_media.MAX_IMAGE_BYTES / 3) * 4:
            raise ValueError()
        raw = base64.b64decode(encoded, validate=True)
        if not raw or len(raw) >= ark_media.MAX_IMAGE_BYTES:
            raise ValueError()
        with Image.open(io.BytesIO(raw)) as photo:
            width, height = photo.size
            if (Image.MIME.get(photo.format) != prefix[5:-7] or width <= 14 or height <= 14
                    or not 196 <= width * height <= 36000000 or not 1/150 <= width/height <= 150):
                raise ValueError()
            photo.verify()
    except Exception:
        _invalid("COVER_AGENT_IMAGE_INVALID")
    # Explicit limits prevent default detail modes from upscaling a small image
    # beyond the admitted bound. Original image bytes are never modified here.
    limits = image.get("image_pixel_limit", {"min_pixels": 1764,
        "max_pixels": min(9031680, max(1764, width * height))})
    if (not isinstance(limits, dict) or set(limits) != {"min_pixels", "max_pixels"}
            or any(type(limits[key]) is not int for key in limits)
            or not 1764 <= limits["min_pixels"] <= limits["max_pixels"] <= 9031680):
        _invalid("COVER_AGENT_IMAGE_LIMIT_INVALID")
    image["image_pixel_limit"] = dict(limits)
    # Official Seed 2.0+ image estimate: pixels/1764. Include rounding and
    # framing allowance rather than relying on an unverified remote URL size.
    return math.ceil(limits["max_pixels"] / 1764) + 256


def _validate_and_measure_payload(payload: dict) -> tuple[dict, dict]:
    """Validate a detached Chat body and measure its conservative input bound.

    Text/tool JSON is counted by UTF-8 bytes (not characters), plus explicit
    framing headroom. Vision uses actual inline bytes and explicit pixel caps.
    The returned bound is admission evidence, never claimed observed usage.
    """
    if not isinstance(payload, dict) or set(payload) - _KEYS:
        _invalid()
    try:
        body = json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False))
    except (ValueError, TypeError, RecursionError):
        _invalid()
    if body.get("model", MODEL) != MODEL or body.get("stream", False) is not False:
        _invalid("COVER_AGENT_MODEL_OR_STREAM_INVALID")
    if body.get("thinking", {"type": "enabled"}) != {"type": "enabled"}:
        _invalid("COVER_AGENT_THINKING_REQUIRED")
    if body.get("reasoning_effort", "high") not in {"low", "medium", "high"}:
        _invalid("COVER_AGENT_THINKING_REQUIRED")
    if body.get("service_tier", "default") != "default":
        _invalid("COVER_AGENT_SERVICE_TIER_INVALID")
    if "max_tokens" in body and "max_completion_tokens" in body:
        _invalid("COVER_AGENT_OUTPUT_LIMIT_INVALID")
    maximum = body.pop("max_tokens", body.get("max_completion_tokens", MAX_OUTPUT_TOKENS))
    if type(maximum) is not int or not 1 <= maximum <= MAX_OUTPUT_TOKENS:
        _invalid("COVER_AGENT_OUTPUT_LIMIT_INVALID")
    body.update(model=MODEL, stream=False, thinking={"type": "enabled"},
        reasoning_effort=body.get("reasoning_effort", "high"),
        max_completion_tokens=maximum, service_tier="default")
    messages = body.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 128:
        _invalid()
    image_tokens, image_count = 0, 0
    for message in messages:
        if (not isinstance(message, dict) or set(message) - {"role", "content", "name",
                "tool_calls", "tool_call_id", "reasoning_content", "encrypted_content"}
                or message.get("role") not in {"system", "developer", "user", "assistant", "tool"}):
            _invalid()
        content = message.get("content")
        if not isinstance(content, (str, list)) and not (content is None and message.get("tool_calls")):
            _invalid()
        if "reasoning_content" in message and not isinstance(message["reasoning_content"], str):
            _invalid()
        if "encrypted_content" in message and (message["role"] != "assistant"
                or not isinstance(message["encrypted_content"], str)):
            _invalid("COVER_AGENT_ENCRYPTED_HISTORY_INVALID")
        if message["role"] == "tool" and not _NAME.fullmatch(str(message.get("tool_call_id", ""))):
            _invalid("COVER_AGENT_TOOL_MESSAGE_INVALID")
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    _invalid()
                if part.get("type") == "text" and set(part) == {"type", "text"} and isinstance(part["text"], str):
                    continue
                if part.get("type") != "image_url" or set(part) != {"type", "image_url"}:
                    _invalid("COVER_AGENT_MODALITY_INVALID")
                image_tokens += _image_tokens(part["image_url"])
                image_count += 1
    tools = body.get("tools", [])
    if not isinstance(tools, list) or len(tools) > 128:
        _invalid("COVER_AGENT_TOOLS_INVALID")
    names = set()
    for tool in tools:
        fn = tool.get("function") if isinstance(tool, dict) else None
        if (not isinstance(tool, dict) or set(tool) != {"type", "function"} or tool["type"] != "function"
                or not isinstance(fn, dict) or set(fn) - {"name", "description", "parameters", "strict"}
                or not _NAME.fullmatch(str(fn.get("name", ""))) or fn["name"] in names
                or ("parameters" in fn and not isinstance(fn["parameters"], dict))):
            _invalid("COVER_AGENT_TOOLS_INVALID")
        names.add(fn["name"])
    if "parallel_tool_calls" in body and type(body["parallel_tool_calls"]) is not bool:
        _invalid("COVER_AGENT_TOOLS_INVALID")
    choice = body.get("tool_choice", "auto" if tools else "none")
    if isinstance(choice, dict):
        if (set(choice) != {"type", "function"} or choice["type"] != "function"
                or not isinstance(choice["function"], dict) or set(choice["function"]) != {"name"}
                or choice["function"]["name"] not in names):
            _invalid("COVER_AGENT_TOOLS_INVALID")
    elif not isinstance(choice, str) or choice not in {"auto", "none", "required"} or (choice == "required" and not tools):
        _invalid("COVER_AGENT_TOOLS_INVALID")
    measurement = _measure_input(body, image_tokens, image_count)
    return body, measurement


def _check_request_size(body):
    if len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()) > ark_media.MAX_REQUEST_BYTES:
        _invalid("COVER_AGENT_REQUEST_TOO_LARGE")


def prepare_payload(payload: dict) -> tuple[dict, int]:
    """Original hard admission: validate, reject input overflow, then wire size."""
    body, measurement = _validate_and_measure_payload(payload)
    bound = measurement["total_bound"]
    if bound > MAX_INPUT_TOKENS:
        raise CoverAgentProviderError("COVER_AGENT_INPUT_LIMIT_EXCEEDED", input_diagnostics=measurement)
    _check_request_size(body)
    return body, bound


def admit_payload(payload: dict) -> dict:
    """Pure preflight decision only for input overflow; all other errors fatal.

    No exception is constructed for this known local non-dispatch rejection, so
    an existing Invocation failure/UNKNOWN is never cleared or replaced.
    """
    body, measurement = _validate_and_measure_payload(payload)
    if measurement["total_bound"] > MAX_INPUT_TOKENS:
        return {"allowed": False, "code": "COVER_AGENT_INPUT_LIMIT_EXCEEDED", "measurement": measurement}
    _check_request_size(body)
    return {"allowed": True}


def _require_price():
    snapshot = billing._pricing_snapshot("doubao", MODEL, prompt_tokens=MAX_INPUT_TOKENS)
    if (snapshot.get("pricing_status") != "exact" or snapshot.get("currency") not in {"RMB", "CNY"}
            or any(snapshot.get(key) != value for key, value in pricing(MAX_INPUT_TOKENS).items()
                if key in {"input", "cache_read", "output"})):
        _invalid("COVER_AGENT_PRICE_UNCONFIRMED")


def _validate_result(data, body, dimensions):
    diagnostic = _output_diagnostics(data, body)

    def reject(code):
        raise CoverAgentProviderError(code, output_diagnostics=diagnostic)

    if data.get("model") != MODEL:
        reject("COVER_AGENT_MODEL_IDENTITY_MISMATCH")
    fallback = data.get("service_status", {})
    if isinstance(fallback, dict) and isinstance(fallback.get("model_fallback"), dict) and fallback["model_fallback"].get("fallback_triggered"):
        reject("COVER_AGENT_MODEL_FALLBACK_REJECTED")
    if dimensions["usage_status"] != "complete":
        reject("COVER_AGENT_USAGE_INCOMPLETE")
    usage = data["usage"]
    if usage["prompt_tokens"] > MAX_INPUT_TOKENS or usage["completion_tokens"] > body["max_completion_tokens"]:
        reject("COVER_AGENT_OBSERVED_LIMIT_EXCEEDED")
    choices = data.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        reject("COVER_AGENT_OUTPUT_INVALID")
    choice = choices[0]
    if choice.get("finish_reason") == "length":
        reject("COVER_AGENT_OUTPUT_LIMIT_REACHED")
    message = choice.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        reject("COVER_AGENT_OUTPUT_INVALID")
    if choice.get("finish_reason") == "stop":
        if message.get("tool_calls") or not isinstance(message.get("content"), str) or not message["content"].strip():
            reject("COVER_AGENT_OUTPUT_EMPTY")
    elif choice.get("finish_reason") == "tool_calls":
        names = {tool["function"]["name"] for tool in body.get("tools", [])}
        calls, identifiers = message.get("tool_calls"), set()
        if not isinstance(calls, list) or not calls:
            reject("COVER_AGENT_TOOL_OUTPUT_INVALID")
        for call in calls:
            function = call.get("function") if isinstance(call, dict) else None
            if (not isinstance(call, dict) or call.get("type") != "function"
                    or not _NAME.fullmatch(str(call.get("id", ""))) or call["id"] in identifiers
                    or not isinstance(function, dict) or function.get("name") not in names
                    or not isinstance(function.get("arguments"), str)):
                reject("COVER_AGENT_TOOL_OUTPUT_INVALID")
            identifiers.add(call["id"])
    else:
        reject("COVER_AGENT_OUTPUT_INCOMPLETE")


def request_timeout(deadline=None):
    read = READ_TIMEOUT_SECONDS
    if deadline is not None:
        if type(deadline) not in {int, float} or not math.isfinite(deadline):
            _invalid("COVER_AGENT_TASK_DEADLINE")
        read = min(read, deadline - time.time() - REQUEST_MARGIN_SECONDS)
        if read <= 0:
            _invalid("COVER_AGENT_TASK_DEADLINE")
    return httpx.Timeout(read, connect=10, write=90, pool=10)


def complete(payload: dict, *, call_id: str, transport=None, deadline=None) -> dict:
    """Dispatch exactly once, returning the complete non-stream Chat response.

    The caller must persist its original intent and recheck its live cover
    claim before entry. It may hold the same admission ticket around that hook;
    nested admission with this exact ID/provider reuses the shared permit.
    """
    if not isinstance(call_id, str) or not _NAME.fullmatch(call_id):
        _invalid("COVER_AGENT_CALL_ID_INVALID")
    current = public_product._invocation.get()
    if current is None or current.route != "/covers" or not billing._ACTIVE_USAGE_ID.get():
        _invalid("COVER_AGENT_ORIGINAL_CONTEXT_REQUIRED")
    job = db.fetchone("SELECT deadline_at FROM cover_jobs WHERE id=? AND user_id=?",
        (current.request_id, current.user_id))
    if not job:
        _invalid("COVER_AGENT_ORIGINAL_CONTEXT_REQUIRED")
    job_deadline = datetime.fromisoformat(job["deadline_at"]).timestamp()
    request_timeout(deadline)  # Reject an invalid/expired host bound before admission.
    deadline = min(job_deadline, deadline) if deadline is not None else job_deadline
    request_timeout(deadline)
    body, _ = prepare_payload(payload)
    _require_price()
    headers = ark_media._headers()
    encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    diagnostic = ark_media._ArkCallDiagnostics(call_id)
    terminal, status = False, None
    with public_product.model_admission_sync(call_id, "doubao"):
        public_product.assert_result_known()
        # Waiting for the shared permit may have consumed the remaining time.
        timeout = request_timeout(deadline)
        reserve = int((Decimal(estimate(body["max_completion_tokens"])["estimated_cost"]) * 1000).to_integral_value(rounding=ROUND_CEILING))
        try:
            public_product._reserve_payload({"model": MODEL, "provider": "doubao", "modality": "image",
                "max_tokens": body["max_completion_tokens"]}, reserve, call_id=call_id,
                require_metered=True, provenance={"task": "cover_generate", "step": "cover_skill_chat",
                    "prompt_scope": "cover_skill_host", "instruction_role": "system"})
        except public_product._SlotsBusy:
            raise CoverAgentProviderError("MODEL_ADMISSION_UNRECONCILED", call_id=call_id) from None
        except public_product.TrialProviderStopped:
            raise
        except Exception as error:
            raise CoverAgentProviderError("COVER_AGENT_RESERVATION_UNCONFIRMED",
                outcome_unknown=True, call_id=call_id,
                reservation_diagnostics=_reservation_diagnostics(error, call_id, reserve)) from None
        try:
            with ark_media._client(transport=transport) as client:
                diagnostic.phase = "transport"
                public_product.mark_model_dispatched(call_id)
                diagnostic.post_entered = True
                response = client.post(ark_media.CHAT_URL, content=encoded,
                    headers={**headers, "Content-Type": "application/json"},
                    extensions={"trace": diagnostic.trace}, timeout=timeout)
                status = diagnostic.http_status = response.status_code
                diagnostic.headers_received = True
                if status != 200:
                    public_product._record_response(call_id, status)
                    terminal = True
                    try:
                        logging.warning(json.dumps(_http_failure_metadata(response), separators=(",", ":")))
                    except Exception:
                        pass  # Optional metadata/logging cannot replace the known HTTP stop.
                    raise CoverAgentProviderError("COVER_AGENT_HTTP_" + str(status), call_id=call_id)
                diagnostic.phase = "response_decode"
                if len(response.content) > MAX_RESPONSE_BYTES:
                    raise ValueError()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError()
                actual = data.get("model")
                if not isinstance(actual, str) or not _MODEL_NAME.fullmatch(actual):
                    actual = "unknown"
                dimensions = ark_media.usage_dimensions(data, audio_possible=False)
                diagnostic.phase = "usage_metering"
                model_router._record_usage("doubao", actual, physical_call_id=call_id, **dimensions)
                diagnostic.phase = "response_accounting"
                public_product._record_response(call_id, status)
                terminal = True
            diagnostic.phase = "output_validation"
            _validate_result(data, body, dimensions)
            return data
        except CoverAgentProviderError as exc:
            if exc.call_id is None:
                exc.call_id = call_id
            raise
        except BaseException as exc:
            diagnostic.log(exc)
            unknown = True
            if not terminal:
                try:
                    # A complete response with a failed local meter is known on
                    # the wire; leave its missing usage as the accounting fence.
                    known_response = diagnostic.phase in {"usage_metering", "response_accounting"} and status == 200
                    not_sent = diagnostic.not_dispatched(exc)
                    public_product._record_response(call_id, status if known_response else diagnostic.http_status,
                        unknown=not known_response and not not_sent, not_dispatched=not_sent)
                    unknown = not not_sent
                except BaseException:
                    pass  # Retain original durable intent/reservation for readback.
            if not isinstance(exc, Exception):
                raise
            raise CoverAgentProviderError("COVER_AGENT_OUTCOME_OR_ACCOUNTING_UNKNOWN_NO_REPLAY"
                if unknown else "COVER_AGENT_NOT_DISPATCHED", outcome_unknown=unknown, call_id=call_id) from None
