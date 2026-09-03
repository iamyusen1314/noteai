import sys
import tempfile
import unittest
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

    async def test_provider_status_is_safe_unavailable_without_protected_source(self):
        status = await admin_server._fetch_api_ai_readiness()

        self.assertEqual(status, {
            "status": "unavailable",
            "source": "protected_status_unavailable",
            "claude_status": "unavailable",
            "kimi_status": "unavailable",
            "claude_configured": False,
            "kimi_configured": False,
        })

    async def test_admin_overview_exposes_explicit_system_status_and_legacy_booleans(self):
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
