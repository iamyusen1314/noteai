#!/usr/bin/env python3
"""Summarize sanitized SSE latency JSONL without retaining request content."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


MIN_RELIABLE_P95_SAMPLES = 100
ALLOWED_OPERATIONS = frozenset({"analyze", "generate", "chat"})
ALLOWED_OUTCOMES = frozenset({"success", "error"})


def nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    rank = max(1, math.ceil((percentile / 100.0) * len(ordered)))
    return ordered[rank - 1]


def latency_stats(values: list[float]) -> dict[str, Any]:
    count = len(values)
    return {
        "sample_count": count,
        "p50_ms": nearest_rank(values, 50),
        "p95_ms": nearest_rank(values, 95),
        "p95_reliable": count >= MIN_RELIABLE_P95_SAMPLES,
        "p95_reliability": "reliable" if count >= MIN_RELIABLE_P95_SAMPLES else "insufficient_sample",
    }


def summarize_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[float]] = defaultdict(list)
    rejected_count = 0
    for record in records:
        try:
            operation = str(record["operation"]).strip()
            outcome = str(record["outcome"]).strip()
            elapsed_ms = float(record["elapsed_ms"])
            if (
                operation not in ALLOWED_OPERATIONS
                or outcome not in ALLOWED_OUTCOMES
                or not math.isfinite(elapsed_ms)
                or elapsed_ms < 0
            ):
                raise ValueError("invalid sanitized latency record")
        except (KeyError, TypeError, ValueError):
            rejected_count += 1
            continue
        groups[(operation, outcome)].append(elapsed_ms)

    all_values = [value for values in groups.values() for value in values]
    overall = latency_stats(all_values)
    overall.update({
        "p95_reliable": False,
        "p95_reliability": "heterogeneous_not_sla",
    })
    return {
        "algorithm": "nearest-rank",
        "minimum_reliable_p95_samples": MIN_RELIABLE_P95_SAMPLES,
        "rejected_count": rejected_count,
        "overall": overall,
        "groups": [
            {"operation": operation, "outcome": outcome, **latency_stats(values)}
            for (operation, outcome), values in sorted(groups.items())
        ],
    }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                records.append({})
                continue
            records.append(value if isinstance(value, dict) else {})
    return records


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute P50/P95 from sanitized operation/outcome/elapsed_ms JSONL."
    )
    parser.add_argument("jsonl", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize_records(read_jsonl(args.jsonl)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
