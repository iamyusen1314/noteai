import asyncio
import importlib
import inspect
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

db = importlib.import_module("db")
billing = importlib.import_module("billing")
idempotency = importlib.import_module("idempotency")
api = importlib.import_module("api")


class PaidRequestIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.old_db_path = db._DB_PATH
        self.temp = tempfile.TemporaryDirectory()
        db._DB_PATH = Path(self.temp.name) / "noteai.db"
        db.init_db()
        billing.clear_active_usage()

    def tearDown(self):
        billing.clear_active_usage()
        db._DB_PATH = self.old_db_path
        self.temp.cleanup()

    def _create_user(self, user_id: str):
        db.execute(
            "INSERT INTO users(id,username,email,password_hash,password_salt,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (
                user_id,
                f"{user_id}_name",
                f"{user_id}@example.com",
                "hash",
                "salt",
                "2026-07-11T00:00:00+00:00",
            ),
        )

    def _claim(self, user_id: str, key: str, payload=None, operation: str = "analyze"):
        return idempotency.claim_and_charge(
            user_id=user_id,
            operation=operation,
            request_id=key,
            payload=payload or {"domain": "美食", "content": "payload-a"},
        )

    def test_sqlite_schema_initialization_is_idempotent_and_digest_only(self):
        db.init_db()
        db.init_db()
        conn = db.get_conn()
        try:
            columns = {
                row["name"] for row in conn.execute(
                    "PRAGMA table_info(idempotency_requests)"
                ).fetchall()
            }
            indexes = {
                row["name"] for row in conn.execute(
                    "PRAGMA index_list(idempotency_requests)"
                ).fetchall()
            }
        finally:
            conn.close()
        self.assertTrue({
            "user_id", "operation", "key_hash", "payload_hash", "status",
            "lease_token_hash", "lease_expires_at", "usage_created",
            "charged_subscription_id", "charged_period_start",
            "charge_applied", "refund_applied", "complete_applied",
            "usage_created_at", "charged_at", "refunded_at", "completed_at", "failed_at",
        }.issubset(columns))
        self.assertFalse({"raw_key", "request_body", "prompt", "reasoning"} & columns)
        self.assertIn("idx_idempotency_status_lease", indexes)

        migration = (
            ROOT / "model" / "migrations" / "postgres" / "0005_idempotency_requests.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS idempotency_requests", migration)
        self.assertIn("CREATE INDEX IF NOT EXISTS idx_idempotency_status_lease", migration)
        for forbidden in ("raw_key", "request_body", "prompt", "reasoning"):
            self.assertNotIn(forbidden, migration)

    def test_missing_user_is_rejected_before_idempotency_insert(self):
        with self.assertRaises(HTTPException) as missing:
            self._claim("missing-user", "missing-user-key")
        self.assertEqual(missing.exception.status_code, 401)
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM idempotency_requests")["c"],
            0,
        )

    def test_same_key_twenty_concurrent_claims_create_one_charge_and_usage(self):
        self._create_user("u-same-key")

        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(
                lambda _index: self._claim("u-same-key", "same-key-20"),
                range(20),
            ))

        self.assertEqual(sum(row["state"] == "owner" for row in results), 1)
        self.assertTrue(all(row["state"] in {"owner", "in_progress"} for row in results))
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM idempotency_requests")["c"], 1
        )
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS c FROM usage_records")["c"], 1)
        sub = db.fetchone(
            "SELECT used_monthly_credits FROM subscriptions WHERE user_id=? AND is_active=1",
            ("u-same-key",),
        )
        self.assertEqual(sub["used_monthly_credits"], 6)

    def test_distinct_keys_competing_for_one_charge_never_make_balance_negative(self):
        self._create_user("u-distinct-keys")
        billing.get_subscription("u-distinct-keys")
        billing.topup_credits("u-distinct-keys", 6)
        db.execute(
            "UPDATE subscriptions SET used_monthly_credits=12 WHERE user_id=? AND is_active=1",
            ("u-distinct-keys",),
        )

        def attempt(index):
            try:
                return self._claim("u-distinct-keys", f"distinct-{index}")["state"]
            except HTTPException as exc:
                return f"http-{exc.status_code}"

        with ThreadPoolExecutor(max_workers=20) as pool:
            states = list(pool.map(attempt, range(20)))

        self.assertEqual(states.count("owner"), 1)
        self.assertEqual(states.count("http-402"), 19)
        credits = db.fetchone(
            "SELECT balance,total_used FROM credits WHERE user_id=?",
            ("u-distinct-keys",),
        )
        self.assertEqual(credits["balance"], 0)
        self.assertEqual(credits["total_used"], 6)
        self.assertGreaterEqual(credits["balance"], 0)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS c FROM usage_records")["c"], 1)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS c FROM idempotency_requests")["c"], 1)

    def test_new_user_concurrent_first_charge_creates_one_active_subscription(self):
        self._create_user("u-new-concurrent")

        def attempt(index):
            try:
                return self._claim(
                    "u-new-concurrent",
                    f"new-user-{index}",
                    operation="generate",
                )["state"]
            except HTTPException as exc:
                return f"http-{exc.status_code}"

        with ThreadPoolExecutor(max_workers=20) as pool:
            states = list(pool.map(attempt, range(20)))

        self.assertEqual(states.count("owner"), 1)
        self.assertEqual(states.count("http-402"), 19)
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM subscriptions WHERE user_id=? AND is_active=1",
                ("u-new-concurrent",),
            )["c"],
            1,
        )
        sub = db.fetchone(
            "SELECT used_monthly_credits FROM subscriptions WHERE user_id=? AND is_active=1",
            ("u-new-concurrent",),
        )
        self.assertEqual(sub["used_monthly_credits"], 8)
        credits = db.fetchone("SELECT balance FROM credits WHERE user_id=?", ("u-new-concurrent",))
        self.assertGreaterEqual(credits["balance"], 0)

    def test_conflict_completion_failure_and_cross_user_states_are_stable(self):
        self._create_user("u-state-a")
        self._create_user("u-state-b")
        first = self._claim("u-state-a", "shared-user-key")
        conflict = self._claim(
            "u-state-a",
            "shared-user-key",
            payload={"domain": "美食", "content": "different"},
        )
        other_user = self._claim("u-state-b", "shared-user-key")

        self.assertEqual(conflict["state"], "conflict")
        self.assertEqual(other_user["state"], "owner")
        self.assertTrue(idempotency.mark_completed(first))
        self.assertFalse(idempotency.mark_completed(first))
        self.assertEqual(self._claim("u-state-a", "shared-user-key")["state"], "completed")

        failed = self._claim("u-state-a", "failed-key", operation="chat_rewrite")
        self.assertTrue(idempotency.mark_failed_and_refund(failed, failure_code="request_failed"))
        self.assertFalse(idempotency.mark_failed_and_refund(failed, failure_code="request_failed"))
        self.assertEqual(
            self._claim("u-state-a", "failed-key", operation="chat_rewrite")["state"],
            "failed",
        )
        failed_row = db.fetchone(
            "SELECT status,refund_applied,failure_code FROM idempotency_requests WHERE id=?",
            (failed["request_id"],),
        )
        self.assertEqual(dict(failed_row), {
            "status": "failed", "refund_applied": 1, "failure_code": "request_failed",
        })

    def test_concurrent_failure_finalization_refunds_wallet_exactly_once(self):
        self._create_user("u-refund-once")
        billing.get_subscription("u-refund-once")
        billing.topup_credits("u-refund-once", 6)
        db.execute(
            "UPDATE subscriptions SET used_monthly_credits=12 WHERE user_id=? AND is_active=1",
            ("u-refund-once",),
        )
        claim = self._claim("u-refund-once", "refund-once")

        with ThreadPoolExecutor(max_workers=20) as pool:
            finalized = list(pool.map(
                lambda _index: idempotency.mark_failed_and_refund(
                    claim, failure_code="request_failed"
                ),
                range(20),
            ))

        self.assertEqual(finalized.count(True), 1)
        self.assertEqual(finalized.count(False), 19)
        credits = db.fetchone(
            "SELECT balance,total_used FROM credits WHERE user_id=?",
            ("u-refund-once",),
        )
        self.assertEqual(dict(credits), {"balance": 6.0, "total_used": 0.0})
        usage = db.fetchone(
            "SELECT source,credits_used FROM usage_records WHERE user_id=?",
            ("u-refund-once",),
        )
        self.assertEqual(dict(usage), {"source": "refunded", "credits_used": 0.0})
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM credit_transactions WHERE user_id=? AND type='refund'",
                ("u-refund-once",),
            )["c"],
            1,
        )
        row = db.fetchone(
            "SELECT charge_applied,usage_created,refund_applied,complete_applied,"
            "charged_at,refunded_at,failed_at FROM idempotency_requests WHERE id=?",
            (claim["request_id"],),
        )
        self.assertEqual(row["charge_applied"], 1)
        self.assertEqual(row["usage_created"], 1)
        self.assertEqual(row["refund_applied"], 1)
        self.assertEqual(row["complete_applied"], 0)
        self.assertTrue(row["charged_at"])
        self.assertTrue(row["refunded_at"])
        self.assertTrue(row["failed_at"])

    def test_monthly_refund_is_bound_to_original_subscription_period(self):
        self._create_user("u-period-bound")
        claim = self._claim("u-period-bound", "period-bound")
        charged_subscription_id = claim["charge"]["subscription_id"]
        db.execute(
            "UPDATE subscriptions SET period_start=?,used_monthly_credits=2 WHERE id=?",
            ("2026-08-01T00:00:00+00:00", charged_subscription_id),
        )

        self.assertTrue(idempotency.mark_failed_and_refund(claim))

        current = db.fetchone(
            "SELECT used_monthly_credits FROM subscriptions WHERE id=?",
            (charged_subscription_id,),
        )
        self.assertEqual(current["used_monthly_credits"], 2)
        usage = db.fetchone(
            "SELECT source,credits_used FROM usage_records WHERE id=?",
            (claim["charge"]["usage_id"],),
        )
        self.assertEqual(dict(usage), {"source": "refunded", "credits_used": 0.0})

    def test_refund_after_upgrade_only_changes_original_subscription(self):
        self._create_user("u-upgrade-bound")
        claim = self._claim("u-upgrade-bound", "upgrade-bound")
        old_subscription_id = claim["charge"]["subscription_id"]
        upgraded = billing.upgrade_subscription("u-upgrade-bound", "pro")
        db.execute(
            "UPDATE subscriptions SET used_monthly_credits=2 WHERE id=?",
            (upgraded["id"],),
        )

        self.assertTrue(idempotency.mark_failed_and_refund(claim))

        old_sub = db.fetchone(
            "SELECT is_active,used_monthly_credits FROM subscriptions WHERE id=?",
            (old_subscription_id,),
        )
        new_sub = db.fetchone(
            "SELECT is_active,used_monthly_credits FROM subscriptions WHERE id=?",
            (upgraded["id"],),
        )
        self.assertEqual(old_sub["is_active"], 0)
        self.assertEqual(old_sub["used_monthly_credits"], 0)
        self.assertEqual(new_sub["is_active"], 1)
        self.assertEqual(new_sub["used_monthly_credits"], 2)

    def test_refund_with_multiple_active_rows_only_changes_charged_row(self):
        self._create_user("u-multi-active")
        claim = self._claim("u-multi-active", "multi-active")
        charged_id = claim["charge"]["subscription_id"]
        second_id = "second-active-subscription"
        db.execute(
            "INSERT INTO subscriptions(id,user_id,tier,started_at,expires_at,is_active,"
            "used_analyze,used_generate,used_chat_rewrite,used_screenshot,"
            "used_monthly_credits,period_start) VALUES(?,?,?,?,?,1,0,0,0,0,2,?)",
            (
                second_id,
                "u-multi-active",
                "pro",
                "2026-07-11T01:00:00+00:00",
                "2099-01-01T00:00:00+00:00",
                "2026-07-01T00:00:00+00:00",
            ),
        )

        self.assertTrue(idempotency.mark_failed_and_refund(claim))
        charged = db.fetchone(
            "SELECT used_monthly_credits FROM subscriptions WHERE id=?", (charged_id,)
        )
        second = db.fetchone(
            "SELECT used_monthly_credits FROM subscriptions WHERE id=?", (second_id,)
        )
        self.assertEqual(charged["used_monthly_credits"], 0)
        self.assertEqual(second["used_monthly_credits"], 2)

    def test_upgrade_and_first_claim_share_user_lock_and_leave_one_active_subscription(self):
        self._create_user("u-upgrade-race")

        def upgrade(_index):
            billing.upgrade_subscription("u-upgrade-race", "pro")
            return "upgrade"

        def claim(_index):
            try:
                return self._claim("u-upgrade-race", "upgrade-race-key")["state"]
            except HTTPException as exc:
                return f"http-{exc.status_code}"

        with ThreadPoolExecutor(max_workers=20) as pool:
            futures = [pool.submit(upgrade, index) for index in range(10)]
            futures.extend(pool.submit(claim, index) for index in range(10))
            states = [future.result() for future in futures]

        self.assertIn("owner", states)
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM subscriptions WHERE user_id=? AND is_active=1",
                ("u-upgrade-race",),
            )["c"],
            1,
        )

    def test_concurrent_completion_finalization_is_applied_once(self):
        self._create_user("u-complete-once")
        claim = self._claim("u-complete-once", "complete-once")
        with ThreadPoolExecutor(max_workers=20) as pool:
            finalized = list(pool.map(
                lambda _index: idempotency.mark_completed(claim),
                range(20),
            ))
        self.assertEqual(finalized.count(True), 1)
        self.assertEqual(finalized.count(False), 19)
        row = db.fetchone(
            "SELECT status,complete_applied,completed_at,refund_applied FROM idempotency_requests WHERE id=?",
            (claim["request_id"],),
        )
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["complete_applied"], 1)
        self.assertTrue(row["completed_at"])
        self.assertEqual(row["refund_applied"], 0)

    def test_quota_failure_leaves_no_claim_or_usage_and_stores_no_raw_payload(self):
        self._create_user("u-no-quota")
        billing.get_subscription("u-no-quota")
        db.execute(
            "UPDATE subscriptions SET used_monthly_credits=12 WHERE user_id=? AND is_active=1",
            ("u-no-quota",),
        )
        raw_key = "private-request-key"
        raw_body = "private正文 prompt reasoning https://secret.invalid"
        with self.assertRaises(HTTPException) as ctx:
            self._claim(
                "u-no-quota",
                raw_key,
                payload={"body": raw_body},
                operation="analyze",
            )
        self.assertEqual(ctx.exception.status_code, 402)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS c FROM idempotency_requests")["c"], 0)
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS c FROM usage_records")["c"], 0)

        self._create_user("u-hash-only")
        claim = self._claim("u-hash-only", raw_key, payload={"body": raw_body})
        stored = dict(db.fetchone("SELECT * FROM idempotency_requests WHERE id=?", (claim["request_id"],)))
        serialized = json.dumps(stored, ensure_ascii=False)
        self.assertNotIn(raw_key, serialized)
        self.assertNotIn(raw_body, serialized)
        self.assertEqual(len(stored["key_hash"]), 64)
        self.assertEqual(len(stored["payload_hash"]), 64)

    def test_expired_running_lease_is_not_automatically_taken_over_in_phase_one(self):
        self._create_user("u-stale")
        claim = self._claim("u-stale", "stale-key")
        db.execute(
            "UPDATE idempotency_requests SET lease_expires_at=? WHERE id=?",
            ("2000-01-01T00:00:00+00:00", claim["request_id"]),
        )
        duplicate = self._claim("u-stale", "stale-key")
        self.assertEqual(duplicate["state"], "in_progress")
        self.assertEqual(db.fetchone("SELECT COUNT(*) AS c FROM usage_records")["c"], 1)

    def test_analyze_route_duplicate_key_does_not_invoke_pipeline_twice(self):
        self._create_user("u-route")
        original_pipeline = api._run_analyze_pipeline
        calls = []

        async def fake_pipeline(req, user, **kwargs):
            calls.append((req.note_title, user["id"], bool(kwargs.get("billing_managed"))))
            return "safe-result"

        api._run_analyze_pipeline = fake_pipeline
        try:
            request = api.AnalyzeInput(note_title="标题", desc="正文", domain="美食")
            first = asyncio.run(api.analyze(
                request,
                user={"id": "u-route"},
                request_id="route-request-key",
            ))
            self.assertEqual(first, "safe-result")
            with self.assertRaises(HTTPException) as duplicate:
                asyncio.run(api.analyze(
                    request,
                    user={"id": "u-route"},
                    request_id="route-request-key",
                ))
            self.assertEqual(duplicate.exception.status_code, 409)
            self.assertEqual(duplicate.exception.detail["code"], "IDEMPOTENCY_COMPLETED")
            with self.assertRaises(HTTPException) as conflict:
                asyncio.run(api.analyze(
                    request.model_copy(update={"desc": "不同正文"}),
                    user={"id": "u-route"},
                    request_id="route-request-key",
                ))
            self.assertEqual(conflict.exception.detail["code"], "IDEMPOTENCY_CONFLICT")
            self.assertEqual(calls, [("标题", "u-route", True)])
            self.assertEqual(db.fetchone("SELECT COUNT(*) AS c FROM usage_records")["c"], 1)
        finally:
            api._run_analyze_pipeline = original_pipeline

    def test_generate_route_duplicate_key_does_not_invoke_agents_twice(self):
        self._create_user("u-generate-route")
        original_agents = api._run_generation_agents
        original_facts = api._maybe_enrich_facts
        original_timing = api._compute_market_timing_for_delivery
        calls = []

        async def fake_agents(**_kwargs):
            calls.append("agents")
            return {
                "title": "安全标题",
                "body": "安全正文",
                "variants": [],
                "ces_percentile": 75.0,
                "grade": "良好",
                "feature_hits": {},
                "quality_issues": [],
                "expert_opinions": [],
                "selection_meta": {},
            }

        async def no_facts(*_args, **_kwargs):
            return {}

        api._run_generation_agents = fake_agents
        api._maybe_enrich_facts = no_facts
        api._compute_market_timing_for_delivery = lambda *_args, **_kwargs: None
        try:
            request = api.GenerateInput(domain="美食", brief="简报")
            first = asyncio.run(api.generate(
                request,
                user={"id": "u-generate-route"},
                request_id="generate-route-key",
            ))
            self.assertEqual(first.note_title, "安全标题")
            with self.assertRaises(HTTPException) as duplicate:
                asyncio.run(api.generate(
                    request,
                    user={"id": "u-generate-route"},
                    request_id="generate-route-key",
                ))
            self.assertEqual(duplicate.exception.detail["code"], "IDEMPOTENCY_COMPLETED")
            self.assertEqual(calls, ["agents"])
            self.assertEqual(db.fetchone("SELECT COUNT(*) AS c FROM usage_records")["c"], 1)
        finally:
            api._run_generation_agents = original_agents
            api._maybe_enrich_facts = original_facts
            api._compute_market_timing_for_delivery = original_timing

    def test_generate_response_construction_failure_refunds_keyed_charge(self):
        self._create_user("u-generate-malformed")
        original_agents = api._run_generation_agents
        original_facts = api._maybe_enrich_facts
        original_timing = api._compute_market_timing_for_delivery

        async def malformed_agents(**_kwargs):
            return {"quality_issues": [], "ces_percentile": 75.0, "grade": "良好"}

        async def no_facts(*_args, **_kwargs):
            return {}

        api._run_generation_agents = malformed_agents
        api._maybe_enrich_facts = no_facts
        api._compute_market_timing_for_delivery = lambda *_args, **_kwargs: None
        try:
            with self.assertRaises(KeyError):
                asyncio.run(api.generate(
                    api.GenerateInput(domain="美食", brief="简报"),
                    user={"id": "u-generate-malformed"},
                    request_id="malformed-generate-key",
                ))
            row = db.fetchone(
                "SELECT status,refund_applied,failure_code FROM idempotency_requests WHERE user_id=?",
                ("u-generate-malformed",),
            )
            self.assertEqual(row["status"], "failed")
            self.assertEqual(row["refund_applied"], 1)
            self.assertEqual(row["failure_code"], "request_failed")
            usage = db.fetchone(
                "SELECT source,credits_used FROM usage_records WHERE user_id=?",
                ("u-generate-malformed",),
            )
            self.assertEqual(usage["source"], "refunded")
            self.assertEqual(usage["credits_used"], 0)
        finally:
            api._run_generation_agents = original_agents
            api._maybe_enrich_facts = original_facts
            api._compute_market_timing_for_delivery = original_timing

    def test_chat_persists_session_before_success_terminal(self):
        source = inspect.getsource(api._chat_sse_generator)
        self.assertLess(
            source.rfind("_persist_chat_session(session_id)"),
            source.rfind("{'type': 'done'}"),
        )

    def test_paid_chat_duplicate_running_key_does_not_start_second_stream(self):
        self._create_user("u-chat-route")
        original_sessions = dict(api._chat_sessions)
        original_generator = api._chat_sse_generator
        calls = []

        async def fake_chat_stream(*_args, **_kwargs):
            calls.append("chat-ai")
            yield 'data: {"type":"done"}\n\n'

        async def consume_response(response):
            return [chunk async for chunk in response.body_iterator]

        api._chat_sessions.clear()
        api._chat_sessions["chat-owned"] = {
            "user_id": "u-chat-route",
            "messages": [],
            "domain": "美食",
        }
        api._chat_sse_generator = fake_chat_stream
        try:
            request = api.ChatMessageInput(
                session_id="chat-owned",
                message="按这个方向重写一版",
            )
            response = asyncio.run(api.chat_message(
                request,
                user={"id": "u-chat-route"},
                request_id="chat-route-key",
            ))
            with self.assertRaises(HTTPException) as duplicate:
                asyncio.run(api.chat_message(
                    request,
                    user={"id": "u-chat-route"},
                    request_id="chat-route-key",
                ))
            self.assertEqual(duplicate.exception.detail["code"], "IDEMPOTENCY_IN_PROGRESS")
            self.assertEqual(calls, [])
            asyncio.run(consume_response(response))
            self.assertEqual(calls, ["chat-ai"])
            self.assertEqual(db.fetchone("SELECT COUNT(*) AS c FROM usage_records")["c"], 1)
        finally:
            api._chat_sse_generator = original_generator
            api._chat_sessions.clear()
            api._chat_sessions.update(original_sessions)

    def test_analyze_stream_claims_before_pipeline_and_refunds_error(self):
        self._create_user("u-analyze-stream")
        original_pipeline = api._run_analyze_pipeline
        calls = []

        async def fake_pipeline(_req, _user, emit=None, **_kwargs):
            calls.append("analyze-stream-ai")
            if emit:
                await emit({"type": "stage", "stage": "safe"})
            return SimpleNamespace(model_dump=lambda: {"result": "safe"})

        async def consume_response(response):
            return [chunk async for chunk in response.body_iterator]

        api._run_analyze_pipeline = fake_pipeline
        try:
            request = api.AnalyzeInput(note_title="标题", desc="正文", domain="美食")
            response = asyncio.run(api.analyze_stream_endpoint(
                request,
                user={"id": "u-analyze-stream"},
                request_id="analyze-stream-key",
            ))
            with self.assertRaises(HTTPException) as duplicate:
                asyncio.run(api.analyze_stream_endpoint(
                    request,
                    user={"id": "u-analyze-stream"},
                    request_id="analyze-stream-key",
                ))
            self.assertEqual(duplicate.exception.detail["code"], "IDEMPOTENCY_IN_PROGRESS")
            self.assertEqual(calls, [])
            asyncio.run(consume_response(response))
            self.assertEqual(calls, ["analyze-stream-ai"])

            async def failed_pipeline(*_args, **_kwargs):
                calls.append("analyze-stream-failed")
                raise HTTPException(status_code=500, detail="fixed failure")

            api._run_analyze_pipeline = failed_pipeline
            failed_response = asyncio.run(api.analyze_stream_endpoint(
                request.model_copy(update={"desc": "失败正文"}),
                user={"id": "u-analyze-stream"},
                request_id="analyze-stream-failed-key",
            ))
            asyncio.run(consume_response(failed_response))
            failed = db.fetchone(
                "SELECT status,refund_applied FROM idempotency_requests "
                "WHERE user_id=? AND status='failed'",
                ("u-analyze-stream",),
            )
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["refund_applied"], 1)
        finally:
            api._run_analyze_pipeline = original_pipeline

    def test_generate_stream_claims_before_pipeline_headerless_works_and_error_refunds(self):
        self._create_user("u-generate-stream")
        original_pipeline = api._generate_pipeline_stream
        original_facts = api._maybe_enrich_facts
        original_timing = api._compute_market_timing_for_delivery
        original_check = api._billing.check_and_deduct
        calls = []

        async def fake_pipeline(**_kwargs):
            calls.append("generate-stream-ai")
            yield {"type": "complete", "quality_issues": []}

        async def no_facts(*_args, **_kwargs):
            return {}

        async def consume_response(response):
            return [chunk async for chunk in response.body_iterator]

        api._generate_pipeline_stream = fake_pipeline
        api._maybe_enrich_facts = no_facts
        api._compute_market_timing_for_delivery = lambda *_args, **_kwargs: None
        try:
            request = api.GenerateInput(domain="美食", brief="简报")
            response = asyncio.run(api.generate_stream_endpoint(
                request,
                user={"id": "u-generate-stream"},
                request_id="generate-stream-key",
            ))
            with self.assertRaises(HTTPException) as duplicate:
                asyncio.run(api.generate_stream_endpoint(
                    request,
                    user={"id": "u-generate-stream"},
                    request_id="generate-stream-key",
                ))
            self.assertEqual(duplicate.exception.detail["code"], "IDEMPOTENCY_IN_PROGRESS")
            self.assertEqual(calls, [])
            asyncio.run(consume_response(response))
            self.assertEqual(calls, ["generate-stream-ai"])

            api._billing.check_and_deduct = (
                lambda user_id, operation: calls.append((user_id, operation)) or {"usage_id": "legacy"}
            )
            headerless = asyncio.run(api.generate_stream_endpoint(
                request.model_copy(update={"brief": "无键兼容"}),
                user={"id": "u-generate-stream"},
            ))
            asyncio.run(consume_response(headerless))
            self.assertIn(("u-generate-stream", "generate"), calls)

            async def failed_pipeline(**_kwargs):
                calls.append("generate-stream-failed")
                raise RuntimeError("fixed stream failure")
                yield {}

            api._generate_pipeline_stream = failed_pipeline
            billing.topup_credits("u-generate-stream", 8)
            failed_response = asyncio.run(api.generate_stream_endpoint(
                request.model_copy(update={"brief": "失败简报"}),
                user={"id": "u-generate-stream"},
                request_id="generate-stream-failed-key",
            ))
            asyncio.run(consume_response(failed_response))
            failed = db.fetchone(
                "SELECT status,refund_applied FROM idempotency_requests "
                "WHERE user_id=? AND status='failed'",
                ("u-generate-stream",),
            )
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["refund_applied"], 1)
        finally:
            api._generate_pipeline_stream = original_pipeline
            api._maybe_enrich_facts = original_facts
            api._compute_market_timing_for_delivery = original_timing
            api._billing.check_and_deduct = original_check

    def test_headerless_entry_points_remain_compatible_and_chat_fast_ignores_key(self):
        self._create_user("u-headerless")
        original_pipeline = api._run_analyze_pipeline
        original_check = api._billing.check_and_deduct
        original_sessions = dict(api._chat_sessions)
        original_generator = api._chat_sse_generator
        original_thinking = api._should_use_thinking
        original_agents = api._run_generation_agents
        original_facts = api._maybe_enrich_facts
        original_timing = api._compute_market_timing_for_delivery
        calls = []

        async def fake_pipeline(_req, _user, **kwargs):
            calls.append(("analyze", kwargs.get("billing_managed")))
            return "headerless-ok"

        async def fake_chat_stream(*_args, **_kwargs):
            calls.append(("chat-stream", False))
            yield 'data: {"type":"done"}\n\n'

        async def fake_agents(**_kwargs):
            calls.append(("generate-agents", False))
            return {
                "title": "标题",
                "body": "正文",
                "ces_percentile": 75.0,
                "grade": "良好",
            }

        async def no_facts(*_args, **_kwargs):
            return {}

        async def consume_response(response):
            return [chunk async for chunk in response.body_iterator]

        api._run_analyze_pipeline = fake_pipeline
        api._billing.check_and_deduct = lambda user_id, op: calls.append((op, "legacy-charge")) or {"usage_id": "legacy"}
        api._chat_sse_generator = fake_chat_stream
        api._run_generation_agents = fake_agents
        api._maybe_enrich_facts = no_facts
        api._compute_market_timing_for_delivery = lambda *_args, **_kwargs: None
        api._chat_sessions.clear()
        api._chat_sessions["headerless-chat"] = {
            "user_id": "u-headerless", "messages": [], "domain": "美食",
        }
        try:
            result = asyncio.run(api.analyze(
                api.AnalyzeInput(note_title="标题", desc="正文", domain="美食"),
                user={"id": "u-headerless"},
            ))
            self.assertEqual(result, "headerless-ok")
            self.assertIn(("analyze", False), calls)

            generated = asyncio.run(api.generate(
                api.GenerateInput(domain="美食", brief="简报"),
                user={"id": "u-headerless"},
            ))
            self.assertEqual(generated.note_title, "标题")
            self.assertIn(("generate", "legacy-charge"), calls)
            self.assertIn(("generate-agents", False), calls)

            api._should_use_thinking = lambda _message: True
            paid_response = asyncio.run(api.chat_message(
                api.ChatMessageInput(session_id="headerless-chat", message="重写"),
                user={"id": "u-headerless"},
            ))
            asyncio.run(consume_response(paid_response))
            self.assertIn(("chat_rewrite", "legacy-charge"), calls)

            api._should_use_thinking = lambda _message: False
            fast_response = asyncio.run(api.chat_message(
                api.ChatMessageInput(session_id="headerless-chat", message="你好"),
                user={"id": "u-headerless"},
                request_id="ignored-fast-key",
            ))
            asyncio.run(consume_response(fast_response))
            self.assertEqual(
                db.fetchone("SELECT COUNT(*) AS c FROM idempotency_requests")["c"],
                0,
            )
        finally:
            api._run_analyze_pipeline = original_pipeline
            api._billing.check_and_deduct = original_check
            api._chat_sse_generator = original_generator
            api._should_use_thinking = original_thinking
            api._run_generation_agents = original_agents
            api._maybe_enrich_facts = original_facts
            api._compute_market_timing_for_delivery = original_timing
            api._chat_sessions.clear()
            api._chat_sessions.update(original_sessions)

    def test_request_id_validation_and_payload_hash_are_stable(self):
        self.assertEqual(
            idempotency.payload_hash({"b": 2, "a": 1}),
            idempotency.payload_hash({"a": 1, "b": 2}),
        )
        self._create_user("u-long-key")
        with self.assertRaises(HTTPException) as invalid:
            api._paid_request_claim(
                "x" * 513,
                user_id="u-long-key",
                operation="analyze",
                payload=api.AnalyzeInput(note_title="标题", desc="正文"),
            )
        self.assertEqual(invalid.exception.status_code, 400)
        self.assertEqual(invalid.exception.detail["code"], "INVALID_REQUEST_ID")

    def test_sse_success_error_incomplete_and_cancel_finalize_once(self):
        self._create_user("u-streams")

        async def success_stream():
            yield 'data: {"type":"complete"}\n\n'

        async def error_stream():
            yield 'data: {"type":"error"}\n\n'

        async def incomplete_stream():
            yield 'data: {"type":"stage"}\n\n'

        async def cancelled_stream():
            raise asyncio.CancelledError()
            yield ""

        async def consume(stream):
            return [chunk async for chunk in stream]

        success = self._claim("u-streams", "stream-success")
        asyncio.run(consume(api._idempotent_sse_stream(
            success_stream(), success, success_types={"complete"}
        )))
        self.assertEqual(
            db.fetchone("SELECT status FROM idempotency_requests WHERE id=?", (success["request_id"],))["status"],
            "completed",
        )

        for key, stream, expected_code in (
            ("stream-error", error_stream(), "stream_failed"),
            ("stream-incomplete", incomplete_stream(), "stream_incomplete"),
        ):
            claim = self._claim("u-streams", key)
            asyncio.run(consume(api._idempotent_sse_stream(
                stream, claim, success_types={"complete"}
            )))
            row = db.fetchone(
                "SELECT status,refund_applied,failure_code FROM idempotency_requests WHERE id=?",
                (claim["request_id"],),
            )
            self.assertEqual(row["status"], "failed")
            self.assertEqual(row["refund_applied"], 1)
            self.assertEqual(row["failure_code"], expected_code)

        cancelled = self._claim("u-streams", "stream-cancelled")
        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(consume(api._idempotent_sse_stream(
                cancelled_stream(), cancelled, success_types={"complete"}
            )))
        cancelled_row = db.fetchone(
            "SELECT status,refund_applied,failure_code FROM idempotency_requests WHERE id=?",
            (cancelled["request_id"],),
        )
        self.assertEqual(cancelled_row["status"], "failed")
        self.assertEqual(cancelled_row["refund_applied"], 1)
        self.assertEqual(cancelled_row["failure_code"], "stream_cancelled")

    def test_sse_consumer_aclose_marks_stream_cancelled_and_refunds(self):
        self._create_user("u-aclose")
        claim = self._claim("u-aclose", "consumer-aclose")

        async def source():
            yield 'data: {"type":"stage"}\n\n'
            await asyncio.Event().wait()

        async def consume_then_close():
            wrapped = api._idempotent_sse_stream(
                source(), claim, success_types={"complete"}
            )
            first = await anext(wrapped)
            self.assertIn("stage", first)
            await wrapped.aclose()

        asyncio.run(consume_then_close())
        row = db.fetchone(
            "SELECT status,refund_applied,failure_code FROM idempotency_requests WHERE id=?",
            (claim["request_id"],),
        )
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["refund_applied"], 1)
        self.assertEqual(row["failure_code"], "stream_cancelled")


if __name__ == "__main__":
    unittest.main()
