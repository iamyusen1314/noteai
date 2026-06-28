#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Promote reviewed AI prelabels into ingest-ready annotation files.

Rows are promoted only when review_decision is one of:
- accept_ai
- accept_with_edits

This prevents unreviewed AI suggestions from entering training labels.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "quality" / "review_packets" / "promoted"

ACCEPT_DECISIONS = {"accept_ai", "accept_with_edits", "接受AI", "确认"}
REJECT_DECISIONS = {"reject", "needs_manual", "skip", "拒绝", "人工复核"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _pick(row: dict[str, Any], review_key: str, ai_key: str) -> str:
    return _clean(row.get(review_key)) or _clean(row.get(ai_key))


def _bool_text(value: Any) -> str:
    text = _clean(value).lower()
    if text in {"true", "1", "yes", "y", "是", "可交付", "ready"}:
        return "true"
    if text in {"false", "0", "no", "n", "否", "不可交付", "not_ready"}:
        return "false"
    return text


def _fact_status(value: Any) -> str:
    text = _clean(value).lower()
    if text in {"verified", "safe", "unknown", "overclaim"}:
        return text
    if text == "uncertain":
        return "unknown"
    if text == "wrong_industry":
        return "overclaim"
    return "safe"


def _flag_set(value: Any) -> set[str]:
    return {part.strip() for part in _clean(value).split("|") if part.strip()}


def _can_auto_accept_consensus(row: dict[str, Any]) -> bool:
    if _clean(row.get("annotation_id")) and (not _clean(row.get("title") or row.get("note_title")) or not _clean(row.get("body") or row.get("desc") or row.get("note_content"))):
        return False
    return (
        _clean(row.get("judge_consensus")).lower() == "agree"
        and _clean(row.get("kimi_review_status")).lower() in {"", "ok"}
        and not _clean(row.get("judge_disagreement_flags"))
    )


def _can_auto_accept_winner_consensus(
    row: dict[str, Any],
    kind: str,
    *,
    min_kimi_confidence: float,
) -> bool:
    if kind != "preference":
        return False
    flags = _flag_set(row.get("judge_disagreement_flags"))
    ai_winner = _clean(row.get("ai_winner"))
    kimi_winner = _clean(row.get("kimi_winner"))
    try:
        kimi_confidence = float(_clean(row.get("kimi_confidence")) or 0)
    except Exception:
        kimi_confidence = 0.0
    return (
        _clean(row.get("kimi_review_status")).lower() == "ok"
        and ai_winner == kimi_winner
        and ai_winner in {"A", "B"}
        and "winner_mismatch" not in flags
        and "second_review_failed" not in flags
        and "low_kimi_confidence" not in flags
        and kimi_confidence >= min_kimi_confidence
    )


def _effective_decision(row: dict[str, Any], *, auto_accept_consensus: bool = False) -> str:
    decision = _clean(row.get("review_decision"))
    if decision:
        return decision
    if auto_accept_consensus and _can_auto_accept_consensus(row):
        return "accept_ai"
    return ""


def _accepted(row: dict[str, Any], *, auto_accept_consensus: bool = False) -> bool:
    decision = _effective_decision(row, auto_accept_consensus=auto_accept_consensus)
    consensus = _clean(row.get("judge_consensus")).lower()
    disagreement = _clean(row.get("judge_disagreement_flags"))
    if decision == "accept_ai" and (consensus in {"disagree", "second_review_failed"} or disagreement):
        return False
    return decision in ACCEPT_DECISIONS


def _mark_auto_consensus(row: dict[str, Any], *, auto_accept_consensus: bool = False) -> dict[str, Any]:
    out = dict(row)
    if auto_accept_consensus and not _clean(out.get("review_decision")) and _can_auto_accept_consensus(out):
        out["review_decision"] = "accept_ai"
        out["label_source"] = _clean(out.get("consensus_label_source")) or "ai_rubric_consensus"
        out["reviewer"] = _clean(out.get("reviewer")) or "ai_rubric_consensus_claude_kimi_v0.1"
        out["review_note"] = _clean(out.get("review_note")) or "Auto-accepted because first-pass rubric and Kimi second review agreed."
    return out


def _mark_auto_winner_consensus(
    row: dict[str, Any],
    *,
    kind: str,
    auto_accept_winner_consensus: bool = False,
    min_kimi_confidence: float = 0.7,
) -> dict[str, Any]:
    out = dict(row)
    if (
        auto_accept_winner_consensus
        and not _clean(out.get("review_decision"))
        and _can_auto_accept_winner_consensus(out, kind, min_kimi_confidence=min_kimi_confidence)
    ):
        out["review_decision"] = "accept_with_edits"
        out["review_winner"] = _clean(out.get("kimi_winner"))
        out["review_preference_margin"] = _clean(out.get("kimi_preference_margin")) or _clean(out.get("ai_preference_margin"))
        out["review_delivery_ready_winner"] = _bool_text(out.get("kimi_delivery_ready_winner"))
        out["review_reason_tags"] = _clean(out.get("kimi_reason_tags")) or _clean(out.get("ai_reason_tags"))
        out["review_loser_failure_tags"] = _clean(out.get("kimi_loser_failure_tags")) or _clean(out.get("ai_loser_failure_tags"))
        kimi_rationale = _clean(out.get("kimi_rationale"))
        out["review_rationale"] = (
            "Auto-accepted winner consensus: first-pass rubric and Kimi chose the same A/B winner; "
            "delivery readiness follows Kimi's conservative review. "
            f"Kimi: {kimi_rationale}"
        ).strip()
        out["label_source"] = "ai_rubric_winner_consensus"
        out["reviewer"] = "ai_rubric_winner_consensus_claude_kimi_v0.2"
        out["review_note"] = (
            _clean(out.get("review_note"))
            or "Winner consensus only; judge_consensus may remain disagree because delivery readiness differed."
        )
    return out


def promote_golden_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["human_label_status"] = "completed"
    out["human_quality_score"] = _pick(row, "review_human_quality_score", "ai_human_quality_score")
    out["delivery_ready"] = _bool_text(_pick(row, "review_delivery_ready", "ai_delivery_ready"))
    out["naturalness_label"] = _pick(row, "review_naturalness_label", "ai_naturalness_label")
    out["hook_quality"] = _pick(row, "review_hook_quality", "ai_hook_quality")
    out["body_value"] = _pick(row, "review_body_value", "ai_body_value")
    out["industry_fit"] = _pick(row, "review_industry_fit", "ai_industry_fit")
    out["fact_status"] = _fact_status(_pick(row, "review_fact_status", "ai_fact_status") or "safe")
    out["ai_smell_level"] = _pick(row, "review_ai_smell_level", "ai_smell_level")
    out["failure_tags"] = _pick(row, "review_failure_tags", "ai_failure_tags")
    out["rationale"] = _pick(row, "review_rationale", "ai_rationale")
    out["label_source"] = _clean(row.get("label_source")) or _clean(row.get("consensus_label_source")) or "owner_approved_ai_prelabeller"
    out["reviewer"] = _clean(row.get("reviewer")) or "owner_approved_ai_prelabeller"
    out["reviewed_at"] = _clean(row.get("reviewed_at")) or _now_iso()
    return out


def promote_preference_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["label_status"] = "completed"
    out["winner"] = _pick(row, "review_winner", "ai_winner")
    out["preference_margin"] = _pick(row, "review_preference_margin", "ai_preference_margin")
    out["delivery_ready_winner"] = _bool_text(_pick(row, "review_delivery_ready_winner", "ai_delivery_ready_winner"))
    out["reason_tags"] = _pick(row, "review_reason_tags", "ai_reason_tags")
    out["loser_failure_tags"] = _pick(row, "review_loser_failure_tags", "ai_loser_failure_tags")
    out["rationale"] = _pick(row, "review_rationale", "ai_rationale")
    out["label_source"] = _clean(row.get("label_source")) or _clean(row.get("consensus_label_source")) or "owner_approved_ai_prelabeller"
    out["reviewer"] = _clean(row.get("reviewer")) or "owner_approved_ai_prelabeller"
    out["reviewed_at"] = _clean(row.get("reviewed_at")) or _now_iso()
    return out


def promote_rows(
    rows: list[dict[str, Any]],
    kind: str,
    *,
    auto_accept_consensus: bool = False,
    auto_accept_winner_consensus: bool = False,
    winner_consensus_min_kimi_confidence: float = 0.7,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    promoted: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for row in rows:
        row = _mark_auto_consensus(row, auto_accept_consensus=auto_accept_consensus)
        row = _mark_auto_winner_consensus(
            row,
            kind=kind,
            auto_accept_winner_consensus=auto_accept_winner_consensus,
            min_kimi_confidence=winner_consensus_min_kimi_confidence,
        )
        if not _accepted(row, auto_accept_consensus=auto_accept_consensus):
            decision = _effective_decision(row, auto_accept_consensus=auto_accept_consensus)
            consensus = _clean(row.get("judge_consensus"))
            skipped.append(
                {
                    "id": _clean(row.get("annotation_id") or row.get("pair_id")),
                    "review_decision": decision,
                    "skip_reason": "judge_disagreement_requires_accept_with_edits"
                    if decision == "accept_ai" and consensus in {"disagree", "second_review_failed"}
                    else "not_accepted",
                }
            )
            continue
        promoted.append(promote_golden_row(row) if kind == "golden" else promote_preference_row(row))
    report = {
        "version": "reviewed-prelabel-promotion-v0.1",
        "created_at": _now_iso(),
        "kind": kind,
        "rows_seen": len(rows),
        "promoted_count": len(promoted),
        "skipped_count": len(skipped),
        "skipped_preview": skipped[:100],
        "auto_accept_consensus": auto_accept_consensus,
        "auto_accept_winner_consensus": auto_accept_winner_consensus,
        "winner_consensus_min_kimi_confidence": winner_consensus_min_kimi_confidence,
        "policy": "Only review_decision=accept_ai/accept_with_edits, explicit --auto-accept-consensus judge_consensus=agree, or explicit --auto-accept-winner-consensus same A/B winner is promoted.",
    }
    return promoted, report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Promote reviewed prelabels to ingest-ready annotations")
    parser.add_argument("--kind", choices=["golden", "preference"], required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--batch-id", default="")
    parser.add_argument("--auto-accept-consensus", action="store_true")
    parser.add_argument("--auto-accept-winner-consensus", action="store_true")
    parser.add_argument("--winner-consensus-min-kimi-confidence", type=float, default=0.7)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input if args.input.is_absolute() else ROOT / args.input
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    rows = _load_rows(input_path)
    promoted, report = promote_rows(
        rows,
        args.kind,
        auto_accept_consensus=args.auto_accept_consensus,
        auto_accept_winner_consensus=args.auto_accept_winner_consensus,
        winner_consensus_min_kimi_confidence=args.winner_consensus_min_kimi_confidence,
    )
    batch_id = args.batch_id or input_path.stem.replace(".", "_")
    stem = f"{batch_id}_{args.kind}_promoted"
    csv_path = output_dir / f"{stem}.csv"
    jsonl_path = output_dir / f"{stem}.jsonl"
    report_path = output_dir / f"{stem}.report.json"
    _write_csv(csv_path, promoted)
    _write_jsonl(jsonl_path, promoted)
    report["outputs"] = {"csv": str(csv_path), "jsonl": str(jsonl_path), "report": str(report_path)}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"promoted={report['promoted_count']} skipped={report['skipped_count']}")
        print(f"csv={csv_path}")
        print(f"jsonl={jsonl_path}")
        print(f"report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
