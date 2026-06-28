import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from adjudicate_golden_review_disagreements import adjudicate_rows  # noqa: E402
from ai_prelabel_review_batch import prelabel_rows  # noqa: E402


class GoldenReviewAdjudicationTests(unittest.TestCase):
    def test_claude_primary_review_can_be_injected_without_network(self):
        def fake_claude_json(system: str, user: str, max_tokens: int) -> dict:
            self.assertIn("Claude 主审", system)
            self.assertIn("品类：美食", user)
            return {
                "quality_score": 82,
                "delivery_ready": True,
                "naturalness_label": 86,
                "hook_quality": 4,
                "body_value": 4,
                "industry_fit": 5,
                "fact_status": "safe",
                "ai_smell_level": 1,
                "failure_tags": ["needs_minor_revision"],
                "confidence": 0.84,
                "rationale": "信息具体，表达自然，可交付。",
                "_claude_model": "test-claude",
            }

        rows = prelabel_rows(
            [
                {
                    "annotation_id": "g1",
                    "domain": "美食",
                    "title": "广州早茶这家稳",
                    "body": "人均、地址、招牌点心和适合人群都写清楚，周末家庭聚餐很稳。",
                }
            ],
            "golden",
            primary_review="claude",
            second_review="none",
            call_claude_json=fake_claude_json,
        )

        self.assertEqual(rows[0]["ai_human_quality_score"], 82)
        self.assertEqual(rows[0]["ai_reviewer"], "claude_primary_reviewer_v0.4:test-claude")
        self.assertEqual(rows[0]["ai_needs_human_review"], "false")

    def test_adjudicates_only_low_risk_close_disagreements(self):
        base = {
            "annotation_id": "g1",
            "domain": "美食",
            "title": "广州早茶这家稳",
            "body": "人均、地址、招牌点心和适合人群都写清楚，周末家庭聚餐很稳。",
            "judge_consensus": "disagree",
            "judge_disagreement_flags": "serious_failure_tag_mismatch",
            "kimi_review_status": "ok",
            "ai_reviewer": "claude_primary_reviewer_v0.4:test-claude",
            "ai_human_quality_score": "78",
            "kimi_human_quality_score": "84",
            "ai_delivery_ready": "true",
            "kimi_delivery_ready": "true",
            "kimi_confidence": "0.8",
            "ai_fact_status": "safe",
            "kimi_fact_status": "safe",
            "ai_failure_tags": "needs_minor_revision",
            "kimi_failure_tags": "",
            "ai_naturalness_label": "82",
            "kimi_naturalness_label": "88",
            "ai_hook_quality": "4",
            "kimi_hook_quality": "5",
            "ai_body_value": "4",
            "kimi_body_value": "5",
            "ai_industry_fit": "5",
            "kimi_industry_fit": "5",
            "ai_smell_level": "1",
            "kimi_ai_smell_level": "1",
        }
        risky = {**base, "annotation_id": "g2", "judge_disagreement_flags": "fact_or_industry_risk"}

        promoted, report = adjudicate_rows([base, risky], max_score_gap=12, min_kimi_confidence=0.7)

        self.assertEqual(len(promoted), 1)
        self.assertEqual(promoted[0]["human_quality_score"], 81)
        self.assertEqual(promoted[0]["delivery_ready"], "true")
        self.assertEqual(promoted[0]["label_source"], "ai_rubric_adjudicated_claude_kimi_v0.1")
        self.assertEqual(report["skipped_reasons"]["risk_flags"], 1)

    def test_caps_high_score_when_adjudicated_row_is_not_delivery_ready(self):
        row = {
            "annotation_id": "g1",
            "domain": "旅行",
            "title": "大西北旅行攻略；青甘环线六天五夜",
            "body": "行程、预算、准备事项都写清楚，但标题存在明显交付短板。",
            "judge_consensus": "disagree",
            "judge_disagreement_flags": "serious_failure_tag_mismatch",
            "kimi_review_status": "ok",
            "ai_reviewer": "claude_primary_reviewer_v0.4:test-claude",
            "ai_human_quality_score": "88",
            "kimi_human_quality_score": "82",
            "ai_delivery_ready": "true",
            "kimi_delivery_ready": "true",
            "kimi_confidence": "0.91",
            "ai_fact_status": "safe",
            "kimi_fact_status": "safe",
            "ai_failure_tags": "title_weak_hook|missing_cta",
            "kimi_failure_tags": "title_unreadable|missing_cta",
            "ai_naturalness_label": "97",
            "kimi_naturalness_label": "88",
            "ai_hook_quality": "3",
            "kimi_hook_quality": "3",
            "ai_body_value": "5",
            "kimi_body_value": "4",
            "ai_industry_fit": "5",
            "kimi_industry_fit": "4",
            "ai_smell_level": "1",
            "kimi_ai_smell_level": "1",
        }

        promoted, _ = adjudicate_rows([row], max_score_gap=12, min_kimi_confidence=0.7)

        self.assertEqual(len(promoted), 1)
        self.assertEqual(promoted[0]["delivery_ready"], "false")
        self.assertEqual(promoted[0]["human_quality_score"], 84)


if __name__ == "__main__":
    unittest.main()
