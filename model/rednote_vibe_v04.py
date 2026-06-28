#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RedNote-Vibe v0.4 data pipeline.

This module intentionally separates raw-data normalization, label construction,
feature extraction, and manifest generation. v0.3 mixed those concerns in the
training script, which made leakage and schema bugs hard to catch.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from feature_extraction import (
    FEATURE_COLS,
    SEMANTIC_FEATURE_COLS,
    TIMING_FEATURE_COLS,
    extract_features,
)


RAW_FILES = {
    "human": "training_set_human.jsonl",
    "aigc": "training_set_aigc.jsonl",
    "exploration": "exploring_set.jsonl",
}

DOMAIN_ALIASES = {
    "": "其他",
    "unknown": "其他",
    "Unknown": "其他",
    "others": "其他",
    "Others": "其他",
    "Food": "美食",
    "food": "美食",
    "餐饮": "美食",
    "食品": "美食",
    "Travel": "旅行",
    "travel": "旅行",
    "Fashion": "穿搭",
    "fashion": "穿搭",
    "时尚": "穿搭",
    "美妆": "穿搭",
    "Health": "健康",
    "health": "健康",
    "Career": "职场",
    "career": "职场",
    "Pets": "宠物",
    "pets": "宠物",
    "Education": "学习",
    "education": "学习",
    "Sports": "运动",
    "sports": "运动",
    "健身": "运动",
    "Relation.": "情感",
    "Relationship": "情感",
    "relationships": "情感",
    "Wellness": "心理",
    "wellness": "心理",
}

VISUAL_FEATURE_COLS = [
    "cover_brightness",
    "cover_warmth",
    "cover_saturation",
    "cover_contrast",
    "cover_sharpness",
    "cover_aspect_ratio",
    "cover_has_face",
    "cover_face_count",
    "cover_has_text",
    "cover_text_prominence",
    "cover_composition_score",
    "cover_aesthetic_score",
    "cover_emotion_intensity",
    "cover_visual_clarity",
]

MODEL_FEATURE_COLS_V04 = (
    list(FEATURE_COLS)
    + list(SEMANTIC_FEATURE_COLS)
    + list(VISUAL_FEATURE_COLS)
    + list(TIMING_FEATURE_COLS)
)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def normalize_domain(value: Any) -> str:
    text = str(value or "").strip()
    return DOMAIN_ALIASES.get(text, text or "其他")


def _safe_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        if isinstance(value, str):
            value = value.replace(",", "").strip()
        if isinstance(value, float) and math.isnan(value):
            return 0
        return max(0, int(float(value)))
    except Exception:
        return 0


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _source_type(filename: str) -> str:
    for source, raw_name in RAW_FILES.items():
        if filename == raw_name:
            return source
    return "unknown"


def normalize_row(row: dict[str, Any], *, filename: str, row_idx: int) -> dict[str, Any] | None:
    source = _source_type(filename)
    title = _safe_text(row.get("note_title"))
    desc = _safe_text(row.get("desc", row.get("note_content", "")))
    domain = normalize_domain(row.get("domain", ""))

    # AIGC rows have no real-world engagement label; keep them out of score
    # training. They are useful later for a separate AI-smell/naturalness model.
    if source == "aigc":
        note_id = f"aigc:{row.get('model_family', '')}:{row.get('model', '')}:{row_idx}"
    else:
        note_id = _safe_text(row.get("note_id"))
        if not note_id:
            return None

    likes = _safe_int(row.get("liked_count", row.get("likes", 0)))
    collections = _safe_int(row.get("collected_count", row.get("collections", 0)))
    comments = _safe_int(row.get("comments_count", row.get("comments", 0)))
    local_time = _safe_text(row.get("local_time"))

    return {
        "note_id": note_id,
        "note_title": title,
        "desc": desc,
        "local_time": local_time,
        "domain": domain,
        "liked_count": likes,
        "collected_count": collections,
        "comments_count": comments,
        "source_type": source,
        "source_file": filename,
        "source_row": row_idx,
        "model_family": _safe_text(row.get("model_family")),
        "model": _safe_text(row.get("model")),
        "text_len": len(title) + len(desc),
        "ces_raw": float(likes + collections + comments * 4),
    }


def load_normalized_rows(raw_dir: Path) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    missing: list[str] = []
    for filename in RAW_FILES.values():
        path = raw_dir / filename
        if not path.exists():
            missing.append(filename)
            continue
        with path.open("r", encoding="utf-8") as fh:
            for idx, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                normalized = normalize_row(row, filename=filename, row_idx=idx)
                if normalized:
                    records.append(normalized)
    if missing:
        raise FileNotFoundError(f"Missing RedNote-Vibe raw files: {', '.join(missing)} in {raw_dir}")
    return pd.DataFrame(records)


def _dedupe_score_rows(df: pd.DataFrame) -> pd.DataFrame:
    score_df = df[df["source_type"].isin(["human", "exploration"])].copy()
    score_df = score_df[score_df["text_len"] >= 20].copy()
    score_df["has_body"] = score_df["desc"].str.len() > 0
    score_df = score_df.sort_values(
        ["note_id", "ces_raw", "text_len", "has_body"],
        ascending=[True, False, False, False],
    )
    return score_df.drop_duplicates("note_id", keep="first").drop(columns=["has_body"])


def _assign_labels(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    # Keep source cohorts separate so older human data is not punished for a
    # different engagement baseline, but labels still mean "top within comparable
    # domain/cohort".
    out["label_group"] = out["source_type"] + "::" + out["domain"]
    out["ces_percentile"] = (
        out.groupby("label_group")["ces_raw"].rank(method="average", pct=True) * 100
    )
    return out


def _build_feature_frame(df: pd.DataFrame, semantic_path: Path | None = None) -> pd.DataFrame:
    semantic_by_id: dict[str, dict[str, float]] = {}
    if semantic_path and semantic_path.exists():
        try:
            sem = pd.read_parquet(semantic_path)
            for _, row in sem.iterrows():
                semantic_by_id[str(row["note_id"])] = {
                    col: float(row.get(col, 0.5) or 0.5)
                    for col in SEMANTIC_FEATURE_COLS
                }
        except Exception:
            semantic_by_id = {}

    records: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        feats = extract_features(
            {
                "note_title": row["note_title"],
                "desc": row["desc"],
                "local_time": row["local_time"] or "2024010112",
                "domain": row["domain"],
            }
        )
        record: dict[str, Any] = {col: float(feats.get(col, 0.0) or 0.0) for col in FEATURE_COLS}

        # v0.4 candidate is 62-column compatible, but only content features are
        # trusted initially. Optional semantic rows are allowed when present; all
        # visual/timing features are neutral so they cannot leak source artifacts.
        sem = semantic_by_id.get(str(row["note_id"]), {})
        for col in SEMANTIC_FEATURE_COLS:
            record[col] = float(sem.get(col, 0.5))
        for col in VISUAL_FEATURE_COLS:
            record[col] = 0.0
        for col in TIMING_FEATURE_COLS:
            record[col] = 0.0

        for meta_col in [
            "note_id",
            "note_title",
            "desc",
            "local_time",
            "domain",
            "source_type",
            "source_file",
            "liked_count",
            "collected_count",
            "comments_count",
            "ces_raw",
            "ces_percentile",
            "label_group",
        ]:
            record[meta_col] = row[meta_col]
        records.append(record)
    return pd.DataFrame(records)


def _raw_manifest(raw_dir: Path) -> dict[str, Any]:
    files: dict[str, dict[str, Any]] = {}
    for filename in RAW_FILES.values():
        path = raw_dir / filename
        if path.exists():
            files[filename] = {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "mtime_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            }
    return {"raw_dir": str(raw_dir), "files": files}


def build_v04_dataset(
    raw_dir: Path,
    output_dir: Path,
    *,
    semantic_path: Path | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized = load_normalized_rows(raw_dir)
    score_rows = _assign_labels(_dedupe_score_rows(normalized))
    feature_df = _build_feature_frame(score_rows, semantic_path=semantic_path)

    normalized_path = output_dir / "normalized_rows.parquet"
    score_path = output_dir / "score_rows.parquet"
    feature_path = output_dir / "features_v04.parquet"
    normalized.to_parquet(normalized_path, index=False)
    score_rows.to_parquet(score_path, index=False)
    feature_df.to_parquet(feature_path, index=False)

    source_counts = normalized["source_type"].value_counts().to_dict()
    score_source_counts = score_rows["source_type"].value_counts().to_dict()
    domain_counts = score_rows["domain"].value_counts().to_dict()
    duplicate_count = int(
        normalized[normalized["source_type"].isin(["human", "exploration"])]["note_id"].duplicated().sum()
    )
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "raw": _raw_manifest(raw_dir),
        "outputs": {
            "normalized_rows": str(normalized_path),
            "score_rows": str(score_path),
            "features": str(feature_path),
        },
        "rows": {
            "normalized": int(len(normalized)),
            "score_rows_deduped": int(len(score_rows)),
            "features": int(len(feature_df)),
            "score_duplicate_note_ids_removed": duplicate_count,
        },
        "source_counts_all": {str(k): int(v) for k, v in source_counts.items()},
        "source_counts_score": {str(k): int(v) for k, v in score_source_counts.items()},
        "domain_counts_score": {str(k): int(v) for k, v in domain_counts.items()},
        "labeling": {
            "ces_raw": "liked_count + collected_count + comments_count * 4",
            "ces_percentile": "rank percentile within source_type::domain",
            "aigc_rows": "excluded from score training; reserved for naturalness/AIGT auxiliary model",
        },
        "feature_columns": MODEL_FEATURE_COLS_V04,
    }
    manifest_path = output_dir / "dataset_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return feature_df, manifest


def summarize_feature_frame(df: pd.DataFrame) -> dict[str, Any]:
    return {
        "rows": int(len(df)),
        "unique_note_ids": int(df["note_id"].nunique()),
        "source_counts": {str(k): int(v) for k, v in df["source_type"].value_counts().items()},
        "domain_counts": {str(k): int(v) for k, v in df["domain"].value_counts().items()},
        "label_mean": float(df["ces_percentile"].mean()),
        "label_min": float(df["ces_percentile"].min()),
        "label_max": float(df["ces_percentile"].max()),
        "top_label_groups": {
            str(k): int(v) for k, v in Counter(df["label_group"]).most_common(20)
        },
    }
