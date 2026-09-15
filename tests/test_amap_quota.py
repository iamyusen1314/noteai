"""Local-only quota/adapter tests; PG requires an explicit disposable socket DB."""

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
import amap_quota as quota
# Import only its Transaction adapter; suppress the legacy SQLite import-time
# initializer. No connection is made from this temporary placeholder setting.
with mock.patch.dict(os.environ, {"DATABASE_URL": "postgresql:///noteai_amap_import_disabled"}):
    import db
import fact_enrichment as facts
import httpx

NOW = quota._clock("2026-09-15T15:00:00Z")


def baseline(**changes):
    row = dict(account_scope=quota.ACCOUNT_SCOPE, service_group=quota.SERVICE_GROUP,
        period="2026-09", period_start="2026-09-01T00:00:00+08:00", period_end="2026-10-01T00:00:00+08:00",
        time_zone="Asia/Shanghai", quota=50000, official_used=1, observed_at="2026-09-15T14:30:00Z",
        source="amap_console_base_search_statistics", snapshot_sha256="a" * 64,
        owner_authorized_at="2026-09-15T14:00:00Z", enterprise_certified=1, license_purchased=0,
        owner_risk_accepted=1, exclusive_noteai_use=1, admitted_count=0,
        billing_observation_json=json.dumps(dict(period_start="2026-09-01", period_end="2026-09-15",
            usage=1, cost_cny=0, observed_at="2026-09-15T14:30:00Z", source="amap_console_bill", scope="observed_period_only")))
    return row | changes


class SQLiteStorage:
    def __init__(self, path):
        self.path = path

    def connection(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def transaction(self, *, write=False):
        conn = self.connection()
        try:
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db.Transaction(conn, False)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def fetchone(self, sql, params=()):
        with self.transaction() as tx:
            return tx.fetchone(sql, params)

    def fetchall(self, sql, params=()):
        with self.transaction() as tx:
            return tx.fetchall(sql, params)


def seed(storage, **changes):
    row = baseline(**changes)
    with storage.transaction(write=True) as tx:
        tx.execute("INSERT INTO amap_quota_buckets(" + ",".join(row) + ") VALUES(" + ",".join("?" for _ in row) + ")", tuple(row.values()))


def admit_result(storage, endpoint="text", identity=None):
    try:
        return quota.admit(endpoint, storage=storage, attempt_id=identity)
    except quota.AmapQuotaError as exc:
        return exc.code


def pg_process_admission(index):
    with mock.patch.object(quota, "_database_now", return_value=NOW):
        result = admit_result(PGStorage(), "text" if index % 2 else "detail")
        return "admitted" if isinstance(result, quota.Admission) else result


class QuotaCases:
    def freeze(self, now=NOW):
        patch = mock.patch.object(quota, "_database_now", return_value=now)
        patch.start()
        self.addCleanup(patch.stop)

    def test_missing_and_expired_snapshot_never_reset(self):
        self.freeze()
        self.assertEqual(admit_result(self.storage), "AMAP_QUOTA_SNAPSHOT_REQUIRED")
        seed(self.operator)
        with mock.patch.object(quota, "_database_now", return_value=quota._clock("2026-10-02T00:00:00Z")):
            self.assertEqual(admit_result(self.storage), "AMAP_QUOTA_SNAPSHOT_EXPIRED")
            result = quota.read_status(storage=self.storage)
            self.assertEqual(result["status"], "snapshot_expired")
            self.assertIsNone(result["remaining"])
        self.assertEqual(len(self.storage.fetchall("SELECT * FROM amap_quota_buckets")), 1)
        self.assertEqual(self.storage.fetchall("SELECT * FROM amap_quota_attempts"), [])

    def test_next_official_month_keeps_original_owner_authorization_and_actual_quota(self):
        self.freeze(quota._clock("2026-10-02T00:00:00Z"))
        seed(self.operator)
        seed(self.operator, period="2026-10", period_start="2026-10-01T00:00:00+08:00",
             period_end="2026-11-01T00:00:00+08:00", observed_at="2026-10-01T10:00:00Z", quota=3, official_used=2)
        self.assertIsInstance(admit_result(self.storage), quota.Admission)
        self.assertEqual(admit_result(self.storage, "detail"), "AMAP_MONTHLY_QUOTA_EXHAUSTED")
        result = quota.read_status(storage=self.storage)
        self.assertEqual(result["snapshot"]["owner_authorized_at"], quota._iso(baseline()["owner_authorized_at"]))
        self.assertEqual(result["snapshot"]["quota"], 3)
        self.assertEqual(result["remaining"], 0)

    def test_future_snapshot_and_boundary_deny(self):
        seed(self.operator)
        self.freeze(NOW - timedelta(hours=1))
        self.assertEqual(admit_result(self.storage), "AMAP_QUOTA_SNAPSHOT_NOT_CURRENT")
        with mock.patch.object(quota, "_database_now", return_value=quota._clock(baseline()["period_end"]) - timedelta(seconds=9)):
            self.assertEqual(admit_result(self.storage), "AMAP_QUOTA_SNAPSHOT_EXPIRED")

    def test_shared_last_slot_atomic_across_instances_and_endpoints(self):
        seed(self.operator, official_used=49999)
        self.freeze()
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(lambda n: admit_result(self.new_storage(), "text" if n % 2 else "detail"), range(32)))
        self.assertEqual(sum(isinstance(item, quota.Admission) for item in results), 1)
        self.assertEqual(results.count("AMAP_MONTHLY_QUOTA_EXHAUSTED"), 31)
        self.assertEqual(len(self.storage.fetchall("SELECT * FROM amap_quota_attempts")), 1)
        self.assertEqual(self.storage.fetchone("SELECT admitted_count FROM amap_quota_buckets")["admitted_count"], 1)

    def test_qps_is_shared_per_endpoint_not_per_instance_or_key(self):
        seed(self.operator)
        self.freeze()
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(lambda _: admit_result(self.new_storage()), range(40)))
        self.assertEqual(sum(isinstance(item, quota.Admission) for item in results), 30)
        self.assertEqual(results.count("AMAP_QPS_LIMIT_REACHED"), 8 + 2)
        self.assertIsInstance(admit_result(self.storage, "detail"), quota.Admission)
        with mock.patch.object(quota, "_database_now", return_value=NOW + timedelta(seconds=1)):
            self.assertIsInstance(admit_result(self.storage), quota.Admission)

    def test_unknown_is_counted_no_replay_and_terminal_is_immutable(self):
        seed(self.operator)
        self.freeze()
        admission = quota.admit("text", storage=self.storage)
        quota.finish(admission, status="unknown", storage=self.storage)
        quota.finish(admission, status="unknown", storage=self.storage)
        self.assertEqual(admit_result(self.storage, identity=admission.id), "AMAP_ADMISSION_ALREADY_USED")
        with self.assertRaisesRegex(quota.AmapQuotaError, "AMAP_OUTCOME_ALREADY_RECORDED"):
            quota.finish(admission, status="succeeded", storage=self.storage)
        self.assertEqual(quota.read_status(storage=self.storage)["remaining"], 49998)
        with self.assertRaises(Exception):
            with self.storage.transaction(write=True) as tx:
                tx.execute("UPDATE amap_quota_buckets SET admitted_count=0")

    def test_endpoint_auth_deny_survives_new_month_until_operator_recovery(self):
        seed(self.operator)
        self.freeze()
        admission = quota.admit("detail", storage=self.storage)
        quota.finish(admission, status="failed", http_status=200, business_code="10012", storage=self.storage)
        self.assertEqual(admit_result(self.storage, "detail"), "AMAP_PROVIDER_ACCESS_RESTRICTED")
        self.assertIsInstance(admit_result(self.storage, "text"), quota.Admission)
        seed(self.operator, period="2026-10", period_start="2026-10-01T00:00:00+08:00",
             period_end="2026-11-01T00:00:00+08:00", observed_at="2026-10-01T10:00:00Z")
        with mock.patch.object(quota, "_database_now", return_value=quota._clock("2026-10-02T00:00:00Z")):
            self.assertEqual(admit_result(self.storage, "detail"), "AMAP_PROVIDER_ACCESS_RESTRICTED")
            self.assertEqual(quota.read_status(storage=self.storage)["snapshot"]["blocked_endpoints"]["detail"], "10012")
            self.assertIsInstance(admit_result(self.storage, "text"), quota.Admission)

    def test_account_deny_and_late_qps_cannot_clear_permanent_denial(self):
        seed(self.operator)
        self.freeze()
        first = quota.admit("text", storage=self.storage)
        second = quota.admit("text", storage=self.storage)
        quota.finish(first, status="failed", business_code="10026", storage=self.storage)
        quota.finish(second, status="failed", business_code="10019", storage=self.storage)
        self.assertEqual(admit_result(self.storage, "detail"), "AMAP_PROVIDER_ACCESS_RESTRICTED")
        self.assertEqual(self.storage.fetchone("SELECT account_block_code FROM amap_quota_buckets")["account_block_code"], "10026")

    def test_qps_temporary_restriction_is_not_global_shutdown(self):
        seed(self.operator)
        self.freeze()
        first = quota.admit("detail", storage=self.storage)
        quota.finish(first, status="failed", business_code="10004", storage=self.storage)
        self.assertEqual(admit_result(self.storage, "detail"), "AMAP_PROVIDER_ACCESS_RESTRICTED")
        self.assertIsInstance(admit_result(self.storage, "text"), quota.Admission)
        with mock.patch.object(quota, "_database_now", return_value=NOW + timedelta(seconds=61)):
            self.assertIsInstance(admit_result(self.storage, "detail"), quota.Admission)

    def test_snapshot_status_is_observation_not_billing_or_activation_inference(self):
        seed(self.operator)
        self.freeze()
        result = quota.read_status(storage=self.storage)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["remaining"], 49999)
        self.assertFalse(result["runtime_activation_inferred"])
        self.assertFalse(result["snapshot_is_realtime"])
        self.assertEqual(result["snapshot"]["billing_observation"]["cost_cny"], 0)
        self.assertEqual(result["snapshot"]["billing_observation"]["scope"], "observed_period_only")
        self.assertNotIn("key", json.dumps(result).lower())


class AmapSQLiteTests(QuotaCases, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="amap-local-test-")
        self.addCleanup(self.temp.cleanup)
        self.storage = SQLiteStorage(str(Path(self.temp.name) / "quota.db"))
        self.operator = self.storage
        with self.storage.connection() as conn:
            conn.executescript(quota.SQLITE_SCHEMA)

    def new_storage(self):
        return SQLiteStorage(self.storage.path)


class AmapAdapterTests(unittest.TestCase):
    freeze = QuotaCases.freeze

    def setUp(self):
        AmapSQLiteTests.setUp(self)
        self.freeze()
        patch = mock.patch.object(quota, "_storage", return_value=self.storage)
        patch.start()
        self.addCleanup(patch.stop)

    def test_two_physical_requests_are_two_admissions_same_poi(self):
        seed(self.operator)
        responses = [httpx.Response(200, json={"status":"1","infocode":"10000","pois":[{"id":"fixture-poi","name":"广州珑厨万博店","address":"甲路1号"}]}),
                     httpx.Response(200, json={"status":"1","infocode":"10000","pois":[{"id":"fixture-poi","business":{"cost":"88"}}]})]
        calls = []
        def respond(request):
            calls.append(request.url.path)
            return responses[len(calls)-1]
        real_client = httpx.Client
        with mock.patch.dict(os.environ, {"AMAP_WEB_KEY":"fixture-not-a-secret"}), \
             mock.patch.object(facts.httpx, "Client", side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs)):
            result = facts._search_amap("广州 珑厨万博店 地址")
        self.assertEqual(calls, ["/v3/place/text", "/v5/place/detail"])
        self.assertEqual(len(result), 1)
        self.assertIn("88", result[0]["facts"]["price"])
        self.assertEqual(quota.read_status(storage=self.storage)["remaining"], 49997)

    def test_denied_admission_or_uncertain_commit_never_dispatches(self):
        client = mock.Mock()
        with self.assertRaisesRegex(facts.FactProviderError, "AMAP_QUOTA_SNAPSHOT_REQUIRED"):
            facts._fact_get(client, next(iter(quota.ENDPOINT_URLS)), params={})
        client.get.assert_not_called()
        seed(self.operator)
        original = self.storage.transaction
        @contextmanager
        def commit_unknown(*, write=False):
            with original(write=write) as tx:
                yield tx
            raise RuntimeError("simulated lost commit acknowledgment")
        with mock.patch.object(self.storage, "transaction", commit_unknown), self.assertRaisesRegex(facts.FactProviderError, "AMAP_QUOTA_STATE_UNKNOWN"):
            facts._fact_get(client, next(iter(quota.ENDPOINT_URLS)), params={})
        client.get.assert_not_called()
        self.assertEqual(self.storage.fetchone("SELECT admitted_count FROM amap_quota_buckets")["admitted_count"], 1)

    def test_timeout_has_one_call_no_retry_no_release(self):
        seed(self.operator)
        client = mock.Mock()
        client.get.side_effect = httpx.ReadTimeout("fixture")
        with self.assertRaises(httpx.ReadTimeout):
            facts._fact_get(client, next(iter(quota.ENDPOINT_URLS)), params={})
        self.assertEqual(client.get.call_count, 1)
        self.assertEqual(self.storage.fetchone("SELECT status FROM amap_quota_attempts")["status"], "unknown")
        self.assertEqual(quota.read_status(storage=self.storage)["remaining"], 49998)

    def test_detail_quota_denial_keeps_base_and_reason_reaches_prompt(self):
        seed(self.operator, official_used=50000)
        with mock.patch.object(facts, "fact_search_enabled", return_value=True), \
             mock.patch.object(facts, "_authorized_fact_items", return_value=[]), \
             mock.patch.object(facts, "_cache_ttl_seconds", return_value=0), \
             mock.patch.object(facts, "_search", side_effect=facts.FactProviderError("AMAP_MONTHLY_QUOTA_EXHAUSTED")):
            result = facts.enrich_content_facts("美食", "珑厨万博店", "广州", provider="amap")
        self.assertTrue(result["enabled"])
        self.assertIn("已有资料和其他功能可继续使用", result["reason"])
        self.assertIn("共享额度已用尽", facts.format_fact_context(result))
        client = mock.Mock()
        marker = facts._READ_TRACE.set(dict(http_requests=0, partial_errors=[]))
        try:
            self.assertEqual(facts._amap_fetch_v5_detail(client, "fixture", "fixture-poi"), {})
            self.assertEqual(facts._READ_TRACE.get()["partial_errors"], ["AMAP_MONTHLY_QUOTA_EXHAUSTED"])
            client.get.assert_not_called()
        finally:
            facts._READ_TRACE.reset(marker)

    def test_other_provider_does_not_use_amap_guard(self):
        client = mock.Mock()
        response = client.get.return_value
        with mock.patch.object(quota, "admit", side_effect=AssertionError("wrong provider")):
            self.assertIs(facts._fact_get(client, "https://example.invalid/search", params={}), response)


PG_ENABLED = os.environ.get("NOTEAI_LOCAL_PG16_AMAP_TEST") == "1"


class PGStorage:
    def __init__(self, role="noteai_app"):
        self.role = role

    @contextmanager
    def transaction(self, *, write=False):
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(host="/var/run/postgresql", dbname="noteai_amap_local", user=self.role, row_factory=dict_row) as conn:
            yield db.Transaction(conn, True)

    def using_postgres(self):
        return True

    def fetchone(self, sql, params=()):
        with self.transaction() as tx:
            return tx.fetchone(sql, params)

    def fetchall(self, sql, params=()):
        with self.transaction() as tx:
            return tx.fetchall(sql, params)


@unittest.skipUnless(PG_ENABLED, "explicit disposable network-none PG16 socket required")
class AmapPostgresTests(QuotaCases, unittest.TestCase):
    def setUp(self):
        self.operator = PGStorage("postgres")
        self.storage = PGStorage()
        with self.operator.transaction(write=True) as tx:
            row = tx.fetchone("SELECT current_setting('server_version_num')::int AS version,inet_server_addr() AS address,current_database() AS db")
            self.assertTrue(160000 <= row["version"] < 170000)
            self.assertIsNone(row["address"])
            self.assertEqual(row["db"], "noteai_amap_local")
            tx.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
            for role in ("noteai_app", "noteai_admin_runtime"):
                if tx.fetchone("SELECT 1 FROM pg_roles WHERE rolname=?", (role,)) is None:
                    tx.execute("CREATE ROLE " + role + " LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT")
            tx.execute("GRANT USAGE ON SCHEMA public TO noteai_app,noteai_admin_runtime")
            tx.conn.execute((ROOT / "model/migrations/postgres/0031_amap_shared_quota.sql").read_text())

    def new_storage(self):
        return PGStorage()

    def test_separate_processes_share_one_account_allocation(self):
        seed(self.operator, official_used=49995)
        with ProcessPoolExecutor(max_workers=4, mp_context=multiprocessing.get_context("fork")) as pool:
            results = list(pool.map(pg_process_admission, range(16)))
        self.assertEqual(results.count("admitted"), 5)
        self.assertEqual(results.count("AMAP_MONTHLY_QUOTA_EXHAUSTED"), 11)
        self.assertEqual(self.storage.fetchone("SELECT count(*) AS count FROM amap_quota_attempts")["count"], 5)

    def test_database_clock_reads_after_bucket_lock(self):
        seed(self.operator)
        # Uses the actual DB clock and transaction adapter, independently of the
        # fixed September business fixtures used in the other boundary tests.
        with self.storage.transaction(write=True) as tx:
            quota._account_lock(tx)
            quota._bucket(tx, lock=True)
            before = quota._database_now(tx)
            tx.fetchone("SELECT pg_sleep(0.03)")
            after = quota._database_now(tx)
        self.assertGreater((after-before).total_seconds(), 0.02)

    def test_roles_cannot_seed_change_baseline_or_delete_and_admin_is_select_only(self):
        seed(self.operator)
        self.freeze()
        self.assertEqual(quota.read_status(storage=PGStorage("noteai_admin_runtime"))["status"], "ready")
        for role, statement in [
            ("noteai_app", "UPDATE amap_quota_buckets SET official_used=0"),
            ("noteai_app", "UPDATE amap_quota_buckets SET quota=100000"),
            ("noteai_app", "UPDATE amap_quota_buckets SET billing_observation_json=NULL"),
            ("noteai_app", "DELETE FROM amap_quota_buckets"),
            ("noteai_app", "TRUNCATE amap_quota_attempts"),
            ("noteai_admin_runtime", "UPDATE amap_quota_buckets SET admitted_count=1"),
            ("noteai_admin_runtime", "DELETE FROM amap_quota_attempts"),
        ]:
            with self.subTest(role=role, statement=statement), self.assertRaises(Exception):
                with PGStorage(role).transaction(write=True) as tx:
                    tx.execute(statement)
        with self.assertRaises(Exception):
            seed(self.storage, period="2026-10")
        with self.assertRaises(Exception):
            with self.storage.transaction(write=True) as tx:
                tx.execute("CREATE TABLE public.amap_runtime_forbidden(id integer)")


if __name__ == "__main__":
    unittest.main()
