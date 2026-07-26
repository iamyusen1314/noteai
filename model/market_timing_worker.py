#!/usr/bin/env python3
"""Independent market timing data pipeline worker.

Run this as a separate cloud worker/cron service. It tries public discovery,
then guarantees a fresh labelled industry evidence pack before exporting a JSON
snapshot that the API can consume through NOTEAI_MARKET_TIMING_SNAPSHOT_URL.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx

import trends_contract
from hot_keywords import (
    BASELINE_EVIDENCE_SOURCE,
    db_status,
    ensure_daily_evidence_pack,
    init_db,
    upsert_keywords,
    write_keyword_snapshot,
)
from scheduler_a import (
    discovery_diagnostics_for_results,
    scrape_once,
    scrape_once_http,
    search_circuit_context,
    session_state_summary,
)
from xhs_acquisition import (
    challenge_cooldown_status,
    collection_safety_status,
    freshness_overview,
    init_db as init_xhs_acquisition_db,
    mark_server_session_logged_out,
    record_scrape_freshness,
    xhs_freshness_required,
)


DEFAULT_SNAPSHOT_PATH = Path(__file__).parent / "data" / "market_timing_snapshot.json"


def _truthy_env(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _xhs_missing_message(xhs_freshness: dict) -> str:
    overview = xhs_freshness.get("overview") or {}
    missing = ", ".join(overview.get("missing_domains") or [])
    if missing:
        return f"XHS_FRESH_EVIDENCE_UNAVAILABLE: missing fresh XHS evidence for {missing}"
    return "XHS_FRESH_EVIDENCE_UNAVAILABLE: fresh XHS evidence gate not satisfied"


def _public_xhs_freshness(value):
    """Deep-copy freshness output while keeping ledger-only de-dup keys private."""
    if isinstance(value, dict):
        return {
            key: _public_xhs_freshness(item)
            for key, item in value.items()
            if key != "evidence_keys"
        }
    if isinstance(value, list):
        return [_public_xhs_freshness(item) for item in value]
    return value


def _upload_snapshot(payload: dict | bytes, url: str) -> None:
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("NOTEAI_MARKET_TIMING_SNAPSHOT_UPLOAD_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    timeout = float(os.environ.get("NOTEAI_MARKET_TIMING_UPLOAD_TIMEOUT", "20") or 20)
    content = (
        payload
        if isinstance(payload, bytes)
        else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    )
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.put(url, content=content, headers=headers)
        resp.raise_for_status()


async def _scrape_selected_adapter(configured_adapter: str):
    """Route one scrape without ever falling back from direct HTTP to browser."""
    from spider_xhs_http import XHSAdapterError, collection_route, collection_route_suspended

    route = collection_route(configured_adapter)
    if collection_route_suspended(route):
        raise XHSAdapterError("collection_suspended")
    if route == "direct":
        return await scrape_once_http()
    return await scrape_once()


async def _run_once_body(
    snapshot_path: Path,
    upload_url: str = "",
    hours: int = 30,
    hard_fail_on_xhs_missing: bool | None = None,
) -> dict:
    init_db()
    init_xhs_acquisition_db()
    active_lease = trends_contract.active_run()
    run_id = active_lease.run_id if active_lease is not None else str(uuid.uuid4())
    scrape_error = ""
    session_status = session_state_summary()
    configured_adapter = os.environ.get(
        "NOTEAI_XHS_ACQUISITION_ADAPTER", ""
    ).strip()
    from spider_xhs_http import XHSAdapterError, collection_route

    route_error = ""
    try:
        collection_mode = collection_route(configured_adapter)
    except XHSAdapterError as exc:
        collection_mode = "blocked"
        route_error = exc.code
    operator_suspended = False
    if collection_mode != "blocked":
        from spider_xhs_http import collection_route_suspended

        operator_suspended = collection_route_suspended(collection_mode)
    safety_status = collection_safety_status()
    blocked_reason = ""
    if route_error:
        blocked_reason = route_error
    elif operator_suspended:
        blocked_reason = "collection_suspended"
    elif safety_status.get("session_blocked"):
        blocked_reason = str(safety_status.get("reason_code") or "")
    if blocked_reason:
        keywords = []
        scrape_error = blocked_reason
        discovery_diagnostics = discovery_diagnostics_for_results(
            [],
            extra_error_code=blocked_reason,
        )
    else:
        challenge_cooldown = challenge_cooldown_status()
        circuit_state = "cooldown" if challenge_cooldown.get("active") else "closed"
        try:
            with search_circuit_context({"state": circuit_state}):
                scrape_result = await _scrape_selected_adapter(configured_adapter)
            keywords = list(scrape_result)
            discovery_diagnostics = discovery_diagnostics_for_results(
                keywords,
                getattr(scrape_result, "diagnostics", None),
            )
        except Exception:
            keywords = []
            scrape_error = "scrape_once_failed"
            discovery_diagnostics = discovery_diagnostics_for_results(
                [],
                extra_error_code="scrape_once_failed",
            )
    if trends_contract.active_run() is not None:
        keywords = trends_contract.bound_keyword_rows(list(keywords))
    diagnostic_codes = set(
        discovery_diagnostics.get("diagnostic_error_codes") or []
    )
    if "server_session_logged_out" in diagnostic_codes:
        mark_server_session_logged_out()
        blocked_reason = "server_session_logged_out"
    print(json.dumps({
        "event": "xhs_discovery_diagnostics",
        "run_id": run_id,
        "diagnostics": discovery_diagnostics,
    }, ensure_ascii=False, sort_keys=True), flush=True)
    if active_lease is not None:
        with trends_contract.publish_transaction(active_lease) as connection:
            attempt_stats = connection.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN status='succeeded' THEN 1 ELSE 0 END)
                           AS succeeded,
                       (
                           SELECT provider_attempt_count
                           FROM xhs_trends_runs WHERE id=?
                       ) AS ledger_count
                FROM xhs_trends_provider_attempts
                WHERE run_id=?
                """,
                (run_id, run_id),
            ).fetchone()
            attempt_total = int(attempt_stats["total"] or 0)
            attempt_succeeded = int(attempt_stats["succeeded"] or 0)
            attempt_ledger_count = int(
                attempt_stats["ledger_count"] or 0
            )
            if (
                attempt_total <= 0
                or attempt_succeeded != attempt_total
                or attempt_ledger_count != attempt_total
                or attempt_total > trends_contract.MAX_PROVIDER_REQUESTS_PER_RUN
            ):
                raise trends_contract.TrendsContractError(
                    "trends_provider_attempt_evidence_incomplete"
                )
            xhs_freshness_internal = record_scrape_freshness(
                keywords,
                run_id=run_id,
                session_status=session_status,
                scrape_error=scrape_error,
                discovery_diagnostics=discovery_diagnostics,
                adapter="spider_xhs_http",
                _connection=connection,
            )
            current_domain_counts = dict(
                xhs_freshness_internal.get("latest_run_domain_counts") or {}
            )
            current_source_health = dict(
                xhs_freshness_internal.get(
                    "latest_run_domain_source_health"
                ) or {}
            )
            xhs_ok = bool(
                not blocked_reason
                and (xhs_freshness_internal.get("overview") or {}).get("ok")
                and all(
                    int(current_domain_counts.get(domain, 0) or 0)
                    >= trends_contract.MIN_SNAPSHOT_KEYWORDS_PER_DOMAIN
                    for domain in trends_contract.REQUIRED_DOMAINS
                )
                and all(
                    bool((current_source_health.get(domain) or {}).get("ok"))
                    for domain in trends_contract.REQUIRED_DOMAINS
                )
            )
            if not xhs_ok:
                raise trends_contract.TrendsContractError(
                    "trends_current_run_xhs_evidence_incomplete"
                )
            publish_rows = trends_contract.build_publish_rows(keywords)
            upsert_keywords(publish_rows, _connection=connection)
            baseline_count = sum(
                str(row.get("source") or "")
                == BASELINE_EVIDENCE_SOURCE
                for row in publish_rows
            )
            baseline_result = {
                "enabled": True,
                "source": BASELINE_EVIDENCE_SOURCE,
                "generated": baseline_count,
                "domains": list(trends_contract.REQUIRED_DOMAINS),
                "reason": "bounded real-first snapshot completion",
            }
            payload, raw_snapshot = trends_contract.snapshot_payload_from_rows(
                publish_rows,
            )
            snapshot_evidence = trends_contract.record_snapshot_evidence(
                connection,
                active_lease,
                payload,
                raw_snapshot,
            )
            provider_count_row = connection.execute(
                """
                SELECT provider_attempt_count
                FROM xhs_trends_runs WHERE id=?
                """,
                (run_id,),
            ).fetchone()
            provider_calls = int(
                provider_count_row["provider_attempt_count"] or 0
            )
            trends_contract.finish_run(
                active_lease,
                succeeded=True,
                snapshot_sha256=snapshot_evidence["sha256"],
                snapshot_size=snapshot_evidence["size"],
                _connection=connection,
            )
        return {
            "keywords": len(keywords),
            "scrape_error": scrape_error,
            "discovery_diagnostics": discovery_diagnostics,
            "session_status": session_status,
            "xhs_freshness": _public_xhs_freshness(
                xhs_freshness_internal
            ),
            "xhs_freshness_overview": (
                xhs_freshness_internal.get("overview") or {}
            ),
            "xhs_freshness_required": True,
            "xhs_freshness_ok": True,
            "latest_run_evidence_count": int(
                xhs_freshness_internal.get(
                    "latest_run_evidence_count", 0
                ) or 0
            ),
            "xhs_freshness_warning": "",
            "baseline": baseline_result,
            "evidence_mode": "real_xhs",
            "snapshot_path": "",
            "snapshot_written": False,
            "domains": sorted((payload.get("domains") or {}).keys()),
            "snapshot_evidence": snapshot_evidence,
            "provider_calls": provider_calls,
            "status": {"trends_contract": "succeeded"},
        }
    if keywords:
        upsert_keywords(keywords)
    xhs_freshness_internal = record_scrape_freshness(
        keywords,
        run_id=run_id,
        session_status=session_status,
        scrape_error=scrape_error,
        discovery_diagnostics=discovery_diagnostics,
        adapter=("spider_xhs_http" if collection_mode == "direct" else "scheduler_a"),
    )
    xhs_freshness_public = _public_xhs_freshness(xhs_freshness_internal)
    xhs_required = xhs_freshness_required()
    xhs_ok = bool((xhs_freshness_internal.get("overview") or {}).get("ok"))
    latest_run_evidence_count = max(
        0,
        int(xhs_freshness_internal.get("latest_run_evidence_count") or 0),
    )
    latest_run_failed = bool(
        latest_run_evidence_count == 0
        or blocked_reason
        or "server_session_logged_out" in diagnostic_codes
    )
    xhs_warning = (
        _xhs_missing_message(xhs_freshness_internal)
        if (xhs_required and not xhs_ok) or latest_run_failed
        else ""
    )
    if xhs_warning and not keywords:
        if blocked_reason == "collection_suspended":
            reason = "XHS_COLLECTION_SUSPENDED: operator suspension is active"
        elif blocked_reason == "runtime_role_not_allowed":
            reason = "XHS_RUNTIME_ROLE_BLOCKED: direct collection requires xhs-http"
        elif blocked_reason == "adapter_not_selected":
            reason = "XHS_ADAPTER_BLOCKED: xhs-http requires spider_xhs_http"
        elif blocked_reason == "server_session_logged_out":
            reason = "XHS_SESSION_LOGGED_OUT: operator re-login is required"
        elif not session_status.get("configured"):
            reason = "XHS_SESSION_REQUIRED: no XHS login session is configured"
        elif not session_status.get("auth_cookie_present"):
            reason = "XHS_SESSION_REQUIRED: XHS authentication cookies are missing"
        elif session_status.get("auth_cookie_expired"):
            reason = "XHS_SESSION_EXPIRED: XHS login session has expired; re-login required"
        else:
            reason = "XHS_SESSION_OR_ACCESS_UNAVAILABLE: configured session returned 0 fresh evidence"
        xhs_warning = f"{xhs_warning}; {reason}"
    if trends_contract.active_run() is not None:
        baseline_result = ensure_daily_evidence_pack(
            max_per_domain=trends_contract.MAX_KEYWORDS_PER_DOMAIN,
            target_total_per_domain=trends_contract.MAX_KEYWORDS_PER_DOMAIN,
        )
        payload = write_keyword_snapshot(
            snapshot_path,
            hours=hours,
            max_per_domain=trends_contract.MAX_KEYWORDS_PER_DOMAIN,
            domains=trends_contract.REQUIRED_DOMAINS,
        )
    else:
        baseline_result = ensure_daily_evidence_pack()
        payload = write_keyword_snapshot(snapshot_path, hours=hours)
    if not (payload.get("domains") or {}):
        raise RuntimeError("market timing snapshot contains 0 domains")
    should_hard_fail = (
        _truthy_env("NOTEAI_XHS_FRESHNESS_HARD_FAIL")
        if hard_fail_on_xhs_missing is None
        else bool(hard_fail_on_xhs_missing)
    )
    if xhs_warning and should_hard_fail:
        raise RuntimeError(xhs_warning)
    if upload_url:
        _upload_snapshot(payload, upload_url)
    evidence_mode = (
        "real_xhs"
        if xhs_ok and not latest_run_failed
        else "baseline_or_partial"
    )
    return {
        "keywords": len(keywords),
        "scrape_error": scrape_error,
        "discovery_diagnostics": discovery_diagnostics,
        "session_status": session_status,
        "xhs_freshness": xhs_freshness_public,
        "xhs_freshness_overview": freshness_overview(),
        "xhs_freshness_required": xhs_required,
        "xhs_freshness_ok": xhs_ok,
        "latest_run_evidence_count": latest_run_evidence_count,
        "xhs_freshness_warning": xhs_warning,
        "baseline": baseline_result,
        "evidence_mode": evidence_mode,
        "snapshot_path": str(snapshot_path),
        "domains": sorted((payload.get("domains") or {}).keys()),
        "status": db_status(),
    }


def _production_trends_route() -> tuple[str, str]:
    """Return `(mode, reason)` without initializing a database or adapter."""
    if os.environ.get("NOTEAI_RUNTIME_ROLE", "").strip() != "xhs-http":
        return "local", ""
    if os.environ.get("NOTEAI_XHS_SERVICE", "").strip() != "trends":
        return "blocked", "xhs_service_role_not_allowed"
    from spider_xhs_http import XHSAdapterError, collection_route, collection_route_suspended

    try:
        route = collection_route(
            os.environ.get("NOTEAI_XHS_ACQUISITION_ADAPTER", "").strip()
        )
    except XHSAdapterError as exc:
        return "blocked", exc.code
    if route != "direct":
        return "blocked", "runtime_role_not_allowed"
    if collection_route_suspended(route):
        return "suspended", "collection_suspended"
    return "direct", ""


async def run_once(
    snapshot_path: Path,
    upload_url: str = "",
    hours: int = 30,
    hard_fail_on_xhs_missing: bool | None = None,
) -> dict:
    """Run one local cycle or one durable production UTC-day cycle."""
    mode, reason = _production_trends_route()
    if mode == "suspended":
        return {
            "skipped": True,
            "reason": reason,
            "provider_called": False,
            "database_writes": 0,
            "snapshot_written": False,
        }
    if mode == "blocked":
        raise trends_contract.TrendsContractError(reason)
    if mode != "direct":
        return await _run_once_body(
            snapshot_path,
            upload_url=upload_url,
            hours=hours,
            hard_fail_on_xhs_missing=hard_fail_on_xhs_missing,
        )
    if upload_url:
        raise trends_contract.TrendsContractError(
            "trends_snapshot_upload_not_allowed"
        )

    try:
        lease = trends_contract.claim_daily_run()
    except (
        trends_contract.TrendsRunBusy,
        trends_contract.TrendsRunAlreadyCompleted,
    ) as exc:
        print(trends_contract.structured_event(
            "trends_run_skipped",
            status="skipped",
            error_code=str(exc),
        ), flush=True)
        return {
            "skipped": True,
            "reason": str(exc),
            "provider_called": False,
            "database_writes": 0,
            "snapshot_written": False,
        }
    print(trends_contract.structured_event(
        "trends_run_started",
        run_id=lease.run_id,
        bucket_key=lease.bucket_key,
        status="running",
    ), flush=True)
    try:
        with trends_contract.activate_run(lease):
            result = await _run_once_body(
                snapshot_path,
                upload_url="",
                hours=hours,
                hard_fail_on_xhs_missing=True,
            )
        provider_calls = int(result.get("provider_calls") or 0)
        snapshot_evidence = dict(result.get("snapshot_evidence") or {})
    except Exception as exc:
        error_code = (
            str(exc)
            if isinstance(exc, trends_contract.TrendsContractError)
            else "market_timing_worker_failed"
        )
        try:
            trends_contract.finish_run(
                lease,
                succeeded=False,
                error_code=error_code,
            )
        except trends_contract.TrendsNeedsManualReview:
            error_code = "trends_provider_outcome_unknown"
        print(trends_contract.structured_event(
            "trends_run_failed",
            run_id=lease.run_id,
            bucket_key=lease.bucket_key,
            status="failed",
            error_code=error_code,
            provider_calls=trends_contract.provider_attempt_count(lease.run_id),
        ), file=sys.stderr, flush=True)
        raise
    result.update({
        "run_id": lease.run_id,
        "bucket_key": lease.bucket_key,
        "provider_calls": provider_calls,
        "snapshot_evidence": snapshot_evidence,
    })
    print(trends_contract.structured_event(
        "trends_run_succeeded",
        run_id=lease.run_id,
        bucket_key=lease.bucket_key,
        status="succeeded",
        provider_calls=provider_calls,
        keyword_count=snapshot_evidence["keyword_count"],
        snapshot_size=snapshot_evidence["size"],
    ), flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run NoteAI market timing cloud pipeline worker")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Run one scrape/export cycle and exit")
    mode.add_argument("--daemon", action="store_true", help="Run forever at the configured interval")
    mode.add_argument(
        "--healthcheck",
        action="store_true",
        help="Check the Trends role/schema without loading an adapter or provider.",
    )
    mode.add_argument(
        "--acknowledge-unknown",
        action="store_true",
        help="Acknowledge a stale unknown provider outcome without retrying it.",
    )
    mode.add_argument(
        "--clear-session-block",
        action="store_true",
        help="Clear the dedicated session stop after operator credential repair.",
    )
    parser.add_argument("--interval", type=int, default=int(os.environ.get("NOTEAI_MARKET_TIMING_WORKER_INTERVAL_MINUTES", "60") or 60))
    parser.add_argument("--snapshot-path", default=os.environ.get("NOTEAI_MARKET_TIMING_SNAPSHOT_PATH", str(DEFAULT_SNAPSHOT_PATH)))
    parser.add_argument("--upload-url", default=os.environ.get("NOTEAI_MARKET_TIMING_SNAPSHOT_UPLOAD_URL", ""))
    parser.add_argument("--hours", type=int, default=int(os.environ.get("NOTEAI_HOT_KEYWORD_FRESH_HOURS", "30") or 30))
    parser.add_argument(
        "--hard-fail-on-xhs-missing",
        action="store_true",
        default=_truthy_env("NOTEAI_XHS_FRESHNESS_HARD_FAIL"),
        help="Exit non-zero if real XHS freshness is missing after writing the local snapshot.",
    )
    args = parser.parse_args()

    if args.healthcheck:
        result = trends_contract.readiness_status()
        print(trends_contract.structured_event(
            "trends_health",
            status=result.get("status"),
            error_code=result.get("reason"),
        ), flush=True)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
        return 0 if result.get("status") == "ready" else 1
    if args.acknowledge_unknown:
        result = trends_contract.acknowledge_provider_outcome_unknown()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
        return 0
    if args.clear_session_block:
        result = trends_contract.clear_session_block()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
        return 0

    if args.interval < 60 or args.interval > 1440:
        parser.error("--interval must be 60..1440")
    if args.hours < 1 or args.hours > 168:
        parser.error("--hours must be 1..168")
    snapshot_path = Path(args.snapshot_path)
    if not args.once and not args.daemon:
        args.once = True

    while True:
        try:
            result = asyncio.run(run_once(
                snapshot_path,
                upload_url=args.upload_url,
                hours=args.hours,
                hard_fail_on_xhs_missing=args.hard_fail_on_xhs_missing,
            ))
            print(json.dumps({"ok": True, **result}, ensure_ascii=False), flush=True)
        except Exception as exc:
            error_code = (
                "xhs_fresh_evidence_unavailable"
                if "XHS_FRESH_EVIDENCE_UNAVAILABLE" in str(exc)
                else "market_timing_worker_failed"
            )
            print(json.dumps({
                "ok": False,
                "error": error_code,
                "error_code": error_code,
                "exception_type": type(exc).__name__,
            }, ensure_ascii=False), file=sys.stderr, flush=True)
            return 1
        if args.once:
            return 0
        time.sleep(max(1, int(args.interval)) * 60)


if __name__ == "__main__":
    raise SystemExit(main())
