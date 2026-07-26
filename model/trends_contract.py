"""Durable execution contract for the production XHS Trends worker.

The contract is intentionally provider-agnostic at the call boundary.  A
production run owns one fenced daily lease, and every XHS HTTP request must be
durably admitted before network I/O.  Unknown outcomes block subsequent calls
until an operator reviews the evidence; they are never retried automatically.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import secrets
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import hot_keywords


SERVICE_KEY = "market_timing"
PRODUCTION_DATABASE_ROLE = "noteai_xhs_trends"
MAX_PROVIDER_REQUESTS_PER_RUN = 34
MAX_PROVIDER_REQUESTS_PER_UTC_DAY = 34
MAX_KEYWORDS_PER_DOMAIN = 15
MAX_KEYWORDS_PER_RUN = 90
MAX_SNAPSHOT_BYTES = 1024 * 1024
LEASE_DURATION = timedelta(minutes=30)
REQUIRED_DOMAINS = tuple(hot_keywords.CORE_EVIDENCE_DOMAINS)
MIN_SNAPSHOT_KEYWORDS_PER_DOMAIN = 12
ALLOWED_ENDPOINTS = frozenset({
    "homefeed",
    "search_recommend",
    "search_notes",
})
ALLOWED_LOG_EVENTS = frozenset({
    "trends_run_started",
    "trends_run_succeeded",
    "trends_run_failed",
    "trends_run_skipped",
    "trends_health",
})


class TrendsContractError(RuntimeError):
    """Stable, secret-free Trends contract failure."""


class TrendsRunBusy(TrendsContractError):
    pass


class TrendsRunAlreadyCompleted(TrendsContractError):
    pass


class TrendsNeedsManualReview(TrendsContractError):
    pass


class TrendsDailyLimitReached(TrendsContractError):
    pass


@dataclass(frozen=True)
class TrendsRunLease:
    run_id: str
    bucket_key: str
    token: str
    token_hash: str
    fence: int
    expires_at: datetime


@dataclass(frozen=True)
class TrendsProviderAttempt:
    attempt_id: str
    run_id: str
    ordinal: int
    endpoint: str


_ACTIVE_LEASE: contextvars.ContextVar[TrendsRunLease | None] = (
    contextvars.ContextVar("noteai_trends_run_lease", default=None)
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clock(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return default


def _postgres() -> bool:
    return hot_keywords.primary_db.using_postgres()


@contextmanager
def _transaction() -> Iterator[Any]:
    conn = hot_keywords._conn()
    try:
        with conn:
            if not _postgres():
                conn.execute("BEGIN IMMEDIATE")
            yield conn
    finally:
        conn.close()


def _ensure_service_row(conn: Any, now: datetime) -> None:
    params = (SERVICE_KEY, "idle", _iso(now))
    if _postgres():
        return
    else:
        conn.execute(
            """
            INSERT OR IGNORE INTO xhs_trends_service_state(
                service_key,status,updated_at
            ) VALUES (?,?,?)
            """,
            params,
        )


def _lock_service_row(conn: Any) -> Any:
    if _postgres():
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext(?))",
            ("noteai:xhs:trends:singleton",),
        )
    suffix = " FOR UPDATE" if _postgres() else ""
    return conn.execute(
        "SELECT * FROM xhs_trends_service_state WHERE service_key=?" + suffix,
        (SERVICE_KEY,),
    ).fetchone()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _assert_lease_row(state: Any, lease: TrendsRunLease, now: datetime) -> None:
    expires_at = _clock(_row_value(state, "lease_expires_at"))
    if (
        _row_value(state, "status") != "running"
        or _row_value(state, "active_run_id") != lease.run_id
        or _row_value(state, "lease_token_hash") != lease.token_hash
        or int(_row_value(state, "lease_fence", -1) or -1) != lease.fence
    ):
        raise TrendsContractError("trends_run_fenced")
    if expires_at is None or expires_at <= now:
        raise TrendsContractError("trends_run_lease_expired")


def claim_daily_run(*, now: datetime | None = None) -> TrendsRunLease:
    """Claim the single UTC-day Trends run without provider or business writes."""
    hot_keywords.init_db()
    current = (now or _utc_now()).astimezone(timezone.utc)
    bucket_key = current.date().isoformat()
    token = secrets.token_urlsafe(32)
    token_hash = _token_hash(token)
    expires_at = current + LEASE_DURATION
    manual_error = ""
    already_completed = False
    run_id = ""
    fence = 0
    with _transaction() as conn:
        _ensure_service_row(conn, current)
        state = _lock_service_row(conn)
        if state is None:
            raise TrendsContractError("trends_service_state_missing")
        if bool(_row_value(state, "session_blocked")):
            raise TrendsNeedsManualReview("trends_session_blocked")
        if _row_value(state, "status") == "needs_manual":
            raise TrendsNeedsManualReview("trends_provider_outcome_unknown")

        active_run_id = str(_row_value(state, "active_run_id") or "")
        if active_run_id:
            active_expiry = _clock(_row_value(state, "lease_expires_at"))
            if active_expiry is None:
                raise TrendsNeedsManualReview("trends_invalid_active_lease")
            if active_expiry > current:
                raise TrendsRunBusy("trends_run_already_active")
            admitted = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM xhs_trends_provider_attempts
                WHERE run_id=? AND status='admitted'
                """,
                (active_run_id,),
            ).fetchone()
            if int(_row_value(admitted, "c", 0) or 0):
                conn.execute(
                    """
                    UPDATE xhs_trends_provider_attempts
                    SET status='outcome_unknown',completed_at=?,
                        error_code='provider_outcome_unknown'
                    WHERE run_id=? AND status='admitted'
                    """,
                    (_iso(current), active_run_id),
                )
                conn.execute(
                    """
                    UPDATE xhs_trends_runs
                    SET status='needs_manual',completed_at=?,
                        last_error_code='provider_outcome_unknown'
                    WHERE id=? AND status='running'
                    """,
                    (_iso(current), active_run_id),
                )
                conn.execute(
                    """
                    UPDATE xhs_trends_service_state
                    SET status='needs_manual',updated_at=?
                    WHERE service_key=?
                    """,
                    (_iso(current), SERVICE_KEY),
                )
                manual_error = "trends_provider_outcome_unknown"
            else:
                terminalized = conn.execute(
                    """
                    UPDATE xhs_trends_runs
                    SET status='failed',completed_at=?,
                        last_error_code='lease_expired_before_provider'
                    WHERE id=? AND status='running'
                    """,
                    (_iso(current), active_run_id),
                )
                if int(getattr(terminalized, "rowcount", 0) or 0) != 1:
                    raise TrendsContractError(
                        "trends_stale_run_terminalize_fenced"
                    )
                cleared = conn.execute(
                    """
                    UPDATE xhs_trends_service_state
                    SET active_run_id=NULL,status='idle',lease_token_hash=NULL,
                        lease_expires_at=NULL,updated_at=?
                    WHERE service_key=? AND active_run_id=?
                    """,
                    (_iso(current), SERVICE_KEY, active_run_id),
                )
                if int(getattr(cleared, "rowcount", 0) or 0) != 1:
                    raise TrendsContractError(
                        "trends_stale_service_clear_fenced"
                    )

        if not manual_error:
            existing = conn.execute(
                "SELECT status FROM xhs_trends_runs WHERE bucket_key=?",
                (bucket_key,),
            ).fetchone()
            if existing:
                already_completed = True
            else:
                fence = int(_row_value(state, "lease_fence", 0) or 0) + 1
                run_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO xhs_trends_runs(
                        id,bucket_key,status,lease_token_hash,lease_fence,
                        lease_expires_at,started_at,provider_attempt_count
                    ) VALUES (?,?,?,?,?,?,?,0)
                    """,
                    (
                        run_id,
                        bucket_key,
                        "running",
                        token_hash,
                        fence,
                        _iso(expires_at),
                        _iso(current),
                    ),
                )
                updated = conn.execute(
                    """
                    UPDATE xhs_trends_service_state
                    SET active_run_id=?,status='running',lease_token_hash=?,
                        lease_fence=?,lease_expires_at=?,updated_at=?
                    WHERE service_key=?
                    """,
                    (
                        run_id,
                        token_hash,
                        fence,
                        _iso(expires_at),
                        _iso(current),
                        SERVICE_KEY,
                    ),
                )
                if int(getattr(updated, "rowcount", 0) or 0) != 1:
                    raise TrendsContractError("trends_run_claim_failed")
    if manual_error:
        raise TrendsNeedsManualReview(manual_error)
    if already_completed:
        raise TrendsRunAlreadyCompleted("trends_daily_bucket_already_used")
    return TrendsRunLease(
        run_id=run_id,
        bucket_key=bucket_key,
        token=token,
        token_hash=token_hash,
        fence=fence,
        expires_at=expires_at,
    )


@contextmanager
def activate_run(lease: TrendsRunLease) -> Iterator[None]:
    token = _ACTIVE_LEASE.set(lease)
    try:
        yield
    finally:
        _ACTIVE_LEASE.reset(token)


def active_run() -> TrendsRunLease | None:
    return _ACTIVE_LEASE.get()


@contextmanager
def publish_transaction(lease: TrendsRunLease) -> Iterator[Any]:
    """Fence all Trends business writes and success publication together."""
    current = _utc_now()
    with _transaction() as conn:
        state = _lock_service_row(conn)
        _assert_lease_row(state, lease, current)
        if bool(_row_value(state, "session_blocked", False)):
            raise TrendsNeedsManualReview("trends_session_blocked")
        yield conn


def admit_provider_request(endpoint: str) -> TrendsProviderAttempt:
    lease = active_run()
    if lease is None:
        raise TrendsContractError("trends_provider_call_without_run")
    endpoint = str(endpoint or "")
    if endpoint not in ALLOWED_ENDPOINTS:
        raise TrendsContractError("trends_provider_endpoint_not_allowed")
    current = _utc_now()
    admitted_date = current.date().isoformat()
    with _transaction() as conn:
        state = _lock_service_row(conn)
        _assert_lease_row(state, lease, current)
        run_count_row = conn.execute(
            "SELECT provider_attempt_count FROM xhs_trends_runs WHERE id=?",
            (lease.run_id,),
        ).fetchone()
        run_count = int(_row_value(run_count_row, "provider_attempt_count", 0) or 0)
        if run_count >= MAX_PROVIDER_REQUESTS_PER_RUN:
            raise TrendsDailyLimitReached("trends_run_provider_limit")
        day_count_row = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM xhs_trends_provider_attempts
            WHERE admitted_date=?
            """,
            (admitted_date,),
        ).fetchone()
        if int(_row_value(day_count_row, "c", 0) or 0) >= MAX_PROVIDER_REQUESTS_PER_UTC_DAY:
            raise TrendsDailyLimitReached("trends_daily_provider_limit")
        attempt_id = str(uuid.uuid4())
        ordinal = run_count + 1
        conn.execute(
            """
            INSERT INTO xhs_trends_provider_attempts(
                id,run_id,ordinal,endpoint,status,admitted_at,admitted_date
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (
                attempt_id,
                lease.run_id,
                ordinal,
                endpoint,
                "admitted",
                _iso(current),
                admitted_date,
            ),
        )
        updated = conn.execute(
            """
            UPDATE xhs_trends_runs
            SET provider_attempt_count=provider_attempt_count+1
            WHERE id=? AND status='running'
              AND lease_token_hash=? AND lease_fence=?
              AND provider_attempt_count=?
            """,
            (lease.run_id, lease.token_hash, lease.fence, run_count),
        )
        if int(getattr(updated, "rowcount", 0) or 0) != 1:
            raise TrendsContractError("trends_provider_admission_fenced")
    return TrendsProviderAttempt(
        attempt_id=attempt_id,
        run_id=lease.run_id,
        ordinal=ordinal,
        endpoint=endpoint,
    )


def complete_provider_request(
    attempt: TrendsProviderAttempt,
    *,
    outcome: str,
    error_code: str = "",
) -> None:
    """Finalize one admission; `outcome_unknown` permanently blocks the run."""
    if outcome not in {"succeeded", "failed", "outcome_unknown"}:
        raise TrendsContractError("trends_provider_outcome_invalid")
    lease = active_run()
    if lease is None or attempt.run_id != lease.run_id:
        raise TrendsContractError("trends_provider_finalize_without_run")
    current = _utc_now()
    safe_error = str(error_code or "")[:64]
    with _transaction() as conn:
        state = _lock_service_row(conn)
        _assert_lease_row(state, lease, current)
        updated = conn.execute(
            """
            UPDATE xhs_trends_provider_attempts
            SET status=?,completed_at=?,error_code=?
            WHERE id=? AND run_id=? AND status='admitted'
            """,
            (
                outcome,
                _iso(current),
                safe_error,
                attempt.attempt_id,
                lease.run_id,
            ),
        )
        if int(getattr(updated, "rowcount", 0) or 0) != 1:
            raise TrendsContractError("trends_provider_finalize_fenced")
        if outcome == "outcome_unknown":
            conn.execute(
                """
                UPDATE xhs_trends_runs
                SET status='needs_manual',completed_at=?,
                    last_error_code='provider_outcome_unknown'
                WHERE id=? AND status='running'
                """,
                (_iso(current), lease.run_id),
            )
            conn.execute(
                """
                UPDATE xhs_trends_service_state
                SET status='needs_manual',updated_at=?
                WHERE service_key=? AND active_run_id=?
                """,
                (_iso(current), SERVICE_KEY, lease.run_id),
            )


def finish_run(
    lease: TrendsRunLease,
    *,
    succeeded: bool,
    error_code: str = "",
    snapshot_sha256: str = "",
    snapshot_size: int = 0,
    _connection=None,
) -> None:
    current = _utc_now()
    safe_error = str(error_code or "")[:64]
    if _connection is not None:
        _finish_run_in_connection(
            _connection,
            lease,
            current=current,
            succeeded=succeeded,
            safe_error=safe_error,
            snapshot_sha256=snapshot_sha256,
            snapshot_size=snapshot_size,
        )
        return
    with _transaction() as conn:
        _finish_run_in_connection(
            conn,
            lease,
            current=current,
            succeeded=succeeded,
            safe_error=safe_error,
            snapshot_sha256=snapshot_sha256,
            snapshot_size=snapshot_size,
        )


def _finish_run_in_connection(
    conn: Any,
    lease: TrendsRunLease,
    *,
    current: datetime,
    succeeded: bool,
    safe_error: str,
    snapshot_sha256: str,
    snapshot_size: int,
) -> None:
    state = _lock_service_row(conn)
    if _row_value(state, "status") == "needs_manual":
        raise TrendsNeedsManualReview("trends_provider_outcome_unknown")
    _assert_lease_row(state, lease, current)
    admitted = conn.execute(
        """
        SELECT COUNT(*) AS c FROM xhs_trends_provider_attempts
        WHERE run_id=? AND status='admitted'
        """,
        (lease.run_id,),
    ).fetchone()
    if int(_row_value(admitted, "c", 0) or 0):
        raise TrendsNeedsManualReview("trends_provider_outcome_unknown")
    if succeeded:
        evidence = conn.execute(
            """
            SELECT run_id,snapshot_sha256,snapshot_size,keyword_count,
                   domain_counts_json,payload_json
            FROM xhs_trends_snapshot_evidence
            WHERE run_id=? AND snapshot_sha256=? AND snapshot_size=?
            """,
            (lease.run_id, snapshot_sha256, int(snapshot_size or 0)),
        ).fetchone()
        if evidence is None:
            raise TrendsContractError("trends_snapshot_evidence_missing")
        try:
            evidence_raw = str(
                _row_value(evidence, "payload_json", "") or ""
            ).encode("utf-8")
            validated = validate_snapshot_payload(
                json.loads(evidence_raw.decode("utf-8")),
                evidence_raw,
            )
            raw_counts = _row_value(evidence, "domain_counts_json", {})
            stored_counts = (
                json.loads(raw_counts)
                if isinstance(raw_counts, str)
                else raw_counts
            )
            if (
                validated["sha256"]
                != _row_value(evidence, "snapshot_sha256")
                or validated["size"]
                != int(_row_value(evidence, "snapshot_size", 0) or 0)
                or validated["keyword_count"]
                != int(_row_value(evidence, "keyword_count", 0) or 0)
                or validated["domain_keyword_counts"] != stored_counts
            ):
                raise TrendsContractError(
                    "trends_snapshot_evidence_invalid"
                )
        except TrendsContractError:
            raise
        except Exception as exc:
            raise TrendsContractError(
                "trends_snapshot_evidence_invalid"
            ) from exc
    status = "succeeded" if succeeded else "failed"
    updated = conn.execute(
        """
        UPDATE xhs_trends_runs
        SET status=?,completed_at=?,last_error_code=?,
            snapshot_sha256=?,snapshot_size=?
        WHERE id=? AND status='running'
          AND lease_token_hash=? AND lease_fence=?
        """,
        (
            status,
            _iso(current),
            safe_error,
            snapshot_sha256,
            int(snapshot_size or 0),
            lease.run_id,
            lease.token_hash,
            lease.fence,
        ),
    )
    if int(getattr(updated, "rowcount", 0) or 0) != 1:
        raise TrendsContractError("trends_run_finalize_fenced")
    state_updated = conn.execute(
        """
        UPDATE xhs_trends_service_state
        SET active_run_id=NULL,status='idle',lease_token_hash=NULL,
            lease_expires_at=NULL,updated_at=?
        WHERE service_key=? AND active_run_id=?
          AND lease_token_hash=? AND lease_fence=?
        """,
        (
            _iso(current),
            SERVICE_KEY,
            lease.run_id,
            lease.token_hash,
            lease.fence,
        ),
    )
    if int(getattr(state_updated, "rowcount", 0) or 0) != 1:
        raise TrendsContractError("trends_service_finalize_fenced")


def provider_attempt_count(run_id: str) -> int:
    conn = hot_keywords._conn()
    try:
        row = conn.execute(
            """
            SELECT provider_attempt_count
            FROM xhs_trends_runs WHERE id=?
            """,
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    return max(0, int(_row_value(row, "provider_attempt_count", 0) or 0))


def assert_run_ready_to_publish(lease: TrendsRunLease) -> None:
    """Fail closed before snapshot publication if the run lost its fence."""
    current = _utc_now()
    conn = hot_keywords._conn()
    try:
        state = conn.execute(
            """
            SELECT active_run_id,status,lease_token_hash,lease_fence,
                   lease_expires_at
            FROM xhs_trends_service_state WHERE service_key=?
            """,
            (SERVICE_KEY,),
        ).fetchone()
        admitted = conn.execute(
            """
            SELECT COUNT(*) AS c FROM xhs_trends_provider_attempts
            WHERE run_id=? AND status='admitted'
            """,
            (lease.run_id,),
        ).fetchone()
    finally:
        conn.close()
    _assert_lease_row(state, lease, current)
    if int(_row_value(admitted, "c", 0) or 0):
        raise TrendsNeedsManualReview("trends_provider_outcome_unknown")


def acknowledge_provider_outcome_unknown() -> dict[str, Any]:
    """Provider-free operator acknowledgement; never retries the daily bucket."""
    current = _utc_now()
    with _transaction() as conn:
        state = _lock_service_row(conn)
        if state is None or _row_value(state, "status") != "needs_manual":
            raise TrendsContractError("trends_no_unknown_outcome_to_acknowledge")
        run_id = str(_row_value(state, "active_run_id") or "")
        conn.execute(
            """
            UPDATE xhs_trends_provider_attempts
            SET status='outcome_unknown',completed_at=?,
                error_code='provider_outcome_unknown'
            WHERE run_id=? AND status='admitted'
            """,
            (_iso(current), run_id),
        )
        conn.execute(
            """
            UPDATE xhs_trends_runs
            SET status='needs_manual',completed_at=COALESCE(completed_at,?),
                last_error_code='provider_outcome_unknown'
            WHERE id=?
            """,
            (_iso(current), run_id),
        )
        updated = conn.execute(
            """
            UPDATE xhs_trends_service_state
            SET active_run_id=NULL,status='idle',lease_token_hash=NULL,
                lease_expires_at=NULL,updated_at=?
            WHERE service_key=? AND active_run_id=? AND status='needs_manual'
            """,
            (_iso(current), SERVICE_KEY, run_id),
        )
        if int(getattr(updated, "rowcount", 0) or 0) != 1:
            raise TrendsContractError("trends_unknown_acknowledge_fenced")
    return {
        "acknowledged": True,
        "run_id": run_id,
        "provider_called": False,
        "retry_performed": False,
    }


def clear_session_block() -> dict[str, Any]:
    """Explicit provider-free operator action after credentials are replaced."""
    current = _utc_now()
    with _transaction() as conn:
        state = _lock_service_row(conn)
        if state is None or not bool(_row_value(state, "session_blocked")):
            raise TrendsContractError("trends_session_block_not_set")
        if _row_value(state, "status") != "idle":
            raise TrendsContractError("trends_session_block_clear_while_active")
        updated = conn.execute(
            """
            UPDATE xhs_trends_service_state
            SET session_blocked=?,session_block_reason='',
                session_blocked_at=NULL,updated_at=?
            WHERE service_key=? AND status='idle' AND session_blocked=?
            """,
            (False, _iso(current), SERVICE_KEY, True),
        )
        if int(getattr(updated, "rowcount", 0) or 0) != 1:
            raise TrendsContractError("trends_session_block_clear_fenced")
    return {
        "cleared": True,
        "provider_called": False,
        "retry_performed": False,
    }


def bound_keyword_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep at most 15 cleaned candidates for each of the six launch domains."""
    candidates: list[dict[str, Any]] = []
    for raw in rows or []:
        cleaned = hot_keywords.clean_scraped_keyword_row(dict(raw))
        domain = (
            str(cleaned.get("category") or cleaned.get("domain") or "")
            if cleaned else ""
        )
        if cleaned and domain in REQUIRED_DOMAINS:
            candidates.append(cleaned)
    domain_order = {domain: index for index, domain in enumerate(REQUIRED_DOMAINS)}
    candidates.sort(key=lambda row: (
        domain_order[str(row.get("category") or row.get("domain") or "")],
        -int(row.get("source_priority") or 0),
        -int(row.get("quality_score") or 0),
        -int(row.get("search_vol") or 0),
        str(row.get("keyword") or ""),
    ))
    bounded: list[dict[str, Any]] = []
    counts = {domain: 0 for domain in REQUIRED_DOMAINS}
    seen: set[tuple[str, str]] = set()
    for cleaned in candidates:
        domain = str(cleaned.get("category") or cleaned.get("domain") or "")
        identity = (domain, str(cleaned.get("keyword") or "").strip())
        if not identity[1] or identity in seen:
            continue
        if counts[domain] >= MAX_KEYWORDS_PER_DOMAIN:
            continue
        bounded.append(cleaned)
        seen.add(identity)
        counts[domain] += 1
    if len(bounded) > MAX_KEYWORDS_PER_RUN:
        raise TrendsContractError("trends_keyword_limit")
    return bounded


def build_publish_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build one deterministic 90-row real-first, labelled evidence pack."""
    published = bound_keyword_rows(rows)
    counts = {
        domain: sum(
            str(row.get("category") or row.get("domain") or "") == domain
            for row in published
        )
        for domain in REQUIRED_DOMAINS
    }
    seen = {
        (
            str(row.get("category") or row.get("domain") or ""),
            str(row.get("keyword") or "").strip(),
        )
        for row in published
    }
    for raw in hot_keywords.baseline_evidence_rows(
        REQUIRED_DOMAINS,
        min_per_domain=MAX_KEYWORDS_PER_DOMAIN,
        max_per_domain=MAX_KEYWORDS_PER_DOMAIN,
    ):
        cleaned = hot_keywords.clean_scraped_keyword_row(dict(raw))
        if not cleaned:
            continue
        domain = str(cleaned.get("category") or "")
        identity = (domain, str(cleaned.get("keyword") or "").strip())
        if (
            domain not in counts
            or not identity[1]
            or identity in seen
            or counts[domain] >= MAX_KEYWORDS_PER_DOMAIN
        ):
            continue
        published.append(cleaned)
        seen.add(identity)
        counts[domain] += 1
    if any(
        counts[domain] < MIN_SNAPSHOT_KEYWORDS_PER_DOMAIN
        for domain in REQUIRED_DOMAINS
    ):
        raise TrendsContractError("trends_publish_domain_missing")
    return bound_keyword_rows(published)


def snapshot_payload_from_rows(
    rows: list[dict[str, Any]],
    *,
    generated_at: datetime | None = None,
) -> tuple[dict[str, Any], bytes]:
    """Serialize only this run's bounded rows; historical DB rows cannot enter."""
    current = (generated_at or _utc_now()).astimezone(timezone.utc)
    captured_at = _iso(current)
    domains = {
        domain: {"captured_at": captured_at, "keywords": []}
        for domain in REQUIRED_DOMAINS
    }
    for row in bound_keyword_rows(rows):
        domain = str(row.get("category") or row.get("domain") or "")
        if domain not in domains:
            continue
        domains[domain]["keywords"].append({
            "keyword": str(row.get("keyword") or "").strip(),
            "search_vol": int(row.get("search_vol", 0) or 0),
            "trend_dir": int(row.get("trend_dir", 0) or 0),
            "source": str(row.get("source") or "unknown"),
            "category": domain,
            "sample_count": int(
                row.get("sample_count", row.get("count", 1)) or 1
            ),
            "quality_score": int(row.get("quality_score", 0) or 0),
            "evidence_level": str(row.get("evidence_level") or "weak"),
            "quality_reason": str(row.get("quality_reason") or ""),
            "captured_at": captured_at,
        })
    payload = {
        "schema_version": 1,
        "generated_at": captured_at,
        "freshness_max_hours": int(hot_keywords.FRESHNESS_MAX_HOURS),
        "domains": domains,
    }
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    validate_snapshot_payload(payload, raw)
    return payload, raw


def record_snapshot_evidence(
    connection: Any,
    lease: TrendsRunLease,
    payload: dict[str, Any],
    raw: bytes,
) -> dict[str, Any]:
    evidence = validate_snapshot_payload(payload, raw)
    connection.execute(
        """
        INSERT INTO xhs_trends_snapshot_evidence(
            run_id,schema_version,snapshot_sha256,snapshot_size,
            keyword_count,domain_counts_json,payload_json,created_at
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            lease.run_id,
            evidence["schema_version"],
            evidence["sha256"],
            evidence["size"],
            evidence["keyword_count"],
            json.dumps(
                evidence["domain_keyword_counts"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            raw.decode("utf-8"),
            _iso(_utc_now()),
        ),
    )
    return evidence


def validate_snapshot_payload(payload: dict[str, Any], raw: bytes) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise TrendsContractError("trends_snapshot_schema_invalid")
    if not raw or len(raw) > MAX_SNAPSHOT_BYTES:
        raise TrendsContractError("trends_snapshot_size_invalid")
    try:
        decoded_payload = json.loads(
            raw.decode("utf-8"),
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        raise TrendsContractError(
            "trends_snapshot_payload_invalid"
        ) from None
    if decoded_payload != payload:
        raise TrendsContractError("trends_snapshot_payload_mismatch")
    domains = payload.get("domains")
    if not isinstance(domains, dict) or set(domains) != set(REQUIRED_DOMAINS):
        raise TrendsContractError("trends_snapshot_domains_invalid")
    counts: dict[str, int] = {}
    for domain in REQUIRED_DOMAINS:
        bucket = domains.get(domain)
        keywords = bucket.get("keywords") if isinstance(bucket, dict) else None
        if (
            not isinstance(keywords, list)
            or len(keywords) < MIN_SNAPSHOT_KEYWORDS_PER_DOMAIN
        ):
            raise TrendsContractError("trends_snapshot_domain_missing")
        if len(keywords) > MAX_KEYWORDS_PER_DOMAIN:
            raise TrendsContractError("trends_snapshot_domain_limit")
        seen: set[str] = set()
        for item in keywords:
            if not isinstance(item, dict):
                raise TrendsContractError("trends_snapshot_keyword_invalid")
            keyword = str(item.get("keyword") or "").strip()
            if not keyword or keyword in seen:
                raise TrendsContractError("trends_snapshot_keyword_invalid")
            if str(item.get("category") or "").strip() != domain:
                raise TrendsContractError("trends_snapshot_keyword_domain")
            seen.add(keyword)
        counts[domain] = len(keywords)
    total = sum(counts.values())
    if total > MAX_KEYWORDS_PER_RUN:
        raise TrendsContractError("trends_snapshot_keyword_limit")
    return {
        "schema_version": 1,
        "domains": list(REQUIRED_DOMAINS),
        "domain_keyword_counts": counts,
        "keyword_count": total,
        "size": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def session_safety_status() -> dict[str, Any]:
    """Read the dedicated Trends session stop without touching settings."""
    conn = hot_keywords._conn()
    try:
        row = conn.execute(
            """
            SELECT session_blocked,session_block_reason,session_blocked_at
            FROM xhs_trends_service_state WHERE service_key=?
            """,
            (SERVICE_KEY,),
        ).fetchone()
    finally:
        conn.close()
    blocked = bool(_row_value(row, "session_blocked", False))
    reason = str(_row_value(row, "session_block_reason", "") or "")
    return {
        "session_blocked": blocked,
        "reason_code": reason if blocked else "",
        "blocked_at": (
            str(_row_value(row, "session_blocked_at", "") or "")
            if blocked else ""
        ),
    }


def mark_session_blocked() -> None:
    lease = active_run()
    if lease is None:
        raise TrendsContractError("trends_session_block_without_run")
    current = _utc_now()
    with _transaction() as conn:
        state = _lock_service_row(conn)
        _assert_lease_row(state, lease, current)
        conn.execute(
            """
            UPDATE xhs_trends_service_state
            SET session_blocked=?,
                session_block_reason='server_session_logged_out',
                session_blocked_at=?,updated_at=?
            WHERE service_key=?
            """,
            (True, _iso(current), _iso(current), SERVICE_KEY),
        )


def readiness_status(*, now: datetime | None = None) -> dict[str, Any]:
    """Provider-free, read-only schema/lease/integrity health."""
    current = (now or _utc_now()).astimezone(timezone.utc)
    if not _postgres() and not hot_keywords.DB_PATH.is_file():
        return {
            "status": "not_ready",
            "reason": "trends_contract_unavailable",
            "provider_called": False,
        }
    conn = hot_keywords._conn()
    try:
        role_ok = True
        if _postgres():
            role_row = conn.execute("SELECT current_user AS role").fetchone()
            role_ok = (
                _row_value(role_row, "role") == PRODUCTION_DATABASE_ROLE
            )
        conn.execute(
            """
            SELECT id,bucket_key,status,lease_token_hash,lease_fence,
                   lease_expires_at,provider_attempt_count
            FROM xhs_trends_runs LIMIT 0
            """
        )
        conn.execute(
            """
            SELECT id,run_id,ordinal,endpoint,status,admitted_at,admitted_date
            FROM xhs_trends_provider_attempts LIMIT 0
            """
        )
        conn.execute(
            """
            SELECT run_id,schema_version,snapshot_sha256,snapshot_size,
                   keyword_count,domain_counts_json,payload_json,created_at
            FROM xhs_trends_snapshot_evidence LIMIT 0
            """
        )
        state = conn.execute(
            "SELECT * FROM xhs_trends_service_state WHERE service_key=?",
            (SERVICE_KEY,),
        ).fetchone()
        admitted = conn.execute(
            """
            SELECT COUNT(*) AS c FROM xhs_trends_provider_attempts
            WHERE status='admitted'
            """
        ).fetchone()
        unknown = conn.execute(
            """
            SELECT COUNT(*) AS c FROM xhs_trends_provider_attempts
            WHERE status='outcome_unknown'
            """
        ).fetchone()
        unlinked = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM xhs_trends_provider_attempts a
            LEFT JOIN xhs_trends_service_state s
              ON s.service_key=? AND s.active_run_id=a.run_id
            WHERE a.status='admitted' AND s.active_run_id IS NULL
            """,
            (SERVICE_KEY,),
        ).fetchone()
        latest_snapshot = conn.execute(
            """
            SELECT r.snapshot_sha256 AS run_snapshot_sha256,
                   r.snapshot_size AS run_snapshot_size,
                   r.provider_attempt_count,
                   e.snapshot_sha256 AS evidence_snapshot_sha256,
                   e.snapshot_size AS evidence_snapshot_size,
                   e.keyword_count,e.domain_counts_json,e.payload_json,
                   (
                       SELECT COUNT(*)
                       FROM xhs_trends_provider_attempts a
                       WHERE a.run_id=r.id
                   ) AS attempt_count,
                   (
                       SELECT COUNT(*)
                       FROM xhs_trends_provider_attempts a
                       WHERE a.run_id=r.id AND a.status='succeeded'
                   ) AS succeeded_attempt_count
            FROM xhs_trends_runs r
            LEFT JOIN xhs_trends_snapshot_evidence e ON e.run_id=r.id
            WHERE r.status='succeeded'
            ORDER BY r.completed_at DESC,r.id DESC
            LIMIT 1
            """
        ).fetchone()
    except Exception:
        return {
            "status": "not_ready",
            "reason": "trends_contract_unavailable",
            "provider_called": False,
        }
    finally:
        conn.close()
    reason = ""
    if bool(_row_value(state, "session_blocked", False)):
        reason = "trends_session_blocked"
    elif state is None:
        reason = "trends_service_state_missing"
    elif not role_ok:
        reason = "trends_database_role_mismatch"
    elif _row_value(state, "status") == "needs_manual":
        reason = "trends_provider_outcome_unknown"
    elif int(_row_value(unlinked, "c", 0) or 0):
        reason = "trends_provider_attempt_unlinked"
    elif _row_value(state, "status") == "running":
        expiry = _clock(_row_value(state, "lease_expires_at"))
        if expiry is None or expiry <= current:
            reason = "trends_run_lease_stale"
    if not reason and latest_snapshot is not None:
        try:
            snapshot_raw = str(
                _row_value(latest_snapshot, "payload_json", "") or ""
            ).encode("utf-8")
            snapshot_payload = json.loads(snapshot_raw.decode("utf-8"))
            snapshot_evidence = validate_snapshot_payload(
                snapshot_payload,
                snapshot_raw,
            )
            raw_domain_counts = _row_value(
                latest_snapshot,
                "domain_counts_json",
                {},
            )
            if isinstance(raw_domain_counts, str):
                stored_domain_counts = json.loads(raw_domain_counts)
            elif isinstance(raw_domain_counts, dict):
                stored_domain_counts = raw_domain_counts
            else:
                stored_domain_counts = {}
            if (
                snapshot_evidence["sha256"]
                != _row_value(
                    latest_snapshot,
                    "evidence_snapshot_sha256",
                )
                or snapshot_evidence["size"]
                != int(
                    _row_value(
                        latest_snapshot,
                        "evidence_snapshot_size",
                        0,
                    ) or 0
                )
                or snapshot_evidence["keyword_count"]
                != int(
                    _row_value(latest_snapshot, "keyword_count", 0) or 0
                )
                or snapshot_evidence["domain_keyword_counts"]
                != stored_domain_counts
                or _row_value(
                    latest_snapshot,
                    "run_snapshot_sha256",
                )
                != _row_value(
                    latest_snapshot,
                    "evidence_snapshot_sha256",
                )
                or int(
                    _row_value(
                        latest_snapshot,
                        "run_snapshot_size",
                        0,
                    ) or 0
                )
                != int(
                    _row_value(
                        latest_snapshot,
                        "evidence_snapshot_size",
                        0,
                    ) or 0
                )
                or int(
                    _row_value(
                        latest_snapshot,
                        "provider_attempt_count",
                        0,
                    ) or 0
                )
                != int(
                    _row_value(latest_snapshot, "attempt_count", 0) or 0
                )
                or int(
                    _row_value(latest_snapshot, "attempt_count", 0) or 0
                )
                != int(
                    _row_value(
                        latest_snapshot,
                        "succeeded_attempt_count",
                        0,
                    ) or 0
                )
                or int(
                    _row_value(latest_snapshot, "attempt_count", 0) or 0
                )
                <= 0
            ):
                reason = "trends_snapshot_evidence_invalid"
        except Exception:
            reason = "trends_snapshot_evidence_invalid"
    return {
        "status": "not_ready" if reason else "ready",
        "reason": reason,
        "provider_called": False,
        "active_provider_attempts": int(_row_value(admitted, "c", 0) or 0),
        "unknown_provider_attempts": int(_row_value(unknown, "c", 0) or 0),
        "unlinked_provider_attempts": int(_row_value(unlinked, "c", 0) or 0),
    }


def structured_event(event: str, **fields: Any) -> str:
    """Serialize only the fixed operational shape used by Trends logs."""
    if event not in ALLOWED_LOG_EVENTS:
        raise TrendsContractError("trends_log_event_not_allowed")
    allowed = {
        "event": str(event or "")[:64],
        "run_id": str(fields.get("run_id") or "")[:64],
        "bucket_key": str(fields.get("bucket_key") or "")[:16],
        "status": str(fields.get("status") or "")[:32],
        "error_code": str(fields.get("error_code") or "")[:64],
        "provider_calls": max(0, int(fields.get("provider_calls") or 0)),
        "keyword_count": max(0, int(fields.get("keyword_count") or 0)),
        "snapshot_size": max(0, int(fields.get("snapshot_size") or 0)),
    }
    return json.dumps(allowed, ensure_ascii=False, sort_keys=True)
