#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a composite quality report for golden labels."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

import api  # noqa: E402
from feature_extraction import FEATURE_COLS, SEMANTIC_FEATURE_COLS, TIMING_FEATURE_COLS, extract_features  # noqa: E402
from naturalness import score_naturalness  # noqa: E402
from rednote_vibe_v04 import MODEL_FEATURE_COLS_V04, VISUAL_FEATURE_COLS  # noqa: E402


V04_MODEL_PATH = ROOT / "model" / "artifacts" / "model_a_v0.4_candidate.lgb"
_V04_MODEL: lgb.Booster | None = None


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_path(path: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    return p


def resolve_content(item: dict) -> dict[str, str]:
    src = item["content_source"]
    src_type = src["type"]
    if src_type == "inline":
        return {
            "id": item["id"],
            "title": src["title"],
            "body": src["body"],
            "domain": src.get("domain") or "美食",
            "local_time": src.get("local_time") or "2026062412",
        }

    data = _load_json(_resolve_path(src["file"]))
    if src_type == "quality_case":
        for case in data:
            if case.get("id") == src["case_id"]:
                return {
                    "id": item["id"],
                    "title": case["title"],
                    "body": case["body"],
                    "domain": case.get("domain") or src.get("domain") or "美食",
                    "local_time": case.get("local_time") or "2026062412",
                }
        raise KeyError(f"case_id not found: {src['case_id']} in {src['file']}")

    if src_type == "json_fields":
        title = data[src["title_field"]]
        body = data[src["body_field"]]
        return {
            "id": item["id"],
            "title": title,
            "body": body,
            "domain": src.get("domain") or data.get("domain") or "美食",
            "local_time": src.get("local_time") or data.get("local_time") or "2026062412",
        }
    raise ValueError(f"Unsupported content_source.type: {src_type}")


def score_v03(content: dict) -> tuple[float, dict[str, float], list[str], bool]:
    note = api.NoteInput(
        note_title=content["title"],
        desc=api._normalize_tags_for_scoring(content["body"]),
        local_time=content.get("local_time") or "2026062412",
        domain=content.get("domain") or "美食",
    )
    semantic_defaults = {col: 0.5 for col in api.SEMANTIC_FEATURE_COLS}
    score, features = api._predict(note, semantic_feats=semantic_defaults)
    issues = api._generated_quality_issues(
        content["title"],
        content["body"],
        content.get("domain") or "美食",
        score,
        features,
    )
    blocking = api._has_blocking_quality_issues(score, issues, content.get("domain") or "美食")
    return float(score), features, issues, bool(blocking)


def _get_v04_model() -> lgb.Booster | None:
    global _V04_MODEL
    if not V04_MODEL_PATH.exists():
        return None
    if _V04_MODEL is None:
        _V04_MODEL = lgb.Booster(model_file=str(V04_MODEL_PATH))
    return _V04_MODEL


def score_v04(content: dict) -> float | None:
    model = _get_v04_model()
    if model is None:
        return None
    base = extract_features(
        {
            "note_title": content["title"],
            "desc": api._normalize_tags_for_scoring(content["body"]),
            "local_time": content.get("local_time") or "2026062412",
            "domain": content.get("domain") or "美食",
        }
    )
    rec: dict[str, float] = {col: float(base.get(col, 0.0) or 0.0) for col in FEATURE_COLS}
    for col in SEMANTIC_FEATURE_COLS:
        rec[col] = 0.5
    for col in VISUAL_FEATURE_COLS:
        rec[col] = 0.0
    for col in TIMING_FEATURE_COLS:
        rec[col] = 0.0
    vector = np.array([[rec[col] for col in MODEL_FEATURE_COLS_V04]], dtype=float)
    return float(max(0.0, min(100.0, model.predict(vector)[0])))


def experimental_signal_score(v03: float, v04: float | None, naturalness: float, issues: list[str], blocking: bool) -> float:
    """A conservative signal for report triage, not a production score.

    v0.3 is intentionally ignored here. It is still displayed as telemetry and
    mismatch evidence, but it must not pull the composite signal up or down.
    """
    v04_value = 50.0 if v04 is None else v04
    issue_penalty = min(30.0, len(issues) * 4.0)
    blocking_penalty = 18.0 if blocking else 0.0
    ai_risk_penalty = 10.0 if naturalness < 20 else (5.0 if naturalness < 50 else 0.0)
    rule_score = max(0.0, 100.0 - issue_penalty - blocking_penalty)
    score = 0.45 * v04_value + 0.35 * naturalness + 0.20 * rule_score
    score -= ai_risk_penalty
    return float(max(0.0, min(100.0, score)))


def evaluate_item(item: dict) -> dict[str, Any]:
    content = resolve_content(item)
    labels = item["labels"]
    v03, features, issues, blocking = score_v03(content)
    v04 = score_v04(content)
    nat = score_naturalness(content["title"], content["body"], content["domain"])
    nat_score = float(nat["naturalness_score"])
    signal = experimental_signal_score(v03, v04, nat_score, issues, blocking)
    delivery_target = bool(labels["delivery_ready"])
    human_score = float(labels["human_quality_score"])
    mismatch_tags: list[str] = []
    if v03 >= 72 and not delivery_target:
        mismatch_tags.append("v03_false_positive")
    if v03 < 60 and delivery_target:
        mismatch_tags.append("v03_false_negative")
    if nat_score < 20 and float(labels["naturalness_label"]) >= 70:
        mismatch_tags.append("naturalness_model_false_positive")
    if signal >= 72 and not delivery_target:
        mismatch_tags.append("signal_false_positive")
    if signal < 60 and delivery_target:
        mismatch_tags.append("signal_false_negative")
    return {
        "id": item["id"],
        "domain": content["domain"],
        "title": content["title"],
        "labels": labels,
        "signals": {
            "v03_score": round(v03, 1),
            "v04_candidate_score": round(v04, 1) if v04 is not None else None,
            "naturalness_model_score": round(nat_score, 1),
            "ai_probability": round(float(nat["ai_probability"]), 4),
            "experimental_signal_score": round(signal, 1),
            "quality_issue_count": len(issues),
            "blocking": blocking,
            "issues": issues[:8],
        },
        "gaps": {
            "v03_minus_human": round(v03 - human_score, 1),
            "v04_minus_human": round(v04 - human_score, 1) if v04 is not None else None,
            "naturalness_model_minus_label": round(nat_score - float(labels["naturalness_label"]), 1),
            "signal_minus_human": round(signal - human_score, 1),
        },
        "mismatch_tags": mismatch_tags,
    }


def build_report(labels_path: Path) -> dict[str, Any]:
    label_doc = _load_json(labels_path)
    rows = [evaluate_item(item) for item in label_doc["items"]]
    mismatch_counts: dict[str, int] = {}
    for row in rows:
        for tag in row["mismatch_tags"]:
            mismatch_counts[tag] = mismatch_counts.get(tag, 0) + 1
    ready_rows = [row for row in rows if row["labels"]["delivery_ready"]]
    blocked_rows = [row for row in rows if not row["labels"]["delivery_ready"]]

    def avg(items: list[dict], path: tuple[str, str]) -> float | None:
        vals = [item[path[0]][path[1]] for item in items if item[path[0]].get(path[1]) is not None]
        return round(float(sum(vals) / len(vals)), 2) if vals else None

    return {
        "labels_file": str(labels_path),
        "total": len(rows),
        "delivery_ready_count": len(ready_rows),
        "not_ready_count": len(blocked_rows),
        "mismatch_counts": mismatch_counts,
        "averages": {
            "ready_v03": avg(ready_rows, ("signals", "v03_score")),
            "not_ready_v03": avg(blocked_rows, ("signals", "v03_score")),
            "ready_v04": avg(ready_rows, ("signals", "v04_candidate_score")),
            "not_ready_v04": avg(blocked_rows, ("signals", "v04_candidate_score")),
            "ready_naturalness_model": avg(ready_rows, ("signals", "naturalness_model_score")),
            "not_ready_naturalness_model": avg(blocked_rows, ("signals", "naturalness_model_score")),
            "ready_experimental_signal": avg(ready_rows, ("signals", "experimental_signal_score")),
            "not_ready_experimental_signal": avg(blocked_rows, ("signals", "experimental_signal_score")),
        },
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build composite quality report from golden labels")
    parser.add_argument("labels", type=Path)
    parser.add_argument("--output", type=Path, default=Path("quality/composite_quality_report.v01.json"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = build_report(args.labels)
    out = args.output if args.output.is_absolute() else ROOT / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"report={out}")
        print(f"total={report['total']} ready={report['delivery_ready_count']} not_ready={report['not_ready_count']}")
        print(f"mismatch_counts={report['mismatch_counts']}")
        print(f"averages={report['averages']}")
        for row in report["rows"]:
            tags = ",".join(row["mismatch_tags"]) or "-"
            print(
                f"{row['id']} domain={row['domain']} human={row['labels']['human_quality_score']} "
                f"ready={row['labels']['delivery_ready']} v03={row['signals']['v03_score']} "
                f"v04={row['signals']['v04_candidate_score']} nat={row['signals']['naturalness_model_score']} "
                f"signal={row['signals']['experimental_signal_score']} tags={tags}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
