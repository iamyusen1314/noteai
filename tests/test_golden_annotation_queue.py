import sys
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from export_golden_annotation_queue import build_annotation_queue, write_jsonl  # noqa: E402


def _score_row(note_id: str, domain: str, score: float, idx: int) -> dict:
    return {
        "note_id": note_id,
        "note_title": f"{domain}标题{idx}",
        "desc": f"{domain}正文内容足够长，用于测试人工 golden 标注队列抽样。{idx}",
        "domain": domain,
        "source_type": "human",
        "source_file": "training_set_human.jsonl",
        "source_row": idx,
        "liked_count": idx,
        "collected_count": idx // 2,
        "comments_count": idx // 3,
        "ces_raw": float(idx),
        "ces_percentile": score,
    }


class GoldenAnnotationQueueTests(unittest.TestCase):
    def test_build_queue_samples_strata_and_adds_empty_label_fields(self):
        score_rows = [
            _score_row("food_top_1", "美食", 92, 1),
            _score_row("food_top_2", "美食", 88, 2),
            _score_row("food_mid", "美食", 45, 3),
            _score_row("food_low", "美食", 10, 4),
            _score_row("travel_top", "旅行", 91, 5),
            _score_row("travel_mid", "旅行", 44, 6),
            _score_row("travel_low", "旅行", 12, 7),
        ]
        normalized_rows = [
            {
                "note_id": "aigc_food",
                "note_title": "AI美食标题",
                "desc": "AI美食正文内容足够长，用于测试。",
                "domain": "美食",
                "source_type": "aigc",
                "source_file": "training_set_aigc.jsonl",
                "source_row": 1,
            },
            {
                "note_id": "aigc_travel",
                "note_title": "AI旅行标题",
                "desc": "AI旅行正文内容足够长，用于测试。",
                "domain": "旅行",
                "source_type": "aigc",
                "source_file": "training_set_aigc.jsonl",
                "source_row": 2,
            },
        ]
        band_plan = {
            "real_top": {"min": 85, "max": 100.1, "count": 1},
            "real_mid": {"min": 35, "max": 55, "count": 1},
            "real_low": {"min": 0, "max": 25, "count": 1},
        }

        rows, report = build_annotation_queue(
            pd.DataFrame(score_rows),
            pd.DataFrame(normalized_rows),
            domains=["美食", "旅行"],
            real_band_plan=band_plan,
            aigc_per_domain=1,
            include_seed_labels=False,
            random_seed=7,
        )

        self.assertEqual(len(rows), 8)
        self.assertEqual(report["totals"]["needs_label"], 8)
        self.assertEqual(report["by_bucket"]["aigc"], 2)
        self.assertEqual(report["by_bucket"]["real_top"], 2)
        self.assertEqual(len({row["annotation_id"] for row in rows}), len(rows))
        self.assertTrue(all(row["human_label_status"] == "needs_label" for row in rows))
        self.assertTrue(all(row["human_quality_score"] == "" for row in rows))
        self.assertTrue(all(row["text_hash"] for row in rows))

    def test_dedupe_removes_duplicate_non_seed_text(self):
        duplicate_a = _score_row("dup_a", "美食", 92, 1)
        duplicate_b = _score_row("dup_b", "美食", 90, 2)
        duplicate_b["note_title"] = duplicate_a["note_title"]
        duplicate_b["desc"] = duplicate_a["desc"]
        band_plan = {"real_top": {"min": 85, "max": 100.1, "count": 2}}

        rows, report = build_annotation_queue(
            pd.DataFrame([duplicate_a, duplicate_b]),
            pd.DataFrame([], columns=["source_type", "domain"]),
            domains=["美食"],
            real_band_plan=band_plan,
            aigc_per_domain=0,
            include_seed_labels=False,
            random_seed=7,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(report["dedupe"]["duplicate_text_removed"], 1)

    def test_jsonl_writer_escapes_unicode_line_separators(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "queue.jsonl"
            write_jsonl(
                [
                    {
                        "annotation_id": "a",
                        "body": "第一段\u2028第二段\u2029第三段",
                    }
                ],
                path,
            )
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            parsed = json.loads(lines[0])
            self.assertEqual(parsed["body"], "第一段\u2028第二段\u2029第三段")


if __name__ == "__main__":
    unittest.main()
