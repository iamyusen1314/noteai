import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from ai_prelabel_review_batch import apply_kimi_second_review, prelabel_golden_row, prelabel_preference_row  # noqa: E402
from promote_reviewed_prelabels import promote_rows  # noqa: E402


class AIPrelabelReviewToolTests(unittest.TestCase):
    def test_golden_prelabel_does_not_fill_official_human_fields(self):
        row = {
            "annotation_id": "g1",
            "human_label_status": "needs_label",
            "domain": "美食",
            "title": "番禺小青龙人均98值得试",
            "body": "招牌小青龙，人均98元，地址在万博，营业时间到21点，建议提前预订。喜欢粤菜探店可以收藏。" * 3,
        }
        out = prelabel_golden_row(row)
        self.assertEqual(out["human_label_status"], "needs_label")
        self.assertNotIn("human_quality_score", out)
        self.assertIn("ai_human_quality_score", out)
        self.assertEqual(out["review_decision"], "")

    def test_promotion_requires_review_decision(self):
        row = prelabel_preference_row({
            "pair_id": "p1",
            "label_status": "needs_label",
            "domain": "穿搭",
            "variant_a_title": "小个子通勤显高3套公式",
            "variant_a_body": "上短下长，白衬衫配高腰裤，价格和身材适配都写清楚。" * 4,
            "variant_b_title": "通勤穿搭",
            "variant_b_body": "很好看，很显高，姐妹们可以试试。" * 4,
        })
        promoted, report = promote_rows([row], "preference")
        self.assertEqual(promoted, [])
        self.assertEqual(report["promoted_count"], 0)

        accepted = dict(row)
        accepted["review_decision"] = "accept_ai"
        promoted, report = promote_rows([accepted], "preference")
        self.assertEqual(report["promoted_count"], 1)
        self.assertEqual(promoted[0]["label_status"], "completed")
        self.assertIn(promoted[0]["winner"], {"A", "B", "tie"})

    def test_kimi_second_review_marks_preference_disagreement(self):
        row = prelabel_preference_row({
            "pair_id": "p2",
            "label_status": "needs_label",
            "domain": "美食",
            "variant_a_title": "番禺小青龙人均98值得试",
            "variant_a_body": "招牌小青龙，人均98元，地址在万博，营业时间到21点，建议提前预订。" * 4,
            "variant_b_title": "普通粤菜",
            "variant_b_body": "这里挺好吃，大家可以来。" * 8,
        })

        def fake_kimi(system, user, max_tokens):
            return {
                "winner": "B",
                "preference_margin": 2,
                "delivery_ready_winner": False,
                "reason_tags": ["naturalness"],
                "loser_failure_tags": ["title_unreadable"],
                "confidence": 0.86,
                "rationale": "Kimi认为B更自然。",
            }

        reviewed = apply_kimi_second_review(row, "preference", fake_kimi)
        self.assertEqual(reviewed["kimi_review_status"], "ok")
        self.assertEqual(reviewed["judge_consensus"], "disagree")
        self.assertIn("winner_mismatch", reviewed["judge_disagreement_flags"])
        self.assertEqual(reviewed["ai_needs_human_review"], "true")

    def test_accept_ai_blocked_when_second_review_disagrees(self):
        row = prelabel_golden_row({
            "annotation_id": "g2",
            "human_label_status": "needs_label",
            "domain": "美食",
            "title": "番禺小青龙人均98值得试",
            "body": "招牌小青龙，人均98元，地址在万博，营业时间到21点，建议提前预订。" * 4,
        })
        row["review_decision"] = "accept_ai"
        row["judge_consensus"] = "disagree"
        row["judge_disagreement_flags"] = "score_gap"
        promoted, report = promote_rows([row], "golden")
        self.assertEqual(promoted, [])
        self.assertEqual(report["promoted_count"], 0)

        row["review_decision"] = "accept_with_edits"
        row["review_human_quality_score"] = "72"
        row["review_delivery_ready"] = "true"
        row["review_naturalness_label"] = "80"
        row["review_hook_quality"] = "4"
        row["review_body_value"] = "4"
        row["review_industry_fit"] = "4"
        promoted, report = promote_rows([row], "golden")
        self.assertEqual(report["promoted_count"], 1)
        self.assertEqual(promoted[0]["human_label_status"], "completed")

    def test_auto_accept_consensus_promotes_agreed_rows_with_label_source(self):
        row = prelabel_preference_row({
            "pair_id": "p3",
            "label_status": "needs_label",
            "domain": "家居",
            "variant_a_title": "小户型收纳动线这样改",
            "variant_a_body": "先按玄关、客厅、厨房分区，列出尺寸、预算和收纳清单，适合小户型参考。" * 4,
            "variant_b_title": "我家变好看了",
            "variant_b_body": "装修后很好看，大家都说不错。" * 8,
        })
        row["judge_consensus"] = "agree"
        row["judge_disagreement_flags"] = ""
        row["consensus_label_source"] = "ai_rubric_consensus"
        row["kimi_review_status"] = "ok"
        promoted, report = promote_rows([row], "preference", auto_accept_consensus=True)
        self.assertEqual(report["promoted_count"], 1)
        self.assertEqual(promoted[0]["label_status"], "completed")
        self.assertEqual(promoted[0]["label_source"], "ai_rubric_consensus")
        self.assertEqual(promoted[0]["reviewer"], "ai_rubric_consensus_claude_kimi_v0.1")

    def test_auto_accept_winner_consensus_promotes_same_winner_only(self):
        row = prelabel_preference_row({
            "pair_id": "p4",
            "label_status": "needs_label",
            "domain": "健身",
            "variant_a_title": "弹力带臀腿新手这样练",
            "variant_a_body": "臀桥15次、蚌式12次、后踢腿12次，每个动作3组，组间休息45秒，先找臀部发力感。" * 4,
            "variant_b_title": "弹力带训练安排",
            "variant_b_body": "动作写得较少，只说跟练就可以，安全边界和组数不够清楚。" * 4,
        })
        row.update(
            {
                "judge_consensus": "disagree",
                "judge_disagreement_flags": "delivery_ready_mismatch",
                "kimi_review_status": "ok",
                "ai_winner": "A",
                "kimi_winner": "A",
                "kimi_preference_margin": "2",
                "kimi_delivery_ready_winner": "false",
                "kimi_reason_tags": "actionability|safety",
                "kimi_loser_failure_tags": "low_info_density",
                "kimi_confidence": "0.82",
                "kimi_rationale": "A动作、组数和安全边界更完整。",
            }
        )
        promoted, report = promote_rows([row], "preference", auto_accept_winner_consensus=True)
        self.assertEqual(report["promoted_count"], 1)
        self.assertEqual(promoted[0]["winner"], "A")
        self.assertEqual(promoted[0]["delivery_ready_winner"], "false")
        self.assertEqual(promoted[0]["label_source"], "ai_rubric_winner_consensus")
        self.assertEqual(promoted[0]["reviewer"], "ai_rubric_winner_consensus_claude_kimi_v0.2")
        self.assertIn("Kimi", promoted[0]["rationale"])

    def test_auto_accept_winner_consensus_rejects_low_confidence(self):
        row = prelabel_preference_row({
            "pair_id": "p5",
            "label_status": "needs_label",
            "domain": "美妆",
            "variant_a_title": "敏感皮通勤防晒",
            "variant_a_body": "肤质前提、耳后试用、补涂和妆前适配都写清楚。" * 5,
            "variant_b_title": "防晒好用",
            "variant_b_body": "很好用，很清爽，大家可以买。" * 8,
        })
        row.update(
            {
                "judge_consensus": "disagree",
                "judge_disagreement_flags": "low_kimi_confidence",
                "kimi_review_status": "ok",
                "ai_winner": "A",
                "kimi_winner": "A",
                "kimi_confidence": "0.65",
            }
        )
        promoted, report = promote_rows([row], "preference", auto_accept_winner_consensus=True)
        self.assertEqual(promoted, [])
        self.assertEqual(report["promoted_count"], 0)

    def test_auto_accept_consensus_does_not_promote_golden_missing_title(self):
        row = prelabel_golden_row({
            "annotation_id": "g3",
            "human_label_status": "needs_label",
            "domain": "美妆",
            "title": "",
            "body": "干皮上妆卡粉时，先用保湿妆前，再少量多次叠遮瑕，最后定妆重点放在鼻翼和眼下。" * 4,
        })
        row["judge_consensus"] = "agree"
        row["judge_disagreement_flags"] = ""
        row["consensus_label_source"] = "ai_rubric_consensus"
        row["kimi_review_status"] = "ok"
        promoted, report = promote_rows([row], "golden", auto_accept_consensus=True)
        self.assertEqual(promoted, [])
        self.assertEqual(report["promoted_count"], 0)

    def test_golden_promotion_preserves_zero_numeric_labels(self):
        row = {
            "annotation_id": "g4",
            "human_label_status": "needs_label",
            "domain": "健身",
            "title": "每日球感练习",
            "body": "#篮球训练#",
            "review_decision": "accept_ai",
            "ai_human_quality_score": 20,
            "ai_delivery_ready": "false",
            "ai_naturalness_label": 0,
            "ai_hook_quality": 1,
            "ai_body_value": 1,
            "ai_industry_fit": 2,
            "ai_fact_status": "safe",
            "ai_smell_level": 4,
            "ai_failure_tags": "too_short|low_info_density",
            "ai_rationale": "低质负样本。",
        }
        promoted, report = promote_rows([row], "golden")
        self.assertEqual(report["promoted_count"], 1)
        self.assertEqual(promoted[0]["naturalness_label"], "0")


if __name__ == "__main__":
    unittest.main()
