"""Bounded selection must not discard independently observed search sources."""
import copy
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))

import hot_keywords
import trends_contract
import xhs_acquisition


ANCHORS = {
    "美食": "火锅", "旅行": "旅行", "穿搭": "穿搭",
    "美妆": "护肤", "家居": "家居", "健身": "健身",
}


def rows_for(domain, source, count, number=15, label=""):
    label = label or ("推荐攻略" if source == "search_recommend" else "体验攻略")
    return [{
        "keyword": f"{ANCHORS[domain]}{label}{index:02d}",
        "category": domain, "source": source, "count": count,
        "search_vol": 50,
    } for index in range(number)]


class TrendsSourceRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_path = hot_keywords.DB_PATH
        hot_keywords.DB_PATH = Path(self.temp.name) / "trends.db"
        hot_keywords.init_db()
        xhs_acquisition.init_db()

    def tearDown(self):
        hot_keywords.DB_PATH = self.old_path
        self.temp.cleanup()

    def freshness(self, rows):
        connection = hot_keywords._conn()
        try:
            with connection:
                return xhs_acquisition.record_scrape_freshness(
                    rows, run_id="synthetic-source-retention", min_count=12,
                    session_status={"configured": True, "auth_cookie_present": True},
                    _connection=connection,
                )
        finally:
            connection.close()

    def assert_six_healthy(self, rows):
        self.assertEqual(len(rows), 90)
        self.assertEqual(len({(r["category"], r["keyword"]) for r in rows}), 90)
        result = self.freshness(rows)
        self.assertTrue(result["overview"]["ok"])
        self.assertEqual(result["latest_run_domain_counts"], dict.fromkeys(ANCHORS, 15))
        for domain in ANCHORS:
            self.assertTrue(result["latest_run_domain_source_health"][domain]["ok"])

    def test_recommend_ranking_preserves_independent_search_for_all_domains(self):
        rows = [row for domain in ANCHORS for row in (
            rows_for(domain, "search_recommend", 6)
            + rows_for(domain, "search_phrase", 1)
        )]
        bounded = trends_contract.bound_keyword_rows(rows)
        self.assert_six_healthy(bounded)
        for domain in ANCHORS:
            self.assertEqual(Counter(r["source"] for r in bounded if r["category"] == domain),
                             {"search_recommend": 14, "search_phrase": 1})

    def test_search_ranking_preserves_independent_recommend_for_all_domains(self):
        rows = [row for domain in ANCHORS for row in (
            rows_for(domain, "search_recommend", 1)
            + rows_for(domain, "search_phrase", 8)
        )]
        bounded = trends_contract.bound_keyword_rows(rows)
        self.assert_six_healthy(bounded)
        for domain in ANCHORS:
            self.assertEqual(Counter(r["source"] for r in bounded if r["category"] == domain),
                             {"search_phrase": 14, "search_recommend": 1})

    def test_already_balanced_selection_keeps_rank_and_existing_rows(self):
        rows = (rows_for("美食", "search_recommend", 6, 8)
                + rows_for("美食", "search_phrase", 1, 7)
                + rows_for("美食", "homefeed_phrase", 2, 10, "家庭火锅"))
        expected = [r["keyword"] for r in rows[:15]]
        self.assertEqual([r["keyword"] for r in trends_contract.bound_keyword_rows(rows)], expected)

    def test_missing_real_source_stays_missing_without_baseline_substitution(self):
        rows = (rows_for("美食", "search_recommend", 6, 30)
                + rows_for("美食", "industry_baseline", 8, 15, "传统火锅"))
        bounded = trends_contract.bound_keyword_rows(rows)
        self.assertEqual(len(bounded), 15)
        health = self.freshness(bounded)["latest_run_domain_source_health"]["美食"]
        self.assertFalse(health["ok"])
        self.assertEqual(health["missing_sources"], ["search_result"])

    def test_one_keyword_cannot_count_as_two_independent_sources(self):
        rows = [
            {"keyword": "火锅体验攻略", "category": "美食", "source": source, "count": 6}
            for source in ("search_recommend", "search_phrase")
        ]
        bounded = trends_contract.bound_keyword_rows(rows)
        self.assertEqual(len(bounded), 1)
        self.assertFalse(self.freshness(bounded)["latest_run_domain_source_health"]["美食"]["ok"])

    def test_shared_first_keyword_uses_an_available_distinct_pair(self):
        shared = {"keyword": "火锅体验攻略", "category": "美食", "count": 6}
        rows = [dict(shared, source="search_recommend"), dict(shared, source="search_phrase")]
        rows += rows_for("美食", "search_recommend", 6, 1, "特色火锅")
        bounded = trends_contract.bound_keyword_rows(rows)
        self.assertEqual(len({r["keyword"] for r in bounded}), 2)
        self.assertEqual({r["source"] for r in bounded}, {"search_recommend", "search_phrase"})
        self.assertTrue(self.freshness(bounded)["latest_run_domain_source_health"]["美食"]["ok"])

    def test_filtered_recommend_cannot_reserve_a_source_slot(self):
        weak = {"keyword": "好看", "category": "穿搭", "source": "search_recommend",
                "count": 1, "quality_score": 100}
        self.assertIsNone(hot_keywords.clean_scraped_keyword_row(weak))
        rows = rows_for("穿搭", "search_phrase", 8)
        rows += [weak, dict(weak, keyword="穿搭视频素材")]
        bounded = trends_contract.bound_keyword_rows(rows)
        self.assertEqual(len(bounded), 15)
        self.assertEqual({r["source"] for r in bounded}, {"search_phrase"})
        self.assertFalse(self.freshness(bounded)["latest_run_domain_source_health"]["穿搭"]["ok"])

    def test_sources_are_not_borrowed_from_another_domain(self):
        rows = rows_for("美食", "search_recommend", 6, 30) + rows_for("旅行", "search_phrase", 8, 30)
        result = self.freshness(trends_contract.bound_keyword_rows(rows))
        self.assertFalse(result["latest_run_domain_source_health"]["美食"]["ok"])
        self.assertFalse(result["latest_run_domain_source_health"]["旅行"]["ok"])

    def test_too_few_real_keywords_are_not_padded_to_pass(self):
        rows = rows_for("美食", "search_recommend", 6, 10) + rows_for("美食", "search_phrase", 1, 1)
        bounded = trends_contract.bound_keyword_rows(rows)
        result = self.freshness(bounded)
        self.assertEqual(len(bounded), 11)
        self.assertEqual(result["latest_run_domain_counts"]["美食"], 11)
        self.assertFalse(result["overview"]["ok"])

    def test_deterministic_repeat_selection_and_input_provenance_unchanged(self):
        rows = rows_for("美食", "search_recommend", 6) + rows_for("美食", "search_phrase", 1)
        before = copy.deepcopy(rows)
        first = trends_contract.bound_keyword_rows(rows)
        reverse = trends_contract.bound_keyword_rows(list(reversed(rows)))
        again = trends_contract.bound_keyword_rows(first)
        identity = lambda values: [(r["category"], r["keyword"], r["source"]) for r in values]
        self.assertEqual(identity(first), identity(reverse))
        self.assertEqual(identity(first), identity(again))
        self.assertEqual(rows, before)
        self.assertLessEqual(len(first), 15)
        self.assertTrue(set(identity(first)).issubset(set(identity(rows))))


if __name__ == "__main__":
    unittest.main()
