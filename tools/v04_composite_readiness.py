#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Report whether v0.4-composite has enough labels to train safely.

This is intentionally strict. The goal is to prevent another v0.3 situation:
high-looking metrics from weak labels, leakage, or a single biased scorer.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

from v04_domain_policy import CORE_PRODUCT_DOMAINS, canonical_product_domain  # noqa: E402

CORE_DOMAINS = CORE_PRODUCT_DOMAINS
DEFAULT_GOLDEN = ROOT / "quality" / "golden_labels.v01.merged.json"
DEFAULT_GOLDEN_FALLBACK = ROOT / "quality" / "golden_labels.v01.seed.json"
DEFAULT_PREF = ROOT / "quality" / "preference_queue.v01.labeled.jsonl"
DEFAULT_PREF_FALLBACK = ROOT / "quality" / "preference_queue.v01.jsonl"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _golden_counts(labels_path: Path) -> dict[str, Any]:
    doc = _load_json(labels_path)
    by_domain: dict[str, Counter] = defaultdict(Counter)
    labeled = 0
    for item in doc.get("items", []):
        labels = item.get("labels") or {}
        src = item.get("content_source") or {}
        domain = src.get("domain") or "未知"
        # quality_case domains are in the referenced case; keep the seed domain
        # as unknown only if it truly cannot be inferred.
        if src.get("type") == "quality_case":
            try:
                cases = _load_json(ROOT / src["file"])
                case = next((row for row in cases if row.get("id") == src.get("case_id")), {})
                domain = case.get("domain") or domain
            except Exception:
                pass
        if "human_quality_score" in labels:
            domain = canonical_product_domain(domain)
            labeled += 1
            by_domain[domain]["labeled"] += 1
            if labels.get("delivery_ready"):
                by_domain[domain]["ready"] += 1
            else:
                by_domain[domain]["not_ready"] += 1
    return {
        "total_labeled": labeled,
        "by_domain": {domain: dict(counts) for domain, counts in sorted(by_domain.items())},
    }


def _preference_counts(queue_path: Path) -> dict[str, Any]:
    rows = _iter_jsonl(queue_path)
    by_domain: dict[str, Counter] = defaultdict(Counter)
    labeled = 0
    for row in rows:
        domain = canonical_product_domain(row.get("domain") or "未知")
        winner = row.get("winner")
        by_domain[domain]["pairs_total"] += 1
        if winner in {"A", "B", "tie"}:
            labeled += 1
            by_domain[domain]["pairs_labeled"] += 1
        else:
            by_domain[domain]["pairs_unlabeled"] += 1
    return {
        "pairs_total": len(rows),
        "pairs_labeled": labeled,
        "by_domain": {domain: dict(counts) for domain, counts in sorted(by_domain.items())},
    }


def build_readiness_report(args: argparse.Namespace) -> dict[str, Any]:
    golden = _golden_counts(Path(args.golden_labels))
    prefs = _preference_counts(Path(args.preference_queue))

    gaps: dict[str, dict[str, int]] = {}
    for domain in CORE_DOMAINS:
        golden_count = int(golden["by_domain"].get(domain, {}).get("labeled", 0))
        pref_count = int(prefs["by_domain"].get(domain, {}).get("pairs_labeled", 0))
        gaps[domain] = {
            "golden_labeled": golden_count,
            "golden_needed_for_candidate": max(0, args.min_golden_candidate - golden_count),
            "golden_needed_for_production": max(0, args.min_golden_production - golden_count),
            "preference_pairs_labeled": pref_count,
            "preference_pairs_needed_for_candidate": max(0, args.min_preference_candidate - pref_count),
            "preference_pairs_needed_for_production": max(0, args.min_preference_production - pref_count),
        }

    candidate_ready = all(
        gaps[d]["golden_needed_for_candidate"] == 0
        and gaps[d]["preference_pairs_needed_for_candidate"] == 0
        for d in CORE_DOMAINS
    )
    production_ready = all(
        gaps[d]["golden_needed_for_production"] == 0
        and gaps[d]["preference_pairs_needed_for_production"] == 0
        for d in CORE_DOMAINS
    )

    return {
        "version": "v04-composite-readiness-v0.1",
        "decision": "production_ready" if production_ready else "candidate_ready" if candidate_ready else "blocked_need_labels",
        "core_domains": list(CORE_DOMAINS),
        "thresholds": {
            "min_golden_candidate_per_domain": args.min_golden_candidate,
            "min_golden_production_per_domain": args.min_golden_production,
            "min_preference_candidate_per_domain": args.min_preference_candidate,
            "min_preference_production_per_domain": args.min_preference_production,
        },
        "golden": golden,
        "preferences": prefs,
        "gaps_by_domain": gaps,
        "training_policy": {
            "v03_usage": "telemetry_only_not_training_target",
            "primary_label": "human_quality_score + delivery_ready + A/B preference",
            "hard_requirements": [
                "Group split by content/task id",
                "Domain calibration report",
                "Golden false-positive/false-negative audit",
                "No deployment until production thresholds and human review pass",
            ],
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check v0.4-composite training readiness")
    default_golden = DEFAULT_GOLDEN if DEFAULT_GOLDEN.exists() else DEFAULT_GOLDEN_FALLBACK
    default_pref = DEFAULT_PREF if DEFAULT_PREF.exists() else DEFAULT_PREF_FALLBACK
    parser.add_argument("--golden-labels", default=str(default_golden))
    parser.add_argument("--preference-queue", default=str(default_pref))
    parser.add_argument("--output", default=str(ROOT / "model" / "artifacts" / "v04_composite_readiness.json"))
    parser.add_argument("--min-golden-candidate", type=int, default=300)
    parser.add_argument("--min-golden-production", type=int, default=1000)
    parser.add_argument("--min-preference-candidate", type=int, default=1000)
    parser.add_argument("--min-preference-production", type=int, default=3000)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_readiness_report(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"decision={report['decision']}")
        print(f"output={output}")
        for domain, gap in report["gaps_by_domain"].items():
            print(
                f"{domain}: golden={gap['golden_labeled']} "
                f"pref={gap['preference_pairs_labeled']} "
                f"need_prod_golden={gap['golden_needed_for_production']} "
                f"need_prod_pref={gap['preference_pairs_needed_for_production']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
