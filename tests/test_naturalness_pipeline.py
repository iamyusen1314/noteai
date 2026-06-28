import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))

from text_naturalness_features import (  # noqa: E402
    NATURALNESS_FEATURE_COLS,
    extract_naturalness_features,
)


class NaturalnessPipelineTests(unittest.TestCase):
    def test_feature_contract_excludes_time_and_domain_leakage(self):
        forbidden = {
            "time_hour",
            "time_weekday",
            "time_is_weekend",
            "time_days_to_holiday",
            "domain_encoded",
        }
        self.assertFalse(forbidden & set(NATURALNESS_FEATURE_COLS))
        self.assertEqual(len(NATURALNESS_FEATURE_COLS), len(set(NATURALNESS_FEATURE_COLS)))

    def test_template_markers_are_counted(self):
        body = "首先，这是一条建议。\n1. 需要注意细节。\n其次，总结一下，以下是方案。"
        feats = extract_naturalness_features("标题", body, "美食")
        self.assertGreaterEqual(feats["ai_transition_count"], 4)
        self.assertGreater(feats["list_marker_count"], 0)

    def test_personal_and_sensory_words_are_counted(self):
        body = "我这次和朋友去吃，入口很香，外皮脆，里面很嫩。姐妹可以收藏。"
        feats = extract_naturalness_features("标题", body, "美食")
        self.assertGreaterEqual(feats["personal_word_count"], 2)
        self.assertGreaterEqual(feats["reader_word_count"], 1)
        self.assertGreaterEqual(feats["sensory_word_count"], 3)


if __name__ == "__main__":
    unittest.main()
