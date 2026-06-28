import json
import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from fill_preference_generation_slots import (  # noqa: E402
    artifact_path,
    build_run_report,
    generation_payload,
    parse_note,
    route_support_status,
    select_rows,
    source_context_from_payload,
)
from build_preference_seed_from_generated_artifacts import _training_body_filter_issues  # noqa: E402


class FillPreferenceGenerationSlotsTests(unittest.TestCase):
    def _row(self, *, route="generate", domain="美食", slot_id="generate_initial"):
        payload = {
            "task_id": "food_1",
            "domain": domain,
            "user_intent": "生成一篇探店笔记",
            "known_facts": ["地点在上海南京西路附近", "人均58元", "营业时间11:00-21:30", "必点蟹黄拌面"],
            "fact_status": "safe",
            "target_reader": "上海用户",
            "quality_focus": ["价格明确"],
            "slot_id": slot_id,
            "origin": "generate",
            "generation_route": route,
            "prompt_focus": ["首稿"],
            "reference": {"title": "参考", "body_excerpt": "参考正文"},
        }
        return {
            "queue_id": f"q_{slot_id}",
            "task_id": "food_1",
            "domain": domain,
            "slot_id": slot_id,
            "origin": "generate",
            "generation_route": route,
            "generation_payload_json": json.dumps(payload, ensure_ascii=False),
        }

    def test_generation_payload_and_source_context_add_food_labels(self):
        row = self._row()
        payload = generation_payload(row)
        context = source_context_from_payload(payload)

        self.assertIn("- 已核验事实：人均58元", context)
        self.assertIn("- 价格/人均：人均58元", context)
        self.assertIn("- 位置/地址：地点在上海南京西路附近", context)
        self.assertIn("- 营业时间：营业时间11:00-21:30", context)
        self.assertIn("- 必点/招牌菜：必点蟹黄拌面", context)

    def test_source_context_does_not_label_internal_missing_fact_constraints(self):
        row = self._row()
        payload = generation_payload(row)
        payload["known_facts"] = [
            "地点在广州番禺万博商圈附近",
            "用户未提供准确人均和营业时间，不能编造具体数字",
            "推荐菜包括芝士焗小青龙、红烧乳鸽",
        ]
        context = source_context_from_payload(payload)

        self.assertIn("- 已核验事实：用户未提供准确人均和营业时间，不能编造具体数字", context)
        self.assertIn("- 位置/地址：地点在广州番禺万博商圈附近", context)
        self.assertNotIn("- 价格/人均：用户未提供准确人均", context)
        self.assertNotIn("- 营业时间：用户未提供准确人均", context)

    def test_parse_note_accepts_xml_and_label_fallback(self):
        parsed = parse_note("<note><title>上海蟹黄面推荐</title><body>正文#标签</body></note>")
        self.assertEqual(parsed, ("上海蟹黄面推荐", "正文#标签"))

        fallback = parse_note("标题：小个子显高公式\n正文：第一套这样穿。\n#穿搭")
        self.assertEqual(fallback, ("小个子显高公式", "第一套这样穿。\n#穿搭"))

    def test_preference_seed_filters_template_fact_sections(self):
        templated = {
            "body": "这家适合聚餐。实用信息：地址：惠福东路470号，人均86元，营业时间08:00-21:00。\n#广州美食"
        }
        natural = {
            "body": "地址和营业时间都很清楚，逛完北京路再去吃比较顺，想省心可以提前收藏导航。\n#广州美食"
        }
        self.assertIn("fact_section_template_filtered", _training_body_filter_issues(templated))
        self.assertEqual(_training_body_filter_issues(natural), [])

    def test_select_rows_skips_manual_and_existing_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            direct = self._row()
            manual = self._row(route="manual", slot_id="manual_natural_rewrite")
            existing = self._row(slot_id="generate_refined")
            path = artifact_path(out, existing)
            path.parent.mkdir(parents=True)
            path.write_text("{}", encoding="utf-8")

            selected, skipped = select_rows([direct, manual, existing], output_dir=out)

            self.assertEqual([row["slot_id"] for row in selected], ["generate_initial"])
            reasons = {item["slot_id"]: item["reason"] for item in skipped}
            self.assertEqual(reasons["manual_natural_rewrite"], "manual_slot_requires_human_rewrite")
            self.assertEqual(reasons["generate_refined"], "artifact_exists")

    def test_route_support_dependent_requires_flag(self):
        self.assertEqual(route_support_status("second_pass", include_dependent=False)[0], False)
        self.assertEqual(route_support_status("second_pass", include_dependent=True), (True, "dependent"))

    def test_build_run_report_summarizes_scores(self):
        row = self._row()
        results = [
            {
                "status": "ready",
                "path": "/tmp/a.json",
                "artifact": {
                    "status": "ready",
                    "domain": "美食",
                    "task_id": "food_1",
                    "slot_id": "generate_initial",
                    "title": "上海蟹黄面推荐",
                    "score": 73.2,
                    "blocking": False,
                },
            },
            {
                "status": "failed",
                "path": "/tmp/b.json",
                "artifact": {
                    "status": "failed",
                    "domain": "美食",
                    "task_id": "food_1",
                    "slot_id": "generate_refined",
                    "error": "boom",
                },
            },
        ]
        report = build_run_report(
            queue_path=Path("/tmp/q.jsonl"),
            output_dir=Path("/tmp/out"),
            selected=[row],
            skipped=[],
            results=results,
            dry_run=False,
        )

        self.assertEqual(report["score_summary"]["legacy_score_ge_reference"], 1)
        self.assertEqual(report["by_status"]["ready"], 1)
        self.assertEqual(report["by_status"]["failed"], 1)
        self.assertEqual(report["ready_outputs"][0]["title"], "上海蟹黄面推荐")


if __name__ == "__main__":
    unittest.main()
