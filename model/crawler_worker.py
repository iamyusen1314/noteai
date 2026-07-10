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
from pathlib import Path

import crawler
import runtime_settings


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


async def _run_loop(limit: int, interval_minutes: int, force: bool) -> None:
    interval_seconds = max(60, int(interval_minutes) * 60)
    while True:
        result = await _run_once(limit=limit, force=force)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        await asyncio.sleep(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run NoteAI tracking crawler worker.")
    parser.add_argument("--once", action="store_true", help="Run one due-task collection round and exit.")
    parser.add_argument("--loop", action="store_true", help="Run continuously with a sleep interval.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum notes per round.")
    parser.add_argument("--interval-minutes", type=int, default=60, help="Loop interval in minutes.")
    parser.add_argument("--force", action="store_true", help="Run even when crawler_config.json has enabled=false.")
    args = parser.parse_args()

    if args.loop:
        asyncio.run(_run_loop(args.limit, args.interval_minutes, args.force))
        return

    result = asyncio.run(_run_once(args.limit, args.force))
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
