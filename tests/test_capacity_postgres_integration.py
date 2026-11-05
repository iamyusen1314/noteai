"""Opt-in owned PG16: real API role/schema, synthetic pre-wire reservations only.

The private driver applies the existing migrations, cover feature and original
App grants. These checks make no HTTP call and are not provider/Linux load GO.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import threading
import unittest
from unittest import mock
from urllib.parse import urlencode
import uuid

from PIL import Image
import billing
import cover_jobs
import db
import model_admission as admission
import model_capacity as capacity
import postdelivery
import private_storage
import public_product as public

LITE = "doubao-seed-2-0-lite-260428"


@unittest.skipUnless(os.environ.get("NOTEAI_CAPACITY_PG_INTEGRATION_TEST") == "1",
                     "explicit owned full-schema PG16 Unix socket required")
class CapacityPostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        socket = Path(os.environ["NOTEAI_CAPACITY_PG_SOCKET"])
        database = os.environ["NOTEAI_CAPACITY_PG_DATABASE"]
        marker = socket.parent / "owned-capacity-integration.json"
        assert socket.is_dir() and socket.parent.name.startswith("na-capacity-int-pg16-")
        assert database.startswith("noteai_capacity_int_")
        assert json.loads(marker.read_text()) == {"database": database, "socket": str(socket), "port": 19432}
        cls.environment = mock.patch.dict(os.environ, {
            "DATABASE_URL": "postgresql://noteai_app@/" + database + "?" + urlencode({
                "host": str(socket), "port": "19432", "connect_timeout": "5"}),
            "PYTHON_DOTENV_DISABLED": "1", "NOTEAI_PUBLIC_PRODUCT": "1",
            "NOTEAI_POSTDELIVERY_SETTLEMENT": "1", "NOTEAI_FACT_SEARCH": "0",
            "NOTEAI_MODEL_CAPACITY_ENABLED": "1", "NOTEAI_MODEL_REMOTE_CONCURRENCY": "16",
            "NOTEAI_MODEL_CAPACITY_MOONSHOT_ENABLED": "0"})
        cls.environment.start()
        try:
            row = db.fetchone("SELECT current_user AS role,current_database() AS db,"
                "inet_server_addr() AS address,current_setting('listen_addresses') AS listeners,"
                "current_setting('server_version_num')::int AS version,"
                "(SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls OR rolinherit "
                "FROM pg_roles WHERE rolname=current_user) AS privileged")
            assert row["role"] == "noteai_app" and row["db"] == database
            assert row["address"] is None and row["listeners"] == "" and not row["privileged"]
            assert 160000 <= row["version"] < 170000
            assert db.fetchone("SELECT relrowsecurity AS active FROM pg_class WHERE oid='system_settings'::regclass")["active"]
            assert not db.fetchone("SELECT has_table_privilege(current_user,'model_capacity_buckets','DELETE') AS allowed")["allowed"]
        except BaseException:
            cls.environment.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        billing.clear_active_usage()
        cls.environment.stop()

    def setUp(self):
        self.scope = "pg-int-" + uuid.uuid4().hex
        self.env = mock.patch.dict(os.environ, {
            "NOTEAI_MODEL_CAPACITY_SCOPE": self.scope,
            "NOTEAI_MODEL_CAPACITY_LIMITS_JSON": json.dumps({LITE: {
                "rpm": 3, "tpm": 100000, "evidence_ref": "owned-fullschema-pg-fixture"}})})
        self.env.start(); self.addCleanup(self.env.stop)
        self.manager = admission.Admission()
        patch = mock.patch.object(admission, "_instance", self.manager)
        patch.start(); self.addCleanup(patch.stop)
        self.user = "capacity-pg-" + uuid.uuid4().hex
        db.execute("INSERT INTO users(id,username,email,password_hash,password_salt,created_at) "
            "VALUES(?,?,?,?,?,?)", (self.user, self.user, self.user + "@example.invalid", "fixture", "fixture", billing._now()))
        billing.get_subscription(self.user)
        db.execute("UPDATE subscriptions SET used_monthly_credits=12 WHERE user_id=?", (self.user,))
        billing.grant_credits(self.user, 128, "owned capacity integration fixture")
        self.backend = private_storage.InMemoryObjectBackend()
        private_storage.configure_object_backend(self.backend, key_epoch="owned-capacity-pg")
        self.addCleanup(private_storage.reset_object_backend)
        billing.clear_active_usage(); self.addCleanup(billing.clear_active_usage)

    def claim(self, cover=False):
        if not cover:
            return postdelivery.reserve_claim(user_id=self.user, operation="generate",
                request_id="pg-int-" + uuid.uuid4().hex, payload={"fixture": True})
        report = str(uuid.uuid4())
        db.execute("INSERT INTO saved_diagnoses(id,user_id,note_title,domain,diagnosis_json,created_at) "
            "VALUES(?,?,?,?,?,?)", (report, self.user, "真实原图", "休闲娱乐体验", "{}", billing._now()))
        out = io.BytesIO(); Image.new("RGB", (32, 24), (44, 88, 111)).save(out, "PNG")
        source = private_storage.store_media_bytes(self.user, purpose="image", content_type="image/png",
            payload=out.getvalue(), item_count=1, ttl_seconds=86400)
        policy = {"enabled": True, "operation": "cover_generate", "provider": "seedream",
            "model_id": cover_jobs.MODEL_ID, "width": 1776, "height": 2368, "credits": 8,
            "retention_seconds": 3 * 86400, "max_physical_calls": 3, "max_image_calls": 1,
            "budget_id": cover_jobs.FORMAL_BUDGET_ID}
        result = cover_jobs.submit_job(user_id=self.user, report_type="analyze", report_id=report,
            request_id="pg-int-cover-" + uuid.uuid4().hex, source_refs=[source.id],
            input_snapshot={"note_title": "真实原图", "note_body": "真实照片", "visual_advice": "保留主体"},
            policy_snapshot=policy, quote_version=cover_jobs.policy_quote_version(policy))
        return cover_jobs.claim_job(result["job_id"])

    @contextmanager
    def context(self, claim, *, cover=False):
        inv = public.Invocation(self.user, claim["request_id"], route="/covers" if cover else "/generate/stream",
            budget_id=cover_jobs.FORMAL_BUDGET_ID if cover else public.BUDGET_ID)
        im = public._invocation.set(inv)
        um = billing._ACTIVE_USAGE_ID.set(claim["charge"]["usage_id"])
        try:
            yield inv
        finally:
            billing._ACTIVE_USAGE_ID.reset(um); public._invocation.reset(im)

    def reserve(self, call_id):
        return public._reserve_payload({"model": LITE, "max_tokens": 10,
            "_capacity_demand": capacity.Demand(LITE, 100, 10)}, 7,
            call_id=call_id, require_metered=True)

    def counters(self):
        return dict(db.fetchone("SELECT COALESCE(sum(request_count),0) AS requests,"
            "COALESCE(sum(token_bound),0) AS tokens FROM model_capacity_buckets WHERE scope_key=?", (self.scope,)))

    def budget_snapshot(self):
        return {r["id"]: r["reserved_milli_cny"] for r in db.fetchall(
            "SELECT id,reserved_milli_cny FROM public_trial_budget WHERE id IN (?,?)",
            (public.BUDGET_ID, cover_jobs.FORMAL_BUDGET_ID))}

    def own_calls(self):
        return [dict(row) for row in db.fetchall("SELECT * FROM public_trial_calls WHERE user_id=? ORDER BY id", (self.user,))]

    def assert_undelivered(self):
        self.assertEqual(dict(db.fetchone("SELECT balance,total_used FROM credits WHERE user_id=?", (self.user,))),
                         {"balance": 128, "total_used": 0})
        self.assertEqual(db.fetchone("SELECT count(*) AS n FROM credit_transactions WHERE user_id=? AND type='usage'", (self.user,))["n"], 0)

    def test_cross_original_report_and_cover_budgets_share_atomic_quota(self):
        claims = [(self.claim(cover=i % 2 == 1), i % 2 == 1) for i in range(6)]
        before = self.budget_snapshot(); barrier = threading.Barrier(4)
        def run(item):
            claim, cover = item
            with self.context(claim, cover=cover):
                barrier.wait(timeout=10)
                try:
                    call = self.reserve(str(uuid.uuid4()))
                    public._record_response(call, None, not_dispatched=True)
                    return "admitted"
                except capacity.QuotaDeferred:
                    return "deferred"
        # Cover both real budget branches deterministically; the remaining
        # normal/cover callers race for their one shared account/model permit.
        for claim, cover in claims[:2]:
            with self.context(claim, cover=cover):
                call = self.reserve(str(uuid.uuid4()))
                public._record_response(call, None, not_dispatched=True)
        with ThreadPoolExecutor(max_workers=4) as executor:
            states = ["admitted", "admitted", *executor.map(run, claims[2:])]
        self.assertEqual((states.count("admitted"), states.count("deferred")), (3, 3))
        self.assertEqual(self.counters(), {"requests": 3, "tokens": 330})
        calls = self.own_calls(); self.assertEqual(len(calls), 3)
        after = self.budget_snapshot()
        for budget in before:
            self.assertEqual(after[budget] - before[budget], 7 * sum(c["budget_id"] == budget for c in calls))
        self.assertTrue(all(json.loads(c["provenance_json"])["capacity"]["scope"] == self.scope for c in calls))
        self.assert_undelivered()

    def test_late_insert_rollback_then_same_call_duplicate_never_charges_twice(self):
        claim = self.claim(); before = self.budget_snapshot(); call = str(uuid.uuid4())
        original = db.Transaction.execute
        def fail(tx, sql, *args):
            if sql.startswith("INSERT INTO public_trial_calls"):
                raise RuntimeError("controlled late physical insert failure")
            return original(tx, sql, *args)
        with self.context(claim):
            with mock.patch.object(db.Transaction, "execute", new=fail):
                with self.assertRaisesRegex(RuntimeError, "late physical insert"):
                    self.reserve(call)
            self.assertEqual(self.counters(), {"requests": 0, "tokens": 0})
            self.assertEqual(self.budget_snapshot(), before); self.assertEqual(self.own_calls(), [])
            self.assertEqual(self.reserve(call), call)
            committed = self.budget_snapshot()
            with self.assertRaises(capacity.CapacityStateError): self.reserve(call)
            self.assertEqual(self.budget_snapshot(), committed)
            self.assertEqual(self.counters(), {"requests": 1, "tokens": 110})
            public._record_response(call, None, not_dispatched=True)
        self.assertEqual(len(self.own_calls()), 1); self.assert_undelivered()

    def test_real_claim_lease_expiry_rejects_before_all_new_reservations(self):
        claim = self.claim(); before = self.budget_snapshot()
        db.execute("UPDATE idempotency_requests SET lease_expires_at=? WHERE id=?", (
            (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), claim["request_id"]))
        with self.context(claim):
            with self.assertRaisesRegex(public.TrialProviderStopped, "MODEL_TASK_LEASE_EXPIRED"):
                self.reserve(str(uuid.uuid4()))
        self.assertEqual(self.counters(), {"requests": 0, "tokens": 0})
        self.assertEqual(self.budget_snapshot(), before); self.assertEqual(self.own_calls(), [])
        self.assert_undelivered()

    def test_cancel_drains_committed_short_transaction_and_ack_unknown_never_retries(self):
        claim = self.claim(); entered = threading.Event(); release = threading.Event()
        call = str(uuid.uuid4()); callbacks = []; attempts = []
        def commit_then_wait():
            attempts.append(call); result = self.reserve(call)
            entered.set(); self.assertTrue(release.wait(10)); return result
        async def run():
            with self.context(claim):
                task = asyncio.create_task(public._reserve_callable_with_capacity(commit_then_wait,
                    on_reserved=lambda value: callbacks.append(value),
                    on_finalized=lambda: callbacks.append("finalized")))
                for _ in range(500):
                    if entered.is_set(): break
                    await asyncio.sleep(.005)
                self.assertTrue(entered.is_set()); task.cancel(); release.set()
                with self.assertRaises(asyncio.CancelledError): await task
        try: asyncio.run(run())
        finally: release.set()
        self.assertEqual((attempts, callbacks), ([call], [call, "finalized"]))
        row = self.own_calls()[0]; self.assertEqual((row["state"], row["http_status"]), ("responded", None))
        other = self.claim(); unknown = str(uuid.uuid4()); ack_attempts = []
        def commit_ack_lost():
            ack_attempts.append(unknown); self.reserve(unknown)
            raise RuntimeError("controlled commit acknowledgement lost")
        async def lost():
            with self.context(other):
                with self.assertRaisesRegex(RuntimeError, "acknowledgement lost"):
                    await public._reserve_callable_with_capacity(commit_ack_lost)
                # Explicit ended-request UNKNOWN marking preserves the money;
                # no HTTP occurred and no retry of this identity is attempted.
                public._record_response(unknown, None, unknown=True)
        asyncio.run(lost())
        self.assertEqual(ack_attempts, [unknown])
        snapshot = next(r for r in self.own_calls() if r["id"] == unknown)
        self.assertEqual((snapshot["state"], snapshot["reserve_milli_cny"]), ("unknown", 7))
        with self.context(other):
            with self.assertRaisesRegex(public.TrialProviderStopped, "UNKNOWN_NO_REPLAY"):
                self.reserve(str(uuid.uuid4()))
        self.assertEqual(next(r for r in self.own_calls() if r["id"] == unknown), snapshot)
        self.assertEqual(self.counters(), {"requests": 2, "tokens": 220})
        self.assertEqual(len(self.own_calls()), 2); self.assert_undelivered()


if __name__ == "__main__":
    unittest.main()
