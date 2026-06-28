#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Conservatively adjudicate Claude/Kimi golden review disagreements.

This tool only promotes low-risk disagreements where both judges are close on
the absolute score and neither judge reports fact/industry risk. Hard
disagreements stay out of training.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "quality" / "review_packets" / "adjudicated"

RISK_FLAGS = {"fact_or_industry_risk", "second_review_failed", "low_kimi_confidence", "primary_review_failed"}
RISK_TAGS = {"fact_overclaim", "wrong_industry", "title_unreadable"}
TRUE_VALUES = {"true", "1", "yes", "y", "是", "可交付", "ready"}
NOT_READY_SCORE_CAP = 84


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        text = _clean(value)
        return float(text) if text else default
    except Exception:
        return default


def _to_int(value: Any, default: int = 3, *, lo: int = 1, hi: int = 5) -> int:
    try:
        n = int(round(float(_clean(value))))
    except Exception:
        n = default
    return max(lo, min(hi, n))


def _flag_set(value: Any) -> set[str]:
    return {part.strip() for part in _clean(value).split("|") if part.strip()}


def _tag_list(*values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, list):
            parts = [str(part).strip() for part in value if str(part).strip()]
        else:
            text = _clean(value)
            parts = [part.strip() for part in text.replace("，", "|").replace(",", "|").split("|") if part.strip()]
        for part in parts:
            if part not in seen:
                out.append(part)
                seen.add(part)
    return out


def _bool_text(value: Any) -> str:
    return "true" if _clean(value).lower() in TRUE_VALUES else "false"


def _load_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            return [dict(row) for row in csv.DictReader(fh)]
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _skip_reason(row: dict[str, Any], *, max_score_gap: float, min_kimi_confidence: float) -> str:
    if _clean(row.get("judge_consensus")).lower() == "agree":
        return "already_consensus"
    if _clean(row.get("kimi_review_status")).lower() != "ok":
        return "second_review_not_ok"
    if not _clean(row.get("title") or row.get("note_title")) or not _clean(row.get("body") or row.get("desc") or row.get("note_content")):
        return "missing_title_or_body"
    flags = _flag_set(row.get("judge_disagreement_flags"))
    if flags & RISK_FLAGS:
        return "risk_flags"
    ai_fact = _clean(row.get("ai_fact_status")).lower()
    kimi_fact = _clean(row.get("kimi_fact_status")).lower()
    if ai_fact in {"overclaim", "wrong_industry"} or kimi_fact in {"overclaim", "wrong_industry", "uncertain"}:
        return "fact_or_industry_risk"
    if _to_float(row.get("kimi_confidence")) < min_kimi_confidence:
        return "low_kimi_confidence"
    ai_score = _to_float(row.get("ai_human_quality_score"), -1)
    kimi_score = _to_float(row.get("kimi_human_quality_score"), -1)
    if ai_score < 0 or kimi_score < 0:
        return "missing_score"
    if abs(ai_score - kimi_score) > max_score_gap:
        return "score_gap_too_large"
    tags = set(_tag_list(row.get("ai_failure_tags"), row.get("kimi_failure_tags")))
    if "wrong_industry" in tags or "fact_overclaim" in tags:
        return "risk_tags"
    return ""


def _quality_score(ai_score: float, kimi_score: float) -> int:
    gap = abs(ai_score - kimi_score)
    if gap <= 8:
        score = round((ai_score + kimi_score) / 2)
    else:
        score = round(min(ai_score, kimi_score))
    return int(max(0, min(100, score)))


def _label_source_for(row: dict[str, Any]) -> tuple[str, str]:
    reviewer = _clean(row.get("ai_reviewer")).lower()
    if "claude" in reviewer:
        return "ai_rubric_adjudicated_claude_kimi_v0.1", "ai_rubric_adjudicator_claude_kimi_v0.1"
    return "ai_rubric_adjudicated_heuristic_kimi_v0.1", "ai_rubric_adjudicator_heuristic_kimi_v0.1"


def adjudicate_rows(
    rows: list[dict[str, Any]],
    *,
    max_score_gap: float = 12.0,
    min_kimi_confidence: float = 0.7,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    promoted: list[dict[str, Any]] = []
    skipped = Counter()
    by_domain = Counter()
    score_buckets = Counter()

    for row in rows:
        reason = _skip_reason(row, max_score_gap=max_score_gap, min_kimi_confidence=min_kimi_confidence)
        if reason:
            skipped[reason] += 1
            continue

        ai_score = _to_float(row.get("ai_human_quality_score"))
        kimi_score = _to_float(row.get("kimi_human_quality_score"))
        score = _quality_score(ai_score, kimi_score)
        tags = _tag_list(row.get("ai_failure_tags"), row.get("kimi_failure_tags"))
        serious_tags = set(tags) & RISK_TAGS
        ready = (
            _bool_text(row.get("ai_delivery_ready")) == "true"
            and _bool_text(row.get("kimi_delivery_ready")) == "true"
            and score >= 78
            and not serious_tags
        )
        if not ready and score >= 85:
            score = NOT_READY_SCORE_CAP
        fact_status = _clean(row.get("kimi_fact_status")) or _clean(row.get("ai_fact_status")) or "safe"
        if fact_status == "uncertain":
            fact_status = "unknown"
        if fact_status not in {"safe", "unknown", "overclaim", "wrong_industry"}:
            fact_status = "safe"

        out = dict(row)
        out["human_label_status"] = "completed"
        out["human_quality_score"] = score
        out["delivery_ready"] = "true" if ready else "false"
        out["naturalness_label"] = int(round((_to_float(row.get("ai_naturalness_label"), 70) + _to_float(row.get("kimi_naturalness_label"), 70)) / 2))
        out["hook_quality"] = _to_int(round((_to_float(row.get("ai_hook_quality"), 3) + _to_float(row.get("kimi_hook_quality"), 3)) / 2))
        out["body_value"] = _to_int(round((_to_float(row.get("ai_body_value"), 3) + _to_float(row.get("kimi_body_value"), 3)) / 2))
        out["industry_fit"] = _to_int(round((_to_float(row.get("ai_industry_fit"), 3) + _to_float(row.get("kimi_industry_fit"), 3)) / 2))
        out["fact_status"] = fact_status
        out["ai_smell_level"] = max(_to_int(row.get("ai_smell_level"), 3), _to_int(row.get("kimi_ai_smell_level"), 3))
        out["failure_tags"] = "|".join(tags)
        out["rationale"] = (
            f"V0.4保守裁决：Claude/Kimi 分差 {abs(ai_score-kimi_score):.1f}，"
            f"取{'均值' if abs(ai_score-kimi_score) <= 8 else '较低分'} {score}；"
            f"问题标签合并为 {','.join(tags) or '无明显硬伤'}。"
        )[:220]
        label_source, reviewer = _label_source_for(row)
        out["label_source"] = label_source
        out["reviewer"] = reviewer
        out["reviewed_at"] = _now_iso()
        out["review_decision"] = "accept_with_edits"
        out["review_note"] = "Conservative adjudication of low-risk Claude/Kimi disagreement."
        promoted.append(out)
        by_domain[_clean(out.get("domain")) or "未知"] += 1
        score_buckets[int(score // 10 * 10)] += 1

    report = {
        "version": "golden-review-adjudication-v0.1",
        "created_at": _now_iso(),
        "policy": (
            "Only low-risk disagreements are adjudicated: Kimi ok, no fact/industry risk, "
            "Kimi confidence above threshold, and score gap within threshold. Delivery-ready "
            "is true only when both judges agree and score >= 78."
        ),
        "params": {
            "max_score_gap": max_score_gap,
            "min_kimi_confidence": min_kimi_confidence,
        },
        "totals": {
            "rows_seen": len(rows),
            "adjudicated_count": len(promoted),
            "skipped_count": sum(skipped.values()),
        },
        "by_domain": dict(sorted(by_domain.items())),
        "score_buckets": dict(sorted(score_buckets.items())),
        "skipped_reasons": dict(sorted(skipped.items())),
    }
    return promoted, report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Conservatively adjudicate golden review disagreements")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--batch-id", default="")
    parser.add_argument("--max-score-gap", type=float, default=12.0)
    parser.add_argument("--min-kimi-confidence", type=float, default=0.7)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input if args.input.is_absolute() else ROOT / args.input
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    rows = _load_rows(input_path)
    promoted, report = adjudicate_rows(
        rows,
        max_score_gap=args.max_score_gap,
        min_kimi_confidence=args.min_kimi_confidence,
    )
    batch_id = args.batch_id or input_path.stem.replace(".", "_")
    stem = f"{batch_id}_golden_adjudicated"
    csv_path = output_dir / f"{stem}.csv"
    jsonl_path = output_dir / f"{stem}.jsonl"
    report_path = output_dir / f"{stem}.report.json"
    _write_csv(csv_path, promoted)
    _write_jsonl(jsonl_path, promoted)
    report["input"] = str(input_path)
    report["outputs"] = {"csv": str(csv_path), "jsonl": str(jsonl_path), "report": str(report_path)}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"adjudicated={report['totals']['adjudicated_count']} skipped={report['totals']['skipped_count']}")
        print(f"jsonl={jsonl_path}")
        print(f"report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
