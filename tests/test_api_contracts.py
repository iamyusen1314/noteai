import asyncio
import base64
import importlib
import json
import os
import sys
import tempfile
import unittest
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import HTTPException
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("NOTEAI_FACT_SEARCH", "0")

api = importlib.import_module("api")
facts = importlib.import_module("fact_enrichment")
feature_extraction = importlib.import_module("feature_extraction")
hot_keywords = importlib.import_module("hot_keywords")


class ApiContractTests(unittest.TestCase):
    def test_health_reports_local_v04_composite_model_label(self):
        original_use_v04 = api.USE_V04_COMPOSITE
        original_report_path = api.V04_TRAIN_REPORT_PATH

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            model_path = tmp_path / "model_v04_composite_regressor.lgb"
            model_path.write_text("placeholder", encoding="utf-8")
            report_path = tmp_path / "model_v04_composite_train_report.json"
            report_path.write_text(json.dumps({
                "training_policy": {"do_not_deploy": False},
                "deployment_gate": {"passed": True},
                "models": {"golden": {"regressor_path": str(model_path)}},
            }), encoding="utf-8")

            try:
                api.USE_V04_COMPOSITE = True
                api.V04_TRAIN_REPORT_PATH = report_path
                self.assertEqual(api._health_model_label(), "v0.4-composite")

                client = TestClient(api.app)
                resp = client.get("/health")
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json()["model"], "v0.4-composite")
            finally:
                api.USE_V04_COMPOSITE = original_use_v04
                api.V04_TRAIN_REPORT_PATH = original_report_path

    def test_health_falls_back_to_legacy_model_label_when_v04_is_not_ready(self):
        original_use_v04 = api.USE_V04_COMPOSITE
        original_report_path = api.V04_TRAIN_REPORT_PATH

        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "model_v04_composite_train_report.json"
            report_path.write_text(json.dumps({
                "training_policy": {"do_not_deploy": False},
                "deployment_gate": {"passed": False},
                "models": {"golden": {"regressor_path": str(Path(tmp) / "missing.lgb")}},
            }), encoding="utf-8")

            try:
                api.USE_V04_COMPOSITE = True
                api.V04_TRAIN_REPORT_PATH = report_path
                self.assertEqual(api._health_model_label(), "legacy_score_model")
            finally:
                api.USE_V04_COMPOSITE = original_use_v04
                api.V04_TRAIN_REPORT_PATH = original_report_path

    def test_anonymous_cost_endpoints_require_auth(self):
        client = TestClient(api.app)
        endpoints = [
            ("/score", {"note_title": "t", "desc": "body", "domain": "美食"}),
            ("/diagnose", {"note_title": "t", "desc": "body", "domain": "美食"}),
            ("/validate-ocr", {"ocr_results": [{"title": "t", "body": "b"}]}),
            ("/extract-screenshot", {"url": "https://example.com"}),
            ("/analyze", {"note_title": "t", "desc": "body", "domain": "美食"}),
            ("/generate", {"domain": "美食", "brief": "brief"}),
            ("/generate/stream", {"domain": "美食", "brief": "brief"}),
            ("/chat/start", {"note_title": "t", "note_body": "body", "domain": "美食"}),
            ("/chat/message", {"session_id": "s", "message": "帮我重写"}),
        ]
        for path, body in endpoints:
            with self.subTest(path=path):
                resp = client.post(path, json=body)
                self.assertEqual(resp.status_code, 401)

    def test_anonymous_market_timing_freshness_requires_auth(self):
        client = TestClient(api.app)
        resp = client.get("/market-timing/freshness")
        self.assertEqual(resp.status_code, 401)

    def test_extract_screenshot_refunds_charge_when_vision_fails(self):
        original_check = api._billing.check_and_deduct
        original_refund = api._billing.refund_operation_charge
        original_key = os.environ.pop("MOONSHOT_API_KEY", None)
        calls = []

        try:
            charge = {"source": "subscription", "credits_used": 0.5, "monthly_credits_used": 0.5, "usage_id": "u1"}
            api._billing.check_and_deduct = lambda user_id, op: charge
            api._billing.refund_operation_charge = lambda user_id, op, ch, desc: calls.append((user_id, op, ch, desc))

            async def run():
                return await api.extract_screenshot(
                    api.ScreenshotExtractInput(image_base64="abc"),
                    user={"id": "u-test"},
                )

            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(run())
        finally:
            api._billing.check_and_deduct = original_check
            api._billing.refund_operation_charge = original_refund
            if original_key is not None:
                os.environ["MOONSHOT_API_KEY"] = original_key

        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(calls, [("u-test", "screenshot", charge, "截图识别失败自动退回")])

    def test_extract_screenshot_preserves_uploaded_image_media_type(self):
        original_check = api._billing.check_and_deduct
        original_refund = api._billing.refund_operation_charge
        original_client = api._httpx.Client
        original_key = os.environ.get("MOONSHOT_API_KEY")
        captured = {}

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "choices": [{
                        "message": {
                            "content": '{"type":"B","title":"","body":"","domain":"美食","cover_desc":"一张清晰的菜品图"}'
                        }
                    }],
                    "usage": {},
                }

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def post(self, url, headers=None, json=None):
                captured["payload"] = json
                return FakeResponse()

        try:
            os.environ["MOONSHOT_API_KEY"] = "test-key"
            api._billing.check_and_deduct = lambda user_id, op: {"source": "subscription"}
            api._billing.refund_operation_charge = lambda *args, **kwargs: None
            api._httpx.Client = FakeClient
            png_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\nfake-png").decode()

            async def run():
                return await api.extract_screenshot(
                    api.ScreenshotExtractInput(image_base64=png_b64),
                    user={"id": "u-test"},
                )

            result = asyncio.run(run())
        finally:
            api._billing.check_and_deduct = original_check
            api._billing.refund_operation_charge = original_refund
            api._httpx.Client = original_client
            if original_key is None:
                os.environ.pop("MOONSHOT_API_KEY", None)
            else:
                os.environ["MOONSHOT_API_KEY"] = original_key

        image_url = captured["payload"]["messages"][0]["content"][0]["image_url"]["url"]
        self.assertTrue(image_url.startswith("data:image/png;base64,"))
        self.assertEqual(result["_media_type"], "image/png")
        self.assertTrue(result["is_photo_only"])
        self.assertEqual(result["tags"], "")

    def test_ocr_body_and_tags_are_separated_for_scoring(self):
        body, tags = api._split_ocr_body_and_tags(
            "点都德红米肠推荐。#广州美食 #北京路早茶[话题]#",
            ["#广州美食", "虾饺皇"],
        )
        self.assertEqual(body, "点都德红米肠推荐。")
        self.assertEqual(tags, "#广州美食 #北京路早茶 #虾饺皇")
        self.assertEqual(api._body_content_len_without_tags(body), 9)

    def test_validate_ocr_preserves_topics_as_separate_field(self):
        async def run():
            return await api.validate_ocr(
                api.ValidateOcrInput(ocr_results=[{
                    "type": "A",
                    "title": "点都德红米肠推荐",
                    "body": "红米肠外皮薄，虾肉弹。#广州美食 #北京路早茶",
                    "domain": "美食",
                }]),
                user={"id": "u-test"},
            )

        result = asyncio.run(run())
        self.assertEqual(result["body"], "红米肠外皮薄，虾肉弹。")
        self.assertEqual(result["tags"], "#广州美食 #北京路早茶")
        self.assertEqual(result["char_count"], 11)

    def test_validate_ocr_agent_merges_topics_without_polluting_body(self):
        original_call = api._mr.call
        original_usage = api._billing.record_free_usage

        async def fake_call(task, system, prompt, max_tokens=800):
            self.assertIn("话题不要混入正文", system)
            self.assertIn("话题:", prompt)
            return json.dumps({
                "title": "点都德红米肠推荐",
                "body": "红米肠外皮薄，虾肉弹。#广州美食",
                "tags": "#广州美食 #北京路早茶 #虾饺皇",
                "domain": "美食",
                "char_count": 11,
            }, ensure_ascii=False)

        try:
            api._mr.call = fake_call
            api._billing.record_free_usage = lambda *args, **kwargs: None

            async def run():
                return await api.validate_ocr(
                    api.ValidateOcrInput(ocr_results=[
                        {
                            "type": "A",
                            "title": "点都德红米肠推荐",
                            "body": "红米肠外皮薄，虾肉弹。#广州美食",
                            "tags": "#北京路早茶",
                            "domain": "美食",
                        },
                        {
                            "type": "A",
                            "title": "点都德红米肠推荐",
                            "body": "红米肠外皮薄，虾肉弹。#广州美食",
                            "tags": "#广州美食 #虾饺皇",
                            "domain": "美食",
                        },
                    ]),
                    user={"id": "u-test"},
                )

            result = asyncio.run(run())
        finally:
            api._mr.call = original_call
            api._billing.record_free_usage = original_usage

        self.assertEqual(result["body"], "红米肠外皮薄，虾肉弹。")
        self.assertEqual(result["tags"], "#广州美食 #北京路早茶 #虾饺皇")
        self.assertEqual(result["char_count"], 11)

    def test_extract_screenshot_maps_moonshot_network_error_to_503(self):
        original_check = api._billing.check_and_deduct
        original_refund = api._billing.refund_operation_charge
        original_client = api._httpx.Client
        original_key = os.environ.get("MOONSHOT_API_KEY")
        calls = []

        class FailingClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def post(self, *args, **kwargs):
                raise api._httpx.ProxyError("503 Service Unavailable")

        try:
            os.environ["MOONSHOT_API_KEY"] = "test-key"
            charge = {"source": "subscription", "credits_used": 0.5}
            api._billing.check_and_deduct = lambda user_id, op: charge
            api._billing.refund_operation_charge = lambda user_id, op, ch, desc: calls.append((user_id, op, ch, desc))
            api._httpx.Client = FailingClient
            jpg_b64 = base64.b64encode(b"\xff\xd8\xfffake-jpg").decode()

            async def run():
                return await api.extract_screenshot(
                    api.ScreenshotExtractInput(image_base64=jpg_b64),
                    user={"id": "u-test"},
                )

            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(run())
        finally:
            api._billing.check_and_deduct = original_check
            api._billing.refund_operation_charge = original_refund
            api._httpx.Client = original_client
            if original_key is None:
                os.environ.pop("MOONSHOT_API_KEY", None)
            else:
                os.environ["MOONSHOT_API_KEY"] = original_key

        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("Moonshot Vision 网络不可达", ctx.exception.detail)
        self.assertEqual(calls, [("u-test", "screenshot", charge, "截图识别失败自动退回")])

    def test_expert_opinion_evidence_is_bound_to_v04_sources(self):
        weakness = api.WeaknessItem(
            feature="domain_food_hours",
            label="餐饮营业时间槽位",
            value=0.0,
            benchmark=1.0,
            suggestion="补充营业时间，提升到店决策确定性。",
        )
        normalized = api._normalize_expert_opinion(
            {
                "role": "内容专家",
                "raw": (
                    "<opinion>内容有真实菜品，但到店决策信息还不完整。</opinion>"
                    "<evidence>餐饮营业时间槽位未命中；事实密度偏低</evidence>"
                    "<impact>会影响读者判断是否值得收藏和到店。</impact>"
                    "<suggestions>补充营业时间；把招牌菜和适合场景前置</suggestions>"
                    "<confidence>0.86</confidence>"
                ),
            },
            weaknesses=[weakness],
            features={
                "commercial_fact_density": 0.42,
                "commercial_actionability": 0.51,
                "commercial_body_has_cta": 1.0,
                "commercial_body_main_char_len": 260.0,
                "domain_food_hours": 0.0,
                "domain_food_must_order": 1.0,
            },
            timing=None,
            visual_score=None,
            cover_feats={},
            semantic_feats={},
            domain="美食",
            percentile=68.4,
            grade="良好",
        )

        self.assertEqual(normalized["evidence_binding"], "v04_structured")
        self.assertGreaterEqual(len(normalized["evidence"]), 2)
        self.assertTrue(all(isinstance(item, dict) for item in normalized["evidence"]))
        first = normalized["evidence"][0]
        self.assertEqual(first["source_type"], "v04_feature")
        self.assertEqual(first["source_key"], "domain_food_hours")
        self.assertEqual(first["value"], 0.0)
        self.assertEqual(first["benchmark"], 1.0)
        self.assertIn("agent_text", first)
        self.assertTrue(any(item.get("source_type") == "v04_score" for item in normalized["evidence"]))

    def test_stale_market_timing_is_disabled_for_user_reports(self):
        original_db = hot_keywords.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                hot_keywords.init_db()
                old = (datetime.now() - timedelta(days=3)).isoformat()
                with sqlite3.connect(str(hot_keywords.DB_PATH)) as conn:
                    conn.execute(
                        """
                        INSERT INTO hot_keywords
                            (keyword, search_vol, trend_dir, source, category, captured_at, captured_date)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        ("番禺美食", 90, 1, "homefeed", "美食", old, old[:10]),
                    )

                timing = hot_keywords.compute_market_timing("番禺美食", "番禺美食探店", "美食")
                self.assertTrue(timing["data_stale"])
                self.assertEqual(timing["timing_coefficient"], 1.0)
                self.assertEqual(timing["matched_keywords"], [])
                self.assertEqual(timing["suggested_keywords"], [])
                self.assertEqual(timing["timing_action"], "stale")
                self.assertIn("市场时机证据已停用", timing["confidence_note"])
        finally:
            hot_keywords.DB_PATH = original_db

    def test_fresh_market_timing_requires_domain_category(self):
        original_db = hot_keywords.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                hot_keywords.init_db()
                food_keywords = [
                    "番禺美食", "番禺粤菜探店", "芝士焗小青龙", "广州早茶点心",
                    "粤菜餐厅", "顺德鱼生", "乳鸽必点", "茶餐厅",
                    "番禺探店", "海鲜砂锅", "牛肉火锅", "小吃宵夜",
                ]
                hot_keywords.upsert_keywords([
                    {
                        "keyword": kw,
                        "search_vol": 88,
                        "trend_dir": 1,
                        "source": "homefeed_phrase",
                        "category": "美食",
                        "count": 3,
                    }
                    for kw in food_keywords
                ] + [
                    {
                        "keyword": "太古里酒店",
                        "search_vol": 92,
                        "trend_dir": 1,
                        "source": "homefeed_phrase",
                        "category": "旅行",
                        "count": 3,
                    }
                ])

                food = hot_keywords.compute_market_timing("番禺美食", "番禺美食探店", "美食")
                beauty = hot_keywords.compute_market_timing("番禺美食", "番禺美食探店", "美妆")
                self.assertFalse(food["data_stale"])
                self.assertIn("番禺美食", food["matched_keywords"])
                self.assertTrue(beauty["data_stale"])
                self.assertEqual(beauty["matched_keywords"], [])
        finally:
            hot_keywords.DB_PATH = original_db

    def test_market_timing_imports_fresh_cloud_snapshot(self):
        original_db = hot_keywords.DB_PATH
        old_snapshot_url = os.environ.get("NOTEAI_MARKET_TIMING_SNAPSHOT_URL")
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                hot_keywords.DB_PATH = tmp / "hot_keywords.db"
                hot_keywords.init_db()
                snapshot = {
                    "schema_version": 1,
                    "generated_at": datetime.now().isoformat(),
                    "domains": {
                        "美食": {
                            "captured_at": datetime.now().isoformat(),
                            "keywords": [
                                {
                                    "keyword": kw,
                                    "search_vol": 91,
                                    "trend_dir": 1,
                                    "source": "cloud_snapshot",
                                    "category": "美食",
                                    "count": 3,
                                }
                                for kw in [
                                    "番禺美食", "番禺粤菜探店", "芝士焗小青龙", "广州早茶点心",
                                    "粤菜餐厅", "顺德鱼生", "乳鸽必点", "茶餐厅",
                                    "番禺探店", "海鲜砂锅", "牛肉火锅", "小吃宵夜",
                                ]
                            ],
                        }
                    },
                }
                snapshot_path = tmp / "snapshot.json"
                snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
                os.environ["NOTEAI_MARKET_TIMING_SNAPSHOT_URL"] = f"file://{snapshot_path}"

                timing = hot_keywords.compute_market_timing("番禺美食", "番禺美食探店", "美食")
                self.assertFalse(timing["data_stale"])
                self.assertFalse(timing["evidence_unavailable"])
                self.assertIn("番禺美食", timing["matched_keywords"])
                self.assertTrue(timing["cloud_sync"].get("enabled"))
        finally:
            hot_keywords.DB_PATH = original_db
            if old_snapshot_url is None:
                os.environ.pop("NOTEAI_MARKET_TIMING_SNAPSHOT_URL", None)
            else:
                os.environ["NOTEAI_MARKET_TIMING_SNAPSHOT_URL"] = old_snapshot_url

    def test_market_timing_imports_authorized_trend_source(self):
        original_db = hot_keywords.DB_PATH
        old_authorized_url = os.environ.get("NOTEAI_AUTHORIZED_TREND_URL")
        old_snapshot_url = os.environ.get("NOTEAI_MARKET_TIMING_SNAPSHOT_URL")
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                hot_keywords.DB_PATH = tmp / "hot_keywords.db"
                hot_keywords.init_db()
                snapshot = {
                    "generated_at": datetime.now().isoformat(),
                    "domains": {
                        "美食": {
                            "captured_at": datetime.now().isoformat(),
                            "keywords": [
                                {
                                    "keyword": kw,
                                    "search_vol": 92,
                                    "trend_dir": 1,
                                    "category": "美食",
                                    "count": 5,
                                }
                                for kw in [
                                    "番禺美食", "番禺粤菜探店", "芝士焗小青龙", "广州早茶点心",
                                    "粤菜餐厅", "顺德鱼生", "乳鸽必点", "茶餐厅",
                                    "番禺探店", "海鲜砂锅", "牛肉火锅", "小吃宵夜",
                                ]
                            ],
                        }
                    },
                }
                snapshot_path = tmp / "authorized_trends.json"
                snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
                os.environ["NOTEAI_AUTHORIZED_TREND_URL"] = f"file://{snapshot_path}"
                os.environ.pop("NOTEAI_MARKET_TIMING_SNAPSHOT_URL", None)

                timing = hot_keywords.compute_market_timing("番禺美食", "番禺美食探店", "美食")
                self.assertFalse(timing["data_stale"])
                self.assertEqual(timing["source_breakdown"].get("authorized_trend"), 12)
                self.assertEqual(timing["is_trending_topic"], 1.0)
                self.assertIn("番禺美食", timing["matched_keywords"])
                self.assertTrue(timing["cloud_sync"].get("enabled"))
                self.assertEqual(timing["cloud_sync"].get("source"), "authorized_trend")
        finally:
            hot_keywords.DB_PATH = original_db
            if old_authorized_url is None:
                os.environ.pop("NOTEAI_AUTHORIZED_TREND_URL", None)
            else:
                os.environ["NOTEAI_AUTHORIZED_TREND_URL"] = old_authorized_url
            if old_snapshot_url is None:
                os.environ.pop("NOTEAI_MARKET_TIMING_SNAPSHOT_URL", None)
            else:
                os.environ["NOTEAI_MARKET_TIMING_SNAPSHOT_URL"] = old_snapshot_url

    def test_required_market_timing_raises_when_evidence_unavailable(self):
        old_required = os.environ.get("NOTEAI_MARKET_TIMING_REQUIRED")
        try:
            os.environ["NOTEAI_MARKET_TIMING_REQUIRED"] = "1"
            with self.assertRaises(HTTPException) as ctx:
                api._enforce_market_timing(
                    {
                        "data_stale": True,
                        "evidence_unavailable": True,
                        "domain_latest_capture": None,
                        "freshness_policy": "要求 30 小时内有行业采集样本",
                    },
                    "美食",
                )
            self.assertEqual(ctx.exception.status_code, 503)
            self.assertEqual(ctx.exception.detail["code"], "MARKET_TIMING_EVIDENCE_UNAVAILABLE")
        finally:
            if old_required is None:
                os.environ.pop("NOTEAI_MARKET_TIMING_REQUIRED", None)
            else:
                os.environ["NOTEAI_MARKET_TIMING_REQUIRED"] = old_required

    def test_api_market_timing_preserves_baseline_source_note(self):
        original_db = hot_keywords.DB_PATH
        old_required = os.environ.get("NOTEAI_MARKET_TIMING_REQUIRED")
        try:
            os.environ["NOTEAI_MARKET_TIMING_REQUIRED"] = "0"
            with tempfile.TemporaryDirectory() as td:
                hot_keywords.DB_PATH = Path(td) / "hot_keywords.db"
                hot_keywords.ensure_daily_evidence_pack(("美食",))

                timing = api._compute_market_timing_for_delivery(
                    "本地美食探店",
                    "周末想找粤菜餐厅",
                    "美食",
                )

                self.assertFalse(timing["data_stale"])
                self.assertIn("不代表平台官方热搜", timing["confidence_note"])
                self.assertIn("pipeline_status", timing)
                self.assertEqual(timing["pipeline_status"].get("state"), "ready")
        finally:
            hot_keywords.DB_PATH = original_db
            if old_required is None:
                os.environ.pop("NOTEAI_MARKET_TIMING_REQUIRED", None)
            else:
                os.environ["NOTEAI_MARKET_TIMING_REQUIRED"] = old_required

    def test_chat_ownership_is_checked_before_billing(self):
        calls = []
        original_check = api._billing.check_and_deduct
        original_record = api._billing.record_free_usage
        original_sessions = dict(api._chat_sessions)
        try:
            api._billing.check_and_deduct = lambda user_id, op: calls.append(("deduct", user_id, op))
            api._billing.record_free_usage = lambda user_id, op: calls.append(("record", user_id, op))
            api._chat_sessions.clear()
            api._chat_sessions["owned_session"] = {"user_id": "owner", "messages": []}

            async def run():
                return await api.chat_message(
                    api.ChatMessageInput(session_id="owned_session", message="帮我重写一版"),
                    user={"id": "intruder"},
                )

            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(run())
            self.assertEqual(ctx.exception.status_code, 403)
            self.assertEqual(calls, [])
        finally:
            api._billing.check_and_deduct = original_check
            api._billing.record_free_usage = original_record
            api._chat_sessions.clear()
            api._chat_sessions.update(original_sessions)

    def test_chat_start_binds_existing_note_for_library_version_chain(self):
        original_db = api._db
        original_sessions = dict(api._chat_sessions)
        original_get_user_learn = api._get_user_learn
        original_memory_prompt = api._memory.build_memory_prompt

        class FakeDB:
            def __init__(self):
                self.executed = []

            def fetchone(self, sql, params=()):
                if "FROM notes" in sql and params == ("note-root", "u1"):
                    return {
                        "id": "note-root",
                        "title": "初始标题",
                        "body": "初始正文",
                        "domain": "美食",
                        "score": 68.0,
                        "grade": "良好",
                        "version": 1,
                    }
                return None

            def execute(self, sql, params=()):
                self.executed.append((sql, params))

        fake_db = FakeDB()
        try:
            api._db = fake_db
            api._chat_sessions.clear()
            api._get_user_learn = lambda user_id: {}
            api._memory.build_memory_prompt = lambda user_id: ""

            resp = asyncio.run(api.chat_start(
                api.ChatStartInput(
                    note_id="note-root",
                    note_title="初始标题",
                    note_body="初始正文",
                    domain="美食",
                    generate_context={"ces_percentile": 68.0, "grade": "良好"},
                ),
                user={"id": "u1"},
            ))

            session = api._chat_sessions[resp.session_id]
            self.assertEqual(session["_last_note_id"], "note-root")
            self.assertEqual(session["note_id"], "note-root")
            self.assertTrue(fake_db.executed)
            self.assertEqual(fake_db.executed[-1][1][2], "note-root")
        finally:
            api._db = original_db
            api._chat_sessions.clear()
            api._chat_sessions.update(original_sessions)
            api._get_user_learn = original_get_user_learn
            api._memory.build_memory_prompt = original_memory_prompt

    def test_chat_start_prefers_selected_plan_score_over_original_diagnosis_score(self):
        original_sessions = dict(api._chat_sessions)
        original_get_user_learn = api._get_user_learn
        original_memory_prompt = api._memory.build_memory_prompt
        original_persist = api._persist_chat_session
        try:
            api._chat_sessions.clear()
            api._get_user_learn = lambda user_id: {}
            api._memory.build_memory_prompt = lambda user_id: ""
            api._persist_chat_session = lambda session_id: None

            resp = asyncio.run(api.chat_start(
                api.ChatStartInput(
                    note_title="用户选中的高分方案标题",
                    note_body="用户选中的高分方案正文，已经不是原始诊断笔记正文。",
                    domain="美食",
                    generate_context={
                        "ces_percentile": 51.2,
                        "composite_score": 51.2,
                        "selected_plan_score": 76.9,
                        "current_score": 76.9,
                        "grade": "良好",
                    },
                ),
                user={"id": "u1"},
            ))

            self.assertEqual(resp.current_score, 76.9)
            self.assertEqual(resp.grade, "优秀")
            session = api._chat_sessions[resp.session_id]
            self.assertEqual(session["current_score"], 76.9)
            self.assertEqual(session["generate_context"]["selected_plan_score"], 76.9)
            self.assertEqual(session["generate_context"]["current_score"], 76.9)
        finally:
            api._chat_sessions.clear()
            api._chat_sessions.update(original_sessions)
            api._get_user_learn = original_get_user_learn
            api._memory.build_memory_prompt = original_memory_prompt
            api._persist_chat_session = original_persist

    def test_chat_note_update_is_emitted_after_version_save(self):
        original_db = api._db
        original_sessions = dict(api._chat_sessions)
        original_stream_chat = api._mr.stream_chat
        original_repair = api._repair_chat_note_if_needed
        original_shape = api._shape_body_for_delivery
        original_sanitize = api._sanitize_title_for_delivery
        original_check_achievements = api._memory.check_and_record_achievements
        original_add_context = api._memory.add_context

        class FakeDB:
            def __init__(self):
                self.executed = []

            def fetchone(self, sql, params=()):
                if "FROM notes" in sql and params == ("note-root", "u1"):
                    return {
                        "id": "note-root",
                        "title": "初始标题",
                        "body": "初始正文",
                        "domain": "美食",
                        "score": 60.0,
                        "grade": "待改进",
                        "version": 1,
                    }
                return None

            def execute(self, sql, params=()):
                self.executed.append((sql, params))

        async def fake_stream_chat(**kwargs):
            yield "content", "<note><title>新版标题</title><body>新版正文 #上海美食</body></note>"

        async def fake_repair(title, body, session, user_msg):
            return title, body, 72.0, {}, "良好", [], False

        async def fake_shape(title, body, domain, fact_source, route):
            return body

        fake_db = FakeDB()
        try:
            api._db = fake_db
            api._chat_sessions.clear()
            api._chat_sessions["s1"] = {
                "note_title": "初始标题",
                "note_body": "初始正文",
                "domain": "美食",
                "local_time": "2026070512",
                "user_id": "u1",
                "current_score": 60.0,
                "messages": [],
                "iteration_count": 0,
                "note_id": "note-root",
                "_last_note_id": "note-root",
                "user_constraints": [],
            }
            api._mr.stream_chat = fake_stream_chat
            api._repair_chat_note_if_needed = fake_repair
            api._shape_body_for_delivery = fake_shape
            api._sanitize_title_for_delivery = lambda title, fact_source, domain: title
            api._memory.check_and_record_achievements = lambda user_id, score, action: []
            api._memory.add_context = lambda *args, **kwargs: None

            async def run():
                events = []
                async for chunk in api._chat_sse_generator("s1", "帮我重写一版"):
                    if not chunk.startswith("data: "):
                        continue
                    events.append(json.loads(chunk.removeprefix("data: ").strip()))
                return events

            events = asyncio.run(run())
            note_update = next(ev for ev in events if ev.get("type") == "note_update")
            saved_note_id = note_update.get("saved_note_id")
            inserted_notes = [
                params for sql, params in fake_db.executed
                if sql.startswith("INSERT INTO notes")
            ]
            self.assertTrue(saved_note_id)
            self.assertEqual(note_update.get("saved_note_version"), 2)
            self.assertEqual(inserted_notes[-1][0], saved_note_id)
            self.assertEqual(inserted_notes[-1][8], "note-root")
            self.assertEqual(inserted_notes[-1][9], 2)
            self.assertEqual(api._chat_sessions["s1"]["_last_note_id"], saved_note_id)
            self.assertEqual(api._chat_sessions["s1"]["note_version"], 2)
            self.assertIn("当前最终稿", api._chat_sessions["s1"]["messages"][-1]["content"])
            self.assertIn("新版标题", api._chat_sessions["s1"]["messages"][-1]["content"])
        finally:
            api._db = original_db
            api._chat_sessions.clear()
            api._chat_sessions.update(original_sessions)
            api._mr.stream_chat = original_stream_chat
            api._repair_chat_note_if_needed = original_repair
            api._shape_body_for_delivery = original_shape
            api._sanitize_title_for_delivery = original_sanitize
            api._memory.check_and_record_achievements = original_check_achievements
            api._memory.add_context = original_add_context

    def test_chat_plan_options_are_structured_and_not_auto_saved(self):
        original_db = api._db
        original_sessions = dict(api._chat_sessions)
        original_stream_chat = api._mr.stream_chat
        original_score_chat_note = api._score_chat_note
        original_sanitize = api._sanitize_title_for_delivery

        class FakeDB:
            def __init__(self):
                self.executed = []

            def fetchone(self, sql, params=()):
                if "FROM notes" in sql and params == ("note-root", "u1"):
                    return {
                        "id": "note-root",
                        "title": "初始标题",
                        "body": "初始正文",
                        "domain": "美食",
                        "score": 62.0,
                        "grade": "良好",
                        "version": 1,
                    }
                return None

            def execute(self, sql, params=()):
                self.executed.append((sql, params))

        async def fake_stream_chat(**kwargs):
            yield "content", (
                "给你三个方向："
                "<options>"
                "<option id=\"A\"><strategy>稳妥提分型</strategy><title>A标题</title><body>A正文 #美食</body></option>"
                "<option id=\"B\"><strategy>互动种草型</strategy><title>B标题</title><body>B正文 #美食</body></option>"
                "<option id=\"C\"><strategy>转化决策型</strategy><title>C标题</title><body>C正文 #美食</body></option>"
                "</options>"
                "<note><title>不应自动保存</title><body>不应保存正文</body></note>"
            )

        async def fake_score(title, body, session):
            scores = {"A标题": 68.2, "B标题": 70.5, "C标题": 69.4}
            score = scores.get(title, 60.0)
            return score, {}, "良好", []

        fake_db = FakeDB()
        try:
            api._db = fake_db
            api._chat_sessions.clear()
            api._chat_sessions["s1"] = {
                "note_title": "初始标题",
                "note_body": "初始正文",
                "domain": "美食",
                "local_time": "2026070718",
                "user_id": "u1",
                "current_score": 62.0,
                "messages": [],
                "iteration_count": 0,
                "note_id": "note-root",
                "_last_note_id": "note-root",
                "user_constraints": [],
            }
            api._mr.stream_chat = fake_stream_chat
            api._score_chat_note = fake_score
            api._sanitize_title_for_delivery = lambda title, fact_source, domain: title

            async def run():
                events = []
                async for chunk in api._chat_sse_generator("s1", "给我三个方案"):
                    if not chunk.startswith("data: "):
                        continue
                    events.append(json.loads(chunk.removeprefix("data: ").strip()))
                return events

            events = asyncio.run(run())
            plan_event = next(ev for ev in events if ev.get("type") == "plan_options")
            self.assertEqual(len(plan_event["options"]), 3)
            self.assertEqual(plan_event["options"][0]["id"], "A")
            self.assertEqual(plan_event["options"][1]["score"], 70.5)
            self.assertFalse(any(ev.get("type") == "note_update" for ev in events))
            self.assertEqual(api._chat_sessions["s1"]["pending_plan_options"][1]["title"], "B标题")
            inserted_notes = [sql for sql, _params in fake_db.executed if sql.startswith("INSERT INTO notes")]
            self.assertEqual(inserted_notes, [])
            self.assertIn("候选方案", api._chat_sessions["s1"]["messages"][-1]["content"])
        finally:
            api._db = original_db
            api._chat_sessions.clear()
            api._chat_sessions.update(original_sessions)
            api._mr.stream_chat = original_stream_chat
            api._score_chat_note = original_score_chat_note
            api._sanitize_title_for_delivery = original_sanitize

    def test_chat_select_plan_saves_chosen_option_as_next_version(self):
        original_db = api._db
        original_sessions = dict(api._chat_sessions)
        original_check_achievements = api._memory.check_and_record_achievements
        original_add_context = api._memory.add_context
        original_persist = api._persist_chat_session

        class FakeDB:
            def __init__(self):
                self.executed = []

            def fetchone(self, sql, params=()):
                if "FROM notes" in sql and params == ("note-root", "u1"):
                    return {
                        "id": "note-root",
                        "title": "初始标题",
                        "body": "初始正文",
                        "domain": "美食",
                        "score": 62.0,
                        "grade": "良好",
                        "version": 1,
                    }
                return None

            def execute(self, sql, params=()):
                self.executed.append((sql, params))

        fake_db = FakeDB()
        try:
            api._db = fake_db
            api._chat_sessions.clear()
            api._chat_sessions["s1"] = {
                "note_title": "初始标题",
                "note_body": "初始正文",
                "domain": "美食",
                "local_time": "2026070718",
                "user_id": "u1",
                "current_score": 62.0,
                "messages": [],
                "iteration_count": 0,
                "note_id": "note-root",
                "_last_note_id": "note-root",
                "pending_plan_options": [
                    {"id": "A", "title": "A标题", "body": "A正文", "score": 68.2, "grade": "良好"},
                    {"id": "B", "title": "B标题", "body": "B正文", "score": 70.5, "grade": "良好"},
                ],
            }
            api._memory.check_and_record_achievements = lambda user_id, score, action: []
            api._memory.add_context = lambda *args, **kwargs: None
            api._persist_chat_session = lambda session_id: None

            resp = asyncio.run(api.chat_select_plan(
                api.ChatSelectPlanInput(session_id="s1", option_id="B"),
                user={"id": "u1"},
            ))

            inserted_notes = [
                params for sql, params in fake_db.executed
                if sql.startswith("INSERT INTO notes")
            ]
            self.assertEqual(resp["title"], "B标题")
            self.assertEqual(resp["score"], 70.5)
            self.assertEqual(resp["saved_note_version"], 2)
            self.assertEqual(resp["selected_option_id"], "B")
            self.assertEqual(inserted_notes[-1][2], "B标题")
            self.assertEqual(inserted_notes[-1][8], "note-root")
            self.assertEqual(inserted_notes[-1][9], 2)
            self.assertEqual(api._chat_sessions["s1"]["note_title"], "B标题")
            self.assertEqual(api._chat_sessions["s1"]["_last_note_id"], resp["saved_note_id"])
            self.assertEqual(api._chat_sessions["s1"]["note_version"], 2)
            self.assertIn("当前最终稿", api._chat_sessions["s1"]["messages"][-1]["content"])
        finally:
            api._db = original_db
            api._chat_sessions.clear()
            api._chat_sessions.update(original_sessions)
            api._memory.check_and_record_achievements = original_check_achievements
            api._memory.add_context = original_add_context
            api._persist_chat_session = original_persist

    def test_note_version_group_for_diagnosis_includes_selected_chat_version(self):
        original_db = api._db

        class FakeDB:
            def fetchall(self, sql, params=()):
                self.assert_query = (sql, params)
                return [
                    {
                        "id": "note-root",
                        "title": "诊断原稿",
                        "body": "原始正文",
                        "domain": "美食",
                        "score": 47.9,
                        "grade": "待改进",
                        "source": "diagnose",
                        "version": 1,
                        "parent_id": None,
                        "created_at": "2026-07-07T10:00:00+00:00",
                    },
                    {
                        "id": "note-v2",
                        "title": "已选方案标题",
                        "body": "已选方案正文",
                        "domain": "美食",
                        "score": 64.0,
                        "grade": "良好",
                        "source": "chat",
                        "version": 2,
                        "parent_id": "note-root",
                        "created_at": "2026-07-07T10:10:00+00:00",
                    },
                    {
                        "id": "other-root",
                        "title": "其他笔记",
                        "body": "其他正文",
                        "domain": "美食",
                        "score": 80.0,
                        "grade": "优秀",
                        "source": "generate",
                        "version": 1,
                        "parent_id": None,
                        "created_at": "2026-07-07T10:20:00+00:00",
                    },
                ]

        try:
            api._db = FakeDB()
            group = api._build_note_version_group_for_root("note-root", "u1")
            self.assertIsNotNone(group)
            self.assertEqual(group["group_id"], "note-root")
            self.assertEqual(group["latest"]["id"], "note-v2")
            self.assertEqual(group["latest"]["title"], "已选方案标题")
            self.assertEqual(group["version_count"], 2)
            self.assertEqual(group["score_trend"], [47.9, 64.0])
            self.assertEqual(group["best_score"], 64.0)
        finally:
            api._db = original_db

    def test_chat_start_rejects_note_id_not_owned_by_user(self):
        original_db = api._db

        class FakeDB:
            def fetchone(self, sql, params=()):
                return None

        try:
            api._db = FakeDB()
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(api.chat_start(
                    api.ChatStartInput(note_id="other-user-note"),
                    user={"id": "u1"},
                ))
            self.assertEqual(ctx.exception.status_code, 404)
        finally:
            api._db = original_db

    def test_test_billing_endpoints_are_disabled_by_default(self):
        old_flag = os.environ.pop("NOTEAI_ENABLE_TEST_BILLING", None)
        try:
            async def run():
                return await api.billing_topup(api.TopupInput(amount=50), user={"id": "u1"})

            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(run())
            self.assertEqual(ctx.exception.status_code, 403)
        finally:
            if old_flag is not None:
                os.environ["NOTEAI_ENABLE_TEST_BILLING"] = old_flag

    def test_quality_contract_tag_ranges(self):
        base_features = {
            "body_len": 220,
            "body_cta_count": 1,
            "body_has_price": 1,
            "body_has_address": 1,
            "body_has_hours": 1,
            "body_has_must_order": 1,
            "title_has_city": 1,
        }
        food_low = dict(base_features, tag_count=4)
        food_ok = dict(base_features, tag_count=5)
        travel_ok = dict(base_features, tag_count=8, body_has_transport=1)
        travel_low = dict(base_features, tag_count=5, body_has_transport=1)

        self.assertTrue(any("话题标签不足" in item for item in api._generated_quality_issues(
            "上海蟹黄面真的香", "正文" * 120, "美食", 75, food_low
        )))
        self.assertFalse(any("话题标签不足" in item for item in api._generated_quality_issues(
            "上海蟹黄面真的香", "正文" * 120, "美食", 75, food_ok
        )))
        self.assertTrue(api._feature_hits_for_generation("上海两日游攻略", travel_ok, 75, "旅行")["tag_count_target"])
        self.assertFalse(api._feature_hits_for_generation("上海两日游攻略", travel_low, 75, "旅行")["tag_count_target"])
        food_hit_body = "正文" * 150 + "#上海美食 #蟹黄面 #南京西路美食 #上海探店 #周末去哪儿"
        food_hit_features = dict(food_ok, body_len=430)
        self.assertTrue(api._feature_hits_for_generation(
            "上海蟹黄面58元真香", food_hit_features, 75, "美食", body=food_hit_body
        )["body_len_target"])
        food_short_target_body = "正文" * 120 + "#上海美食 #蟹黄面 #南京西路美食 #上海探店 #周末去哪儿"
        self.assertFalse(api._feature_hits_for_generation(
            "上海蟹黄面58元真香", food_hit_features, 75, "美食", body=food_short_target_body
        )["body_len_target"])

    def test_delivery_compaction_preserves_complete_tail_cta(self):
        body = (
            "这份流程适合收藏起来慢慢看。"
            + "南瓜泥先从一小勺开始，观察三天再加胡萝卜软颗粒，颗粒大小要能用舌头压碎。"
            * 8
            + "\n#8月龄辅食 #辅食顺序 #过敏观察"
        )
        compacted = api._compact_body_to_delivery_limit(body, "母婴")
        main, tags = api._split_body_and_tags(compacted)

        self.assertLessEqual(api._body_content_len_without_tags(compacted), api._quality_body_max("母婴"))
        self.assertTrue(api._has_delivery_cta_near_end(main), compacted)
        self.assertIn("收藏", main)
        self.assertIn("评论区", main)
        self.assertNotRegex(main, r"(有用先收|路线先收)$")
        self.assertIn("#8月龄辅食", tags)

    def test_feature_governance_covers_all_62_training_features(self):
        expected = (
            set(api.FEATURE_COLS)
            | set(api.SEMANTIC_FEATURE_COLS)
            | set(api.VISUAL_FEATURE_COLS)
            | set(api.TIMING_FEATURE_COLS)
        )
        self.assertEqual(
            len(api.FEATURE_COLS)
            + len(api.SEMANTIC_FEATURE_COLS)
            + len(api.VISUAL_FEATURE_COLS)
            + len(api.TIMING_FEATURE_COLS),
            62,
        )
        self.assertEqual(len(expected), 62)
        self.assertEqual(expected - set(api.FEATURE_GOVERNANCE), set())
        self.assertEqual(set(api.FEATURE_GOVERNANCE) - expected, set())

        gates = {spec["gate"] for spec in api.FEATURE_GOVERNANCE.values()}
        self.assertEqual({"hard", "repair", "diagnostic", "monitor"} - gates, set())
        for feature, spec in api.FEATURE_GOVERNANCE.items():
            with self.subTest(feature=feature):
                self.assertIn(spec["gate"], {"hard", "repair", "diagnostic", "monitor"})
                self.assertIn(spec["direction"], {"high", "low", "band", "monitor"})
                self.assertTrue(spec["label"])
                self.assertTrue(spec["repair_action"])

        self.assertEqual(api.FEATURE_GOVERNANCE["semantic_emotional_intensity"]["gate"], "repair")
        self.assertEqual(api.FEATURE_GOVERNANCE["cover_aesthetic_score"]["gate"], "monitor")
        self.assertEqual(api.FEATURE_GOVERNANCE["body_len"]["gate"], "hard")
        self.assertTrue(api._feature_applies_to_domain(api.FEATURE_GOVERNANCE["body_has_price"], "美食"))
        self.assertFalse(api._feature_applies_to_domain(api.FEATURE_GOVERNANCE["body_has_price"], "母婴"))

        brief = api._get_feature_governance_brief("美食")
        self.assertIn("62维特征治理简报", brief)
        self.assertIn("硬门禁", brief)
        self.assertIn("语义情绪强度", brief)
        self.assertIn("监控特征", brief)

    def test_runtime_prompt_neutralizes_legacy_v03_guidance(self):
        original_get = api._pm.get
        try:
            api._pm.get = lambda key, fallback="": (
                "你是基于v0.3模型10万+真实数据的专家。目标是CES≥70，"
                "body_len（正文字数）= 37%权重，最重要单一特征。"
            )
            prompt = api._runtime_prompt("agent_content_system", "美食")
            self.assertIn("V0.4运行时最高优先级覆盖", prompt)
            self.assertIn("复合交付目标", prompt)
            self.assertIn("高质量可交付", prompt)
            self.assertNotIn("v0.3模型", prompt)
            self.assertNotIn("CES≥70", prompt)
            self.assertNotIn("37%权重", prompt)
        finally:
            api._pm.get = original_get

    def test_v04_predict_merges_realtime_feature_planes(self):
        note = api.NoteInput(
            note_title="广州番禺小青龙人均98值得试",
            desc=(
                "番禺万博这家粤菜适合聚餐，招牌芝士焗小青龙建议必点。"
                "地址在广晟万博城A座7层，人均98元，营业时间09:00-14:00/17:00-21:00，周末建议提前预订。"
                "#番禺美食 #粤菜聚餐 #芝士焗小青龙 #广州探店 #周末聚餐"
            ),
            local_time="2026062812",
            domain="美食",
        )
        _score, features = api._predict(
            note,
            semantic_feats={
                "semantic_emotional_intensity": 0.71,
                "semantic_empathetic_engagement": 0.66,
                "semantic_rhetorical_score": 0.63,
            },
            cover_feats={
                "cover_aesthetic_score": 0.82,
                "cover_composition_score": 0.76,
                "cover_visual_clarity": 0.79,
            },
            timing_feats={
                "keyword_search_vol": 0.77,
                "trend_momentum": 0.55,
            },
        )

        self.assertEqual(len(features), len(api.COMPOSITE_FEATURE_COLS))
        self.assertEqual(features["semantic_emotional_intensity"], 0.71)
        self.assertEqual(features["cover_aesthetic_score"], 0.82)
        self.assertEqual(features["keyword_search_vol"], 0.77)

    def test_report_metadata_exposes_v04_composite_contract(self):
        features = api.build_composite_features(
            title="广州番禺小青龙人均98值得试",
            body=(
                "番禺万博这家粤菜适合聚餐，招牌芝士焗小青龙建议必点。"
                "地址在广晟万博城A座7层，人均98元，营业时间09:00-14:00/17:00-21:00，周末建议提前预订。"
                "乳鸽皮脆肉嫩，真实探店可以点赞收藏。\n"
                "#番禺美食 #粤菜聚餐 #芝士焗小青龙 #广州探店 #周末聚餐"
            ),
            domain="美食",
        )
        meta = api._build_report_metadata(features, "美食")
        schema = meta["feature_schema"]

        self.assertEqual(schema["contract_feature_count"], len(api.COMPOSITE_FEATURE_COLS))
        self.assertGreater(schema["contract_feature_count"], 100)
        self.assertEqual(schema["feature_count"], len(api.COMPOSITE_FEATURE_COLS))
        self.assertEqual(sum(g["count"] for g in meta["feature_groups"]), len(api.COMPOSITE_FEATURE_COLS))
        self.assertIn("commercial_facts", {d["key"] for d in meta["dimension_scores"]})
        self.assertIn("semantic", {d["key"] for d in meta["dimension_scores"]})
        self.assertTrue(meta["top_feature_contributions"])

    def test_v04_artifact_path_resolves_cloud_deployment_paths(self):
        filename = "model_v04_composite_regressor_experimental_20260628T013926Z.lgb"
        local = api.MODEL_DIR / filename
        self.assertTrue(local.exists(), local)

        stale_training_path = f"/Users/openclaw/Desktop/noteai/model/artifacts/{filename}"
        self.assertEqual(api._resolve_model_artifact_path(stale_training_path).resolve(), local.resolve())
        self.assertEqual(api._resolve_model_artifact_path(f"artifacts/{filename}").resolve(), local.resolve())

    def test_semantic_governance_repairs_without_hard_blocking(self):
        features = {
            "body_len": 300,
            "tag_count": 5,
            "body_cta_count": 2,
            "body_has_price": 1,
            "body_has_address": 1,
            "body_has_hours": 1,
            "body_has_must_order": 1,
            "title_has_pos_emotion": 1,
            "title_has_number": 1,
            "title_has_city": 1,
            "plad_phrasal_repetition": 0.12,
            "plad_sentence_burstiness": 0.7,
            "plad_unique_emoji_ratio": 0.2,
            "semantic_emotional_intensity": 0.1,
            "semantic_empathetic_engagement": 0.1,
            "semantic_rhetorical_score": 0.1,
        }
        fixes = api._build_fix_instructions(features, [], "美食")
        self.assertTrue(
            any(("语义" in item or "共情" in item or "情绪" in item) for item in fixes),
            fixes,
        )

        body = "正" * 300 + "#上海美食 #蟹黄面 #南京西路美食 #上海探店 #周末去哪儿"
        issues = api._generated_quality_issues(
            "上海蟹黄面58元真香",
            body,
            "美食",
            75,
            features,
        )
        self.assertFalse(api._has_blocking_quality_issues(75, issues), issues)

    def test_generation_agents_receive_feature_governance_brief(self):
        original_call = api._mr.call
        calls = []

        async def fake_call(route, system, user, **kwargs):
            calls.append((route, system, user, kwargs))
            return (
                "<draft_title>上海蟹黄面58元真香</draft_title>"
                "<draft_body>南京西路这家蟹黄面人均58元，招牌蟹黄拌面香气很足。"
                "营业时间每天11:00-21:00，排队二十分钟也值得，记得点赞收藏。"
                "#上海美食 #蟹黄面 #南京西路美食 #上海探店 #周末去哪儿</draft_body>"
            )

        try:
            api._mr.call = fake_call
            asyncio.run(api._gent_content("美食", "南京西路蟹黄面，人均58元", {}, "蟹黄面特写"))
        finally:
            api._mr.call = original_call

        self.assertEqual(len(calls), 1)
        self.assertIn("62维特征治理简报", calls[0][1])
        self.assertIn("硬门禁", calls[0][1])
        self.assertIn("生成修复", calls[0][1])

    def test_agent_arbitrate_generates_distinct_plan_bodies(self):
        original_call = api._mr.call
        original_sleep = api.asyncio.sleep
        calls = []

        async def fake_sleep(_seconds):
            return None

        async def fake_call(route, system, user, **kwargs):
            calls.append((route, system, user, kwargs))
            if "【输出格式强约束】" in user:
                return (
                    "<diagnosis>标题缺少清晰角度，需要拆成三套不同表达。</diagnosis>"
                    "<plan_a_title>58元蟹黄面真香</plan_a_title>"
                    "<plan_b_title>下班冲这碗面</plan_b_title>"
                    "<plan_c_title>普通店竟然翻盘</plan_c_title>"
                    "<plan>分别测试数据、场景、反差三种角度。</plan>"
                    "<dispute>数据派和情绪派都可行。</dispute>"
                )
            if "数据/结果型" in system:
                return "人均58元的蟹黄拌面，蟹黄量给得很足，排队20分钟也值。点赞收藏，下次按这个点。"
            if "场景/情绪型" in system:
                return "下班路过这家小店，热气一上来就很治愈，蟹黄裹住面条特别香。点赞收藏，想吃面时直接来。"
            if "反向/颠覆型" in system:
                return "本来以为是普通面馆，没想到蟹黄香气和小馄饨都很稳，反差感很强。点赞收藏，别错过。"
            return ""

        try:
            api._mr.call = fake_call
            api.asyncio.sleep = fake_sleep
            result = asyncio.run(api._agent_arbitrate(
                "南京西路蟹黄面",
                "美食",
                62.0,
                "待优化",
                [{
                    "role": "内容专家",
                    "raw": (
                        "<opinion>内容结构偏散。</opinion>"
                        "<titles>候选标题一\n候选标题二\n候选标题三</titles>"
                        "<body>这是一篇内容专家候选正文，不应该被三个方案直接复用。</body>"
                        "<confidence>0.8</confidence>"
                    ),
                }],
            ))
        finally:
            api._mr.call = original_call
            api.asyncio.sleep = original_sleep

        bodies = [p["body"] for p in result["plans"]]
        self.assertEqual(len(bodies), 3)
        self.assertEqual(len(set(bodies)), 3)
        self.assertIn("本阶段只输出诊断和3个标题", calls[0][2])
        self.assertFalse(any(body == "这是一篇内容专家候选正文，不应该被三个方案直接复用。" for body in bodies))

    def test_plan_title_distinct_repair_handles_duplicate_titles(self):
        titles = api._make_plan_titles_distinct(
            [
                "38平出租屋3000元改造，收纳动线",
                "38平出租屋3000元改造，收纳动线",
                "38平出租屋3000元改造，收纳动线",
            ],
            "家居",
            "38平出租屋，预算3000元，想做收纳和动线改造。",
        )
        self.assertEqual(len(titles), 3)
        self.assertEqual(len(set(titles)), 3)
        self.assertTrue(all(6 <= len(title) <= api._TITLE_DELIVERY_MAX for title in titles))
        self.assertFalse(any(api._title_readability_issues(title, "家居") for title in titles), titles)

    def test_rqs_title_tail_repairs_cover_latest_probe_patterns(self):
        cases = [
            ("南京西路蟹黄拌面58元，周末排队值不", "美食", "南京西路蟹黄拌面58元，周末排队值得"),
            ("南京西路蟹黄拌面58元，周末排队20", "美食", "58元蟹黄拌面，排队20分钟"),
            ("黄皮混干皮选腮红，这支奶杏玫瑰色真", "美妆", "黄皮混干皮腮红，奶杏玫瑰色显白"),
            ("黄皮混干皮用这支腮红，通勤妆显气色还", "美妆", "黄皮混干皮腮红，通勤妆显气色"),
            ("黄皮混干皮用这支腮红很稳，显白不显毛", "美妆", "黄皮混干皮腮红，显白不显毛孔"),
            ("黄皮混干皮亲测｜79元腮红显白不显毛", "美妆", "黄皮混干皮79元腮红，显白不显毛孔"),
            ("小个子通勤显高3套公式，89元起搭", "穿搭", "小个子通勤显高3套公式，89元起"),
            ("小个子显高3套通勤公式，89元衬衫开", "穿搭", "小个子通勤显高，89元衬衫起"),
            ("小个子通勤显高3套公式，89元衬衫开", "穿搭", "小个子通勤显高，89元衬衫起"),
            ("新手居家7天减脂计划，4个动作20", "健身", "新手居家7天减脂，4个动作20分钟"),
            ("新手居家减脂7天计划，4个动作20", "健身", "新手居家7天减脂，4个动作20分钟"),
            ("新手居家减脂7天计划，4个动作每晚2", "健身", "新手居家减脂，每晚20分钟"),
            ("新手居家减脂7天循环，4个动作20", "健身", "新手居家减脂7天，4个动作20分钟"),
            ("新手7天居家减脂，4个动作避坑执行指", "健身", "新手居家减脂，4个动作避坑"),
            ("新手膝盖友好7天减脂计划，4个动作2", "健身", "新手膝盖友好减脂，4个动作"),
            ("居家减脂7天循环，4个动作新手也能坚", "健身", "居家减脂7天循环，4个动作"),
            ("38平出租屋3000元改造，从乱到有", "家居", "38平出租屋3000元改造，有序收纳"),
            ("38平出租屋3000元改造，很稳的收", "家居", "38平出租屋3000元改造，有序收纳"),
            ("38平出租屋3000元改造，终于走路", "家居", "38平出租屋3000元改造，动线更顺"),
            ("成都3天2晚慢游攻略，1200元这样", "旅行", "成都3天2晚1200元慢游"),
            ("成都3天2晚慢游实测，1200元人均", "旅行", "成都3天2晚1200元慢游"),
        ]
        for raw, domain, expected in cases:
            with self.subTest(raw=raw):
                repaired = api._sanitize_title_for_delivery(raw, "", domain)
                self.assertEqual(repaired, expected)
                self.assertLessEqual(len(repaired), api._TITLE_DELIVERY_MAX)
                self.assertFalse(api._title_readability_issues(repaired, domain), repaired)

    def test_agent_arbitrate_body_failure_does_not_duplicate_shared_candidate(self):
        original_call = api._mr.call
        original_sleep = api.asyncio.sleep
        shared_candidate = "这是一篇内容专家候选正文，不应该被三个方案直接复用。点赞收藏。"

        async def fake_sleep(_seconds):
            return None

        async def fake_call(route, system, user, **kwargs):
            if "【输出格式强约束】" in user:
                return (
                    "<diagnosis>需要三套方向。</diagnosis>"
                    "<plan_a_title>58元蟹黄面真香</plan_a_title>"
                    "<plan_b_title>下班冲这碗面</plan_b_title>"
                    "<plan_c_title>普通店竟然翻盘</plan_c_title>"
                    "<plan>分别测试三种角度。</plan>"
                    "<dispute>无</dispute>"
                )
            return ""

        try:
            api._mr.call = fake_call
            api.asyncio.sleep = fake_sleep
            result = asyncio.run(api._agent_arbitrate(
                "南京西路蟹黄面",
                "美食",
                62.0,
                "待优化",
                [{
                    "role": "内容专家",
                    "raw": (
                        "<opinion>内容结构偏散。</opinion>"
                        "<titles>候选标题一\n候选标题二\n候选标题三</titles>"
                        f"<body>{shared_candidate}</body>"
                        "<confidence>0.8</confidence>"
                    ),
                }],
            ))
        finally:
            api._mr.call = original_call
            api.asyncio.sleep = original_sleep

        bodies = [p["body"] for p in result["plans"]]
        self.assertEqual(len(bodies), 3)
        self.assertEqual(len(set(bodies)), 3)
        self.assertFalse(any(body == shared_candidate for body in bodies))
        self.assertTrue(all(p.get("fallback") == "style_candidate" for p in result["plans"]))

    def test_model_router_retries_empty_claude_response_before_fallback(self):
        original_call_claude = api._mr._call_claude
        original_call_kimi = api._mr._call_kimi
        original_attempts = api._mr.MODEL_RETRY_ATTEMPTS
        original_delay = api._mr.MODEL_RETRY_BASE_DELAY
        original_sleep = api._mr.asyncio.sleep
        original_route = dict(api._mr.TASK_ROUTING["diagnosis"])
        attempts = {"claude": 0, "kimi": 0}

        async def fake_sleep(_seconds):
            return None

        async def fake_claude(*args, **kwargs):
            attempts["claude"] += 1
            return "" if attempts["claude"] == 1 else "ok-after-retry"

        async def fake_kimi(*args, **kwargs):
            attempts["kimi"] += 1
            return "fallback-should-not-be-used"

        try:
            api._mr._call_claude = fake_claude
            api._mr._call_kimi = fake_kimi
            api._mr.MODEL_RETRY_ATTEMPTS = 3
            api._mr.MODEL_RETRY_BASE_DELAY = 0
            api._mr.asyncio.sleep = fake_sleep
            api._mr.TASK_ROUTING["diagnosis"] = {
                "primary": api._mr.CLAUDE_HAIKU,
                "fallback": [api._mr.KIMI_TEXT],
            }
            result = asyncio.run(api._mr.call("diagnosis", "system", "user"))
        finally:
            api._mr._call_claude = original_call_claude
            api._mr._call_kimi = original_call_kimi
            api._mr.MODEL_RETRY_ATTEMPTS = original_attempts
            api._mr.MODEL_RETRY_BASE_DELAY = original_delay
            api._mr.asyncio.sleep = original_sleep
            api._mr.TASK_ROUTING["diagnosis"] = original_route

        self.assertEqual(result, "ok-after-retry")
        self.assertEqual(attempts["claude"], 2)
        self.assertEqual(attempts["kimi"], 0)

    def test_model_router_times_out_slow_claude_before_fallback(self):
        original_call_claude = api._mr._call_claude
        original_call_kimi = api._mr._call_kimi
        original_attempts = api._mr.MODEL_RETRY_ATTEMPTS
        original_timeout = api._mr.CLAUDE_FAST_TIMEOUT_SECONDS
        original_route = dict(api._mr.TASK_ROUTING["content_gen"])
        attempts = {"claude": 0, "kimi": 0}

        async def slow_claude(*args, **kwargs):
            attempts["claude"] += 1
            await asyncio.sleep(0.05)
            return "late"

        async def fake_kimi(*args, **kwargs):
            attempts["kimi"] += 1
            return "fallback-after-timeout"

        try:
            api._mr._call_claude = slow_claude
            api._mr._call_kimi = fake_kimi
            api._mr.MODEL_RETRY_ATTEMPTS = 1
            api._mr.CLAUDE_FAST_TIMEOUT_SECONDS = 0.01
            api._mr.TASK_ROUTING["content_gen"] = {
                "primary": api._mr.CLAUDE_HAIKU,
                "fallback": [api._mr.KIMI_TEXT],
            }
            result = asyncio.run(api._mr.call("content_gen", "system", "user"))
        finally:
            api._mr._call_claude = original_call_claude
            api._mr._call_kimi = original_call_kimi
            api._mr.MODEL_RETRY_ATTEMPTS = original_attempts
            api._mr.CLAUDE_FAST_TIMEOUT_SECONDS = original_timeout
            api._mr.TASK_ROUTING["content_gen"] = original_route

        self.assertEqual(result, "fallback-after-timeout")
        self.assertEqual(attempts["claude"], 1)
        self.assertEqual(attempts["kimi"], 1)

    def test_video_analyze_fails_fast_when_video_understanding_is_empty(self):
        original_check = api._billing.check_and_deduct
        original_record = api._billing.record_free_usage
        original_video = api._kimi_video_understand
        original_predict = api._predict
        original_frames = dict(api._video_frames)
        predict_called = {"value": False}

        async def fake_video(*args, **kwargs):
            return ""

        def fake_predict(*args, **kwargs):
            predict_called["value"] = True
            return 50.0, {}

        try:
            api._billing.check_and_deduct = lambda user_id, op: None
            api._billing.record_free_usage = lambda user_id, op: None
            api._kimi_video_understand = fake_video
            api._predict = fake_predict
            api._video_frames.clear()
            api._video_frames["vid-empty"] = {
                "frames": [b"fake-frame"],
                "duration_sec": 1.0,
                "raw_fps": 1.0,
            }

            async def run():
                return await api.analyze(
                    api.AnalyzeInput(
                        note_title="",
                        desc="",
                        local_time="2026062412",
                        domain="美食",
                        video_file_id="vid-empty",
                    ),
                    user={"id": "u1"},
                )

            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(run())
        finally:
            api._billing.check_and_deduct = original_check
            api._billing.record_free_usage = original_record
            api._kimi_video_understand = original_video
            api._predict = original_predict
            api._video_frames.clear()
            api._video_frames.update(original_frames)

        self.assertEqual(ctx.exception.status_code, 502)
        self.assertFalse(predict_called["value"])

    def test_video_library_body_summarizes_material_without_raw_analysis_markdown(self):
        body = api._video_library_note_body(
            "",
            "### 深度解读\n"
            "1. 整体场景与视觉氛围\n"
            "- 桌面出现乳鸽、小青龙和多人聚餐画面，适合做广州粤菜探店素材。\n"
            "#### 标题钩子\n"
            "- 这个套餐适合周末聚餐",
            duration_sec=3.0,
            frames_extracted=3,
            frames_to_ai=2,
        )
        self.assertIn("【视频素材理解】", body)
        self.assertIn("视频约 3.0s", body)
        self.assertIn("AI 理解使用 2/3 帧", body)
        self.assertIn("乳鸽", body)
        self.assertNotIn("###", body)
        self.assertNotIn("深度解读", body)
        self.assertNotIn("标题钩子", body)

    def test_chat_start_surfaces_missing_fact_supplement_prompts(self):
        original_persist = api._persist_chat_session
        original_get_user_learn = api._get_user_learn
        original_memory_prompt = api._memory.build_memory_prompt
        result = None
        try:
            api._persist_chat_session = lambda *_args, **_kwargs: None
            api._get_user_learn = lambda *_args, **_kwargs: {}
            api._memory.build_memory_prompt = lambda *_args, **_kwargs: ""
            result = asyncio.run(api.chat_start(
                api.ChatStartInput(
                    note_title="广州粤菜聚餐",
                    note_body="乳鸽和小青龙都适合聚餐，建议收藏。",
                    domain="美食",
                    generate_context={
                        "current_score": 72.0,
                        "grade": "良好",
                        "content_intent": "决策转化型",
                        "merchant_visibility": "展示商家",
                        "fact_source_policy": "skip",
                        "quality_issues": ["美食笔记缺少营业时间或周末营业信息"],
                    },
                ),
                user={"id": "u-test"},
            ))
            self.assertEqual(result.current_score, 72.0)
            self.assertTrue(result.supplement_prompts)
            self.assertEqual(result.supplement_prompts[0]["field"], "business_hours")
            self.assertIn("营业时间", result.welcome)
            prompt = api._build_chat_system_prompt(api._chat_sessions[result.session_id])
            self.assertIn("【待用户补充事实】", prompt)
            self.assertIn("不得擅自编造", prompt)
        finally:
            api._persist_chat_session = original_persist
            api._get_user_learn = original_get_user_learn
            api._memory.build_memory_prompt = original_memory_prompt
            if result is not None:
                api._chat_sessions.pop(result.session_id, None)

    def test_chat_structured_supplements_merge_into_fact_context(self):
        session = {
            "note_title": "广州粤菜聚餐",
            "note_body": "乳鸽和小青龙都适合聚餐，建议收藏。",
            "domain": "美食",
            "current_score": 67.0,
            "messages": [],
            "supplement_prompts": [
                {"field": "price", "label": "补充人均/价格"},
                {"field": "must_order", "label": "补充必点"},
                {"field": "business_hours", "label": "补充营业时间"},
            ],
            "fact_context": "- 价格/人均：人均80元\n- 位置/地址：北京路商圈",
            "generate_context": {},
        }
        merged = api._merge_supplement_values_into_session(
            session,
            {
                "price": "100元",
                "must_order": "小青龙乌冬、汤泡饭",
                "business_hours": "周一至周日 11:00-22:00",
            },
        )
        self.assertEqual(merged["price"], "人均100元")
        self.assertEqual(merged["must_order"], "小青龙乌冬、汤泡饭")
        self.assertEqual(merged["business_hours"], "周一至周日 11:00-22:00")
        self.assertIn("- 价格/人均：人均100元", session["fact_context"])
        self.assertIn("- 必点/招牌菜：小青龙乌冬、汤泡饭", session["fact_context"])
        self.assertIn("- 营业时间：周一至周日 11:00-22:00", session["fact_context"])
        self.assertNotIn("人均80元", session["fact_context"])
        self.assertEqual(
            session["generate_context"]["confirmed_supplement_values"]["must_order"],
            "小青龙乌冬、汤泡饭",
        )
        prompt = api._build_chat_system_prompt(session)
        self.assertIn("【已核验事实边界】", prompt)
        self.assertIn("价格/人均：人均100元", prompt)
        self.assertIn("必点/招牌菜：小青龙乌冬、汤泡饭", prompt)
        self.assertIn("营业时间：周一至周日 11:00-22:00", prompt)
        msg = api.ChatMessageInput(
            session_id="s-test",
            message="我已补充真实信息，请继续优化。",
            supplement_values={"price": "100元"},
        )
        self.assertEqual(msg.supplement_values, {"price": "100元"})

    def test_analyze_entrypoints_share_v04_agent_fact_memory_chain(self):
        original_check = api._billing.check_and_deduct
        original_record = api._billing.record_free_usage
        original_video = api._kimi_video_understand
        original_quick = api._kimi_vision_quick
        original_frames = dict(api._video_frames)
        original_enrich = api._maybe_enrich_facts
        original_append_fact = api._append_fact_enrichment
        original_scheduler = api._SCHEDULER_AVAILABLE
        original_semantic = api.compute_semantic_features
        original_predict = api._predict
        original_find_weaknesses = api._find_weaknesses
        original_run_agents = api._run_five_agents
        original_shape = api._shape_body_for_delivery
        original_score = api._score_generated_note
        original_quality = api._generated_quality_issues
        original_integrity = api._delivery_integrity_issues
        original_needs_lift = api._needs_v04_score_lift
        original_memory_prompt = api._memory.build_memory_prompt
        original_memory_achievement = api._memory.check_and_record_achievements
        original_log = api._log_analysis
        original_db_execute = api._db.execute
        captured_notes = []
        captured_agent_contexts = []
        fact_calls = []

        async def fake_video(file_id, domain, brief):
            return "视频里拍到芝士焗小青龙、红烧乳鸽和万博门店环境，适合做餐饮探店诊断。"

        async def fake_enrich(domain, title, text, **_kwargs):
            fact_calls.append((domain, title, text))
            return {
                "enabled": True,
                "provider": "amap",
                "query": "长禧家珑厨万博广晟店",
                "facts": {"price": "人均98元", "hours": "11:00-22:00"},
                "sources": [{"title": "高德地图"}],
                "confidence": 0.9,
            }

        def fake_append_fact(text, _enrichment):
            return (
                (text or "").strip()
                + "\n\n【联网事实补全】\n"
                + "- 事实源：高德地图\n"
                + "- 位置/地址：广州番禺万博商圈\n"
                + "- 价格/人均：人均98元\n"
                + "- 营业时间：11:00-22:00\n"
                + "- 必点/招牌菜：芝士焗小青龙、红烧乳鸽"
            )

        async def fake_run_agents(note, *_args, **_kwargs):
            captured_notes.append(note)
            captured_agent_contexts.append(_kwargs.get("agent_context", ""))
            bodies = [
                "先看决策信息：长禧家珑厨在广州番禺万博商圈，人均98元，营业时间11:00-22:00。芝士焗小青龙是招牌，红烧乳鸽适合分享。点赞收藏。#广州美食 #番禺美食 #粤菜 #万博探店 #小青龙",
                "这版从菜品种草切入：芝士焗小青龙上桌有热度，红烧乳鸽皮脆肉嫩，适合想吃粤菜的人。地址在广州番禺万博商圈，人均98元。点赞收藏。#广州美食 #番禺美食 #粤菜 #万博美食 #探店",
                "适合想稳一点聚餐的人：这里胜在菜品信息清楚，人均98元，营业时间11:00-22:00。小青龙和乳鸽优先点，赶时间先确认排队。点赞收藏。#广州美食 #番禺美食 #粤菜聚餐 #万博 #周末去哪儿",
            ]
            return {
                "diagnosis": "三入口统一进入五 agent 诊断。",
                "titles": ["万博粤菜人均98元", "小青龙乳鸽这样点", "番禺聚餐小青龙乳鸽"],
                "plans": [
                    {"title": "万博粤菜人均98元", "body": bodies[0]},
                    {"title": "小青龙乳鸽这样点", "body": bodies[1]},
                    {"title": "番禺聚餐小青龙乳鸽", "body": bodies[2]},
                ],
                "plan": "按决策、菜品、避坑三方向输出。",
                "body": bodies[0],
                "dispute": "",
                "expert_opinions": [{"role": "内容专家", "raw": "ok"}],
            }

        async def fake_shape(_title, body, *_args, **_kwargs):
            return body

        async def fake_score(_title, _body, *_args, **_kwargs):
            return 73.0, {
                "body_len": 300,
                "tag_count": 5,
                "body_cta_count": 1,
                "body_has_price": 1,
                "body_has_address": 1,
                "body_has_hours": 1,
                "body_has_must_order": 1,
                "title_has_city": 1,
                "title_has_number": 1,
                "title_has_pos_emotion": 1,
                "plad_number_ratio": 0.03,
            }, "良好"

        try:
            api._billing.check_and_deduct = lambda user_id, op: None
            api._billing.record_free_usage = lambda user_id, op: None
            api._kimi_video_understand = fake_video
            api._kimi_vision_quick = lambda *_args, **_kwargs: "截图里有餐厅门头、芝士焗小青龙和人均98元信息。"
            api._video_frames.clear()
            api._video_frames["vid-ok"] = {"frames": [b"fake-frame"], "duration_sec": 3.0, "raw_fps": 1.0}
            api._maybe_enrich_facts = fake_enrich
            api._append_fact_enrichment = fake_append_fact
            api._SCHEDULER_AVAILABLE = False
            api.compute_semantic_features = lambda *_args, **_kwargs: {
                "semantic_emotional_intensity": 0.5,
                "semantic_empathetic_engagement": 0.5,
                "semantic_rhetorical_score": 0.5,
            }
            api._predict = lambda *_args, **_kwargs: (68.0, {})
            api._find_weaknesses = lambda *_args, **_kwargs: []
            api._run_five_agents = fake_run_agents
            api._shape_body_for_delivery = fake_shape
            api._score_generated_note = fake_score
            api._generated_quality_issues = lambda *_args, **_kwargs: []
            api._delivery_integrity_issues = lambda *_args, **_kwargs: []
            api._needs_v04_score_lift = lambda *_args, **_kwargs: False
            api._memory.build_memory_prompt = lambda user_id: "用户偏好：文案自然，少模板。"
            api._memory.check_and_record_achievements = lambda *_args, **_kwargs: None
            api._log_analysis = lambda *_args, **_kwargs: None
            api._db.execute = lambda *_args, **_kwargs: None

            requests = [
                api.AnalyzeInput(
                    note_title="长禧家珑厨万博广晟店",
                    desc="手动输入：想做番禺万博粤菜探店。",
                    local_time="2026062812",
                    domain="美食",
                ),
                api.AnalyzeInput(
                    note_title="长禧家珑厨万博广晟店",
                    desc="截图上传：需要根据图片判断怎么写。",
                    local_time="2026062812",
                    domain="美食",
                    extra_images=["fake-image-b64"],
                ),
                api.AnalyzeInput(
                    note_title="长禧家珑厨万博广晟店",
                    desc="视频上传：帮我诊断视频素材适合怎么写。",
                    local_time="2026062812",
                    domain="美食",
                    video_file_id="vid-ok",
                ),
            ]
            responses = [
                asyncio.run(api.analyze(req, user={"id": "u1"}))
                for req in requests
            ]
        finally:
            api._billing.check_and_deduct = original_check
            api._billing.record_free_usage = original_record
            api._kimi_video_understand = original_video
            api._kimi_vision_quick = original_quick
            api._video_frames.clear()
            api._video_frames.update(original_frames)
            api._maybe_enrich_facts = original_enrich
            api._append_fact_enrichment = original_append_fact
            api._SCHEDULER_AVAILABLE = original_scheduler
            api.compute_semantic_features = original_semantic
            api._predict = original_predict
            api._find_weaknesses = original_find_weaknesses
            api._run_five_agents = original_run_agents
            api._shape_body_for_delivery = original_shape
            api._score_generated_note = original_score
            api._generated_quality_issues = original_quality
            api._delivery_integrity_issues = original_integrity
            api._needs_v04_score_lift = original_needs_lift
            api._memory.build_memory_prompt = original_memory_prompt
            api._memory.check_and_record_achievements = original_memory_achievement
            api._log_analysis = original_log
            api._db.execute = original_db_execute

        self.assertEqual(len(fact_calls), 3)
        self.assertNotIn("截图里有餐厅门头", fact_calls[1][2])
        self.assertIn("视频里拍到芝士焗小青龙", fact_calls[2][2])
        self.assertEqual(len(captured_notes), 3)
        self.assertIn("手动输入", captured_notes[0].desc)
        self.assertNotIn("【其他内容图片描述】", captured_notes[1].desc)
        self.assertIn("【视频画面内容（AI 解读）】", captured_notes[2].desc)
        self.assertEqual(responses[2].input_diagnostics["video_duration_sec"], 3.0)
        self.assertEqual(responses[2].input_diagnostics["video_frames_extracted"], 1)
        self.assertEqual(responses[2].input_diagnostics["video_frames_to_ai"], 1)
        self.assertEqual(len(captured_agent_contexts), 3)
        self.assertIn("【其他内容图片描述】", captured_agent_contexts[1])
        for ctx in captured_agent_contexts:
            self.assertIn("【联网事实补全】", ctx)
            self.assertIn("【用户长期偏好/记忆】", ctx)
            self.assertIn("用户偏好：文案自然", ctx)

        for resp in responses:
            self.assertEqual(resp.model_used, "claude-routed-5-agents")
            self.assertEqual(len(resp.suggested_plans), 3)
            bodies = [item["body"] for item in resp.suggested_plans]
            self.assertEqual(len(set(bodies)), 3)
            self.assertFalse(any(item["quality_failed"] for item in resp.suggested_plans))
            self.assertIn(resp.suggested_body, bodies)

    def test_structured_fact_boundary_flags_unprovided_price_without_blocking_narrative(self):
        source = "广州番禺万博珑厨双人套餐，适合周末约会，菜品有小青龙和乳鸽。"
        body = (
            "朋友说这里环境不错，进门灯光很舒服。人均188元，营业时间11:00-22:00，"
            "周末排队45分钟。点赞收藏。"
        )
        issues = api._structured_fact_boundary_issues(body, source, "美食")
        self.assertTrue(any("价格" in item for item in issues), issues)
        self.assertTrue(any("营业时间" in item for item in issues), issues)
        self.assertTrue(any("排队" in item for item in issues), issues)
        self.assertFalse(api._has_blocking_quality_issues(80, issues, "美食"))

        narrative_only = "朋友说这里环境不错，进门灯光很舒服，乳鸽香气很足。点赞收藏。"
        self.assertEqual(api._structured_fact_boundary_issues(narrative_only, source, "美食"), [])

        travel_source = "广州长隆酒店：美团豪华型，美团真实评分4.8，￥929起/晚"
        travel_body = "这家住宿起价929元/晚，适合想住在园区里的亲子家庭。"
        self.assertFalse(api._structured_fact_boundary_issues(travel_body, travel_source, "旅行"))

    def test_structured_fact_boundary_blocks_unprovided_price_value_claims(self):
        source = "广州番禺万博珑厨双人套餐，菜品有小青龙、乳鸽和点心拼盘。"
        issues = api._structured_fact_boundary_issues("精致粤菜不贵，这套很划算，物有所值。点赞收藏。", source, "美食")
        self.assertTrue(any("价格依据" in item for item in issues), issues)
        overclaim_issues = api._structured_fact_boundary_issues("五一聚餐首选，98块吃出五星体验。", source, "美食")
        self.assertTrue(any("五星/满分" in item for item in overclaim_issues), overclaim_issues)
        self.assertTrue(any("节假日" in item for item in overclaim_issues), overclaim_issues)
        amenity_ok = api._structured_fact_boundary_issues("停车便利，地铁口出来就到，适合朋友聚餐。", source, "美食")
        self.assertFalse(any("停车/地铁" in item for item in amenity_ok), amenity_ok)
        group_size_issues = api._structured_fact_boundary_issues("店在7层，适合2-6人小聚。", source, "美食")
        self.assertTrue(any("人数/适用规模" in item for item in group_size_issues), group_size_issues)

        sourced = "用户明确说这家不贵，适合周末聚餐。"
        self.assertEqual(api._structured_fact_boundary_issues("这家不贵，适合周末聚餐。点赞收藏。", sourced, "美食"), [])

    def test_title_sanitizer_removes_low_quality_and_unverified_title_claims(self):
        source = "【联网事实补全】\n- 价格/人均：人均98元\n- 评分/口碑：高德评分4.5"
        title = api._sanitize_title_for_delivery("五一聚餐首选，芝士小青龙绝了", source, "美食")
        self.assertNotIn("五一", title)
        self.assertNotIn("绝了", title)
        self.assertLessEqual(len(title), api._TITLE_DELIVERY_MAX)

        backed = api._sanitize_title_for_delivery("万博这家粤菜，98块吃出五星体验", source, "美食")
        self.assertNotIn("五星体验", backed)
        self.assertIn("聚餐体验", backed)

    def test_parking_and_metro_are_allowed_but_group_size_is_softened(self):
        source = "【联网事实补全】\n- 位置/地址：南村镇汉溪大道东386号广晟万博城A座7层\n- 价格/人均：人均98元\n- 营业时间：09:00-14:00 17:00-21:00"
        body = "番禺万博这家粤菜停车便利，地铁口出来就到，适合2-6人周末小聚，芝士小青龙是必点。"
        shaped = api._insert_safe_fact_line(body, "美食", source)
        self.assertIn("停车便利", shaped)
        self.assertIn("地铁口", shaped)
        self.assertNotIn("2-6人", shaped)
        self.assertIn("适合多人", shaped)
        self.assertFalse(api._structured_fact_boundary_issues(shaped, source, "美食"))

    def test_unprovided_chinese_group_size_table_is_softened(self):
        source = "38平出租屋改造，总预算3000元，可折叠餐桌268元，窄边书桌399元。"
        body = "原来四人桌放在客厅中间，不吃饭时就是障碍物。换成可折叠餐桌268元后，动线更顺。"
        shaped = api._insert_safe_fact_line(body, "家居", source)

        self.assertNotIn("四人桌", shaped)
        self.assertIn("固定餐桌", shaped)
        self.assertFalse(api._structured_fact_boundary_issues(shaped, source, "家居"))

    def test_emoji_practical_info_is_normalized_without_duplicate_fact_line(self):
        source = "【联网事实补全】\n- 位置/地址：南村镇汉溪大道东386号广晟万博城A座7层\n- 价格/人均：人均98元\n- 营业时间：09:00-14:00 17:00-21:00"
        body = (
            "芝士焗小青龙是必点，乳鸽适合分享。点赞收藏。\n\n"
            "📍 南村镇汉溪大道东386号广晟万博城A座7层\n"
            "💰 人均98元｜高德评分4.5\n"
            "⏰ 09:00-14:00 / 17:00-21:00\n"
            "📲 周末建议提前预订\n"
            "#番禺探店 #粤菜聚餐 #广州美食 #芝士焗小青龙 #乳鸽"
        )
        shaped = api._insert_safe_fact_line(body, "美食", source)
        self.assertIn("门店地址在南村镇汉溪大道东386号广晟万博城A座7层", shaped)
        self.assertIn("人均98元", shaped)
        self.assertIn("营业时间09:00-14:00 / 17:00-21:00", shaped)
        self.assertIn("周末建议提前预订", shaped)
        self.assertNotIn("地址：", shaped)
        self.assertNotIn("人均/价格：", shaped)
        self.assertEqual(shaped.count("实用信息："), 0)

    def test_body_format_issues_detect_multi_plan_pollution(self):
        polluted = "# 方案一：反差冲击型\n\n**标题**：广州番禺珑厨\n\n**正文**：这是一篇正文。\n\n---\n\n# 方案二：场景型"
        self.assertTrue(api._body_format_issues(polluted))
        clean = "小青龙上桌时芝士还在微微冒泡，乳鸽皮脆肉嫩。点赞收藏。#广州美食 #粤菜"
        self.assertEqual(api._body_format_issues(clean), [])

    def test_safe_food_fact_line_hits_features_without_fabricated_numbers(self):
        source = "广州番禺万博珑厨双人套餐素材，未提供套餐价格、人均消费、营业时间、排队时长。"
        body = (
            "芝士焗小青龙是必点，乳鸽皮脆肉嫩，忘不了鱼清鲜，点心拼盘和雪燕杏花羹适合收尾。"
            "点赞收藏，评论区告诉我你最想试哪一道。#广州美食 #番禺美食 #万博美食 #粤菜 #探店"
        )
        shaped = api._insert_safe_fact_line(body, "美食", source)
        self.assertNotIn("位于广州番禺万博商圈", shaped)
        self.assertNotIn("套餐价格以门店套餐页为准", shaped)
        self.assertNotIn("营业时间以门店公示为准", shaped)
        self.assertNotIn("周末建议提前预订", shaped)
        self.assertFalse(any("结构化事实不能编造" in item for item in api._structured_fact_boundary_issues(shaped, source, "美食")))

        note = api.NoteInput(
            note_title="广州番禺珑厨，6道粤菜绝了",
            desc=api._normalize_tags_for_scoring(shaped),
            local_time="2026062419",
            domain="美食",
        )
        _score, features = api._predict(note)
        self.assertEqual(features.get("body_has_price"), 0)
        self.assertEqual(features.get("body_has_hours"), 0)
        self.assertEqual(features.get("body_has_booking"), 0)

    def test_internal_missing_fact_constraints_do_not_leak_into_delivery_body(self):
        source = "\n".join([
            "【任务事实】",
            "- 位置/地址：地点在广州番禺万博商圈附近",
            "- 价格/人均：用户未提供准确人均和营业时间，不能编造具体数字",
            "- 营业时间：用户未提供准确人均和营业时间，不能编造具体数字",
            "- 已核验事实：用户未提供准确人均和营业时间，不能编造具体数字",
        ])
        body = (
            "芝士焗小青龙是必点，红烧乳鸽火候稳定。\n\n"
            "实用信息：地址：地点在广州番禺万博商圈附近，用户未提供准确人均和营业时间，不能编造具体数字，"
            "营业时间：用户未提供准确人均和营业时间，不能编造具体数字。\n"
            "#番禺美食 #粤菜聚餐 #万博商圈 #芝士焗小青龙 #家庭聚餐"
        )
        shaped = api._insert_safe_fact_line(body, "美食", source)
        self.assertNotIn("用户未提供", shaped)
        self.assertNotIn("不能编造", shaped)
        self.assertNotIn("实用信息：", shaped)
        self.assertNotIn("套餐价格以门店套餐页为准", shaped)
        self.assertNotIn("营业时间以门店公示为准", shaped)
        self.assertNotIn("，。", shaped)
        self.assertEqual(api._body_format_issues(shaped), [])

    def test_safe_food_fact_line_prefers_verified_fact_context(self):
        source = "\n".join([
            "【联网事实补全】",
            "- 位置/地址：南村镇汉溪大道东386号广晟万博城A座7层",
            "- 价格/人均：人均98元",
            "- 营业时间：周一至周日 11:00-22:00",
            "- 评分/口碑：高德评分4.5",
            "- 预订/排队：高德显示支持订餐/预订",
        ])
        shaped = api._insert_safe_fact_line(
            "芝士焗小青龙是招牌，乳鸽火候稳定，适合番禺万博聚餐。",
            "美食",
            source,
        )
        safe_line = api._safe_fact_line("美食", source)
        self.assertIn("门店地址在南村镇汉溪大道东386号广晟万博城A座7层", safe_line)
        self.assertIn("人均98元", safe_line)
        self.assertIn("高德评分4.5", safe_line)
        self.assertIn("营业时间周一至周日 11:00-22:00", safe_line)
        self.assertNotIn("门店地址在南村镇汉溪大道东386号广晟万博城A座7层", shaped)
        self.assertNotIn("套餐价格以门店套餐页为准", shaped)
        self.assertFalse(api._structured_fact_boundary_issues(shaped, source, "美食"))

    def test_verified_fact_prefix_context_extracts_amap_hours(self):
        source = "\n".join([
            "【联网事实补全】",
            "- 已核验事实：事实源：高德地图",
            "- 已核验事实：门店名：蜀大侠火锅(春熙路旗舰店)",
            "- 已核验事实：地址：上东大街6号春南商场2层(西南书城)",
            "- 已核验事实：人均：89元",
            "- 已核验事实：营业时间：00:00-01:00 11:00-24:00",
            "- 已核验事实：高德评分：4.6",
        ])
        self.assertEqual(api._fact_context_value(source, "营业时间"), "00:00-01:00 11:00-24:00")
        safe_line = api._safe_fact_line("美食", source)
        self.assertIn("门店地址在上东大街6号春南商场2层(西南书城)", safe_line)
        self.assertIn("人均89元", safe_line)
        self.assertIn("高德评分4.6", safe_line)
        self.assertIn("营业时间00:00-01:00 11:00-24:00", safe_line)
        shaped = api._insert_safe_fact_line(
            "毛肚和巴蜀麻辣牛肉是必点，第一次来可以选鸳鸯锅。",
            "美食",
            source,
        )
        self.assertNotIn("门店地址在上东大街6号春南商场2层(西南书城)", shaped)
        self.assertNotIn("人均89元", shaped)
        self.assertNotIn("高德评分4.6", shaped)
        self.assertNotIn("营业时间00:00-01:00 11:00-24:00", shaped)
        self.assertNotIn("营业时间以门店公示为准", shaped)

    def test_food_decision_facts_survive_delivery_compaction(self):
        source = "\n".join([
            "【联网事实补全】",
            "- 已核验事实：地址：上东大街6号春南商场2层",
            "- 已核验事实：人均：89元",
            "- 已核验事实：营业时间：00:00-01:00 11:00-24:00",
        ])
        raw = (
            "第一次来春熙路吃火锅，先把锅底和点单顺序想清楚。"
            + "毛肚、牛肉、虾滑都适合先上，素菜和甜品放在后半程调节辣度。"
            * 8
            + "\n\n地址：上东大街6号春南商场2层，人均89元，营业时间：00:00-01:00 11:00-24:00，周末建议提前预订。"
            "\n#成都火锅 #春熙路美食 #蜀大侠"
        )
        shaped = api._compact_body_to_delivery_limit(api._insert_safe_fact_line(raw, "美食", source), "美食")
        self.assertLessEqual(api._body_content_len_without_tags(shaped), api._quality_body_max("美食"))
        self.assertIn("营业时间", shaped)
        self.assertIn("人均89元", shaped)
        self.assertIn("收藏", shaped)
        self.assertIn("#成都火锅", shaped)

    def test_safe_food_fact_line_strips_duplicate_fact_labels_from_amap_context(self):
        source = "\n".join([
            "【联网事实补全】",
            "- 位置/地址：门店名：陶陶居酒家(第十甫路店)",
            "- 位置/地址：地址：第十甫路20号1-5层",
            "- 价格/人均：人均：110元",
            "- 价格/人均：套餐信息：虾饺皇、烧鹅、奶黄包",
            "- 营业时间：营业时间：08:00-16:30 17:00-21:30",
            "- 评分/口碑：高德评分：4.7",
        ])
        shaped = api._insert_safe_fact_line(
            "陶陶居虾饺皇是招牌，烧鹅和奶黄包也值得点。",
            "美食",
            source,
        )
        safe_line = api._safe_fact_line("美食", source)
        self.assertIn("门店地址在第十甫路20号1-5层", safe_line)
        self.assertIn("人均110元", safe_line)
        self.assertIn("高德评分4.7", safe_line)
        self.assertIn("营业时间08:00-16:30 17:00-21:30", safe_line)
        self.assertNotIn("门店地址在第十甫路20号1-5层", shaped)
        self.assertNotIn("门店地址在陶陶居", shaped)
        self.assertNotIn("门店地址在地址", shaped)
        self.assertNotIn("营业时间营业时间", shaped)
        self.assertNotIn("人均：", shaped)
        self.assertNotIn("高德评分：", shaped)

        natural = api._insert_safe_fact_line(
            "陶陶居位于第十甫路20号1-5层，人均110元，早茶时段08:00-16:30营业，虾饺皇是招牌。点赞收藏。",
            "美食",
            source,
        )
        self.assertEqual(natural.count("门店地址在"), 0)
        self.assertEqual(natural.count("08:00-16:30"), 1)

        polluted = api._insert_safe_fact_line(
            "陶陶居虾饺皇是招牌。\n\n门店地址在门店名：陶陶居酒家(第十甫路店)，人均110元，营业时间08:00-16:30 17:00-21:30。",
            "美食",
            source,
        )
        self.assertNotIn("门店地址在门店名", polluted)
        self.assertNotIn("门店地址在第十甫路20号1-5层", polluted)

    def test_low_quality_phrases_are_soft_issues_and_polished(self):
        source = "【联网事实补全】\n- 价格/人均：人均98元\n- 位置/地址：广州番禺万博\n- 营业时间：每天11:00-22:00"
        body = (
            "这只乳鸽绝了，香气直冲脑门，骨头都能嚼碎，根本停不下来。"
            "芝士焗小青龙适合放在第一道，虾肉和芝士的咸香更容易打开胃口，"
            "乳鸽适合两三个人分着吃，忘不了鱼负责清鲜口，点心拼盘和雪燕杏花羹适合收尾，"
            "如果是番禺万博附近聚餐，这种点单顺序信息完整，长辈朋友都比较容易接受，"
            "人均和地址已经写在实用信息里，读者不需要再翻评论区确认，"
            "营业时间也能帮助判断中午家庭聚餐还是晚上朋友局更合适，"
            "整篇重点放在怎么点、谁适合、到店前要确认什么，而不是堆夸张形容词，"
            "实用信息写清楚以后，读者能直接判断要不要收藏导航。点赞收藏。"
            "#广州美食 #番禺美食 #粤菜 #探店 #周末去哪儿"
        )
        issues = api._generated_quality_issues(
            "番禺万博粤菜聚餐",
            body,
            "美食",
            65,
            {
                "body_len": 260,
                "tag_count": 5,
                "body_cta_count": 1,
                "body_has_price": 1,
                "body_has_address": 1,
                "body_has_hours": 1,
                "body_has_must_order": 1,
            },
        )
        self.assertTrue(any("模板化/夸张表达" in item for item in issues), issues)
        self.assertFalse(api._has_blocking_quality_issues(65, issues, "美食"))
        shaped = api._insert_safe_fact_line(body, "美食", source)
        self.assertNotIn("直冲脑门", shaped)
        self.assertNotIn("骨头都能嚼碎", shaped)
        self.assertIn("香气很明显", shaped)
        self.assertIn("皮脆肉嫩，火候到位", shaped)

    def test_food_buffet_claim_requires_explicit_source(self):
        source = "\n".join([
            "【联网事实补全】",
            "- 位置/地址：惠福东路470号",
            "- 价格/人均：人均86元",
            "- 营业时间：08:00-16:00 17:00-21:00",
        ])
        raw = "点都德在惠福东路470号，人均86元吃到饱，营业时间08:00-16:00，虾饺皇必点。"
        shaped = api._insert_safe_fact_line(raw, "美食", source)
        self.assertNotIn("吃到饱", shaped)
        self.assertIn("人均86元，点心选择不少", shaped)
        self.assertTrue(any("吃到饱" in item for item in api._structured_fact_boundary_issues(raw, source, "美食")))

        buffet_source = source + "\n- 套餐说明：自助不限量，支持吃到饱"
        self.assertFalse(api._structured_fact_boundary_issues(raw, buffet_source, "美食"))

    def test_delivery_cta_is_inserted_before_tags(self):
        body = "芝士焗小青龙必点，乳鸽皮脆肉嫩。\n#广州美食 #番禺美食"
        shaped = api._ensure_delivery_cta(body, "美食")
        self.assertIn("收藏", shaped)
        self.assertIn("评论区", shaped)
        self.assertLess(shaped.index("收藏"), shaped.index("#广州美食"))
        note = api.NoteInput(note_title="广州番禺珑厨，6道粤菜绝了", desc=api._normalize_tags_for_scoring(shaped), domain="美食")
        _score, features = api._predict(note)
        self.assertGreaterEqual(features.get("body_cta_count", 0), 1)

    def test_food_seed_intent_skips_amap_without_merchant(self):
        result = asyncio.run(api._maybe_enrich_facts(
            "美食",
            "广州龙虾乌冬",
            "只想写真实种草，不展示店名",
            content_intent="真实种草型",
            merchant_visibility="auto",
        ))
        self.assertFalse(result.get("enabled"))
        self.assertEqual(result.get("decision", {}).get("reason"), "seeding_mode_does_not_need_store_facts")
        self.assertFalse(result.get("decision", {}).get("needs_user_supplement"))

    def test_food_decision_intent_requires_confirmed_merchant(self):
        result = asyncio.run(api._maybe_enrich_facts(
            "美食",
            "广州龙虾乌冬",
            "需要到店决策信息，但没有店名",
            content_intent="决策转化型",
            merchant_visibility="show",
        ))
        decision = result.get("decision", {})
        self.assertFalse(result.get("enabled"))
        self.assertEqual(decision.get("reason"), "missing_confirmed_merchant_name")
        self.assertTrue(decision.get("needs_user_supplement"))
        self.assertIn("merchant_name", decision.get("supplement_fields", []))

    def test_food_decision_intent_with_merchant_calls_fact_provider(self):
        original = api._facts.enrich_content_facts
        calls = []

        def fake_enrich(domain, title, text):
            calls.append((domain, title, text))
            return {
                "enabled": True,
                "provider": "amap",
                "query": "长禧家珑厨",
                "facts": {"位置/地址": "广州番禺万博"},
                "sources": [],
                "confidence": 0.9,
            }

        try:
            api._facts.enrich_content_facts = fake_enrich
            result = asyncio.run(api._maybe_enrich_facts(
                "美食",
                "番禺万博粤菜聚餐",
                "芝士焗小青龙和乳鸽适合聚餐",
                content_intent="决策转化型",
                merchant_visibility="show",
                merchant_name="长禧家珑厨万博广晟店",
            ))
        finally:
            api._facts.enrich_content_facts = original

        self.assertTrue(result.get("enabled"))
        self.assertEqual(result.get("decision", {}).get("provider"), "amap")
        self.assertEqual(calls[0][0], "美食")
        self.assertEqual(calls[0][1], "长禧家珑厨万博广晟店")
        self.assertIn("门店名：长禧家珑厨万博广晟店", calls[0][2])

    def test_placeholder_fact_sentences_are_removed_and_flagged(self):
        body = (
            "门店位于广州本地商圈，套餐价格以门店套餐页为准，营业时间以门店公示为准，周末建议提前预订。"
            "龙虾乌冬汤底很浓，海胆甜虾丼也适合一起点。点赞收藏。#广州美食 #乌冬面 #日料"
        )
        cleaned = api._insert_safe_fact_line(body, "美食", "广州龙虾乌冬")
        self.assertNotIn("门店位于广州本地商圈", cleaned)
        self.assertNotIn("套餐价格以门店套餐页为准", cleaned)
        self.assertNotIn("营业时间以门店公示为准", cleaned)
        issues = api._generated_quality_issues(
            "广州龙虾乌冬推荐",
            body,
            "美食",
            72.0,
            {"tag_count": 3, "body_cta_count": 1, "body_has_price": 0, "body_has_address": 0, "body_has_hours": 0, "body_has_must_order": 1},
            "【创作方向契约】\n- 用户选择的笔记类型：真实种草型。\n- 商家/品牌展示策略：AI识别后决定",
        )
        self.assertTrue(any("占位符" in item or "兜底句" in item for item in issues))

    def test_food_title_sanitizer_removes_overused_stable_template(self):
        source = "【创作方向契约】\n- 用户选择的笔记类型：真实种草型。\n广州番禺万博，芝士焗小青龙、龙虾乌冬、海胆甜虾丼。"
        title = api._sanitize_title_for_delivery("番禺万博这家真的稳", source, "美食")
        self.assertNotIn("这家真的稳", title)
        self.assertNotIn("很稳", title)
        self.assertNotIn("值得冲", title)
        self.assertLessEqual(len(title), api._TITLE_DELIVERY_MAX)

    def test_seed_intent_does_not_penalize_missing_store_facts(self):
        source = "【创作方向契约】\n- 用户选择的笔记类型：真实种草型。\n- 商家/品牌展示策略：不展示商家"
        issues = api._generated_quality_issues(
            "广州龙虾乌冬面推荐",
            "龙虾乌冬汤底浓，海胆甜虾丼也很有记忆点，适合收藏下次慢慢点。点赞收藏。#广州美食 #龙虾乌冬 #日料 #一人食 #海鲜",
            "美食",
            72.0,
            {"tag_count": 5, "body_cta_count": 1, "body_has_price": 0, "body_has_address": 0, "body_has_hours": 0, "body_has_must_order": 1},
            source,
        )
        self.assertFalse(any("缺少真实价格" in item for item in issues))
        self.assertFalse(any("缺少地址" in item for item in issues))
        self.assertFalse(any("缺少营业时间" in item for item in issues))

    def test_fact_enrichment_prefers_china_local_provider_and_formats_context(self):
        old_env = {k: os.environ.get(k) for k in [
            "NOTEAI_FACT_SEARCH",
            "NOTEAI_FACT_SEARCH_PROVIDER",
            "NOTEAI_FACT_SEARCH_CACHE_TTL",
            "AMAP_WEB_KEY",
            "BAIDU_MAP_AK",
            "TENCENT_MAP_KEY",
            "SERPAPI_API_KEY",
        ]}
        try:
            os.environ["NOTEAI_FACT_SEARCH"] = "1"
            os.environ["NOTEAI_FACT_SEARCH_PROVIDER"] = "auto"
            os.environ["AMAP_WEB_KEY"] = "amap-test"
            os.environ["SERPAPI_API_KEY"] = "serp-test"
            self.assertEqual(facts._provider_name(), "amap")
            self.assertTrue(facts.fact_search_enabled())

            items = [{
                "title": "珑厨万博店",
                "snippet": "地址：广州番禺区万博商圈。人均188元。营业时间 11:00-22:00，可提前预订。",
                "url": "https://example.test/poi",
            }]
            extracted = facts.extract_facts_from_search_items(items)
            self.assertIn("人均188元", extracted.get("price", ""))
            self.assertIn("营业时间", extracted.get("hours", ""))
            ctx = facts.format_fact_context({
                "query": "广州 珑厨万博店 地址 营业时间 人均 预订",
                "facts": extracted,
                "sources": [{"title": "珑厨万博店", "url": "https://example.test/poi"}],
                "confidence": 0.7,
            })
            self.assertIn("联网事实补全", ctx)
            self.assertIn("只能引用这里列出的事实", ctx)
            self.assertIn("来源", ctx)
        finally:
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_amap_poi_business_fields_are_structured_for_food_generation(self):
        poi = {
            "id": "B0TEST",
            "name": "长禧家.珑厨(万博广晟店)",
            "type": "餐饮服务;中餐厅;广东菜(粤菜)",
            "address": "南村镇汉溪大道东386号广晟万博城A座7层",
            "tel": "18102253116",
            "business_area": "长隆",
            "tag": "鸿运烧味拼盘,木炭烧黑棕鹅,盐焗罗氏虾",
            "biz_ext": {
                "rating": "4.5",
                "cost": "98.00",
                "meal_ordering": "0",
            },
            "photos": [
                {"title": "门店环境", "url": "https://example.test/photo1.jpg"},
                {"title": "菜品", "url": "https://example.test/photo2.jpg"},
            ],
        }

        item = facts._amap_poi_to_item(poi)
        extracted = facts.extract_facts_from_search_items([item])
        self.assertEqual(extracted["price"], "人均98元")
        self.assertEqual(extracted["rating"], "高德评分4.5")
        self.assertIn("鸿运烧味拼盘", extracted["must_order"])
        self.assertIn("长隆", extracted["business_area"])
        self.assertIn("广东菜", extracted["category"])
        self.assertIn("2张高德门店图片", extracted["photos"])

        ctx = facts.format_fact_context({
            "query": "广州 珑厨万博店 地址 营业时间 人均 预订",
            "facts": extracted,
            "sources": [item],
            "provider": "amap",
            "confidence": 0.9,
        })
        self.assertIn("价格/人均：人均98元", ctx)
        self.assertIn("评分/口碑：高德评分4.5", ctx)
        self.assertIn("商圈：长隆", ctx)
        self.assertIn("门店图片：2张高德门店图片", ctx)

    def test_amap_query_uses_store_keyword_and_rejects_unrelated_poi(self):
        keyword = facts._amap_keyword_from_query("广州 番禺 万博 珑厨万博店 地址 营业时间 人均 预订")
        self.assertEqual(keyword, "珑厨万博店")
        good_poi = {
            "name": "长禧家.珑厨(万博广晟店)",
            "address": "南村镇汉溪大道东386号广晟万博城A座7层",
            "type": "餐饮服务;中餐厅;广东菜(粤菜)",
            "tag": "盐焗罗氏虾",
        }
        bad_poi = {
            "name": "万博牛仔(广州旗舰店)",
            "address": "新港西路82号",
            "type": "购物服务;服装鞋帽皮具店",
            "tag": "",
        }
        self.assertTrue(facts._amap_poi_matches_keyword(good_poi, keyword))
        self.assertFalse(facts._amap_poi_matches_keyword(bad_poi, keyword))

    def test_location_extraction_does_not_treat_road_name_as_city(self):
        self.assertEqual(facts._extract_region("广州 北京路 点都德聚福楼 地址 营业时间"), "广州")
        self.assertEqual(facts._extract_region("上海 南京西路 蟹黄面 地址 营业时间"), "上海")
        self.assertEqual(facts._extract_region("北京 国贸 商务酒店"), "北京")
        query = facts.build_fact_query("美食", "点都德聚福楼 北京路", "广州北京路早茶，虾饺红米肠")
        self.assertIn("广州", query)
        self.assertIn("点都德聚福楼", query)
        self.assertFalse(query.startswith("北京 "), query)

    def test_amap_parenthesized_shop_name_keeps_brand_core_and_ranks_restaurant(self):
        query = "万博 广州 番禺 长禧家.珑厨(万博广晟店) 地址 营业时间 人均 预订"
        keyword = facts._amap_keyword_from_query(query)
        self.assertEqual(keyword, "长禧家.珑厨")
        restaurant = {
            "name": "长禧家.珑厨(万博广晟店)",
            "address": "南村镇汉溪大道东386号广晟万博城A座7层",
            "type": "餐饮服务;中餐厅;广东菜(粤菜)",
            "business_area": "长隆",
            "tag": "鸿运烧味拼盘,木炭烧黑棕鹅",
        }
        mall = {
            "name": "广晟万博城·晟荟潮流商业MALL(广晟·万博城店)",
            "address": "南村镇万博二路89号广晟万博城商业街2栋3楼",
            "type": "购物服务;商场;购物中心",
            "business_area": "长隆",
            "tag": "",
        }
        other_branch = {
            "name": "长禧家.珑厨(东风东路店)",
            "address": "东风东路749号首层",
            "type": "餐饮服务;中餐厅;中餐厅",
            "business_area": "东风",
            "tag": "料理",
        }
        self.assertTrue(facts._amap_poi_matches_keyword(restaurant, keyword))
        self.assertFalse(facts._amap_poi_matches_keyword(mall, keyword))
        self.assertGreater(
            facts._amap_poi_rank(restaurant, keyword, query),
            facts._amap_poi_rank(other_branch, keyword, query),
        )

    def test_amap_v5_detail_business_fields_merge_into_facts(self):
        base = {
            "name": "长禧家.珑厨(万博广晟店)",
            "id": "BTEST",
            "address": "南村镇汉溪大道东386号广晟万博城A座7层",
            "type": "餐饮服务;中餐厅;广东菜(粤菜)",
            "biz_ext": {"cost": "98", "rating": "4.5"},
        }
        detail = {
            "business": {
                "opentime_today": "11:00-22:00",
                "tag": "芝士焗小青龙,鸿运烧味拼盘",
                "tel": "020-00000000",
            },
            "photos": [{"title": "门店环境"}, {"title": "菜品图"}],
        }
        merged = facts._merge_amap_detail(base, detail)
        extracted = facts._amap_poi_facts(merged)
        self.assertEqual(extracted["hours"], "11:00-22:00")
        self.assertEqual(extracted["price"], "人均98元")
        self.assertEqual(extracted["rating"], "高德评分4.5")
        self.assertIn("芝士焗小青龙", extracted["must_order"])
        self.assertIn("2张高德门店图片", extracted["photos"])

    def test_fact_provider_routes_food_to_amap_and_travel_to_meituan_travel(self):
        old_env = {k: os.environ.get(k) for k in [
            "NOTEAI_FACT_SEARCH",
            "NOTEAI_FACT_SEARCH_PROVIDER",
            "AMAP_WEB_KEY",
            "MEITUAN_AI_HUB_TOKEN",
            "MEITUAN_OPEN_TOKEN",
            "NOTEAI_MEITUAN_TRAVEL_ENABLED",
        ]}
        original_ready = facts._meituan_travel_ready
        try:
            os.environ["NOTEAI_FACT_SEARCH"] = "1"
            os.environ["NOTEAI_FACT_SEARCH_PROVIDER"] = "auto"
            os.environ["AMAP_WEB_KEY"] = "amap-test"
            os.environ["MEITUAN_AI_HUB_TOKEN"] = "token-test"
            facts._meituan_travel_ready = lambda: True
            self.assertEqual(facts._provider_name("美食"), "amap")
            self.assertEqual(facts._provider_name("餐饮"), "amap")
            self.assertEqual(facts._provider_name("旅行"), "meituan_travel")
            self.assertEqual(facts._provider_name("酒店"), "meituan_travel")
        finally:
            facts._meituan_travel_ready = original_ready
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_local_verified_facts_feed_high_value_food_context(self):
        old_env = {k: os.environ.get(k) for k in [
            "NOTEAI_FACT_SEARCH",
            "NOTEAI_FACT_SEARCH_PROVIDER",
            "NOTEAI_LOCAL_VERIFIED_FACTS_PATH",
            "NOTEAI_AUTHORIZED_FACTS_PATH",
            "AMAP_WEB_KEY",
            "BAIDU_MAP_AK",
            "TENCENT_MAP_KEY",
            "SERPAPI_API_KEY",
            "BING_SEARCH_API_KEY",
            "GOOGLE_API_KEY",
            "GOOGLE_CSE_ID",
        ]}
        original_loader = facts._load_authorized_fact_records
        original_cache = facts._LOCAL_FACT_CACHE
        try:
            os.environ["NOTEAI_FACT_SEARCH"] = "1"
            os.environ.pop("NOTEAI_FACT_SEARCH_PROVIDER", None)
            for key in ["AMAP_WEB_KEY", "BAIDU_MAP_AK", "TENCENT_MAP_KEY", "SERPAPI_API_KEY", "BING_SEARCH_API_KEY", "GOOGLE_API_KEY", "GOOGLE_CSE_ID"]:
                os.environ.pop(key, None)
            facts._LOCAL_FACT_CACHE = None
            facts._load_authorized_fact_records = lambda: [{
                "name": "珑厨万博店",
                "aliases": ["珑厨", "万博珑厨"],
                "domain": "美食",
                "city": "广州",
                "business_area": "番禺万博",
                "source": "用户素材/人工核验",
                "facts": {
                    "address": "南村镇汉溪大道东386号广晟万博城A座7层",
                    "deal": "双人套餐含芝士焗小青龙、乳鸽、忘不了鱼",
                    "must_order": ["芝士焗小青龙", "乳鸽"],
                    "review_keywords": ["聚餐", "小青龙", "粤菜"],
                },
            }]

            enriched = facts.enrich_content_facts("美食", "广州番禺珑厨", "店名：珑厨万博店 双人套餐")
            self.assertEqual(enriched["provider"], "local_verified")
            self.assertIn("芝士焗小青龙", enriched["facts"].get("must_order", ""))
            self.assertIn("双人套餐", enriched["facts"].get("deal", ""))
            ctx = facts.format_fact_context(enriched)
            self.assertIn("必点/招牌菜", ctx)
            self.assertIn("团购/套餐", ctx)
            self.assertIn("事实源：local_verified", ctx)
        finally:
            facts._load_authorized_fact_records = original_loader
            facts._LOCAL_FACT_CACHE = original_cache
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_local_verified_facts_require_shop_identity_match(self):
        record = {
            "name": "珑厨万博店",
            "aliases": ["珑厨", "万博珑厨"],
            "domain": "美食",
            "city": "广州",
            "business_area": "番禺万博",
            "facts": {
                "address": "南村镇汉溪大道东386号广晟万博城A座7层",
                "must_order": "芝士焗小青龙、乳鸽",
            },
        }
        self.assertGreater(facts._record_match_score(record, "广州番禺珑厨万博店 双人套餐", "美食"), 0)
        self.assertEqual(facts._record_match_score(record, "广州北京路点都德聚福楼 虾饺 红米肠", "美食"), 0)

    def test_fact_enrichment_redacts_provider_keys_from_errors(self):
        text = "403 for url https://restapi.amap.com/v3/place/text?key=secret-key&keywords=test&ak=secret-ak"
        redacted = facts._redact_secret_values(text)
        self.assertNotIn("secret-key", redacted)
        self.assertNotIn("secret-ak", redacted)
        self.assertIn("key=<redacted>", redacted)
        self.assertIn("ak=<redacted>", redacted)

    def test_meituan_token_alone_enables_ai_hub_but_not_service_retail_api(self):
        keys = [
            "MEITUAN_AI_HUB_TOKEN",
            "MEITUAN_OPEN_TOKEN",
            "MEITUAN_DEVELOPER_ID",
            "MEITUAN_SIGN_KEY",
            "MEITUAN_APP_AUTH_TOKEN",
            "MEITUAN_OPEN_APP_KEY",
            "MEITUAN_OPEN_APP_SECRET",
            "MEITUAN_OPEN_SIGN",
            "MEITUAN_OPEN_AES_KEY",
        ]
        old_env = {k: os.environ.get(k) for k in keys}
        try:
            for key in keys:
                os.environ.pop(key, None)
            os.environ["MEITUAN_OPEN_TOKEN"] = "token-test"
            status = facts.meituan_credentials_status()
            self.assertTrue(status["token_present"])
            self.assertTrue(status["ai_hub_ready"])
            self.assertTrue(status["travel_skill_ready"])
            self.assertFalse(status["service_retail_api_ready"])
            self.assertTrue(status["ready"])
            self.assertIn("MEITUAN_DEVELOPER_ID", status["missing_for_mt_tech"])
            self.assertIn("MEITUAN_SIGN_KEY", status["missing_for_mt_tech"])
            self.assertIn("MEITUAN_APP_AUTH_TOKEN", status["missing_for_mt_tech"])
            self.assertIn("MEITUAN_OPEN_APP_KEY", status["missing_for_oauth"])
            self.assertIn("MEITUAN_OPEN_SIGN", status["missing_for_enterprise"])
        finally:
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_fact_enrichment_does_not_cache_third_party_results_by_default(self):
        old_env = {k: os.environ.get(k) for k in [
            "NOTEAI_FACT_SEARCH",
            "NOTEAI_FACT_SEARCH_PROVIDER",
            "NOTEAI_FACT_SEARCH_CACHE_TTL",
            "AMAP_WEB_KEY",
        ]}
        original_search = facts._search
        facts._CACHE.clear()
        calls = {"count": 0}

        def fake_search(query, provider=None):
            calls["count"] += 1
            return "amap", [{
                "title": "珑厨万博店",
                "snippet": "地址：广州番禺区万博商圈。",
                "url": "amap://poi/test",
            }]

        try:
            os.environ["NOTEAI_FACT_SEARCH"] = "1"
            os.environ.pop("NOTEAI_FACT_SEARCH_PROVIDER", None)
            os.environ.pop("NOTEAI_FACT_SEARCH_CACHE_TTL", None)
            os.environ["AMAP_WEB_KEY"] = "amap-test"
            facts._search = fake_search

            first = facts.enrich_content_facts("美食", "广州番禺珑厨", "珑厨万博店")
            second = facts.enrich_content_facts("美食", "广州番禺珑厨", "珑厨万博店")

            self.assertEqual(calls["count"], 2)
            self.assertFalse(first.get("cached"))
            self.assertFalse(second.get("cached"))
        finally:
            facts._search = original_search
            facts._CACHE.clear()
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_generate_endpoint_blocks_quality_failed_result(self):
        original_check = api._billing.check_and_deduct
        original_get_sub = api._billing.get_subscription
        original_run = api._run_generation_agents

        async def fake_run(*args, **kwargs):
            return {
                "title": "广州番禺宝藏粤菜",
                "body": "人均188元，营业时间11:00-22:00。点赞收藏。",
                "variants": [],
                "ces_percentile": 43.4,
                "grade": "待改进",
                "feature_hits": {},
                "quality_issues": ["正文仍有占位符或待补信息，不能作为最终可交付内容"],
                "quality_failed": True,
                "expert_opinions": [],
                "image_desc": "",
            }

        try:
            api._billing.check_and_deduct = lambda user_id, op: None
            api._billing.get_subscription = lambda user_id: {"tier": "pro_plus"}
            api._run_generation_agents = fake_run

            async def run():
                return await api.generate(
                    api.GenerateInput(domain="美食", brief="广州番禺万博珑厨双人套餐"),
                    user={"id": "u1"},
                )

            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(run())
        finally:
            api._billing.check_and_deduct = original_check
            api._billing.get_subscription = original_get_sub
            api._run_generation_agents = original_run

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail["code"], "QUALITY_FAILED")

    def test_legacy_score_only_hard_blocks_below_sixty(self):
        issues = ["旧评分器低于历史参考线（当前51.0分，参考≥72分，仅作遥测）"]
        self.assertTrue(api._has_blocking_quality_issues(59.9, issues, "美食"))
        self.assertFalse(api._has_blocking_quality_issues(60.0, issues, "美食"))
        self.assertFalse(api._has_blocking_quality_issues(67.0, issues, "美食"))
        self.assertFalse(api._has_blocking_quality_issues(80.0, ["标题不自然：结尾像被硬截断，语义不完整"], "美食"))
        self.assertTrue(api._has_blocking_quality_issues(80.0, ["正文为空"], "美食"))
        low_score_issues = api._generated_quality_issues(
            "小个子显高公式",
            "白衬衫和高腰裤适合通勤，点赞收藏。#穿搭 #通勤穿搭 #小个子穿搭",
            "穿搭",
            59.5,
            {"body_len": 80, "tag_count": 3, "body_cta_count": 1},
        )
        self.assertTrue(any("评分低于硬拦线" in issue for issue in low_score_issues), low_score_issues)

    def test_plan_strategy_labels_are_domain_aware_not_food_only(self):
        self.assertEqual(api._plan_strategy_labels("美食"), ("决策信息型", "菜品种草型", "避坑决策型"))
        self.assertEqual(api._plan_strategy_labels("旅行"), ("决策信息型", "体验路线型", "避坑取舍型"))
        self.assertEqual(api._plan_strategy_labels("穿搭"), ("决策信息型", "搭配公式型", "避坑取舍型"))
        self.assertEqual(api._plan_strategy_labels("美妆"), ("决策信息型", "肤质反馈型", "避坑取舍型"))
        self.assertEqual(api._plan_strategy_labels("健身"), ("决策信息型", "动作计划型", "避坑取舍型"))

    def test_generation_planning_brief_is_domain_aware(self):
        food_source = "\n".join([
            "【联网事实补全】",
            "查询：万博 广州 番禺 长禧家.珑厨",
            "- 位置/地址：南村镇汉溪大道东386号广晟万博城A座7层",
            "- 价格/人均：人均98元",
            "- 营业时间：09:00-14:00 17:00-21:00",
            "- 必点/招牌菜：芝士焗小青龙、乳鸽",
        ])
        food = api._build_generation_planning_brief("美食", "广州番禺粤菜", food_source, "菜品种草型")
        travel_source = "\n".join([
            "【联网事实补全】",
            "- 已核验事实：事实源：美团酒旅 skill",
            "- 已核验事实：锦舍酒店(成都春熙路太古里店)：美团高档型，美团真实评分4.8，210元起/晚，落地窗，距太升南路地铁站步行约700米",
            "- 已核验事实：全季酒店(成都太古里中心店)：美团高档型，美团真实评分4.7，456元起/晚，太古里旁，距春熙路地铁站步行约600米",
        ])
        travel = api._build_generation_planning_brief("酒店", "成都太古里住宿", travel_source, "决策信息型")
        beauty = api._build_generation_planning_brief(
            "美妆",
            "干皮粉底液",
            "肤质：混干敏感皮\n产品：粉底液 色号：01\n用量：少量多次拍开",
            "肤质反馈型",
        )
        fashion = api._build_generation_planning_brief(
            "穿搭",
            "宽肩通勤穿搭",
            "身材：宽肩\n场合：通勤\n单品：V领针织衫、直筒西裤",
            "搭配公式型",
        )
        home = api._build_generation_planning_brief(
            "家居",
            "4平阳台改造",
            "空间：4平阳台\n预算：2600元\n清单：洞洞板、洗衣柜、折叠台面",
            "清单复刻型",
        )
        fitness = api._build_generation_planning_brief(
            "健身",
            "居家练臀",
            "动作：臀桥 深蹲 拉伸\n时长：18分钟\n人群：新手",
            "动作计划型",
        )
        baby = api._build_generation_planning_brief(
            "母婴",
            "6月龄睡前流程",
            "月龄：6个月\n用品：睡袋、绘本、夜灯\n观察：揉眼睛、发呆",
            "安全流程型",
        )

        self.assertIn("必点/招牌/推荐", food)
        self.assertIn("人均98元", food)
        self.assertIn("标题地点建议=广州番禺万博商圈", food)
        self.assertIn("商业价值槽位", food)
        self.assertIn("营业时间", food)
        self.assertIn("路线/交通/预算", travel)
        self.assertIn("写作模式=酒店/住宿对比", travel)
        self.assertIn("美团真实评分4.8", travel)
        self.assertIn("210元起/晚", travel)
        self.assertIn("地铁站步行约700米", travel)
        self.assertIn("酒店优先写美团评分", travel)
        self.assertNotIn("芝士焗小青龙", travel)
        self.assertIn("肤质/色号/妆效", beauty)
        self.assertIn("肤质/诉求=混干敏感皮", beauty)
        self.assertIn("产品/色号=粉底液 色号：01", beauty)
        self.assertIn("价格/渠道口径", beauty)
        self.assertIn("身材/场合=宽肩", fashion)
        self.assertIn("单品/版型=V领针织衫、直筒西裤", fashion)
        self.assertIn("价格或渠道口径", fashion)
        self.assertIn("空间/痛点=4平阳台", home)
        self.assertIn("尺寸/预算=2600元", home)
        self.assertIn("组数/次数/时长", fitness)
        self.assertIn("全部动作/拉伸", fitness)
        self.assertIn("动作/拉伸=臀桥 深蹲 拉伸", fitness)
        self.assertIn("组数/时长=18分钟", fitness)
        office_fitness = api._build_generation_planning_brief(
            "健身",
            "",
            "动作包括肩胛后缩30秒、靠墙天使8次、斜方肌轻拉30秒、胸小肌开肩30秒。适合久坐上班族办公室做。",
            "首稿",
        )
        self.assertIn("办公室肩颈放松", office_fitness)
        self.assertIn("肩颈放松/8分钟/办公室", office_fitness)
        self.assertIn("不要写坚持一周", office_fitness)
        glute_fitness = api._build_generation_planning_brief(
            "健身",
            "",
            "动作包括弹力带臀桥15次、蚌式开合12次、跪姿后踢腿12次、侧向走10步。重点是找到臀部发力感。",
            "首稿",
        )
        self.assertIn("弹力带臀腿塑形", glute_fitness)
        self.assertIn("弹力带/臀腿/发力感", glute_fitness)
        self.assertIn("月龄/场景=6个月", baby)
        self.assertIn("用品/环境=睡袋、绘本、夜灯", baby)

    def test_travel_safe_fact_brief_uses_meituan_hotel_facts(self):
        source = "\n".join([
            "- 已核验事实：事实源：美团酒旅 skill",
            "- 已核验事实：广州星河湾酒店：美团五星级，美团真实评分4.6，480元起/晚，免费穿梭巴士去长隆欢乐世界，早餐有现做米粉和车仔面",
            "- 已核验事实：丽呈花园酒店(广州野生动物世界店)：美团高档型，美团真实评分4.9，391元起/晚，花园欢乐亲子房，接送服务",
        ])
        brief = api._safe_fact_delivery_brief("酒旅", source)
        self.assertIn("旅行/酒旅事实安全策略", brief)
        self.assertIn("酒店/住宿对比", brief)
        self.assertIn("美团酒旅", brief)
        self.assertIn("480元起/晚", brief)
        self.assertIn("免费穿梭巴士", brief)
        self.assertIn("不要写Markdown粗体小标题", brief)
        self.assertIn("至少自然保留3项", brief)

    def test_travel_route_does_not_require_hotel_fact_density(self):
        source = (
            "成都3天2晚慢游路线，预算1200元，住春熙路附近，"
            "第一天人民公园和宽窄巷子，第二天熊猫基地和东郊记忆，第三天太古里。"
        )
        body = (
            "成都3天2晚适合慢慢逛，预算按1200元左右准备，住春熙路附近吃喝和地铁都方便。"
            "第一天人民公园和宽窄巷子，第二天熊猫基地和东郊记忆，第三天太古里，不用把行程排太满。"
            "路线先收藏，评论区问我行程细节。#成都旅行 #成都攻略 #3天2晚 #春熙路 #慢旅行 #城市漫游 #旅行路线 #周末去哪儿"
        )
        self.assertEqual(api._travel_hotel_fact_density_issues(body, source, "旅行"), [])

    def test_fashion_and_home_safe_fact_briefs_are_domain_specific(self):
        fashion = api._safe_fact_delivery_brief("穿搭", "身材：梨形\n单品：直筒西裤\n价格：199元")
        self.assertIn("穿搭事实与自然度策略", fashion)
        self.assertIn("价格按实际链接/门店为准", fashion)
        self.assertIn("160穿出165", fashion)

        home = api._safe_fact_delivery_brief("家居", "空间：4平阳台\n预算：2600元\n清单：洞洞板、洗衣柜")
        self.assertIn("家居复刻事实策略", home)
        self.assertIn("正文前120字", home)
        self.assertIn("预算按实际单品清单为准", home)

    def test_beauty_safe_fact_brief_forbids_unbacked_experience_claims(self):
        brief = api._safe_fact_delivery_brief(
            "美妆",
            "肤质/诉求：混干敏感皮\n产品：轻薄型防晒乳，SPF50 PA++++\n价格/渠道：89元\n用量/手法：两指量，分两次薄涂",
        )
        self.assertIn("美妆事实与肤质反馈策略", brief)
        self.assertIn("价格按购买渠道为准", brief)
        self.assertIn("不写用了多久", brief)
        self.assertIn("没泛红", brief)
        self.assertIn("8小时不补涂", brief)
        self.assertIn("两指量", brief)
        expression = api._quality_expression_brief("美妆")
        self.assertIn("唇妆/彩妆", expression)
        self.assertIn("防晒/底妆", expression)
        self.assertIn("元话术", expression)

    def test_travel_delivery_cleanup_removes_markdown_and_unsupported_value_claims(self):
        source = "\n".join([
            "- 已核验事实：三亚亚龙湾雅高铂尔曼别墅度假酒店：美团豪华型，美团真实评分4.5，666元起/晚，独栋别墅，部分房型私家泳池，中西式早餐，距离公共沙滩约200米",
        ])
        raw = (
            "**预算优先｜铂尔曼**\n"
            "亚龙湾亲子酒店里，这家最划算，提前2周预订能拿到更优惠房价，闭眼冲。\n"
            "#三亚旅游 #亚龙湾酒店"
        )
        shaped = api._insert_safe_fact_line(raw, "旅行", source)
        self.assertNotIn("**", shaped)
        self.assertNotIn("最划算", shaped)
        self.assertNotIn("闭眼冲", shaped)
        self.assertNotIn("提前2周预订能拿到更优惠房价", shaped)
        self.assertIn("预算更友好", shaped)
        self.assertIn("房价和优惠以平台实时页为准", shaped)
        self.assertIn("收藏", shaped)
        self.assertIn("评论区", shaped)

    def test_travel_single_hotel_delivery_promotes_meituan_facts(self):
        source = "\n".join([
            "- 已核验事实：事实源：美团酒旅 skill",
            "- 已核验事实：广州长隆酒店：美团豪华型，美团真实评分4.8，￥929起/晚",
            "- 已核验事实：地址：广州市番禺区汉溪大道东299号，位于长隆度假区核心位置",
            "- 已核验事实：交通/距离：紧邻长隆欢乐世界、水上乐园、野生动物世界，有免费穿梭巴士",
            "- 已核验事实：亲子设施/体验：儿童乐园、探趣亲子房、白虎自助餐厅、火烈鸟",
            "- 已核验事实：权益：住客可享提前半小时入园",
            "- 已核验事实：停车：酒店有免费停车场",
            "- 已核验事实：套餐/房型：部分房型或套餐可能包含乐园门票，具体以美团实时页为准",
        ])
        raw = (
            "如果预算允许，直接订这家就行，省去比较其他酒店的时间，一价全包的体验对家庭出游最省心。"
            "广州长隆酒店美团评分4.8分，起价￥929起/晚，位于长隆度假区核心位置，有免费穿梭巴士。"
            "美团评分4.8、929元起/晚的长隆酒店，有免费穿梭巴士，住客还能提前半小时入园。"
            "这家是首选，能避开高峰期排队，让孩子多玩2-3小时，也不用担心小孩挑食。"
            "如果计划玩2-3天，能省掉每天往返的时间和车费，也能直接省掉门票钱。"
            "选这家能多睡一会儿还能提前进园，性价比确实在线。"
            "住客能提前半小时入园，相当于多了半天游玩时间，有时能省掉一笔门票费。值得收藏。"
            "适合3-12岁的孩子，预算在900-1200元/晚，旺季房间紧张，建议提前2-3周预订。"
            "如果想早上多玩一会儿再退房，可以提前咨询前台是否支持延迟退房。"
            "有时能省不少门票钱，早上人少的时候先玩热门项目，套餐组合经常调整，问酒店能否延迟。"
            "如果想降低预算，可以看美团上有没有近期活动房型，或者选择淡季时段。"
            "酒店就在园区旁边，有班车，也有亲子设施。"
            "#广州长隆 #亲子酒店"
        )
        shaped = api._insert_safe_fact_line(raw, "旅行", source)
        self.assertIn("广州长隆酒店美团评分4.8、929元起/晚", shaped[:100])
        self.assertIn("免费穿梭巴士", shaped[:180])
        self.assertIn("提前半小时入园", shaped[:220])
        self.assertEqual(shaped.count("美团评分4.8"), 1)
        self.assertEqual(shaped.count("929元起/晚"), 1)
        self.assertNotIn("￥929", shaped)
        self.assertNotIn("直接订这家就行", shaped)
        self.assertNotIn("一价全包", shaped)
        self.assertNotIn("淡季时段", shaped)
        self.assertNotIn("首选", shaped)
        self.assertNotIn("多玩2-3小时", shaped)
        self.assertNotIn("不用担心小孩挑食", shaped)
        self.assertNotIn("计划玩2-3天", shaped)
        self.assertNotIn("车费", shaped)
        self.assertNotIn("省掉门票钱", shaped)
        self.assertNotIn("省掉一笔门票费", shaped)
        self.assertNotIn("多睡一会儿", shaped)
        self.assertNotIn("多了半天游玩时间", shaped)
        self.assertNotIn("性价比确实在线", shaped)
        self.assertNotIn("3-12岁", shaped)
        self.assertNotIn("900-1200元", shaped)
        self.assertNotIn("旺季房间紧张", shaped)
        self.assertNotIn("提前2-3周", shaped)
        self.assertNotIn("延迟退房", shaped)
        self.assertNotIn("省不少门票钱", shaped)
        self.assertNotIn("热门项目", shaped)
        self.assertNotIn("套餐组合经常调整", shaped)
        self.assertNotIn("能否延迟", shaped)
        self.assertFalse(api._structured_fact_boundary_issues(shaped, source, "旅行"))
        self.assertFalse(api._delivery_integrity_issues(shaped, source, "旅行"))

    def test_unsupported_structured_claims_are_cleaned_before_delivery(self):
        travel_source = "- 已核验事实：酒店位于北京国贸商圈，商务大床房一晚约720元，步行到地铁站约5分钟"
        travel = api._insert_safe_fact_line(
            "这家不是五星酒店那个水平，春节房间紧张，现场买票常排队1小时以上。\n#北京住宿",
            "旅行",
            travel_source,
        )
        self.assertNotIn("五星", travel)
        self.assertNotIn("春节", travel)
        self.assertNotIn("1小时", travel)
        self.assertFalse(api._structured_fact_boundary_issues(travel, travel_source, "旅行"))

        food_source = "- 已核验事实：地点在广州越秀公园附近，人均88元，营业时间07:30-14:30，周末9点前到店排队更少"
        food = api._insert_safe_fact_line(
            "我们一家四口周末9点20分到店，只等了不到15分钟，虾饺是招牌。\n#广州早茶",
            "美食",
            food_source,
        )
        self.assertNotIn("一家四口", food)
        self.assertNotIn("15分钟", food)
        self.assertFalse(api._structured_fact_boundary_issues(food, food_source, "美食"))
        weekday_text = "周一到周五人会少一些，适合错峰早茶。"
        self.assertFalse(api._structured_fact_boundary_issues(weekday_text, food_source, "美食"))

    def test_beauty_delivery_cleanup_removes_unbacked_experience_claims(self):
        source = "\n".join([
            "- 已核验事实：肤质/诉求：混干敏感皮，通勤防晒，怕拔干、搓泥和闷痘",
            "- 已核验事实：产品：轻薄型防晒乳，SPF50 PA++++",
            "- 已核验事实：价格/渠道：89元，价格按购买渠道为准",
            "- 已核验事实：用量/手法：早上两指量，分两次薄涂，成膜后再上粉底",
            "- 已核验事实：妆效/边界：成膜后不泛白，后续底妆更服帖；不适合追求强润色或替代底妆的人",
        ])
        cleaned = api._insert_safe_fact_line(
            "混干敏感皮选防晒最怕拔干、搓泥、闷痘。我用了半年轻薄型防晒乳（SPF50 PA++++，89元），真的不搓泥。"
            "敏感肌那阵子更没泛红过，能坚持到下班、中午不用补妆。两指量分两次薄涂，成膜需要2-3分钟，成膜后不泛白，后续底妆更服帖，用量省的话能用2-3个月。点赞收藏。"
            "#混干敏感皮 #防晒乳 #通勤防晒 #不搓泥 #SPF50",
            "美妆",
            source,
        )
        self.assertNotIn("用了半年", cleaned)
        self.assertNotIn("没泛红", cleaned)
        self.assertNotIn("中午不用补妆", cleaned)
        self.assertNotIn("坚持到下班", cleaned)
        self.assertNotIn("真的不搓泥", cleaned)
        self.assertNotIn("2-3分钟", cleaned)
        self.assertNotIn("能用2-3个月", cleaned)
        self.assertNotIn("十来秒", api._insert_safe_fact_line("等个十来秒再涂第二遍。点赞收藏。#防晒 #美妆 #通勤妆 #敏感肌 #成膜", "美妆", source))
        self.assertIn("SPF50", cleaned)
        self.assertIn("89元", cleaned)
        self.assertIn("两指量", cleaned)
        self.assertIn("成膜后不泛白", cleaned)
        self.assertIn("局部试用", cleaned)
        self.assertIn("按防晒说明补涂", cleaned)
        self.assertFalse(api._structured_fact_boundary_issues(cleaned, source, "美妆"), cleaned)

    def test_beauty_boundary_flags_unbacked_claims_before_cleanup(self):
        issues = api._structured_fact_boundary_issues(
            "这支防晒我用了快一个月，敏感期没泛红，8小时不补涂也很稳。",
            "产品：清爽型防晒乳\n肤质：混干敏感皮\n用量：两指量",
            "美妆",
        )
        self.assertTrue(any("试用/功效边界" in item for item in issues), issues)

    def test_beauty_delivery_cleanup_preserves_sourced_duration_claims(self):
        source = "肤质：混干皮\n产品：奶杏玫瑰色腮红\n价格：79元\n持妆约6小时\n用法：苹果肌到太阳穴斜扫"
        cleaned = api._insert_safe_fact_line(
            "混干皮用这支奶杏玫瑰色腮红，79元，持妆约6小时。用法是从苹果肌到太阳穴斜扫。有用先收藏。#腮红 #混干皮 #通勤妆 #美妆",
            "美妆",
            source,
        )
        self.assertIn("持妆约6小时", cleaned)
        self.assertFalse(api._structured_fact_boundary_issues(cleaned, source, "美妆"), cleaned)

    def test_beauty_delivery_adds_safe_price_channel_when_missing(self):
        cleaned = api._insert_safe_fact_line(
            "油皮夏天底妆先薄涂控油乳，粉底液少量多次用湿海绵拍开，出油后纸巾按压再补散粉。有用先收藏。#油皮底妆 #夏季持妆 #粉底液 #控油 #散粉",
            "美妆",
            "肤质是夏季油皮\n粉底液少量多次，用湿海绵拍开\n出油后用纸巾按压再补散粉",
        )
        self.assertIn("价格按购买渠道为准", cleaned)
        self.assertFalse(api._structured_fact_boundary_issues(cleaned, "", "美妆"), cleaned)

    def test_beauty_delivery_cleanup_keeps_duration_claims_specific(self):
        source = "\n".join([
            "- 已核验事实：肤质是夏季油皮，T区容易出油",
            "- 已核验事实：粉底液少量多次，用湿海绵拍开",
            "- 已核验事实：带妆6小时后T区会出油但不明显斑驳",
            "- 已核验事实：出油后用纸巾按压再补散粉",
        ])
        cleaned = api._insert_safe_fact_line(
            "我的做法是少量多次，通勤一整天妆面都还能hold住。"
            "妆前准备很关键T区先薄涂控油乳。"
            "粉底液少量多次是重点不要一次性按压太多粉底液。"
            "容易出油的位置要特殊对待鼻翼和下巴薄上一层散粉。"
            "有用先收藏。#油皮底妆 #夏季持妆 #粉底液 #控油 #散粉",
            "美妆",
            source,
        )
        self.assertNotIn("一整天", cleaned)
        self.assertNotIn("hold住", cleaned)
        self.assertIn("带妆6小时后T区会出油但不明显斑驳", cleaned)
        self.assertIn("妆前准备很关键。T区", cleaned)
        self.assertIn("粉底液少量多次是重点。不要", cleaned)
        self.assertIn("容易出油的位置要特殊对待。鼻翼", cleaned)
        self.assertFalse(api._structured_fact_boundary_issues(cleaned, source, "美妆"), cleaned)

    def test_baby_delivery_cleanup_removes_unsupported_result_experience(self):
        source = (
            "- 已核验事实：宝宝月龄是6个月\n"
            "- 已核验事实：睡前流程包括洗澡、抚触、换睡袋、关主灯、读短绘本\n"
            "- 已核验事实：观察困信号包括揉眼睛、发呆、打哈欠\n"
            "- 已核验事实：不承诺睡整觉"
        )
        cleaned = api._insert_safe_fact_line(
            "6月龄睡前流程我坚持了两个多月，宝宝身体开始有预期感，宝宝睡得更踏实。"
            "洗澡、抚触、换睡袋、关主灯、读短绘本，揉眼睛就开始。点赞收藏。"
            "#6月龄睡眠 #宝宝睡前流程 #新手父母 #婴儿护理 #育儿经验",
            "母婴",
            source,
        )
        self.assertNotIn("两个多月", cleaned)
        self.assertNotIn("睡得更踏实", cleaned)
        self.assertIn("困信号", cleaned)
        self.assertIn("接受度", cleaned)

    def test_baby_delivery_cleanup_removes_unsupported_env_numbers(self):
        source = (
            "- 已核验事实：宝宝月龄是6个月\n"
            "- 已核验事实：睡前流程包括洗澡、抚触、换睡袋、关主灯、读短绘本\n"
            "- 已核验事实：观察困信号包括揉眼睛、发呆、打哈欠"
        )
        cleaned = api._insert_safe_fact_line(
            "6月龄睡前流程从洗澡开始，水温37-38℃，室温22-24℃，湿度50-60%，"
            "再抚触、换睡袋、关主灯、读短绘本，揉眼睛就开始。点赞收藏。"
            "#6月龄睡眠 #宝宝睡前流程 #新手父母 #婴儿护理 #育儿经验",
            "母婴",
            source,
        )
        self.assertNotIn("37-38", cleaned)
        self.assertNotIn("22-24", cleaned)
        self.assertNotIn("50-60", cleaned)
        self.assertIn("洗澡水温按日常安全习惯控制", cleaned)
        self.assertIn("环境保持舒适", cleaned)
        self.assertIn("湿度按家庭环境调整", cleaned)

    def test_baby_delivery_cleanup_removes_unsupported_future_results_and_feeding_counts(self):
        source = (
            "- 已核验事实：宝宝月龄是6个月\n"
            "- 已核验事实：睡前流程包括洗澡、抚触、换睡袋、关主灯、读短绘本\n"
            "- 已核验事实：不承诺睡整觉"
        )
        cleaned = api._insert_safe_fact_line(
            "6月龄睡前流程比各种哄睡技巧更有效，坚持一周以上能看出效果，"
            "夜间可能还要吃1-2次奶，适合没有肠绞痛的宝宝。点赞收藏。"
            "#6月龄睡眠 #宝宝睡前流程 #新手父母 #婴儿护理 #育儿经验",
            "母婴",
            source,
        )
        self.assertNotIn("更有效", cleaned)
        self.assertNotIn("一周以上能看出效果", cleaned)
        self.assertNotIn("1-2次奶", cleaned)
        self.assertNotIn("肠绞痛", cleaned)
        self.assertIn("更容易执行", cleaned)
        self.assertIn("立竿见影", cleaned)

    def test_baby_delivery_cleanup_removes_unsupported_development_conditions(self):
        source = (
            "- 已核验事实：宝宝月龄是6个月\n"
            "- 已核验事实：睡前流程包括洗澡、抚触、换睡袋、关主灯、读短绘本\n"
            "- 已核验事实：观察困信号包括揉眼睛、发呆、打哈欠"
        )
        cleaned = api._insert_safe_fact_line(
            "6月龄睡前流程包括洗澡、抚触、换睡袋、关主灯、读短绘本。"
            "这个流程适合已经能坐起来、对绘本有兴趣的6月龄宝宝。点赞收藏。"
            "#6月龄睡眠 #睡前流程 #新手父母 #婴儿护理 #育儿经验",
            "母婴",
            source,
        )
        self.assertNotIn("已经能坐起来", cleaned)
        self.assertNotIn("对绘本有兴趣", cleaned)
        self.assertIn("家长想减少睡前拉扯", cleaned)

    def test_baby_delivery_cleanup_formats_flow_into_three_paragraphs(self):
        source = (
            "- 已核验事实：宝宝月龄是6个月\n"
            "- 已核验事实：睡前流程包括洗澡、抚触、换睡袋、关主灯、读短绘本\n"
            "- 已核验事实：观察困信号包括揉眼睛、发呆、打哈欠\n"
            "- 已核验事实：宝宝明显哭闹时先停下来安抚"
        )
        cleaned = api._insert_safe_fact_line(
            "6月龄睡前流程我不建议弄得太满。洗澡、抚触、换睡袋、关主灯、读短绘本，控制在25分钟内就够了。"
            "困信号很关键，别等宝宝哭闹才反应。揉眼睛、发呆、打哈欠这几个信号出现，说明困意来了。"
            "如果中途宝宝明显哭闹，先停下来安抚一会儿，不要硬推进。"
            "这个流程适合已经有基础作息、能区分白天和夜晚的6月龄宝宝。"
            "有用先收藏，评论区聊聊你的情况。"
            "#6月龄睡眠 #睡前流程 #困信号识别 #新手父母 #育儿经验",
            "母婴",
            source,
        )
        self.assertGreaterEqual(api._substantive_paragraph_count(cleaned), 3)
        self.assertNotIn("基础作息", cleaned)
        self.assertNotIn("白天和夜晚", cleaned)

    def test_baby_delivery_cleanup_formats_natural_signal_phrases(self):
        source = (
            "- 已核验事实：宝宝月龄是6个月\n"
            "- 已核验事实：睡前流程包括洗澡、抚触、换睡袋、关主灯、读短绘本\n"
            "- 已核验事实：观察困信号包括揉眼睛、发呆、打哈欠"
        )
        cleaned = api._insert_safe_fact_line(
            "6月龄睡前流程我不建议弄得太满。洗澡、抚触、换睡袋、关主灯、读短绘本，控制在25分钟内就够了。"
            "看困信号比看时间更重要。揉眼睛、发呆、打哈欠这些都是信号，出现了就说明该睡了。"
            "适合已经有一定作息基础的6月龄宝宝家长。如果宝宝还在频繁夜醒或白天睡眠混乱，先稳定白天作息再考虑睡前流程。"
            "有用先收藏，评论区聊聊你的情况。"
            "#6月龄睡眠 #睡前流程 #新手父母 #育儿经验 #睡眠规律",
            "母婴",
            source,
        )
        self.assertGreaterEqual(api._substantive_paragraph_count(cleaned), 3)
        self.assertNotIn("一定作息基础", cleaned)
        issues = api._generated_quality_issues("6月龄睡前流程推荐，25分钟就够", cleaned, "母婴", 72.0, {
            "tag_count": 5,
            "body_cta_count": 2,
            "commercial_body_sentence_count": 8,
            "commercial_body_avg_sentence_len": 36,
        })
        self.assertFalse(any("3段安全流程卡" in item for item in issues), issues)

    def test_baby_generation_quality_flags_missing_three_substantive_paragraphs(self):
        body = (
            "6月龄睡前流程我更建议简化。洗澡、抚触、换睡袋、关主灯、读短绘本，5步控制在25分钟内。"
            "揉眼睛、发呆、打哈欠出现时就开始流程，哭闹时先停下来轻声安抚，不要硬继续。"
            "卧室保持暗光，白噪音音量放低，目的是减少突然声音干扰，不是把房间填满。"
            "如果宝宝中途烦躁，先暂停流程轻声安抚，等他平复再继续，不要为了完成步骤硬推进。"
            "这个流程更适合家长想减少睡前拉扯、先固定顺序的6月龄宝宝，重点是每天用同一套信号帮助宝宝识别睡前节奏。\n\n"
            "有用先收藏，评论区聊聊你的情况。\n"
            "#6月龄睡眠 #睡前流程 #困信号观察 #新手父母 #婴儿护理"
        )
        features = {
            "tag_count": 5,
            "body_cta_count": 2,
            "commercial_body_sentence_count": 8,
            "commercial_body_avg_sentence_len": 36,
        }
        issues = api._generated_quality_issues("6月龄睡前流程推荐", body, "母婴", 72.0, features)
        self.assertTrue(any("3段安全流程卡" in item for item in issues), issues)
        self.assertFalse(api._has_blocking_quality_issues(72.0, issues, "母婴"), issues)

    def test_fitness_delivery_cleanup_removes_unsupported_personal_feedback(self):
        cleaned = api._insert_safe_fact_line(
            "18分钟膝盖友好减脂，我自己试过，膝盖不适的朋友也能跟上。"
            "第一轮做坐姿抬腿30秒，第二轮臀桥12次，第三轮靠墙半蹲20秒。点赞收藏。"
            "#居家健身 #减脂 #膝盖友好 #新手健身 #低冲击训练",
            "健身",
            "膝盖友好、低冲击、18分钟、坐姿抬腿、臀桥、靠墙半蹲。",
        )
        self.assertNotIn("我自己试过", cleaned)
        self.assertNotIn("朋友也能跟上", cleaned)
        self.assertIn("低冲击版本", cleaned)

    def test_fitness_delivery_cleanup_removes_unsupported_result_promises(self):
        source = (
            "训练目标是新手居家减脂，目标效果是减脂塑形。每次训练约18分钟。"
            "动作包括原地踏步60秒、臀桥15次、死虫12次、靠墙静蹲30秒。"
            "四个动作做3轮，每轮之间休息60秒，结束后拉伸小腿和臀腿。"
        )
        self.assertFalse(api._fitness_source_allows_result_claims(source))
        self.assertTrue(api._fitness_source_allows_result_claims("连续打卡第2周，动作变轻松，围度有变化。"))
        cleaned = api._insert_safe_fact_line(
            "18分钟低冲击训练，每周3-4次就能感受身体变化。"
            "原地踏步60秒、臀桥15次、死虫12次、靠墙静蹲30秒做3轮。"
            "坚持2周你就会发现动作变轻松了，靠墙半蹲也有效果。"
            "新手第一周可能会酸，这是正常的恢复反应。"
            "训练后拉伸能缓解肌肉紧张、减少第二天酸痛。"
            "想跟练先收藏，评论区说你的目标。"
            "#膝盖友好 #居家减脂 #低冲击训练 #新手健身 #18分钟训练",
            "健身",
            source,
        )
        self.assertNotIn("每周3-4次就能感受身体变化", cleaned)
        self.assertNotIn("坚持2周你就会发现", cleaned)
        self.assertNotIn("也有效果", cleaned)
        self.assertNotIn("第一周可能会酸", cleaned)
        self.assertNotIn("减少第二天酸痛", cleaned)
        self.assertIn("按体力", cleaned)

    def test_fitness_delivery_cleanup_removes_probe_result_and_medical_claims(self):
        source = (
            "适合久坐上班族午休或下班前做。总时长约8分钟。"
            "动作包括肩胛后缩30秒、靠墙天使8次、斜方肌轻拉30秒、胸小肌开肩30秒。"
            "每个动作做2轮，动作过程中不追求疼痛感，如果出现麻木或刺痛应停止。"
        )
        cleaned = api._insert_safe_fact_line(
            "办公室用一面墙和一把椅子就能完成这套8分钟肩颈放松，"
            "特别适合没有颈椎病变、只是单纯肌肉疲劳的上班族缓解久坐僵硬。"
            "肩胛后缩30秒、靠墙天使8次、斜方肌轻拉30秒、胸小肌开肩30秒，每个动作做2轮。"
            "整个过程不追求疼痛感，如果出现麻木或刺痛就停止，说明可能压到神经。"
            "坚持一周你会发现下午肩颈酸痛感明显缓解。"
            "想跟练先收藏，评论区说你的目标。"
            "#办公室健身 #肩颈放松 #上班族运动 #久坐放松 #低门槛训练",
            "健身",
            source,
        )
        self.assertNotIn("颈椎病变", cleaned)
        self.assertNotIn("可能压到神经", cleaned)
        self.assertNotIn("坚持一周", cleaned)
        self.assertNotIn("明显缓解", cleaned)
        self.assertIn("麻木或刺痛", cleaned)
        self.assertIn("停止", cleaned)
        self.assertNotIn("说明说明", cleaned)
        self.assertFalse(api._delivery_integrity_issues(cleaned, source, "健身"), cleaned)

    def test_fitness_delivery_cleanup_appends_missing_source_stretch(self):
        source = (
            "动作包括原地踏步60秒、臀桥15次、死虫12次、靠墙静蹲30秒。"
            "训练前热身5分钟，结束后拉伸小腿和臀腿。"
        )
        cleaned = api._insert_safe_fact_line(
            "18分钟低冲击训练，先热身5分钟，再做原地踏步、臀桥、死虫、靠墙静蹲。"
            "想跟练先收藏，评论区说你的目标。"
            "#膝盖友好 #居家减脂 #低冲击训练 #新手健身 #18分钟训练",
            "健身",
            source,
        )
        self.assertIn("拉伸小腿和臀腿", cleaned)
        self.assertFalse(api._delivery_integrity_issues(cleaned, source, "健身"), cleaned)

    def test_fitness_delivery_integrity_requires_source_actions(self):
        source = "动作包括原地踏步60秒、臀桥15次、死虫12次、靠墙静蹲30秒。"
        body = "18分钟低冲击训练包括原地踏步、臀桥和死虫，膝盖不舒服就减少强度。想跟练先收藏。"
        issues = api._delivery_integrity_issues(body, source, "健身")
        self.assertTrue(any("靠墙静蹲" in item for item in issues), issues)
        self.assertFalse(api._has_blocking_quality_issues(75.0, issues, "健身"))

    def test_baby_safe_fact_delivery_brief_forbids_new_result_experience(self):
        brief = api._safe_fact_delivery_brief("母婴", "- 已核验事实：宝宝月龄是6个月")
        self.assertIn("流程卡+观察清单", brief)
        self.assertIn("不得新增未提供的具体经历", brief)
        self.assertIn("已经能坐", brief)
        self.assertIn("坚持两个月", brief)
        self.assertIn("水温37-38℃", brief)

    def test_domain_expression_briefs_cover_weak_strategy_domains(self):
        self.assertIn("安全流程卡", api._quality_expression_brief("母婴"))
        self.assertIn("260-320字", api._quality_expression_brief("母婴"))
        self.assertIn("3段自然正文", api._quality_expression_brief("母婴"))
        self.assertIn("发育或兴趣条件", api._quality_expression_brief("母婴"))
        self.assertIn("温湿度/水温数字", api._quality_expression_brief("母婴"))
        self.assertIn("可跟练计划", api._quality_expression_brief("健身"))
        self.assertIn("不能漏最后一个动作", api._quality_expression_brief("健身"))
        self.assertIn("我自己试过", api._quality_expression_brief("健身"))
        self.assertIn("身材场景搭配公式", api._quality_expression_brief("穿搭"))
        self.assertIn("160穿出165", api._quality_expression_brief("穿搭"))
        self.assertIn("起价/预算", api._quality_expression_brief("旅行"))
        self.assertIn("正文前120字", api._quality_expression_brief("家居"))

    def test_fashion_overpromise_is_repaired_and_flagged(self):
        bad_title = "梨形遮胯公式推荐，160穿出165腿"
        title_issues = api._title_readability_issues(bad_title, "穿搭")
        self.assertTrue(any("夸大身材变化" in issue for issue in title_issues), title_issues)
        repaired_title = api._sanitize_title_for_delivery(bad_title, "", "穿搭")
        self.assertEqual(repaired_title, "梨形通勤遮胯显高公式")
        self.assertLessEqual(len(repaired_title), api._TITLE_DELIVERY_MAX)
        self.assertFalse(api._title_readability_issues(repaired_title, "穿搭"))

        raw_body = (
            "160cm穿完直接有165的既视感，视觉像是凭空多出来五厘米，"
            "同事都说我瘦了。价格按实际链接为准。点赞收藏。#梨形穿搭 #通勤穿搭"
        )
        shaped = api._insert_safe_fact_line(raw_body, "穿搭", "身材：160cm梨形\n单品：直筒西裤")
        self.assertNotIn("165", shaped)
        self.assertNotIn("多出来五厘米", shaped)
        self.assertNotIn("同事都说我瘦了", shaped)
        self.assertIn("比例", shaped)

    def test_travel_markdown_cleanup_preserves_xiaohongshu_hashtags(self):
        raw = "# 方案一\n亚龙湾酒店按预算和沙滩距离选。\n#三亚旅游 #亚龙湾酒店"
        cleaned = api._clean_markdown_delivery_artifacts(raw)
        self.assertNotIn("# 方案一", cleaned)
        self.assertIn("#三亚旅游 #亚龙湾酒店", cleaned)
        issues = api._human_readability_issues("亚龙湾酒店按预算和沙滩距离选。\n#三亚旅游 #亚龙湾酒店", "旅行")
        self.assertFalse(any("Markdown" in issue for issue in issues), issues)

    def test_travel_and_home_density_issues_are_soft_repair_signals(self):
        travel_source = "\n".join([
            "- 已核验事实：事实源：美团酒旅 skill",
            "- 已核验事实：广州星河湾酒店：美团五星级，美团真实评分4.6，480元起/晚，免费穿梭巴士去长隆欢乐世界，早餐有现做米粉",
        ])
        weak_travel = "这家亲子酒店适合去长隆，整体比较省心，适合带娃。点赞收藏。#广州旅行 #亲子酒店"
        strong_travel = "广州星河湾酒店480元起/晚，美团真实评分4.6，免费穿梭巴士去长隆，早餐有现做米粉，适合优先省交通的亲子家庭。点赞收藏。#广州旅行 #亲子酒店"
        weak_issues = api._delivery_integrity_issues(weak_travel, travel_source, "旅行")
        self.assertTrue(any("事实密度不足" in issue for issue in weak_issues), weak_issues)
        self.assertFalse(api._has_blocking_quality_issues(70.0, weak_issues, "旅行"))
        self.assertFalse(api._delivery_integrity_issues(strong_travel, travel_source, "旅行"))

        home_source = "空间：4平阳台\n预算：2600元\n清单：洞洞板、洗衣柜、折叠台面\n痛点：洗衣区杂乱、拿取不顺"
        weak_home = "4平阳台改造后好看很多，整体更干净，适合小户型参考。点赞收藏。#阳台改造 #小户型"
        strong_home = "4平阳台2600元改完，洗衣区从杂乱变顺手，洞洞板收纳清洁工具，洗衣柜藏杂物，折叠台面让晾晒动线更顺，复刻前先量尺寸。点赞收藏。#阳台改造 #小户型"
        home_issues = api._delivery_integrity_issues(weak_home, home_source, "家居")
        self.assertTrue(any("复刻信息不足" in issue for issue in home_issues), home_issues)
        self.assertFalse(api._has_blocking_quality_issues(70.0, home_issues, "家居"))
        self.assertFalse(api._delivery_integrity_issues(strong_home, home_source, "家居"))

    def test_travel_route_time_windows_are_not_business_hours(self):
        route_text = "DAY 1 上午09:00-12:00走断桥和白堤，下午14:00-16:30去灵隐寺。"
        issues = api._structured_fact_boundary_issues(route_text, "", "旅行")
        self.assertFalse(any("营业时间" in issue for issue in issues), issues)

        natural_route_text = "关键是住在湖滨，路线顺序对了，不用每天奔波。DAY 1 从断桥开始慢走。"
        natural_issues = api._structured_fact_boundary_issues(natural_route_text, "", "旅行")
        self.assertFalse(any("营业时间" in issue for issue in natural_issues), natural_issues)

        business_text = "灵隐寺营业时间09:00-17:00，下午再去河坊街。"
        business_issues = api._structured_fact_boundary_issues(business_text, "", "旅行")
        self.assertTrue(any("营业时间" in issue for issue in business_issues), business_issues)

    def test_recommendation_terms_are_allowed_not_polished_away(self):
        text = "这家是第一选择，芝士焗小青龙值得冲，招牌菜必点也推荐。"
        self.assertEqual(api._polish_low_quality_phrases(text), text)
        self.assertEqual(api._human_readability_issues(text, "美食"), [])

    def test_low_quality_phrase_polish_keeps_physical_ceiling_descriptions(self):
        text = "死虫动作仰卧，双臂伸向天花板，保持腰背贴地。"
        self.assertEqual(api._polish_low_quality_phrases(text), text)
        self.assertNotIn("代表性很强", api._polish_low_quality_phrases(text))
        self.assertEqual(api._human_readability_issues(text, "健身"), [])

    def test_title_readability_blocks_score_hacking_titles(self):
        bad = "广州番禺万博98元值得点"
        good = "广州番禺98元小青龙，聚餐点单不踩雷"
        natural_price_title = "北京路早茶点都德，人均86元很稳"
        chopped = "南京西路蟹黄拌面58元，周末必排队的"
        dangling = "8月龄宝宝辅食顺序｜从泥糊到软颗粒安"
        fitness_dangling = "弹力带臀腿新手这样练，找对发力感最关"
        travel_dangling = "广州亲子酒店住珠江新城挺省心，地铁8"
        home_dangling = "4平阳台洗衣区2600元改造，收纳动"
        food_dangling = "南京西路蟹黄面午餐稳，工作日11:3"
        hotel_dangling = "三亚亲子酒店选亚龙湾，亲子房1"
        food_digit_tail = "西湖湖滨早午餐｜班尼迪克蛋必点，10"
        hotel_action_tail = "三亚亲子酒店选亚龙湾更省心，低龄娃泡"
        food_queue_tail = "南京西路蟹黄面午餐稳，11点半前来排"
        hotel_transport_tail = "成都第一次来住太古里附近，吃喝地铁"
        food_price_digit_tail = "广州西关陶陶居，百年老字号早茶人均1"
        food_price_label_tail = "广州西关陶陶居｜百年老字号早茶，人均"
        food_price_colon_tail = "广州西关陶陶居：百年老字号早茶，人均"
        food_amap_bad_tail = "广州番禺万博粤菜，招牌芝士焗虾人均9"
        food_dish_tail = "广州西关陶陶居，百年老字号早茶必点虾"
        food_brand_tail = "成都春熙路火锅第一次怎么点｜蜀大侠人"
        food_action_tail = "成都春熙路蜀大侠，第一次吃川火的点单"
        food_action_tail_v2 = "成都春熙路蜀大侠，第一次吃川火锅这样"
        food_not_tail = "春熙路蜀大侠火锅：第一次来这样点才不"
        food_city_not_tail = "成都春熙路蜀大侠，第一次来怎么点才不"
        food_not_question_tail = "春熙路蜀大侠火锅，第一次来怎么点才不"
        food_not_step_tail = "春熙路蜀大侠火锅，第一次来这样点不踩"
        food_point_not_tail = "春熙路蜀大侠火锅，人均89元这样点不"
        food_steady_tail = "广州北京路早茶，点都德人均86稳得"
        food_price_no_unit_tail = "番禺万博粤菜聚餐，长禧家珑厨人均98"
        food_wrong_tail = "番禺万博粤菜聚餐，人均98这家4.5"
        food_amap_dish_tail = "番禺万博粤菜聚餐，芝士焗小青龙招牌必"
        food_diandoude_tail = "北京路早茶点都德，人均86元必点金牌"
        food_diandoude_steady_tail = "北京路逛街必吃，点都德早茶人均86稳"
        food_diandoude_morning_tail = "北京路点都德虾饺必点，人均86广式早"
        food_shudaxia_tail = "成都春熙路火锅第一次怎么点｜蜀大侠必"
        food_spicy_beef_tail = "成都春熙路蜀大侠人均89元巴蜀麻辣牛"
        food_taotaoju_tail = "广州陶陶居西关，百年老字号早茶必点这"
        food_taotaoju_shrimp_tail = "广州西关陶陶居早茶，百年招牌虾饺皇必"
        food_shudaxia_step_tail = "成都春熙路火锅第一次点单，这样不会踩"
        food_shudaxia_avoid_tail = "成都春熙路火锅避坑指南，这样点不会"
        food_shudaxia_order_tail = "春熙路蜀大侠，第一次来必点这样吃"
        food_longxi_price_order_tail = "番禺万博粤菜聚餐，这家98元人均很稳"
        beauty_dangling = "混干敏感皮防晒｜两指量少量多次才不搓"
        beauty_dangling_v2 = "混干敏感皮通勤防晒，两指量分次涂不搓"
        beauty_dangling_v3 = "敏感混干皮通勤防晒，涂了不搓泥还能上"
        beauty_dangling_v4 = "油皮夏天底妆少量多次不厚涂，6小时不"
        beauty_dangling_v5 = "黄黑皮通勤口红，玫瑰棕薄涂不显肤69"
        beauty_dangling_v6 = "敏感混干皮通勤防晒，涂完直接上粉底不"
        beauty_dangling_v7 = "油皮夏天底妆少量多次才稳妥，6小时不"
        beauty_dangling_v8 = "黄黑皮口红，薄涂素颜很稳，69元玫瑰"
        beauty_unbacked_title = "黄黑皮通勤口红，这支玫瑰棕我能涂一年"
        beauty_price_title = "敏感混干皮防晒，上粉底不搓泥很稳"
        beauty_source_with_price = "产品是一支清爽型防晒乳\n价格89元\n后续上粉底不容易搓泥"
        hotel_count_tail = "广州长隆亲子酒店按预算和距离选，这4"
        hotel_distance_tail = "成都太古里5家酒店对比：地铁距离"
        hotel_distance_tail_v2 = "成都太古里春熙路5家酒店对比，地铁距"
        hotel_budget_tail = "成都太古里住宿按地铁选：5家酒店预算"
        hotel_transport_bad = "广州长隆亲子酒店，按预算和交通省心程"
        hotel_value_bad = "亚龙湾五家亲子酒店对比，哪家最划算"
        hotel_budget_dimension_tail = "三亚亚龙湾5家亲子酒店怎么选，预算"
        hotel_business_dimension_tail = "北京国贸出差酒店怎么选，隔音和地铁要"
        hotel_route_question_tail = "杭州西湖2天1晚，湖滨住宿怎么选才不"
        hotel_tail_let = "三亚亚龙湾亲子酒店怎么选，5家对比让"
        hotel_tail_price = "三亚亚龙湾亲子酒店怎么选，五家酒店价"
        hotel_tail_save = "广州长隆亲子酒店按预算选，班车接送省"
        hotel_tail_by = "广州长隆亲子酒店怎么选：4家酒店按"
        hotel_tail_metro = "成都太古里春熙路5家酒店怎么选，按地"
        route_tail_lingyin = "杭州西湖2天1晚怎么走，湖滨住宿+灵"
        hotel_tail_distance = "成都太古里春熙路酒店怎么选，按地铁距"
        hotel_tail_is = "北京国贸出差酒店怎么选，隔音和地铁是"
        hotel_tail_compare = "国贸出差选酒店，地铁早餐隔音这样比"
        hotel_price_tail = "三亚亚龙湾5家亲子酒店怎么选，价格差"
        hotel_facility_tail = "三亚亚龙湾五家亲子酒店，价格、设施"
        hotel_room_tail = "广州长隆亲子酒店按预算选，班车早餐房"
        travel_single_hotel_source = "\n".join([
            "- 已核验事实：事实源：美团酒旅 skill",
            "- 已核验事实：广州长隆酒店：美团豪华型，美团真实评分4.8，￥929起/晚",
            "- 已核验事实：地址：广州市番禺区汉溪大道东299号，位于长隆度假区核心位置",
            "- 已核验事实：交通/距离：紧邻长隆欢乐世界、水上乐园、野生动物世界，有免费穿梭巴士",
            "- 已核验事实：亲子设施/体验：儿童乐园、探趣亲子房、白虎自助餐厅、火烈鸟",
            "- 已核验事实：权益：住客可享提前半小时入园",
        ])
        travel_single_hotel_tail = "带娃去长隆，这家亲子酒店929起要不"
        travel_single_hotel_cold = "广州长隆亲子酒店怎么选"
        fashion_high_waist_tail = "梨形160显高显遮胯：短上衣+高腰A"
        home_storage_tail = "4平阳台洗衣区改造，2600元搞定收"
        home_folding_tail = "4平阳台洗衣区改造，2600元让折叠"
        home_complete_tail = "4平小阳台洗衣改造，2600元做完整"
        home_build_tail = "4平阳台洗衣区改造，2600元打造"
        fitness_round_tail = "18分钟膝盖友好减脂，4个动作3轮搞"
        fitness_new_tail = "18分钟膝盖友好居家减脂，4个动作新"
        fitness_count_tail = "膝盖友好的18分钟居家减脂训练，4个"
        fitness_ge_tail = "膝盖不好也能在家减脂，18分钟4个动"
        fitness_newbie_tail = "膝盖友好的18分钟居家减脂，新手也能"
        fitness_newbie_tail_v2 = "18分钟膝盖友好的居家减脂训练，新手"
        fitness_newbie_tail_v3 = "18分钟膝盖友好减脂，4个动作适合新"
        fitness_missing_ge = "膝盖友好很稳，18分钟4动作新手减脂"
        fitness_unsupported_period = "膝盖友好的18分钟居家减脂，新手3周"
        baby_minutes_tail = "6月龄睡前流程别弄太复杂，25分钟足"
        baby_steps_tail = "6月龄睡前流程别弄太复杂，5步25"
        bad_issues = api._title_readability_issues(bad, "美食")
        self.assertTrue(any("标题不自然" in issue for issue in bad_issues), bad_issues)
        self.assertEqual(api._title_readability_issues(natural_price_title, "美食"), [])
        self.assertTrue(any("硬截断" in issue for issue in api._title_readability_issues(chopped, "美食")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(dangling, "母婴")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(fitness_dangling, "健身")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(travel_dangling, "旅行")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(home_dangling, "家居")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(food_dangling, "美食")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(hotel_dangling, "旅行")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(food_digit_tail, "美食")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(hotel_action_tail, "旅行")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(food_queue_tail, "美食")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(hotel_transport_tail, "旅行")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(food_price_digit_tail, "美食")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(food_price_label_tail, "美食")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(food_amap_bad_tail, "美食")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(food_not_tail, "美食")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(food_not_step_tail, "美食")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(food_amap_dish_tail, "美食")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(food_diandoude_tail, "美食")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(food_diandoude_steady_tail, "美食")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(food_diandoude_morning_tail, "美食")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(food_shudaxia_tail, "美食")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(food_spicy_beef_tail, "美食")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(food_taotaoju_tail, "美食")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(food_taotaoju_shrimp_tail, "美食")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(food_shudaxia_step_tail, "美食")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(food_shudaxia_avoid_tail, "美食")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(food_shudaxia_order_tail, "美食")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(food_longxi_price_order_tail, "美食")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(hotel_count_tail, "旅行")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(hotel_distance_tail, "旅行")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(hotel_price_tail, "旅行")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(hotel_facility_tail, "旅行")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(hotel_room_tail, "旅行")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(fashion_high_waist_tail, "穿搭")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(home_storage_tail, "家居")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(home_folding_tail, "家居")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(home_complete_tail, "家居")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(home_build_tail, "家居")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(fitness_round_tail, "健身")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(fitness_new_tail, "健身")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(fitness_count_tail, "健身")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(fitness_ge_tail, "健身")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(fitness_newbie_tail, "健身")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(fitness_newbie_tail_v2, "健身")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(fitness_newbie_tail_v3, "健身")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(baby_minutes_tail, "母婴")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(baby_steps_tail, "母婴")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(beauty_dangling, "美妆")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(beauty_dangling_v2, "美妆")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(beauty_dangling_v3, "美妆")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(beauty_dangling_v4, "美妆")))
        self.assertTrue(any("断词" in issue for issue in api._title_readability_issues(beauty_dangling_v5, "美妆")))
        self.assertEqual(api._title_readability_issues(good, "美食"), [])
        self.assertFalse(api._has_blocking_quality_issues(72.1, bad_issues, "美食"))
        self.assertEqual(api._sanitize_title_for_delivery(food_price_digit_tail, "", "美食"), "广州西关陶陶居早茶必点")
        self.assertEqual(api._sanitize_title_for_delivery(food_price_colon_tail, "", "美食"), "广州西关陶陶居老字号早茶")
        food_amap_source = "\n".join([
            "- 门店名：长禧家.珑厨(万博广晟店)",
            "- 位置/地址：南村镇汉溪大道东386号广晟万博城A座7层",
            "- 商圈：番禺万博",
            "- 价格/人均：人均98元",
            "- 必点/招牌菜：芝士焗小青龙、乳鸽、忘不了鱼、雪燕杏花羹",
            "- 营业时间：09:00-14:00 17:00-21:00",
        ])
        self.assertEqual(
            api._sanitize_title_for_delivery(food_amap_bad_tail, food_amap_source, "美食"),
            "番禺万博芝士焗小青龙必点",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("番禺万博粤菜聚餐，这家人均98很稳", food_amap_source, "美食"),
            "番禺万博芝士焗小青龙必点",
        )
        self.assertEqual(api._sanitize_title_for_delivery(food_dish_tail, "", "美食"), "广州西关陶陶居虾饺必点")
        self.assertEqual(api._sanitize_title_for_delivery(food_brand_tail, "", "美食"), "成都春熙路蜀大侠这样点")
        self.assertEqual(api._sanitize_title_for_delivery(food_action_tail, "", "美食"), "成都蜀大侠第一次点单攻略")
        self.assertEqual(api._sanitize_title_for_delivery(food_action_tail_v2, "", "美食"), "成都蜀大侠第一次点单攻略")
        self.assertEqual(api._sanitize_title_for_delivery(food_city_not_tail, "", "美食"), "成都蜀大侠第一次这样点")
        self.assertEqual(api._sanitize_title_for_delivery(food_not_question_tail, "", "美食"), "春熙路蜀大侠第一次这样点")
        self.assertEqual(api._sanitize_title_for_delivery(food_not_step_tail, "", "美食"), "春熙路蜀大侠这样点不踩雷")
        self.assertEqual(api._sanitize_title_for_delivery(food_point_not_tail, "", "美食"), "春熙路蜀大侠这样点不踩雷")
        self.assertEqual(api._sanitize_title_for_delivery(food_steady_tail, "", "美食"), "广州北京路点都德早茶稳")
        self.assertEqual(api._sanitize_title_for_delivery(food_price_no_unit_tail, "", "美食"), "番禺万博长禧家珑厨人均98元")
        self.assertEqual(api._sanitize_title_for_delivery(food_wrong_tail, "", "美食"), "番禺万博长禧家珑厨人均98元")
        self.assertEqual(api._sanitize_title_for_delivery(food_amap_dish_tail, "", "美食"), "番禺万博芝士焗小青龙必点")
        self.assertEqual(api._sanitize_title_for_delivery(food_diandoude_tail, "", "美食"), "北京路点都德金牌虾饺皇必点")
        self.assertEqual(api._sanitize_title_for_delivery(food_diandoude_steady_tail, "", "美食"), "北京路点都德早茶人均86元")
        self.assertEqual(api._sanitize_title_for_delivery(food_diandoude_morning_tail, "", "美食"), "北京路点都德虾饺皇必点")
        self.assertEqual(api._sanitize_title_for_delivery(food_shudaxia_tail, "", "美食"), "成都春熙路蜀大侠这样点")
        self.assertEqual(api._sanitize_title_for_delivery(food_spicy_beef_tail, "", "美食"), "成都春熙路蜀大侠麻辣牛肉必点")
        self.assertEqual(api._sanitize_title_for_delivery(food_taotaoju_tail, "", "美食"), "广州西关陶陶居早茶必点")
        self.assertEqual(api._sanitize_title_for_delivery(food_taotaoju_shrimp_tail, "", "美食"), "广州西关陶陶居虾饺皇必点")
        self.assertEqual(api._sanitize_title_for_delivery(food_shudaxia_step_tail, "", "美食"), "成都春熙路火锅这样点不踩雷")
        self.assertEqual(api._sanitize_title_for_delivery(food_shudaxia_avoid_tail, "", "美食"), "成都春熙路火锅这样点不踩雷")
        self.assertEqual(api._sanitize_title_for_delivery(food_shudaxia_order_tail, "", "美食"), "春熙路蜀大侠第一次这样点")
        self.assertEqual(api._sanitize_title_for_delivery(food_longxi_price_order_tail, "", "美食"), "番禺万博长禧家珑厨人均98元")
        self.assertEqual(
            api._sanitize_title_for_delivery(beauty_dangling, "", "美妆"),
            "混干敏感皮防晒，两指量才不搓泥",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery(beauty_dangling_v2, "", "美妆"),
            "混干敏感皮防晒，两指量分次涂不搓泥",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery(beauty_dangling_v3, "", "美妆"),
            "敏感混干皮防晒，上粉底不搓泥很稳",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery(beauty_dangling_v4, "", "美妆"),
            "油皮夏天底妆，6小时不斑驳很稳",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery(beauty_dangling_v5, "", "美妆"),
            "黄黑皮玫瑰棕口红，69元很稳",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery(beauty_dangling_v6, "", "美妆"),
            "敏感混干皮防晒，上粉底不搓泥很稳",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery(beauty_dangling_v7, "", "美妆"),
            "油皮夏天底妆，6小时不斑驳很稳",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery(beauty_dangling_v8, "", "美妆"),
            "黄黑皮玫瑰棕口红，69元很稳",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery(beauty_unbacked_title, "", "美妆"),
            "黄黑皮玫瑰棕口红，69元很稳",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery(beauty_price_title, beauty_source_with_price, "美妆"),
            "敏感混干皮防晒，89元不搓泥很稳",
        )
        self.assertEqual(api._sanitize_title_for_delivery(hotel_distance_tail, "", "旅行"), "成都太古里酒店按地铁选")
        self.assertEqual(api._sanitize_title_for_delivery(hotel_distance_tail_v2, "", "旅行"), "成都太古里酒店按地铁选")
        self.assertEqual(api._sanitize_title_for_delivery(hotel_budget_tail, "", "旅行"), "成都太古里住宿按预算选")
        self.assertEqual(api._sanitize_title_for_delivery(hotel_transport_bad, "", "旅行"), "广州长隆亲子酒店交通省心选")
        self.assertEqual(api._sanitize_title_for_delivery(hotel_value_bad, "", "旅行"), "亚龙湾亲子酒店按预算选")
        self.assertEqual(api._sanitize_title_for_delivery(hotel_budget_dimension_tail, "", "旅行"), "三亚亚龙湾5家亲子酒店怎么选")
        self.assertEqual(api._sanitize_title_for_delivery(hotel_business_dimension_tail, "", "旅行"), "北京国贸出差酒店怎么选")
        self.assertEqual(api._sanitize_title_for_delivery(hotel_route_question_tail, "", "旅行"), "杭州西湖2天1晚不赶路")
        self.assertEqual(api._sanitize_title_for_delivery(hotel_tail_let, "", "旅行"), "三亚亚龙湾亲子酒店怎么选")
        self.assertEqual(api._sanitize_title_for_delivery(hotel_tail_price, "", "旅行"), "三亚亚龙湾亲子酒店怎么选")
        self.assertEqual(api._sanitize_title_for_delivery(hotel_tail_save, "", "旅行"), "广州长隆亲子酒店按预算选")
        self.assertEqual(api._sanitize_title_for_delivery(hotel_tail_by, "", "旅行"), "广州长隆亲子酒店怎么选")
        self.assertEqual(api._sanitize_title_for_delivery(hotel_tail_metro, "", "旅行"), "成都太古里春熙路5家酒店怎么选")
        self.assertEqual(api._sanitize_title_for_delivery(route_tail_lingyin, "", "旅行"), "杭州西湖2天1晚灵隐路线")
        self.assertEqual(api._sanitize_title_for_delivery(hotel_tail_distance, "", "旅行"), "成都太古里春熙路酒店怎么选")
        self.assertEqual(api._sanitize_title_for_delivery(hotel_tail_is, "", "旅行"), "北京国贸出差酒店怎么选")
        self.assertEqual(api._sanitize_title_for_delivery(hotel_tail_compare, "", "旅行"), "国贸出差酒店按通勤隔音选")
        self.assertEqual(
            api._sanitize_title_for_delivery(travel_single_hotel_tail, travel_single_hotel_source, "旅行"),
            "广州长隆亲子酒店，929元起值得选",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery(travel_single_hotel_cold, travel_single_hotel_source, "旅行"),
            "广州长隆亲子酒店，929元起值得选",
        )
        self.assertEqual(api._sanitize_title_for_delivery(fashion_high_waist_tail, "", "穿搭"), "梨形160通勤显高遮胯公式")
        self.assertEqual(api._sanitize_title_for_delivery(home_storage_tail, "", "家居"), "4平阳台洗衣区，2600元顺手收纳")
        self.assertEqual(api._sanitize_title_for_delivery(home_folding_tail, "", "家居"), "4平阳台洗衣区，2600元顺手收纳")
        self.assertEqual(api._sanitize_title_for_delivery(home_complete_tail, "", "家居"), "4平小阳台洗衣区，2600元顺手收纳")
        self.assertEqual(api._sanitize_title_for_delivery(home_build_tail, "", "家居"), "4平阳台洗衣区，2600元顺手收纳")
        self.assertEqual(api._sanitize_title_for_delivery(fitness_round_tail, "", "健身"), "18分钟膝盖友好减脂，4个动作3轮")
        self.assertEqual(api._sanitize_title_for_delivery(fitness_new_tail, "", "健身"), "18分钟膝盖友好减脂，4个动作")
        self.assertEqual(api._sanitize_title_for_delivery(fitness_count_tail, "", "健身"), "膝盖友好18分钟减脂，4个动作")
        self.assertEqual(api._sanitize_title_for_delivery(fitness_ge_tail, "", "健身"), "膝盖友好18分钟减脂，4个动作")
        self.assertEqual(api._sanitize_title_for_delivery(fitness_newbie_tail, "", "健身"), "膝盖友好18分钟减脂，新手可练")
        self.assertEqual(api._sanitize_title_for_delivery(fitness_newbie_tail_v2, "", "健身"), "18分钟膝盖友好减脂，新手可练")
        self.assertEqual(api._sanitize_title_for_delivery(fitness_newbie_tail_v3, "", "健身"), "18分钟膝盖友好减脂，新手可练")
        self.assertEqual(api._sanitize_title_for_delivery(fitness_missing_ge, "", "健身"), "膝盖友好18分钟，4个动作减脂")
        self.assertEqual(api._sanitize_title_for_delivery(fitness_unsupported_period, "", "健身"), "18分钟膝盖友好减脂，新手可练")
        self.assertEqual(api._sanitize_title_for_delivery(baby_minutes_tail, "", "母婴"), "6月龄睡前流程推荐，25分钟就够")
        self.assertEqual(api._sanitize_title_for_delivery(baby_steps_tail, "", "母婴"), "6月龄睡前流程推荐，25分钟就够")
        self.assertEqual(
            api._sanitize_title_for_delivery("6月龄睡前流程别太复杂，25分钟就够", "", "母婴"),
            "6月龄睡前流程推荐，25分钟就够",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("6月龄睡前流程别复杂，这样做就够推荐", "", "母婴"),
            "6月龄睡前流程推荐，25分钟就够",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("6月龄睡前流程别弄太复杂，这5步就够", "", "母婴"),
            "6月龄睡前流程推荐，25分钟就够",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("18分钟膝盖友好减脂，4个动作值得", "", "健身"),
            "18分钟膝盖友好减脂，4个动作",
        )
        self.assertEqual(
            api._fallback_title_under_limit("广州长隆亲子酒店怎么选，929起的长隆酒店值吗"),
            "广州长隆亲子酒店怎么选",
        )

    def test_food_title_positive_and_location_features_match_v04_strategy(self):
        feats = feature_extraction.extract_features({
            "note_title": "番禺万博芝士焗小青龙必点",
            "desc": "番禺万博这家粤菜人均98元，营业时间09:00-21:00，招牌芝士焗小青龙必点。#广州美食",
            "domain": "美食",
            "local_time": "2026062817",
        })
        self.assertEqual(feats["title_has_pos_emotion"], 1)
        self.assertEqual(feats["title_has_city"], 1)

    def test_food_delivery_dedupes_repeated_amap_fact_sentences(self):
        source = "\n".join([
            "- 位置/地址：南村镇汉溪大道东386号广晟万博城A座7层",
            "- 价格/人均：人均98元",
            "- 营业时间：09:00-14:00 17:00-21:00",
            "- 评分/口碑：高德评分4.5",
            "- 预订/排队：周末建议提前预订或查看平台排队状态",
            "- 必点/招牌菜：芝士焗小青龙、乳鸽、忘不了鱼",
        ])
        body = (
            "番禺万博商圈找粤菜聚餐，长禧家珑厨是个不错的选择。"
            "门店地址在南村镇汉溪大道东386号广晟万博城A座7层，人均98元，高德评分4.5，营业时间09:00-14:00 17:00-21:00，周末建议提前预订。"
            "门店在南村镇汉溪大道东386号广晟万博城A座7层，人均98元，高德评分4.5，中午11点到下午2点、晚上5点到9点营业，周末聚餐建议提前预订或查看平台排队状态。"
            "招牌菜必点芝士焗小青龙，乳鸽皮脆肉嫩。"
            "#番禺万博 #粤菜聚餐 #芝士焗小青龙 #广州美食 #周末聚餐"
        )
        shaped = api._insert_safe_fact_line(body, "美食", source)
        self.assertEqual(shaped.count("广晟万博城A座7层"), 1)
        self.assertEqual(shaped.count("高德评分4.5"), 1)
        self.assertIn("芝士焗小青龙", shaped)
        self.assertFalse(api._structured_fact_boundary_issues(shaped, source, "美食"))

    def test_food_delivery_removes_unsupported_dim_sum_expansion(self):
        source = "\n".join([
            "- 已核验事实：事实源：用户素材/人工核验 + 高德地图",
            "- 已核验事实：门店名：长禧家.珑厨(万博广晟店)",
            "- 已核验事实：地址：南村镇汉溪大道东386号广晟万博城A座7层",
            "- 已核验事实：人均：98元",
            "- 已核验事实：营业时间：09:00-14:00 17:00-21:00",
            "- 已核验事实：招牌/推荐：芝士焗小青龙、乳鸽、忘不了鱼、雪燕杏花羹",
            "- 已核验事实：套餐信息：双人套餐素材包含芝士焗小青龙、乳鸽、忘不了鱼、点心拼盘、雪燕杏花羹、龙虾",
        ])
        raw = (
            "招牌菜必点芝士焗小青龙，乳鸽皮脆肉嫩。"
            "点心拼盘搭配着吃，虾饺、烧卖等都很精致。"
            "地址：南村镇汉溪大道东386号广晟万博城A座7层。"
            "#番禺美食 #粤菜聚餐 #芝士焗小青龙 #点心拼盘 #周末聚餐"
        )
        self.assertTrue(any("未提供菜品" in item for item in api._structured_fact_boundary_issues(raw, source, "美食")))
        shaped = api._insert_safe_fact_line(raw, "美食", source)
        self.assertNotIn("虾饺", shaped)
        self.assertNotIn("烧卖", shaped)
        self.assertNotIn("地址：", shaped)
        self.assertIn("点心拼盘按门店实际出品搭配主菜", shaped)
        self.assertIn("门店地址在南村镇汉溪大道东386号广晟万博城A座7层", shaped)
        self.assertFalse(api._structured_fact_boundary_issues(shaped, source, "美食"))

    def test_food_delivery_keeps_sourced_dim_sum_names(self):
        source = "\n".join([
            "- 已核验事实：事实源：高德地图",
            "- 已核验事实：门店名：点都德(聚福楼)",
            "- 已核验事实：推荐/高频菜品：金牌虾饺皇、明虾蟹子烧卖、潮州粉果",
            "- 已核验事实：地址：惠福东路470号",
            "- 已核验事实：人均：86元",
            "- 已核验事实：营业时间：08:00-16:00 17:00-21:00",
        ])
        raw = "点都德虾饺皇和明虾蟹子烧卖是高频菜品，潮州粉果也值得点。"
        shaped = api._insert_safe_fact_line(raw, "美食", source)
        self.assertIn("虾饺皇", shaped)
        self.assertIn("明虾蟹子烧卖", shaped)
        self.assertFalse(api._structured_fact_boundary_issues(shaped, source, "美食"))
        self.assertEqual(
            api._fallback_title_under_limit("番禺万博粤菜聚餐推荐，芝士焗小青龙必点"),
            "番禺万博粤菜聚餐推荐，芝士焗小青龙必点",
        )
        self.assertEqual(
            api._fallback_title_under_limit("160cm梨形身材夏季通勤显高遮胯搭配公式"),
            "160cm梨形通勤显高遮胯搭配公式",
        )
        self.assertEqual(
            api._fallback_title_under_limit("4平阳台洗衣区改造，2600元做出顺手的收纳动线"),
            "4平阳台洗衣区，2600元顺手收纳",
        )
        self.assertEqual(
            api._fallback_title_under_limit("4平阳台洗衣区改造，2600元让动线顺畅"),
            "4平阳台洗衣区改造，2600元让动线顺畅",
        )

    def test_food_fact_section_template_is_repair_signal_not_hard_block(self):
        body = "这家适合聚餐。实用信息：地址：惠福东路470号，人均86元，营业时间08:00-21:00。点赞收藏。#广州美食"
        issues = api._human_readability_issues(body, "美食")
        self.assertTrue(any("板块化" in issue for issue in issues), issues)
        self.assertFalse(api._has_blocking_quality_issues(70, issues, "美食"))

    def test_travel_body_is_compacted_to_delivery_limit_without_losing_tags(self):
        sentence = "这家酒店预算清楚，地铁距离明确，早餐和亲子设施都能帮助家庭快速做决定。"
        raw = "\n".join([sentence for _ in range(30)]) + "\n#三亚旅游 #亲子酒店 #亚龙湾"
        compact = api._compact_body_to_delivery_limit(raw, "旅行")
        self.assertLessEqual(api._body_content_len_without_tags(compact), 520)
        self.assertIn("收藏", compact)
        self.assertIn("评论区", compact)
        self.assertIn("#三亚旅游", compact)

    def test_split_body_and_tags_removes_tags_without_leading_space(self):
        main, tags = api._split_body_and_tags("点都德红米肠推荐。#广州美食 #北京路早茶")
        self.assertEqual(main, "点都德红米肠推荐。")
        self.assertEqual(tags, "#广州美食 #北京路早茶")

    def test_v04_lift_instructions_are_domain_specific_and_fact_safe(self):
        low_features = {
            "commercial_fact_density": 0.52,
            "commercial_specificity": 0.61,
            "commercial_domain_slot_coverage": 0.70,
            "commercial_actionability": 0.82,
        }
        mother_items = api._v04_generation_lift_instructions(low_features, "母婴", 66.0)
        mother_text = "\n".join(mother_items)
        self.assertIn("月龄", mother_text)
        self.assertIn("安全边界", mother_text)
        self.assertIn("观察指标", mother_text)
        self.assertIn("不写我家娃", mother_text)
        self.assertNotIn("医生推荐", mother_text)
        self.assertTrue(api._needs_v04_score_lift(66.0, low_features, "母婴", ""))
        self.assertFalse(api._needs_v04_score_lift(73.0, low_features, "母婴", ""))

        travel_text = "\n".join(api._build_fix_instructions({"body_len": 360, "body_has_price": 0, "body_has_transport": 0}, [], "旅行"))
        self.assertIn("预算按实际交通和住宿为准", travel_text)
        self.assertIn("交通/路线", travel_text)
        self.assertNotIn("2800", travel_text)

        beauty_text = "\n".join(api._build_fix_instructions({"body_len": 240, "body_has_price": 0}, [], "美妆"))
        self.assertIn("价格按购买渠道为准", beauty_text)
        self.assertNotIn("大牌的1/3", beauty_text)

        home_text = "\n".join(api._build_fix_instructions({"body_len": 320, "body_has_price": 0}, [], "家居"))
        self.assertIn("预算按实际单品清单为准", home_text)
        self.assertNotIn("3200", home_text)

        fashion_lift_text = "\n".join(api._v04_generation_lift_instructions({"body_has_price": 0}, "穿搭", 66.0))
        beauty_lift_text = "\n".join(api._v04_generation_lift_instructions({"body_has_price": 0}, "美妆", 66.0))
        travel_lift_text = "\n".join(api._v04_generation_lift_instructions(
            {"body_has_price": 0, "body_has_transport": 0},
            "旅行",
            66.0,
            "广州长隆酒店：美团真实评分4.8，￥929起/晚，免费穿梭巴士",
        ))
        home_lift_text = "\n".join(api._v04_generation_lift_instructions(
            {"body_has_price": 0},
            "家居",
            66.0,
            "4平阳台，预算2600元，清单洞洞板、洗衣柜",
        ))
        self.assertIn("价格按实际链接/门店为准", fashion_lift_text)
        self.assertIn("禁止穿出165", fashion_lift_text)
        self.assertIn("价格按购买渠道为准", beauty_lift_text)
        self.assertIn("交通/路线", travel_lift_text)
        self.assertIn("美团评分/起价/位置/交通", travel_lift_text)
        self.assertIn("空间痛点", home_lift_text)

    def test_score_directed_second_pass_runs_for_low_v04_without_explicit_issue(self):
        original_call = api._mr.call
        original_score = api._score_generated_note
        original_shape = api._shape_body_for_delivery
        calls = []

        current_features = {
            "title_len": 10,
            "body_len": 280,
            "tag_count": 5,
            "body_cta_count": 1,
            "title_has_pos_emotion": 1,
            "title_has_number": 1,
            "plad_phrasal_repetition": 0.12,
            "plad_avg_sentence_len": 38,
            "plad_sentence_burstiness": 0.70,
            "commercial_fact_density": 0.52,
            "commercial_specificity": 0.60,
            "commercial_domain_slot_coverage": 0.70,
            "commercial_actionability": 0.86,
        }
        improved_features = dict(current_features)
        improved_features.update({
            "body_len": 300,
            "commercial_fact_density": 0.76,
            "commercial_specificity": 0.78,
            "commercial_domain_slot_coverage": 0.90,
            "commercial_actionability": 0.94,
        })
        improved_body = (
            "10月龄出牙期护理可以先从清洁和观察做起，吃完辅食后用温水纱布轻擦牙龈，动作放轻，"
            "重点看有没有红肿、破皮和明显抗拒，第一次尝试新牙胶也先短时间使用，成人全程看护更稳。"
            "步骤很简单，第一步饭后清洁口腔，第二步把牙胶按说明清洗晾干，第三步每次使用后观察吞咽、口水和睡眠变化，"
            "如果出现持续哭闹、皮疹或发热，就不要继续自行加量，及时咨询专业医生。"
            "这类方法更适合已经进入出牙期、能接受口腔清洁的宝宝，不适合口腔破损或正在发热的时候照搬，"
            "家长可以先收藏这份步骤，按自家宝宝状态慢慢调整，觉得有用记得点赞收藏。"
            "#10月龄宝宝 #出牙护理 #育儿经验 #新手妈妈 #宝宝护理"
        )

        async def fake_call(route, system, user, **kwargs):
            calls.append((route, system, user, kwargs))
            return f"<note><title>10月龄出牙护理推荐</title><body>{improved_body}</body></note>"

        async def fake_score(title, body, domain, local_time, timing, cover_feats):
            return 72.4, improved_features, "优秀"

        async def fake_shape(title, body, domain, source_context, style_hint=""):
            return body

        try:
            api._mr.call = fake_call
            api._score_generated_note = fake_score
            api._shape_body_for_delivery = fake_shape
            result = asyncio.run(api._score_directed_second_pass(
                "10月龄出牙护理推荐",
                (
                    "10月龄出牙期护理可以先从饭后清洁开始，用温水纱布轻擦牙龈，动作放轻，"
                    "再准备干净牙胶短时间尝试，重点观察口水、哭闹、皮肤和睡眠变化。"
                    "如果宝宝明显抗拒，就先停下来安抚，不要为了完成步骤硬推进；如果有发热、破皮或持续哭闹，"
                    "需要及时咨询专业医生。这个版本已经可读，但信息密度偏低，适合继续补强观察指标和安全边界。"
                    "原稿还可以补清楚每一步的顺序、每次观察多久、哪些情况不适合继续，以及家长怎么记录变化，"
                    "这样读者才知道不是单纯买一个牙胶，而是在做一套安全的出牙期护理流程。"
                    "有用先收藏，评论区聊聊你的情况。#10月龄宝宝 #出牙护理 #育儿经验 #新手妈妈 #宝宝护理"
                ),
                "母婴",
                "2026062512",
                source_context="10月龄宝宝，出牙期护理。",
                style_hint="V0.4低分二修",
                current_score=66.0,
                current_features=current_features,
                current_grade="良好",
                current_issues=[],
                route="arbitrate",
            ))
        finally:
            api._mr.call = original_call
            api._score_generated_note = original_score
            api._shape_body_for_delivery = original_shape

        title, body, score, _features, _grade, issues, repaired, reason = result
        self.assertTrue(repaired, reason)
        self.assertGreaterEqual(score, 72.0)
        self.assertIn("10月龄", title)
        self.assertIn("观察", body)
        self.assertFalse(api._has_blocking_quality_issues(score, issues, "母婴"), issues)
        self.assertIn("V0.4质量未到参考线", calls[0][2])
        self.assertIn("母婴提质", calls[0][2])

    def test_second_pass_continues_after_deterministic_lift_when_still_below_v04_target(self):
        original_det = api._try_deterministic_score_lift
        original_call = api._mr.call
        original_score = api._score_generated_note
        original_shape = api._shape_body_for_delivery
        calls = []
        base_features = {
            "title_len": 18,
            "body_len": 360,
            "tag_count": 7,
            "body_cta_count": 1,
            "title_has_number": 1,
            "commercial_fact_density": 1.0,
            "commercial_specificity": 1.0,
            "commercial_domain_slot_coverage": 1.0,
            "commercial_actionability": 1.0,
        }
        improved_features = dict(base_features, plad_avg_sentence_len=38)
        improved_features.update({
            "title_len": 14,
            "title_has_pos_emotion": 1,
            "plad_number_ratio": 0.05,
            "plad_phrasal_repetition": 0.08,
            "plad_sentence_burstiness": 0.55,
        })

        async def fake_det(*args, **kwargs):
            return (
                "膝盖友好的18分钟居家减脂",
                "确定性修补后的正文。想跟练先收藏，评论区说你的目标。#居家健身 #减脂 #新手训练 #膝盖友好 #低冲击",
                70.0,
                dict(base_features),
                "良好",
                [],
                True,
                "确定性二修采纳",
            )

        async def fake_call(route, system, user, **kwargs):
            calls.append((route, system, user, kwargs))
            return (
                "<note><title>18分钟膝盖友好训练推荐计划</title>"
                "<body>18分钟低冲击训练适合新手，先热身5分钟，再做原地踏步60秒、臀桥15次、死虫12次和靠墙静蹲30秒。"
                "第一轮先把速度放慢，原地踏步只要脚掌轻落地，臀桥顶端停1秒感受臀部发力，死虫全程腰背贴地，靠墙静蹲按膝盖状态减少时间。"
                "每轮之间休息60秒，动作间可以喝水调整呼吸；膝盖不舒服就跳过靠墙静蹲，改成坐姿腿部拉伸。"
                "训练后拉伸小腿和臀腿3-5分钟，第二天酸胀明显就休息一天，不要连续硬练。"
                "这套计划不承诺快速瘦身，重点是建立稳定运动习惯，适合在客厅或卧室完成。想跟练先收藏，评论区说你的目标。"
                "#居家健身 #膝盖友好 #低冲击 #新手训练 #减脂</body></note>"
            )

        async def fake_score(title, body, domain, local_time, timing, cover_feats):
            return 73.2, improved_features, "优秀"

        async def fake_shape(title, body, domain, source_context, style_hint=""):
            return body

        try:
            api._try_deterministic_score_lift = fake_det
            api._mr.call = fake_call
            api._score_generated_note = fake_score
            api._shape_body_for_delivery = fake_shape
            result = asyncio.run(api._score_directed_second_pass(
                "膝盖友好的18分钟居家减脂，4个动作",
                "原稿正文。",
                "健身",
                "2026062512",
                source_context="18分钟，原地踏步60秒、臀桥15次、死虫12次、靠墙静蹲30秒。",
                current_score=69.0,
                current_features=base_features,
                current_grade="良好",
                current_issues=[],
                route="content_gen",
            ))
        finally:
            api._try_deterministic_score_lift = original_det
            api._mr.call = original_call
            api._score_generated_note = original_score
            api._shape_body_for_delivery = original_shape

        title, _body, score, _features, _grade, _issues, repaired, reason = result
        self.assertTrue(repaired, reason)
        self.assertGreaterEqual(score, 72.0)
        self.assertIn("推荐", title)
        self.assertEqual(len(calls), 1)
        self.assertIn("V0.4质量未到参考线", calls[0][2])

    def test_score_directed_second_pass_accepts_higher_scoring_candidate(self):
        original_call = api._mr.call
        original_score = api._score_generated_note
        original_shape = api._shape_body_for_delivery
        calls = []

        current_features = {
            "title_len": 13,
            "body_len": 380,
            "tag_count": 5,
            "body_cta_count": 1,
            "title_has_pos_emotion": 0,
            "title_has_number": 1,
            "title_has_city": 1,
            "body_has_price": 1,
            "body_has_address": 1,
            "body_has_hours": 1,
            "body_has_must_order": 0,
            "plad_phrasal_repetition": 0.03,
            "plad_avg_sentence_len": 24,
            "plad_sentence_burstiness": 0.4,
        }
        improved_features = dict(current_features)
        improved_features.update({
            "body_len": 330,
            "body_cta_count": 2,
            "title_has_pos_emotion": 1,
            "body_has_must_order": 1,
            "plad_phrasal_repetition": 0.12,
            "plad_avg_sentence_len": 38,
            "plad_sentence_burstiness": 0.68,
        })

        async def fake_call(route, system, user, **kwargs):
            calls.append((route, system, user, kwargs))
            return (
                "<note><title>广州番禺粤菜值得试</title>"
                "<body>番禺万博这家粤菜馆人均98元，地址在广晟万博城A座7层，营业时间09:00-14:00 17:00-21:00，"
                "芝士焗小青龙是招牌也推荐，点单围绕它展开更稳，乳鸽和清蒸鱼适合搭配。"
                "如果是第一次去，先点芝士焗小青龙更容易判断出品，外壳微焦但虾肉保持弹性，咸香不会压过海鲜甜味，"
                "乳鸽适合放在中段，皮脆肉嫩，清蒸鱼负责收尾，调味克制，整体更像一桌稳定粤菜而不是网红摆拍。"
                "番禺万博聚餐选择很多，这家胜在信息清楚、菜品稳定、到店决策简单，适合收藏，下次想吃粤菜可以直接照着点，记得点赞收藏。"
                "#广州美食 #番禺美食 #粤菜 #万博美食 #芝士焗小青龙</body></note>"
            )

        async def fake_score(title, body, domain, local_time, timing, cover_feats):
            return 70.4, improved_features, "良好"

        async def fake_shape(title, body, domain, source_context, style_hint=""):
            return body

        try:
            api._mr.call = fake_call
            api._score_generated_note = fake_score
            api._shape_body_for_delivery = fake_shape
            result = asyncio.run(api._score_directed_second_pass(
                "广州番禺粤菜聚餐怎么点",
                (
                    "广州番禺万博这家粤菜馆适合朋友聚餐，人均98元，地址在广晟万博城A座7层，"
                    "营业时间09:00-14:00 17:00-21:00。旧正文已经写清位置、价格和时间，"
                    "但还没有把招牌菜和推荐点单说清楚，读者只能知道这家店在哪，却不知道第一次去应该怎么点。"
                    "如果是周末聚餐，可以提前看门店页确认订位情况，正文需要继续补充菜品顺序和适合人群。"
                    "比如第一道菜适合负责记忆点，第二道菜负责照顾不吃海鲜的人，最后再补一个清淡收尾，"
                    "这些点单逻辑比单纯报地址更能帮助用户决定要不要去。"
                    "这份信息先收藏，评论区聊聊你想试哪道。#广州美食 #番禺美食 #粤菜 #万博美食 #聚餐"
                ),
                "美食",
                "2026062512",
                source_context=(
                    "- 位置/地址：南村镇汉溪大道东386号广晟万博城A座7层\n"
                    "- 价格/人均：人均98元\n"
                    "- 营业时间：09:00-14:00 17:00-21:00"
                ),
                style_hint="单测二修",
                current_score=66.0,
                current_features=current_features,
                current_grade="良好",
                current_issues=["旧评分器低于历史参考线（当前66.0分，参考≥72分，仅作遥测）", "美食笔记缺少必点/招牌/推荐菜信息"],
                route="arbitrate",
            ))
        finally:
            api._mr.call = original_call
            api._score_generated_note = original_score
            api._shape_body_for_delivery = original_shape

        title, body, score, _features, _grade, issues, repaired, reason = result
        self.assertTrue(repaired, reason)
        self.assertEqual(score, 70.4)
        self.assertRegex(title, r"(?:推荐|必点|值得|稳)")
        self.assertFalse(api._has_blocking_quality_issues(score, issues, "美食"), issues)
        self.assertIn("当前特征快照", calls[0][2])
        self.assertIn("美食提质", calls[0][2])
        self.assertNotIn("从以下选1个：绝了", calls[0][2])

    def test_score_directed_second_pass_rejects_lower_scoring_candidate(self):
        original_call = api._mr.call
        original_score = api._score_generated_note
        original_shape = api._shape_body_for_delivery

        features = {
            "title_len": 13,
            "body_len": 330,
            "tag_count": 5,
            "body_cta_count": 1,
            "title_has_pos_emotion": 0,
            "title_has_number": 1,
            "title_has_city": 1,
            "body_has_price": 1,
            "body_has_address": 1,
            "body_has_hours": 1,
            "body_has_must_order": 1,
            "plad_phrasal_repetition": 0.08,
            "plad_avg_sentence_len": 32,
            "plad_sentence_burstiness": 0.6,
        }

        async def fake_call(route, system, user, **kwargs):
            return (
                "<note><title>广州番禺粤菜值得试</title>"
                "<body>候选稿虽然更顺，但评分更低，记得点赞收藏。"
                "#广州美食 #番禺美食 #粤菜 #万博美食 #聚餐</body></note>"
            )

        async def fake_score(title, body, domain, local_time, timing, cover_feats):
            return 64.0, dict(features, title_has_pos_emotion=1), "良好"

        async def fake_shape(title, body, domain, source_context, style_hint=""):
            return body

        try:
            api._mr.call = fake_call
            api._score_generated_note = fake_score
            api._shape_body_for_delivery = fake_shape
            result = asyncio.run(api._score_directed_second_pass(
                "广州番禺粤菜人均98",
                "原稿正文",
                "美食",
                "2026062512",
                source_context="- 价格/人均：人均98元",
                current_score=66.0,
                current_features=features,
                current_grade="良好",
                current_issues=["旧评分器低于历史参考线（当前66.0分，参考≥72分，仅作遥测）"],
                route="arbitrate",
            ))
        finally:
            api._mr.call = original_call
            api._score_generated_note = original_score
            api._shape_body_for_delivery = original_shape

        title, body, score, _features, _grade, _issues, repaired, reason = result
        self.assertFalse(repaired, reason)
        self.assertEqual(title, "广州番禺粤菜人均98")
        self.assertEqual(body, "原稿正文")
        self.assertEqual(score, 66.0)

    def test_generation_delivery_limits_block_title_boundary_and_overlong_food_body(self):
        title_at_platform_boundary = "南京西路蟹黄拌面绝了，人均58元排队也要"
        self.assertEqual(len(title_at_platform_boundary), 20)
        self.assertLessEqual(
            len(api._fallback_title_under_limit(title_at_platform_boundary)),
            api._TITLE_DELIVERY_MAX,
        )
        self.assertFalse(api._fallback_title_under_limit(title_at_platform_boundary).endswith("的"))
        overlong_without_semantic_clause = "南京西路蟹黄拌面人均58元工作日午餐稳，适合赶时间"
        self.assertEqual(
            api._fallback_title_under_limit(overlong_without_semantic_clause),
            overlong_without_semantic_clause,
        )
        self.assertGreater(len(api._fallback_title_under_limit(overlong_without_semantic_clause)), api._TITLE_DELIVERY_MAX)
        overlong_fitness_title = "7天居家减脂4动作，新手友好无器械计划"
        self.assertEqual(
            api._fallback_title_under_limit(overlong_fitness_title),
            "7天居家减脂4个动作，新手友好无器械计划",
        )
        self.assertEqual(
            api._fallback_title_under_limit("8月龄宝宝辅食顺序｜从泥糊到软颗粒安全过渡"),
            "8月龄宝宝辅食顺序｜从泥糊到软颗粒安全过渡",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("油皮夏天底妆这样更稳，6小时不明显斑", "", "美妆"),
            "油皮夏天底妆这样更稳，6小时不斑驳",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("弹力带臀腿新手这样练，找对发力感最关", "", "健身"),
            "弹力带臀腿新手这样练，发力感是关键",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("弹力带臀腿新手计划：4个动作3组，找", "", "健身"),
            "弹力带臀腿新手计划：4个动作3组",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("宝宝出牙期护理｜我的观察清单和避坑经", "", "母婴"),
            "宝宝出牙期护理｜观察和避坑经验",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("科技园42元午餐，10分钟出餐稳定套", "", "美食"),
            "科技园42元午餐，10分钟出餐",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("杭州2天1晚亲子游，别排太满留时间休", "", "旅行"),
            "杭州亲子游别排满，留时间休息",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("新手7天居家减脂，4个动作每晚20分", "", "健身"),
            "新手7天居家减脂，每晚20分钟",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("成都建设路火锅，不辣也能吃，人均92", "", "美食"),
            "建设路火锅不辣也能吃，人均92元",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("广州亲子酒店住珠江新城挺省心，地铁8", "", "旅行"),
            "广州亲子酒店，地铁8分钟更省心",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("梨形身材夏季通勤3套显高公式，遮胯显", "", "穿搭"),
            "梨形通勤3套，显高遮胯",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("4平阳台洗衣区2600元改造，收纳动", "", "家居"),
            "4平阳台洗衣区，收纳动线这样改",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("12平卧室1500元改造，灯光窗帘让", "", "家居"),
            "12平卧室改造，灯光窗帘很关键",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("12平卧室1500元改造，终于能好好", "", "家居"),
            "12平卧室改造，终于能好好睡",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("南京西路蟹黄面午餐稳，人均58元工作", "", "美食"),
            "南京西路蟹黄面，人均58元午餐稳",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("南京西路蟹黄面午餐稳，工作日11:3", "", "美食"),
            "南京西路蟹黄面，11点半前去",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("南京西路蟹黄面午餐稳，11点半前来排", "", "美食"),
            "南京西路蟹黄面，11点半前排队",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("西湖湖滨早午餐｜10点前来避排队，招", "", "美食"),
            "西湖湖滨早午餐，10点前避排队",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("西湖湖滨早午餐｜班尼迪克蛋必点，10", "", "美食"),
            "西湖湖滨早午餐，班尼迪克蛋必点",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("西湖边早午餐别太晚去，人均76元值得", "", "美食"),
            "西湖边早午餐，班尼迪克蛋必点",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("成都春熙路火锅避坑指南：微辣锅底+必", "", "美食"),
            "春熙路火锅新手点单避坑指南",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("三亚亲子酒店选亚龙湾，亲子房1", "", "旅行"),
            "三亚亲子酒店，亲子房约1280",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("三亚亲子酒店选亚龙湾，省心度假的实际", "", "旅行"),
            "三亚亲子酒店，省心度假真实感受",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("三亚亲子酒店选亚龙湾更省心，低龄娃泡", "", "旅行"),
            "三亚亲子酒店，低龄娃泡酒店",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("三亚亲子酒店选亚龙湾，省心泡酒店的正", "", "旅行"),
            "三亚亲子酒店，省心泡酒店实测",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("杭州2天1晚住湖滨银泰，西湖灵隐这样", "", "旅行"),
            "杭州2天1晚，西湖灵隐这样排",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("杭州2天1晚住湖滨更顺，西湖灵隐这样", "", "旅行"),
            "杭州2天1晚，西湖灵隐这样排",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("杭州2天1晚住湖滨银泰，西湖灵隐不赶", "", "旅行"),
            "杭州2天1晚，西湖灵隐不赶路",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("杭州2天1晚住湖滨银泰，西湖灵隐不用", "", "旅行"),
            "杭州2天1晚，西湖灵隐不用赶",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("成都首次住宿选择：太古里附近酒店吃喝", "", "旅行"),
            "成都首次住太古里，吃喝地铁方便",
        )
        self.assertEqual(
            api._sanitize_title_for_delivery("北京国贸出差选这类酒店，地铁5分钟省", "", "旅行"),
            "北京国贸出差，地铁5分钟省通勤",
        )
        self.assertFalse(api._title_readability_issues("北京国贸出差，地铁5分钟省通勤", "旅行"))
        self.assertFalse(api._title_readability_issues("宝宝出牙期这样护理，避免误区少走弯路", "母婴"))
        self.assertEqual(
            api._sanitize_title_for_delivery("成都第一次来住太古里附近，吃喝地铁", "", "旅行"),
            "成都住太古里，吃喝地铁方便",
        )
        raw_note = f"<note><title>{title_at_platform_boundary}</title><body>正文</body></note>"
        self.assertEqual(api._extract_note_from_response(raw_note)[0], title_at_platform_boundary)

        features = {
            "body_len": 390,
            "tag_count": 6,
            "body_cta_count": 1,
            "body_has_price": 1,
            "body_has_address": 1,
            "body_has_hours": 1,
            "body_has_must_order": 1,
            "title_has_city": 1,
        }
        body = "正文" * 190
        issues = api._generated_quality_issues(
            title_at_platform_boundary,
            body,
            "美食",
            75,
            features,
        )
        self.assertFalse(any("标题超过平台上限" in item for item in issues))
        self.assertTrue(any("正文超过目标上限" in item for item in issues))
        self.assertFalse(api._has_blocking_quality_issues(75, issues))

        thin_price_dish_title = "198元龙虾乌冬，汤浓到底不腻"
        thin_title_issues = api._title_readability_issues(thin_price_dish_title, "美食")
        self.assertTrue(any("价格+菜品+泛评价" in item for item in thin_title_issues), thin_title_issues)
        delivery_meta = api._title_delivery_meta(thin_price_dish_title, thin_price_dish_title, thin_title_issues)
        self.assertTrue(delivery_meta["needs_refine"])
        self.assertEqual(delivery_meta["target"], "16-20字")

    def test_body_max_contract_applies_to_all_primary_domains(self):
        required_feature_flags = {
            "美食": {"body_has_price": 1, "body_has_address": 1, "body_has_hours": 1, "body_has_must_order": 1},
            "旅行": {"body_has_price": 1, "body_has_transport": 1},
            "穿搭": {"body_has_price": 1},
            "美妆": {"body_has_price": 1},
            "家居": {"body_has_price": 1},
            "健身": {"plad_number_ratio": 0.02},
            "母婴": {},
        }
        for domain, target in api._DOMAIN_QUALITY_TARGETS.items():
            with self.subTest(domain=domain):
                max_body = int(target["body_max"])
                tag_min = int(target["tag_min"])
                features = {
                    "body_len": max_body + 1,
                    "tag_count": tag_min,
                    "body_cta_count": 1,
                    "title_has_city": 1,
                    **required_feature_flags.get(domain, {}),
                }
                issues = api._generated_quality_issues(
                    "高质量标题58元真香",
                    "正" * (max_body + 1),
                    domain,
                    75,
                    features,
                )
                self.assertTrue(any("正文超过目标上限" in item for item in issues), issues)
                self.assertFalse(api._has_blocking_quality_issues(75, issues), issues)

    def test_narrative_details_are_not_hard_blocked(self):
        body = (
            "朋友说下周还想来，巷子里热气很足，蟹黄拌面香气明显，人均58元，"
            "南京西路地铁站出来走几分钟，营业时间到晚上九点，排队二十分钟，"
            "招牌小馄饨也推荐，面条裹满蟹黄酱汁，咸鲜感很足。"
        ) * 3 + "点赞收藏下次直接导航。#上海探店 #南京西路美食 #蟹黄拌面 #上海美食推荐 #周末去哪吃"
        features = {
            "body_len": 320,
            "tag_count": 5,
            "body_cta_count": 1,
            "body_has_price": 1,
            "body_has_address": 1,
            "body_has_hours": 1,
            "body_has_must_order": 1,
            "title_has_city": 1,
        }
        issues = api._generated_quality_issues("上海蟹黄面真香", body, "美食", 75, features)
        self.assertFalse(api._has_blocking_quality_issues(75, issues), issues)

    def test_generation_xml_aliases_match_existing_prompts(self):
        raw = (
            "<draft_title>上海蟹黄面真的香</draft_title>"
            "<draft_body>正文草稿</draft_body>"
            "<keyword_tip>蟹黄面重复3次</keyword_tip>"
            "<tag_recommendation>#上海美食 #蟹黄面</tag_recommendation>"
            "<user_angle>今晚就想去</user_angle>"
        )
        self.assertEqual(api._xtag_any(raw, "title", "draft_title"), "上海蟹黄面真的香")
        self.assertEqual(api._xtag_any(raw, "body", "draft_body"), "正文草稿")
        self.assertEqual(api._xtag_any(raw, "keywords", "keyword_tip"), "蟹黄面重复3次")
        self.assertEqual(api._xtag_any(raw, "tags", "tag_recommendation"), "#上海美食 #蟹黄面")
        self.assertEqual(api._xtag_any(raw, "hook", "user_angle"), "今晚就想去")

    def test_chat_quality_repair_can_replace_below_sixty_rewrite(self):
        original_score = api._score_chat_note
        original_call = api._mr.call

        async def fake_score(title, body, session):
            if title == "低质标题":
                return 59.0, {}, "待改进", ["正文过短（当前20字，美食最低交付标准≥220字）"]
            return 75.0, {"body_len": 260, "tag_count": 5, "body_cta_count": 1}, "良好", []

        async def fake_call(*args, **kwargs):
            return (
                "<note><title>上海蟹黄面真的香</title>"
                "<body>这家蟹黄面香气很足，价格和地址都写清楚，适合周末收藏再去。"
                "#上海美食 #蟹黄面 #周末去哪儿 #探店 #本地人推荐</body></note>"
            )

        try:
            api._score_chat_note = fake_score
            api._mr.call = fake_call

            async def run():
                return await api._repair_chat_note_if_needed(
                    "低质标题",
                    "太好吃了。#美食",
                    {"domain": "美食", "local_time": "2026062412"},
                    "帮我重写一版",
                )

            title, body, score, feats, grade, issues, repaired = asyncio.run(run())
            self.assertTrue(repaired)
            self.assertEqual(title, "上海蟹黄面真的香")
            self.assertEqual(score, 75.0)
            self.assertEqual(issues, [])
        finally:
            api._score_chat_note = original_score
            api._mr.call = original_call

    def test_chat_quality_repair_runs_v04_lift_without_explicit_issue(self):
        original_score = api._score_chat_note
        original_second_pass = api._score_directed_second_pass
        calls = []

        low_features = {
            "commercial_fact_density": 0.52,
            "commercial_specificity": 0.62,
            "commercial_domain_slot_coverage": 0.70,
            "commercial_actionability": 0.82,
        }
        improved_features = dict(low_features)
        improved_features.update({
            "commercial_fact_density": 0.78,
            "commercial_specificity": 0.78,
            "commercial_domain_slot_coverage": 0.90,
            "commercial_actionability": 0.94,
        })

        async def fake_score(title, body, session):
            return 66.0, low_features, "良好", []

        async def fake_second_pass(title, body, domain, local_time, **kwargs):
            calls.append((title, body, domain, local_time, kwargs))
            return (
                "混干皮粉底液推荐",
                "混干皮选粉底液先看服帖度和卡粉边界，少量多次拍开更稳。#美妆 #粉底液 #混干皮 #底妆",
                73.2,
                improved_features,
                "优秀",
                [],
                True,
                "V0.4低分二修采纳",
            )

        try:
            api._score_chat_note = fake_score
            api._score_directed_second_pass = fake_second_pass

            title, body, score, feats, grade, issues, repaired = asyncio.run(
                api._repair_chat_note_if_needed(
                    "混干皮粉底液",
                    "这支粉底液挺适合日常。#美妆 #粉底液",
                    {
                        "domain": "美妆",
                        "local_time": "2026062812",
                        "fact_context": "肤质：混干敏感皮\n产品：粉底液 色号：01",
                    },
                    "帮我优化得更像真实分享",
                )
            )
        finally:
            api._score_chat_note = original_score
            api._score_directed_second_pass = original_second_pass

        self.assertTrue(repaired)
        self.assertEqual(score, 73.2)
        self.assertEqual(title, "混干皮粉底液推荐")
        self.assertEqual(issues, [])
        self.assertEqual(len(calls), 1)
        self.assertIn("肤质：混干敏感皮", calls[0][4]["source_context"])

    def test_chat_quality_repair_reverts_score_regression(self):
        original_score = api._score_chat_note
        original_second_pass = api._score_directed_second_pass

        async def fake_score(title, body, session):
            if title == "上一版标题":
                return 76.0, {"body_len": 300, "tag_count": 5, "body_cta_count": 1}, "优秀", []
            return 70.5, {"body_len": 280, "tag_count": 5, "body_cta_count": 1}, "良好", []

        async def fake_second_pass(title, body, domain, local_time, **kwargs):
            return (
                title,
                body,
                71.0,
                {"body_len": 285, "tag_count": 5, "body_cta_count": 1},
                "良好",
                [],
                False,
                "still_regressed",
            )

        try:
            api._score_chat_note = fake_score
            api._score_directed_second_pass = fake_second_pass

            title, body, score, feats, grade, issues, repaired = asyncio.run(
                api._repair_chat_note_if_needed(
                    "改写标题",
                    "改写正文。#美食 #探店 #周末去哪儿 #本地生活 #收藏",
                    {
                        "domain": "美食",
                        "local_time": "2026062812",
                        "note_title": "上一版标题",
                        "note_body": "上一版正文信息密度更高。#美食 #探店 #周末去哪儿 #本地生活 #收藏",
                        "current_score": 76.0,
                    },
                    "帮我改得更自然",
                )
            )
        finally:
            api._score_chat_note = original_score
            api._score_directed_second_pass = original_second_pass

        self.assertTrue(repaired)
        self.assertEqual(title, "上一版标题")
        self.assertEqual(score, 76.0)
        self.assertTrue(any("对话改写分数低于当前版本" in issue for issue in issues), issues)

    def test_generation_selector_prefers_clean_candidate_over_issue_penalty(self):
        original_score_candidate = api._score_generation_delivery_candidate
        original_ranker = api.get_v04_preference_ranker

        async def fake_score_candidate(candidate, **_kwargs):
            if candidate["origin"] == "high_but_bad":
                return {
                    **candidate,
                    "score": 72.0,
                    "features": {"candidate_id": 1},
                    "grade": "优秀",
                    "quality_issues": ["标题不自然：像硬拼关键词", "正文内部格式太重"],
                    "blocking": False,
                    "publishable_prob": 0.50,
                    "ranker_win_rate": None,
                    "selector_score": api._selector_score(
                        72.0,
                        ["标题不自然：像硬拼关键词", "正文内部格式太重"],
                        False,
                        0.50,
                        None,
                    ),
                }
            return {
                **candidate,
                "score": 70.0,
                "features": {"candidate_id": 2},
                "grade": "良好",
                "quality_issues": [],
                "blocking": False,
                "publishable_prob": 0.55,
                "ranker_win_rate": None,
                "selector_score": api._selector_score(70.0, [], False, 0.55, None),
            }

        try:
            api._score_generation_delivery_candidate = fake_score_candidate
            api.get_v04_preference_ranker = lambda: None
            selection = asyncio.run(api._select_best_generation_candidate(
                [
                    {"origin": "high_but_bad", "title": "标题A", "body": "正文A"},
                    {"origin": "clean", "title": "标题B", "body": "正文B"},
                ],
                domain="美食",
                local_time="2026062812",
            ))
        finally:
            api._score_generation_delivery_candidate = original_score_candidate
            api.get_v04_preference_ranker = original_ranker

        self.assertEqual(selection["selected"]["origin"], "clean")
        self.assertEqual(selection["candidate_count"], 2)
        self.assertEqual(selection["viable_count"], 2)

    def test_generation_selector_uses_v04_ranker_when_scores_are_close(self):
        original_score_candidate = api._score_generation_delivery_candidate
        original_ranker = api.get_v04_preference_ranker
        original_rank_prob = api._v04_ranker_a_win_probability

        async def fake_score_candidate(candidate, **_kwargs):
            candidate_id = 1 if candidate["origin"] == "plain" else 2
            return {
                **candidate,
                "score": 70.0,
                "features": {"candidate_id": candidate_id},
                "grade": "良好",
                "quality_issues": [],
                "blocking": False,
                "publishable_prob": 0.50,
                "ranker_win_rate": None,
                "selector_score": api._selector_score(70.0, [], False, 0.50, None),
            }

        def fake_rank_probability(features_a, features_b):
            if features_a.get("candidate_id") == 1 and features_b.get("candidate_id") == 2:
                return 0.10
            return 0.90

        try:
            api._score_generation_delivery_candidate = fake_score_candidate
            api.get_v04_preference_ranker = lambda: object()
            api._v04_ranker_a_win_probability = fake_rank_probability
            selection = asyncio.run(api._select_best_generation_candidate(
                [
                    {"origin": "plain", "title": "标题A", "body": "正文A"},
                    {"origin": "ranked", "title": "标题B", "body": "正文B"},
                ],
                domain="美食",
                local_time="2026062812",
            ))
        finally:
            api._score_generation_delivery_candidate = original_score_candidate
            api.get_v04_preference_ranker = original_ranker
            api._v04_ranker_a_win_probability = original_rank_prob

        self.assertEqual(selection["selected"]["origin"], "ranked")
        self.assertTrue(selection["used_ranker"])
        meta = api._selection_meta_payload(selection)
        self.assertEqual(meta["selected_origin"], "ranked")
        self.assertNotIn("body", meta["candidates"][0])

    def test_generation_selector_keeps_ready_clean_candidate_above_ranker_preference(self):
        original_score_candidate = api._score_generation_delivery_candidate
        original_ranker = api.get_v04_preference_ranker
        original_rank_prob = api._v04_ranker_a_win_probability

        async def fake_score_candidate(candidate, **_kwargs):
            if candidate["origin"] == "ranker_favorite_with_issue":
                score = 69.1
                issues = ["家居笔记缺少价格/预算/购买成本信息"]
                candidate_id = 1
            else:
                score = 72.1
                issues = []
                candidate_id = 2
            return {
                **candidate,
                "score": score,
                "features": {"candidate_id": candidate_id},
                "grade": "良好",
                "quality_issues": issues,
                "blocking": False,
                "publishable_prob": 0.90,
                "ranker_win_rate": None,
                "selector_score": api._selector_score(score, issues, False, 0.90, None),
            }

        def fake_rank_probability(features_a, features_b):
            if features_a.get("candidate_id") == 1 and features_b.get("candidate_id") == 2:
                return 0.98
            return 0.02

        try:
            api._score_generation_delivery_candidate = fake_score_candidate
            api.get_v04_preference_ranker = lambda: object()
            api._v04_ranker_a_win_probability = fake_rank_probability
            selection = asyncio.run(api._select_best_generation_candidate(
                [
                    {"origin": "ranker_favorite_with_issue", "title": "标题A", "body": "正文A"},
                    {"origin": "ready_clean", "title": "标题B", "body": "正文B"},
                ],
                domain="家居",
                local_time="2026062812",
            ))
        finally:
            api._score_generation_delivery_candidate = original_score_candidate
            api.get_v04_preference_ranker = original_ranker
            api._v04_ranker_a_win_probability = original_rank_prob

        self.assertEqual(selection["selected"]["origin"], "ready_clean")
        self.assertTrue(selection["used_ranker"])

    def test_user_constraints_contract_normalizes_and_fixes_publish_time(self):
        constraints = api._normalize_user_constraints([
            "不改标题",
            "固定发布时间 18:00",
            "目标：带货",
            "重点优化：曝光量",
        ])

        self.assertEqual(constraints, ["不改标题", "固定发布时间 18:00", "目标：带货", "重点优化：曝光量"])
        self.assertEqual(api._local_time_with_user_constraints("2026070120", constraints), "2026070118")
        payload = api._constraint_contract_payload(constraints)
        self.assertTrue(payload["hard_rules"]["keep_title"])
        self.assertEqual(payload["hard_rules"]["publish_time"], "18:00")
        self.assertTrue(payload["goals"]["commerce_conversion"])
        self.assertTrue(payload["goals"]["exposure"])

    def test_user_constraints_brief_and_hard_guard_are_enforced(self):
        constraints = ["不改标题", "不改封面", "重点优化：互动率"]
        brief = api._user_constraints_brief(constraints, "对话优化")

        self.assertIn("不改标题", brief)
        self.assertIn("不得建议换封面", brief)
        self.assertIn("互动率", brief)
        guarded_title, guarded_body, changed = api._apply_user_constraint_hard_guards(
            "新标题",
            "正文",
            "原始标题",
            constraints,
        )
        self.assertTrue(changed)
        self.assertEqual(guarded_title, "原始标题")
        self.assertEqual(guarded_body, "正文")

    def test_chat_system_prompt_reads_user_constraints(self):
        prompt = api._build_chat_system_prompt({
            "domain": "美食",
            "note_title": "原始标题",
            "note_body": "正文里有真实菜品和地址。",
            "current_score": 68.0,
            "user_constraints": ["不改标题", "固定发布时间 18:00", "目标：涨粉"],
            "generate_context": {},
            "user_prefs": {},
        })

        self.assertIn("用户约束执行契约", prompt)
        self.assertIn("已有标题必须原样保留", prompt)
        self.assertIn("固定发布时间为18:00", prompt)
        self.assertIn("涨粉", prompt)


if __name__ == "__main__":
    unittest.main()
