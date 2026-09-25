"""Ark Seed 2.0 material understanding; no text-route or entitlement fallback.

Wire contract: official Ark Chat Completions, Responses and Files APIs.
Only model identity and numeric usage cross the billing boundary. Payloads,
credentials, reasoning and response bodies must not be logged by this adapter.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import re
import socket
import ssl
import sys
import time
import uuid

import httpx
from PIL import Image

MODEL = "doubao-seed-2-0-lite-260428"
BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
CHAT_URL = BASE_URL + "/chat/completions"
RESPONSES_URL = BASE_URL + "/responses"
PRICE_VERSION = "ark-official-2026-09-13-lite-260428"
MAX_REQUEST_BYTES = 64 * 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_VIDEO_BYTES = 100 * 1024 * 1024  # Existing NoteAI upload scope.
_FILE_ID = re.compile(r"file-[A-Za-z0-9_-]{1,128}\Z")


class ArkMediaError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def configured() -> bool:
    return bool(os.environ.get("NOTEAI_ARK_API_KEY"))


def pricing(prompt_tokens: int) -> dict:
    """Catalogue CNY/million, selected on complete input including audio/cache."""
    if type(prompt_tokens) is not int or not 0 <= prompt_tokens <= 262144:
        raise ArkMediaError("ARK_USAGE_OUT_OF_RANGE")
    if prompt_tokens <= 32768:
        rates = (.6, .12, 9., 1.8, 3.6)
    elif prompt_tokens <= 131072:
        rates = (.9, .18, 13.5, 2.7, 5.4)
    else:
        rates = (1.8, .36, 27., 5.4, 10.8)
    return dict(zip(("input", "cache_read", "audio_input", "audio_cache_read", "output"), rates))


def usage_dimensions(data: dict, *, audio_possible: bool) -> dict:
    """Disjoint input dimensions; absent audio details are never assumed zero."""
    usage = data.get("usage")
    missing = {"tokens_in": 0, "tokens_out": 0, "usage_status": "usage_missing"}
    if not isinstance(usage, dict):
        return missing
    p, out = usage.get("prompt_tokens"), usage.get("completion_tokens")
    integer = lambda value: type(value) is int and value >= 0
    if not integer(p) or not integer(out):
        return missing
    details = usage.get("prompt_tokens_details")
    details = details if isinstance(details, dict) else {}
    c = details.get("cached_tokens")
    a = details.get("audio_tokens")
    if a is None and not audio_possible:
        a = 0
    ac = details.get("audio_cached_tokens")
    if ac is None and (a == 0 or c == 0):
        ac = 0
    if not all(integer(value) for value in (a, c, ac)) or not (ac <= a <= p and ac <= c <= p and p - a - c + ac >= 0):
        return {"tokens_in": 0, "tokens_out": out,
                "unclassified_input_tokens": p, "usage_status": "usage_incomplete"}
    return {"tokens_in": p - a - c + ac, "tokens_out": out,
            "cache_read_tokens": c - ac, "audio_input_tokens": a - ac,
            "audio_cache_read_tokens": ac, "usage_status": "complete"}


def image_part(payload: bytes) -> dict:
    if not payload or len(payload) >= MAX_IMAGE_BYTES:
        raise ArkMediaError("ARK_IMAGE_SIZE_INVALID")
    try:
        with Image.open(io.BytesIO(payload)) as image:
            if image.format not in {"PNG", "JPEG", "WEBP"} or not 196 <= image.width * image.height <= 36000000:
                raise ArkMediaError("ARK_IMAGE_FORMAT_INVALID")
            mime = Image.MIME[image.format]
            image.verify()
    except ArkMediaError:
        raise
    except Exception:
        raise ArkMediaError("ARK_IMAGE_INVALID") from None
    return {"type": "image_url", "image_url": {
        "url": "data:" + mime + ";base64," + base64.b64encode(payload).decode(),
        "detail": "xhigh",
    }}


def video_part(payload: bytes, *, mime: str, fps: float = 1.0) -> dict:
    if mime not in {"video/mp4", "video/quicktime", "video/x-msvideo"}:
        raise ArkMediaError("ARK_VIDEO_FORMAT_INVALID")
    if not payload or len(payload) > 50 * 1024 * 1024 or not .2 <= fps <= 5:
        raise ArkMediaError("ARK_VIDEO_REQUIRES_FILES")
    # The complete original video, including its audio track, is transmitted.
    return {"type": "input_video", "video_url":
        "data:" + mime + ";base64," + base64.b64encode(payload).decode(), "fps": fps}


def file_video_part(file_id: str, *, fps: float = 1.0) -> dict:
    if not _FILE_ID.fullmatch(file_id) or not .2 <= fps <= 5:
        raise ArkMediaError("ARK_FILE_REFERENCE_INVALID")
    # Files preprocessing already fixes fps and the audio-capable model.
    return {"type": "input_video", "file_id": file_id}


def _headers() -> dict:
    key = os.environ.get("NOTEAI_ARK_API_KEY")
    if not key:
        raise ArkMediaError("ARK_NOT_CONFIGURED")
    return {"Authorization": "Bearer " + key}


def _client(*, transport=None) -> httpx.Client:
    return httpx.Client(transport=transport, trust_env=False, follow_redirects=False,
                        timeout=httpx.Timeout(240, connect=10, write=90, pool=10))


def _stop(code: str):
    import public_product
    current = public_product._invocation.get()
    if current is not None and not current.failure:
        current.failure = code
    raise public_product.TrialProviderStopped(current.failure if current else code)


def chat(prompt: str, parts: list[dict], *, max_tokens: int = 4096,
         audio_possible: bool = False, json_output: bool = False, transport=None) -> str:
    return _complete(prompt, parts, max_tokens=max_tokens, audio_possible=audio_possible,
                     json_output=json_output, transport=transport)


def video(prompt: str, parts: list[dict], *, max_tokens: int = 8192, media: dict | None = None, transport=None) -> str:
    """Full audio/video via the documented Responses input_video contract."""
    if not parts or any(not isinstance(part, dict) or part.get("type") != "input_video" for part in parts):
        raise ArkMediaError("ARK_VIDEO_INVALID")
    return _complete(prompt, parts, max_tokens=max_tokens, audio_possible=True,
                     responses=True, media=media, transport=transport)


def _failure_kind(exc: BaseException) -> str:
    # Never include arbitrary exception names or text in diagnostic output.
    for cls, label in ((asyncio.CancelledError, "cancelled"), (KeyboardInterrupt, "interrupted"),
            (SystemExit, "system_exit"), (socket.gaierror, "dns_error"),
            (ssl.SSLCertVerificationError, "tls_certificate_error"), (ssl.SSLError, "tls_error"),
            (httpx.ConnectTimeout, "connect_timeout"), (httpx.ConnectError, "connect_error"),
            (httpx.PoolTimeout, "pool_timeout"), (httpx.WriteTimeout, "write_timeout"),
            (httpx.WriteError, "write_error"), (httpx.ReadTimeout, "read_timeout"),
            (httpx.ReadError, "read_error"), (httpx.RemoteProtocolError, "remote_protocol_error"),
            (httpx.LocalProtocolError, "local_protocol_error"), (httpx.DecodingError, "decoding_error"),
            (json.JSONDecodeError, "json_decode_error"), (UnicodeError, "unicode_error"),
            (ValueError, "value_error"), (TypeError, "type_error"), (OSError, "os_error")):
        if isinstance(exc, cls):
            return label
    # HTTPX maps these original httpcore exceptions using `raise ... from exc`.
    cls = type(exc)
    core = {"ConnectError": "connect_error", "ConnectTimeout": "connect_timeout",
        "PoolTimeout": "pool_timeout", "WriteError": "write_error", "WriteTimeout": "write_timeout",
        "ReadError": "read_error", "ReadTimeout": "read_timeout",
        "RemoteProtocolError": "remote_protocol_error", "LocalProtocolError": "local_protocol_error"}
    if cls.__module__.split(".")[0] == "httpcore" and cls.__name__ in core:
        return core[cls.__name__]
    return "operation_error"


def _failure_chain(exc: BaseException) -> list[str]:
    chain, seen = [], set()
    while isinstance(exc, BaseException) and id(exc) not in seen and len(chain) < 6:
        seen.add(id(exc)); chain.append(_failure_kind(exc))
        exc = exc.__cause__ if exc.__cause__ is not None else (None if exc.__suppress_context__ else exc.__context__)
    return chain


class _ArkCallDiagnostics:
    """One call's fixed trace projection; raw trace info is never retained/logged."""
    def __init__(self, call_id):
        self.call_id = call_id
        self.started = time.monotonic()
        self.phase = "client_setup"
        self.network_phase = "unobserved"
        self.post_entered = False
        self.send_observed = False
        self.pre_send_failure_observed = False
        self.headers_received = False
        self.http_status = None
        self.trace_events = 0
        self.last_trace_event = None
        self.failure_reason = None

    def trace(self, name, info):
        stages = {"connection.connect_tcp": "connect", "connection.start_tls": "tls",
            "http11.send_request_headers": "request_send", "http11.send_request_body": "request_send",
            "http11.receive_response_headers": "response_read", "http11.receive_response_body": "response_read",
            "http2.send_request_headers": "request_send", "http2.send_request_body": "request_send",
            "http2.receive_response_headers": "response_read", "http2.receive_response_body": "response_read"}
        if not isinstance(name, str):
            return
        event, _, outcome = name.rpartition(".")
        if event not in stages or outcome not in {"started", "complete", "failed"}:
            return
        self.trace_events += 1
        self.last_trace_event = name
        self.network_phase = stages[event]
        if event in {"connection.connect_tcp", "connection.start_tls"} and outcome == "failed":
            self.pre_send_failure_observed = True
        if event.startswith(("http11.send_request_", "http2.send_request_")):
            self.send_observed = True
        if event in {"http11.receive_response_headers", "http2.receive_response_headers"} and outcome == "complete":
            self.headers_received = True
            value = info.get("return_value") if isinstance(info, dict) else None
            # Actual httpcore HTTP/1.1 return tuple: version, status, reason, headers, trailing data.
            if isinstance(value, tuple) and len(value) == 5 and type(value[1]) is int and 100 <= value[1] <= 599:
                self.http_status = value[1]

    def not_dispatched(self, exc):
        # A send event is evidence of a possible partial write, even if a later
        # exception happens to have a connection-related type. Never erase it.
        if self.send_observed or self.headers_received or self.http_status is not None:
            return False
        if not self.post_entered:
            return True
        # Opaque/custom transports need not emit trace callbacks. A mapped
        # ConnectError alone cannot prove where that transport failed.
        return isinstance(exc, httpx.PoolTimeout) or (
            self.pre_send_failure_observed and isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)))

    def log(self, exc, *, phase=None, role="primary"):
        import security_redaction
        chain = _failure_chain(exc)
        network = self.network_phase
        if "dns_error" in chain and network in {"unobserved", "connect"}:
            network = "dns"
        elif any(kind in chain for kind in ("tls_error", "tls_certificate_error")) and network in {"unobserved", "connect", "tls"}:
            network = "tls"
        elif network == "unobserved":
            network = {"connect_error": "connect", "connect_timeout": "connect", "pool_timeout": "pool_wait",
                "write_error": "request_send", "write_timeout": "request_send", "read_error": "response_read",
                "read_timeout": "response_read", "remote_protocol_error": "response_read"}.get(chain[0], "unobserved")
        event = security_redaction.safe_failure_event("provider", provider="doubao",
            phase="ark_inference_" + (phase or self.phase), http_status=self.http_status,
            duration_ms=max(0, round((time.monotonic() - self.started) * 1000)))
        event.update(schema="noteai.ark_media_failure.v1", call_id=self.call_id,
            error_code="ark_media_" + chain[0], exception_chain=chain, network_phase=network,
            trace_event_count=self.trace_events, transport_event=self.last_trace_event,
            failure_reason=self.failure_reason, request_send_observed=self.send_observed,
            response_headers_received=True if self.headers_received else None,
            dispatch_state="not_dispatched" if self.not_dispatched(exc) else "unknown",
            cancellation=not isinstance(exc, Exception), failure_role=role)
        try:
            print(json.dumps(event, allow_nan=False), file=sys.stderr, flush=True)
        except Exception:
            pass  # Logging failure must never replace durable accounting/cancellation.


def _complete(prompt: str, parts: list[dict], *, max_tokens: int,
              audio_possible: bool, json_output: bool = False, responses: bool = False,
              media: dict | None = None, transport=None) -> str:
    """One physical inference. Record even a truncated response before failing."""
    import public_product
    import model_router
    if not prompt or not parts or type(max_tokens) is not int or not 1 <= max_tokens <= 32768:
        raise ArkMediaError("ARK_INPUT_INVALID")
    payload = ({"model": MODEL, "input": [{"role": "user", "content": [
        *parts, {"type": "input_text", "text": prompt}]}],
        "max_output_tokens": max_tokens, "store": False, "thinking": {"type": "disabled"}, "stream": False}
        if responses else {"model": MODEL, "messages": [{"role": "user", "content": [
        *parts, {"type": "text", "text": prompt}]}],
        "max_tokens": max_tokens, "thinking": {"type": "disabled"}, "stream": False})
    if json_output:
        payload["response_format"] = {"type": "json_object"}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > MAX_REQUEST_BYTES:
        raise ArkMediaError("ARK_REQUEST_REQUIRES_FILES")
    headers = _headers()
    public_product.assert_result_known()
    call_id = str(uuid.uuid4())
    deadline = time.monotonic() + 90
    import prompt_manager
    provenance = prompt_manager.call_provenance("media_understanding", prompt,
        step="video_audio_understanding" if audio_possible else "image_understanding",
        prompt_keys=(), prompt_role="user")
    # Conservative reservation only; owner_metered never uses it as a money cap.
    reserve = int((262144 * (27 if audio_possible else 1.8) + max_tokens * 10.8) / 1000) + 1
    while True:
        try:
            public_product._reserve_payload({"model": MODEL, "max_tokens": max_tokens,
                "provider": "doubao", "modality": "video_audio" if audio_possible else "image",
                **({"media": media} if media is not None else {})},
                reserve, call_id=call_id, require_metered=True, provenance=provenance)
            break
        except public_product._SlotsBusy:
            if time.monotonic() >= deadline:
                raise public_product.TrialProviderStopped("PUBLIC_TRIAL_BUSY_OR_UNRECONCILED") from None
            time.sleep(.25)
    status = None
    diagnostic = _ArkCallDiagnostics(call_id)
    def stop(code):
        diagnostic.failure_reason = code
        _stop(code)
    try:
        with _client(transport=transport) as client:
            diagnostic.phase = "transport"
            diagnostic.post_entered = True
            response = client.post(RESPONSES_URL if responses else CHAT_URL, content=encoded,
                                   headers={**headers, "Content-Type": "application/json"},
                                   extensions={"trace": diagnostic.trace})
            status = response.status_code
            diagnostic.http_status = status
            diagnostic.headers_received = True
            diagnostic.phase = "response_accounting"
            if status != 200:
                public_product._record_response(call_id, status)
                stop("ARK_HTTP_" + str(status))
            diagnostic.phase = "response_decode"
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError()
            actual_model = data.get("model") if isinstance(data.get("model"), str) else "unknown"
            if not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,100}", actual_model):
                actual_model = "unknown"
            diagnostic.phase = "usage_metering"
            usage = data.get("usage")
            meter_data = {"usage": {"prompt_tokens": usage.get("input_tokens"),
                "completion_tokens": usage.get("output_tokens"),
                "prompt_tokens_details": usage.get("input_tokens_details")}} if responses and isinstance(usage, dict) else data
            dimensions = usage_dimensions(meter_data, audio_possible=audio_possible)
            model_router._record_usage("doubao", actual_model,
                physical_call_id=call_id, **dimensions)
            nonterminal = responses and data.get("status") not in {"completed", "incomplete", "failed"}
            diagnostic.phase = "response_accounting"
            public_product._record_response(call_id, status, **({"unknown": True} if nonterminal else {}))
            if nonterminal:
                stop("ARK_OUTCOME_OR_ACCOUNTING_UNKNOWN_NO_REPLAY")
        diagnostic.phase = "model_validation"
        if actual_model != MODEL:
            stop("ARK_MODEL_IDENTITY_MISMATCH")
        diagnostic.phase = "usage_validation"
        if dimensions["usage_status"] != "complete":
            stop("ARK_USAGE_INCOMPLETE")
        diagnostic.phase = "output_validation"
        if responses:
            if data.get("status") != "completed" or data.get("error") or data.get("incomplete_details"):
                stop("ARK_OUTPUT_INCOMPLETE")
            output = data.get("output")
            if not isinstance(output, list) or any(not isinstance(item, dict) or item.get("type") not in {"message", "reasoning"} for item in output):
                stop("ARK_OUTPUT_INCOMPLETE")
            messages = [item for item in output if item.get("type") == "message"]
            if len(messages) != 1 or messages[0].get("role") != "assistant" or messages[0].get("status") != "completed" or messages[0].get("partial") is True:
                stop("ARK_OUTPUT_INCOMPLETE")
            content = messages[0].get("content")
            if not isinstance(content, list) or not content or any(not isinstance(item, dict) or
                    item.get("type") != "output_text" or not isinstance(item.get("text"), str) for item in content):
                stop("ARK_OUTPUT_EMPTY")
            result = "\n".join(item["text"] for item in content).strip()
            if not result:
                stop("ARK_OUTPUT_EMPTY")
            return result
        choices = data.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict) or choices[0].get("finish_reason") != "stop":
            stop("ARK_OUTPUT_INCOMPLETE")
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            stop("ARK_OUTPUT_EMPTY")
        return content.strip()

    except public_product.TrialProviderStopped as exc:
        # Preserve existing known rejection / unsettled accounting semantics.
        diagnostic.log(exc)
        raise
    except BaseException as exc:
        # Persist the original failure first: terminal accounting may also fail.
        diagnostic.log(exc)
        try:
            public_product._record_response(call_id, diagnostic.http_status,
                unknown=not diagnostic.not_dispatched(exc), not_dispatched=diagnostic.not_dispatched(exc))
        except BaseException as persist_exc:
            diagnostic.log(persist_exc, phase="result_persistence", role="terminal_persistence")
        if not isinstance(exc, Exception):
            raise  # Cancellation and process interruption retain their type.
        raise public_product.TrialProviderStopped("ARK_OUTCOME_OR_ACCOUNTING_UNKNOWN_NO_REPLAY") from None


def upload_video(payload: bytes, *, mime: str, persist, fps: float = 1.0, expire_at: int | None = None,
                 upload_ref: str | None = None, transport=None) -> str:
    """Caller must durably claim the media upload before invoking this once.

    persist records returned ID/status before any later inference. On an unknown
    upload the original claim is retained, never blindly retried.
    """
    if not payload or len(payload) > MAX_VIDEO_BYTES or mime not in {"video/mp4", "video/quicktime", "video/x-msvideo"} or not .2 <= fps <= 5:
        raise ArkMediaError("ARK_VIDEO_INVALID")
    headers = _headers()
    expire_at = expire_at if expire_at is not None else int(time.time()) + 86410
    if type(expire_at) is not int or not int(time.time()) + 86400 <= expire_at <= int(time.time()) + 30 * 86400:
        raise ArkMediaError("ARK_FILE_EXPIRY_INVALID")
    if upload_ref is not None and (not isinstance(upload_ref, str) or
            not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", upload_ref)):
        raise ArkMediaError("ARK_FILE_UPLOAD_REFERENCE_INVALID")
    known_id = None
    terminal_saved = False
    started = time.monotonic()
    phase, status = "transport", None
    def record_failure(exc, failure_phase):
        # Fixed concepts only. Never serialize exception text/request/response.
        import security_redaction
        event = security_redaction.safe_failure_event("provider", exc,
            provider="doubao", phase="ark_file_upload_" + failure_phase,
            http_status=status, duration_ms=round((time.monotonic() - started) * 1000))
        event["response_received"] = status is not None
        if upload_ref:
            event["upload_ref"] = upload_ref
        if known_id:
            event["file_id"] = known_id
        try:
            print(json.dumps(event), file=sys.stderr, flush=True)
        except (OSError, ValueError):
            # A broken log sink must not prevent the durable unknown write.
            pass
    try:
        with _client(transport=transport) as client:
            response = client.post(BASE_URL + "/files", headers=headers,
                data={"purpose": "user_data", "expire_at": str(expire_at),
                      "preprocess_configs[video][fps]": str(fps),
                      "preprocess_configs[video][model]": MODEL},
                files={"file": ("material" + ("-" + upload_ref if upload_ref else "") +
                    {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/x-msvideo": ".avi"}[mime], io.BytesIO(payload), mime)})
            status = response.status_code
            if response.status_code != 200:
                rejected = response.status_code in {400, 401, 403, 404, 413, 415, 422, 429}
                phase = "persist_result"
                persist({"state": "failed" if rejected else "unknown", "http_status": response.status_code})
                terminal_saved = True
                phase = "response_status"
                raise ArkMediaError("ARK_FILE_HTTP_" + str(response.status_code))
            phase = "response_decode"
            data = response.json()
            file_id = data.get("id") if isinstance(data, dict) else None
            if not isinstance(file_id, str) or not _FILE_ID.fullmatch(file_id):
                raise ArkMediaError("ARK_FILE_IDENTITY_UNCONFIRMED")
            known_id = file_id
            phase = "persist_result"
            persist({"state": "uploaded", "file_id": file_id, "model": MODEL})
            return file_id
    except BaseException as exc:
        record_failure(exc, phase)
        if not terminal_saved:
            # Keep a returned identifier even when its first durable write had
            # an uncertain outcome. It is the only exact readback reference.
            try:
                persist({"state": "unknown", **({"file_id": known_id} if known_id else {})})
            except BaseException as persist_exc:
                # The first write may have committed. Keep its identity in the
                # existing durable log and preserve both failure classifications.
                record_failure(persist_exc, "persist_unknown")
        if isinstance(exc, ArkMediaError):
            raise
        raise ArkMediaError("ARK_FILE_UPLOAD_UNKNOWN_NO_REPLAY") from None


def wait_file(file_id: str, *, max_wait: int = 180, transport=None) -> None:
    if not _FILE_ID.fullmatch(file_id):
        raise ArkMediaError("ARK_FILE_REFERENCE_INVALID")
    headers = _headers()
    deadline = time.monotonic() + max_wait
    with _client(transport=transport) as client:
        while True:
            response = client.get(BASE_URL + "/files/" + file_id, headers=headers)
            if response.status_code != 200:
                raise ArkMediaError("ARK_FILE_STATUS_HTTP_" + str(response.status_code))
            data = response.json()
            if data.get("id") != file_id:
                raise ArkMediaError("ARK_FILE_IDENTITY_MISMATCH")
            if data.get("status") == "active":
                return
            if data.get("status") != "processing":
                raise ArkMediaError("ARK_FILE_NOT_ACTIVE")
            if time.monotonic() >= deadline:
                raise ArkMediaError("ARK_FILE_PROCESSING_TIMEOUT")
            time.sleep(2)


def read_file_state(file_id: str, *, transport=None) -> str:
    """Read only the original file. Unspecified errors do not certify absence."""
    if not _FILE_ID.fullmatch(file_id):
        raise ArkMediaError("ARK_FILE_REFERENCE_INVALID")
    with _client(transport=transport) as client:
        response = client.get(BASE_URL + "/files/" + file_id, headers=_headers())
        if response.status_code != 200:
            raise ArkMediaError("ARK_FILE_STATUS_HTTP_" + str(response.status_code))
        data = response.json()
        if not isinstance(data, dict) or data.get("id") != file_id or data.get("status") not in {"active", "processing", "failed", "error"}:
            raise ArkMediaError("ARK_FILE_IDENTITY_OR_STATE_UNCONFIRMED")
        return data["status"]


def delete_file(file_id: str, *, transport=None) -> None:
    """Only after the original inference has a known terminal, never in UNKNOWN."""
    if not _FILE_ID.fullmatch(file_id):
        raise ArkMediaError("ARK_FILE_REFERENCE_INVALID")
    with _client(transport=transport) as client:
        response = client.delete(BASE_URL + "/files/" + file_id, headers=_headers())
        if response.status_code != 200:
            raise ArkMediaError("ARK_FILE_DELETE_UNCONFIRMED")
        data = response.json()
        if data.get("id") != file_id or data.get("deleted") is not True:
            raise ArkMediaError("ARK_FILE_DELETE_UNCONFIRMED")
