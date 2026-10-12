"""Actual, task-owned PG16 acceptance; all observations are offline fixtures.

Run only through tools/run_amap_postgres_acceptance.py, which creates a fresh
Unix-socket-only cluster and unique databases. No production DSN or provider
credential is accepted. The original 13 quota + 2 ACL cases are inherited with
their storage binding replaced; their original business-clock fixtures remain
mocked where the original tests mock them. Renewal tests use the actual PG clock.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import unittest
from unittest import mock
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from tests import test_amap_quota as original
from tests import test_amap_quota_acl as original_acl
import amap_quota as quota
import refresh_amap_quota_snapshot as refresh
import psycopg
from psycopg import sql
from psycopg.rows import dict_row

ENABLED = os.environ.get("NOTEAI_AMAP_REAL_PG_TEST") == "1"
SOCKET = os.environ.get("NOTEAI_AMAP_REAL_PG_SOCKET", "")
PORT = os.environ.get("NOTEAI_AMAP_REAL_PG_PORT", "")
QUOTA_DB = os.environ.get("NOTEAI_AMAP_REAL_PG_QUOTA_DB", "")
ACL_DB = os.environ.get("NOTEAI_AMAP_REAL_PG_ACL_DB", "")
REFRESH_DB = os.environ.get("NOTEAI_AMAP_REAL_PG_REFRESH_DB", "")
SCHEMA = ROOT / "model/migrations/postgres/0031_amap_shared_quota.sql"
FIXTURE_KEY = "offline-postgres-acceptance-never-provider"


def require_fixture():
    if (not ENABLED or not re.fullmatch(r"/tmp/na-amap-pg16-[A-Za-z0-9_-]+/socket", SOCKET)
        or not PORT.isdigit() or not 1024 <= int(PORT) <= 65535
        or any(not re.fullmatch(r"noteai_amap_test_[0-9a-f]{12}_(?:quota|acl|refresh)", name)
               for name in (QUOTA_DB, ACL_DB, REFRESH_DB))):
        raise AssertionError("explicit task-owned local PG16 fixture required")
    marker = json.loads((Path(SOCKET).parent / "noteai-amap-fixture.json").read_text())
    if marker != {"socket": SOCKET, "port": int(PORT), "databases": [QUOTA_DB, ACL_DB, REFRESH_DB]}:
        raise AssertionError("task-owned fixture marker mismatch")


def connect(database, role="postgres", *, autocommit=False, dictionaries=True):
    require_fixture()
    return psycopg.connect(host=SOCKET, port=int(PORT), dbname=database, user=role,
                          autocommit=autocommit, row_factory=dict_row if dictionaries else None,
                          connect_timeout=5, application_name="noteai_amap_acceptance")


def assert_local_owner(connection, database):
    row = connection.execute("SELECT current_setting('server_version_num')::int AS version, "
        "inet_server_addr() AS address,current_database() AS db,current_user AS role").fetchone()
    if not (160000 <= row["version"] < 170000 and row["address"] is None
            and row["db"] == database and row["role"] == "postgres"):
        raise AssertionError("isolated owner PG16 socket/database required")


def install_schema(database):
    with connect(database, autocommit=True) as connection:
        assert_local_owner(connection, database)
        connection.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
        for role in ("noteai_app", "noteai_admin_runtime"):
            if connection.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone() is None:
                connection.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT").format(sql.Identifier(role)))
            else:
                connection.execute(sql.SQL("ALTER ROLE {} LOGIN").format(sql.Identifier(role)))
        connection.execute("GRANT USAGE ON SCHEMA public TO noteai_app,noteai_admin_runtime")
        connection.execute(SCHEMA.read_text())


class RealStorage:
    def __init__(self, role="noteai_app", database=QUOTA_DB):
        self.role, self.database = role, database

    @contextmanager
    def transaction(self, *, write=False):
        with connect(self.database, self.role) as connection:
            yield original.db.Transaction(connection, True)

    def using_postgres(self):
        return True

    def fetchone(self, query, params=()):
        with self.transaction() as tx:
            return tx.fetchone(query, params)

    def fetchall(self, query, params=()):
        with self.transaction() as tx:
            return tx.fetchall(query, params)


class OriginalQuotaPostgresAcceptance(original.AmapPostgresTests):
    __unittest_skip__ = not ENABLED
    __unittest_skip_why__ = "explicit task-owned PG16 acceptance runner required"

    def setUp(self):
        install_schema(QUOTA_DB)
        patch = mock.patch.object(original, "PGStorage", RealStorage)
        patch.start()
        self.addCleanup(patch.stop)
        self.operator = RealStorage("postgres")
        self.storage = RealStorage()


class OriginalAclPostgresAcceptance(original_acl.AmapQuotaAclTests):
    __unittest_skip__ = not ENABLED
    __unittest_skip_why__ = "explicit task-owned PG16 acceptance runner required"

    @classmethod
    def setUpClass(cls):
        cls.owner = connect(ACL_DB, autocommit=True, dictionaries=False)
        version, address, database = cls.owner.execute(
            "SELECT current_setting('server_version_num')::int,inet_server_addr(),current_database()"
        ).fetchone()
        if not (160000 <= version < 170000 and address is None and database == ACL_DB):
            cls.owner.close()
            raise AssertionError("task-owned local PG16 ACL fixture required")
        for role in (*original_acl.ROLES, original_acl.EXTRA_ROLE):
            cls.owner.execute(sql.SQL("DO $roles$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname={name}) "
                "THEN CREATE ROLE {role} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT; END IF; END $roles$").format(
                    name=sql.Literal(role), role=sql.Identifier(role)))


@unittest.skipUnless(ENABLED, "explicit task-owned PG16 acceptance runner required")
class RenewalPostgresAcceptance(unittest.TestCase):
    def setUp(self):
        install_schema(REFRESH_DB)
        self.owner = RealStorage("postgres", REFRESH_DB)
        self.app = RealStorage("noteai_app", REFRESH_DB)
        self.temp = tempfile.TemporaryDirectory(prefix="amap-real-pg-evidence-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.artifact = self.path / "SYNTHETIC_NOT_OFFICIAL.txt"
        self.artifact.write_text("Offline simulated console observation for actual isolated PG acceptance only.")
        self.evidence_path = self.path / "SYNTHETIC_NOT_OFFICIAL.json"
        with self.owner.transaction() as tx:
            now = quota._database_now(tx)
        period, start, end = refresh._calendar(now)
        _, old_start, _ = refresh._calendar(start-timedelta(days=1))
        self.old = original.baseline(period=old_start.astimezone(refresh.SHANGHAI).strftime("%Y-%m"),
            period_start=quota._iso(old_start), period_end=quota._iso(start),
            observed_at=quota._iso(old_start+timedelta(days=1)), owner_authorized_at=quota._iso(old_start),
            billing_observation_json=None)
        with self.owner.transaction(write=True) as tx:
            tx.execute("INSERT INTO amap_quota_buckets(" + ",".join(self.old) + ") VALUES(" +
                       ",".join("?" for _ in self.old) + ")", tuple(self.old.values()))
        self.document = dict(version=1, account_scope=quota.ACCOUNT_SCOPE, service_group=quota.SERVICE_GROUP,
            period=period, period_start=quota._iso(start), period_end=quota._iso(end), time_zone="Asia/Shanghai",
            quota=12, official_used=2, observed_at=quota._iso(now-timedelta(seconds=30)), source=refresh.SOURCE,
            official_observation_sha256=hashlib.sha256(self.artifact.read_bytes()).hexdigest(),
            attestations=dict(console_account_matches=True, key_alias=refresh.KEY_ALIAS, key_scope="web_service",
                verified_at=quota._iso(now-timedelta(seconds=10)), runtime_key_observed_at=quota._iso(now-timedelta(seconds=20)),
                enterprise_certified=True, license_purchased=False, owner_risk_accepted=True, exclusive_noteai_use=True))

    def prepared(self):
        self.evidence_path.write_text(json.dumps(self.document))
        return refresh.prepare_evidence(self.evidence_path, self.artifact,
                                        configured_key=FIXTURE_KEY, observed_key=FIXTURE_KEY)

    def maintenance(self, role="postgres"):
        require_fixture()
        query = urlencode(dict(host=SOCKET, port=PORT, user=role, application_name="noteai_amap_renewal_acceptance"))
        return refresh.MaintenancePostgresStorage("postgresql:///" + REFRESH_DB + "?" + query)

    def rows(self):
        return [dict(row) for row in self.owner.fetchall("SELECT * FROM amap_quota_buckets ORDER BY period")]

    def test_real_readonly_plan_cannot_write_and_plan_leaves_baseline_unchanged(self):
        before = self.rows()
        with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
            with self.maintenance().transaction() as tx:
                state = tx.fetchone("SELECT current_setting('transaction_read_only') AS ro,current_schema() AS schema")
                self.assertEqual(state, {"ro": "on", "schema": "pg_catalog"})
                tx.execute("UPDATE public.amap_quota_buckets SET admitted_count=admitted_count+1")
        result = refresh.refresh_snapshot(self.maintenance(), self.prepared())
        self.assertEqual(result["status"], "plan_ready")
        self.assertFalse(result["changed"])
        self.assertEqual(self.rows(), before)

    def test_real_role_gates_keep_app_and_admin_unable_to_renew(self):
        before = self.rows()
        for role in ("noteai_app", "noteai_admin_runtime"):
            with self.subTest(role=role), self.assertRaisesRegex(refresh.RefreshError, "AMAP_REFRESH_MAINTENANCE_ROLE_REQUIRED"):
                refresh.refresh_snapshot(self.maintenance(role), self.prepared(), apply=True)
        self.assertEqual(self.rows(), before)

    def test_real_refresh_restores_admission_without_changing_old_rows_or_bills(self):
        before = self.rows()[0]
        self.assertEqual(quota.read_status(storage=self.app)["status"], "snapshot_expired")
        with self.assertRaisesRegex(quota.AmapQuotaError, "AMAP_QUOTA_SNAPSHOT_EXPIRED"):
            quota.admit("text", storage=self.app)
        result = refresh.refresh_snapshot(self.maintenance(), self.prepared(), apply=True)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(self.rows()[0], before)
        self.assertIsNone(self.rows()[1]["billing_observation_json"])
        self.assertEqual(self.rows()[1]["owner_authorized_at"], self.old["owner_authorized_at"])
        admission = quota.admit("text", storage=self.app)
        quota.finish(admission, status="succeeded", http_status=200, business_code="10000", storage=self.app)
        self.assertEqual(quota.read_status(storage=self.app)["remaining"], 9)

    def test_real_noop_and_conflict_preserve_admissions_and_restrictions(self):
        prepared = self.prepared()
        refresh.refresh_snapshot(self.maintenance(), prepared, apply=True)
        admission = quota.admit("detail", storage=self.app)
        quota.finish(admission, status="failed", business_code="10012", storage=self.app)
        before = self.rows()
        result = refresh.refresh_snapshot(self.maintenance(), prepared, apply=True)
        self.assertEqual((result["status"], result["admitted_count"]), ("same_month_noop", 1))
        self.document["official_used"] += 1
        with self.assertRaisesRegex(refresh.RefreshError, "AMAP_REFRESH_CURRENT_BASELINE_CONFLICT"):
            refresh.refresh_snapshot(self.maintenance(), self.prepared(), apply=True)
        self.assertEqual(self.rows(), before)

    def test_real_concurrent_refresh_and_app_allocation_use_shared_lock(self):
        prepared = self.prepared()
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: refresh.refresh_snapshot(self.maintenance(), prepared, apply=True), range(12)))
        self.assertEqual(sum(result["status"] == "applied" for result in results), 1)
        self.assertEqual(sum(result["status"] == "same_month_noop" for result in results), 11)
        with ThreadPoolExecutor(max_workers=8) as pool:
            def admission(_):
                try:
                    return quota.admit("text", storage=RealStorage("noteai_app", REFRESH_DB))
                except quota.AmapQuotaError as exc:
                    return exc.code
            outcomes = list(pool.map(admission, range(20)))
        self.assertEqual(sum(isinstance(outcome, quota.Admission) for outcome in outcomes), 10)
        self.assertEqual(outcomes.count("AMAP_MONTHLY_QUOTA_EXHAUSTED"), 10)
        self.assertEqual(self.rows()[1]["admitted_count"], 10)

    def test_real_maintenance_waits_on_original_advisory_account_lock(self):
        prepared = self.prepared()
        with connect(REFRESH_DB, autocommit=True) as holder, ThreadPoolExecutor(max_workers=1) as pool:
            holder.execute("BEGIN")
            holder.execute("SELECT pg_advisory_xact_lock(1095582032,1112752979)")
            future = pool.submit(refresh.refresh_snapshot, self.maintenance(), prepared, apply=True)
            try:
                waited = False
                deadline = time.monotonic()+2
                while time.monotonic() < deadline:
                    # PG16 caches activity information for this holder's open
                    # transaction. Refresh only its observation, not counters.
                    holder.execute("SELECT pg_stat_clear_snapshot()")
                    row = holder.execute("SELECT count(*) AS n FROM pg_stat_activity WHERE datname=%s "
                        "AND application_name='noteai_amap_renewal_acceptance' AND wait_event='advisory'", (REFRESH_DB,)).fetchone()
                    if row["n"]:
                        waited = True
                        break
                    time.sleep(0.03)
                self.assertTrue(waited, "actual PG advisory wait was not observed")
                self.assertFalse(future.done())
            finally:
                holder.execute("COMMIT")
            self.assertEqual(future.result(timeout=5)["status"], "applied")

    def test_real_database_failure_rolls_back_only_new_month(self):
        prepared = self.prepared()
        before = self.rows()
        with self.owner.transaction(write=True) as tx:
            tx.execute("CREATE FUNCTION public.amap_test_reject_insert() RETURNS trigger LANGUAGE plpgsql AS "
                       "$$ BEGIN RAISE EXCEPTION 'isolated fixture insert failure'; END $$")
            tx.execute("CREATE TRIGGER amap_test_reject_insert BEFORE INSERT ON public.amap_quota_buckets "
                       "FOR EACH ROW EXECUTE FUNCTION public.amap_test_reject_insert()")
        with self.assertRaisesRegex(refresh.RefreshError, "AMAP_REFRESH_STATE_UNAVAILABLE"):
            refresh.refresh_snapshot(self.maintenance(), prepared, apply=True)
        self.assertEqual(self.rows(), before)
        self.assertEqual(self.owner.fetchall("SELECT * FROM amap_quota_attempts"), [])

    def test_real_database_clock_rejects_future_evidence_without_write(self):
        before = self.rows()
        self.document["observed_at"] = quota._iso(datetime.now(timezone.utc)+timedelta(hours=1))
        with self.assertRaisesRegex(refresh.RefreshError, "AMAP_REFRESH_OBSERVATION_NOT_CURRENT"):
            refresh.refresh_snapshot(self.maintenance(), self.prepared(), apply=True)
        self.assertEqual(self.rows(), before)

    def test_actual_cli_plan_apply_and_repeat_receipts_are_separate(self):
        self.prepared()
        args = ["--evidence", str(self.evidence_path), "--official-observation", str(self.artifact)]
        receipts = []
        with mock.patch.dict(os.environ, {"AMAP_WEB_KEY": FIXTURE_KEY, "NOTEAI_AMAP_OBSERVED_KEY": FIXTURE_KEY,
                             "NOTEAI_AMAP_REFRESH_DSN": self.maintenance().dsn}):
            for mode in ("--plan", "--apply", "--apply"):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                    self.assertEqual(refresh.main([*args, mode]), 0)
                receipts.append(json.loads(out.getvalue()))
        self.assertEqual([result["status"] for result in receipts], ["plan_ready", "applied", "same_month_noop"])
        self.assertTrue(all(result["provider_requests"] == 0 for result in receipts))
        self.assertEqual(len(self.rows()), 2)


if __name__ == "__main__":
    unittest.main()
