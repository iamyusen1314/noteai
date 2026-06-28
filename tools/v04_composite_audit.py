#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit the latest v0.4 composite training artifacts before deployment.

This report intentionally sits outside the trainer. The trainer proves a model
can be built; this script asks whether the held-out behavior is trustworthy
enough to even consider a shadow rollout.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, mean_absolute_error, mean_squared_error, roc_auc_score


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

from train_v04_composite import _split, _split_preference_by_variant_holdout  # noqa: E402
from v04_composite_features import COMPOSITE_FEATURE_COLS  # noqa: E402


DEFAULT_REPORT = ROOT / "model" / "artifacts" / "model_v04_composite_train_report.json"
DEFAULT_OUTPUT = ROOT / "model" / "artifacts" / "v04_composite_audit.json"
EXCELLENT_SCORE = 72.0
LOW_SCORE = 60.0


def _resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _as_float_array(values: Any) -> np.ndarray:
    return np.asarray(values, dtype=float)


def _round(value: Any, digits: int = 4) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    return round(float(value), digits)


def _regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float | None]:
    if len(y_true) == 0:
        return {"rows": 0, "rmse": None, "mae": None, "bias": None, "spearman": None}
    pred = np.clip(_as_float_array(y_pred), 0, 100)
    return {
        "rows": int(len(y_true)),
        "rmse": _round(np.sqrt(mean_squared_error(y_true, pred))),
        "mae": _round(mean_absolute_error(y_true, pred)),
        "bias": _round(np.mean(pred - y_true)),
        "spearman": _round(pd.Series(pred).corr(pd.Series(y_true), method="spearman")) if len(y_true) > 1 else None,
    }


def _binary_metrics(y_true: np.ndarray, y_prob: np.ndarray) -> dict[str, float | int | None]:
    if len(y_true) == 0:
        return {"rows": 0, "accuracy": None, "auc": None, "positive_rate": None}
    pred = (_as_float_array(y_prob) >= 0.5).astype(int)
    true = np.asarray(y_true, dtype=int)
    out: dict[str, float | int | None] = {
        "rows": int(len(true)),
        "accuracy": _round(accuracy_score(true, pred)),
        "auc": _round(roc_auc_score(true, y_prob)) if len(set(true.tolist())) > 1 else None,
        "positive_rate": _round(float(np.mean(true))),
        "predicted_positive_rate": _round(float(np.mean(pred))),
        "false_positive": int(((pred == 1) & (true == 0)).sum()),
        "false_negative": int(((pred == 0) & (true == 1)).sum()),
        "true_positive": int(((pred == 1) & (true == 1)).sum()),
        "true_negative": int(((pred == 0) & (true == 0)).sum()),
    }
    return out


def _sample_columns(df: pd.DataFrame, extra_cols: list[str]) -> list[dict[str, Any]]:
    cols = [
        col
        for col in [
            "content_id",
            "pair_id",
            "task_id",
            "domain",
            "title",
            "variant_a_title",
            "variant_b_title",
            "human_quality_score",
            "predicted_score",
            "score_error",
            "delivery_ready",
            "predicted_ready_prob",
            "predicted_a_win_prob",
            "preference_label_a_wins",
            "winner",
            "preference_margin",
        ]
        + extra_cols
        if col in df.columns
    ]
    rows: list[dict[str, Any]] = []
    for raw in df[cols].head(20).to_dict(orient="records"):
        row: dict[str, Any] = {}
        for key, value in raw.items():
            if isinstance(value, float):
                row[key] = _round(value)
            elif pd.isna(value):
                row[key] = None
            else:
                text = str(value)
                row[key] = text[:180] if key in {"title", "variant_a_title", "variant_b_title"} else value
        rows.append(row)
    return rows


def _domain_regression_report(df: pd.DataFrame, classifier_target_col: str = "delivery_ready") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for domain, part in df.groupby(df["domain"].astype(str), dropna=False):
        strict_ready = part["delivery_ready"].astype(bool)
        target_ready = part[classifier_target_col].astype(bool)
        hard_block = (
            part["hard_delivery_block"].astype(bool)
            if "hard_delivery_block" in part.columns
            else ~target_ready
        )
        metrics = _regression_metrics(
            part["human_quality_score"].astype(float).to_numpy(),
            part["predicted_score"].astype(float).to_numpy(),
        )
        metrics.update(
            {
                "ready_rate": _round(part["delivery_ready"].astype(int).mean()),
                "strict_delivery_ready_rate": _round(strict_ready.astype(int).mean()),
                "classifier_target_positive_rate": _round(target_ready.astype(int).mean()),
                "hard_block_rate": _round(hard_block.astype(int).mean()),
                "avg_true_score": _round(part["human_quality_score"].astype(float).mean()),
                "avg_predicted_score": _round(part["predicted_score"].astype(float).mean()),
                "score_false_positive_72_not_ready": int(
                    ((part["predicted_score"] >= EXCELLENT_SCORE) & (~strict_ready)).sum()
                ),
                "score_false_positive_72_hard_blocked": int(
                    ((part["predicted_score"] >= EXCELLENT_SCORE) & hard_block).sum()
                ),
                "score_false_negative_below_60_ready": int(
                    ((part["predicted_score"] < LOW_SCORE) & strict_ready).sum()
                ),
                "score_false_negative_below_60_publishable": int(
                    ((part["predicted_score"] < LOW_SCORE) & target_ready).sum()
                ),
                "ready_classifier": _binary_metrics(
                    part[classifier_target_col].astype(int).to_numpy(),
                    part["predicted_ready_prob"].astype(float).to_numpy(),
                )
                if "predicted_ready_prob" in part.columns
                else None,
            }
        )
        out[str(domain)] = metrics
    return dict(sorted(out.items()))


def audit_golden(report: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    golden_model = report.get("models", {}).get("golden", {})
    if not golden_model.get("trained"):
        return {"trained": False, "reason": golden_model.get("reason") or "golden model was not trained"}

    dataset_outputs = report.get("dataset", {}).get("outputs", {})
    golden_path = _resolve(dataset_outputs.get("golden_parquet") or args.golden_parquet)
    golden_df = pd.read_parquet(golden_path)
    for col in COMPOSITE_FEATURE_COLS:
        if col not in golden_df.columns:
            golden_df[col] = 0.0
    X = golden_df[COMPOSITE_FEATURE_COLS].astype(float)
    train_idx, val_idx, split = _split(golden_df, "content_id", args)
    val = golden_df.iloc[val_idx].copy()

    regressor_path = _resolve(golden_model["regressor_path"])
    regressor = lgb.Booster(model_file=str(regressor_path))
    val["predicted_score"] = np.clip(regressor.predict(X.iloc[val_idx]), 0, 100)
    val["score_error"] = val["predicted_score"].astype(float) - val["human_quality_score"].astype(float)

    classifier_info = golden_model.get("classifier") or {}
    classifier_report: dict[str, Any] = {"trained": False}
    classifier_target_col = classifier_info.get("target_column") or "delivery_ready"
    if classifier_target_col not in val.columns:
        classifier_target_col = "delivery_ready"
    if classifier_info.get("trained") and classifier_info.get("path"):
        classifier = lgb.Booster(model_file=str(_resolve(classifier_info["path"])))
        val["predicted_ready_prob"] = classifier.predict(X.iloc[val_idx])
        classifier_report = {
            "trained": True,
            "target_column": classifier_target_col,
            "overall": _binary_metrics(
                val[classifier_target_col].astype(int).to_numpy(),
                val["predicted_ready_prob"].astype(float).to_numpy(),
            ),
            "by_domain": {
                str(domain): _binary_metrics(
                    part[classifier_target_col].astype(int).to_numpy(),
                    part["predicted_ready_prob"].astype(float).to_numpy(),
                )
                for domain, part in val.groupby(val["domain"].astype(str), dropna=False)
            },
        }

    classifier_target_ready = val[classifier_target_col].astype(bool)
    hard_block = (
        val["hard_delivery_block"].astype(bool)
        if "hard_delivery_block" in val.columns
        else ~classifier_target_ready
    )
    false_positive = val[(val["predicted_score"] >= EXCELLENT_SCORE) & (~val["delivery_ready"].astype(bool))]
    hard_false_positive = val[(val["predicted_score"] >= EXCELLENT_SCORE) & hard_block]
    false_negative = val[(val["predicted_score"] < LOW_SCORE) & (val["delivery_ready"].astype(bool))]
    low_score_publishable = val[(val["predicted_score"] < LOW_SCORE) & classifier_target_ready]
    ready_fp = (
        val[(val["predicted_ready_prob"] >= 0.5) & (~val[classifier_target_col].astype(bool))]
        if "predicted_ready_prob" in val.columns
        else val.iloc[0:0]
    )
    high_error = val.assign(abs_error=val["score_error"].abs()).sort_values("abs_error", ascending=False)

    return {
        "trained": True,
        "dataset": str(golden_path),
        "regressor_path": str(regressor_path),
        "split": split,
        "overall": _regression_metrics(
            val["human_quality_score"].astype(float).to_numpy(),
            val["predicted_score"].astype(float).to_numpy(),
        ),
        "by_domain": _domain_regression_report(val, classifier_target_col),
        "ready_classifier": classifier_report,
        "error_counts": {
            "score_false_positive_72_not_ready": int(len(false_positive)),
            "score_false_positive_72_hard_blocked": int(len(hard_false_positive)),
            "score_false_negative_below_60_ready": int(len(false_negative)),
            "score_false_negative_below_60_publishable": int(len(low_score_publishable)),
            "ready_classifier_false_positive": int(len(ready_fp)),
        },
        "samples": {
            "largest_score_errors": _sample_columns(high_error, ["abs_error", "failure_tags", "label_rationale"]),
            "score_false_positive_72_not_ready": _sample_columns(
                false_positive.sort_values("predicted_score", ascending=False),
                ["failure_tags", "label_rationale"],
            ),
            "score_false_positive_72_hard_blocked": _sample_columns(
                hard_false_positive.sort_values("predicted_score", ascending=False),
                ["failure_tags", "label_rationale"],
            ),
            "score_false_negative_below_60_ready": _sample_columns(
                false_negative.sort_values("predicted_score", ascending=True),
                ["failure_tags", "label_rationale"],
            ),
            "score_false_negative_below_60_publishable": _sample_columns(
                low_score_publishable.sort_values("predicted_score", ascending=True),
                ["failure_tags", "label_rationale"],
            ),
            "ready_classifier_false_positive": _sample_columns(
                ready_fp.sort_values("predicted_ready_prob", ascending=False),
                ["failure_tags", "label_rationale"],
            ),
        },
    }


def _margin_bucket(value: Any) -> str:
    try:
        margin = abs(float(value))
    except (TypeError, ValueError):
        return "unknown"
    if margin < 10:
        return "lt10"
    if margin < 20:
        return "10_19"
    if margin < 30:
        return "20_29"
    return "gte30"


def audit_ranker(report: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    ranker_info = report.get("models", {}).get("preference_ranker", {})
    if not ranker_info.get("trained"):
        return {"trained": False, "reason": ranker_info.get("reason") or "ranker was not trained"}

    dataset_outputs = report.get("dataset", {}).get("outputs", {})
    pref_path = _resolve(dataset_outputs.get("preference_parquet") or args.preference_parquet)
    pref_df = pd.read_parquet(pref_path)
    binary_df = pref_df[pref_df["preference_label_a_wins"].astype(float).isin([0.0, 1.0])].copy()
    train_cols = [f"delta__{col}" for col in COMPOSITE_FEATURE_COLS]
    for col in train_cols:
        if col not in binary_df.columns:
            binary_df[col] = 0.0

    X = binary_df[train_cols].astype(float)
    train_idx, val_idx, split = _split_preference_by_variant_holdout(binary_df, args)
    val = binary_df.iloc[val_idx].copy()
    ranker_path = _resolve(ranker_info["path"])
    ranker = lgb.Booster(model_file=str(ranker_path))
    val["predicted_a_win_prob"] = ranker.predict(X.iloc[val_idx])
    val["predicted_label_a_wins"] = (val["predicted_a_win_prob"] >= 0.5).astype(int)
    val["correct"] = val["predicted_label_a_wins"].astype(int) == val["preference_label_a_wins"].astype(int)
    val["margin_bucket"] = val["preference_margin"].map(_margin_bucket) if "preference_margin" in val.columns else "unknown"

    by_domain: dict[str, Any] = {}
    for domain, part in val.groupby(val["domain"].astype(str), dropna=False):
        by_domain[str(domain)] = _binary_metrics(
            part["preference_label_a_wins"].astype(int).to_numpy(),
            part["predicted_a_win_prob"].astype(float).to_numpy(),
        )
    by_margin: dict[str, Any] = {}
    for bucket, part in val.groupby(val["margin_bucket"].astype(str), dropna=False):
        by_margin[str(bucket)] = _binary_metrics(
            part["preference_label_a_wins"].astype(int).to_numpy(),
            part["predicted_a_win_prob"].astype(float).to_numpy(),
        )

    wrong = val[~val["correct"]].copy()
    return {
        "trained": True,
        "dataset": str(pref_path),
        "ranker_path": str(ranker_path),
        "binary_rows": int(len(binary_df)),
        "winner_distribution_all_binary": {
            str(k): int(v) for k, v in binary_df["winner"].astype(str).value_counts().items()
        },
        "split": split,
        "overall": _binary_metrics(
            val["preference_label_a_wins"].astype(int).to_numpy(),
            val["predicted_a_win_prob"].astype(float).to_numpy(),
        ),
        "by_domain": dict(sorted(by_domain.items())),
        "by_margin_bucket": dict(sorted(by_margin.items())),
        "validation_winner_distribution": {str(k): int(v) for k, v in val["winner"].astype(str).value_counts().items()},
        "error_counts": {
            "wrong_predictions": int(len(wrong)),
            "cross_partition_rows_dropped": int(split.get("dropped_cross_partition_rows") or 0),
            "cross_partition_drop_rate_over_binary": _round(
                float(split.get("dropped_cross_partition_rows") or 0) / max(len(binary_df), 1)
            ),
        },
        "samples": {
            "wrong_predictions": _sample_columns(
                wrong.sort_values("predicted_a_win_prob", ascending=False),
                ["reason_tags", "rationale"],
            ),
            "highest_confidence_predictions": _sample_columns(
                val.assign(confidence=(val["predicted_a_win_prob"] - 0.5).abs()).sort_values(
                    "confidence", ascending=False
                ),
                ["confidence", "reason_tags", "rationale"],
            ),
        },
    }


def build_deployment_gate(report: dict[str, Any], golden: dict[str, Any], ranker: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []

    training_policy = report.get("training_policy", {})
    readiness = report.get("readiness", {})
    if training_policy.get("do_not_deploy"):
        blockers.append("trainer_report_do_not_deploy_true")
    if not readiness.get("production_ready"):
        blockers.append("readiness_not_production_ready")

    if golden.get("trained"):
        for domain, metrics in golden.get("by_domain", {}).items():
            mae = metrics.get("mae")
            if mae is not None and float(mae) > 8.0:
                warnings.append(f"golden_domain_mae_gt_8:{domain}")
            classifier = (metrics.get("ready_classifier") or {}) if isinstance(metrics, dict) else {}
            auc = classifier.get("auc") if isinstance(classifier, dict) else None
            if auc is not None and float(auc) < 0.70:
                warnings.append(f"ready_classifier_domain_auc_lt_0.70:{domain}")

    if ranker.get("trained"):
        split = ranker.get("split") or {}
        drop_rate = (ranker.get("error_counts") or {}).get("cross_partition_drop_rate_over_binary")
        if drop_rate is not None and float(drop_rate) > 0.30:
            warnings.append("ranker_variant_holdout_drops_many_cross_partition_pairs")
        if (ranker.get("overall") or {}).get("auc") is not None and float((ranker.get("overall") or {})["auc"]) > 0.995:
            warnings.append("ranker_auc_extremely_high_audit_for_easy_distilled_pairs")
        if split.get("overlap_variants") != 0:
            blockers.append("ranker_variant_leakage_detected")

    return {
        "decision": "blocked_not_deployable" if blockers else "audit_pass_shadow_only",
        "blockers": blockers,
        "warnings": warnings,
        "notes": [
            "A pass here only allows shadow evaluation; production deployment still needs generation-chain QA.",
            "Score thresholds are audit heuristics, not user-facing scoring rules.",
        ],
    }


def build_audit(args: argparse.Namespace) -> dict[str, Any]:
    report_path = _resolve(args.train_report)
    report = _load_json(report_path)
    golden = audit_golden(report, args)
    ranker = audit_ranker(report, args)
    return {
        "version": "v04-composite-audit-v0.1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "train_report": str(report_path),
        "run_id": report.get("run_id"),
        "training_decision": report.get("decision"),
        "readiness": report.get("readiness"),
        "dataset_counts": (report.get("dataset") or {}).get("counts"),
        "golden": golden,
        "preference_ranker": ranker,
        "deployment_gate": build_deployment_gate(report, golden, ranker),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit v0.4 composite model artifacts")
    parser.add_argument("--train-report", default=str(DEFAULT_REPORT))
    parser.add_argument("--golden-parquet", default=str(ROOT / "model" / "data" / "v04_composite" / "golden_training_rows.parquet"))
    parser.add_argument(
        "--preference-parquet",
        default=str(ROOT / "model" / "data" / "v04_composite" / "preference_pair_rows.parquet"),
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--val-size", type=float, default=0.30)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    audit = build_audit(args)
    output = _resolve(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(audit, ensure_ascii=False, indent=2))
    else:
        gate = audit["deployment_gate"]
        print(f"decision={gate['decision']}")
        print(f"output={output}")
        print(f"blockers={','.join(gate['blockers']) if gate['blockers'] else 'none'}")
        print(f"warnings={','.join(gate['warnings']) if gate['warnings'] else 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
