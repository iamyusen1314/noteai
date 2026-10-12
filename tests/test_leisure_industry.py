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
        for project in ("洗浴", "汗蒸", "桑拿", "干蒸", "湿蒸", "泳池", "游泳", "汤泉", "SPA", "推拿", "按摩", "沐足", "足浴"):
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
            ("湿蒸30分钟。", "干蒸30分钟，湿蒸15分钟。"),
            ("足浴45分钟。", "沐足45分钟。"),
            ("按摩45分钟。", "推拿45分钟。"),
        ):
            with self.subTest(output=output):
                self.assertTrue(any("项目时长" in issue for issue in api._delivery_integrity_issues(output, source, DOMAIN)))
        self.assertFalse(api._delivery_integrity_issues("按摩是否90分钟，足浴时长需确认。", "", DOMAIN))
        combined = "洗浴中心24小时可进，按摩45分钟需另收费，含自助餐但不含SPA。"
        self.assertEqual(api._leisure_duration_claims(combined), {("按摩", "2.7E+3")})
        self.assertFalse(api._delivery_integrity_issues(combined, combined, DOMAIN))
        for output in ("洗浴24小时。", "按摩24小时。", "桑拿45分钟。"):
            self.assertTrue(any("项目时长" in issue for issue in api._delivery_integrity_issues(output, combined, DOMAIN)))
        self.assertIn("按摩45分钟需另收费", api._safe_fact_delivery_brief(DOMAIN, combined))

    def test_actual_spa_labels_are_not_clinical_but_symptom_recommendations_are_blocked(self):
        label = "SPA理疗室，工作人员站在理疗床边，展示颂钵理疗；项目称呼为理疗师，不据此认定职业资质。"
        self.assertEqual(api._normalize_screenshot_domain(DOMAIN, label), DOMAIN)
        self.assertFalse(api._delivery_integrity_issues(label, label, DOMAIN))
        for text in (
            "整套流程适合长期压力积累、睡眠质量不稳定、颈肩容易僵紧的人。",
            "颂钵项目适合睡眠质量不稳定的人。", "SPA针对颈肩僵紧人群。",
            "按摩推荐给肩颈经常疼痛的人。", "汤泉可以改善睡眠质量。", "足浴缓解颈肩僵紧。",
            "不是不适合睡眠质量不稳定的人。", "不是不能改善睡眠质量。",
            "不承诺改善睡眠质量，但针对颈肩容易僵紧的人。",
        ):
            with self.subTest(text=text):
                # Even a vendor/creator statement is no basis for endorsing a
                # symptom-specific recommendation in the leisure category.
                for source in ("只记录SPA空间和金属钵敲击动作。", text):
                    issues = api._delivery_integrity_issues(text, source, DOMAIN)
                    self.assertTrue(any("医疗功效" in issue for issue in issues))
                    self.assertTrue(api._has_blocking_quality_issues(95, issues, DOMAIN))
        for text in (
            "适合希望暂时放下压力、安排周末休闲的人。", "我觉得休息区很安静，想放空一会儿。",
            "颂钵理疗、理疗师、理疗床是素材中的项目称呼，不证明医疗资质。",
            "不适合睡眠质量不稳定的人。", "本项目不用于改善睡眠质量。",
            "无法缓解颈肩僵紧。", "该项目是否适合睡眠质量不稳定的人？",
            "这套流程是否可以改善睡眠质量？", "足浴适合颈肩容易僵紧的人吗？",
            "是否适合睡眠质量不稳定人群需确认。", "我最近睡眠质量不稳定，这次仅记录空间环境。",
        ):
            with self.subTest(text=text):
                self.assertFalse(api._delivery_integrity_issues(text, text, DOMAIN))

    def test_entitlements_bind_package_scope_service_polarity_and_condition(self):
        for output, source in (
            ("套餐A包含按摩和足浴，不含餐饮。", "套餐A包含按摩和足浴，不含餐饮。"),
            ("套餐A含水疗。", "A套餐包含SPA。"),
            ("套餐A不含按摩。", "套餐A不含按摩。"),
            ("套餐A赠送足浴。", "套餐A赠送足疗。"),
            ("套餐A包含汗蒸，不含桑拿。", "套餐A包含汗蒸，不含桑拿。"),
            ("套餐A含干蒸，不含湿蒸。", "套餐A含干蒸，不含湿蒸。"),
            ("套餐A含早餐、午餐，不含晚餐和宵夜。", "套餐A含早餐、午餐，不含晚餐和宵夜。"),
            ("套餐A含泳池，不含包房、麻将和电竞。", "套餐A含泳池，不含包房、麻将和电竞。"),
            ("套餐A含PS和Switch、软饮，不含特调饮料和酒水。", "套餐A含ps和switch、软饮，不含特调饮料和酒水。"),
            ("本次素材包含饮品摆放和泳池画面。", "项目/空间：饮品台与泳池画面。"),
            ("照片里的套餐A含泳池。", "照片里的套餐A含泳池。"),
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
            ("套餐A包含桑拿。", "套餐A包含汗蒸，不含桑拿。"),
            ("套餐A包含SPA。", "套餐A含自助餐但不含SPA。"),
            ("包含按摩。", "洗浴中心24小时可进，按摩45分钟需另收费，含自助餐但不含SPA。"),
            ("套餐A含湿蒸。", "套餐A含干蒸，不含湿蒸。"),
            ("套餐A含午餐。", "套餐A含早餐。"),
            ("套餐A含晚餐。", "套餐A含午餐。"),
            ("套餐A含宵夜。", "套餐A含晚餐。"),
            ("套餐A含自助餐晚餐。", "套餐A含自助餐午餐。"),
            ("套餐A含泳池。", "洗浴中心可见泳池，套餐A权益待确认。"),
            ("套餐A含包房。", "套餐A不含包房。"),
            ("套餐A含麻将和电竞。", "套餐A不含麻将和电竞，套餐B含麻将和电竞。"),
            ("套餐A免费提供软饮。", "套餐A含软饮。"),
            ("套餐A含特调饮料和酒水。", "套餐A含软饮，不含特调饮料和酒水。"),
            ("套餐A含饮品。", "套餐A含软饮。"),
            ("照片里的套餐A含泳池。", "照片显示泳池。"),
            ("套餐含SPA。", "素材包含SPA画面。"),
        ):
            with self.subTest(output=output):
                self.assertTrue(any("套餐服务权益" in issue for issue in api._delivery_integrity_issues(output, source, DOMAIN)))
        self.assertFalse(api._delivery_integrity_issues("套餐A含不含按摩？套餐B是否赠送足浴需确认。", "", DOMAIN))
        self.assertFalse(api._delivery_integrity_issues("套餐A含不含泳池、包房或早餐？麻将、电竞和酒水需确认。", "", DOMAIN))

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
            self.assertIn("不证明未返回的服务权益", brief)

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

    def test_exact_scene_labels_are_compatible_without_keyword_reclassification(self):
        for label in ("洗浴中心", "洗浴汗蒸", "汗蒸", "桑拿", "按摩足疗SPA", "SPA体验", "KTV", "ktv", "卡拉OK", "卡拉OK厅", "酒吧", "清吧", "音乐酒吧"):
            with self.subTest(label=label):
                self.assertEqual(policy.canonical_product_domain(label), DOMAIN)
                self.assertEqual(prompts.canonicalize_domain(label), DOMAIN)
                self.assertEqual(api._normalize_screenshot_domain(label, "本次真实休闲活动"), DOMAIN)
        for domain, text in (("美食", "餐厅饮品与自助餐"), ("美妆", "本地生活里的护肤与底妆体验"), ("旅行", "酒店旅行与泳池"),
                             ("健身", "训练计划与运动"), ("未知", "正文提到KTV和按摩")):
            self.assertEqual(api._normalize_screenshot_domain(domain, text), domain if domain != "未知" else "")
        self.assertEqual(policy.canonical_product_domain("本地生活体验"), "本地生活体验")
        with self.assertRaises(ValueError):
            prompts.canonicalize_domain("本地生活体验")
        for text in ("餐厅主菜与饮品", "护肤与底妆体验", "普通本地生活记录"):
            self.assertEqual(api._normalize_screenshot_domain("本地生活体验", text), "")
        for label in ("Livehouse", "LiveHouse", "livehouse", "桌游", "密室", "观演", "手作体验", "运动休闲"):
            self.assertEqual(policy.canonical_product_domain(label), label)
            with self.assertRaises(ValueError):
                prompts.canonicalize_domain(label)
            self.assertEqual(api._normalize_screenshot_domain(label, "当前独立活动"), "")

    def test_shared_general_contract_does_not_require_unprovided_subscene_slots(self):
        for key in ("agent_content_system", "agent_visual_system", "agent_growth_system", "agent_user_system",
                    "gent_content_system", "gent_visual_system", "gent_growth_system", "gent_user_system",
                    "gent_arbitrate_system", "agent_arbitrate_system", "chat_system"):
            preview = prompts.industry_preview(key, DOMAIN, "通用基础模板{domain}").text
            self.assertIn("公共槽位", preview)
            self.assertIn("行业名不证明任何子场景", preview)
            self.assertIn("综合场所", preview)
            self.assertIn("自助餐/海鲜及室内休闲娱乐游玩可以共存", preview)
            self.assertIn("不假定每家都有全部项目", preview)
            self.assertIn("内部候选配套认知（不是任何商家的事实或必须清单）", preview)
            self.assertIn("不按设施数量或清单齐全抬分", preview)
            self.assertIn("干蒸不等于湿蒸", preview)
            self.assertIn("早餐不推出午餐/晚餐/宵夜", preview)
            self.assertIn("场景不明时写一般真实体验", preview)
            self.assertNotIn("真实洗浴/汤泉/水疗/按摩项目或空间 +", preview)
            self.assertNotIn("不套菜品", preview)
            self.assertNotRegex(preview, "观演文化|运动休闲|手作体验|密室|Livehouse|互动游艺")
        for material, expected in (("包房唱歌与话筒画面", "包房唱歌"), ("饮品与音乐舞台", "饮品"),
                                   ("洗浴中心室内娱乐游玩空间", "室内娱乐"), ("汤泉泡池和自助餐", "自助餐")):
            bits = api._domain_generation_fact_bits(DOMAIN, material)
            self.assertTrue(any(expected in bit for bit in bits))
        self.assertEqual(api._domain_generation_fact_bits(DOMAIN, "尚未说明具体项目"), ["项目/空间=尚未说明具体项目"])
        fallback = api._plan_title_fallback_options(DOMAIN, "避坑取舍型", "休闲活动")
        self.assertFalse(any("按摩" in title or "套餐" in title for title in fallback))
        actual_material = "项目/空间：庭院、水池、自助餐与饮料柜台；价格、时段和服务权益未知。"
        summarized = "；".join(api._domain_generation_fact_bits(DOMAIN, actual_material))
        self.assertIn("庭院、水池、自助餐与饮料柜台", summarized)
        self.assertNotRegex(summarized, "麻将|电竞|干蒸|湿蒸|泳池|包房|SPA|免费")
        self.assertEqual(api._normalize_screenshot_domain(DOMAIN, "洗浴中心内可见泳池，游泳仅作为已有休闲项目，不谈健康功效"), DOMAIN)
        self.assertTrue(any("医疗功效" in issue for issue in api._delivery_integrity_issues("游泳缓解疾病。", "洗浴中心含泳池。", DOMAIN)))

    def test_representative_general_scenes_preserve_mock_single_and_nine_generation_outputs(self):
        scenes = (
            ("洗浴综合项目", "项目/空间：庭院、水池、自助餐与饮料柜台；具体项目条件与时段权益未知", "本次相关区域是庭院、水池、自助餐与饮料柜台，具体权益待确认。", "#洗浴体验 #自助餐"),
            ("按摩足疗SPA", "项目：按摩、足疗与SPA；空间：休闲按摩区与水疗区域；具体流程未知", "休闲按摩、足疗与SPA是本次已提供项目，具体流程待确认。", "#按摩体验 #足疗SPA"),
            ("包房唱歌", "项目：KTV包房唱歌；空间：包房与话筒", "本次素材只有包房、话筒与唱歌活动。", "#包房唱歌 #KTV"),
            ("饮品音乐", "项目：酒吧饮品与现场音乐；空间：饮品台与舞台", "本次素材包含饮品摆放与音乐舞台。", "#饮品音乐 #酒吧"),
            ("休闲空间", "空间：普通房间与座椅；具体项目未知", "目前只看到房间与座椅，具体参与项目待确认。", "#空间记录 #休闲体验"),
        )
        for scene, material, narrative, tags in scenes:
            for count in (1, 9):
                with self.subTest(scene=scene, count=count):
                    captures = []
                    body = narrative + "\n" + tags + " #周末记录 #场景记录 #真实素材"
                    raw = f"<title>{scene}真实体验</title><body>{body}</body><variants>{scene}空间记录\n{scene}参与前确认\n{scene}场景取舍</variants><rationale>实际素材</rationale>"
                    async def fake_call(task, system, user, **kwargs):
                        captures.append((kwargs.get('trace_step'), system, user))
                        return raw if task == 'arbitrate' else f"<draft_title>{scene}真实体验</draft_title><draft_body>{body}</draft_body>"
                    async def shape(_title, value, *_args, **_kwargs):
                        return value
                    observations = "\n".join(f"图片{i + 1}：{narrative}" for i in range(count))
                    with mock.patch.object(api, '_runtime_prompt', return_value='离线基础模板{domain}'), \
                         mock.patch.object(api._mr, 'call', side_effect=fake_call), \
                         mock.patch.object(api, '_shape_body_for_delivery', side_effect=shape):
                        async def run():
                            content = await api._gent_content(DOMAIN, material, api._get_dk(DOMAIN), observations)
                            return await api._gent_arbitrate(DOMAIN, [content, {'role': '视觉专家', '_image_desc': observations}], None, [], fact_context=material)
                        result = asyncio.run(run())
                    self.assertEqual(result['title'], scene + '真实体验')
                    self.assertEqual(result['body'], body)
                    self.assertIn(tags, result['body'])
                    self.assertEqual(len(result['variants']), 3)
                    self.assertFalse(api._delivery_integrity_issues(result['title'] + '\n' + result['body'], material, DOMAIN))
                    for step, system, user in captures:
                        self.assertIn('行业名不证明任何子场景', system)
                        self.assertIn(f'图片{count}：', user)
                    if scene == '洗浴综合项目':
                        self.assertIn('自助餐', result['body'])
                        self.assertIn('饮料柜台', result['body'])
                        self.assertNotRegex(result['body'], '麻将|电竞|干蒸|湿蒸|泳池|包房|SPA|免费')
                    elif scene == '按摩足疗SPA':
                        self.assertIn('足疗', result['body'])
                        self.assertNotRegex(result['title'] + result['body'], '泡汤|泡池|汤泉|唱歌|酒水')
                    else:
                        self.assertNotRegex(result['title'] + result['body'], '泡汤|泡池|按摩|技师|汤泉')

    def test_media_understanding_receives_general_context_in_the_existing_call(self):
        for helper in (api._kimi_vision_understand, api._kimi_vision_quick):
            with mock.patch.object(api, '_read_image_input', return_value=b'not-real-image-fixture'), \
                 mock.patch.object(api._ark_media, 'image_part', return_value={'offline': True}), \
                 mock.patch.object(api._ark_media, 'chat', return_value='包房与话筒的离线观察') as chat:
                self.assertEqual(helper('offline-fixture', DOMAIN, 'KTV包房唱歌'), '包房与话筒的离线观察')
            self.assertEqual(chat.call_count, 1)
            self.assertIn('行业名不证明任何子场景', chat.call_args.args[0])
            self.assertIn('KTV包房唱歌', chat.call_args.args[0])

    def test_body_shaping_uses_the_same_general_scene_contract(self):
        captures = []
        async def model(_task, system, user, **kwargs):
            captures.append((system, user, kwargs.get('trace_step')))
            return '本次只记录普通房间与座椅，参与项目待确认。\n#空间记录 #休闲体验 #真实素材 #场景记录 #周末记录'
        with mock.patch.object(api._mr, 'call', side_effect=model):
            result = asyncio.run(api._shape_body_for_delivery('休闲空间记录', '房间与座椅。', DOMAIN, '空间：普通房间与座椅；具体项目未知'))
        self.assertEqual(len(captures), 1)
        self.assertEqual(captures[0][2], 'delivery_body_shaping')
        self.assertIn('行业名不证明任何子场景', captures[0][0])
        self.assertIn('场景不明时写一般真实体验', captures[0][0])
        self.assertIn('普通房间与座椅', captures[0][1])
        self.assertNotRegex(result, '汤泉|泡池|按摩|技师')

    def test_general_project_aggregate_slots_preserve_all_model_columns(self):
        fixed_columns = tuple(features.COMPOSITE_FEATURE_COLS)
        for text in ('洗浴汗蒸与室内娱乐游玩', '按摩足疗SPA', '包房唱歌', '饮品与音乐', '普通休闲空间', '汤泉与自助餐'):
            result = features.build_composite_features(title='真实休闲项目', body=text, domain=DOMAIN)
            self.assertEqual(tuple(result), fixed_columns)
            self.assertEqual(len(result), 124)
            self.assertGreater(result['commercial_domain_slot_count'], 0)
        self.assertEqual(tuple(features.COMPOSITE_FEATURE_COLS), fixed_columns)
        self.assertEqual(trends_contract.REQUIRED_DOMAINS, ('美食', '旅行', '穿搭', '美妆', '家居', '健身'))
        one = features.build_composite_features(title='真实休闲项目', body='泳池。', domain=DOMAIN)
        many = features.build_composite_features(title='真实休闲项目', body='泳池、干蒸、湿蒸、早餐、午餐、晚餐、宵夜、麻将、电竞、PS、Switch、包房、软饮、特调饮料。', domain=DOMAIN)
        for key in ('commercial_domain_slot_count', 'commercial_domain_missing_slot_count', 'commercial_domain_slot_coverage'):
            self.assertEqual(one[key], many[key])

    def test_fresh_general_domain_keywords_do_not_push_other_scene_topics(self):
        status = {'has_fresh_domain_data': True, 'domain_keyword_count': 15,
                  'domain_qualified_keyword_count': 15, 'domain_source_breakdown': {'offline-fixture': 15}}
        def row(keyword):
            return {'keyword': keyword, 'vol': 30, 'trend_dir': 0, 'source': 'offline-fixture',
                    'category': DOMAIN, 'quality_score': 80, 'sample_count': 1, 'evidence_level': 'medium'}
        leisure_rows = [row('汤泉体验'), row('包房唱歌'), row('酒吧音乐')]
        food_rows = [row('海鲜砂锅')]
        def keywords(*_args, **kwargs):
            return food_rows if kwargs.get('domain') == '美食' else leisure_rows
        with mock.patch.object(hot_keywords, '_load_domain_stats'), mock.patch.object(hot_keywords, '_DOMAIN_STATS', {}), \
             mock.patch.object(hot_keywords, 'ensure_fresh_domain_keywords', return_value={'ok': True, 'status': status}), \
             mock.patch.object(hot_keywords, 'get_top_keywords', side_effect=keywords), \
             mock.patch.object(hot_keywords, 'compute_trend_peak_distance', return_value=0):
            unknown = hot_keywords.compute_market_timing('普通休闲空间', '房间与座椅', DOMAIN)
            ktv = hot_keywords.compute_market_timing('包房唱歌', '话筒与包房', DOMAIN)
            bar = hot_keywords.compute_market_timing('酒吧音乐', '饮品台与音乐舞台', DOMAIN)
            food = hot_keywords.compute_market_timing('餐厅记录', '开业信息', '美食')
        for result in (unknown, ktv, bar):
            self.assertEqual(result['suggested_keywords'], [])
            self.assertEqual(result['suggested_keyword_evidence'], [])
            self.assertIsNone(result['category_avg_ces'])
            self.assertFalse(result['benchmark_available'])
        self.assertEqual(ktv['matched_keywords'], ['包房唱歌'])
        self.assertEqual(bar['matched_keywords'], ['酒吧音乐'])
        self.assertEqual(food['suggested_keywords'], ['海鲜砂锅'])


if __name__ == "__main__":
    unittest.main()
