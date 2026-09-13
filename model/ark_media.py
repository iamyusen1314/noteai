"""Ark Seed 2.0 material understanding; no text-route or entitlement fallback.

Wire contract: official Ark Chat Completions and Files APIs (2026-09-13).
Only model identity and numeric usage cross the billing boundary. Payloads,
credentials, reasoning and response bodies must not be logged by this adapter.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import time
import uuid

import httpx
from PIL import Image

MODEL = "doubao-seed-2-0-lite-260428"
BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
CHAT_URL = BASE_URL + "/chat/completions"
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
    return {"type": "video_url", "video_url": {
        "url": "data:" + mime + ";base64," + base64.b64encode(payload).decode(), "fps": fps,
    }}


def file_video_part(file_id: str, *, fps: float = 1.0) -> dict:
    if not _FILE_ID.fullmatch(file_id) or not .2 <= fps <= 5:
        raise ArkMediaError("ARK_FILE_REFERENCE_INVALID")
    # Files preprocessing already fixes fps and the audio-capable model.
    return {"type": "video_url", "video_url": {"file_id": file_id}}


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
    """One physical inference. Record even a truncated response before failing."""
    import public_product
    import model_router
    if not prompt or not parts or type(max_tokens) is not int or not 1 <= max_tokens <= 32768:
        raise ArkMediaError("ARK_INPUT_INVALID")
    payload = {"model": MODEL, "messages": [{"role": "user", "content": [
        *parts, {"type": "text", "text": prompt}]}],
        "max_tokens": max_tokens, "thinking": {"type": "disabled"}, "stream": False}
    if json_output:
        payload["response_format"] = {"type": "json_object"}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > MAX_REQUEST_BYTES:
        raise ArkMediaError("ARK_REQUEST_REQUIRES_FILES")
    headers = _headers()
    public_product.assert_result_known()
    call_id = str(uuid.uuid4())
    deadline = time.monotonic() + 90
    # Conservative reservation only; owner_metered never uses it as a money cap.
    reserve = int((262144 * (27 if audio_possible else 1.8) + max_tokens * 10.8) / 1000) + 1
    while True:
        try:
            public_product._reserve_payload({"model": MODEL, "max_tokens": max_tokens,
                "provider": "doubao", "modality": "video_audio" if audio_possible else "image"},
                reserve, call_id=call_id, require_metered=True)
            break
        except public_product._SlotsBusy:
            if time.monotonic() >= deadline:
                raise public_product.TrialProviderStopped("PUBLIC_TRIAL_BUSY_OR_UNRECONCILED") from None
            time.sleep(.25)
    status = None
    try:
        with _client(transport=transport) as client:
            response = client.post(CHAT_URL, content=encoded,
                                   headers={**headers, "Content-Type": "application/json"})
            status = response.status_code
            if status != 200:
                public_product._record_response(call_id, status)
                _stop("ARK_HTTP_" + str(status))
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError()
            actual_model = data.get("model") if isinstance(data.get("model"), str) else "unknown"
            if not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,100}", actual_model):
                actual_model = "unknown"
            dimensions = usage_dimensions(data, audio_possible=audio_possible)
            model_router._record_usage("doubao", actual_model,
                physical_call_id=call_id, **dimensions)
            public_product._record_response(call_id, status)
    except public_product.TrialProviderStopped:
        # HTTP failures already have a known terminal. Accounting failures
        # remain dispatched/unconfirmed for reconciliation; never re-dispatch.
        raise
    except BaseException:
        public_product._record_response(call_id, status, unknown=True)
        raise public_product.TrialProviderStopped("ARK_OUTCOME_OR_ACCOUNTING_UNKNOWN_NO_REPLAY") from None
    if actual_model != MODEL:
        _stop("ARK_MODEL_IDENTITY_MISMATCH")
    if dimensions["usage_status"] != "complete":
        _stop("ARK_USAGE_INCOMPLETE")
    choices = data.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict) or choices[0].get("finish_reason") != "stop":
        _stop("ARK_OUTPUT_INCOMPLETE")
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        _stop("ARK_OUTPUT_EMPTY")
    return content.strip()


def upload_video(payload: bytes, *, mime: str, persist, fps: float = 1.0, expire_at: int | None = None, transport=None) -> str:
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
    known_id = None
    terminal_saved = False
    try:
        with _client(transport=transport) as client:
            response = client.post(BASE_URL + "/files", headers=headers,
                data={"purpose": "user_data", "expire_at": str(expire_at),
                      "preprocess_configs[video][fps]": str(fps),
                      "preprocess_configs[video][model]": MODEL},
                files={"file": ("material" + {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/x-msvideo": ".avi"}[mime], payload, mime)})
            if response.status_code != 200:
                rejected = response.status_code in {400, 401, 403, 404, 413, 415, 422, 429}
                persist({"state": "failed" if rejected else "unknown", "http_status": response.status_code})
                terminal_saved = True
                raise ArkMediaError("ARK_FILE_HTTP_" + str(response.status_code))
            data = response.json()
            file_id = data.get("id") if isinstance(data, dict) else None
            if not isinstance(file_id, str) or not _FILE_ID.fullmatch(file_id):
                raise ArkMediaError("ARK_FILE_IDENTITY_UNCONFIRMED")
            known_id = file_id
            persist({"state": "uploaded", "file_id": file_id, "model": MODEL})
            return file_id
    except BaseException as exc:
        if not terminal_saved:
            # Keep a returned identifier even when its first durable write had
            # an uncertain outcome. It is the only exact readback reference.
            persist({"state": "unknown", **({"file_id": known_id} if known_id else {})})
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
        if data.get("id") != file_id or data.get("status") not in {"active", "processing", "error"}:
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
