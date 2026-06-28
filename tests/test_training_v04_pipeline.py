import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))

from rednote_vibe_v04 import (  # noqa: E402
    MODEL_FEATURE_COLS_V04,
    build_v04_dataset,
    normalize_row,
)
from train_v04 import _assert_no_leakage  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


class TrainingV04PipelineTests(unittest.TestCase):
    def test_normalize_row_accepts_rednote_vibe_current_schema(self):
        row = {
            "note_id": "n1",
            "note_title": "标题",
            "note_content": "正文",
            "likes": 10,
            "collections": 3,
            "comments": 2,
            "domain": "Food",
            "local_time": "2025060108",
        }
        out = normalize_row(row, filename="exploring_set.jsonl", row_idx=1)
        self.assertEqual(out["desc"], "正文")
        self.assertEqual(out["liked_count"], 10)
        self.assertEqual(out["collected_count"], 3)
        self.assertEqual(out["comments_count"], 2)
        self.assertEqual(out["domain"], "美食")
        self.assertEqual(out["ces_raw"], 21.0)

    def test_build_dataset_excludes_aigc_and_dedupes_score_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "raw"
            out = Path(tmp) / "out"
            raw.mkdir()
            _write_jsonl(
                raw / "exploring_set.jsonl",
                [
                    {
                        "note_id": "same",
                        "note_title": "低互动标题",
                        "note_content": "这是一条足够长的低互动正文，用于测试重复样本处理。",
                        "likes": 1,
                        "collections": 1,
                        "comments": 0,
                        "domain": "美食",
                        "local_time": "2025010108",
                    },
                    {
                        "note_id": "same",
                        "note_title": "高互动标题",
                        "note_content": "这是一条足够长的高互动正文，用于测试重复样本处理。",
                        "likes": 100,
                        "collections": 20,
                        "comments": 5,
                        "domain": "美食",
                        "local_time": "2025010109",
                    },
                    {
                        "note_id": "other",
                        "note_title": "另一条标题",
                        "note_content": "这是另一条足够长的真实帖子正文，用于提供标签分布。",
                        "likes": 10,
                        "collections": 2,
                        "comments": 1,
                        "domain": "美食",
                        "local_time": "2025010110",
                    },
                ],
            )
            _write_jsonl(
                raw / "training_set_human.jsonl",
                [
                    {
                        "note_id": "human1",
                        "note_title": "人工标题",
                        "desc": "这是一条足够长的人工笔记正文。",
                        "liked_count": 8,
                        "collected_count": 2,
                        "comments_count": 1,
                        "domain": "旅行",
                        "local_time": "2021010108",
                    }
                ],
            )
            _write_jsonl(
                raw / "training_set_aigc.jsonl",
                [
                    {
                        "note_title": "AI标题",
                        "note_content": "这是AI生成内容，不能进入真实互动评分训练。",
                        "domain": "美食",
                        "model_family": "OpenAI",
                        "model": "test",
                    }
                ],
            )

            features, manifest = build_v04_dataset(raw, out)
            self.assertEqual(manifest["source_counts_all"]["aigc"], 1)
            self.assertNotIn("aigc", set(features["source_type"]))
            self.assertEqual(features["note_id"].nunique(), len(features))
            same = features[features["note_id"] == "same"].iloc[0]
            self.assertEqual(same["note_title"], "高互动标题")
            self.assertEqual(float(same["ces_raw"]), 140.0)

    def test_feature_contract_is_62_unique_columns(self):
        self.assertEqual(len(MODEL_FEATURE_COLS_V04), 62)
        self.assertEqual(len(MODEL_FEATURE_COLS_V04), len(set(MODEL_FEATURE_COLS_V04)))

    def test_group_leakage_audit_detects_overlap(self):
        train = pd.DataFrame({"note_id": ["a", "b"]})
        val = pd.DataFrame({"note_id": ["c"]})
        self.assertTrue(_assert_no_leakage(train, val)["passed"])
        val_bad = pd.DataFrame({"note_id": ["b"]})
        self.assertFalse(_assert_no_leakage(train, val_bad)["passed"])


if __name__ == "__main__":
    unittest.main()
