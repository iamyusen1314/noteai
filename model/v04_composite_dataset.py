#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build v0.4-composite supervised datasets from human labels.

Outputs are deliberately separated from the older v0.4 CES candidate dataset.
This dataset is for delivery quality: human golden labels and same-task A/B
preference labels. Legacy model scores in raw queues are excluded from training
features and targets.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from v04_composite_features import COMPOSITE_FEATURE_COLS, build_composite_features, canonical_domain


ROOT = Path(__file__).resolve().parents[1]
_MERGED_GOLDEN = ROOT / "quality" / "golden_labels.v01.merged.json"
_LABELED_PREFERENCE = ROOT / "quality" / "preference_queue.v01.labeled.jsonl"
DEFAULT_GOLDEN_LABELS = _MERGED_GOLDEN if _MERGED_GOLDEN.exists() else ROOT / "quality" / "golden_labels.v01.seed.json"
DEFAULT_PREFERENCE_QUEUE = _LABELED_PREFERENCE if _LABELED_PREFERENCE.exists() else ROOT / "quality" / "preference_queue.v01.jsonl"
DEFAULT_OUTPUT_DIR = ROOT / "model" / "data" / "v04_composite"

FORBIDDEN_TRAINING_SUBSTRINGS = (
    "v03",
    "legacy_score",
    "variant_a_score",
    "variant_b_score",
    "score_hack",
    "ces_percentile",
)

HARD_BLOCK_FAILURE_TAGS = {
    "wrong_industry",
    "overclaim",
    "fact_overclaim",
    "unsafe_claim",
    "medical_overclaim",
    "score_hacking",
}
HARD_BLOCK_FACT_STATUS = {"overclaim", "wrong_industry"}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _resolve_path(path: str | Path) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    return p


def _dig(doc: Any, dotted_path: str | None) -> Any:
    if not dotted_path:
        return None
    cur = doc
    for part in dotted_path.split("."):
        if isinstance(cur, list):
            cur = cur[int(part)]
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def resolve_golden_content(item: dict[str, Any]) -> dict[str, str]:
    src = item.get("content_source") or {}
    src_type = src.get("type")
    if src_type == "inline":
        return {
            "content_id": str(item["id"]),
            "title": str(src.get("title") or ""),
            "body": str(src.get("body") or ""),
            "domain": canonical_domain(src.get("domain")),
            "local_time": str(src.get("local_time") or "2026062412"),
        }

    data = _load_json(_resolve_path(src["file"]))
    if src_type == "quality_case":
        case = next((row for row in data if row.get("id") == src.get("case_id")), None)
        if case is None:
            raise KeyError(f"case_id not found: {src.get('case_id')} in {src.get('file')}")
        return {
            "content_id": str(item["id"]),
            "title": str(case.get("title") or ""),
            "body": str(case.get("body") or ""),
            "domain": canonical_domain(case.get("domain") or src.get("domain")),
            "local_time": str(case.get("local_time") or src.get("local_time") or "2026062412"),
        }

    if src_type == "json_fields":
        return {
            "content_id": str(item["id"]),
            "title": str(_dig(data, src.get("title_field")) or ""),
            "body": str(_dig(data, src.get("body_field")) or ""),
            "domain": canonical_domain(src.get("domain") or data.get("domain")),
            "local_time": str(src.get("local_time") or data.get("local_time") or "2026062412"),
        }
    raise ValueError(f"Unsupported content_source.type: {src_type}")


def _split_pipe(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    if value is None:
        return []
    return [v for v in str(value).split("|") if v]


def _delivery_target_labels(
    *,
    human_quality_score: float,
    delivery_ready: bool,
    fact_status: str,
    failure_tags: list[str],
) -> dict[str, int]:
    """Separate fatal blocks from notes that are useful but need light revision.

    The original delivery_ready label is intentionally strict and often marks
    72+ score notes as false for missing CTA or weak titles. Product behavior
    should not hard-block those; it should send them to revision.
    """
    tags = {str(tag).strip() for tag in failure_tags if str(tag).strip()}
    hard_block = (
        human_quality_score < 60.0
        or str(fact_status or "").strip() in HARD_BLOCK_FACT_STATUS
        or bool(tags & HARD_BLOCK_FAILURE_TAGS)
    )
    needs_revision = bool((not delivery_ready) and not hard_block)
    return {
        "delivery_ready_strict": int(delivery_ready),
        "hard_delivery_block": int(hard_block),
        "needs_revision": int(needs_revision),
        "publishable_or_repairable": int(not hard_block),
    }


def build_golden_training_rows(labels_path: Path = DEFAULT_GOLDEN_LABELS) -> pd.DataFrame:
    doc = _load_json(labels_path)
    records: list[dict[str, Any]] = []
    for item in doc.get("items", []):
        labels = item.get("labels") or {}
        if "human_quality_score" not in labels:
            continue
        content = resolve_golden_content(item)
        features = build_composite_features(
            title=content["title"],
            body=content["body"],
            domain=content["domain"],
            local_time=content["local_time"],
        )
        failure_tags = _split_pipe(labels.get("failure_tags", []))
        human_quality_score = float(labels["human_quality_score"])
        delivery_ready = bool(labels.get("delivery_ready"))
        fact_status = str(labels.get("fact_status") or "unknown")
        delivery_targets = _delivery_target_labels(
            human_quality_score=human_quality_score,
            delivery_ready=delivery_ready,
            fact_status=fact_status,
            failure_tags=failure_tags,
        )
        rec: dict[str, Any] = {
            "row_type": "golden",
            "content_id": content["content_id"],
            "domain": content["domain"],
            "title": content["title"],
            "body": content["body"],
            "human_quality_score": human_quality_score,
            "delivery_ready": int(delivery_ready),
            "naturalness_label": float(labels.get("naturalness_label", 50.0) or 0.0),
            "hook_quality": int(labels.get("hook_quality", 0) or 0),
            "body_value": int(labels.get("body_value", 0) or 0),
            "industry_fit": int(labels.get("industry_fit", 0) or 0),
            "fact_status": fact_status,
            "fact_verified": int(labels.get("fact_status") == "verified"),
            "fact_overclaim": int(labels.get("fact_status") == "overclaim"),
            "ai_smell_level": int(labels.get("ai_smell_level", 0) or 0),
            "failure_tags": "|".join(failure_tags),
            "label_rationale": str(labels.get("rationale") or ""),
        }
        rec.update(delivery_targets)
        rec.update(features)
        records.append(rec)
    return pd.DataFrame(records)


def _variant_from_preference_row(row: dict[str, Any], side: str) -> dict[str, Any]:
    prefix = f"variant_{side.lower()}_"
    return {
        "id": row.get(prefix + "id") or "",
        "origin": row.get(prefix + "origin") or "",
        "title": row.get(prefix + "title") or "",
        "body": row.get(prefix + "body") or "",
        "source_file": row.get(prefix + "source_file") or "",
    }


def _winner_label(winner: str) -> float | None:
    if winner == "A":
        return 1.0
    if winner == "B":
        return 0.0
    if winner == "tie":
        return 0.5
    return None


def build_preference_pair_rows(queue_path: Path = DEFAULT_PREFERENCE_QUEUE) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for row in _iter_jsonl(queue_path):
        winner = row.get("winner")
        y = _winner_label(str(winner or ""))
        if y is None:
            continue
        domain = canonical_domain(row.get("domain"))
        a = _variant_from_preference_row(row, "a")
        b = _variant_from_preference_row(row, "b")
        features_a = build_composite_features(title=a["title"], body=a["body"], domain=domain)
        features_b = build_composite_features(title=b["title"], body=b["body"], domain=domain)
        margin = row.get("preference_margin")
        try:
            margin_value = int(margin)
        except Exception:
            margin_value = 0
        rec: dict[str, Any] = {
            "row_type": "preference_pair",
            "pair_id": row.get("pair_id") or "",
            "task_id": row.get("task_id") or "",
            "domain": domain,
            "winner": winner,
            "preference_label_a_wins": y,
            "preference_margin": margin_value,
            "delivery_ready_winner": row.get("delivery_ready_winner"),
            "reason_tags": "|".join(_split_pipe(row.get("reason_tags"))),
            "loser_failure_tags": "|".join(_split_pipe(row.get("loser_failure_tags"))),
            "rationale": row.get("rationale") or "",
            "variant_a_id": a["id"],
            "variant_a_origin": a["origin"],
            "variant_a_title": a["title"],
            "variant_a_body": a["body"],
            "variant_b_id": b["id"],
            "variant_b_origin": b["origin"],
            "variant_b_title": b["title"],
            "variant_b_body": b["body"],
        }
        for col in COMPOSITE_FEATURE_COLS:
            rec[f"a__{col}"] = float(features_a.get(col, 0.0) or 0.0)
            rec[f"b__{col}"] = float(features_b.get(col, 0.0) or 0.0)
            rec[f"delta__{col}"] = float(features_a.get(col, 0.0) or 0.0) - float(features_b.get(col, 0.0) or 0.0)
        records.append(rec)
    return pd.DataFrame(records)


def assert_no_forbidden_training_columns(columns: list[str]) -> None:
    offenders = [
        col
        for col in columns
        for forbidden in FORBIDDEN_TRAINING_SUBSTRINGS
        if forbidden in col.lower()
    ]
    if offenders:
        raise AssertionError(f"Forbidden legacy/leaky training columns: {sorted(set(offenders))}")


def _write_jsonl(path: Path, df: pd.DataFrame) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in df.to_dict(orient="records"):
            line = json.dumps(row, ensure_ascii=False)
            line = line.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
            fh.write(line + "\n")


def _domain_counts(df: pd.DataFrame) -> dict[str, int]:
    if df.empty or "domain" not in df.columns:
        return {}
    return {str(k): int(v) for k, v in Counter(df["domain"]).most_common()}


def build_and_write_composite_dataset(
    *,
    golden_labels: Path = DEFAULT_GOLDEN_LABELS,
    preference_queue: Path = DEFAULT_PREFERENCE_QUEUE,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    golden_df = build_golden_training_rows(golden_labels)
    pref_df = build_preference_pair_rows(preference_queue)

    assert_no_forbidden_training_columns(COMPOSITE_FEATURE_COLS)
    assert_no_forbidden_training_columns([f"delta__{col}" for col in COMPOSITE_FEATURE_COLS])

    golden_parquet = output_dir / "golden_training_rows.parquet"
    preference_parquet = output_dir / "preference_pair_rows.parquet"
    golden_jsonl = output_dir / "golden_training_rows.jsonl"
    preference_jsonl = output_dir / "preference_pair_rows.jsonl"
    manifest_path = output_dir / "dataset_manifest.json"

    golden_df.to_parquet(golden_parquet, index=False)
    pref_df.to_parquet(preference_parquet, index=False)
    _write_jsonl(golden_jsonl, golden_df)
    _write_jsonl(preference_jsonl, pref_df)

    pref_winners = pref_df["winner"].value_counts().to_dict() if not pref_df.empty else {}
    manifest = {
        "version": "v04-composite-dataset-v0.1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "golden_labels": str(golden_labels),
            "preference_queue": str(preference_queue),
        },
        "outputs": {
            "golden_parquet": str(golden_parquet),
            "golden_jsonl": str(golden_jsonl),
            "preference_parquet": str(preference_parquet),
            "preference_jsonl": str(preference_jsonl),
        },
        "counts": {
            "golden_rows": int(len(golden_df)),
            "preference_pair_rows": int(len(pref_df)),
            "golden_by_domain": _domain_counts(golden_df),
            "preference_by_domain": _domain_counts(pref_df),
            "preference_winners": {str(k): int(v) for k, v in pref_winners.items()},
        },
        "feature_contract": {
            "feature_count_single": len(COMPOSITE_FEATURE_COLS),
            "single_feature_columns": COMPOSITE_FEATURE_COLS,
            "preference_training_columns": [f"delta__{col}" for col in COMPOSITE_FEATURE_COLS],
            "legacy_score_policy": "raw queue scores are excluded from composite features and targets",
            "forbidden_training_substrings": list(FORBIDDEN_TRAINING_SUBSTRINGS),
        },
        "label_contract": {
            "golden_targets": [
                "human_quality_score",
                "delivery_ready",
                "delivery_ready_strict",
                "publishable_or_repairable",
                "hard_delivery_block",
                "needs_revision",
                "naturalness_label",
                "hook_quality",
                "body_value",
                "industry_fit",
                "fact_status",
                "ai_smell_level",
            ],
            "delivery_target_policy": (
                "delivery_ready remains the strict review label; publishable_or_repairable is the "
                "classifier target for product gating so 60+ light-revision notes are revised, not hard-blocked"
            ),
            "preference_target": "preference_label_a_wins",
        },
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v0.4-composite training datasets")
    parser.add_argument("--golden-labels", default=str(DEFAULT_GOLDEN_LABELS))
    parser.add_argument("--preference-queue", default=str(DEFAULT_PREFERENCE_QUEUE))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = build_and_write_composite_dataset(
        golden_labels=Path(args.golden_labels),
        preference_queue=Path(args.preference_queue),
        output_dir=Path(args.output_dir),
    )
    if args.json:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    else:
        counts = manifest["counts"]
        print(f"golden_rows={counts['golden_rows']}")
        print(f"preference_pair_rows={counts['preference_pair_rows']}")
        print(f"output_dir={Path(args.output_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
