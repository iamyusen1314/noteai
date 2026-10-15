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

    def test_bath_opening_and_stay_claims_retain_existing_fact_gate(self):
        # Bar now follows the owner's light policy; comprehensive bath venues
        # retain the existing source checks. This is an offline contract only.
        source = ("门店名：甲汤泉生活\n"
                  "作者仅提供泡池与庭院；开业及停留制度未知。\n"
                  "【联网事实补全】\n对象：甲汤泉生活\n"
                  "人均116元。营业11:00到24:00。")
        claims = ("静安新开汤泉馆", "静安汤泉馆新开", "人均116不催场",
                  "不用赶点也不怕被催走", "这家汤泉的节奏比一般餐厅宽松",
                  "适合想从傍晚坐到深夜、边聊边放松不赶场的成年人局",
                  "想找不催场的汤泉，这家值得先存下来")
        for claim in claims:
            with self.subTest(claim=claim):
                issues = api._delivery_integrity_issues(claim, source, DOMAIN)
                self.assertTrue(any("开业" in issue or "停留" in issue for issue in issues))
                self.assertTrue(api._has_blocking_quality_issues(95, issues, DOMAIN))
        for variant in ("静安汤泉馆新开", "汤泉馆不催场"):
            issues = api._delivery_integrity_issues("泡池与庭院选择参考。", source, DOMAIN, title_variants=[variant])
            self.assertTrue(any(issue.startswith("备选标题1：") for issue in issues))
            self.assertTrue(api._has_blocking_quality_issues(95, issues, DOMAIN))
        public, notices = api._leisure_public_fact_text("本店不催场。节奏轻松。", source)
        self.assertNotIn("不催场", public)
        self.assertIn("节奏轻松", public)
        self.assertTrue(any("停留" in notice for notice in notices))

    def test_leisure_opening_and_stay_keep_source_polarity_and_occasion(self):
        for source, claim in (("作者确认：本店新开。", "刚开业的汤泉馆。"),
                              ("作者确认：本店2026年10月开业。", "开业日期为2026年10月。"),
                              ("作者确认：本店不催场。", "不会被催走。"),
                              ("作者确认：本店不催场。", "不怕催走。"),
                              ("商家确认：本店不限时停留。", "不用赶点。"),
                              ("作者确认：本店到点必须离场。", "本店到点必须离场。"),
                              ("商家确认：可从傍晚坐到深夜。", "从傍晚坐到深夜。")):
            with self.subTest(source=source, claim=claim):
                self.assertFalse(api._delivery_integrity_issues(claim, source, DOMAIN))
        for source, claim in (("本店2025年10月开业。", "开业日期为2026年10月。"),
                              ("本店不是新开的汤泉馆。", "新开汤泉馆。"),
                              ("本店不催场。", "本店不是不催场。"),
                              ("本店不是不催场。", "本店不催场。"),
                              ("本店不限时停留。", "本店不是不限时停留。"),
                              ("本店不是不限时停留。", "本店不限时停留。"),
                              ("我昨天那一桌未被催走。", "本店不催场。"),
                              ("我未被催走。", "本店不催场。"),
                              ("本店不催场。", "本店不限时停留。"),
                              ("营业11:00到24:00。", "从傍晚坐到深夜。")):
            with self.subTest(source=source, claim=claim):
                self.assertTrue(api._delivery_integrity_issues(claim, source, DOMAIN))
        for source in ("开业与是否催场未知。", "写作要求：本店新开且不催场。",
                       "如果本店新开且不催场，可以慢坐。",
                       "门店名：甲店\n【联网事实补全】\n对象：乙店\n乙店新开且不催场。",
                       api._generation_delivery_source_context(DOMAIN, "BBQ与酒水。", "本店新开且不催场。")):
            with self.subTest(source=source):
                self.assertTrue(api._delivery_integrity_issues("新开酒吧。", source, DOMAIN))
                self.assertTrue(api._delivery_integrity_issues("本店不催场。", source, DOMAIN))

    def test_leisure_opening_and_stay_preserve_soft_plans_and_ktv_scope(self):
        source = "仅有空间素材，开业与停留制度未知。"
        for soft in ("节奏轻松，松弛感少见。", "这是一种新选择，也是我的新发现。",
                     "运动酒吧开在静安。", "服务员在这家酒吧新开了一瓶酒。",
                     "第一次走进运动酒吧的读者可以先整理需求。",
                     "工作日下班或周末约人。", "我计划不赶场，只选一家店。",
                     "建议不赶场，只去一家酒吧。", "想慢慢聊，按自己的节奏规划行程。",
                     "建议先确认是否催场、可停多久。", "不应承诺不催场。", "不写新开酒吧。",
                     "画面风格比一般餐厅宽松。", "浴场的空间风格少见，节奏轻松。"):
            with self.subTest(soft=soft):
                self.assertFalse(api._delivery_integrity_issues(soft, source, DOMAIN))
        ktv = "本次主题是KTV，作者整理选歌与聚会参考。"
        self.assertTrue(api._leisure_ktv_light_context(ktv))
        self.assertFalse(api._delivery_integrity_issues("新开KTV，不催场，不限时停留。", ktv, DOMAIN))
        for old in OLD_DOMAINS:
            self.assertFalse(api._structured_fact_boundary_issues("新开门店，不催场。", source, old), old)

    def test_primary_bar_uses_light_experience_policy_and_common_fact_rules(self):
        source = "门店名：Parlay帕雷餐厅运动酒吧(静安店)\n本次主题是运动酒吧，作者整理BBQ与酒水选择参考，不涉及SPA。"
        self.assertFalse(api._leisure_ktv_light_context(source))
        self.assertTrue(api._leisure_ktv_light_context(source, include_bar=True))
        copy = "50人小聚，两个空间各自独立，音乐氛围松弛。活动3小时，排队10分钟。"
        self.assertFalse(api._delivery_integrity_issues(copy, source, DOMAIN))
        self.assertFalse(api._leisure_public_fact_issues(copy, source))
        self.assertFalse(api._leisure_public_fact_text(copy, source)[1])
        for hard in ("人均118元。", "位于康定路。", "营业时间18:00-22:00。", "酒吧治疗失眠。", "我这次去了酒吧。"):
            with self.subTest(hard=hard):
                self.assertTrue(api._delivery_integrity_issues(hard, source, DOMAIN))
        for mixed in ("洗浴中心含酒廊、酒吧和KTV。", "汤泉、按摩SPA及酒吧综合体验。",
                      "本次酒吧或SPA主题尚未确认。", "如果本次是酒吧体验。"):
            self.assertFalse(api._leisure_ktv_light_context(mixed, include_bar=True))
        self.assertFalse(api._leisure_ktv_light_context("主题未知。", "酒吧小聚。", include_bar=True))
        expression = api._quality_expression_brief(DOMAIN, source)
        safety = api._safe_fact_delivery_brief(DOMAIN, source)
        self.assertIn("酒吧轻量", expression)
        self.assertIn("酒吧轻量", safety)
        self.assertNotIn("唱歌聚会", expression + safety)
        self.assertIn("不补写未提供的开业、停留保证", safety)
        self.assertIn("不鼓励过量饮酒", safety)

    def test_selector_rejects_unsupported_opening_and_stay_despite_high_score(self):
        candidates = [{"origin": "unsupported", "title": "新开运动酒吧不催场", "body": "不用赶点也不怕被催走。", "variants": []},
                      {"origin": "sourced", "title": "BBQ与酒水选择参考", "body": "整理BBQ与酒水，按自己的节奏规划行程。", "variants": []}]
        async def fit(title, *_args, **_kwargs):
            return title
        with mock.patch.object(api, "_fit_title_limit", side_effect=fit), \
             mock.patch.object(api, "_score_generated_note", new=mock.AsyncMock(return_value=(95, {}, "优秀"))), \
             mock.patch.object(api, "_generated_quality_issues", side_effect=lambda *_args, **_kwargs: []), \
             mock.patch.object(api, "_v04_publishable_probability", return_value=None), \
             mock.patch.object(api, "get_v04_preference_ranker", return_value=None):
            result = asyncio.run(api._select_best_generation_candidate(candidates, domain=DOMAIN, local_time="20261015",
                source_context="作者整理本店BBQ与酒水；开业及停留制度未知。"))
        self.assertEqual(result["selected"]["origin"], "sourced")
        self.assertEqual(result["viable_count"], 1)

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
        for merchant in ("清风洗浴中心", "清风汗蒸馆", "清风汤泉", "水石清池·汤泉生活",
                         "清风水疗中心", "清风按摩馆", "清风足疗", "清风足浴店",
                         "清风KTV", "清风Ktv", "清风酒吧", "清风清吧"):
            found, name = api._merchant_entity_signal(DOMAIN, merchant, "", "")
            self.assertTrue(found)
            self.assertEqual(name, merchant)
            query = facts.build_fact_query(DOMAIN, merchant, "广州")
            self.assertIn(merchant, query)
            self.assertIn("预约", query)
            keyword = facts._amap_keyword_from_query(query)
            self.assertEqual(keyword, merchant)
            self.assertTrue(facts._amap_poi_matches_keyword({"name": merchant}, keyword))
            self.assertTrue(facts._amap_poi_matches_keyword({"name": merchant}, merchant))
            self.assertFalse(facts._amap_poi_matches_keyword({"name": "另一家汤泉"}, merchant))
        local = {"domain": "按摩", "name": "清风按摩馆", "facts": {"address": "测试街8号"}}
        canonical = {**local, "domain": DOMAIN}
        self.assertEqual(facts._record_match_score(local, "清风按摩馆", DOMAIN),
                         facts._record_match_score(canonical, "清风按摩馆", DOMAIN))
        self.assertEqual(facts._record_match_score(local, "另一家按摩馆", DOMAIN), 0)
        for label in ("洗浴中心", "洗浴汗蒸", "汗蒸", "汤泉", "按摩足疗SPA", "足疗", "SPA", "KTV", "酒吧", "清吧"):
            self.assertEqual(api._merchant_entity_signal(DOMAIN, "", "", label), (False, ""))
            for old_domain in ("美食", "旅行"):
                self.assertEqual(api._merchant_entity_signal(old_domain, "", "", label), (True, label))

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

    def test_actual_unsupported_geography_crowd_and_rarity_are_blocking(self):
        # Snippets from the retained failed real bath9 output, not gold quality
        # labels or a claim that this offline test re-ran a model.
        source = "素材来自广州。分店地址、营业时间与客流时段未知；仅展示庭院、水池、海鲜自助和饮品柜台。"
        for category in ("洗浴汗蒸", "按摩足疗SPA", "KTV", "酒吧"):
            for claim in ("广州CBD旁", "藏在市中心的休闲空间", "白天下午人少", "周末无需排队",
                          "这类搭配在广州城区并不多见", "上午营业", "水温舒服", "海鲜新鲜",
                          "服务很贴心", "环境安静", "卫生有保障", "我这次泡完很舒服"):
                with self.subTest(category=category, claim=claim):
                    issues = api._delivery_integrity_issues(claim, f"本次项目类型：{category}。{source}", DOMAIN)
                    if category in {"KTV", "酒吧"} and claim in {"白天下午人少", "周末无需排队", "水温舒服", "海鲜新鲜", "服务很贴心", "环境安静", "卫生有保障"}:
                        self.assertFalse(issues)  # Owner's primary KTV/bar light copy policy.
                        continue
                    self.assertTrue(issues, claim)
                    self.assertTrue(api._has_blocking_quality_issues(95, issues, DOMAIN))
        for claim in ("是否在CBD旁需确认", "下午是否人少需确认", "水温舒服吗？", "不能根据图片写成广州CBD旁",
                      "图中人少，座位与灯光清晰", "庭院、泳池、自助餐和饮品柜台是本次可见区域"):
            self.assertFalse(api._delivery_integrity_issues(claim, source, DOMAIN), claim)
        self.assertTrue(api._delivery_integrity_issues("照片中不用排队", source, DOMAIN))
        self.assertTrue(api._delivery_integrity_issues("照片中水质干净", source, DOMAIN))
        # New KTV policy uses source intent, not the observed failed final
        # candidate (which was not retained). No model call is replayed here.
        ktv = "本次主要主题是KTV唱歌聚会，围绕选歌和聚会筹备写作。"
        copy = "50人聚会，两个包房各自独立。周末人少，隔音很好。欢唱3小时，套餐A含餐饮，排队10分钟。"
        self.assertTrue(api._leisure_ktv_light_context(ktv))
        self.assertFalse(api._delivery_integrity_issues(copy, ktv, DOMAIN))
        public, notices = api._leisure_public_fact_text(copy, ktv)
        self.assertFalse(notices)
        self.assertIn("欢唱3小时", public)
        self.assertIn("套餐A含餐饮", public)
        for other in ("洗浴中心含KTV配套。", "KTV与按摩足疗SPA综合体验。",
                      "KTV与SPA的主要主题未知。", "KTV主题未知。", "如果本次是KTV聚会。",
                      "门店名：甲店\n对象：乙店\nKTV唱歌聚会。",
                      "主题未知。\n" + api._LEISURE_VISUAL_SOURCE_MARKER + "\nKTV唱歌聚会。",
                      "主题未知。\n【联网事实补全】\n对象：KTV门店"):
            with self.subTest(source=other):
                self.assertFalse(api._leisure_ktv_light_context(other))
                self.assertTrue(api._delivery_integrity_issues("KTV欢唱3小时。", other, DOMAIN))
        self.assertTrue(api._leisure_ktv_light_context(ktv, "SPA风格的装修。"))
        self.assertFalse(api._delivery_integrity_issues("SPA项目60分钟。", ktv, DOMAIN))
        # Primary scope is fixed by the original author brief in candidate,
        # repair and public checks; comma normalization must not flip it.
        comma_source = "本次主题是KTV，不涉及SPA。"
        comma_copy = "包房各自独立，隔音很好，欢唱3小时。"
        self.assertTrue(api._leisure_ktv_light_context(comma_source, "洗浴风格的装修。"))
        self.assertFalse(api._delivery_integrity_issues(comma_copy, comma_source, DOMAIN))
        self.assertFalse(api._leisure_public_fact_issues(comma_copy, comma_source))
        self.assertFalse(api._leisure_public_fact_text(comma_copy, comma_source)[1])
        self.assertIn("KTV轻量", api._quality_expression_brief(DOMAIN, comma_source))
        self.assertIn("KTV轻量", api._safe_fact_delivery_brief(DOMAIN, comma_source))
        self.assertFalse(api._leisure_ktv_light_context("洗浴中心含KTV配套。", "KTV聚会。"))
        for hard in ("人均118元。", "位于康定路。", "营业时间18:00-22:00。", "KTV治疗失眠。", "我这次去了KTV。"):
            with self.subTest(hard=hard):
                self.assertTrue(api._delivery_integrity_issues(hard, ktv, DOMAIN))
        given = ktv + "\n地址：康定路358号。\n人均116元。\n营业时间18:00-22:00。"
        self.assertFalse(api._delivery_integrity_issues("位于康定路。人均116元。营业时间18:00-22:00。", given, DOMAIN))
        self.assertTrue(api._delivery_integrity_issues("营业时间20:00-24:00。", given, DOMAIN))
        self.assertIn("KTV轻量", api._safe_fact_delivery_brief(DOMAIN, ktv))
        self.assertIn("KTV轻量", api._quality_expression_brief(DOMAIN, ktv))
        self.assertNotIn("KTV轻量", api._quality_expression_brief(DOMAIN, "洗浴中心含KTV配套。"))

    def test_leisure_ai_observations_cannot_supply_hard_fact_authority(self):
        original = "广州休闲素材。地址、时段客流和作者温感未知。套餐不含SPA。"
        visual = "藏在CBD旁的庭院。下午人少。水温舒服，温度40度。套餐包含SPA。"
        context = api._generation_delivery_source_context(DOMAIN, original, visual)
        self.assertIn(visual, context)  # Keep pixels' scene material for writing.
        self.assertEqual(api._leisure_nonvisual_fact_source(context), original + "\n\n")
        for claim in ("CBD旁", "下午人少", "水温舒服", "水温40度", "套餐包含SPA"):
            self.assertTrue(api._delivery_integrity_issues(claim, context, DOMAIN), claim)
        self.assertFalse(api._delivery_integrity_issues("画面里的庭院呈现木调与暖光风格", context, DOMAIN))
        self.assertFalse(api._delivery_integrity_issues("套餐不含SPA", context, DOMAIN))
        safe_brief = api._safe_fact_delivery_brief(DOMAIN, context)
        self.assertNotIn("CBD旁", safe_brief)
        self.assertNotIn("下午人少", safe_brief)
        for domain in OLD_DOMAINS:
            self.assertEqual(api._generation_delivery_source_context(domain, original, visual), original + "\n\n" + visual)

    def test_sound_and_food_state_grammar_preserves_source_and_polarity(self):
        unknown = "素材有庭院、泳池、海鲜展示与饮品柜台；声音体验和食材状态未知。"
        # Actual391 includes the first/last two forms. These are finite source
        # contracts, not a new model run or human quality labels.
        claims = ("没有嘈杂人声", "听不到吵闹声", "环境没有噪音", "环境嘈杂", "嘈杂的人声",
                  "满台鲜活海鲜自助", "鲜活生鲜", "食材新鲜", "新鲜的食品", "海鲜不新鲜")
        for claim in claims:
            with self.subTest(claim=claim):
                issues = api._delivery_integrity_issues(claim, unknown, DOMAIN)
                self.assertTrue(any("感官" in issue for issue in issues), claim)
                self.assertTrue(api._has_blocking_quality_issues(95, issues, DOMAIN))
                self.assertFalse(api._delivery_integrity_issues(claim, claim, DOMAIN), claim)
        for source, claim in (("食品新鲜", "新鲜的食品"), ("海鲜鲜活", "鲜活海鲜"),
                              ("人声嘈杂", "嘈杂的人声"), ("海鲜不新鲜", "不新鲜的海鲜")):
            self.assertFalse(api._delivery_integrity_issues(claim, source, DOMAIN), (source, claim))
        for source, claim in (("海鲜不新鲜", "海鲜新鲜"), ("海鲜新鲜", "不新鲜的海鲜"),
                              ("人声嘈杂", "没有嘈杂人声"), ("没有嘈杂人声", "没有人声")):
            self.assertTrue(api._delivery_integrity_issues(claim, source, DOMAIN), (source, claim))
        for source, claim in (("照片中无人。", "没有人声。"),
                              ("照片里没有嘈杂人声。", "没有嘈杂人声。"),
                              ("图中环境安静。", "环境安静。")):
            self.assertTrue(api._delivery_integrity_issues(claim, source, DOMAIN), (source, claim))
        self.assertFalse(api._delivery_integrity_issues("没有嘈杂人声。", "照片里无人。作者实际听到没有嘈杂人声。", DOMAIN))
        for visible in ("静谧雅致的画面与暖黄灯光。", "宁静的视觉效果适合留白构图。",
                        "生鲜展示区与饮品柜台可见。", "海鲜展示照片带来视觉新鲜感。",
                        "建议背对大厅拍摄，先庭院后餐台。"):
            self.assertFalse(api._delivery_integrity_issues(visible, unknown, DOMAIN), visible)

    def test_completed_visit_grammar_binds_actor_time_and_affirmation(self):
        unknown = "素材来自广州水石清池·汤泉生活；未提供作者亲历，不写亲测。"
        for claim in ("这是我在水石清池的真实打卡体验。", "我的实际探店经历。",
                      "我们在水石清池的亲身体验。", "我昨天亲自去了水石清池。",
                      "我这次在水石清池的真实打卡体验。", "我不是没去过水石清池。"):
            with self.subTest(claim=claim):
                self.assertTrue(any("亲历" in issue for issue in api._delivery_integrity_issues(claim, unknown, DOMAIN)), claim)
                self.assertFalse(api._delivery_integrity_issues(claim, claim, DOMAIN), claim)
        source = "作者说我昨天打卡了水石清池。"
        self.assertFalse(api._delivery_integrity_issues("我打卡了水石清池。", source, DOMAIN))
        for prior, claim in ((source, "我今天打卡了水石清池。"),
                             ("朋友的真实打卡体验。", "我的真实打卡体验。"),
                             ("朋友亲测过。", "我亲测过。"),
                             ("我没有去过水石清池。", "我去过水石清池。"),
                             ("我未亲测。", "我亲测。"),
                             ("请写我不是没去过水石清池。", "我去过水石清池。")):
            self.assertTrue(api._delivery_integrity_issues(claim, prior, DOMAIN), (prior, claim))
        for not_completed in ("我的待打卡攻略。", "我的计划打卡体验。", "我计划去水石清池。",
                              "以后准备亲测。", "我没有去过水石清池。", "未亲测，不写亲测。",
                              "我的看图实际体验。", "我是否去过需要确认？"):
            self.assertFalse(api._leisure_observation_fact_claims(not_completed)["visit"], not_completed)
            self.assertFalse(api._delivery_integrity_issues(not_completed, unknown, DOMAIN), not_completed)

    def test_spatial_independence_needs_scope_but_editorial_groups_are_not_floorplans(self):
        unknown = "仅展示庭院、水景座位、泳池、餐饮展示区；没有平面图或区位确认。"
        for claim in ("餐饮展示区各自独立分区。", "这里有独立包房。", "空间互不干扰。"):
            self.assertTrue(any("空间布局" in issue for issue in api._delivery_integrity_issues(claim, unknown, DOMAIN)), claim)
            self.assertFalse(api._delivery_integrity_issues(claim, "作者确认：" + claim, DOMAIN), claim)
        for source, claim in (("洗浴中心内KTV包房独立。", "SPA包房独立。"),
                              ("没有独立包房。", "独立包房。"),
                              ("包房独立。", "包房互不干扰。")):
            self.assertTrue(api._delivery_integrity_issues(claim, source, DOMAIN), (source, claim))
        self.assertFalse(api._delivery_integrity_issues("SPA包房独立。", "KTV包房独立。", DOMAIN))
        # An explicit facility count remains physical even in a reference
        # guide. Editorial themes and visible-image groupings remain allowed.
        physical = "水石清池3大分区游览顺序参考攻略。"
        self.assertTrue(api._delivery_integrity_issues(physical, unknown, DOMAIN))
        self.assertFalse(api._delivery_integrity_issues(physical, "门店名：水石清池\n对象：水石清池\n作者确认：水石清池实际设有3个分区。", DOMAIN))
        self.assertTrue(api._delivery_integrity_issues(physical, "门店名：水石清池\n对象：另一家门店\n实际设有3个分区。", DOMAIN))
        for editorial in ("按庭院、泳池、餐饮三个主题组织正文。", "按3个编辑主题整理素材。", "画面分为3个分组。",
                          "建议先拍庭院，再拍水景座位与餐台。"):
            self.assertFalse(api._delivery_integrity_issues(editorial, unknown, DOMAIN), editorial)
        safe_brief = api._safe_fact_delivery_brief(DOMAIN, unknown)
        self.assertIn("编辑分组当作设施库存或物理布局", safe_brief)
        for city in ("城中心禅意汤泉打卡指南", "城市中央的休闲空间", "市中心休闲空间"):
            self.assertTrue(any("地理区位" in issue for issue in api._delivery_integrity_issues(city, "城市广州，地址未知。", DOMAIN)), city)
        self.assertFalse(api._delivery_integrity_issues("城中心的休闲空间", "作者确认位于市中心。", DOMAIN))

    def test_actual391_public_fields_use_the_same_grammar_without_fake_provenance(self):
        source = "本轮素材来自广州水石清池·汤泉生活；仅展示庭院、水景座位、泳池、餐台和飲品柜台。作者亲历、声音体验、食材新鲜度及平面布局未知。"
        opinion = {"role": "用户专家", "opinion": "庭院与餐台可见。这是我在水石清池的真实打卡体验。",
                   "reason": "背对大厅，没有嘈杂人声。", "evidence": ["满台鲜活海鲜自助。"],
                   "suggestions": ["餐饮展示区各自独立分区。", "建议按庭院、泳池、餐饮三个主题组织正文。"]}
        before = json.dumps(opinion, ensure_ascii=False)
        public = api._generation_public_expert_opinions([opinion], source, DOMAIN)
        summary = api._generation_public_visual_summary("城中心禅意汤泉打卡指南。满台鲜活海鲜自助。鲜活生鲜。木桥与暖黄光线可见。", source, DOMAIN)
        progress = api._generation_public_progress_event({"type": "expert_opinion", "content": opinion["opinion"],
                                                        "detail": opinion["reason"], "progress": 22}, source, DOMAIN)
        saved = api._sanitize_chat_generate_context({"cover_analysis": summary, "expert_opinions": public})
        for value in (public, summary, progress, saved):
            encoded = json.dumps(value, ensure_ascii=False)
            for unsupported in ("真实打卡体验", "没有嘈杂人声", "鲜活海鲜", "鲜活生鲜", "城中心", "各自独立分区"):
                self.assertNotIn(unsupported, encoded)
            self.assertIn("已省略相关建议", encoded)
        self.assertIn("三个主题", json.dumps(public, ensure_ascii=False))
        self.assertIn("木桥与暖黄光线", summary)
        self.assertIn("空间布局独立关系", json.dumps(public, ensure_ascii=False))
        self.assertEqual(json.dumps(opinion, ensure_ascii=False), before)
        # Raw AI repetition must not authorize any of these claims after resume.
        contaminated = api._generation_delivery_source_context(DOMAIN, source, before)
        self.assertNotIn("真实打卡体验", json.dumps(api._generation_public_expert_opinions([opinion], contaminated, DOMAIN), ensure_ascii=False))

    def test_actual_c1f_complete_public_fields_use_shared_fact_families(self):
        # Exact affected fields from the retained 34,449-byte actual report,
        # SHA256 ff619f140bbeea27b2acac6a6961c2464d96047ea56619069988bd1bcf1bf858.
        # Offline regression only; the original paid report stays unchanged.
        actual = {'fact_context': '【本次用户创作简报；不是外部独立核验】\n本轮素材来自水石清池·汤泉生活。城市及分店尚未确认。作者确认这是含洗浴、水疗、自助餐的大型综合休闲项目；本次9张图仅展示庭院与水景座位、室内水池、海鲜自助展示和饮品柜台。围绕这些真实区域整理一篇可收藏的休闲体验参考，正文覆盖多张相关素材，分清空间与餐饮主题，不用设施数量制造高分。未提供本人温感、味道、卫生、服务体验或疗效，不写亲测。价格、营业时间、票种、时长、具体包含权益、其他配套与分店地址未知；检索返回且对象对应的事实才可引用，失败时说明缺失，不杜撰。不推断每个中心都有SPA、汗蒸、娱乐项目或所有餐次。', 'note_title': '水石清池汤泉｜庭院泳池海鲜一站攻略', 'note_body': '水石清池把新中式禅意庭院、室内泳池、海鲜自助台和酒廊吧台整合在同一屋檐下，适合想一站完成泡浴＋餐饮＋拍照的周末安排。\n\n庭院区是水石清池第一个打卡点，黑松、白沙枯山水、朱红拱桥与青石水景搭暖光宫灯，夜间光影分层清晰，侘寂感强，傍晚入场拍照最出效果。\n\n室内泳池区用暖金星光顶倒映蓝调池水，哑光石质墙面配嵌入式灯带；泡池区以原木格栅围出独立小角落，池边搭禅意置石，两个区域风格不同、可按需选择，具体区域开放时段建议到店确认。\n\n海鲜自助台冰鲜蟹腿、贝类整排陈列在碎冰金属盛器里，视觉陈列丰富，餐期时段和是否包含在门票内建议提前问清楚再决定。\n\n酒廊吧台适合泡完汤后小坐，弧形吧台配环形暖黄灯带和整排酒墙，整体氛围偏沉静，饮品种类待到店确认。\n\n计划去水石清池的，建议出发前确认营业时间、票种价格和各区段的权益范围，避免到场后预期差距，评论区可以聊聊你的行程安排。\n\n#汤泉打卡 #新中式设计 #室内泳池 #海鲜自助 #庭院景观 #周末放松 #城市休闲', 'title_variants': ['水石清池汤泉生活｜泳池海鲜庭院全攻略', '新中式汤泉+海鲜自助一站｜水石清池攻略', '水石清池｜庭院泳池海鲜自助周末怎么玩'], 'cover_analysis': '缺少地理区位来源依据，已省略相关建议。\n医疗功效表述不适用休闲内容，已省略相关建议。\n缺少温感/味道/卫生/服务/声音体验来源依据，已省略相关建议。\n【主图】\n黑松，白砂枯山水，红桥，青石水榭，暖光宫灯，高级静谧\n新中式禅意庭院景观\n\n【其余8张素材图】\n\n图2（深度）：场景：暖光星顶下的静谧室内泳池，氛围感拉满\n核心元素：暖金色星光顶，清透蓝调池水，哑光石质墙面，嵌入式暖光灯，轻奢镜面设计，静谧高级感\n情绪基调：精致高级，沉浸松弛\n爆文角度：水石清池休闲打卡攻略\n视觉亮点：星光顶倒映泳池\n\n核心元素：黑松，白沙枯山水，深灰金属檐顶，原木立柱，侘寂高级感，城市隐世感\n情绪基调：静谧雅致，精致高级\n爆文角度：都市新中式汤泉打卡地\n视觉亮点：松间新中式禅意庭院\n\n图4（深度）：场景：水石清池汤泉，质感海鲜自助餐区氛围感拉满\n核心元素：暗调暖光，粗粝石质，木质餐台，鲜气海鲜，精致摆盘，沉静高级\n情绪基调：精致高级，沉浸享受\n爆文角度：汤泉海鲜自助攻略\n\n图5（深度）：场景：暖调质感汤泉空间，木格格栅衬着氤氲泡池松弛感拉满\n核心元素：暖棕柔光，石材泡池，原木格栅，禅意置石，温润地砖，静谧氛围\n爆文角度：水石清池汤泉打卡指南\n视觉亮点：暖光木格禅意泡池\n\n图6（深度）：场景：暖光环绕的质感汤泉饮品吧台休憩空间\n核心元素：暗调金属肌理，暖黄环形灯带，弧形吧台，整排酒墙，温润氛围感，黄铜质感立柱\n情绪基调：高级沉静，沉浸松弛\n爆文角度：汤泉里的质感酒廊打卡点\n视觉亮点：环形灯带酒墙吧台\n\n图7（深度）：场景：暖光轻奢的室内汤池空间氛围感拉满\n核心元素：深灰大理石，暖金柔光灯，静谧汤池，景观置石，温润质感，松弛氛围\n情绪基调：静谧高级，沉浸疗愈\n爆文角度：汤泉轻奢打卡全攻略\n视觉亮点：暖光环绕的大汤池\n\n图8（深度）：城市高楼间藏着中式禅意庭院汤泉空间\n黑松，红桥，青石水景，和风声的松弛感，雅致侘寂，日光漫洒\n朱红日式小桥\n\n图9（深度）：场景：水石清池海鲜自助台，冰鲜海产满满铺陈超诱人\n核心元素：冰鲜海鲜，金属盛器，碎冰，橙红蟹腿，亮白冰面，高级质感\n情绪基调：精致奢华，满足畅快\n爆文角度：汤泉店海鲜自助图鉴\n视觉亮点：满满豪华海鲜阵容', 'expert_opinions': [{'confidence': 0.0, 'evidence': [], 'evidence_binding': '', 'impact': '缺少地理区位来源依据，已省略相关建议。\n医疗功效表述不适用休闲内容，已省略相关建议。', 'opinion': '城市商务区内的新中式庭院景观。\n可见元素包括：\n- 景观设计：黑松盆栽、白砂铺装的枯山水区域、红色木质拱桥、青石板水榭结构\n- 照明氛围：暖色宫灯照亮庭院，营造夜间柔和光线\n- 建筑风格：现代建筑与传统中式元素结合，开放式或半开放式庭院布局\n- 色彩基调：黑、白、红、青灰为主，暖光点缀\n- 空间感：纵深感明显，层次分明，视线开阔\n\n素材突出庭院的设计感和静谧氛围，但画面本身不能证明：汤泉水温、泉水成分、卫生标准、是否为真实温泉或循环水、庭院是否为汤泉专属区域或公共景观、实际体验舒适度、营业时段、收费标准、预约流程。', 'reason': '缺少地理区位来源依据，已省略相关建议。\n医疗功效表述不适用休闲内容，已省略相关建议。', 'role': '视觉专家', 'suggestions': ['强调都市人的松弛需求，突出新中式设计如何在商务区创造避世感。\n适合强调地理位置便利性与氛围转换效果，吸引工作日解压的职场人群。', '**设计美学视角**：「新中式庭院怎么做出高级感」—— 拆解黑松、枯山水、红桥、青石、宫灯等元素的搭配逻辑，讨论现代汤泉空间如何融合传统美学。', '**体验决策视角**：「新中式汤泉庭院，适合什么时候去」—— 围绕实际汤泉项目（若素材对应具体商家），讨论夜间庭院氛围、套餐权益、适合人群（朋友小聚、情侣约会、家庭放松）。\n需补充：是否可预约庭院区域、是否需额外费用、餐饮/休息配套、营业时间。']}, {'confidence': 0.0, 'evidence': [], 'evidence_binding': '', 'impact': '缺少常态或时段客流来源依据，已省略相关建议。\n**发布时机建议**：当前无新鲜热词依据（时机系数1.0，热词为空）。\n建议：\n- **可选补充**：若作者确认营业时间或特定套餐时段，才在正文中绑定\n- **建议发布前确认**：地址、营业时间、价格、预约方式等，补充到文末"实用信息"或评论区，增强可信度', 'opinion': '**核心词融入策略**：\n\n1. **标题层**（已内置方案中）\n- 新中式禅意、庭院、汤泉、泳池、海鲜自助、酒廊\n- 自然服务标题叙事，不额外堆砌\n\n2. **正文自然融入位置**\n- 开场：快速定位"汤泉综合项目"\n- 空间1：庭院景观描写（黑松、白沙、禅意、侘寂）\n- 空间2：室内泳池段落（星光顶、大理石、高级感）\n- 空间3：海鲜自助段落（冰鲜、摆盘、自助形式）\n- 空间4：饮品酒廊段落（酒墙、吧台、休息空间）\n- 结尾：收藏价值 + CTA\n\n3. **禁止做法**\n- 不为热词补充不存在的项目（如图片没有汗蒸、按摩、KTV，不写）\n- 不强行拼接关键词破坏可读性\n- 不用"新品""限时"等虚假热词信号', 'reason': '缺少常态或时段客流来源依据，已省略相关建议。\n**发布时机建议**：当前无新鲜热词依据（时机系数1.0，热词为空）。\n建议：\n- **可选补充**：若作者确认营业时间或特定套餐时段，才在正文中绑定\n- **建议发布前确认**：地址、营业时间、价格、预约方式等，补充到文末"实用信息"或评论区，增强可信度', 'role': '增长专家', 'suggestions': ['**核心词融入策略**：', '**标题层**（已内置方案中）', '新中式禅意、庭院、汤泉、泳池、海鲜自助、酒廊', '自然服务标题叙事，不额外堆砌']}, {'confidence': 0.0, 'evidence': [], 'evidence_binding': '', 'impact': '缺少地理区位来源依据，已省略相关建议。', 'opinion': '松间庭院、星光泳池、海鲜自助，每个角落都值得收藏。', 'reason': '缺少地理区位来源依据，已省略相关建议。', 'role': '用户专家', 'suggestions': []}], 'features': {'body_cta_count': 1.0, 'body_has_address': 1.0, 'body_has_booking': 0.0, 'body_has_hours': 1.0, 'body_has_must_order': 0.0, 'body_has_price': 1.0, 'body_has_transport': 1.0, 'body_len': 431.0, 'category_avg_ces': 0.0, 'category_saturation': 0.0, 'commercial_actionability': 1.0, 'commercial_ai_probability': 0.0, 'commercial_body_avg_sentence_len': 51.857142857142854, 'commercial_body_char_len': 431.0, 'commercial_body_cta_count': 1.0, 'commercial_body_has_cta': 1.0, 'commercial_body_has_first_person': 0.0, 'commercial_body_low_quality_phrase_count': 0.0, 'commercial_body_main_char_len': 380.0, 'commercial_body_paragraph_count': 6.0, 'commercial_body_price_mentions': 0.0, 'commercial_body_sentence_burstiness': 0.19295549319931088, 'commercial_body_sentence_count': 7.0, 'commercial_body_specific_number_count': 0.0, 'commercial_body_tag_count': 7.0, 'commercial_body_template_phrase_count': 0.0, 'commercial_domain_missing_slot_count': 0.0, 'commercial_domain_slot_count': 4.0, 'commercial_domain_slot_coverage': 1.0, 'commercial_fact_density': 0.5, 'commercial_naturalness_available': 0.0, 'commercial_naturalness_score': 50.0, 'commercial_specificity': 0.25, 'commercial_title_char_len': 17.0, 'commercial_title_has_domain_anchor': 1.0, 'commercial_title_has_number': 0.0, 'commercial_title_has_recommendation': 0.0, 'commercial_title_in_delivery_range': 1.0, 'commercial_title_price_recommendation_join': 0.0, 'commercial_title_template_phrase_count': 0.0, 'commercial_title_unreadable_risk': 0.0, 'content_freshness': 0.0, 'cover_aesthetic_score': 0.0, 'cover_aspect_ratio': 1.7758, 'cover_brightness': 0.4287, 'cover_composition_score': 0.0, 'cover_contrast': 0.2354, 'cover_emotion_intensity': 0.0, 'cover_face_count': 0.0, 'cover_has_face': 0.0, 'cover_has_text': 0.0, 'cover_saturation': 0.2499, 'cover_sharpness': 0.0896, 'cover_text_prominence': 0.0, 'cover_visual_clarity': 0.0, 'cover_warmth': 0.2735, 'domain_baby_age': 0.0, 'domain_baby_materials': 0.0, 'domain_baby_safety': 0.0, 'domain_baby_steps': 0.0, 'domain_beauty_effect': 0.0, 'domain_beauty_price': 0.0, 'domain_beauty_product': 0.0, 'domain_beauty_skin': 0.0, 'domain_encoded': 17.0, 'domain_fashion_fit': 0.0, 'domain_fashion_items': 0.0, 'domain_fashion_logic': 0.0, 'domain_fashion_price': 0.0, 'domain_fitness_action': 0.0, 'domain_fitness_dosage': 0.0, 'domain_fitness_safety': 0.0, 'domain_fitness_target': 0.0, 'domain_food_address': 0.0, 'domain_food_booking': 0.0, 'domain_food_hours': 0.0, 'domain_food_must_order': 0.0, 'domain_food_price': 0.0, 'domain_food_taste_evidence': 0.0, 'domain_home_before_after': 0.0, 'domain_home_budget': 0.0, 'domain_home_items': 0.0, 'domain_home_space': 0.0, 'domain_travel_avoid': 0.0, 'domain_travel_budget': 0.0, 'domain_travel_route': 0.0, 'domain_travel_season': 0.0, 'domain_travel_transport': 0.0, 'is_trending_topic': 0.0, 'keyword_competition': 0.0, 'keyword_search_vol': 0.0, 'plad_avg_sentence_len': 61.57142857142857, 'plad_emoji_density': 0.0, 'plad_immediate_repetition': 0.0, 'plad_interactive_stance': 0.14285714285714285, 'plad_number_ratio': 0.0, 'plad_phrasal_repetition': 0.032710280373831724, 'plad_punctuation_ratio': 0.06904231625835189, 'plad_sentence_burstiness': 0.20467667023425473, 'plad_sentence_count': 7.0, 'plad_ttr': 0.7515923566878981, 'plad_unique_emoji_ratio': 0.0, 'plad_word_burstiness': 0.5625685978790208, 'plad_word_freq_entropy': 6.710070191497884, 'semantic_emotional_intensity': 0.62, 'semantic_empathetic_engagement': 0.75, 'semantic_rhetorical_score': 0.78, 'tag_count': 7.0, 'tag_has_city': 0.0, 'tag_has_food_travel': 1.0, 'time_days_to_holiday': 12.0, 'time_hour': 10.0, 'time_is_weekend': 0.0, 'time_weekday': 2.0, 'title_has_city': 0.0, 'title_has_neg_emotion': 0.0, 'title_has_new_signal': 0.0, 'title_has_number': 0.0, 'title_has_pos_emotion': 0.0, 'title_has_price': 0.0, 'title_has_question': 0.0, 'title_len': 17.0, 'trend_momentum': 0.0, 'trend_peak_distance': 0.0}}
        source = actual["fact_context"]
        self.assertIn("城市及分店尚未确认", source)
        issues = api._delivery_integrity_issues(actual["note_title"] + "\n" + actual["note_body"], source, DOMAIN,
                                               title_variants=actual["title_variants"])
        self.assertTrue(any("空间布局" in issue for issue in issues))
        self.assertTrue(api._has_blocking_quality_issues(73, issues, DOMAIN))
        cover = api._generation_public_visual_summary(actual["cover_analysis"], source, DOMAIN)
        opinions = api._generation_public_expert_opinions(actual["expert_opinions"], source, DOMAIN)
        progress = api._generation_public_progress_event({"type": "expert_opinion", "content": actual["cover_analysis"]}, source, DOMAIN)
        saved = api._sanitize_chat_generate_context({"cover_analysis": cover, "expert_opinions": opinions})
        for public in (cover, opinions, progress, saved):
            encoded = json.dumps(public, ensure_ascii=False)
            for unsupported in ("和风声", "商务区内", "商务区创造避世感", "地理位置便利性"):
                self.assertNotIn(unsupported, encoded)
        for visible in ("原木格栅", "蓝调池水", "黑松", "红桥", "雅致侘寂"):
            self.assertIn(visible, cover)
        # Bare visual mood is not automatically a medical treatment claim.
        self.assertIn("静谧高级", cover)
        hits = api._generation_public_feature_hits(actual["note_title"], actual["note_body"], actual["features"], 73, DOMAIN, source)
        self.assertFalse(hits["has_price"])
        self.assertFalse(hits["has_address"])
        self.assertTrue(api._feature_hits_for_generation(actual["note_title"], actual["features"], 73, DOMAIN, body=actual["note_body"])["has_price"])

    def test_actual_single_refine2_requires_all_title_and_visual_fact_contracts(self):
        # Exact affected fields from retained actual 31,492-byte report,
        # SHA256 c6030254713b3589ece72ac27302278f55a31d40317114eb31a9c723f4814e5c. No live replay.
        actual = {'fact_context': '【本次用户创作简报；不是外部独立核验】\n本轮素材来自水石清池·汤泉生活。城市及分店尚未确认。本轮是水石清池·汤泉生活的一张室内水池素材。只围绕可见水池、石材、灯光、扶手与毛巾陈列组织一个真实空间观察主题。作者未提供泡池水温、亲身触感、卫生、服务或疗效，不写亲测、舒服到睡着、治失眠等。单图不扩展成该店全设施清单，不补SPA、足疗、自助餐权益。地址、营业时间、票价、项目时长和包含条件未提供；只使用真实对应检索字段，缺失需明确。', 'note_title': '水石清池汤泉，3处细节让人当场想收藏', 'note_body': '走进水石清池·汤泉生活，汤泉池区第一眼就不像普通大众浴场。池壁和池底全用深灰理石铺就，纹理沉稳，颗粒感清晰，暖金色氛围光从上方均匀打下，水面折出细碎光斑，散在深灰理石上。深灰配暖金的冷暖对比，和常见白瓷砖浴池完全不在一个调性，整个汤泉池区有种被刻意设计过的层次感，视觉克制，不浮夸。\n\n黄铜扶手沿汤泉池边设置，弧度自然，暖光下透出温润金属光泽。竖向格栅配景石造景，空间纵深感比普通浴场更明显，整排净白毛巾整齐陈列在池边，这3处细节从图片就能直接判断，不是靠滤镜撑起来的质感。\n\n不追热闹氛围、想找视觉干净利落的汤泉池区，水石清池·汤泉生活值得放进候选清单，票价和营业信息建议出发前官方渠道确认。先收藏，有到店体验的朋友欢迎评论区聊聊👇\n\n#汤泉 #质感汤池 #深灰理石 #设计感空间 #松弛感打卡 #汤泉生活 #小众汤泉', 'title_variants': ['水石清池汤泉池区，深灰理石暖金光3处细节太克制', '不像大众浴场，水石清池汤泉3处细节值得收藏', '深灰理石配暖金光，水石清池汤泉池区质感在哪'], 'cover_analysis': '场景：暖光裹住浅泛涟漪的室内汤泡池\n核心元素：深灰理石，暖金氛围光，竖格栅背景，景石造景，黄铜扶手，整排净白毛巾\n情绪基调：暖沉静谧松弛\n爆文角度：质感汤池打卡新选择\n视觉亮点：暖光映满整池', 'expert_opinions': [{'confidence': 0.0, 'evidence': [], 'evidence_binding': '', 'impact': '医疗功效表述不适用休闲内容，已省略相关建议。', 'opinion': '室内汤泡池特写，深灰理石池壁与池底清晰可见，水面泛起浅涟漪反射暖金色氛围光。\n竖向格栅背景营造纵深感，嵌入景石造景点缀池侧，黄铜扶手沿池边设置便于上下。\n池边整齐摆放净白毛巾，暖色照明均匀覆盖全池，构图呈现沉静、质感的休闲氛围。\n光线柔和不刺眼，材质层次分明（理石纹理、金属光泽、纺织质感），无明显人物活动。', 'reason': '医疗功效表述不适用休闲内容，已省略相关建议。', 'role': '视觉专家', 'suggestions': ['**质感汤池打卡新选择** — 以深灰理石+暖金光为视觉核心，聚焦汤泡池的设计感与松弛氛围，适合寻求"高级感泡汤体验"的读者，突出空间美学而非功效承诺。', '**细节见品质｜洗浴中心的隐藏高级汤区** — 用黄铜扶手、理石铺装、毛巾摆放等细节展现管理与设计用心，面向注重体验品质与卫生细节的消费者，强调"不只是泡汤"的整体感受。']}, {'confidence': 0.0, 'evidence': [], 'evidence_binding': '', 'impact': '医疗功效表述不适用休闲内容，已省略相关建议。\n缺少常态或时段客流来源依据，已省略相关建议。\n**发布时间建议**：\n- 当前无新鲜热词或平台峰值证据，建议按常规节奏发布\n- 汤泉品类无特殊时间限制；\n- 建议不在商家客流低谷时发布（如平日凌晨），以便评论互动有回应\n- **优先级**：内容质量 > 时间节点；\n此稿已达成交付标准，不必等待热词', 'opinion': '**核心词融入策略**：\n- **"深灰理石+暖金灯光"**：标题开篇即出现，是视觉核心，读者秒懂打卡点\n- **"汤泉"**：品类词，正文首句"走进水石清池·汤泉生活"自然带出，第一个话题标签\n- **"打卡背景"**：行为词，正文中段与适配人群对应，标签"打卡新选择"呼应\n- **"设计感""细节"**：品质词，贯穿正文（黄铜、毛巾、石材、扶手），支撑"认真对待"的核心印象\n\n**避坑**：不强行堆砌"SPA、按摩、自助餐"等未提供项目；\n不补地址、票价、营业时间（用户未提供，缺失不扣重分）', 'reason': '医疗功效表述不适用休闲内容，已省略相关建议。\n缺少常态或时段客流来源依据，已省略相关建议。\n**发布时间建议**：\n- 当前无新鲜热词或平台峰值证据，建议按常规节奏发布\n- 汤泉品类无特殊时间限制；\n- 建议不在商家客流低谷时发布（如平日凌晨），以便评论互动有回应\n- **优先级**：内容质量 > 时间节点；\n此稿已达成交付标准，不必等待热词', 'role': '增长专家', 'suggestions': ['**核心词融入策略**：', '**"深灰理石+暖金灯光"**：标题开篇即出现，是视觉核心，读者秒懂打卡点', '**"汤泉"**：品类词，正文首句"走进水石清池·汤泉生活"自然带出，第一个话题标签']}, {'confidence': 0.0, 'evidence': [], 'evidence_binding': '', 'impact': '', 'opinion': '暖光裹着涟漪，深灰理石配黄铜细节，整排净白毛巾整齐陈列——这样的泡池设计，光看就能感受到空间的用心。', 'reason': '', 'role': '用户专家', 'suggestions': []}], 'selection_meta': {'candidate_count': 4, 'candidates': [{'blocking': False, 'issue_count': 0, 'origin': 'refine_round_2', 'publishable_prob': 0.974, 'ranker_win_rate': 0.993, 'score': 73.5, 'selector_score': 79.24, 'title': '水石清池汤泉，3处细节让人当场想收藏'}, {'blocking': False, 'issue_count': 0, 'origin': 'refine_round_1', 'publishable_prob': 0.967, 'ranker_win_rate': 0.419, 'score': 69.2, 'selector_score': 72.57, 'title': '深灰理石配暖金光，水石清池汤泉值得收藏'}, {'blocking': True, 'issue_count': 2, 'origin': 'arbitrate_initial', 'publishable_prob': 0.974, 'ranker_win_rate': 0.58, 'score': 71.0, 'selector_score': -57.88, 'title': '深灰理石+暖金光｜这家汤泉值得收藏'}, {'blocking': True, 'issue_count': 2, 'origin': 'selector_challenger_1', 'publishable_prob': 0.977, 'ranker_win_rate': 0.009, 'score': 69.5, 'selector_score': -61.65, 'title': '暖金灯光配深灰石｜这个汤泉池质感值得一泡'}], 'selected_origin': 'refine_round_2', 'selected_score': 73.5, 'selected_selector_score': 79.24, 'selected_title': '水石清池汤泉，3处细节让人当场想收藏', 'source_correction_count': 0, 'source_corrections_retained': False, 'used_ranker': True, 'viable_count': 2}}
        self.assertEqual(actual["selection_meta"]["selected_origin"], "refine_round_2")
        self.assertEqual(actual["selection_meta"]["selected_score"], 73.5)
        self.assertEqual([len(value) for value in actual["title_variants"]], [23, 21, 21])
        issues = api._delivery_integrity_issues(actual["note_title"] + "\n" + actual["note_body"], actual["fact_context"], DOMAIN,
                                               title_variants=actual["title_variants"])
        for family in ("空间布局", "作者亲历", "比较", "加工过程", "备选标题1", "备选标题2", "备选标题3"):
            self.assertTrue(any(family in issue for issue in issues), (family, issues))
        self.assertTrue(api._has_blocking_quality_issues(73.5, issues, DOMAIN))
        visible = "图中可见深灰石纹、暖金光、水面反光、金属色扶手、竖格栅、景石与白毛巾陈列，这3处细节适合作为编辑焦点。"
        self.assertFalse(api._delivery_integrity_issues(visible, actual["fact_context"], DOMAIN))
        public, notices = api._leisure_public_fact_text(actual["note_body"], actual["fact_context"])
        for unsupported in ("全用深灰理石", "比普通浴场", "不是靠滤镜", "第一眼就不像"):
            self.assertNotIn(unsupported, public)
        self.assertTrue(notices)
        # A saved score and the original zero issues do not replace this audit.
        self.assertEqual(actual["selection_meta"]["viable_count"], 2)

    def test_visual_attribute_relations_keep_scope_and_source_polarity(self):
        unknown = "门店名：甲店\n只有池景照片；作者到访、工程材料、对比资料和拍摄处理未知。"
        claims = ("池壁和池底全用深灰理石铺就。", "池壁全部采用石材。", "池壁和池底都是大理石。",
                  "整个泳池都采用大理石。", "整个泳池采用大理石。", "池壁池底铺满理石。", "全池采用石材。", "不像普通大众浴场。",
                  "空间纵深感比普通浴场更明显。", "和常见白瓷砖浴池完全不在一个调性。",
                  "不是靠滤镜撑起来的质感。", "没有后期。", "未经后期处理。", "原片直出。", "这张经过后期。",
                  "走进甲店，池景第一眼就显得雅致。")
        for claim in claims:
            with self.subTest(claim=claim):
                self.assertTrue(api._delivery_integrity_issues(claim, unknown, DOMAIN))
                self.assertFalse(api._delivery_integrity_issues(claim, "门店名：甲店\n对象：甲店\n作者确认：" + claim, DOMAIN))
                for source in ("门店名：甲店\n对象：乙店\n" + claim, "门店名：甲店\n写作要求：\n" + claim,
                               "门店名：甲店\n" + claim.rstrip("。") + "，尚未确认。"):
                    self.assertTrue(api._delivery_integrity_issues(claim, source, DOMAIN), (claim, source))
                self.assertTrue(api._delivery_integrity_issues(claim, api._generation_delivery_source_context(DOMAIN, unknown, claim), DOMAIN))
        for claim in ("看图就知道池壁池底全用理石。", "看图就知道原片没有滤镜。", "建议收藏这张无滤镜原片。",
                      "图1比普通浴场更有纵深。", "冷暖对比比普通浴场更明显。", "池壁全由石材铺成。"):
            self.assertTrue(api._delivery_integrity_issues(claim, unknown, DOMAIN), claim)
        for source, claim in (("看图就知道池壁全用理石。", "池壁全用理石。"),
                              ("图1比普通浴场更有纵深。", "比普通浴场更有纵深。")):
            self.assertTrue(api._delivery_integrity_issues(claim, "门店名：甲店\n" + source, DOMAIN))
        for source, claim in (("池壁全用石材。", "池底全用石材。"), ("池壁并不全用石材。", "池壁全用石材。"),
                              ("池壁全用石材。", "池壁并不全用石材。"), ("没有后期。", "这张经过后期。"),
                              ("池壁不全用石材。", "池壁全用石材。"), ("池壁全用石材。", "池壁不全用石材。"),
                              ("池壁全用石材与瓷砖。", "池壁全用石材。"),
                              ("这张经过后期。", "没有后期。"), ("比普通浴场更明显。", "比其他酒吧更明显。")):
            self.assertTrue(api._delivery_integrity_issues(claim, source, DOMAIN), (source, claim))
        self.assertFalse(api._delivery_integrity_issues("照片没有滤镜。", "作者确认这张照片没有滤镜。", DOMAIN))
        for allowed in ("深灰石纹与暖光形成冷暖对比，视觉克制。", "3处编辑细节是扶手、格栅和毛巾陈列。",
                        "两张图的画面风格不同。", "建议对比其他浴场的照片后再选择。", "下次计划走进甲店，第一眼先看池景。",
                        "想象走进甲店，眼前是暖光画面。", "当你走进甲店，第一眼可以先留意配色。",
                        "跟随镜头走进甲店，第一眼看到石纹与灯带。", "画面有电影滤镜感。", "拍摄时可以尝试暖色滤镜。",
                        "拍摄时可以使用滤镜。", "下次拍摄不加滤镜。", "扶手全是金属色泽。", "池壁全是理石纹理。",
                        "整个池壁呈现石纹。", "池壁都是石材质感。", "画面像用了滤镜。"):
            self.assertFalse(api._delivery_integrity_issues(allowed, unknown, DOMAIN), allowed)

    def test_variant_contract_blocks_without_extra_model_calls_or_truncation(self):
        variants = ["水石清池汤泉池区，深灰理石暖金光3处细节太克制"]
        candidate = {"title": "水石清池池景素材与暖光观察参考", "body": "从图片看，可见石纹、水面和暖光。", "variants": variants}
        async def fit(title, *_args, **_kwargs):
            return title
        with mock.patch.object(api, "_fit_title_limit", side_effect=fit) as title_fit, \
             mock.patch.object(api._mr, "call", new=mock.AsyncMock()) as model, \
             mock.patch.object(api, "_score_generated_note", new=mock.AsyncMock(return_value=(95, {}, "优秀"))), \
             mock.patch.object(api, "_generated_quality_issues", return_value=[]), \
             mock.patch.object(api, "_v04_publishable_probability", return_value=None):
            scored = asyncio.run(api._score_generation_delivery_candidate(candidate, domain=DOMAIN, local_time="2026101413",
                                                                          timing=None, cover_feats=None, source_context="只有池景照片。"))
        self.assertTrue(scored["blocking"])
        self.assertEqual(scored["variants"], variants)
        self.assertEqual(title_fit.call_count, 1)  # Main only; no added variant LLM loop.
        model.assert_not_awaited()
        self.assertTrue(api._has_blocking_quality_issues(95, api._delivery_integrity_issues("可见灯光。", "", DOMAIN, title_variants=variants), DOMAIN))
        for domain in ("美食", "旅行", "穿搭", "美妆", "家居", "健身", "母婴"):
            self.assertFalse(any("标题超过平台上限" in issue for issue in api._delivery_integrity_issues("可见灯光。", "", domain, title_variants=variants)))
            self.assertFalse(api._has_blocking_quality_issues(95, ["备选标题1：标题超过平台上限"], domain))
            with mock.patch.object(api, "_fit_title_limit", side_effect=fit), \
                 mock.patch.object(api, "_score_generated_note", new=mock.AsyncMock(return_value=(95, {}, "优秀"))), \
                 mock.patch.object(api, "_generated_quality_issues", return_value=[]), \
                 mock.patch.object(api, "_v04_publishable_probability", return_value=None):
                old = asyncio.run(api._score_generation_delivery_candidate({"title": "原来明确完整的素材观察", "body": "可见灯光。"},
                    domain=domain, local_time="2026101413", timing=None, cover_feats=None, source_context="只提供素材。"))
            self.assertNotIn("variants", old)

    def test_body_shaping_keeps_visual_material_outside_fact_processing(self):
        brief = "门店名：甲店\n作者到访、材料铺装、声音及价格未知。"
        image = "图1：深灰石纹、格栅、暖光和白毛巾可见。池底全部铺石材。排队10分钟。"
        context = api._generation_delivery_source_context(DOMAIN, brief, image)
        with mock.patch.object(api._mr, "call", new=mock.AsyncMock(return_value="图中可见石纹、暖光和毛巾。")) as model, \
             mock.patch.object(api, "_insert_safe_fact_line", wraps=api._insert_safe_fact_line) as clean:
            asyncio.run(api._shape_body_for_delivery("池景与暖光素材观察", "可见石纹。", DOMAIN, context))
        user = model.call_args.args[2]
        self.assertIn(image, user)
        self.assertIn(api._LEISURE_VISUAL_SOURCE_MARKER, user)
        authority = user.split("完整只读事实依据", 1)[1].split(api._LEISURE_VISUAL_SOURCE_MARKER, 1)[0]
        self.assertNotIn("池底全部", authority)
        for call in clean.call_args_list:
            self.assertEqual(call.args[2], api._leisure_nonvisual_fact_source(context))
        self.assertTrue(api._delivery_integrity_issues("池底全部铺石材。", context, DOMAIN))
        self.assertFalse(api._delivery_integrity_issues("图中有暖光和石纹。", context, DOMAIN))

    def test_actual849_visible_groups_and_subjective_rarity_remain_deliverable(self):
        # Exact fields from 35,124-byte retained report, SHA256
        # 7ed5a9292b1ad8c807a529ff0050725d0ff2209565d1422cb353c289e16cac71.
        # Latest owner preference permits visual grouping/subjective rarity;
        # original author brief and candidate telemetry are retained unchanged.
        actual = {'fact_context': '【本次用户创作简报；不是外部独立核验】\n本轮素材来自水石清池·汤泉生活。城市及分店尚未确认。作者确认这是含洗浴、水疗、自助餐的大型综合休闲项目；本次9张图仅展示庭院与水景座位、室内水池、海鲜自助展示和饮品柜台。围绕这些真实区域整理一篇可收藏的休闲体验参考，正文覆盖多张相关素材，分清空间与餐饮主题，不用设施数量制造高分。未提供本人温感、味道、卫生、服务体验或疗效，不写亲测。价格、营业时间、票种、时长、具体包含权益、其他配套与分店地址未知；检索返回且对象对应的事实才可引用，失败时说明缺失，不杜撰。不推断每个中心都有SPA、汗蒸、娱乐项目或所有餐次。', 'note_title': '松景庭院+星光泳池，水石清池汤泉逛吃攻略', 'note_body': '水石清池·汤泉生活集庭院、室内水景、汤泉和海鲜自助于一处，适合周末把泡汤、用餐、拍照串联成整日行程。\n\n松景庭院｜入场第一眼\n黑松、白砂枯山水、朱红小桥嵌在青石板水景，背景城市玻璃幕墙，传统格局与都市高楼并置同框，是场所辨识度最高的拍照位。\n\n星光泳池与汤泉泡区｜两种空间分开\n室内泳池顶部星光吊顶映照暖金色水面，汤泉泡池用木格栅屏风、叠石造景和暖调漫射光营造东方格调，两处空间视觉风格各自独立，层次感丰富。\n\n海鲜自助台｜汤泉场所里少见的配置\n展示台可见雪蟹、青口贝、刺身等冷鲜品类，暖棕金属台面配柔光灯带，品类视觉丰盛。具体包含餐次、收费和权益绑定条件未确认，建议提前联系门店核实。\n\n吧台区｜泡汤后的收尾位\n弧形台面、暗调饰面、威士忌陈列，暖光氛围感强，适合汤泉结束后慢坐，饮品单与价格待核实。\n\n价格、票种及具体权益建议提前向门店确认。\n\n有用先收藏，评论区聊聊你的情况。\n#水石清池 #汤泉休闲 #新中式美学 #海鲜自助 #庭院景观 #周末打卡 #松景泳池 #一站式体验', 'title_variants': ['水石清池汤泉，庭院+海鲜自助一站打卡', '新中式汤泉藏庭院，水石清池逛吃全攻略', '庭院松景+海鲜自助，水石清池汤泉值得去'], 'selection_meta': {'candidate_count': 4, 'candidates': [{'blocking': False, 'issue_count': 0, 'origin': 'refine_round_1', 'publishable_prob': 0.934, 'ranker_win_rate': 0.402, 'score': 67.5, 'selector_score': 70.56, 'title': '松景庭院+星光泳池，水石清池汤泉逛吃攻略'}, {'blocking': True, 'issue_count': 2, 'origin': 'refine_round_2', 'publishable_prob': 0.969, 'ranker_win_rate': 0.999, 'score': 75.6, 'selector_score': -48.63, 'title': '水石清池·4区全覆盖，汤泉逛吃新攻略'}, {'blocking': True, 'issue_count': 3, 'origin': 'selector_challenger_1', 'publishable_prob': 0.921, 'ranker_win_rate': 0.549, 'score': 67.9, 'selector_score': -59.51, 'title': '水石清池汤泉｜庭院松景+海鲜自助的闹中取静'}, {'blocking': True, 'issue_count': 1, 'origin': 'arbitrate_initial', 'publishable_prob': 0.652, 'ranker_win_rate': 0.051, 'score': 63.3, 'selector_score': -62.3, 'title': '水石清池汤泉全攻略｜庭院+泳池+海鲜自助'}], 'selected_origin': 'refine_round_1', 'selected_score': 67.5, 'selected_selector_score': 70.56, 'selected_title': '松景庭院+星光泳池，水石清池汤泉逛吃攻略', 'source_correction_count': 0, 'source_corrections_retained': False, 'used_ranker': True, 'viable_count': 1}}
        self.assertEqual(actual["selection_meta"]["selected_origin"], "refine_round_1")
        self.assertEqual(actual["selection_meta"]["selected_score"], 67.5)
        self.assertEqual(actual["selection_meta"]["viable_count"], 1)
        self.assertFalse(api._delivery_integrity_issues(actual["note_title"] + "\n" + actual["note_body"], actual["fact_context"], DOMAIN,
                                                      title_variants=actual["title_variants"]))
        public, notices = api._leisure_public_fact_text(actual["note_body"], actual["fact_context"])
        self.assertIn("两种空间分开", public)
        self.assertIn("两处空间视觉风格各自独立", public)
        self.assertIn("汤泉场所里少见", public)
        self.assertIn("海鲜自助台", public)
        unknown = "门店名：甲店\n只有空间和餐饮照片；价格、地址、权益及实际设施总数未知。"
        for soft in ("两个区域风格不同。", "两个区域，风格不同。", "照片分别展示两个区域。", "两种空间分开。", "两处空间视觉风格各自独立。",
                     "SPA里自助餐少见。", "酒吧这种庭院配置少有。", "KTV里的餐台很罕见。", "汤泉的这种搭配稀缺。",
                     "这组汤泉搭配不多见。", "按两个编辑主题整理素材。"):
            self.assertFalse(api._delivery_integrity_issues(soft, unknown, DOMAIN), soft)
            retained, _ = api._leisure_public_fact_text(soft, unknown)
            self.assertIn(soft.rstrip("。"), retained.replace("\n", ""))
        for hard in ("实际设有两个区域，画面风格不同。", "共有4个空间，视觉风格各异。", "4区全覆盖。",
                     "实际设有4个汤泉区。", "两个汤泉区，呈现两种风格。", "同城唯一组合。", "全城只有这一家。"):
            self.assertTrue(api._delivery_integrity_issues(hard, unknown, DOMAIN), hard)
            self.assertTrue(api._delivery_integrity_issues(hard, api._generation_delivery_source_context(DOMAIN, unknown, hard), DOMAIN), hard)
            self.assertFalse(api._delivery_integrity_issues(hard, "门店名：甲店\n对象：甲店\n" + hard, DOMAIN), hard)
        for hard in ("价格118元。", "位于康定路。", "门票免费包含SPA。", "治失眠。"):
            self.assertTrue(api._delivery_integrity_issues(hard, unknown, DOMAIN), hard)
        self.assertIn("男女用途", api._safe_fact_delivery_brief(DOMAIN, unknown))
        self.assertIn("非视觉来源明确", api._safe_fact_delivery_brief(DOMAIN, unknown))
        for domain in OLD_DOMAINS:
            self.assertNotIn("空间画面风格及少见", api._safe_fact_delivery_brief(domain, unknown))

    def test_relation_families_require_same_object_positive_or_negative_sources(self):
        unknown = "门店名：甲店\n仅有庭院、泳池、格栅画面；布局、声音和区位未知。"
        pairs = (
            ("庭院和泳池整合在同一屋檐下。", "庭院和泳池并不同一屋檐下。"),
            ("泡池区以格栅围出独立小角落。", "泡池区没有独立小角落。"),
            ("泳池区。泡池区。两个实际区域。", "泳池区。泡池区。不存在两个实际区域。"),
            ("庭院连通餐饮区。", "庭院不连通餐饮区。"),
            ("泳池在休息区内。", "泳池不在休息区内。"),
            ("有风声。", "没有风声。"),
            ("播放音乐。", "不播放音乐。"),
            ("风声轻柔。", "风声不轻柔。"),
            ("位于商务区内。", "不在商务区内。"),
            ("地理位置便利。", "地理位置不便利。"),
        )
        for positive, negative in pairs:
            for claim in (positive, negative):
                with self.subTest(claim=claim):
                    self.assertTrue(api._delivery_integrity_issues(claim, unknown, DOMAIN))
                    own = "门店名：甲店\n对象：甲店\n作者确认：" + claim
                    self.assertFalse(api._delivery_integrity_issues(claim, own, DOMAIN), claim)
                    for bad_source in ("门店名：甲店\n对象：乙店\n" + claim,
                                       "门店名：甲店\n对象：甲店\n对象：不是甲店\n" + claim,
                                       "门店名：甲店\n写作要求：\n" + claim,
                                       "门店名：甲店\n对象：甲店\n" + claim.rstrip("。") + "，尚未确认。",
                                       "门店名：甲店\n如果" + claim,
                                       "门店名：甲店\n另一家门店" + claim):
                        self.assertTrue(api._delivery_integrity_issues(claim, bad_source, DOMAIN), bad_source)
                    opposite = negative if claim == positive else positive
                    self.assertTrue(api._delivery_integrity_issues(claim, "作者确认：" + opposite, DOMAIN), (claim, opposite))
        for allowed in ("两类画面风格不同。", "照片里可见原木格栅和蓝调泳池。", "格栅映衬泡池，画面静谧雅致。",
                        "泳池区。泡池区。两个区域风格不同。", "泳池区与泡池区，两个区域风格不同，开放时段建议确认。",
                        "建议先拍庭院再拍泳池。", "建议确认位置和交通是否便利。", "风声是否轻柔需要确认。"):
            self.assertFalse(api._delivery_integrity_issues(allowed, unknown, DOMAIN), allowed)
        for source in ("城市：上海。", "图中高楼与庭院可见。", "门店地址：康定路358弄。", "商圈：曹家渡。"):
            self.assertTrue(api._delivery_integrity_issues("地理位置便利。", source, DOMAIN), source)
        self.assertTrue(api._delivery_integrity_issues("商务区内。", "商务区附近。", DOMAIN))
        self.assertTrue(api._delivery_integrity_issues("风声比街上更轻柔。", "作者确认有风声。", DOMAIN))
        for theme in ("KTV音乐空间聚会攻略。", "以音乐为主题整理KTV选歌参考。",
                      "音乐聚会的曲目选择参考。", "想把音乐内容整理成一份KTV选歌清单。"):
            self.assertFalse(api._delivery_integrity_issues(theme, unknown, DOMAIN), theme)
        for sound in ("本店播放音乐。", "在KTV听到音乐。", "音乐声很轻柔。", "本店有音乐。"):
            self.assertTrue(api._delivery_integrity_issues(sound, unknown, DOMAIN), sound)
            self.assertFalse(api._delivery_integrity_issues(sound, "作者确认：" + sound, DOMAIN), sound)
        self.assertTrue(api._delivery_integrity_issues("庭院和泳池在同一屋檐下。", "作者确认这是综合洗浴中心，含庭院和泳池。", DOMAIN))

        for place in ("商务区", "CBD", "市中心", "商圈"):
            self.assertTrue(api._delivery_integrity_issues("位于" + place + "。", "作者确认靠近" + place + "。", DOMAIN), place)
            self.assertTrue(api._delivery_integrity_issues("不在" + place + "。", "作者确认位于" + place + "。", DOMAIN), place)
        self.assertTrue(api._delivery_integrity_issues("白天有风声。", "作者确认晚上有风声。", DOMAIN))
        self.assertTrue(api._delivery_integrity_issues("我听到风声。", "朋友听到风声。", DOMAIN))
        self.assertFalse(api._delivery_integrity_issues("泳池在休息区内。", "作者确认休息区内有泳池。", DOMAIN))
        self.assertTrue(api._delivery_integrity_issues("照片里格栅围出独立小角落。", unknown, DOMAIN))
        self.assertFalse(api._delivery_integrity_issues("照片分别展示两个区域。", unknown, DOMAIN))

        for claim in ("泡池区以原木格栅围出独立小角落，具体区域开放时段建议到店确认。",
                      "室内分两个汤泉区，开放时段待确认。"):
            self.assertTrue(api._delivery_integrity_issues(claim, unknown, DOMAIN), claim)
        self.assertTrue(api._delivery_integrity_issues("两个区域，开放时段待确认。", "区域数量未知。", DOMAIN))

    def test_spatial_backreferences_stay_in_this_observation_block(self):
        source = "作者确认泳池区和泡池区是两个实际区域。"
        text = "场景：泳池区。泡池区。两个实际区域。"
        self.assertFalse(api._delivery_integrity_issues(text, source, DOMAIN))
        safe, notices = api._leisure_public_fact_text(text, source)
        self.assertFalse(notices)
        self.assertIn("两个实际区域", safe)
        # A different image cannot provide the missing subject for this image's
        # count, nor can known style groups establish real facility quantities.
        separate = "图1：场景：泳池区与泡池区\n图2：场景：两个实际区域。"
        self.assertTrue(api._delivery_integrity_issues(separate, source, DOMAIN))
        self.assertTrue(api._delivery_integrity_issues(text, "泳池区和泡池区呈现两种画面风格。", DOMAIN))
        self.assertFalse(api._delivery_integrity_issues("汤泉区。两个实际区域。", "作者确认实际有两个汤泉区。", DOMAIN))
        self.assertFalse(api._delivery_integrity_issues("两个区域风格不同。", "只有图片，区域数量未知。", DOMAIN))
        self.assertFalse(api._delivery_integrity_issues("泳池区和泡池区。这些区域互通。", "泳池区和泡池区互通。", DOMAIN))
        self.assertTrue(api._delivery_integrity_issues("泳池区和泡池区。这些区域互通。", "泳池区和餐饮区互通。", DOMAIN))
        own = "门店名：甲店\n对象：甲店\n泳池区与泡池区。\n对象：乙店\n两个区域。"
        self.assertTrue(api._delivery_integrity_issues(text, own, DOMAIN))

    def test_leisure_media_prompt_clarifies_only_still_image_claims(self):
        for domain in (DOMAIN, "美食"):
            with mock.patch.object(api, "_read_image_input", return_value=b"offline-fixture"), \
                 mock.patch.object(api._ark_media, "image_part", return_value={"offline": True}), \
                 mock.patch.object(api._ark_media, "chat", return_value="可见光线与池景") as chat:
                api._kimi_vision_understand("fixture", domain, "材料说明")
            prompt = chat.call_args.args[0]
            self.assertEqual("照片不可听" in prompt, domain == DOMAIN)
            self.assertEqual("实际区域数量" in prompt, domain == DOMAIN)
            self.assertEqual("温暖治愈/精致高级/活力有趣/沉浸享受" in prompt, domain != DOMAIN)
            with mock.patch.object(api, "_runtime_prompt", return_value="视觉原模板{domain}"), \
                 mock.patch.object(api._mr, "call", new=mock.AsyncMock(return_value="可见光线")) as model:
                asyncio.run(api._gent_visual(None, domain, "已有材料", {}))
            self.assertEqual("照片不可听" in model.call_args.args[1], domain == DOMAIN)

    def test_public_fact_checks_do_not_change_legacy_features_or_other_domains(self):
        source = "门店名：甲店\n地址：康定路358弄。\n价格：人均116元。"
        features = {"body_has_price": 1, "body_has_address": 1}
        for body, price, address in (("建议确认票价与分店地址。", False, False),
                                      ("地址：康定路358弄，人均116元。", True, True),
                                      ("地址在康定路358弄，人均116元。", True, True),
                                      ("地址在康定路358弄99室，人均116元。", True, False),
                                      ("位于康定路，人均118元。", False, True),
                                      ("位于南京西路，人均116元。", True, False)):
            hits = api._generation_public_feature_hits("休闲场景参考攻略", body, features, 73, DOMAIN, source)
            self.assertEqual((hits["has_price"], hits["has_address"]), (price, address), body)
        for known, quoted, expected in (("116.5元", "116.9元", False),
                                        ("116.50元", "116.5元", True),
                                        ("￥116.5元", "￥116.9元", False),
                                        ("￥116.50元", "116.5元", True),
                                        ("116元/人", "116元/晚", False),
                                        ("116元/人", "116元/人", True)):
            hits = api._generation_public_feature_hits("休闲场景参考攻略", "价格：" + quoted + "。", features, 73, DOMAIN,
                                                       "门店名：甲店\n价格：" + known + "。")
            self.assertEqual(hits["has_price"], expected, (known, quoted))
        long_address = "广州市天河区珠江新城花城广场东侧某某商业街道123号"
        self.assertTrue(api._generation_public_feature_hits("休闲场景参考攻略", "地址：" + long_address + "。", features, 73, DOMAIN,
                                                           "门店名：甲店\n地址：" + long_address)["has_address"])
        for bad_source in ("门店名：甲店\n对象：乙店\n价格：人均116元。\n地址：康定路358弄。",
                           "门店名：甲店\n写作要求：\n价格：人均116元。\n地址：康定路358弄。",
                           "门店名：甲店\n价格：人均116元未知。\n地址：康定路358弄未确认。"):
            hits = api._generation_public_feature_hits("休闲场景参考攻略", "地址在康定路358弄，人均116元。", features, 73, DOMAIN, bad_source)
            self.assertFalse(hits["has_price"])
            self.assertFalse(hits["has_address"])
        for domain in ("美食", "旅行", "穿搭", "母婴", "健身", "美妆", "职场"):
            self.assertEqual(api._generation_public_feature_hits("标题", "待确认地址和价格", features, 73, domain, ""),
                             api._feature_hits_for_generation("标题", features, 73, domain, body="待确认地址和价格"))
        self.assertEqual(features, {"body_has_price": 1, "body_has_address": 1})

    def test_actual_amap_location_fields_support_only_same_merchant_exact_places(self):
        # Retained real PARLAY supplier fields assembled through the normal
        # formatter; this offline fixture does not invoke a provider or model.
        enrichment = {'provider': 'amap', 'query': '上海 PARLAY 地址 营业时间 项目 价格 预约', 'facts': {'address': '康定路358弄陕康里18弄103室', 'business_area': '曹家渡', 'price': '人均116元', 'rating': '高德评分4.6'}, 'entities': [{'name': 'Parlay帕雷餐厅＆运动酒吧(静安店)', 'facts': {'address': '康定路358弄陕康里18弄103室', 'business_area': '曹家渡', 'price': '人均116元', 'rating': '高德评分4.6'}, 'source': '高德地图', 'url': 'amap://poi/B0KDZ1P847'}], 'sources': [{'title': 'Parlay帕雷餐厅＆运动酒吧(静安店)', 'source': '高德地图', 'url': 'amap://poi/B0KDZ1P847'}], 'calls': {'partial_errors': []}}
        brief = "门店名：Parlay帕雷餐厅运动酒吧(静安店)\n城市：上海。"
        source = api._generation_delivery_source_context(DOMAIN, api._append_fact_enrichment(brief, enrichment), "")
        for claim in ("门店位于康定路358弄陕康里18弄103室。", "位于康定路。", "位于曹家渡商圈。",
                      "地址：康定路358弄陕康里18弄103室。", "高德显示人均116元、评分4.6。"):
            self.assertFalse(api._delivery_integrity_issues(claim, source, DOMAIN), claim)
        public_hits = api._generation_public_feature_hits("PARLAY场景参考攻略", "位于康定路，人均116元。", {"body_has_price": 1, "body_has_address": 1}, 73, DOMAIN, source)
        self.assertTrue(public_hits["has_price"])
        self.assertTrue(public_hits["has_address"])
        for claim in ("位于南京西路。", "位于定路。", "临近康定路。", "靠近曹家渡商圈。",
                      "位于曹家商圈。", "CBD旁的酒吧。", "人均118元。"):
            self.assertTrue(api._delivery_integrity_issues(claim, source, DOMAIN), claim)
        for unsupported_source in ("地址：康定路附近。", "地址：位于康定路附近。", "地址：距康定路100米。",
                                   "地址：康定路358弄，待确认。", "地址：可能位于康定路。",
                                   "地址：康定路，不是本店地址。",
                                   "地址：康定路未知。", "地址：并非康定路。", "地址：没有康定路。",
                                   "请写地址：康定路。", "希望地址：康定路。", "地址：照片中位于康定路。"):
            self.assertTrue(api._delivery_integrity_issues("位于康定路。", brief + "\n" + unsupported_source, DOMAIN), unsupported_source)
        for unsupported_source in ("商圈：曹家渡附近。", "商圈：曹家渡待确认。", "商圈：曹家渡，待核实。", "请写商圈：曹家渡。"):
            self.assertTrue(api._delivery_integrity_issues("位于曹家渡商圈。", brief + "\n" + unsupported_source, DOMAIN), unsupported_source)
        foreign = {**enrichment, "entities": [{"name": "另一家酒吧", "facts": enrichment["facts"]}]}
        foreign_source = api._append_fact_enrichment(brief, foreign)
        self.assertTrue(api._delivery_integrity_issues("位于康定路。", foreign_source, DOMAIN))
        self.assertTrue(api._delivery_integrity_issues("位于曹家渡商圈。", foreign_source, DOMAIN))
        no_objects = api._facts.format_fact_context({**enrichment, "entities": []})
        self.assertTrue(api._delivery_integrity_issues("位于康定路。", brief + "\n\n" + no_objects, DOMAIN))
        self.assertTrue(api._delivery_integrity_issues("位于康定路。", no_objects, DOMAIN))
        self.assertFalse(api._delivery_integrity_issues("位于康定路。", brief + "\n地址：康定路358弄。", DOMAIN))
        visual_only = api._generation_delivery_source_context(DOMAIN, brief, api._facts.format_fact_context(enrichment))
        self.assertTrue(api._delivery_integrity_issues("位于康定路。", visual_only, DOMAIN))
        self.assertTrue(api._delivery_integrity_issues("位于曹家渡商圈。", visual_only, DOMAIN))
        self.assertFalse(api._delivery_integrity_issues("位于上海市静安区康定路。", "地址：上海市静安区康定路358弄。", DOMAIN))
        self.assertTrue(api._delivery_integrity_issues("位于康定路。", "地址：上海市静安区康定路358弄。", DOMAIN))
        for unsupported_source in (
            "门店名：甲店\n【联网事实补全】\n地址：康定路358弄\n对象：乙店\n地址：康定路358弄\n对象：甲店\n商圈：曹家渡",
            "门店名：甲店\n对象：甲店\n商圈：曹家渡\n对象：不是甲店\n地址：康定路358弄",
            "对象：需要确认\n地址：康定路358弄",
            "对象：甲店\n地址：康定路358弄\n对象：乙店\n商圈：曹家渡",
            "门店名：甲店\n写作要求：\n地址：康定路。",
            "门店名：甲店\n对象：甲店\n来源：\n地址：康定路358弄",
        ):
            self.assertTrue(api._delivery_integrity_issues("位于康定路。", unsupported_source, DOMAIN), unsupported_source)
        self.assertTrue(api._delivery_integrity_issues("位于府中路。", "门店名：甲店\n地址：市府中路123号", DOMAIN))
        self.assertFalse(api._delivery_integrity_issues("位于市府中路。", "门店名：甲店\n地址：市府中路123号", DOMAIN))

    def test_spatial_counts_entrance_and_circulation_keep_source_scope(self):
        unknown = "仅展示庭院、水景座位、室内水池、餐台和饮品柜台；空间数量、入口及动线未知。"
        for claim in ("双区汤泉攻略。", "2区汤泉攻略。", "二区汤泉攻略。", "室内分两个汤泉区，风格各走一路。", "汤泉分为两区。",
                      "一进门是整片禅意庭院。", "入口连接庭院。", "庭院连通餐饮区。",
                      "动线清晰，不需要反复移场。"):
            with self.subTest(claim=claim):
                issues = api._delivery_integrity_issues(claim, unknown, DOMAIN)
                self.assertTrue(any("空间布局" in issue for issue in issues), claim)
                self.assertTrue(api._has_blocking_quality_issues(95, issues, DOMAIN))
                self.assertFalse(api._delivery_integrity_issues(claim, "作者确认：" + claim, DOMAIN), claim)
        for source, claim in (("室内有两个汤泉区。", "双区汤泉攻略。"),
                              ("作者确认：这里实际设有两个汤泉区。", "双区汤泉攻略。"),
                              ("作者确认：这里实际设有两个汤泉区。", "两个实际汤泉区。"),
                              ("两个实体汤泉区。", "2区汤泉攻略。"),
                              ("十三个汤泉区。", "13区汤泉攻略。"),
                              ("餐饮区连通庭院。", "庭院连通餐饮区。")):
            self.assertFalse(api._delivery_integrity_issues(claim, source, DOMAIN), (source, claim))
        for source, claim in (("室内有三个汤泉区。", "双区汤泉攻略。"),
                              ("两张照片展示不同池景风格。", "室内分两个汤泉区。"),
                              ("两种汤泉画面风格。", "双区汤泉攻略。"),
                              ("三个实际汤泉区。", "两个实际汤泉区。"),
                              ("一个汤泉区。", "十一区汤泉攻略。"),
                              ("照片分别展示两个汤泉区。", "双区汤泉攻略。"),
                              ("没有两个汤泉区。", "双区汤泉攻略。"),
                              ("不存在两个汤泉区。", "双区汤泉攻略。"),
                              ("请写室内有两个汤泉区。", "双区汤泉攻略。"),
                              ("门店名称：双区汤泉。", "双区汤泉攻略。"),
                              ("入口通向庭院。", "入口是庭院。"),
                              ("入口是庭院。", "入口是大厅。"),
                              ("庭院连通餐饮区。", "庭院连通休息区。"),
                              ("汤泉区动线清晰。", "餐饮区动线清晰。")):
            self.assertTrue(api._delivery_integrity_issues(claim, source, DOMAIN), (source, claim))
        for allowed in ("按庭院、水池、餐台三个编辑主题组织正文。", "按3个编辑主题整理素材。", "画面分为3个分组。",
                        "素材有两张汤泉区照片，呈现两种池景视觉风格。", "建议先拍庭院，再拍水景座位与餐台。",
                        "下次计划进门后先拍庭院。", "按图1到图3的拍摄顺序整理素材。",
                        "如果实际有两个汤泉区，确认后再按心情选择。", "画面入口处是庭院造景。",
                        "空间数量、入口位置和实际通行关系需要确认。"):
            self.assertFalse(api._delivery_integrity_issues(allowed, unknown, DOMAIN), allowed)
        self.assertFalse(api._leisure_observation_fact_claims("一进门是庭院。")["visit"])
        self.assertTrue(api._delivery_integrity_issues("两个汤泉区，呈现两种风格。", unknown, DOMAIN))

    def test_subjectless_sound_and_implicit_completed_visits_are_not_visual_moods(self):
        unknown = "仅有空间照片；作者到访、声音和个人感受未知。"
        for claim in ("安静得出乎预料。", "比想象中更安静。", "没想到这里这么安静。", "闹中取静。", "照片里很安静。",
                      "进门后就发现环境很安静。", "泡完后觉得很舒服。", "一篇实地参考清单。"):
            with self.subTest(claim=claim):
                self.assertTrue(api._delivery_integrity_issues(claim, unknown, DOMAIN), claim)
                if "照片" not in claim:
                    self.assertFalse(api._delivery_integrity_issues(claim, "作者确认：" + claim, DOMAIN), claim)
        self.assertFalse(api._delivery_integrity_issues("安静得出乎预料。", "作者说没想到环境这么安静。", DOMAIN))
        self.assertTrue(api._delivery_integrity_issues("安静得出乎预料。", "作者说环境安静。", DOMAIN))
        self.assertTrue(api._delivery_integrity_issues("安静。", "照片中环境安静。", DOMAIN))
        for allowed in ("静谧雅致的画面与暖黄灯光。", "宁静的视觉效果适合留白构图。",
                        "画面呈现闹中取静的视觉意象。", "图片氛围安静高级。", "都市休闲空间的木调风格。",
                        "下次计划进门后看看庭院。", "建议先拍庭院再拍餐台。", "计划写实地参考清单。",
                        "同一次来可以按已确认的项目安排自己的拍摄主题。", "我没有去过，不写亲测。"):
            self.assertFalse(api._delivery_integrity_issues(allowed, unknown, DOMAIN), allowed)
        self.assertTrue(api._delivery_integrity_issues("这次进门后就发现庭院。", "朋友进门后就发现庭院。", DOMAIN))

    def test_food_qualifiers_keep_this_image_field_scope_and_reset(self):
        unknown = "素材只有海鲜展示和庭院照片；食材状态未知。"
        unsafe = "图9（深度）：场景：海鲜自助展示\n核心元素：海鲜，银质餐盆，透亮碎冰，精致摆盘，丰富鲜活\n视觉亮点：海鲜餐台"
        self.assertTrue(api._delivery_integrity_issues(unsafe, unknown, DOMAIN))
        self.assertFalse(api._delivery_integrity_issues(unsafe, "作者确认海鲜鲜活。", DOMAIN))
        safe, notices = api._leisure_public_fact_text(unsafe, unknown)
        self.assertNotIn("鲜活", safe)
        for visible in ("海鲜", "银质餐盆", "透亮碎冰", "精致摆盘"):
            self.assertIn(visible, safe)
        self.assertTrue(notices)
        for visual in ("图1：场景：海鲜展示\n核心元素：银盘\n图2：场景：庭院\n核心元素：鲜活色彩，暖灯",
                       "场景：海鲜餐台\n核心元素：银盘\n场景：庭院\n核心元素：鲜活色彩，白砂",
                       "海鲜餐台可见。\n\n庭院的画面鲜活，暖灯清晰。",
                       "场景：海鲜展示\n核心元素：画面鲜活，精致摆盘，视觉新鲜感"):
            self.assertFalse(api._delivery_integrity_issues(visual, unknown, DOMAIN), visual)
            public, notices = api._leisure_public_fact_text(visual, unknown)
            self.assertEqual(notices, [], visual)
            self.assertIn("鲜活", public)

    def test_selector_rejects_high_score_unsupported_spatial_candidate(self):
        candidates = [{"origin": "unsafe", "title": "双区汤泉空间参考", "body": "室内分两个汤泉区，动线清晰。", "variants": ["双区汤泉攻略"]},
                      {"origin": "visible", "title": "庭院池景素材参考", "body": "按庭院、水池、餐台三个编辑主题组织正文。", "variants": []}]
        async def fit(title, *_args, **_kwargs):
            return title
        with mock.patch.object(api, "_fit_title_limit", side_effect=fit), \
             mock.patch.object(api, "_score_generated_note", new=mock.AsyncMock(return_value=(95, {}, "优秀"))), \
             mock.patch.object(api, "_generated_quality_issues", side_effect=lambda *_args, **_kwargs: []), \
             mock.patch.object(api, "_v04_publishable_probability", return_value=None), \
             mock.patch.object(api, "get_v04_preference_ranker", return_value=None):
            result = asyncio.run(api._select_best_generation_candidate(candidates, domain=DOMAIN, local_time="2026101412",
                source_context="只展示庭院、水池和餐台；布局未知。"))
        self.assertEqual(result["selected"]["origin"], "visible")
        self.assertEqual(result["viable_count"], 1)

    def test_stream_quality_repair_restates_only_leisure_fact_policy(self):
        raw = "<title>庭院素材创作参考</title><body>庭院和水池可见。</body><variants>庭院场景参考</variants><rationale>素材取舍</rationale>"
        for domain in (DOMAIN, "美食"):
            captured = []
            async def model(_task, system, user, **kwargs):
                if kwargs.get("trace_step") == "generation_quality_repair":
                    captured.append((system, user))
                return raw
            async def stream(*_args, **_kwargs):
                yield "content", raw
            async def shape(_title, value, *_args, **_kwargs):
                return value
            async def fit(title, *_args, **_kwargs):
                return title
            with mock.patch.object(api, "_runtime_prompt", return_value="原始模板{domain}"), \
                 mock.patch.object(api._mr, "call", side_effect=model), \
                 mock.patch.object(api._mr, "stream", side_effect=stream), \
                 mock.patch.object(api, "_fit_title_limit", side_effect=fit), \
                 mock.patch.object(api, "_shape_body_for_delivery", side_effect=shape), \
                 mock.patch.object(api, "_generation_candidate_count", return_value=1), \
                 mock.patch.object(api, "_predict", side_effect=RuntimeError("offline prompt test")), \
                 mock.patch.object(api, "_score_generated_note", new=mock.AsyncMock(return_value=(95, {}, "优秀"))), \
                 mock.patch.object(api, "_generated_quality_issues", side_effect=lambda *_args, **_kwargs: ["标题偏短"]), \
                 mock.patch.object(api, "_needs_v04_score_lift", return_value=False), \
                 mock.patch.object(api, "_find_weaknesses", return_value=[]), \
                 mock.patch.object(api, "_build_fix_instructions", return_value=[]), \
                 mock.patch.object(api._clarification, "pause"), \
                 mock.patch.object(api.asyncio, "sleep", new=mock.AsyncMock()):
                async def run():
                    generator = api._generate_pipeline_stream(domain, "素材有庭院和水池；实际体验未知。", None,
                        None, {}, None, "2026101412")
                    try:
                        async for _event in generator:
                            if captured:
                                break
                    finally:
                        await generator.aclose()
                asyncio.run(run())
            self.assertTrue(captured, domain)
            system, user = captured[0]
            self.assertEqual("【休闲娱乐体验事实安全策略】" in system, domain == DOMAIN)
            self.assertEqual("【休闲娱乐体验表达要求】" in system, domain == DOMAIN)
            self.assertEqual("上方当前标题与正文是待修模型草稿" in user, domain == DOMAIN)

    def test_actual_ad_full_report_cannot_pass_the_shared_fact_gate(self):
        # Exact retained public projection from real saved note5f0811a9; this
        # offline shadow is regression evidence, never a new live acceptance.
        source = '【本次用户创作简报；不是外部独立核验】\n本轮素材来自广州水石清池·汤泉生活。作者确认这是含洗浴、水疗、自助餐的大型综合休闲项目；本次9张图仅展示庭院与水景座位、室内水池、海鲜自助展示和饮品柜台。围绕这些真实区域整理一篇可收藏的休闲体验参考，正文覆盖多张相关素材，分清空间与餐饮主题，不用设施数量制造高分。未提供本人温感、味道、卫生、服务体验或疗效，不写亲测。价格、营业时间、票种、时长、具体包含权益、其他配套与分店地址未知；检索返回且对象对应的事实才可引用，失败时说明缺失，不杜撰。不推断每个中心都有SPA、汗蒸、娱乐项目或所有餐次。'
        title = '水石清池双区汤泉＋禅庭＋海鲜自助攻略'
        body = '一进门是整片禅意庭院，青松造景配白砾石铺地，朱红小桥架在流水松景里，安静得出乎预料。值得拍照。\n\n室内分两个汤泉区，风格各走一路。暖金柔光汤泉区配星光吊顶，池水清透，石质墙面沉稳，整体偏开阔明亮；暗调奢石汤泉区则是黄铜暖光搭木格栅，深色石材，灯光收敛，氛围更私密内敛，两个汤泉区风格差异明显，同一次来可以感受两种完全不同的汤泉体验。按心情选区。\n\n海鲜自助台铺满碎冰，冰鲜海鲜一整排展开，暖调灯光下摆盘整齐，适合汤泉结束后直接落座用餐，一站解决饭局，不用另找地方。饮品吧台区暖金弧形台面配环形灯带，深色肌理，坐下来趁汤泉结束前点一杯，节奏刚好。\n\n这家适合带家人或朋友半日消磨：禅意庭院打卡拍照，双区汤泉各取风格，海鲜自助收尾，动线清晰，不需要反复移场，对亲子或多人出行比较友好。不带娃的两人组也适合。\n\n有用先收藏，评论区聊聊你的情况。\n#广州汤泉 #水石清池 #双区汤泉 #禅意庭院 #海鲜自助 #广州周末休闲 #广州洗浴'
        variants = ['水石清池｜双区汤泉＋禅意庭院＋海鲜自助', '广州水石清池｜双区汤泉＋海鲜自助攻略', '水石清池双区汤泉＋海鲜自助半日玩法']
        cover = '缺少地理区位来源依据，已省略相关建议。\n医疗功效表述不适用休闲内容，已省略相关建议。\n缺少温感/味道/卫生/服务/声音体验来源依据，已省略相关建议。\n【主图】\n核心元素：青松造景，白砾石，黑石板，朱红小桥，侘寂静谧，流水庭院\n爆文角度：广州禅意汤泉庭院打卡攻略\n视觉亮点：红桥嵌在松庭里\n【其余8张素材图】\n图2（深度）：场景：广州水石清池·汤泉暖调静谧的轻奢室内泳池空间\n核心元素：暖金柔光，星光吊顶，静谧池水，石质墙面，奢雅质感，松弛氛围\n情绪基调：精致高级，沉浸享受\n爆文角度：汤泉打卡休闲清单\n视觉亮点：星光沉水泳池\n图3（深度）：藏在都市里的禅意庭院，闹中取静太适合放松\n松景,黑瓦白砂,太湖石,原木立柱,玻璃窗,新中式禅意\n静谧高级，松弛惬意\n黑松禅意枯山水景\n图4（深度）：场景：氛围感满满的海鲜自助区，暖光衬得餐台精致诱人\n核心元素：深棕质感台面，冷鲜海鲜，暖调灯光，石质肌理，餐盘堆叠，静谧高端\n情绪基调：精致高级，沉浸式享食氛围\n爆文角度：水石清池自助逛吃攻略\n图5（深度）：暖调柔光笼罩雅致汤泉室内泡池空间\n温润木色,质感石质,柔光格栅,清透汤泉,整洁雅致,松弛氛围\n广州汤泉休闲好去处\n木格栅汤池氛围感拉满\n图6（深度）：场景：暖光鎏金质感的汤泉休闲吧台空间氛围感拉满\n核心元素：暖金光泽，深色肌理材质，弧形吧台，环形灯带，藏酒陈列，松弛高级感\n情绪基调：精致高级，沉浸享受\n爆文角度：广州汤泉休闲打卡攻略\n视觉亮点：暖金弧形质感吧台\n图7（深度）：场景：暖光包裹的质感室内汤泉，静谧松弛的都市休闲空间\n核心元素：暗调奢石，黄铜暖光，粼粼汤泉，造景山石，温润氛围，整饬整洁\n爆文角度：广州汤泉躺平好去处清单\n视觉亮点：暖光粼粼的质感汤池\n闹中取静\n核心元素：黛瓦红桥，迎客松，白石枯山水，暖光石灯，静谧松弛，新中式质感\n爆文角度：广州汤泉庭院打卡参考\n视觉亮点：红桥映禅意庭院\n图9（深度）：场景：广州水石清池汤泉，海鲜自助区摆满冰鲜海鲜盛宴\n核心元素：冰鲜海鲜，银质餐盆，透亮碎冰，暖光氛围感，精致摆盘，丰富鲜活\n情绪基调：精致奢享，诱人满足\n爆文角度：汤泉海鲜自助打卡攻略\n视觉亮点：满台豪华冰鲜海鲜'
        opinions = [{'confidence': 0.0, 'evidence': [], 'evidence_binding': '', 'impact': '缺少地理区位来源依据，已省略相关建议。\n医疗功效表述不适用休闲内容，已省略相关建议。\n缺少价格/收费来源依据，已省略相关建议。', 'opinion': '可见元素：青松造景（修剪整齐的松树群）、白色细砾石铺装地面、黑色石板路径、朱红色小木桥跨越水景、流水景观。\n构图采用纵深视角，红桥作前景焦点，松树和水景层次递进。\n光线为自然日光，营造清晰的影调对比。\n色彩对比明显：深绿松色、白砾石、黑石板、朱红桥色。\n整体呈现日式庭园的简约美学特征，空间开阔但视线引导清晰。', 'reason': '缺少地理区位来源依据，已省略相关建议。\n医疗功效表述不适用休闲内容，已省略相关建议。\n缺少价格/收费来源依据，已省略相关建议。', 'role': '视觉专家', 'suggestions': ['**切入点1：「打卡攻略」角度**', '红桥 + 松庭的视觉焦点\n适合写：庭院具体位置、最佳拍摄角度、光线时段选择、必拍景点组合、到店流程与开放区域。\n读者价值是明确知道怎么去、怎么拍、花多少时间。', '**切入点2：「休闲体验」角度**', '聚焦庭院作为汤泉空间的松弛感受。\n适合写：泡汤前后的庭院散步、视觉氛围如何缓解都市压力、庭院与汤泉的体验链路、适合什么时段来（午后/傍晚/周末）、配套休息空间。']}, {'confidence': 0.0, 'evidence': [], 'evidence_binding': '', 'impact': '医疗功效表述不适用休闲内容，已省略相关建议。\n缺少相关事实来源依据，已省略相关建议。\n缺少常态或时段客流来源依据，已省略相关建议。\n**发布时机建议**：\n- 当前无新鲜热词数据支撑特定时段优势（时机系数 1.0）\n- **建议**：根据商家实际客流和平台发布规律自主判断，暂无强时机约束', 'opinion': '**核心词融入策略**：\n- **主词**：汤泉、禅意、庭院、广州（地域）、打卡、松弛、海鲜自助\n- **融入位置**：\n- 标题：汤泉、禅意、庭院、海鲜自助（自然组合，无堆砌）\n- 一段：禅意庭院、闹中取静、松弛（场景氛围）\n- 二段：室内水景、汤泉、精致高级（空间体验）\n- 三段：海鲜自助、逛吃（餐饮体验）', 'reason': '医疗功效表述不适用休闲内容，已省略相关建议。\n缺少相关事实来源依据，已省略相关建议。\n缺少常态或时段客流来源依据，已省略相关建议。\n**发布时机建议**：\n- 当前无新鲜热词数据支撑特定时段优势（时机系数 1.0）\n- **建议**：根据商家实际客流和平台发布规律自主判断，暂无强时机约束', 'role': '增长专家', 'suggestions': ['**核心词融入策略**：', '**主词**：汤泉、禅意、庭院、广州（地域）、打卡、松弛、海鲜自助', '**融入位置**：', '标题：汤泉、禅意、庭院、海鲜自助（自然组合，无堆砌）']}, {'confidence': 0.0, 'evidence': [], 'evidence_binding': '', 'impact': '缺少地理区位来源依据，已省略相关建议。', 'opinion': '从禅意庭院到海鲜自助，每个角落都是松弛感——一篇实地参考清单。', 'reason': '缺少地理区位来源依据，已省略相关建议。', 'role': '用户专家', 'suggestions': []}]
        issues = api._delivery_integrity_issues(title + "\n" + body, source, DOMAIN, title_variants=variants)
        self.assertTrue(api._has_blocking_quality_issues(95, issues, DOMAIN))
        self.assertTrue(any("空间布局" in issue for issue in issues))
        self.assertTrue(any("感官" in issue for issue in issues))
        self.assertTrue(all(any(f"备选标题{i}：" in issue for issue in issues) for i in range(1, 4)))
        self.assertTrue(api._leisure_public_fact_issues(cover, source))
        original = json.dumps(opinions, ensure_ascii=False)
        public_cover = api._generation_public_visual_summary(cover, source, DOMAIN)
        public_experts = api._generation_public_expert_opinions(opinions, source, DOMAIN)
        public_progress = api._generation_public_progress_event({"type": "expert_opinion", "content": cover, "detail": opinions[-1]["opinion"]}, source, DOMAIN)
        for value in (public_cover, public_experts, public_progress):
            encoded = json.dumps(value, ensure_ascii=False)
            for unsupported in ("丰富鲜活", "闹中取静", "实地参考清单"):
                self.assertNotIn(unsupported, encoded)
        for visible in ("侘寂静谧", "透亮碎冰", "银质餐盆", "精致摆盘", "暖金柔光", "静谧松弛"):
            self.assertIn(visible, public_cover)
        self.assertEqual(json.dumps(opinions, ensure_ascii=False), original)
        contaminated = api._generation_delivery_source_context(DOMAIN, source, cover + "\n" + body)
        self.assertTrue(api._delivery_integrity_issues(title + "\n" + body, contaminated, DOMAIN, title_variants=variants))

    def test_public_experts_omit_unknown_claims_and_preserve_internal_drafts(self):
        original = [{"role": "视觉专家", "raw": (
            "<scene>庭院有白砂与木桥，位于CBD旁。光线暖黄。</scene>"
            "<hooks>CBD隐藏禅意庭院\n城市禅意空间对比</hooks>"
        )}, {"role": "用户专家", "opinion": "被闹市包围的休闲场所。", "reason": "白天下午人少。",
             "suggestions": ["用木桥与庭院作开头。", "宣传周末无需排队。"]}]
        before = json.dumps(original, ensure_ascii=False)
        source = "广州，地址与客流时段未知。画面有庭院、白砂、木桥与暖黄光线。"
        for category in ("洗浴汗蒸", "按摩足疗SPA", "KTV", "酒吧"):
            with self.subTest(category=category):
                public = api._generation_public_expert_opinions(original, f"类型：{category}。{source}", DOMAIN)
                encoded = json.dumps(public, ensure_ascii=False)
                for unsupported in ("CBD", "闹市", "白天下午人少", "周末无需排队"):
                    if category in {"KTV", "酒吧"} and unsupported in {"白天下午人少", "周末无需排队"}:
                        self.assertIn(unsupported, encoded)
                    else:
                        self.assertNotIn(unsupported, encoded)
                for supported in ("木桥", "光线暖黄", "缺少地理区位来源依据", "缺少常态或时段客流来源依据"):
                    if category in {"KTV", "酒吧"} and supported == "缺少常态或时段客流来源依据":
                        self.assertNotIn(supported, encoded)
                    else:
                        self.assertIn(supported, encoded)
                self.assertEqual(public[0]["evidence"], [])
                self.assertIn("城市禅意空间对比", public[0]["suggestions"])
        self.assertEqual(json.dumps(original, ensure_ascii=False), before)

    def test_public_experts_keep_source_scope_and_reject_visual_authority(self):
        opinion = {"role": "视觉专家", "raw": "<scene>庭院有木桥，位于CBD旁。</scene><hooks>CBD旁休闲空间</hooks>"}
        supported = api._generation_public_expert_opinions([opinion], "商家位于CBD旁。", DOMAIN)
        self.assertIn("CBD旁", json.dumps(supported, ensure_ascii=False))
        contaminated = api._generation_delivery_source_context(DOMAIN, "广州，地址未知。", "位于CBD旁。")
        unknown = api._generation_public_expert_opinions([opinion], contaminated, DOMAIN)
        self.assertNotIn("CBD", json.dumps(unknown, ensure_ascii=False))
        self.assertIn("木桥", json.dumps(unknown, ensure_ascii=False))

    def test_public_medical_advice_is_omitted_even_with_repeated_source(self):
        opinion = {"role": "用户专家", "opinion": "颂钵理疗区有理疗床。", "evidence": ["SPA可以改善睡眠质量。"],
                   "suggestions": ["推荐给颈肩容易僵紧的人。", "可以按实际空间描述放松氛围。"]}
        public = api._generation_public_expert_opinions([opinion], "颂钵理疗区有理疗床。SPA可以改善睡眠质量。", DOMAIN)
        encoded = json.dumps(public, ensure_ascii=False)
        for unsafe in ("改善睡眠质量", "颈肩容易僵紧"):
            self.assertNotIn(unsafe, encoded)
        for safe in ("医疗功效表述不适用休闲内容", "理疗床", "放松氛围"):
            self.assertIn(safe, encoded)
        self.assertEqual(public[0]["evidence"], [])

    def test_public_evidence_retains_numeric_telemetry_not_fake_assertions(self):
        metric = {"label": "正文含地址字样", "source_key": "has_address", "value": 1, "status": "available"}
        opinions = [{"role": "增长专家", "opinion": "优先展示可见区域。", "evidence": [
            "这是同城唯一组合。", {"agent_text": "CBD旁休闲场所", "value": 1}, metric],
            "suggestions": ["用庭院和自助餐的真实组合解释读者价值。"]}]
        public = api._generation_public_expert_opinions(opinions, "广州，位置未知；有庭院与自助餐。", DOMAIN)
        self.assertEqual(public[0]["evidence"], [metric])
        for unsafe in ("CBD", "唯一"):
            self.assertNotIn(unsafe, json.dumps(public, ensure_ascii=False))
        self.assertIn("同城稀缺比较", public[0]["reason"])

    def test_public_visual_progress_and_saved_context_share_one_boundary(self):
        source = "广州，位置、时段客流、个人体验未知。"
        event = {"type": "expert_opinion", "role": "视觉分析师", "agent_idx": 0,
                 "content": "庭院有木桥，位于CBD旁。光线暖黄。", "detail": "以CBD隐藏庭院为钩子。", "progress": 22}
        public = api._generation_public_progress_event(event, source, DOMAIN)
        cover = api._generation_public_visual_summary(event["content"] + "\n水温舒服。", source, DOMAIN)
        opinions = api._generation_public_expert_opinions(
            [{"role": "视觉专家", "opinion": event["content"], "suggestions": [event["detail"]]}], source, DOMAIN)
        saved = api._sanitize_chat_generate_context({"cover_analysis": cover, "expert_opinions": opinions})
        for value in (public, saved):
            encoded = json.dumps(value, ensure_ascii=False)
            for unsafe in ("CBD", "水温舒服"):
                self.assertNotIn(unsafe, encoded)
            for safe in ("木桥", "已省略相关建议"):
                self.assertIn(safe, encoded)
        self.assertEqual(event["detail"], "以CBD隐藏庭院为钩子。")
        self.assertEqual(public["progress"], 22)

    def test_clarified_context_keeps_external_and_confirmation_before_ai_observations(self):
        material = "【商家原始素材】广州；价格、权益和具体区位未知。"
        observed = "CBD旁的庭院。套餐A包含SPA。"
        enrichment = {"provider": "amap", "facts": {"address": "测试街8号"}, "sources": []}
        external = facts.format_fact_context(enrichment)
        confirmation = "【本次商家确认】套餐A含按摩，不含SPA；按摩45分钟需另收费。"
        for pipeline in ("generate_stream", "analyze"):
            prepared = {"pipeline": pipeline, "source_material": material,
                        "image_desc": observed, "video_desc_for_library": observed,
                        "fact_context": external, "metadata": {"fact_enrichment": enrichment}}
            if pipeline == "generate_stream":
                prepared["domain"] = DOMAIN
            else:
                prepared["request"] = {"domain": DOMAIN}
            context = api._clarified_fact_context(prepared, confirmation)
            trusted = api._leisure_nonvisual_fact_source(context)
            self.assertIn("测试街8号", trusted)
            self.assertIn(confirmation, trusted)
            self.assertNotIn("CBD", trusted)
            self.assertNotIn("套餐A包含SPA", trusted)
            self.assertIn(observed, context)  # Original observation retained as such.
            self.assertIn(api._LEISURE_VISUAL_SOURCE_MARKER, context)
            self.assertTrue(api._delivery_integrity_issues("CBD旁", context, DOMAIN))
            self.assertTrue(api._delivery_integrity_issues("套餐A包含SPA", context, DOMAIN))
            self.assertFalse(api._delivery_integrity_issues("地址是测试街8号。", context, DOMAIN))
            self.assertFalse(api._delivery_integrity_issues(confirmation, context, DOMAIN))
            public = api._generation_public_expert_opinions([{"role": "视觉专家", "opinion": observed}], context, DOMAIN)
            self.assertNotIn("CBD", json.dumps(public, ensure_ascii=False))
            for domain in OLD_DOMAINS:
                legacy = api._clarified_fact_context({**prepared, "domain": domain}, confirmation)
                self.assertEqual(legacy, "\n\n".join((material,
                    "【素材观察（AI识别，未作外部独立核验）】\n" + observed, external, confirmation)))

    def test_public_projection_keeps_questions_negations_and_old_domains_exact(self):
        source = "未提供位置。"
        text = "是否在CBD旁需确认？不能根据图片写成CBD旁。没有医疗功效。庭院光线暖黄。"
        safe, notices = api._leisure_public_fact_text(text, source)
        self.assertEqual(notices, [])
        self.assertIn("是否在CBD旁需确认", safe)
        original = [{"role": "视觉专家", "raw": "<scene>CBD旁的空间</scene><hooks>城市景观</hooks>"}]
        event = {"type": "expert_opinion", "content": "CBD旁的空间", "detail": "景观", "progress": 22}
        for domain in OLD_DOMAINS:
            self.assertEqual(api._generation_public_expert_opinions(original, source, domain), api._public_expert_opinions(original))
            self.assertEqual(api._generation_public_visual_summary(text, source, domain), text)
            self.assertIs(api._generation_public_progress_event(event, source, domain), event)

    def test_public_omission_does_not_release_cross_clause_comparisons(self):
        for claim in ("位于广州城区，这类搭配并不多见。", "工作日下午到店，这里人少。",
                      "泡池水温，真的很舒服。", "本次亲测，到店体验很好。"):
            public = api._generation_public_visual_summary(claim + "木桥与暖黄光线可见。", "广州，其余事实未知。", DOMAIN)
            for unsafe in ("广州城区", "这里人少", "真的很舒服", "本次亲测"):
                self.assertNotIn(unsafe, public)
            self.assertIn("木桥", public)
            if "不多见" in claim:
                self.assertIn("不多见", public)

    def test_mock_stream_public_previews_preserve_only_internal_raw_drafts(self):
        captures = []
        source = "广州；有庭院、泳池与自助餐，具体区位未知。"
        async def model(task, system, user, **kwargs):
            if kwargs.get("trace_step") == "generation_visual":
                return "<scene>庭院有木桥，位于CBD旁。光线暖黄。</scene><hooks>CBD隐藏庭院</hooks>"
            return "<draft_title>庭院休闲</draft_title><draft_body>被闹市包围的休闲空间。</draft_body>"
        async def stream(task, system, user, **kwargs):
            captures.append(user)
            yield "content", "<title>庭院泳池休闲体验</title><body>可见庭院、泳池与自助餐。</body><rationale>以CBD旁作叙事</rationale>"
        async def shape(_title, value, *_args, **_kwargs):
            return value
        with mock.patch.object(api, "_runtime_prompt", return_value="测试基础模板{domain}"), \
             mock.patch.object(api, "_kimi_vision_understand", return_value="庭院有木桥，位于CBD旁。光线暖黄。"), \
             mock.patch.object(api._mr, "call", side_effect=model), \
             mock.patch.object(api._mr, "stream", side_effect=stream), \
             mock.patch.object(api, "_shape_body_for_delivery", side_effect=shape), \
             mock.patch.object(api, "_generation_candidate_count", return_value=1), \
             mock.patch.object(api, "_predict", side_effect=RuntimeError("skip offline artifact scoring")), \
             mock.patch.object(api._clarification, "pause") as pause, \
             mock.patch.object(api.asyncio, "sleep", new=mock.AsyncMock()):
            async def run():
                generator = api._generate_pipeline_stream(DOMAIN, source, None,
                    None, {}, None, "2026101412", cover_images=["mock-image"])
                events = []
                try:
                    async for event in generator:
                        events.append(event)
                        if event["type"] == "p3_done":
                            break
                finally:
                    await generator.aclose()
                return events
            events = asyncio.run(run())
        for event in events:
            if event["type"] in {"expert_opinion", "p3_done"}:
                encoded = json.dumps(event, ensure_ascii=False)
                self.assertNotIn("CBD", encoded)
                self.assertNotIn("闹市", encoded)
        self.assertIn("CBD隐藏庭院", captures[0])
        self.assertIn("CBD隐藏庭院", json.dumps(pause.call_args.args[0], ensure_ascii=False))
        prepared, private_opinions = pause.call_args.args[:2]
        self.assertIs(private_opinions, prepared["opinions"])
        visual = next(item for item in private_opinions if item.get("role") == "视觉专家")
        self.assertIn("CBD隐藏庭院", visual["raw"])
        public = api._generation_public_expert_opinions(private_opinions, source, DOMAIN)
        encoded = json.dumps(public, ensure_ascii=False)
        self.assertNotIn("CBD", encoded)
        self.assertNotIn("闹市", encoded)

    def test_claim_families_keep_provided_scope_and_personal_information(self):
        source = "门店在CBD旁。下午人少。下午营业。作者说水温舒服、服务贴心。作者说我泡完很舒服。"
        for claim in ("CBD附近", "下午人少", "下午营业", "水温舒服", "服务贴心", "我泡完很舒服"):
            self.assertFalse(api._delivery_integrity_issues(claim, source, DOMAIN), claim)
        for claim in ("CBD内", "周末人少", "上午人少", "上午营业", "海鲜新鲜", "卫生合格"):
            self.assertTrue(api._delivery_integrity_issues(claim, source, DOMAIN), claim)
        self.assertTrue(api._delivery_integrity_issues("CBD旁", "是否CBD旁需确认", DOMAIN))
        self.assertTrue(api._delivery_integrity_issues("CBD旁", "希望写成CBD旁", DOMAIN))
        self.assertTrue(api._delivery_integrity_issues("下午人少", "请写下午人少", DOMAIN))
        issues = api._delivery_integrity_issues("实际可见庭院与餐台", "广州", DOMAIN, title_variants=["市中心休闲攻略"])
        self.assertTrue(any("备选标题1" in issue for issue in issues))

    def test_leisure_vision_and_content_assembly_close_the_sensory_conflict(self):
        for function in (api._kimi_vision_understand, api._kimi_vision_quick):
            with mock.patch.object(api, "_read_image_input", return_value=b"synthetic-local-image"), \
                 mock.patch.object(api._ark_media, "image_part", return_value={"type": "image"}), \
                 mock.patch.object(api._ark_media, "chat", return_value="可见木调空间") as model:
                function("synthetic", DOMAIN, "城市广州，地址未知")
            prompt = model.call_args.args[0]
            self.assertIn("空画面不证明常态客流", prompt)
            self.assertIn("CBD/商圈/市中心", prompt)
        for domain in (DOMAIN, *OLD_DOMAINS):
            with mock.patch.object(api, "_runtime_prompt", return_value="原始基础模板{domain}"), \
                 mock.patch.object(api._mr, "call", new=mock.AsyncMock(return_value="<draft_title>真实标题</draft_title>")) as model:
                asyncio.run(api._gent_content(domain, "本次真实文字", api._get_dk(domain), "可见木调空间"))
            system = model.call_args.args[1]
            self.assertEqual("图片可用于场景/感官/氛围描述。" in system, domain != DOMAIN)
            if domain == DOMAIN:
                self.assertIn("AI视觉推断不构成区位", system)
                self.assertIn("无需排队", system)

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

    def test_actual_spa_named_duration_ranges_keep_identity_and_type(self):
        # Exact author input from frozen spafoottext.json SHA256 000fa1ba0e99f061649897bf9d34ec4d6c21d1193687db5796d17e5bf72ca635.
        # The failed isolated candidate was not retained; these are offline
        # paired expressions, not a reconstruction of its fatal sentence.
        source = '本例是公开项目资料整理的文字输入，不是本人到店或图片观察。正文不展示商家名、地址或分店。公开品牌资料列出“云足疗A款”时长70–90分钟；另有“云脊疗SPA”，其项目说明提到精油推拿，但没有给该SPA时长或价格。只能把70–90分钟绑定足疗A款，不能移给SPA。“云脊疗SPA”只是真实项目名称，不支持任何脊椎、疾病、睡眠、康复或治疗功效。写成休闲项目选择与确认要点；没有证据证明某套餐同时含两个项目、餐饮或留宿，也没有本人触感、技师或效果信息，缺项明确提示，不编造。'
        for text in (
            '云足疗A款时长70–90分钟。', '云足疗A款时长70-90分钟。',
            '云足疗A款时长70分钟至90分钟。', '足疗A款时长70到90分钟。',
            '足疗时长70～90分钟。', '云脊疗SPA介绍中提到精油推拿，时长需确认。',
            '选择足疗A款70–90分钟。', '预约足疗A款70分钟至90分钟。', '可选足疗A款70–90分钟。',
            '云脊疗SPA只是真实项目名称，不支持任何脊椎、疾病、睡眠、康复或治疗功效。',
        ):
            with self.subTest(text=text):
                self.assertFalse(api._delivery_integrity_issues(text, source, DOMAIN))
                public, issues = api._leisure_public_fact_text(text, source)
                self.assertFalse(issues)
                self.assertIn(text.rstrip('。'), public)
        for text in (
            '云足疗A款时长70分钟。', '足疗A款90分钟。', '云足疗B款90分钟。',
            '云足疗B款时长70–90分钟。', '云脊疗SPA时长70–90分钟。',
            '云脊疗SPA时长90分钟。', '足疗A款时长70分钟起。',
            '晴足疗A款70-90分钟。', '新云足疗A款70-90分钟。', '云足疗A款90-70分钟。',
            '选择足疗B款70-90分钟。', '预约晴足疗A款70-90分钟。', '可选足疗A款90分钟。',
        ):
            with self.subTest(text=text):
                issues = api._delivery_integrity_issues(text, source, DOMAIN)
                self.assertTrue(any('项目时长' in issue for issue in issues))
                self.assertTrue(api._has_blocking_quality_issues(95, issues, DOMAIN))
        for output, evidence in (
            ('按摩1-1.5小时。', '按摩60至90分钟。'),
            ('SPA3600秒到5400秒。', '水疗1小时至1.5小时。'),
            ('KTV欢唱2–3小时。', '欢唱120-180分钟。'),
            ('调酒体验45到60分钟。', '调酒体验0.75～1小时。'),
            ('品酒体验30分钟。', '品酒体验时长30分钟。'),
            ('足疗A款70–90分钟。', '服务项目：云足疗A款\n时长：70-90分钟。'),
        ):
            with self.subTest(output=output, evidence=evidence):
                self.assertFalse(api._delivery_integrity_issues(output, evidence, DOMAIN))
        claimed = '足疗A款70-90分钟。'
        for evidence in (
            '门店名：甲店\n对象：乙店\n项目：云足疗A款\n时长：70-90分钟。',
            '另一家门店云足疗A款70-90分钟。', '足疗A款70-90分钟未确认。',
            '足疗A款是否70-90分钟？', '写作要求：\n足疗A款70-90分钟。',
            '本次时长未知。\n' + api._LEISURE_VISUAL_SOURCE_MARKER + '\n足疗A款70-90分钟。',
            '项目：足疗A款未知\n时长：70-90分钟。',
            '没有足疗A款70-90分钟。',
            '项目：足疗A款\n时长：50-60分钟。\n项目：足疗B款未知\n时长：70-90分钟。',
        ):
            with self.subTest(evidence=evidence):
                self.assertTrue(any('项目时长' in issue for issue in api._delivery_integrity_issues(claimed, evidence, DOMAIN)))
        ambiguous = '“云足疗A款”70-90分钟，“云足疗B款”70-90分钟。'
        self.assertTrue(any('项目时长' in issue for issue in api._delivery_integrity_issues('足疗70-90分钟。', ambiguous, DOMAIN)))
        self.assertTrue(any('项目时长' in issue for issue in api._delivery_integrity_issues('建议收藏足疗A款70-90分钟。', '', DOMAIN)))
        self.assertTrue(any('项目时长' in issue for issue in api._delivery_integrity_issues('建议欢唱2小时的项目实际时长3小时。', '', DOMAIN)))
        self.assertTrue(any('项目时长' in issue for issue in api._delivery_integrity_issues('按摩90-70分钟。', '按摩90-70分钟。', DOMAIN)))
        self.assertFalse(api._delivery_integrity_issues('KTV欢唱2小时。', 'KTV营业2小时。', DOMAIN))
        self.assertFalse(api._leisure_duration_claims('KTV营业2小时。'))
        for text in ('建议在酒吧停留2小时。', '计划安排KTV欢唱2小时。', '洗浴中心24小时可进。'):
            self.assertFalse(api._leisure_duration_claims(text))

    def test_explicit_medical_denials_do_not_negate_other_affirmed_claims(self):
        for text in (
            '云脊疗SPA不支持治疗功效。', '云脊疗SPA不宣称疗效。',
            '本项目不支持任何脊椎、疾病、睡眠、康复或治疗功效。',
            'SPA不宣称治疗、康复和改善睡眠质量。',
        ):
            with self.subTest(text=text):
                self.assertFalse(api._delivery_integrity_issues(text, '', DOMAIN))
        for text in (
            '云脊疗SPA支持治疗功效。', '云脊疗SPA宣称疗效。',
            '不是不支持治疗功效。', '并非不宣称疗效。', '不能说不支持康复。',
            '不支持不宣称疗效。', '不宣称不支持治疗功效。',
            '不支持不支持治疗功效。', '不宣称不宣称疗效。',
            'SPA不支持治疗，但可以改善失眠。', 'SPA不宣称疗效，具有康复效果。',
        ):
            with self.subTest(text=text):
                self.assertTrue(any('医疗功效' in issue for issue in api._delivery_integrity_issues(text, text, DOMAIN)))

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

    def test_ps_entitlement_is_not_inferred_from_latin_word_substrings(self):
        cases = (
            ("cups_leak", "套餐A含PS游戏机。", "套餐A含CUPS（杯具）使用。", True),
            ("maps_leak", "套餐A含PS游戏机。", "套餐A含Google Maps导览服务。", True),
            ("apps_leak", "套餐A含PS游戏机。", "套餐A含音乐Apps点歌服务。", True),
            ("cups_false_rejection", "套餐A含CUPS（杯具）使用。", "套餐A含杯具使用。", False),
            ("maps_false_rejection", "套餐A含Google Maps导览服务。", "套餐A含地图导览服务。", False),
            ("explicit_ps", "套餐A含PS游戏机。", "套餐A含PS游戏机。", False),
            ("lowercase_ps", "套餐A含PS和Switch。", "套餐A含ps和switch。", False),
            ("existing_ps5_recognition", "套餐A含PS5游戏机。", "套餐A含PS5游戏机。", False),
            ("negative_ps", "套餐A不含PS游戏机。", "套餐A不含ps游戏机。", False),
            ("unprovided_ps", "套餐A含PS游戏机。", "套餐A含杯具使用。", True),
        )
        for label, output, source, expected_issue in cases:
            with self.subTest(label=label):
                issues = api._delivery_integrity_issues(output, source, DOMAIN)
                self.assertEqual(any("套餐服务权益" in issue for issue in issues), expected_issue)
                if expected_issue:
                    self.assertTrue(api._has_blocking_quality_issues(95, issues, DOMAIN))
                else:
                    self.assertFalse(issues)

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
