import importlib
import asyncio
import json
import sys
import tempfile
import unittest
from unittest import mock
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

    def test_call_details_preserve_audio_unknown_and_unlinked_history_without_payload(self):
        billing.record_free_usage('u-high', 'generate')
        usage_id = db.fetchone("SELECT id FROM usage_records WHERE user_id='u-high'")['id']
        provenance = json.dumps({'model':'doubao-seed-2-0-lite-260428', 'route':'/generate/stream',
            'modality':'video_audio', 'model_config_revision':2, 'cookie':'SECRET_SENTINEL',
            'task':'media_understanding','step':'video_audio_understanding','prompt_scope':'call_templates',
            'instruction_role':'user','instruction_sha256':'b'*64,'instruction_text':'SECRET_SENTINEL','missing_prompt_keys':[],
            'prompts':{'creator.travel':{'source':'managed_prompts','version':7,'sha256':'a'*64,'content':'SECRET_SENTINEL'}}})
        for call_id, state in [('linked-call','responded'), ('unknown-call','unknown')]:
            db.execute('INSERT INTO public_trial_calls(id,budget_id,user_id,request_hash,state,reserve_milli_cny,created_at,usage_record_id,provenance_json) VALUES(?,?,?,?,?,?,?,?,?)',
                (call_id,'website-free-product-20260912','u-high',call_id,state,0,'2026-09-14T00:00:00Z',usage_id,provenance))
        billing.record_model_usage('doubao','doubao-seed-2-0-lite-260428',tokens_in=100,tokens_out=20,
            audio_input_tokens=30,physical_call_id='linked-call')
        billing.record_model_usage('kimi','kimi-k2.6',tokens_in=100,tokens_out=20)
        detail = admin_server._admin_usage_call_details('u-high',usage_id)
        self.assertEqual(detail['status'],'available')
        self.assertEqual(len(detail['calls']),3)
        linked = next(c for c in detail['calls'] if c.get('call_id')=='linked-call')
        unknown = next(c for c in detail['calls'] if c.get('call_id')=='unknown-call')
        self.assertEqual(linked['audio_input_tokens'],30)
        self.assertEqual(linked['step'],'video_audio_understanding')
        self.assertEqual(linked['prompt_scope'],'call_templates')
        self.assertEqual(linked['instruction_role'],'user')
        self.assertEqual(linked['instruction_sha256'],'b'*64)
        self.assertEqual(admin_server._admin_call_provenance('{}')['prompt_scope'],'request_snapshot')
        self.assertGreater(linked['known_cost_rmb'],0)
        self.assertEqual(linked['loaded_prompt_versions'][0]['version'],7)
        self.assertIsNone(unknown['model'])
        self.assertIsNone(unknown['known_cost_rmb'])
        self.assertEqual(detail['calls'][-1]['binding'],'historical_model_record_only')
        self.assertNotIn('SECRET_SENTINEL',json.dumps(detail))
        self.assertEqual(admin_server._admin_usage_call_details('u-low',usage_id)['calls'],[])

    def test_detail_query_failure_is_not_empty_success(self):
        billing.record_free_usage('u-high','generate')
        with mock.patch.object(admin_server,'_admin_usage_call_details',side_effect=PermissionError):
            result=asyncio.run(admin_server.admin_user_detail('u-high',{}))
        self.assertEqual(result['recent_usage'][0]['call_details']['status'],'unavailable')


if __name__ == "__main__":
    unittest.main()
