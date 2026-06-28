#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Write a compact first-core-domain gap report for v0.4 training."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

from v04_domain_policy import CORE_PRODUCT_DOMAINS, canonical_product_domain  # noqa: E402


DEFAULT_ANNOTATION_REPORT = ROOT / "quality" / "annotation_queue.v01.report.json"
DEFAULT_SUPPLEMENT_REPORT_V01 = ROOT / "quality" / "annotation_queue.v01.core_supplement.report.json"
DEFAULT_SUPPLEMENT_REPORT_V02 = ROOT / "quality" / "annotation_queue.v01.core_supplement.v02.report.json"
DEFAULT_SUPPLEMENT_REPORT = DEFAULT_SUPPLEMENT_REPORT_V02 if DEFAULT_SUPPLEMENT_REPORT_V02.exists() else DEFAULT_SUPPLEMENT_REPORT_V01
DEFAULT_GOLDEN_BATCH_REPORTS = (
    ROOT / "quality" / "labeling_batches" / "v04_round01_golden.report.json",
    ROOT / "quality" / "labeling_batches" / "v04_round01b_golden.report.json",
)
DEFAULT_PREFERENCE_BATCH_REPORTS = (
    ROOT / "quality" / "labeling_batches" / "v04_round01_preference.report.json",
    ROOT / "quality" / "labeling_batches" / "v04_round01b_preference.report.json",
)
DEFAULT_READINESS_REPORT = ROOT / "model" / "artifacts" / "v04_composite_readiness.json"
DEFAULT_HEALTH_REPORT = ROOT / "model" / "artifacts" / "v04_training_data_health.json"
DEFAULT_OUTPUT = ROOT / "model" / "artifacts" / "v04_core_domain_gap_report.json"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_paths(value: str) -> list[Path]:
    return [Path(part.strip()) for part in value.split(",") if part.strip()]


def _sum_report_counts(paths: list[Path], key: str = "by_domain") -> tuple[dict[str, int], list[str]]:
    counts: dict[str, int] = {}
    used: list[str] = []
    for path in paths:
        doc = _load_json(path)
        if not doc:
            continue
        used.append(str(path))
        for domain, value in (doc.get(key) or {}).items():
            canonical = canonical_product_domain(domain)
            counts[canonical] = counts.get(canonical, 0) + int(value or 0)
    return counts, used


def _count_for(counts: dict[str, Any], domain: str) -> int:
    total = 0
    for key, value in counts.items():
        if canonical_product_domain(key) == domain:
            total += int(value or 0)
    return total


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    annotation = _load_json(Path(args.annotation_report))
    supplement = _load_json(Path(args.supplement_report))
    golden_batch_counts, golden_batch_reports = _sum_report_counts(_parse_paths(args.golden_batch_reports))
    preference_batch_counts, preference_batch_reports = _sum_report_counts(_parse_paths(args.preference_batch_reports))
    readiness = _load_json(Path(args.readiness_report))
    health = _load_json(Path(args.health_report))

    queue_counts = annotation.get("by_domain_needs_label") or {}
    supplement_queue_counts = supplement.get("by_domain_selected") or {}
    readiness_gaps = readiness.get("gaps_by_domain") or {}

    rows: list[dict[str, Any]] = []
    for domain in CORE_PRODUCT_DOMAINS:
        gap = readiness_gaps.get(domain) or {}
        rows.append(
            {
                "domain": domain,
                "queue_needs_label": _count_for(queue_counts, domain) + _count_for(supplement_queue_counts, domain),
                "round01_golden_exported": _count_for(golden_batch_counts, domain),
                "round01_preference_exported": _count_for(preference_batch_counts, domain),
                "golden_labeled_current": int(gap.get("golden_labeled", 0) or 0),
                "preference_pairs_labeled_current": int(gap.get("preference_pairs_labeled", 0) or 0),
                "golden_needed_for_candidate": int(gap.get("golden_needed_for_candidate", 0) or 0),
                "preference_pairs_needed_for_candidate": int(gap.get("preference_pairs_needed_for_candidate", 0) or 0),
                "golden_needed_for_production": int(gap.get("golden_needed_for_production", 0) or 0),
                "preference_pairs_needed_for_production": int(gap.get("preference_pairs_needed_for_production", 0) or 0),
            }
        )

    missing_queue_domains = [
        row["domain"]
        for row in rows
        if row["queue_needs_label"] == 0
    ]
    missing_main_snapshot_domains = [
        domain
        for domain in CORE_PRODUCT_DOMAINS
        if _count_for(queue_counts, domain) == 0
    ]
    return {
        "version": "v04-core-domain-gap-report-v0.1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "decision": readiness.get("decision") or health.get("decision") or "unknown",
        "core_domains": list(CORE_PRODUCT_DOMAINS),
        "inputs": {
            "annotation_report": str(args.annotation_report),
            "supplement_report": str(args.supplement_report),
            "golden_batch_reports": golden_batch_reports,
            "preference_batch_reports": preference_batch_reports,
            "readiness_report": str(args.readiness_report),
            "health_report": str(args.health_report),
        },
        "rows": rows,
        "summary": {
            "round01_golden_total": sum(row["round01_golden_exported"] for row in rows),
            "round01_preference_total": sum(row["round01_preference_exported"] for row in rows),
            "core_domains_with_queue_needs_label": [
                row["domain"] for row in rows if row["queue_needs_label"] > 0
            ],
            "core_domains_missing_queue_needs_label": missing_queue_domains,
            "core_domains_missing_main_snapshot": missing_main_snapshot_domains,
            "health_issues": health.get("issues", []),
            "policy": (
                "Do not train a deployable v0.4-composite model until candidate/production "
                "label thresholds are met and health issues are cleared."
            ),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v0.4 first-core-domain gap report")
    parser.add_argument("--annotation-report", default=str(DEFAULT_ANNOTATION_REPORT))
    parser.add_argument("--supplement-report", default=str(DEFAULT_SUPPLEMENT_REPORT))
    parser.add_argument(
        "--golden-batch-reports",
        default=",".join(str(path) for path in DEFAULT_GOLDEN_BATCH_REPORTS),
    )
    parser.add_argument(
        "--preference-batch-reports",
        default=",".join(str(path) for path in DEFAULT_PREFERENCE_BATCH_REPORTS),
    )
    parser.add_argument("--readiness-report", default=str(DEFAULT_READINESS_REPORT))
    parser.add_argument("--health-report", default=str(DEFAULT_HEALTH_REPORT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"decision={report['decision']}")
        print(f"output={output}")
        for row in report["rows"]:
            print(
                f"{row['domain']}: queue={row['queue_needs_label']} "
                f"round01_golden={row['round01_golden_exported']} "
                f"round01_pref={row['round01_preference_exported']} "
                f"labeled_golden={row['golden_labeled_current']} "
                f"labeled_pref={row['preference_pairs_labeled_current']} "
                f"need_prod_golden={row['golden_needed_for_production']} "
                f"need_prod_pref={row['preference_pairs_needed_for_production']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
