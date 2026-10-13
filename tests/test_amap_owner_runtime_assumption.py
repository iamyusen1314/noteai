"""Synthetic v2 owner receipts, SQLite and clocks; NOT real supplier acceptance.

The mock receipt is explicitly nonofficial. No real Key, authenticated console,
production/PG connection, model call or scheduler installation is performed.
"""
from datetime import timedelta
import hashlib
import io
import json
import os
from unittest import mock
import unittest

from tests import test_amap_recurring_budget as legacy
from tests import test_amap_recurring_worker as worker_fixture
from tests import test_amap_quota_refresh as offline
from tests import test_amap_admin_recurring_render as admin_fixture

quota = legacy.quota
producer = legacy.recurring
refresh = legacy.refresh
worker = worker_fixture.worker
KEY = offline.KEY
NOW = quota._clock("2026-10-13T06:00:00Z")
NOVEMBER = quota._clock("2026-11-01T00:01:00+08:00")


class OwnerRuntimeAssumptionTests(unittest.TestCase):
    rows = legacy.RecurringBudgetTests.rows
    apply = legacy.RecurringBudgetTests.apply
    old_attempt = legacy.RecurringBudgetTests.old_attempt
    assert_hold = legacy.RecurringBudgetTests.assert_hold

    def setUp(self):
        legacy.RecurringBudgetTests.setUp(self)
        clock = mock.patch.object(quota, "_database_now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)

    def prepare(self, **keys):
        self.entitlement_artifact = self.path / "OFFLINE_OWNER_NOT_OFFICIAL.json"
        self.entitlement_artifact.write_text('{"scope":"OFFLINE owner runtime assumption; NOT OFFICIAL"}')
        self.rules_artifact = self.path / "OFFLINE_RULES_NOT_OFFICIAL.txt"
        self.rules_artifact.write_text("OFFLINE NOT OFFICIAL: mock shared monthly rules.")
        if not hasattr(self, "entitlement_document"):
            self.entitlement_document = dict(version=2,
                account_scope=quota.ACCOUNT_SCOPE, service_group=quota.SERVICE_GROUP,
                time_zone="Asia/Shanghai", monthly_quota=50000,
                valid_from="2026-10-13T00:00:00+08:00", valid_until="2027-10-13T00:00:00+08:00",
                recorded_at="2026-10-13T00:01:00+08:00", validity_basis="owner_runtime_assumption",
                validity_evidence_sha256=hashlib.sha256(self.entitlement_artifact.read_bytes()).hexdigest(),
                official_rules_sha256=hashlib.sha256(self.rules_artifact.read_bytes()).hexdigest(),
                attestations=dict(console_account_matches=True, key_alias="noteai-rot-0902", key_scope="web_service",
                    enterprise_certified=True, license_purchased=False, owner_risk_accepted=True,
                    exclusive_noteai_use=True, all_shared_search_metered=True,
                    metering_continuous_since="2026-10-13T00:00:00+08:00"))
        self.entitlement_path = self.path / "OFFLINE_OWNER_RUNTIME_ASSUMPTION.json"
        self.entitlement_path.write_text(json.dumps(self.entitlement_document))
        prepared = producer.prepare_entitlement(self.entitlement_path, self.entitlement_artifact, self.rules_artifact,
            configured_key=keys.get("configured_key", KEY), approved_key=keys.get("approved_key", KEY),
            observed_key=keys.get("observed_key", KEY))
        prepared.runtime.update(NOTEAI_AMAP_RECURRING_ENTITLEMENT_SHA256=prepared.metadata["entitlement_sha256"],
            NOTEAI_AMAP_RECURRING_RULES_SHA256=prepared.metadata["official_rules_sha256"],
            NOTEAI_AMAP_RECURRING_RULES_STATUS_FILE="/run/offline-owner-policy/rules-status.json")
        self.rules_status = lambda: worker._policy(prepared, quota._database_now(None),
            worker_fixture.FakeObserver(b"OFFLINE"), verified=True)
        return prepared

    def seed_current_console(self):
        self.document.update(observed_at="2026-10-13T05:00:00Z")
        self.document["attestations"].update(verified_at="2026-10-13T05:10:00Z",
            runtime_key_observed_at="2026-10-13T05:05:00Z")
        refresh.refresh_snapshot(self.storage, offline.AmapRefreshTests.prepare(self), apply=True)
        with self.storage.transaction(write=True) as tx:
            tx.execute("UPDATE amap_quota_buckets SET admitted_count=7 WHERE period='2026-10'")

    def test_owner_validity_is_typed_and_not_backdated_or_an_official_artifact(self):
        value = self.prepare().metadata
        self.assertEqual(value["validity_basis"], "owner_runtime_assumption")
        self.assertEqual(quota._clock(value["valid_from"]), quota._clock("2026-10-13T00:00:00+08:00"))
        self.assertEqual(quota._clock(value["valid_until"]), quota._clock("2027-10-13T00:00:00+08:00"))
        self.assertNotIn("official_entitlement_sha256", value)
        self.assertNotIn("verified_at", value)

    def test_original_v1_digest_and_source_keys_remain_compatible(self):
        prepared = legacy.RecurringBudgetTests.prepare(self)
        raw = dict(self.entitlement_document)
        raw["attestations"] = dict(raw["attestations"])
        for name in ("valid_from", "valid_until", "verified_at"):
            raw[name] = quota._iso(quota._clock(raw[name]))
        raw["attestations"]["metering_continuous_since"] = quota._iso(
            quota._clock(raw["attestations"]["metering_continuous_since"]))
        expected = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(prepared.metadata["entitlement_sha256"], expected)
        self.apply(prepared)
        self.assertNotIn("p", quota._recurring_budget(self.rows()[-1]))

    def test_existing_october_console_noop_preserves_every_row_and_count(self):
        self.seed_current_console()
        prepared = self.prepare()
        before = self.rows()
        for apply in (False, True, True):
            result = producer.produce_month_budget(self.storage, prepared, apply=apply)
            self.assertEqual(result["status"], "same_month_noop")
            self.assertEqual(result["evidence_scope"], "existing_console_observation")
            self.assertEqual(result["admitted_count"], 7)
        self.assertEqual(self.rows(), before)
        self.assertEqual(self.rows()[-1]["source"], refresh.SOURCE)

    def test_missing_first_partial_month_cannot_be_invented(self):
        self.assert_hold("MONTH_NOT_COVERED", lambda: self.apply(self.prepare()))

    def test_november_december_january_are_separate_budgets_with_null_official_usage(self):
        prepared = self.prepare()
        self.old_attempt(status="unknown")
        for instant, period in ((NOVEMBER, "2026-11"), ("2026-12-01T00:01:00+08:00", "2026-12"),
                               ("2027-01-01T00:01:00+08:00", "2027-01")):
            with mock.patch.object(quota, "_database_now", return_value=quota._clock(instant)), \
                 mock.patch.dict(os.environ, prepared.runtime, clear=True):
                result = self.apply(prepared)
                self.assertEqual(result["period"], period)
                self.assertFalse(result["official_validity_verified"])
                self.assertEqual(result["validity_basis"], "owner_runtime_assumption")
                self.assertEqual(result["unmetered_usage_upper_bound"], 1)
                self.assertIsNone(result["official_used"])
                attempt = quota.admit("text", storage=self.storage)
                quota.finish(attempt, status="succeeded", http_status=200, business_code="10000", storage=self.storage)
                snapshot = quota.read_status(storage=self.storage)["snapshot"]
                self.assertFalse(snapshot["official_usage_observed"])
                self.assertFalse(snapshot["official_validity_verified"])
                self.assertIsNone(snapshot["official_entitlement_artifact_sha256"])
                self.assertIsNone(snapshot["official_used"])
                self.assertEqual(snapshot["admitted_in_local_budget"], 1)
                self.assertLessEqual(len(self.rows()[-1]["source"]), 500)
        self.assertEqual([row["period"] for row in self.rows()], ["2026-09", "2026-11", "2026-12", "2027-01"])
        self.assertEqual(self.rows()[0]["admitted_count"], 1)

    def test_unknown_shared_usage_and_identity_mismatch_are_not_waived(self):
        self.prepare()
        for unknown in (None, False):
            self.entitlement_document["attestations"]["all_shared_search_metered"] = unknown
            with self.assertRaisesRegex(refresh.RefreshError, "EVIDENCE_INVALID"):
                self.prepare()
        self.entitlement_document["attestations"]["all_shared_search_metered"] = True
        with self.assertRaisesRegex(refresh.RefreshError, "KEY_MISMATCH"):
            self.prepare(approved_key="different offline mock")

    def test_incomplete_new_month_metering_holds_without_append(self):
        self.prepare()
        self.entitlement_document["attestations"]["metering_continuous_since"] = "2026-11-02T00:00:00+08:00"
        prepared = self.prepare()
        with mock.patch.object(quota, "_database_now", return_value=NOVEMBER):
            self.assert_hold("SHARED_METERING_GAP", lambda: self.apply(prepared))

    def test_changed_rules_or_owner_receipt_do_not_self_approve(self):
        self.prepare()
        for field in ("official_rules_sha256", "validity_evidence_sha256"):
            original = self.entitlement_document[field]
            self.entitlement_document[field] = "f" * 64
            with self.assertRaisesRegex(refresh.RefreshError, "ARTIFACT_MISMATCH"):
                self.prepare()
            self.entitlement_document[field] = original
        self.entitlement_document["validity_basis"] = "official_verified"
        with self.assertRaisesRegex(refresh.RefreshError, "EVIDENCE_INVALID"):
            self.prepare()

    def test_last_partial_month_uses_exact_finite_expiry_and_margin(self):
        prepared = self.prepare()
        with mock.patch.object(quota, "_database_now", return_value=quota._clock("2027-10-01T00:01:00+08:00")):
            self.assertEqual(self.apply(prepared)["period"], "2027-10")
        expiry = quota._clock(prepared.metadata["valid_until"])
        with mock.patch.dict(os.environ, prepared.runtime, clear=True):
            with mock.patch.object(quota, "_database_now", return_value=expiry-timedelta(seconds=11)):
                quota.admit("text", storage=self.storage)
                self.assertEqual(quota.read_status(storage=self.storage)["snapshot"]["admission_closes_at"],
                    quota._iso(expiry-timedelta(seconds=10)))
            before = self.rows()
            for instant in (expiry-timedelta(seconds=10), expiry, expiry+timedelta(seconds=1)):
                with mock.patch.object(quota, "_database_now", return_value=instant):
                    with self.assertRaisesRegex(quota.AmapQuotaError, "RIGHTS_EXPIRED"):
                        quota.admit("detail", storage=self.storage)
            self.assertEqual(self.rows(), before)
        with mock.patch.object(quota, "_database_now", return_value=expiry):
            self.assert_hold("MONTH_NOT_COVERED", lambda: self.apply(prepared))

    def test_stale_future_or_false_official_policy_denies_without_debit(self):
        prepared = self.prepare()
        with mock.patch.object(quota, "_database_now", return_value=NOVEMBER):
            self.apply(prepared)
            verified = self.rules_status()
            for change in ({"state": "HOLD"}, {"observed_at": quota._iso(NOVEMBER-timedelta(hours=8))},
                           {"observed_at": quota._iso(NOVEMBER+timedelta(seconds=1))},
                           {"validity_basis": "official_verified"}, {"official_validity_verified": True},
                           {"official_entitlement_artifact_sha256": prepared.metadata["validity_evidence_sha256"]}):
                self.rules_status = lambda change=change: dict(verified, **change)
                before = self.rows()
                with mock.patch.dict(os.environ, prepared.runtime, clear=True):
                    with self.assertRaisesRegex(quota.AmapQuotaError, "RULES_UNCONFIRMED"):
                        quota.admit("detail", storage=self.storage)
                self.assertEqual(self.rows(), before)

    def test_insufficient_uncertainty_budget_and_local_exhaustion_stop_calls(self):
        prepared = self.prepare()
        with mock.patch.object(quota, "_database_now", return_value=NOVEMBER):
            with mock.patch.object(producer, "_risk_reserve", return_value=50000):
                self.assert_hold("UNCERTAIN_USAGE_EXHAUSTS_BUDGET", lambda: self.apply(prepared))
            self.apply(prepared)
            with self.storage.transaction(write=True) as tx:
                tx.execute("UPDATE amap_quota_buckets SET admitted_count=50000 WHERE period='2026-11'")
            before = self.rows()
            with mock.patch.dict(os.environ, prepared.runtime, clear=True):
                self.assertEqual(quota.read_status(storage=self.storage)["status"], "quota_exhausted")
                with self.assertRaisesRegex(quota.AmapQuotaError, "MONTHLY_QUOTA_EXHAUSTED"):
                    quota.admit("text", storage=self.storage)
            self.assertEqual(self.rows(), before)
        with mock.patch.object(quota, "_database_now", return_value=quota._clock("2026-12-01T00:01:00+08:00")), \
             mock.patch.dict(os.environ, prepared.runtime, clear=True):
            self.apply(prepared)
            quota.admit("text", storage=self.storage)
        self.assertEqual(self.rows()[-2]["admitted_count"], 50000)

    def test_actual_denial_survives_new_month_and_service_assumption(self):
        prepared = self.prepare()
        with mock.patch.object(quota, "_database_now", return_value=NOVEMBER), \
             mock.patch.dict(os.environ, prepared.runtime, clear=True):
            self.apply(prepared)
            attempt = quota.admit("text", storage=self.storage)
            quota.finish(attempt, status="failed", http_status=403, storage=self.storage)
        with mock.patch.object(quota, "_database_now", return_value=quota._clock("2026-12-01T00:01:00+08:00")), \
             mock.patch.dict(os.environ, prepared.runtime, clear=True):
            self.apply(prepared)
            with self.assertRaisesRegex(quota.AmapQuotaError, "ACCESS_RESTRICTED"):
                quota.admit("text", storage=self.storage)
        self.assertEqual(self.rows()[-2]["text_block_code"], "HTTP_403")

    def test_cli_cannot_label_v2_receipt_as_official_entitlement(self):
        prepared = self.prepare()
        args = ["--entitlement", str(self.entitlement_path), "--official-entitlement", str(self.entitlement_artifact),
                "--current-official-rules", str(self.rules_artifact)]
        environment = dict(prepared.runtime, NOTEAI_AMAP_OBSERVED_KEY=KEY, NOTEAI_AMAP_RECURRING_APPROVED_KEY=KEY)
        with mock.patch.dict(os.environ, environment, clear=True), mock.patch("sys.stdout", new_callable=io.StringIO) as output, \
             mock.patch.object(producer, "MaintenancePostgresStorage") as storage:
            self.assertEqual(producer.main(args), 1)
        self.assertEqual(json.loads(output.getvalue())["code"], "AMAP_RECURRING_VALIDITY_CHANNEL_MISMATCH")
        storage.assert_not_called()


class OwnerRuntimeWorkerTests(unittest.TestCase):
    rows = OwnerRuntimeAssumptionTests.rows
    prepare = OwnerRuntimeAssumptionTests.prepare
    seed_current_console = OwnerRuntimeAssumptionTests.seed_current_console
    tick = worker_fixture.WorkerTests.tick
    app_environment = worker_fixture.WorkerTests.app_environment

    def setUp(self):
        OwnerRuntimeAssumptionTests.setUp(self)
        self.seed_current_console()
        self.prepared = self.prepare()
        self.rules_body = self.rules_artifact.read_bytes()
        self.state = worker_fixture.MemoryState(self.path)
        self.state.private = self.rules_status()
        self.state.published = self.rules_status()
        self.loader = worker_fixture.Loader(self.prepared)
        self.policy_patch = mock.patch.object(quota, "_read_rules_status", side_effect=lambda path:
            self.state.private if path == self.state.private_path else self.state.published)
        self.policy_patch.start()
        self.addCleanup(self.policy_patch.stop)

    def test_first_partial_console_noop_then_new_month_once_and_typed_policy(self):
        before = self.rows()
        self.assertEqual(self.tick()["state"], "CURRENT_MONTH_NOOP")
        self.assertEqual(self.rows(), before)
        self.assertFalse(self.state.started)
        with mock.patch.object(quota, "_database_now", return_value=NOVEMBER):
            self.assertEqual(self.tick()["state"], "APPLY_ACKNOWLEDGED")
            self.assertEqual(self.tick()["state"], "CURRENT_MONTH_NOOP")
        self.assertEqual(list(self.state.started), ["2026-11"])
        self.assertFalse(self.state.published["official_validity_verified"])
        self.assertIsNone(self.state.published["official_entitlement_artifact_sha256"])
        self.assertEqual(self.state.published["validity_basis"], "owner_runtime_assumption")

    def test_public_rule_failure_holds_admission_then_next_check_recovers(self):
        with mock.patch.object(quota, "_database_now", return_value=NOVEMBER):
            self.tick()
            before = self.rows()
            self.assertEqual(self.tick(fail=True)["state"], "HOLD")
            with mock.patch.dict(os.environ, self.app_environment(), clear=True):
                with self.assertRaisesRegex(quota.AmapQuotaError, "RULES_UNCONFIRMED"):
                    quota.admit("text", storage=self.storage)
            self.assertEqual(self.rows(), before)
            self.assertEqual(self.tick()["state"], "CURRENT_MONTH_NOOP")
            with mock.patch.dict(os.environ, self.app_environment(), clear=True):
                quota.admit("text", storage=self.storage)

    def test_unknown_commit_confirmed_by_readonly_without_duplicate_apply(self):
        self.storage.unknown_commit = True
        with mock.patch.object(quota, "_database_now", return_value=NOVEMBER):
            self.assertEqual(self.tick()["state"], "APPLY_CONFIRMED_READONLY")
            self.storage.unknown_commit = False
            self.assertEqual(self.tick()["state"], "CURRENT_MONTH_NOOP")
        self.assertEqual(self.state.results["2026-11"]["status"], "commit_unknown")
        self.assertTrue(self.state.confirmed["2026-11"]["binding_matches"])
        self.assertEqual(len(self.rows()), 3)

    def test_unknown_absent_row_never_reapplies(self):
        original = producer.produce_month_budget
        def uncertain(storage, prepared, **kwargs):
            if kwargs.get("apply"):
                raise producer.CommitUnknown()
            return original(storage, prepared, **kwargs)
        with mock.patch.object(quota, "_database_now", return_value=NOVEMBER), \
             mock.patch.object(producer, "produce_month_budget", side_effect=uncertain) as mocked:
            self.assertEqual(self.tick()["state"], "HOLD_APPLY_RESULT")
            self.assertEqual(self.tick()["state"], "HOLD_UNKNOWN_READONLY")
        self.assertEqual(sum(call.kwargs.get("apply") is True for call in mocked.call_args_list), 1)
        self.assertEqual(len(self.rows()), 2)

    def test_claimed_insert_failure_is_preserved_and_not_retried(self):
        self.storage.fail_readback = True
        with mock.patch.object(quota, "_database_now", return_value=NOVEMBER):
            self.assertEqual(self.tick()["state"], "HOLD_APPLY_RESULT")
            original = dict(self.state.results["2026-11"])
            self.storage.fail_readback = False
            self.assertEqual(self.tick()["state"], "HOLD_RECORDED_ATTEMPT")
        self.assertEqual(self.state.results["2026-11"], original)
        self.assertEqual(len(self.rows()), 2)


class OwnerRuntimeAdminRenderTests(unittest.TestCase):
    render = admin_fixture.AmapAdminRenderTests.render
    snapshot = admin_fixture.AmapAdminRenderTests.snapshot

    def test_owner_runtime_period_is_explicitly_nonofficial_and_not_yearly_quota(self):
        snapshot = self.snapshot()
        snapshot.update(validity_basis="owner_runtime_assumption", official_validity_verified=False,
            entitlement_valid_from="2026-10-13", entitlement_valid_until="2027-10-13")
        result = self.render(dict(status="ready", snapshot=snapshot))
        for phrase in ("用户指定的服务可用期运行假设（非官方有效期证明）", "不保证全年免费额度或接口可用",
                       "逐月依据当前官方规则和完整共享计量", "实际接口拒绝时停止受影响调用",
                       "官方当月已用量未知"):
            self.assertIn(phrase, result)
        self.assertNotIn("已核实的持续权益", result)
        self.assertNotIn("官方观察 0", result)

    def test_official_v1_view_does_not_become_owner_assumption(self):
        snapshot = self.snapshot()
        snapshot.update(validity_basis="official_verified", official_validity_verified=True)
        result = self.render(dict(status="ready", snapshot=snapshot))
        self.assertIn("已核实的持续权益", result)
        self.assertNotIn("用户指定的服务可用期运行假设", result)


@unittest.skipUnless(os.environ.get("NOTEAI_AMAP_REAL_PG_TEST") == "1",
                     "explicit disposable PG16 runner required")
class OwnerRuntimePostgresTests(unittest.TestCase):
    """Actual unchanged0031/ACL, synthetic owner receipt and business clock."""
    rows = OwnerRuntimeAssumptionTests.rows
    prepare = OwnerRuntimeAssumptionTests.prepare
    seed_current_console = OwnerRuntimeAssumptionTests.seed_current_console

    def setUp(self):
        from tests import test_amap_quota_real_postgres as pg
        OwnerRuntimeAssumptionTests.setUp(self)
        self.pg = pg
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
                 application_name="noteai_amap_owner_assumption_acceptance")))

    def test_real_v2_append_partial_noop_acl_public_provenance_and_expiry(self):
        self.seed_current_console()
        prepared = self.prepare()
        before = self.rows()
        self.assertEqual(producer.produce_month_budget(self.maintenance(), prepared, apply=True)["status"],
                         "same_month_noop")
        self.assertEqual(self.rows(), before)
        with mock.patch.object(quota, "_database_now", return_value=NOVEMBER):
            with self.assertRaisesRegex(refresh.RefreshError, "MAINTENANCE_ROLE_REQUIRED"):
                producer.produce_month_budget(self.maintenance("noteai_app"), prepared, apply=True)
            self.assertEqual(self.rows(), before)
            plan = producer.produce_month_budget(self.maintenance(), prepared)
            self.assertEqual(producer.produce_month_budget(self.maintenance(), prepared, apply=True,
                expected_binding=plan["budget_binding_sha256"])["status"], "applied")
            self.assertLessEqual(len(self.rows()[-1]["source"]), 500)
            with mock.patch.dict(os.environ, prepared.runtime, clear=True):
                attempt = quota.admit("text", storage=self.app)
                quota.finish(attempt, status="unknown", storage=self.app)
                state = quota.read_status(storage=self.app)
            self.assertEqual(state["snapshot"]["validity_basis"], "owner_runtime_assumption")
            self.assertFalse(state["snapshot"]["official_validity_verified"])
            self.assertIsNone(state["snapshot"]["official_entitlement_artifact_sha256"])
            self.assertIsNone(state["snapshot"]["official_used"])
            self.assertNotIn(hashlib.sha256(KEY.encode()).hexdigest(), json.dumps(state))
            self.assertEqual(producer.produce_month_budget(self.maintenance(), prepared, apply=True)["admitted_count"], 1)
            before = self.rows()
            verified = self.rules_status()
            self.rules_status = lambda: dict(verified, official_validity_verified=True)
            with mock.patch.dict(os.environ, prepared.runtime, clear=True):
                with self.assertRaisesRegex(quota.AmapQuotaError, "RULES_UNCONFIRMED"):
                    quota.admit("detail", storage=self.app)
            self.assertEqual(self.rows(), before)
            self.prepare()  # Restore only synthetic policy; no database write.
        with mock.patch.object(quota, "_database_now", return_value=quota._clock("2027-10-01T00:01:00+08:00")):
            result = producer.produce_month_budget(self.maintenance(), prepared, apply=True)
            self.assertEqual(result["unmetered_usage_upper_bound"], 1)
        expiry = quota._clock(prepared.metadata["valid_until"])
        with mock.patch.dict(os.environ, prepared.runtime, clear=True):
            with mock.patch.object(quota, "_database_now", return_value=expiry-timedelta(seconds=11)):
                quota.admit("text", storage=self.app)
            before = self.rows()
            with mock.patch.object(quota, "_database_now", return_value=expiry-timedelta(seconds=10)):
                with self.assertRaisesRegex(quota.AmapQuotaError, "RIGHTS_EXPIRED"):
                    quota.admit("detail", storage=self.app)
            self.assertEqual(self.rows(), before)
        self.assertEqual(self.rows()[1], before[1])
