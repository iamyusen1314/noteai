import sys
import tempfile
import unittest
from unittest import mock
import httpx
from pathlib import Path


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
                response = httpx.Response(200, json={"release": "free_product", "ai_open": admission})
                with mock.patch.object(httpx.AsyncClient, "get", new_callable=mock.AsyncMock, return_value=response) as get:
                    status = await admin_server._fetch_api_ai_readiness()
                get.assert_awaited_once_with("https://noteaipro.com/public/status")
                self.assertEqual(status["source"], "api_public_status")
                self.assertEqual(status["kimi_status"], "admission_open" if admission else "admission_closed")
                self.assertEqual(status["claude_status"], "not_in_public_route")
                self.assertFalse(status["upstream_probed"])
                self.assertFalse(status["claude_configuration_known"])

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
