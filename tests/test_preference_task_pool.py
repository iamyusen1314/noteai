import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from export_preference_task_pool import build_generation_queue, write_jsonl  # noqa: E402


class PreferenceTaskPoolTests(unittest.TestCase):
    def test_build_generation_queue_expands_slots_and_reports_targets(self):
        pool = {
            "version": "preference-task-pool-v0.1",
            "tasks": [
                {
                    "task_id": "food_1",
                    "domain": "美食",
                    "task_status": "needs_generation",
                    "priority": "high",
                    "source_case_id": "case_1",
                    "user_intent": "生成美食笔记",
                    "known_facts": ["人均58元", "必点蟹黄面"],
                    "fact_status": "safe",
                    "target_reader": "上海用户",
                    "quality_focus": ["价格", "口味"],
                    "reference_title": "参考标题",
                    "reference_body": "参考正文",
                    "variant_slots": [
                        {
                            "slot_id": "generate_initial",
                            "origin": "generate",
                            "status": "needs_generation",
                            "generation_route": "generate",
                            "prompt_focus": ["首稿"],
                        },
                        {
                            "slot_id": "manual_natural_rewrite",
                            "origin": "manual",
                            "status": "ready",
                            "generation_route": "manual",
                            "prompt_focus": ["自然"],
                            "source_file": "manual.json",
                        },
                    ],
                }
            ],
        }

        rows, report = build_generation_queue(pool)
        self.assertEqual(len(rows), 2)
        self.assertEqual(report["totals"]["tasks"], 1)
        self.assertEqual(report["totals"]["generation_rows"], 2)
        self.assertEqual(report["totals"]["needs_generation_slots"], 1)
        self.assertEqual(report["totals"]["ready_slots"], 1)
        self.assertEqual(report["by_domain_generation_rows"]["美食"], 2)
        self.assertIn("generation_payload_json", rows[0])
        payload = json.loads(rows[0]["generation_payload_json"])
        self.assertEqual(payload["known_facts"], ["人均58元", "必点蟹黄面"])
        self.assertGreater(report["coverage_gaps"]["task_targets"]["美食"]["rough_tasks_needed_for_3000_pairs_at_9_variants"], 0)

    def test_jsonl_writer_escapes_unicode_line_separators(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "generation.jsonl"
            write_jsonl(
                [
                    {
                        "queue_id": "q",
                        "user_intent": "第一段\u2028第二段",
                        "known_facts": "第三段\u2029第四段",
                    }
                ],
                path,
            )
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            parsed = json.loads(lines[0])
            self.assertEqual(parsed["user_intent"], "第一段\u2028第二段")
            self.assertEqual(parsed["known_facts"], "第三段\u2029第四段")


if __name__ == "__main__":
    unittest.main()
