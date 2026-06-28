import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from export_preference_annotation_queue import build_preference_queue, write_jsonl  # noqa: E402


class PreferenceAnnotationQueueTests(unittest.TestCase):
    def test_build_queue_resolves_variants_and_locked_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "variants.json"
            source.write_text(
                json.dumps(
                    {
                        "items": [
                            {"title": "A标题", "body": "A正文足够长", "score": 60},
                            {"title": "B标题", "body": "B正文足够长", "score": 72},
                        ],
                        "manual": {"title": "C标题", "body": "C正文足够长", "score": 80},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            seed = {
                "version": "preference-pair-seeds-v0.1",
                "tasks": [
                    {
                        "task_id": "task_1",
                        "domain": "美食",
                        "task_context": "同一任务",
                        "comparison_focus": ["标题", "正文"],
                        "variants": [
                            {
                                "id": "a",
                                "origin": "gen",
                                "source_file": str(source),
                                "title_path": "items.0.title",
                                "body_path": "items.0.body",
                                "score_path": "items.0.score",
                            },
                            {
                                "id": "b",
                                "origin": "repair",
                                "source_file": str(source),
                                "title_path": "items.1.title",
                                "body_path": "items.1.body",
                                "score_path": "items.1.score",
                            },
                            {
                                "id": "c",
                                "origin": "manual",
                                "source_file": str(source),
                                "title_path": "manual.title",
                                "body_path": "manual.body",
                                "score_path": "manual.score",
                            },
                        ],
                        "locked_pairs": [
                            {
                                "variant_a": "a",
                                "variant_b": "c",
                                "winner_variant_id": "c",
                                "preference_margin": 3,
                                "delivery_ready_winner": True,
                                "reason_tags": ["naturalness"],
                                "loser_failure_tags": ["ai_smell"],
                                "rationale": "C更自然",
                            }
                        ],
                    }
                ],
            }

            rows, report = build_preference_queue(seed)
            self.assertEqual(len(rows), 3)
            self.assertEqual(report["totals"]["locked_seed"], 1)
            locked = [row for row in rows if row["label_status"] == "locked_seed"][0]
            self.assertEqual(locked["winner"], "B")
            self.assertEqual(locked["preference_margin"], 3)
            self.assertEqual(locked["delivery_ready_winner"], True)
            self.assertEqual(locked["variant_b_id"], "c")
            self.assertEqual(locked["reason_tags"], "naturalness")

    def test_jsonl_writer_escapes_unicode_line_separators(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pref.jsonl"
            write_jsonl(
                [
                    {
                        "pair_id": "p",
                        "variant_a_body": "第一段\u2028第二段",
                        "variant_b_body": "第三段\u2029第四段",
                    }
                ],
                path,
            )
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            parsed = json.loads(lines[0])
            self.assertEqual(parsed["variant_a_body"], "第一段\u2028第二段")
            self.assertEqual(parsed["variant_b_body"], "第三段\u2029第四段")


if __name__ == "__main__":
    unittest.main()
