"""Recoverable AI admission, opaque payload refs, outbox and settlement.

The primary database stores only fixed states, canonical identifiers, hashes,
bounded counters and timestamps. Request/result bodies live behind a
``PayloadStore`` implementation and never enter SQL, task messages or logs.
No production storage adapter is selected implicitly: missing configuration
fails closed before billing or queue admission.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

import ai_operations
import billing
import content_retention
import db
import idempotency


MAX_OBJECT_BYTES = 128 * 1024 * 1024
MAX_INLINE_REQUEST_BYTES = 256 * 1024
MAX_MEDIA_REFS = 10
REQUEST_TTL_SECONDS = 7 * 24 * 60 * 60
RESULT_TTL_SECONDS = 30 * 24 * 60 * 60
OUTBOX_MAX_ATTEMPTS = 20
DURABLE_AI_NOTIFY_CHANNEL = "noteai_durable_ai_ready_v1"

_OPERATION_NAMESPACE = uuid.UUID("c5098114-a6c5-4c9f-a527-565123d2e1bd")
_REFERENCE_NAMESPACE = uuid.UUID("c1b87e7b-234d-44f7-83c8-b219ea1ec68a")
_OUTBOX_NAMESPACE = uuid.UUID("c15d23bb-d15b-41c5-b6e1-31963d2addc7")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RAW_MEDIA_FIELDS = frozenset({
    "cover_image",
    "cover_images",
    "extra_images",
    "image_base64",
    "video_file_id",
})
_FAILURE_CODES = frozenset({
    "worker_failed",
    "provider_failed",
    "payload_unavailable",
    "cancelled",
    "provider_outcome_unknown",
    "result_store_unknown",
})


class RefPurpose(str, Enum):
    REQUEST = "request"
    RESULT = "result"


class DurableAiError(RuntimeError):
    def __init__(self, code: str, message: str, *, http_status: int = 503):
        super().__init__(message)
        self.code = code
        self.http_status = int(http_status)


class PayloadUnavailable(DurableAiError):
    def __init__(self, code: str = "DURABLE_AI_STORAGE_UNAVAILABLE"):
        super().__init__(
            code,
            "Durable AI payload storage is unavailable",
            http_status=503,
        )


@dataclass(frozen=True)
class PayloadReference:
    id: str
    operation_id: str
    subject_hash: str
    purpose: str
    object_key_hash: str
    content_sha256: str
    size_bytes: int
    item_count: int
    schema_version: int
    encryption_mode: str
    key_epoch_hash: str
    state: str
    expires_at: str
    created_at: str
    ready_at: str
    deleted_at: str | None = None
    created: bool = field(default=True, compare=False, repr=False)

    def database_values(self) -> tuple[Any, ...]:
        return (
            self.id,
            self.operation_id,
            self.subject_hash,
            self.purpose,
            self.object_key_hash,
            self.content_sha256,
            self.size_bytes,
            self.item_count,
            self.schema_version,
            self.encryption_mode,
            self.key_epoch_hash,
            self.state,
            self.expires_at,
            self.created_at,
            self.ready_at,
            self.deleted_at,
        )


@dataclass(frozen=True)
class OutboxLease:
    outbox_id: str
    operation_id: str
    owner_token: str = field(repr=False)
    fence: int
    expires_at: str


class PayloadStore(ABC):
    @abstractmethod
    def put(
        self,
        *,
        operation_id: str,
        user_id: str,
        purpose: str | RefPurpose,
        payload: bytes,
        item_count: int,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> PayloadReference:
        raise NotImplementedError

    @abstractmethod
    def get(self, reference: PayloadReference, *, user_id: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def delete(self, reference: PayloadReference, *, user_id: str) -> bool:
        raise NotImplementedError


class UnavailablePayloadStore(PayloadStore):
    def put(self, **_kwargs) -> PayloadReference:
        raise PayloadUnavailable()

    def get(self, _reference: PayloadReference, *, user_id: str) -> bytes:
        del user_id
        raise PayloadUnavailable()

    def delete(self, _reference: PayloadReference, *, user_id: str) -> bool:
        del user_id
        raise PayloadUnavailable()


class InMemoryPayloadStore(PayloadStore):
    """Deterministic, owner-bound test store; never selected from environment."""

    def __init__(self, *, key_epoch: str = "test-key-epoch-1"):
        self._key_epoch = str(key_epoch or "")
        if not self._key_epoch:
            raise ValueError("key epoch is required")
        self._objects: dict[str, tuple[PayloadReference, bytes]] = {}
        self._lock = threading.Lock()

    def put(
        self,
        *,
        operation_id: str,
        user_id: str,
        purpose: str | RefPurpose,
        payload: bytes,
        item_count: int,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> PayloadReference:
        op_id = _canonical_uuid(operation_id, "operation id")
        purpose_value = _purpose(purpose)
        body = bytes(payload)
        if not body or len(body) > MAX_OBJECT_BYTES:
            raise ValueError("payload size is outside the durable object limit")
        count = _bounded_int(item_count, "item_count", minimum=0, maximum=1000)
        ttl = _bounded_int(
            ttl_seconds,
            "ttl_seconds",
            minimum=60,
            maximum=90 * 24 * 60 * 60,
        )
        subject_hash = idempotency.operation_subject_hash(str(user_id or ""))
        ref_id = str(uuid.uuid5(_REFERENCE_NAMESPACE, f"{op_id}:{purpose_value}"))
        now_value = _utc(now)
        now_iso = now_value.isoformat()
        descriptor = PayloadReference(
            id=ref_id,
            operation_id=op_id,
            subject_hash=subject_hash,
            purpose=purpose_value,
            object_key_hash=_sha256(f"noteai:private-object:v1:{ref_id}"),
            content_sha256=hashlib.sha256(body).hexdigest(),
            size_bytes=len(body),
            item_count=count,
            schema_version=1,
            encryption_mode="provider_managed",
            key_epoch_hash=_sha256(self._key_epoch),
            state="ready",
            expires_at=(now_value + timedelta(seconds=ttl)).isoformat(),
            created_at=now_iso,
            ready_at=now_iso,
        )
        with self._lock:
            existing = self._objects.get(ref_id)
            if existing:
                stored_ref, stored_body = existing
                if (
                    stored_ref.subject_hash != subject_hash
                    or stored_ref.purpose != purpose_value
                    or stored_body != body
                ):
                    raise DurableAiError(
                        "DURABLE_AI_REFERENCE_CONFLICT",
                        "Opaque payload reference conflicts with existing content",
                        http_status=409,
                    )
                return PayloadReference(
                    **{
                        **asdict(stored_ref),
                        "created": False,
                    }
                )
            self._objects[ref_id] = (descriptor, body)
        return descriptor

    def get(self, reference: PayloadReference, *, user_id: str) -> bytes:
        subject_hash = idempotency.operation_subject_hash(str(user_id or ""))
        with self._lock:
            stored = self._objects.get(reference.id)
            if not stored:
                raise PayloadUnavailable("DURABLE_AI_PAYLOAD_NOT_FOUND")
            stored_ref, body = stored
            if (
                stored_ref.subject_hash != subject_hash
                or reference.subject_hash != subject_hash
                or stored_ref.content_sha256 != reference.content_sha256
                or stored_ref.state != "ready"
            ):
                raise PayloadUnavailable("DURABLE_AI_PAYLOAD_NOT_FOUND")
            if _parse_clock(stored_ref.expires_at) <= datetime.now(timezone.utc):
                raise PayloadUnavailable("DURABLE_AI_PAYLOAD_EXPIRED")
            return bytes(body)

    def delete(self, reference: PayloadReference, *, user_id: str) -> bool:
        subject_hash = idempotency.operation_subject_hash(str(user_id or ""))
        if reference.subject_hash != subject_hash:
            return False
        with self._lock:
            stored = self._objects.get(reference.id)
            if not stored:
                return True
            stored_ref, _body = stored
            if (
                stored_ref.subject_hash != subject_hash
                or stored_ref.content_sha256 != reference.content_sha256
            ):
                return False
            del self._objects[reference.id]
        return True


_payload_store: PayloadStore = UnavailablePayloadStore()


def configure_payload_store(store: PayloadStore) -> None:
    """Install an explicit adapter; callers own its Secret/network lifecycle."""
    if not isinstance(store, PayloadStore):
        raise TypeError("store must implement PayloadStore")
    global _payload_store
    _payload_store = store


def reset_payload_store() -> None:
    global _payload_store
    _payload_store = UnavailablePayloadStore()


def get_payload_store() -> PayloadStore:
    return _payload_store


def _delete_uncommitted_reference(
    store: PayloadStore,
    reference: PayloadReference,
    *,
    user_id: str,
) -> None:
    if not reference.created:
        return
    try:
        deleted = store.delete(reference, user_id=user_id)
    except DurableAiError:
        raise
    except BaseException as exc:
        raise PayloadUnavailable(
            "DURABLE_AI_ORPHAN_CLEANUP_FAILED"
        ) from exc
    if not deleted:
        raise PayloadUnavailable("DURABLE_AI_ORPHAN_CLEANUP_FAILED")


class _ReferenceCommitGuard:
    """Delete a newly created object unless the enclosing DB commit succeeds."""

    def __init__(
        self,
        store: PayloadStore,
        reference: PayloadReference,
        *,
        user_id: str,
    ):
        self.store = store
        self.reference = reference
        self.user_id = user_id
        self._commit_requested = False

    def __enter__(self) -> "_ReferenceCommitGuard":
        return self

    def commit(self) -> None:
        self._commit_requested = True

    def __exit__(self, exc_type, _exc, _traceback) -> bool:
        if exc_type is not None or not self._commit_requested:
            _delete_uncommitted_reference(
                self.store,
                self.reference,
                user_id=self.user_id,
            )
        return False


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return current.astimezone(timezone.utc)


def _parse_clock(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _sha256(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else str(value).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _digest(value: str, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return normalized


def _canonical_uuid(value: str, label: str) -> str:
    raw = str(value or "").strip()
    try:
        parsed = uuid.UUID(raw)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"{label} must be a canonical UUID") from exc
    if str(parsed) != raw:
        raise ValueError(f"{label} must be a canonical UUID")
    return raw


def _bounded_int(
    value: int,
    label: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if normalized != value or normalized < minimum or normalized > maximum:
        raise ValueError(f"{label} is outside the allowed range")
    return normalized


def _purpose(value: str | RefPurpose) -> str:
    raw = value.value if isinstance(value, RefPurpose) else str(value or "")
    if raw not in {item.value for item in RefPurpose}:
        raise ValueError("invalid payload purpose")
    return raw


def operation_id_for(user_id: str, operation: str, request_id: str) -> str:
    normalized = idempotency.normalize_request_id(request_id)
    if not normalized:
        raise ValueError("request id is required")
    kind = ai_operations.OperationKind(str(operation or "")).value
    subject = idempotency.operation_subject_hash(str(user_id or ""))
    key_hash = _sha256(normalized)
    return str(uuid.uuid5(_OPERATION_NAMESPACE, f"{subject}:{kind}:{key_hash}"))


def payload_reference_id_for(operation_id: str, purpose: str | RefPurpose) -> str:
    """Return the stable opaque object reference for one operation purpose."""
    op_id = _canonical_uuid(operation_id, "operation id")
    purpose_value = _purpose(purpose)
    return str(uuid.uuid5(_REFERENCE_NAMESPACE, f"{op_id}:{purpose_value}"))


def _count_items(value: Any, *, depth: int = 0) -> int:
    if depth > 12:
        raise ValueError("payload nesting is too deep")
    if isinstance(value, dict):
        return min(
            1000,
            len(value)
            + sum(_count_items(item, depth=depth + 1) for item in value.values()),
        )
    if isinstance(value, list):
        return min(
            1000,
            len(value)
            + sum(_count_items(item, depth=depth + 1) for item in value),
        )
    return 1


def _reject_raw_media(value: Any, *, depth: int = 0) -> None:
    if depth > 12:
        raise DurableAiError(
            "DURABLE_AI_PAYLOAD_INVALID",
            "AI job payload nesting is too deep",
            http_status=422,
        )
    if isinstance(value, float) and not math.isfinite(value):
        raise DurableAiError(
            "DURABLE_AI_PAYLOAD_INVALID",
            "AI job payload contains a non-finite number",
            http_status=422,
        )
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key) in _RAW_MEDIA_FIELDS and item not in (None, "", []):
                raise DurableAiError(
                    "DURABLE_AI_MEDIA_REFERENCE_REQUIRED",
                    "Durable AI accepts only owner-bound opaque media references",
                    http_status=422,
                )
            if str(key) == "media_refs" and item not in (None, []):
                if not isinstance(item, list) or len(item) > MAX_MEDIA_REFS:
                    raise DurableAiError(
                        "DURABLE_AI_MEDIA_REFERENCE_INVALID",
                        "Invalid durable media reference list",
                        http_status=422,
                    )
                for ref in item:
                    try:
                        _canonical_uuid(str(ref), "media reference")
                    except ValueError as exc:
                        raise DurableAiError(
                            "DURABLE_AI_MEDIA_REFERENCE_INVALID",
                            "Invalid durable media reference",
                            http_status=422,
                        ) from exc
            _reject_raw_media(item, depth=depth + 1)
    elif isinstance(value, list):
        for item in value:
            _reject_raw_media(item, depth=depth + 1)


def canonical_payload(payload: Any) -> tuple[bytes, int]:
    _reject_raw_media(payload)
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DurableAiError(
            "DURABLE_AI_PAYLOAD_INVALID",
            "AI job payload is not canonical JSON",
            http_status=422,
        ) from exc
    if not encoded or len(encoded) > MAX_INLINE_REQUEST_BYTES:
        raise DurableAiError(
            "DURABLE_AI_PAYLOAD_TOO_LARGE",
            "AI job payload exceeds the inline request contract",
            http_status=413,
        )
    return encoded, _count_items(payload)


def media_reference_ids(payload: Any) -> list[str]:
    """Extract the canonical owner-bound media references from a request."""
    values: list[str] = []

    def visit(value: Any, *, depth: int = 0) -> None:
        if depth > 12:
            raise DurableAiError(
                "DURABLE_AI_PAYLOAD_INVALID",
                "AI job payload nesting is too deep",
                http_status=422,
            )
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key) == "media_refs" and item not in (None, []):
                    for reference_id in item:
                        values.append(
                            _canonical_uuid(str(reference_id), "media reference")
                        )
                visit(item, depth=depth + 1)
        elif isinstance(value, list):
            for item in value:
                visit(item, depth=depth + 1)

    try:
        visit(payload)
    except ValueError as exc:
        raise DurableAiError(
            "DURABLE_AI_MEDIA_REFERENCE_INVALID",
            "Invalid durable media reference",
            http_status=422,
        ) from exc
    if len(values) > MAX_MEDIA_REFS or len(values) != len(set(values)):
        raise DurableAiError(
            "DURABLE_AI_MEDIA_REFERENCE_INVALID",
            "Invalid durable media reference list",
            http_status=422,
        )
    return values


def _validate_reference(
    reference: PayloadReference,
    *,
    operation_id: str,
    subject_hash: str,
    purpose: RefPurpose,
) -> None:
    _canonical_uuid(reference.id, "reference id")
    if reference.operation_id != operation_id:
        raise ValueError("reference operation mismatch")
    if reference.subject_hash != subject_hash:
        raise ValueError("reference subject mismatch")
    if reference.purpose != purpose.value or reference.state != "ready":
        raise ValueError("reference state or purpose mismatch")
    for label, value in (
        ("object_key_hash", reference.object_key_hash),
        ("content_sha256", reference.content_sha256),
        ("key_epoch_hash", reference.key_epoch_hash),
    ):
        _digest(value, label)
    if reference.encryption_mode not in {"provider_managed", "envelope_aes256"}:
        raise ValueError("invalid encryption mode")
    if _parse_clock(reference.ready_at) >= _parse_clock(reference.expires_at):
        raise ValueError("reference expiry must follow readiness")


def _insert_payload_reference(tx: db.Transaction, reference: PayloadReference) -> None:
    tx.execute(
        "INSERT INTO ai_payload_refs("
        "id,operation_id,subject_hash,purpose,object_key_hash,content_sha256,"
        "size_bytes,item_count,schema_version,encryption_mode,key_epoch_hash,state,"
        "expires_at,created_at,ready_at,deleted_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        reference.database_values(),
    )


def admit_job(
    *,
    user_id: str,
    operation: str,
    request_id: str,
    payload: Any,
    now: datetime | None = None,
    store: PayloadStore | None = None,
) -> dict[str, Any]:
    """Persist object metadata, charge, queue, settlement and outbox atomically."""
    normalized_request_id = idempotency.normalize_request_id(request_id)
    if not normalized_request_id:
        raise ValueError("request id is required")
    try:
        kind = ai_operations.OperationKind(str(operation or "")).value
    except ValueError as exc:
        raise ValueError("invalid durable AI operation") from exc
    body, item_count = canonical_payload(payload)
    media_ids = media_reference_ids(payload)
    op_id = operation_id_for(user_id, kind, normalized_request_id)
    now_value = _utc(now)
    now_iso = now_value.isoformat()
    subject_hash = idempotency.operation_subject_hash(str(user_id or ""))
    request_hash = hashlib.sha256(body).hexdigest()
    payload_store = store or get_payload_store()
    try:
        request_ref = payload_store.put(
            operation_id=op_id,
            user_id=user_id,
            purpose=RefPurpose.REQUEST,
            payload=body,
            item_count=item_count,
            ttl_seconds=REQUEST_TTL_SECONDS,
            now=now_value,
        )
    except DurableAiError as exc:
        if exc.code == "DURABLE_AI_REFERENCE_CONFLICT":
            return {"state": "conflict"}
        raise
    _validate_reference(
        request_ref,
        operation_id=op_id,
        subject_hash=subject_hash,
        purpose=RefPurpose.REQUEST,
    )
    key_hash = _sha256(normalized_request_id)
    request_row_id = str(uuid.uuid5(_OPERATION_NAMESPACE, f"{op_id}:admission"))
    outbox_id = str(uuid.uuid5(_OUTBOX_NAMESPACE, op_id))
    lease_hash = _sha256(secrets.token_urlsafe(32))

    with _ReferenceCommitGuard(
        payload_store,
        request_ref,
        user_id=user_id,
    ) as reference_guard, db.transaction(write=True) as tx:
        try:
            content_retention.assert_user_writable_with_storage(tx, user_id)
        except ValueError as exc:
            raise DurableAiError(
                "DURABLE_AI_ACCOUNT_UNAVAILABLE",
                "Account is unavailable for durable AI admission",
                http_status=401,
            ) from exc
        cursor = tx.execute(
            "INSERT INTO idempotency_requests("
            "id,user_id,operation,key_hash,payload_hash,status,lease_token_hash,"
            "lease_expires_at,created_at,updated_at) "
            "VALUES(?,?,?,?,?,'running',?,?,?,?) "
            "ON CONFLICT(user_id,operation,key_hash) DO NOTHING",
            (
                request_row_id,
                user_id,
                kind,
                key_hash,
                request_hash,
                lease_hash,
                (now_value + timedelta(days=7)).isoformat(),
                now_iso,
                now_iso,
            ),
        )
        inserted = int(getattr(cursor, "rowcount", 0) or 0) == 1
        lock = " FOR UPDATE" if tx.postgres else ""
        claim = tx.fetchone(
            "SELECT * FROM idempotency_requests "
            f"WHERE user_id=? AND operation=? AND key_hash=?{lock}",
            (user_id, kind, key_hash),
        )
        if not claim:
            raise RuntimeError("durable admission row unavailable")
        current_claim = dict(claim)
        if not inserted:
            if current_claim.get("payload_hash") != request_hash:
                return {"state": "conflict"}
            link = tx.fetchone(
                "SELECT a.operation_id,o.status,s.billing_state "
                "FROM ai_operation_admissions a "
                "JOIN ai_operations o ON o.id=a.operation_id "
                "JOIN ai_operation_settlements s ON s.operation_id=o.id "
                f"WHERE a.idempotency_request_id=?{lock}",
                (current_claim["id"],),
            )
            if not link:
                return {"state": "legacy_unlinked"}
            return {
                "state": "existing",
                "operation_id": link["operation_id"],
                "status": link["status"],
                "billing_state": link["billing_state"],
            }

        locked_media: list[Any] = []
        if media_ids:
            try:
                import private_storage

                locked_media = private_storage.lock_ready_media_refs(
                    tx,
                    user_id,
                    media_ids,
                    now=now_value,
                )
            except private_storage.PrivateStorageError as exc:
                raise DurableAiError(
                    "DURABLE_AI_MEDIA_REFERENCE_UNAVAILABLE",
                    "Durable media reference is unavailable",
                    http_status=422,
                ) from exc
        charge = billing.check_and_deduct_in_transaction(tx, user_id, kind)
        subscription = tx.fetchone(
            "SELECT tier FROM subscriptions WHERE user_id=? AND is_active=1 "
            f"ORDER BY started_at DESC LIMIT 1{lock}",
            (user_id,),
        )
        priority = 1 if subscription and subscription["tier"] in {"pro_plus", "studio"} else 0
        ai_operations.enqueue_operation_in_transaction(
            tx,
            subject_hash=subject_hash,
            request_hash=request_hash,
            operation_kind=kind,
            operation_id=op_id,
            priority=priority,
            now=now_value,
        )
        if locked_media:
            private_storage.link_media_refs_in_transaction(
                tx,
                op_id,
                locked_media,
                now=now_value,
            )
        tx.execute(
            "INSERT INTO ai_operation_admissions("
            "operation_id,idempotency_request_id,created_at) VALUES(?,?,?)",
            (op_id, request_row_id, now_iso),
        )
        _insert_payload_reference(tx, request_ref)
        tx.execute(
            "INSERT INTO ai_operation_settlements("
            "operation_id,request_ref_id,billing_state,failure_code,created_at,updated_at) "
            "VALUES(?,?,'charged','',?,?)",
            (op_id, request_ref.id, now_iso, now_iso),
        )
        tx.execute(
            "INSERT INTO ai_operation_outbox("
            "id,operation_id,event_type,state,available_at,created_at,updated_at) "
            "VALUES(?,?,'operation_ready','pending',?,?,?)",
            (outbox_id, op_id, now_iso, now_iso, now_iso),
        )
        tx.execute(
            "UPDATE idempotency_requests SET usage_id=?,charged_subscription_id=?,"
            "charged_period_start=?,charge_source=?,credits_used=?,"
            "monthly_credits_used=?,wallet_credits_used=?,usage_created=1,charge_applied=1,"
            "usage_created_at=?,charged_at=?,updated_at=? WHERE id=?",
            (
                charge.get("usage_id"),
                charge.get("subscription_id") or None,
                charge.get("subscription_period_start") or None,
                charge.get("source") or "",
                float(charge.get("credits_used") or 0),
                float(charge.get("monthly_credits_used") or 0),
                float(charge.get("wallet_credits_used") or 0),
                now_iso,
                now_iso,
                now_iso,
                request_row_id,
            ),
        )
        reference_guard.commit()
    return {
        "state": "admitted",
        "operation_id": op_id,
        "status": ai_operations.OperationStatus.QUEUED.value,
        "billing_state": "charged",
    }


def _reference_from_row(row: Any) -> PayloadReference:
    data = dict(row)
    return PayloadReference(
        **{
            field_name: data.get(field_name)
            for field_name in PayloadReference.__dataclass_fields__
            if field_name != "created"
        },
        created=False,
    )


def request_context(operation_id: str) -> dict[str, Any] | None:
    """Return internal worker metadata without raw user content."""
    op_id = _canonical_uuid(operation_id, "operation id")
    row = db.fetchone(
        "SELECT i.user_id,i.usage_id,o.operation_kind,r.* "
        "FROM ai_operations o "
        "JOIN ai_operation_admissions a ON a.operation_id=o.id "
        "JOIN idempotency_requests i ON i.id=a.idempotency_request_id "
        "JOIN ai_operation_settlements s ON s.operation_id=o.id "
        "JOIN ai_payload_refs r ON r.id=s.request_ref_id "
        "WHERE o.id=? AND r.purpose='request' AND r.state='ready'",
        (op_id,),
    )
    if not row:
        return None
    data = dict(row)
    reference = _reference_from_row(data)
    return {
        "user_id": data["user_id"],
        "usage_id": data.get("usage_id"),
        "operation_kind": data["operation_kind"],
        "reference": reference,
    }


def load_request(
    operation_id: str,
    *,
    store: PayloadStore | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    context = request_context(operation_id)
    if not context:
        raise PayloadUnavailable("DURABLE_AI_PAYLOAD_NOT_FOUND")
    body = (store or get_payload_store()).get(
        context["reference"],
        user_id=context["user_id"],
    )
    if hashlib.sha256(body).hexdigest() != context["reference"].content_sha256:
        raise PayloadUnavailable("DURABLE_AI_PAYLOAD_HASH_MISMATCH")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PayloadUnavailable("DURABLE_AI_PAYLOAD_INVALID") from exc
    return context, payload


def _settlement_rows(
    tx: db.Transaction,
    operation_id: str,
) -> tuple[dict[str, Any], dict[str, Any]] | tuple[None, None]:
    admission_lock = " FOR UPDATE OF i" if tx.postgres else ""
    settlement_lock = " FOR UPDATE" if tx.postgres else ""
    admission = tx.fetchone(
        "SELECT i.* FROM ai_operation_admissions a "
        "JOIN idempotency_requests i ON i.id=a.idempotency_request_id "
        f"WHERE a.operation_id=?{admission_lock}",
        (operation_id,),
    )
    settlement = tx.fetchone(
        "SELECT * FROM ai_operation_settlements WHERE operation_id=?"
        f"{settlement_lock}",
        (operation_id,),
    )
    if not admission or not settlement:
        return None, None
    return dict(admission), dict(settlement)


def _user_for_operation(operation_id: str) -> str | None:
    row = db.fetchone(
        "SELECT i.user_id FROM ai_operation_admissions a "
        "JOIN idempotency_requests i ON i.id=a.idempotency_request_id "
        "WHERE a.operation_id=?",
        (operation_id,),
    )
    return str(row["user_id"]) if row else None


def begin_provider_attempt_for_user(
    lease: ai_operations.OperationLease,
    *,
    user_id: str,
    provider: str,
    request_hash: str,
    model_hash: str,
    input_count: int = 0,
    now: datetime | None = None,
) -> ai_operations.ProviderAttempt | None:
    """Acquire the canonical user fence immediately before provider admission."""
    now_iso = _utc(now).isoformat()
    with db.transaction(write=True) as tx:
        try:
            content_retention.assert_user_writable_with_storage(
                tx,
                user_id,
                lock_row=False,
            )
        except ValueError:
            return None
        owned = tx.fetchone(
            "SELECT a.operation_id FROM ai_operation_admissions a "
            "JOIN idempotency_requests i ON i.id=a.idempotency_request_id "
            "WHERE a.operation_id=? AND i.user_id=?",
            (lease.operation_id, user_id),
        )
        if not owned:
            return None
        return ai_operations.begin_provider_attempt_in_transaction(
            tx,
            lease,
            provider=provider,
            request_hash=request_hash,
            model_hash=model_hash,
            input_count=input_count,
            now_iso=now_iso,
        )


def settle_success(
    lease: ai_operations.OperationLease,
    *,
    result_payload: Any,
    result_count: int = 1,
    now: datetime | None = None,
    store: PayloadStore | None = None,
) -> bool:
    user_id = _user_for_operation(lease.operation_id)
    if not user_id:
        return False
    body = json.dumps(
        result_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if not body or len(body) > MAX_OBJECT_BYTES:
        raise ValueError("result payload size is outside the durable object limit")
    count = _bounded_int(result_count, "result_count", minimum=0, maximum=1000)
    now_value = _utc(now)
    payload_store = store or get_payload_store()
    result_ref = payload_store.put(
        operation_id=lease.operation_id,
        user_id=user_id,
        purpose=RefPurpose.RESULT,
        payload=body,
        item_count=count,
        ttl_seconds=RESULT_TTL_SECONDS,
        now=now_value,
    )
    subject_hash = idempotency.operation_subject_hash(user_id)
    _validate_reference(
        result_ref,
        operation_id=lease.operation_id,
        subject_hash=subject_hash,
        purpose=RefPurpose.RESULT,
    )
    now_iso = now_value.isoformat()
    with _ReferenceCommitGuard(
        payload_store,
        result_ref,
        user_id=user_id,
    ) as reference_guard, db.transaction(write=True) as tx:
        try:
            content_retention.assert_user_writable_with_storage(
                tx,
                user_id,
                lock_row=False,
            )
        except ValueError:
            return False
        claim, settlement = _settlement_rows(tx, lease.operation_id)
        if (
            not claim
            or not settlement
            or settlement["billing_state"] != "charged"
            or claim["status"] != "running"
        ):
            return False
        if not ai_operations.finish_operation_in_transaction(
            tx,
            lease,
            status=ai_operations.OperationStatus.SUCCEEDED,
            result_hash=result_ref.content_sha256,
            result_count=count,
            now_iso=now_iso,
        ):
            return False
        _insert_payload_reference(tx, result_ref)
        tx.execute(
            "UPDATE idempotency_requests SET status='completed',complete_applied=1,"
            "completed_at=?,updated_at=? WHERE id=? AND status='running'",
            (now_iso, now_iso, claim["id"]),
        )
        tx.execute(
            "UPDATE ai_operation_settlements SET result_ref_id=?,"
            "billing_state='completed',failure_code='',settled_at=?,updated_at=? "
            "WHERE operation_id=? AND billing_state='charged'",
            (result_ref.id, now_iso, now_iso, lease.operation_id),
        )
        reference_guard.commit()
    return True


def settle_failure(
    lease: ai_operations.OperationLease,
    *,
    failure_code: str,
    cancelled: bool = False,
    now: datetime | None = None,
) -> bool:
    code = str(failure_code or "")
    if code not in _FAILURE_CODES - {
        "provider_outcome_unknown",
        "result_store_unknown",
    }:
        raise ValueError("invalid durable AI failure code")
    user_id = _user_for_operation(lease.operation_id)
    if not user_id:
        return False
    now_iso = _utc(now).isoformat()
    with db.transaction(write=True) as tx:
        try:
            content_retention.assert_user_writable_with_storage(
                tx,
                user_id,
                lock_row=False,
            )
        except ValueError:
            return False
        claim, settlement = _settlement_rows(tx, lease.operation_id)
        if (
            not claim
            or not settlement
            or settlement["billing_state"] != "charged"
            or claim["status"] != "running"
        ):
            return False
        terminal_status = (
            ai_operations.OperationStatus.CANCELLED
            if cancelled
            else ai_operations.OperationStatus.FAILED
        )
        if not ai_operations.finish_operation_in_transaction(
            tx,
            lease,
            status=terminal_status,
            now_iso=now_iso,
        ):
            return False
        idempotency._fail_running_request_in_transaction(
            tx,
            claim,
            failure_code=code,
            now_iso=now_iso,
        )
        tx.execute(
            "UPDATE ai_operation_settlements SET billing_state='refunded',"
            "failure_code=?,settled_at=?,updated_at=? "
            "WHERE operation_id=? AND billing_state='charged'",
            (code, now_iso, now_iso, lease.operation_id),
        )
    return True


def settle_outcome_unknown(
    lease: ai_operations.OperationLease,
    *,
    failure_code: str = "provider_outcome_unknown",
    now: datetime | None = None,
) -> bool:
    code = str(failure_code or "")
    if code not in {"provider_outcome_unknown", "result_store_unknown"}:
        raise ValueError("invalid unknown-outcome code")
    user_id = _user_for_operation(lease.operation_id)
    if not user_id:
        return False
    now_iso = _utc(now).isoformat()
    with db.transaction(write=True) as tx:
        try:
            content_retention.assert_user_writable_with_storage(
                tx,
                user_id,
                lock_row=False,
            )
        except ValueError:
            return False
        claim, settlement = _settlement_rows(tx, lease.operation_id)
        if (
            not claim
            or not settlement
            or settlement["billing_state"] != "charged"
            or claim["status"] != "running"
        ):
            return False
        if not ai_operations.mark_operation_outcome_unknown_in_transaction(
            tx,
            lease,
            now_iso=now_iso,
        ):
            return False
        tx.execute(
            "UPDATE idempotency_requests SET failure_code=?,updated_at=? "
            "WHERE id=? AND status='running'",
            (code, now_iso, claim["id"]),
        )
        tx.execute(
            "UPDATE ai_operation_settlements SET billing_state='needs_manual',"
            "failure_code=?,settled_at=?,updated_at=? "
            "WHERE operation_id=? AND billing_state='charged'",
            (code, now_iso, now_iso, lease.operation_id),
        )
    return True


def claim_outbox(
    *,
    lease_seconds: int = 30,
    owner_token: str | None = None,
    operation_id: str | None = None,
    now: datetime | None = None,
) -> OutboxLease | None:
    seconds = _bounded_int(
        lease_seconds,
        "lease_seconds",
        minimum=1,
        maximum=300,
    )
    token = str(owner_token or secrets.token_urlsafe(32))
    if len(token) < 16 or len(token) > 512:
        raise ValueError("owner token length is invalid")
    exact_operation_id = (
        _canonical_uuid(operation_id, "operation_id")
        if operation_id is not None
        else None
    )
    now_value = _utc(now)
    now_iso = now_value.isoformat()
    expires_iso = (now_value + timedelta(seconds=seconds)).isoformat()
    with db.transaction(write=True) as tx:
        row_lock = " FOR UPDATE OF b SKIP LOCKED" if tx.postgres else ""
        if exact_operation_id is not None:
            exact = tx.fetchone(
                "SELECT b.* FROM ai_operation_outbox b "
                "WHERE b.operation_id=? AND b.state='pending' "
                "AND b.available_at<=? AND b.attempt_count<? "
                "AND (b.lease_expires_at IS NULL OR b.lease_expires_at<=?) "
                f"ORDER BY b.created_at,b.id LIMIT 1{row_lock}",
                (
                    exact_operation_id,
                    now_iso,
                    OUTBOX_MAX_ATTEMPTS,
                    now_iso,
                ),
            )
            current = dict(exact) if exact else None
        else:
            state_lock = " FOR UPDATE" if tx.postgres else ""
            dispatch = tx.fetchone(
                f"SELECT priority_streak FROM ai_dispatch_state "
                f"WHERE service_key='durable_ai'{state_lock}"
            )
            streak = min(
                3,
                max(0, int(dict(dispatch).get("priority_streak") or 0))
                if dispatch else 0,
            )

            def candidate(priority_lane: bool):
                predicate = "o.priority>0" if priority_lane else "o.priority=0"
                return tx.fetchone(
                    "SELECT b.* FROM ai_operation_outbox b "
                    "JOIN ai_operations o ON o.id=b.operation_id "
                    "WHERE b.state='pending' AND b.available_at<=? "
                    "AND b.attempt_count<? "
                    "AND (b.lease_expires_at IS NULL OR b.lease_expires_at<=?) "
                    f"AND {predicate} "
                    f"ORDER BY b.created_at,b.id LIMIT 1{row_lock}",
                    (now_iso, OUTBOX_MAX_ATTEMPTS, now_iso),
                )

            priority_candidate = candidate(True)
            standard_candidate = candidate(False)
            priority_row = (
                dict(priority_candidate) if priority_candidate else None
            )
            standard_row = (
                dict(standard_candidate) if standard_candidate else None
            )
            if priority_row and standard_row:
                current = standard_row if streak >= 3 else priority_row
            else:
                current = priority_row or standard_row
        if not current:
            return None
        if exact_operation_id is None:
            next_streak = (
                min(3, streak + 1)
                if int(
                    tx.fetchone(
                        "SELECT priority FROM ai_operations WHERE id=?",
                        (current["operation_id"],),
                    )["priority"]
                    or 0
                )
                > 0
                else 0
            )
            tx.execute(
                "UPDATE ai_dispatch_state SET priority_streak=?,updated_at=? "
                "WHERE service_key='durable_ai'",
                (next_streak, now_iso),
            )
        fence = int(current.get("lease_fence") or 0) + 1
        tx.execute(
            "UPDATE ai_operation_outbox SET lease_owner_hash=?,lease_fence=?,"
            "lease_expires_at=?,attempt_count=attempt_count+1,updated_at=? "
            "WHERE id=? AND state='pending'",
            (_sha256(token), fence, expires_iso, now_iso, current["id"]),
        )
    return OutboxLease(
        current["id"],
        current["operation_id"],
        token,
        fence,
        expires_iso,
    )


def _mark_outbox_delivered_in_transaction(
    tx: db.Transaction,
    lease: OutboxLease,
    *,
    now_iso: str,
    notify: bool,
) -> bool:
    if notify and not tx.postgres:
        raise DurableAiError(
            "DURABLE_AI_POSTGRES_REQUIRED",
            "Native durable AI wake-up requires PostgreSQL",
        )
    lock = " FOR UPDATE" if tx.postgres else ""
    row = tx.fetchone(
        f"SELECT * FROM ai_operation_outbox WHERE id=?{lock}",
        (lease.outbox_id,),
    )
    if not row:
        return False
    current = dict(row)
    if not (
        current.get("state") == "pending"
        and current.get("operation_id") == lease.operation_id
        and int(current.get("lease_fence") or 0) == lease.fence
        and current.get("lease_owner_hash") == _sha256(lease.owner_token)
        and str(current.get("lease_expires_at") or "") > now_iso
    ):
        return False
    cursor = tx.execute(
        "UPDATE ai_operation_outbox SET state='delivered',"
        "lease_owner_hash=NULL,lease_expires_at=NULL,delivered_at=?,updated_at=? "
        "WHERE id=? AND state='pending'",
        (now_iso, now_iso, lease.outbox_id),
    )
    if int(getattr(cursor, "rowcount", 0) or 0) != 1:
        return False
    if notify:
        tx.execute(
            "SELECT pg_notify(?,?)",
            (DURABLE_AI_NOTIFY_CHANNEL, lease.operation_id),
        )
    return True


def mark_outbox_delivered(
    lease: OutboxLease,
    *,
    now: datetime | None = None,
) -> bool:
    """Acknowledge an injected publisher after it emits the operation UUID."""
    now_iso = _utc(now).isoformat()
    with db.transaction(write=True) as tx:
        return _mark_outbox_delivered_in_transaction(
            tx,
            lease,
            now_iso=now_iso,
            notify=False,
        )


def mark_outbox_delivered_and_notify(
    lease: OutboxLease,
    *,
    now: datetime | None = None,
) -> bool:
    """Commit delivered state and a PostgreSQL wake hint in one transaction."""
    now_iso = _utc(now).isoformat()
    with db.transaction(write=True) as tx:
        return _mark_outbox_delivered_in_transaction(
            tx,
            lease,
            now_iso=now_iso,
            notify=True,
        )


def _claim_delivered_operation(
    *,
    operation_id: str | None,
    lease_seconds: int,
    owner_token: str | None,
    now: datetime | None,
) -> ai_operations.OperationLease | None:
    now_value = _utc(now)
    now_iso = now_value.isoformat()
    op_id = (
        _canonical_uuid(operation_id, "operation id")
        if operation_id is not None
        else None
    )
    with db.transaction(write=True) as tx:
        exact_predicate = "AND o.id=? " if op_id else ""
        params: tuple[Any, ...] = (
            (op_id, now_iso, now_iso)
            if op_id
            else (now_iso, now_iso)
        )
        lock = " FOR UPDATE OF o SKIP LOCKED" if tx.postgres else ""
        row = tx.fetchone(
            "SELECT o.id FROM ai_operation_outbox b "
            "JOIN ai_operations o ON o.id=b.operation_id "
            "JOIN ai_operation_settlements s ON s.operation_id=o.id "
            "WHERE b.state='delivered' AND s.billing_state='charged' "
            f"{exact_predicate}"
            "AND ((o.status='queued' AND o.available_at<=?) OR "
            "(o.status='running' AND o.provider_phase='not_started' "
            "AND o.lease_expires_at IS NOT NULL AND o.lease_expires_at<=?)) "
            "ORDER BY b.delivered_at,b.id LIMIT 1"
            f"{lock}",
            params,
        )
        if not row:
            return None
        return ai_operations.claim_operation_in_transaction(
            tx,
            row["id"],
            lease_seconds=lease_seconds,
            owner_token=owner_token,
            now=now_value,
        )


def claim_delivered_operation(
    operation_id: str,
    *,
    lease_seconds: int = 900,
    owner_token: str | None = None,
    now: datetime | None = None,
) -> ai_operations.OperationLease | None:
    """Claim one exact UUID only while its authoritative Outbox row is delivered."""
    return _claim_delivered_operation(
        operation_id=operation_id,
        lease_seconds=lease_seconds,
        owner_token=owner_token,
        now=now,
    )


def claim_next_delivered_operation(
    *,
    lease_seconds: int = 900,
    owner_token: str | None = None,
    now: datetime | None = None,
) -> ai_operations.OperationLease | None:
    """Claim the next delivered UUID; notifications are only wake hints."""
    return _claim_delivered_operation(
        operation_id=None,
        lease_seconds=lease_seconds,
        owner_token=owner_token,
        now=now,
    )


def recover_unstarted_leases(
    *,
    limit: int = 10,
    now: datetime | None = None,
) -> int:
    """Return only expired, provider-free leases to the content-free Outbox."""
    bounded_limit = _bounded_int(limit, "limit", minimum=1, maximum=100)
    now_iso = _utc(now).isoformat()
    recovered = 0
    for _index in range(bounded_limit):
        candidate = db.fetchone(
            "SELECT o.id,i.user_id FROM ai_operations o "
            "JOIN ai_operation_admissions a ON a.operation_id=o.id "
            "JOIN idempotency_requests i ON i.id=a.idempotency_request_id "
            "JOIN ai_operation_settlements s ON s.operation_id=o.id "
            "JOIN ai_operation_outbox b ON b.operation_id=o.id "
            "WHERE o.status='running' AND o.provider_phase='not_started' "
            "AND o.lease_expires_at IS NOT NULL AND o.lease_expires_at<=? "
            "AND s.billing_state='charged' AND b.state='delivered' "
            "AND b.attempt_count<? ORDER BY o.lease_expires_at,o.id LIMIT 1",
            (now_iso, OUTBOX_MAX_ATTEMPTS),
        )
        if not candidate:
            break
        operation_id = candidate["id"]
        user_id = candidate["user_id"]
        with db.transaction(write=True) as tx:
            try:
                content_retention.assert_user_writable_with_storage(
                    tx,
                    user_id,
                    lock_row=False,
                )
            except ValueError:
                continue
            lock = " FOR UPDATE" if tx.postgres else ""
            operation = tx.fetchone(
                f"SELECT * FROM ai_operations WHERE id=?{lock}",
                (operation_id,),
            )
            outbox = tx.fetchone(
                f"SELECT * FROM ai_operation_outbox WHERE operation_id=?{lock}",
                (operation_id,),
            )
            settlement = tx.fetchone(
                f"SELECT billing_state FROM ai_operation_settlements "
                f"WHERE operation_id=?{lock}",
                (operation_id,),
            )
            if not operation or not outbox or not settlement:
                continue
            current_operation = dict(operation)
            current_outbox = dict(outbox)
            if not (
                current_operation.get("status") == "running"
                and current_operation.get("provider_phase") == "not_started"
                and str(current_operation.get("lease_expires_at") or "") <= now_iso
                and current_outbox.get("state") == "delivered"
                and int(current_outbox.get("attempt_count") or 0)
                < OUTBOX_MAX_ATTEMPTS
                and settlement["billing_state"] == "charged"
            ):
                continue
            tx.execute(
                "UPDATE ai_operation_outbox SET state='pending',available_at=?,"
                "lease_owner_hash=NULL,lease_expires_at=NULL,delivered_at=NULL,"
                "updated_at=? WHERE operation_id=? AND state='delivered'",
                (now_iso, now_iso, operation_id),
            )
            recovered += 1
    return recovered


def reconcile_stale_provider_outcomes(
    *,
    limit: int = 10,
    now: datetime | None = None,
) -> int:
    """Quarantine stale provider-side effects without retrying or refunding."""
    bounded_limit = _bounded_int(limit, "limit", minimum=1, maximum=100)
    now_iso = _utc(now).isoformat()
    reconciled = 0
    for _index in range(bounded_limit):
        candidate = db.fetchone(
            "SELECT o.id,i.user_id FROM ai_operations o "
            "JOIN ai_operation_admissions a ON a.operation_id=o.id "
            "JOIN idempotency_requests i ON i.id=a.idempotency_request_id "
            "JOIN ai_operation_settlements s ON s.operation_id=o.id "
            "WHERE o.status='running' AND o.provider_phase<>'not_started' "
            "AND o.lease_expires_at IS NOT NULL AND o.lease_expires_at<=? "
            "AND s.billing_state='charged' "
            "ORDER BY o.lease_expires_at,o.id LIMIT 1",
            (now_iso,),
        )
        if not candidate:
            break
        operation_id = candidate["id"]
        user_id = candidate["user_id"]
        with db.transaction(write=True) as tx:
            try:
                content_retention.assert_user_writable_with_storage(
                    tx,
                    user_id,
                    lock_row=False,
                )
            except ValueError:
                continue
            lock = " FOR UPDATE" if tx.postgres else ""
            operation = tx.fetchone(
                f"SELECT * FROM ai_operations WHERE id=?{lock}",
                (operation_id,),
            )
            claim, settlement = _settlement_rows(tx, operation_id)
            if not operation or not claim or not settlement:
                continue
            current = dict(operation)
            if not (
                current.get("status") == "running"
                and current.get("provider_phase") != "not_started"
                and str(current.get("lease_expires_at") or "") <= now_iso
                and settlement["billing_state"] == "charged"
                and claim["status"] == "running"
            ):
                continue
            ai_operations.quarantine_stale_started_in_transaction(
                tx,
                current,
                now_iso=now_iso,
            )
            tx.execute(
                "UPDATE idempotency_requests SET failure_code="
                "'provider_outcome_unknown',updated_at=? "
                "WHERE id=? AND status='running'",
                (now_iso, claim["id"]),
            )
            tx.execute(
                "UPDATE ai_operation_settlements SET billing_state='needs_manual',"
                "failure_code='provider_outcome_unknown',settled_at=?,updated_at=? "
                "WHERE operation_id=? AND billing_state='charged'",
                (now_iso, now_iso, operation_id),
            )
            reconciled += 1
    return reconciled


def settle_unstarted_user_jobs_for_deletion_with_storage(
    tx: db.Transaction,
    user_id: str,
    *,
    now: datetime | None = None,
) -> int:
    """Cancel/refund only work proved provider-free under the user write fence."""
    now_iso = _utc(now).isoformat()
    lock = " FOR UPDATE OF o,s,i" if tx.postgres else ""
    rows = tx.fetchall(
        "SELECT o.id AS operation_id,o.status AS operation_status,"
        "o.provider_phase,s.billing_state,i.* "
        "FROM ai_operation_admissions a "
        "JOIN ai_operations o ON o.id=a.operation_id "
        "JOIN ai_operation_settlements s ON s.operation_id=o.id "
        "JOIN idempotency_requests i ON i.id=a.idempotency_request_id "
        "WHERE i.user_id=? AND i.status='running' "
        "ORDER BY i.created_at,i.id"
        + lock,
        (user_id,),
    )
    settled = 0
    for row in rows:
        current = dict(row)
        status = current["operation_status"]
        phase = current["provider_phase"]
        billing_state = current["billing_state"]
        if billing_state != "charged":
            raise ValueError("durable AI settlement is inconsistent")
        provider_free = (
            status == ai_operations.OperationStatus.QUEUED.value
            or (
                status == ai_operations.OperationStatus.RUNNING.value
                and phase == ai_operations.ProviderPhase.NOT_STARTED.value
            )
        )
        if not provider_free:
            raise ValueError("有正在处理的 AI 请求，请等待完成后重试删除")
        if not ai_operations.cancel_unstarted_operation_in_transaction(
            tx,
            current["operation_id"],
            now_iso=now_iso,
        ):
            raise ValueError("durable AI cancellation fence was lost")
        idempotency._fail_running_request_in_transaction(
            tx,
            current,
            failure_code="stream_cancelled",
            now_iso=now_iso,
        )
        tx.execute(
            "UPDATE ai_operation_settlements SET billing_state='refunded',"
            "failure_code='cancelled',settled_at=?,updated_at=? "
            "WHERE operation_id=? AND billing_state='charged'",
            (now_iso, now_iso, current["operation_id"]),
        )
        tx.execute(
            "UPDATE ai_operation_outbox SET state='dead',updated_at=? "
            "WHERE operation_id=? AND state IN ('pending','delivered')",
            (now_iso, current["operation_id"]),
        )
        settled += 1
    return settled


def delete_user_payloads(
    user_id: str,
    *,
    store: PayloadStore | None = None,
    now: datetime | None = None,
) -> int:
    """Idempotently erase owner objects before primary account deletion."""
    rows = db.fetchall(
        "SELECT r.* FROM ai_payload_refs r "
        "JOIN ai_operation_admissions a ON a.operation_id=r.operation_id "
        "JOIN idempotency_requests i ON i.id=a.idempotency_request_id "
        "WHERE i.user_id=? AND r.state='ready' ORDER BY r.created_at,r.id",
        (user_id,),
    )
    if not rows:
        return 0
    payload_store = store or get_payload_store()
    references = [_reference_from_row(row) for row in rows]
    for reference in references:
        if not payload_store.delete(reference, user_id=user_id):
            raise PayloadUnavailable("DURABLE_AI_PAYLOAD_DELETE_FAILED")
    now_iso = _utc(now).isoformat()
    deleted = 0
    with db.transaction(write=True) as tx:
        try:
            content_retention.lock_user_write_fence_with_storage(
                tx,
                user_id,
                allow_deletion_requested=True,
            )
        except ValueError as exc:
            raise PayloadUnavailable(
                "DURABLE_AI_PAYLOAD_OWNER_UNAVAILABLE"
            ) from exc
        lock = " FOR UPDATE OF r,i" if tx.postgres else ""
        for reference in references:
            owned = tx.fetchone(
                "SELECT r.id,r.state FROM ai_payload_refs r "
                "JOIN ai_operation_admissions a ON a.operation_id=r.operation_id "
                "JOIN idempotency_requests i ON i.id=a.idempotency_request_id "
                f"WHERE i.user_id=? AND r.id=?{lock}",
                (user_id, reference.id),
            )
            if not owned or owned["state"] != "ready":
                continue
            tx.execute(
                "UPDATE ai_payload_refs SET state='deleted',deleted_at=? "
                "WHERE id=? AND state='ready'",
                (now_iso, reference.id),
            )
            deleted += 1
    return deleted


def has_ready_user_payloads(storage: Any, user_id: str) -> bool:
    return bool(
        storage.fetchone(
            "SELECT 1 FROM ai_payload_refs r "
            "JOIN ai_operation_admissions a ON a.operation_id=r.operation_id "
            "JOIN idempotency_requests i ON i.id=a.idempotency_request_id "
            "WHERE i.user_id=? AND r.state='ready' LIMIT 1",
            (user_id,),
        )
    )


def status_for_user(user_id: str, operation_id: str) -> dict[str, Any] | None:
    try:
        op_id = _canonical_uuid(operation_id, "operation id")
    except ValueError:
        return None
    row = db.fetchone(
        "SELECT o.id AS operation_id,o.operation_kind,o.status,o.priority,"
        "o.event_sequence,o.result_count,o.created_at,o.updated_at,o.started_at,"
        "o.terminal_at,s.billing_state,s.failure_code,"
        "CASE WHEN s.result_ref_id IS NULL THEN 0 ELSE 1 END AS result_available "
        "FROM ai_operations o "
        "JOIN ai_operation_admissions a ON a.operation_id=o.id "
        "JOIN idempotency_requests i ON i.id=a.idempotency_request_id "
        "JOIN ai_operation_settlements s ON s.operation_id=o.id "
        "WHERE i.user_id=? AND o.id=?",
        (str(user_id or ""), op_id),
    )
    if not row:
        return None
    result = dict(row)
    if result["billing_state"] == "refunded":
        result["user_status"] = "refunded"
    elif result["status"] == "outcome_unknown":
        result["user_status"] = "needs_manual"
    else:
        result["user_status"] = result["status"]
    result["result_available"] = bool(result["result_available"])
    return result


def events_for_user(
    user_id: str,
    operation_id: str,
    *,
    after_sequence: int = 0,
) -> list[dict[str, Any]] | None:
    status = status_for_user(user_id, operation_id)
    if not status:
        return None
    after = _bounded_int(
        after_sequence,
        "after_sequence",
        minimum=0,
        maximum=2_147_483_647,
    )
    rows = db.fetchall(
        "SELECT sequence,event_type,operation_status,provider,item_count,recorded_at "
        "FROM ai_operation_events WHERE operation_id=? AND sequence>? "
        "ORDER BY sequence",
        (operation_id, after),
    )
    return [dict(row) for row in rows]


def result_for_user(
    user_id: str,
    operation_id: str,
    *,
    store: PayloadStore | None = None,
) -> Any:
    status = status_for_user(user_id, operation_id)
    if not status:
        raise DurableAiError(
            "DURABLE_AI_JOB_NOT_FOUND",
            "Durable AI job was not found",
            http_status=404,
        )
    if status["status"] != "succeeded" or not status["result_available"]:
        raise DurableAiError(
            "DURABLE_AI_RESULT_NOT_READY",
            "Durable AI result is not ready",
            http_status=409,
        )
    row = db.fetchone(
        "SELECT r.* FROM ai_operation_settlements s "
        "JOIN ai_payload_refs r ON r.id=s.result_ref_id "
        "WHERE s.operation_id=? AND r.purpose='result' AND r.state='ready'",
        (operation_id,),
    )
    if not row:
        raise PayloadUnavailable("DURABLE_AI_RESULT_NOT_FOUND")
    reference = _reference_from_row(row)
    body = (store or get_payload_store()).get(reference, user_id=user_id)
    if hashlib.sha256(body).hexdigest() != reference.content_sha256:
        raise PayloadUnavailable("DURABLE_AI_PAYLOAD_HASH_MISMATCH")
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PayloadUnavailable("DURABLE_AI_RESULT_INVALID") from exc


def admin_summary() -> dict[str, Any]:
    """Return fixed counts/clocks only; no subject, request or object hashes."""
    status_rows = db.fetchall(
        "SELECT status,COUNT(*) AS count FROM ai_operations "
        "GROUP BY status ORDER BY status"
    )
    settlement_rows = db.fetchall(
        "SELECT billing_state,COUNT(*) AS count FROM ai_operation_settlements "
        "GROUP BY billing_state ORDER BY billing_state"
    )
    outbox_rows = db.fetchall(
        "SELECT state,COUNT(*) AS count FROM ai_operation_outbox "
        "GROUP BY state ORDER BY state"
    )
    oldest = db.fetchone(
        "SELECT MIN(created_at) AS oldest_queued_at FROM ai_operations "
        "WHERE status='queued'"
    )
    return {
        "operations": {row["status"]: int(row["count"]) for row in status_rows},
        "settlements": {
            row["billing_state"]: int(row["count"]) for row in settlement_rows
        },
        "outbox": {row["state"]: int(row["count"]) for row in outbox_rows},
        "oldest_queued_at": oldest["oldest_queued_at"] if oldest else None,
        "raw_payload_included": False,
        "provider_called": False,
    }


def dispatcher_health() -> dict[str, Any]:
    """Read only the dispatcher-owned pending queue surface."""
    if not database_role_matches("noteai_ai_dispatcher"):
        return {
            "ok": False,
            "reason": "database_role_mismatch",
            "provider_called": False,
            "database_write": False,
        }
    try:
        row = db.fetchone(
            "SELECT COUNT(*) AS pending_outbox,"
            "COALESCE(SUM(CASE WHEN attempt_count>=? THEN 1 ELSE 0 END),0) "
            "AS exhausted_outbox "
            "FROM ai_operation_outbox WHERE state='pending'",
            (OUTBOX_MAX_ATTEMPTS,),
        )
        data = dict(row) if row else {}
        exhausted = int(data.get("exhausted_outbox") or 0)
        return {
            "ok": exhausted == 0,
            "reason": "ready" if exhausted == 0 else "manual_attention_required",
            "pending_outbox": int(data.get("pending_outbox") or 0),
            "exhausted_outbox": exhausted,
            "provider_called": False,
            "database_write": False,
        }
    except Exception:
        return {
            "ok": False,
            "reason": "durable_ai_schema_unavailable",
            "provider_called": False,
            "database_write": False,
        }


def worker_health() -> dict[str, Any]:
    """Read only worker-visible delivered, payload and settlement surfaces."""
    if not database_role_matches("noteai_ai_worker"):
        return {
            "ok": False,
            "reason": "database_role_mismatch",
            "provider_called": False,
            "database_write": False,
        }
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        row = db.fetchone(
            "SELECT "
            "(SELECT COUNT(*) FROM ai_operation_settlements "
            " WHERE billing_state='needs_manual') AS needs_manual,"
            "(SELECT COUNT(*) FROM ai_payload_refs "
            " WHERE state='ready' AND expires_at<=?) AS expired_ready,"
            "(SELECT COUNT(*) FROM ai_operations o "
            " JOIN ai_operation_settlements s ON s.operation_id=o.id "
            " WHERE o.status='running' AND o.provider_phase<>'not_started' "
            " AND o.lease_expires_at IS NOT NULL AND o.lease_expires_at<=? "
            " AND s.billing_state='charged') AS stale_provider_outcome,"
            "(SELECT COUNT(*) FROM ai_operations o "
            " JOIN ai_operation_settlements s ON s.operation_id=o.id "
            " JOIN ai_operation_outbox b ON b.operation_id=o.id "
            " WHERE o.status='running' AND o.provider_phase='not_started' "
            " AND o.lease_expires_at IS NOT NULL AND o.lease_expires_at<=? "
            " AND s.billing_state='charged' AND b.state='delivered') "
            "AS recoverable_unstarted",
            (now_iso, now_iso, now_iso),
        )
        data = dict(row) if row else {}
        blocking = (
            int(data.get("needs_manual") or 0)
            + int(data.get("expired_ready") or 0)
            + int(data.get("stale_provider_outcome") or 0)
        )
        return {
            "ok": blocking == 0,
            "reason": "ready" if blocking == 0 else "manual_attention_required",
            "needs_manual": int(data.get("needs_manual") or 0),
            "expired_ready": int(data.get("expired_ready") or 0),
            "stale_provider_outcome": int(
                data.get("stale_provider_outcome") or 0
            ),
            "recoverable_unstarted": int(
                data.get("recoverable_unstarted") or 0
            ),
            "provider_called": False,
            "database_write": False,
        }
    except Exception:
        return {
            "ok": False,
            "reason": "durable_ai_schema_unavailable",
            "provider_called": False,
            "database_write": False,
        }


def database_role_matches(expected_role: str) -> bool:
    """Fail closed unless PostgreSQL reports the exact dedicated login role."""
    if expected_role not in {"noteai_ai_dispatcher", "noteai_ai_worker"}:
        return False
    if not db.using_postgres():
        return False
    try:
        row = db.fetchone(
            "SELECT session_user AS session_role,current_user AS database_role"
        )
    except Exception:
        return False
    return bool(
        row
        and str(row["session_role"]) == expected_role
        and str(row["database_role"]) == expected_role
    )


def health() -> dict[str, Any]:
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        row = db.fetchone(
            "SELECT "
            "(SELECT COUNT(*) FROM ai_operation_settlements "
            " WHERE billing_state='needs_manual') AS needs_manual,"
            "(SELECT COUNT(*) FROM ai_operation_outbox "
            " WHERE state='pending' AND attempt_count>=?) AS exhausted_outbox,"
            "(SELECT COUNT(*) FROM ai_payload_refs "
            " WHERE state='ready' AND expires_at<=?) AS expired_ready,"
            "(SELECT COUNT(*) FROM ai_operations o "
            " JOIN ai_operation_settlements s ON s.operation_id=o.id "
            " WHERE o.status='running' AND o.provider_phase<>'not_started' "
            " AND o.lease_expires_at IS NOT NULL AND o.lease_expires_at<=? "
            " AND s.billing_state='charged') AS stale_provider_outcome,"
            "(SELECT COUNT(*) FROM ai_operations o "
            " JOIN ai_operation_settlements s ON s.operation_id=o.id "
            " JOIN ai_operation_outbox b ON b.operation_id=o.id "
            " WHERE o.status='running' AND o.provider_phase='not_started' "
            " AND o.lease_expires_at IS NOT NULL AND o.lease_expires_at<=? "
            " AND s.billing_state='charged' AND b.state='delivered') "
            "AS recoverable_unstarted",
            (
                OUTBOX_MAX_ATTEMPTS,
                now_iso,
                now_iso,
                now_iso,
            ),
        )
        data = dict(row) if row else {}
        ready = not any(int(data.get(key) or 0) for key in data)
        return {
            "ok": ready,
            "reason": "ready" if ready else "manual_attention_required",
            "needs_manual": int(data.get("needs_manual") or 0),
            "exhausted_outbox": int(data.get("exhausted_outbox") or 0),
            "expired_ready": int(data.get("expired_ready") or 0),
            "stale_provider_outcome": int(
                data.get("stale_provider_outcome") or 0
            ),
            "recoverable_unstarted": int(
                data.get("recoverable_unstarted") or 0
            ),
            "provider_called": False,
            "database_write": False,
        }
    except Exception:
        return {
            "ok": False,
            "reason": "durable_ai_schema_unavailable",
            "provider_called": False,
            "database_write": False,
        }
