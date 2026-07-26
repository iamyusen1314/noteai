"""XHS acquisition health and freshness ledger.

This module records whether the market-timing worker has acquired fresh,
real Xiaohongshu evidence for each core industry. It deliberately separates
"fresh XHS evidence" from baseline evidence so production can enforce a hard
freshness gate without pretending fallback rows are platform evidence.
"""

from __future__ import annotations

import json
import math
import os
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

import hot_keywords
import runtime_settings
import security_redaction


REAL_XHS_EVIDENCE_SOURCES = {
    "hot_search",
    "search_recommend",
    "search_phrase",
    "search_token",
    "homefeed_phrase",
    "homefeed_token",
    "crawler",
    "xhs_downloader",
    "mediacrawler",
}

LATEST_RUN_SOURCE_BUCKETS = (
    "homefeed",
    "search_result",
    "search_recommend",
    "hot_search",
    "other",
)

ACCESS_STATUSES = frozenset({
    "normal",
    "challenge",
    "cooldown",
    "login_required",
    "suspended",
})
PUBLIC_HEALTH_ERROR_SUMMARIES = {
    "": "",
    "access_challenge_detected": "Search discovery stopped after an access challenge",
    "access_challenge_cooldown_active": "Search discovery skipped during access challenge cooldown",
    "auth_cookie_missing": "XHS authentication cookies are missing",
    "collection_suspended": "XHS collection is suspended by operator policy",
    "cookie_expired": "XHS login session has expired",
    "cookie_not_configured": "XHS login session is not configured",
    "latest_run_no_evidence": "Latest run produced no XHS evidence",
    "latest_run_search_result_missing": "Latest run is missing search result evidence",
    "latest_run_search_recommend_missing": "Latest run is missing search recommendation evidence",
    "latest_run_search_sources_missing": "Latest run is missing required search source evidence",
    "latest_run_source_degraded": "Latest run source coverage is degraded",
    "selector_changed": "Crawler selector validation failed",
    "server_session_logged_out": "XHS server session requires operator re-login",
    "session_or_access_unavailable": "Configured XHS session returned no fresh evidence",
    "sidecar_empty_or_error": "XHS downloader returned no usable detail",
    "sidecar_not_configured": "XHS downloader sidecar is not configured",
    "scrape_once_failed": "XHS collection cycle failed before producing evidence",
}
PUBLIC_HEALTH_ERROR_CODES = frozenset(PUBLIC_HEALTH_ERROR_SUMMARIES)
_COLLECTION_SAFETY_KEY = "xhs_collection_safety"
_COLLECTION_SAFETY_REASON_CODES = frozenset({"", "server_session_logged_out"})


def _latest_run_source_bucket(source: str) -> str:
    normalized = str(source or "").strip().lower()
    if normalized in {"homefeed", "homefeed_phrase", "homefeed_token"}:
        return "homefeed"
    if normalized in {"search_result", "search_phrase", "search_token"}:
        return "search_result"
    if normalized == "search_recommend":
        return "search_recommend"
    if normalized == "hot_search":
        return "hot_search"
    return "other"


def normalize_latest_run_source_breakdown(source_counts: dict[str, Any] | None) -> dict[str, int]:
    breakdown = {bucket: 0 for bucket in LATEST_RUN_SOURCE_BUCKETS}
    for source, raw_count in (source_counts or {}).items():
        try:
            count = max(0, int(raw_count or 0))
        except Exception:
            count = 0
        breakdown[_latest_run_source_bucket(source)] += count
    return breakdown


def _build_latest_run_source_health(
    source_counts: dict[str, Any] | None,
    evidence_count: int,
    *,
    run_id: str = "",
    checked_at: str = "",
    available: bool = True,
) -> dict[str, Any]:
    breakdown = normalize_latest_run_source_breakdown(source_counts)
    base = {
        "available": bool(available),
        "run_id": run_id,
        "checked_at": checked_at,
        "evidence_count": max(0, int(evidence_count or 0)),
        "source_breakdown": breakdown,
        "missing_sources": [],
        "error_code": "",
    }
    if not available:
        return {**base, "ok": None, "status": "unknown"}
    if base["evidence_count"] <= 0:
        return {
            **base,
            "ok": False,
            "status": "failed",
            "error_code": "latest_run_no_evidence",
        }
    missing = [
        source for source in ("search_result", "search_recommend")
        if breakdown.get(source, 0) <= 0
    ]
    if missing:
        if len(missing) == 2:
            error_code = "latest_run_search_sources_missing"
        elif missing[0] == "search_result":
            error_code = "latest_run_search_result_missing"
        else:
            error_code = "latest_run_search_recommend_missing"
        return {
            **base,
            "ok": False,
            "status": "degraded",
            "missing_sources": missing,
            "error_code": error_code,
        }
    return {**base, "ok": True, "status": "healthy"}

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS xhs_crawler_health (
    id                       TEXT PRIMARY KEY,
    run_id                   TEXT NOT NULL,
    adapter                  TEXT NOT NULL,
    domain                   TEXT DEFAULT '',
    profile_cookie_valid     INTEGER DEFAULT 0,
    note_page_access_valid   INTEGER DEFAULT 0,
    shortlink_canonicalized  INTEGER DEFAULT 0,
    selector_valid           INTEGER DEFAULT 0,
    risk_login_detected      INTEGER DEFAULT 0,
    evidence_count           INTEGER DEFAULT 0,
    status                   TEXT NOT NULL,
    error_code               TEXT DEFAULT '',
    error_summary            TEXT DEFAULT '',
    checked_at               TEXT NOT NULL,
    details_json             TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_xhs_health_run ON xhs_crawler_health(run_id, checked_at);
CREATE INDEX IF NOT EXISTS idx_xhs_health_domain ON xhs_crawler_health(domain, checked_at);

CREATE TABLE IF NOT EXISTS xhs_freshness_ledger (
    id              TEXT PRIMARY KEY,
    domain          TEXT NOT NULL,
    evidence_date   TEXT NOT NULL,
    source          TEXT NOT NULL,
    evidence_count  INTEGER DEFAULT 0,
    status          TEXT NOT NULL,
    acquired_at     TEXT NOT NULL,
    fresh_until     TEXT NOT NULL,
    last_run_id     TEXT NOT NULL,
    details_json    TEXT DEFAULT '{}',
    UNIQUE(domain, evidence_date)
);

CREATE INDEX IF NOT EXISTS idx_xhs_freshness_domain ON xhs_freshness_ledger(domain, acquired_at);
CREATE INDEX IF NOT EXISTS idx_xhs_freshness_status ON xhs_freshness_ledger(status, fresh_until);
"""


@dataclass
class CrawlerHealth:
    adapter: str
    status: str
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    domain: str = ""
    profile_cookie_valid: bool = False
    note_page_access_valid: bool = False
    shortlink_canonicalized: bool = False
    selector_valid: bool = False
    risk_login_detected: bool = False
    evidence_count: int = 0
    error_code: str = ""
    error_summary: str = ""
    details: dict[str, Any] = field(default_factory=dict)


def _now() -> datetime:
    return datetime.now()


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).isoformat()


def _json_safe(value: Any) -> str:
    try:
        return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)
    except Exception:
        return "{}"


def _parse_json_object(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def init_db() -> None:
    hot_keywords.init_db()
    if hot_keywords.primary_db.using_postgres():
        return
    conn = hot_keywords._conn()
    try:
        with conn:
            conn.executescript(_INIT_SQL)
    finally:
        conn.close()


def xhs_freshness_required() -> bool:
    raw = (
        os.environ.get("NOTEAI_XHS_FRESHNESS_REQUIRED")
        or os.environ.get("NOTEAI_MARKET_TIMING_REQUIRE_XHS_FRESHNESS")
        or "0"
    )
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def collection_safety_status() -> dict[str, Any]:
    """Return the fixed, secret-free cross-Cron collection safety state."""
    raw = runtime_settings.get_json(_COLLECTION_SAFETY_KEY, {})
    raw = raw if isinstance(raw, dict) else {}
    reason_code = str(raw.get("reason_code") or "")
    if reason_code not in _COLLECTION_SAFETY_REASON_CODES:
        reason_code = ""
    blocked = bool(raw.get("session_blocked") and reason_code)
    return {
        "session_blocked": blocked,
        "reason_code": reason_code if blocked else "",
        "blocked_at": str(raw.get("blocked_at") or "") if blocked else "",
    }


def mark_server_session_logged_out() -> dict[str, Any]:
    """Persist a safe stop flag after the server redirects collection to login."""
    state = {
        "session_blocked": True,
        "reason_code": "server_session_logged_out",
        "blocked_at": datetime.now(timezone.utc).isoformat(),
    }
    runtime_settings.set_json(_COLLECTION_SAFETY_KEY, state)
    return state


def clear_collection_session_block() -> None:
    """Clear only the server-session stop flag after an operator cookie update."""
    runtime_settings.set_json(_COLLECTION_SAFETY_KEY, {
        "session_blocked": False,
        "reason_code": "",
        "blocked_at": "",
    })


def minimum_evidence_per_domain() -> int:
    return hot_keywords._min_domain_keywords()


def record_health(health: CrawlerHealth | dict[str, Any]) -> dict:
    init_db()
    if isinstance(health, CrawlerHealth):
        payload = asdict(health)
    else:
        payload = dict(health)
    row_id = payload.get("id") or str(uuid.uuid4())
    checked_at = payload.get("checked_at") or _iso()
    conn = hot_keywords._conn()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO xhs_crawler_health
                    (id, run_id, adapter, domain, profile_cookie_valid,
                     note_page_access_valid, shortlink_canonicalized, selector_valid,
                     risk_login_detected, evidence_count, status, error_code,
                     error_summary, checked_at, details_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row_id,
                    payload.get("run_id") or str(uuid.uuid4()),
                    payload.get("adapter") or "unknown",
                    payload.get("domain") or "",
                    1 if payload.get("profile_cookie_valid") else 0,
                    1 if payload.get("note_page_access_valid") else 0,
                    1 if payload.get("shortlink_canonicalized") else 0,
                    1 if payload.get("selector_valid") else 0,
                    1 if payload.get("risk_login_detected") else 0,
                    int(payload.get("evidence_count") or 0),
                    payload.get("status") or "unknown",
                    payload.get("error_code") or "",
                    str(payload.get("error_summary") or "")[:500],
                    checked_at,
                    _json_safe(payload.get("details") or payload.get("details_json") or {}),
                ),
            )
    finally:
        conn.close()
    return {"id": row_id, "checked_at": checked_at}


def _is_real_xhs_row(row: dict) -> bool:
    source = str(row.get("source") or "").strip()
    if source not in REAL_XHS_EVIDENCE_SOURCES:
        return False
    return int(row.get("quality_score", 0) or 0) >= 55


def _row_domain(row: dict) -> str:
    return str(row.get("category") or row.get("domain") or "").strip()


def _first_text(payload: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _first_int(payload: dict, keys: tuple[str, ...]) -> int:
    for key in keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        if value in (None, ""):
            continue
        try:
            if isinstance(value, str):
                cleaned = value.replace(",", "").replace("+", "").strip()
                if not cleaned:
                    continue
                if "万" in cleaned:
                    return int(float(cleaned.replace("万", "")) * 10000)
                return int(float(cleaned or 0))
            return int(value or 0)
        except Exception:
            continue
    return 0


def _candidate_note_payloads(value: Any) -> list[dict]:
    if isinstance(value, dict):
        candidates = []
        for key in ("note", "note_card", "item", "items", "data", "detail", "result", "info"):
            child = value.get(key)
            if isinstance(child, (dict, list)):
                candidates.extend(_candidate_note_payloads(child))
        if any(key in value for key in (
            "title",
            "desc",
            "display_title",
            "liked_count",
            "collected_count",
            "comments_count",
            "作品ID",
            "作品标题",
            "作品描述",
            "点赞数量",
            "收藏数量",
            "评论数量",
            "分享数量",
        )):
            candidates.append(value)
        return candidates
    if isinstance(value, list):
        out: list[dict] = []
        for item in value:
            out.extend(_candidate_note_payloads(item))
        return out
    return []


def normalize_sidecar_detail(payload: dict | list | None) -> dict:
    """Normalize common XHS-Downloader-style detail payloads.

    Different sidecar versions wrap note data differently. This keeps the
    contract tolerant while returning a stable NoteAI shape.
    """
    candidates = _candidate_note_payloads(payload or {})
    note = candidates[0] if candidates else {}
    stats = note.get("interact_info") if isinstance(note.get("interact_info"), dict) else {}
    merged = {**note, **stats}
    title = _first_text(merged, ("title", "display_title", "note_title", "作品标题"))
    desc = _first_text(merged, ("desc", "description", "content", "note_desc", "作品描述"))
    note_id = _first_text(merged, ("note_id", "id", "item_id", "aweme_id", "作品ID"))
    normalized = {
        "note_id": note_id,
        "title": title,
        "desc": desc,
        "likes": _first_int(merged, ("liked_count", "likes", "like_count", "liked", "点赞数量")),
        "saves": _first_int(merged, ("collected_count", "collects", "saves", "collect_count", "collected", "收藏数量")),
        "comments": _first_int(merged, ("comments_count", "comment_count", "comments", "评论数量")),
        "shares": _first_int(merged, ("share_count", "shares", "分享数量")),
        "source": "xhs_downloader",
    }
    normalized["has_content"] = bool(title or desc or note_id)
    normalized["has_metrics"] = any(int(normalized[key] or 0) > 0 for key in ("likes", "saves", "comments", "shares"))
    return normalized


def record_freshness(
    domain: str,
    evidence_count: int,
    *,
    source: str,
    run_id: str,
    details: dict[str, Any] | None = None,
    acquired_at: datetime | None = None,
    min_count: int | None = None,
) -> dict:
    init_db()
    acquired = acquired_at or _now()
    minimum = int(min_count or minimum_evidence_per_domain())
    count = int(evidence_count or 0)
    status = "fresh" if count >= minimum else "insufficient"
    fresh_until = acquired + timedelta(hours=hot_keywords.FRESHNESS_MAX_HOURS)
    evidence_date = acquired.strftime("%Y-%m-%d")
    row_id = str(uuid.uuid4())
    conn = hot_keywords._conn()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO xhs_freshness_ledger
                    (id, domain, evidence_date, source, evidence_count, status,
                     acquired_at, fresh_until, last_run_id, details_json)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(domain, evidence_date) DO UPDATE SET
                    source=excluded.source,
                    evidence_count=excluded.evidence_count,
                    status=excluded.status,
                    acquired_at=excluded.acquired_at,
                    fresh_until=excluded.fresh_until,
                    last_run_id=excluded.last_run_id,
                    details_json=excluded.details_json
                """,
                (
                    row_id,
                    domain,
                    evidence_date,
                    source,
                    count,
                    status,
                    acquired.isoformat(),
                    fresh_until.isoformat(),
                    run_id,
                    _json_safe(details or {}),
                ),
            )
    finally:
        conn.close()
    return {
        "domain": domain,
        "evidence_date": evidence_date,
        "source": source,
        "evidence_count": count,
        "minimum": minimum,
        "status": status,
        "fresh_until": fresh_until.isoformat(),
        "run_id": run_id,
    }


def record_scrape_freshness(
    rows: list[dict],
    *,
    run_id: str | None = None,
    domains: tuple[str, ...] | list[str] | None = None,
    min_count: int | None = None,
    session_status: dict[str, Any] | None = None,
    scrape_error: str = "",
    discovery_diagnostics: dict[str, Any] | None = None,
    adapter: str = "scheduler_a",
) -> dict:
    init_db()
    effective_run_id = run_id or str(uuid.uuid4())
    domain_counts: dict[str, int] = defaultdict(int)
    domain_evidence_keys: dict[str, set[str]] = defaultdict(set)
    domain_source_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    source_counts: dict[str, int] = defaultdict(int)
    for raw in rows or []:
        cleaned = hot_keywords.clean_scraped_keyword_row(dict(raw))
        if not cleaned or not _is_real_xhs_row(cleaned):
            continue
        domain = _row_domain(cleaned)
        if not domain:
            continue
        domain_counts[domain] += 1
        source = str(cleaned.get("source") or "unknown")
        source_counts[source] += 1
        domain_source_counts[domain][source] += 1
        domain_evidence_keys[domain].add(json.dumps(
            [source, str(cleaned.get("keyword") or "").strip()],
            ensure_ascii=False,
            separators=(",", ":"),
        ))

    target_domains = tuple(domains or hot_keywords.CORE_EVIDENCE_DOMAINS)
    ledger = []
    acquired = _now()
    evidence_date = acquired.strftime("%Y-%m-%d")
    session = dict(session_status or {})
    safe_discovery_diagnostics: dict[str, Any] = {}
    if discovery_diagnostics is not None:
        try:
            from scheduler_a import sanitize_discovery_diagnostics
            safe_discovery_diagnostics = sanitize_discovery_diagnostics(discovery_diagnostics)
        except Exception:
            safe_discovery_diagnostics = {}
    diagnostic_codes = set(safe_discovery_diagnostics.get("diagnostic_error_codes") or [])
    circuit_state = str((safe_discovery_diagnostics.get("circuit") or {}).get("state") or "closed")
    if "server_session_logged_out" in diagnostic_codes:
        access_status = "login_required"
    elif "collection_suspended" in diagnostic_codes:
        access_status = "suspended"
    elif "possible_access_challenge" in diagnostic_codes or circuit_state == "open":
        access_status = "challenge"
    elif circuit_state == "cooldown" or "challenge_cooldown_active" in diagnostic_codes:
        access_status = "cooldown"
    else:
        access_status = "normal"
    configured_cookie_valid = bool(
        session.get("configured")
        and session.get("auth_cookie_present")
        and not session.get("auth_cookie_expired")
    )
    for domain in target_domains:
        current_keys = set(domain_evidence_keys.get(domain, set()))
        conn = hot_keywords._conn()
        try:
            previous = conn.execute(
                "SELECT details_json FROM xhs_freshness_ledger WHERE domain=? AND evidence_date=?",
                (domain, evidence_date),
            ).fetchone()
        finally:
            conn.close()
        previous_details = _parse_json_object(previous["details_json"]) if previous else {}
        previous_keys = {
            str(value) for value in (previous_details.get("evidence_keys") or []) if value
        }
        accumulated_keys = previous_keys | current_keys
        count = len(accumulated_keys)
        current_count = int(domain_counts.get(domain, 0) or 0)
        latest_source_health = _build_latest_run_source_health(
            domain_source_counts.get(domain),
            current_count,
            run_id=effective_run_id,
            checked_at=acquired.isoformat(),
        )
        details = {
            "source_counts": dict(source_counts),
            "latest_run_source_counts": dict(domain_source_counts.get(domain, {})),
            "latest_run_source_breakdown": latest_source_health["source_breakdown"],
            "latest_run_source_health": latest_source_health,
            "evidence_keys": sorted(accumulated_keys),
            "latest_run_evidence_count": current_count,
            "session_configured": bool(session.get("configured")),
            "discovery_diagnostics": safe_discovery_diagnostics,
            "access_status": access_status,
        }
        ledger.append(record_freshness(
            domain,
            count,
            source="xhs_public_scrape",
            run_id=effective_run_id,
            min_count=min_count,
            details=details,
            acquired_at=acquired,
        ))
        # The freshness ledger needs de-duplication keys; crawler health does not.
        # Keep raw keyword-bearing evidence keys out of operational health details.
        health_details = {
            key: value for key, value in details.items()
            if key != "evidence_keys"
        }
        if access_status == "login_required":
            health_status = "failed"
            error_code = "server_session_logged_out"
            error_summary = PUBLIC_HEALTH_ERROR_SUMMARIES[error_code]
            risk_login = True
        elif access_status == "suspended":
            health_status = "failed"
            error_code = "collection_suspended"
            error_summary = PUBLIC_HEALTH_ERROR_SUMMARIES[error_code]
            risk_login = False
        elif access_status == "challenge":
            health_status = "degraded"
            error_code = "access_challenge_detected"
            error_summary = "Search discovery stopped after an access challenge"
            risk_login = False
        elif access_status == "cooldown":
            health_status = "degraded"
            error_code = "access_challenge_cooldown_active"
            error_summary = "Search discovery skipped during access challenge cooldown"
            risk_login = False
        elif current_count > 0:
            if latest_source_health.get("ok") is False:
                health_status = "degraded"
                error_code = str(latest_source_health.get("error_code") or "latest_run_source_degraded")
                missing_sources = ", ".join(latest_source_health.get("missing_sources") or [])
                error_summary = f"Latest run missing required search source evidence: {missing_sources}"
            else:
                health_status = "ok" if count >= int(min_count or minimum_evidence_per_domain()) else "insufficient"
                error_code = ""
                error_summary = ""
            risk_login = False
        elif not session.get("configured"):
            health_status = "failed"
            error_code = "cookie_not_configured"
            error_summary = "XHS login session is not configured"
            risk_login = True
        elif not session.get("auth_cookie_present"):
            health_status = "failed"
            error_code = "auth_cookie_missing"
            error_summary = "XHS authentication cookies are missing"
            risk_login = True
        elif session.get("auth_cookie_expired"):
            health_status = "failed"
            error_code = "cookie_expired"
            error_summary = "XHS login session has expired"
            risk_login = True
        elif scrape_error == "scrape_once_failed":
            health_status = "failed"
            error_code = "scrape_once_failed"
            error_summary = PUBLIC_HEALTH_ERROR_SUMMARIES[error_code]
            risk_login = False
        else:
            health_status = "failed"
            error_code = "session_or_access_unavailable"
            error_summary = PUBLIC_HEALTH_ERROR_SUMMARIES[error_code]
            risk_login = False
        cookie_valid = bool(
            access_status not in {"login_required", "suspended"}
            and (
                current_count > 0
                or (
                    access_status in {"challenge", "cooldown"}
                    and configured_cookie_valid
                )
            )
        )
        current_access_valid = bool(
            current_count > 0
            and access_status not in {"login_required", "suspended"}
        )
        record_health(CrawlerHealth(
            run_id=effective_run_id,
            adapter=adapter,
            domain=domain,
            status=health_status,
            profile_cookie_valid=cookie_valid,
            note_page_access_valid=current_access_valid,
            selector_valid=current_access_valid,
            risk_login_detected=risk_login,
            evidence_count=count,
            error_code=error_code,
            error_summary=error_summary,
            details=health_details,
        ))

    overview = freshness_overview(target_domains)
    return {
        "run_id": effective_run_id,
        "source": "xhs_public_scrape",
        "source_counts": dict(source_counts),
        "latest_run_source_breakdown": normalize_latest_run_source_breakdown(source_counts),
        "latest_run_evidence_count": sum(
            max(0, int(domain_counts.get(domain, 0) or 0))
            for domain in target_domains
        ),
        "domains": ledger,
        "overview": overview,
    }


def freshness_status(domain: str, *, now: datetime | None = None, min_count: int | None = None) -> dict:
    init_db()
    minimum = int(min_count or minimum_evidence_per_domain())
    current = now or _now()
    conn = hot_keywords._conn()
    try:
        rows = conn.execute(
            """
            SELECT * FROM xhs_freshness_ledger
            WHERE domain=?
            ORDER BY acquired_at DESC
            LIMIT 4
            """,
            (domain,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return {
            "domain": domain,
            "ok": False,
            "status": "missing",
            "evidence_count": 0,
            "minimum": minimum,
            "reason": "no_xhs_freshness_record",
        }
    active_rows = []
    for candidate in rows:
        try:
            fresh_until = datetime.fromisoformat(candidate["fresh_until"])
        except Exception:
            continue
        if fresh_until >= current:
            active_rows.append((candidate, fresh_until))
    if not active_rows:
        row = rows[0]
        return {
            "domain": domain,
            "ok": False,
            "status": "expired",
            "source": row["source"],
            "evidence_count": 0,
            "minimum": minimum,
            "acquired_at": row["acquired_at"],
            "fresh_until": row["fresh_until"],
            "last_run_id": row["last_run_id"],
            "reason": "xhs_freshness_expired",
        }
    evidence_keys: set[str] = set()
    legacy_count = 0
    for candidate, _ in active_rows:
        details = _parse_json_object(candidate["details_json"])
        keys = {str(value) for value in (details.get("evidence_keys") or []) if value}
        if keys:
            evidence_keys.update(keys)
        else:
            legacy_count = max(legacy_count, int(candidate["evidence_count"] or 0))
    row = active_rows[0][0]
    count = max(len(evidence_keys), legacy_count)
    latest_fresh_until = max(fresh_until for _, fresh_until in active_rows)
    ok = count >= minimum
    return {
        "domain": domain,
        "ok": bool(ok),
        "status": "fresh" if ok else "insufficient",
        "source": row["source"],
        "evidence_count": count,
        "minimum": minimum,
        "acquired_at": row["acquired_at"],
        "fresh_until": latest_fresh_until.isoformat(),
        "last_run_id": row["last_run_id"],
        "reason": "" if ok else "xhs_freshness_not_satisfied",
    }


def freshness_overview(domains: tuple[str, ...] | list[str] | None = None) -> dict:
    target_domains = tuple(domains or hot_keywords.CORE_EVIDENCE_DOMAINS)
    statuses = [freshness_status(domain) for domain in target_domains]
    missing = [row["domain"] for row in statuses if not row.get("ok")]
    access = access_status_overview()
    return {
        "ok": not missing,
        "required": xhs_freshness_required(),
        "domains": statuses,
        "missing_domains": missing,
        "latest_run_source_health": latest_run_source_health(target_domains),
        "access_status": access["access_status"],
        "access_error_code": access["error_code"],
        "challenge_cooldown": access["challenge_cooldown"],
    }


def recent_health(limit: int = 50, domain: str = "", adapter: str = "") -> list[dict]:
    init_db()
    clauses: list[str] = []
    params: list[Any] = []
    if domain:
        clauses.append("domain=?")
        params.append(domain)
    if adapter:
        clauses.append("adapter=?")
        params.append(adapter)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    safe_limit = max(1, min(int(limit or 50), 200))
    conn = hot_keywords._conn()
    try:
        rows = conn.execute(
            f"""
            SELECT id, run_id, adapter, domain, profile_cookie_valid,
                   note_page_access_valid, shortlink_canonicalized, selector_valid,
                   risk_login_detected, evidence_count, status, error_code,
                   error_summary, checked_at, details_json
            FROM xhs_crawler_health
            {where}
            ORDER BY checked_at DESC
            LIMIT ?
            """,
            (*params, safe_limit),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for row in rows:
        out.append({
            "id": row["id"],
            "run_id": row["run_id"],
            "adapter": row["adapter"],
            "domain": row["domain"],
            "profile_cookie_valid": bool(row["profile_cookie_valid"]),
            "note_page_access_valid": bool(row["note_page_access_valid"]),
            "shortlink_canonicalized": bool(row["shortlink_canonicalized"]),
            "selector_valid": bool(row["selector_valid"]),
            "risk_login_detected": bool(row["risk_login_detected"]),
            "evidence_count": int(row["evidence_count"] or 0),
            "status": row["status"],
            "error_code": row["error_code"] or "",
            "error_summary": row["error_summary"] or "",
            "checked_at": row["checked_at"],
            "details": _parse_json_object(row["details_json"]),
        })
    return out


def recent_collection_health(limit: int = 50, domain: str = "") -> list[dict]:
    """Return direct and legacy scheduler health in one newest-first view."""
    safe_limit = max(1, min(int(limit or 50), 200))
    rows = recent_health(
        limit=safe_limit, domain=domain, adapter="spider_xhs_http"
    ) + recent_health(
        limit=safe_limit, domain=domain, adapter="scheduler_a"
    )
    rows.sort(key=lambda row: str(row.get("checked_at") or ""), reverse=True)
    return rows[:safe_limit]


def _checked_at_epoch(value: Any) -> float | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def challenge_cooldown_status(
    *,
    now: datetime | None = None,
    cooldown_minutes: int | None = None,
) -> dict[str, Any]:
    """Return safe circuit state by scanning recent challenge health records.

    Cooldown rows are deliberately not treated as new challenges. Scanning the
    full recent window prevents a newer cooldown row from hiding the challenge
    that originally opened the circuit.
    """
    raw_minutes = (
        cooldown_minutes
        if cooldown_minutes is not None
        else os.environ.get("NOTEAI_XHS_CHALLENGE_COOLDOWN_MINUTES", "360")
    )
    try:
        minutes = max(0, int(raw_minutes or 0))
    except Exception:
        minutes = 360
    current = now or _now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current_epoch = current.timestamp()
    challenge_rows = []
    for row in recent_collection_health(limit=200):
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        diagnostics = (
            details.get("discovery_diagnostics")
            if isinstance(details.get("discovery_diagnostics"), dict)
            else {}
        )
        codes = set(diagnostics.get("diagnostic_error_codes") or [])
        is_challenge = (
            row.get("error_code") == "access_challenge_detected"
            or details.get("access_status") == "challenge"
            or "possible_access_challenge" in codes
        )
        checked_epoch = _checked_at_epoch(row.get("checked_at"))
        if is_challenge and checked_epoch is not None:
            challenge_rows.append((checked_epoch, str(row.get("checked_at") or "")))
    if not challenge_rows:
        return {"active": False, "last_challenge_at": "", "remaining_seconds": 0}
    last_epoch, last_checked_at = max(challenge_rows, key=lambda item: item[0])
    remaining = max(0.0, minutes * 60 - (current_epoch - last_epoch))
    return {
        "active": bool(minutes > 0 and remaining > 0),
        "last_challenge_at": last_checked_at,
        "remaining_seconds": int(math.ceil(remaining)),
    }


def access_status_overview() -> dict[str, Any]:
    rows = recent_collection_health(limit=200)
    latest = rows[0] if rows else {}
    details = latest.get("details") if isinstance(latest.get("details"), dict) else {}
    latest_status = str(details.get("access_status") or "")
    latest_error = str(latest.get("error_code") or "")
    cooldown = challenge_cooldown_status()
    if (
        latest_status == "login_required"
        or latest_error == "server_session_logged_out"
    ):
        access_status = "login_required"
        error_code = "server_session_logged_out"
    elif latest_status == "suspended" or latest_error == "collection_suspended":
        access_status = "suspended"
        error_code = "collection_suspended"
    elif latest_status == "challenge" or latest_error == "access_challenge_detected":
        access_status = "challenge"
        error_code = "access_challenge_detected"
    elif cooldown.get("active"):
        access_status = "cooldown"
        error_code = "access_challenge_cooldown_active"
    else:
        access_status = "normal"
        error_code = ""
    return {
        "access_status": access_status,
        "error_code": error_code,
        "challenge_cooldown": cooldown,
    }


def _safe_public_source_health(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    status = str(raw.get("status") or "unknown")
    if status not in {"unknown", "healthy", "degraded", "failed"}:
        status = "unknown"
    ok_value = raw.get("ok")
    ok = ok_value if isinstance(ok_value, bool) else None
    error_code = str(raw.get("error_code") or "")
    if error_code not in {
        "",
        "latest_run_no_evidence",
        "latest_run_search_result_missing",
        "latest_run_search_recommend_missing",
        "latest_run_search_sources_missing",
    }:
        error_code = ""
    try:
        evidence_count = max(0, int(raw.get("evidence_count") or 0))
    except Exception:
        evidence_count = 0
    raw_missing = raw.get("missing_sources")
    raw_missing = raw_missing if isinstance(raw_missing, (list, tuple, set)) else []
    missing_sources = [
        source for source in ("search_result", "search_recommend")
        if source in raw_missing
    ]
    return {
        "available": bool(raw.get("available")),
        "ok": ok,
        "status": status,
        "evidence_count": evidence_count,
        "source_breakdown": normalize_latest_run_source_breakdown(
            raw.get("source_breakdown") if isinstance(raw.get("source_breakdown"), dict) else {}
        ),
        "missing_sources": missing_sources,
        "error_code": error_code,
    }


def _safe_public_health_details(value: Any, access_status: str) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    safe: dict[str, Any] = {"access_status": access_status}
    try:
        safe["latest_run_evidence_count"] = max(
            0, int(raw.get("latest_run_evidence_count") or 0)
        )
    except Exception:
        safe["latest_run_evidence_count"] = 0
    safe["session_configured"] = bool(raw.get("session_configured"))
    safe["latest_run_source_breakdown"] = normalize_latest_run_source_breakdown(
        raw.get("latest_run_source_breakdown")
        if isinstance(raw.get("latest_run_source_breakdown"), dict)
        else {}
    )
    safe["latest_run_source_health"] = _safe_public_source_health(
        raw.get("latest_run_source_health")
    )
    return safe


def public_recent_health(limit: int = 50, domain: str = "", adapter: str = "") -> list[dict]:
    """Return the legacy row shape with only fixed, non-sensitive diagnostics."""
    public_rows = []
    for row in recent_health(limit=limit, domain=domain, adapter=adapter):
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        access_status = str(details.get("access_status") or "normal")
        if access_status not in ACCESS_STATUSES:
            access_status = "normal"
        error_code = str(row.get("error_code") or "")
        if error_code not in PUBLIC_HEALTH_ERROR_CODES:
            error_code = ""
        if error_code == "access_challenge_detected":
            access_status = "challenge"
        elif error_code == "access_challenge_cooldown_active":
            access_status = "cooldown"
        elif error_code == "server_session_logged_out":
            access_status = "login_required"
        elif error_code == "collection_suspended":
            access_status = "suspended"
        error_summary = PUBLIC_HEALTH_ERROR_SUMMARIES.get(error_code, "")
        safe_details = _safe_public_health_details(details, access_status)
        public_rows.append({
            key: row.get(key)
            for key in (
                "id",
                "run_id",
                "adapter",
                "domain",
                "profile_cookie_valid",
                "note_page_access_valid",
                "shortlink_canonicalized",
                "selector_valid",
                "risk_login_detected",
                "evidence_count",
                "status",
                "checked_at",
            )
        } | {
            "error_code": error_code,
            "error_summary": error_summary,
            "details": safe_details,
            "access_status": access_status,
        })
    return public_rows


def latest_run_source_health(domains: tuple[str, ...] | list[str] | None = None) -> dict[str, Any]:
    """Return source coverage for the latest scheduler run without changing freshness."""
    target_domains = set(domains or hot_keywords.CORE_EVIDENCE_DOMAINS)
    rows = [
        row for row in recent_collection_health(limit=200)
        if not target_domains or row.get("domain") in target_domains
    ]
    if not rows:
        return {
            **_build_latest_run_source_health({}, 0, available=False),
            "domains": [],
        }

    latest_run_id = str(rows[0].get("run_id") or "")
    run_rows = [row for row in rows if str(row.get("run_id") or "") == latest_run_id]
    checked_at = max((str(row.get("checked_at") or "") for row in run_rows), default="")
    evidence_count = sum(
        max(0, int((row.get("details") or {}).get("latest_run_evidence_count") or 0))
        for row in run_rows
    )

    source_counts: dict[str, int] = defaultdict(int)
    new_details_available = False
    legacy_source_counts: dict[str, Any] | None = None
    for row in run_rows:
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        per_domain = details.get("latest_run_source_counts")
        if isinstance(per_domain, dict):
            new_details_available = True
            for source, raw_count in per_domain.items():
                try:
                    source_counts[str(source)] += max(0, int(raw_count or 0))
                except Exception:
                    continue
        elif legacy_source_counts is None and isinstance(details.get("source_counts"), dict):
            # Older records copied the same run-wide source_counts onto each domain.
            legacy_source_counts = details["source_counts"]

    if not new_details_available and legacy_source_counts is not None:
        source_counts.update(legacy_source_counts)
    available = bool(new_details_available or legacy_source_counts is not None)
    if evidence_count <= 0 and available:
        evidence_count = sum(normalize_latest_run_source_breakdown(source_counts).values())
    health = _build_latest_run_source_health(
        source_counts,
        evidence_count,
        run_id=latest_run_id,
        checked_at=checked_at,
        available=available,
    )
    return {
        **health,
        "domains": sorted({str(row.get("domain") or "") for row in run_rows if row.get("domain")}),
    }


def freshness_probe(
    domains: tuple[str, ...] | list[str] | None = None,
    *,
    deadline_hour: int | None = None,
    deadline_minute: int = 0,
    now: datetime | None = None,
) -> dict:
    current = now or _now()
    hour = int(deadline_hour if deadline_hour is not None else os.environ.get("NOTEAI_XHS_FRESHNESS_DEADLINE_HOUR", "7") or 7)
    minute = int(os.environ.get("NOTEAI_XHS_FRESHNESS_DEADLINE_MINUTE", str(deadline_minute)) or deadline_minute)
    deadline = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    overview = freshness_overview(domains)
    missing = overview.get("missing_domains") or []
    latest_source_health = overview.get("latest_run_source_health") or {}
    source_degraded = bool(
        latest_source_health.get("available")
        and latest_source_health.get("ok") is False
    )
    access_action_required = overview.get("access_status") in {
        "login_required",
        "suspended",
    }
    return {
        **overview,
        "checked_at": current.isoformat(),
        "deadline": deadline.isoformat(),
        "deadline_passed": current >= deadline,
        "deadline_missed": bool(missing and current >= deadline),
        "action_required": bool(missing or source_degraded or access_action_required),
        "message": (
            "XHS collection is suspended pending operator action"
            if overview.get("access_status") == "suspended" else
            "XHS server session requires operator re-login"
            if overview.get("access_status") == "login_required" else
            "XHS cumulative freshness satisfied, but latest run source coverage is degraded"
            if not missing and source_degraded else
            "XHS freshness satisfied"
            if not missing else
            f"Missing fresh XHS evidence for: {', '.join(missing)}"
        ),
    }


class XHSDownloaderSidecar:
    """Small adapter for a separately managed XHS-Downloader API service."""

    def __init__(self, base_url: str | None = None, timeout: float | None = None):
        self.base_url = (base_url or os.environ.get("NOTEAI_XHS_DOWNLOADER_URL", "")).rstrip("/")
        self.timeout = float(timeout or os.environ.get("NOTEAI_XHS_DOWNLOADER_TIMEOUT", "20") or 20)
        self.detail_path = os.environ.get("NOTEAI_XHS_DOWNLOADER_DETAIL_PATH", "/xhs/detail").strip() or "/xhs/detail"

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def public_status(self) -> dict:
        parsed = urlparse(self.base_url) if self.base_url else None
        return {
            "configured": self.configured,
            "host": parsed.hostname if parsed else "",
            "scheme": parsed.scheme if parsed else "",
        }

    def fetch_detail(self, url: str, *, cookie: str = "", proxy: str = "") -> dict:
        if not self.configured:
            return {"ok": False, "error_code": "sidecar_not_configured"}
        payload = {
            "url": url,
            "download": False,
            "skip": False,
        }
        if cookie:
            payload["cookie"] = cookie
        if proxy:
            payload["proxy"] = proxy
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                resp = client.post(f"{self.base_url}{self.detail_path}", json=payload)
                resp.raise_for_status()
                data = resp.json()
                return {"ok": True, "data": data, "normalized": normalize_sidecar_detail(data)}
        except Exception as exc:
            return {
                "ok": False,
                "error_code": security_redaction.stable_error_code(exc),
                "error_summary": "sidecar_request_failed",
            }


def sidecar_status() -> dict:
    return XHSDownloaderSidecar().public_status()


def fetch_detail_with_sidecar(url: str, *, domain: str = "", run_id: str | None = None) -> dict:
    """Fetch one note detail through a configured sidecar and record health.

    The caller controls when this is used. If no sidecar URL is configured, no
    network call is made.
    """
    effective_run_id = run_id or str(uuid.uuid4())
    adapter = XHSDownloaderSidecar()
    result = adapter.fetch_detail(url)
    normalized = result.get("normalized") if isinstance(result.get("normalized"), dict) else {}
    ok = bool(result.get("ok") and (normalized.get("has_content") or normalized.get("has_metrics")))
    error_summary = result.get("error_summary") or result.get("error_code") or ""
    risk_login = (
        str(result.get("error_code") or "").lower() == "httpstatuserror"
        or any(
            marker in str(error_summary).lower()
            for marker in ("login", "sign-in", "cookie", "403", "401")
        )
    )
    record_health(CrawlerHealth(
        run_id=effective_run_id,
        adapter="xhs_downloader",
        domain=domain,
        status="ok" if ok else "failed",
        note_page_access_valid=ok,
        shortlink_canonicalized=ok,
        selector_valid=ok,
        risk_login_detected=risk_login,
        evidence_count=1 if ok else 0,
        error_code="" if ok else str(result.get("error_code") or "sidecar_empty_or_error"),
        error_summary="" if ok else str(error_summary)[:300],
        details={"sidecar": adapter.public_status(), "normalized": normalized if ok else {}},
    ))
    return {**result, "run_id": effective_run_id}
