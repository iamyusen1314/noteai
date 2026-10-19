"""Bounded, opaque image provenance for an owner's saved report.

A UUID is only a reference, never proof of ownership or a downloadable URL.
Callers must authorize the report before inspecting its sources. The existing
private-storage reader then verifies owner, purpose, TTL and stored bytes.
This module neither extends retention nor creates replacement images.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any


MAX_SOURCE_REFS = 9
MAX_REPORT_SOURCE_REFS = 10
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class CoverSourceValidationError(ValueError):
    """Invalid public source-reference input; never includes its raw value."""


def _source_ref(value: Any) -> str | None:
    if not isinstance(value, str) or not _UUID_RE.fullmatch(value):
        return None
    return str(uuid.UUID(value))


def normalize_source_refs(value: Any, *, maximum: int = MAX_SOURCE_REFS) -> list[str]:
    """Validate a new list, canonicalize UUIDs and preserve the first occurrence.

    The raw list is bounded before deduplication. URLs, data URIs, raw base64,
    arbitrary dictionaries and noncanonical UUID encodings are not sources.
    An empty list is valid and means a real upload is still required.
    """
    if type(maximum) is not int or not 1 <= maximum <= MAX_REPORT_SOURCE_REFS:
        raise CoverSourceValidationError("Invalid source reference limit")
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or len(value) > maximum:
        raise CoverSourceValidationError("Invalid cover source references")
    result = []
    for value_item in value:
        reference_id = _source_ref(value_item)
        if reference_id is None:
            raise CoverSourceValidationError("Invalid cover source references")
        if reference_id not in result:
            result.append(reference_id)
    return result


def source_items_from_inputs(
    *, cover_image: Any = None, cover_images: Any = None, extra_images: Any = None,
) -> list[dict]:
    """Preserve the exact input field/index of every recoverable original image.

    Legacy inline images are omitted without renumbering later observations.
    Repeated UUIDs retain each distinct original position. Generation's
    nonempty cover_images replaces the compatibility cover_image, matching the
    existing pipeline. A report may have one cover plus nine extra images.
    """
    if isinstance(cover_images, (list, tuple)) and cover_images:
        if len(cover_images) > MAX_SOURCE_REFS:
            raise CoverSourceValidationError("Too many report source references")
        candidates = [("cover_images", index, value)
                      for index, value in enumerate(cover_images, start=1)]
    else:
        candidates = [("cover_image", 1, cover_image)]
    if isinstance(extra_images, (list, tuple)):
        if len(extra_images) > MAX_SOURCE_REFS:
            raise CoverSourceValidationError("Too many report source references")
        candidates.extend(("extra_images", index, value)
                          for index, value in enumerate(extra_images, start=1))
    if len(candidates) > MAX_REPORT_SOURCE_REFS:
        raise CoverSourceValidationError("Too many report source references")
    result = []
    for input_field, image_index, candidate in candidates:
        reference_id = _source_ref(candidate)
        if reference_id is not None:
            result.append({"input_field": input_field, "image_index": image_index,
                           "media_ref": reference_id})
    return result


def source_refs_from_inputs(
    *, cover_image: Any = None, cover_images: Any = None, extra_images: Any = None,
) -> list[str]:
    """Extract and deduplicate the recoverable image candidates in input order.

    Use source_items_from_inputs alongside these references when preserving
    observation numbers. These identifiers alone do not authorize image use;
    inspect_sources must verify the authenticated owner's actual stored bytes.
    """
    items = source_items_from_inputs(
        cover_image=cover_image, cover_images=cover_images, extra_images=extra_images,
    )
    return list(dict.fromkeys(item["media_ref"] for item in items))


def project_source_items(value: Any) -> list[dict]:
    """Project only valid original field/index/UUID mappings; fail closed."""
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or len(value) > MAX_REPORT_SOURCE_REFS:
        return []
    result = []
    positions = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"input_field", "image_index", "media_ref"}:
            return []
        field = item["input_field"]
        index = item["image_index"]
        if (not isinstance(field, str)
                or field not in {"cover_image", "cover_images", "extra_images"}
                or type(index) is not int or not 1 <= index <= MAX_SOURCE_REFS
                or (field == "cover_image" and index != 1)):
            return []
        reference_id = _source_ref(item["media_ref"])
        if reference_id is None or (field, index) in positions:
            return []
        positions.add((field, index))
        result.append({"input_field": field, "image_index": index, "media_ref": reference_id})
    return result


def project_source_refs(value: Any, *, maximum: int = MAX_SOURCE_REFS) -> list[str]:
    """Fail closed when projecting an old or malformed persisted public field."""
    try:
        return normalize_source_refs(value, maximum=maximum)
    except CoverSourceValidationError:
        return []


def inspect_sources(
    user_id: str, reference_ids: Any, *, now: datetime | None = None,
) -> dict:
    """Read and verify existing uploads, returning only safe public status.

    Missing, expired, deleted, wrong-purpose and other-owner references share
    one reupload response. A storage outage/integrity failure is kept distinct
    so the UI does not tell the user their photo expired without evidence.
    All bytes, object keys, hashes and supplier lifecycle fields stay private.
    Report inspection supports ten references for the legacy cover-plus-nine
    input contract; a cover job still accepts at most nine selected candidates.
    This blocking reader should run through the existing media worker slot.
    """
    identifiers = normalize_source_refs(reference_ids, maximum=MAX_REPORT_SOURCE_REFS)
    if not isinstance(user_id, str) or not user_id:
        raise CoverSourceValidationError("An authenticated source owner is required")
    if not identifiers:
        return {"status": "reupload_required", "sources": [], "ready_count": 0}

    import private_storage

    sources = []
    for reference_id in identifiers:
        try:
            reference, body = private_storage.load_media_bytes(
                reference_id, user_id=user_id, purpose="image", now=now,
            )
            del body
        except private_storage.MediaReferenceUnavailable:
            sources.append({"media_ref": reference_id, "status": "reupload_required"})
        except private_storage.PrivateStorageError as exc:
            status = (
                "reupload_required" if exc.code == "PRIVATE_OBJECT_NOT_FOUND"
                else "storage_unavailable"
            )
            sources.append({"media_ref": reference_id, "status": status})
        else:
            sources.append({
                "media_ref": reference.id, "status": "ready",
                "expires_at": reference.expires_at,
                "content_type": reference.content_type,
            })
    if any(source["status"] == "storage_unavailable" for source in sources):
        status = "storage_unavailable"
    elif any(source["status"] != "ready" for source in sources):
        status = "reupload_required"
    else:
        status = "ready"
    return {
        "status": status, "sources": sources,
        "ready_count": sum(source["status"] == "ready" for source in sources),
    }
