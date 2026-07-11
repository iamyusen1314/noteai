import asyncio
import importlib
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

hot_keywords = importlib.import_module("hot_keywords")
market_timing_worker = importlib.import_module("market_timing_worker")
xhs_acquisition = importlib.import_module("xhs_acquisition")
xhs_health_probe = importlib.import_module("xhs_health_probe")
admin_server = importlib.import_module("admin_server")
scheduler_a = importlib.import_module("scheduler_a")


def _real_xhs_rows() -> list[dict]:
    rows = []
    for domain in hot_keywords.CORE_EVIDENCE_DOMAINS:
        for row in hot_keywords.baseline_evidence_rows((domain,), min_per_domain=16):
            cloned = dict(row)
            cloned["source"] = "search_phrase"
            cloned["count"] = 4
            rows.append(cloned)
    return rows


class XHSAcquisitionLedgerTests(unittest.TestCase):
    def test_baseline_rows_do_not_satisfy_real_xhs_freshness(self):
        original_db = hot_keywords.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                result = xhs_acquisition.record_scrape_freshness(
                    hot_keywords.baseline_evidence_rows(("美食",), min_per_domain=16),
                    run_id="baseline-only",
                    domains=("美食",),
                )

                self.assertFalse(result["overview"]["ok"])
                status = xhs_acquisition.freshness_status("美食")
                self.assertFalse(status["ok"])
                self.assertEqual(status["evidence_count"], 0)
                self.assertEqual(status["status"], "insufficient")
        finally:
            hot_keywords.DB_PATH = original_db

    def test_real_xhs_rows_satisfy_core_domain_freshness(self):
        original_db = hot_keywords.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                result = xhs_acquisition.record_scrape_freshness(_real_xhs_rows(), run_id="real-xhs")

                self.assertTrue(result["overview"]["ok"])
                self.assertEqual(result["overview"]["missing_domains"], [])
                for domain in hot_keywords.CORE_EVIDENCE_DOMAINS:
                    status = xhs_acquisition.freshness_status(domain)
                    self.assertTrue(status["ok"], domain)
                    self.assertGreaterEqual(status["evidence_count"], status["minimum"])
        finally:
            hot_keywords.DB_PATH = original_db

    def test_same_day_real_evidence_accumulates_by_unique_keyword(self):
        original_db = hot_keywords.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                rows = []
                for row in hot_keywords.baseline_evidence_rows(("美食",), min_per_domain=16):
                    cloned = dict(row)
                    cloned["source"] = "search_phrase"
                    cloned["count"] = 4
                    rows.append(cloned)

                first = xhs_acquisition.record_scrape_freshness(
                    rows[:7], run_id="accumulate-1", domains=("美食",), min_count=12,
                    session_status={"configured": True, "auth_cookie_present": True},
                )
                self.assertFalse(first["overview"]["ok"])
                self.assertEqual(first["overview"]["domains"][0]["evidence_count"], 7)

                duplicate = xhs_acquisition.record_scrape_freshness(
                    rows[:7], run_id="accumulate-duplicate", domains=("美食",), min_count=12,
                    session_status={"configured": True, "auth_cookie_present": True},
                )
                self.assertEqual(duplicate["overview"]["domains"][0]["evidence_count"], 7)

                completed = xhs_acquisition.record_scrape_freshness(
                    rows[7:14], run_id="accumulate-2", domains=("美食",), min_count=12,
                    session_status={"configured": True, "auth_cookie_present": True},
                )
                self.assertTrue(completed["overview"]["ok"])
                self.assertEqual(completed["overview"]["domains"][0]["evidence_count"], 13)
        finally:
            hot_keywords.DB_PATH = original_db

    def test_zero_evidence_records_actionable_cookie_health(self):
        original_db = hot_keywords.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                xhs_acquisition.record_scrape_freshness(
                    [], run_id="missing-cookie", domains=("美食",),
                    session_status={"configured": False, "auth_cookie_present": False},
                )
                health = xhs_acquisition.recent_health(domain="美食", adapter="scheduler_a")
                self.assertEqual(health[0]["status"], "failed")
                self.assertEqual(health[0]["error_code"], "cookie_not_configured")
                self.assertTrue(health[0]["risk_login_detected"])
        finally:
            hot_keywords.DB_PATH = original_db

    def test_session_summary_never_exposes_cookie_values(self):
        future = 4_102_444_800
        state = {"cookies": [
            {"name": "web_session", "value": "secret-session", "expires": future},
            {"name": "a1", "value": "secret-device", "expires": future},
        ]}
        with patch.object(scheduler_a, "_get_session_state", return_value=state):
            summary = scheduler_a.session_state_summary()
        self.assertTrue(summary["configured"])
        self.assertTrue(summary["auth_cookie_present"])
        self.assertFalse(summary["auth_cookie_expired"])
        self.assertEqual(summary["cookie_count"], 2)
        self.assertNotIn("secret-session", json.dumps(summary))
        self.assertNotIn("secret-device", json.dumps(summary))

    def test_worker_xhs_required_exports_baseline_with_warning(self):
        original_db = hot_keywords.DB_PATH
        original_scrape_once = market_timing_worker.scrape_once
        old_required = os.environ.get("NOTEAI_XHS_FRESHNESS_REQUIRED")
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                hot_keywords.DB_PATH = tmp / "hot_keywords.db"
                os.environ["NOTEAI_XHS_FRESHNESS_REQUIRED"] = "1"

                async def empty_scrape():
                    return []

                market_timing_worker.scrape_once = empty_scrape
                snapshot_path = tmp / "market_timing_snapshot.json"
                result = asyncio.run(market_timing_worker.run_once(snapshot_path))

                self.assertTrue(snapshot_path.exists())
                self.assertFalse(result["xhs_freshness_ok"])
                self.assertIn("XHS_FRESH_EVIDENCE_UNAVAILABLE", result["xhs_freshness_warning"])
                self.assertEqual(result["evidence_mode"], "baseline_or_partial")
                payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
                self.assertEqual(payload["domains"]["美食"]["keywords"][0]["source"], "industry_baseline")
        finally:
            hot_keywords.DB_PATH = original_db
            market_timing_worker.scrape_once = original_scrape_once
            if old_required is None:
                os.environ.pop("NOTEAI_XHS_FRESHNESS_REQUIRED", None)
            else:
                os.environ["NOTEAI_XHS_FRESHNESS_REQUIRED"] = old_required

    def test_worker_explicit_hard_fail_raises_after_local_snapshot(self):
        original_db = hot_keywords.DB_PATH
        original_scrape_once = market_timing_worker.scrape_once
        old_required = os.environ.get("NOTEAI_XHS_FRESHNESS_REQUIRED")
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                hot_keywords.DB_PATH = tmp / "hot_keywords.db"
                os.environ["NOTEAI_XHS_FRESHNESS_REQUIRED"] = "1"

                async def empty_scrape():
                    return []

                market_timing_worker.scrape_once = empty_scrape
                snapshot_path = tmp / "market_timing_snapshot.json"
                with self.assertRaisesRegex(RuntimeError, "XHS_FRESH_EVIDENCE_UNAVAILABLE"):
                    asyncio.run(market_timing_worker.run_once(
                        snapshot_path,
                        hard_fail_on_xhs_missing=True,
                    ))
                self.assertTrue(snapshot_path.exists())
        finally:
            hot_keywords.DB_PATH = original_db
            market_timing_worker.scrape_once = original_scrape_once
            if old_required is None:
                os.environ.pop("NOTEAI_XHS_FRESHNESS_REQUIRED", None)
            else:
                os.environ["NOTEAI_XHS_FRESHNESS_REQUIRED"] = old_required

    def test_worker_hard_gate_allows_real_xhs_snapshot(self):
        original_db = hot_keywords.DB_PATH
        original_scrape_once = market_timing_worker.scrape_once
        old_required = os.environ.get("NOTEAI_XHS_FRESHNESS_REQUIRED")
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                hot_keywords.DB_PATH = tmp / "hot_keywords.db"
                os.environ["NOTEAI_XHS_FRESHNESS_REQUIRED"] = "1"

                async def real_scrape():
                    return _real_xhs_rows()

                market_timing_worker.scrape_once = real_scrape
                snapshot_path = tmp / "market_timing_snapshot.json"
                result = asyncio.run(market_timing_worker.run_once(snapshot_path))
                self.assertTrue(result["xhs_freshness_overview"]["ok"])
                self.assertTrue(snapshot_path.exists())
                payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
                self.assertIn("美食", payload["domains"])
                self.assertNotEqual(payload["domains"]["美食"]["keywords"][0]["source"], "industry_baseline")
        finally:
            hot_keywords.DB_PATH = original_db
            market_timing_worker.scrape_once = original_scrape_once
            if old_required is None:
                os.environ.pop("NOTEAI_XHS_FRESHNESS_REQUIRED", None)
            else:
                os.environ["NOTEAI_XHS_FRESHNESS_REQUIRED"] = old_required

    def test_recent_health_probe_and_cli_exit_code(self):
        original_db = hot_keywords.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                xhs_acquisition.record_health(xhs_acquisition.CrawlerHealth(
                    run_id="health-run",
                    adapter="scheduler_a",
                    domain="美食",
                    status="insufficient",
                    evidence_count=3,
                    error_code="selector_changed",
                    error_summary="selector drift",
                ))
                recent = xhs_acquisition.recent_health(domain="美食")
                self.assertEqual(len(recent), 1)
                self.assertEqual(recent[0]["adapter"], "scheduler_a")
                self.assertEqual(recent[0]["error_code"], "selector_changed")

                probe = xhs_acquisition.freshness_probe(("美食",), deadline_hour=0)
                self.assertFalse(probe["ok"])
                self.assertTrue(probe["action_required"])
                self.assertIn("美食", probe["missing_domains"])

                with patch.object(sys, "argv", ["xhs_health_probe.py", "--domain", "美食", "--deadline-hour", "0"]):
                    with redirect_stdout(io.StringIO()):
                        self.assertEqual(xhs_health_probe.main(), 2)
        finally:
            hot_keywords.DB_PATH = original_db

    def test_sidecar_not_configured_records_failed_health_without_network(self):
        original_db = hot_keywords.DB_PATH
        old_url = os.environ.pop("NOTEAI_XHS_DOWNLOADER_URL", None)
        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                result = xhs_acquisition.fetch_detail_with_sidecar(
                    "https://www.xiaohongshu.com/explore/test",
                    domain="美食",
                    run_id="sidecar-run",
                )
                self.assertFalse(result["ok"])
                self.assertEqual(result["error_code"], "sidecar_not_configured")
                health = xhs_acquisition.recent_health(adapter="xhs_downloader")
                self.assertEqual(len(health), 1)
                self.assertEqual(health[0]["status"], "failed")
                self.assertFalse(health[0]["note_page_access_valid"])
        finally:
            hot_keywords.DB_PATH = original_db
            if old_url is not None:
                os.environ["NOTEAI_XHS_DOWNLOADER_URL"] = old_url

    def test_sidecar_success_normalizes_detail_and_records_health(self):
        original_db = hot_keywords.DB_PATH
        old_url = os.environ.get("NOTEAI_XHS_DOWNLOADER_URL")
        original_client = xhs_acquisition.httpx.Client
        captured = {}

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "data": {
                        "note": {
                            "note_id": "note-123",
                            "display_title": "真实笔记标题",
                            "desc": "真实笔记正文",
                            "interact_info": {
                                "liked_count": "1.2万",
                                "collected_count": "88",
                                "comments_count": 7,
                            },
                        }
                    }
                }

        class FakeClient:
            def __init__(self, *args, **kwargs):
                captured["init"] = kwargs

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def post(self, url, json=None):
                captured["url"] = url
                captured["payload"] = json
                return FakeResponse()

        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                os.environ["NOTEAI_XHS_DOWNLOADER_URL"] = "http://sidecar.local"
                xhs_acquisition.httpx.Client = FakeClient

                result = xhs_acquisition.fetch_detail_with_sidecar(
                    "https://www.xiaohongshu.com/explore/test",
                    domain="美食",
                    run_id="sidecar-ok",
                )
                self.assertTrue(result["ok"])
                self.assertEqual(captured["url"], "http://sidecar.local/xhs/detail")
                self.assertEqual(captured["payload"]["url"], "https://www.xiaohongshu.com/explore/test")
                self.assertEqual(result["normalized"]["likes"], 12000)
                self.assertEqual(result["normalized"]["saves"], 88)
                health = xhs_acquisition.recent_health(adapter="xhs_downloader")
                self.assertEqual(health[0]["status"], "ok")
                self.assertTrue(health[0]["selector_valid"])
                self.assertEqual(health[0]["evidence_count"], 1)
        finally:
            hot_keywords.DB_PATH = original_db
            xhs_acquisition.httpx.Client = original_client
            if old_url is None:
                os.environ.pop("NOTEAI_XHS_DOWNLOADER_URL", None)
            else:
                os.environ["NOTEAI_XHS_DOWNLOADER_URL"] = old_url

    def test_sidecar_normalizes_xhs_downloader_chinese_schema(self):
        payload = {
            "data": {
                "作品ID": "6a2264420000000035032a92",
                "作者ID": "author-123",
                "作品标题": "真实笔记标题",
                "作品描述": "真实笔记正文",
                "点赞数量": "1.1万",
                "收藏数量": "2,345",
                "评论数量": "67",
                "分享数量": 8,
                "下载地址": ["https://example.invalid/a.jpg"],
            },
            "message": "success",
        }

        normalized = xhs_acquisition.normalize_sidecar_detail(payload)

        self.assertTrue(normalized["has_content"])
        self.assertTrue(normalized["has_metrics"])
        self.assertEqual(normalized["note_id"], "6a2264420000000035032a92")
        self.assertEqual(normalized["title"], "真实笔记标题")
        self.assertEqual(normalized["desc"], "真实笔记正文")
        self.assertEqual(normalized["likes"], 11000)
        self.assertEqual(normalized["saves"], 2345)
        self.assertEqual(normalized["comments"], 67)
        self.assertEqual(normalized["shares"], 8)

    def test_sidecar_http_failure_records_risk_login(self):
        original_db = hot_keywords.DB_PATH
        old_url = os.environ.get("NOTEAI_XHS_DOWNLOADER_URL")
        original_client = xhs_acquisition.httpx.Client

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def post(self, url, json=None):
                raise xhs_acquisition.httpx.HTTPStatusError(
                    "403 login required",
                    request=None,
                    response=None,
                )

        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                os.environ["NOTEAI_XHS_DOWNLOADER_URL"] = "http://sidecar.local"
                xhs_acquisition.httpx.Client = FakeClient

                result = xhs_acquisition.fetch_detail_with_sidecar(
                    "https://www.xiaohongshu.com/explore/test",
                    domain="美食",
                    run_id="sidecar-fail",
                )
                self.assertFalse(result["ok"])
                health = xhs_acquisition.recent_health(adapter="xhs_downloader")
                self.assertEqual(health[0]["status"], "failed")
                self.assertTrue(health[0]["risk_login_detected"])
        finally:
            hot_keywords.DB_PATH = original_db
            xhs_acquisition.httpx.Client = original_client
            if old_url is None:
                os.environ.pop("NOTEAI_XHS_DOWNLOADER_URL", None)
            else:
                os.environ["NOTEAI_XHS_DOWNLOADER_URL"] = old_url

    def test_admin_xhs_handlers_read_freshness_and_health(self):
        original_db = hot_keywords.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                xhs_acquisition.record_scrape_freshness(_real_xhs_rows(), run_id="admin-read")
                xhs_acquisition.record_health(xhs_acquisition.CrawlerHealth(
                    run_id="admin-read",
                    adapter="scheduler_a",
                    domain="美食",
                    status="ok",
                    evidence_count=16,
                ))

                freshness = asyncio.run(admin_server.admin_xhs_freshness(admin={"username": "admin"}))
                health = asyncio.run(admin_server.admin_xhs_health(admin={"username": "admin"}))
                self.assertTrue(freshness["ok"])
                self.assertIn("health", health)
                self.assertGreaterEqual(len(health["health"]), 1)
                self.assertIn("sidecar", health)
        finally:
            hot_keywords.DB_PATH = original_db


if __name__ == "__main__":
    unittest.main()
