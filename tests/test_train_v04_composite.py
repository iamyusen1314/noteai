import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))

from train_v04_composite import _deployment_gate, train_composite  # noqa: E402


def _args(tmp: Path, golden: Path, pref: Path) -> argparse.Namespace:
    return argparse.Namespace(
        golden_labels=str(golden),
        preference_queue=str(pref),
        output_dir=str(tmp / "data"),
        artifact_dir=str(tmp / "artifacts"),
        val_size=0.3,
        random_state=42,
        min_golden_candidate_per_domain=300,
        min_preference_candidate_per_domain=1000,
        min_golden_production_per_domain=1000,
        min_preference_production_per_domain=3000,
        min_golden_total_to_train=300,
        min_preference_total_to_train=1000,
        allow_experimental_small_data=False,
    )


class TrainV04CompositeTests(unittest.TestCase):
    def test_training_guard_blocks_under_labeled_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            golden = tmp_path / "golden.json"
            pref = tmp_path / "pref.jsonl"
            golden.write_text(
                json.dumps(
                    {
                        "version": "golden-labels-v0.1",
                        "items": [
                            {
                                "id": "tiny",
                                "content_source": {"type": "inline", "domain": "美食", "title": "小青龙人均98很稳", "body": "招牌小青龙，人均98元，地址营业时间清楚，点赞收藏。"},
                                "labels": {
                                    "human_quality_score": 80,
                                    "delivery_ready": True,
                                    "naturalness_label": 80,
                                    "fact_status": "verified",
                                    "ai_smell_level": 1,
                                    "failure_tags": [],
                                },
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            pref.write_text("", encoding="utf-8")
            report = train_composite(_args(tmp_path, golden, pref))
            self.assertEqual(report["decision"], "blocked_need_labels")
            self.assertTrue(report["training_policy"]["do_not_deploy"])
            self.assertFalse(report["deployment_gate"]["passed"])
            self.assertIn("readiness_not_production_ready", report["deployment_gate"]["blockers"])
            self.assertFalse(report["models"]["golden"]["trained"])
            self.assertTrue((tmp_path / "artifacts" / "model_v04_composite_train_report.json").exists())

    def test_deployment_gate_allows_only_ready_metrics(self):
        readiness = {"production_ready": True}
        models = {
            "golden": {
                "trained": True,
                "split": {"passed": True},
                "regression_metrics": {"mae": 5.5, "spearman": 0.78},
                "classifier": {"trained": True, "metrics": {"auc": 0.88}},
            },
            "preference_ranker": {
                "trained": True,
                "split": {
                    "passed": True,
                    "overlap_variants": 0,
                    "train_rows": 100,
                    "val_rows": 30,
                    "dropped_cross_partition_rows": 10,
                },
                "metrics": {"auc": 0.95},
            },
        }

        gate = _deployment_gate(readiness, models)

        self.assertTrue(gate["passed"])
        self.assertEqual(gate["decision"], "deployable_model_artifacts")


if __name__ == "__main__":
    unittest.main()
