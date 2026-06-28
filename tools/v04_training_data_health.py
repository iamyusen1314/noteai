#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Health audit for v0.4-composite training data."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

from v04_composite_dataset import build_golden_training_rows, build_preference_pair_rows  # noqa: E402
from v04_domain_policy import CORE_PRODUCT_DOMAINS, canonical_product_domain  # noqa: E402


CORE_DOMAINS = CORE_PRODUCT_DOMAINS
DEFAULT_GOLDEN = ROOT / "quality" / "golden_labels.v01.merged.json"
DEFAULT_GOLDEN_FALLBACK = ROOT / "quality" / "golden_labels.v01.seed.json"
DEFAULT_PREF = ROOT / "quality" / "preference_queue.v01.labeled.jsonl"
DEFAULT_PREF_FALLBACK = ROOT / "quality" / "preference_queue.v01.jsonl"
DEFAULT_OUTPUT = ROOT / "model" / "artifacts" / "v04_training_data_health.json"


def _hash_text(title: str, body: str) -> str:
    return hashlib.sha256(f"{title}\n{body}".encode("utf-8")).hexdigest()[:16]


def _counts_by_domain(df) -> dict[str, int]:
    if df.empty or "domain" not in df.columns:
        return {}
    counts = Counter(canonical_product_domain(value) for value in df["domain"].tolist())
    return dict(sorted({str(k): int(v) for k, v in counts.items()}.items()))


def _duplicate_texts(df) -> list[dict[str, Any]]:
    if df.empty:
        return []
    hashes: dict[str, list[str]] = {}
    for _, row in df.iterrows():
        h = _hash_text(str(row.get("title") or ""), str(row.get("body") or ""))
        hashes.setdefault(h, []).append(str(row.get("content_id") or ""))
    return [
        {"text_hash": h, "ids": ids[:10], "count": len(ids)}
        for h, ids in hashes.items()
        if len(ids) > 1
    ][:50]


def build_health_report(args: argparse.Namespace) -> dict[str, Any]:
    golden_path = Path(args.golden_labels)
    pref_path = Path(args.preference_queue)
    golden_df = build_golden_training_rows(golden_path)
    pref_df = build_preference_pair_rows(pref_path)

    golden_counts = _counts_by_domain(golden_df)
    pref_counts = _counts_by_domain(pref_df)
    gaps: dict[str, dict[str, int]] = {}
    for domain in CORE_DOMAINS:
        g = golden_counts.get(domain, 0)
        p = pref_counts.get(domain, 0)
        gaps[domain] = {
            "golden_labeled": int(g),
            "preference_pairs_labeled": int(p),
            "golden_needed_candidate": max(0, args.min_golden_candidate - int(g)),
            "preference_needed_candidate": max(0, args.min_preference_candidate - int(p)),
            "golden_needed_production": max(0, args.min_golden_production - int(g)),
            "preference_needed_production": max(0, args.min_preference_production - int(p)),
        }

    ready_counts = (
        {str(k): int(v) for k, v in golden_df["delivery_ready"].value_counts().items()}
        if not golden_df.empty and "delivery_ready" in golden_df.columns else {}
    )
    winner_counts = (
        {str(k): int(v) for k, v in pref_df["winner"].value_counts().items()}
        if not pref_df.empty and "winner" in pref_df.columns else {}
    )
    pair_target_counts = (
        {str(k): int(v) for k, v in pref_df["preference_label_a_wins"].value_counts().items()}
        if not pref_df.empty and "preference_label_a_wins" in pref_df.columns else {}
    )

    candidate_ready = all(
        item["golden_needed_candidate"] == 0 and item["preference_needed_candidate"] == 0
        for item in gaps.values()
    )
    production_ready = all(
        item["golden_needed_production"] == 0 and item["preference_needed_production"] == 0
        for item in gaps.values()
    )
    issues: list[str] = []
    if len(golden_df) == 0:
        issues.append("no_golden_rows")
    if len(pref_df) == 0:
        issues.append("no_preference_rows")
    if len(set(golden_df["delivery_ready"].astype(int).tolist())) < 2 if not golden_df.empty else True:
        issues.append("golden_delivery_ready_single_class")
    binary_pref = pref_df[pref_df["preference_label_a_wins"].isin([0.0, 1.0])] if not pref_df.empty else pref_df
    if binary_pref.empty or len(set(binary_pref["preference_label_a_wins"].astype(float).tolist())) < 2:
        issues.append("preference_winner_single_class_or_empty")

    return {
        "version": "v04-training-data-health-v0.1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "decision": "production_ready" if production_ready else "candidate_ready" if candidate_ready else "blocked_need_labels",
        "inputs": {
            "golden_labels": str(golden_path),
            "preference_queue": str(pref_path),
        },
        "thresholds": {
            "min_golden_candidate_per_domain": args.min_golden_candidate,
            "min_preference_candidate_per_domain": args.min_preference_candidate,
            "min_golden_production_per_domain": args.min_golden_production,
            "min_preference_production_per_domain": args.min_preference_production,
        },
        "counts": {
            "golden_rows": int(len(golden_df)),
            "preference_pair_rows": int(len(pref_df)),
            "golden_by_domain": golden_counts,
            "preference_by_domain": pref_counts,
            "delivery_ready_counts": ready_counts,
            "preference_winner_counts": winner_counts,
            "preference_target_counts": pair_target_counts,
        },
        "gaps_by_domain": gaps,
        "issues": issues,
        "duplicates": {
            "golden_duplicate_texts": _duplicate_texts(golden_df),
        },
    }


def parse_args() -> argparse.Namespace:
    default_golden = DEFAULT_GOLDEN if DEFAULT_GOLDEN.exists() else DEFAULT_GOLDEN_FALLBACK
    default_pref = DEFAULT_PREF if DEFAULT_PREF.exists() else DEFAULT_PREF_FALLBACK
    parser = argparse.ArgumentParser(description="Audit v0.4-composite training data health")
    parser.add_argument("--golden-labels", default=str(default_golden))
    parser.add_argument("--preference-queue", default=str(default_pref))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--min-golden-candidate", type=int, default=300)
    parser.add_argument("--min-preference-candidate", type=int, default=1000)
    parser.add_argument("--min-golden-production", type=int, default=1000)
    parser.add_argument("--min-preference-production", type=int, default=3000)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_health_report(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"decision={report['decision']}")
        print(f"golden_rows={report['counts']['golden_rows']} preference_pairs={report['counts']['preference_pair_rows']}")
        print(f"issues={report['issues']}")
        print(f"output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
