#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NoteAI Pro — Model A v0.3 Training Script
LightGBM on 37 content features + 14 visual features + 8 timing features = 59 features
PLAD expanded from 4 → 13 features (RedNote-Vibe paper Table 2).

Three data paths merged into one training set:
  Path A (91,517 rows): features.parquet + timing_features.parquet
                         — full 37 content features + 8 timing
  Path B (10,000 rows): cover_metadata_v2.jsonl × cover_features_v2.parquet × timing_features.parquet
                         — 8 title features + 14 visual + 8 timing = 30 features (body/plad cols = 0)
  Path C (51,878 rows): features_human.parquet + timing_features_human.parquet
                         — full 37 content features + 8 timing (CES ranked within human set)
"""

import json
import sys
import warnings
from pathlib import Path

import lightgbm as lgb
import mlflow
import mlflow.lightgbm
import numpy as np
import pandas as pd
from sklearn.metrics import mean_squared_error
from sklearn.model_selection import train_test_split

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))
warnings.filterwarnings("ignore")

from feature_extraction import FEATURE_COLS, TIMING_FEATURE_COLS, SEMANTIC_FEATURE_COLS, extract_features  # noqa: E402

# ── Paths ─────────────────────────────────────────────────────────────────────

CONTENT_FEATURES   = BASE_DIR / "data" / "features.parquet"
TIMING_FEATURES    = BASE_DIR / "data" / "timing_features.parquet"
SEMANTIC_FEATURES  = BASE_DIR / "data" / "semantic_features.parquet"
COVER_METADATA     = BASE_DIR / "data" / "cover_metadata_v2.jsonl"
COVER_FEATURES_V2  = BASE_DIR / "data" / "cover_features_v2.parquet"
HUMAN_FEATURES     = BASE_DIR / "data" / "features_human.parquet"
HUMAN_TIMING       = BASE_DIR / "data" / "timing_features_human.parquet"
MODEL_DIR          = BASE_DIR / "artifacts"
MODEL_PATH         = MODEL_DIR / "model_a_v0.3.lgb"
MLFLOW_TRACKING    = f"sqlite:///{BASE_DIR / 'mlflow.db'}"

MODEL_DIR.mkdir(exist_ok=True)

# 14 visual feature columns from cover_features_v2.parquet
VISUAL_FEATURE_COLS = [
    "cover_brightness", "cover_warmth", "cover_saturation", "cover_contrast",
    "cover_sharpness", "cover_aspect_ratio", "cover_has_face", "cover_face_count",
    "cover_has_text", "cover_text_prominence", "cover_composition_score",
    "cover_aesthetic_score", "cover_emotion_intensity", "cover_visual_clarity",
]

# Semantic features are optional: included when semantic_features.parquet exists
_SEMANTIC_AVAILABLE = SEMANTIC_FEATURES.exists()
_EFFECTIVE_CONTENT_COLS = FEATURE_COLS + (SEMANTIC_FEATURE_COLS if _SEMANTIC_AVAILABLE else [])
ALL_FEATURE_COLS = _EFFECTIVE_CONTENT_COLS + VISUAL_FEATURE_COLS + TIMING_FEATURE_COLS
print(f"Feature set: {len(FEATURE_COLS)} local + "
      f"{len(SEMANTIC_FEATURE_COLS) if _SEMANTIC_AVAILABLE else 0} semantic + "
      f"{len(VISUAL_FEATURE_COLS)} visual + {len(TIMING_FEATURE_COLS)} timing "
      f"= {len(ALL_FEATURE_COLS)} total")

LGBM_PARAMS = {
    "num_leaves":        127,
    "n_estimators":      11000,
    "learning_rate":     0.05,
    "subsample":         0.8,
    "colsample_bytree":  0.8,
    "min_child_samples": 20,
    "reg_alpha":         0.1,
    "reg_lambda":        1.0,
    "random_state":      42,
    "n_jobs":            -1,
    "verbose":           -1,
}

_DOMAIN_MAP = {
    "运动健康": "运动", "家居家装": "家居", "亲子": "情感",
}


# ── Path B builder ────────────────────────────────────────────────────────────

def _build_path_b() -> pd.DataFrame | None:
    """cover_metadata_v2 × cover_features_v2 × timing_features → 30-feature rows."""
    if not COVER_METADATA.exists() or not TIMING_FEATURES.exists():
        return None

    print("Building Path B (cover_metadata × cover_features × timing) ...")
    df_timing = pd.read_parquet(TIMING_FEATURES).set_index("note_id")

    # Load cover visual features
    df_visual = None
    if COVER_FEATURES_V2.exists():
        df_visual = pd.read_parquet(COVER_FEATURES_V2)
        # index may already be note_id, or it may be a column
        if "note_id" not in df_visual.columns:
            df_visual = df_visual.reset_index().rename(columns={"index": "note_id"})
        df_visual = df_visual.set_index("note_id")
        print(f"  cover_features_v2: {len(df_visual)} rows × {len(VISUAL_FEATURE_COLS)} visual cols")

    records = []
    with open(COVER_METADATA, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue

            note_id = row.get("note_id", "")
            title   = row.get("note_title", "") or ""
            channel = row.get("channel", "")
            domain  = _DOMAIN_MAP.get(channel, channel) or "综合"
            liked   = int(row.get("liked_count", 0) or 0)

            # Title-based content features
            try:
                feats = extract_features({
                    "note_title": title, "desc": "", "domain": domain,
                    "local_time": "2024010112", "liked_count": liked,
                    "collected_count": 0, "comments_count": 0,
                })
            except Exception:
                feats = {c: 0 for c in FEATURE_COLS}

            record = {c: feats.get(c, 0) for c in FEATURE_COLS}

            # Visual features
            for vc in VISUAL_FEATURE_COLS:
                if df_visual is not None and note_id in df_visual.index:
                    record[vc] = float(df_visual.loc[note_id, vc]) if vc in df_visual.columns else 0.0
                else:
                    record[vc] = 0.0

            # Timing features
            for tc in TIMING_FEATURE_COLS:
                record[tc] = float(df_timing.loc[note_id, tc]) if note_id in df_timing.index else 0.0

            record["note_id"]     = note_id
            record["liked_count"] = liked
            record["domain"]      = domain
            records.append(record)

    if not records:
        return None

    df_b = pd.DataFrame(records)
    df_b["ces_percentile"] = df_b.groupby("domain")["liked_count"].rank(pct=True) * 100
    has_visual = (df_b[VISUAL_FEATURE_COLS].abs().sum(axis=1) > 0).sum()
    has_timing = (df_b[TIMING_FEATURE_COLS].abs().sum(axis=1) > 0).sum()
    print(f"  Path B: {len(df_b)} rows | visual={has_visual} | timing={has_timing}")
    return df_b


# ── Path C builder ────────────────────────────────────────────────────────────

def _build_path_c() -> pd.DataFrame | None:
    """training_set_human features + timing — full 28 content + 8 timing."""
    if not HUMAN_FEATURES.exists():
        print(f"[SKIP] Path C: {HUMAN_FEATURES} not found")
        return None

    print(f"Building Path C (training_set_human) ...")
    df_c = pd.read_parquet(HUMAN_FEATURES)
    print(f"  features_human: {len(df_c)} rows")

    if HUMAN_TIMING.exists():
        df_t = pd.read_parquet(HUMAN_TIMING)
        df_c = df_c.merge(df_t, on="note_id", how="left")
        matched = df_t["note_id"].isin(df_c["note_id"]).sum()
        print(f"  timing_human matched: {matched:,}")
    else:
        print(f"  [WARN] {HUMAN_TIMING} not found, timing cols = 0")

    for col in VISUAL_FEATURE_COLS:
        df_c[col] = 0.0  # no cover images for human dataset

    return df_c


# ── Main data loader ──────────────────────────────────────────────────────────

def load_data() -> tuple[pd.DataFrame, dict]:
    # ── Path A ────────────────────────────────────────────────────────────────
    print(f"Path A: {CONTENT_FEATURES}")
    df_a = pd.read_parquet(CONTENT_FEATURES)
    if TIMING_FEATURES.exists():
        df_t = pd.read_parquet(TIMING_FEATURES)
        df_a = df_a.merge(df_t, on="note_id", how="left")
    if _SEMANTIC_AVAILABLE:
        df_s = pd.read_parquet(SEMANTIC_FEATURES)
        df_a = df_a.merge(df_s, on="note_id", how="left")
        matched = df_s["note_id"].isin(df_a["note_id"]).sum()
        print(f"  Semantic features joined: {matched:,} rows")
    for col in VISUAL_FEATURE_COLS:
        df_a[col] = 0.0
    print(f"  Shape: {df_a.shape}")

    # ── Path B ────────────────────────────────────────────────────────────────
    df_b = _build_path_b()

    # ── Path C ────────────────────────────────────────────────────────────────
    # Human dataset has mean liked_count=50 vs exploring_set mean=2834 (56x gap).
    # Global CES recomputation pushes human notes to the bottom quartile even when
    # their content features are comparable, creating an unbridgeable signal gap.
    # Human data is therefore disabled until we have a population-aware labeling strategy.
    df_c = None  # _build_path_c() disabled — see comment above

    # ── Merge, dedup on note_id ───────────────────────────────────────────────
    shared = ALL_FEATURE_COLS + ["ces_percentile", "note_id"]
    parts = [df_a]
    if df_b is not None:
        existing_ids = set(df_a["note_id"].dropna())
        df_b_new = df_b[~df_b["note_id"].isin(existing_ids)]
        if len(df_b_new):
            parts.append(df_b_new)
            print(f"  Path B adds {len(df_b_new):,} new rows")
    if df_c is not None:
        existing_ids = set(pd.concat([p["note_id"] for p in parts]).dropna())
        df_c_new = df_c[~df_c["note_id"].isin(existing_ids)]
        if len(df_c_new):
            parts.append(df_c_new)
            print(f"  Path C adds {len(df_c_new):,} new rows")

    df = pd.concat(
        [p[[c for c in (shared + ["liked_count"]) if c in p.columns]] for p in parts],
        ignore_index=True,
    )
    # Each path keeps its own per-dataset CES percentile (internally consistent).
    # A global recomputation would mix populations with different base engagement rates
    # (exploring_set median=1 vs cover_metadata median=232), creating label noise.

    for col in ALL_FEATURE_COLS:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = df[col].fillna(0.0)

    stats = {
        "total": len(df),
        "n_timing": int((df[TIMING_FEATURE_COLS].abs().sum(axis=1) > 0).sum()),
        "n_visual": int((df[VISUAL_FEATURE_COLS].abs().sum(axis=1) > 0).sum()),
    }
    print(f"\nFinal dataset : {stats['total']:,} rows × {len(ALL_FEATURE_COLS)} features")
    print(f"  timing > 0  : {stats['n_timing']:,} ({stats['n_timing']/stats['total']*100:.1f}%)")
    print(f"  visual > 0  : {stats['n_visual']:,} ({stats['n_visual']/stats['total']*100:.1f}%)")
    return df, stats


# ── Training ──────────────────────────────────────────────────────────────────

def train():
    mlflow.set_tracking_uri(MLFLOW_TRACKING)
    mlflow.set_experiment("model_a_v0.3")

    with mlflow.start_run(run_name="v0.3_50feat_ABC"):
        df, stats = load_data()

        X = df[ALL_FEATURE_COLS].fillna(0.0).astype(float)
        y = df["ces_percentile"]

        print(f"\nTarget: {y.min():.1f} – {y.max():.1f}  (mean {y.mean():.1f})")

        X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.20, random_state=42)
        print(f"Train: {len(X_train):,}  Val: {len(X_val):,}")

        print(f"\nTraining LightGBM ({len(ALL_FEATURE_COLS)} features) ...")
        model = lgb.LGBMRegressor(**LGBM_PARAMS)
        model.fit(X_train, y_train, eval_set=[(X_val, y_val)],
                  callbacks=[lgb.log_evaluation(1000), lgb.early_stopping(500, verbose=False)])

        y_pred = model.predict(X_val)
        rmse_val = float(np.sqrt(mean_squared_error(y_val, y_pred)))
        acc_10pt = float(np.mean(np.abs(y_pred - y_val) <= 10) * 100)

        print(f"\n{'='*52}")
        print(f"Val RMSE       : {rmse_val:.4f}")
        print(f"Accuracy ±10pt : {acc_10pt:.2f}%")
        print(f"{'='*52}")

        importance = pd.Series(
            model.booster_.feature_importance(importance_type="gain"),
            index=ALL_FEATURE_COLS,
        ).sort_values(ascending=False)

        print("\nTop-20 features by gain importance:")
        print(importance.head(20).round(2).to_string())

        c_imp = importance[FEATURE_COLS].sum()
        v_imp = importance[VISUAL_FEATURE_COLS].sum()
        t_imp = importance[TIMING_FEATURE_COLS].sum()
        total = c_imp + v_imp + t_imp
        if total > 0:
            print(f"\nContent group : {c_imp/total*100:.1f}%")
            print(f"Visual  group : {v_imp/total*100:.1f}%")
            print(f"Timing  group : {t_imp/total*100:.1f}%")

        model.booster_.save_model(str(MODEL_PATH))
        print(f"\nModel saved → {MODEL_PATH}")

        mlflow.log_params({**LGBM_PARAMS,
                           "num_features": len(ALL_FEATURE_COLS),
                           "n_content": len(FEATURE_COLS),
                           "n_semantic": len(SEMANTIC_FEATURE_COLS) if _SEMANTIC_AVAILABLE else 0,
                           "n_visual": len(VISUAL_FEATURE_COLS),
                           "n_timing": len(TIMING_FEATURE_COLS),
                           "train_rows": len(X_train), "val_rows": len(X_val),
                           "total_rows": stats["total"]})
        mlflow.log_metric("rmse_val",  rmse_val)
        mlflow.log_metric("acc_10pt",  acc_10pt)
        mlflow.log_metric("n_timing_rows", float(stats["n_timing"]))
        mlflow.log_metric("n_visual_rows", float(stats["n_visual"]))
        mlflow.lightgbm.log_model(model.booster_, "model")

        return model, rmse_val, acc_10pt


if __name__ == "__main__":
    train()
