"""Shared, provider-free safety contract for XHS Tracking."""
from __future__ import annotations

import re
import uuid
import hashlib
import json
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


def observation_generation(note: dict) -> int:
    generation = note.get("observation_generation", 0)
    if type(generation) is not int or generation < 0:
        raise TrackingContractError("invalid_observation_generation")
    return generation


def validate_observation_binding(value: dict) -> dict:
    keys={'track_id','owner_id','generation','observation_started_at','initial_snapshot',
          'previous_attempt_id','previous_attempt_sha256'}
    try:
        if not isinstance(value,dict) or type(value.get('generation')) is not int or value['generation'] not in {1,2}:
            raise ValueError()
        if set(value)!=(keys if value['generation']==1 else keys|{'sealed_attempts'}):
            raise ValueError()
        for name in ('track_id','owner_id','previous_attempt_id'):
            if str(uuid.UUID(value[name]))!=value[name]:raise ValueError()
        anchor=datetime.fromisoformat(value['observation_started_at'].replace('Z','+00:00'))
        if anchor.tzinfo is None:raise ValueError()
        if not re.fullmatch(r'[0-9a-f]{64}',value['previous_attempt_sha256']):raise ValueError()
        if value['generation']==2:
            sealed=value['sealed_attempts']
            if not isinstance(sealed,list) or len(sealed)!=2:raise ValueError()
            for generation,entry in enumerate(sealed):
                if (not isinstance(entry,dict) or set(entry)!={'generation','attempt_id','sha256'}
                    or type(entry['generation']) is not int or entry['generation']!=generation
                    or str(uuid.UUID(entry['attempt_id']))!=entry['attempt_id']
                    or not re.fullmatch(r'[0-9a-f]{64}',entry['sha256'])):raise ValueError()
            if (sealed[0]['attempt_id']==sealed[1]['attempt_id']
                or sealed[-1]['attempt_id']!=value['previous_attempt_id']
                or sealed[-1]['sha256']!=value['previous_attempt_sha256']):raise ValueError()
        metrics=value['initial_snapshot']
        if not isinstance(metrics,dict) or set(metrics)!={'likes','saves','comments'}:raise ValueError()
        validate_provider_metrics(metrics)
        result=json.loads(json.dumps(value))
        result['observation_started_at']=anchor.astimezone(timezone.utc).isoformat()
        return result
    except (ValueError,TypeError,KeyError,AttributeError):
        raise TrackingContractError('invalid_observation_binding') from None


def assert_observation_binding(note: dict, binding: dict) -> None:
    try:
        anchor=datetime.fromisoformat(note['observation_started_at'].replace('Z','+00:00')).astimezone(timezone.utc).isoformat()
        if (note['id']!=binding['track_id'] or note['user_id']!=binding['owner_id']
            or observation_generation(note)!=binding['generation'] or anchor!=binding['observation_started_at']
            or note['observation_initial_snapshot']!=binding['initial_snapshot']):raise ValueError()
    except (ValueError,TypeError,KeyError,AttributeError):
        raise TrackingContractError('observation_binding_changed') from None


def observation_history_digest(row: dict) -> str:
    fields=('id','track_id','user_id','run_id','stage','status','admitted_at','completed_at','error_code')
    value={key:row[key] for key in fields}
    for key in ('admitted_at','completed_at'):
        parsed=datetime.fromisoformat(str(value[key]).replace('Z','+00:00'))
        if parsed.tzinfo is None:raise TrackingContractError('invalid_observation_history')
        value[key]=parsed.astimezone(timezone.utc).isoformat()
    value['observation_generation']=row.get('observation_generation',0)
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()


def assert_observation_history(rows: list, binding: dict) -> list:
    """Check every sealed failed generation; return only the current attempts.

    Callers doing database work must hold the target row and these history rows
    locked through claim/admission. Generation1's original binding stays unchanged.
    """
    binding=validate_observation_binding(binding)
    try:
        expected=binding.get('sealed_attempts',[{'generation':0,
            'attempt_id':binding['previous_attempt_id'],'sha256':binding['previous_attempt_sha256']}])
        current=[row for row in rows if row.get('observation_generation',0)==binding['generation']]
        prior=[row for row in rows if row.get('observation_generation',0)!=binding['generation']]
        if len(prior)!=len(expected):raise ValueError()
        anchor=datetime.fromisoformat(binding['observation_started_at'])
        for entry in expected:
            matches=[row for row in prior if row['id']==entry['attempt_id']]
            if len(matches)!=1:raise ValueError()
            row=matches[0]
            admitted=datetime.fromisoformat(str(row['admitted_at']).replace('Z','+00:00'))
            completed=datetime.fromisoformat(str(row['completed_at']).replace('Z','+00:00'))
            if (row.get('observation_generation',0)!=entry['generation']
                or row['track_id']!=binding['track_id'] or row['user_id']!=binding['owner_id']
                or row['status']!='failed' or row['stage']!='24h'
                or not row['error_code'] or row['error_code']=='provider_outcome_unknown'
                or admitted.tzinfo is None or completed.tzinfo is None
                or not admitted<=completed<anchor
                or observation_history_digest(row)!=entry['sha256']):raise ValueError()
        if any(row['track_id']!=binding['track_id'] or row['user_id']!=binding['owner_id'] for row in current):
            raise ValueError()
        return current
    except (ValueError,TypeError,KeyError,AttributeError):
        raise TrackingContractError('observation_history_changed') from None


def observation_stage_ready(note: dict, stage: str, now: datetime) -> bool:
    """Prospective generations use a new T0; generation zero keeps its contract."""
    if observation_generation(note) == 0:
        return True
    try:
        anchor = datetime.fromisoformat(note["observation_started_at"].replace("Z", "+00:00"))
        if anchor.tzinfo is None:
            return False
        if stage == "24h":
            return anchor + timedelta(hours=24) <= now < anchor + timedelta(hours=72)
        previous = datetime.fromisoformat(note["check_24h_at"].replace("Z", "+00:00"))
        return (stage == "7d" and previous.tzinfo is not None
                and anchor + timedelta(hours=24) <= previous < anchor + timedelta(hours=72)
                and now >= anchor + timedelta(hours=72) and now > previous)
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def deterministic_effect_id(track_id: str, effect: str, *, generation: int = 0) -> str:
    if effect not in {"growth", "memory"}:
        raise TrackingContractError("invalid_tracking_effect")
    observation_generation({"observation_generation": generation})
    identity = f"{track_id}:terminal:{effect}"
    if generation:
        identity = f"{track_id}:observation:{generation}:terminal:{effect}"
    return str(uuid.uuid5(_EFFECT_NAMESPACE, identity))
