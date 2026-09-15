import sys
import json
import tempfile
import unittest
from unittest import mock
import httpx
from pathlib import Path
from types import SimpleNamespace


MODEL_DIR = Path(__file__).resolve().parents[1] / "model"
sys.path.insert(0, str(MODEL_DIR))

import admin_server
import db


class AdminSystemStatusTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._old_db_path = db._DB_PATH
        self._tmpdir = tempfile.TemporaryDirectory()
        db._DB_PATH = Path(self._tmpdir.name) / "noteai.db"
        db.init_db()

    def tearDown(self):
        db._DB_PATH = self._old_db_path
        self._tmpdir.cleanup()

    async def test_release_status_uses_only_fixed_owned_read_and_separates_health(self):
        for admission in (True, False):
            with self.subTest(admission=admission):
                response = httpx.Response(200, json={"release": "free_product", "ai_open": admission,
                    "suppliers": [{"id": "kimi", "enabled": False, "business": []},
                                  {"id": "claude", "enabled": admission, "business": ["diagnosis", "chat"]}]})
                with mock.patch.object(httpx.AsyncClient, "get", new_callable=mock.AsyncMock, return_value=response) as get:
                    status = await admin_server._fetch_api_ai_readiness()
                get.assert_awaited_once_with("https://noteaipro.com/public/status")
                self.assertEqual(status["source"], "api_public_status")
                self.assertEqual(status["kimi_status"], "not_in_public_route")
                self.assertEqual(status["claude_status"], "admission_open" if admission else "admission_closed")
                self.assertFalse(status["upstream_probed"])
                self.assertFalse(status["claude_configuration_known"])

    async def test_missing_or_unknown_routes_do_not_report_a_provider_as_selected(self):
        for suppliers in (None, [{"id": "claude", "enabled": False, "business": None}],
                          [{"id": "claude", "enabled": True, "business": ["chat"]}] * 2,
                          [None, {"id": "kimi", "enabled": "true", "business": ["diagnosis"]}]):
            response = httpx.Response(200, json={"release": "free_product", "ai_open": True,
                                                "suppliers": suppliers})
            with mock.patch.object(httpx.AsyncClient, "get", new_callable=mock.AsyncMock, return_value=response):
                status = await admin_server._fetch_api_ai_readiness()
            self.assertEqual(status["claude_status"], "unavailable")
            self.assertEqual(status["kimi_status"], "unavailable")
            if suppliers is None or any(not isinstance(row, dict) for row in suppliers) or len(suppliers) == 2:
                self.assertIsNone(status["suppliers"])

    async def test_global_admission_closed_overrides_provider_availability(self):
        response = httpx.Response(200, json={"release": "free_product", "ai_open": False,
            "suppliers": [{"id": "claude", "group": "generation_models", "enabled": True, "business": ["chat"]}]})
        with mock.patch.object(httpx.AsyncClient, "get", new_callable=mock.AsyncMock, return_value=response):
            status = await admin_server._fetch_api_ai_readiness()
        self.assertEqual(status["claude_status"], "admission_closed")
        self.assertFalse(status["suppliers"][0]["enabled"])

    async def test_source_failure_and_malformed_status_do_not_imply_unconfigured(self):
        for response in (httpx.Response(503), httpx.Response(302),
                         httpx.Response(200, json={"release": "free_product", "ai_open": "true"}),
                         httpx.Response(200, json={"release": "website_and_accounts", "ai_open": False})):
            with mock.patch.object(httpx.AsyncClient, "get", new_callable=mock.AsyncMock, return_value=response):
                status = await admin_server._fetch_api_ai_readiness()
            self.assertEqual(status["kimi_status"], "unavailable")
            self.assertIn("source_error", status)
            self.assertFalse(status["upstream_probed"])

    async def test_history_failure_is_unknown_not_empty_or_healthy(self):
        with mock.patch.object(db, "fetchall", side_effect=RuntimeError("synthetic")), mock.patch.object(
                httpx.AsyncClient, "get", new_callable=mock.AsyncMock, side_effect=httpx.ConnectError("offline")):
            status = await admin_server._fetch_api_ai_readiness()
        self.assertIsNone(status["recent_usage"])
        self.assertEqual(status["usage_source"], "query_unavailable")

    async def test_amap_shared_status_is_read_only_and_does_not_enable_runtime(self):
        quota = {"status": "ready", "snapshot_is_realtime": False,
                 "runtime_activation_inferred": False, "snapshot": {"remaining": 49999}}
        reader = mock.Mock(return_value=quota)
        module = SimpleNamespace(read_status=reader, admit=mock.Mock(side_effect=AssertionError("admission forbidden")))
        response = httpx.Response(200, json={"release": "free_product", "ai_open": True,
            "suppliers": [{"id": "amap", "group": "data_tools", "enabled": False, "business": ["美食诊断"]}]})
        with mock.patch.dict(sys.modules, {"amap_quota": module}), mock.patch.object(
                httpx.AsyncClient, "get", new_callable=mock.AsyncMock, return_value=response) as get:
            status = await admin_server._fetch_api_ai_readiness()
        reader.assert_called_once_with(storage=db)
        module.admit.assert_not_called()
        get.assert_awaited_once_with("https://noteaipro.com/public/status")
        self.assertEqual(status["amap_quota"], quota)
        self.assertFalse(status["suppliers"][0]["enabled"])
        self.assertFalse(status["upstream_probed"])

    async def test_amap_status_failure_preserves_unknown_without_echoing_details(self):
        module = SimpleNamespace(read_status=mock.Mock(side_effect=RuntimeError("private connection details")))
        with mock.patch.dict(sys.modules, {"amap_quota": module}), mock.patch.object(
                httpx.AsyncClient, "get", new_callable=mock.AsyncMock, side_effect=httpx.ConnectError("offline")):
            status = await admin_server._fetch_api_ai_readiness()
        self.assertEqual(status["amap_quota"]["status"], "unavailable")
        self.assertIsNone(status["amap_quota"]["snapshot"])
        self.assertNotIn("private", json.dumps(status))

    async def test_actual_amap_status_reader_uses_only_shared_selects(self):
        import amap_quota
        bucket = {"account_scope": amap_quota.ACCOUNT_SCOPE, "service_group": amap_quota.SERVICE_GROUP,
                  "period": "2026-09", "period_start": "2026-08-31T16:00:00Z",
                  "period_end": "2026-09-30T16:00:00Z", "time_zone": "Asia/Shanghai",
                  "quota": 50000, "official_used": 1, "admitted_count": 2,
                  "observed_at": "2026-09-15T15:04:00Z", "owner_authorized_at": "2026-09-15T15:00:00Z",
                  "source": "synthetic_console_snapshot", "snapshot_sha256": "a" * 64,
                  "enterprise_certified": 1, "license_purchased": 0, "owner_risk_accepted": 1,
                  "exclusive_noteai_use": 1, "billing_observation_json": None}
        for prefix in ("account", "text", "detail"):
            bucket.update({prefix + "_block_code": None, prefix + "_block_until": None})
        queries = []
        def fetchone(query, *args):
            self.assertTrue(query.startswith("SELECT "))
            self.assertNotIn("FOR UPDATE", query)
            queries.append(query)
            return bucket if "amap_quota_buckets" in query else {"now": "2026-09-15T15:10:00Z"}
        def fetchall(query, *args):
            self.assertTrue(query.startswith("SELECT "))
            self.assertNotIn("FOR UPDATE", query)
            if "amap_quota_buckets" in query:
                queries.append(query)
                return [bucket]
            return []
        storage = SimpleNamespace(fetchone=fetchone, fetchall=fetchall)
        response = httpx.Response(200, json={"release": "free_product", "ai_open": True,
            "suppliers": [{"id": "amap", "group": "data_tools", "enabled": False, "business": ["美食诊断"]}]})
        with mock.patch.object(admin_server, "db", storage), mock.patch.object(amap_quota, "admit", side_effect=AssertionError("admission forbidden")), mock.patch.object(
                httpx.AsyncClient, "get", new_callable=mock.AsyncMock, return_value=response) as get:
            status = await admin_server._fetch_api_ai_readiness()
        self.assertEqual(len(queries), 3)
        self.assertEqual(status["amap_quota"]["status"], "ready")
        self.assertEqual(status["amap_quota"]["snapshot"]["remaining"], 49997)
        self.assertIsNone(status["amap_quota"]["snapshot"]["billing_observation"])
        self.assertFalse(status["suppliers"][0]["enabled"])
        get.assert_awaited_once_with("https://noteaipro.com/public/status")

    def test_cached_or_pending_observation_does_not_replace_last_actual_result(self):
        def observation(identity, time, status, *, cached=False, calls=1):
            return {"observation_id": identity, "provider": "amap", "observed_at": time,
                    "status": status, "cached": cached, "http_requests": calls,
                    "cli_invocations": 0, "cost_cny": None, "cost_status": "unknown"}
        success = observation("success", "2026-09-15T10:00:00Z", "matched")
        failed = observation("failed", "2026-09-15T11:00:00Z", "partial")
        failed["partial_errors"] = ["AMAP_BUSINESS_10003"]
        cached = observation("cached", "2026-09-15T12:00:00Z", "matched", cached=True, calls=0)
        pending = observation("pending", "2026-09-15T13:00:00Z", "result_pending", calls=None)
        def rows(query, *args):
            if "fact_observations_json FROM usage_records" in query:
                return [{"recorded_at": "2026-09-15T13:00:00Z", "operation": "diagnosis",
                         "fact_observations_json": json.dumps([success, failed, cached, pending])}]
            return [{"created_at": "2026-09-15T10:00:00Z", "provenance_json": json.dumps({"fact_observation": success})}]
        with mock.patch.object(db, "fetchall", side_effect=rows):
            history, coverage = admin_server._fact_usage_history()
        actual = history["amap"]
        self.assertEqual(actual["count"], 4)
        self.assertEqual(actual["latest"]["status"], "result_pending")
        self.assertEqual(actual["latest_actual_result"]["status"], "partial")
        self.assertEqual(actual["latest_actual_failure"]["partial_errors"], ["AMAP_BUSINESS_10003"])
        self.assertEqual(actual["latest_verified_success"]["observed_at"], success["observed_at"])
        self.assertEqual(actual["latest_actual_result"]["source"], "usage_records.fact_observations_json")
        self.assertEqual(coverage, "task_observations_and_legacy")

    async def test_admin_overview_exposes_explicit_system_status_and_legacy_booleans(self):
        with mock.patch.object(httpx.AsyncClient, "get", new_callable=mock.AsyncMock, side_effect=httpx.ConnectError("offline")):
            payload = await admin_server.admin_overview(admin={"username": "synthetic-admin"})

        system = payload["system"]
        self.assertEqual(system["ai_runtime"]["status"], "unavailable")
        self.assertEqual(system["ai_runtime"]["source"], "protected_status_unavailable")
        self.assertFalse(system["claude_configured"])
        self.assertFalse(system["kimi_configured"])
        self.assertEqual(system["database_backend"], "sqlite")
        self.assertTrue(system["database_ok"])
        self.assertNotIn("kimi_key_prefix", system)
        self.assertNotIn("db_size_mb", system)


if __name__ == "__main__":
    unittest.main()
