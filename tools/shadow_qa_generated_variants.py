#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shadow-QA generated note artifacts with the current V0.4 composite gate.

This is an audit tool, not a training-data ingester. It re-scores existing
generated artifacts and reports where the real generation chain still falls
short before production deployment.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

import lightgbm as lgb
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("NOTEAI_FACT_SEARCH", "0")

import api as note_api  # noqa: E402
from naturalness import score_naturalness  # noqa: E402
from v04_composite_features import COMPOSITE_FEATURE_COLS, build_composite_features, canonical_domain  # noqa: E402


DEFAULT_ARTIFACT_DIR = ROOT / "quality" / "generated_variants"
DEFAULT_REPORT = ROOT / "quality" / "shadow_qa_generated_variants.v04.json"
DEFAULT_MARKDOWN = ROOT / "quality" / "shadow_qa_generated_variants.v04.md"
DEFAULT_TRAIN_REPORT = ROOT / "model" / "artifacts" / "model_v04_composite_train_report.json"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _round(value: Any, digits: int = 4) -> float | None:
    try:
        if value is None:
            return None
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _load_boosters(train_report: Path) -> tuple[dict[str, Any], lgb.Booster, lgb.Booster | None]:
    report = _load_json(train_report)
    golden = report.get("models", {}).get("golden", {})
    regressor_path = Path(golden.get("regressor_path") or "")
    if not regressor_path.exists():
        raise FileNotFoundError(f"V0.4 regressor not found: {regressor_path}")
    classifier_info = golden.get("classifier") or {}
    classifier_path = Path(classifier_info.get("path") or "")
    classifier = lgb.Booster(model_file=str(classifier_path)) if classifier_path.exists() else None
    return report, lgb.Booster(model_file=str(regressor_path)), classifier


def _artifact_paths(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.glob("*/*/*.json")
        if path.name not in {"latest_report.json"} and not path.name.startswith("run_report_")
    )


def _legacy_score(title: str, body: str, domain: str, local_time: str) -> tuple[float | None, dict[str, float], list[str]]:
    try:
        note = note_api.NoteInput(
            note_title=title,
            desc=note_api._normalize_tags_for_scoring(body),
            domain=domain,
            local_time=local_time or "2026062712",
        )
        semantic_defaults = {col: 0.5 for col in note_api.SEMANTIC_FEATURE_COLS}
        score, features = note_api._predict(note, semantic_feats=semantic_defaults)
        issues = note_api._generated_quality_issues(title, body, domain, score, features)
        return float(score), features, issues
    except Exception as exc:
        return None, {}, [f"legacy_score_failed:{type(exc).__name__}"]


def _v04_scores(
    *,
    regressor: lgb.Booster,
    classifier: lgb.Booster | None,
    title: str,
    body: str,
    domain: str,
    local_time: str,
) -> tuple[float, float | None, dict[str, float]]:
    features = build_composite_features(
        title=title,
        body=body,
        domain=domain,
        local_time=local_time or "2026062712",
    )
    vector = np.array([[float(features.get(col, 0.0) or 0.0) for col in COMPOSITE_FEATURE_COLS]], dtype=float)
    score = float(np.clip(regressor.predict(vector)[0], 0, 100))
    probability = float(classifier.predict(vector)[0]) if classifier is not None else None
    return score, probability, features


def _dedupe_issues(*issue_groups: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for issues in issue_groups:
        for issue in issues:
            text = str(issue).strip()
            if text and text not in seen:
                seen.add(text)
                out.append(text)
    return out


def _risk_tags(
    *,
    artifact: dict[str, Any],
    title: str,
    body: str,
    domain: str,
    source_context: str,
    v04_score: float,
    publishable_prob: float | None,
    issues: list[str],
    features: dict[str, float],
) -> list[str]:
    tags: list[str] = []
    canonical = canonical_domain(domain)
    body_len = note_api._body_content_len_without_tags(body)
    body_max = note_api._quality_body_max(canonical)
    body_floor = note_api._quality_body_target_floor(canonical)
    fact_issues = note_api._structured_fact_boundary_issues(f"{title}\n{body}", source_context, canonical)

    if artifact.get("blocking"):
        tags.append("historical_artifact_blocking")
    if v04_score < 60:
        tags.append("v04_score_lt_60")
    if publishable_prob is not None and publishable_prob < 0.5:
        tags.append("publishable_prob_lt_0.5")
    if v04_score >= 72 and publishable_prob is not None and publishable_prob < 0.5:
        tags.append("score_high_but_gate_low")
    if len(title) > getattr(note_api, "_TITLE_DELIVERY_MAX", 20):
        tags.append("title_over_delivery_limit")
    if len(title) < 6:
        tags.append("title_too_short")
    if body_floor and body_len < body_floor:
        tags.append("body_below_target_floor")
    if body_max and body_len > body_max:
        tags.append("body_over_target_max")
    if fact_issues:
        tags.append("structured_fact_boundary")
    if any("标题不自然" in issue or "标题超过" in issue or "标题过短" in issue for issue in issues):
        tags.append("title_readability")
    if any("正文超过" in issue or "正文过短" in issue or "正文低于" in issue for issue in issues):
        tags.append("body_length")
    if any("缺少互动引导" in issue for issue in issues):
        tags.append("missing_cta")
    if canonical == "美食" and not features.get("domain_food_must_order", 0):
        tags.append("food_missing_must_order_signal")
    if canonical == "美食" and not features.get("domain_food_hours", 0):
        tags.append("food_missing_hours_signal")
    if canonical == "旅行" and not features.get("domain_travel_transport", 0):
        tags.append("travel_missing_transport_signal")
    return tags


def evaluate_artifact(path: Path, regressor: lgb.Booster, classifier: lgb.Booster | None) -> dict[str, Any] | None:
    try:
        artifact = _load_json(path)
    except Exception as exc:
        return {"path": _rel(path), "status": "invalid_json", "error": str(exc)}

    raw_title = str(artifact.get("title") or "").strip()
    raw_body = str(artifact.get("body") or "").strip()
    if not raw_title or not raw_body:
        return None

    domain = canonical_domain(artifact.get("domain") or "")
    source_context = str(artifact.get("source_context") or "")
    title = note_api._sanitize_title_for_delivery(raw_title, source_context, domain)
    pre_shape_body = note_api._insert_safe_fact_line(raw_body, domain, source_context)
    raw_body_len = note_api._body_content_len_without_tags(pre_shape_body)
    body = note_api._compact_body_to_delivery_limit(pre_shape_body, domain)
    local_time = str(artifact.get("local_time") or "2026062712")

    legacy, legacy_features, legacy_issues = _legacy_score(title, body, domain, local_time)
    v04_score, publishable_prob, v04_features = _v04_scores(
        regressor=regressor,
        classifier=classifier,
        title=title,
        body=body,
        domain=domain,
        local_time=local_time,
    )
    natural = score_naturalness(title, body, domain)
    fact_issues = note_api._structured_fact_boundary_issues(f"{title}\n{body}", source_context, domain)
    format_issues = note_api._body_format_issues(body)
    title_issues = note_api._title_readability_issues(title, domain)
    readability_issues = note_api._human_readability_issues(body, domain)
    artifact_issues = [str(issue) for issue in artifact.get("quality_issues") or []]
    current_issues = _dedupe_issues(
        legacy_issues,
        fact_issues,
        format_issues,
        title_issues,
        readability_issues,
    )
    tags = _risk_tags(
        artifact=artifact,
        title=title,
        body=body,
        domain=domain,
        source_context=source_context,
        v04_score=v04_score,
        publishable_prob=publishable_prob,
        issues=current_issues,
        features=v04_features,
    )
    hard_block = bool(
        v04_score < 60
        or fact_issues
        or artifact.get("status") != "ready"
        or any(tag in tags for tag in ("title_over_delivery_limit", "title_too_short"))
    )
    shadow_ready = bool((not hard_block) and (publishable_prob is None or publishable_prob >= 0.5))

    return {
        "path": _rel(path),
        "artifact_set": path.parents[1].name,
        "task_id": str(artifact.get("task_id") or path.parent.name),
        "slot_id": str(artifact.get("slot_id") or path.stem),
        "origin": str(artifact.get("origin") or path.stem),
        "domain": domain,
        "status": str(artifact.get("status") or ""),
        "title": title,
        "title_len": len(title),
        "raw_body_len": raw_body_len,
        "body_len": note_api._body_content_len_without_tags(body),
        "delivery_shape_applied": body != pre_shape_body,
        "scores": {
            "v04_score": _round(v04_score, 3),
            "publishable_prob": _round(publishable_prob, 4),
            "legacy_reference_score": _round(legacy, 3),
            "artifact_score": _round(artifact.get("score"), 3),
            "naturalness_score": _round(natural.get("naturalness_score"), 3),
            "ai_probability": _round(natural.get("ai_probability"), 4),
        },
        "shadow_ready": shadow_ready,
        "hard_block": hard_block,
        "risk_tags": tags,
        "issue_count": len(current_issues),
        "issues": current_issues[:12],
        "artifact_issues": artifact_issues[:12],
        "feature_snapshot": {
            "commercial_fact_density": _round(v04_features.get("commercial_fact_density"), 3),
            "commercial_actionability": _round(v04_features.get("commercial_actionability"), 3),
            "commercial_specificity": _round(v04_features.get("commercial_specificity"), 3),
            "domain_slot_coverage": _round(v04_features.get("commercial_domain_slot_coverage"), 3),
            "tag_count": _round(v04_features.get("tag_count"), 0),
            "cta_count": _round(v04_features.get("body_cta_count"), 0),
            "body_has_price": int(v04_features.get("body_has_price", 0) or 0),
            "body_has_address": int(v04_features.get("body_has_address", 0) or 0),
            "body_has_hours": int(v04_features.get("body_has_hours", 0) or 0),
            "body_has_must_order": int(v04_features.get("body_has_must_order", 0) or 0),
        },
    }


def _avg(rows: list[dict[str, Any]], score_key: str) -> float | None:
    values = [row["scores"].get(score_key) for row in rows if row.get("scores", {}).get(score_key) is not None]
    return round(mean(values), 3) if values else None


def _summarize_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    ready = sum(1 for row in rows if row.get("shadow_ready"))
    hard = sum(1 for row in rows if row.get("hard_block"))
    high = sum(1 for row in rows if (row.get("scores", {}).get("v04_score") or 0) >= 72)
    shaped = sum(1 for row in rows if row.get("delivery_shape_applied"))
    historical_blocking = sum(
        1 for row in rows if "historical_artifact_blocking" in row.get("risk_tags", [])
    )
    risk_counts = Counter(
        tag
        for row in rows
        for tag in row.get("risk_tags", [])
        if tag != "historical_artifact_blocking"
    )
    return {
        "count": total,
        "shadow_ready_count": ready,
        "shadow_ready_rate": round(ready / total, 4) if total else 0.0,
        "hard_block_count": hard,
        "historical_artifact_blocking_count": historical_blocking,
        "delivery_shape_applied_count": shaped,
        "delivery_shape_applied_rate": round(shaped / total, 4) if total else 0.0,
        "v04_score_ge_72_count": high,
        "v04_score_ge_72_rate": round(high / total, 4) if total else 0.0,
        "avg_v04_score": _avg(rows, "v04_score"),
        "avg_publishable_prob": _avg(rows, "publishable_prob"),
        "avg_naturalness": _avg(rows, "naturalness_score"),
        "top_risks": dict(risk_counts.most_common(8)),
    }


def build_report(artifact_dir: Path, train_report: Path) -> dict[str, Any]:
    train, regressor, classifier = _load_boosters(train_report)
    rows = [row for path in _artifact_paths(artifact_dir) if (row := evaluate_artifact(path, regressor, classifier))]
    rows = [row for row in rows if row.get("scores")]
    by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_set: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_domain[row["domain"]].append(row)
        by_set[row["artifact_set"]].append(row)

    worst = sorted(
        rows,
        key=lambda row: (
            int(row.get("shadow_ready", False)),
            row.get("scores", {}).get("v04_score") or 0.0,
            -(row.get("issue_count") or 0),
        ),
    )[:25]
    high_risk = [
        row for row in rows
        if row.get("scores", {}).get("v04_score", 0) >= 72 and not row.get("shadow_ready")
    ][:25]
    return {
        "version": "v04-generated-shadow-qa-v0.1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "artifact_dir": str(artifact_dir),
            "train_report": str(train_report),
            "train_run_id": train.get("run_id"),
            "classifier_target": (
                train.get("models", {}).get("golden", {}).get("classifier", {}).get("target_column")
            ),
        },
        "summary": _summarize_group(rows),
        "by_domain": {key: _summarize_group(value) for key, value in sorted(by_domain.items())},
        "by_artifact_set": {key: _summarize_group(value) for key, value in sorted(by_set.items())},
        "worst_cases": worst,
        "high_score_not_ready_cases": high_risk,
        "rows": rows,
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# V0.4 Generated Variant Shadow QA",
        "",
        f"- Created at: `{report['created_at']}`",
        f"- Train run: `{report['inputs'].get('train_run_id')}`",
        f"- Classifier target: `{report['inputs'].get('classifier_target')}`",
        "",
        "## Summary",
        "",
    ]
    summary = report["summary"]
    for key in [
        "count",
        "shadow_ready_count",
        "shadow_ready_rate",
        "hard_block_count",
        "delivery_shape_applied_count",
        "delivery_shape_applied_rate",
        "v04_score_ge_72_count",
        "v04_score_ge_72_rate",
        "avg_v04_score",
        "avg_publishable_prob",
        "avg_naturalness",
    ]:
        lines.append(f"- {key}: `{summary.get(key)}`")
    lines.extend(["", "## By Domain", ""])
    lines.append("| Domain | Count | Ready Rate | Avg V0.4 | Avg Gate Prob | >=72 | Top Risks |")
    lines.append("|---|---:|---:|---:|---:|---:|---|")
    for domain, item in report["by_domain"].items():
        risks = ", ".join(f"{k}:{v}" for k, v in item.get("top_risks", {}).items())
        lines.append(
            f"| {domain} | {item['count']} | {item['shadow_ready_rate']} | "
            f"{item['avg_v04_score']} | {item['avg_publishable_prob']} | "
            f"{item['v04_score_ge_72_count']} | {risks} |"
        )
    lines.extend(["", "## Worst Cases", ""])
    for row in report.get("worst_cases", [])[:15]:
        lines.append(
            f"- `{row['path']}` {row['domain']} {row['slot_id']} "
            f"score=`{row['scores']['v04_score']}` prob=`{row['scores']['publishable_prob']}` "
            f"ready=`{row['shadow_ready']}` risks=`{','.join(row['risk_tags'])}` "
            f"title={row['title']}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Shadow-QA generated variants with V0.4 composite models")
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--train-report", type=Path, default=DEFAULT_TRAIN_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact_dir = args.artifact_dir if args.artifact_dir.is_absolute() else ROOT / args.artifact_dir
    train_report = args.train_report if args.train_report.is_absolute() else ROOT / args.train_report
    output = args.output if args.output.is_absolute() else ROOT / args.output
    markdown = args.markdown if args.markdown.is_absolute() else ROOT / args.markdown
    report = build_report(artifact_dir, train_report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(report, markdown)
    if args.json:
        printable = {k: report[k] for k in ("version", "created_at", "inputs", "summary", "by_domain", "by_artifact_set")}
        printable["outputs"] = {"report": str(output), "markdown": str(markdown)}
        print(json.dumps(printable, ensure_ascii=False, indent=2))
    else:
        print(f"rows={report['summary']['count']} ready_rate={report['summary']['shadow_ready_rate']}")
        print(f"report={output}")
        print(f"markdown={markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
