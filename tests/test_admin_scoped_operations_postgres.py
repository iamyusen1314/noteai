"""Approved disposable PG16 only: exercise the real incremental Admin ACL."""
import json
import os
from pathlib import Path
import sys
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import db
import billing
import admin_entitlements
import admin_operations
import admin_prompts
import admin_tasks
import model_runtime_config
import durable_ai
from fastapi import HTTPException


@unittest.skipUnless(os.environ.get("NOTEAI_RUN_ADMIN_OPERATIONS_PG16") == "1", "explicit disposable PG16 run only")
class AdminOperationsPostgres(unittest.TestCase):
    def setUp(self):
        self.owner_url = os.environ["NOTEAI_TEST_POSTGRES_URL"]
        self.admin_url = os.environ["NOTEAI_TEST_ADMIN_POSTGRES_URL"]
        self.dispatcher_url = os.environ["NOTEAI_TEST_DISPATCHER_POSTGRES_URL"]
        self.env = patch.dict(os.environ, {"DATABASE_URL":self.owner_url, "PYTHON_DOTENV_DISABLED":"1"})
        self.env.start()
        self.uid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db.execute("INSERT INTO users(id,username,password_hash,password_salt,created_at) VALUES(?,?,?,?,?)",
                   (self.uid, "isolated_admin_ops_"+self.uid, "not-a-login", "isolated-salt", now))
        billing.get_subscription(self.uid)
        os.environ["DATABASE_URL"] = self.admin_url

    def tearDown(self):
        self.env.stop()

    def owner_query(self, query, params=()):
        with patch.dict(os.environ, {"DATABASE_URL":self.owner_url}):
            return db.fetchone(query, params)

    def gift(self, request_id, preview):
        return admin_entitlements.apply(self.uid, preview["payload"], actor="noteai_admin", request_id=request_id,
            reason="explicit isolated gift verification", expected=preview["expected"])

    def test_real_role_concurrent_same_id_and_stale_preview(self):
        p = admin_entitlements.preview(self.uid, {"action":"adjust_credits","source":"gift","amount":9})
        rid = str(uuid.uuid4())
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.gift(rid, p), range(2)))
        self.assertEqual(sorted(x["replayed"] for x in results), [False, True])
        self.assertEqual(self.owner_query("SELECT COUNT(*) AS n FROM credit_transactions WHERE user_id=?", (self.uid,))["n"], 1)
        self.assertEqual(self.owner_query("SELECT balance FROM credits WHERE user_id=?", (self.uid,))["balance"], 9)
        stale_id = str(uuid.uuid4())
        with self.assertRaises(HTTPException) as error:
            self.gift(stale_id, p)
        self.assertEqual(error.exception.status_code, 409)
        stored = db.fetchone("SELECT result_json FROM admin_operations WHERE id=?", (stale_id,))
        self.assertFalse(json.loads(stored["result_json"])["ok"])
        with patch.dict(os.environ, {"DATABASE_URL":self.owner_url}):
            self.assertEqual(billing.get_quota_status(self.uid)["wallet_credits_balance"], 9)

    def test_failed_callback_rolls_back_business_and_retains_result(self):
        p = admin_entitlements.preview(self.uid, {"action":"adjust_credits","source":"trial","amount":5})
        self.gift(str(uuid.uuid4()), p)
        rid = str(uuid.uuid4())
        def fail(tx):
            tx.execute("UPDATE credits SET balance=6 WHERE user_id=?", (self.uid,))
            raise HTTPException(409, "isolated declared failure")
        with self.assertRaises(HTTPException):
            admin_operations.execute(actor="noteai_admin", request_id=rid, action="test:rollback", target=self.uid,
                reason="isolated transaction recovery", payload={}, callback=fail)
        self.assertEqual(self.owner_query("SELECT balance FROM credits WHERE user_id=?", (self.uid,))["balance"], 5)
        self.assertFalse(json.loads(db.fetchone("SELECT result_json FROM admin_operations WHERE id=?", (rid,))["result_json"])["ok"])

    def test_wallet_only_legacy_user_keeps_subscription_absent(self):
        with patch.dict(os.environ, {"DATABASE_URL":self.owner_url}):
            db.execute("DELETE FROM subscriptions WHERE user_id=?", (self.uid,))
        payload = {"action":"adjust_credits","source":"gift","amount":1}
        p = admin_entitlements.preview(self.uid, payload)
        rid = str(uuid.uuid4())
        self.gift(rid, p)
        self.assertTrue(self.gift(rid, p)["replayed"])
        self.gift(str(uuid.uuid4()), admin_entitlements.preview(self.uid, {**payload,"amount":-1}))
        self.assertEqual(self.owner_query("SELECT balance FROM credits WHERE user_id=?",(self.uid,))["balance"],0)
        self.assertEqual(self.owner_query("SELECT COUNT(*) AS n FROM subscriptions WHERE user_id=?",(self.uid,))["n"],0)
        with self.assertRaises(HTTPException) as denied:
            admin_entitlements.preview(self.uid,{"action":"set_membership","source":"gift","tier":"free"})
        self.assertEqual(denied.exception.status_code,409)
        p = admin_entitlements.preview(self.uid,payload)
        with patch.dict(os.environ,{"DATABASE_URL":self.owner_url}):
            billing.get_subscription(self.uid)
        with self.assertRaises(HTTPException) as stale:
            self.gift(str(uuid.uuid4()),p)
        self.assertEqual(stale.exception.status_code,409)

    def test_role_denies_identity_cash_secret_and_record_rewrite(self):
        queries = [
            ("UPDATE users SET username='not-permitted' WHERE id=?", (self.uid,)),
            ("UPDATE subscriptions SET used_monthly_credits=0 WHERE user_id=?", (self.uid,)),
            ("UPDATE credits SET total_purchased=99 WHERE user_id=?", (self.uid,)),
            ("INSERT INTO credit_transactions(id,user_id,type,amount,balance_after,description,paid_rmb,recorded_at) VALUES(?,?,'gift',1,1,'invalid',0,?)", (str(uuid.uuid4()),self.uid,datetime.now(timezone.utc).isoformat())),
            ("INSERT INTO system_settings(key,value_json,is_secret,updated_at) VALUES('admin_model_config_secret_test','{}',1,'test')",()),
            ("INSERT INTO system_settings(key,value_json,is_secret,updated_at) VALUES('unapproved_test_key','{}',0,'test')",()),
            ("UPDATE admin_operations SET reason='rewritten'",()),
            ("DELETE FROM admin_operations",()),
            ("UPDATE payment_orders SET payment_status='paid'",()),
        ]
        for query, params in queries:
            with self.subTest(query=query.split()[0:3]):
                with self.assertRaises(Exception) as denied:
                    db.execute(query, params)
                self.assertEqual(getattr(denied.exception, "sqlstate", None), "42501")
        with db.transaction(write=True) as tx:
            tx.execute("SELECT public.noteai_admin_lock_user(?)", (self.uid,))
            self.assertEqual(tx.fetchone("SELECT id FROM users WHERE id=?", (self.uid,))["id"], self.uid)

    def test_real_prompt_draft_publication_and_nonsecret_model_restore(self):
        key = "chat_system"
        p = admin_prompts.detail(key)
        draft = str(uuid.uuid4())
        admin_prompts.draft(key, "explicit isolated PG16 prompt", actor="noteai_admin", request_id=draft,
            reason="isolated prompt edit", expected_version=p["version"], expected_draft_id=(p["draft"] or {}).get("draft_id"))
        self.assertEqual(admin_prompts.detail(key)["version"], p["version"])
        result = admin_prompts.publish(key, actor="noteai_admin", request_id=str(uuid.uuid4()), reason="isolated publish",
            draft_id=draft, expected_version=p["version"])
        self.assertEqual(result["after"]["version"], p["version"]+1)
        admin_prompts.publish(key, actor="noteai_admin", request_id=str(uuid.uuid4()), reason="isolated restore",
            draft_id=None, expected_version=p["version"]+1, rollback_version=p["version"])
        current = model_runtime_config.read("test")
        config = model_runtime_config.defaults();config["chat"]["max_tokens"] = 512
        for action in ("draft", "activate", "restore"):
            result = model_runtime_config.change(action, "test", actor="noteai_admin", request_id=str(uuid.uuid4()),
                reason="isolated model config", expected=current["revision"], config=config if action=="draft" else None)
            current = result["after"]
        self.assertEqual(current["active"]["chat"]["max_tokens"], 32768)

    def admit(self, scope, ago=0):
        with patch.dict(os.environ, {"DATABASE_URL":self.owner_url,"NOTEAI_DURABLE_AI_SUSPENDED":"0"}):
            now = datetime.now(timezone.utc)-timedelta(seconds=ago)
            result = durable_ai.admit_job(user_id=self.uid, operation="analyze", request_id=str(uuid.uuid4()),
                payload={"content":"isolated marked task","domain":"美食"}, store=durable_ai.InMemoryPayloadStore(),
                admin_control_scope=scope, now=now)
            return result["operation_id"], now

    def task_change(self, op, action, preview=None, rid=None, **kw):
        preview = preview or admin_tasks.detail(op)
        return admin_tasks.change(op, action, actor="noteai_admin", request_id=rid or str(uuid.uuid4()),
            reason="isolated original task control", expected=preview["expected"], **kw)

    def test_pause_resume_schedule_real_dispatcher_and_protected_sql_denial(self):
        op, _ = self.admit("ordinary")
        self.task_change(op, "pause")
        with patch.dict(os.environ, {"DATABASE_URL":self.dispatcher_url}):
            self.assertIsNone(durable_ai.claim_outbox(operation_id=op))
            other = durable_ai.claim_outbox()
            self.assertTrue(other is None or other.operation_id != op)
        self.task_change(op, "schedule", priority=2, available_at=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat())
        self.task_change(op, "resume")
        with patch.dict(os.environ, {"DATABASE_URL":self.dispatcher_url}):
            self.assertIsNone(durable_ai.claim_outbox(operation_id=op))
            lease = durable_ai.claim_outbox(operation_id=op, now=datetime.now(timezone.utc)+timedelta(minutes=6))
            self.assertEqual(lease.operation_id, op)
        protected, _ = self.admit("protected")
        with self.assertRaises(Exception):
            db.execute("UPDATE ai_operations SET operator_paused=1 WHERE id=?", (protected,))
        with self.assertRaises(Exception):
            db.execute("UPDATE ai_operations SET admin_control_scope='ordinary' WHERE id=?", (protected,))

    def test_expired_retry_preserves_original_fence_and_billing(self):
        op, now = self.admit("ordinary", ago=300)
        with patch.dict(os.environ, {"DATABASE_URL":self.owner_url}):
            dispatch = durable_ai.claim_outbox(operation_id=op, now=now+timedelta(seconds=1))
            durable_ai.mark_outbox_delivered(dispatch, now=now+timedelta(seconds=2))
            worker = durable_ai.claim_delivered_operation(op, lease_seconds=30, now=now+timedelta(seconds=3))
        before = admin_tasks.detail(op);rid = str(uuid.uuid4())
        r = self.task_change(op, "retry", before, rid)
        self.assertTrue(self.task_change(op, "retry", before, rid)["replayed"])
        self.assertEqual(r["after"]["lease_fence"], worker.fence)
        self.assertEqual(r["after"]["dispatch_attempts"], 1)
        self.assertEqual(r["after"]["provider_attempt_rows"], 0)
        self.assertEqual(r["after"]["billing_state"], "charged")

    def test_competing_retry_intents_only_one_requeues(self):
        op, now = self.admit("ordinary", ago=300)
        with patch.dict(os.environ, {"DATABASE_URL":self.owner_url}):
            dispatch = durable_ai.claim_outbox(operation_id=op, now=now+timedelta(seconds=1))
            durable_ai.mark_outbox_delivered(dispatch, now=now+timedelta(seconds=2))
            durable_ai.claim_delivered_operation(op, lease_seconds=30, now=now+timedelta(seconds=3))
        before = admin_tasks.detail(op)
        def attempt(rid):
            try:
                return self.task_change(op, "retry", before, rid)
            except HTTPException as error:
                return error.status_code
        ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, ids))
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
        self.assertEqual(results.count(409), 1)
        winner = ids[next(i for i, r in enumerate(results) if isinstance(r, dict))]
        self.assertTrue(self.task_change(op, "retry", before, winner)["replayed"])
        after = admin_tasks.detail(op)["task"]
        self.assertEqual(after["outbox_state"], "pending")
        self.assertEqual(after["dispatch_attempts"], 1)
        self.assertEqual(after["provider_attempt_rows"], 0)

    def test_worker_claim_first_rejects_stale_pause(self):
        op, now = self.admit("ordinary")
        preview = admin_tasks.detail(op)
        with patch.dict(os.environ, {"DATABASE_URL":self.owner_url}):
            dispatch = durable_ai.claim_outbox(operation_id=op, now=now+timedelta(seconds=1))
            durable_ai.mark_outbox_delivered(dispatch, now=now+timedelta(seconds=2))
        worker_url = self.admin_url.replace("noteai_admin_runtime:", "noteai_ai_worker:")
        with patch.dict(os.environ, {"DATABASE_URL":worker_url}):
            worker = durable_ai.claim_delivered_operation(op, lease_seconds=60, now=now+timedelta(seconds=3))
            self.assertEqual(worker.operation_id, op)
        with self.assertRaises(HTTPException) as denied:
            self.task_change(op, "pause", preview)
        self.assertEqual(denied.exception.status_code, 409)
        self.assertFalse(admin_tasks.detail(op)["task"]["operator_paused"])

    def test_http_owner_and_viewer_boundaries_with_real_role(self):
        from fastapi.testclient import TestClient
        import admin_server, admin_auth, time
        with patch.dict(os.environ, {"NOTEAI_DEPLOYMENT_STAGE":"production", "ADMIN_USERNAME":"noteai_admin",
                "ADMIN_PASSWORD":"disposable-admin-test-password-only", "NOTEAI_ADMIN_OPERATIONS_ENABLED":"1",
                "NOTEAI_ADMIN_OPERATION_SCOPES":"entitlement_management,prompt_mutation,model_configuration,task_management"}):
            client = TestClient(admin_server.admin_app)
            path = "/admin/users/"+self.uid+"/entitlements/preview"
            payload = {"action":"adjust_credits","source":"trial","amount":3}
            self.assertEqual(client.post(path, json=payload).status_code, 403)
            self.assertEqual(client.post(path, json=payload, headers={"Authorization":"Bearer user_explicit_isolated"}).status_code, 403)
            viewer = "admin_"+str(uuid.uuid4())
            db.execute("INSERT INTO admin_sessions(token,username,created_at,expires_at) VALUES(?,?,?,?)",
                (admin_auth._token_digest(viewer), "isolated_viewer",time.time(),time.time()+60))
            try:
                denied = client.post(path, json=payload, headers={"Authorization":"Bearer "+viewer})
                self.assertIn(denied.status_code, (403,409))
                login = client.post("/admin/login", json={"username":"noteai_admin","password":os.environ["ADMIN_PASSWORD"]})
                self.assertEqual(login.status_code,200)
                token = login.json()["token"];headers={"Authorization":"Bearer "+token}
                try:
                    preview = client.post(path, json=payload, headers=headers)
                    self.assertEqual(preview.status_code,200,preview.text)
                    p = preview.json();rid=str(uuid.uuid4())
                    body = {"request_id":rid,"reason":"isolated HTTP owner flow","expected":p["expected"],"payload":payload}
                    result = client.post(path.replace("preview","apply"), json=body, headers=headers)
                    self.assertEqual(result.status_code,200,result.text)
                    again = client.post(path.replace("preview","apply"),json=body,headers=headers)
                    self.assertTrue(again.json()["replayed"])
                    detail = client.get("/admin/users/"+self.uid,headers=headers)
                    self.assertEqual(detail.status_code,200,detail.text)
                    self.assertEqual(detail.json()["quota"]["wallet_balance"],3)
                    self.assertEqual(client.get("/admin/prompts",headers=headers).status_code,200)
                    self.assertEqual(client.get("/admin/tasks",headers=headers).status_code,200)
                    self.assertEqual(client.get("/admin/model-config?scope=test",headers=headers).status_code,200)
                finally:
                    self.assertEqual(client.post("/admin/logout",headers=headers).status_code,200)
                    self.assertEqual(client.get("/admin/tasks",headers=headers).status_code,403)
            finally:
                admin_auth.admin_logout(viewer)


if __name__ == "__main__":
    unittest.main()
