import importlib
import asyncio
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

hot_keywords = importlib.import_module("hot_keywords")
scheduler_a = importlib.import_module("scheduler_a")
market_timing_worker = importlib.import_module("market_timing_worker")


class MarketTimingKeywordQualityTests(unittest.TestCase):
    def test_scraped_keyword_cleaner_filters_generic_noise(self):
        self.assertIsNone(hot_keywords.clean_scraped_keyword_row({
            "keyword": "真的",
            "category": "美食",
            "source": "homefeed_token",
            "search_vol": 90,
            "count": 6,
        }))
        self.assertIsNone(hot_keywords.clean_scraped_keyword_row({
            "keyword": "哈哈哈",
            "category": "情感",
            "source": "homefeed_token",
            "search_vol": 90,
            "count": 3,
        }))

    def test_scraped_keyword_cleaner_keeps_domain_specific_signals(self):
        food = hot_keywords.clean_scraped_keyword_row({
            "keyword": "芝士焗小青龙",
            "category": "美食",
            "source": "homefeed_phrase",
            "search_vol": 50,
            "count": 3,
        })
        self.assertIsNotNone(food)
        self.assertGreater(food["search_vol"], 50)
        self.assertIn("domain_hint", food["quality_reason"])
        self.assertGreaterEqual(food["quality_score"], 74)
        self.assertEqual(food["evidence_level"], "strong")

        travel = hot_keywords.clean_scraped_keyword_row({
            "keyword": "新疆旅游攻略",
            "category": "旅行",
            "source": "homefeed_phrase",
            "search_vol": 50,
            "count": 2,
        })
        self.assertIsNotNone(travel)
        self.assertIn("domain_hint", travel["quality_reason"])

        beauty = hot_keywords.clean_scraped_keyword_row({
            "keyword": "夏天防晒底妆",
            "category": "美妆",
            "source": "homefeed_phrase",
            "search_vol": 50,
            "count": 2,
        })
        self.assertIsNotNone(beauty)
        self.assertIn("domain_hint", beauty["quality_reason"])

        makeup = hot_keywords.clean_scraped_keyword_row({
            "keyword": "makeup",
            "category": "美妆",
            "source": "homefeed_phrase",
            "search_vol": 50,
            "count": 2,
        })
        self.assertIsNotNone(makeup)
        self.assertIn("domain_hint", makeup["quality_reason"])

        search_food = hot_keywords.clean_scraped_keyword_row({
            "keyword": "番禺粤菜探店",
            "category": "美食",
            "source": "search_phrase",
            "search_vol": 50,
            "count": 1,
        })
        self.assertIsNotNone(search_food)
        self.assertGreaterEqual(search_food["quality_score"], 74)
        self.assertEqual(search_food["evidence_level"], "strong")
        self.assertIn("search_discovery", search_food["quality_reason"])

        recommend_food = hot_keywords.clean_scraped_keyword_row({
            "keyword": "美食探店路边摊",
            "category": "美食",
            "source": "search_recommend",
            "search_vol": 50,
            "count": 6,
        })
        self.assertIsNotNone(recommend_food)
        self.assertGreaterEqual(recommend_food["quality_score"], 74)
        self.assertEqual(recommend_food["evidence_level"], "strong")
        self.assertIn("search_recommend", recommend_food["quality_reason"])

        baseline_food = hot_keywords.clean_scraped_keyword_row({
            "keyword": "本地美食探店",
            "category": "美食",
            "source": "industry_baseline",
            "search_vol": 60,
            "count": 3,
        })
        self.assertIsNotNone(baseline_food)
        self.assertGreaterEqual(baseline_food["quality_score"], 55)
        self.assertEqual(baseline_food["evidence_level"], "medium")
        self.assertIn("industry_baseline", baseline_food["quality_reason"])

    def test_scraped_keyword_cleaner_blocks_domain_mismatch_tokens(self):
        self.assertIsNone(hot_keywords.clean_scraped_keyword_row({
            "keyword": "面试",
            "category": "美食",
            "source": "homefeed_token",
            "search_vol": 80,
            "count": 5,
        }))
        self.assertIsNone(hot_keywords.clean_scraped_keyword_row({
            "keyword": "clean",
            "category": "美妆",
            "source": "homefeed_phrase",
            "search_vol": 80,
            "count": 2,
        }))
        self.assertIsNone(hot_keywords.clean_scraped_keyword_row({
            "keyword": "厨房",
            "category": "美食",
            "source": "homefeed_token",
            "search_vol": 80,
            "count": 3,
        }))
        self.assertIsNone(hot_keywords.clean_scraped_keyword_row({
            "keyword": "下午5点左右给大家上一些一叶一芽",
            "category": "家居",
            "source": "homefeed_phrase",
            "search_vol": 80,
            "count": 1,
        }))
        self.assertIsNone(hot_keywords.clean_scraped_keyword_row({
            "keyword": "美食探店博主怎么做",
            "category": "美食",
            "source": "search_recommend",
            "search_vol": 80,
            "count": 6,
        }))
        self.assertIsNone(hot_keywords.clean_scraped_keyword_row({
            "keyword": "旅行攻略excel",
            "category": "旅行",
            "source": "search_recommend",
            "search_vol": 80,
            "count": 6,
        }))
        self.assertIsNotNone(hot_keywords.clean_scraped_keyword_row({
            "keyword": "装修避坑指南",
            "category": "家居",
            "source": "search_recommend",
            "search_vol": 80,
            "count": 6,
        }))

    def test_upsert_keywords_applies_cleaning_before_storage(self):
        original_db = hot_keywords.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                hot_keywords.init_db()
                hot_keywords.upsert_keywords([
                    {"keyword": "真的", "search_vol": 90, "trend_dir": 1, "source": "homefeed_token", "category": "美食", "count": 9},
                    {"keyword": "面试", "search_vol": 90, "trend_dir": 1, "source": "homefeed_token", "category": "美食", "count": 8},
                    {"keyword": "番禺粤菜探店", "search_vol": 70, "trend_dir": 1, "source": "homefeed_phrase", "category": "美食", "count": 3},
                ])
                with sqlite3.connect(str(hot_keywords.DB_PATH)) as conn:
                    rows = conn.execute("SELECT keyword, category, source FROM hot_keywords").fetchall()
                self.assertEqual(rows, [("番禺粤菜探店", "美食", "homefeed_phrase")])
        finally:
            hot_keywords.DB_PATH = original_db

    def test_market_timing_requires_minimum_qualified_domain_evidence(self):
        original_db = hot_keywords.DB_PATH
        old_min = hot_keywords.os.environ.get("NOTEAI_MARKET_TIMING_MIN_DOMAIN_KEYWORDS")
        try:
            hot_keywords.os.environ["NOTEAI_MARKET_TIMING_MIN_DOMAIN_KEYWORDS"] = "12"
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                hot_keywords.init_db()
                hot_keywords.upsert_keywords([
                    {
                        "keyword": f"番禺粤菜探店{i}",
                        "search_vol": 80,
                        "trend_dir": 1,
                        "source": "homefeed_phrase",
                        "category": "美食",
                        "count": 3,
                    }
                    for i in range(8)
                ])
                status = hot_keywords.db_status("美食")
                self.assertEqual(status["domain_keyword_count"], 8)
                self.assertFalse(status["has_fresh_domain_data"])
                timing = hot_keywords.compute_market_timing("番禺粤菜探店1", "粤菜餐厅", "美食")
                self.assertTrue(timing["data_stale"])
                self.assertIn("8/12", timing["confidence_note"])
        finally:
            hot_keywords.DB_PATH = original_db
            if old_min is None:
                hot_keywords.os.environ.pop("NOTEAI_MARKET_TIMING_MIN_DOMAIN_KEYWORDS", None)
            else:
                hot_keywords.os.environ["NOTEAI_MARKET_TIMING_MIN_DOMAIN_KEYWORDS"] = old_min

    def test_scheduler_channels_cover_core_business_domains(self):
        categories = {name for _, name in scheduler_a.CHANNELS}
        for required in {"美食", "旅行", "穿搭", "美妆", "家居", "健身"}:
            self.assertIn(required, categories)

    def test_scheduler_search_discovery_covers_core_business_domains(self):
        for required in {"美食", "旅行", "穿搭", "美妆", "家居", "健身"}:
            self.assertIn(required, scheduler_a.SEARCH_SEEDS)
            self.assertGreaterEqual(len(scheduler_a.SEARCH_SEEDS[required]), 2)
        self.assertIn("%E7%BE%8E%E9%A3%9F", scheduler_a._search_url("美食探店"))

    def test_daily_baseline_pack_covers_core_domains_when_db_is_empty(self):
        original_db = hot_keywords.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                result = hot_keywords.ensure_daily_evidence_pack()
                self.assertEqual(set(result["domains"]), set(hot_keywords.CORE_EVIDENCE_DOMAINS))
                status = hot_keywords.db_status("美食")
                self.assertTrue(status["has_fresh_domain_data"])
                self.assertGreaterEqual(status["domain_qualified_keyword_count"], 12)
                self.assertGreaterEqual(status["domain_source_breakdown"].get("industry_baseline", 0), 12)
        finally:
            hot_keywords.DB_PATH = original_db

    def test_baseline_evidence_is_fresh_but_not_fake_trending(self):
        original_db = hot_keywords.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                hot_keywords.ensure_daily_evidence_pack(("美食",))
                timing = hot_keywords.compute_market_timing("本地美食探店", "周末想找粤菜餐厅", "美食")
                self.assertFalse(timing["data_stale"])
                self.assertFalse(timing["evidence_unavailable"])
                self.assertGreaterEqual(timing["source_breakdown"].get("industry_baseline", 0), 12)
                self.assertEqual(timing["is_trending_topic"], 0.0)
                self.assertLessEqual(timing["timing_coefficient"], 1.05)
                self.assertIn("不代表平台官方热搜", timing["confidence_note"])
        finally:
            hot_keywords.DB_PATH = original_db

    def test_worker_exports_baseline_pack_when_scrape_is_empty(self):
        original_db = hot_keywords.DB_PATH
        original_scrape_once = market_timing_worker.scrape_once
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                hot_keywords.DB_PATH = tmp / "hot_keywords.db"

                async def empty_scrape():
                    return []

                market_timing_worker.scrape_once = empty_scrape
                result = asyncio.run(market_timing_worker.run_once(tmp / "market_timing_snapshot.json"))
                self.assertEqual(result["keywords"], 0)
                self.assertEqual(result["baseline"].get("source"), "industry_baseline")
                self.assertEqual(set(result["domains"]), set(hot_keywords.CORE_EVIDENCE_DOMAINS))
                payload = json.loads((tmp / "market_timing_snapshot.json").read_text(encoding="utf-8"))
                self.assertIn("美食", payload["domains"])
                self.assertEqual(payload["domains"]["美食"]["keywords"][0]["source"], "industry_baseline")
        finally:
            hot_keywords.DB_PATH = original_db
            market_timing_worker.scrape_once = original_scrape_once


if __name__ == "__main__":
    unittest.main()
