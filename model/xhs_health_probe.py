#!/usr/bin/env python3
"""Probe real XHS freshness before the daily evidence deadline."""

from __future__ import annotations

import argparse
import json
import sys

import hot_keywords
import xhs_acquisition


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check XHS real-evidence freshness ledger.")
    parser.add_argument("--domain", action="append", default=[], help="Domain to check. Repeatable.")
    parser.add_argument("--deadline-hour", type=int, default=None)
    parser.add_argument("--deadline-minute", type=int, default=0)
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    domains = tuple(args.domain) if args.domain else hot_keywords.CORE_EVIDENCE_DOMAINS
    result = xhs_acquisition.freshness_probe(
        domains,
        deadline_hour=args.deadline_hour,
        deadline_minute=args.deadline_minute,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
