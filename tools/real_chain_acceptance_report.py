#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the RQS-07 real-chain acceptance report.

The report aggregates existing real generation artifacts and run reports. It is
deliberately lightweight: no model calls, no fact-search calls, and no training
data ingestion. Large JSON artifacts stay under ignored quality directories;
the committed output is a concise Markdown acceptance record.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("NOTEAI_FACT_SEARCH", "0")

import api as note_api  # noqa: E402


DEFAULT_ARTIFACT_DIR = ROOT / "quality" / "generated_variants" / "v36_rqs05_06_regression"
DEFAULT_SHADOW_REPORT = ROOT / "quality" / "shadow_qa_generated_variants.v04.json"
DEFAULT_OUTPUT = ROOT / "docs" / "RQS07_REAL_CHAIN_ACCEPTANCE_REPORT.md"

DIRECT_ROUTES = {"analyze", "generate", "offline_candidate"}
DEPENDENT_ROUTES = {"second_pass", "chat"}
REQUIRED_DOMAINS = {"美食", "旅行", "穿搭", "美妆", "家居", "健身"}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _round(value: Any, digits: int = 3) -> float | None:
    try:
        if value is None:
            return None
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _score_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "min": None,
            "mean": None,
            "median": None,
            "max": None,
            "ge_60_count": 0,
            "ge_72_count": 0,
        }
    return {
        "count": len(values),
        "min": round(min(values), 3),
        "mean": round(mean(values), 3),
        "median": round(median(values), 3),
        "max": round(max(values), 3),
        "ge_60_count": sum(1 for value in values if value >= 60),
        "ge_72_count": sum(1 for value in values if value >= 72),
        "ge_72_rate": round(sum(1 for value in values if value >= 72) / len(values), 4),
    }


def _artifact_files(artifact_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in artifact_dir.glob("*/*.json")
        if path.name != "latest_report.json" and not path.name.startswith("run_report_")
    )


def _run_report_files(artifact_dir: Path) -> list[Path]:
    return sorted(artifact_dir.glob("run_report_*.json"))


def load_artifacts(artifact_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in _artifact_files(artifact_dir):
        try:
            artifact = _load_json(path)
        except Exception as exc:
            rows.append({
                "path": _rel(path),
                "status": "invalid_json",
                "error": str(exc),
                "score": None,
                "blocking": True,
                "title_issues_after_sanitize": ["invalid_json"],
            })
            continue
        domain = str(artifact.get("domain") or "")
        raw_title = str(artifact.get("title") or "")
        source_context = str(artifact.get("source_context") or "")
        title = note_api._sanitize_title_for_delivery(raw_title, source_context, domain)
        title_issues = note_api._title_readability_issues(title, domain)
        rows.append({
            "path": _rel(path),
            "task_id": str(artifact.get("task_id") or path.parent.name),
            "slot_id": str(artifact.get("slot_id") or path.stem),
            "domain": domain,
            "generation_route": str(artifact.get("generation_route") or ""),
            "status": str(artifact.get("status") or ""),
            "score": _round(artifact.get("score"), 3),
            "blocking": bool(artifact.get("blocking")),
            "title": title,
            "title_changed_by_sanitize": title != raw_title,
            "title_issues_after_sanitize": title_issues,
            "quality_issues": [str(item) for item in artifact.get("quality_issues") or []],
            "generation_notes": [str(item) for item in artifact.get("generation_notes") or []],
            "body_signature": "".join(str(artifact.get("body") or "").split()),
            "source_context": source_context,
        })
    return rows


def load_run_reports(artifact_dir: Path) -> list[dict[str, Any]]:
    reports = []
    for path in _run_report_files(artifact_dir):
        data = _load_json(path)
        reports.append({
            "path": _rel(path),
            "created_at": data.get("created_at"),
            "result_count": int(data.get("result_count") or 0),
            "by_status": data.get("by_status") or {},
            "score_summary": data.get("score_summary") or {},
            "failure_count": len(data.get("failures") or []),
            "blocked_count": int((data.get("score_summary") or {}).get("blocked_count") or 0),
            "ready_count": int((data.get("by_status") or {}).get("ready") or 0),
        })
    reports.sort(key=lambda item: str(item.get("created_at") or ""))
    return reports


def summarize_artifacts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [float(row["score"]) for row in rows if row.get("score") is not None]
    by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_route: dict[str, list[dict[str, Any]]] = defaultdict(list)
    diagnosis_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_domain[row["domain"]].append(row)
        by_route[row["generation_route"]].append(row)
        if row["slot_id"] in {"diagnosis_plan_a", "diagnosis_plan_b", "diagnosis_plan_c"}:
            diagnosis_by_task[row["task_id"]].append(row)

    diagnosis_integrity = []
    for task_id, items in sorted(diagnosis_by_task.items()):
        bodies = {row["body_signature"] for row in items if row.get("body_signature")}
        titles = {row["title"] for row in items if row.get("title")}
        diagnosis_integrity.append({
            "task_id": task_id,
            "plan_count": len(items),
            "unique_body_count": len(bodies),
            "unique_title_count": len(titles),
            "body_distinct": len(items) == 3 and len(bodies) == 3,
        })

    title_issue_rows = [row for row in rows if row.get("title_issues_after_sanitize")]
    failures = [row for row in rows if row.get("status") in {"failed", "invalid_json"}]
    blocking = [row for row in rows if row.get("blocking") or row.get("status") == "blocked"]
    score_lt_60 = [row for row in rows if row.get("score") is not None and float(row["score"]) < 60]
    score_lt_72 = [row for row in rows if row.get("score") is not None and float(row["score"]) < 72]

    return {
        "count": len(rows),
        "status_counts": dict(Counter(row.get("status") for row in rows)),
        "route_counts": dict(Counter(row.get("generation_route") for row in rows)),
        "score_summary": _score_summary(scores),
        "blocking_count": len(blocking),
        "failure_count": len(failures),
        "score_lt_60_count": len(score_lt_60),
        "score_lt_72_count": len(score_lt_72),
        "title_changed_by_sanitize_count": sum(1 for row in rows if row.get("title_changed_by_sanitize")),
        "title_issues_after_sanitize_count": len(title_issue_rows),
        "chat_regression_fallback_count": sum(
            1
            for row in rows
            if "chat_rewrite_rejected_score_drop_or_blocking" in row.get("generation_notes", [])
        ),
        "by_domain": {
            domain: {
                "count": len(items),
                "score_summary": _score_summary([
                    float(row["score"]) for row in items if row.get("score") is not None
                ]),
                "blocking_count": sum(1 for row in items if row.get("blocking")),
                "title_issue_count": sum(1 for row in items if row.get("title_issues_after_sanitize")),
                "routes": dict(Counter(row.get("generation_route") for row in items)),
            }
            for domain, items in sorted(by_domain.items())
        },
        "by_route": {
            route: {
                "count": len(items),
                "score_summary": _score_summary([
                    float(row["score"]) for row in items if row.get("score") is not None
                ]),
                "blocking_count": sum(1 for row in items if row.get("blocking")),
            }
            for route, items in sorted(by_route.items())
        },
        "diagnosis_integrity": diagnosis_integrity,
        "samples": {
            "score_lt_72": [
                {
                    "path": row["path"],
                    "domain": row["domain"],
                    "slot_id": row["slot_id"],
                    "score": row["score"],
                    "title": row["title"],
                }
                for row in sorted(score_lt_72, key=lambda item: float(item["score"] or 0))[:8]
            ],
            "title_issue_rows": [
                {
                    "path": row["path"],
                    "domain": row["domain"],
                    "title": row["title"],
                    "issues": row["title_issues_after_sanitize"],
                }
                for row in title_issue_rows[:8]
            ],
        },
    }


def summarize_run_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(reports),
        "failure_count": sum(report["failure_count"] for report in reports),
        "blocked_count": sum(report["blocked_count"] for report in reports),
        "ready_count": sum(report["ready_count"] for report in reports),
        "reports": reports,
    }


def load_shadow_summary(shadow_report: Path, artifact_set: str) -> dict[str, Any]:
    if not shadow_report.exists():
        return {"available": False, "path": _rel(shadow_report), "artifact_set": artifact_set}
    data = _load_json(shadow_report)
    by_set = data.get("by_artifact_set") or {}
    item = by_set.get(artifact_set)
    return {
        "available": True,
        "path": _rel(shadow_report),
        "created_at": data.get("created_at"),
        "artifact_set": artifact_set,
        "overall": data.get("summary") or {},
        "artifact_set_summary": item,
    }


def evaluate_gates(artifact_summary: dict[str, Any], run_summary: dict[str, Any], shadow: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "run_reports_have_no_failures": run_summary.get("failure_count", 0) == 0,
        "run_reports_have_no_blocked_outputs": run_summary.get("blocked_count", 0) == 0,
        "artifacts_have_no_blocking": artifact_summary.get("blocking_count", 0) == 0,
        "artifacts_have_no_failures": artifact_summary.get("failure_count", 0) == 0,
        "all_artifacts_score_ge_60": artifact_summary.get("score_lt_60_count", 0) == 0,
        "titles_readable_after_delivery_sanitize": artifact_summary.get("title_issues_after_sanitize_count", 0) == 0,
        "all_required_domains_present": REQUIRED_DOMAINS.issubset(set(artifact_summary.get("by_domain", {}).keys())),
        "diagnosis_bodies_are_distinct": all(
            item.get("body_distinct") for item in artifact_summary.get("diagnosis_integrity", [])
        ),
    }
    if shadow.get("available") and shadow.get("artifact_set_summary"):
        shadow_item = shadow["artifact_set_summary"]
        checks["shadow_set_ready_rate_is_1"] = float(shadow_item.get("shadow_ready_rate") or 0.0) == 1.0
        checks["shadow_set_hard_block_is_0"] = int(shadow_item.get("hard_block_count") or 0) == 0
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "failed_checks": [key for key, value in checks.items() if not value],
    }


def build_report(artifact_dir: Path, shadow_report: Path) -> dict[str, Any]:
    artifact_dir = artifact_dir if artifact_dir.is_absolute() else ROOT / artifact_dir
    shadow_report = shadow_report if shadow_report.is_absolute() else ROOT / shadow_report
    rows = load_artifacts(artifact_dir)
    reports = load_run_reports(artifact_dir)
    artifact_summary = summarize_artifacts(rows)
    run_summary = summarize_run_reports(reports)
    shadow = load_shadow_summary(shadow_report, artifact_dir.name)
    gates = evaluate_gates(artifact_summary, run_summary, shadow)
    return {
        "version": "rqs07-real-chain-acceptance-v0.1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artifact_dir": _rel(artifact_dir),
        "artifact_set": artifact_dir.name,
        "artifact_summary": artifact_summary,
        "run_summary": run_summary,
        "shadow_summary": shadow,
        "gates": gates,
    }


def write_markdown(report: dict[str, Any], output: Path) -> None:
    artifact = report["artifact_summary"]
    score = artifact["score_summary"]
    run = report["run_summary"]
    gates = report["gates"]
    shadow = report["shadow_summary"]

    lines = [
        "# RQS-07 Real Chain Acceptance Report",
        "",
        f"- Created at: `{report['created_at']}`",
        f"- Artifact set: `{report['artifact_set']}`",
        f"- Artifact dir: `{report['artifact_dir']}`",
        f"- Gate: `{'PASS' if gates['passed'] else 'FAIL'}`",
        "",
        "## Gate Checks",
        "",
    ]
    for key, value in gates["checks"].items():
        lines.append(f"- {key}: `{'pass' if value else 'fail'}`")

    lines.extend([
        "",
        "## Artifact Summary",
        "",
        f"- Artifacts: `{artifact['count']}`",
        f"- Status counts: `{json.dumps(artifact['status_counts'], ensure_ascii=False)}`",
        f"- Route counts: `{json.dumps(artifact['route_counts'], ensure_ascii=False)}`",
        f"- Blocking: `{artifact['blocking_count']}`",
        f"- Failures: `{artifact['failure_count']}`",
        f"- Scores: count `{score['count']}`, min `{score['min']}`, mean `{score['mean']}`, median `{score['median']}`, max `{score['max']}`",
        f"- Score >= 60: `{score['ge_60_count']}/{score['count']}`",
        f"- Score >= 72: `{score['ge_72_count']}/{score['count']}`",
        f"- Title issues after delivery sanitize: `{artifact['title_issues_after_sanitize_count']}`",
        f"- Titles changed by sanitize: `{artifact['title_changed_by_sanitize_count']}`",
        f"- Chat regression fallback count: `{artifact['chat_regression_fallback_count']}`",
        "",
        "## Run Reports",
        "",
        f"- Run reports: `{run['count']}`",
        f"- Ready outputs: `{run['ready_count']}`",
        f"- Failures: `{run['failure_count']}`",
        f"- Blocked outputs: `{run['blocked_count']}`",
    ])
    for item in run["reports"]:
        summary = item.get("score_summary") or {}
        lines.append(
            f"- `{item['path']}` ready `{item['ready_count']}`, failures `{item['failure_count']}`, "
            f"blocked `{item['blocked_count']}`, mean `{summary.get('mean')}`, min `{summary.get('min')}`"
        )

    lines.extend(["", "## By Domain", ""])
    lines.append("| Domain | Count | Mean | Median | Min | >=72 | Blocking | Title Issues | Routes |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---|")
    for domain, item in artifact["by_domain"].items():
        s = item["score_summary"]
        routes = ", ".join(f"{k}:{v}" for k, v in item["routes"].items())
        lines.append(
            f"| {domain} | {item['count']} | {s['mean']} | {s['median']} | {s['min']} | "
            f"{s['ge_72_count']} | {item['blocking_count']} | {item['title_issue_count']} | {routes} |"
        )

    lines.extend(["", "## Diagnosis Integrity", ""])
    lines.append("| Task | Plans | Unique Bodies | Unique Titles | Body Distinct |")
    lines.append("|---|---:|---:|---:|---|")
    for item in artifact["diagnosis_integrity"]:
        lines.append(
            f"| {item['task_id']} | {item['plan_count']} | {item['unique_body_count']} | "
            f"{item['unique_title_count']} | `{item['body_distinct']}` |"
        )

    if shadow.get("available"):
        lines.extend(["", "## Shadow QA", ""])
        lines.append(f"- Shadow report: `{shadow.get('path')}`")
        lines.append(f"- Shadow report created at: `{shadow.get('created_at')}`")
        set_summary = shadow.get("artifact_set_summary")
        if set_summary:
            lines.append(f"- Artifact set ready rate: `{set_summary.get('shadow_ready_rate')}`")
            lines.append(f"- Artifact set hard block count: `{set_summary.get('hard_block_count')}`")
            lines.append(f"- Artifact set avg V0.4 score: `{set_summary.get('avg_v04_score')}`")
            lines.append(f"- Artifact set >=72: `{set_summary.get('v04_score_ge_72_count')}/{set_summary.get('count')}`")
        else:
            lines.append("- Artifact set summary: `not found in shadow report`")
        overall = shadow.get("overall") or {}
        if overall:
            top_risks = json.dumps(overall.get("top_risks") or {}, ensure_ascii=False)
            lines.extend([
                "",
                "### Historical Generated Variants Context",
                "",
                "- This section is audit context only. The RQS-07 gate above is scoped to the current artifact set.",
                f"- Overall historical count: `{overall.get('count')}`",
                f"- Overall shadow ready rate: `{overall.get('shadow_ready_rate')}`",
                f"- Overall hard block count: `{overall.get('hard_block_count')}`",
                f"- Overall avg V0.4 score: `{overall.get('avg_v04_score')}`",
                f"- Overall >=72: `{overall.get('v04_score_ge_72_count')}/{overall.get('count')}`",
                f"- Historical top risks: `{top_risks}`",
            ])

    low_samples = artifact["samples"]["score_lt_72"]
    lines.extend(["", "## Residual Risks", ""])
    if not low_samples and not gates["failed_checks"]:
        lines.append("- No blocking residual risk in this artifact set.")
    else:
        if low_samples:
            lines.append("- Non-blocking <72 samples remain. They are above the 60 hard gate and should be handled by selector/chat in production:")
            for row in low_samples:
                lines.append(
                    f"  - `{row['path']}` {row['domain']} {row['slot_id']} score `{row['score']}` title `{row['title']}`"
                )
        if gates["failed_checks"]:
            lines.append(f"- Failed gate checks: `{', '.join(gates['failed_checks'])}`")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build RQS-07 real-chain acceptance report")
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--shadow-report", type=Path, default=DEFAULT_SHADOW_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--json", action="store_true", help="Print compact JSON summary")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(args.artifact_dir, args.shadow_report)
    output = args.output if args.output.is_absolute() else ROOT / args.output
    write_markdown(report, output)
    if args.json:
        printable = {
            "version": report["version"],
            "artifact_set": report["artifact_set"],
            "gates": report["gates"],
            "score_summary": report["artifact_summary"]["score_summary"],
            "run_summary": {
                "ready_count": report["run_summary"]["ready_count"],
                "failure_count": report["run_summary"]["failure_count"],
                "blocked_count": report["run_summary"]["blocked_count"],
            },
            "output": _rel(output),
        }
        print(json.dumps(printable, ensure_ascii=False, indent=2))
    else:
        print(f"gate={'PASS' if report['gates']['passed'] else 'FAIL'}")
        print(f"output={output}")
    return 0 if report["gates"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
