"""Disposable SQLite + mock HTTP tests; fixtures are not official observations.

No production storage, Key, console or paid model is accessed. CLI's PostgreSQL
session properties are checked with a fake connection, not a live PostgreSQL
acceptance claim.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
sys.path.insert(0, str(ROOT / "tools"))
import amap_quota as quota
import refresh_amap_quota_snapshot as refresh

NOW = quota._clock("2026-10-12T06:00:00Z")
KEY = "offline-mocked-key-never-provider"


class Transaction:
    postgres = False

    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, params=()):
        return self.connection.execute(sql, params)

    def fetchone(self, sql, params=()):
        return self.execute(sql, params).fetchone()

    def fetchall(self, sql, params=()):
        return self.execute(sql, params).fetchall()


class TempStorage:
    def __init__(self, path):
        self.path = path
        self.fail_readback = False
        self.unknown_commit = False

    @contextmanager
    def transaction(self, *, write=False):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            tx = Transaction(connection)
            if self.fail_readback:
                execute = tx.execute
                def fail(sql, params=()):
                    result = execute(sql, params)
                    if sql.startswith("INSERT INTO amap_quota_buckets"):
                        raise RuntimeError("offline rollback test")
                    return result
                tx.execute = fail
            yield tx
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
            if write and self.unknown_commit:
                raise refresh.CommitUnknown()
        finally:
            connection.close()

    def fetchone(self, sql, params=()):
        with self.transaction() as tx:
            return tx.fetchone(sql, params)

    def fetchall(self, sql, params=()):
        with self.transaction() as tx:
            return tx.fetchall(sql, params)


class AmapRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="amap-refresh-offline-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.storage = TempStorage(str(self.path / "quota.sqlite3"))
        with closing(sqlite3.connect(self.storage.path)) as connection:
            connection.executescript(quota.SQLITE_SCHEMA)
        self.old = dict(account_scope=quota.ACCOUNT_SCOPE, service_group=quota.SERVICE_GROUP,
            period="2026-09", period_start="2026-09-01T00:00:00+08:00", period_end="2026-10-01T00:00:00+08:00",
            time_zone="Asia/Shanghai", quota=50000, official_used=1, observed_at="2026-09-15T14:30:00Z",
            source=refresh.SOURCE, snapshot_sha256="a" * 64, owner_authorized_at="2026-09-15T14:00:00Z",
            enterprise_certified=1, license_purchased=0, owner_risk_accepted=1, exclusive_noteai_use=1,
            admitted_count=0, billing_observation_json=None)
        with self.storage.transaction(write=True) as tx:
            tx.execute("INSERT INTO amap_quota_buckets(" + ",".join(self.old) + ") VALUES(" +
                       ",".join("?" for _ in self.old) + ")", tuple(self.old.values()))
        self.artifact = self.path / "OFFLINE_NOT_OFFICIAL.txt"
        self.artifact.write_text("Offline mocked observation, never an official console record.")
        self.document = dict(version=1, account_scope=quota.ACCOUNT_SCOPE, service_group=quota.SERVICE_GROUP,
            period="2026-10", period_start="2026-10-01T00:00:00+08:00", period_end="2026-11-01T00:00:00+08:00",
            time_zone="Asia/Shanghai", quota=50000, official_used=4, observed_at="2026-10-12T05:00:00Z",
            source=refresh.SOURCE, official_observation_sha256=hashlib.sha256(self.artifact.read_bytes()).hexdigest(),
            attestations=dict(console_account_matches=True, key_alias=refresh.KEY_ALIAS, key_scope="web_service",
                verified_at="2026-10-12T05:10:00Z", runtime_key_observed_at="2026-10-12T05:05:00Z",
                enterprise_certified=True, license_purchased=False, owner_risk_accepted=True, exclusive_noteai_use=True))
        self.evidence_path = self.path / "OFFLINE_NOT_OFFICIAL.json"
        self.clock = mock.patch.object(quota, "_database_now", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def prepare(self, **kwargs):
        self.evidence_path.write_text(json.dumps(self.document))
        return refresh.prepare_evidence(self.evidence_path, self.artifact,
                                        configured_key=kwargs.get("configured_key", KEY),
                                        observed_key=kwargs.get("observed_key", KEY))

    def rows(self):
        return [dict(row) for row in self.storage.fetchall("SELECT * FROM amap_quota_buckets ORDER BY period")]

    def assert_rejected(self, code, operation):
        before = self.rows()
        with self.assertRaisesRegex(refresh.RefreshError, code):
            operation()
        self.assertEqual(self.rows(), before)

    def test_plan_is_readonly_and_expired_baseline_is_not_reset(self):
        before = self.rows()
        status = quota.read_status(storage=self.storage)
        self.assertEqual(status["status"], "snapshot_expired")
        self.assertTrue(status["renewal_required"])
        self.assertIsNone(status["remaining"])
        self.assertEqual(status["renewal_action"], "verify_and_append_current_month_observation")
        with self.assertRaisesRegex(quota.AmapQuotaError, "AMAP_QUOTA_SNAPSHOT_EXPIRED"):
            quota.admit("text", storage=self.storage)
        plan = refresh.refresh_snapshot(self.storage, self.prepare())
        self.assertEqual(plan["status"], "plan_ready")
        self.assertFalse(plan["changed"])
        self.assertEqual(plan["provider_requests"], 0)
        self.assertEqual(self.rows(), before)

    def test_first_snapshot_is_not_guessed_from_runtime_or_month_calendar(self):
        with self.storage.transaction(write=True) as tx:
            tx.execute("DELETE FROM amap_quota_buckets")
        self.assert_rejected("AMAP_REFRESH_ORIGINAL_SNAPSHOT_REQUIRED",
                             lambda: refresh.refresh_snapshot(self.storage, self.prepare(), apply=True))

    def test_new_month_append_keeps_originals_and_restores_controlled_admission(self):
        before = self.rows()[0]
        result = refresh.refresh_snapshot(self.storage, self.prepare(), apply=True)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["evidence_scope"], "operator_attested_console_observation")
        self.assertEqual(self.rows()[0], before)
        self.assertEqual(self.rows()[1]["owner_authorized_at"], self.old["owner_authorized_at"])
        self.assertIsNone(self.rows()[1]["billing_observation_json"])
        admission = quota.admit("text", storage=self.storage)
        quota.finish(admission, status="succeeded", business_code="10000", http_status=200, storage=self.storage)
        self.assertEqual(quota.read_status(storage=self.storage)["remaining"], 49995)
        self.assertFalse(quota.read_status(storage=self.storage)["renewal_required"])

    def test_normal_expired_refresh_failure_and_recovery_mock_http(self):
        import fact_enrichment as facts
        import httpx
        original_admit, original_finish = quota.admit, quota.finish
        calls = []
        def response(request):
            calls.append(request)
            return httpx.Response(200, json={"status": "1", "infocode": "10000", "pois": [{"name": "离线汤泉"}]})
        with mock.patch.object(quota, "admit", side_effect=lambda endpoint: original_admit(endpoint, storage=self.storage)), \
             mock.patch.object(quota, "finish", side_effect=lambda admission, **kw: original_finish(admission, storage=self.storage, **kw)), \
             httpx.Client(transport=httpx.MockTransport(response)) as client:
            with self.assertRaisesRegex(facts.FactProviderError, "AMAP_QUOTA_SNAPSHOT_EXPIRED"):
                facts._fact_get(client, "https://restapi.amap.com/v3/place/text", params={"key": KEY})
            self.assertEqual(calls, [])
            prepared = self.prepare()
            self.storage.fail_readback = True
            self.assert_rejected("AMAP_REFRESH_STATE_UNAVAILABLE",
                                 lambda: refresh.refresh_snapshot(self.storage, prepared, apply=True))
            self.storage.fail_readback = False
            self.assertEqual(calls, [])
            refresh.refresh_snapshot(self.storage, prepared, apply=True)
            result = facts._amap_response(facts._fact_get(client, "https://restapi.amap.com/v3/place/text", params={"key": KEY}))
            self.assertEqual(result["pois"][0]["name"], "离线汤泉")
            self.assertEqual(len(calls), 1)
        reason = facts._amap_unavailable_reason("AMAP_QUOTA_SNAPSHOT_EXPIRED")
        self.assertIn("需由维护核实并续期", reason)
        self.assertIn("不会编造", reason)
        self.assertNotIn("amap_quota_snapshot", reason)

    def test_same_query_failed_lookup_is_not_cached_after_refresh(self):
        import fact_enrichment as facts
        import httpx
        original_admit, original_finish, original_client = quota.admit, quota.finish, httpx.Client
        calls = []
        def response(request):
            calls.append(request)
            return httpx.Response(200, json={"status": "1", "infocode": "10000", "pois": [{
                "id": "", "name": "离线餐厅", "address": "杭州市西湖区离线路1号",
                "biz_ext": {"opentime": "10:00-23:00"}}]})
        def client(**kwargs):
            return original_client(transport=httpx.MockTransport(response), **kwargs)
        with mock.patch.dict(os.environ, {"AMAP_WEB_KEY": KEY, "NOTEAI_FACT_SEARCH": "1",
                             "NOTEAI_FACT_SEARCH_CACHE_TTL": "300"}, clear=True), \
             mock.patch.dict(facts._CACHE, {}, clear=True), \
             mock.patch.object(facts, "_authorized_fact_items", return_value=[]), \
             mock.patch.object(facts, "build_fact_query", return_value="离线餐厅"), \
             mock.patch.object(quota, "admit", side_effect=lambda endpoint: original_admit(endpoint, storage=self.storage)), \
             mock.patch.object(quota, "finish", side_effect=lambda admission, **kw: original_finish(admission, storage=self.storage, **kw)), \
             mock.patch.object(facts.httpx, "Client", side_effect=client):
            failed = facts.enrich_content_facts("美食", "离线餐厅", "查真实营业信息", provider="amap")
            self.assertEqual(failed["error_code"], "AMAP_QUOTA_SNAPSHOT_EXPIRED")
            self.assertEqual(failed["facts"], {})
            self.assertEqual(failed["calls"]["http_requests"], 0)
            self.assertEqual(facts._CACHE, {})
            refresh.refresh_snapshot(self.storage, self.prepare(), apply=True)
            restored = facts.enrich_content_facts("美食", "离线餐厅", "查真实营业信息", provider="amap")
            self.assertFalse(restored.get("error_code"))
            self.assertEqual(restored["facts"]["address"], "杭州市西湖区离线路1号")
            self.assertEqual(restored["facts"]["hours"], "10:00-23:00")
            self.assertNotIn("price", restored["facts"])
            self.assertFalse(restored.get("cached", False))
            self.assertEqual(restored["calls"]["http_requests"], 1)
            self.assertEqual(len(calls), 1)


    def test_quota_exhausted_after_verified_new_month_does_not_dispatch(self):
        self.document.update(quota=2, official_used=2)
        result = refresh.refresh_snapshot(self.storage, self.prepare(), apply=True)
        self.assertEqual(result["remaining"], 0)
        self.assertEqual(quota.read_status(storage=self.storage)["status"], "quota_exhausted")
        with self.assertRaisesRegex(quota.AmapQuotaError, "AMAP_MONTHLY_QUOTA_EXHAUSTED"):
            quota.admit("text", storage=self.storage)
        self.assertEqual(self.storage.fetchall("SELECT * FROM amap_quota_attempts"), [])

    def test_same_month_repeat_noop_preserves_admissions_restrictions_and_bill(self):
        prepared = self.prepare()
        refresh.refresh_snapshot(self.storage, prepared, apply=True)
        admission = quota.admit("detail", storage=self.storage)
        quota.finish(admission, status="failed", business_code="10012", storage=self.storage)
        with self.storage.transaction(write=True) as tx:
            tx.execute("UPDATE amap_quota_buckets SET billing_observation_json=? WHERE period='2026-10'", ("{}",))
        before = self.rows()
        # No new quota is created, so original evidence age cannot reset counts.
        with mock.patch.object(quota, "_database_now", return_value=NOW + timedelta(days=2)):
            result = refresh.refresh_snapshot(self.storage, prepared, apply=True)
        self.assertEqual(result["status"], "same_month_noop")
        self.assertFalse(result["changed"])
        self.assertEqual(result["admitted_count"], 1)
        self.assertEqual(result["blocked_endpoints"]["detail"], "10012")
        self.assertEqual(self.rows(), before)

    def test_same_month_conflict_never_upserts_or_resets(self):
        refresh.refresh_snapshot(self.storage, self.prepare(), apply=True)
        quota.admit("text", storage=self.storage)
        self.document["official_used"] += 1
        self.assert_rejected("AMAP_REFRESH_CURRENT_BASELINE_CONFLICT",
                             lambda: refresh.refresh_snapshot(self.storage, self.prepare(), apply=True))

    def test_old_auth_restriction_survives_new_month(self):
        with mock.patch.object(quota, "_database_now", return_value=quota._clock("2026-09-15T15:00:00Z")):
            admission = quota.admit("detail", storage=self.storage)
            quota.finish(admission, status="failed", business_code="10012", storage=self.storage)
        result = refresh.refresh_snapshot(self.storage, self.prepare(), apply=True)
        self.assertEqual(result["blocked_endpoints"]["detail"], "10012")
        with self.assertRaisesRegex(quota.AmapQuotaError, "AMAP_PROVIDER_ACCESS_RESTRICTED"):
            quota.admit("detail", storage=self.storage)
        self.assertIsInstance(quota.admit("text", storage=self.storage), quota.Admission)

    def test_concurrent_operator_attempts_one_append_all_others_noop(self):
        prepared = self.prepare()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: refresh.refresh_snapshot(TempStorage(self.storage.path), prepared, apply=True), range(12)))
        self.assertEqual(sum(row["status"] == "applied" for row in results), 1)
        self.assertEqual(sum(row["status"] == "same_month_noop" for row in results), 11)
        self.assertEqual(len(self.rows()), 2)

    def test_unknown_commit_is_not_retried_or_reported_as_unchanged(self):
        prepared = self.prepare()
        self.storage.unknown_commit = True
        with self.assertRaises(refresh.CommitUnknown):
            refresh.refresh_snapshot(self.storage, prepared, apply=True)
        self.storage.unknown_commit = False
        self.assertEqual(len(self.rows()), 2)
        # Explicit manual readback is a separate SELECT-only operation.
        result = refresh.refresh_snapshot(self.storage, prepared)
        self.assertEqual(result["status"], "same_month_noop")
        self.assertEqual(result["snapshot_sha256"], prepared.baseline["snapshot_sha256"])

    def test_zero_quota_keeps_safe_hold_without_manufacturing_positive_quota(self):
        self.document.update(quota=0, official_used=0)
        self.assert_rejected("AMAP_REFRESH_OFFICIAL_QUOTA_ZERO_HOLD",
                             lambda: refresh.refresh_snapshot(self.storage, self.prepare(), apply=True))

    def test_future_observation_rejected(self):
        self.document["observed_at"] = "2026-10-12T07:00:00Z"
        self.assert_rejected("AMAP_REFRESH_OBSERVATION_NOT_CURRENT",
                             lambda: refresh.refresh_snapshot(self.storage, self.prepare(), apply=True))

    def test_future_or_approximate_month_boundaries_rejected(self):
        for changes in ({"period": "2026-11"}, {"period_start": "2026-10-01T00:00:00Z"},
                        {"period_end": "2026-11-01T00:00:00Z"}):
            with self.subTest(changes=changes):
                saved = self.document.copy()
                self.document.update(changes)
                self.assert_rejected("AMAP_REFRESH_PERIOD_NOT_CURRENT",
                                     lambda: refresh.refresh_snapshot(self.storage, self.prepare(), apply=True))
                self.document = saved

    def test_stale_new_observation_is_not_a_current_quota_refresh(self):
        self.document["observed_at"] = "2026-10-10T05:00:00Z"
        self.assert_rejected("AMAP_REFRESH_OBSERVATION_TOO_OLD",
                             lambda: refresh.refresh_snapshot(self.storage, self.prepare(), apply=True))

    def test_status_and_admission_share_ten_second_database_clock_guard(self):
        refresh.refresh_snapshot(self.storage, self.prepare(), apply=True)
        end = quota._clock(self.document["period_end"])
        for offset, expected in ((11, "ready"), (10, "snapshot_expired"), (9, "snapshot_expired"), (0, "snapshot_expired")):
            with self.subTest(offset=offset), mock.patch.object(quota, "_database_now", return_value=end - timedelta(seconds=offset)):
                status = quota.read_status(storage=self.storage)
                self.assertEqual(status["status"], expected)
                if expected == "snapshot_expired":
                    with self.assertRaisesRegex(quota.AmapQuotaError, "AMAP_QUOTA_SNAPSHOT_EXPIRED"):
                        quota.admit("text", storage=self.storage)
        with mock.patch.object(quota, "_database_now", return_value=end - timedelta(seconds=9)):
            self.assert_rejected("AMAP_REFRESH_PERIOD_CLOSING",
                                 lambda: refresh.refresh_snapshot(self.storage, self.prepare(), apply=True))

    def test_admin_soon_warning_uses_database_clock_within_seventy_two_hours(self):
        refresh.refresh_snapshot(self.storage, self.prepare(), apply=True)
        end = quota._clock(self.document["period_end"])
        for hours, expected in ((73, False), (72, True), (24, True)):
            with self.subTest(hours=hours), mock.patch.object(quota, "_database_now", return_value=end - timedelta(hours=hours)):
                status = quota.read_status(storage=self.storage)
                self.assertEqual(status["status"], "ready")
                self.assertEqual(status["renewal_due_soon"], expected)
                self.assertFalse(status["renewal_required"])
        with mock.patch.object(quota, "_database_now", return_value=end - timedelta(seconds=9)):
            status = quota.read_status(storage=self.storage)
            self.assertFalse(status["renewal_due_soon"])
            self.assertTrue(status["renewal_required"])
            self.assertEqual(status["renewal_action"], "verify_new_month_observation_at_period_end")

    def test_missing_evidence_document_is_not_reconstructed(self):
        self.prepare()
        self.evidence_path.unlink()
        self.assert_rejected("AMAP_REFRESH_EVIDENCE_UNREADABLE", lambda: refresh.prepare_evidence(
            self.evidence_path, self.artifact, configured_key=KEY, observed_key=KEY))

    def test_wrong_key_alias_account_scope_or_artifact_rejected_without_writes(self):
        self.assert_rejected("AMAP_REFRESH_KEY_MISMATCH", lambda: self.prepare(observed_key="wrong-offline-key"))
        self.assert_rejected("AMAP_REFRESH_KEY_OBSERVATION_REQUIRED", lambda: self.prepare(configured_key=None))
        saved = self.document["attestations"].copy()
        for changes in ({"key_alias": "other-key"}, {"console_account_matches": False}, {"exclusive_noteai_use": False}):
            self.document["attestations"].update(changes)
            self.assert_rejected("AMAP_REFRESH_ATTESTATION_INVALID", self.prepare)
            self.document["attestations"] = saved.copy()
        self.document["official_observation_sha256"] = "b" * 64
        self.assert_rejected("AMAP_REFRESH_OFFICIAL_ARTIFACT_MISMATCH", self.prepare)
        self.artifact.unlink()
        self.assert_rejected("AMAP_REFRESH_OFFICIAL_ARTIFACT_REQUIRED", self.prepare)

    def test_cli_error_does_not_print_key_dsn_or_traceback_and_imports_no_db(self):
        self.prepare()
        with mock.patch.dict(os.environ, {"AMAP_WEB_KEY": KEY, "NOTEAI_AMAP_OBSERVED_KEY": KEY,
                            "NOTEAI_AMAP_REFRESH_DSN": "secret-invalid-dsn"}), mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            result = refresh.main(["--evidence", str(self.evidence_path), "--official-observation", str(self.artifact)])
        self.assertEqual(result, 1)
        data = json.loads(out.getvalue())
        self.assertEqual(data["code"], "AMAP_REFRESH_MAINTENANCE_DSN_REQUIRED")
        for secret in (KEY, "secret-invalid-dsn", "Traceback"):
            self.assertNotIn(secret, out.getvalue())
        self.assertNotIn("import db", Path(refresh.__file__).read_text().replace("No db import", ""))

    def test_cli_commit_unknown_reports_manual_readback_without_retry(self):
        self.prepare()
        with mock.patch.dict(os.environ, {"AMAP_WEB_KEY": KEY, "NOTEAI_AMAP_OBSERVED_KEY": KEY,
                             "NOTEAI_AMAP_REFRESH_DSN": "postgresql:///offline-never-connected"}), \
             mock.patch.object(refresh, "refresh_snapshot", side_effect=refresh.CommitUnknown()) as dispatch, \
             mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            code = refresh.main(["--evidence", str(self.evidence_path), "--official-observation", str(self.artifact), "--apply"])
        self.assertEqual(code, 2)
        self.assertEqual(dispatch.call_count, 1)
        result = json.loads(out.getvalue())
        self.assertEqual(result["status"], "commit_unknown")
        self.assertIsNone(result["changed"])
        self.assertTrue(result["manual_readback_required"])
        self.assertFalse(result["automatic_retry"])

    def test_invalid_cli_arguments_do_not_echo_accidentally_supplied_secret(self):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
             mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            with self.assertRaises(SystemExit) as exit:
                refresh.main(["--dsn", "postgresql://password-accidentally-in-argv"])
        self.assertEqual(exit.exception.code, 2)
        self.assertEqual(json.loads(out.getvalue())["code"], "AMAP_REFRESH_ARGUMENTS_INVALID")
        self.assertNotIn("password-accidentally-in-argv", out.getvalue() + err.getvalue())


class FakePostgresConnection:
    def __init__(self, role="maintenance_role", insert=True, fail_commit=False):
        self.role, self.insert, self.fail_commit = role, insert, fail_commit
        self.commands = []
        self.closed = False

    def execute(self, sql, params=()):
        self.commands.append(sql)
        if sql == "COMMIT" and self.fail_commit:
            raise RuntimeError("unknown offline response")
        value = {"role": self.role, "can_read": True, "can_insert": self.insert} if sql.startswith("SELECT current_user") else None
        return SimpleNamespace(fetchone=lambda: value)

    def close(self):
        self.closed = True


class AmapRefreshSessionTests(unittest.TestCase):
    def connection(self, **kwargs):
        connection = FakePostgresConnection(**kwargs)
        patch = mock.patch.dict(sys.modules, {"psycopg": SimpleNamespace(connect=lambda *args, **kw: connection),
                              "psycopg.rows": SimpleNamespace(dict_row=object())})
        patch.start()
        self.addCleanup(patch.stop)
        return connection

    def test_default_plan_postgres_transaction_is_read_only_no_init(self):
        connection = self.connection(insert=False)
        with refresh.MaintenancePostgresStorage("postgresql:///offline-no-provider").transaction() as tx:
            self.assertTrue(tx.postgres)
        self.assertEqual(connection.commands[0:2], ["BEGIN", "SET TRANSACTION READ ONLY"])
        self.assertIn("COMMIT", connection.commands)
        self.assertTrue(connection.closed)
        self.assertFalse(any(command.startswith(("CREATE", "INSERT", "UPDATE", "DELETE")) for command in connection.commands))

    def test_runtime_admin_roles_and_missing_insert_permission_are_rejected(self):
        for role, insert in (("noteai_app", True), ("noteai_admin_runtime", True), ("maintenance_role", False)):
            with self.subTest(role=role):
                connection = self.connection(role=role, insert=insert)
                with self.assertRaisesRegex(refresh.RefreshError, "AMAP_REFRESH_MAINTENANCE_ROLE_REQUIRED"):
                    with refresh.MaintenancePostgresStorage("postgresql:///offline-no-provider").transaction(write=True):
                        self.fail("unprivileged session was accepted")
                self.assertIn("ROLLBACK", connection.commands)
                self.assertNotIn("COMMIT", connection.commands)

    def test_commit_failure_does_not_retry(self):
        connection = self.connection(fail_commit=True)
        with self.assertRaises(refresh.CommitUnknown):
            with refresh.MaintenancePostgresStorage("postgresql:///offline-no-provider").transaction(write=True):
                pass
        self.assertEqual(connection.commands.count("COMMIT"), 1)
        self.assertTrue(connection.closed)


if __name__ == "__main__":
    unittest.main()
