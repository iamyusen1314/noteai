"""
NoteAI Pro — Model A v0.1 Training Script
LightGBM regression on CES percentile score (0-100)
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

from feature_extraction import FEATURE_COLS, TARGET_COL, load_and_extract

warnings.filterwarnings("ignore")

DATA_PATH = Path(__file__).parent / "data/RedNote-Vibe-Dataset/exploring_set.jsonl"
FEATURES_PATH = Path(__file__).parent / "data/features.parquet"
MODEL_DIR = Path(__file__).parent / "artifacts"
MODEL_DIR.mkdir(exist_ok=True)

LGBM_PARAMS = {
    "objective": "regression",
    "metric": "rmse",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "max_depth": -1,
    "min_child_samples": 50,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "reg_alpha": 0.1,
    "reg_lambda": 0.1,
    "verbose": -1,
    "n_jobs": -1,
}


def load_data() -> pd.DataFrame:
    if FEATURES_PATH.exists():
        print(f"Loading cached features from {FEATURES_PATH}")
        return pd.read_parquet(FEATURES_PATH)
    print("No cache found, running feature extraction...")
    df = load_and_extract(str(DATA_PATH))
    df.to_parquet(FEATURES_PATH, index=False)
    return df


def train():
    mlflow.set_experiment("noteai_model_a")

    with mlflow.start_run(run_name="v0.1_rednote_vibe"):
        # ── Load data ──────────────────────────────────────────
        df = load_data()

        X = df[FEATURE_COLS].fillna(0).astype(float)
        y = df[TARGET_COL].fillna(50.0)

        print(f"\nDataset: {len(df):,} rows × {len(FEATURE_COLS)} features")
        print(f"Target range: {y.min():.1f} – {y.max():.1f}  (mean {y.mean():.1f})")

        # ── Split ──────────────────────────────────────────────
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.15, random_state=42
        )
        X_train, X_val, y_train, y_val = train_test_split(
            X_train, y_train, test_size=0.15, random_state=42
        )
        print(f"Train: {len(X_train):,}  Val: {len(X_val):,}  Test: {len(X_test):,}")

        # ── Train ──────────────────────────────────────────────
        dtrain = lgb.Dataset(X_train, label=y_train)
        dval = lgb.Dataset(X_val, label=y_val, reference=dtrain)

        print("\nTraining LightGBM...")
        callbacks = [
            lgb.early_stopping(50, verbose=False),
            lgb.log_evaluation(100),
        ]
        model = lgb.train(
            LGBM_PARAMS,
            dtrain,
            num_boost_round=1000,
            valid_sets=[dtrain, dval],
            valid_names=["train", "val"],
            callbacks=callbacks,
        )

        # ── Evaluate ───────────────────────────────────────────
        y_pred_val = model.predict(X_val)
        y_pred_test = model.predict(X_test)

        rmse_val = np.sqrt(mean_squared_error(y_val, y_pred_val))
        rmse_test = np.sqrt(mean_squared_error(y_test, y_pred_test))

        # Accuracy within ±10 percentile points
        acc_10 = np.mean(np.abs(y_pred_test - y_test) <= 10) * 100

        print(f"\n{'='*40}")
        print(f"Val  RMSE : {rmse_val:.2f}")
        print(f"Test RMSE : {rmse_test:.2f}  (target: <15)")
        print(f"±10pt acc : {acc_10:.1f}%")
        print(f"Best iter : {model.best_iteration}")
        print(f"{'='*40}")

        # ── Feature importance ─────────────────────────────────
        importance = pd.Series(
            model.feature_importance(importance_type="gain"),
            index=FEATURE_COLS,
        ).sort_values(ascending=False)
        print("\nTop-10 feature importance (gain):")
        print(importance.head(10).round(1).to_string())

        # ── MLflow logging ─────────────────────────────────────
        mlflow.log_params(LGBM_PARAMS)
        mlflow.log_param("num_features", len(FEATURE_COLS))
        mlflow.log_param("train_rows", len(X_train))
        mlflow.log_param("data_source", "RedNote-Vibe exploring_set")
        mlflow.log_metric("rmse_val", rmse_val)
        mlflow.log_metric("rmse_test", rmse_test)
        mlflow.log_metric("acc_within_10pt", acc_10)
        mlflow.log_metric("best_iteration", model.best_iteration)
        mlflow.lightgbm.log_model(model, "model")

        # ── Save model ─────────────────────────────────────────
        model_path = MODEL_DIR / "model_a_v0.1.lgb"
        model.save_model(str(model_path))
        print(f"\nModel saved: {model_path}")

        # ── Quick inference test ───────────────────────────────
        sample = X_test.iloc[:3]
        preds = model.predict(sample)
        actuals = y_test.iloc[:3].values
        print("\nSample predictions (percentile score 0-100):")
        for pred, actual in zip(preds, actuals):
            print(f"  predicted: {pred:.1f}  actual: {actual:.1f}  diff: {abs(pred-actual):.1f}")

        return model, rmse_test


if __name__ == "__main__":
    train()
