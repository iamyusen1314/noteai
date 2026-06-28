#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NoteAI Model A v0.4 candidate trainer.

Safety goals:
- canonical RedNote-Vibe schema normalization
- one row per note_id for scoring
- one consistent CES label definition
- GroupShuffleSplit by note_id to avoid leakage
- source/domain calibration report before any deployment
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import GroupShuffleSplit

from rednote_vibe_v04 import MODEL_FEATURE_COLS_V04, build_v04_dataset, summarize_feature_frame


BASE_DIR = Path(__file__).parent
DEFAULT_RAW_DIR = BASE_DIR / "data" / "RedNote-Vibe-Dataset"
DEFAULT_OUTPUT_DIR = BASE_DIR / "data" / "v04"
DEFAULT_ARTIFACT_DIR = BASE_DIR / "artifacts"
DEFAULT_SEMANTIC_PATH = BASE_DIR / "data" / "semantic_features.parquet"


LGBM_PARAMS = {
    "objective": "regression_l2",
    "num_leaves": 63,
    "n_estimators": 5000,
    "learning_rate": 0.03,
    "subsample": 0.85,
    "colsample_bytree": 0.85,
    "min_child_samples": 80,
    "reg_alpha": 0.2,
    "reg_lambda": 2.0,
    "random_state": 42,
    "n_jobs": -1,
    "verbose": -1,
}


def _clip(values: np.ndarray) -> np.ndarray:
    return np.clip(values.astype(float), 0.0, 100.0)


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    pred = _clip(y_pred)
    y = y_true.astype(float)
    return {
        "rmse": float(np.sqrt(mean_squared_error(y, pred))),
        "mae": float(mean_absolute_error(y, pred)),
        "acc_5pt": float(np.mean(np.abs(pred - y) <= 5) * 100),
        "acc_10pt": float(np.mean(np.abs(pred - y) <= 10) * 100),
        "bias": float(np.mean(pred - y)),
        "spearman": float(pd.Series(pred).corr(pd.Series(y), method="spearman")),
    }


def _group_metrics(df: pd.DataFrame, group_col: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group, part in df.groupby(group_col):
        if len(part) < 20:
            continue
        m = _metrics(part["y_true"].to_numpy(float), part["y_pred"].to_numpy(float))
        rows.append(
            {
                group_col: str(group),
                "rows": int(len(part)),
                "label_mean": float(part["y_true"].mean()),
                "pred_mean": float(part["y_pred"].mean()),
                **m,
            }
        )
    return sorted(rows, key=lambda item: item["rows"], reverse=True)


def _calibration_table(df: pd.DataFrame) -> list[dict[str, Any]]:
    out = df.copy()
    try:
        out["pred_bucket"] = pd.qcut(out["y_pred"], 10, duplicates="drop")
    except ValueError:
        return []
    rows = []
    for bucket, part in out.groupby("pred_bucket", observed=True):
        rows.append(
            {
                "bucket": str(bucket),
                "rows": int(len(part)),
                "pred_mean": float(part["y_pred"].mean()),
                "label_mean": float(part["y_true"].mean()),
                "bias": float((part["y_pred"] - part["y_true"]).mean()),
            }
        )
    return rows


def _sample_weights(df: pd.DataFrame, human_weight: float) -> np.ndarray:
    weights = np.ones(len(df), dtype=float)
    weights[df["source_type"].to_numpy() == "human"] = human_weight
    return weights


def _assert_no_leakage(train_df: pd.DataFrame, val_df: pd.DataFrame) -> dict[str, Any]:
    train_ids = set(train_df["note_id"].astype(str))
    val_ids = set(val_df["note_id"].astype(str))
    overlap = train_ids & val_ids
    return {
        "train_unique_note_ids": len(train_ids),
        "val_unique_note_ids": len(val_ids),
        "overlap_note_ids": len(overlap),
        "passed": len(overlap) == 0,
    }


def train_candidate(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    artifact_dir = Path(args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    feature_path = output_dir / "features_v04.parquet"
    if args.rebuild_dataset or not feature_path.exists():
        feature_df, dataset_manifest = build_v04_dataset(
            Path(args.raw_dir),
            output_dir,
            semantic_path=Path(args.semantic_path) if args.use_semantic else None,
        )
    else:
        feature_df = pd.read_parquet(feature_path)
        manifest_path = output_dir / "dataset_manifest.json"
        dataset_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}

    for col in MODEL_FEATURE_COLS_V04:
        if col not in feature_df.columns:
            feature_df[col] = 0.0
        feature_df[col] = pd.to_numeric(feature_df[col], errors="coerce").fillna(0.0)

    feature_df = feature_df.dropna(subset=["ces_percentile", "note_id"]).copy()
    X = feature_df[MODEL_FEATURE_COLS_V04].astype(float)
    y = feature_df["ces_percentile"].astype(float).to_numpy()
    groups = feature_df["note_id"].astype(str).to_numpy()

    splitter = GroupShuffleSplit(
        n_splits=1,
        test_size=args.val_size,
        random_state=args.random_state,
    )
    train_idx, val_idx = next(splitter.split(X, y, groups=groups))
    train_df = feature_df.iloc[train_idx].copy()
    val_df = feature_df.iloc[val_idx].copy()
    leakage = _assert_no_leakage(train_df, val_df)
    if not leakage["passed"]:
        raise RuntimeError(f"Group split leaked note_ids: {leakage}")

    model = lgb.LGBMRegressor(**{**LGBM_PARAMS, "random_state": args.random_state})
    model.fit(
        X.iloc[train_idx],
        y[train_idx],
        sample_weight=_sample_weights(train_df, args.human_weight),
        eval_set=[(X.iloc[val_idx], y[val_idx])],
        eval_sample_weight=[_sample_weights(val_df, args.human_weight)],
        callbacks=[
            lgb.early_stopping(args.early_stopping_rounds, verbose=False),
            lgb.log_evaluation(args.log_period),
        ],
    )

    pred_val = _clip(model.predict(X.iloc[val_idx]))
    eval_df = val_df[
        ["note_id", "domain", "source_type", "label_group", "ces_percentile", "ces_raw"]
    ].copy()
    eval_df["y_true"] = y[val_idx]
    eval_df["y_pred"] = pred_val
    eval_df["abs_error"] = (eval_df["y_pred"] - eval_df["y_true"]).abs()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    model_path = artifact_dir / f"model_a_v0.4_candidate_{run_id}.lgb"
    latest_candidate_path = artifact_dir / "model_a_v0.4_candidate.lgb"
    model.booster_.save_model(str(model_path))
    model.booster_.save_model(str(latest_candidate_path))

    importance = (
        pd.Series(model.booster_.feature_importance(importance_type="gain"), index=MODEL_FEATURE_COLS_V04)
        .sort_values(ascending=False)
        .reset_index()
        .rename(columns={"index": "feature", 0: "gain"})
    )

    report = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": {
            "version": "v0.4-candidate",
            "path": str(model_path),
            "latest_candidate_path": str(latest_candidate_path),
            "feature_count": len(MODEL_FEATURE_COLS_V04),
            "feature_columns": MODEL_FEATURE_COLS_V04,
            "params": {**LGBM_PARAMS, "random_state": args.random_state},
            "best_iteration": int(model.best_iteration_ or 0),
        },
        "dataset": dataset_manifest,
        "dataset_summary": summarize_feature_frame(feature_df),
        "split": {
            "method": "GroupShuffleSplit(note_id)",
            "val_size": args.val_size,
            "random_state": args.random_state,
            "train_rows": int(len(train_df)),
            "val_rows": int(len(val_df)),
            "leakage": leakage,
            "human_weight": args.human_weight,
        },
        "metrics": _metrics(eval_df["y_true"].to_numpy(float), eval_df["y_pred"].to_numpy(float)),
        "metrics_by_domain": _group_metrics(eval_df, "domain"),
        "metrics_by_source": _group_metrics(eval_df, "source_type"),
        "metrics_by_label_group": _group_metrics(eval_df, "label_group"),
        "calibration": _calibration_table(eval_df),
        "top_features_gain": importance.head(40).to_dict(orient="records"),
    }

    report_path = artifact_dir / f"model_a_v0.4_report_{run_id}.json"
    latest_report_path = artifact_dir / "model_a_v0.4_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    eval_df.to_parquet(output_dir / f"validation_predictions_{run_id}.parquet", index=False)
    importance.to_csv(output_dir / f"feature_importance_{run_id}.csv", index=False)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train NoteAI Model A v0.4 candidate")
    parser.add_argument("--raw-dir", default=str(DEFAULT_RAW_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--artifact-dir", default=str(DEFAULT_ARTIFACT_DIR))
    parser.add_argument("--semantic-path", default=str(DEFAULT_SEMANTIC_PATH))
    parser.add_argument("--use-semantic", action="store_true", help="Use existing semantic_features.parquet when available")
    parser.add_argument("--rebuild-dataset", action="store_true")
    parser.add_argument("--val-size", type=float, default=0.20)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--human-weight", type=float, default=0.85)
    parser.add_argument("--early-stopping-rounds", type=int, default=250)
    parser.add_argument("--log-period", type=int, default=250)
    return parser.parse_args()


def main() -> None:
    report = train_candidate(parse_args())
    print(json.dumps({
        "model": report["model"]["latest_candidate_path"],
        "feature_count": report["model"]["feature_count"],
        "rows": report["dataset_summary"]["rows"],
        "metrics": report["metrics"],
        "leakage": report["split"]["leakage"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
