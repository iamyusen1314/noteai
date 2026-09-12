"""Owner operations on disposable storage; never send provider requests."""
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

os.environ["PYTHON_DOTENV_DISABLED"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import db
import admin_entitlements as entitlements
import admin_operations as operations
import admin_prompts as prompts
import billing
import admin_tasks
import durable_ai
import ai_operations
import model_runtime_config
import prompt_manager
from fastapi import HTTPException


class ScopedAdminOperations(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"DATABASE_URL": "", "PYTHON_DOTENV_DISABLED": "1"})
        self.env.start()
        self.path = patch.object(db, "_DB_PATH", Path(self.temp.name) / "test.sqlite3")
        self.path.start()
        db.init_db()
        self.uid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db.execute("INSERT INTO users(id,username,password_hash,password_salt,created_at) VALUES(?,?,?,?,?)", (self.uid, "test_admin_ops", "test-only-no-login", "test-only-salt", now))
        billing.get_subscription(self.uid)

    def tearDown(self):
        prompt_manager._cache = {}
        prompt_manager._cache_ts = 0
        self.path.stop()
        self.env.stop()
        self.temp.cleanup()

    def adjust(self, payload, request_id=None, expected=None):
        p = entitlements.preview(self.uid, payload)
        return entitlements.apply(self.uid, payload, actor="noteai_admin", request_id=request_id or str(uuid.uuid4()),
                                  reason="明确标记的测试调整", expected=expected or p["expected"])

    def test_gift_replay_and_changed_binding_do_not_duplicate_or_fake_cash(self):
        p = {"action": "adjust_credits", "source": "gift", "amount": 9}
        before = entitlements.preview(self.uid, p)
        rid = str(uuid.uuid4())
        r = self.adjust(p, rid, before["expected"])
        r2 = self.adjust(p, rid, before["expected"])
        self.assertEqual(r["after"]["wallet_balance"], 9)
        self.assertTrue(r2["replayed"])
        self.assertEqual(billing.get_quota_status(self.uid)["wallet_credits_balance"], 9)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM credit_transactions WHERE user_id=?", (self.uid,))["n"], 1)
        self.assertEqual(db.fetchone("SELECT SUM(paid_rmb) AS cash FROM credit_transactions WHERE user_id=?", (self.uid,))["cash"], 0)
        with self.assertRaises(HTTPException):
            self.adjust({**p, "amount": 10}, rid, before["expected"])
        with self.assertRaises(HTTPException):
            self.adjust(p, expected=before["expected"])

    def test_noncash_recovery_and_no_negative_or_unknown_balance(self):
        self.adjust({"action": "adjust_credits", "source": "trial", "amount": 9})
        self.adjust({"action": "adjust_credits", "source": "compensation", "amount": -4})
        self.assertEqual(billing.get_quota_status(self.uid)["wallet_credits_balance"], 5)
        with self.assertRaises(HTTPException):
            self.adjust({"action": "adjust_credits", "source": "gift", "amount": -6})
        for amount in ("NaN", "Infinity", 0, 10001, "0.001"):
            with self.assertRaises(HTTPException):
                entitlements.preview(self.uid, {"action": "adjust_credits", "source": "gift", "amount": amount})

    def test_wallet_without_subscription_and_new_subscription_invalidates_preview(self):
        db.execute("DELETE FROM subscriptions WHERE user_id=?", (self.uid,))
        payload = {"action": "adjust_credits", "source": "gift", "amount": 1}
        p = entitlements.preview(self.uid, payload)
        self.assertIsNone(p["before"]["subscription_id"])
        rid = str(uuid.uuid4())
        self.adjust(payload, rid, p["expected"])
        self.assertTrue(self.adjust(payload, rid, p["expected"])["replayed"])
        self.adjust({**payload, "amount": -1})
        self.assertEqual(db.fetchone("SELECT balance FROM credits WHERE user_id=?", (self.uid,))["balance"], 0)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM subscriptions WHERE user_id=?", (self.uid,))["n"], 0)
        for change in ({"action":"set_membership","source":"gift","tier":"free"},
                       {"action":"set_features","source":"gift","features":{"score":False}}):
            with self.assertRaises(HTTPException) as denied:
                entitlements.preview(self.uid, change)
            self.assertEqual(denied.exception.status_code, 409)
        p = entitlements.preview(self.uid, payload)
        billing.get_subscription(self.uid)
        with self.assertRaises(HTTPException) as stale:
            self.adjust(payload, expected=p["expected"])
        self.assertEqual(stale.exception.status_code, 409)

    def test_membership_preserves_usage_and_feature_denial_applies_to_free_route(self):
        sub = billing.get_subscription(self.uid)
        db.execute("UPDATE subscriptions SET used_monthly_credits=6 WHERE id=?", (sub["id"],))
        end = (datetime.now(timezone.utc) + timedelta(days=20)).isoformat()
        self.adjust({"action": "set_membership", "source": "compensation", "tier": "pro", "expires_at": end})
        q = billing.get_quota_status(self.uid)
        self.assertEqual(q["monthly_credits_used"], 6)
        self.assertEqual(q["entitlement_source"], "compensation")
        self.adjust({"action": "set_features", "source": "trial", "features": {"score": False}})
        with self.assertRaises(HTTPException) as denied:
            with db.transaction(write=True) as tx:
                billing.check_and_deduct_in_transaction(tx, self.uid, "score")
        self.assertEqual(denied.exception.status_code, 403)
        before = db.fetchone("SELECT COUNT(*) AS n FROM usage_records")["n"]
        with self.assertRaises(HTTPException) as denied:
            billing.record_free_usage(self.uid, "score")
        self.assertEqual(denied.exception.status_code, 403)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM usage_records")["n"], before)

    def test_draft_does_not_publish_publish_reads_and_restore_is_atomic(self):
        key = "chat_system"
        d = prompts.detail(key)
        self.assertEqual(d["source"], "baseline_not_published")
        rid = str(uuid.uuid4())
        prompts.draft(key, "isolated test draft", actor="noteai_admin", request_id=rid, reason="测试草稿与发布", expected_version=0)
        self.assertEqual(prompt_manager.get(key, "unchanged"), "unchanged")
        pub = str(uuid.uuid4())
        r = prompts.publish(key, actor="noteai_admin", request_id=pub, reason="测试正式加载路径", draft_id=rid, expected_version=0)
        prompt_manager.reload()
        self.assertEqual(prompt_manager.get(key), "isolated test draft")
        self.assertEqual(r["after"]["version"], 1)
        self.assertTrue(prompts.publish(key, actor="noteai_admin", request_id=pub, reason="测试正式加载路径", draft_id=rid, expected_version=0)["replayed"])
        rid2 = str(uuid.uuid4())
        prompts.draft(key, "second isolated revision", actor="noteai_admin", request_id=rid2, reason="测试第二次草稿", expected_version=1, expected_draft_id=rid)
        prompts.publish(key, actor="noteai_admin", request_id=str(uuid.uuid4()), reason="测试第二次发布", draft_id=rid2, expected_version=1)
        prompts.publish(key, actor="noteai_admin", request_id=str(uuid.uuid4()), reason="测试恢复上一版本", draft_id=None, expected_version=2, rollback_version=1)
        prompt_manager.reload()
        self.assertEqual(prompt_manager.get(key), "isolated test draft")
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM prompt_history WHERE prompt_key=?", (key,))["n"], 3)

    def test_model_draft_activate_restore_and_inflight_snapshot(self):
        with patch.dict(os.environ, {"NOTEAI_MODEL_CONFIG_ENABLED": "1"}):
            config = model_runtime_config.defaults()
            config["chat"]["max_tokens"] = 512
            def change(action, revision, value=None):
                return model_runtime_config.change(action, "test", actor="noteai_admin", request_id=str(uuid.uuid4()),
                    reason="隔离模型配置测试", expected=revision, config=value)
            change("draft", 0, config)
            self.assertEqual(model_runtime_config.resolve("chat", "kimi-k2.6", 16000, scope="test")[1], 16000)
            change("activate", 1)
            self.assertEqual(model_runtime_config.resolve("chat", "kimi-k2.6", 16000, scope="test")[1], 512)
            self.assertEqual(model_runtime_config.resolve("chat", "kimi-k2.6", 16000)[1], 16000)
            change("restore", 2)
            self.assertEqual(model_runtime_config.resolve("chat", "kimi-k2.6", 16000, scope="test")[1], 16000)
            with self.assertRaises(HTTPException):
                change("activate", 1)
            import public_product
            config["semantic"]["enabled"] = False
            invocation = public_product.Invocation(self.uid, "isolated-request", model_config={"active":config})
            token = public_product._invocation.set(invocation)
            try:
                with patch.dict(os.environ, {"NOTEAI_PUBLIC_PRODUCT":"1"}):
                    with self.assertRaises(public_product.TrialProviderStopped):
                        model_runtime_config.resolve("semantic", "kimi-k2.6", 300)
                    with self.assertRaises(public_product.TrialProviderStopped):
                        public_product.assert_result_known()
                self.assertEqual(invocation.failure, "PUBLIC_MODEL_ROUTE_PAUSED")
            finally:
                public_product._invocation.reset(token)

    def admit_task(self, *, scope="ordinary", ago=0):
        store = durable_ai.InMemoryPayloadStore()
        now = datetime.now(timezone.utc) - timedelta(seconds=ago)
        with patch.dict(os.environ, {"NOTEAI_DURABLE_AI_SUSPENDED":"0"}):
            result = durable_ai.admit_job(user_id=self.uid, operation="analyze", request_id=str(uuid.uuid4()),
                payload={"domain":"美食","content":"explicit isolated admin task"}, store=store, now=now,
                admin_control_scope=scope)
        return result["operation_id"], now

    def task_change(self, operation_id, action, request_id=None, preview=None, **kwargs):
        preview = preview or admin_tasks.detail(operation_id)
        return admin_tasks.change(operation_id, action, actor="noteai_admin", request_id=request_id or str(uuid.uuid4()),
            reason="明确标记的隔离任务验证", expected=preview["expected"], **kwargs)

    def test_pause_blocks_exact_general_worker_claim_and_resume_preserves_id(self):
        op, _ = self.admit_task()
        self.task_change(op, "pause")
        self.assertIsNone(durable_ai.claim_outbox(operation_id=op))
        self.assertIsNone(durable_ai.claim_outbox())
        self.assertIsNone(ai_operations.claim_operation(op, lease_seconds=30))
        self.assertIsNone(ai_operations.claim_next_operation(lease_seconds=30))
        self.task_change(op, "resume")
        lease = durable_ai.claim_outbox(operation_id=op)
        self.assertEqual(lease.operation_id, op)
        self.assertTrue(durable_ai.mark_outbox_delivered(lease))
        worker = durable_ai.claim_delivered_operation(op, lease_seconds=30)
        self.assertEqual(worker.operation_id, op)
        self.assertIsNone(durable_ai.claim_delivered_operation(op, lease_seconds=30))
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM ai_provider_attempts")["n"], 0)

    def test_retry_only_original_unstarted_expired_operation_and_never_protected(self):
        op, now = self.admit_task(ago=300)
        lease = durable_ai.claim_outbox(operation_id=op, now=now+timedelta(seconds=1))
        durable_ai.mark_outbox_delivered(lease, now=now+timedelta(seconds=2))
        worker = durable_ai.claim_delivered_operation(op, lease_seconds=30, now=now+timedelta(seconds=3))
        original = admin_tasks.detail(op)
        self.assertEqual(original["allowed_actions"], ["retry"])
        request_id = str(uuid.uuid4())
        r = self.task_change(op, "retry", request_id, original)
        replay = self.task_change(op, "retry", request_id, original)
        self.assertTrue(replay["replayed"])
        self.assertEqual(r["after"]["dispatch_attempts"], 1)
        self.assertEqual(r["after"]["lease_fence"], worker.fence)
        self.assertEqual(r["after"]["provider_attempt_count"], 0)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS n FROM ai_operations")["n"], 1)
        protected, _ = self.admit_task(scope="protected")
        self.assertEqual(admin_tasks.detail(protected)["allowed_actions"], [])
        with self.assertRaises(HTTPException):
            self.task_change(protected, "pause")


if __name__ == "__main__":
    unittest.main()
