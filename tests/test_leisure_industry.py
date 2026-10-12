"""Offline industry contracts. Media/model replies are synthetic fixtures, not live acceptance."""
import asyncio
import base64
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
# db skips its legacy import-time SQLite initialization in this mode. No
# connection to this sentinel is made; each test then selects isolated SQLite.
with mock.patch.dict(os.environ, {"DATABASE_URL": "postgresql:///offline-import-disabled"}):
    import api
    import fact_enrichment as facts
    import hot_keywords
    import memory
    import prompt_composer as prompts
    import trends_contract
    import v04_composite_features as features
    import v04_domain_policy as policy

DOMAIN = "休闲娱乐体验"
CATEGORIES = ("洗浴", "汤泉", "水疗", "按摩")
OLD_DOMAINS = ("美食", "旅行", "穿搭", "美妆", "家居", "健身", "母婴")


class LeisureIndustryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        from contextlib import ExitStack
        self.stack = ExitStack()
        self.stack.enter_context(mock.patch.object(api._db, "_DB_PATH", Path(self.temp.name) / "primary.db"))
        self.stack.enter_context(mock.patch.object(hot_keywords, "DB_PATH", Path(self.temp.name) / "keywords.db"))
        self.stack.enter_context(mock.patch.dict(os.environ, {"DATABASE_URL": "", "NOTEAI_FACT_SEARCH": "0", "NOTEAI_PUBLIC_PRODUCT": "0"}))
        self.stack.enter_context(mock.patch("httpx.Client.send", side_effect=AssertionError("offline test cannot use network")))
        self.stack.enter_context(mock.patch("httpx.AsyncClient.send", side_effect=AssertionError("offline test cannot use network")))

    def tearDown(self):
        self.stack.close()
        self.temp.cleanup()

    def test_classification_and_shared_prompt_layers_cover_every_category(self):
        for category in (*CATEGORIES, "SPA", "足浴", DOMAIN):
            with self.subTest(category=category):
                self.assertEqual(policy.canonical_product_domain(category), DOMAIN)
                self.assertEqual(prompts.canonicalize_domain(category), DOMAIN)
                self.assertEqual(api._normalize_screenshot_domain(category, "周末休闲项目"), DOMAIN)
                for key in ("agent_content_system", "agent_visual_system", "agent_growth_system", "agent_user_system",
                            "gent_content_system", "gent_arbitrate_system", "chat_system"):
                    preview = prompts.industry_preview(key, category, "本次{domain}基础模板")
                    self.assertEqual(preview.domain, DOMAIN)
                    self.assertIn(DOMAIN, preview.text)
                    self.assertIn("医疗", preview.text)
        self.assertEqual(set(prompts.SUPPORTED_DOMAINS), {*OLD_DOMAINS, DOMAIN})
        for domain in OLD_DOMAINS:
            self.assertEqual(prompts.canonicalize_domain(domain), domain)
            self.assertIsNot(prompts._get_dk(domain), prompts._DEFAULT_DOMAIN_KNOWLEDGE)
            self.assertIn(domain, prompts._GEN_CHECKLISTS)
        admin = (ROOT / "model" / "admin.html").read_text()
        self.assertIn('<option value="休闲娱乐体验">休闲娱乐体验</option>', admin)

    def test_clinical_material_is_not_classified_from_massage_keyword(self):
        for text in ("医院康复科给患者按摩", "门诊预约，中医科诊疗", "临床病历中的按摩"):
            self.assertEqual(api._normalize_screenshot_domain("按摩", text), "")
        self.assertEqual(api._normalize_screenshot_domain("汤泉", "这不是医院，只写真实休闲体验，不能治疗疾病"), DOMAIN)
        self.assertEqual(api._normalize_screenshot_domain("未知", "有按摩两个字"), "")

    def test_real_preferences_can_use_the_new_domain_without_cross_domain_scope(self):
        for domain in (DOMAIN, "按摩"):
            found = memory.extract_explicit_preferences("请记住这个行业以后少用表情", domain=domain)
            self.assertTrue(found)
            self.assertEqual(found[0]["domain"], DOMAIN)
        found = memory.extract_explicit_preferences("请记住以后美食笔记少用表情", domain=DOMAIN)
        self.assertEqual(found[0]["domain"], "美食")

    def test_to_store_decision_reuses_amap_and_respects_user_visibility(self):
        for category in CATEGORIES:
            decision = api._fact_source_decision(category, "", "", "决策转化型", "show", "清风" + category, "auto")
            self.assertEqual((decision["enabled"], decision["provider"]), (True, "amap"))
            self.assertEqual(decision["reason"], "leisure_decision_or_visible_merchant")
            hidden = api._fact_source_decision(category, "", "", "决策转化型", "hide", "清风" + category, "auto")
            self.assertFalse(hidden["enabled"])
            missing = api._fact_source_decision(category, "", "周末想放松", "决策转化型", "show", "", "auto")
            self.assertTrue(missing["needs_user_supplement"])
        for domain, provider, name in (("美食", "amap", "清风餐厅"), ("旅行", "meituan_travel", "清风酒店")):
            decision = api._fact_source_decision(domain, "", "", "决策转化型", "show", name, "auto")
            self.assertTrue(decision["enabled"])
            self.assertEqual(decision["provider"], provider)

    def test_query_and_exact_merchant_selection_support_leisure_names(self):
        for merchant in ("清风洗浴中心", "清风汤泉", "清风水疗中心", "清风按摩馆"):
            found, name = api._merchant_entity_signal(DOMAIN, merchant, "", "")
            self.assertTrue(found)
            self.assertEqual(name, merchant)
            query = facts.build_fact_query(DOMAIN, merchant, "广州")
            self.assertIn(merchant, query)
            self.assertIn("预约", query)
            self.assertTrue(facts._amap_poi_matches_keyword({"name": merchant}, merchant))
            self.assertFalse(facts._amap_poi_matches_keyword({"name": "另一家汤泉"}, merchant))
        local = {"domain": "按摩", "name": "清风按摩馆", "facts": {"address": "测试街8号"}}
        canonical = {**local, "domain": DOMAIN}
        self.assertEqual(facts._record_match_score(local, "清风按摩馆", DOMAIN),
                         facts._record_match_score(canonical, "清风按摩馆", DOMAIN))
        self.assertEqual(facts._record_match_score(local, "另一家按摩馆", DOMAIN), 0)

    def test_structured_facts_and_medical_claims_are_blocking(self):
        src = "项目：按摩60分钟。价格：128元。水温：40度。套餐不含按摩，按摩需另外收费。"
        self.assertFalse(api._structured_fact_boundary_issues("按摩60分钟，价格128元，水温40℃。", src, DOMAIN))
        for text in ("按摩90分钟", "水温42度", "价格88元", "套餐包含按摩", "没有依据但排毒祛湿", "缓解颈椎病",
                     "按摩无痛治疗失眠", "无副作用排毒祛湿", "没有副作用排毒祛湿", "不能错过的治疗失眠汤泉",
                     "不是不能治疗失眠", "不是没有疗效", "不可能没有疗效", "没有没有疗效",
                     "不承诺排毒祛湿，但可以治疗颈椎病"):
            with self.subTest(text=text):
                issues = api._delivery_integrity_issues(text, src, DOMAIN)
                self.assertTrue(issues, text)
                self.assertTrue(api._has_blocking_quality_issues(95, issues, DOMAIN))
        for text in ("这里只谈休闲放松，没有医疗功效。", "不能治疗失眠，不提供疾病康复。", "不是医院，不承诺排毒祛湿。",
                     "无疗效，无法治疗失眠。", "本项目不用于治疗疾病。", "套餐是否包含按摩？",
                     "按摩项目时长是否60分钟？", "水温是否40度？"):
            self.assertFalse(api._delivery_integrity_issues(text, "", DOMAIN), text)
        issues = api._delivery_integrity_issues("周末休闲体验", "", DOMAIN, title_variants=["按摩治疗失眠"])
        self.assertTrue(any("备选标题1" in issue for issue in issues))

    def test_duration_is_bound_to_each_project_and_preserves_units(self):
        for project in ("洗浴", "汤泉", "SPA", "按摩", "足浴"):
            with self.subTest(project=project):
                source = f"{project}45分钟。"
                self.assertFalse(api._delivery_integrity_issues(source, source, DOMAIN))
                issues = api._delivery_integrity_issues(f"{project}90分钟。", source, DOMAIN)
                self.assertTrue(any("项目时长" in issue for issue in issues))
                self.assertTrue(api._has_blocking_quality_issues(95, issues, DOMAIN))
        for output, source in (
            ("按摩1小时。", "按摩60分钟。"),
            ("水疗45分钟。", "SPA45分钟。"),
            ("足浴45分钟。", "足疗45分钟。"),
            ("60分钟按摩和45分钟足浴。", "按摩60分钟、足浴45分钟。"),
            ("按摩60分钟。", "服务项目：按摩\n时长：60分钟。"),
        ):
            with self.subTest(output=output):
                self.assertFalse(api._delivery_integrity_issues(output, source, DOMAIN))
        for output, source in (
            ("按摩90分钟。", "按摩60分钟，水疗90分钟。"),
            ("足浴90分钟。", "足浴45分钟。"),
            ("按摩60分钟、足浴60分钟。", "按摩60分钟、足浴45分钟。"),
            ("按摩60分钟。", "项目时长60分钟，具体项目未知。"),
            ("足浴45分钟。", "足浴是否45分钟需确认。"),
        ):
            with self.subTest(output=output):
                self.assertTrue(any("项目时长" in issue for issue in api._delivery_integrity_issues(output, source, DOMAIN)))
        self.assertFalse(api._delivery_integrity_issues("按摩是否90分钟，足浴时长需确认。", "", DOMAIN))

    def test_entitlements_bind_package_scope_service_polarity_and_condition(self):
        for output, source in (
            ("套餐A包含按摩和足浴，不含餐饮。", "套餐A包含按摩和足浴，不含餐饮。"),
            ("套餐A含水疗。", "A套餐包含SPA。"),
            ("套餐A不含按摩。", "套餐A不含按摩。"),
            ("套餐A赠送足浴。", "套餐A赠送足疗。"),
        ):
            with self.subTest(output=output):
                self.assertFalse(api._delivery_integrity_issues(output, source, DOMAIN))
        for output, source in (
            ("套餐B包含按摩。", "套餐A包含按摩，套餐B不含按摩。"),
            ("套餐A包含足浴。", "套餐A不含足浴。"),
            ("套餐A不含按摩。", "套餐A包含按摩。"),
            ("套餐B赠送足浴。", "套餐A赠送足浴。"),
            ("SPA套餐含按摩。", "洗浴套餐含按摩。"),
            ("套餐A免费提供足浴。", "套餐A包含足浴。"),
            ("套餐A含足浴。", "套餐是否含足浴需确认。"),
        ):
            with self.subTest(output=output):
                self.assertTrue(any("套餐服务权益" in issue for issue in api._delivery_integrity_issues(output, source, DOMAIN)))
        self.assertFalse(api._delivery_integrity_issues("套餐A含不含按摩？套餐B是否赠送足浴需确认。", "", DOMAIN))

    def test_lookup_failure_and_success_keep_facts_truthful(self):
        failed = facts.format_fact_context({"error": "provider_request_failed", "facts": {}, "provider": "amap"})
        self.assertIn("事实检索未完成", failed)
        self.assertIn("不得编造", failed)
        real = {"provider": "amap", "facts": {"address": "测试街8号", "hours": "10:00-22:00"}, "sources": []}
        context = facts.format_fact_context(real)
        self.assertIn("测试街8号", context)
        self.assertIn("10:00-22:00", context)
        self.assertNotIn("128元", context)
        for source in (failed, context):
            brief = api._safe_fact_delivery_brief(DOMAIN, source)
            self.assertIn("不编造", brief)
            self.assertIn("不证明套餐", brief)

    def test_fixed_model_features_and_existing_trends_contract_are_preserved(self):
        self.assertEqual(len(features.COMPOSITE_FEATURE_COLS), 124)
        self.assertFalse(any(name.startswith("domain_leisure") for name in features.COMPOSITE_FEATURE_COLS))
        result = features.build_composite_features(title="周末汤泉怎么选", body="汤泉泡池与休息区，先更衣再休息。预约和套餐包含项目需确认，适合周末休闲。", domain=DOMAIN)
        self.assertEqual(list(result), features.COMPOSITE_FEATURE_COLS)
        self.assertGreater(result["commercial_domain_slot_coverage"], 0)
        self.assertEqual(trends_contract.REQUIRED_DOMAINS, ("美食", "旅行", "穿搭", "美妆", "家居", "健身"))

    def test_missing_trend_and_benchmark_are_unknown_not_invented(self):
        status = {"has_fresh_domain_data": False, "domain_keyword_count": 0, "domain_source_breakdown": {}}
        with mock.patch.object(hot_keywords, "_load_domain_stats"), mock.patch.object(hot_keywords, "_DOMAIN_STATS", {}), \
             mock.patch.object(hot_keywords, "ensure_fresh_domain_keywords", return_value={"ok": False, "status": status}):
            stats = hot_keywords.get_domain_stats(DOMAIN)
            timing = hot_keywords.compute_market_timing("休闲体验", "", DOMAIN)
            legacy = hot_keywords.get_domain_stats("不支持的历史行业")
        self.assertEqual(legacy, {"avg_ces": 50.0, "saturation": 0.5})
        self.assertIsNone(stats["avg_ces"])
        self.assertIsNone(stats["saturation"])
        self.assertFalse(timing["benchmark_available"])
        self.assertTrue(timing["data_stale"])
        self.assertEqual(timing["matched_keywords"], [])
        self.assertIsNone(timing["category_avg_ces"])
        self.assertIsNone(timing["category_saturation"])
        public = api.MarketTiming(**timing).model_dump()
        self.assertIsNone(public["category_avg_ces"])
        sanitized = api._sanitize_public_schema_value(public, api._MARKET_TIMING_SCHEMA)
        self.assertFalse(sanitized["benchmark_available"])

    def test_actual_screenshot_handler_normalizes_mocked_categories(self):
        image = io.BytesIO()
        Image.new("RGB", (300, 200), "green").save(image, "PNG")
        encoded = base64.b64encode(image.getvalue()).decode()
        for category in CATEGORIES:
            reply = {"type": "A", "title": "周末" + category, "body": "实际截图文字", "tags": ["#休闲体验"], "domain": category}
            with mock.patch.object(api._billing, "check_and_deduct", return_value={"source": "synthetic"}), \
                 mock.patch.object(api._ark_media, "chat", return_value=json.dumps(reply)) as model:
                result = asyncio.run(api.extract_screenshot(api.ScreenshotExtractInput(image_base64=encoded), user={"id": "offline"}, request_id=None))
            self.assertEqual(result["domain"], DOMAIN)
            self.assertEqual(result["title"], reply["title"])
            self.assertEqual(result["text_body"], reply["body"])
            self.assertEqual(result["tags"], "#休闲体验")
            self.assertIn("医院", model.call_args.args[0])
            self.assertIn(DOMAIN, model.call_args.args[0])

    def test_single_and_nine_screenshot_merge_preserve_title_copy_and_topics(self):
        for count in (1, 9):
            rows = [{"type": "A", "title": "周末汤泉", "text_body": f"图{i + 1}真实区域", "tags": "#汤泉体验", "domain": "汤泉"} for i in range(count)]
            reply = {"title": "周末汤泉", "body": "\n".join(row["text_body"] for row in rows), "tags": "#汤泉体验 #休闲体验", "domain": "汤泉"}
            with mock.patch.object(api._mr, "call", new=mock.AsyncMock(return_value=json.dumps(reply))) as model:
                result = asyncio.run(api._validate_ocr_impl(api.ValidateOcrInput(ocr_results=rows), {"id": "offline"}))
            self.assertEqual(result["domain"], DOMAIN)
            self.assertEqual(result["title"], "周末汤泉")
            for i in range(count):
                self.assertIn(f"图{i + 1}真实区域", result["text_body"])
            self.assertIn("#汤泉体验", result["tags"])
            if count == 9:
                self.assertIn(DOMAIN, model.call_args.args[1])
                self.assertIn("图9真实区域", model.call_args.args[2])
            else:
                model.assert_not_called()

    def test_photo_only_clinical_observations_do_not_become_leisure(self):
        image = io.BytesIO()
        Image.new("RGB", (300, 200), "green").save(image, "PNG")
        encoded = base64.b64encode(image.getvalue()).decode()
        for observation, expected in (("医院康复科患者按摩", ""), ("汤泉泡池与休息区", DOMAIN)):
            reply = {"type": "B", "title": "", "body": "", "tags": [], "domain": "按摩", "cover_desc": observation}
            with mock.patch.object(api._billing, "check_and_deduct", return_value={"source": "synthetic"}), \
                 mock.patch.object(api._ark_media, "chat", return_value=json.dumps(reply)):
                extracted = asyncio.run(api.extract_screenshot(api.ScreenshotExtractInput(image_base64=encoded), user={"id": "offline"}, request_id=None))
            self.assertEqual(extracted["domain"], expected)
            for count in (1, 9):
                merged = asyncio.run(api._validate_ocr_impl(api.ValidateOcrInput(ocr_results=[reply] * count), {"id": "offline"}))
                self.assertEqual(merged["domain"], expected)

    def test_single_and_nine_image_generation_reach_real_prompt_and_output_parsers_with_mock_models(self):
        title = "周末汤泉休闲体验"
        body = "泡池和休息区是本次可见空间。先确认套餐包含项目，再安排周末休闲。\n#汤泉体验 #休闲体验 #周末休闲 #泡池 #休息区"
        raw = f"<title>{title}</title><body>{body}</body><variants>汤泉到店怎么选\n汤泉空间与流程\n汤泉套餐确认清单</variants><rationale>真实素材取舍</rationale>"
        for count in (1, 9):
            captures = []
            async def fake_call(task, system, user, **kwargs):
                captures.append((kwargs.get("trace_step"), system, user))
                return raw if task == "arbitrate" else f"<draft_title>{title}</draft_title><draft_body>{body}</draft_body>"
            async def shape(_title, value, *_args, **_kwargs):
                return value
            observations = "\n".join(f"图片{i + 1}：真实休闲区域{i + 1}" for i in range(count))
            dk = api._get_dk(DOMAIN)
            with mock.patch.object(api, "_runtime_prompt", return_value="测试基础模板{domain}"), \
                 mock.patch.object(api._mr, "call", side_effect=fake_call), \
                 mock.patch.object(api, "_shape_body_for_delivery", side_effect=shape):
                async def run():
                    content = await api._gent_content(DOMAIN, "项目：汤泉；空间：泡池与休息区", dk, observations)
                    return await api._gent_arbitrate(DOMAIN, [content, {"role": "视觉专家", "_image_desc": observations}], None, [], fact_context="仅有泡池与休息区，无其他门店事实")
                result = asyncio.run(run())
            self.assertEqual(result["title"], title)
            self.assertEqual(result["body"], body)
            self.assertEqual(len(result["variants"]), 3)
            self.assertIn("#汤泉体验", result["body"])
            for step, system, user in captures:
                self.assertIn(DOMAIN, system)
                self.assertIn("不编造", system)
                self.assertIn(f"真实休闲区域{count}", user)
            self.assertFalse(api._delivery_integrity_issues(title + "\n" + body, "项目：汤泉；空间：泡池与休息区", DOMAIN))

    def test_stream_generation_observes_every_uploaded_image_before_arbitration(self):
        title = "周末汤泉休闲体验"
        body = "素材中的泡池与休息区。\n#汤泉体验 #休闲体验 #周末休闲 #泡池 #休息区"
        raw = f"<title>{title}</title><body>{body}</body><variants>汤泉到店怎么选\n汤泉空间与流程\n汤泉套餐确认清单</variants><rationale>素材取舍</rationale>"
        for count in (1, 9):
            vision_inputs, calls, stream_calls = [], [], []
            def vision(image, *_args):
                vision_inputs.append(image)
                return f"{image}的实际休闲区域观察"
            async def model(task, system, user, **kwargs):
                calls.append((kwargs.get('trace_step'), system, user))
                return f"<draft_title>{title}</draft_title><draft_body>{body}</draft_body>"
            async def stream(task, system, user, **kwargs):
                stream_calls.append((system, user))
                yield "content", raw
            async def shape(_title, value, *_args, **_kwargs):
                return value
            with mock.patch.object(api, "_runtime_prompt", return_value="测试基础模板{domain}"), \
                 mock.patch.object(api, "_kimi_vision_understand", side_effect=vision), \
                 mock.patch.object(api._mr, "call", side_effect=model), \
                 mock.patch.object(api._mr, "stream", side_effect=stream), \
                 mock.patch.object(api, "_shape_body_for_delivery", side_effect=shape), \
                 mock.patch.object(api, "_generation_candidate_count", return_value=1), \
                 mock.patch.object(api, "_predict", side_effect=RuntimeError("skip artifact scoring in this prompt test")), \
                 mock.patch.object(api._clarification, "pause"), \
                 mock.patch.object(api.asyncio, "sleep", new=mock.AsyncMock()):
                async def run():
                    generator = api._generate_pipeline_stream(DOMAIN, "本次素材是汤泉泡池与休息区，无更多事实", None,
                        None, {}, None, "2026101212", cover_images=[f"图{i + 1}" for i in range(count)])
                    events = []
                    try:
                        async for event in generator:
                            events.append(event)
                            if event['type'] == 'p3_done':
                                break
                    finally:
                        await generator.aclose()
                    return events
                events = asyncio.run(run())
            self.assertEqual(set(vision_inputs), {f"图{i + 1}" for i in range(count)})
            self.assertEqual(events[-1]["title"], title)
            self.assertEqual(len(stream_calls), 1)
            self.assertIn(f"图{count}的实际休闲区域观察", stream_calls[0][1])
            self.assertIn("医疗功效", stream_calls[0][0])
            content_call = next(call for call in calls if call[0] == 'generation_content')
            self.assertIn(f"图{count}的实际休闲区域观察", content_call[2])


if __name__ == "__main__":
    unittest.main()
