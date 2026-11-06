"""Persistent model rate boundaries; local SQLite, no supplier or cloud calls."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import importlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import db
import model_capacity as capacity


LITE = "doubao-seed-2-0-lite-260428"
PRO = "doubao-seed-2-1-pro-260915"
IMAGE = "doubao-seedream-5-0-pro-260628"
KIMI = "kimi-k2.6"
HAIKU = "claude-haiku-4-5-20251001"
HAIKU_5_5 = "claude-haiku-5-5"
SONNET = "claude-sonnet-4-6"


class ModelCapacityTests(unittest.TestCase):
    integrity_error = sqlite3.IntegrityError

    def setUp(self):
        self.environment = mock.patch.dict(os.environ, {
            "NOTEAI_MODEL_CAPACITY_ENABLED": "1", "NOTEAI_MODEL_CAPACITY_SCOPE": "ark-primary",
            "NOTEAI_MODEL_CAPACITY_LIMITS_JSON": "",
            "NOTEAI_MODEL_CAPACITY_MOONSHOT_ENABLED": "0"})
        self.environment.start(); self.addCleanup(self.environment.stop)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "capacity.db"
        self.now = datetime(2026, 11, 5, 0, 0, 0, 500000, tzinfo=timezone.utc)
        with self.transaction() as tx:
            capacity.init_sqlite_schema(tx.conn)
            tx.execute("CREATE TABLE public_trial_calls(id TEXT PRIMARY KEY,state TEXT,"
                       "reserve_milli_cny INTEGER,provenance_json TEXT,budget_id TEXT)")
            tx.execute("INSERT INTO public_trial_calls VALUES(?,?,?,?,?)", (
                "old-unknown", "unknown", 10080, '{"original":"unchanged"}', "old-budget"))

    @contextmanager
    def transaction(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield db.Transaction(connection, False)
            connection.commit()
        except BaseException:
            connection.rollback(); raise
        finally:
            connection.close()

    def overrides(self, model=LITE, **values):
        os.environ["NOTEAI_MODEL_CAPACITY_LIMITS_JSON"] = json.dumps({
            model: {**values, "evidence_ref": "isolated-test-policy"}})

    def consume(self, demand=None, *, call_id="call-one", now=None, budget="normal"):
        demand = demand or capacity.Demand(LITE, 10, 5)
        with self.transaction() as tx:
            snapshot = capacity.reserve_in_transaction(tx, demand, call_id=call_id, now=now or self.now)
            tx.execute("INSERT INTO public_trial_calls VALUES(?,?,?,?,?)", (
                call_id, "dispatched", 3146, json.dumps({"quota": snapshot}), budget))
        return snapshot

    def seed(self, model, requests=1, tokens=1, images=0, inputs=None, outputs=0):
        policy = capacity.policy_for(model); second = int(self.now.timestamp())
        with self.transaction() as tx:
            tx.execute("INSERT INTO model_capacity_buckets VALUES(?,?,?,?,?,?,?,?,?)", (
                policy.scope_key, policy.quota_key, second % 61, second, requests, tokens, images, tokens if inputs is None else inputs, outputs))

    def rows(self, table="model_capacity_buckets"):
        with self.transaction() as tx:
            return [dict(row) for row in tx.fetchall("SELECT * FROM " + table + " ORDER BY 1,2")]

    def test_disabled_and_unverified_models_keep_legacy_path_without_creating_buckets(self):
        os.environ["NOTEAI_MODEL_CAPACITY_ENABLED"] = "0"
        self.assertIsNone(capacity.policy_for(LITE))
        self.assertEqual(self.consume(), {})
        os.environ["NOTEAI_MODEL_CAPACITY_ENABLED"] = "1"
        self.assertIsNone(capacity.policy_for("claude-sonnet-4-6"))
        with self.transaction() as tx:
            self.assertEqual(capacity.reserve_in_transaction(tx,
                capacity.Demand("claude-sonnet-4-6", 10, 10), call_id="legacy-claude", now=self.now), {})
        self.assertEqual(self.rows(), [])

    def test_exact_verified_official_ceilings_and_no_unsupported_quota_units(self):
        self.assertEqual((capacity.policy_for(LITE).rpm, capacity.policy_for(LITE).tpm), (30000, 5000000))
        self.assertEqual((capacity.policy_for(PRO).rpm, capacity.policy_for(PRO).tpm), (500, 1000000))
        self.assertEqual((capacity.policy_for(IMAGE).rpm, capacity.policy_for(IMAGE).tpm,
                          capacity.policy_for(IMAGE).ipm), (None, None, 500))
        self.overrides(IMAGE, rpm=100)
        with self.assertRaises(capacity.CapacityConfigurationError): capacity.policy_for(IMAGE)
        os.environ["NOTEAI_MODEL_CAPACITY_LIMITS_JSON"] = json.dumps({LITE: {"rpm": 3}})
        with self.assertRaises(capacity.CapacityConfigurationError): capacity.policy_for(LITE)

    def test_known_model_ids_are_pure_and_malformed_policy_never_silently_falls_back(self):
        self.assertEqual(set(capacity.model_ids()), {LITE, PRO, IMAGE, KIMI, HAIKU, SONNET, HAIKU_5_5})
        os.environ["NOTEAI_MODEL_CAPACITY_ENABLED"] = "0"
        self.assertEqual(set(capacity.model_ids()), {LITE, PRO, IMAGE, KIMI, HAIKU, SONNET, HAIKU_5_5})
        self.assertIsNone(capacity.policy_for(LITE))
        os.environ["NOTEAI_MODEL_CAPACITY_ENABLED"] = "1"
        self.overrides(rpm=2)
        raw = json.loads(os.environ["NOTEAI_MODEL_CAPACITY_LIMITS_JSON"])
        raw[LITE]["evidence_ref"] = " "
        os.environ["NOTEAI_MODEL_CAPACITY_LIMITS_JSON"] = json.dumps(raw)
        with self.assertRaises(capacity.CapacityConfigurationError): capacity.policy_for(LITE)
        os.environ["NOTEAI_MODEL_CAPACITY_LIMITS_JSON"] = "[" * 2000 + "]" * 2000
        with self.assertRaises(capacity.CapacityConfigurationError): capacity.policy_for(LITE)

    def test_rpm_exact_boundary_defers_then_ages_without_resetting_history(self):
        self.seed(LITE, requests=29999, tokens=29999)
        self.consume()
        before = self.rows()
        with self.assertRaises(capacity.QuotaDeferred) as outcome:
            self.consume(call_id="blocked")
        self.assertEqual(outcome.exception.reason, "MODEL_CAPACITY_RPM")
        self.assertEqual(outcome.exception.retry_at, int(self.now.timestamp()) + 61)
        self.assertEqual(self.rows(), before)
        with self.transaction() as tx:
            decision = capacity.read_available(tx, capacity.Demand(LITE, 10, 5),
                                               now=self.now + timedelta(seconds=60))
        self.assertFalse(decision.allowed)
        self.consume(call_id="after-window", now=self.now + timedelta(seconds=61))
        self.assertEqual(len(self.rows()), 1)

    def test_tpm_counts_input_plus_max_output_including_cached_and_unknown_bounds(self):
        self.seed(PRO, tokens=999990)
        snap = self.consume(capacity.Demand(PRO, 5, 5))
        self.assertEqual((snap["input_bound"], snap["output_bound"], snap["tpm"]), (5, 5, 1000000))
        with self.transaction() as tx:
            tx.execute("UPDATE public_trial_calls SET state='unknown' WHERE id='call-one'")
        with self.assertRaises(capacity.QuotaDeferred) as outcome:
            self.consume(capacity.Demand(PRO, 0, 1), call_id="no-unknown-refund")
        self.assertEqual(outcome.exception.reason, "MODEL_CAPACITY_TPM")
        self.assertEqual(self.rows()[0]["token_bound"], 1000000)

    def test_seedream_ipm_is_output_images_and_independent_from_text_model(self):
        self.seed(IMAGE, requests=499, tokens=0, images=499)
        self.consume(capacity.Demand(IMAGE, 0, 0, 1))
        with self.assertRaises(capacity.QuotaDeferred) as outcome:
            self.consume(capacity.Demand(IMAGE, 0, 0, 1), call_id="image-blocked")
        self.assertEqual(outcome.exception.reason, "MODEL_CAPACITY_IPM")
        self.consume(capacity.Demand(LITE, 1000, 100), call_id="independent-lite")
        self.consume(capacity.Demand(PRO, 1000, 100), call_id="independent-pro")
        self.assertEqual(len(self.rows()), 3)

    def test_impossible_or_malformed_demand_rejects_without_any_write(self):
        before = self.rows()
        for args in [(LITE, -1, 0), (LITE, True, 0), (LITE, 0, 1.5)]:
            with self.assertRaises(capacity.CapacityDemandError): capacity.Demand(*args)
        for demand in [capacity.Demand(PRO, 1000000, 1), capacity.Demand(IMAGE, 0, 0, 501),
                       capacity.Demand(IMAGE, 1, 0, 1), capacity.Demand(LITE, 0, 0, 1)]:
            with self.assertRaises(capacity.CapacityDemandError): self.consume(demand)
        self.assertEqual(self.rows(), before)

    def test_cross_budget_concurrent_admission_never_exceeds_same_account_model_limit(self):
        self.overrides(rpm=17)
        def submit(index):
            try:
                self.consume(call_id="concurrent-" + str(index), budget="cover" if index % 2 else "normal")
                return "admitted"
            except capacity.QuotaDeferred:
                return "deferred"
        with ThreadPoolExecutor(max_workers=10) as workers:
            results = list(workers.map(submit, range(100)))
        self.assertEqual((results.count("admitted"), results.count("deferred")), (17, 83))
        self.assertEqual((self.rows()[0]["request_count"], self.rows()[0]["token_bound"]), (17, 255))
        self.assertEqual(len(self.rows("public_trial_calls")), 18)

    def test_process_recreation_does_not_reset_rate_and_original_call_never_replays(self):
        self.overrides(rpm=1)
        self.consume()
        reloaded = importlib.reload(capacity)
        with self.assertRaises(reloaded.QuotaDeferred): self.consume(call_id="after-reload")
        with self.assertRaises(reloaded.CapacityStateError) as outcome:
            self.consume(call_id="call-one", now=self.now + timedelta(seconds=120))
        self.assertEqual(outcome.exception.args, ("MODEL_CAPACITY_CALL_ALREADY_RESERVED",))
        self.assertEqual(self.rows()[0]["request_count"], 1)

    def test_bucket_and_physical_intent_roll_back_together_after_failed_unique_insert(self):
        with self.assertRaises(self.integrity_error):
            with self.transaction() as tx:
                capacity.reserve_in_transaction(tx, capacity.Demand(LITE, 10, 5),
                                                call_id="new-before-failed-save", now=self.now)
                tx.execute("INSERT INTO public_trial_calls VALUES(?,?,?,?,?)", (
                    "old-unknown", "dispatched", 1, "{}", "normal"))
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.rows("public_trial_calls"), [{"id": "old-unknown", "state": "unknown",
            "reserve_milli_cny": 10080, "provenance_json": '{"original":"unchanged"}', "budget_id": "old-budget"}])

    def test_rate_aging_and_cancellation_do_not_modify_original_unknown_or_cost(self):
        original = self.rows("public_trial_calls")[0]
        self.consume()
        with self.transaction() as tx:
            tx.execute("UPDATE public_trial_calls SET state='responded' WHERE id='call-one'")
        self.assertEqual(self.rows()[0]["request_count"], 1)
        for index in range(1, 131):
            self.consume(call_id="ring-" + str(index), now=self.now + timedelta(seconds=index))
        self.assertEqual(len(self.rows()), 61)
        self.assertEqual(next(row for row in self.rows("public_trial_calls") if row["id"] == "old-unknown"), original)

    def test_clock_reversal_fails_closed_and_read_hint_has_no_side_effects(self):
        self.consume()
        before = self.rows()
        with self.assertRaises(capacity.CapacityStateError) as outcome:
            self.consume(call_id="back-clock", now=self.now - timedelta(seconds=1))
        self.assertEqual(outcome.exception.args, ("MODEL_CAPACITY_CLOCK_REVERSED",))
        with self.transaction() as tx:
            self.assertTrue(capacity.read_available(tx, capacity.Demand(LITE, 10, 5), now=self.now).allowed)
        self.assertEqual(self.rows(), before)

    def test_sqlite_schema_initialization_does_not_commit_the_callers_transaction(self):
        path = Path(self.temp.name) / "initialize-rollback.db"
        conn = sqlite3.connect(path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            capacity.init_sqlite_schema(conn)
            self.assertTrue(conn.in_transaction)
            conn.rollback()
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='model_capacity_buckets'").fetchone())
        finally:
            conn.close()

    def test_no_override_resets_an_active_window_and_database_clock_is_used(self):
        self.consume()
        self.overrides(rpm=1)
        with self.assertRaises(capacity.QuotaDeferred): self.consume(call_id="lowered-limit")
        with self.transaction() as tx:
            policy = capacity.policy_for(LITE)
            tx.execute("DELETE FROM model_capacity_buckets WHERE scope_key=? AND quota_key=?", (
                policy.scope_key, policy.quota_key))
            snap = capacity.reserve_in_transaction(tx, capacity.Demand(LITE, 1, 1), call_id="db-clock")
            actual = tx.fetchone("SELECT cast(strftime('%s','now') AS INTEGER) AS second")["second"]
            self.assertLessEqual(abs(snap["admitted_epoch_second"] - actual), 1)
            tx.execute("INSERT INTO public_trial_calls VALUES(?,?,?,?,?)", ("db-clock", "dispatched", 1, "{}", "normal"))

    def test_moonshot_policy_requires_separate_verified_account_activation(self):
        self.assertIsNone(capacity.policy_for(KIMI))
        os.environ["NOTEAI_MODEL_CAPACITY_MOONSHOT_ENABLED"] = "1"
        policy = capacity.policy_for(KIMI)
        self.assertEqual((policy.rpm, policy.tpm, policy.concurrency), (200, 3000000, 50))
        self.assertEqual((policy.scope_key, policy.quota_key), ("moonshot-primary", "moonshot-account"))
        self.assertEqual((policy.itpm, policy.otpm, policy.ipm), (None, None, None))
        os.environ["NOTEAI_MODEL_CAPACITY_ENABLED"] = "0"
        self.assertIsNone(capacity.policy_for(KIMI))

    def test_moonshot_account_rate_is_shared_across_budgets_and_independent_of_ark(self):
        os.environ["NOTEAI_MODEL_CAPACITY_MOONSHOT_ENABLED"] = "1"
        self.overrides(KIMI, rpm=2, tpm=100, concurrency=50)
        first = self.consume(capacity.Demand(KIMI, 10, 5), call_id="kimi-normal", budget="normal")
        second = self.consume(capacity.Demand(KIMI, 10, 5), call_id="kimi-cover", budget="cover")
        self.assertEqual((first["scope"], first["quota_key"]), (second["scope"], second["quota_key"]))
        self.assertEqual(first["concurrency"], 50)
        with self.assertRaises(capacity.QuotaDeferred) as outcome:
            self.consume(capacity.Demand(KIMI, 1, 1), call_id="kimi-third-user")
        self.assertEqual(outcome.exception.reason, "MODEL_CAPACITY_RPM")
        self.consume(capacity.Demand(LITE, 10, 10), call_id="ark-independent")
        self.assertEqual({row["scope_key"] for row in self.rows()}, {"moonshot-primary", "ark-primary"})

    def test_claude_requires_complete_evidenced_rates_and_limits_input_separately(self):
        self.assertIsNone(capacity.policy_for(HAIKU))
        self.assertIsNone(capacity.policy_for(SONNET))
        self.overrides(HAIKU, rpm=10, itpm=100)
        with self.assertRaises(capacity.CapacityConfigurationError): capacity.policy_for(HAIKU)
        self.overrides(HAIKU, rpm=10, itpm=100, otpm=50)
        self.assertIsNone(capacity.policy_for(SONNET))
        policy = capacity.policy_for(HAIKU)
        self.assertEqual((policy.scope_key, policy.itpm, policy.otpm, policy.tpm),
                         ("claude-primary", 100, 50, None))
        snap = self.consume(capacity.Demand(HAIKU, 100, 1), call_id="claude-input-full")
        self.assertEqual((snap["input_bound"], snap["output_bound"]), (100, 1))
        with self.assertRaises(capacity.QuotaDeferred) as outcome:
            self.consume(capacity.Demand(HAIKU, 1, 0), call_id="claude-input-blocked")
        self.assertEqual(outcome.exception.reason, "MODEL_CAPACITY_ITPM")

    def test_claude_output_quota_survives_restart_unknown_and_ages_independently(self):
        self.overrides(SONNET, rpm=10, itpm=1000, otpm=5)
        self.consume(capacity.Demand(SONNET, 10, 5), call_id="claude-output-full")
        with self.transaction() as tx:
            tx.execute("UPDATE public_trial_calls SET state='unknown' WHERE id='claude-output-full'")
        importlib.reload(capacity)
        with self.assertRaises(capacity.QuotaDeferred) as outcome:
            self.consume(capacity.Demand(SONNET, 1, 1), call_id="claude-output-blocked")
        self.assertEqual(outcome.exception.reason, "MODEL_CAPACITY_OTPM")
        self.assertEqual((self.rows()[0]["input_bound"], self.rows()[0]["output_bound"],
                          self.rows()[0]["token_bound"]), (10, 5, 15))
        self.consume(capacity.Demand(SONNET, 1, 1), call_id="claude-next-minute",
                     now=self.now + timedelta(seconds=61))
        old = next(row for row in self.rows("public_trial_calls") if row["id"] == "claude-output-full")
        self.assertEqual((old["state"], old["reserve_milli_cny"]), ("unknown", 3146))

    def test_concurrent_separate_token_dimensions_never_overshoot_same_account(self):
        self.overrides(HAIKU, rpm=100, itpm=33, otpm=22, concurrency=50)
        def submit(index):
            try:
                self.consume(capacity.Demand(HAIKU, 3, 2), call_id="split-" + str(index),
                             budget="normal" if index % 2 else "cover")
                return "admitted"
            except capacity.QuotaDeferred:
                return "deferred"
        with ThreadPoolExecutor(max_workers=10) as workers:
            results = list(workers.map(submit, range(100)))
        self.assertEqual((results.count("admitted"), results.count("deferred")), (11, 89))
        row = self.rows()[0]
        self.assertEqual((row["request_count"], row["input_bound"], row["output_bound"], row["token_bound"]),
                         (11, 33, 22, 55))
        self.assertEqual(capacity.policy_for(HAIKU).concurrency, 50)


if __name__ == "__main__":
    unittest.main()
