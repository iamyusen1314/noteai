"""Shared wire constants and HMAC signing for the internal Claude Gateway."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time


MESSAGES_PATH = "/internal/v2/messages"
STREAM_PATH = "/internal/v2/messages/stream"
READINESS_PATH = "/internal/v2/readiness"

HEADER_KEY_ID = "X-NoteAI-Key-ID"
HEADER_TIMESTAMP = "X-NoteAI-Timestamp"
HEADER_NONCE = "X-NoteAI-Nonce"
HEADER_SIGNATURE = "X-NoteAI-Signature"
HEADER_PROTOCOL_VERSION = "X-NoteAI-Protocol-Version"
HEADER_AUTHORITY = "X-NoteAI-Authority"
HEADER_CONFIG_EPOCH = "X-NoteAI-Config-Epoch"
HEADER_KEY_EPOCH = "X-NoteAI-Key-Epoch"
HEADER_READINESS_CHALLENGE = "X-NoteAI-Readiness-Challenge"

PROTOCOL_VERSION = "claude-gateway.v2"
ALLOWED_MODELS = frozenset({
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6",
})
USAGE_COUNT_MAX = 1_000_000_000
USAGE_FIELDS = frozenset({
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
    "cache_creation",
})
USAGE_REQUIRED_FIELDS = frozenset({
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
})
USAGE_CACHE_FIELDS = frozenset({
    "ephemeral_5m_input_tokens",
    "ephemeral_1h_input_tokens",
})
OPERATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{24,128}$")


def valid_operation_id(value) -> bool:
    return isinstance(value, str) and OPERATION_ID_PATTERN.fullmatch(value) is not None


def _valid_token_count(value) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= USAGE_COUNT_MAX
    )


def valid_usage_envelope(value) -> bool:
    if value is None:
        return True
    if (
        not isinstance(value, dict)
        or set(value) - USAGE_FIELDS
        or not USAGE_REQUIRED_FIELDS.issubset(value)
    ):
        return False
    for key, item in value.items():
        if key == "cache_creation":
            if not isinstance(item, dict) or set(item) - USAGE_CACHE_FIELDS:
                return False
            if not all(_valid_token_count(count) for count in item.values()):
                return False
        elif not _valid_token_count(item):
            return False
    return True


def body_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def canonical_request(
    method: str,
    path: str,
    key_id: str,
    protocol_version: str,
    content_type: str,
    timestamp: str,
    nonce: str,
    body: bytes,
    *,
    authority: str = "",
    config_epoch: str = "",
    key_epoch: str = "",
) -> bytes:
    return "\n".join((
        method.upper(),
        path,
        authority,
        config_epoch,
        key_epoch,
        key_id,
        protocol_version,
        content_type,
        timestamp,
        nonce,
        body_sha256(body),
    )).encode("utf-8")


def signature(
    secret: str,
    method: str,
    path: str,
    key_id: str,
    protocol_version: str,
    content_type: str,
    timestamp: str,
    nonce: str,
    body: bytes,
    *,
    authority: str = "",
    config_epoch: str = "",
    key_epoch: str = "",
) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        canonical_request(
            method,
            path,
            key_id,
            protocol_version,
            content_type,
            timestamp,
            nonce,
            body,
            authority=authority,
            config_epoch=config_epoch,
            key_epoch=key_epoch,
        ),
        hashlib.sha256,
    ).hexdigest()


def auth_headers(
    *,
    key_id: str,
    secret: str,
    method: str,
    path: str,
    authority: str,
    config_epoch: str,
    key_epoch: str,
    body: bytes,
    timestamp: int | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    timestamp_text = str(int(time.time()) if timestamp is None else int(timestamp))
    nonce_text = nonce or secrets.token_urlsafe(24)
    content_type = "application/json"
    return {
        HEADER_KEY_ID: key_id,
        HEADER_TIMESTAMP: timestamp_text,
        HEADER_NONCE: nonce_text,
        HEADER_SIGNATURE: signature(
            secret=secret,
            method=method,
            path=path,
            key_id=key_id,
            protocol_version=PROTOCOL_VERSION,
            content_type=content_type,
            timestamp=timestamp_text,
            nonce=nonce_text,
            body=body,
            authority=authority,
            config_epoch=config_epoch,
            key_epoch=key_epoch,
        ),
        "Content-Type": content_type,
        "Accept": "application/x-ndjson, application/json",
        "Host": authority,
        HEADER_AUTHORITY: authority,
        HEADER_CONFIG_EPOCH: config_epoch,
        HEADER_KEY_EPOCH: key_epoch,
        HEADER_PROTOCOL_VERSION: PROTOCOL_VERSION,
    }


def readiness_attestation(secret: str, payload: dict) -> str:
    unsigned = dict(payload)
    unsigned.pop("attestation", None)
    canonical = json.dumps(
        unsigned,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hmac.new(
        secret.encode("utf-8"),
        b"noteai-readiness-v2\n" + canonical,
        hashlib.sha256,
    ).hexdigest()


def verify_readiness_attestation(secret: str, payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False
    supplied = payload.get("attestation")
    if not isinstance(supplied, str) or not re.fullmatch(r"[0-9a-f]{64}", supplied):
        return False
    return hmac.compare_digest(supplied, readiness_attestation(secret, payload))
