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
from decimal import Decimal, ROUND_CEILING
import io
import json
import math
import re

from PIL import Image

import ark_media
import billing
import model_router
import public_product


MODEL = "doubao-seed-2-1-pro-260915"
PRICE_VERSION = "ark-public-seed-2-1-pro-260915-2026-10-22"
MAX_INPUT_TOKENS = 131072
MAX_OUTPUT_TOKENS = 8192  # Includes reasoning, unlike Chat max_tokens.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_NAME = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_MODEL_NAME = re.compile(r"[A-Za-z0-9_.:-]{1,100}\Z")
_KEYS = {"model", "messages", "tools", "tool_choice", "parallel_tool_calls",
    "max_tokens", "max_completion_tokens", "thinking", "reasoning_effort",
    "stream", "temperature", "top_p", "presence_penalty", "frequency_penalty",
    "response_format", "seed", "service_tier"}


class CoverAgentProviderError(public_product.TrialProviderStopped):
    def __init__(self, code, *, outcome_unknown=False, call_id=None):
        self.code = code
        self.outcome_unknown = bool(outcome_unknown)
        self.call_id = call_id
        super().__init__(code)


def pricing(prompt_tokens: int) -> dict:
    """Standard catalogue CNY/million, not the account's final supplier bill.

    Billing can price an unexpected over-bound response without losing its real
    usage. The smaller 128k admission bound is enforced separately below.
    """
    if type(prompt_tokens) is not int or not 0 <= prompt_tokens <= 1048576:
        raise ValueError("cover agent pricing input is outside the model context")
    return {"input": 6.0, "cache_read": 1.2, "output": 30.0,
            "audio_input": None, "audio_cache_read": None}


def estimate() -> dict:
    amount = (Decimal(MAX_INPUT_TOKENS) * Decimal("6")
        + Decimal(MAX_OUTPUT_TOKENS) * Decimal("30")) / Decimal(1000000)
    return {"provider": "doubao", "model_id": MODEL, "currency": "CNY",
        "input_token_bound": MAX_INPUT_TOKENS, "output_token_bound": MAX_OUTPUT_TOKENS,
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


def prepare_payload(payload: dict) -> tuple[dict, int]:
    """Validate a detached Chat body and return its conservative input bound.

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
        max_completion_tokens=maximum, service_tier="default")
    messages = body.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 128:
        _invalid()
    image_tokens = 0
    for message in messages:
        if (not isinstance(message, dict) or set(message) - {"role", "content", "name",
                "tool_calls", "tool_call_id", "reasoning_content"}
                or message.get("role") not in {"system", "developer", "user", "assistant", "tool"}):
            _invalid()
        content = message.get("content")
        if not isinstance(content, (str, list)) and not (content is None and message.get("tool_calls")):
            _invalid()
        if "reasoning_content" in message and not isinstance(message["reasoning_content"], str):
            _invalid()
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
    measured = deepcopy(body)
    for message in measured["messages"]:
        if isinstance(message.get("content"), list):
            for part in message["content"]:
                if part.get("type") == "image_url":
                    part["image_url"]["url"] = ""
    text_bytes = len(json.dumps(measured, ensure_ascii=False, separators=(",", ":")).encode())
    bound = text_bytes + image_tokens + 128 * (len(messages) + len(tools)) + 1024
    if bound > MAX_INPUT_TOKENS:
        _invalid("COVER_AGENT_INPUT_LIMIT_EXCEEDED")
    if len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()) > ark_media.MAX_REQUEST_BYTES:
        _invalid("COVER_AGENT_REQUEST_TOO_LARGE")
    return body, bound


def _require_price():
    snapshot = billing._pricing_snapshot("doubao", MODEL, prompt_tokens=MAX_INPUT_TOKENS)
    if (snapshot.get("pricing_status") != "exact" or snapshot.get("currency") not in {"RMB", "CNY"}
            or any(snapshot.get(key) != value for key, value in pricing(MAX_INPUT_TOKENS).items()
                if key in {"input", "cache_read", "output"})):
        _invalid("COVER_AGENT_PRICE_UNCONFIRMED")


def _validate_result(data, body, dimensions):
    if data.get("model") != MODEL:
        _invalid("COVER_AGENT_MODEL_IDENTITY_MISMATCH")
    fallback = data.get("service_status", {})
    if isinstance(fallback, dict) and isinstance(fallback.get("model_fallback"), dict) and fallback["model_fallback"].get("fallback_triggered"):
        _invalid("COVER_AGENT_MODEL_FALLBACK_REJECTED")
    if dimensions["usage_status"] != "complete":
        _invalid("COVER_AGENT_USAGE_INCOMPLETE")
    usage = data["usage"]
    if usage["prompt_tokens"] > MAX_INPUT_TOKENS or usage["completion_tokens"] > body["max_completion_tokens"]:
        _invalid("COVER_AGENT_OBSERVED_LIMIT_EXCEEDED")
    choices = data.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        _invalid("COVER_AGENT_OUTPUT_INVALID")
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        _invalid("COVER_AGENT_OUTPUT_INVALID")
    if choice.get("finish_reason") == "stop":
        if message.get("tool_calls") or not isinstance(message.get("content"), str) or not message["content"].strip():
            _invalid("COVER_AGENT_OUTPUT_EMPTY")
    elif choice.get("finish_reason") == "tool_calls":
        names = {tool["function"]["name"] for tool in body.get("tools", [])}
        calls, identifiers = message.get("tool_calls"), set()
        if not isinstance(calls, list) or not calls:
            _invalid("COVER_AGENT_TOOL_OUTPUT_INVALID")
        for call in calls:
            function = call.get("function") if isinstance(call, dict) else None
            if (not isinstance(call, dict) or call.get("type") != "function"
                    or not _NAME.fullmatch(str(call.get("id", ""))) or call["id"] in identifiers
                    or not isinstance(function, dict) or function.get("name") not in names
                    or not isinstance(function.get("arguments"), str)):
                _invalid("COVER_AGENT_TOOL_OUTPUT_INVALID")
            identifiers.add(call["id"])
    else:
        _invalid("COVER_AGENT_OUTPUT_INCOMPLETE")


def complete(payload: dict, *, call_id: str, transport=None) -> dict:
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
    body, _ = prepare_payload(payload)
    _require_price()
    headers = ark_media._headers()
    encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    diagnostic = ark_media._ArkCallDiagnostics(call_id)
    terminal, status = False, None
    with public_product.model_admission_sync(call_id, "doubao"):
        public_product.assert_result_known()
        reserve = int((Decimal(estimate()["estimated_cost"]) * 1000).to_integral_value(rounding=ROUND_CEILING))
        try:
            public_product._reserve_payload({"model": MODEL, "provider": "doubao", "modality": "image",
                "max_tokens": body["max_completion_tokens"]}, reserve, call_id=call_id,
                require_metered=True, provenance={"task": "cover_generate", "step": "cover_skill_chat",
                    "prompt_scope": "cover_skill_host", "instruction_role": "system"})
        except public_product._SlotsBusy:
            raise CoverAgentProviderError("MODEL_ADMISSION_UNRECONCILED", call_id=call_id) from None
        except public_product.TrialProviderStopped:
            raise
        except Exception:
            raise CoverAgentProviderError("COVER_AGENT_RESERVATION_UNCONFIRMED",
                outcome_unknown=True, call_id=call_id) from None
        try:
            with ark_media._client(transport=transport) as client:
                diagnostic.phase = "transport"
                public_product.mark_model_dispatched(call_id)
                diagnostic.post_entered = True
                response = client.post(ark_media.CHAT_URL, content=encoded,
                    headers={**headers, "Content-Type": "application/json"},
                    extensions={"trace": diagnostic.trace})
                status = diagnostic.http_status = response.status_code
                diagnostic.headers_received = True
                if status != 200:
                    public_product._record_response(call_id, status)
                    terminal = True
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
