import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from build_preference_pairs_from_golden_labels import build_pairs  # noqa: E402


def _item(item_id: str, score: int, ready: bool, title: str) -> dict:
    return {
        "id": item_id,
        "content_source": {
            "type": "inline",
            "domain": "美食",
            "title": title,
            "body": f"{title}，地址、人均和招牌菜都写清楚，点赞收藏。#广州美食 #探店",
        },
        "labels": {
            "human_quality_score": score,
            "delivery_ready": ready,
            "naturalness_label": score,
            "fact_status": "safe",
            "ai_smell_level": 1 if ready else 4,
            "failure_tags": [] if ready else ["low_info_density"],
        },
    }


class GoldenPairwiseDistillationTests(unittest.TestCase):
    def test_builds_only_large_gap_pairs_with_auditable_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "golden.json"
            path.write_text(
                json.dumps(
                    {
                        "version": "golden-labels-v0.1",
                        "items": [
                            _item("good", 88, True, "广州早茶人均88稳"),
                            _item("mid", 74, True, "广州早茶家庭聚餐"),
                            _item("bad", 42, False, "这家早茶绝了"),
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            rows, report = build_pairs(golden_path=path, max_pairs_per_domain=10, min_score_gap=20, ready_gap_min=12)

            self.assertEqual(len(rows), 2)
            self.assertEqual(report["totals"]["pairs"], 2)
            self.assertEqual({row["label_source"] for row in rows}, {"golden_pairwise_distillation"})
            self.assertTrue(all(row["winner"] in {"A", "B"} for row in rows))
            self.assertTrue(all("golden_score_gap" in row["reason_tags"] for row in rows))
            self.assertTrue(all(row["task_id"] == "golden_distilled_美食" for row in rows))


if __name__ == "__main__":
    unittest.main()
