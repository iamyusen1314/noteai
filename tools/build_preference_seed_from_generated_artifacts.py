#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a preference seed file from generated variant artifacts."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("NOTEAI_FACT_SEARCH", "0")

import api as note_api  # noqa: E402

DEFAULT_TASK_POOL = ROOT / "quality" / "preference_task_pool.v01.seed.json"
DEFAULT_ARTIFACT_DIR = ROOT / "quality" / "generated_variants" / "v01"
DEFAULT_OUTPUT = ROOT / "quality" / "preference_pairs.v01.generated_from_artifacts.json"
DEFAULT_REPORT = ROOT / "quality" / "preference_pairs.v01.generated_from_artifacts.report.json"
_TRAINING_BODY_FACT_SECTION_RE = re.compile(
    r"(?:^|[\n。；;])\s*实用信息\s*[:：]\s*(?:地址|位置|人均|价格|营业|时间|交通|预订|排队)"
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _task_context(task: dict[str, Any]) -> str:
    facts = "；".join(str(item) for item in task.get("known_facts", []))
    return (
        f"用户意图：{task.get('user_intent', '')}\n"
        f"目标读者：{task.get('target_reader', '')}\n"
        f"已知事实：{facts}"
    ).strip()


def _variant_from_artifact(path: Path, artifact: dict[str, Any]) -> dict[str, Any] | None:
    if artifact.get("status") != "ready":
        return None
    raw_title = str(artifact.get("title") or "").strip()
    raw_body = str(artifact.get("body") or "").strip()
    if not raw_title or not raw_body:
        return None
    task_id = str(artifact.get("task_id") or path.parent.name)
    slot_id = str(artifact.get("slot_id") or path.stem)
    domain = str(artifact.get("domain") or "")
    source_context = str(artifact.get("source_context") or "")
    title = note_api._sanitize_title_for_delivery(raw_title, source_context, domain)
    body = note_api._insert_safe_fact_line(raw_body, domain, source_context)
    try:
        score, _features = note_api._predict(
            note_api.NoteInput(
                note_title=title,
                desc=note_api._normalize_tags_for_scoring(body),
                domain=domain,
                local_time=str(artifact.get("local_time") or ""),
            )
        )
    except Exception:
        score = artifact.get("score")
    return {
        "id": f"{task_id}__{slot_id}",
        "origin": artifact.get("origin") or slot_id,
        "source_file": _rel(path),
        "title": title,
        "body": body,
        "score": round(float(score), 3) if score is not None else artifact.get("score"),
        "original_score": artifact.get("score"),
        "title_path": "title",
        "body_path": "body",
        "score_path": "score",
    }


def _training_body_filter_issues(artifact: dict[str, Any]) -> list[str]:
    body = str(artifact.get("body") or "")
    issues: list[str] = []
    if note_api._body_format_issues(body):
        issues.append("body_format_filtered")
    if _TRAINING_BODY_FACT_SECTION_RE.search(body):
        issues.append("fact_section_template_filtered")
    return issues


def build_seed(
    *,
    task_pool_path: Path,
    artifact_dir: Path,
    include_blocking: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    pool = _load_json(task_pool_path)
    tasks_by_id = {task["task_id"]: task for task in pool.get("tasks", [])}
    variants_by_task: dict[str, list[dict[str, Any]]] = {task_id: [] for task_id in tasks_by_id}
    skipped: list[dict[str, str]] = []
    artifact_count = 0

    for path in sorted(artifact_dir.glob("*/*.json")):
        artifact_count += 1
        try:
            artifact = _load_json(path)
        except Exception as exc:
            skipped.append({"path": str(path), "reason": f"invalid_json:{exc}"})
            continue
        if artifact.get("blocking") and not include_blocking:
            skipped.append({"path": str(path), "reason": "blocking_filtered"})
            continue
        title_issues = note_api._title_readability_issues(
            str(artifact.get("title") or ""),
            str(artifact.get("domain") or ""),
        )
        if title_issues:
            skipped.append({"path": str(path), "reason": f"title_unreadable_filtered:{'|'.join(title_issues)}"})
            continue
        body_filter_issues = _training_body_filter_issues(artifact)
        if body_filter_issues:
            skipped.append({"path": str(path), "reason": "|".join(body_filter_issues)})
            continue
        task_id = str(artifact.get("task_id") or path.parent.name)
        if task_id not in variants_by_task:
            skipped.append({"path": str(path), "reason": f"task_not_in_pool:{task_id}"})
            continue
        variant = _variant_from_artifact(path, artifact)
        if not variant:
            skipped.append({"path": str(path), "reason": "not_ready_or_missing_text"})
            continue
        variants_by_task[task_id].append(variant)

    seed_tasks: list[dict[str, Any]] = []
    for task_id, task in tasks_by_id.items():
        variants = sorted(variants_by_task.get(task_id, []), key=lambda item: item["id"])
        if len(variants) < 2:
            skipped.append({"path": task_id, "reason": "task_has_less_than_two_variants"})
            continue
        seed_tasks.append(
            {
                "task_id": task_id,
                "domain": task.get("domain", ""),
                "task_context": _task_context(task),
                "comparison_focus": task.get("quality_focus", []),
                "variants": variants,
                "locked_pairs": [],
            }
        )

    doc = {
        "version": "preference-pairs-generated-from-artifacts-v0.1",
        "description": "Generated same-task variants assembled from auditable artifact files. Requires human A/B labels before training.",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tasks": seed_tasks,
    }
    report = {
        "version": "preference-seed-from-artifacts-report-v0.1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "task_pool": str(task_pool_path),
            "artifact_dir": str(artifact_dir),
            "include_blocking": include_blocking,
        },
        "artifact_count": artifact_count,
        "task_count": len(seed_tasks),
        "variant_count": sum(len(task["variants"]) for task in seed_tasks),
        "variants_by_task": {task["task_id"]: len(task["variants"]) for task in seed_tasks},
        "skipped": skipped[:200],
        "policy": "This seed creates preference labeling queues only; labels must be human-reviewed before training.",
    }
    return doc, report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build preference seed from generated artifacts")
    parser.add_argument("--task-pool", type=Path, default=DEFAULT_TASK_POOL)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--include-blocking", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    task_pool = args.task_pool if args.task_pool.is_absolute() else ROOT / args.task_pool
    artifact_dir = args.artifact_dir if args.artifact_dir.is_absolute() else ROOT / args.artifact_dir
    output = args.output if args.output.is_absolute() else ROOT / args.output
    report_path = args.report if args.report.is_absolute() else ROOT / args.report
    doc, report = build_seed(
        task_pool_path=task_pool,
        artifact_dir=artifact_dir,
        include_blocking=bool(args.include_blocking),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    report["outputs"] = {"seed": str(output), "report": str(report_path)}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"tasks={report['task_count']} variants={report['variant_count']}")
        print(f"seed={output}")
        print(f"report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
