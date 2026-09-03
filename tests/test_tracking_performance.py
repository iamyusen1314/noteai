import asyncio
import importlib
import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("NOTEAI_FACT_SEARCH", "0")

api = importlib.import_module("api")
perf = importlib.import_module("performance_scoring")
crawler = importlib.import_module("crawler")


class PerformanceScoringTests(unittest.TestCase):
    def test_manual_tracking_score_reports_confidence_and_training_flag(self):
        score = perf.score_performance(
            domain="美食",
            likes=120,
            saves=80,
            comments=14,
            views=900,
            predicted_ces=68.0,
            evidence_source="manual",
            window="7d",
        )

        self.assertGreater(score.actual_ces, 0)
        self.assertIn(score.grade, {"优秀", "良好", "待改进", "需优化"})
        self.assertEqual(score.evidence_source, "manual")
        self.assertFalse(score.views_estimated)
        self.assertEqual(score.confidence_label, "中")
        self.assertIn("strongest_signal", score.insights)
        self.assertIn("prediction_delta", score.insights)

    def test_estimated_views_reduce_confidence(self):
        explicit = perf.score_performance(
            domain="美食",
            likes=60,
            saves=30,
            comments=5,
            views=700,
            evidence_source="crawler",
            window="7d",
        )
        estimated = perf.score_performance(
            domain="美食",
            likes=60,
            saves=30,
            comments=5,
            views=None,
            evidence_source="crawler",
            window="7d",
        )

        self.assertFalse(explicit.views_estimated)
        self.assertTrue(estimated.views_estimated)
        self.assertLess(estimated.confidence, explicit.confidence)


class CrawlerSidecarFallbackTests(unittest.TestCase):
    def test_sidecar_fallback_returns_tracking_metrics(self):
        original_xhs_acquisition = crawler.xhs_acquisition
        old_url = os.environ.get("NOTEAI_XHS_DOWNLOADER_URL")
        captured = {}

        class FakeAcquisition:
            @staticmethod
            def fetch_detail_with_sidecar(url, domain=""):
                captured["url"] = url
                captured["domain"] = domain
                return {
                    "ok": True,
                    "normalized": {
                        "has_content": True,
                        "has_metrics": True,
                        "title": "真实笔记标题",
                        "likes": 292,
                        "saves": 252,
                        "comments": 747,
                    },
                }

        try:
            os.environ["NOTEAI_XHS_DOWNLOADER_URL"] = "http://127.0.0.1:5556"
            crawler.xhs_acquisition = FakeAcquisition

            data = asyncio.run(crawler._extract_note_data_with_sidecar(
                "http://xhslink.com/o/example",
                domain="美食",
            ))

            self.assertEqual(captured["domain"], "美食")
            self.assertEqual(data["likes"], 292)
            self.assertEqual(data["saves"], 252)
            self.assertEqual(data["comments"], 747)
            self.assertEqual(data["title"], "真实笔记标题")
        finally:
            crawler.xhs_acquisition = original_xhs_acquisition
            if old_url is None:
                os.environ.pop("NOTEAI_XHS_DOWNLOADER_URL", None)
            else:
                os.environ["NOTEAI_XHS_DOWNLOADER_URL"] = old_url


class TrackingApiContractTests(unittest.TestCase):
    def test_track_url_persists_source_note_root_and_title(self):
        original_db = api._db

        class FakeDB:
            def __init__(self):
                self.executed = []

            def fetchone(self, sql, params=()):
                if "FROM tracked_notes" in sql:
                    return None
                if "title,body,domain" in sql and params == ("note-v2", "u1"):
                    return {
                        "id": "note-v2",
                        "title": "版本二标题",
                        "body": "正文",
                        "domain": "美食",
                        "score": 72.0,
                        "grade": "良好",
                        "version": 2,
                        "parent_id": "note-root",
                    }
                if "SELECT id,parent_id FROM notes" in sql and params == ("note-v2", "u1"):
                    return {"id": "note-v2", "parent_id": "note-root"}
                if "SELECT id,parent_id FROM notes" in sql and params == ("note-root", "u1"):
                    return {"id": "note-root", "parent_id": None}
                return None

            def execute(self, sql, params=()):
                self.executed.append((sql, params))

        fake_db = FakeDB()
        try:
            api._db = fake_db
            resp = asyncio.run(api.track_url(
                api.TrackUrlInput(
                    xhs_url="https://www.xiaohongshu.com/explore/0123456789abcdef01234567",
                    source_note_id="note-v2",
                    note_title="版本二标题",
                    predicted_ces=None,
                ),
                user={"id": "u1"},
            ))

            insert_params = fake_db.executed[-1][1]
            self.assertEqual(resp["source_note_id"], "note-v2")
            self.assertEqual(resp["source_root_note_id"], "note-root")
            self.assertEqual(insert_params[2], "note-v2")
            self.assertEqual(insert_params[3], "note-root")
            self.assertEqual(insert_params[7], "版本二标题")
            self.assertEqual(insert_params[9], 72.0)
            self.assertEqual(insert_params[13], "pending")
        finally:
            api._db = original_db

    def test_manual_fill_writes_growth_record_to_source_note(self):
        original_db = api._db
        original_add_context = api._memory.add_context

        class FakeDB:
            def __init__(self):
                self.executed = []

            def fetchone(self, sql, params=()):
                if "FROM tracked_notes" in sql:
                    return {
                        "id": "track-1",
                        "user_id": "u1",
                        "source_note_id": "note-v2",
                        "note_title": "版本二标题",
                        "domain": "美食",
                        "predicted_ces": 70.0,
                        "likes_24h": 30,
                        "saves_24h": 20,
                        "comments_24h": 3,
                        "status": "needs_manual",
                        "active_attempt_id": None,
                    }
                return None

            def execute(self, sql, params=()):
                self.executed.append((sql, params))

        fake_db = FakeDB()
        try:
            api._db = fake_db
            api._memory.add_context = lambda *args, **kwargs: None
            resp = asyncio.run(api.fill_tracking_data(
                "track-1",
                api.ManualFillInput(likes=120, saves=80, comments=12, views=900),
                user={"id": "u1"},
            ))

            growth_inserts = [
                params for sql, params in fake_db.executed
                if sql.startswith("INSERT INTO growth_records")
            ]
            self.assertTrue(resp["ok"])
            self.assertEqual(resp["confidence_label"], "中")
            self.assertEqual(growth_inserts[-1][2], "note-v2")
        finally:
            api._db = original_db
            api._memory.add_context = original_add_context


if __name__ == "__main__":
    unittest.main()
