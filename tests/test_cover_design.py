"""Offline v2 prompt/provenance contracts, not model or aesthetic acceptance."""
from pathlib import Path
import io
import json
import sys
import unittest
from unittest import mock
import uuid
from PIL import Image, ImageChops

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

    def test_contain_preview_matches_pasted_pixels_for_landscape_exact_and_portrait(self):
        for size in ((1671, 941), (1920, 960), (600, 800), (600, 1200)):
            with self.subTest(size=size):
                stream = io.BytesIO()
                Image.new("RGB", size, "navy").save(stream, "PNG")
                source = {"media_ref": self.refs[0], "width": size[0], "height": size[1],
                          "payload": stream.getvalue()}
                preview = design.build_design_brief(self.context, [source])["sources"][0]["uncropped_full_canvas_contain"]
                base, _ = renderer.compose_sources([source], photo_plan(self.refs[0]))
                with Image.open(io.BytesIO(base)) as actual:
                    bounds = ImageChops.difference(actual, Image.new("RGB", actual.size, "white")).getbbox()
                expected = [round(value / (renderer.WIDTH if index % 2 == 0 else renderer.HEIGHT), 6)
                            for index, value in enumerate(bounds)]
                self.assertEqual(preview["actual_photo_bbox"], expected)
                area = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
                self.assertEqual(preview["photo_area_fraction"], round(area / (renderer.WIDTH * renderer.HEIGHT), 6))
                if size == (1671, 941):
                    self.assertLess(preview["photo_area_fraction"], .43)
                    self.assertGreater(preview["actual_photo_bbox"][1], .28)

    def test_missing_source_dimensions_do_not_invent_a_contain_preview(self):
        source = {"media_ref": self.refs[0]}
        brief = design.build_design_brief(self.context, [source])
        self.assertIsNone(brief["sources"][0]["uncropped_full_canvas_contain"])
        self.assertIsNone(brief["sources"][0]["width"])

    def test_unrepresentable_uncropped_hint_does_not_discard_other_candidates(self):
        sources = [{**self.sources[0], "width": 40000, "height": 1}, self.sources[1]]
        labels = design.build_design_brief(self.context, sources)["sources"]
        self.assertEqual([item["source_ref"] for item in labels], self.refs[:2])
        self.assertIsNone(labels[0]["uncropped_full_canvas_contain"])
        self.assertIsNotNone(labels[1]["uncropped_full_canvas_contain"])

    def test_director_receives_container_semantics_and_real_occupancy(self):
        prompt = design.build_design_prompt(self.context, self.sources)
        brief = json.loads(prompt.split("\n本地证据与本任务素材=", 1)[1])
        self.assertTrue(all(item["uncropped_full_canvas_contain"]["photo_area_fraction"] < .43
                            for item in brief["sources"]))
        self.assertIn("not actual photo bounds", prompt)
        self.assertIn("fit:cover/object_fit不受支持", prompt)
        self.assertIn("crop必须包含原图全部关键主体", prompt)
        self.assertIn("1–3张明确分景", prompt)

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

    def span_response(self, spans, **updates):
        value = photo_plan(self.refs[0])
        del value["text"]
        template = value["text_layers"][0]
        value["text_layers"] = [{**{key: item for key, item in template.items() if key != "text"},
                                 "copy_span": span} for span in spans]
        return {**value, **updates}

    def test_director_selects_actual_ui_title_without_transcribing_or_changing_saved_schema(self):
        # The title was observed in the real UI; this response is a fixture,
        # not a reconstruction of the failed supplier's unretained response.
        context = {**self.context, "approved_titles": ["闹市高楼里的日式庭院汤泉，松弛感很出彩"]}
        value = self.span_response([{"title_id": "t1", "start": 2, "end": 6},
                                    {"title_id": "t1", "start": 6, "end": 12}])
        original = json.dumps(value, ensure_ascii=False)
        resolved = design.materialize_design_response(value, context)
        safe = design.validate_design(resolved, context, self.refs)
        self.assertEqual(safe["text"], "高楼里的\n日式庭院汤泉")
        self.assertEqual(safe["schema_version"], 2)
        self.assertTrue(all("copy_span" not in layer for layer in resolved["text_layers"]))
        self.assertEqual(json.dumps(value, ensure_ascii=False), original)
        self.assertNotIn("text", value)

    def test_copy_catalog_indexes_original_unicode_and_only_removes_lf(self):
        title = "甲， \n乙😀e\u0301"
        context = {**self.context, "approved_titles": [title, title, "其他标题"]}
        brief = design.build_design_brief(context, self.sources[:1])
        self.assertEqual(brief["copy_catalog"], [
            {"title_id": "t1", "indexed_chars": list(enumerate("甲， 乙😀e\u0301")), "end": 7},
            {"title_id": "t2", "indexed_chars": list(enumerate("其他标题")), "end": 4}])
        value = self.span_response([{"title_id": "t1", "start": 0, "end": 7}])
        resolved = design.materialize_design_response(value, context)
        self.assertEqual(resolved["text"], "甲， 乙😀e\u0301")
        prompt = design.build_design_prompt(context, self.sources[:1])
        contract = json.loads(prompt.split("输出合同=", 1)[1].split("\n实际制作能力=", 1)[0])
        self.assertNotIn("text", contract)
        self.assertNotIn("text", contract["text_layers"][0])
        self.assertIn("不要自行数汉字或按UTF-16计数", prompt)

    def test_span_selection_preserves_punctuation_and_explicit_semantic_line_breaks(self):
        context = {**self.context, "approved_titles": ["松影，红桥都市"]}
        value = self.span_response([{"title_id": "t1", "start": 0, "end": 3},
                                    {"title_id": "t1", "start": 3, "end": 5},
                                    {"title_id": "t1", "start": 5, "end": 7}])
        resolved = design.materialize_design_response(value, context)
        self.assertEqual(self.validate(resolved, context)["text"], "松影，\n红桥\n都市")
        value = self.span_response([{"title_id": "t1", "start": 0, "end": 7}])
        value["text_layers"][0]["line_breaks"] = [3, 5]
        self.assertEqual(design.materialize_design_response(value, context)["text"], "松影，\n红桥\n都市")

    def test_invalid_copy_selection_stops_without_fallback_or_free_text(self):
        good = {"title_id": "t1", "start": 0, "end": 4}
        context = {**self.context, "approved_titles": ["甲" * 40, "乙" * 40]}
        for span, error in (
            ({**good, "title_id": "unknown"}, "COPY_TITLE_INVALID"),
            ({**good, "start": -1}, "COPY_RANGE_INVALID"),
            ({**good, "start": True}, "COPY_RANGE_INVALID"),
            ({**good, "end": 4.0}, "COPY_RANGE_INVALID"),
            ({**good, "end": 0}, "COPY_RANGE_INVALID"),
            ({**good, "end": 41}, "COPY_RANGE_INVALID"),
            ({**good, "end": 33}, "COPY_TOO_LONG"),
        ):
            with self.subTest(span=span), self.assertRaisesRegex(design.CoverDesignError, error):
                design.materialize_design_response(self.span_response([span]), context)
        for second, error in (
            ({"title_id": "t1", "start": 5, "end": 8}, "COPY_NOT_CONTIGUOUS"),
            ({"title_id": "t1", "start": 3, "end": 8}, "COPY_NOT_CONTIGUOUS"),
            ({"title_id": "t2", "start": 4, "end": 8}, "COPY_TITLE_INVALID"),
            ({"title_id": "t1", "start": 4, "end": 33}, "COPY_TOO_LONG"),
        ):
            with self.subTest(second=second), self.assertRaisesRegex(design.CoverDesignError, error):
                design.materialize_design_response(self.span_response([good, second]), context)
        for mixed in (self.span_response([good], text="甲"), photo_plan(self.refs[0])):
            with self.assertRaisesRegex(design.CoverDesignError, "COPY_CONTRACT_INVALID"):
                design.materialize_design_response(mixed, context)
        mixed = self.span_response([good])
        mixed["text_layers"][0]["text"] = "甲"
        with self.assertRaisesRegex(design.CoverDesignError, "COPY_CONTRACT_INVALID"):
            design.materialize_design_response(mixed, context)

    def test_explicit_line_breaks_cannot_remove_characters_or_use_invalid_boundaries(self):
        span = {"title_id": "t1", "start": 1, "end": 5}
        for breaks in ([0], [1], [5], [2, 2], [3, 2], [True], [2.0], [[2]], "2"):
            value = self.span_response([span])
            value["text_layers"][0]["line_breaks"] = breaks
            with self.subTest(breaks=breaks), self.assertRaisesRegex(design.CoverDesignError, "COPY_BREAKS_INVALID"):
                design.materialize_design_response(value, self.context)

    def test_director_line_limit_matches_actual_renderer_and_prompt(self):
        context = {**self.context, "approved_titles": ["庭院汤泉松影红桥都市"]}
        value = self.span_response([{"title_id": "t1", "start": 0, "end": 10}])
        value["text_layers"][0]["line_breaks"] = [2, 4, 6]
        resolved = design.materialize_design_response(value, context)
        self.assertEqual(resolved["text"], "庭院\n汤泉\n松影\n红桥都市")
        value["text_layers"][0]["line_breaks"] = [2, 4, 6, 8]
        with self.assertRaisesRegex(design.CoverDesignError, "COPY_BREAKS_INVALID"):
            design.materialize_design_response(value, context)
        prompt = design.build_design_prompt(context, self.sources[:1])
        capabilities = json.loads(prompt.split("\n实际制作能力=", 1)[1].split("\n本地证据与本任务素材=", 1)[0])
        limits = capabilities["text_layout"]
        self.assertEqual(limits["max_rendered_lines_per_layer"], 4)
        self.assertEqual(limits["max_explicit_line_breaks"], 3)
        self.assertEqual(limits["padding_px"], 8)
        self.assertTrue(limits["font_size_is_fixed"])
        self.assertIn("每层总计最多4行", prompt)
        self.assertIn("实际带描边字形必须完整落在bbox内", prompt)

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

    def test_complete_brief_over_concision_target_retains_every_exclusion(self):
        plan = photo_plan(self.refs[0])
        for field in ("industry", "subtype", "content_intent", "reader_question", "visual_strategy"):
            plan["design_brief"][field] = "字" * 80
        exclusions = ["未证实价格不得新增", "不声称本人到访", "不得借用他店设施", "不新增疗效"]
        plan["design_brief"]["factual_exclusions"] = exclusions
        safe = self.validate(plan)
        for field, value in plan["design_brief"].items():
            self.assertEqual(safe["design_brief"][field], value)
        self.assertEqual(safe["design_brief"]["interpretation_status"], "director_proposal_not_verified_facts")
        self.assertEqual(safe["text"], plan["text"])

    def test_brief_concision_target_is_not_a_delivery_boundary(self):
        for total in (300, 301, 500):
            with self.subTest(total=total):
                plan = photo_plan(self.refs[0])
                brief = plan["design_brief"]
                fields = [(brief, key) for key in ("industry", "subtype", "content_intent",
                          "reader_question", "visual_strategy")]
                fields += [(brief["source_reasons"][0], "reason"),
                           (brief["reference_usage"][0], "borrow"),
                           (brief["reference_usage"][0], "limit"),
                           (brief["factual_exclusions"], 0)]
                remaining = total - len(fields)
                for parent, key in fields:
                    extra = min(99, remaining)
                    parent[key] = "字" * (1 + extra)
                    remaining -= extra
                self.assertEqual(remaining, 0)
                safe = self.validate(plan)["design_brief"]
                for key, value in brief.items():
                    self.assertEqual(safe[key], value)

    def test_maximum_complete_audit_structure_is_bounded_without_truncation(self):
        plan = photo_plan(self.refs[0])
        plan["photos"] = [{**plan["photos"][0], "source_ref": self.refs[index],
                           "bbox": [0, .2 + index * .26, 1, .46 + index * .26]}
                          for index in range(3)]
        evidence = ["xhs-community-truth-and-title", "xhs-product-note-20260211", "xhs-food-202402-p13"]
        brief = {key: "字" * 100 for key in ("industry", "subtype", "content_intent",
                 "reader_question", "visual_strategy")}
        brief.update(source_reasons=[{"source_ref": ref, "reason": "字" * 100} for ref in self.refs[:3]],
                     evidence_ids=evidence,
                     reference_usage=[{"evidence_id": ref, "borrow": "字" * 100, "limit": "字" * 100}
                                      for ref in evidence],
                     factual_exclusions=["字" * 100 for _ in range(4)])
        plan["design_brief"] = brief
        safe = self.validate(plan, {**self.context, "domain": "美食"})["design_brief"]
        for key, value in brief.items():
            self.assertEqual(safe[key], value)

    def test_brief_individual_field_and_list_bounds_still_reject(self):
        changes = (
            ("visual_strategy", "字" * 101),
            ("visual_strategy", "说明\x00"),
            ("factual_exclusions", ["边界"] * 5),
            ("factual_exclusions", ["字" * 101]),
        )
        for field, value in changes:
            with self.subTest(field=field, value=value):
                plan = photo_plan(self.refs[0])
                plan["design_brief"][field] = value
                with self.assertRaisesRegex(design.CoverDesignError, "COVER_DESIGN_BRIEF_INVALID"):
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
