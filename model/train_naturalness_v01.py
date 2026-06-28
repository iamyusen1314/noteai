#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Train a RedNote-Vibe AIGT / naturalness auxiliary model."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    confusion_matrix,
    precision_recall_fscore_support,
    roc_auc_score,
)

from rednote_vibe_v04 import load_normalized_rows
from text_naturalness_features import NATURALNESS_FEATURE_COLS, extract_naturalness_features


BASE_DIR = Path(__file__).parent
DEFAULT_RAW_DIR = BASE_DIR / "data" / "RedNote-Vibe-Dataset"
DEFAULT_OUTPUT_DIR = BASE_DIR / "data" / "naturalness_v01"
DEFAULT_ARTIFACT_DIR = BASE_DIR / "artifacts"

VAL_AI_MODELS = {"claude-sonnet-4", "gpt-4.1", "qwen3", "gemini-2.5"}

LGBM_PARAMS = {
    "objective": "binary",
    "n_estimators": 3000,
    "learning_rate": 0.03,
    "num_leaves": 63,
    "subsample": 0.85,
    "colsample_bytree": 0.85,
    "min_child_samples": 60,
    "reg_alpha": 0.2,
    "reg_lambda": 2.0,
    "random_state": 42,
    "n_jobs": -1,
    "verbose": -1,
    "class_weight": "balanced",
}


def _build_feature_frame(raw_dir: Path, output_dir: Path, force: bool = False) -> pd.DataFrame:
    output_dir.mkdir(parents=True, exist_ok=True)
    feature_path = output_dir / "features_naturalness_v01.parquet"
    if feature_path.exists() and not force:
        return pd.read_parquet(feature_path)

    rows = load_normalized_rows(raw_dir)
    rows = rows[rows["source_type"].isin(["human", "aigc"])].copy()
    rows = rows[rows["text_len"] >= 20].copy()
    records: list[dict[str, Any]] = []
    for _, row in rows.iterrows():
        feats = extract_naturalness_features(row["note_title"], row["desc"], row["domain"])
        feats.update(
            {
                "note_id": row["note_id"],
                "domain": row["domain"],
                "source_type": row["source_type"],
                "model_family": row.get("model_family", ""),
                "model": row.get("model", ""),
                "is_ai": 1 if row["source_type"] == "aigc" else 0,
            }
        )
        records.append(feats)
    df = pd.DataFrame(records)
    df.to_parquet(feature_path, index=False)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "raw_dir": str(raw_dir),
        "feature_path": str(feature_path),
        "rows": int(len(df)),
        "source_counts": {str(k): int(v) for k, v in df["source_type"].value_counts().items()},
        "domain_counts": {str(k): int(v) for k, v in df["domain"].value_counts().items()},
        "ai_model_counts": {str(k): int(v) for k, v in df[df["is_ai"] == 1]["model"].value_counts().items()},
        "feature_columns": NATURALNESS_FEATURE_COLS,
        "excluded_features": "time and domain-encoding features are excluded to reduce source leakage",
    }
    (output_dir / "dataset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return df


def _split_model_holdout(df: pd.DataFrame, random_state: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(random_state)
    ai_val = (df["is_ai"] == 1) & (df["model"].isin(VAL_AI_MODELS))
    human_idx = df.index[df["is_ai"] == 0].to_numpy()
    rng.shuffle(human_idx)
    val_human_count = max(1, int(len(human_idx) * 0.2))
    human_val_set = set(human_idx[:val_human_count])
    human_val = df.index.to_series().isin(human_val_set)
    val_mask = ai_val | human_val
    train_idx = df.index[~val_mask].to_numpy()
    val_idx = df.index[val_mask].to_numpy()
    return train_idx, val_idx


def _metrics(y_true: np.ndarray, prob: np.ndarray, threshold: float = 0.5) -> dict[str, Any]:
    pred = (prob >= threshold).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true, pred, average="binary", zero_division=0
    )
    tn, fp, fn, tp = confusion_matrix(y_true, pred, labels=[0, 1]).ravel()
    return {
        "roc_auc": float(roc_auc_score(y_true, prob)),
        "average_precision": float(average_precision_score(y_true, prob)),
        "accuracy": float(accuracy_score(y_true, pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, pred)),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "threshold": threshold,
        "confusion": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "human_false_positive_rate": float(fp / max(fp + tn, 1)),
        "ai_false_negative_rate": float(fn / max(fn + tp, 1)),
    }


def _threshold_table(y_true: np.ndarray, prob: np.ndarray) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for threshold in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
        m = _metrics(y_true, prob, threshold)
        rows.append(
            {
                key: m[key]
                for key in [
                    "threshold",
                    "precision",
                    "recall",
                    "f1",
                    "human_false_positive_rate",
                    "ai_false_negative_rate",
                ]
            }
        )
    return rows


def _group_metrics(eval_df: pd.DataFrame, group_col: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group, part in eval_df.groupby(group_col):
        if len(part) < 20 or part["is_ai"].nunique() < 2:
            continue
        m = _metrics(part["is_ai"].to_numpy(int), part["ai_probability"].to_numpy(float))
        rows.append({"group": str(group), "rows": int(len(part)), **m})
    return sorted(rows, key=lambda item: item["rows"], reverse=True)


def train(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    artifact_dir = Path(args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    df = _build_feature_frame(Path(args.raw_dir), output_dir, force=args.rebuild_features)

    for col in NATURALNESS_FEATURE_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    train_idx, val_idx = _split_model_holdout(df, args.random_state)
    train_df = df.loc[train_idx].copy()
    val_df = df.loc[val_idx].copy()

    model = lgb.LGBMClassifier(**{**LGBM_PARAMS, "random_state": args.random_state})
    model.fit(
        train_df[NATURALNESS_FEATURE_COLS].astype(float),
        train_df["is_ai"].astype(int),
        eval_set=[(val_df[NATURALNESS_FEATURE_COLS].astype(float), val_df["is_ai"].astype(int))],
        callbacks=[
            lgb.early_stopping(args.early_stopping_rounds, verbose=False),
            lgb.log_evaluation(args.log_period),
        ],
    )

    prob = model.predict_proba(val_df[NATURALNESS_FEATURE_COLS].astype(float))[:, 1]
    eval_df = val_df[["note_id", "domain", "source_type", "model_family", "model", "is_ai"]].copy()
    eval_df["ai_probability"] = prob
    eval_df["naturalness_score"] = (1.0 - prob) * 100

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    model_path = artifact_dir / f"model_naturalness_v0.1_{run_id}.lgb"
    latest_path = artifact_dir / "model_naturalness_v0.1.lgb"
    model.booster_.save_model(str(model_path))
    model.booster_.save_model(str(latest_path))

    importance = (
        pd.Series(model.booster_.feature_importance(importance_type="gain"), index=NATURALNESS_FEATURE_COLS)
        .sort_values(ascending=False)
        .reset_index()
        .rename(columns={"index": "feature", 0: "gain"})
    )
    report = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": {
            "version": "naturalness-v0.1-candidate",
            "path": str(model_path),
            "latest_candidate_path": str(latest_path),
            "feature_count": len(NATURALNESS_FEATURE_COLS),
            "feature_columns": NATURALNESS_FEATURE_COLS,
            "best_iteration": int(model.best_iteration_ or 0),
            "params": {**LGBM_PARAMS, "random_state": args.random_state},
        },
        "split": {
            "method": "AI model holdout + 20% human random holdout",
            "held_out_ai_models": sorted(VAL_AI_MODELS),
            "train_rows": int(len(train_df)),
            "val_rows": int(len(val_df)),
            "train_source_counts": {str(k): int(v) for k, v in train_df["source_type"].value_counts().items()},
            "val_source_counts": {str(k): int(v) for k, v in val_df["source_type"].value_counts().items()},
        },
        "metrics": _metrics(eval_df["is_ai"].to_numpy(int), eval_df["ai_probability"].to_numpy(float)),
        "threshold_table": _threshold_table(eval_df["is_ai"].to_numpy(int), eval_df["ai_probability"].to_numpy(float)),
        "metrics_by_domain": _group_metrics(eval_df, "domain"),
        "metrics_by_model_family": _group_metrics(eval_df, "model_family"),
        "top_features_gain": importance.head(40).to_dict(orient="records"),
    }

    report_path = artifact_dir / f"model_naturalness_v0.1_report_{run_id}.json"
    latest_report = artifact_dir / "model_naturalness_v0.1_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    eval_df.to_parquet(output_dir / f"validation_predictions_{run_id}.parquet", index=False)
    importance.to_csv(output_dir / f"feature_importance_{run_id}.csv", index=False)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train NoteAI naturalness/AIGT auxiliary model")
    parser.add_argument("--raw-dir", default=str(DEFAULT_RAW_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--artifact-dir", default=str(DEFAULT_ARTIFACT_DIR))
    parser.add_argument("--rebuild-features", action="store_true")
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--early-stopping-rounds", type=int, default=200)
    parser.add_argument("--log-period", type=int, default=250)
    return parser.parse_args()


def main() -> None:
    report = train(parse_args())
    print(
        json.dumps(
            {
                "model": report["model"]["latest_candidate_path"],
                "feature_count": report["model"]["feature_count"],
                "split": report["split"],
                "metrics": report["metrics"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
