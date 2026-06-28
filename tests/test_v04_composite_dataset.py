import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))

from v04_composite_dataset import (  # noqa: E402
    assert_no_forbidden_training_columns,
    build_and_write_composite_dataset,
    build_golden_training_rows,
    build_preference_pair_rows,
)
from v04_composite_features import COMPOSITE_FEATURE_COLS  # noqa: E402


class V04CompositeDatasetTests(unittest.TestCase):
    def test_builds_golden_rows_from_inline_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "golden.json"
            path.write_text(
                json.dumps(
                    {
                        "version": "golden-labels-v0.1",
                        "items": [
                            {
                                "id": "inline_good_food",
                                "content_source": {
                                    "type": "inline",
                                    "domain": "美食",
                                    "title": "万博城小青龙人均98很稳",
                                    "body": "招牌芝士焗小青龙建议必点，地址在万博城A座7层，人均98元，营业时间09:00-21:00，喜欢就点赞收藏。#广州美食 #粤菜",
                                },
                                "labels": {
                                    "human_quality_score": 82,
                                    "delivery_ready": True,
                                    "naturalness_label": 80,
                                    "hook_quality": 4,
                                    "body_value": 4,
                                    "industry_fit": 5,
                                    "fact_status": "verified",
                                    "ai_smell_level": 1,
                                    "failure_tags": ["delivery_ready"],
                                },
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            df = build_golden_training_rows(path)
            self.assertEqual(len(df), 1)
            self.assertEqual(df.iloc[0]["human_quality_score"], 82)
            self.assertEqual(df.iloc[0]["delivery_ready_strict"], 1)
            self.assertEqual(df.iloc[0]["publishable_or_repairable"], 1)
            self.assertEqual(df.iloc[0]["hard_delivery_block"], 0)
            self.assertEqual(df.iloc[0]["needs_revision"], 0)
            self.assertIn("commercial_fact_density", df.columns)
            self.assertEqual(df.iloc[0]["domain_food_must_order"], 1.0)

    def test_delivery_target_splits_light_revision_from_hard_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "golden.json"
            path.write_text(
                json.dumps(
                    {
                        "version": "golden-labels-v0.1",
                        "items": [
                            {
                                "id": "light_revision",
                                "content_source": {
                                    "type": "inline",
                                    "domain": "美食",
                                    "title": "万博粤菜小青龙挺稳",
                                    "body": "芝士焗小青龙和乳鸽都适合聚餐，信息还可以再补，点赞收藏。#广州美食",
                                },
                                "labels": {
                                    "human_quality_score": 76,
                                    "delivery_ready": False,
                                    "naturalness_label": 76,
                                    "fact_status": "safe",
                                    "ai_smell_level": 2,
                                    "failure_tags": ["needs_minor_revision", "missing_cta"],
                                },
                            },
                            {
                                "id": "hard_block",
                                "content_source": {
                                    "type": "inline",
                                    "domain": "美食",
                                    "title": "好吃",
                                    "body": "好吃。",
                                },
                                "labels": {
                                    "human_quality_score": 38,
                                    "delivery_ready": False,
                                    "naturalness_label": 30,
                                    "fact_status": "safe",
                                    "ai_smell_level": 5,
                                    "failure_tags": ["too_short"],
                                },
                            },
                            {
                                "id": "repairable_short",
                                "content_source": {
                                    "type": "inline",
                                    "domain": "美食",
                                    "title": "万博粤菜",
                                    "body": "小青龙和乳鸽可以再补细节。",
                                },
                                "labels": {
                                    "human_quality_score": 68,
                                    "delivery_ready": False,
                                    "naturalness_label": 68,
                                    "fact_status": "safe",
                                    "ai_smell_level": 3,
                                    "failure_tags": ["too_short", "needs_minor_revision"],
                                },
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            df = build_golden_training_rows(path).set_index("content_id")

            self.assertEqual(df.loc["light_revision", "delivery_ready_strict"], 0)
            self.assertEqual(df.loc["light_revision", "publishable_or_repairable"], 1)
            self.assertEqual(df.loc["light_revision", "hard_delivery_block"], 0)
            self.assertEqual(df.loc["light_revision", "needs_revision"], 1)

            self.assertEqual(df.loc["hard_block", "publishable_or_repairable"], 0)
            self.assertEqual(df.loc["hard_block", "hard_delivery_block"], 1)
            self.assertEqual(df.loc["hard_block", "needs_revision"], 0)

            self.assertEqual(df.loc["repairable_short", "publishable_or_repairable"], 1)
            self.assertEqual(df.loc["repairable_short", "hard_delivery_block"], 0)
            self.assertEqual(df.loc["repairable_short", "needs_revision"], 1)

    def test_preference_pairs_exclude_legacy_scores_from_training_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = Path(tmp) / "pref.jsonl"
            row = {
                "pair_id": "p1",
                "task_id": "t1",
                "domain": "美食",
                "winner": "A",
                "preference_margin": 2,
                "delivery_ready_winner": True,
                "reason_tags": "naturalness|body_specificity",
                "variant_a_id": "a",
                "variant_a_title": "万博城小青龙人均98很稳",
                "variant_a_body": "招牌小青龙、人均98元、地址清楚，去之前确认营业时间，点赞收藏。#广州美食 #粤菜",
                "variant_a_score": 55.0,
                "variant_b_id": "b",
                "variant_b_title": "广州番禺万博98元值得点",
                "variant_b_body": "这家真的绝了，闭眼冲，姐妹们都去。#美食",
                "variant_b_score": 82.0,
            }
            queue.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

            df = build_preference_pair_rows(queue)
            self.assertEqual(len(df), 1)
            self.assertEqual(df.iloc[0]["preference_label_a_wins"], 1.0)
            self.assertNotIn("variant_a_score", df.columns)
            self.assertNotIn("variant_b_score", df.columns)
            self.assertIn("delta__commercial_title_unreadable_risk", df.columns)
            assert_no_forbidden_training_columns(COMPOSITE_FEATURE_COLS)
            assert_no_forbidden_training_columns([c for c in df.columns if c.startswith("delta__")])

    def test_write_manifest_records_score_exclusion_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            golden = tmp_path / "golden.json"
            pref = tmp_path / "pref.jsonl"
            out = tmp_path / "out"
            golden.write_text(
                json.dumps(
                    {
                        "version": "golden-labels-v0.1",
                        "items": [
                            {
                                "id": "x",
                                "content_source": {"type": "inline", "domain": "健身", "title": "新手居家减脂动作很稳", "body": "深蹲卷腹平板支撑，每组15次，注意膝盖，点赞收藏。"},
                                "labels": {
                                    "human_quality_score": 70,
                                    "delivery_ready": True,
                                    "naturalness_label": 70,
                                    "fact_status": "safe",
                                    "ai_smell_level": 2,
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
            manifest = build_and_write_composite_dataset(golden_labels=golden, preference_queue=pref, output_dir=out)
            self.assertEqual(manifest["counts"]["golden_rows"], 1)
            self.assertIn("excluded", manifest["feature_contract"]["legacy_score_policy"])
            self.assertTrue((out / "golden_training_rows.parquet").exists())

    def test_training_jsonl_escapes_unicode_line_separators(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            golden = tmp_path / "golden.json"
            pref = tmp_path / "pref.jsonl"
            out = tmp_path / "out"
            golden.write_text(
                json.dumps(
                    {
                        "version": "golden-labels-v0.1",
                        "items": [
                            {
                                "id": "line_separator_case",
                                "content_source": {
                                    "type": "inline",
                                    "domain": "美妆",
                                    "title": "防晒霜真实使用反馈",
                                    "body": "第一段\u2028第二段\u2029第三段",
                                },
                                "labels": {
                                    "human_quality_score": 76,
                                    "delivery_ready": True,
                                    "naturalness_label": 80,
                                    "fact_status": "safe",
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

            build_and_write_composite_dataset(golden_labels=golden, preference_queue=pref, output_dir=out)

            lines = (out / "golden_training_rows.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            parsed = json.loads(lines[0])
            self.assertEqual(parsed["body"], "第一段\u2028第二段\u2029第三段")


if __name__ == "__main__":
    unittest.main()
