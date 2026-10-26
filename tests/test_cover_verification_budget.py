"""Optional release-only cover ceiling; real temporary SQLite, no supplier I/O."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
import unittest
import uuid
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import billing
import cover_jobs
import db
import model_admission
import public_product
from tests import test_cover_jobs as job_fixtures


class CoverVerificationBudgetTests(unittest.TestCase):
    def setUp(self):
        self.environment = mock.patch.dict(os.environ, {"NOTEAI_PUBLIC_PRODUCT": "0"})
        self.environment.start()
        for suffix in ("USER_ID", "SINCE_UTC", "MAX_MILLI"):
            os.environ.pop("NOTEAI_COVER_VERIFY_" + suffix, None)
        self.network = mock.patch("socket.socket.connect", side_effect=AssertionError("network forbidden"))
        self.network.start()
        self.fixture = job_fixtures.CoverJobsTests()
        self.fixture.setUp()
        self.owner = str(uuid.uuid4())
        db.execute("INSERT INTO users(id,username,email,password_hash,password_salt,created_at) VALUES(?,?,?,?,?,?)",
            (self.owner, self.owner, self.owner + "@example.invalid", "fixture", "fixture", self.fixture.now.isoformat()))
        billing.get_subscription(self.owner)
        billing.grant_credits(self.owner, 64, "offline fixture")
        self.fixture.user = self.owner
        self.fixture.report = str(uuid.uuid4())
        db.execute("INSERT INTO saved_diagnoses(id,user_id,note_title,domain,diagnosis_json,created_at) VALUES(?,?,?,?,?,?)",
            (self.fixture.report, self.owner, "真实门店", "休闲娱乐体验", '{"visual":"真实照片"}', self.fixture.now.isoformat()))
        self.fixture.source = self.fixture.image(self.owner, small=True)
        self.fixture.policy.update(budget_id=cover_jobs.FORMAL_BUDGET_ID, design_version=3,
            max_physical_calls=None, workflow_engine="editable_design_opencode_v1",
            design_model="doubao-seed-2-1-pro-260915")
        self.task, self.claim = self.fixture.claim()
        self.invocation = public_product.Invocation(self.owner, self.claim["request_id"], route="/covers",
            budget_id=cover_jobs.FORMAL_BUDGET_ID)
        self.marker = public_product._invocation.set(self.invocation)
        self.usage_marker = billing._ACTIVE_USAGE_ID.set(self.claim["charge"]["usage_id"])
        self.admission = mock.patch.object(model_admission, "current",
            return_value=model_admission.Admission(model_admission.Limits(physical=2, seedream=1)))
        self.admission.start()

    def tearDown(self):
        self.admission.stop()
        billing._ACTIVE_USAGE_ID.reset(self.usage_marker)
        public_product._invocation.reset(self.marker)
        self.fixture.tearDown()
        self.network.stop()
        self.environment.stop()

    def configure(self, cap="7804"):
        os.environ.update(NOTEAI_COVER_VERIFY_USER_ID=self.owner,
            NOTEAI_COVER_VERIFY_SINCE_UTC=(self.fixture.now - timedelta(seconds=1)).isoformat(),
            NOTEAI_COVER_VERIFY_MAX_MILLI=cap)

    def reserve(self, amount):
        return public_product._reserve_payload({"model": "doubao-seed-2-1-pro-260915"}, amount,
            require_metered=True)

    def counters(self):
        return (db.fetchone("SELECT reserved_milli_cny FROM public_trial_budget WHERE id=?",
            (cover_jobs.FORMAL_BUDGET_ID,))[0], db.fetchone("SELECT COUNT(*) FROM public_trial_calls")[0])

    def reject_unchanged(self, amount, code):
        before = self.counters()
        self.invocation.failure = ""
        with self.assertRaises(public_product.TrialProviderStopped) as stopped:
            self.reserve(amount)
        self.assertEqual(str(stopped.exception), code)
        if code.startswith("COVER_VERIFY_"):
            self.assertEqual(stopped.exception.code, code)
        self.assertEqual(self.counters(), before)

    def text(self, reserve, cost, *, currency="RMB", status="complete"):
        self.invocation.failure = ""
        call = self.reserve(reserve)
        model_id = str(uuid.uuid4())
        db.execute("INSERT INTO model_usage_records(id,usage_record_id,provider,model,price_currency,usd_cny,"
            "price_version,known_cost_rmb,pricing_status,usage_status,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (model_id, self.claim["charge"]["usage_id"], "doubao", "doubao-seed-2-1-pro-260915", currency,
             1, "offline-fixed-price", cost, "exact", status, datetime.now(timezone.utc).isoformat()))
        db.execute("UPDATE public_trial_calls SET state='responded',http_status=200,model_usage_record_id=?,"
            "usage_fingerprint=? WHERE id=?", (model_id, "a" * 64, call))
        return call, model_id

    def image(self):
        self.invocation.failure = ""
        call = self.reserve(760)
        stamp = datetime.now(timezone.utc).isoformat()
        db.execute("INSERT INTO cover_image_usage(id,job_id,usage_id,provider,model_id,state,input_images,"
            "output_images,billed_images,width,height,pricing_json,estimated_cost,currency,price_version,"
            "cost_status,http_status,created_at,completed_at) VALUES(?,?,?,?,?,'responded',9,1,1,1776,2368,?,"
            "'0.76','CNY','fixture','unknown',200,?,?)", (call, self.task["job_id"],
            self.claim["charge"]["usage_id"], "seedream", cover_jobs.MODEL_ID, '{"fixture":true}', stamp, stamp))
        db.execute("UPDATE public_trial_calls SET state='responded',http_status=200 WHERE id=?", (call,))
        return call

    def test_actual_call_ceil_and_unbilled_image_hold_not_native_counter(self):
        self.configure()
        self.text(2753, "0.1000001")  # Per-call ceiling is 101 milli-CNY, never zero.
        self.text(2753, "0.200")
        self.image()  # Native cumulative hold is 6266, conservative actual is 1061.
        self.assertEqual(self.counters(), (6266, 3))
        self.reserve(6743)  # Exactly 7804, even though cumulative reserve exceeds 7804.
        self.assertEqual(self.counters(), (13009, 4))
        self.reject_unchanged(1, "COVER_VERIFY_BUDGET_EXHAUSTED")
        self.assertEqual(self.fixture.balances()[1], 0)  # No delivery/credit settlement.

    def test_billed_image_uses_actual_even_above_original_reserve(self):
        self.configure()
        call = self.image()
        db.execute("UPDATE cover_image_usage SET cost_status='billed',actual_cost='8.0001',"
            "evidence_ref_hash=? WHERE id=?", ("a" * 64, call))
        self.reject_unchanged(1, "COVER_VERIFY_BUDGET_EXHAUSTED")

    def test_invalid_currency_cost_or_dual_accounting_stops_before_insert(self):
        self.configure()
        call, model = self.text(2753, "0.1")
        for values in (("USD", ".1", "complete"), ("RMB", None, "complete"),
                       ("CNY", "NaN", "complete"), ("CNY", -1, "complete"), ("RMB", ".1", "partial")):
            with self.subTest(values=values):
                db.execute("UPDATE model_usage_records SET price_currency=?,known_cost_rmb=?,usage_status=? WHERE id=?",
                    (*values, model))
                self.reject_unchanged(1, "COVER_VERIFY_ACCOUNTING_UNCONFIRMED")
        db.execute("UPDATE model_usage_records SET price_currency='RMB',known_cost_rmb=.1,usage_status='complete' WHERE id=?", (model,))
        image = self.image()
        duplicate = str(uuid.uuid4())
        db.execute("INSERT INTO model_usage_records(id,usage_record_id,provider,model,price_currency,usd_cny,"
            "price_version,known_cost_rmb,pricing_status,usage_status,recorded_at) "
            "SELECT ?,usage_record_id,provider,model,price_currency,usd_cny,price_version,known_cost_rmb,"
            "pricing_status,usage_status,recorded_at FROM model_usage_records WHERE id=?", (duplicate, model))
        db.execute("UPDATE public_trial_calls SET model_usage_record_id=?,usage_fingerprint=? WHERE id=?", (duplicate, "a" * 64, image))
        self.reject_unchanged(1, "COVER_VERIFY_ACCOUNTING_UNCONFIRMED")

    def test_non200_holds_and_original_unknown_or_unlinked_guards_precede_ceiling(self):
        self.configure()
        call = self.reserve(2753)
        db.execute("UPDATE public_trial_calls SET state='responded',http_status=401 WHERE id=?", (call,))
        self.reserve(5051)
        self.reject_unchanged(1, "COVER_VERIFY_BUDGET_EXHAUSTED")
        db.execute("UPDATE public_trial_calls SET state='unknown',http_status=NULL WHERE id=?", (call,))
        self.reject_unchanged(1, "PUBLIC_TRIAL_UNKNOWN_NO_REPLAY")
        db.execute("UPDATE public_trial_calls SET state='responded',http_status=200 WHERE id=?", (call,))
        self.reject_unchanged(1, "COVER_ACCOUNTING_UNCONFIRMED_NO_REPLAY")

    def test_first_persisted_job_only_and_since_is_not_a_reset(self):
        self.configure()
        self.reserve(1)
        other = self.fixture.submit()
        second = cover_jobs.claim_job(other["job_id"])
        self.invocation.request_id = second["request_id"]
        billing._ACTIVE_USAGE_ID.set(second["charge"]["usage_id"])
        self.reject_unchanged(1, "COVER_VERIFY_TASK_SCOPE_INVALID")
        self.invocation.failure = ""
        os.environ["NOTEAI_COVER_VERIFY_SINCE_UTC"] = (self.fixture.now + timedelta(days=1)).isoformat()
        self.reject_unchanged(1, "COVER_VERIFY_TASK_SCOPE_INVALID")

    def test_opt_in_config_and_unrelated_users_or_report_routes_keep_old_behavior(self):
        self.reserve(9000)  # No optional environment, formal is owner-metered limit zero.
        self.configure()
        os.environ["NOTEAI_COVER_VERIFY_MAX_MILLI"] = "invalid"
        self.reject_unchanged(1, "COVER_VERIFY_BUDGET_CONFIG_INVALID")
        self.invocation.failure = ""
        os.environ["NOTEAI_COVER_VERIFY_USER_ID"] = str(uuid.uuid4())
        public_product._record_response(next(iter(self.invocation.call_ids)), 401)
        self.reserve(9000)  # Another owner is outside this release scope.
        self.invocation.failure = ""
        self.invocation.route = "/generate/stream"
        self.invocation.budget_id = public_product.BUDGET_ID
        db.execute("UPDATE public_trial_budget SET enabled=1 WHERE id=?", (public_product.BUDGET_ID,))
        public_product._reserve_payload({"model": "doubao-seed-2-1-pro-260915"}, 1)
        # Optional cover configuration never applies to reports.


if __name__ == "__main__":
    unittest.main()
