import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import composite_quality_report as report  # noqa: E402


class CompositeQualityReportTests(unittest.TestCase):
    def test_resolve_quality_case(self):
        item = {
            "id": "food_contract_good",
            "content_source": {
                "type": "quality_case",
                "file": "quality/golden_notes.sample.json",
                "case_id": "food_contract_good",
            },
            "labels": {},
        }
        content = report.resolve_content(item)
        self.assertEqual(content["domain"], "美食")
        self.assertIn("蟹黄拌面", content["title"] + content["body"])

    def test_experimental_signal_penalizes_blocking_and_ai_risk(self):
        clean = report.experimental_signal_score(80, 70, 90, [], False)
        risky = report.experimental_signal_score(80, 70, 5, ["标题不自然", "事实风险"], True)
        self.assertGreater(clean, risky)


if __name__ == "__main__":
    unittest.main()
