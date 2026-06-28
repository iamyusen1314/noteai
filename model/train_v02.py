"""
NoteAI Pro — Model A v0.2 Training Script
LightGBM on 8 title features + 14 cover features = 22 features
Target: liked_count percentile within channel (0-100)
Data: 10,000 homefeed notes with cover images + display_title
"""

import warnings
from pathlib import Path

import lightgbm as lgb
import mlflow
import mlflow.lightgbm
import numpy as np
import pandas as pd
from sklearn.metrics import mean_squared_error
from sklearn.model_selection import train_test_split

from feature_extraction import (
    POS_EMOTION, NEG_EMOTION, PRICE_WORDS, NEW_SIGNAL, CHINESE_CITIES,
    has_any, DOMAIN_MAP,
)

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).parent
METADATA_V2 = BASE_DIR / "data/cover_metadata_v2.jsonl"
COVER_FEATURES_V2 = BASE_DIR / "data/cover_features_v2.parquet"
MODEL_DIR = BASE_DIR / "artifacts"
MODEL_DIR.mkdir(exist_ok=True)

LGBM_PARAMS = {
    "objective": "regression",
    "metric": "rmse",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "max_depth": -1,
    "min_child_samples": 30,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "reg_alpha": 0.1,
    "reg_lambda": 0.1,
    "verbose": -1,
    "n_jobs": -1,
}

TITLE_FEATURE_COLS = [
    "title_len", "title_has_pos_emotion", "title_has_neg_emotion",
    "title_has_price", "title_has_question", "title_has_number",
    "title_has_new_signal", "title_has_city",
]

COVER_FEATURE_COLS = [
    "cover_brightness", "cover_warmth", "cover_saturation", "cover_contrast",
    "cover_sharpness", "cover_aspect_ratio", "cover_has_face", "cover_face_count",
    "cover_has_text", "cover_text_prominence", "cover_composition_score",
    "cover_aesthetic_score", "cover_emotion_intensity", "cover_visual_clarity",
]

import re

def extract_title_features(title: str) -> dict:
    title = title or ""
    return {
        "title_len": len(title),
        "title_has_pos_emotion": has_any(title, POS_EMOTION),
        "title_has_neg_emotion": has_any(title, NEG_EMOTION),
        "title_has_price": has_any(title, PRICE_WORDS),
        "title_has_question": int("?" in title or "？" in title),
        "title_has_number": int(bool(re.search(r"\d", title))),
        "title_has_new_signal": has_any(title, NEW_SIGNAL),
        "title_has_city": has_any(title, CHINESE_CITIES),
    }


def load_data() -> pd.DataFrame:
    import json

    # Load metadata (title + liked_count + channel)
    print("Loading metadata...")
    meta_rows = []
    with open(METADATA_V2) as f:
        for line in f:
            try:
                meta_rows.append(json.loads(line.strip()))
            except Exception:
                continue
    df_meta = pd.DataFrame(meta_rows)
    print(f"  Metadata: {len(df_meta):,} rows")

    # Extract title features
    print("Extracting title features...")
    title_feats = [extract_title_features(r) for r in df_meta["note_title"]]
    df_title = pd.DataFrame(title_feats)
    df_meta = pd.concat([df_meta.reset_index(drop=True), df_title], axis=1)

    # Load cover features
    print("Loading cover features...")
    df_cover = pd.read_parquet(COVER_FEATURES_V2)
    df_cover = df_cover.reset_index()  # note_id becomes a column
    print(f"  Cover features: {len(df_cover):,} rows")

    # Merge on note_id
    df = df_meta.merge(df_cover[["note_id"] + COVER_FEATURE_COLS],
                       on="note_id", how="inner")
    print(f"  After merge: {len(df):,} rows")

    # Channel → domain encoding
    DOMAIN_LABELS = list(DOMAIN_MAP.values()) + ["others"]
    df["domain_encoded"] = df["channel"].map(
        lambda ch: DOMAIN_LABELS.index(DOMAIN_MAP.get(ch, "others"))
    )

    # Target: percentile rank of liked_count within channel (0-100)
    df["target"] = df.groupby("channel")["liked_count"].rank(pct=True) * 100

    return df


def train():
    mlflow.set_experiment("noteai_model_a")

    with mlflow.start_run(run_name="v0.2_title_cover"):
        df = load_data()

        ALL_FEATURE_COLS = TITLE_FEATURE_COLS + COVER_FEATURE_COLS
        X = df[ALL_FEATURE_COLS].fillna(0).astype(float)
        y = df["target"]

        print(f"\nDataset : {len(df):,} rows × {len(ALL_FEATURE_COLS)} features")
        print(f"Target  : {y.min():.1f} – {y.max():.1f}  (mean {y.mean():.1f})")

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.15, random_state=42
        )
        X_train, X_val, y_train, y_val = train_test_split(
            X_train, y_train, test_size=0.15, random_state=42
        )
        print(f"Train: {len(X_train):,}  Val: {len(X_val):,}  Test: {len(X_test):,}")

        dtrain = lgb.Dataset(X_train, label=y_train)
        dval = lgb.Dataset(X_val, label=y_val, reference=dtrain)

        print("\nTraining LightGBM (title + cover, 22 features)...")
        model = lgb.train(
            LGBM_PARAMS,
            dtrain,
            num_boost_round=1000,
            valid_sets=[dtrain, dval],
            valid_names=["train", "val"],
            callbacks=[
                lgb.early_stopping(50, verbose=False),
                lgb.log_evaluation(100),
            ],
        )

        y_pred_val = model.predict(X_val)
        y_pred_test = model.predict(X_test)
        rmse_val = np.sqrt(mean_squared_error(y_val, y_pred_val))
        rmse_test = np.sqrt(mean_squared_error(y_test, y_pred_test))
        acc_10 = np.mean(np.abs(y_pred_test - y_test) <= 10) * 100

        print(f"\n{'='*45}")
        print(f"Val  RMSE : {rmse_val:.2f}")
        print(f"Test RMSE : {rmse_test:.2f}  (target: <15)")
        print(f"±10pt acc : {acc_10:.1f}%")
        print(f"Best iter : {model.best_iteration}")
        print(f"{'='*45}")

        importance = pd.Series(
            model.feature_importance(importance_type="gain"),
            index=ALL_FEATURE_COLS,
        ).sort_values(ascending=False)
        print("\nTop-15 feature importance (gain):")
        print(importance.head(15).round(1).to_string())
        print()

        # Show cover vs title group importance
        cover_imp = importance[COVER_FEATURE_COLS].sum()
        title_imp = importance[TITLE_FEATURE_COLS].sum()
        total_imp = cover_imp + title_imp
        print(f"Cover features contribution : {cover_imp/total_imp*100:.1f}%")
        print(f"Title features contribution : {title_imp/total_imp*100:.1f}%")

        mlflow.log_params(LGBM_PARAMS)
        mlflow.log_param("num_features", len(ALL_FEATURE_COLS))
        mlflow.log_param("train_rows", len(X_train))
        mlflow.log_param("data_source", "homefeed_v2_title_cover")
        mlflow.log_metric("rmse_val", rmse_val)
        mlflow.log_metric("rmse_test", rmse_test)
        mlflow.log_metric("acc_within_10pt", acc_10)
        mlflow.log_metric("best_iteration", model.best_iteration)
        mlflow.lightgbm.log_model(model, "model")

        model_path = MODEL_DIR / "model_a_v0.2.lgb"
        model.save_model(str(model_path))
        print(f"\nModel saved: {model_path}")

        return model, rmse_test


if __name__ == "__main__":
    train()
