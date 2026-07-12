"""Shared wire constants and HMAC signing for the internal Claude Gateway."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time


MESSAGES_PATH = "/internal/v1/messages"
STREAM_PATH = "/internal/v1/messages/stream"

HEADER_KEY_ID = "X-NoteAI-Key-ID"
HEADER_TIMESTAMP = "X-NoteAI-Timestamp"
HEADER_NONCE = "X-NoteAI-Nonce"
HEADER_SIGNATURE = "X-NoteAI-Signature"
HEADER_PROTOCOL_VERSION = "X-NoteAI-Protocol-Version"

PROTOCOL_VERSION = "claude-gateway.v1"
ALLOWED_MODELS = frozenset({
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6",
})
USAGE_TOKEN_MAX = 1_000_000_000
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


def _valid_token_count(value) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= USAGE_TOKEN_MAX
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
) -> bytes:
    return "\n".join((
        method.upper(),
        path,
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
        ),
        hashlib.sha256,
    ).hexdigest()


def auth_headers(
    *,
    key_id: str,
    secret: str,
    method: str,
    path: str,
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
            secret,
            method,
            path,
            key_id,
            PROTOCOL_VERSION,
            content_type,
            timestamp_text,
            nonce_text,
            body,
        ),
        "Content-Type": content_type,
        "Accept": "application/x-ndjson, application/json",
        HEADER_PROTOCOL_VERSION: PROTOCOL_VERSION,
    }
