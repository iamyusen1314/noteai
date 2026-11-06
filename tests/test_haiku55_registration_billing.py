"""New-model registration/pricing only; private SQLite, no supplier/cloud calls."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
with mock.patch("dotenv.load_dotenv", return_value=False), mock.patch.dict(os.environ, {
    "DATABASE_URL": "postgresql:///offline-import-disabled",
}):
    import db
    import billing
    import claude_gateway_protocol as protocol
    import model_admission as admission
    import model_capacity as capacity
    import model_runtime_config as config

NEW = "claude-haiku-5-5"
OLD = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-6"


class Haiku55RegistrationBillingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.stack = __import__("contextlib").ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(db, "_DB_PATH", Path(self.temp.name) / "private.db"))
        environment = {"DATABASE_URL": "", "NOTEAI_BILLING_USD_CNY": "7",
                       "NOTEAI_MODEL_CONFIG_ENABLED": "0", "NOTEAI_MODEL_CAPACITY_ENABLED": "1",
                       "NOTEAI_MODEL_CAPACITY_LIMITS_JSON": "", "NOTEAI_MODEL_REMOTE_CONCURRENCY": "64"}
        self.stack.enter_context(mock.patch.dict(os.environ, environment))
        self.stack.enter_context(mock.patch("dotenv.load_dotenv", return_value=False))
        self.stack.enter_context(mock.patch("httpx.Client.send", side_effect=AssertionError("offline network forbidden")))
        self.stack.enter_context(mock.patch("httpx.AsyncClient.send", side_effect=AssertionError("offline network forbidden")))
        billing.clear_active_usage()
        self.addCleanup(billing.clear_active_usage)

    def test_candidate_is_pure_three_route_upgrade_and_old_active_defaults_stay_selected(self):
        original = config.defaults()
        before = copy.deepcopy(original)
        candidate = config.haiku55_candidate_config(original)
        self.assertEqual(original, before)
        self.assertEqual(config.defaults(), before)
        for task in ("diagnosis", "content_gen", "semantic"):
            self.assertEqual(candidate[task]["model"], NEW)
            self.assertEqual(candidate[task]["effort"], "low" if task == "semantic" else "medium")
        for task in ("chat", "arbitrate"):
            self.assertEqual(candidate[task], original[task])
            self.assertEqual(candidate[task]["model"], SONNET)
        with mock.patch.object(db, "fetchone", return_value=None):
            self.assertEqual(config.read()["active"], original)
        with mock.patch.dict(os.environ, {"NOTEAI_MODEL_CONFIG_ENABLED": "1"}), \
                mock.patch.object(config, "read", return_value={"active": original}):
            self.assertEqual(config.resolve("content_gen", NEW, 16000)[0], OLD)
        self.assertEqual(config.resolve_effort("semantic", NEW), "low")
        self.assertEqual(config.resolve_effort("content_gen", NEW), "medium")
        self.assertIsNone(config.resolve_effort("content_gen", OLD))
        candidate["content_gen"]["effort"] = "high"
        with mock.patch.dict(os.environ, {"NOTEAI_MODEL_CONFIG_ENABLED": "1"}), \
                mock.patch.object(config, "read", return_value={"active": candidate}):
            self.assertEqual(config.resolve_effort("content_gen", NEW), "high")
        for bad in ([], "unknown"):
            invalid = copy.deepcopy(candidate)
            invalid["content_gen"]["effort"] = bad
            with self.assertRaises(HTTPException):
                config.validate(invalid)
        for task in ("diagnosis", "content_gen", "semantic"):
            # All three original product routes can invoke bounded <=4096
            # helpers; xhigh/max cannot run with their disabled-thinking mode.
            for incompatible in ("xhigh", "max"):
                invalid = copy.deepcopy(candidate)
                invalid[task]["effort"] = incompatible
                with self.assertRaises(HTTPException):
                    config.validate(invalid)
            invalid = copy.deepcopy(candidate)
            invalid[task]["max_tokens"] = 256
            with self.assertRaises(HTTPException):
                config.validate(invalid)
        invalid = copy.deepcopy(original)
        invalid["content_gen"]["effort"] = "medium"
        with self.assertRaises(HTTPException):
            config.validate(invalid)
        self.assertEqual(config.validate(original, existing=True), original)
        self.assertTrue({OLD, SONNET, NEW} <= protocol.ALLOWED_MODELS)
        self.assertEqual(protocol.HAIKU_5_5_EFFORTS, {"low", "medium", "high", "xhigh", "max"})

    def test_exact_context_boundary_all_rates_and_unknown_context_reserve_are_conservative(self):
        for total in (0, 99999, 100000):
            with self.subTest(input_tokens=total):
                rate = billing._pricing_snapshot("claude", NEW, prompt_tokens=total)
                self.assertEqual([rate[k] for k in ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")],
                                 [0.1, 0.5, 0.01, 0.125, 0.2])
                self.assertEqual(rate["pricing_status"], "exact")
        for total in (100001, None):
            with self.subTest(input_tokens=total):
                rate = billing._pricing_snapshot("claude", NEW, prompt_tokens=total)
                self.assertEqual([rate[k] for k in ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")],
                                 [0.5, 2.5, 0.05, 0.625, 1.0])
                self.assertIn("long_context", rate["price_version"])
        self.assertEqual(billing._pricing_snapshot("claude", NEW, prompt_tokens=5)["input"], 0.1,
                         "A previous long request must not change a later short request's tier")
        self.assertEqual(billing._pricing_snapshot("kimi", NEW)["pricing_status"], "unpriced")
        for invalid in (-1, True, "100001"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                billing._pricing_snapshot("claude", NEW, prompt_tokens=invalid)
        key = billing._price_env_key(NEW + "_short_context", "cache_read", "USD")
        with mock.patch.dict(os.environ, {key: "0"}):
            self.assertEqual(billing._pricing_snapshot("claude", NEW, prompt_tokens=100)["pricing_status"], "unpriced")
            self.assertEqual(billing._pricing_snapshot("claude", NEW)["pricing_status"], "unpriced",
                             "Unknown pre-wire context must validate both possible settlement tiers")

    def _create_owner(self):
        db.init_db()
        db.execute("INSERT INTO users(id,username,email,password_hash,password_salt,created_at) VALUES(?,?,?,?,?,?)",
                   ("fixture-user", "fixture-user", "fixture@example.invalid", "hash", "salt", "2026-11-06T00:00:00+00:00"))

    def test_real_ledger_counts_cache_input_for_whole_call_tier_without_rewriting_old_costs(self):
        self._create_owner()
        billing.record_free_usage("fixture-user", "score")
        billing.record_model_usage("claude", OLD, tokens_in=1000, tokens_out=200)
        old = dict(db.fetchone("SELECT * FROM model_usage_records WHERE model=?", (OLD,)))
        for uncached, expected_cost in ((40000, 0.056), (40001, 0.2800035)):
            billing.record_free_usage("fixture-user", "score")
            billing.record_model_usage("claude", NEW, tokens_in=uncached, tokens_out=1000,
                cache_read_tokens=40000, cache_write_tokens=20000,
                cache_write_5m_tokens=12000, cache_write_1h_tokens=8000)
            row = dict(db.fetchone("SELECT * FROM model_usage_records WHERE model=? AND input_tokens=?",
                                   (NEW, uncached)))
            self.assertAlmostEqual(row["known_cost_rmb"], expected_cost, places=9)
            self.assertEqual(row["pricing_status"], "exact")
            self.assertEqual(row["usage_status"], "complete")
            self.assertEqual(row["input_price_per_1m"], 0.1 if uncached == 40000 else 0.5)
            parent = db.fetchone("SELECT cost_mode,credits_used FROM usage_records WHERE id=?", (row["usage_record_id"],))
            self.assertEqual(parent["cost_mode"], "actual")
            self.assertEqual(float(parent["credits_used"]), 0)
        self.assertEqual(dict(db.fetchone("SELECT * FROM model_usage_records WHERE id=?", (old["id"],))), old)
        self.assertEqual(billing.OPERATIONS["generate"]["credits"], 8)

    def test_unknown_cache_ttl_stays_incomplete_instead_of_promoting_zero_cache_cost(self):
        self._create_owner()
        billing.record_free_usage("fixture-user", "score")
        # The normal Claude transport supplies this status when its cache
        # creation usage has no known TTL; the ledger must preserve it.
        billing.record_model_usage("claude", NEW, tokens_in=100, tokens_out=20,
            cache_write_tokens=50, cache_write_unknown_ttl_tokens=50,
            usage_status="cache_ttl_unknown")
        row = db.fetchone("SELECT usage_status FROM model_usage_records WHERE model=?", (NEW,))
        self.assertEqual(row["usage_status"], "cache_ttl_unknown")
        parent = db.fetchone("SELECT cost_mode FROM usage_records WHERE user_id=?", ("fixture-user",))
        self.assertEqual(parent["cost_mode"], "usage_incomplete")

    def test_new_policy_requires_its_own_evidence_before_queue_or_transaction_admission(self):
        old_policy = {"rpm": 10000, "itpm": 10000000, "otpm": 2000000, "evidence_ref": "existing-4.5-fixture"}
        os.environ["NOTEAI_MODEL_CAPACITY_LIMITS_JSON"] = json.dumps({OLD: old_policy, SONNET: old_policy})
        self.assertEqual(capacity.policy_for(OLD).quota_key, "claude-haiku-4.5")
        self.assertIsNone(capacity.policy_for(NEW))
        demand = capacity.Demand(NEW, 10, 10)
        with self.assertRaisesRegex(capacity.CapacityConfigurationError, "UNVERIFIED"):
            capacity.reserve_in_transaction(None, demand, call_id="never-dispatched")
        with self.assertRaisesRegex(capacity.CapacityConfigurationError, "UNVERIFIED"):
            capacity.read_available(None, demand)
        manager = admission.Admission()
        operation, owned = manager.register("fixture-user", "fixture-request", route="/generate/stream")
        self.assertTrue(owned)
        with self.assertRaisesRegex(admission.AdmissionError, "UNVERIFIED"):
            manager.calls.enqueue(operation, "unverified-new-model", "claude", model_id=NEW)
        self.assertEqual(operation.outstanding, 0)
        self.assertEqual(len(manager.calls.active), 0)
        manager.finish(operation)
        new_policy = {"rpm": 13000, "itpm": 10000000, "otpm": 2000000,
                      "evidence_ref": "HAIKU55-QUOTA-DEFAULT-ACTUAL001-20261106"}
        os.environ["NOTEAI_MODEL_CAPACITY_LIMITS_JSON"] = json.dumps({OLD: old_policy, SONNET: old_policy, NEW: new_policy})
        actual = capacity.require_verified_policy(NEW)
        self.assertEqual((actual.rpm, actual.itpm, actual.otpm), (13000, 10000000, 2000000))
        self.assertEqual(actual.quota_key, "claude-haiku-5.5")
        self.assertNotEqual(actual.quota_key, capacity.policy_for(OLD).quota_key)
        self.assertEqual(capacity.policy_for(OLD).rpm, 10000)
        ready = admission.Admission()
        op, _ = ready.register("fixture-user", "fixture-request-2", route="/generate/stream")
        ticket = ready.calls.enqueue(op, "verified-new-model", "claude", model_id=NEW)
        ready.calls.release(ticket)
        ready.finish(op)
        self.assertEqual(op.outstanding, 0)
        self.assertIn(("claude", NEW), ready.calls.families)
        self.assertEqual(set(protocol.ALLOWED_MODELS), {OLD, SONNET, NEW})


if __name__ == "__main__":
    unittest.main()
