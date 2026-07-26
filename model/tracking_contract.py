"""Shared, provider-free safety contract for XHS Tracking."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit


MAX_ROUND_LIMIT = 50
DAILY_PROVIDER_LIMIT = 300
MAX_METRIC_VALUE = 2_147_483_647
CLAIM_LEASE = timedelta(minutes=15)
ALLOWED_TRACKING_STATUSES = {
    "pending",
    "checking_24h",
    "checking_7d",
    "needs_manual",
    "complete",
    "failed",
    "account_deletion_pending",
}
CLAIMABLE_STATUSES = {"pending", "checking_24h", "checking_7d"}
TERMINAL_STATUSES = {"complete", "account_deletion_pending"}
MANUAL_FILL_STATUSES = {"needs_manual", "failed"}
_NOTE_ID_RE = re.compile(r"^[0-9a-fA-F]{24}$")
_FULL_PATH_RE = re.compile(
    r"^/(?:explore|discovery/item)/([0-9a-fA-F]{24})/?$"
)
_ALLOWED_HOSTS = {"www.xiaohongshu.com", "xiaohongshu.com"}
_EFFECT_NAMESPACE = uuid.UUID("9b588fb0-5c08-4b09-bf83-271ff72b559b")


class TrackingContractError(ValueError):
    """Stable validation failure without echoing untrusted input."""


class TrackingDailyLimitReached(TrackingContractError):
    """The durable UTC-day provider admission cap is exhausted."""


def normalize_xhs_note_url(value: str) -> tuple[str, str]:
    """Return a canonical, secret-free full note URL and its note id.

    Short links are deliberately rejected until a bounded, trusted resolver is
    available. Query strings and fragments are never persisted.
    """
    raw = str(value or "").strip()
    if not raw or len(raw) > 2048:
        raise TrackingContractError("invalid_xhs_note_url")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except (TypeError, ValueError):
        raise TrackingContractError("invalid_xhs_note_url") from None
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme.lower() != "https"
        or host not in _ALLOWED_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
    ):
        raise TrackingContractError("invalid_xhs_note_url")
    match = _FULL_PATH_RE.fullmatch(parsed.path)
    if not match:
        raise TrackingContractError("invalid_xhs_note_url")
    note_id = match.group(1).lower()
    if not _NOTE_ID_RE.fullmatch(note_id):
        raise TrackingContractError("invalid_xhs_note_url")
    return (canonical_xhs_note_url(note_id), note_id)


def canonical_xhs_note_url(note_id: str) -> str:
    """Build the only persisted/public URL shape from one exact note id."""
    normalized = str(note_id or "").strip().lower()
    if not _NOTE_ID_RE.fullmatch(normalized):
        raise TrackingContractError("invalid_xhs_note_id")
    return f"https://www.xiaohongshu.com/explore/{normalized}"


def safe_public_xhs_note_url(
    stored_url: str | None,
    stored_note_id: str | None,
) -> str | None:
    """Return a canonical URL without ever reflecting a legacy raw value."""
    try:
        canonical, parsed_note_id = normalize_xhs_note_url(stored_url or "")
        if (
            stored_note_id is None
            or parsed_note_id == str(stored_note_id).strip().lower()
        ):
            return canonical
    except TrackingContractError:
        pass
    try:
        return canonical_xhs_note_url(stored_note_id or "")
    except TrackingContractError:
        return None


def parse_published_at(
    value: str | None,
    *,
    now: datetime | None = None,
) -> str | None:
    """Validate one explicitly-zoned publication clock and normalize to UTC."""
    if value is None or value == "":
        return None
    if not isinstance(value, str) or value != value.strip():
        raise TrackingContractError("invalid_published_at")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        raise TrackingContractError("invalid_published_at") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TrackingContractError("invalid_published_at")
    if abs(parsed.utcoffset()) > timedelta(hours=14):
        raise TrackingContractError("invalid_published_at")
    normalized = parsed.astimezone(timezone.utc)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if normalized > current + timedelta(minutes=5):
        raise TrackingContractError("published_at_in_future")
    return normalized.isoformat()


def next_check_at(
    published_at: str | None,
    *,
    hours: int,
    now: datetime | None = None,
) -> str:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    normalized = parse_published_at(published_at, now=current)
    base = (
        datetime.fromisoformat(normalized)
        if normalized is not None
        else current
    )
    due = base + timedelta(hours=hours)
    return (due if due > current else current).isoformat()


def validate_round_limit(value: int) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        raise ValueError("invalid_tracking_round_limit") from None
    if limit < 1 or limit > MAX_ROUND_LIMIT:
        raise ValueError("invalid_tracking_round_limit")
    return limit


def validate_provider_metrics(data: dict) -> dict:
    if not isinstance(data, dict):
        raise TrackingContractError("invalid_provider_metrics")
    normalized = dict(data)
    for key in ("likes", "saves", "comments"):
        value = data.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            or value > MAX_METRIC_VALUE
        ):
            raise TrackingContractError("invalid_provider_metrics")
        normalized[key] = value
    normalized["title"] = str(data.get("title") or "")[:100]
    return normalized


def stage_for_status(status: str) -> str:
    if status == "pending":
        return "24h"
    if status in {"checking_24h", "checking_7d"}:
        return "7d"
    raise TrackingContractError("invalid_tracking_stage")


def deterministic_effect_id(track_id: str, effect: str) -> str:
    if effect not in {"growth", "memory"}:
        raise TrackingContractError("invalid_tracking_effect")
    return str(uuid.uuid5(_EFFECT_NAMESPACE, f"{track_id}:terminal:{effect}"))
