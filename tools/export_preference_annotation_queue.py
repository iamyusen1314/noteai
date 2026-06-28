#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export A/B preference annotation queues for generated note variants."""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VERSION = "preference-annotation-queue-v0.1"

DEFAULT_SEED_PATH = ROOT / "quality" / "preference_pairs.v01.seed.json"
DEFAULT_OUTPUT_JSONL = ROOT / "quality" / "preference_queue.v01.jsonl"
DEFAULT_OUTPUT_CSV = ROOT / "quality" / "preference_queue.v01.csv"
DEFAULT_REPORT = ROOT / "quality" / "preference_queue.v01.report.json"

PREFERENCE_COLUMNS = [
    "pair_id",
    "version",
    "label_status",
    "priority",
    "task_id",
    "domain",
    "task_context",
    "comparison_focus",
    "variant_a_id",
    "variant_a_origin",
    "variant_a_title",
    "variant_a_body",
    "variant_a_body_char_len",
    "variant_a_score",
    "variant_a_source_file",
    "variant_b_id",
    "variant_b_origin",
    "variant_b_title",
    "variant_b_body",
    "variant_b_body_char_len",
    "variant_b_score",
    "variant_b_source_file",
    "winner",
    "preference_margin",
    "delivery_ready_winner",
    "reason_tags",
    "loser_failure_tags",
    "rationale",
    "reviewer",
    "reviewed_at",
    "pair_text_hash",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_hash(*parts: Any, length: int = 12) -> str:
    text = "\n".join(str(part or "") for part in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def _slug(text: str) -> str:
    keep = []
    for ch in str(text or "").lower():
        if ch.isascii() and (ch.isalnum() or ch in {"_", "-"}):
            keep.append(ch)
        elif ch.isspace():
            keep.append("_")
    out = "".join(keep).strip("_")
    return out or _stable_hash(text, length=8)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_path(path: str | Path) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    return p


def _get_path(data: Any, dotted_path: str, default: Any = "") -> Any:
    current = data
    for part in str(dotted_path or "").split("."):
        if part == "":
            continue
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return default
        elif isinstance(current, dict):
            if part not in current:
                return default
            current = current[part]
        else:
            return default
    return default if current is None else current


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_score(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return round(float(value), 4)
    except Exception:
        return None


def _variant_from_spec(spec: dict[str, Any]) -> dict[str, Any]:
    source_file = spec.get("source_file", "")
    data: Any = {}
    if source_file:
        data = _load_json(_resolve_path(source_file))
    title = spec.get("title")
    body = spec.get("body")
    score = spec.get("score")
    if title is None:
        title = _get_path(data, spec.get("title_path", "title"), "")
    if body is None:
        body = _get_path(data, spec.get("body_path", "body"), "")
    if score is None and spec.get("score_path"):
        score = _get_path(data, spec.get("score_path", ""), None)
    title = _clean_text(title)
    body = _clean_text(body)
    if not title or not body:
        raise ValueError(f"Variant {spec.get('id')} missing title/body from {source_file}")
    return {
        "id": spec["id"],
        "origin": spec.get("origin", ""),
        "title": title,
        "body": body,
        "score": _clean_score(score),
        "source_file": source_file,
        "title_path": spec.get("title_path", ""),
        "body_path": spec.get("body_path", ""),
        "score_path": spec.get("score_path", ""),
        "text_hash": _stable_hash(title, body, length=16),
    }


def _lock_key(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted([a, b]))


def _locked_pair_map(task: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for item in task.get("locked_pairs", []):
        out[_lock_key(item["variant_a"], item["variant_b"])] = item
    return out


def _empty_labels() -> dict[str, Any]:
    return {
        "winner": "",
        "preference_margin": "",
        "delivery_ready_winner": "",
        "reason_tags": "",
        "loser_failure_tags": "",
        "rationale": "",
        "reviewer": "",
        "reviewed_at": "",
    }


def _labels_for_pair(locked: dict[str, Any] | None, a_id: str, b_id: str) -> tuple[str, dict[str, Any]]:
    labels = _empty_labels()
    if not locked:
        return "needs_label", labels
    winner_variant = locked.get("winner_variant_id", "")
    if winner_variant == a_id:
        winner = "A"
    elif winner_variant == b_id:
        winner = "B"
    elif winner_variant in {"tie", "skip"}:
        winner = winner_variant
    else:
        winner = ""
    labels.update(
        {
            "winner": winner,
            "preference_margin": locked.get("preference_margin", ""),
            "delivery_ready_winner": locked.get("delivery_ready_winner", ""),
            "reason_tags": "|".join(locked.get("reason_tags", [])),
            "loser_failure_tags": "|".join(locked.get("loser_failure_tags", [])),
            "rationale": locked.get("rationale", ""),
        }
    )
    return "locked_seed", labels


def _priority_for_pair(label_status: str, a: dict[str, Any], b: dict[str, Any]) -> str:
    if label_status == "locked_seed":
        return "high"
    origins = {a.get("origin"), b.get("origin")}
    if "delivery_quality_second_pass" in origins or "manual_natural_rewrite" in origins:
        return "high"
    if "chat_optimize" in " ".join(str(origin) for origin in origins):
        return "medium"
    return "normal"


def _row_for_pair(
    *,
    task: dict[str, Any],
    a: dict[str, Any],
    b: dict[str, Any],
    sequence: int,
    locked: dict[str, Any] | None,
) -> dict[str, Any]:
    label_status, labels = _labels_for_pair(locked, a["id"], b["id"])
    text_hash = _stable_hash(a["text_hash"], b["text_hash"], length=16)
    pair_id = f"pref01_{_slug(task['task_id'])}_{sequence:04d}_{text_hash[:8]}"
    focus = "|".join(task.get("comparison_focus", []))
    row = {
        "pair_id": pair_id,
        "version": VERSION,
        "label_status": label_status,
        "priority": _priority_for_pair(label_status, a, b),
        "task_id": task["task_id"],
        "domain": task.get("domain", ""),
        "task_context": task.get("task_context", ""),
        "comparison_focus": focus,
        "variant_a_id": a["id"],
        "variant_a_origin": a.get("origin", ""),
        "variant_a_title": a["title"],
        "variant_a_body": a["body"],
        "variant_a_body_char_len": len(a["body"]),
        "variant_a_score": "" if a.get("score") is None else a["score"],
        "variant_a_source_file": a.get("source_file", ""),
        "variant_b_id": b["id"],
        "variant_b_origin": b.get("origin", ""),
        "variant_b_title": b["title"],
        "variant_b_body": b["body"],
        "variant_b_body_char_len": len(b["body"]),
        "variant_b_score": "" if b.get("score") is None else b["score"],
        "variant_b_source_file": b.get("source_file", ""),
        **labels,
        "pair_text_hash": text_hash,
    }
    return row


def build_preference_queue(seed_doc: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    skipped_variants: list[dict[str, str]] = []
    sequence = 1
    for task in seed_doc.get("tasks", []):
        variants: list[dict[str, Any]] = []
        for spec in task.get("variants", []):
            try:
                variants.append(_variant_from_spec(spec))
            except Exception as exc:
                skipped_variants.append(
                    {
                        "task_id": str(task.get("task_id", "")),
                        "variant_id": str(spec.get("id", "")),
                        "error": str(exc),
                    }
                )
        locks = _locked_pair_map(task)
        for a, b in itertools.combinations(variants, 2):
            locked = locks.get(_lock_key(a["id"], b["id"]))
            rows.append(
                _row_for_pair(
                    task=task,
                    a=a,
                    b=b,
                    sequence=sequence,
                    locked=locked,
                )
            )
            sequence += 1
    rows = _dedupe_rows(rows)
    report = build_report(rows, skipped_variants=skipped_variants)
    return rows, report


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = tuple(sorted([row["variant_a_id"], row["variant_b_id"]]) + [row["task_id"]])
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key, ""))
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: item[0]))


def _origin_pair(row: dict[str, Any]) -> str:
    return " vs ".join(sorted([row["variant_a_origin"], row["variant_b_origin"]]))


def build_report(rows: list[dict[str, Any]], *, skipped_variants: list[dict[str, str]]) -> dict[str, Any]:
    needs_label = [row for row in rows if row["label_status"] == "needs_label"]
    locked = [row for row in rows if row["label_status"] == "locked_seed"]
    origin_pairs: dict[str, int] = {}
    for row in rows:
        key = _origin_pair(row)
        origin_pairs[key] = origin_pairs.get(key, 0) + 1
    domains = _count_by(rows, "domain")
    under_target = {
        domain: {
            "selected_pairs": count,
            "production_preference_target": 3000,
        }
        for domain, count in domains.items()
        if count < 3000
    }
    return {
        "version": VERSION,
        "created_at": _now_iso(),
        "status": "preference_queue_needs_human_labels",
        "totals": {
            "pairs": len(rows),
            "needs_label": len(needs_label),
            "locked_seed": len(locked),
        },
        "by_domain": domains,
        "by_task": _count_by(rows, "task_id"),
        "by_label_status": _count_by(rows, "label_status"),
        "by_origin_pair": dict(sorted(origin_pairs.items(), key=lambda item: item[0])),
        "targets": {
            "production_preference_pairs_per_core_domain": 3000,
            "note": "This queue is only a seed. Production training needs thousands of same-task A/B comparisons per core industry.",
        },
        "coverage_gaps": {
            "under_preference_target": under_target,
            "missing_core_domains": [
                "旅行",
                "穿搭",
                "美妆",
                "家居",
                "健身",
                "母婴",
            ],
        },
        "skipped_variants": skipped_variants,
    }


def write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            line = json.dumps(row, ensure_ascii=False, sort_keys=True)
            line = line.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
            fh.write(line + "\n")


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=PREFERENCE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export A/B preference annotation queue.")
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED_PATH)
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    seed_path = args.seed if args.seed.is_absolute() else ROOT / args.seed
    output_jsonl = args.output_jsonl if args.output_jsonl.is_absolute() else ROOT / args.output_jsonl
    output_csv = args.output_csv if args.output_csv.is_absolute() else ROOT / args.output_csv
    report_path = args.report if args.report.is_absolute() else ROOT / args.report

    seed_doc = _load_json(seed_path)
    rows, report = build_preference_queue(seed_doc)
    report.update(
        {
            "inputs": {"seed": str(seed_path)},
            "outputs": {
                "jsonl": str(output_jsonl),
                "csv": str(output_csv),
                "report": str(report_path),
            },
        }
    )
    write_jsonl(rows, output_jsonl)
    write_csv(rows, output_csv)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"jsonl={output_jsonl}")
    print(f"csv={output_csv}")
    print(f"report={report_path}")
    print(f"pairs={report['totals']['pairs']} needs_label={report['totals']['needs_label']} locked_seed={report['totals']['locked_seed']}")
    print(f"by_domain={report['by_domain']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
