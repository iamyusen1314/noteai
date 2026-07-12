#!/usr/bin/env python3
"""Audit, apply, or safely roll back the managed V0.4 Prompt baseline."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
sys.path.insert(0, str(MODEL_DIR))

import db  # noqa: E402
import prompt_manager  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--rollback", action="store_true")
    args = parser.parse_args()

    if args.rollback:
        result = prompt_manager.rollback_versioned_baseline()
        print(
            "prompt_baseline_status=rolled_back "
            f"restored={result['restored']} removed={result['removed']}"
        )
        return 0
    if args.apply:
        result = prompt_manager.apply_versioned_baseline()
        print(
            "prompt_baseline_status=applied "
            f"inserted={result['inserted']} updated={result['updated']} "
            f"current={result['already_current']} skipped={result['skipped_custom']}"
        )
        return 0
    result = prompt_manager.apply_versioned_baseline(dry_run=True)
    print(
        "prompt_baseline_status=dry_run "
        f"missing={result['missing']} eligible={result['eligible_update']} "
        f"current={result['already_current']} skipped={result['skipped_custom']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
