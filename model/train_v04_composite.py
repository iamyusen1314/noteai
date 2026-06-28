#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Train/guard v0.4-composite delivery quality models.

This script is intentionally strict. With today's seed labels it can build the
dataset and, if explicitly requested, train a tiny experimental regressor for
pipeline validation. It will not pretend that a production model exists before
golden and preference labels reach the required volume and balance.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, mean_absolute_error, mean_squared_error, roc_auc_score
from sklearn.model_selection import GroupShuffleSplit

from v04_composite_dataset import (
    DEFAULT_GOLDEN_LABELS,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PREFERENCE_QUEUE,
    build_and_write_composite_dataset,
)
from v04_composite_features import COMPOSITE_FEATURE_COLS


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT_DIR = ROOT / "model" / "artifacts"
CORE_DOMAINS = ("美食", "旅行", "穿搭", "美妆", "家居", "健身", "母婴")
PUBLISHABLE_CLASSIFIER_TARGET = "publishable_or_repairable"
DEFAULT_MIN_GOLDEN_PRODUCTION_PER_DOMAIN = 600
DEPLOYMENT_METRIC_GATES = {
    "max_regression_mae": 8.0,
    "min_regression_spearman": 0.70,
    "min_publishable_classifier_auc": 0.80,
    "min_preference_ranker_auc": 0.90,
}


REGRESSOR_PARAMS = {
    "objective": "regression_l2",
    "n_estimators": 300,
    "learning_rate": 0.05,
    "num_leaves": 15,
    "min_child_samples": 2,
    "subsample": 0.9,
    "colsample_bytree": 0.9,
    "reg_lambda": 1.0,
    "random_state": 42,
    "n_jobs": -1,
    "verbose": -1,
}

CLASSIFIER_PARAMS = {
    "objective": "binary",
    "n_estimators": 250,
    "learning_rate": 0.05,
    "num_leaves": 15,
    "min_child_samples": 2,
    "subsample": 0.9,
    "colsample_bytree": 0.9,
    "reg_lambda": 1.0,
    "random_state": 42,
    "n_jobs": -1,
    "verbose": -1,
}


def _count_by_domain(df: pd.DataFrame) -> dict[str, int]:
    if df.empty or "domain" not in df.columns:
        return {}
    return {str(k): int(v) for k, v in df["domain"].value_counts().items()}


def _readiness(golden_df: pd.DataFrame, pref_df: pd.DataFrame, args: argparse.Namespace) -> dict[str, Any]:
    golden_counts = _count_by_domain(golden_df)
    pref_counts = _count_by_domain(pref_df)
    gaps: dict[str, dict[str, int]] = {}
    for domain in CORE_DOMAINS:
        g = int(golden_counts.get(domain, 0))
        p = int(pref_counts.get(domain, 0))
        gaps[domain] = {
            "golden_labeled": g,
            "preference_pairs_labeled": p,
            "golden_needed_for_candidate": max(0, args.min_golden_candidate_per_domain - g),
            "preference_needed_for_candidate": max(0, args.min_preference_candidate_per_domain - p),
            "golden_needed_for_production": max(0, args.min_golden_production_per_domain - g),
            "preference_needed_for_production": max(0, args.min_preference_production_per_domain - p),
        }
    candidate_ready = all(
        gap["golden_needed_for_candidate"] == 0 and gap["preference_needed_for_candidate"] == 0
        for gap in gaps.values()
    )
    production_ready = all(
        gap["golden_needed_for_production"] == 0 and gap["preference_needed_for_production"] == 0
        for gap in gaps.values()
    )
    return {
        "decision": "production_ready" if production_ready else "candidate_ready" if candidate_ready else "blocked_need_labels",
        "candidate_ready": candidate_ready,
        "production_ready": production_ready,
        "gaps_by_domain": gaps,
        "thresholds": {
            "min_golden_candidate_per_domain": args.min_golden_candidate_per_domain,
            "min_preference_candidate_per_domain": args.min_preference_candidate_per_domain,
            "min_golden_production_per_domain": args.min_golden_production_per_domain,
            "min_preference_production_per_domain": args.min_preference_production_per_domain,
        },
    }


def _split(df: pd.DataFrame, group_col: str, args: argparse.Namespace) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    if len(df) < 6 or df[group_col].nunique() < 3:
        idx = np.arange(len(df))
        return idx, idx, {
            "method": "insample_tiny_dataset",
            "warning": "not a validation split; only used for experimental pipeline validation",
            "train_rows": int(len(idx)),
            "val_rows": int(len(idx)),
            "overlap_groups": int(df[group_col].nunique()),
        }
    splitter = GroupShuffleSplit(n_splits=1, test_size=args.val_size, random_state=args.random_state)
    train_idx, val_idx = next(splitter.split(df, groups=df[group_col].astype(str)))
    train_groups = set(df.iloc[train_idx][group_col].astype(str))
    val_groups = set(df.iloc[val_idx][group_col].astype(str))
    return train_idx, val_idx, {
        "method": f"GroupShuffleSplit({group_col})",
        "train_rows": int(len(train_idx)),
        "val_rows": int(len(val_idx)),
        "overlap_groups": int(len(train_groups & val_groups)),
        "passed": len(train_groups & val_groups) == 0,
    }


def _split_preference_by_variant_holdout(
    df: pd.DataFrame,
    args: argparse.Namespace,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Split pairwise rows without letting the same variant leak across sets."""
    required_cols = {"variant_a_id", "variant_b_id", "domain"}
    if not required_cols.issubset(df.columns):
        train_idx, val_idx, split = _split(df, "task_id" if "task_id" in df.columns else "pair_id", args)
        split["warning"] = "variant ids missing; fell back to grouped split"
        return train_idx, val_idx, split

    rng = np.random.default_rng(args.random_state)
    train_variant_ids: set[str] = set()
    val_variant_ids: set[str] = set()
    domain_variant_counts: dict[str, dict[str, int]] = {}

    for domain, domain_df in df.groupby(df["domain"].astype(str), dropna=False):
        variants = sorted(
            {
                str(v)
                for v in pd.concat([domain_df["variant_a_id"], domain_df["variant_b_id"]]).astype(str)
                if str(v).strip()
            }
        )
        if len(variants) < 3:
            train_variant_ids.update(variants)
            domain_variant_counts[str(domain)] = {
                "variants": len(variants),
                "train_variants": len(variants),
                "val_variants": 0,
            }
            continue
        shuffled = variants[:]
        rng.shuffle(shuffled)
        val_count = max(1, min(len(shuffled) - 1, int(round(len(shuffled) * args.val_size))))
        val_set = set(shuffled[:val_count])
        train_set = set(shuffled[val_count:])
        val_variant_ids.update(val_set)
        train_variant_ids.update(train_set)
        domain_variant_counts[str(domain)] = {
            "variants": len(variants),
            "train_variants": len(train_set),
            "val_variants": len(val_set),
        }

    train_idx: list[int] = []
    val_idx: list[int] = []
    dropped_cross_partition = 0
    dropped_missing_variant = 0
    for pos, row in enumerate(df.itertuples(index=False)):
        a = str(getattr(row, "variant_a_id", "") or "").strip()
        b = str(getattr(row, "variant_b_id", "") or "").strip()
        if not a or not b:
            dropped_missing_variant += 1
            continue
        if a in train_variant_ids and b in train_variant_ids:
            train_idx.append(pos)
        elif a in val_variant_ids and b in val_variant_ids:
            val_idx.append(pos)
        else:
            dropped_cross_partition += 1

    if len(train_idx) == 0 or len(val_idx) == 0:
        fallback_group = "task_id" if "task_id" in df.columns else "pair_id"
        fallback_train_idx, fallback_val_idx, split = _split(df, fallback_group, args)
        split["warning"] = "variant holdout produced empty train/val; fell back to grouped split"
        return fallback_train_idx, fallback_val_idx, split

    train_variants_used = set(df.iloc[train_idx]["variant_a_id"].astype(str)) | set(
        df.iloc[train_idx]["variant_b_id"].astype(str)
    )
    val_variants_used = set(df.iloc[val_idx]["variant_a_id"].astype(str)) | set(
        df.iloc[val_idx]["variant_b_id"].astype(str)
    )
    overlap = train_variants_used & val_variants_used
    return np.array(train_idx), np.array(val_idx), {
        "method": "VariantHoldoutSplit(domain, variant_a_id, variant_b_id)",
        "train_rows": int(len(train_idx)),
        "val_rows": int(len(val_idx)),
        "dropped_cross_partition_rows": int(dropped_cross_partition),
        "dropped_missing_variant_rows": int(dropped_missing_variant),
        "train_variant_count": int(len(train_variants_used)),
        "val_variant_count": int(len(val_variants_used)),
        "overlap_variants": int(len(overlap)),
        "passed": len(overlap) == 0,
        "domain_variant_counts": domain_variant_counts,
    }


def _regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float | None]:
    if len(y_true) == 0:
        return {}
    pred = np.clip(y_pred.astype(float), 0, 100)
    return {
        "rmse": float(np.sqrt(mean_squared_error(y_true, pred))),
        "mae": float(mean_absolute_error(y_true, pred)),
        "bias": float(np.mean(pred - y_true)),
        "spearman": float(pd.Series(pred).corr(pd.Series(y_true), method="spearman")) if len(y_true) > 1 else None,
    }


def _classification_metrics(y_true: np.ndarray, y_prob: np.ndarray) -> dict[str, float | None]:
    if len(y_true) == 0:
        return {}
    pred = (y_prob >= 0.5).astype(int)
    out: dict[str, float | None] = {"accuracy": float(accuracy_score(y_true, pred))}
    out["auc"] = float(roc_auc_score(y_true, y_prob)) if len(set(y_true.tolist())) > 1 else None
    return out


def _can_train_binary(y: pd.Series) -> bool:
    return len(y) >= 8 and len(set(y.astype(float).tolist())) >= 2


def _train_golden_models(
    golden_df: pd.DataFrame,
    artifact_dir: Path,
    run_id: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    if len(golden_df) < args.min_golden_total_to_train:
        return {
            "trained": False,
            "reason": f"not enough golden rows: {len(golden_df)} < {args.min_golden_total_to_train}",
        }
    for col in COMPOSITE_FEATURE_COLS:
        if col not in golden_df.columns:
            golden_df[col] = 0.0
    X = golden_df[COMPOSITE_FEATURE_COLS].astype(float)
    train_idx, val_idx, split = _split(golden_df, "content_id", args)

    reg = lgb.LGBMRegressor(**{**REGRESSOR_PARAMS, "random_state": args.random_state})
    reg.fit(
        X.iloc[train_idx],
        golden_df.iloc[train_idx]["human_quality_score"].astype(float).to_numpy(),
        eval_set=[(X.iloc[val_idx], golden_df.iloc[val_idx]["human_quality_score"].astype(float).to_numpy())],
        callbacks=[lgb.log_evaluation(0)],
    )
    reg_path = artifact_dir / f"model_v04_composite_regressor_experimental_{run_id}.lgb"
    reg.booster_.save_model(str(reg_path))
    reg_pred = reg.predict(X.iloc[val_idx])

    result: dict[str, Any] = {
        "trained": True,
        "regressor_path": str(reg_path),
        "split": split,
        "regression_metrics": _regression_metrics(
            golden_df.iloc[val_idx]["human_quality_score"].astype(float).to_numpy(),
            reg_pred,
        ),
        "classifier": {"trained": False},
    }

    classifier_target = PUBLISHABLE_CLASSIFIER_TARGET if PUBLISHABLE_CLASSIFIER_TARGET in golden_df.columns else "delivery_ready"
    y_ready = golden_df[classifier_target].astype(int)
    if _can_train_binary(y_ready):
        clf = lgb.LGBMClassifier(**{**CLASSIFIER_PARAMS, "random_state": args.random_state})
        clf.fit(
            X.iloc[train_idx],
            y_ready.iloc[train_idx].to_numpy(),
            eval_set=[(X.iloc[val_idx], y_ready.iloc[val_idx].to_numpy())],
            callbacks=[lgb.log_evaluation(0)],
        )
        clf_path = artifact_dir / f"model_v04_composite_ready_classifier_experimental_{run_id}.lgb"
        clf.booster_.save_model(str(clf_path))
        prob = clf.predict_proba(X.iloc[val_idx])[:, 1]
        result["classifier"] = {
            "trained": True,
            "target_column": classifier_target,
            "target_policy": "1 means publishable now or repairable without hard blocking; 0 means hard delivery block",
            "target_positive_rate": float(y_ready.mean()),
            "path": str(clf_path),
            "metrics": _classification_metrics(y_ready.iloc[val_idx].to_numpy(), prob),
        }
    else:
        result["classifier"] = {
            "trained": False,
            "target_column": classifier_target,
            "reason": f"{classifier_target} label needs at least 8 rows and both classes",
        }
    return result


def _train_preference_ranker(
    pref_df: pd.DataFrame,
    artifact_dir: Path,
    run_id: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    if len(pref_df) < args.min_preference_total_to_train:
        return {
            "trained": False,
            "reason": f"not enough preference rows: {len(pref_df)} < {args.min_preference_total_to_train}",
        }
    train_cols = [f"delta__{col}" for col in COMPOSITE_FEATURE_COLS]
    y = pref_df["preference_label_a_wins"].astype(float)
    binary_df = pref_df[y.isin([0.0, 1.0])].copy()
    if not _can_train_binary(binary_df["preference_label_a_wins"] if not binary_df.empty else pd.Series(dtype=float)):
        return {
            "trained": False,
            "reason": "preference ranker needs at least 8 non-tie rows and both A/B winner classes",
            "winner_distribution": pref_df["winner"].value_counts().to_dict() if not pref_df.empty else {},
        }
    for col in train_cols:
        if col not in binary_df.columns:
            binary_df[col] = 0.0
    X = binary_df[train_cols].astype(float)
    train_idx, val_idx, split = _split_preference_by_variant_holdout(binary_df, args)
    ranker = lgb.LGBMClassifier(**{**CLASSIFIER_PARAMS, "random_state": args.random_state})
    ranker.fit(
        X.iloc[train_idx],
        binary_df.iloc[train_idx]["preference_label_a_wins"].astype(int).to_numpy(),
        eval_set=[(X.iloc[val_idx], binary_df.iloc[val_idx]["preference_label_a_wins"].astype(int).to_numpy())],
        callbacks=[lgb.log_evaluation(0)],
    )
    path = artifact_dir / f"model_v04_composite_ranker_experimental_{run_id}.lgb"
    ranker.booster_.save_model(str(path))
    prob = ranker.predict_proba(X.iloc[val_idx])[:, 1]
    return {
        "trained": True,
        "path": str(path),
        "split": split,
        "metrics": _classification_metrics(binary_df.iloc[val_idx]["preference_label_a_wins"].astype(int).to_numpy(), prob),
    }


def _deployment_gate(readiness: dict[str, Any], models: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []

    if not readiness.get("production_ready"):
        blockers.append("readiness_not_production_ready")

    golden = models.get("golden") or {}
    if not golden.get("trained"):
        blockers.append("golden_model_not_trained")
    else:
        split = golden.get("split") or {}
        if split.get("passed") is False:
            blockers.append("golden_split_leakage_detected")
        reg = golden.get("regression_metrics") or {}
        mae = reg.get("mae")
        spearman = reg.get("spearman")
        if mae is None or float(mae) > DEPLOYMENT_METRIC_GATES["max_regression_mae"]:
            blockers.append("regression_mae_above_gate")
        if spearman is None or float(spearman) < DEPLOYMENT_METRIC_GATES["min_regression_spearman"]:
            blockers.append("regression_spearman_below_gate")
        clf = golden.get("classifier") or {}
        if not clf.get("trained"):
            blockers.append("publishable_classifier_not_trained")
        else:
            auc = (clf.get("metrics") or {}).get("auc")
            if auc is None or float(auc) < DEPLOYMENT_METRIC_GATES["min_publishable_classifier_auc"]:
                blockers.append("publishable_classifier_auc_below_gate")

    ranker = models.get("preference_ranker") or {}
    if not ranker.get("trained"):
        blockers.append("preference_ranker_not_trained")
    else:
        split = ranker.get("split") or {}
        if split.get("passed") is False or int(split.get("overlap_variants") or 0) != 0:
            blockers.append("preference_ranker_variant_leakage_detected")
        auc = (ranker.get("metrics") or {}).get("auc")
        if auc is None or float(auc) < DEPLOYMENT_METRIC_GATES["min_preference_ranker_auc"]:
            blockers.append("preference_ranker_auc_below_gate")
        drop_rate = float(split.get("dropped_cross_partition_rows") or 0) / max(
            int(split.get("train_rows") or 0) + int(split.get("val_rows") or 0) + int(split.get("dropped_cross_partition_rows") or 0),
            1,
        )
        if drop_rate > 0.30:
            warnings.append("preference_ranker_variant_holdout_dropped_many_cross_partition_pairs")

    return {
        "passed": not blockers,
        "decision": "deployable_model_artifacts" if not blockers else "blocked_not_deployable",
        "blockers": blockers,
        "warnings": warnings,
        "metric_gates": DEPLOYMENT_METRIC_GATES,
    }


def train_composite(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    artifact_dir = Path(args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    dataset_manifest = build_and_write_composite_dataset(
        golden_labels=Path(args.golden_labels),
        preference_queue=Path(args.preference_queue),
        output_dir=output_dir,
    )
    golden_df = pd.read_parquet(output_dir / "golden_training_rows.parquet")
    pref_df = pd.read_parquet(output_dir / "preference_pair_rows.parquet")
    readiness = _readiness(golden_df, pref_df, args)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report: dict[str, Any] = {
        "version": "v04-composite-train-v0.1",
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": dataset_manifest,
        "readiness": readiness,
        "training_policy": {
            "primary_targets": [
                "human_quality_score",
                PUBLISHABLE_CLASSIFIER_TARGET,
                "hard_delivery_block",
                "preference_label_a_wins",
            ],
            "strict_review_label": "delivery_ready",
            "delivery_gate_policy": "score<60 or fatal fact/safety/industry issues are hard-blocked; 60+ light-revision notes stay eligible for revision.",
            "v03_usage": "telemetry_only_excluded_from_features_and_targets",
            "production_ready": False,
            "do_not_deploy": True,
        },
        "models": {},
    }

    if not args.allow_experimental_small_data and not readiness["candidate_ready"]:
        report["decision"] = "blocked_need_labels"
        report["models"] = {
            "golden": {"trained": False, "reason": "candidate label thresholds not met"},
            "preference_ranker": {"trained": False, "reason": "candidate label thresholds not met"},
        }
    else:
        report["decision"] = "experimental_not_production" if args.allow_experimental_small_data else "candidate_training"
        if args.allow_experimental_small_data:
            report["training_policy"]["experimental_small_data"] = True
            report["training_policy"]["warning"] = "Models trained in this mode validate the pipeline only; they are not product quality."
        report["models"] = {
            "golden": _train_golden_models(golden_df, artifact_dir, run_id, args),
            "preference_ranker": _train_preference_ranker(pref_df, artifact_dir, run_id, args),
        }

    deployment_gate = _deployment_gate(readiness, report["models"])
    report["deployment_gate"] = deployment_gate
    if deployment_gate["passed"]:
        report["decision"] = "production_training"
        report["training_policy"]["production_ready"] = True
        report["training_policy"]["do_not_deploy"] = False
    else:
        report["training_policy"]["production_ready"] = False
        report["training_policy"]["do_not_deploy"] = True

    latest_path = artifact_dir / "model_v04_composite_train_report.json"
    run_path = artifact_dir / f"model_v04_composite_train_report_{run_id}.json"
    latest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    run_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(latest_path)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train or guard v0.4-composite models")
    parser.add_argument("--golden-labels", default=str(DEFAULT_GOLDEN_LABELS))
    parser.add_argument("--preference-queue", default=str(DEFAULT_PREFERENCE_QUEUE))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--artifact-dir", default=str(DEFAULT_ARTIFACT_DIR))
    parser.add_argument("--val-size", type=float, default=0.30)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--min-golden-candidate-per-domain", type=int, default=300)
    parser.add_argument("--min-preference-candidate-per-domain", type=int, default=1000)
    parser.add_argument("--min-golden-production-per-domain", type=int, default=DEFAULT_MIN_GOLDEN_PRODUCTION_PER_DOMAIN)
    parser.add_argument("--min-preference-production-per-domain", type=int, default=3000)
    parser.add_argument("--min-golden-total-to-train", type=int, default=300)
    parser.add_argument("--min-preference-total-to-train", type=int, default=1000)
    parser.add_argument("--allow-experimental-small-data", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.allow_experimental_small_data:
        args.min_golden_total_to_train = min(args.min_golden_total_to_train, 8)
        args.min_preference_total_to_train = min(args.min_preference_total_to_train, 3)
    report = train_composite(args)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"decision={report['decision']}")
        print(f"report={report['report_path']}")
        print(f"golden_rows={report['dataset']['counts']['golden_rows']}")
        print(f"preference_pairs={report['dataset']['counts']['preference_pair_rows']}")
        print(f"do_not_deploy={report['training_policy']['do_not_deploy']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
