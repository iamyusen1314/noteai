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

from hot_keywords import (
    db_status,
    ensure_daily_evidence_pack,
    init_db,
    upsert_keywords,
    write_keyword_snapshot,
)
from scheduler_a import (
    discovery_diagnostics_for_results,
    scrape_once,
    search_circuit_context,
    session_state_summary,
)
from xhs_acquisition import (
    challenge_cooldown_status,
    freshness_overview,
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


def _upload_snapshot(payload: dict, url: str) -> None:
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("NOTEAI_MARKET_TIMING_SNAPSHOT_UPLOAD_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    timeout = float(os.environ.get("NOTEAI_MARKET_TIMING_UPLOAD_TIMEOUT", "20") or 20)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.put(url, content=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers)
        resp.raise_for_status()


async def run_once(
    snapshot_path: Path,
    upload_url: str = "",
    hours: int = 30,
    hard_fail_on_xhs_missing: bool | None = None,
) -> dict:
    init_db()
    run_id = str(uuid.uuid4())
    scrape_error = ""
    session_status = session_state_summary()
    challenge_cooldown = challenge_cooldown_status()
    circuit_state = "cooldown" if challenge_cooldown.get("active") else "closed"
    try:
        with search_circuit_context({"state": circuit_state}):
            scrape_result = await scrape_once()
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
    print(json.dumps({
        "event": "xhs_discovery_diagnostics",
        "run_id": run_id,
        "diagnostics": discovery_diagnostics,
    }, ensure_ascii=False, sort_keys=True), flush=True)
    if keywords:
        upsert_keywords(keywords)
    xhs_freshness_internal = record_scrape_freshness(
        keywords,
        run_id=run_id,
        session_status=session_status,
        scrape_error=scrape_error,
        discovery_diagnostics=discovery_diagnostics,
    )
    xhs_freshness_public = _public_xhs_freshness(xhs_freshness_internal)
    xhs_required = xhs_freshness_required()
    xhs_ok = bool((xhs_freshness_internal.get("overview") or {}).get("ok"))
    xhs_warning = _xhs_missing_message(xhs_freshness_internal) if xhs_required and not xhs_ok else ""
    if xhs_warning and not keywords:
        if not session_status.get("configured"):
            reason = "XHS_SESSION_REQUIRED: no XHS login session is configured"
        elif not session_status.get("auth_cookie_present"):
            reason = "XHS_SESSION_REQUIRED: XHS authentication cookies are missing"
        elif session_status.get("auth_cookie_expired"):
            reason = "XHS_SESSION_EXPIRED: XHS login session has expired; re-login required"
        else:
            reason = "XHS_SESSION_OR_ACCESS_UNAVAILABLE: configured session returned 0 fresh evidence"
        xhs_warning = f"{xhs_warning}; {reason}"
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
    evidence_mode = "real_xhs" if xhs_ok else "baseline_or_partial"
    return {
        "keywords": len(keywords),
        "scrape_error": scrape_error,
        "discovery_diagnostics": discovery_diagnostics,
        "session_status": session_status,
        "xhs_freshness": xhs_freshness_public,
        "xhs_freshness_overview": freshness_overview(),
        "xhs_freshness_required": xhs_required,
        "xhs_freshness_ok": xhs_ok,
        "xhs_freshness_warning": xhs_warning,
        "baseline": baseline_result,
        "evidence_mode": evidence_mode,
        "snapshot_path": str(snapshot_path),
        "domains": sorted((payload.get("domains") or {}).keys()),
        "status": db_status(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run NoteAI market timing cloud pipeline worker")
    parser.add_argument("--once", action="store_true", help="Run one scrape/export cycle and exit")
    parser.add_argument("--daemon", action="store_true", help="Run forever at the configured interval")
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
            if args.once:
                return 1
        if args.once:
            return 0
        time.sleep(max(1, int(args.interval)) * 60)


if __name__ == "__main__":
    raise SystemExit(main())
