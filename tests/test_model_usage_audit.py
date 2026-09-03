import importlib
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

db = importlib.import_module("db")
billing = importlib.import_module("billing")
model_router = importlib.import_module("model_router")
api = importlib.import_module("api")
admin_server = importlib.import_module("admin_server")


class ModelUsageAuditTests(unittest.TestCase):
    def setUp(self):
        self._old_db_path = db._DB_PATH
        self._tmpdir = tempfile.TemporaryDirectory()
        db._DB_PATH = Path(self._tmpdir.name) / "noteai.db"
        db.init_db()
        billing.clear_active_usage()
        db.execute(
            "INSERT INTO users(id,username,email,password_hash,password_salt,created_at) "
            "VALUES(?,?,?,?,?,?)",
            ("u-audit", "audit", "audit@example.com", "hash", "salt", "2026-07-12T00:00:00+00:00"),
        )

    def tearDown(self):
        billing.clear_active_usage()
        db._DB_PATH = self._old_db_path
        self._tmpdir.cleanup()

    def _new_usage(self, operation="score"):
        billing.record_free_usage("u-audit", operation)
        return db.fetchone(
            "SELECT id FROM usage_records WHERE user_id=? ORDER BY recorded_at DESC LIMIT 1",
            ("u-audit",),
        )["id"]

    def _parent(self, usage_id):
        return dict(db.fetchone("SELECT * FROM usage_records WHERE id=?", (usage_id,)))

    def _children(self, usage_id):
        return [dict(row) for row in db.fetchall(
            "SELECT * FROM model_usage_records WHERE usage_record_id=? ORDER BY recorded_at,id",
            (usage_id,),
        )]

    def test_four_confirmed_models_have_auditable_exact_prices(self):
        usage_id = self._new_usage()
        billing.record_model_usage(
            "claude", "claude-haiku-4-5-20251001",
            tokens_in=1_000_000, tokens_out=1_000_000,
            cache_read_tokens=1_000_000,
            cache_write_tokens=2_000_000,
            cache_write_5m_tokens=1_000_000,
            cache_write_1h_tokens=1_000_000,
        )
        billing.record_model_usage(
            "claude", "claude-sonnet-4-6",
            tokens_in=1_000_000, tokens_out=1_000_000,
            cache_read_tokens=1_000_000,
        )
        billing.record_model_usage(
            "kimi", "kimi-k2.6",
            tokens_in=1_000_000, tokens_out=1_000_000,
            cache_read_tokens=1_000_000,
        )
        billing.record_model_usage(
            "kimi", "moonshot-v1-32k-vision-preview",
            tokens_in=1_000_000, tokens_out=1_000_000,
        )

        children = self._children(usage_id)
        self.assertEqual(len(children), 4)
        self.assertEqual({row["pricing_status"] for row in children}, {"exact"})
        self.assertEqual({row["usage_status"] for row in children}, {"complete"})
        # Haiku: ($1 + $5 + $0.1 + $1.25 + $2) * 7 = RMB 65.45.
        self.assertAlmostEqual(children[0]["known_cost_rmb"], 65.45, places=6)
        # Sonnet RMB 128.1; K2.6 RMB 34.6; Vision RMB 25.
        self.assertAlmostEqual(sum(row["known_cost_rmb"] for row in children), 253.15, places=6)
        parent = self._parent(usage_id)
        self.assertEqual(parent["cost_mode"], "actual")
        self.assertAlmostEqual(parent["actual_model_cost_rmb"], 253.15, places=6)
        self.assertAlmostEqual(parent["cost_rmb"], 253.15, places=6)

    def test_zero_exact_price_override_never_grants_actual_for_used_dimension(self):
        cases = (
            ("NOTEAI_MODEL_PRICE_CLAUDE_HAIKU_4_5_20251001_INPUT_PER_1M_USD", {"tokens_in": 100}),
            ("NOTEAI_MODEL_PRICE_CLAUDE_HAIKU_4_5_20251001_OUTPUT_PER_1M_USD", {"tokens_out": 100}),
            ("NOTEAI_MODEL_PRICE_CLAUDE_HAIKU_4_5_20251001_CACHE_READ_PER_1M_USD", {"cache_read_tokens": 100}),
        )
        for index, (key, usage) in enumerate(cases):
            old = os.environ.get(key)
            try:
                os.environ[key] = "0"
                usage_id = self._new_usage(("score", "diagnose", "chat_fast")[index])
                billing.record_model_usage(
                    "claude", "claude-haiku-4-5-20251001", **usage
                )
                child = self._children(usage_id)[0]
                self.assertEqual(child["pricing_status"], "unpriced")
                self.assertIsNone(child[
                    ("input_price_per_1m", "output_price_per_1m", "cache_read_price_per_1m")[index]
                ])
                self.assertEqual(self._parent(usage_id)["cost_mode"], "unpriced")
            finally:
                if old is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = old

    def test_kimi_cached_tokens_supports_both_shapes_and_top_level_precedence(self):
        first = self._new_usage("score")
        model_router._record_kimi_usage("kimi-k2.6", {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "cached_tokens": 30,
        })
        row = self._children(first)[0]
        self.assertEqual(row["input_tokens"], 70)
        self.assertEqual(row["cache_read_input_tokens"], 30)
        self.assertEqual(row["usage_status"], "complete")

        second = self._new_usage("diagnose")
        model_router._record_kimi_usage("kimi-k2.6", {
            "prompt_tokens": 80,
            "completion_tokens": 10,
            "prompt_tokens_details": {"cached_tokens": 25},
        })
        row = self._children(second)[0]
        self.assertEqual((row["input_tokens"], row["cache_read_input_tokens"]), (55, 25))

        third = self._new_usage("chat_fast")
        model_router._record_kimi_usage("kimi-k2.6", {
            "prompt_tokens": 26,
            "completion_tokens": 6,
            "cached_tokens": 4,
            "prompt_tokens_details": {"cached_tokens": 9},
        })
        row = self._children(third)[0]
        self.assertEqual((row["input_tokens"], row["cache_read_input_tokens"]), (22, 4))
        self.assertEqual(row["usage_status"], "complete")
        self.assertEqual(self._parent(third)["cost_mode"], "actual")

    def test_kimi_missing_cache_matches_explicit_zero_for_complete_usage(self):
        # Provider-specific compatibility: preserve explicit cache counts, but
        # normalize an omitted cache count in otherwise complete Kimi usage.
        variants = (
            {"cached_tokens": 0},
            {"prompt_tokens_details": {"cached_tokens": 0}},
            {},
            {"prompt_tokens_details": None},
            {"prompt_tokens_details": {}},
            {"prompt_tokens_details": SimpleNamespace(cached_tokens=0)},
            {"cached_tokens": 0, "prompt_tokens_details": {"cached_tokens": 9}},
        )
        expected = None
        for index, cache_shape in enumerate(variants):
            with self.subTest(index=index):
                usage_id = self._new_usage()
                model_router._record_kimi_usage("kimi-k2.6", {
                    "prompt_tokens": 26,
                    "completion_tokens": 6,
                    **cache_shape,
                })
                rows = self._children(usage_id)
                self.assertEqual(len(rows), 1)
                child = rows[0]
                parent = self._parent(usage_id)
                self.assertEqual(child["input_tokens"], 26)
                self.assertEqual(child["output_tokens"], 6)
                self.assertEqual(child["cache_read_input_tokens"], 0)
                self.assertEqual(child["unclassified_input_tokens"], 0)
                self.assertEqual(child["usage_status"], "complete")
                self.assertEqual(child["pricing_status"], "exact")
                self.assertEqual(parent["cost_mode"], "actual")
                self.assertEqual(parent["model_calls"], 1)
                projection = (
                    child["known_cost_rmb"], parent["tokens_in"],
                    parent["tokens_out"], parent["actual_model_cost_rmb"],
                )
                if expected is None:
                    expected = projection
                self.assertEqual(projection, expected)

    def test_kimi_missing_cache_never_completes_missing_or_invalid_usage(self):
        cases = (
            None,
            {},
            {"completion_tokens": 6},
            {"prompt_tokens": 26},
            {"prompt_tokens": None, "completion_tokens": 6},
            {"prompt_tokens": 26, "completion_tokens": None},
            {"prompt_tokens": True, "completion_tokens": 6},
            {"prompt_tokens": 26, "completion_tokens": False},
            {"prompt_tokens": "26", "completion_tokens": 6},
            {"prompt_tokens": 26, "completion_tokens": "6"},
            {"prompt_tokens": 26.0, "completion_tokens": 6},
            {"prompt_tokens": 26, "completion_tokens": 6.0},
            {"prompt_tokens": -1, "completion_tokens": 6},
            {"prompt_tokens": 26, "completion_tokens": -1},
            SimpleNamespace(prompt_tokens=26, completion_tokens=6),
            {"prompt_tokens": 26, "completion_tokens": 6, "prompt_tokens_details": SimpleNamespace()},
            {"prompt_tokens": 26, "completion_tokens": 6, "prompt_tokens_details": []},
            {"prompt_tokens": 26, "completion_tokens": 6, "prompt_tokens_details": "invalid"},
        )
        for index, usage in enumerate(cases):
            with self.subTest(index=index):
                usage_id = self._new_usage()
                model_router._record_kimi_usage("kimi-k2.6", usage)
                rows = self._children(usage_id)
                self.assertEqual(len(rows), 1)
                self.assertIn(rows[0]["usage_status"], {"usage_missing", "cache_usage_missing"})
                self.assertEqual(self._parent(usage_id)["cost_mode"], "usage_incomplete")

    def test_kimi_invalid_or_excess_cache_remains_fail_closed(self):
        invalid_shapes = (
            {"cached_tokens": "invalid"},
            {"prompt_tokens_details": {"cached_tokens": "invalid"}},
            {"cached_tokens": "invalid", "prompt_tokens_details": {"cached_tokens": 0}},
        )
        for index, cache_shape in enumerate(invalid_shapes):
            with self.subTest(invalid=index):
                usage_id = self._new_usage()
                with self.assertRaises(ValueError):
                    model_router._record_kimi_usage("kimi-k2.6", {
                        "prompt_tokens": 26, "completion_tokens": 6, **cache_shape,
                    })
                self.assertEqual(self._children(usage_id), [])
                self.assertNotEqual(self._parent(usage_id)["cost_mode"], "actual")

        for cache_shape in (
            {"cached_tokens": 27},
            {"prompt_tokens_details": {"cached_tokens": 27}},
        ):
            with self.subTest(excess=cache_shape):
                usage_id = self._new_usage()
                model_router._record_kimi_usage("kimi-k2.6", {
                    "prompt_tokens": 26, "completion_tokens": 6, **cache_shape,
                })
                row = self._children(usage_id)[0]
                self.assertEqual(row["usage_status"], "usage_incomplete")
                self.assertEqual(row["unclassified_input_tokens"], 26)
                self.assertEqual(self._parent(usage_id)["cost_mode"], "usage_incomplete")

    def test_direct_api_kimi_usage_uses_same_cache_contract(self):
        usage_id = self._new_usage("screenshot")
        api._record_kimi_usage_from_payload({
            "model": "kimi-k2.6",
            "usage": {"prompt_tokens": 120, "completion_tokens": 30, "cached_tokens": 20},
        })
        row = self._children(usage_id)[0]
        self.assertEqual(row["input_tokens"], 100)
        self.assertEqual(row["cache_read_input_tokens"], 20)
        self.assertEqual(row["usage_status"], "complete")

    def test_kimi_stream_usage_accepts_choice_nested_and_top_level_shapes(self):
        nested = model_router._extract_kimi_stream_usage({
            "choices": [{
                "finish_reason": "stop",
                "usage": {"prompt_tokens": 120, "completion_tokens": 30, "cached_tokens": 20},
            }]
        })
        top_level = model_router._extract_kimi_stream_usage({
            "usage": {"prompt_tokens": 80, "completion_tokens": 10, "cached_tokens": 5},
            "choices": [{"finish_reason": "stop"}],
        })
        self.assertEqual(nested["cached_tokens"], 20)
        self.assertEqual(top_level["cached_tokens"], 5)
        self.assertIsNone(model_router._extract_kimi_stream_usage({"choices": "invalid"}))

        usage_id = self._new_usage("score")
        model_router._record_kimi_usage("kimi-k2.6", nested)
        child = self._children(usage_id)[0]
        self.assertEqual(child["cache_read_input_tokens"], 20)
        self.assertEqual(child["usage_status"], "complete")
        self.assertNotEqual(self._parent(usage_id)["cost_mode"], "usage_incomplete")

    def test_claude_cache_write_without_ttl_split_is_incomplete(self):
        usage_id = self._new_usage()
        model_router._record_claude_usage("claude-sonnet-4-6", {
            "input_tokens": 100,
            "cache_creation_input_tokens": 40,
            "cache_read_input_tokens": 20,
            "output_tokens": 10,
        })
        row = self._children(usage_id)[0]
        self.assertEqual(row["cache_write_input_tokens"], 40)
        self.assertEqual(row["cache_write_unknown_ttl_tokens"], 40)
        self.assertEqual(row["usage_status"], "cache_ttl_unknown")
        self.assertEqual(self._parent(usage_id)["cost_mode"], "usage_incomplete")

    def test_partial_downgrade_is_order_independent_and_generic_never_actual(self):
        for reverse in (False, True):
            usage_id = self._new_usage("score" if not reverse else "diagnose")
            calls = [
                lambda: billing.record_model_usage(
                    "claude", "claude-haiku-4-5-20251001", tokens_in=100, tokens_out=20
                ),
                lambda: billing.record_model_usage(
                    "other", "unpriced-model", tokens_in=100, tokens_out=20
                ),
            ]
            if reverse:
                calls.reverse()
            for call in calls:
                call()
            parent = self._parent(usage_id)
            self.assertEqual(parent["cost_mode"], "partial")
            self.assertGreater(parent["actual_model_cost_rmb"], 0)
            self.assertEqual(len(self._children(usage_id)), 2)

    def test_refund_preserves_supplier_child_cost(self):
        billing.get_subscription("u-audit")
        charge = billing.check_and_deduct("u-audit", "analyze")
        billing.record_model_usage(
            "claude", "claude-haiku-4-5-20251001", tokens_in=1000, tokens_out=200
        )
        usage_id = charge["usage_id"]
        cost_before = self._parent(usage_id)["cost_rmb"]
        billing.refund_operation_charge("u-audit", "analyze", charge, "audit refund")
        parent = self._parent(usage_id)
        self.assertEqual(parent["source"], "refunded")
        self.assertEqual(parent["credits_used"], 0)
        self.assertEqual(parent["cost_rmb"], cost_before)
        self.assertEqual(len(self._children(usage_id)), 1)

    def test_twenty_concurrent_calls_recompute_parent_without_lost_updates(self):
        usage_id = self._new_usage()

        def worker():
            billing._record_model_usage_for_usage_id(
                usage_id,
                "claude", "claude-haiku-4-5-20251001",
                tokens_in=100, tokens_out=10,
            )

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        parent = self._parent(usage_id)
        self.assertEqual(parent["model_calls"], 20)
        self.assertEqual(parent["tokens_in"], 2000)
        self.assertEqual(parent["tokens_out"], 200)
        self.assertEqual(len(self._children(usage_id)), 20)
        self.assertEqual(parent["cost_mode"], "actual")

    def test_admin_payload_exposes_model_cache_and_coverage_without_false_margin_claim(self):
        usage_id = self._new_usage()
        billing.record_model_usage(
            "kimi", "kimi-k2.6", tokens_in=70, cache_read_tokens=30, tokens_out=20
        )
        payload = admin_server.build_usage_stats_payload(days=30)
        self.assertEqual(payload["coverage"]["strict_actual_records"], 1)
        self.assertTrue(payload["coverage"]["actual_margin_ready"])
        model = payload["by_model"][0]
        self.assertEqual(model["model"], "kimi-k2.6")
        self.assertEqual(model["cache_read_tokens"], 30)
        self.assertEqual(payload["cache"]["read_tokens"], 30)

        db.execute("DELETE FROM model_usage_records WHERE usage_record_id=?", (usage_id,))
        payload = admin_server.build_usage_stats_payload(days=30)
        self.assertFalse(payload["coverage"]["actual_margin_ready"])
        self.assertEqual(payload["coverage"]["legacy_unverifiable_records"], 1)

    def test_sqlite_to_postgres_order_keeps_child_after_parent(self):
        migration_tool = (ROOT / "scripts" / "migrate_sqlite_to_postgres.py").read_text(encoding="utf-8")
        self.assertLess(migration_tool.index('"usage_records"'), migration_tool.index('"model_usage_records"'))
        migration = ROOT / "model" / "migrations" / "postgres" / "0006_model_usage_records.sql"
        self.assertTrue(migration.exists())
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS model_usage_records", sql)
        self.assertIn("REFERENCES usage_records(id) ON DELETE CASCADE", sql)
        db.init_db()
        columns = {
            row[1] for row in db.fetchall("PRAGMA table_info(model_usage_records)")
        }
        self.assertFalse({"prompt", "response", "reasoning", "request_id"} & columns)


if __name__ == "__main__":
    unittest.main()
