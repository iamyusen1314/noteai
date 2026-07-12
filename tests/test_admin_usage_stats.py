import importlib
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

db = importlib.import_module("db")
billing = importlib.import_module("billing")
admin_server = importlib.import_module("admin_server")


class AdminUsageStatsTests(unittest.TestCase):
    def setUp(self):
        self._old_db_path = db._DB_PATH
        self._tmpdir = tempfile.TemporaryDirectory()
        db._DB_PATH = Path(self._tmpdir.name) / "noteai.db"
        db.init_db()
        billing.clear_active_usage()
        for user_id, username in (("u-high", "high_cost"), ("u-low", "low_cost")):
            db.execute(
                "INSERT INTO users(id,username,email,password_hash,password_salt,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (user_id, username, f"{user_id}@example.com", "hash", "salt", "2026-07-12T00:00:00+00:00"),
            )

    def tearDown(self):
        billing.clear_active_usage()
        db._DB_PATH = self._old_db_path
        self._tmpdir.cleanup()

    def test_sqlite_top_users_returns_grouped_username_and_totals(self):
        billing.record_free_usage("u-high", "generate", tokens_in=1200, tokens_out=300)
        billing.record_free_usage("u-low", "score", tokens_in=40, tokens_out=10)
        billing.record_free_usage("u-low", "score", tokens_in=50, tokens_out=20)

        payload = admin_server.build_usage_stats_payload(days=30)

        self.assertEqual(
            payload["top_users"],
            [
                {"username": "high_cost", "ops": 1, "tokens": 1500, "cost": 1.28},
                {"username": "low_cost", "ops": 2, "tokens": 120, "cost": 0.022},
            ],
        )

    def test_admin_usage_page_handles_non_ok_response_without_raw_error(self):
        html = (MODEL_DIR / "admin.html").read_text(encoding="utf-8")

        self.assertIn("if (!r.ok) throw new Error('usage stats request failed');", html)
        self.assertIn("用量数据加载失败，请稍后重试。", html)
        self.assertIn("暂无可显示数据", html)

    def test_admin_user_detail_rejects_missing_and_ordinary_user_tokens(self):
        client = TestClient(admin_server.admin_app)

        missing = client.get("/admin/users/u-high")
        ordinary = client.get(
            "/admin/users/u-high",
            headers={"Authorization": "Bearer ordinary-user-token"},
        )

        self.assertEqual(missing.status_code, 403)
        self.assertEqual(ordinary.status_code, 403)


if __name__ == "__main__":
    unittest.main()
