"""Synthetic entitlement documents and disposable SQLite; no official acceptance.

The files explicitly say OFFLINE NOT OFFICIAL. No real Key, supplier, paid model,
production DB, scheduler or live PostgreSQL is used by this module.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
sys.path.insert(0, str(ROOT / "tools"))
from tests import test_amap_quota_refresh as offline
KEY, NOW = offline.KEY, offline.NOW
import amap_quota as quota
import derive_amap_monthly_budget as recurring
import refresh_amap_quota_snapshot as refresh


class RecurringBudgetTests(unittest.TestCase):
    rows = offline.AmapRefreshTests.rows

    def setUp(self):
        offline.AmapRefreshTests.setUp(self)
        # These SQL/business-clock tests inject root-owned metadata. The
        # separate worker tests cover bounded secure-file policy validation.
        self.rules_status = None
        patch = mock.patch.object(quota, "_read_rules_status", side_effect=lambda path: self.rules_status())
        patch.start()
        self.addCleanup(patch.stop)

    def prepare(self, *, runtime=True, **keys):
        self.entitlement_artifact = self.path / "OFFLINE_NOT_OFFICIAL_ENTITLEMENT.txt"
        self.entitlement_artifact.write_text("OFFLINE NOT OFFICIAL: mock finite monthly allowance contract.")
        self.rules_artifact = self.path / "OFFLINE_NOT_OFFICIAL_RULES.txt"
        self.rules_artifact.write_text("OFFLINE NOT OFFICIAL: mock shared basic-search monthly rules.")
        self.entitlement_document = getattr(self, "entitlement_document", dict(version=1,
            account_scope=quota.ACCOUNT_SCOPE, service_group=quota.SERVICE_GROUP, time_zone="Asia/Shanghai",
            monthly_quota=50000, valid_from="2026-09-15T00:00:00.000000+00:00",
            valid_until="2027-09-15T00:00:00.000000+00:00", verified_at="2026-09-16T00:00:00.000000+00:00",
            official_entitlement_sha256=hashlib.sha256(self.entitlement_artifact.read_bytes()).hexdigest(),
            official_rules_sha256=hashlib.sha256(self.rules_artifact.read_bytes()).hexdigest(),
            attestations=dict(console_account_matches=True, key_alias="noteai-rot-0902", key_scope="web_service",
                enterprise_certified=True, license_purchased=False, owner_risk_accepted=True,
                exclusive_noteai_use=True, all_shared_search_metered=True,
                metering_continuous_since="2026-09-15T00:00:00.000000+00:00")))
        self.entitlement_path = self.path / "OFFLINE_NOT_OFFICIAL_ENTITLEMENT.json"
        self.entitlement_path.write_text(json.dumps(self.entitlement_document))
        evidence = recurring.prepare_entitlement(self.entitlement_path, self.entitlement_artifact, self.rules_artifact,
            configured_key=keys.get("configured_key", KEY), approved_key=keys.get("approved_key", KEY),
            observed_key=keys.get("observed_key", KEY))
        if runtime:
            evidence.runtime.update(NOTEAI_AMAP_RECURRING_ENTITLEMENT_SHA256=evidence.metadata["entitlement_sha256"],
                NOTEAI_AMAP_RECURRING_RULES_SHA256=evidence.metadata["official_rules_sha256"])
        else:
            evidence.runtime.update(NOTEAI_AMAP_RECURRING_ENTITLEMENT_SHA256=None,
                NOTEAI_AMAP_RECURRING_RULES_SHA256=None)
        evidence.runtime["NOTEAI_AMAP_RECURRING_RULES_STATUS_FILE"] = "/run/offline-nonsecret-rules/rules-status.json"
        self.rules_status = lambda: dict(schema="noteai.amap_recurring_rules_status.v1", state="VERIFIED",
            source_url=quota.PUBLIC_RULES_URL, observed_at=quota._iso(quota._database_now(None)),
            entitlement_sha256=evidence.metadata["entitlement_sha256"],
            official_entitlement_artifact_sha256=evidence.metadata["official_entitlement_sha256"],
            rules_sha256=evidence.metadata["official_rules_sha256"],
            valid_from=evidence.metadata["valid_from"], valid_until=evidence.metadata["valid_until"])
        return evidence

    def apply(self, evidence=None):
        return recurring.produce_month_budget(self.storage, evidence or self.prepare(), apply=True)

    def assert_hold(self, code, operation):
        before = self.rows()
        with self.assertRaisesRegex(refresh.RefreshError, code):
            operation()
        self.assertEqual(self.rows(), before)

    def old_attempt(self, *, status="unknown", completed=None):
        identity = str(uuid.uuid4())
        with self.storage.transaction(write=True) as tx:
            tx.execute("UPDATE amap_quota_buckets SET admitted_count=admitted_count+1 WHERE period='2026-09'")
            tx.execute("INSERT INTO amap_quota_attempts(id,account_scope,service_group,period,endpoint,admitted_at,status,completed_at) "
                "VALUES(?,?,?,'2026-09','text',?,?,?)", (identity, quota.ACCOUNT_SCOPE, quota.SERVICE_GROUP,
                    "2026-09-30T15:59:48.000000+00:00", status, completed))
        return identity

    def test_default_plan_has_no_writes_or_provider_requests(self):
        prepared = self.prepare()
        before = self.rows()
        result = recurring.produce_month_budget(self.storage, prepared)
        self.assertEqual(result["status"], "plan_ready")
        self.assertEqual(result["provider_requests"], 0)
        self.assertIsNone(result["official_used"])
        self.assertEqual(self.rows(), before)

    def test_derived_status_is_local_budget_not_official_zero(self):
        prepared = self.prepare()
        self.apply(prepared)
        with mock.patch.dict(os.environ, prepared.runtime, clear=True):
            state = quota.read_status(storage=self.storage)
        self.assertEqual(state["status"], "ready")
        snapshot = state["snapshot"]
        self.assertIsNone(snapshot["official_used"])
        self.assertIsNone(snapshot["observed_at"])
        self.assertEqual(snapshot["budget_derived_at"], quota._iso(NOW))
        self.assertEqual(snapshot["unmetered_usage_upper_bound"], 0)
        self.assertFalse(snapshot["official_usage_observed"])
        self.assertEqual(snapshot["source"], quota.RECURRING_SOURCE.rstrip(":"))
        serialized = json.dumps(state)
        self.assertNotIn(KEY, serialized)
        self.assertNotIn(hashlib.sha256(KEY.encode()).hexdigest(), serialized)
        self.assertLessEqual(len(self.rows()[-1]["source"]), 500)
        self.assertIsNone(self.rows()[-1]["billing_observation_json"])

    def test_november_december_january_use_same_finite_entitlement(self):
        prepared = self.prepare()
        for instant, period in ((NOW, "2026-10"), ("2026-11-01T00:01:00+08:00", "2026-11"),
            ("2026-12-01T00:01:00+08:00", "2026-12"), ("2027-01-01T00:01:00+08:00", "2027-01")):
            with mock.patch.object(quota, "_database_now", return_value=quota._clock(instant)):
                result = self.apply(prepared)
                self.assertEqual(result["period"], period)
                with mock.patch.dict(os.environ, prepared.runtime, clear=True):
                    self.assertIsInstance(quota.admit("text", storage=self.storage), quota.Admission)
        self.assertEqual(len(self.rows()), 5)
        self.assertEqual(self.rows()[0]["official_used"], 1)

    def test_same_month_noop_preserves_admissions_blocks_and_unknown_billing(self):
        prepared = self.prepare()
        self.apply(prepared)
        with mock.patch.dict(os.environ, prepared.runtime, clear=True):
            admitted = quota.admit("text", storage=self.storage)
            quota.finish(admitted, status="failed", http_status=403, storage=self.storage)
        before = self.rows()
        result = self.apply(prepared)
        self.assertEqual(result["status"], "same_month_noop")
        self.assertEqual(result["admitted_count"], 1)
        self.assertEqual(self.rows(), before)
        self.assertEqual(result["blocked_endpoints"]["text"], "HTTP_403")

    def test_no_configuration_cannot_become_ready(self):
        prepared = self.prepare(runtime=False)
        self.assert_hold("CONFIGURATION_REQUIRED", lambda: self.apply(prepared))

    def test_key_change_stops_each_active_admission(self):
        prepared = self.prepare()
        self.apply(prepared)
        changed = dict(prepared.runtime, AMAP_WEB_KEY="offline changed Key")
        before = self.rows()
        with mock.patch.dict(os.environ, changed, clear=True):
            with self.assertRaisesRegex(quota.AmapQuotaError, "BINDING_CHANGED"):
                quota.admit("text", storage=self.storage)
            self.assertEqual(quota.read_status(storage=self.storage)["status"], "recurring_hold")
        self.assertEqual(self.rows(), before)

    def test_changing_both_key_env_values_cannot_rebind_existing_budget(self):
        prepared = self.prepare()
        self.apply(prepared)
        changed = dict(prepared.runtime, AMAP_WEB_KEY="offline replacement key",
            NOTEAI_AMAP_RECURRING_APPROVED_KEY="offline replacement key")
        with mock.patch.dict(os.environ, changed, clear=True):
            with self.assertRaisesRegex(quota.AmapQuotaError, "BINDING_CHANGED"):
                quota.admit("text", storage=self.storage)
            serialized = json.dumps(quota.read_status(storage=self.storage))
        self.assertNotIn('"k"', serialized)
        self.assertNotIn(hashlib.sha256(KEY.encode()).hexdigest(), serialized)
        self.assertNotIn(KEY, repr(prepared))
        self.assertNotIn(hashlib.sha256(KEY.encode()).hexdigest(), repr(prepared))

    def test_next_month_old_entitlement_cannot_rebind_key(self):
        self.apply(self.prepare())
        changed = self.prepare(configured_key="offline new key", approved_key="offline new key",
            observed_key="offline new key")
        with mock.patch.object(quota, "_database_now", return_value=quota._clock("2026-11-01T00:01:00+08:00")):
            self.assert_hold("BINDING_CHANGED", lambda: self.apply(changed))

    def test_changed_official_rules_stop_each_active_admission(self):
        prepared = self.prepare()
        self.apply(prepared)
        changed = dict(prepared.runtime, NOTEAI_AMAP_RECURRING_RULES_SHA256="c" * 64)
        with mock.patch.dict(os.environ, changed, clear=True):
            with self.assertRaisesRegex(quota.AmapQuotaError, "RULES_CHANGED"):
                quota.admit("detail", storage=self.storage)

    def test_observer_failure_stale_future_or_wrong_rights_holds_existing_month(self):
        prepared = self.prepare()
        self.apply(prepared)
        valid = self.rules_status()
        before = self.rows()
        for change in ({"state": "HOLD"}, {"observed_at": quota._iso(NOW-timedelta(hours=7, seconds=1))},
                       {"observed_at": quota._iso(NOW+timedelta(seconds=1))},
                       {"entitlement_sha256": "f" * 64}, {"rules_sha256": "c" * 64}):
            self.rules_status = lambda change=change: dict(valid, **change)
            with mock.patch.dict(os.environ, prepared.runtime, clear=True):
                with self.assertRaisesRegex(quota.AmapQuotaError, "RULES_UNCONFIRMED"):
                    quota.admit("text", storage=self.storage)
        self.assertEqual(self.rows(), before)

    def test_missing_runtime_configuration_holds_existing_derived_budget(self):
        self.apply()
        with mock.patch.dict(os.environ, {}, clear=True):
            state = quota.read_status(storage=self.storage)
            self.assertEqual(state["reason"], "AMAP_QUOTA_RECURRING_CONFIGURATION_REQUIRED")
            self.assertIsNone(state["remaining"])

    def test_old_unknown_reserved_and_late_completion_are_reserved(self):
        identities = [self.old_attempt(), self.old_attempt(status="reserved"),
            self.old_attempt(status="succeeded", completed="2026-10-01T00:00:01+08:00")]
        prepared = self.prepare()
        result = self.apply(prepared)
        self.assertEqual(result["unmetered_usage_upper_bound"], 3)
        self.assertEqual(result["remaining"], 49997)
        with mock.patch.object(quota, "_database_now", return_value=quota._clock("2026-11-01T00:01:00+08:00")):
            result = self.apply(prepared)
            self.assertEqual(result["unmetered_usage_upper_bound"], 2)
        self.assertEqual(len(self.storage.fetchall("SELECT id FROM amap_quota_attempts")), len(identities))
        self.assertEqual(self.rows()[0]["admitted_count"], 3)

    def test_old_durable_denial_is_not_cleared_by_month_derivation(self):
        with self.storage.transaction(write=True) as tx:
            tx.execute("UPDATE amap_quota_buckets SET account_block_code='10044' WHERE period='2026-09'")
        prepared = self.prepare()
        self.assertEqual(self.apply(prepared)["blocked_endpoints"]["text"], "10044")
        with mock.patch.dict(os.environ, prepared.runtime, clear=True):
            with self.assertRaisesRegex(quota.AmapQuotaError, "ACCESS_RESTRICTED"):
                quota.admit("text", storage=self.storage)
        self.assertEqual(self.rows()[0]["account_block_code"], "10044")

    def test_quota_exhaustion_and_next_month_recovery_keep_risk_reserve(self):
        self.old_attempt()
        prepared = self.prepare()
        self.apply(prepared)
        with self.storage.transaction(write=True) as tx:
            tx.execute("UPDATE amap_quota_buckets SET admitted_count=49999 WHERE period='2026-10'")
        with mock.patch.dict(os.environ, prepared.runtime, clear=True):
            with self.assertRaisesRegex(quota.AmapQuotaError, "MONTHLY_QUOTA_EXHAUSTED"):
                quota.admit("text", storage=self.storage)
            with mock.patch.object(quota, "_database_now", return_value=quota._clock("2026-11-01T00:01:00+08:00")):
                self.assertEqual(self.apply(prepared)["remaining"], 49999)
                self.assertIsInstance(quota.admit("text", storage=self.storage), quota.Admission)
        self.assertEqual(self.rows()[1]["admitted_count"], 49999)

    def test_unknown_commit_is_readonly_reconciled_and_never_reapplied(self):
        prepared = self.prepare()
        plan = recurring.produce_month_budget(self.storage, prepared)
        marker = self.path / "2026-10.attempt.json"
        recurring._claim_attempt(marker, plan)
        self.storage.unknown_commit = True
        with self.assertRaises(refresh.CommitUnknown):
            self.apply(prepared)
        self.storage.unknown_commit = False
        result = recurring.produce_month_budget(self.storage, prepared)
        self.assertEqual(result["status"], "same_month_noop")
        self.assert_hold("RECONCILIATION_REQUIRED", lambda: recurring._claim_attempt(marker, plan))
        self.assertEqual(len(self.rows()), 2)

    def test_insert_failure_rolls_back_without_extending_old_baseline(self):
        prepared = self.prepare()
        self.storage.fail_readback = True
        self.assert_hold("STATE_UNAVAILABLE", lambda: self.apply(prepared))
        self.assertEqual(len(self.rows()), 1)

    def test_concurrent_producers_append_once(self):
        prepared = self.prepare()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: self.apply(prepared), range(2)))
        self.assertEqual(sorted(result["status"] for result in results), ["applied", "same_month_noop"])
        self.assertEqual(len(self.rows()), 2)

    def test_conflicting_same_month_entitlement_cannot_reset_admissions(self):
        original = self.prepare()
        self.apply(original)
        self.entitlement_document["verified_at"] = "2026-09-17T00:00:00.000000+00:00"
        changed = self.prepare()
        self.assert_hold("BASELINE_CONFLICT", lambda: self.apply(changed))

    def test_future_verification_is_rejected(self):
        self.prepare()
        self.entitlement_document["verified_at"] = "2026-11-01T00:00:00.000000+00:00"
        future = self.prepare()
        self.assert_hold("MONTH_NOT_COVERED", lambda: self.apply(future))

    def test_metering_gap_is_rejected(self):
        self.prepare()
        self.entitlement_document["attestations"]["metering_continuous_since"] = "2026-10-02T00:00:00.000000+00:00"
        incomplete = self.prepare()
        self.assert_hold("SHARED_METERING_GAP", lambda: self.apply(incomplete))

    def test_finite_entitlement_cannot_create_month_outside_coverage(self):
        prepared = self.prepare()
        for instant in ("2026-09-16T00:01:00+08:00", "2027-09-15T00:00:00+00:00",
                        "2027-10-01T00:01:00+08:00"):
            with mock.patch.object(quota, "_database_now", return_value=quota._clock(instant)):
                self.assert_hold("MONTH_NOT_COVERED", lambda: self.apply(prepared))

    def test_last_partial_month_retains_budget_until_exact_rights_margin(self):
        prepared = self.prepare()
        with mock.patch.object(quota, "_database_now", return_value=quota._clock("2027-09-01T00:01:00+08:00")):
            self.assertEqual(self.apply(prepared)["period"], "2027-09")
        expiry = quota._clock(prepared.metadata["valid_until"])
        with mock.patch.dict(os.environ, prepared.runtime, clear=True):
            with mock.patch.object(quota, "_database_now", return_value=expiry-timedelta(seconds=11)):
                self.assertIsInstance(quota.admit("text", storage=self.storage), quota.Admission)
                state = quota.read_status(storage=self.storage)
                self.assertEqual(state["snapshot"]["admission_closes_at"], quota._iso(expiry-timedelta(seconds=10)))
            for instant in (expiry-timedelta(seconds=10), expiry, expiry+timedelta(seconds=1)):
                with mock.patch.object(quota, "_database_now", return_value=instant):
                    with self.assertRaisesRegex(quota.AmapQuotaError, "RIGHTS_EXPIRED"):
                        quota.admit("detail", storage=self.storage)
                    self.assertEqual(quota.read_status(storage=self.storage)["status"], "recurring_hold")
        self.assertEqual(self.rows()[-1]["admitted_count"], 1)

    def test_every_admission_checks_real_expiry_and_ten_second_margin(self):
        prepared = self.prepare()
        self.apply(prepared)
        row = self.rows()[-1]
        metadata = quota._recurring_budget(row)
        metadata["u"] = "2026-10-13T00:00:00.000000+00:00"
        row["source"] = quota.RECURRING_SOURCE + json.dumps(metadata, separators=(",", ":"))
        for clock in ("2026-10-12T23:59:51+00:00", "2026-10-13T00:00:00+00:00"):
            with self.assertRaisesRegex(quota.AmapQuotaError, "RIGHTS_EXPIRED"):
                quota._recurring_check(row, quota._clock(clock), environment=prepared.runtime)

    def test_month_closing_margin_does_not_append(self):
        prepared = self.prepare()
        with mock.patch.object(quota, "_database_now", return_value=quota._clock("2026-11-01T00:00:00+08:00")-timedelta(seconds=9)):
            self.assert_hold("PERIOD_CLOSING", lambda: self.apply(prepared))

    def test_original_console_row_retains_shape_and_behavior(self):
        with mock.patch.object(quota, "_database_now", return_value=quota._clock("2026-09-16T00:00:00Z")), \
             mock.patch.dict(os.environ, {}, clear=True):
            state = quota.read_status(storage=self.storage)
            self.assertEqual(state["status"], "ready")
            self.assertEqual(state["snapshot"]["official_used"], 1)
            self.assertEqual(state["snapshot"]["source"], refresh.SOURCE)
            self.assertNotIn("source_kind", state["snapshot"])
            self.assertNotIn("budget_derived_at", state["snapshot"])
            self.assertIsInstance(quota.admit("text", storage=self.storage), quota.Admission)

    def test_missing_exact_dates_cannot_be_inferred_from_key_validity(self):
        self.prepare()
        self.entitlement_document["valid_until"] = None
        with self.assertRaisesRegex(refresh.RefreshError, "RIGHTS_DATES_REQUIRED"):
            self.prepare()

    def test_wrong_key_and_changed_document_are_not_accepted(self):
        with self.assertRaisesRegex(refresh.RefreshError, "KEY_MISMATCH"):
            self.prepare(approved_key="offline unrelated key")
        self.prepare()
        self.entitlement_document["official_entitlement_sha256"] = "f" * 64
        with self.assertRaisesRegex(refresh.RefreshError, "ARTIFACT_MISMATCH"):
            self.prepare()

    def test_unknown_external_shared_usage_is_not_discounted_into_safety(self):
        self.prepare()
        self.entitlement_document["attestations"]["all_shared_search_metered"] = False
        with self.assertRaisesRegex(refresh.RefreshError, "EVIDENCE_INVALID"):
            self.prepare()

    def test_invalid_arguments_never_echo_accidental_secrets(self):
        output = io.StringIO()
        with mock.patch("sys.stdout", output), self.assertRaises(SystemExit):
            recurring.main(["--dsn", "postgresql://accidental-secret"])
        self.assertNotIn("accidental-secret", output.getvalue())
        self.assertIn("ARGUMENTS_INVALID", output.getvalue())

    def test_plan_binding_change_cannot_write(self):
        prepared = self.prepare()
        self.assert_hold("PLAN_CHANGED", lambda: recurring.produce_month_budget(self.storage,
            prepared, apply=True, expected_binding="f" * 64))


@unittest.skipUnless(os.environ.get("NOTEAI_AMAP_REAL_PG_TEST") == "1",
                     "explicit disposable PG16 runner required")
class RecurringPostgresTests(unittest.TestCase):
    """Actual 0031/ACL/locks, synthetic finite rights and controlled month clock."""
    rows = offline.AmapRefreshTests.rows
    prepare = RecurringBudgetTests.prepare
    apply = RecurringBudgetTests.apply
    old_attempt = RecurringBudgetTests.old_attempt

    def setUp(self):
        from tests import test_amap_quota_real_postgres as pg
        self.pg = pg
        RecurringBudgetTests.setUp(self)
        pg.install_schema(pg.REFRESH_DB)
        self.storage = pg.RealStorage("postgres", pg.REFRESH_DB)
        self.app = pg.RealStorage("noteai_app", pg.REFRESH_DB)
        with self.storage.transaction(write=True) as tx:
            tx.execute("INSERT INTO amap_quota_buckets(" + ",".join(self.old) + ") VALUES(" +
                ",".join("?" for _ in self.old) + ")", tuple(self.old.values()))

    def maintenance(self, role="postgres"):
        from urllib.parse import urlencode
        return refresh.MaintenancePostgresStorage("postgresql:///" + self.pg.REFRESH_DB + "?" + urlencode(
            dict(host=self.pg.SOCKET, port=self.pg.PORT, user=role,
                 application_name="noteai_amap_recurring_acceptance")))

    def test_real_append_noop_and_legacy_status_contract(self):
        with mock.patch.object(quota, "_database_now", return_value=quota._clock("2026-09-16T00:00:00Z")):
            legacy = quota.read_status(storage=self.app)
            self.assertEqual(legacy["snapshot"]["official_used"], 1)
            self.assertNotIn("source_kind", legacy["snapshot"])
        prepared = self.prepare()
        self.assertEqual(recurring.produce_month_budget(self.maintenance(), prepared, apply=True)["status"], "applied")
        with mock.patch.dict(os.environ, prepared.runtime, clear=True):
            attempt = quota.admit("text", storage=self.app)
            quota.finish(attempt, status="unknown", storage=self.app)
            state = quota.read_status(storage=self.app)
        self.assertIsNone(state["snapshot"]["official_used"])
        self.assertEqual(state["snapshot"]["remaining"], 49999)
        self.assertEqual(recurring.produce_month_budget(self.maintenance(), prepared, apply=True)["admitted_count"], 1)
        self.assertEqual(len(self.rows()), 2)
        self.assertLessEqual(len(self.rows()[-1]["source"]), 500)
        verified = self.rules_status()
        for change in ({"state": "HOLD"}, {"observed_at": "2026-10-12T16:59:59Z"},
                       {"observed_at": "2026-10-13T00:00:01Z"}):
            self.rules_status = lambda change=change: dict(verified, **change)
            with mock.patch.dict(os.environ, prepared.runtime, clear=True):
                with self.assertRaisesRegex(quota.AmapQuotaError, "RULES_UNCONFIRMED"):
                    quota.admit("detail", storage=self.app)
                self.assertEqual(quota.read_status(storage=self.app)["status"], "recurring_hold")
            self.assertEqual(self.rows()[-1]["admitted_count"], 1)
        self.rules_status = lambda: verified
        changed = dict(prepared.runtime, AMAP_WEB_KEY="offline replacement key",
            NOTEAI_AMAP_RECURRING_APPROVED_KEY="offline replacement key")
        with mock.patch.dict(os.environ, changed, clear=True):
            with self.assertRaisesRegex(quota.AmapQuotaError, "BINDING_CHANGED"):
                quota.admit("detail", storage=self.app)
            serialized = json.dumps(quota.read_status(storage=self.app))
        self.assertNotIn(hashlib.sha256(KEY.encode()).hexdigest(), serialized)
        self.assertNotIn('"k"', serialized)
        prepared = self.prepare()  # restore dynamic synthetic policy metadata
        with mock.patch.object(quota, "_database_now", return_value=quota._clock("2027-09-01T00:01:00+08:00")):
            self.assertEqual(recurring.produce_month_budget(self.maintenance(), prepared, apply=True)["period"], "2027-09")
        expiry = quota._clock(prepared.metadata["valid_until"])
        with mock.patch.dict(os.environ, prepared.runtime, clear=True):
            with mock.patch.object(quota, "_database_now", return_value=expiry-timedelta(seconds=11)):
                self.assertIsInstance(quota.admit("text", storage=self.app), quota.Admission)
            with mock.patch.object(quota, "_database_now", return_value=expiry-timedelta(seconds=10)):
                with self.assertRaisesRegex(quota.AmapQuotaError, "RIGHTS_EXPIRED"):
                    quota.admit("detail", storage=self.app)
        self.assertEqual(self.rows()[-1]["admitted_count"], 1)

    def test_real_concurrent_producers_and_app_admissions(self):
        prepared = self.prepare()
        with ThreadPoolExecutor(max_workers=4) as executor:
            outcomes = list(executor.map(lambda _: recurring.produce_month_budget(self.maintenance(), prepared, apply=True), range(4)))
        self.assertEqual([outcome["status"] for outcome in outcomes].count("applied"), 1)
        with mock.patch.dict(os.environ, prepared.runtime, clear=True), ThreadPoolExecutor(max_workers=8) as executor:
            attempts = list(executor.map(lambda _: quota.admit("text", storage=self.pg.RealStorage(
                "noteai_app", self.pg.REFRESH_DB)), range(8)))
        self.assertTrue(all(isinstance(attempt, quota.Admission) for attempt in attempts))
        self.assertEqual(self.rows()[-1]["admitted_count"], 8)

    def test_real_producer_waits_on_existing_account_advisory_lock(self):
        import time
        prepared = self.prepare()
        with self.pg.connect(self.pg.REFRESH_DB, autocommit=True) as holder, ThreadPoolExecutor(max_workers=1) as executor:
            holder.execute("BEGIN")
            holder.execute("SELECT pg_advisory_xact_lock(1095582032,1112752979)")
            future = executor.submit(recurring.produce_month_budget, self.maintenance(), prepared, apply=True)
            try:
                waiting = False
                deadline = time.monotonic()+2
                while time.monotonic() < deadline:
                    holder.execute("SELECT pg_stat_clear_snapshot()")
                    row = holder.execute("SELECT count(*) AS n FROM pg_stat_activity WHERE datname=%s "
                        "AND application_name='noteai_amap_recurring_acceptance' AND wait_event='advisory'",
                        (self.pg.REFRESH_DB,)).fetchone()
                    if row["n"]:
                        waiting = True
                        break
                    time.sleep(0.03)
                self.assertTrue(waiting)
                self.assertFalse(future.done())
            finally:
                holder.execute("COMMIT")
            self.assertEqual(future.result(timeout=5)["status"], "applied")

    def test_real_old_unknown_and_durable_denial_are_preserved(self):
        identity = self.old_attempt(status="unknown")
        with self.storage.transaction(write=True) as tx:
            tx.execute("UPDATE amap_quota_buckets SET account_block_code='10044' WHERE period='2026-09'")
        prepared = self.prepare()
        result = recurring.produce_month_budget(self.maintenance(), prepared, apply=True)
        self.assertEqual(result["unmetered_usage_upper_bound"], 1)
        self.assertEqual(self.storage.fetchone("SELECT status FROM amap_quota_attempts WHERE id=?", (identity,))["status"], "unknown")
        with mock.patch.dict(os.environ, prepared.runtime, clear=True):
            with self.assertRaisesRegex(quota.AmapQuotaError, "ACCESS_RESTRICTED"):
                quota.admit("detail", storage=self.app)
        self.assertEqual(self.rows()[0]["admitted_count"], 1)

    def test_real_readonly_role_boundary_and_insert_rollback(self):
        with self.maintenance().transaction() as tx:
            self.assertEqual(tx.fetchone("SELECT current_setting('transaction_read_only') AS value")["value"], "on")
        prepared = self.prepare()
        with self.assertRaisesRegex(refresh.RefreshError, "MAINTENANCE_ROLE_REQUIRED"):
            recurring.produce_month_budget(self.maintenance("noteai_app"), prepared, apply=True)
        with self.storage.transaction(write=True) as tx:
            tx.execute("CREATE FUNCTION public.amap_recurring_reject_insert() RETURNS trigger LANGUAGE plpgsql AS "
                "$$ BEGIN RAISE EXCEPTION 'synthetic rollback fixture'; END $$")
            tx.execute("CREATE TRIGGER amap_recurring_reject_insert BEFORE INSERT ON public.amap_quota_buckets "
                "FOR EACH ROW EXECUTE FUNCTION public.amap_recurring_reject_insert()")
        before = self.rows()
        with self.assertRaisesRegex(refresh.RefreshError, "STATE_UNAVAILABLE"):
            recurring.produce_month_budget(self.maintenance(), prepared, apply=True)
        self.assertEqual(self.rows(), before)

    def test_real_cli_separates_plan_apply_and_readonly_noop(self):
        prepared = self.prepare()
        args = ["--entitlement", str(self.entitlement_path), "--official-entitlement", str(self.entitlement_artifact),
            "--current-official-rules", str(self.rules_artifact), "--attempt-state", str(self.path / "october.attempt")]
        receipts = []
        environment = dict(prepared.runtime, NOTEAI_AMAP_OBSERVED_KEY=KEY,
            NOTEAI_AMAP_RECURRING_APPROVED_KEY=KEY,
            NOTEAI_AMAP_REFRESH_DSN=self.maintenance().dsn)
        with mock.patch.dict(os.environ, environment, clear=True):
            for mode in ("--plan", "--apply", "--apply"):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                    self.assertEqual(recurring.main([*args, mode]), 0)
                receipts.append(json.loads(output.getvalue()))
        self.assertEqual([receipt["status"] for receipt in receipts], ["plan_ready", "applied", "same_month_noop"])
        self.assertEqual(len(self.rows()), 2)
