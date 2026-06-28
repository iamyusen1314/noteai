import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from export_core_domain_supplement_queue import build_supplement_queue  # noqa: E402


class CoreDomainSupplementQueueTests(unittest.TestCase):
    def _build_rows(self, rows):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp) / "raw"
            raw_dir.mkdir()
            existing = Path(tmp) / "existing.jsonl"
            existing.write_text("", encoding="utf-8")
            (raw_dir / "training_set_human.jsonl").write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                encoding="utf-8",
            )
            (raw_dir / "exploring_set.jsonl").write_text("", encoding="utf-8")

            return build_supplement_queue(
                raw_dir=raw_dir,
                domains=["美妆", "家居", "母婴", "健身"],
                existing_queue=existing,
                per_domain=10,
                min_score=7,
                min_body_chars=10,
            )

    def test_best_matching_domain_wins_instead_of_first_domain(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp) / "raw"
            raw_dir.mkdir()
            existing = Path(tmp) / "existing.jsonl"
            existing.write_text("", encoding="utf-8")
            row = {
                "note_title": "减脂训练一周计划",
                "note_content": "健身训练动作安排，臀腿训练3组12次，蛋白质饮食和热量控制都写清楚。",
                "liked_count": 10,
                "collected_count": 3,
                "comments_count": 1,
            }
            (raw_dir / "training_set_human.jsonl").write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            (raw_dir / "exploring_set.jsonl").write_text("", encoding="utf-8")

            rows, report = build_supplement_queue(
                raw_dir=raw_dir,
                domains=["美食", "健身"],
                existing_queue=existing,
                per_domain=10,
                min_score=7,
                min_body_chars=10,
            )

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["domain"], "健身")
            self.assertEqual(report["by_domain_selected"]["健身"], 1)

    def test_expanded_beauty_terms_are_mined(self):
        rows, report = self._build_rows(
            [
                {
                    "note_title": "油痘肌面膜美白记录",
                    "note_content": "这篇主要写痘痘、毛孔和刷酸后的修护，面膜保湿不黏，敏感肌也要先局部测试。",
                    "liked_count": 8,
                    "collected_count": 2,
                    "comments_count": 1,
                }
            ]
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["domain"], "美妆")
        self.assertEqual(report["by_domain_selected"]["美妆"], 1)

    def test_expanded_home_terms_are_mined(self):
        rows, report = self._build_rows(
            [
                {
                    "note_title": "我家新家入住后的厨房收纳",
                    "note_content": "入住三个月最满意的是餐边柜和洗碗机，餐桌动线顺了很多，小户型也不显乱。",
                    "liked_count": 8,
                    "collected_count": 2,
                    "comments_count": 1,
                }
            ]
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["domain"], "家居")
        self.assertEqual(report["by_domain_selected"]["家居"], 1)

    def test_expanded_maternity_terms_are_mined(self):
        rows, report = self._build_rows(
            [
                {
                    "note_title": "孩子幼儿园入园准备清单",
                    "note_content": "小朋友入园前要准备姓名贴、安抚物和绘本，分离焦虑阶段家长可以提前做亲子沟通。",
                    "liked_count": 8,
                    "collected_count": 2,
                    "comments_count": 1,
                }
            ]
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["domain"], "母婴")
        self.assertEqual(report["by_domain_selected"]["母婴"], 1)


if __name__ == "__main__":
    unittest.main()
