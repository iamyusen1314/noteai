"""Offline regression from an actually rejected leisure candidate; no paid replay.

The actual candidate also had a package-rights issue. This target changes no
judgment about that independent issue and tests the medical classification only.
"""
import atexit
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
_IMPORT_DIRECTORY = tempfile.TemporaryDirectory(prefix="noteai-leisure-gate-")
atexit.register(_IMPORT_DIRECTORY.cleanup)
_PRIVATE_SQLITE = Path(_IMPORT_DIRECTORY.name) / "offline.sqlite3"
with mock.patch("dotenv.load_dotenv", return_value=False), mock.patch.dict(os.environ, {
    "DATABASE_URL": "", "NOTEAI_SQLITE_PATH": str(_PRIVATE_SQLITE),
    "NOTEAI_FACT_SEARCH": "0", "NOTEAI_PUBLIC_PRODUCT": "0",
}), mock.patch("httpx.Client.send", side_effect=AssertionError("offline network forbidden")), \
        mock.patch("httpx.AsyncClient.send", side_effect=AssertionError("offline network forbidden")):
    import api

DOMAIN = "休闲娱乐体验"
SOURCE = "商家原始素材：汤泉空间及泳池图片；不支持任何医疗功效，套餐权益仍需独立核实。"
ACTUAL_REJECTED_BODY = '广州番禺万博CBD里藏着一家汤泉馆——水石清池·汤泉生活，门票包含泳池、女宾水池、男宾水池和清池书吧，进来随便用，不用纠结加购。\n\n泳池是整个空间的视觉核心。星空顶暖光洒在镜面水面，金属躺椅沿池排开，格栅灯墙衬着水波倒影，游几圈或发呆放空都适合。\n\n汤泉区男女分开，暖棕木纹格栅、原生造景石、柔暖漫射光裹着整个空间，脚边糙石映着地灯，泡进去静谧感直接拉满。\n\n隐藏亮点在观景休息区——巨幅落地窗正对CBD城景，弧形软包沙发傍晚落日时分坐着特别治愈；榻榻米软垫可以躺着看落日，拱形百叶窗透进焦糖暖光，慵懒刚刚好。清池书吧安静在旁，泡完汤泉缓在这儿收尾，很舒服。\n\n适合下班后一个人来汤泉放空，也适合朋友周末组团。门票全包，到了就能用。\n\n你最想先打卡哪个区——泳池星空下发呆，还是汤泉泡到忘记时间？评论告诉我！\n\n#广州汤泉 #室内泳池 #番禺万博 #CBD休闲 #下班去哪玩 #汤泉放松 #周末打卡'
ACTUAL_CONFIRMATION_CONTEXT = "【本次商家确认；仅适用于本任务，不是外部独立核验或长期偏好】\n本次最新商家确认优先于旧口径；历史仅留存，旧专家草稿不是事实。\n下列原问题范围仅用于定位问题；回答明确更正的门店、套餐和适用日期优先。正文及标题须保留影响内容的适用条件，不得将限时活动泛化为长期承诺，也不得用回答时间推断活动日期。\n- 原问题范围：门店：水石清池·汤泉生活；套餐/对象：水石清池·汤泉生活；时间：仅本次，未声明长期有效\n问题：素材提及'市区''CBD'，请确认门店所在城市，便于标签和搜索覆盖\n当前回答：广州番禺万博CBD\n- 原问题范围：门店：水石清池·汤泉生活；套餐/对象：水石清池·汤泉生活；时间：仅本次，未声明长期有效\n问题：泳池、汤泉、书吧等区域是否包含在门票内，还是需要单独付费或套餐选择？\n当前回答：全包含在门票"
ACTUAL_RAW_BRIEF = '泳池、女宾水池、男宾水池、清池书吧'
MERCHANT = "水石清池·汤泉生活"


class LeisureFactGateRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="noteai-leisure-gate-case-")
        self.addCleanup(self.temp.cleanup)
        self.stack = __import__("contextlib").ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(api._db, "_DB_PATH", Path(self.temp.name) / "private.sqlite3"))
        self.stack.enter_context(mock.patch.dict(os.environ, {
            "DATABASE_URL": "", "NOTEAI_SQLITE_PATH": str(Path(self.temp.name) / "private.sqlite3"),
            "NOTEAI_FACT_SEARCH": "0", "NOTEAI_PUBLIC_PRODUCT": "0",
        }))
        self.stack.enter_context(mock.patch("dotenv.load_dotenv", return_value=False))
        self.stack.enter_context(mock.patch("httpx.Client.send", side_effect=AssertionError("offline network forbidden")))
        self.stack.enter_context(mock.patch("httpx.AsyncClient.send", side_effect=AssertionError("offline network forbidden")))

    def test_actual_scene_healing_is_not_medical_but_explicit_treatment_stays_blocking(self):
        # Actual title/body/score are not repaired or re-generated in this test.
        actual_issues = api._structured_fact_boundary_issues(ACTUAL_REJECTED_BODY, SOURCE, DOMAIN)
        self.assertTrue(any("套餐服务权益" in issue for issue in actual_issues),
            "The separate entitlement classification has not been relaxed")
        medical_misclassified = [issue for issue in actual_issues if "医疗功效" in issue]
        with self.subTest(actual_final_candidate=True):
            self.assertEqual(medical_misclassified, [],
                "A sofa/sunset atmosphere feeling is not a medical efficacy claim")
        for text in (
            "弧形软包沙发傍晚落日时分坐着特别治愈。",
            "落日和暖光营造的氛围看着很治愈。",
            "这片落日的画面让我觉得很治愈。",
        ):
            with self.subTest(scene=text):
                self.assertFalse(any("医疗功效" in issue for issue in
                    api._structured_fact_boundary_issues(text, SOURCE, DOMAIN)))
        for text in (
            "汤泉可以治愈失眠。", "泡汤可以治愈颈椎病。", "按摩可以治愈颈肩疼痛。",
            "这个氛围看着很治愈，还能治疗失眠。",
            "落日时分坐着特别治愈，可以改善睡眠质量。",
            "坐着很治愈失眠症状。", "这里的落日氛围能治愈疾病。",
            "不是不能治愈失眠。", "并非不宣称疗效。", "不支持治疗，但可以改善失眠。",
            "落日看着特别治愈，失眠患者也适合。",
            "落日看着很治愈，而且这里提供治疗。", "这里可以治愈。",
            "景色很治愈。这里还能治疗失眠。",
            "落日看着特别治愈，颈部僵硬的人也适合。",
            "落日看着特别治愈，肩部僵紧的人也适合。",
        ):
            with self.subTest(clinical=text):
                issues = api._structured_fact_boundary_issues(text, SOURCE, DOMAIN)
                self.assertTrue(any("医疗功效" in issue for issue in issues))
                self.assertTrue(api._has_blocking_quality_issues(95, issues, DOMAIN))
        with self.subTest(explicit_denial=True):
            self.assertFalse(api._structured_fact_boundary_issues("本项目不宣称治疗、康复和改善睡眠质量。", SOURCE, DOMAIN))


    def test_actual_confirmed_ticket_answer_supports_only_its_merchant_services_and_scope(self):
        # Exact 1004-byte real answer_context, including the question that names
        # the services; the short answer alone does not repeat those nouns.
        import hashlib
        self.assertEqual(len(ACTUAL_CONFIRMATION_CONTEXT.encode()), 1004)
        self.assertEqual(hashlib.sha256(ACTUAL_CONFIRMATION_CONTEXT.encode()).hexdigest(),
            "c8c525e9c9489668d2281f3f4c14f18c93310efb7c7ec56d924f9890e31bba12")
        intent_header = api._content_intent_brief(DOMAIN, "真实种草型", "AI识别后决定",
            MERCHANT, "auto", "AI爆文生成")
        self.assertIn("用户补充名称：" + MERCHANT, intent_header)
        def source(context):
            return intent_header + "\n\n" + ACTUAL_RAW_BRIEF + "\n\n" + context
        def entitlement_issues(text, context):
            return [issue for issue in api._structured_fact_boundary_issues(text, source(context), DOMAIN)
                if "套餐服务权益" in issue]
        included = "门票包含泳池、汤泉和书吧。"
        for claim in (included, ACTUAL_REJECTED_BODY):
            with self.subTest(confirmed_claim=claim[:32]):
                self.assertEqual(entitlement_issues(claim, ACTUAL_CONFIRMATION_CONTEXT), [],
                    "Explicit same-merchant ticket confirmation must use the question's bounded service scope")
        # Every negative keeps the actual intent header and raw original media
        # labels; only the authority/scope shown in that case differs.
        contexts = {
            "unanswered": ACTUAL_CONFIRMATION_CONTEXT.replace("当前回答：全包含在门票", ""),
            "unknown": ACTUAL_CONFIRMATION_CONTEXT.replace("当前回答：全包含在门票",
                "当前回答：用户暂不确定；不再重复问，本次不写成事实。核心卖点相关部分待确认，其余继续完成。"),
            "omitted": ACTUAL_CONFIRMATION_CONTEXT.replace("当前回答：全包含在门票",
                "当前回答：用户选择不写此项；所有标题、方案及后续优化都不得写入此项，也不能换种说法暗示。"),
            "denied": ACTUAL_CONFIRMATION_CONTEXT.replace("当前回答：全包含在门票", "当前回答：不包含在门票，需要另外购买。"),
            "other_merchant": ACTUAL_CONFIRMATION_CONTEXT.replace(MERCHANT, "乙汤泉生活"),
            "named_package": ACTUAL_CONFIRMATION_CONTEXT.replace("套餐/对象：" + MERCHANT, "套餐/对象：套餐A"),
            "limited_time": ACTUAL_CONFIRMATION_CONTEXT.replace("时间：仅本次，未声明长期有效",
                "时间：2026年11月5日18:00至22:00"),
            "question_weekday_limited": ACTUAL_CONFIRMATION_CONTEXT.replace(
                "泳池、汤泉、书吧等区域是否包含在门票内，还是需要单独付费或套餐选择？",
                "泳池是否包含在门票内，仅限工作日？"),
            "question_named_package": ACTUAL_CONFIRMATION_CONTEXT.replace(
                "泳池、汤泉、书吧等区域是否包含在门票内，还是需要单独付费或套餐选择？",
                "泳池是否包含在门票内，问的是A套餐？"),
            "question_excludes_pool": ACTUAL_CONFIRMATION_CONTEXT.replace(
                "泳池、汤泉、书吧等区域是否包含在门票内，还是需要单独付费或套餐选择？",
                "泳池之外的按摩是否包含在门票内，还是需要单独付费？"),
        }
        for label, context in contexts.items():
            with self.subTest(unconfirmed_or_different_scope=label):
                claim = "门票包含泳池。" if label.startswith("question_") else included
                self.assertTrue(entitlement_issues(claim, context),
                    "Question text, unknown/negative answers or different scope cannot authorize generic ticket rights")
        for claim in ("门票包含自助餐。", "门票包含按摩。", "门票包含过夜。", "门票赠送泳池、汤泉和书吧。"):
            with self.subTest(extra_service_or_condition=claim):
                self.assertTrue(entitlement_issues(claim, ACTUAL_CONFIRMATION_CONTEXT))



    def test_later_ticket_answer_replaces_earlier_unconditional_rights(self):
        intent_header = api._content_intent_brief(DOMAIN, "真实种草型", "AI识别后决定",
            MERCHANT, "auto", "AI爆文生成")
        # Same question/merchant/object is repeated by a later confirmation.
        # This is not a second authority that can be unioned with the old yes.
        latest_block = "- 原问题范围：" + ACTUAL_CONFIRMATION_CONTEXT.rsplit("\n- 原问题范围：", 1)[1]
        for label, block in (
            ("latest_unknown", latest_block.replace("当前回答：全包含在门票", "当前回答：未知")),
            ("latest_denied", latest_block.replace("当前回答：全包含在门票", "当前回答：不包含在门票")),
            ("latest_qualified", latest_block.replace("当前回答：全包含在门票", "当前回答：全包含在门票，但按摩另付")),
            ("latest_time_limited", latest_block.replace("时间：仅本次，未声明长期有效", "时间：2026-11-05")),
            ("latest_question_limited", latest_block.replace(
                "泳池、汤泉、书吧等区域是否包含在门票内，还是需要单独付费或套餐选择？",
                "泳池是否包含在门票内，仅限工作日？")),
        ):
            with self.subTest(later_confirmation=label):
                source = (intent_header + "\n\n" + ACTUAL_RAW_BRIEF + "\n\n"
                    + ACTUAL_CONFIRMATION_CONTEXT + "\n" + block)
                issues = api._structured_fact_boundary_issues("门票包含泳池。", source, DOMAIN)
                self.assertTrue(any("套餐服务权益" in issue for issue in issues),
                    "A later unknown/negative/qualified/time-limited answer must invalidate the old unconditional yes")


if __name__ == "__main__":
    unittest.main()
