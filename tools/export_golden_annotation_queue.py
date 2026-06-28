#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export a stratified human-labeling queue for composite golden training."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

from v04_domain_policy import (  # noqa: E402
    CORE_PRODUCT_DOMAINS,
    canonical_product_domain,
    canonical_product_domains,
)


VERSION = "golden-annotation-queue-v0.1"

DEFAULT_SCORE_PATH = ROOT / "model" / "data" / "v04" / "score_rows.parquet"
DEFAULT_FEATURES_PATH = DEFAULT_SCORE_PATH
DEFAULT_NORMALIZED_PATH = ROOT / "model" / "data" / "v04" / "normalized_rows.parquet"
DEFAULT_SEED_LABELS_PATH = ROOT / "quality" / "golden_labels.v01.seed.json"
DEFAULT_OUTPUT_JSONL = ROOT / "quality" / "annotation_queue.v01.jsonl"
DEFAULT_OUTPUT_CSV = ROOT / "quality" / "annotation_queue.v01.csv"
DEFAULT_REPORT = ROOT / "quality" / "annotation_queue.v01.report.json"

DOMAIN_SLUGS = {
    "美食": "food",
    "旅行": "travel",
    "穿搭": "fashion",
    "美妆": "beauty",
    "家居": "home",
    "健康": "health",
    "运动": "sports",
    "健身": "fitness",
    "母婴": "baby",
    "职场": "career",
    "情感": "relationship",
    "心理": "wellness",
    "宠物": "pets",
    "学习": "education",
    "其他": "other",
}

DEFAULT_REAL_BAND_PLAN = {
    "real_top": {"min": 85.0, "max": 100.0001, "count": 80},
    "real_good": {"min": 70.0, "max": 85.0, "count": 50},
    "real_boundary": {"min": 55.0, "max": 70.0, "count": 70},
    "real_mid": {"min": 35.0, "max": 55.0, "count": 50},
    "real_low": {"min": 0.0, "max": 25.0, "count": 60},
}
DEFAULT_AIGC_PER_DOMAIN = 40

ANNOTATION_COLUMNS = [
    "annotation_id",
    "version",
    "human_label_status",
    "priority",
    "domain",
    "sample_bucket",
    "sample_source",
    "source_type",
    "source_file",
    "source_row",
    "note_id",
    "title",
    "body",
    "body_char_len",
    "liked_count",
    "collected_count",
    "comments_count",
    "ces_raw",
    "ces_percentile",
    "human_quality_score",
    "delivery_ready",
    "naturalness_label",
    "hook_quality",
    "body_value",
    "industry_fit",
    "fact_status",
    "ai_smell_level",
    "failure_tags",
    "rationale",
    "reviewer",
    "reviewed_at",
    "text_hash",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_hash(*parts: Any, length: int = 12) -> str:
    text = "\n".join(str(part or "") for part in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def _stable_sample(df: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    if n <= 0 or df.empty:
        return df.head(0).copy()
    if len(df) <= n:
        return df.sort_values(["note_id", "source_file", "source_row"], kind="mergesort").copy()
    return df.sample(n=n, random_state=seed).sort_values(["note_id"], kind="mergesort").copy()


def _domain_slug(domain: str) -> str:
    normalized = canonical_product_domain(domain)
    return DOMAIN_SLUGS.get(normalized, _stable_hash(normalized, length=8))


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _row_text_hash(title: str, body: str) -> str:
    return _stable_hash(title.strip(), body.strip(), length=16)


def _priority_for_bucket(bucket: str) -> str:
    if bucket in {"real_top", "real_boundary", "seed_locked"}:
        return "high"
    if bucket in {"aigc", "real_low"}:
        return "medium"
    return "normal"


def _empty_label_fields() -> dict[str, Any]:
    return {
        "human_quality_score": "",
        "delivery_ready": "",
        "naturalness_label": "",
        "hook_quality": "",
        "body_value": "",
        "industry_fit": "",
        "fact_status": "",
        "ai_smell_level": "",
        "failure_tags": "",
        "rationale": "",
        "reviewer": "",
        "reviewed_at": "",
    }


def _annotation_row(
    *,
    domain: str,
    bucket: str,
    source: str,
    row: dict[str, Any],
    sequence: int,
    label_status: str = "needs_label",
    labels: dict[str, Any] | None = None,
) -> dict[str, Any]:
    title = _clean_text(row.get("note_title") or row.get("title"))
    body = _clean_text(row.get("desc") or row.get("body") or row.get("note_content"))
    note_id = _clean_text(row.get("note_id")) or f"{source}:{bucket}:{sequence}:{_row_text_hash(title, body)}"
    text_hash = _row_text_hash(title, body)
    prefix = _domain_slug(domain)
    annotation_id = f"gq01_{prefix}_{bucket}_{sequence:04d}_{text_hash[:8]}"
    label_fields = _empty_label_fields()
    if labels:
        label_fields.update(
            {
                "human_quality_score": labels.get("human_quality_score", ""),
                "delivery_ready": labels.get("delivery_ready", ""),
                "naturalness_label": labels.get("naturalness_label", ""),
                "hook_quality": labels.get("hook_quality", ""),
                "body_value": labels.get("body_value", ""),
                "industry_fit": labels.get("industry_fit", ""),
                "fact_status": labels.get("fact_status", ""),
                "ai_smell_level": labels.get("ai_smell_level", ""),
                "failure_tags": "|".join(labels.get("failure_tags", [])),
                "rationale": labels.get("rationale", ""),
            }
        )
    return {
        "annotation_id": annotation_id,
        "version": VERSION,
        "human_label_status": label_status,
        "priority": _priority_for_bucket(bucket),
        "domain": canonical_product_domain(domain),
        "sample_bucket": bucket,
        "sample_source": source,
        "source_type": _clean_text(row.get("source_type")),
        "source_file": _clean_text(row.get("source_file")),
        "source_row": int(row.get("source_row") or 0),
        "note_id": note_id,
        "title": title,
        "body": body,
        "body_char_len": len(body),
        "liked_count": int(row.get("liked_count") or 0),
        "collected_count": int(row.get("collected_count") or 0),
        "comments_count": int(row.get("comments_count") or 0),
        "ces_raw": float(row.get("ces_raw") or 0.0),
        "ces_percentile": round(float(row.get("ces_percentile") or 0.0), 4),
        **label_fields,
        "text_hash": text_hash,
    }


def _select_real_samples(
    score_df: pd.DataFrame,
    *,
    domains: list[str],
    real_band_plan: dict[str, dict[str, float]],
    random_seed: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    shortfalls: list[dict[str, Any]] = []
    sequence = 1
    for domain in domains:
        domain_df = score_df[score_df["domain"] == domain].copy()
        for offset, (bucket, spec) in enumerate(real_band_plan.items(), 1):
            lo = float(spec["min"])
            hi = float(spec["max"])
            target = int(spec["count"])
            band_df = domain_df[
                (domain_df["ces_percentile"] >= lo)
                & (domain_df["ces_percentile"] < hi)
            ].copy()
            sample = _stable_sample(band_df, target, random_seed + offset + len(rows))
            if len(sample) < target:
                shortfalls.append(
                    {
                        "domain": domain,
                        "sample_bucket": bucket,
                        "target": target,
                        "available": int(len(band_df)),
                        "selected": int(len(sample)),
                    }
                )
            for _, item in sample.iterrows():
                rows.append(
                    _annotation_row(
                        domain=domain,
                        bucket=bucket,
                        source="rednote_vibe_score",
                        row=item.to_dict(),
                        sequence=sequence,
                    )
                )
                sequence += 1
    return rows, {"shortfalls": shortfalls}


def _select_aigc_samples(
    normalized_df: pd.DataFrame,
    *,
    domains: list[str],
    per_domain: int,
    random_seed: int,
    start_sequence: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    shortfalls: list[dict[str, Any]] = []
    if "source_type" not in normalized_df.columns:
        return rows, {"shortfalls": [{"reason": "normalized_df_missing_source_type"}]}
    aigc = normalized_df[normalized_df["source_type"] == "aigc"].copy()
    if aigc.empty:
        return rows, {"shortfalls": [{"reason": "no_aigc_rows"}]}
    sequence = start_sequence
    for idx, domain in enumerate(domains, 1):
        domain_df = aigc[aigc["domain"] == domain].copy()
        sample = _stable_sample(domain_df, per_domain, random_seed + 1000 + idx)
        if len(sample) < per_domain:
            shortfalls.append(
                {
                    "domain": domain,
                    "sample_bucket": "aigc",
                    "target": per_domain,
                    "available": int(len(domain_df)),
                    "selected": int(len(sample)),
                }
            )
        for _, item in sample.iterrows():
            rows.append(
                _annotation_row(
                    domain=domain,
                    bucket="aigc",
                    source="rednote_vibe_aigc",
                    row=item.to_dict(),
                    sequence=sequence,
                )
            )
            sequence += 1
    return rows, {"shortfalls": shortfalls}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_content_source(item: dict[str, Any]) -> dict[str, str]:
    src = item["content_source"]
    src_type = src["type"]
    if src_type == "inline":
        return {
            "title": src["title"],
            "body": src["body"],
            "domain": src.get("domain") or "美食",
        }
    data_path = Path(src.get("file", ""))
    if not data_path.is_absolute():
        data_path = ROOT / data_path
    data = _load_json(data_path)
    if src_type == "quality_case":
        for case in data:
            if case.get("id") == src.get("case_id"):
                return {
                    "title": case["title"],
                    "body": case["body"],
                    "domain": case.get("domain") or src.get("domain") or "美食",
                }
        raise KeyError(f"case_id not found: {src.get('case_id')} in {data_path}")
    if src_type == "json_fields":
        return {
            "title": data[src["title_field"]],
            "body": data[src["body_field"]],
            "domain": src.get("domain") or data.get("domain") or "美食",
        }
    raise ValueError(f"Unsupported content_source.type: {src_type}")


def _load_seed_rows(seed_labels_path: Path, *, start_sequence: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not seed_labels_path.exists():
        return [], {"seed_labels_path": str(seed_labels_path), "loaded": 0, "missing": True}
    doc = _load_json(seed_labels_path)
    rows: list[dict[str, Any]] = []
    sequence = start_sequence
    for item in doc.get("items", []):
        content = _resolve_content_source(item)
        source_row = {
            "note_id": item.get("id", ""),
            "note_title": content["title"],
            "desc": content["body"],
            "source_type": "noteai_seed",
            "source_file": item["content_source"].get("file", ""),
        }
        rows.append(
            _annotation_row(
                domain=content["domain"],
                bucket="seed_locked",
                source="noteai_golden_seed",
                row=source_row,
                sequence=sequence,
                label_status="locked_seed",
                labels=item.get("labels", {}),
            )
        )
        sequence += 1
    return rows, {"seed_labels_path": str(seed_labels_path), "loaded": len(rows), "missing": False}


def _dedupe_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    seen_text: set[str] = set()
    seen_id: set[str] = set()
    out: list[dict[str, Any]] = []
    duplicate_text = 0
    duplicate_id = 0
    for row in rows:
        if row["annotation_id"] in seen_id:
            duplicate_id += 1
            continue
        if row["text_hash"] in seen_text and row["sample_bucket"] != "seed_locked":
            duplicate_text += 1
            continue
        seen_id.add(row["annotation_id"])
        seen_text.add(row["text_hash"])
        out.append(row)
    return out, {"duplicate_text_removed": duplicate_text, "duplicate_id_removed": duplicate_id}


def build_annotation_queue(
    score_df: pd.DataFrame,
    normalized_df: pd.DataFrame,
    *,
    domains: list[str] | None = None,
    real_band_plan: dict[str, dict[str, float]] | None = None,
    aigc_per_domain: int = DEFAULT_AIGC_PER_DOMAIN,
    include_seed_labels: bool = True,
    seed_labels_path: Path = DEFAULT_SEED_LABELS_PATH,
    random_seed: int = 42,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    required_cols = {"note_id", "note_title", "desc", "domain", "source_type", "ces_percentile"}
    missing_cols = sorted(required_cols - set(score_df.columns))
    if missing_cols:
        raise ValueError(f"score_df missing required columns: {missing_cols}")

    score_df = score_df.copy()
    normalized_df = normalized_df.copy()
    score_df["domain"] = score_df["domain"].map(canonical_product_domain)
    if "domain" in normalized_df.columns:
        normalized_df["domain"] = normalized_df["domain"].map(canonical_product_domain)

    if domains is None:
        domains = sorted(score_df["domain"].dropna().map(canonical_product_domain).unique().tolist())
    else:
        domains = canonical_product_domains(domains)

    band_plan = real_band_plan or DEFAULT_REAL_BAND_PLAN
    real_rows, real_meta = _select_real_samples(
        score_df,
        domains=domains,
        real_band_plan=band_plan,
        random_seed=random_seed,
    )
    aigc_rows, aigc_meta = _select_aigc_samples(
        normalized_df,
        domains=domains,
        per_domain=aigc_per_domain,
        random_seed=random_seed,
        start_sequence=len(real_rows) + 1,
    )
    seed_rows: list[dict[str, Any]] = []
    seed_meta: dict[str, Any] = {"loaded": 0, "missing": False}
    if include_seed_labels:
        seed_rows, seed_meta = _load_seed_rows(seed_labels_path, start_sequence=len(real_rows) + len(aigc_rows) + 1)

    rows, dedupe_meta = _dedupe_rows(real_rows + aigc_rows + seed_rows)
    report = build_report(
        rows,
        domains=domains,
        real_band_plan=band_plan,
        aigc_per_domain=aigc_per_domain,
        real_meta=real_meta,
        aigc_meta=aigc_meta,
        seed_meta=seed_meta,
    )
    report["dedupe"] = dedupe_meta
    return rows, report


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key, ""))
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: item[0]))


def build_report(
    rows: list[dict[str, Any]],
    *,
    domains: list[str],
    real_band_plan: dict[str, dict[str, float]],
    aigc_per_domain: int,
    real_meta: dict[str, Any],
    aigc_meta: dict[str, Any],
    seed_meta: dict[str, Any],
) -> dict[str, Any]:
    needs_label = [row for row in rows if row["human_label_status"] == "needs_label"]
    by_domain = _count_by(rows, "domain")
    by_domain_needs_label = _count_by(needs_label, "domain")
    target_per_domain = sum(int(spec["count"]) for spec in real_band_plan.values()) + int(aigc_per_domain)
    under_target = {
        domain: {
            "selected_needs_label": by_domain_needs_label.get(domain, 0),
            "target_default": target_per_domain,
        }
        for domain in domains
        if by_domain_needs_label.get(domain, 0) < target_per_domain
    }
    core_domains = list(CORE_PRODUCT_DOMAINS)
    missing_product_domains = [domain for domain in core_domains if domain not in domains]
    product_seed_only = [
        domain
        for domain in core_domains
        if domain not in domains and by_domain.get(domain, 0) > 0
    ]
    return {
        "version": VERSION,
        "created_at": _now_iso(),
        "status": "annotation_queue_needs_human_labels",
        "totals": {
            "rows": len(rows),
            "needs_label": len(needs_label),
            "locked_seed": len(rows) - len(needs_label),
        },
        "by_domain": by_domain,
        "by_domain_needs_label": by_domain_needs_label,
        "by_bucket": _count_by(rows, "sample_bucket"),
        "by_source": _count_by(rows, "sample_source"),
        "domains_sampled": domains,
        "default_targets": {
            "candidate_core_domain_min": 300,
            "candidate_core_domain_target": 500,
            "production_core_domain_min": 1000,
            "production_core_domain_target": 2000,
            "preference_pairs_per_core_domain_target": 3000,
            "queue_default_per_observed_domain": target_per_domain,
            "real_band_plan": DEFAULT_REAL_BAND_PLAN,
            "aigc_per_domain": DEFAULT_AIGC_PER_DOMAIN,
        },
        "coverage_gaps": {
            "under_default_target": under_target,
            "missing_product_domains_in_rednote_vibe_snapshot": missing_product_domains,
            "product_domains_seed_only": product_seed_only,
            "note": "Missing product domains need generated/user-material samples or finer domain remapping before final training.",
        },
        "shortfalls": {
            "real": real_meta.get("shortfalls", []),
            "aigc": aigc_meta.get("shortfalls", []),
        },
        "seed_labels": seed_meta,
    }


def write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            line = json.dumps(row, ensure_ascii=False, sort_keys=True)
            # JSON Lines readers split on Unicode line/paragraph separators too.
            # Keep Chinese readable while escaping separators that would corrupt records.
            line = line.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
            fh.write(line + "\n")


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=ANNOTATION_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_domains(value: str) -> list[str]:
    return canonical_product_domains(part.strip() for part in value.split(",") if part.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a stratified golden annotation queue.")
    parser.add_argument("--features-path", type=Path, default=DEFAULT_FEATURES_PATH, help="Score rows parquet. Kept as --features-path for backward compatibility.")
    parser.add_argument("--normalized-path", type=Path, default=DEFAULT_NORMALIZED_PATH)
    parser.add_argument("--seed-labels", type=Path, default=DEFAULT_SEED_LABELS_PATH)
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--domains", type=str, default="", help="Comma-separated domains. Default: all observed score domains.")
    parser.add_argument("--aigc-per-domain", type=int, default=DEFAULT_AIGC_PER_DOMAIN)
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument("--no-seed-labels", action="store_true")
    args = parser.parse_args()

    features_path = args.features_path if args.features_path.is_absolute() else ROOT / args.features_path
    normalized_path = args.normalized_path if args.normalized_path.is_absolute() else ROOT / args.normalized_path
    seed_labels = args.seed_labels if args.seed_labels.is_absolute() else ROOT / args.seed_labels
    output_jsonl = args.output_jsonl if args.output_jsonl.is_absolute() else ROOT / args.output_jsonl
    output_csv = args.output_csv if args.output_csv.is_absolute() else ROOT / args.output_csv
    report_path = args.report if args.report.is_absolute() else ROOT / args.report

    if not features_path.exists():
        raise FileNotFoundError(f"features parquet not found: {features_path}")
    if not normalized_path.exists():
        raise FileNotFoundError(f"normalized parquet not found: {normalized_path}")

    score_df = pd.read_parquet(features_path)
    normalized_df = pd.read_parquet(normalized_path)
    domains = parse_domains(args.domains) if args.domains else None
    rows, report = build_annotation_queue(
        score_df,
        normalized_df,
        domains=domains,
        aigc_per_domain=args.aigc_per_domain,
        include_seed_labels=not args.no_seed_labels,
        seed_labels_path=seed_labels,
        random_seed=args.random_seed,
    )
    report.update(
        {
            "inputs": {
                "features_path": str(features_path),
                "normalized_path": str(normalized_path),
                "seed_labels_path": str(seed_labels),
            },
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
    print(f"rows={report['totals']['rows']} needs_label={report['totals']['needs_label']} locked_seed={report['totals']['locked_seed']}")
    print(f"by_domain={report['by_domain']}")
    if report["coverage_gaps"]["missing_product_domains_in_rednote_vibe_snapshot"]:
        print(f"missing_product_domains={report['coverage_gaps']['missing_product_domains_in_rednote_vibe_snapshot']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
