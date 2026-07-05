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
from scheduler_a import scrape_once
from xhs_acquisition import (
    freshness_overview,
    record_scrape_freshness,
    xhs_freshness_required,
)


DEFAULT_SNAPSHOT_PATH = Path(__file__).parent / "data" / "market_timing_snapshot.json"


def _upload_snapshot(payload: dict, url: str) -> None:
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("NOTEAI_MARKET_TIMING_SNAPSHOT_UPLOAD_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    timeout = float(os.environ.get("NOTEAI_MARKET_TIMING_UPLOAD_TIMEOUT", "20") or 20)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.put(url, content=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers)
        resp.raise_for_status()


async def run_once(snapshot_path: Path, upload_url: str = "", hours: int = 30) -> dict:
    init_db()
    run_id = str(uuid.uuid4())
    scrape_error = ""
    try:
        keywords = await scrape_once()
    except Exception as exc:
        keywords = []
        scrape_error = f"{type(exc).__name__}: {exc}"
    if keywords:
        upsert_keywords(keywords)
    xhs_freshness = record_scrape_freshness(keywords, run_id=run_id)
    if xhs_freshness_required() and not (xhs_freshness.get("overview") or {}).get("ok"):
        missing = ", ".join((xhs_freshness.get("overview") or {}).get("missing_domains") or [])
        raise RuntimeError(f"XHS_FRESH_EVIDENCE_UNAVAILABLE: missing fresh XHS evidence for {missing}")
    baseline_result = ensure_daily_evidence_pack()
    payload = write_keyword_snapshot(snapshot_path, hours=hours)
    if not (payload.get("domains") or {}):
        raise RuntimeError("market timing snapshot contains 0 domains")
    if upload_url:
        _upload_snapshot(payload, upload_url)
    return {
        "keywords": len(keywords),
        "scrape_error": scrape_error,
        "xhs_freshness": xhs_freshness,
        "xhs_freshness_overview": freshness_overview(),
        "baseline": baseline_result,
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
    args = parser.parse_args()

    snapshot_path = Path(args.snapshot_path)
    if not args.once and not args.daemon:
        args.once = True

    while True:
        try:
            result = asyncio.run(run_once(snapshot_path, upload_url=args.upload_url, hours=args.hours))
            print(json.dumps({"ok": True, **result}, ensure_ascii=False), flush=True)
        except Exception as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr, flush=True)
            if args.once:
                return 1
        if args.once:
            return 0
        time.sleep(max(1, int(args.interval)) * 60)


if __name__ == "__main__":
    raise SystemExit(main())
