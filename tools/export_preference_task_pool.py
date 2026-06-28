#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export generation backlog rows from a multi-industry preference task pool."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VERSION = "preference-generation-queue-v0.1"

DEFAULT_POOL_PATH = ROOT / "quality" / "preference_task_pool.v01.seed.json"
DEFAULT_OUTPUT_JSONL = ROOT / "quality" / "preference_generation_queue.v01.jsonl"
DEFAULT_OUTPUT_CSV = ROOT / "quality" / "preference_generation_queue.v01.csv"
DEFAULT_REPORT = ROOT / "quality" / "preference_generation_queue.v01.report.json"

CORE_PRODUCT_DOMAINS = ["美食", "旅行", "穿搭", "美妆", "家居", "健身", "母婴"]
PREFERENCE_TARGET_PER_DOMAIN = 3000

GENERATION_COLUMNS = [
    "queue_id",
    "version",
    "task_id",
    "domain",
    "task_status",
    "priority",
    "source_case_id",
    "slot_id",
    "origin",
    "slot_status",
    "generation_route",
    "prompt_focus",
    "user_intent",
    "known_facts",
    "fact_status",
    "target_reader",
    "quality_focus",
    "reference_title",
    "reference_body",
    "source_file",
    "title_path",
    "body_path",
    "score_path",
    "generation_payload_json",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_hash(*parts: Any, length: int = 12) -> str:
    text = "\n".join(str(part or "") for part in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def _join(items: list[Any] | None) -> str:
    return "|".join(str(item) for item in (items or []))


def _payload(task: dict[str, Any], slot: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": task["task_id"],
        "domain": task["domain"],
        "user_intent": task["user_intent"],
        "known_facts": task.get("known_facts", []),
        "fact_status": task.get("fact_status", ""),
        "target_reader": task.get("target_reader", ""),
        "quality_focus": task.get("quality_focus", []),
        "slot_id": slot["slot_id"],
        "origin": slot["origin"],
        "generation_route": slot.get("generation_route", ""),
        "prompt_focus": slot.get("prompt_focus", []),
        "reference": {
            "title": task.get("reference_title", ""),
            "body_excerpt": task.get("reference_body", ""),
            "source_case_id": task.get("source_case_id", ""),
        },
    }


def build_generation_queue(pool_doc: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in pool_doc.get("tasks", []):
        for slot in task.get("variant_slots", []):
            queue_id = f"pgen01_{task['task_id']}_{slot['slot_id']}_{_stable_hash(task['task_id'], slot['slot_id'], length=8)}"
            payload = _payload(task, slot)
            rows.append(
                {
                    "queue_id": queue_id,
                    "version": VERSION,
                    "task_id": task["task_id"],
                    "domain": task["domain"],
                    "task_status": task.get("task_status", ""),
                    "priority": task.get("priority", "normal"),
                    "source_case_id": task.get("source_case_id", ""),
                    "slot_id": slot["slot_id"],
                    "origin": slot["origin"],
                    "slot_status": slot.get("status", ""),
                    "generation_route": slot.get("generation_route", ""),
                    "prompt_focus": _join(slot.get("prompt_focus", [])),
                    "user_intent": task.get("user_intent", ""),
                    "known_facts": _join(task.get("known_facts", [])),
                    "fact_status": task.get("fact_status", ""),
                    "target_reader": task.get("target_reader", ""),
                    "quality_focus": _join(task.get("quality_focus", [])),
                    "reference_title": task.get("reference_title", ""),
                    "reference_body": task.get("reference_body", ""),
                    "source_file": slot.get("source_file", ""),
                    "title_path": slot.get("title_path", ""),
                    "body_path": slot.get("body_path", ""),
                    "score_path": slot.get("score_path", ""),
                    "generation_payload_json": json.dumps(payload, ensure_ascii=False, sort_keys=True),
                }
            )
    report = build_report(pool_doc, rows)
    return rows, report


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key, ""))
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: item[0]))


def build_report(pool_doc: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    tasks = pool_doc.get("tasks", [])
    by_domain_tasks: dict[str, int] = {}
    ready_slots = 0
    needs_generation_slots = 0
    skipped_slots = 0
    potential_pairs_by_domain: dict[str, int] = {}
    for task in tasks:
        domain = task.get("domain", "")
        by_domain_tasks[domain] = by_domain_tasks.get(domain, 0) + 1
        ready_count = 0
        for slot in task.get("variant_slots", []):
            status = slot.get("status", "")
            if status == "ready":
                ready_slots += 1
                ready_count += 1
            elif status == "needs_generation":
                needs_generation_slots += 1
            elif status == "skipped":
                skipped_slots += 1
        potential_pairs_by_domain[domain] = potential_pairs_by_domain.get(domain, 0) + max(0, ready_count * (ready_count - 1) // 2)

    missing_core_domains = [domain for domain in CORE_PRODUCT_DOMAINS if by_domain_tasks.get(domain, 0) == 0]
    current_tasks_by_domain = by_domain_tasks
    task_targets = {
        domain: {
            "current_tasks": current_tasks_by_domain.get(domain, 0),
            "rough_tasks_needed_for_3000_pairs_at_9_variants": max(
                0,
                84 - current_tasks_by_domain.get(domain, 0),
            ),
            "note": "9 completed variants create 36 A/B pairs; about 84 completed tasks reach 3000 pairs.",
        }
        for domain in CORE_PRODUCT_DOMAINS
    }
    return {
        "version": VERSION,
        "created_at": _now_iso(),
        "status": "generation_queue_needs_real_outputs",
        "totals": {
            "tasks": len(tasks),
            "generation_rows": len(rows),
            "ready_slots": ready_slots,
            "needs_generation_slots": needs_generation_slots,
            "skipped_slots": skipped_slots,
        },
        "by_domain_tasks": dict(sorted(by_domain_tasks.items())),
        "by_domain_generation_rows": _count_by(rows, "domain"),
        "by_origin": _count_by(rows, "origin"),
        "by_generation_route": _count_by(rows, "generation_route"),
        "potential_pairs_by_domain_from_ready_slots": dict(sorted(potential_pairs_by_domain.items())),
        "targets": {
            "preference_pairs_per_core_domain": PREFERENCE_TARGET_PER_DOMAIN,
            "completed_tasks_needed_per_core_domain_if_9_variants_each": 84,
            "variant_slots_per_task": 9,
        },
        "coverage_gaps": {
            "missing_core_domains": missing_core_domains,
            "task_targets": task_targets,
        },
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
        writer = csv.DictWriter(fh, fieldnames=GENERATION_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export generation queue from preference task pool.")
    parser.add_argument("--pool", type=Path, default=DEFAULT_POOL_PATH)
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    pool_path = _resolve_path(args.pool)
    output_jsonl = _resolve_path(args.output_jsonl)
    output_csv = _resolve_path(args.output_csv)
    report_path = _resolve_path(args.report)
    pool_doc = _load_json(pool_path)
    rows, report = build_generation_queue(pool_doc)
    report.update(
        {
            "inputs": {"pool": str(pool_path)},
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
    print(
        f"tasks={report['totals']['tasks']} rows={report['totals']['generation_rows']} "
        f"needs_generation={report['totals']['needs_generation_slots']} ready={report['totals']['ready_slots']}"
    )
    print(f"by_domain={report['by_domain_generation_rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
