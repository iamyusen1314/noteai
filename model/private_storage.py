"""Owner-bound private object storage and recovery-safe media lifecycle.

The relational database stores only opaque identifiers, digests, bounded
counters, fixed states and UTC clocks. Object keys and user content stay in a
private backend. No backend is selected unless an explicit configuration is
provided; production callers therefore fail closed by default.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import threading
import uuid
import zipfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import db
import durable_ai
import idempotency


MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_VIDEO_BUNDLE_BYTES = 64 * 1024 * 1024
MAX_VIDEO_FRAMES = 100
MAX_FRAME_BYTES = 2 * 1024 * 1024
MEDIA_TTL_SECONDS = 24 * 60 * 60
MAX_OBJECT_LIST_LIMIT = 1000
ORPHAN_MIN_AGE_SECONDS = 24 * 60 * 60

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_OBJECT_KEY_RE = re.compile(
    r"^v1/(payload|media)/(request|result|image|video_frames)/"
    r"[0-9a-f]{12}/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}\.(json|bin|zip)$"
)
_PURPOSES = frozenset({"image", "video_frames"})
_CONTENT_TYPES = {
    "image": frozenset({"image/jpeg", "image/png", "image/webp"}),
    "video_frames": frozenset({"application/vnd.noteai.video-frames+zip"}),
}


class PrivateStorageError(RuntimeError):
    def __init__(self, code: str, message: str = "Private storage unavailable"):
        super().__init__(message)
        self.code = str(code)


class ObjectStorageUnavailable(PrivateStorageError):
    def __init__(self, code: str = "PRIVATE_STORAGE_UNAVAILABLE"):
        super().__init__(code)


class MediaReferenceUnavailable(PrivateStorageError):
    def __init__(self, code: str = "PRIVATE_MEDIA_NOT_FOUND"):
        super().__init__(code, "Private media reference unavailable")


@dataclass(frozen=True)
class StoredObject:
    key: str = field(repr=False)
    size_bytes: int
    content_sha256: str
    created_at: str
    metadata: dict[str, str] = field(repr=False)


class ObjectBackend(ABC):
    @abstractmethod
    def put_if_absent(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str,
        metadata: dict[str, str],
    ) -> bool:
        """Write once and return True; return False when the key exists."""

    @abstractmethod
    def get(self, key: str, *, max_bytes: int) -> tuple[bytes, dict[str, str]]:
        raise NotImplementedError

    @abstractmethod
    def head(self, key: str) -> StoredObject | None:
        raise NotImplementedError

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Idempotently delete a key and return True on a known final state."""

    @abstractmethod
    def list(
        self,
        prefix: str,
        *,
        limit: int,
        cursor: str | None = None,
    ) -> tuple[list[StoredObject], str | None]:
        raise NotImplementedError


class UnavailableObjectBackend(ObjectBackend):
    def put_if_absent(self, *_args, **_kwargs) -> bool:
        raise ObjectStorageUnavailable()

    def get(self, *_args, **_kwargs) -> tuple[bytes, dict[str, str]]:
        raise ObjectStorageUnavailable()

    def head(self, *_args, **_kwargs) -> StoredObject | None:
        raise ObjectStorageUnavailable()

    def delete(self, *_args, **_kwargs) -> bool:
        raise ObjectStorageUnavailable()

    def list(self, *_args, **_kwargs) -> tuple[list[StoredObject], str | None]:
        raise ObjectStorageUnavailable()


class InMemoryObjectBackend(ObjectBackend):
    """Process-safe test adapter; never selected from environment."""

    def __init__(self):
        self._objects: dict[str, tuple[bytes, dict[str, str], str]] = {}
        self._lock = threading.Lock()

    def put_if_absent(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str,
        metadata: dict[str, str],
    ) -> bool:
        normalized = _object_key(key)
        payload = bytes(body)
        created_at = _canonical_clock(metadata.get("created_at"))
        values = _canonical_metadata(metadata)
        values["content_type"] = _content_type_value(content_type)
        with self._lock:
            if normalized in self._objects:
                return False
            self._objects[normalized] = (payload, values, created_at)
        return True

    def get(self, key: str, *, max_bytes: int) -> tuple[bytes, dict[str, str]]:
        normalized = _object_key(key)
        maximum = _bounded_int(max_bytes, "max_bytes", 1, durable_ai.MAX_OBJECT_BYTES)
        with self._lock:
            item = self._objects.get(normalized)
            if item is None:
                raise ObjectStorageUnavailable("PRIVATE_OBJECT_NOT_FOUND")
            body, metadata, _created_at = item
            if len(body) > maximum:
                raise ObjectStorageUnavailable("PRIVATE_OBJECT_TOO_LARGE")
            return bytes(body), dict(metadata)

    def head(self, key: str) -> StoredObject | None:
        normalized = _object_key(key)
        with self._lock:
            item = self._objects.get(normalized)
            if item is None:
                return None
            body, metadata, created_at = item
            return StoredObject(
                key=normalized,
                size_bytes=len(body),
                content_sha256=hashlib.sha256(body).hexdigest(),
                created_at=created_at,
                metadata=dict(metadata),
            )

    def delete(self, key: str) -> bool:
        normalized = _object_key(key)
        with self._lock:
            self._objects.pop(normalized, None)
        return True

    def list(
        self,
        prefix: str,
        *,
        limit: int,
        cursor: str | None = None,
    ) -> tuple[list[StoredObject], str | None]:
        bounded = _bounded_int(limit, "limit", 1, MAX_OBJECT_LIST_LIMIT)
        normalized_prefix = _object_prefix(prefix)
        with self._lock:
            keys = sorted(
                key
                for key in self._objects
                if key.startswith(normalized_prefix)
                and (cursor is None or key > cursor)
            )
        selected = keys[:bounded]
        items = [self.head(key) for key in selected]
        next_cursor = selected[-1] if len(keys) > bounded else None
        return [item for item in items if item is not None], next_cursor


class LocalDirectoryObjectBackend(ObjectBackend):
    """Isolated restart/cross-process proof adapter, prohibited in production."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            self.root.chmod(0o700)
        except OSError:
            pass

    def _paths(self, key: str) -> tuple[Path, Path]:
        normalized = _object_key(key)
        body = (self.root / normalized).resolve()
        if self.root not in body.parents:
            raise ValueError("object key escapes storage root")
        return body, body.with_name(body.name + ".meta.json")

    @staticmethod
    def _exclusive_write(path: Path, body: bytes) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            try:
                path.unlink()
            except OSError:
                pass
            raise

    def put_if_absent(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str,
        metadata: dict[str, str],
    ) -> bool:
        payload_path, meta_path = self._paths(key)
        payload_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        values = _canonical_metadata(metadata)
        values["content_type"] = _content_type_value(content_type)
        encoded = json.dumps(
            values,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            self._exclusive_write(payload_path, bytes(body))
        except FileExistsError:
            return False
        try:
            self._exclusive_write(meta_path, encoded)
        except BaseException:
            try:
                payload_path.unlink()
            except OSError:
                pass
            raise
        return True

    def get(self, key: str, *, max_bytes: int) -> tuple[bytes, dict[str, str]]:
        payload_path, meta_path = self._paths(key)
        maximum = _bounded_int(max_bytes, "max_bytes", 1, durable_ai.MAX_OBJECT_BYTES)
        try:
            if payload_path.stat().st_size > maximum:
                raise ObjectStorageUnavailable("PRIVATE_OBJECT_TOO_LARGE")
            body = payload_path.read_bytes()
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ObjectStorageUnavailable("PRIVATE_OBJECT_NOT_FOUND") from exc
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ObjectStorageUnavailable("PRIVATE_OBJECT_READ_FAILED") from exc
        if len(body) > maximum:
            raise ObjectStorageUnavailable("PRIVATE_OBJECT_TOO_LARGE")
        return body, _canonical_metadata(metadata)

    def head(self, key: str) -> StoredObject | None:
        payload_path, _meta_path = self._paths(key)
        try:
            body, metadata = self.get(key, max_bytes=durable_ai.MAX_OBJECT_BYTES)
            created_at = _canonical_clock(metadata.get("created_at"))
        except ObjectStorageUnavailable as exc:
            if exc.code == "PRIVATE_OBJECT_NOT_FOUND":
                return None
            raise
        return StoredObject(
            key=_object_key(key),
            size_bytes=payload_path.stat().st_size,
            content_sha256=hashlib.sha256(body).hexdigest(),
            created_at=created_at,
            metadata=metadata,
        )

    def delete(self, key: str) -> bool:
        payload_path, meta_path = self._paths(key)
        for path in (meta_path, payload_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise ObjectStorageUnavailable("PRIVATE_OBJECT_DELETE_FAILED") from exc
        return True

    def list(
        self,
        prefix: str,
        *,
        limit: int,
        cursor: str | None = None,
    ) -> tuple[list[StoredObject], str | None]:
        bounded = _bounded_int(limit, "limit", 1, MAX_OBJECT_LIST_LIMIT)
        normalized_prefix = _object_prefix(prefix)
        keys: list[str] = []
        for meta_path in self.root.rglob("*.meta.json"):
            relative = meta_path.relative_to(self.root).as_posix()
            key = relative[: -len(".meta.json")]
            if (
                key.startswith(normalized_prefix)
                and _OBJECT_KEY_RE.fullmatch(key)
                and (cursor is None or key > cursor)
            ):
                keys.append(key)
        keys.sort()
        selected = keys[:bounded]
        items = [self.head(key) for key in selected]
        next_cursor = selected[-1] if len(keys) > bounded else None
        return [item for item in items if item is not None], next_cursor


class AliyunOssObjectBackend(ObjectBackend):
    """Private OSS adapter using conditional writes and server-side encryption."""

    def __init__(
        self,
        *,
        client: Any,
        bucket: str,
        key_prefix: str = "noteai-private",
        kms_key_id: str | None = None,
    ):
        self.client = client
        self.bucket = _bucket(bucket)
        self.key_prefix = str(key_prefix or "").strip().strip("/")
        if not re.fullmatch(r"[a-z0-9][a-z0-9/_-]{0,62}", self.key_prefix):
            raise ValueError("invalid OSS key prefix")
        self.kms_key_id = str(kms_key_id or "").strip() or None

    def _remote_key(self, key: str) -> str:
        return f"{self.key_prefix}/{_object_key(key)}"

    @staticmethod
    def _status(exc: BaseException) -> int | None:
        for name in ("status_code", "status", "http_status"):
            value = getattr(exc, name, None)
            try:
                if value is not None:
                    return int(value)
            except (TypeError, ValueError):
                continue
        return None

    def put_if_absent(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str,
        metadata: dict[str, str],
    ) -> bool:
        try:
            import alibabacloud_oss_v2 as oss

            request = oss.PutObjectRequest(
                bucket=self.bucket,
                key=self._remote_key(key),
                body=bytes(body),
                content_type=_content_type_value(content_type),
                metadata=_canonical_metadata(metadata),
                forbid_overwrite=True,
                server_side_encryption="KMS" if self.kms_key_id else "AES256",
                server_side_encryption_key_id=self.kms_key_id,
            )
            self.client.put_object(request)
            return True
        except BaseException as exc:
            if self._status(exc) in {409, 412}:
                return False
            raise ObjectStorageUnavailable("PRIVATE_OBJECT_WRITE_FAILED") from exc

    def get(self, key: str, *, max_bytes: int) -> tuple[bytes, dict[str, str]]:
        maximum = _bounded_int(max_bytes, "max_bytes", 1, durable_ai.MAX_OBJECT_BYTES)
        try:
            import alibabacloud_oss_v2 as oss

            result = self.client.get_object(
                oss.GetObjectRequest(bucket=self.bucket, key=self._remote_key(key))
            )
            declared = int(getattr(result, "content_length", 0) or 0)
            if declared < 1 or declared > maximum:
                raise ObjectStorageUnavailable("PRIVATE_OBJECT_TOO_LARGE")
            stream = result.body
            chunks: list[bytes] = []
            size = 0
            try:
                if hasattr(stream, "iter_bytes"):
                    for chunk in stream.iter_bytes(block_size=1024 * 1024):
                        value = bytes(chunk)
                        size += len(value)
                        if size > maximum:
                            raise ObjectStorageUnavailable(
                                "PRIVATE_OBJECT_TOO_LARGE"
                            )
                        chunks.append(value)
                    body = b"".join(chunks)
                else:
                    body = stream.read(maximum + 1)
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()
            if len(body) > maximum:
                raise ObjectStorageUnavailable("PRIVATE_OBJECT_TOO_LARGE")
            if len(body) != declared:
                raise ObjectStorageUnavailable("PRIVATE_OBJECT_SIZE_MISMATCH")
            return bytes(body), _canonical_metadata(
                dict(getattr(result, "metadata", None) or {})
            )
        except ObjectStorageUnavailable:
            raise
        except BaseException as exc:
            code = (
                "PRIVATE_OBJECT_NOT_FOUND"
                if self._status(exc) == 404
                else "PRIVATE_OBJECT_READ_FAILED"
            )
            raise ObjectStorageUnavailable(code) from exc

    def head(self, key: str) -> StoredObject | None:
        try:
            import alibabacloud_oss_v2 as oss

            result = self.client.head_object(
                oss.HeadObjectRequest(bucket=self.bucket, key=self._remote_key(key))
            )
        except BaseException as exc:
            if self._status(exc) == 404:
                return None
            raise ObjectStorageUnavailable("PRIVATE_OBJECT_HEAD_FAILED") from exc
        metadata = _canonical_metadata(dict(getattr(result, "metadata", None) or {}))
        return StoredObject(
            key=_object_key(key),
            size_bytes=int(getattr(result, "content_length", 0) or 0),
            content_sha256=_digest(
                metadata.get("content_sha256"),
                "content_sha256",
            ),
            created_at=_canonical_clock(metadata.get("created_at")),
            metadata=metadata,
        )

    def delete(self, key: str) -> bool:
        try:
            import alibabacloud_oss_v2 as oss

            self.client.delete_object(
                oss.DeleteObjectRequest(bucket=self.bucket, key=self._remote_key(key))
            )
            return True
        except BaseException as exc:
            if self._status(exc) == 404:
                return True
            raise ObjectStorageUnavailable("PRIVATE_OBJECT_DELETE_FAILED") from exc

    def list(
        self,
        prefix: str,
        *,
        limit: int,
        cursor: str | None = None,
    ) -> tuple[list[StoredObject], str | None]:
        bounded = _bounded_int(limit, "limit", 1, MAX_OBJECT_LIST_LIMIT)
        logical_prefix = _object_prefix(prefix)
        try:
            import alibabacloud_oss_v2 as oss

            result = self.client.list_objects_v2(
                oss.ListObjectsV2Request(
                    bucket=self.bucket,
                    prefix=f"{self.key_prefix}/{logical_prefix}",
                    max_keys=bounded,
                    continuation_token=cursor,
                )
            )
            items: list[StoredObject] = []
            for value in list(getattr(result, "contents", None) or []):
                remote = str(getattr(value, "key", "") or "")
                logical = remote.removeprefix(f"{self.key_prefix}/")
                if not _OBJECT_KEY_RE.fullmatch(logical):
                    continue
                head = self.head(logical)
                if head is not None:
                    items.append(head)
            next_cursor = (
                str(getattr(result, "next_continuation_token", "") or "") or None
            )
            return items, next_cursor
        except ObjectStorageUnavailable:
            raise
        except BaseException as exc:
            raise ObjectStorageUnavailable("PRIVATE_OBJECT_LIST_FAILED") from exc


@dataclass(frozen=True)
class MediaReference:
    id: str
    subject_hash: str
    purpose: str
    content_type: str
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
            self.subject_hash,
            self.purpose,
            self.content_type,
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


_object_backend: ObjectBackend = UnavailableObjectBackend()
_key_epoch = ""


def configure_object_backend(backend: ObjectBackend, *, key_epoch: str) -> None:
    if not isinstance(backend, ObjectBackend):
        raise TypeError("backend must implement ObjectBackend")
    epoch = str(key_epoch or "").strip()
    if not epoch or len(epoch) > 256:
        raise ValueError("private storage key epoch is required")
    global _object_backend, _key_epoch
    _object_backend = backend
    _key_epoch = epoch


def reset_object_backend() -> None:
    global _object_backend, _key_epoch
    _object_backend = UnavailableObjectBackend()
    _key_epoch = ""


def get_object_backend() -> ObjectBackend:
    if isinstance(_object_backend, UnavailableObjectBackend):
        raise ObjectStorageUnavailable()
    return _object_backend


def object_backend_configured() -> bool:
    return not isinstance(_object_backend, UnavailableObjectBackend)


def _key_epoch_value() -> str:
    if not _key_epoch:
        raise ObjectStorageUnavailable()
    return _key_epoch


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return current.astimezone(timezone.utc)


def _canonical_clock(value: Any) -> str:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid object clock") from exc
    if parsed.tzinfo is None:
        raise ValueError("object clock must include timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _bounded_int(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if normalized != value or not minimum <= normalized <= maximum:
        raise ValueError(f"{label} is outside the allowed range")
    return normalized


def _digest(value: Any, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return normalized


def _object_key(value: str) -> str:
    normalized = str(value or "").strip()
    if not _OBJECT_KEY_RE.fullmatch(normalized):
        raise ValueError("invalid private object key")
    return normalized


def _object_prefix(value: str) -> str:
    normalized = str(value or "").strip().strip("/")
    if normalized not in {
        "v1",
        "v1/payload",
        "v1/media",
        "v1/payload/request",
        "v1/payload/result",
        "v1/media/image",
        "v1/media/video_frames",
    }:
        raise ValueError("invalid private object prefix")
    return normalized + "/"


def _bucket(value: str) -> str:
    normalized = str(value or "").strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", normalized):
        raise ValueError("invalid private OSS bucket")
    return normalized


def _content_type_value(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in set().union(*_CONTENT_TYPES.values()) | {
        "application/json"
    }:
        raise ValueError("invalid private object content type")
    return normalized


def _canonical_metadata(values: dict[str, Any]) -> dict[str, str]:
    if not isinstance(values, dict) or len(values) > 24:
        raise ValueError("invalid private object metadata")
    result: dict[str, str] = {}
    for raw_key, raw_value in values.items():
        key = str(raw_key or "").strip().lower().replace("-", "_")
        value = str(raw_value or "").strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", key):
            raise ValueError("invalid private object metadata key")
        if not value or len(value.encode("utf-8")) > 512:
            raise ValueError("invalid private object metadata value")
        result[key] = value
    return result


def _media_key(reference_id: str, subject_hash: str, purpose: str) -> str:
    suffix = "zip" if purpose == "video_frames" else "bin"
    return _object_key(
        f"v1/media/{purpose}/{subject_hash[:12]}/{reference_id}.{suffix}"
    )


def _payload_key(
    reference_id: str,
    subject_hash: str,
    purpose: str,
) -> str:
    return _object_key(
        f"v1/payload/{purpose}/{subject_hash[:12]}/{reference_id}.json"
    )


def _object_metadata(
    *,
    reference_id: str,
    subject_hash: str,
    purpose: str,
    content_sha256: str,
    size_bytes: int,
    item_count: int,
    expires_at: str,
    created_at: str,
    key_epoch_hash: str,
    schema_version: int = 1,
) -> dict[str, str]:
    return {
        "reference_id": str(uuid.UUID(reference_id)),
        "subject_hash": _digest(subject_hash, "subject_hash"),
        "purpose": str(purpose),
        "content_sha256": _digest(content_sha256, "content_sha256"),
        "size_bytes": str(_bounded_int(size_bytes, "size_bytes", 1, durable_ai.MAX_OBJECT_BYTES)),
        "item_count": str(_bounded_int(item_count, "item_count", 0, 1000)),
        "schema_version": str(_bounded_int(schema_version, "schema_version", 1, 16)),
        "encryption_mode": "provider_managed",
        "key_epoch_hash": _digest(key_epoch_hash, "key_epoch_hash"),
        "expires_at": _canonical_clock(expires_at),
        "created_at": _canonical_clock(created_at),
    }


def _verify_object(
    *,
    body: bytes,
    metadata: dict[str, str],
    reference_id: str,
    subject_hash: str,
    purpose: str,
    content_sha256: str,
    size_bytes: int,
    item_count: int,
    expires_at: str,
    key_epoch_hash: str,
) -> None:
    expected = _object_metadata(
        reference_id=reference_id,
        subject_hash=subject_hash,
        purpose=purpose,
        content_sha256=content_sha256,
        size_bytes=size_bytes,
        item_count=item_count,
        expires_at=expires_at,
        created_at=metadata.get("created_at"),
        key_epoch_hash=key_epoch_hash,
    )
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise ObjectStorageUnavailable("PRIVATE_OBJECT_METADATA_MISMATCH")
    if len(body) != size_bytes:
        raise ObjectStorageUnavailable("PRIVATE_OBJECT_SIZE_MISMATCH")
    if hashlib.sha256(body).hexdigest() != content_sha256:
        raise ObjectStorageUnavailable("PRIVATE_OBJECT_HASH_MISMATCH")


def validate_stored_object_descriptor(item: StoredObject) -> None:
    """Validate a listed/head object without reading or exposing its content."""
    key = _object_key(item.key)
    metadata = _canonical_metadata(item.metadata)
    try:
        reference_id = str(uuid.UUID(metadata["reference_id"]))
        subject_hash = _digest(metadata["subject_hash"], "subject_hash")
        purpose = str(metadata["purpose"])
        content_sha = _digest(metadata["content_sha256"], "content_sha256")
        key_epoch_hash = _digest(
            metadata["key_epoch_hash"],
            "key_epoch_hash",
        )
        size_bytes = _bounded_int(
            int(metadata["size_bytes"]),
            "size_bytes",
            1,
            durable_ai.MAX_OBJECT_BYTES,
        )
        _bounded_int(
            int(metadata["item_count"]),
            "item_count",
            0,
            1000,
        )
        _bounded_int(
            int(metadata["schema_version"]),
            "schema_version",
            1,
            16,
        )
        created_at = datetime.fromisoformat(_canonical_clock(metadata["created_at"]))
        expires_at = datetime.fromisoformat(_canonical_clock(metadata["expires_at"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ObjectStorageUnavailable("PRIVATE_OBJECT_METADATA_MISMATCH") from exc
    try:
        expected_key = (
            _payload_key(reference_id, subject_hash, purpose)
            if key.startswith("v1/payload/")
            else _media_key(reference_id, subject_hash, purpose)
        )
    except ValueError as exc:
        raise ObjectStorageUnavailable("PRIVATE_OBJECT_METADATA_MISMATCH") from exc
    if (
        key != expected_key
        or size_bytes != int(item.size_bytes)
        or content_sha != _digest(item.content_sha256, "content_sha256")
        or metadata.get("encryption_mode") != "provider_managed"
        or not key_epoch_hash
        or created_at >= expires_at
    ):
        raise ObjectStorageUnavailable("PRIVATE_OBJECT_METADATA_MISMATCH")


class PrivateObjectPayloadStore(durable_ai.PayloadStore):
    """Durable AI request/result store backed by the shared private backend."""

    def __init__(self, backend: ObjectBackend | None = None, *, key_epoch: str | None = None):
        self.backend = backend
        self.key_epoch = key_epoch

    def _backend(self) -> ObjectBackend:
        return self.backend or get_object_backend()

    def _epoch(self) -> str:
        return str(self.key_epoch or _key_epoch_value())

    def put(
        self,
        *,
        operation_id: str,
        user_id: str,
        purpose: str | durable_ai.RefPurpose,
        payload: bytes,
        item_count: int,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> durable_ai.PayloadReference:
        op_id = str(uuid.UUID(str(operation_id)))
        purpose_value = (
            purpose.value if isinstance(purpose, durable_ai.RefPurpose) else str(purpose)
        )
        if purpose_value not in {"request", "result"}:
            raise ValueError("invalid payload purpose")
        body = bytes(payload)
        if not body or len(body) > durable_ai.MAX_OBJECT_BYTES:
            raise ValueError("payload size is outside the durable object limit")
        count = _bounded_int(item_count, "item_count", 0, 1000)
        ttl = _bounded_int(ttl_seconds, "ttl_seconds", 60, 90 * 24 * 60 * 60)
        subject_hash = idempotency.operation_subject_hash(str(user_id or ""))
        reference_id = durable_ai.payload_reference_id_for(op_id, purpose_value)
        current = _utc(now)
        created_at = current.isoformat()
        expires_at = (current + timedelta(seconds=ttl)).isoformat()
        content_sha = hashlib.sha256(body).hexdigest()
        epoch_hash = hashlib.sha256(self._epoch().encode("utf-8")).hexdigest()
        key = _payload_key(reference_id, subject_hash, purpose_value)
        metadata = _object_metadata(
            reference_id=reference_id,
            subject_hash=subject_hash,
            purpose=purpose_value,
            content_sha256=content_sha,
            size_bytes=len(body),
            item_count=count,
            expires_at=expires_at,
            created_at=created_at,
            key_epoch_hash=epoch_hash,
        )
        try:
            created = self._backend().put_if_absent(
                key,
                body,
                content_type="application/json",
                metadata=metadata,
            )
            if not created:
                existing_body, existing_metadata = self._backend().get(
                    key,
                    max_bytes=durable_ai.MAX_OBJECT_BYTES,
                )
                existing_expires_at = _canonical_clock(
                    existing_metadata.get("expires_at")
                )
                existing_created_at = _canonical_clock(
                    existing_metadata.get("created_at")
                )
                existing_epoch_hash = _digest(
                    existing_metadata.get("key_epoch_hash"),
                    "key_epoch_hash",
                )
                _verify_object(
                    body=existing_body,
                    metadata=existing_metadata,
                    reference_id=reference_id,
                    subject_hash=subject_hash,
                    purpose=purpose_value,
                    content_sha256=content_sha,
                    size_bytes=len(body),
                    item_count=count,
                    expires_at=existing_expires_at,
                    key_epoch_hash=existing_epoch_hash,
                )
                if existing_body != body:
                    raise durable_ai.DurableAiError(
                        "DURABLE_AI_REFERENCE_CONFLICT",
                        "Opaque payload reference conflicts with existing content",
                        http_status=409,
                    )
                if datetime.fromisoformat(existing_expires_at) <= current:
                    raise durable_ai.PayloadUnavailable(
                        "DURABLE_AI_PAYLOAD_NOT_FOUND"
                    )
                created_at = existing_created_at
                expires_at = existing_expires_at
                epoch_hash = existing_epoch_hash
        except durable_ai.DurableAiError:
            raise
        except PrivateStorageError as exc:
            raise durable_ai.PayloadUnavailable(exc.code) from exc
        return durable_ai.PayloadReference(
            id=reference_id,
            operation_id=op_id,
            subject_hash=subject_hash,
            purpose=purpose_value,
            object_key_hash=hashlib.sha256(key.encode("utf-8")).hexdigest(),
            content_sha256=content_sha,
            size_bytes=len(body),
            item_count=count,
            schema_version=1,
            encryption_mode="provider_managed",
            key_epoch_hash=epoch_hash,
            state="ready",
            expires_at=expires_at,
            created_at=created_at,
            ready_at=created_at,
            created=created,
        )

    def get(
        self,
        reference: durable_ai.PayloadReference,
        *,
        user_id: str,
    ) -> bytes:
        subject_hash = idempotency.operation_subject_hash(str(user_id or ""))
        if (
            reference.subject_hash != subject_hash
            or reference.state != "ready"
            or _utc() >= datetime.fromisoformat(reference.expires_at)
        ):
            raise durable_ai.PayloadUnavailable("DURABLE_AI_PAYLOAD_NOT_FOUND")
        key = _payload_key(reference.id, subject_hash, reference.purpose)
        if hashlib.sha256(key.encode("utf-8")).hexdigest() != reference.object_key_hash:
            raise durable_ai.PayloadUnavailable("DURABLE_AI_PAYLOAD_NOT_FOUND")
        try:
            body, metadata = self._backend().get(
                key,
                max_bytes=durable_ai.MAX_OBJECT_BYTES,
            )
            _verify_object(
                body=body,
                metadata=metadata,
                reference_id=reference.id,
                subject_hash=subject_hash,
                purpose=reference.purpose,
                content_sha256=reference.content_sha256,
                size_bytes=reference.size_bytes,
                item_count=reference.item_count,
                expires_at=reference.expires_at,
                key_epoch_hash=reference.key_epoch_hash,
            )
            return body
        except PrivateStorageError as exc:
            raise durable_ai.PayloadUnavailable(exc.code) from exc

    def delete(
        self,
        reference: durable_ai.PayloadReference,
        *,
        user_id: str,
    ) -> bool:
        subject_hash = idempotency.operation_subject_hash(str(user_id or ""))
        if reference.subject_hash != subject_hash:
            raise durable_ai.PayloadUnavailable("DURABLE_AI_PAYLOAD_NOT_FOUND")
        key = _payload_key(reference.id, subject_hash, reference.purpose)
        if hashlib.sha256(key.encode("utf-8")).hexdigest() != reference.object_key_hash:
            raise durable_ai.PayloadUnavailable("DURABLE_AI_PAYLOAD_NOT_FOUND")
        try:
            return self._backend().delete(key)
        except PrivateStorageError as exc:
            raise durable_ai.PayloadUnavailable(exc.code) from exc


def _media_reference_from_row(row: Any) -> MediaReference:
    data = dict(row)
    return MediaReference(
        **{
            name: data.get(name)
            for name in MediaReference.__dataclass_fields__
            if name != "created"
        },
        created=False,
    )


def store_media_bytes(
    user_id: str,
    *,
    purpose: str,
    content_type: str,
    payload: bytes,
    item_count: int,
    ttl_seconds: int = MEDIA_TTL_SECONDS,
    now: datetime | None = None,
    backend: ObjectBackend | None = None,
) -> MediaReference:
    purpose_value = str(purpose or "")
    if purpose_value not in _PURPOSES:
        raise ValueError("invalid private media purpose")
    normalized_type = _content_type_value(content_type)
    if normalized_type not in _CONTENT_TYPES[purpose_value]:
        raise ValueError("media content type does not match purpose")
    body = bytes(payload)
    maximum = MAX_IMAGE_BYTES if purpose_value == "image" else MAX_VIDEO_BUNDLE_BYTES
    if not body or len(body) > maximum:
        raise ValueError("private media size is outside the allowed range")
    count = _bounded_int(
        item_count,
        "item_count",
        1,
        1 if purpose_value == "image" else MAX_VIDEO_FRAMES,
    )
    ttl = _bounded_int(ttl_seconds, "ttl_seconds", 60, 30 * 24 * 60 * 60)
    subject_hash = idempotency.operation_subject_hash(str(user_id or ""))
    current = _utc(now)
    created_at = current.isoformat()
    expires_at = (current + timedelta(seconds=ttl)).isoformat()
    reference_id = str(uuid.uuid4())
    content_sha = hashlib.sha256(body).hexdigest()
    epoch_hash = hashlib.sha256(_key_epoch_value().encode("utf-8")).hexdigest()
    key = _media_key(reference_id, subject_hash, purpose_value)
    metadata = _object_metadata(
        reference_id=reference_id,
        subject_hash=subject_hash,
        purpose=purpose_value,
        content_sha256=content_sha,
        size_bytes=len(body),
        item_count=count,
        expires_at=expires_at,
        created_at=created_at,
        key_epoch_hash=epoch_hash,
    )
    selected = backend or get_object_backend()
    created = selected.put_if_absent(
        key,
        body,
        content_type=normalized_type,
        metadata=metadata,
    )
    if not created:
        raise ObjectStorageUnavailable("PRIVATE_MEDIA_REFERENCE_CONFLICT")
    reference = MediaReference(
        id=reference_id,
        subject_hash=subject_hash,
        purpose=purpose_value,
        content_type=normalized_type,
        object_key_hash=hashlib.sha256(key.encode("utf-8")).hexdigest(),
        content_sha256=content_sha,
        size_bytes=len(body),
        item_count=count,
        schema_version=1,
        encryption_mode="provider_managed",
        key_epoch_hash=epoch_hash,
        state="ready",
        expires_at=expires_at,
        created_at=created_at,
        ready_at=created_at,
    )
    try:
        with db.transaction(write=True) as tx:
            import content_retention

            content_retention.assert_user_writable_with_storage(tx, user_id)
            tx.execute(
                "INSERT INTO private_media_refs("
                "id,subject_hash,purpose,content_type,object_key_hash,content_sha256,"
                "size_bytes,item_count,schema_version,encryption_mode,key_epoch_hash,"
                "state,expires_at,created_at,ready_at,deleted_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                reference.database_values(),
            )
    except BaseException:
        try:
            removed = selected.delete(key)
        except BaseException as cleanup_exc:
            raise ObjectStorageUnavailable(
                "PRIVATE_MEDIA_ORPHAN_CLEANUP_FAILED"
            ) from cleanup_exc
        if not removed:
            raise ObjectStorageUnavailable("PRIVATE_MEDIA_ORPHAN_CLEANUP_FAILED")
        raise
    return reference


def lock_ready_media_refs(
    tx: db.Transaction,
    user_id: str,
    reference_ids: Iterable[str],
    *,
    now: datetime | None = None,
) -> list[MediaReference]:
    identifiers = [str(uuid.UUID(str(value))) for value in reference_ids]
    if len(identifiers) != len(set(identifiers)) or len(identifiers) > durable_ai.MAX_MEDIA_REFS:
        raise MediaReferenceUnavailable("PRIVATE_MEDIA_REFERENCE_INVALID")
    if not identifiers:
        return []
    subject_hash = idempotency.operation_subject_hash(str(user_id or ""))
    current_iso = _utc(now).isoformat()
    lock = " FOR UPDATE" if tx.postgres else ""
    references: list[MediaReference] = []
    for reference_id in identifiers:
        row = tx.fetchone(
            "SELECT * FROM private_media_refs "
            f"WHERE id=? AND subject_hash=?{lock}",
            (reference_id, subject_hash),
        )
        if not row:
            raise MediaReferenceUnavailable()
        reference = _media_reference_from_row(row)
        if reference.state != "ready" or reference.expires_at <= current_iso:
            raise MediaReferenceUnavailable()
        references.append(reference)
    return references


def link_media_refs_in_transaction(
    tx: db.Transaction,
    operation_id: str,
    references: Iterable[MediaReference],
    *,
    now: datetime | None = None,
) -> None:
    current_iso = _utc(now).isoformat()
    for ordinal, reference in enumerate(references):
        tx.execute(
            "INSERT INTO ai_operation_media_refs("
            "operation_id,media_ref_id,ordinal,created_at) VALUES(?,?,?,?)",
            (str(uuid.UUID(operation_id)), reference.id, ordinal, current_iso),
        )


def media_refs_for_operation(operation_id: str) -> list[MediaReference]:
    rows = db.fetchall(
        "SELECT m.* FROM ai_operation_media_refs l "
        "JOIN private_media_refs m ON m.id=l.media_ref_id "
        "WHERE l.operation_id=? ORDER BY l.ordinal",
        (str(uuid.UUID(operation_id)),),
    )
    return [_media_reference_from_row(row) for row in rows]


def load_media_bytes(
    reference_id: str,
    *,
    user_id: str,
    purpose: str | None = None,
    backend: ObjectBackend | None = None,
    now: datetime | None = None,
) -> tuple[MediaReference, bytes]:
    subject_hash = idempotency.operation_subject_hash(str(user_id or ""))
    row = db.fetchone(
        "SELECT * FROM private_media_refs WHERE id=? AND subject_hash=?",
        (str(uuid.UUID(reference_id)), subject_hash),
    )
    if not row:
        raise MediaReferenceUnavailable()
    reference = _media_reference_from_row(row)
    if (
        reference.state != "ready"
        or _utc(now) >= datetime.fromisoformat(reference.expires_at)
        or (purpose is not None and reference.purpose != purpose)
    ):
        raise MediaReferenceUnavailable()
    key = _media_key(reference.id, subject_hash, reference.purpose)
    if hashlib.sha256(key.encode("utf-8")).hexdigest() != reference.object_key_hash:
        raise MediaReferenceUnavailable()
    selected = backend or get_object_backend()
    body, metadata = selected.get(
        key,
        max_bytes=MAX_IMAGE_BYTES
        if reference.purpose == "image"
        else MAX_VIDEO_BUNDLE_BYTES,
    )
    _verify_object(
        body=body,
        metadata=metadata,
        reference_id=reference.id,
        subject_hash=subject_hash,
        purpose=reference.purpose,
        content_sha256=reference.content_sha256,
        size_bytes=reference.size_bytes,
        item_count=reference.item_count,
        expires_at=reference.expires_at,
        key_epoch_hash=reference.key_epoch_hash,
    )
    return reference, body


def delete_user_media(
    user_id: str,
    *,
    backend: ObjectBackend | None = None,
    now: datetime | None = None,
) -> int:
    subject_hash = idempotency.operation_subject_hash(str(user_id or ""))
    rows = db.fetchall(
        "SELECT * FROM private_media_refs "
        "WHERE subject_hash=? AND state='ready' ORDER BY created_at,id",
        (subject_hash,),
    )
    if not rows:
        return 0
    selected = backend or get_object_backend()
    references = [_media_reference_from_row(row) for row in rows]
    for reference in references:
        key = _media_key(reference.id, subject_hash, reference.purpose)
        if hashlib.sha256(key.encode("utf-8")).hexdigest() != reference.object_key_hash:
            raise ObjectStorageUnavailable("PRIVATE_MEDIA_KEY_MISMATCH")
        if not selected.delete(key):
            raise ObjectStorageUnavailable("PRIVATE_MEDIA_DELETE_FAILED")
    current_iso = _utc(now).isoformat()
    with db.transaction(write=True) as tx:
        import content_retention

        content_retention.lock_user_write_fence_with_storage(
            tx,
            user_id,
            allow_deletion_requested=True,
        )
        for reference in references:
            tx.execute(
                "UPDATE private_media_refs SET state='deleted',deleted_at=? "
                "WHERE id=? AND subject_hash=? AND state='ready'",
                (current_iso, reference.id, subject_hash),
            )
    return len(references)


def has_ready_user_media(storage: Any, user_id: str) -> bool:
    subject_hash = idempotency.operation_subject_hash(str(user_id or ""))
    return bool(
        storage.fetchone(
            "SELECT 1 FROM private_media_refs "
            "WHERE subject_hash=? AND state='ready' LIMIT 1",
            (subject_hash,),
        )
    )


def expire_media(
    *,
    limit: int = 50,
    now: datetime | None = None,
    backend: ObjectBackend | None = None,
) -> int:
    bounded = _bounded_int(limit, "limit", 1, 100)
    current_iso = _utc(now).isoformat()
    rows = db.fetchall(
        "SELECT * FROM private_media_refs "
        "WHERE state='ready' AND expires_at<=? ORDER BY expires_at,id LIMIT ?",
        (current_iso, bounded),
    )
    selected = backend or get_object_backend()
    expired = 0
    for row in rows:
        reference = _media_reference_from_row(row)
        key = _media_key(reference.id, reference.subject_hash, reference.purpose)
        if hashlib.sha256(key.encode("utf-8")).hexdigest() != reference.object_key_hash:
            raise ObjectStorageUnavailable("PRIVATE_MEDIA_KEY_MISMATCH")
        if not selected.delete(key):
            raise ObjectStorageUnavailable("PRIVATE_MEDIA_DELETE_FAILED")
        with db.transaction(write=True) as tx:
            updated = tx.execute(
                "UPDATE private_media_refs SET state='expired',deleted_at=? "
                "WHERE id=? AND state='ready' AND expires_at<=?",
                (current_iso, reference.id, current_iso),
            )
            expired += int(getattr(updated, "rowcount", 0) or 0)
    return expired


def reconcile_orphans(
    *,
    prefix: str = "v1/media",
    limit: int = 100,
    minimum_age_seconds: int = ORPHAN_MIN_AGE_SECONDS,
    apply: bool = False,
    now: datetime | None = None,
    backend: ObjectBackend | None = None,
) -> dict[str, Any]:
    bounded = _bounded_int(limit, "limit", 1, MAX_OBJECT_LIST_LIMIT)
    minimum_age = _bounded_int(
        minimum_age_seconds,
        "minimum_age_seconds",
        ORPHAN_MIN_AGE_SECONDS,
        30 * 24 * 60 * 60,
    )
    current = _utc(now)
    selected = backend or get_object_backend()
    objects, cursor = selected.list(prefix, limit=bounded)
    scanned = 0
    orphan_count = 0
    deleted_count = 0
    survivor_digests: list[str] = []
    for item in objects:
        scanned += 1
        validate_stored_object_descriptor(item)
        try:
            reference_id = item.metadata["reference_id"]
            uuid.UUID(reference_id)
            created = datetime.fromisoformat(item.created_at)
        except (KeyError, TypeError, ValueError) as exc:
            raise ObjectStorageUnavailable("PRIVATE_OBJECT_METADATA_MISMATCH") from exc
        if current - created < timedelta(seconds=minimum_age):
            continue
        table = (
            "ai_payload_refs"
            if item.key.startswith("v1/payload/")
            else "private_media_refs"
        )
        exists = db.fetchone(
            f"SELECT 1 FROM {table} WHERE id=?",
            (reference_id,),
        )
        if exists:
            continue
        orphan_count += 1
        survivor_digests.append(hashlib.sha256(item.key.encode("utf-8")).hexdigest())
        if apply:
            if not selected.delete(item.key):
                raise ObjectStorageUnavailable("PRIVATE_OBJECT_DELETE_FAILED")
            deleted_count += 1
    return {
        "mode": "apply" if apply else "dry_run",
        "scanned_count": scanned,
        "orphan_count": orphan_count,
        "deleted_count": deleted_count,
        "orphan_key_hashes": sorted(survivor_digests),
        "truncated": cursor is not None,
        "content_included": False,
    }


def build_video_frame_bundle(
    frames: Iterable[bytes],
    *,
    duration_sec: float,
    raw_fps: float,
) -> bytes:
    values = [bytes(frame) for frame in frames]
    if not 1 <= len(values) <= MAX_VIDEO_FRAMES:
        raise ValueError("video frame count is outside the allowed range")
    if not 0 < float(duration_sec) <= 90:
        raise ValueError("video duration is outside the allowed range")
    if not 0 < float(raw_fps) <= 1000:
        raise ValueError("video FPS is outside the allowed range")
    entries: list[dict[str, Any]] = []
    for index, frame in enumerate(values):
        if not 4 <= len(frame) <= MAX_FRAME_BYTES:
            raise ValueError("video frame size is outside the allowed range")
        if not frame.startswith(b"\xff\xd8") or not frame.endswith(b"\xff\xd9"):
            raise ValueError("video frame is not canonical JPEG")
        entries.append(
            {
                "name": f"frames/{index:03d}.jpg",
                "sha256": hashlib.sha256(frame).hexdigest(),
                "size_bytes": len(frame),
            }
        )
    manifest = {
        "schema_version": 1,
        "purpose": "video_frames",
        "duration_millis": int(round(float(duration_sec) * 1000)),
        "raw_fps_millis": int(round(float(raw_fps) * 1000)),
        "frame_count": len(values),
        "frames": entries,
    }
    manifest_bytes = json.dumps(
        manifest,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer,
        mode="w",
        compression=zipfile.ZIP_STORED,
        strict_timestamps=True,
    ) as archive:
        for name, body in [
            ("manifest.json", manifest_bytes),
            *((entry["name"], values[index]) for index, entry in enumerate(entries)),
        ]:
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o600 << 16
            archive.writestr(info, body)
    result = buffer.getvalue()
    if len(result) > MAX_VIDEO_BUNDLE_BYTES:
        raise ValueError("video frame bundle exceeds the allowed size")
    return result


def read_video_frame_bundle(payload: bytes) -> dict[str, Any]:
    body = bytes(payload)
    if not body or len(body) > MAX_VIDEO_BUNDLE_BYTES:
        raise ObjectStorageUnavailable("PRIVATE_VIDEO_BUNDLE_INVALID")
    try:
        with zipfile.ZipFile(io.BytesIO(body), mode="r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if (
                not infos
                or names[0] != "manifest.json"
                or len(names) > MAX_VIDEO_FRAMES + 1
                or len(names) != len(set(names))
                or any(
                    info.is_dir()
                    or info.compress_type != zipfile.ZIP_STORED
                    or info.file_size > MAX_FRAME_BYTES
                    for info in infos[1:]
                )
            ):
                raise ValueError("invalid video frame bundle entries")
            manifest = json.loads(archive.read("manifest.json"))
            if (
                manifest.get("schema_version") != 1
                or manifest.get("purpose") != "video_frames"
                or int(manifest.get("frame_count") or 0) != len(infos) - 1
                or not 1 <= len(infos) - 1 <= MAX_VIDEO_FRAMES
            ):
                raise ValueError("invalid video frame manifest")
            frames: list[bytes] = []
            entries = manifest.get("frames")
            if not isinstance(entries, list) or len(entries) != len(infos) - 1:
                raise ValueError("invalid video frame manifest entries")
            for index, entry in enumerate(entries):
                expected_name = f"frames/{index:03d}.jpg"
                if entry.get("name") != expected_name or names[index + 1] != expected_name:
                    raise ValueError("noncanonical video frame ordering")
                frame = archive.read(expected_name)
                if (
                    len(frame) != int(entry.get("size_bytes") or -1)
                    or hashlib.sha256(frame).hexdigest() != entry.get("sha256")
                    or not frame.startswith(b"\xff\xd8")
                    or not frame.endswith(b"\xff\xd9")
                ):
                    raise ValueError("video frame integrity mismatch")
                frames.append(frame)
    except (ValueError, KeyError, TypeError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise ObjectStorageUnavailable("PRIVATE_VIDEO_BUNDLE_INVALID") from exc
    return {
        "frames": frames,
        "duration_sec": int(manifest["duration_millis"]) / 1000.0,
        "raw_fps": int(manifest["raw_fps_millis"]) / 1000.0,
    }


def configure_from_environment() -> bool:
    """Select OSS only from an explicit production-safe environment contract."""
    backend_name = os.environ.get("NOTEAI_PRIVATE_STORAGE_BACKEND", "").strip()
    if not backend_name:
        return False
    if backend_name != "aliyun_oss":
        raise RuntimeError("unsupported private storage backend")
    if any(
        os.environ.get(name)
        for name in (
            "ALIBABA_CLOUD_ACCESS_KEY_ID",
            "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
            "OSS_ACCESS_KEY_ID",
            "OSS_ACCESS_KEY_SECRET",
        )
    ):
        raise RuntimeError("static OSS credentials are prohibited")
    bucket = os.environ.get("NOTEAI_OSS_PRIVATE_BUCKET", "")
    region = os.environ.get("NOTEAI_OSS_REGION", "")
    endpoint = os.environ.get("NOTEAI_OSS_ENDPOINT", "")
    role_name = os.environ.get("NOTEAI_OSS_RAM_ROLE", "")
    epoch = os.environ.get("NOTEAI_PRIVATE_STORAGE_KEY_EPOCH", "")
    if not all(str(value or "").strip() for value in (bucket, region, endpoint, role_name, epoch)):
        raise RuntimeError("incomplete private OSS configuration")
    normalized_region = str(region).strip()
    expected_endpoint = (
        f"https://oss-{normalized_region}-internal.aliyuncs.com"
    )
    if (
        not re.fullmatch(r"cn-[a-z0-9-]{2,32}", normalized_region)
        or str(endpoint).strip() != expected_endpoint
    ):
        raise RuntimeError("private OSS endpoint must be the regional internal HTTPS endpoint")
    try:
        import alibabacloud_oss_v2 as oss
        from alibabacloud_credentials.client import Client as CredentialClient
        from alibabacloud_credentials.models import Config as CredentialConfig

        credential_client = CredentialClient(
            CredentialConfig(
                type="ecs_ram_role",
                role_name=role_name,
                enable_imds_v2=True,
                disable_imds_v1=True,
                metadata_token_duration=60,
            )
        )

        def credentials():
            value = credential_client.get_credential()
            return oss.credentials.Credentials(
                access_key_id=value.access_key_id,
                access_key_secret=value.access_key_secret,
                security_token=value.security_token,
            )

        provider = oss.credentials.CredentialsProviderFunc(credentials)
        config = oss.config.load_default()
        config.credentials_provider = provider
        config.region = region
        config.endpoint = endpoint
        config.use_internal_endpoint = True
        config.connect_timeout = 5
        config.readwrite_timeout = 30
        client = oss.Client(config)
    except BaseException as exc:
        raise RuntimeError("private OSS client initialization failed") from exc
    selected = AliyunOssObjectBackend(
        client=client,
        bucket=bucket,
        key_prefix=os.environ.get("NOTEAI_OSS_KEY_PREFIX", "noteai-private"),
        kms_key_id=os.environ.get("NOTEAI_OSS_KMS_KEY_ID") or None,
    )
    configure_object_backend(selected, key_epoch=epoch)
    durable_ai.configure_payload_store(
        PrivateObjectPayloadStore(selected, key_epoch=epoch)
    )
    return True
