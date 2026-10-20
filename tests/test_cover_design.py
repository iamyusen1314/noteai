"""Offline v2 prompt/provenance contracts, not model or aesthetic acceptance."""
from pathlib import Path
import json
import sys
import unittest
from unittest import mock
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import cover_design as design
import cover_renderer as renderer


def model_brief(reference):
    return {
        "industry": "休闲娱乐", "subtype": "以原图判断",
        "content_intent": "展示真实环境", "reader_question": "庭院有什么看点",
        "visual_strategy": "主景明确，文字避开关键主体",
        "source_reasons": [{"source_ref": reference, "reason": "画面清晰，主体完整"}],
        "evidence_ids": ["xhs-community-truth-and-title"],
        "reference_usage": [{"evidence_id": "xhs-community-truth-and-title",
                             "borrow": "图文相符", "limit": "不借他店事实"}],
        "factual_exclusions": ["不新增设施价格或体验"],
    }


def photo_plan(reference, text="松影红桥"):
    return {
        "schema_version": 2, "route": "photo", "background_color": "#FFFFFF",
        "photos": [{"source_ref": reference, "crop": [0, 0, 1, 1],
                    "subject_bbox": [.2, .3, .8, .8], "bbox": [0, 0, 1, 1]}],
        "text_layers": [{"text": text, "bbox": [.04, .02, .96, .17],
                         "font_id": "SourceHanSansSC-Bold", "font_size": 96,
                         "align": "left", "color": "#111111"}],
        "text": text, "design_brief": model_brief(reference),
    }


class CoverDesignTests(unittest.TestCase):
    def setUp(self):
        self.refs = [str(uuid.uuid4()) for _ in range(9)]
        self.sources = [{"media_ref": ref, "width": 1671, "height": 941,
                         "payload": b"PRIVATE_IMAGE_BYTES_MUST_NOT_ENTER_PROMPT"}
                        for ref in self.refs]
        self.context = {
            "title": "松影红桥都市禅意汤泉值得来", "title_variants": ["庭院暖光汤池"],
            "approved_titles": ["松影红桥都市禅意汤泉值得来"],
            "body": "本人保存的笔记内容。", "domain": "休闲娱乐",
            "visual_advice": "按原图5与8观察；不能把候选1当原图1。",
            "source_items": [
                {"input_field": "cover_images", "image_index": 5, "media_ref": self.refs[0]},
                {"input_field": "cover_images", "image_index": 8, "media_ref": self.refs[0]},
            ],
        }

    def validate(self, plan=None, context=None):
        return design.validate_design(plan or photo_plan(self.refs[0]),
                                      context or self.context, self.refs)

    def test_single_source_brief_preserves_positions_dimensions_and_hides_bytes(self):
        brief = design.build_design_brief(self.context, self.sources[:1])
        source = brief["sources"][0]
        self.assertEqual(source["source_ref"], self.refs[0])
        self.assertEqual((source["width"], source["height"]), (1671, 941))
        self.assertEqual([item["image_index"] for item in source["original_positions"]], [5, 8])
        self.assertIsNone(brief["subtype"])
        self.assertNotIn("PRIVATE_IMAGE", json.dumps(brief, ensure_ascii=False))
        self.assertEqual(brief["evidence_version"], design.EVIDENCE_VERSION)

    def test_nine_source_prompt_uses_every_attachment_in_real_order(self):
        prompt = design.build_design_prompt(self.context, self.sources)
        serialized = prompt.split("\n本地证据与本任务素材=", 1)[1]
        brief = json.loads(serialized)
        self.assertEqual([item["source_ref"] for item in brief["sources"]], self.refs)
        self.assertEqual([item["candidate_number"] for item in brief["sources"]], list(range(1, 10)))
        self.assertEqual(brief["sources"][1]["original_positions"], [])
        self.assertIn("候选编号不等于报告观察原图号", prompt)
        self.assertIn("全部1–9张", prompt)
        self.assertIn("空格、标点和字序不得改", prompt)
        self.assertIn("实际制作能力=", prompt)
        self.assertNotIn("PRIVATE_IMAGE", prompt)

    def test_missing_renderer_capability_is_not_silently_given_an_old_template(self):
        with mock.patch.object(renderer, "design_capabilities", None), self.assertRaisesRegex(
                design.CoverDesignError, "COVER_DESIGN_CAPABILITIES_UNAVAILABLE"):
            design.build_design_prompt(self.context, self.sources[:1])

    def test_unknown_and_leisure_industries_do_not_inherit_bathing_or_hotel_rules(self):
        for domain in ("休闲娱乐", "leisure", "全新行业", "leisure-洗浴"):
            with self.subTest(domain=domain):
                brief = design.build_design_brief({**self.context, "domain": domain}, self.sources[:1])
                self.assertIsNone(brief["subtype"])
                self.assertEqual({item["id"] for item in brief["reference_rules"]},
                                 {"xhs-community-truth-and-title", "xhs-product-note-20260211"})
        for domain, expected in (("餐饮", "xhs-food-202402-p13"),
                                 ("酒店", "xhs-hospitality-202401-p19"),
                                 ("美妆", "xhs-beauty-2020-p08-p11")):
            with self.subTest(domain=domain):
                references = design.build_design_brief({**self.context, "domain": domain},
                                                       self.sources[:1])["reference_rules"]
                chosen = next(item for item in references if item["id"] == expected)
                self.assertTrue(chosen["url"])
                self.assertTrue(chosen["scope"])
                self.assertEqual(chosen["kind"], "historical_attributed_report_mirror")

    def test_source_input_limits_reject_duplicates_urls_and_silent_truncation(self):
        for sources in ([], self.sources + [self.sources[0]], self.sources[:1] * 2,
                        [{"media_ref": "https://example.invalid/photo.png"}]):
            with self.subTest(sources=len(sources)), self.assertRaisesRegex(
                    design.CoverDesignError, "COVER_DESIGN_SOURCE_INVALID"):
                design.build_design_brief(self.context, sources)
        with self.assertRaisesRegex(design.CoverDesignError, "COVER_DESIGN_SOURCE_DIMENSIONS_INVALID"):
            design.build_design_brief(self.context, [{**self.sources[0], "width": True}])

    def test_real_v2_renderer_plan_and_brief_are_validated_separately(self):
        original = photo_plan(self.refs[0])
        with mock.patch.object(renderer, "validate_plan", wraps=renderer.validate_plan) as validate:
            safe = self.validate(original)
        self.assertNotIn("design_brief", validate.call_args.args[0])
        self.assertEqual(safe["schema_version"], 2)
        self.assertEqual(safe["design_brief"]["interpretation_status"], "director_proposal_not_verified_facts")
        self.assertEqual(original["design_brief"], model_brief(self.refs[0]))

    def test_selected_source_and_source_reason_cannot_reference_another_task(self):
        foreign = str(uuid.uuid4())
        bad = photo_plan(foreign)
        with self.assertRaisesRegex(design.CoverDesignError, "COVER_DESIGN_SOURCE_INVALID"):
            self.validate(bad)
        for source_ref in (self.refs[1], []):
            bad = photo_plan(self.refs[0])
            bad["design_brief"]["source_reasons"][0]["source_ref"] = source_ref
            with self.subTest(source_ref=source_ref), self.assertRaisesRegex(
                    design.CoverDesignError, "COVER_DESIGN_SOURCE_INVALID"):
                self.validate(bad)

    def test_one_selected_title_controls_excerpts_with_legacy_fallback_only_when_absent(self):
        with self.assertRaisesRegex(design.CoverDesignError, "COVER_DESIGN_TEXT_NOT_FROM_TITLE"):
            self.validate(photo_plan(self.refs[0], "庭院暖光汤池"))
        legacy = {key: value for key, value in self.context.items() if key != "approved_titles"}
        self.assertEqual(self.validate(photo_plan(self.refs[0], "庭院暖光汤池"), legacy)["text"], "庭院暖光汤池")
        with self.assertRaisesRegex(design.CoverDesignError, "COVER_DESIGN_TITLE_INVALID"):
            self.validate(context={**self.context, "approved_titles": []})

    def test_copy_keeps_punctuation_spaces_and_single_title_order(self):
        cases = [(["松影，红桥"], "松影红桥"), (["松影 红桥"], "松影红桥"),
                 (["松影红桥", "都市禅意汤泉"], "红桥都市"),
                 (["松影红桥"], "红桥松影")]
        for titles, text in cases:
            with self.subTest(text=text, titles=titles), self.assertRaisesRegex(
                    design.CoverDesignError, "COVER_DESIGN_TEXT_NOT_FROM_TITLE"):
                self.validate(photo_plan(self.refs[0], text), {**self.context, "approved_titles": titles})
        safe = self.validate(photo_plan(self.refs[0], "松影，\n红桥"),
                             {**self.context, "approved_titles": ["松影，红桥"]})
        self.assertEqual(safe["text"], "松影，\n红桥")

    def test_text_layers_must_exactly_reconstruct_the_top_level_copy(self):
        plan = photo_plan(self.refs[0])
        plan["text_layers"].append({**plan["text_layers"][0], "text": "都市禅意汤泉",
                                    "bbox": [.04, .18, .96, .29]})
        plan["text"] = "松影红桥\n都市禅意汤泉"
        self.assertEqual(self.validate(plan)["text"], plan["text"])
        plan["text"] = "松影红桥都市禅意汤泉"
        with self.assertRaises(design.CoverDesignError):
            self.validate(plan)

    def test_brief_cannot_invent_reference_authority_or_mark_facts_verified(self):
        for field, update, error in (
            ("evidence_ids", ["fake-current-viral-rule"], "COVER_DESIGN_EVIDENCE_INVALID"),
            ("evidence_ids", ["xhs-hospitality-202401-p19"], "COVER_DESIGN_EVIDENCE_INVALID"),
            ("verified", True, "COVER_DESIGN_BRIEF_INVALID"),
        ):
            with self.subTest(field=field, update=update):
                plan = photo_plan(self.refs[0])
                plan["design_brief"][field] = update
                with self.assertRaisesRegex(design.CoverDesignError, error):
                    self.validate(plan)
        plan = photo_plan(self.refs[0])
        for field in ("industry", "subtype", "content_intent", "reader_question", "visual_strategy"):
            plan["design_brief"][field] = "字" * 80
        with self.assertRaisesRegex(design.CoverDesignError, "COVER_DESIGN_BRIEF_TOO_LONG"):
            self.validate(plan)

    def test_renderer_rejection_propagates_and_v1_is_not_reinterpreted_as_v2(self):
        with mock.patch.object(renderer, "validate_plan", side_effect=renderer.CoverRenderError("COVER_SUBJECT_CROPPED")):
            with self.assertRaisesRegex(design.CoverDesignError, "COVER_SUBJECT_CROPPED"):
                self.validate()
        for version in (1, True, 2.0):
            plan = photo_plan(self.refs[0])
            plan["schema_version"] = version
            with self.subTest(version=version), self.assertRaisesRegex(
                    design.CoverDesignError, "COVER_DESIGN_VERSION_INVALID"):
                self.validate(plan)


if __name__ == "__main__":
    unittest.main()
