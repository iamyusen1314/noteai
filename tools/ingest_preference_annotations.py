#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate and export completed A/B preference annotations."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

from v04_domain_policy import canonical_product_domain  # noqa: E402

DEFAULT_INPUT = ROOT / "quality" / "preference_queue.v01.jsonl"
DEFAULT_OUTPUT_JSONL = ROOT / "quality" / "preference_queue.v01.labeled.jsonl"
DEFAULT_OUTPUT_JSON = ROOT / "quality" / "preference_labels.v01.merged.json"
DEFAULT_REPORT = ROOT / "quality" / "preference_labels.v01.merged.report.json"

WINNERS = {"A", "B", "tie", "skip"}


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
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _split_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    sep = "|" if "|" in text else ","
    return [part.strip() for part in text.split(sep) if part.strip()]


def _parse_margin(value: Any, errors: list[str]) -> int | None:
    try:
        margin = int(float(str(value).strip()))
    except Exception:
        errors.append("preference_margin must be 0-3")
        return None
    if margin < 0 or margin > 3:
        errors.append("preference_margin must be 0-3")
        return None
    return margin


def _parse_delivery_ready(value: Any) -> bool | str:
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "是"}:
        return True
    if text in {"false", "0", "no", "n", "否"}:
        return False
    return ""


def _is_completed(row: dict[str, Any]) -> bool:
    winner = str(row.get("winner") or "").strip()
    return winner in WINNERS


def validate_preference_row(row: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    pair_id = str(row.get("pair_id") or "").strip()
    winner = str(row.get("winner") or "").strip()
    if not pair_id:
        errors.append("pair_id missing")
    if winner not in WINNERS:
        errors.append("winner must be A/B/tie/skip")
    for side in ("a", "b"):
        if not str(row.get(f"variant_{side}_title") or "").strip():
            errors.append(f"variant_{side}_title missing")
        if not str(row.get(f"variant_{side}_body") or "").strip():
            errors.append(f"variant_{side}_body missing")

    margin = _parse_margin(row.get("preference_margin", 0), errors)
    reason_tags = _split_tags(row.get("reason_tags"))
    loser_tags = _split_tags(row.get("loser_failure_tags"))
    rationale = str(row.get("rationale") or "").strip()
    if winner in {"A", "B"}:
        if margin == 0:
            warnings.append("A/B winner with margin=0")
        if not reason_tags:
            warnings.append("A/B winner without reason_tags")
        if not rationale:
            warnings.append("A/B winner without rationale")
    if winner == "tie" and margin not in {0, None}:
        warnings.append("tie should normally use margin=0")
    if errors:
        return None, errors, warnings

    out = dict(row)
    out["label_status"] = "completed" if row.get("label_status") == "needs_label" else row.get("label_status", "completed")
    out["winner"] = winner
    out["preference_margin"] = margin
    out["delivery_ready_winner"] = _parse_delivery_ready(row.get("delivery_ready_winner"))
    out["domain"] = canonical_product_domain(row.get("domain"))
    out["reason_tags"] = "|".join(reason_tags)
    out["loser_failure_tags"] = "|".join(loser_tags)
    out["rationale"] = rationale
    return out, errors, warnings


def _to_schema_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "pair_id": row["pair_id"],
        "task_id": row.get("task_id", ""),
        "domain": row.get("domain", ""),
        "task_context": row.get("task_context", ""),
        "comparison_focus": _split_tags(row.get("comparison_focus")),
        "variant_a": {
            "id": row.get("variant_a_id", ""),
            "origin": row.get("variant_a_origin", ""),
            "title": row.get("variant_a_title", ""),
            "body": row.get("variant_a_body", ""),
            "score": row.get("variant_a_score") if row.get("variant_a_score") != "" else None,
            "source_file": row.get("variant_a_source_file", ""),
        },
        "variant_b": {
            "id": row.get("variant_b_id", ""),
            "origin": row.get("variant_b_origin", ""),
            "title": row.get("variant_b_title", ""),
            "body": row.get("variant_b_body", ""),
            "score": row.get("variant_b_score") if row.get("variant_b_score") != "" else None,
            "source_file": row.get("variant_b_source_file", ""),
        },
        "labels": {
            "winner": row.get("winner", ""),
            "preference_margin": row.get("preference_margin", 0),
            "delivery_ready_winner": row.get("delivery_ready_winner", ""),
            "reason_tags": _split_tags(row.get("reason_tags")),
            "loser_failure_tags": _split_tags(row.get("loser_failure_tags")),
            "rationale": row.get("rationale", ""),
            "reviewer": row.get("reviewer", ""),
            "reviewed_at": row.get("reviewed_at", ""),
            "label_source": row.get("label_source", ""),
            "judge_consensus": row.get("judge_consensus", ""),
            "judge_disagreement_flags": _split_tags(row.get("judge_disagreement_flags")),
        },
    }


def ingest_preference_annotations(
    *,
    input_path: Path | list[Path] = DEFAULT_INPUT,
    output_jsonl: Path = DEFAULT_OUTPUT_JSONL,
    output_json: Path = DEFAULT_OUTPUT_JSON,
    report_path: Path = DEFAULT_REPORT,
) -> dict[str, Any]:
    input_paths = input_path if isinstance(input_path, list) else [input_path]
    rows: list[dict[str, Any]] = []
    for path in input_paths:
        rows.extend(_load_rows(path))
    labeled: list[dict[str, Any]] = []
    schema_items: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    skipped_unlabeled = 0
    skipped_skip = 0
    skipped_duplicate = 0
    seen_pair_ids: set[str] = set()

    for row in rows:
        pair_id = str(row.get("pair_id") or "")
        if not _is_completed(row):
            skipped_unlabeled += 1
            continue
        normalized, row_errors, row_warnings = validate_preference_row(row)
        if row_errors:
            errors.append({"id": pair_id, "errors": row_errors})
            continue
        for warning in row_warnings:
            warnings.append({"id": pair_id, "warning": warning})
        if normalized and normalized.get("winner") == "skip":
            skipped_skip += 1
            continue
        if normalized:
            normalized_pair_id = str(normalized.get("pair_id") or "")
            if normalized_pair_id in seen_pair_ids:
                skipped_duplicate += 1
                continue
            seen_pair_ids.add(normalized_pair_id)
            labeled.append(normalized)
            schema_items.append(_to_schema_item(normalized))

    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_jsonl, labeled)
    output_doc = {
        "version": "preference-labels-v0.1",
        "description": "Completed A/B preference labels for v0.4-composite training.",
        "items": schema_items,
        "metadata": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "inputs": [str(path) for path in input_paths],
            "labeled_count": len(labeled),
        },
    }
    output_json.write_text(json.dumps(output_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "version": "preference-ingest-report-v0.1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "inputs": [str(path) for path in input_paths],
        "output_jsonl": str(output_jsonl),
        "output_json": str(output_json),
        "rows_seen": len(rows),
        "labeled_count": len(labeled),
        "skipped_unlabeled": skipped_unlabeled,
        "skipped_skip": skipped_skip,
        "skipped_duplicate": skipped_duplicate,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors[:100],
        "warnings": warnings[:100],
        "decision": "failed" if errors else "ok",
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest completed preference annotations")
    parser.add_argument("--input", action="append", help="Input JSONL/CSV. Can be passed multiple times.")
    parser.add_argument("--output-jsonl", default=str(DEFAULT_OUTPUT_JSONL))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_paths = [Path(item) for item in (args.input or [str(DEFAULT_INPUT)])]
    report = ingest_preference_annotations(
        input_path=input_paths,
        output_jsonl=Path(args.output_jsonl),
        output_json=Path(args.output_json),
        report_path=Path(args.report),
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"decision={report['decision']}")
        print(f"labeled={report['labeled_count']} skipped={report['skipped_unlabeled']} errors={report['error_count']}")
        print(f"output_jsonl={report['output_jsonl']}")
    return 1 if report["decision"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
