"""Synthetic accounting projection tests; no network, real accounts or bills."""
import contextvars
import importlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import usage_reporting as reporting


NOW = datetime(2026, 9, 19, 0, 0, tzinfo=timezone.utc)


def parent(usage_id="parent", **changes):
    return {"id": usage_id, "operation": "generate", "source": "subscription",
            "cost_mode": "actual", "estimated_cost_rmb": 1.28,
            "fact_observations_json": "[]", **changes}


def child(usage_id="parent", **changes):
    return {"id": "model", "usage_record_id": usage_id, "pricing_status": "exact",
            "usage_status": "complete", "known_cost_rmb": 0.5,
            **{key: 0 for key in reporting.TOKEN_INPUT_FIELDS},
            "input_tokens": 20, "output_tokens": 5, **changes}


def physical(usage_id="parent", **changes):
    return {"usage_record_id": usage_id, "model_usage_record_id": "model", "state": "responded",
            "http_status": 200, "provenance_json": '{"step":"semantic_features"}', **changes}


def project(usage=None, models=None, calls=None, requests=()):
    return reporting.project_usage(usage_rows=[parent()] if usage is None else usage,
        model_rows=[child()] if models is None else models,
        physical_rows=[physical()] if calls is None else calls, request_rows=requests,
        window=reporting.reporting_window(period="calendar_month", now=NOW))


class UsageReportingProjectionTests(unittest.TestCase):
    def test_calendar_month_and_rolling_days_are_explicit_utc(self):
        clock = datetime.fromisoformat("2026-10-01T07:59:59+08:00")
        month = reporting.reporting_window(period="calendar_month", now=clock)
        self.assertEqual(month["start"], "2026-09-01T00:00:00+00:00")
        self.assertEqual(month["end"], "2026-10-01T00:00:00+00:00")
        self.assertEqual(month["timezone"], "UTC")
        rolling = reporting.reporting_window(days=30, now=clock)
        self.assertNotEqual(month["start"], rolling["start"])
        for days in (0, -1, True, 367):
            with self.subTest(days=days), self.assertRaises(ValueError):
                reporting.reporting_window(days=days, now=NOW)

    def test_child_calculated_cost_is_counted_once_and_never_supplier_bill(self):
        value = project(requests=[{"usage_id": "parent", "operation": "generate", "status": "completed"}])["accounting"]
        self.assertEqual(value["business"]["completed"], 1)
        self.assertEqual(value["models"]["usage_records"], 1)
        self.assertEqual(value["cost"]["known_calculated_rmb"], 0.5)
        self.assertTrue(value["cost"]["complete"])
        self.assertIsNone(value["cost"]["supplier_bill_paid_rmb"])
        self.assertIsNone(value["cost"]["platform_total_rmb"])
        self.assertIsNone(value["physical"]["actual_http_requests"])
        self.assertEqual(value["physical"]["http_responses_observed"], 1)

    def test_one_unknown_after_priced_child_prevents_false_complete_cost(self):
        calls = [physical(), physical(model_usage_record_id=None, state="unknown", http_status=None)]
        value = project(calls=calls)["accounting"]
        self.assertEqual(value["cost"]["known_calculated_rmb"], 0.5)
        self.assertFalse(value["cost"]["complete"])
        self.assertEqual(value["cost"]["unknown_records"], 1)
        self.assertEqual(value["physical"]["unknown"], 1)
        self.assertEqual(value["physical"]["usage_missing"], 1)

    def test_model_record_without_physical_binding_is_not_http(self):
        value = project(calls=[])["accounting"]
        self.assertEqual(value["models"]["without_physical_binding"], 1)
        self.assertEqual(value["physical"]["recorded"], 0)
        self.assertFalse(value["cost"]["complete"])
        self.assertEqual(value["business"]["status_unknown"], 1)

    def test_unpriced_usage_keeps_explicit_estimate_separate_from_partial_known_cost(self):
        missing = child(pricing_status="unpriced", known_cost_rmb=0)
        value = project(models=[missing])["accounting"]
        self.assertEqual(value["cost"]["estimated_only_rmb"], 1.28)
        self.assertEqual(value["cost"]["known_calculated_rmb"], 0)
        self.assertFalse(value["cost"]["complete"])
        missing["known_cost_rmb"] = 0.12
        value = project(models=[missing])["accounting"]
        self.assertEqual(value["cost"]["estimated_only_rmb"], 0)
        self.assertEqual(value["cost"]["known_calculated_rmb"], 0.12)
        self.assertEqual(value["models"]["token_coverage"], "recorded")
        self.assertEqual(value["models"]["usage_incomplete"], 0)
        self.assertEqual(value["models"]["pricing_gaps"], 1)

    def test_auxiliary_is_not_another_business_or_another_cost(self):
        values = [parent(), parent("video", operation="video_analyze", source="free",
                                  cost_mode="included_in_parent", estimated_cost_rmb=0)]
        value = project(usage=values)
        self.assertEqual(value["accounting"]["business"]["recorded"], 1)
        self.assertEqual(value["accounting"]["auxiliary"]["recorded"], 1)
        self.assertEqual(value["accounting"]["cost"]["known_calculated_rmb"], 0.5)
        self.assertEqual(value["operation_accounting"]["video_analyze"]["kind"], "auxiliary_event")
        self.assertEqual(value["operation_accounting"]["video_analyze"]["included_in_parent_records"], 1)

    def test_missing_estimated_manual_cache_and_refund_are_separate(self):
        values = [parent("estimate", cost_mode="estimated"), parent(source="refunded")]
        item = child(pricing_status="manual", cache_read_input_tokens=10, cache_write_input_tokens=3,
                     audio_input_tokens=7, audio_cache_read_input_tokens=2)
        value = project(usage=values, models=[item])["accounting"]
        self.assertEqual(value["cost"]["estimated_only_rmb"], 1.28)
        self.assertEqual(value["cost"]["known_calculated_rmb"], 0)
        self.assertEqual(value["cost"]["manual_cost_rmb"], 0.5)
        self.assertEqual(value["models"]["tokens_in"], 42)
        self.assertEqual(value["models"]["cache_read_tokens"], 12)
        self.assertEqual(value["models"]["cache_write_tokens"], 3)
        self.assertEqual(value["business"]["refunded"], 1)
        self.assertFalse(value["cost"]["complete"])

    def test_local_score_is_only_observed_and_duplicate_event_not_double_counted(self):
        event = {"schema": "noteai.local_step.v1", "kind": "local_step", "step": "local_score",
                 "outcome": "succeeded", "observation_id": "one", "raw": "PRIVATE_SENTINEL"}
        value = project(usage=[parent(fact_observations_json=json.dumps([event, event]))])
        local = value["accounting"]["local_steps"]
        self.assertEqual(local["by_step"], {"local_score": {"succeeded": 1, "failed": 0}})
        self.assertEqual(local["status"], "partially_recorded")
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(value))
        self.assertEqual(project()["accounting"]["local_steps"]["status"], "not_recorded")
        self.assertEqual(project()["accounting"]["local_steps"]["by_step"], {})

    def test_untrusted_metadata_is_not_exposed_or_treated_as_actual_zero(self):
        value = project(usage=[parent(fact_observations_json='[{"kind":"local_step","step":{}}]')],
            calls=[physical(provenance_json='{"step":{"raw":"PRIVATE_SENTINEL"}}')],
            models=[child(known_cost_rmb=float("nan"))])
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(value, allow_nan=False))
        self.assertFalse(value["accounting"]["cost"]["complete"])
        self.assertEqual(value["accounting"]["local_steps"]["metadata_invalid_records"], 1)

    def test_subscription_period_uses_stored_dates_not_report_window(self):
        paid = reporting.subscription_period({"tier": "pro", "period_start": "2026-09-08T00:00:00+00:00",
                                               "expires_at": "2026-10-08T00:00:00+00:00"})
        self.assertEqual(paid["kind"], "stored_subscription_period")
        self.assertEqual(paid["start"], "2026-09-08T00:00:00+00:00")
        free = reporting.subscription_period({"tier": "free", "period_start": "2026-09-01T00:00:00+00:00",
                                               "expires_at": "2099-01-01T00:00:00+00:00"})
        self.assertEqual(free["end"], "2026-10-01T00:00:00+00:00")
        self.assertEqual(free["account_expires_at"], "2099-01-01T00:00:00+00:00")


class UsageReportingStorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = importlib.import_module("db")
        cls.billing = importlib.import_module("billing")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_path = self.db._DB_PATH
        self.db._DB_PATH = Path(self.temp.name) / "synthetic.db"
        self.db.init_db()
        self.billing.clear_active_usage()
        for user_id in ("owner", "other"):
            self.db.execute("INSERT INTO users(id,username,email,password_hash,password_salt,created_at) VALUES(?,?,?,?,?,?)",
                            (user_id, user_id, user_id + "@example.invalid", "hash", "salt", "2026-09-01T00:00:00+00:00"))

    def tearDown(self):
        self.billing.clear_active_usage()
        self.db._DB_PATH = self.old_path
        self.temp.cleanup()

    def usage(self, owner="owner", op="generate", at="2026-09-18T00:00:00+00:00"):
        self.billing.record_free_usage(owner, op)
        usage_id = self.billing._ACTIVE_USAGE_ID.get()
        self.db.execute("UPDATE usage_records SET recorded_at=? WHERE id=?", (at, usage_id))
        return usage_id

    def report(self, period="calendar_month"):
        with mock.patch.object(reporting, "datetime") as clock:
            clock.now.return_value = NOW
            return self.billing.get_usage_summary("owner", period=period)

    def test_summary_is_readonly_and_owner_scoped_even_mismatched_physical_owner(self):
        usage_id = self.usage()
        self.usage(owner="other")
        self.db.execute("INSERT INTO public_trial_calls(id,budget_id,user_id,request_hash,state,reserve_milli_cny,created_at,usage_record_id) VALUES(?,?,?,?,?,?,?,?)",
                        ("bad-owner", "website-free-product-20260912", "other", "hash", "unknown", 1, "2026-09-18T00:00:00Z", usage_id))
        before = self.db._DB_PATH.read_bytes()
        value = self.report()
        self.assertEqual(value["accounting"]["business"]["recorded"], 1)
        self.assertEqual(value["accounting"]["physical"]["recorded"], 0)
        self.assertEqual(before, self.db._DB_PATH.read_bytes())
        self.assertEqual(value["window"]["kind"], "calendar_month")
        self.assertEqual(value["total_api_cost_basis"], "legacy_mixed_estimate_and_usage_calculation")

    def test_explicit_month_does_not_change_legacy_rolling_call(self):
        self.usage(at="2026-08-31T23:00:00+00:00")
        self.usage(at="2026-09-01T00:00:00+00:00")
        self.usage(at="2026-10-01T00:00:00+00:00")
        self.assertEqual(self.report()["accounting"]["business"]["recorded"], 1)
        self.assertEqual(self.report("rolling_days")["accounting"]["business"]["recorded"], 2)

    def test_local_steps_use_active_owner_preserve_facts_and_never_charge(self):
        usage_id = self.usage()
        facts = [{"provider": "amap", "status": "success", "cost_cny": None}]
        self.db.execute("UPDATE usage_records SET fact_observations_json=? WHERE id=?", (json.dumps(facts), usage_id))
        before = dict(self.db.fetchone("SELECT credits_used,cost_rmb,model_calls,tokens_in FROM usage_records WHERE id=?", (usage_id,)))
        self.assertFalse(self.billing.record_local_step("local_score", "succeeded", user_id="other"))
        self.assertTrue(self.billing.record_local_step("local_score", "succeeded"))
        self.assertTrue(self.billing.record_local_step("local_score", "failed", user_id="owner"))
        self.assertEqual(before, dict(self.db.fetchone("SELECT credits_used,cost_rmb,model_calls,tokens_in FROM usage_records WHERE id=?", (usage_id,))))
        row = self.db.fetchone("SELECT fact_observations_json FROM usage_records WHERE id=?", (usage_id,))
        self.assertEqual(json.loads(row["fact_observations_json"])[0], facts[0])
        self.assertEqual(self.report()["accounting"]["local_steps"]["by_step"]["local_score"], {"succeeded": 1, "failed": 1})
        self.assertFalse(contextvars.Context().run(self.billing.record_local_step, "local_score", "succeeded"))

    def test_telemetry_failure_and_no_active_parent_do_not_change_business(self):
        self.assertFalse(self.billing.record_local_step("local_score", "succeeded"))
        self.usage()
        with mock.patch.object(self.db, "transaction", side_effect=RuntimeError("PRIVATE_SENTINEL")):
            self.assertFalse(self.billing.record_local_step("local_score", "failed"))
        self.assertFalse(self.billing.record_local_step("unknown", "succeeded"))
        self.assertEqual(self.report()["accounting"]["local_steps"]["status"], "not_recorded")

    def test_local_step_takes_owner_fence_before_parent_row_lock(self):
        usage_id = self.usage()
        events = []
        tx = mock.MagicMock(postgres=True)
        def read(sql, args):
            events.append("parent_lock" if "FOR UPDATE" in sql else "owner_read")
            if "FOR UPDATE" in sql:
                self.assertEqual(events, ["owner_read", "owner_fence", "parent_lock"])
                self.assertEqual(args, (usage_id, "owner"))
            return {"user_id": "owner", "fact_observations_json": "[]"}
        tx.fetchone.side_effect = read
        transaction = mock.MagicMock()
        transaction.__enter__.return_value = tx
        with mock.patch.object(self.db, "transaction", return_value=transaction), \
             mock.patch.object(self.billing.content_retention, "assert_user_writable_with_storage",
                               side_effect=lambda storage, owner: events.append("owner_fence")):
            self.assertTrue(self.billing.record_local_step("local_score", "succeeded"))
        self.assertEqual(events, ["owner_read", "owner_fence", "parent_lock"])

    def test_local_observation_limit_is_bounded_and_does_not_consume_fact_limit(self):
        usage_id = self.usage()
        facts = [{"provider": "amap", "observation_id": str(index)} for index in range(32)]
        self.db.execute("UPDATE usage_records SET fact_observations_json=? WHERE id=?", (json.dumps(facts), usage_id))
        for _ in range(16):
            self.assertTrue(self.billing.record_local_step("local_score", "succeeded"))
        self.assertFalse(self.billing.record_local_step("local_score", "succeeded"))
        stored = json.loads(self.db.fetchone("SELECT fact_observations_json FROM usage_records WHERE id=?", (usage_id,))[0])
        self.assertEqual(stored[:32], facts)
        self.assertEqual(len(stored), 48)

    def test_admin_and_user_use_same_month_and_unknown_cost_veto(self):
        admin = importlib.import_module("admin_server")
        usage_id = self.usage()
        self.billing.record_model_usage("kimi", "kimi-k2.6", tokens_in=100, tokens_out=20)
        self.db.execute("INSERT INTO public_trial_calls(id,budget_id,user_id,request_hash,state,reserve_milli_cny,created_at,usage_record_id) VALUES(?,?,?,?,?,?,?,?)",
                        ("unresolved", "website-free-product-20260912", "owner", "hash", "unknown", 1, "2026-09-18T00:00:00Z", usage_id))
        self.usage(at="2026-08-31T23:59:59+00:00")
        original_window = reporting.reporting_window
        with mock.patch.object(reporting, "reporting_window", side_effect=lambda **kw: original_window(**{**kw, "now": NOW})):
            public = self.billing.get_usage_summary("owner", period="calendar_month")
            management = admin.build_usage_stats_payload(period="calendar_month")
        self.assertEqual(public["accounting"], management["accounting"])
        self.assertEqual(public["window"], management["window"])
        self.assertFalse(management["coverage"]["actual_margin_ready"])
        self.assertFalse(management["accounting"]["cost"]["complete"])


if __name__ == "__main__":
    unittest.main()
