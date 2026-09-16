"""Pure source-level regression: no API import, database, model or HTTP call."""
import ast
from pathlib import Path
import re
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_definitions(path, names, namespace):
    selected = []
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            selected.append(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id in names for target in targets):
                selected.append(node)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)


ns = {"re": re}
load_definitions(ROOT / "model/prompt_composer.py", {"_TRAVEL_DOMAIN_ALIASES", "_DOMAIN_ALIASES", "_GEN_CHECKLIST_ALIASES"}, ns)
load_definitions(ROOT / "model/api.py", {
    "_food_operating_assertions", "_food_operating_fact_issues", "_fact_assertions",
    "_merchant_entity_signal", "_normalize_merchant_name", "_GENERIC_MERCHANT_NAMES",
    "_structured_fact_boundary_issues", "_has_blocking_quality_issues",
    "_PRICE_FACT_RE", "_PRICE_VALUE_CLAIM_RE", "_BUFFET_VALUE_CLAIM_RE",
    "_BUSINESS_HOURS_RE", "_BUSINESS_TIME_RANGE_RE", "_QUEUE_TIME_RE",
    "_UNVERIFIED_RATING_BACKING_RE", "_UNVERIFIED_HOLIDAY_SCENE_RE", "_UNVERIFIED_GROUP_SIZE_RE",
    "_source_has_price_evidence", "_source_has_buffet_evidence",
    "_unsupported_food_dish_expansion_terms", "_FOOD_DISH_EXPANSION_TERMS",
}, ns)
# Exercise the real fatal-issue branch independently of score thresholds.
ns["_quality_min_acceptable_percentile"] = lambda domain: 0
api = SimpleNamespace(**ns)
clarification = {}
load_definitions(ROOT / "model/task_clarification.py", {"answer_context"}, clarification)


def confirmation(question, status, answer=""):
    return clarification["answer_context"]({
        "questions": [{"question_id": "q1", "question": question}],
        "answers": [{"question_id": "q1", "status": status, "answer": answer,
                     "merchant": "示例餐厅甲店", "object": "本次门店", "time_range": "本次"}],
    })


class FoodOperatingFactBoundaryTests(unittest.TestCase):
    def issues(self, text, source="原素材：点心和门店照片。"):
        return api._structured_fact_boundary_issues(text, source, "美食")

    def test_actual_unbacked_operating_claims_are_fatal_even_with_high_score(self):
        text = ("陶陶居分茶市、午市、晚市，各时段收档时间不同。"
                "最好提前在美团或来电预订座位，减少等位时间。")
        source = "广州陶陶居(正佳广场店)，用户提供点心素材。\n" + confirmation("营业时间是什么？", "unknown")
        issues = self.issues(text, source)
        self.assertTrue(any("分时段营业" in issue for issue in issues))
        self.assertTrue(any("订位渠道" in issue for issue in issues))
        self.assertTrue(api._has_blocking_quality_issues(99, issues, "美食"))

    def test_genuine_questions_and_verification_advice_do_not_claim_capability(self):
        for text in (
            "这家是否分茶市、午市、晚市？", "收档时间不同吗？", "可以通过美团订位吗？",
            "可以提前电话订位？", "可以提前电话订位?", "门店分早茶、午市、晚市？",
            "出发前确认营业安排及是否接受订位。", "建议先询问门店是否支持电话预约。",
            "不要默认写可以通过美团订位。", "营业安排未知，先确认再出发。",
            "想吃早茶，还是午餐去？", "菜单里有早茶点心。",
            "订位方式以门店确认为准。", "想订位的话，先向门店核实是否可以电话订位。",
            "“可通过美团订位”是误写，应改为先向门店确认。", "美团订位指南",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.issues(text), [])

    def test_conditions_do_not_establish_unmentioned_channels_or_later_assertions(self):
        for text in ("若门店支持电话订位，可提前电话预约。", "如果接受预约，再按实际渠道订位。"):
            with self.subTest(text=text):
                self.assertEqual(self.issues(text), [])
        for text in ("如果人多，最好提前在美团订位。", "若接受预约，可通过美团订位。",
                     "若支持电话订位，可先预约；这家也支持美团订位。",
                     "建议先确认是否支持订位，但美团可以预约。"):
            with self.subTest(text=text):
                self.assertTrue(self.issues(text))

    def test_explicit_source_only_allows_the_same_operating_facts(self):
        source = "门店分茶市、午市、晚市。各时段收档时间不同。门店支持电话订位。"
        self.assertEqual(self.issues("分茶市、午市、晚市，各时段收档时间不同。可来电预订座位。", source), [])
        self.assertTrue(self.issues("还提供夜市。", source))
        self.assertTrue(self.issues("可在美团订位。", source))
        self.assertTrue(self.issues("来电订位能减少等位时间。", source))

    def test_numeric_hours_do_not_prove_split_sessions_or_different_closing(self):
        source = "营业时间10:00-22:00。"
        self.assertTrue(self.issues("分茶市、午市、晚市。", source))
        self.assertTrue(self.issues("各时段收档时间不同。", "分茶市、午市、晚市。"))

    def test_supplier_fact_field_is_usable_but_query_is_not_evidence(self):
        source = "【联网事实补全】\n查询：是否可以在美团订位\n- 预订/排队：支持电话预订。"
        self.assertEqual(self.issues("可以来电订位。", source), [])
        self.assertTrue(self.issues("可以在美团订位。", source))
        self.assertTrue(self.issues("可以在美团订位。", "查询：门店支持美团订位\n事实检索失败。"))

    def test_unknown_and_omit_override_only_the_corresponding_field(self):
        original = "门店分茶市、午市、晚市。支持电话订位。\n"
        for status in ("unknown", "omitted"):
            source = original + confirmation("本店分哪些营业时段，收档时间如何？", status)
            with self.subTest(status=status):
                self.assertTrue(self.issues("门店分茶市、午市、晚市。", source))
                self.assertEqual(self.issues("可电话订位。", source), [])
                self.assertEqual(self.issues("请先确认营业安排。", source), [])
                price_only = original + confirmation("人均价格是多少？", status)
                self.assertEqual(self.issues("门店分茶市、午市、晚市。", price_only), [])

    def test_confirmation_question_never_becomes_evidence(self):
        for status in ("unknown", "omitted"):
            source = confirmation("是否支持电话和美团订位？", status)
            self.assertTrue(self.issues("支持美团订位。", source))
        source = confirmation("是否支持电话和美团订位？", "confirmed", "只支持电话订位。")
        self.assertEqual(self.issues("可来电订位。", source), [])
        self.assertTrue(self.issues("可在美团订位。", source))

    def test_latest_answer_supersedes_old_confirmation(self):
        old = confirmation("是否支持电话和美团订位？", "confirmed", "支持美团订位。")
        latest = confirmation("是否支持电话和美团订位？", "unknown")
        self.assertTrue(self.issues("支持美团订位。", old + "\n" + latest))
        restored = confirmation("是否支持电话和美团订位？", "confirmed", "只支持电话订位。")
        self.assertEqual(self.issues("支持电话订位。", latest + "\n" + restored), [])
        self.assertTrue(self.issues("支持美团订位。", latest + "\n" + restored))

    def test_negative_source_cannot_prove_positive_service(self):
        self.assertTrue(self.issues("支持电话订位。", "门店不接受电话订位。"))
        self.assertTrue(self.issues("门店不接受电话订位。", "门店支持电话订位。"))
        self.assertEqual(self.issues("门店不接受电话订位。", "门店不接受电话订位。"), [])
        for source in ("没有证据表明可以美团订位。", "希望正文写可以美团订位。",
                       "要求：分茶市、午市、晚市，可美团订位。", "建议提前在美团订位。",
                       "【旧专家草稿】\n可以美团订位。"):
            with self.subTest(source=source):
                self.assertTrue(self.issues("可以美团订位。", source))

    def test_current_merchant_binding_excludes_other_branch_evidence(self):
        target = "本次商家：陶陶居正佳店\n"
        for other in ("对比历史：陶陶居丽影店支持美团订位。",
                      "陶陶居丽影店支持美团订位。",
                      "【联网事实补全】\n对象：陶陶居丽影店\n- 预订/排队：支持美团订位。",
                      confirmation("是否支持美团订位？", "confirmed", "支持美团订位。")
                      .replace("示例餐厅甲店", "陶陶居丽影店")):
            with self.subTest(other=other):
                self.assertTrue(self.issues("正佳店可以美团订位。", target + other))
        source = target + "【联网事实补全】\n对象：陶陶居正佳店\n- 预订/排队：支持电话订位。"
        self.assertEqual(self.issues("正佳店可以电话订位。", source), [])
        corrected = confirmation("是否支持订位？", "confirmed", "更正为陶陶居正佳店，支持电话订位。")
        corrected = corrected.replace("示例餐厅甲店", "陶陶居丽影店")
        self.assertEqual(self.issues("正佳店可以电话订位。", target + corrected), [])

    def test_instruction_block_does_not_hide_following_original_user_facts(self):
        source = "【创作方向契约｜AI生成完整交付】\n- 写作重点：希望支持美团订位。\n\n用户说：支持电话订位。"
        self.assertEqual(self.issues("可以电话订位。", source), [])
        self.assertTrue(self.issues("可以美团订位。", source))

    def test_optional_merchant_field_reuses_original_explicit_branch(self):
        source = "广州陶陶居(正佳广场店)\n陶陶居丽影广场店支持美团订位。"
        self.assertTrue(self.issues("正佳广场店可美团订位。", source))
        source = "广州陶陶居(正佳广场店)\n本店支持电话订位。"
        self.assertEqual(self.issues("正佳广场店可电话订位。", source), [])
        self.assertTrue(self.issues("正佳广场店可美团订位。", source))

    def test_waiting_unknown_does_not_remove_known_booking_channel(self):
        source = "门店支持电话订位。\n" + confirmation("预订能否减少等位时间？", "unknown")
        self.assertEqual(self.issues("可电话订位。", source), [])
        self.assertTrue(self.issues("电话订位能减少等位。", source))

    def test_existing_synonyms_respect_unknown(self):
        for source, question, text in (
            ("可以美团预定。", "可以通过美团预定吗？", "可以美团预定。"),
            ("分早茶、午市、晚市。", "几点打烊？", "分早茶、午市、晚市。"),
        ):
            self.assertTrue(self.issues(text, source + "\n" + confirmation(question, "unknown")))

    def test_generic_booking_does_not_require_inventing_a_channel(self):
        self.assertEqual(self.issues("可以提前预约。", "门店支持电话订位。"), [])
        self.assertTrue(self.issues("最好提前预约。"))
        self.assertTrue(self.issues("可以通过小程序订位。", "门店接受预约。"))
        self.assertTrue(self.issues("订位渠道：美团或电话。"))
        self.assertEqual(self.issues("订位渠道：电话。", "门店支持电话订位。"), [])
        self.assertTrue(self.issues("订位渠道：美团或电话。", "门店支持电话订位。"))

    def test_existing_final_and_candidate_paths_still_use_same_guard(self):
        tree = ast.parse((ROOT / "model/api.py").read_text())
        funcs = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        delivery_calls = [node for node in ast.walk(funcs["_delivery_integrity_issues"])
                          if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                          and node.func.id == "_structured_fact_boundary_issues"]
        self.assertEqual(len(delivery_calls), 2)  # Main text plus each title variant.
        pipeline = funcs["_generate_pipeline_stream"]
        final_guard = max(node.lineno for node in ast.walk(pipeline) if isinstance(node, ast.Call)
                          and isinstance(node.func, ast.Name) and node.func.id == "_delivery_integrity_issues")
        completed = min(node.lineno for node in ast.walk(pipeline) if isinstance(node, ast.Dict)
                        and any(isinstance(key, ast.Constant) and key.value == "type"
                                and isinstance(value, ast.Constant) and value.value == "complete"
                                for key, value in zip(node.keys, node.values)))
        self.assertLess(final_guard, completed)


# Reuse two original guard regressions verbatim without importing the API server.
for node in ast.walk(ast.parse((ROOT / "tests/test_api_contracts.py").read_text())):
    if isinstance(node, ast.FunctionDef) and node.name in {
        "test_structured_fact_boundary_flags_unprovided_price_without_blocking_narrative",
        "test_structured_fact_boundary_blocks_unprovided_price_value_claims",
    }:
        scope = {"api": api}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "existing_fact_regression", "exec"), scope)
        setattr(FoodOperatingFactBoundaryTests, node.name, scope[node.name])


if __name__ == "__main__":
    unittest.main()
