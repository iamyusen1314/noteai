"""Affected accounting checks on an explicitly owned, disposable PG16 socket.

No production DSN, supplier traffic, migration runner or persistent resources.
The incident runner installs only the original schema31/ordinary app ACL first.
"""
import asyncio
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest import mock
from urllib.parse import urlencode

import httpx
import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import ark_media
import billing
import db
import idempotency
import public_product


ENABLED = os.environ.get("NOTEAI_GENERATION_ACCOUNTING_PG_TEST") == "1"


@unittest.skipUnless(ENABLED, "explicit incident-local PG16 fixture required")
class GenerationAccountingPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        socket = Path(os.environ["NOTEAI_GENERATION_ACCOUNTING_PG_SOCKET"])
        database = os.environ["NOTEAI_GENERATION_ACCOUNTING_PG_DATABASE"]
        assert socket.is_dir() and socket.parent.name.startswith("na-generation-pg16-")
        assert database.startswith("noteai_generation_test_")
        cls.environment = mock.patch.dict(os.environ, {
            "DATABASE_URL": "postgresql://noteai_app@/" + database + "?" + urlencode({
                "host": str(socket), "port": "19432", "connect_timeout": "5"}),
            "PYTHON_DOTENV_DISABLED": "1", "NOTEAI_PUBLIC_PRODUCT": "1",
            "NOTEAI_ARK_API_KEY": "synthetic-offline-only",
        })
        cls.environment.start()
        with db.get_conn() as connection:
            identity = connection.execute("SELECT current_database() AS db,current_user AS role,"
                "inet_server_addr() AS address,current_setting('listen_addresses') AS listeners,"
                "current_setting('server_version_num')::int AS version,"
                "(SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls "
                "FROM pg_roles WHERE rolname=current_user) AS privileged").fetchone()
            assert identity["db"] == database and identity["role"] == "noteai_app"
            assert identity["address"] is None and identity["listeners"] == ""
            assert 160000 <= identity["version"] < 170000 and not identity["privileged"]

    @classmethod
    def tearDownClass(cls):
        billing.clear_active_usage()
        cls.environment.stop()

    def setUp(self):
        billing.clear_active_usage()
        self.uid = "accounting-pg-" + uuid.uuid4().hex
        db.execute("INSERT INTO users(id,username,email,password_hash,password_salt,created_at) "
                   "VALUES(?,?,?,?,?,?)", (self.uid, self.uid, self.uid + "@example.invalid",
                                          "synthetic", "synthetic", billing._now()))
        self.key = "accounting-original-" + uuid.uuid4().hex
        self.claim = idempotency.claim_and_charge(user_id=self.uid, operation="generate",
            request_id=self.key, payload={"images": ["synthetic-only"]})
        self.assertEqual(self.claim["state"], "owner")
        self.usage = self.claim["charge"]["usage_id"]
        self.marker = public_product._invocation.set(public_product.Invocation(self.uid, self.key))
        self.wires = []

    def tearDown(self):
        public_product._invocation.reset(self.marker)
        billing.clear_active_usage()

    def call_fixture(self, uid=None, usage=None, request=None):
        uid, usage = uid or self.uid, usage or self.usage
        call = str(uuid.uuid4())
        db.execute("INSERT INTO public_trial_calls(id,budget_id,user_id,request_hash,state,"
                   "reserve_milli_cny,created_at,usage_record_id,provenance_json) "
                   "VALUES(?,?,?,?,?,?,?,?,?)", (call, public_product.BUDGET_ID, uid,
                   hashlib.sha256((request or self.key).encode()).hexdigest(), "dispatched",
                   1, billing._now(), usage, "{}"))
        return call

    def chat(self):
        def response(request):
            self.wires.append(request)
            return httpx.Response(200, json={"model": ark_media.MODEL,
                "usage": {"prompt_tokens": 100, "completion_tokens": 10,
                          "prompt_tokens_details": {"cached_tokens": 0}},
                "choices": [{"finish_reason": "stop", "message": {"content": "observed image"}}]})
        return ark_media.chat("fixture", [{}], transport=httpx.MockTransport(response))

    def calls(self):
        return [dict(row) for row in db.fetchall("SELECT id,state,http_status,model_usage_record_id "
            "FROM public_trial_calls WHERE usage_record_id=? ORDER BY id", (self.usage,))]

    def test_http200_actual_pg_statement_failure_closes_wire_without_fake_meter(self):
        def invalid_statement(*args, **kwargs):
            db.execute("SELECT 1/0")  # Actual PG22012, not a presumed production cause.
        log = io.StringIO()
        with contextlib.redirect_stderr(log), mock.patch.object(billing,
                "record_model_usage", side_effect=invalid_statement) as record:
            with self.assertRaisesRegex(public_product.TrialProviderStopped,
                                        "PUBLIC_MODEL_ACCOUNTING_UNCONFIRMED"):
                self.chat()
        self.assertEqual((len(self.wires), record.call_count), (1, 1))
        call = self.calls()[0]
        self.assertEqual((call["state"], call["http_status"]), ("responded", 200))
        self.assertIsNone(call["model_usage_record_id"])
        self.assertEqual(db.fetchone("SELECT count(*) AS n FROM model_usage_records "
                                    "WHERE usage_record_id=?", (self.usage,))["n"], 0)
        events = [json.loads(line) for line in log.getvalue().splitlines()]
        self.assertEqual((events[0]["exception_class"], events[0]["sqlstate"]),
                         ("DivisionByZero", "22012"))
        with self.assertRaises(public_product.TrialProviderStopped):
            public_product.assert_result_known()

    def test_actual_pg_usage_commit_then_unknown_ack_is_not_metered_twice(self):
        original = billing.record_model_usage
        def unknown_ack(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("synthetic lost local acknowledgement")
        with contextlib.redirect_stderr(io.StringIO()), mock.patch.object(billing,
                "record_model_usage", side_effect=unknown_ack) as record:
            with self.assertRaisesRegex(public_product.TrialProviderStopped,
                                        "PUBLIC_MODEL_ACCOUNTING_UNCONFIRMED"):
                self.chat()
        self.assertEqual((len(self.wires), record.call_count), (1, 1))
        self.assertEqual(self.calls()[0]["state"], "responded")
        self.assertIsNotNone(self.calls()[0]["model_usage_record_id"])
        rows = db.fetchall("SELECT known_cost_rmb FROM model_usage_records WHERE usage_record_id=?",
                           (self.usage,))
        self.assertEqual(len(rows), 1)
        self.assertGreater(rows[0]["known_cost_rmb"], 0)

    def test_actual_pg_terminal_commit_unknown_ack_reads_before_repeating_update(self):
        original, execute = public_product._record_response, db.Transaction.execute
        attempts, updates = [], []
        def terminal(*args, **kwargs):
            attempts.append(True)
            original(*args, **kwargs)
            if len(attempts) == 1:
                raise public_product.TrialProviderStopped("PUBLIC_TRIAL_RESULT_PERSISTENCE_UNKNOWN")
        def tracked(tx, statement, *args, **kwargs):
            if statement.startswith("UPDATE public_trial_calls SET state="):
                updates.append(True)
            return execute(tx, statement, *args, **kwargs)
        with contextlib.redirect_stderr(io.StringIO()), mock.patch.object(public_product,
                "_record_response", side_effect=terminal), mock.patch.object(
                db.Transaction, "execute", new=tracked):
            self.assertEqual(self.chat(), "observed image")
        self.assertEqual((len(self.wires), len(attempts), len(updates)), (1, 2, 1))
        self.assertEqual(self.calls()[0]["state"], "responded")
        with self.assertRaises(public_product.TrialProviderStopped):
            public_product.assert_result_known()

    def test_ten_users_nine_calls_concurrent_pg_metering_has_no_lost_totals(self):
        owners = [(self.uid, self.usage, self.key)]
        for _ in range(9):
            uid = "accounting-pg-" + uuid.uuid4().hex
            db.execute("INSERT INTO users(id,username,email,password_hash,password_salt,created_at) "
                       "VALUES(?,?,?,?,?,?)", (uid, uid, uid + "@example.invalid", "synthetic",
                                              "synthetic", billing._now()))
            key = "accounting-original-" + uuid.uuid4().hex
            claim = idempotency.claim_and_charge(user_id=uid, operation="generate",
                                                 request_id=key, payload={"fixture": True})
            owners.append((uid, claim["charge"]["usage_id"], key))
        jobs = [(usage, self.call_fixture(uid, usage, key))
                for uid, usage, key in owners for _ in range(9)]
        def meter(job):
            usage, call = job
            billing.record_model_usage("doubao", ark_media.MODEL, tokens_in=100, tokens_out=10,
                                       usage_status="complete", physical_call_id=call)
            public_product._record_response(call, 200)
            return usage, call
        with ThreadPoolExecutor(max_workers=10) as pool:
            self.assertEqual(len(list(pool.map(meter, jobs))), 90)
        # Exact repeated local settlement is a read/no-op, never another wire.
        billing.clear_active_usage()
        meter(jobs[0])
        for uid, usage, _ in owners:
            parent = db.fetchone("SELECT model_calls,actual_model_cost_rmb,cost_mode "
                                 "FROM usage_records WHERE id=?", (usage,))
            children = db.fetchall("SELECT known_cost_rmb FROM model_usage_records "
                                   "WHERE usage_record_id=?", (usage,))
            self.assertEqual((parent["model_calls"], len(children), parent["cost_mode"]), (9, 9, "actual"))
            self.assertAlmostEqual(parent["actual_model_cost_rmb"],
                                   sum(row["known_cost_rmb"] for row in children), places=9)
            self.assertEqual(db.fetchone("SELECT count(*) AS n FROM public_trial_calls "
                "WHERE usage_record_id=? AND (state<>'responded' OR http_status<>200 "
                "OR model_usage_record_id IS NULL)", (usage,))["n"], 0)
        print("PG_ACCOUNTING_CONCURRENCY " + json.dumps({"users": 10, "calls_each": 9,
            "threads_max": 10, "real_provider_calls": 0, "database_only_not_capacity": True}))

    def test_mixed_six_call_refund_is_once_and_preserves_supplier_records(self):
        for index in range(6):
            call = self.call_fixture()
            if index < 5:
                billing.record_model_usage("doubao", ark_media.MODEL, tokens_in=100,
                    tokens_out=10, physical_call_id=call, usage_status="complete")
                public_product._record_response(call, 200)
        self.assertTrue(idempotency.mark_failed_and_refund(self.claim, failure_code="stream_cancelled"))
        row = dict(db.fetchone("SELECT * FROM idempotency_requests WHERE id=?", (self.claim["request_id"],)))
        self.assertEqual(row["refund_applied"], 0)
        expiry = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        db.execute("UPDATE idempotency_requests SET lease_expires_at=? WHERE id=?",
                   (expiry, self.claim["request_id"]))
        manifest = self.calls()
        costs = [dict(r) for r in db.fetchall("SELECT id,known_cost_rmb FROM model_usage_records "
                                            "WHERE usage_record_id=? ORDER BY id", (self.usage,))]
        kwargs = {"expected_usage_id": self.usage, "expected_provider_calls": manifest,
            "expected_lease_expires_at": expiry, "expected_credits": 8,
            "expected_subscription_id": row["charged_subscription_id"],
            "expected_period_start": row["charged_period_start"], "original_execution_ended": True}
        for changed in ({"original_execution_ended": False}, {"expected_provider_calls": manifest[:5]}):
            with self.assertRaises(ValueError):
                idempotency.reconcile_undelivered_generate_calls(self.uid, self.claim["request_id"],
                                                                 **{**kwargs, **changed})
        def settle(_):
            return idempotency.reconcile_undelivered_generate_calls(
                self.uid, self.claim["request_id"], **kwargs)["refund_status"]
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(list(pool.map(settle, range(4))), ["refunded"] * 4)
        after = db.fetchone("SELECT refund_applied,failed_at FROM idempotency_requests WHERE id=?",
                            (self.claim["request_id"],))
        self.assertEqual((after["refund_applied"], after["failed_at"]), (1, row["failed_at"]))
        self.assertEqual(self.calls(), manifest)
        self.assertEqual([dict(r) for r in db.fetchall("SELECT id,known_cost_rmb FROM model_usage_records "
            "WHERE usage_record_id=? ORDER BY id", (self.usage,))], costs)
        self.assertEqual(db.fetchone("SELECT used_monthly_credits FROM subscriptions WHERE id=?",
                                    (row["charged_subscription_id"],))["used_monthly_credits"], 0)
        self.assertEqual(db.fetchone("SELECT source,credits_used FROM usage_records WHERE id=?",
                                    (self.usage,))["source"], "refunded")


if __name__ == "__main__":
    unittest.main()
