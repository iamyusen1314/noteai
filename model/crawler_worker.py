"""
Note real-performance crawler worker.

Use `--once` for cron jobs and `--loop` for a long-running background worker.
The worker only schedules/executes crawler collection; it does not start the
user API or admin API.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

import crawler
import runtime_settings
import tracking_contract


CONFIG_FILE = Path(__file__).parent / "crawler_config.json"


def _load_config() -> dict:
    stored = runtime_settings.get_json("crawler_config")
    if isinstance(stored, dict):
        return stored
    if not CONFIG_FILE.exists():
        return {"enabled": False}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"enabled": False}


async def _run_once(limit: int, force: bool) -> dict:
    config = _load_config()
    if not force and not bool(config.get("enabled", False)):
        return {"skipped": True, "reason": "crawler disabled"}
    return await crawler.run_collection_round(limit=limit)


def _result_exit_code(result: dict) -> int:
    """Map one structured outcome to a stable process contract."""
    if result.get("error"):
        return 1
    if int(result.get("failed") or 0) > 0:
        return 1
    if result.get("skipped"):
        return 0 if result.get("reason") in {
            "collection_suspended",
            "crawler disabled",
        } else 1
    return 0


async def _run_loop(limit: int, interval_minutes: int, force: bool) -> int:
    interval_seconds = max(60, int(interval_minutes) * 60)
    while True:
        result = await _run_once(limit=limit, force=force)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        exit_code = _result_exit_code(result)
        if exit_code:
            return exit_code
        await asyncio.sleep(interval_seconds)


def _round_limit(value: str) -> int:
    try:
        return tracking_contract.validate_round_limit(int(value))
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(
            f"limit must be 1..{tracking_contract.MAX_ROUND_LIMIT}"
        ) from None


def _interval_minutes(value: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("interval must be 1..1440") from None
    if parsed < 1 or parsed > 1440:
        raise argparse.ArgumentTypeError("interval must be 1..1440")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Run NoteAI tracking crawler worker.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Run one due-task collection round and exit.")
    mode.add_argument("--loop", action="store_true", help="Run continuously with a sleep interval.")
    mode.add_argument(
        "--healthcheck",
        action="store_true",
        help="Check the Tracking role/schema without calling a provider.",
    )
    mode.add_argument(
        "--reconcile-stale",
        action="store_true",
        help="Mark expired admitted calls outcome-unknown without retrying them.",
    )
    parser.add_argument("--limit", type=_round_limit, default=50, help="Maximum notes per round.")
    parser.add_argument(
        "--interval-minutes",
        type=_interval_minutes,
        default=60,
        help="Loop interval in minutes.",
    )
    parser.add_argument("--force", action="store_true", help="Run even when crawler_config.json has enabled=false.")
    args = parser.parse_args()

    if args.healthcheck:
        result = crawler.tracking_readiness_status()
        print(json.dumps(result, ensure_ascii=False), flush=True)
        raise SystemExit(0 if result.get("status") == "ready" else 1)

    if args.reconcile_stale:
        if os.environ.get("NOTEAI_RUNTIME_ROLE", "").strip() != "xhs-http":
            result = {
                "error": "runtime_role_not_allowed",
                "provider_called": False,
            }
            print(json.dumps(result, ensure_ascii=False), flush=True)
            raise SystemExit(1)
        try:
            reconciled = crawler._reconcile_stale_provider_attempts(
                limit=args.limit
            )
        except Exception:
            result = {
                "error": "tracking_stale_reconcile_failed",
                "provider_called": False,
                "retry_performed": False,
            }
            print(json.dumps(result, ensure_ascii=False), flush=True)
            raise SystemExit(1)
        result = {
            "reconciled": reconciled,
            "provider_called": False,
            "retry_performed": False,
        }
        print(json.dumps(result, ensure_ascii=False), flush=True)
        raise SystemExit(0)

    if args.loop:
        raise SystemExit(
            asyncio.run(
                _run_loop(args.limit, args.interval_minutes, args.force)
            )
        )

    result = asyncio.run(_run_once(args.limit, args.force))
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    raise SystemExit(_result_exit_code(result))


if __name__ == "__main__":
    main()
