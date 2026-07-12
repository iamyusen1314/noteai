import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODEL_DIR = Path(__file__).resolve().parents[1] / "model"
sys.path.insert(0, str(MODEL_DIR))

import admin_server
import db


class _FailingAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def get(self, url, **kwargs):
        raise admin_server.httpx.ConnectError("PRIVATE_UPSTREAM_DETAIL")


class _StaticResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _StaticAsyncClient:
    response = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def get(self, url, **kwargs):
        return self.response


class AdminSystemStatusTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._old_db_path = db._DB_PATH
        self._tmpdir = tempfile.TemporaryDirectory()
        db._DB_PATH = Path(self._tmpdir.name) / "noteai.db"
        db.init_db()

    def tearDown(self):
        db._DB_PATH = self._old_db_path
        self._tmpdir.cleanup()

    def test_fixed_ai_readiness_fields_report_configured(self):
        status = admin_server._parse_api_ai_readiness({
            "checks": {
                "ai": {
                    "ok": True,
                    "claude_configured": True,
                    "moonshot_configured": True,
                }
            }
        })
        self.assertEqual(status, {
            "status": "configured",
            "source": "api_readiness",
            "claude_status": "configured",
            "kimi_status": "configured",
            "claude_configured": True,
            "kimi_configured": True,
        })

    def test_fixed_ai_readiness_fields_report_provider_not_configured(self):
        status = admin_server._parse_api_ai_readiness({
            "checks": {
                "ai": {
                    "ok": False,
                    "claude_configured": True,
                    "moonshot_configured": False,
                }
            }
        })
        self.assertEqual(status["status"], "not_configured")
        self.assertEqual(status["claude_status"], "configured")
        self.assertEqual(status["kimi_status"], "not_configured")
        self.assertTrue(status["claude_configured"])
        self.assertFalse(status["kimi_configured"])

    def test_missing_or_inconsistent_readiness_fields_are_unavailable(self):
        for payload in (
            {},
            {"checks": {"ai": {}}},
            {"checks": {"ai": {"ok": True, "claude_configured": True}}},
            {"checks": {"ai": {
                "ok": False,
                "claude_configured": True,
                "moonshot_configured": True,
            }}},
        ):
            with self.subTest(payload=payload):
                status = admin_server._parse_api_ai_readiness(payload)
                self.assertEqual(status["status"], "unavailable")
                self.assertEqual(status["claude_status"], "unavailable")
                self.assertEqual(status["kimi_status"], "unavailable")
                self.assertFalse(status["claude_configured"])
                self.assertFalse(status["kimi_configured"])
                self.assertNotIn("error", status)

    async def test_unreachable_readiness_returns_fixed_unavailable_without_details(self):
        with (
            mock.patch.dict(os.environ, {
                "NOTEAI_API_READINESS_URL": "https://api.example.invalid/health/ready",
            }, clear=False),
            mock.patch.object(admin_server.httpx, "AsyncClient", _FailingAsyncClient),
        ):
            status = await admin_server._fetch_api_ai_readiness()
        self.assertEqual(status["status"], "unavailable")
        self.assertEqual(status["source"], "api_readiness")
        self.assertNotIn("PRIVATE_UPSTREAM_DETAIL", repr(status))
        self.assertNotIn("url", status)

    async def test_503_with_valid_fixed_ai_payload_reports_provider_configuration(self):
        _StaticAsyncClient.response = _StaticResponse(503, {
            "status": "not_ready",
            "checks": {
                "ai": {
                    "ok": False,
                    "claude_configured": True,
                    "moonshot_configured": False,
                }
            },
        })
        with (
            mock.patch.dict(os.environ, {
                "NOTEAI_API_READINESS_URL": "https://api.example.invalid/health/ready",
            }, clear=False),
            mock.patch.object(admin_server.httpx, "AsyncClient", _StaticAsyncClient),
        ):
            status = await admin_server._fetch_api_ai_readiness()
        self.assertEqual(status["status"], "not_configured")
        self.assertEqual(status["claude_status"], "configured")
        self.assertEqual(status["kimi_status"], "not_configured")

    async def test_503_with_malformed_or_inconsistent_ai_payload_is_unavailable(self):
        payloads = (
            {"status": "not_ready", "checks": {}},
            {"status": "not_ready", "checks": {"ai": {
                "ok": False,
                "claude_configured": True,
                "moonshot_configured": True,
            }}},
            "PRIVATE_UPSTREAM_BODY",
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                _StaticAsyncClient.response = _StaticResponse(503, payload)
                with (
                    mock.patch.dict(os.environ, {
                        "NOTEAI_API_READINESS_URL": "https://api.example.invalid/health/ready",
                    }, clear=False),
                    mock.patch.object(admin_server.httpx, "AsyncClient", _StaticAsyncClient),
                ):
                    status = await admin_server._fetch_api_ai_readiness()
                self.assertEqual(status["status"], "unavailable")
                self.assertNotIn("PRIVATE_UPSTREAM_BODY", repr(status))
                self.assertNotIn("url", status)

    async def test_admin_overview_exposes_explicit_system_status_and_legacy_booleans(self):
        ai_status = {
            "status": "configured",
            "source": "api_readiness",
            "claude_status": "configured",
            "kimi_status": "configured",
            "claude_configured": True,
            "kimi_configured": True,
        }
        with mock.patch.object(
            admin_server,
            "_fetch_api_ai_readiness",
            mock.AsyncMock(return_value=ai_status),
        ):
            payload = await admin_server.admin_overview(admin={"username": "synthetic-admin"})

        system = payload["system"]
        self.assertEqual(system["ai_runtime"], ai_status)
        self.assertTrue(system["claude_configured"])
        self.assertTrue(system["kimi_configured"])
        self.assertEqual(system["database_backend"], "sqlite")
        self.assertTrue(system["database_ok"])
        self.assertNotIn("kimi_key_prefix", system)
        self.assertNotIn("db_size_mb", system)


if __name__ == "__main__":
    unittest.main()
