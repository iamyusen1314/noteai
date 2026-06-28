#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate and merge completed golden annotations into training labels."""

from __future__ import annotations

import argparse
import csv
import hashlib
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

DEFAULT_INPUT = ROOT / "quality" / "annotation_queue.v01.jsonl"
DEFAULT_SEED = ROOT / "quality" / "golden_labels.v01.seed.json"
DEFAULT_OUTPUT = ROOT / "quality" / "golden_labels.v01.merged.json"
DEFAULT_REPORT = ROOT / "quality" / "golden_labels.v01.merged.report.json"

FACT_STATUS = {"verified", "safe", "unknown", "overclaim"}
TRUE_VALUES = {"true", "1", "yes", "y", "是", "可交付", "ready"}
FALSE_VALUES = {"false", "0", "no", "n", "否", "不可交付", "not_ready"}


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


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _stable_text_hash(title: Any, body: Any) -> str:
    text = f"{str(title or '').strip()}\n{str(body or '').strip()}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _item_text_hash(item: dict[str, Any]) -> str:
    trace_hash = str(item.get("source_trace", {}).get("text_hash") or "").strip()
    if trace_hash:
        return trace_hash
    source = item.get("content_source", {})
    return _stable_text_hash(source.get("title"), source.get("body"))


def _parse_float(value: Any, field: str, errors: list[str], *, lo: float = 0.0, hi: float = 100.0) -> float | None:
    try:
        score = float(str(value).strip())
    except Exception:
        errors.append(f"{field}: must be a number")
        return None
    if score < lo or score > hi:
        errors.append(f"{field}: must be in [{lo}, {hi}]")
        return None
    return score


def _parse_int(value: Any, field: str, errors: list[str], *, lo: int = 1, hi: int = 5) -> int | None:
    try:
        n = int(float(str(value).strip()))
    except Exception:
        errors.append(f"{field}: must be an integer")
        return None
    if n < lo or n > hi:
        errors.append(f"{field}: must be in [{lo}, {hi}]")
        return None
    return n


def _parse_bool(value: Any, field: str, errors: list[str]) -> bool | None:
    text = str(value).strip().lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    errors.append(f"{field}: must be true/false")
    return None


def _split_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    sep = "|" if "|" in text else ","
    return [part.strip() for part in text.split(sep) if part.strip()]


def _is_completed(row: dict[str, Any]) -> bool:
    status = str(row.get("human_label_status", "")).strip()
    if status in {"locked_seed", "completed", "labeled", "reviewed"}:
        return True
    required = ("human_quality_score", "delivery_ready", "naturalness_label", "fact_status", "ai_smell_level")
    return all(str(row.get(field, "")).strip() for field in required)


def row_to_golden_item(row: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    row_id = str(row.get("annotation_id") or row.get("id") or "").strip()
    title = str(row.get("title") or "").strip()
    body = str(row.get("body") or "").strip()
    raw_domain = str(row.get("domain") or "").strip()
    domain = canonical_product_domain(raw_domain)
    if not row_id:
        errors.append("annotation_id missing")
    if not title:
        errors.append("title missing")
    if not body:
        errors.append("body missing")
    if not raw_domain:
        errors.append("domain missing")

    human_score = _parse_float(row.get("human_quality_score"), "human_quality_score", errors)
    delivery_ready = _parse_bool(row.get("delivery_ready"), "delivery_ready", errors)
    naturalness = _parse_float(row.get("naturalness_label"), "naturalness_label", errors)
    hook_quality = _parse_int(row.get("hook_quality", 3), "hook_quality", errors) if str(row.get("hook_quality", "")).strip() else 0
    body_value = _parse_int(row.get("body_value", 3), "body_value", errors) if str(row.get("body_value", "")).strip() else 0
    industry_fit = _parse_int(row.get("industry_fit", 3), "industry_fit", errors) if str(row.get("industry_fit", "")).strip() else 0
    fact_status = str(row.get("fact_status") or "").strip()
    if fact_status not in FACT_STATUS:
        errors.append(f"fact_status: must be one of {sorted(FACT_STATUS)}")
    ai_smell = _parse_int(row.get("ai_smell_level"), "ai_smell_level", errors)

    if human_score is not None and delivery_ready is not None:
        if delivery_ready and human_score < 70:
            warnings.append("delivery_ready=true with score < 70")
        if not delivery_ready and human_score >= 85:
            warnings.append("delivery_ready=false with score >= 85")

    if errors:
        return None, errors, warnings

    labels: dict[str, Any] = {
        "human_quality_score": human_score,
        "delivery_ready": delivery_ready,
        "naturalness_label": naturalness,
        "fact_status": fact_status,
        "ai_smell_level": ai_smell,
        "failure_tags": _split_tags(row.get("failure_tags")),
        "rationale": str(row.get("rationale") or "").strip(),
    }
    if hook_quality:
        labels["hook_quality"] = hook_quality
    if body_value:
        labels["body_value"] = body_value
    if industry_fit:
        labels["industry_fit"] = industry_fit
    if row.get("reviewer"):
        labels["reviewer"] = str(row.get("reviewer"))
    if row.get("reviewed_at"):
        labels["reviewed_at"] = str(row.get("reviewed_at"))
    if row.get("label_source"):
        labels["label_source"] = str(row.get("label_source"))
    if row.get("judge_consensus"):
        labels["judge_consensus"] = str(row.get("judge_consensus"))
    if row.get("judge_disagreement_flags"):
        labels["judge_disagreement_flags"] = _split_tags(row.get("judge_disagreement_flags"))

    item = {
        "id": row_id,
        "content_source": {
            "type": "inline",
            "file": "",
            "domain": domain,
            "title": title,
            "body": body,
            "local_time": str(row.get("local_time") or "2026062412"),
        },
        "labels": labels,
        "source_trace": {
            "annotation_id": row_id,
            "note_id": str(row.get("note_id") or ""),
            "sample_bucket": str(row.get("sample_bucket") or ""),
            "sample_source": str(row.get("sample_source") or ""),
            "source_file": str(row.get("source_file") or ""),
            "source_row": row.get("source_row", ""),
            "text_hash": str(row.get("text_hash") or ""),
        },
    }
    return item, errors, warnings


def ingest_golden_annotations(
    *,
    input_path: Path = DEFAULT_INPUT,
    seed_path: Path = DEFAULT_SEED,
    output_path: Path = DEFAULT_OUTPUT,
    report_path: Path = DEFAULT_REPORT,
) -> dict[str, Any]:
    rows = _load_rows(input_path)
    seed_doc = _load_json(seed_path) if seed_path.exists() else {"version": "golden-labels-v0.1", "items": []}
    seed_items = list(seed_doc.get("items", []))
    seen_ids = {item.get("id") for item in seed_items}
    seen_text_hashes = {_item_text_hash(item) for item in seed_items if _item_text_hash(item)}
    items = list(seed_items)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    duplicate_texts: list[dict[str, Any]] = []
    imported = 0
    skipped_unlabeled = 0
    skipped_locked_seed = 0
    skipped_duplicate_text = 0

    for row in rows:
        row_id = str(row.get("annotation_id") or row.get("id") or "")
        if str(row.get("human_label_status", "")).strip() == "locked_seed":
            skipped_locked_seed += 1
            continue
        if not _is_completed(row):
            skipped_unlabeled += 1
            continue
        item, row_errors, row_warnings = row_to_golden_item(row)
        if row_errors:
            errors.append({"id": row_id, "errors": row_errors})
            continue
        for warning in row_warnings:
            warnings.append({"id": row_id, "warning": warning})
        if not item:
            continue
        text_hash = _item_text_hash(item)
        if text_hash and text_hash in seen_text_hashes:
            skipped_duplicate_text += 1
            duplicate_texts.append({"id": item["id"], "text_hash": text_hash})
            continue
        if item["id"] not in seen_ids:
            items.append(item)
            seen_ids.add(item["id"])
            if text_hash:
                seen_text_hashes.add(text_hash)
            imported += 1

    merged = {
        "version": "golden-labels-v0.1",
        "description": "Merged seed + completed human annotations for v0.4-composite training.",
        "items": items,
        "metadata": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "seed_file": str(seed_path),
            "annotation_input": str(input_path),
            "seed_count": len(seed_items),
            "imported_count": imported,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "version": "golden-ingest-report-v0.1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input": str(input_path),
        "output": str(output_path),
        "seed_count": len(seed_items),
        "rows_seen": len(rows),
        "imported_count": imported,
        "skipped_unlabeled": skipped_unlabeled,
        "skipped_locked_seed": skipped_locked_seed,
        "skipped_duplicate_text": skipped_duplicate_text,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "duplicate_texts": duplicate_texts[:100],
        "errors": errors[:100],
        "warnings": warnings[:100],
        "decision": "failed" if errors else "ok",
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest completed golden annotations")
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--seed", default=str(DEFAULT_SEED))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = ingest_golden_annotations(
        input_path=Path(args.input),
        seed_path=Path(args.seed),
        output_path=Path(args.output),
        report_path=Path(args.report),
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"decision={report['decision']}")
        print(f"imported={report['imported_count']} skipped={report['skipped_unlabeled']} errors={report['error_count']}")
        print(f"output={report['output']}")
    return 1 if report["decision"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
