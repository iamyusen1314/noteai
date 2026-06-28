#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export small human-labeling batches from golden/preference queues."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

from v04_domain_policy import canonical_product_domain, canonical_product_domains  # noqa: E402

DEFAULT_GOLDEN_QUEUE = ROOT / "quality" / "annotation_queue.v01.jsonl"
DEFAULT_PREFERENCE_QUEUE = ROOT / "quality" / "preference_queue.v01.jsonl"
DEFAULT_OUTPUT_DIR = ROOT / "quality" / "labeling_batches"


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
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


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _source_paths(patterns: str) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    for raw in (part.strip() for part in str(patterns or "").split(",")):
        if not raw:
            continue
        pattern_path = Path(raw)
        if pattern_path.is_absolute():
            matches = list(pattern_path.parent.glob(pattern_path.name))
        else:
            matches = list(ROOT.glob(raw))
        if not matches and pattern_path.exists():
            matches = [pattern_path]
        for path in matches:
            resolved = path.resolve()
            if resolved.is_file() and resolved not in seen:
                paths.append(resolved)
                seen.add(resolved)
    return paths


def _ids_from_json(path: Path, kind: str) -> set[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    rows = data.get("items") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return set()
    key = _id_key(kind)
    ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_id = str(row.get(key) or row.get("id") or "").strip()
        if row_id:
            ids.add(row_id)
    return ids


def _load_excluded_ids(patterns: str, kind: str) -> tuple[set[str], list[str]]:
    ids: set[str] = set()
    paths = _source_paths(patterns)
    key = _id_key(kind)
    for path in paths:
        if path.suffix.lower() == ".json" and not path.name.endswith(".jsonl"):
            ids.update(_ids_from_json(path, kind))
            continue
        for row in _iter_jsonl(path) if path.suffix.lower() != ".csv" else _load_csv(path):
            row_id = str(row.get(key) or row.get("id") or "").strip()
            if row_id:
                ids.add(row_id)
    return ids, [str(path) for path in paths]


def _load_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def _status_key(kind: str) -> str:
    return "human_label_status" if kind == "golden" else "label_status"


def _id_key(kind: str) -> str:
    return "annotation_id" if kind == "golden" else "pair_id"


def _is_unlabeled(row: dict[str, Any], kind: str) -> bool:
    status = str(row.get(_status_key(kind), "")).strip()
    if status not in {"needs_label", ""}:
        return False
    if kind == "golden":
        return not str(row.get("human_quality_score", "")).strip()
    return str(row.get("winner", "")).strip() == ""


def _filter_rows(rows: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    out = [row for row in rows if _is_unlabeled(row, args.kind)]
    exclude_ids, _exclude_sources = _load_excluded_ids(getattr(args, "exclude_ids_from", ""), args.kind)
    if exclude_ids:
        key = _id_key(args.kind)
        out = [row for row in out if str(row.get(key) or row.get("id") or "").strip() not in exclude_ids]
    if args.domains:
        wanted = set(canonical_product_domains(d.strip() for d in args.domains.split(",") if d.strip()))
        out = [row for row in out if canonical_product_domain(row.get("domain")) in wanted]
    if args.priorities:
        wanted = {p.strip() for p in args.priorities.split(",") if p.strip()}
        out = [row for row in out if row.get("priority") in wanted]
    out.sort(
        key=lambda row: (
            {"high": 0, "medium": 1, "normal": 2}.get(str(row.get("priority")), 9),
            canonical_product_domain(row.get("domain")),
            str(row.get(_id_key(args.kind), "")),
        )
    )
    return out


def select_batch(rows: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    filtered = _filter_rows(rows, args)
    if args.per_domain <= 0:
        return filtered[: args.max_rows]

    by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in filtered:
        by_domain[canonical_product_domain(row.get("domain") or "未知")].append(row)

    selected: list[dict[str, Any]] = []
    for domain in sorted(by_domain):
        selected.extend(by_domain[domain][: args.per_domain])
    selected.sort(
        key=lambda row: (
            {"high": 0, "medium": 1, "normal": 2}.get(str(row.get("priority")), 9),
            canonical_product_domain(row.get("domain")),
            str(row.get(_id_key(args.kind), "")),
        )
    )
    return selected[: args.max_rows]


def export_batch(args: argparse.Namespace) -> dict[str, Any]:
    queue_path = Path(args.queue)
    rows = _iter_jsonl(queue_path)
    exclude_ids, exclude_sources = _load_excluded_ids(getattr(args, "exclude_ids_from", ""), args.kind)
    batch = [
        {**row, "domain": canonical_product_domain(row.get("domain") or "未知")}
        for row in select_batch(rows, args)
    ]

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    batch_id = args.batch_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = f"{batch_id}_{args.kind}"
    jsonl_path = output_dir / f"{stem}.jsonl"
    csv_path = output_dir / f"{stem}.csv"
    report_path = output_dir / f"{stem}.report.json"
    _write_jsonl(jsonl_path, batch)
    _write_csv(csv_path, batch)

    report = {
        "version": "labeling-batch-v0.1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "kind": args.kind,
        "queue": str(queue_path),
        "outputs": {"jsonl": str(jsonl_path), "csv": str(csv_path)},
        "batch_id": batch_id,
        "rows": len(batch),
        "by_domain": dict(Counter(canonical_product_domain(row.get("domain") or "未知") for row in batch)),
        "by_priority": dict(Counter(str(row.get("priority") or "") for row in batch)),
        "selection": {
            "max_rows": args.max_rows,
            "per_domain": args.per_domain,
            "domains": args.domains,
            "priorities": args.priorities,
            "exclude_ids_from": getattr(args, "exclude_ids_from", ""),
            "excluded_id_count": len(exclude_ids),
            "exclude_source_count": len(exclude_sources),
            "exclude_sources": exclude_sources[:50],
        },
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report"] = str(report_path)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a manageable labeling batch")
    parser.add_argument("--kind", choices=["golden", "preference"], required=True)
    parser.add_argument("--queue", default=None)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--batch-id", default="")
    parser.add_argument("--max-rows", type=int, default=200)
    parser.add_argument("--per-domain", type=int, default=0)
    parser.add_argument("--domains", default="")
    parser.add_argument("--priorities", default="high,medium,normal")
    parser.add_argument(
        "--exclude-ids-from",
        default="",
        help="Comma-separated files/globs whose annotation_id or pair_id should be skipped.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not args.queue:
        args.queue = str(DEFAULT_GOLDEN_QUEUE if args.kind == "golden" else DEFAULT_PREFERENCE_QUEUE)
    return args


def main() -> int:
    args = parse_args()
    report = export_batch(args)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"rows={report['rows']}")
        print(f"jsonl={report['outputs']['jsonl']}")
        print(f"csv={report['outputs']['csv']}")
        print(f"report={report['report']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
