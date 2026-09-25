"""Isolated main-operation credit contract; no provider calls or paid orders."""
import asyncio
import importlib
import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
db = importlib.import_module("db")
billing = importlib.import_module("billing")
idempotency = importlib.import_module("idempotency")
api = importlib.import_module("api")


class VideoCreditConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.previous_db = db._DB_PATH
        self.temp = tempfile.TemporaryDirectory()
        db._DB_PATH = Path(self.temp.name) / "credits.db"
        db.init_db()
        billing.clear_active_usage()
        self.user = {"id": "synthetic-video-user"}
        db.execute("INSERT INTO users(id,username,email,password_hash,password_salt,created_at) VALUES(?,?,?,?,?,?)",
                   (self.user["id"], "synthetic-video", "synthetic@example.invalid", "hash", "salt", billing._now()))

    def tearDown(self):
        billing.clear_active_usage()
        db._DB_PATH = self.previous_db
        self.temp.cleanup()

    def claim(self, key="original-key", operation="generate", version=None, video=True):
        return idempotency.claim_and_charge(user_id=self.user["id"], operation=operation,
            request_id=key, payload={"video_file_id": "synthetic-video" if video else None},
            quote_version=version)

    def spendable(self):
        return billing.get_quota_status(self.user["id"])["total_available_credits"]

    def test_quote_tiers_charge_receipt_and_usage_share_nondefault_server_price(self):
        with mock.patch.dict(billing.OPERATIONS, {"analyze": {**billing.OPERATIONS["analyze"], "credits": 7}}):
            quote = asyncio.run(api.billing_quote("analyze", True, self.user))
            tiers = asyncio.run(api.billing_tiers())
            claim = self.claim(operation="analyze", version=quote["quote_version"])
            receipt = billing.get_charge_receipt(self.user["id"], "analyze", claim["charge"], claim["request_id"])
            usage = billing.get_usage_summary(self.user["id"])["recent_records"][0]
            self.assertEqual([quote["credits"], tiers["credit_costs"]["analyze"], receipt["credits_used"], usage["credits_used"]], [7] * 4)
            self.assertEqual(quote["video_credits"], 0)
            self.assertEqual(tiers["operation_costs"]["video_analyze"]["included_in"], ["analyze", "generate"])
            self.assertEqual(usage["usage_id"], receipt["usage_id"])
            self.assertEqual(usage["request_id"], claim["request_id"])
            self.assertEqual((receipt["monthly_credits_used"], receipt["wallet_credits_used"]), (7, 0))

    def test_quote_has_no_charge_or_usage(self):
        quote = billing.get_operation_quote(self.user["id"], "generate", has_video=True)
        self.assertEqual(quote["credits"], 8)
        self.assertTrue(quote["can_afford"])
        self.assertEqual(db.fetchone("SELECT COUNT(*) n FROM usage_records")["n"], 0)
        self.assertEqual(self.spendable(), 12)

    def test_quote_change_blocks_new_charge_but_original_key_is_resolved(self):
        version = billing.billing_quote_version()
        original = self.claim(version=version)
        with mock.patch.dict(billing.OPERATIONS, {"generate": {**billing.OPERATIONS["generate"], "credits": 9}}):
            self.assertEqual(self.claim(version=version)["state"], "in_progress")
            with self.assertRaises(HTTPException) as stale:
                self.claim(key="new-key", version=version)
            self.assertEqual(stale.exception.detail["code"], "BILLING_QUOTE_CHANGED")
        self.assertEqual(self.spendable(), 4)
        self.assertEqual(db.fetchone("SELECT COUNT(*) n FROM idempotency_requests")["n"], 1)
        self.assertEqual(original["charge"]["credits_used"], 8)

    def test_insufficient_balance_rolls_back_claim_charge_and_usage(self):
        self.claim()
        with self.assertRaises(HTTPException) as denied:
            self.claim(key="insufficient")
        self.assertEqual(denied.exception.status_code, 402)
        self.assertEqual(self.spendable(), 4)
        self.assertEqual(db.fetchone("SELECT COUNT(*) n FROM usage_records")["n"], 1)
        self.assertEqual(db.fetchone("SELECT COUNT(*) n FROM idempotency_requests")["n"], 1)

    def test_concurrent_duplicate_video_submissions_charge_once(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.claim(), range(6)))
        self.assertEqual(sum(result["state"] == "owner" for result in results), 1)
        self.assertEqual(self.spendable(), 4)
        self.assertEqual(db.fetchone("SELECT COUNT(*) n FROM usage_records")["n"], 1)

    def test_mixed_charge_refund_and_retry_reconcile_original_sources(self):
        billing.get_subscription(self.user["id"])
        db.execute("UPDATE subscriptions SET used_monthly_credits=9 WHERE user_id=?", (self.user["id"],))
        billing.grant_credits(self.user["id"], 10, "synthetic fixture")
        claim = self.claim()
        self.assertEqual((claim["charge"]["monthly_credits_used"], claim["charge"]["wallet_credits_used"]), (3, 5))
        self.assertTrue(idempotency.mark_failed_and_refund(claim))
        self.assertFalse(idempotency.mark_failed_and_refund(claim))
        self.assertEqual(self.spendable(), 13)
        refunded = billing.get_charge_receipt(self.user["id"], "generate", claim["charge"])
        self.assertEqual((refunded["status"], refunded["credits_used"], refunded["refunded_credits"]), ("refunded", 0, 8))
        self.assertEqual(self.claim()["state"], "failed")
        self.assertEqual(self.claim(key="new-confirmed-retry")["charge"]["credits_used"], 8)
        amounts = [row["amount"] for row in db.fetchall("SELECT amount FROM credit_transactions WHERE type IN ('usage','refund') ORDER BY recorded_at")]
        self.assertEqual(amounts, [-5, 5, -5])

    def test_headerless_duplicate_refund_is_at_most_once(self):
        billing.get_subscription(self.user["id"])
        db.execute("UPDATE subscriptions SET used_monthly_credits=12 WHERE user_id=?", (self.user["id"],))
        billing.grant_credits(self.user["id"], 10, "synthetic fixture")
        charge = billing.check_and_deduct(self.user["id"], "generate")
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: billing.refund_operation_charge(self.user["id"], "generate", charge, "synthetic failure"), range(4)))
        self.assertEqual(self.spendable(), 10)
        self.assertEqual(db.fetchone("SELECT COUNT(*) n FROM credit_transactions WHERE type='refund'")["n"], 1)

    def add_unknown_call(self, charge):
        db.execute("INSERT INTO public_trial_calls(id,budget_id,user_id,request_hash,state,reserve_milli_cny,created_at,usage_record_id) VALUES(?,?,?,?,?,?,?,?)",
            ("synthetic-call", "website-free-product-20260912", self.user["id"], "synthetic-hash", "unknown", 1, billing._now(), charge["usage_id"]))

    def test_unknown_supplier_call_keeps_its_cost_but_failed_delivery_refunds_customer(self):
        claim = self.claim()
        self.add_unknown_call(claim["charge"])
        self.assertTrue(idempotency.mark_failed_and_refund(claim, failure_code="stream_failed"))
        self.assertFalse(idempotency.mark_failed_and_refund(claim, failure_code="stream_failed"))
        self.assertEqual(self.claim()["state"], "failed")
        self.assertEqual(self.spendable(), 12)
        self.assertEqual(db.fetchone("SELECT source FROM usage_records WHERE id=?", (claim["charge"]["usage_id"],))["source"], "refunded")
        self.assertEqual(db.fetchone("SELECT state FROM public_trial_calls WHERE id='synthetic-call'")["state"], "unknown")

    def test_keyed_error_event_preserves_failure_and_receipt_when_supplier_is_unknown(self):
        claim = self.claim()
        self.add_unknown_call(claim["charge"])
        async def run():
            async def source():
                yield 'data: {"type":"error","error_code":"video_understanding_failed","message":"视频理解未完成"}\n\n'
            stream = api._idempotent_sse_stream(source(), claim, success_types={"complete"})
            return [json.loads(chunk.removeprefix("data: ").strip()) async for chunk in
                    api._timed_sse_stream(stream, operation="generate", success_types={"complete"})]
        event = asyncio.run(run())[-1]
        self.assertEqual(event["error_code"], "video_understanding_failed")
        self.assertEqual(event["billing"]["status"], "refunded")
        self.assertEqual(self.spendable(), 12)
        self.assertEqual(db.fetchone("SELECT state FROM public_trial_calls WHERE id='synthetic-call'")["state"], "unknown")

    async def consume_generate(self, events, request_id=None):
        async def pipeline(**kwargs):
            for event in events:
                if isinstance(event, BaseException):
                    raise event
                yield event
        async def no_facts(*args, **kwargs):
            return {}
        with mock.patch.object(api, "_generate_pipeline_stream", pipeline), \
             mock.patch.object(api, "_maybe_enrich_facts", no_facts), \
             mock.patch.object(api, "_compute_market_timing_for_delivery", return_value=None):
            response = await api.generate_stream_endpoint(api.GenerateInput(brief="synthetic", video_file_id="synthetic-video"), self.user, request_id)
            return [json.loads(chunk.removeprefix("data: ").strip()) async for chunk in response.body_iterator]

    def test_headerless_stream_success_exposes_real_receipt(self):
        events = asyncio.run(self.consume_generate([{"type": "complete", "quality_issues": []}]))
        self.assertEqual(events[-1]["billing"]["credits_used"], 8)
        self.assertEqual(self.spendable(), 4)

    def test_headerless_stream_errors_timeouts_and_incomplete_stream_refund(self):
        for failure in [[{"type": "error", "message": "synthetic failure"}], [asyncio.TimeoutError()], []]:
            with self.subTest(failure=str(failure)):
                events = asyncio.run(self.consume_generate(failure))
                self.assertEqual(events[-1]["type"], "error")
                self.assertEqual(self.spendable(), 12)
        self.assertEqual(db.fetchone("SELECT COUNT(*) n FROM usage_records WHERE source='refunded'")["n"], 3)

    def test_keyed_stream_receipt_matches_ledger(self):
        events = asyncio.run(self.consume_generate([{"type": "complete", "quality_issues": []}], "keyed-success"))
        receipt = events[-1]["billing"]
        row = billing.get_usage_summary(self.user["id"])["recent_records"][0]
        self.assertEqual(receipt["request_id"], row["request_id"])
        self.assertEqual(receipt["credits_used"], row["credits_used"])
        self.assertEqual(row["status"], "completed")

    def test_headerless_json_failure_and_response_validation_failure_refund(self):
        async def no_facts(*args, **kwargs):
            return {}
        for result in [asyncio.TimeoutError(), {"quality_issues": [], "ces_percentile": 70, "grade": "良好"}]:
            async def agents(**kwargs):
                if isinstance(result, BaseException):
                    raise result
                return result
            with mock.patch.object(api, "_run_generation_agents", agents), \
                 mock.patch.object(api, "_maybe_enrich_facts", no_facts), \
                 mock.patch.object(api, "_compute_market_timing_for_delivery", return_value=None):
                with self.assertRaises((HTTPException, KeyError)):
                    asyncio.run(api.generate(api.GenerateInput(brief="synthetic"), self.user))
            self.assertEqual(self.spendable(), 12)

    def test_json_generate_model_keeps_charge_receipt(self):
        async def agents(**kwargs):
            return {"title": "synthetic", "body": "synthetic body", "quality_issues": [], "ces_percentile": 70, "grade": "良好"}
        async def no_facts(*args, **kwargs):
            return {}
        with mock.patch.object(api, "_run_generation_agents", agents), \
             mock.patch.object(api, "_maybe_enrich_facts", no_facts), \
             mock.patch.object(api, "_compute_market_timing_for_delivery", return_value=None):
            response = asyncio.run(api.generate(api.GenerateInput(brief="synthetic"), self.user))
        self.assertEqual(response.model_dump()["billing"]["credits_used"], 8)
        self.assertIn("billing", api.AnalyzeResponse.model_fields)

    def test_public_http_quote_authentication_stale_price_and_no_key_boundary(self):
        from fastapi.testclient import TestClient
        import public_account
        env = {"NOTEAI_PUBLIC_PRODUCT": "1", "NOTEAI_PUBLIC_ACCOUNT_ONLY": "0",
               "NOTEAI_PUBLIC_ORIGINS": "https://noteaipro.com", "NOTEAI_MODEL_CONFIG_ENABLED": "0"}
        with mock.patch.dict(os.environ, env):
            user = api._auth.create_user("http-quote-user", "SyntheticOnlyPassword42!",
                phone="+8613800138999", phone_verified=True,
                contract_version=public_account.PRODUCT_CONTRACT_VERSION, privacy_accepted=True)
            client = TestClient(api.app, headers={"Origin": "https://noteaipro.com",
                "Authorization": "Bearer " + api._auth.create_token(user["id"])})
            denied = TestClient(api.app).get("/billing/quote?operation=generate&has_video=true")
            self.assertEqual(denied.status_code, 401)
            response = client.get("/billing/quote?operation=generate&has_video=true")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["credits"], 8)
            self.assertEqual(client.post("/generate/stream", json={"brief": "synthetic"}).status_code, 400)
            self.assertEqual(client.post("/generate", json={"brief": "synthetic"}).status_code, 404)
            stale = client.post("/generate/stream", json={"brief": "synthetic"},
                headers={"X-Request-ID": "new-price-request", "X-Billing-Quote-Version": "outdated"})
            self.assertEqual(stale.status_code, 409, stale.text)
            self.assertEqual(stale.json()["detail"]["code"], "BILLING_QUOTE_CHANGED")
            self.assertEqual(db.fetchone("SELECT COUNT(*) n FROM usage_records")["n"], 0)
            self.assertEqual(db.fetchone("SELECT COUNT(*) n FROM idempotency_requests")["n"], 0)
        # Local/cross-origin deployments without the same-origin public proxy.
        cors = TestClient(api.app).options("/generate/stream", headers={
            "Origin": "https://noteaipro.com", "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,x-request-id,x-billing-quote-version"})
        self.assertEqual(cors.status_code, 200)
        self.assertIn("X-Billing-Quote-Version", cors.headers["access-control-allow-headers"])

    def test_headerless_analyze_auxiliary_record_failure_restores_primary_charge(self):
        request = api.AnalyzeInput(note_title="synthetic", desc="synthetic body", video_file_id="synthetic-video")
        async def stream():
            response = await api.analyze_stream_endpoint(request, self.user)
            return [json.loads(chunk.removeprefix("data: ").strip()) async for chunk in response.body_iterator]
        with mock.patch.object(billing, "record_auxiliary_usage", side_effect=RuntimeError("synthetic pre-pipeline failure")):
            with self.assertRaises(RuntimeError):
                asyncio.run(api.analyze(request, self.user))
            self.assertEqual(self.spendable(), 12)
            events = asyncio.run(stream())
            self.assertEqual(events[-1]["billing"]["status"], "refunded")
            self.assertEqual(self.spendable(), 12)
        self.assertEqual(db.fetchone("SELECT COUNT(*) n FROM usage_records WHERE source='refunded'")["n"], 2)

    def test_nginx_quote_allowlist_preserves_topup_exclusion(self):
        import re
        root = Path(__file__).resolve().parents[1]
        config = (root / "deploy/production/public-account.locations.conf").read_text()
        route = next(line.split("~", 1)[1].rsplit("{", 1)[0].strip() for line in config.splitlines()
                     if line.startswith("location ~ ") and "billing/" in line)
        self.assertIsNotNone(re.fullmatch(route, "/billing/quote"))
        self.assertIsNone(re.fullmatch(route, "/billing/topup"))
        self.assertIsNone(re.fullmatch(route, "/billing/upgrade"))

    def test_report_sanitizer_preserves_safe_receipt_and_original_diagnosis(self):
        claim = self.claim(operation="analyze")
        receipt = billing.get_charge_receipt(self.user["id"], "analyze", claim["charge"], claim["request_id"])
        original = {"ai_diagnosis": "synthetic diagnosis", "video_analysis": "synthetic video observation", "billing": receipt}
        persisted = api._sanitize_persisted_diagnosis(original)
        self.assertEqual(persisted, original)
        self.assertEqual(api._sanitize_persisted_diagnosis(json.loads(json.dumps(persisted))), original)
        import uuid
        diagnosis_id = str(uuid.uuid4())
        now = billing._now()
        api._insert_content_with_retention(
            "INSERT INTO saved_diagnoses(id,user_id,note_title,domain,ces_percentile,composite_score,grade,diagnosis_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (diagnosis_id, self.user["id"], "synthetic", "美食", 70, 70, "良好", json.dumps(persisted), now),
            "diagnosis", diagnosis_id, self.user["id"], created_at=now)
        reopened = asyncio.run(api.get_diagnosis(diagnosis_id, self.user))
        self.assertEqual({key: reopened[key] for key in original}, original)
        self.assertEqual(api._generation_report_result({**original, "note_title": "synthetic", "note_body": "synthetic"})["billing"], receipt)
        unsafe = {**original, "billing": {**receipt, "raw_provider_response": "private"}}
        self.assertNotIn("billing", api._sanitize_persisted_diagnosis(unsafe))
        self.assertEqual(api._sanitize_persisted_diagnosis(unsafe)["ai_diagnosis"], original["ai_diagnosis"])

    def test_unknown_sse_exposes_unconfirmed_without_refund_receipt(self):
        charge = billing.check_and_deduct(self.user["id"], "generate")
        self.add_unknown_call(charge)
        async def run():
            async def source():
                yield 'data: {"type":"error","message":"synthetic"}\n\n'
            wrapped = api._idempotent_sse_stream(source(), None, success_types={"complete"},
                unkeyed_charge=charge, user_id=self.user["id"], operation="generate")
            return [json.loads(chunk.removeprefix("data: ").strip()) async for chunk in
                api._timed_sse_stream(wrapped, operation="generate", success_types={"complete"})]
        event = asyncio.run(run())[-1]
        self.assertEqual(event["error_code"], "BILLING_OUTCOME_UNCONFIRMED")
        self.assertEqual(event["billing"], {"status": "unconfirmed"})
        self.assertEqual(self.spendable(), 4)

    def test_headerless_stream_closed_before_result_refunds_once(self):
        charge = billing.check_and_deduct(self.user["id"], "generate")
        async def run():
            async def source():
                yield 'data: {"type":"stage"}\n\n'
                yield 'data: {"type":"complete"}\n\n'
            stream = api._idempotent_sse_stream(source(), None, success_types={"complete"},
                unkeyed_charge=charge, user_id=self.user["id"], operation="generate")
            await anext(stream)
            await stream.aclose()
        asyncio.run(run())
        self.assertEqual(self.spendable(), 12)
        self.assertEqual(billing.get_charge_receipt(self.user["id"], "generate", charge)["status"], "refunded")

    def test_quote_header_is_allowed_by_cors(self):
        cors = next(middleware for middleware in api.app.user_middleware if middleware.cls.__name__ == "CORSMiddleware")
        self.assertIn("X-Billing-Quote-Version", cors.kwargs["allow_headers"])


if __name__ == "__main__":
    unittest.main()
