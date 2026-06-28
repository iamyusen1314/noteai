import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))

from v04_composite_features import (  # noqa: E402
    COMPOSITE_FEATURE_COLS,
    build_composite_features,
)


class V04CompositeFeatureTests(unittest.TestCase):
    def test_food_delivery_slots_and_bad_title_risk(self):
        body = (
            "番禺万博这家粤菜适合聚餐，招牌芝士焗小青龙建议必点。"
            "地址在广晟万博城A座7层，人均98元，营业时间09:00-14:00/17:00-21:00，周末建议提前预订。"
            "乳鸽皮脆肉嫩，雪燕杏花羹清甜，喜欢这类真实探店可以点赞收藏。\n"
            "#番禺美食 #粤菜聚餐 #芝士焗小青龙 #广州探店 #周末聚餐"
        )
        good = build_composite_features(title="广州番禺小青龙人均98值得试", body=body, domain="美食")
        bad = build_composite_features(title="广州番禺万博98元值得点", body=body, domain="美食")

        self.assertEqual(good["domain_food_price"], 1.0)
        self.assertEqual(good["domain_food_address"], 1.0)
        self.assertEqual(good["domain_food_hours"], 1.0)
        self.assertEqual(good["domain_food_must_order"], 1.0)
        self.assertGreaterEqual(good["commercial_domain_slot_coverage"], 0.8)
        self.assertEqual(good["commercial_title_unreadable_risk"], 0.0)
        self.assertEqual(bad["commercial_title_unreadable_risk"], 1.0)

    def test_fitness_action_plan_features(self):
        body = (
            "这套居家减脂适合新手，先热身再做深蹲、卷腹、平板支撑。"
            "每个动作3组，每组15次，平板支撑30秒，注意膝盖和腰不要代偿。"
            "主要练腰腹和核心，想跟练的点赞收藏。\n"
            "#居家健身 #减脂 #新手训练 #腰腹训练 #自律打卡"
        )
        feats = build_composite_features(title="新手居家减脂4个动作很稳", body=body, domain="健身")
        self.assertEqual(feats["domain_fitness_action"], 1.0)
        self.assertEqual(feats["domain_fitness_dosage"], 1.0)
        self.assertEqual(feats["domain_fitness_target"], 1.0)
        self.assertEqual(feats["domain_fitness_safety"], 1.0)
        self.assertGreater(feats["commercial_actionability"], 0.5)
        self.assertGreaterEqual(feats["commercial_fact_density"], 0.75)
        self.assertGreaterEqual(feats["commercial_specificity"], 0.75)

    def test_travel_transport_covers_route_and_hotel_distance_terms(self):
        route_body = (
            "大理4天慢旅行，第二天骑电动车去才村码头和龙龛码头，第三天包车到双廊。"
            "人均预算2200元，返程当天睡到自然醒，路线不要排太满。"
            "路线先收藏，评论区问我行程细节。\n#大理旅行 #洱海 #慢旅行 #路线攻略"
        )
        hotel_body = (
            "三亚亚龙湾亲子酒店适合泡酒店，房价666元起，距离公共沙滩约200米。"
            "儿童乐园和早餐都清楚，靠近沙滩比每天跑市区省心。"
            "路线先收藏，评论区问我行程细节。\n#三亚亲子酒店 #亚龙湾 #沙滩度假"
        )
        route = build_composite_features(title="大理4天慢旅行路线", body=route_body, domain="旅行")
        hotel = build_composite_features(title="亚龙湾亲子酒店怎么选", body=hotel_body, domain="旅行")

        self.assertEqual(route["domain_travel_transport"], 1.0)
        self.assertEqual(hotel["domain_travel_transport"], 1.0)

    def test_baby_sleep_routine_counts_care_items_as_domain_materials(self):
        body = (
            "6月龄宝宝睡前流程控制在25分钟内，顺序是洗澡、抚触、换睡袋、关主灯、读短绘本。"
            "观察困信号包括揉眼睛、发呆、打哈欠，明显哭闹时先停下来安抚。"
            "卧室保持暗光，白噪音音量要低，不承诺睡整觉，有用先点赞收藏。\n"
            "#6月龄睡眠 #宝宝睡前流程 #新手父母 #婴儿护理 #育儿经验"
        )
        feats = build_composite_features(title="6月龄睡前流程推荐", body=body, domain="母婴")
        self.assertEqual(feats["domain_baby_age"], 1.0)
        self.assertEqual(feats["domain_baby_safety"], 1.0)
        self.assertEqual(feats["domain_baby_steps"], 1.0)
        self.assertEqual(feats["domain_baby_materials"], 1.0)
        self.assertGreaterEqual(feats["commercial_domain_slot_coverage"], 1.0)
        self.assertGreaterEqual(feats["commercial_fact_density"], 0.75)
        self.assertGreaterEqual(feats["commercial_specificity"], 0.75)

    def test_feature_contract_is_unique_and_large_enough(self):
        self.assertEqual(len(COMPOSITE_FEATURE_COLS), len(set(COMPOSITE_FEATURE_COLS)))
        self.assertGreater(len(COMPOSITE_FEATURE_COLS), 100)


if __name__ == "__main__":
    unittest.main()
