import asyncio
import importlib
import inspect
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
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

    def _waiting_task(self, uid="merchant-a", key="clarification-test-key"):
        import task_clarification as clarification
        self._create_user(uid)
        claim = self._claim(uid, key, operation="generate")
        source = "蓝猫店双人套餐198元，门票另有组合，9月活动。"
        opinion = {"role": "内容专家", "raw": '<clarifications>' + json.dumps([{
            "field": "package_inclusions", "question": "198元的双人套餐包含门票吗？",
            "source_quote": "双人套餐198元，门票另有组合", "object": "双人套餐",
            "time_range": "9月", "required": True, "options": ["包含", "不包含"]}], ensure_ascii=False) + '</clarifications>'}
        marker = clarification.execution.set({"claim": claim})
        try:
            with self.assertRaises(clarification.WaitingForInput) as waiting:
                clarification.pause({"domain": "美食", "local_time": "", "image_desc": "原图片完整观察"},
                    [opinion], source=source, merchant="蓝猫店", completed_steps=["素材理解"])
        finally:
            clarification.execution.reset(marker)
        return claim, waiting.exception.event, opinion, source

    def test_clarification_json_wrappers_keep_source_checks_and_hide_private_logs(self):
        import task_clarification as clarification
        import io
        from contextlib import redirect_stderr
        source = "蓝猫店9月双人套餐198元，饮品另有口径。"
        item = {"field": "drink_inclusion", "question": "这个双人套餐是否包含饮品？",
                "source_quote": "饮品另有口径", "object": "双人套餐", "time_range": "9月"}
        outputs = []
        log = io.StringIO()
        marker = clarification.execution.set({"claim": "synthetic-only"})
        try:
            with redirect_stderr(log):
                for payload in ([item], {"questions": [item]}, {"clarifications": [item]}):
                    raw = '<clarifications>```json\n' + json.dumps(payload, ensure_ascii=False) + '\n```</clarifications>'
                    outputs.append(clarification.questions_from_opinions(
                        [{"role": "内容专家", "raw": raw}], source, "蓝猫店"))
                # A whole JSON response can be recovered without interpreting
                # arbitrary prose as a question or relaxing source ownership.
                for raw in (json.dumps([item]), '```json\n' + json.dumps({"questions": [item]}) + '\n```'):
                    outputs.append(clarification.questions_from_opinions(
                        [{"role": "内容专家", "raw": raw}], source, "蓝猫店"))
                invalid = {**item, "source_quote": "不存在的另一商家套餐"}
                rejected = clarification.questions_from_opinions([{"role": "内容专家",
                    "raw": '<clarifications>' + json.dumps([invalid]) + '</clarifications>'}], source, "蓝猫店")
        finally:
            clarification.execution.reset(marker)
        self.assertTrue(all(output == outputs[0] for output in outputs))
        self.assertEqual(len(outputs[0]), 1)
        self.assertEqual(rejected, [])
        self.assertIn('source_quote_mismatch', log.getvalue())
        for private in (source, item['question'], item['source_quote'], '蓝猫店'):
            self.assertNotIn(private, log.getvalue())

    def test_clarification_source_reference_resolves_original_and_scopes_time(self):
        import task_clarification as clarification
        source = "蓝猫店9月双人套餐198元，茶饮两杯。\n蓝猫店10月双人套餐198元，茶饮另点。"
        marker = clarification.execution.set({"claim": {"request_id": "task-a"}, "merchant": "蓝猫店"})
        try:
            index, references = clarification.source_references(source)
            items = [{"field": "drink_inclusion", "question": "这个双人套餐是否包含茶饮？",
                      "source_id": ref, "source_quote": "模型概述不能代替原文", "object": "双人套餐",
                      "time_range": "9月" if "9月" in value else "10月"}
                     for ref, value in references.items()]
            opinion = {"role": "内容专家", "clarification_sources": references,
                       "raw": '<clarifications>' + json.dumps(items) + '</clarifications>'}
            questions = clarification.questions_from_opinions([opinion], source, "蓝猫店")
            self.assertEqual(len(questions), 2)
            self.assertNotEqual(questions[0]['question_id'], questions[1]['question_id'])
            self.assertEqual([q['source_quote'] for q in questions], list(references.values()))
            self.assertEqual(clarification.questions_from_opinions([opinion], source, "蓝猫店", questions), [])
            # A real reference from another operation cannot resolve in this map.
            other_marker = clarification.execution.set({"claim": {"request_id": "task-b"}, "merchant": "红猫店"})
            try:
                _, other = clarification.source_references(source)
            finally:
                clarification.execution.reset(other_marker)
            self.assertTrue(set(references).isdisjoint(other))
            self.assertEqual(clarification.questions_from_opinions(
                [{**opinion, 'clarification_sources': other}], source, "红猫店"), [])
            self.assertEqual(clarification.questions_from_opinions([opinion], "其他商家套餐", "红猫店"), [])
            self.assertTrue(all(ref in index for ref in references))
        finally:
            clarification.execution.reset(marker)

    def test_clarification_conflict_preserves_both_exact_source_references(self):
        import task_clarification as clarification
        source = "9月蓝猫店双人套餐198元，茶饮两杯。\n9月蓝猫店双人套餐198元，茶饮另点。"
        marker = clarification.execution.set({"claim": {"request_id": "conflict-task"}, "merchant": "蓝猫店"})
        try:
            _, refs = clarification.source_references(source)
            keys = list(refs)
            item = {"field": "drink_inclusion", "question": "198元套餐是否包含两杯茶饮？",
                    "object": "双人套餐198元", "time_range": "9月", "required": True}
            def parse(reference):
                return clarification.questions_from_opinions([{"role": "内容专家",
                    "clarification_sources": refs, "raw": '<clarifications>' +
                    json.dumps([{**item, **reference}]) + '</clarifications>'}], source, "蓝猫店")
            legacy = parse({"source_id": ", ".join(keys)})
            current = parse({"source_ids": keys})
            self.assertEqual(legacy, current)
            self.assertEqual(len(current), 1)
            self.assertEqual(current[0]['source_quotes'], list(refs.values()))
            # Existing single-source question identities do not change.
            self.assertEqual(current[0]['question_id'], parse({"source_id": keys[0]})[0]['question_id'])
            self.assertEqual(parse({"source_ids": [keys[0], "s_foreign"]}), [])
            self.assertEqual(parse({"source_id": keys[0] + ", s_foreign"}), [])
            self.assertEqual(parse({"source_ids": []}), [])
        finally:
            clarification.execution.reset(marker)

    def test_clarification_resume_concurrent_answers_keep_original_charge(self):
        import task_clarification as clarification
        claim, event, _, _ = self._waiting_task()
        answers = [{"question_id": event["questions"][0]["question_id"], "status": "confirmed", "answer": "9月双人套餐不含门票，门票另购；只适用于蓝猫店。"}]
        def run(_):
            try:
                return clarification.resume("merchant-a", claim["request_id"], 1, answers)
            except HTTPException as exc:
                return exc.status_code
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(run, range(8)))
        owners = [r for r in results if isinstance(r, tuple)]
        self.assertEqual(len(owners), 1)
        self.assertEqual(results.count(409), 7)
        next_claim, task = owners[0]
        self.assertEqual(next_claim["charge"]["usage_id"], claim["charge"]["usage_id"])
        self.assertEqual(db.fetchone("SELECT COUNT(*) n FROM usage_records")["n"], 1)
        self.assertEqual(db.fetchone("SELECT COUNT(*) n FROM idempotency_requests")["n"], 1)
        self.assertFalse(idempotency.mark_completed(claim))
        self.assertFalse(idempotency.mark_failed_and_refund(claim))
        clarification.save_result(next_claim, {"note_title": "真实剩余内容", "note_body": "不含门票", "ces_percentile": 72})
        self.assertTrue(idempotency.mark_completed(next_claim, confirm_existing=True))
        recovered = clarification.read("merchant-a", claim["request_id"])
        self.assertEqual(recovered["status"], "completed")
        self.assertEqual(recovered["answers"][0]["source"], "merchant_confirmation")
        self.assertNotIn("prepared", recovered)
        self.assertNotIn("lease_token", recovered)

    def test_clarification_saved_result_obeys_original_note_deletion_and_atomicity(self):
        from unittest import mock
        import task_clarification as clarification
        claim, event, _, _ = self._waiting_task()
        resumed, task = clarification.resume("merchant-a", claim["request_id"], 1,
            [{"question_id": event["questions"][0]["question_id"], "status": "omitted"}])
        result = {"note_title":"原任务结果", "note_body":"只写明确的内容。", "ces_percentile":72}
        with mock.patch.object(clarification.content_retention, "_record_content_with_storage", side_effect=RuntimeError("synthetic storage failure")):
            with self.assertRaises(RuntimeError): clarification.save_result(resumed, dict(result))
        self.assertEqual(db.fetchone("SELECT COUNT(*) n FROM notes")["n"], 0)
        self.assertEqual(clarification.read("merchant-a", claim["request_id"])["status"], "running")
        clarification.save_result(resumed, dict(result))
        session = db.fetchone("SELECT note_id FROM chat_sessions WHERE id=?", (claim["request_id"],))
        self.assertEqual(session["note_id"], claim["request_id"])
        db.execute("UPDATE content_retention SET deleted_at=? WHERE content_id=?", (idempotency._iso(), claim["request_id"]))
        with self.assertRaises(HTTPException) as deleted:
            clarification.read("merchant-a", claim["request_id"])
        self.assertEqual(deleted.exception.status_code, 404)

    def test_clarification_no_duplicate_questions_or_cross_merchant_access(self):
        import task_clarification as clarification
        claim, event, opinion, source = self._waiting_task()
        answers = [{"question_id": event["questions"][0]["question_id"], "status": "omitted"}]
        next_claim, task = clarification.resume("merchant-a", claim["request_id"], 1, answers)
        self.assertEqual(clarification.questions_from_opinions([opinion], source, "蓝猫店", task["answers"]), [])
        self.assertIn("所有标题、方案", clarification.answer_context(task))
        self.assertEqual(clarification.pending_confirmation(task), [])
        self._create_user("merchant-b")
        with self.assertRaises(HTTPException) as denied:
            clarification.read("merchant-b", claim["request_id"])
        self.assertEqual(denied.exception.status_code, 404)
        with self.assertRaises(HTTPException):
            clarification.resume("merchant-b", claim["request_id"], 1, answers)
        self.assertEqual(len(clarification.questions_from_opinions([opinion], source, "另一门店", task["answers"])), 1)

    def test_clarification_free_answer_is_not_truncated_unknown_core_stays_pending(self):
        import task_clarification as clarification
        claim, event, _, _ = self._waiting_task()
        question = event["questions"][0]
        task = {"questions": [question], "answers": [], "version": 1}
        text = "具体说明：" + "只适用于本门店本月活动，不含其它套餐。" * 40
        answer = clarification._answer_update(task, [{"question_id": question["question_id"], "status": "confirmed", "answer": text}])
        task["answers"].extend(answer)
        self.assertIn(text, clarification.answer_context(task))
        task["version"] = 2
        task["answers"].extend(clarification._answer_update(task, [{"question_id": question["question_id"], "status": "unknown"}]))
        self.assertNotIn(text, clarification.answer_context(task))
        self.assertEqual(clarification.pending_confirmation(task), [question["question"]])
        task["version"] = 3
        correction = "更正：只在9月周末有效，不含门票。"
        task["answers"].extend(clarification._answer_update(task, [{"question_id": question["question_id"], "status": "confirmed", "answer": correction}]))
        self.assertIn(correction, clarification.answer_context(task))
        self.assertNotIn(text, clarification.answer_context(task))
        self.assertEqual(len(task["answers"]), 3)  # immutable prior answers stay private history

    def test_clarification_waiting_stream_is_not_failure_or_complete(self):
        import task_clarification as clarification
        claim, event, _, _ = self._waiting_task()
        async def stream():
            yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
        async def collect():
            return [chunk async for chunk in api._timed_sse_stream(
                api._idempotent_sse_stream(stream(), claim, success_types={"complete"}),
                operation="generate", success_types={"complete"})]
        chunks = asyncio.run(collect())
        result = json.loads(chunks[0][6:])
        self.assertTrue(result["terminal"])
        self.assertEqual(result["outcome"], "awaiting_input")
        row = db.fetchone("SELECT * FROM idempotency_requests WHERE id=?", (claim["request_id"],))
        self.assertEqual((row["status"], row["complete_applied"], row["refund_applied"]), ("waiting_for_input", 0, 0))
        self.assertEqual(self._claim("merchant-a", "clarification-test-key", operation="generate")["session_id"], claim["request_id"])

    def test_clarification_unknown_original_call_blocks_resume_and_account_deletion(self):
        import task_clarification as clarification
        claim, event, _, _ = self._waiting_task()
        db.execute("INSERT INTO public_trial_calls(id,budget_id,user_id,request_hash,state,reserve_milli_cny,created_at,usage_record_id) VALUES(?,?,?,?,?,?,?,?)",
                   ("unknown-call", "website-free-product-20260912", "merchant-a", "a"*64, "unknown", 1, "2026-09-14", claim["charge"]["usage_id"]))
        with self.assertRaises(HTTPException):
            clarification.resume("merchant-a", claim["request_id"], 1, [{"question_id": event["questions"][0]["question_id"], "status": "omitted"}])
        with self.assertRaises(ValueError):
            with db.transaction(write=True) as tx:
                idempotency.settle_expired_requests_for_account_deletion_with_storage(tx, "merchant-a")
        self.assertEqual(clarification.read("merchant-a", claim["request_id"])["status"], "waiting_for_input")

    def test_clarification_account_deletion_cancels_waiting_once_without_expiring_lease(self):
        claim, event, _, _ = self._waiting_task()
        with db.transaction(write=True) as tx:
            count = idempotency.settle_expired_requests_for_account_deletion_with_storage(tx, "merchant-a")
        self.assertEqual(count, 1)
        with db.transaction(write=True) as tx:
            self.assertEqual(idempotency.settle_expired_requests_for_account_deletion_with_storage(tx, "merchant-a"), 0)
        row = db.fetchone("SELECT * FROM idempotency_requests WHERE id=?", (claim["request_id"],))
        self.assertEqual((row["status"], row["refund_applied"], row["failure_code"]), ("failed", 1, "cancelled_waiting"))

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
        self.assertTrue(idempotency.mark_completed(first, confirm_existing=True))
        for key, value in (
            ("lease_token", "wrong"), ("user_id", "u-state-b"),
            ("operation", "generate"), ("payload_hash", "wrong"),
            ("charge", {"usage_id": "unrelated"}),
        ):
            self.assertFalse(idempotency.mark_completed(
                {**first, key: value}, confirm_existing=True,
            ))
        self.assertEqual(self._claim("u-state-a", "shared-user-key")["state"], "completed")

        failed = self._claim("u-state-a", "failed-key", operation="chat_rewrite")
        self.assertTrue(idempotency.mark_failed_and_refund(failed, failure_code="request_failed"))
        self.assertFalse(idempotency.mark_failed_and_refund(failed, failure_code="request_failed"))
        self.assertFalse(idempotency.mark_completed(failed, confirm_existing=True))
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
        charged_period_start = datetime.fromisoformat(
            claim["charge"]["subscription_period_start"]
        )
        if charged_period_start.month == 12:
            different_period_start = charged_period_start.replace(
                year=charged_period_start.year + 1,
                month=1,
            )
        else:
            different_period_start = charged_period_start.replace(
                month=charged_period_start.month + 1
            )
        db.execute(
            "UPDATE subscriptions SET period_start=?,used_monthly_credits=2 WHERE id=?",
            (different_period_start.isoformat(), charged_subscription_id),
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

    def test_sse_lost_claim_never_emits_success_or_refunds_new_owner(self):
        self._create_user("u-lost-completion")
        claim = self._claim("u-lost-completion", "lost-completion")
        db.execute(
            "UPDATE idempotency_requests SET lease_token_hash=? WHERE id=?",
            ("new-owner-lease", claim["request_id"]),
        )

        async def source():
            yield 'data: {"type":"complete"}\n\n'

        async def consume():
            return [json.loads(chunk.removeprefix("data: ").strip())
                    async for chunk in api._idempotent_sse_stream(
                        source(), claim, success_types={"complete"},
                    )]

        events = asyncio.run(consume())
        self.assertEqual([event["type"] for event in events], ["error"])
        self.assertEqual(events[0]["error_code"], "completion_unconfirmed")
        row = db.fetchone(
            "SELECT status,complete_applied,refund_applied FROM idempotency_requests WHERE id=?",
            (claim["request_id"],),
        )
        self.assertEqual(dict(row), {
            "status": "running", "complete_applied": 0, "refund_applied": 0,
        })

    def _run_capacity(self,legacy, source=None, extra_questions=(), invalid_reference=False):
        import ast, copy, os, httpx
        from contextlib import ExitStack
        from unittest import mock
        uid='synthetic-capacity-owner'
        self._create_user(uid)
        db.execute("UPDATE public_trial_budget SET enabled=1,policy_mode='owner_metered' WHERE id=?",(api._public_product.BUDGET_ID,))
        source=source or '蓝猫咖啡店9月双人套餐198元，包含饮品。'
        questions=[{'field':'drink_count','question':'这个双人套餐一共包含几杯饮品？','source_quote':'包含饮品','object':'双人套餐','time_range':'9月','required':False,'options':[]}]
        questions.extend(extra_questions)
        requests=[];stops=[]
        auxiliary_ready = asyncio.Event()
        auxiliary_count = 0
        async def gateway_http(request):
            nonlocal auxiliary_count
            self.assertEqual(request.method,'POST')
            self.assertEqual(request.url.path,api._mr._cgp.MESSAGES_PATH)
            body=json.loads(request.content);requests.append(body)
            self.assertEqual(body['model'],api._mr.CLAUDE_HAIKU)
            self.assertIsNone(body['thinking_budget'])
            self.assertEqual(body['temperature'],0.7)
            content='自然澄清，沿用本次商家信息' in body['system']
            # Keep the real two-call concurrency limit. Content returns first;
            # both auxiliary requests are then in flight before either fails.
            if not content:
                auxiliary_count += 1
                if auxiliary_count == 2:
                    auxiliary_ready.set()
                await asyncio.wait_for(auxiliary_ready.wait(), 5)
            enough=body['max_tokens'] >= (2048 if content else 4096)
            stop='end_turn' if enough else 'max_tokens';stops.append(stop)
            if content:
                supplied = body['messages'][-1]['content']
                reference_json = supplied.split('【本次素材索引：只用于定位澄清问题，不是新增事实】\n', 1)[1]
                references = json.loads(reference_json)
                source_id = next(key for key, value in references.items() if value == source)
                questions[0]['source_id'] = 's_nonexistent' if invalid_reference else source_id
                questions[0]['source_quote'] = '模型改写，不应由商家解决逐字匹配'
            raw=('<title>蓝猫咖啡店双人套餐</title><body>商家原始素材</body><clarifications>'+json.dumps(questions,ensure_ascii=False)+'</clarifications>') if content else '<keyword_tip>咖啡套餐</keyword_tip><tag_recommendation>咖啡</tag_recommendation><user_angle>确认套餐内容后决定</user_angle><hook>介绍已知套餐</hook>'
            return httpx.Response(200,json={'protocol_version':api._mr._cgp.PROTOCOL_VERSION,'text_blocks':[raw],
                'model':body['model'],'stop_reason':stop,'usage':{'input_tokens':1000,'output_tokens':1500 if content else (2500 if enough else body['max_tokens']),
                'cache_read_input_tokens':0,'cache_creation_input_tokens':0}})
        async def post():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app),base_url='http://isolated') as client:
                response=await client.post('/generate/stream',headers={'Origin':'https://noteaipro.com','X-Request-ID':'capacity-first-'+('legacy' if legacy else 'current')},
                    json={'domain':'美食','brief':source,'merchant_name':'蓝猫咖啡店','fact_source_policy':'skip'})
            self.assertEqual(response.status_code,200,response.text)
            return [json.loads(v.removeprefix('data: ').strip()) for v in response.text.split('\n\n') if v.startswith('data: ')]
        state={'active':{task:{'model':api._mr.CLAUDE_HAIKU if task!='arbitrate' else api._mr.CLAUDE_SONNET,'enabled':True,'max_tokens':16000} for task in api._mr._runtime_config.TASKS}}
        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ,{'NOTEAI_TASK_CLARIFICATION_ENABLED':'1','NOTEAI_PUBLIC_PRODUCT':'1',
                'NOTEAI_PUBLIC_ORIGINS':'https://noteaipro.com','NOTEAI_MODEL_CONFIG_ENABLED':'1','NOTEAI_FACT_SEARCH':'0',
                'NOTEAI_CLAUDE_TRANSPORT':'gateway','NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH':'synthetic-config-1','NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH':'synthetic-key-1'}))
            transport=api._mr.GatewayClaudeTransport(base_url='https://gateway.example.invalid',key_id='synthetic-key',secret='synthetic-only-secret',http_transport=httpx.MockTransport(gateway_http))
            stack.enter_context(mock.patch.object(api._mr,'get_claude_transport',return_value=transport))
            stack.enter_context(mock.patch.object(api._mr._runtime_config,'read',return_value=state))
            stack.enter_context(mock.patch.object(api._public_product,'authenticated_user',new=mock.AsyncMock(return_value={'id':uid})))
            api.app.dependency_overrides[api._auth.get_current_user]=lambda:{'id':uid}
            stack.callback(api.app.dependency_overrides.clear)
            stack.enter_context(mock.patch.object(api,'_compute_market_timing_for_delivery',return_value=None))
            stack.enter_context(mock.patch.object(api.asyncio,'sleep',new=mock.AsyncMock()))
            arb=stack.enter_context(mock.patch.object(api._mr,'stream',side_effect=AssertionError('must pause or fail before arbitration')))
            if legacy:
                tree=ast.parse(Path(api.__file__).read_text())
                for name,limit in (('_gent_content',4096),('_gent_growth',2048),('_gent_user',2048)):
                    function=copy.deepcopy(next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name==name))
                    changed=0
                    for node in ast.walk(function):
                        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name) and node.func.value.id=='_mr' and node.func.attr=='call':
                            kw=next(k for k in node.keywords if k.arg=='max_tokens');kw.value=ast.Constant(limit);changed+=1
                    self.assertEqual(changed,1)
                    module=ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[]));namespace={}
                    exec(compile(module,'synthetic_legacy_limit_only','exec'),api.__dict__,namespace)
                    stack.enter_context(mock.patch.object(api,name,new=namespace[name]))
            events=asyncio.run(post())
            self.assertEqual(arb.call_count,0)
        self.assertEqual(len(requests),3)
        self.assertEqual(len({r['operation_id'] for r in requests}),3)
        row=dict(db.fetchone('SELECT id,usage_id,status,credits_used,charge_applied,refund_applied,complete_applied FROM idempotency_requests WHERE user_id=?',(uid,)))
        self.assertEqual(row['credits_used'],8)
        self.assertEqual(row['charge_applied'],1)
        self.assertEqual(row['complete_applied'],0)
        calls=[dict(r) for r in db.fetchall('SELECT state,http_status,usage_record_id,model_usage_record_id FROM public_trial_calls WHERE user_id=?',(uid,))]
        self.assertEqual(len(calls),3)
        self.assertTrue(all(r['state']=='responded' and r['http_status']==200 and r['usage_record_id']==row['usage_id'] and r['model_usage_record_id'] for r in calls),calls)
        self.assertEqual(db.fetchone('SELECT count(*) n FROM usage_records WHERE user_id=?',(uid,))['n'],1)
        if invalid_reference:
            self.assertEqual((row['status'], row['refund_applied']), ('failed', 1))
            self.assertEqual(events[-1]['type'], 'error')
            saved=db.fetchone('SELECT generate_ctx_json FROM chat_sessions WHERE id=?', (row['id'],))
            private=json.loads(saved['generate_ctx_json'])['expert_preparation']
            self.assertEqual(private['parse_statuses'], ['unknown_source_id'])
            self.assertEqual(len(private['opinions']), 4)
            content=next(o for o in private['opinions'] if o.get('role')=='内容专家')
            self.assertIn('s_nonexistent', content['raw'])
            self.assertTrue(content['clarification_sources'])
            self.assertNotIn('s_nonexistent', json.dumps(events))
        elif legacy:
            self.assertEqual(sorted(r['max_tokens'] for r in requests),[2048,2048,4096])
            self.assertEqual(sorted(stops),['end_turn','max_tokens','max_tokens'])
            self.assertEqual((row['status'],row['refund_applied']),('failed',1))
            self.assertEqual(events[-1]['type'],'error')
            self.assertEqual(db.fetchone('SELECT count(*) n FROM chat_sessions')['n'],0)
        else:
            self.assertEqual([r['max_tokens'] for r in requests],[16000]*3)
            self.assertEqual(stops,['end_turn']*3)
            self.assertEqual((row['status'],row['refund_applied']),('waiting_for_input',0))
            self.assertEqual(events[-1]['type'],'clarification_required')
            self.assertEqual(events[-1]['session_id'],row['id'])
            restored=api._clarification.read(uid,row['id'])
            self.assertEqual(restored['status'],'waiting_for_input')
            self.assertEqual(len(restored['questions']),len(questions))
            saved=db.fetchone('SELECT generate_ctx_json FROM chat_sessions WHERE id=? AND user_id=?',(row['id'],uid))
            prepared=json.loads(saved['generate_ctx_json'])['task_continuation']['prepared']
            self.assertEqual(prepared['source_material'],'【商家原始素材】\n'+source)
            self.assertEqual(len(prepared['opinions']),4)
        print('SYNTHETIC_GATEWAY_FIRST_GENERATE',json.dumps({'legacy_limits':legacy,'state':row['status'],'charge':1,'credits':8,'refund':row['refund_applied'],'calls':len(calls),'cost_linked':True,'retries':0}),flush=True)

    def test_legacy_limits_are_known_truncation_and_refund_once(self):self._run_capacity(True)

    def test_current_16000_limits_save_original_claim_waiting_without_refund(self):self._run_capacity(False)

    def test_invalid_question_metadata_retains_private_experts_without_arbitration(self):
        self._run_capacity(False, invalid_reference=True)


    def test_original_waiting_resumes_through_real_pipeline_once(self):
        import os, httpx
        from contextlib import ExitStack
        from unittest import mock
        SOURCE = '蓝猫咖啡店9月双人套餐198元，包含饮品。甜点品类尚未定，停车优惠另议。'
        TITLE = '蓝猫咖啡店双人套餐怎么点更明白'
        ANSWER = ('套餐包含2杯拿铁，热饮不加糖。门店位于北京路商圈，营业时间为每日10:00-20:00。'
                  '到店可以先核对套餐内容，再决定是否点单。两杯饮品属于同一双人套餐，不是每人各两杯。'
                  '我希望文字说清每份套餐的内容，不要自行推断甜点、停车优惠或额外赠送。'
                  '以下是本次活动的完整说明，全部仅适用于蓝猫咖啡店2026年9月双人套餐，不适用于其他门店或日期。' +
                  '饮品数量已经确认，不必再次询问；未知项目不要写成事实，原素材与这段回答都应完整保留。' * 6)
        BODY = ('蓝猫咖啡店的双人套餐怎么点更明白？9月这份套餐198元，包含2杯拿铁，热饮不加糖。'
                '想找朋友一起喝咖啡，可以先从这份已确认的清单看起，不需要被没有说明的搭配带着走。'
                '两杯饮品合在同一份套餐里，点单时把数量核对清楚，会更容易按自己的口味做决定。\n\n'
                '门店位于北京路商圈，营业时间为每日10:00-20:00。拿铁是这次套餐已确认的饮品，'
                '如果平时喝咖啡的习惯不一样，不妨先问清出品安排，再决定是不是自己想喝的那一杯。'
                '已经写明的套餐内容可以作为点单参考，没有说明的项目就先留空，不需要替商家添加承诺。\n\n'
                '约朋友见面时，把门店、时间和这份套餐的清单一起发过去，沟通起来会更直接。'
                '到店前可以再核对当日安排，选适合自己的时间慢慢聊。收藏这份说明，点单时记得对照数量。'
                '你更习惯和朋友一起点套餐，还是各选各的口味？欢迎在评论里聊聊。\n'
                '#蓝猫咖啡店 #北京路咖啡 #拿铁 #双人套餐 #咖啡探店 #朋友聚会')
        RAW = f'<title>{TITLE}</title><body>{BODY}</body><variants></variants><rationale>沿用完整商家说明，不补写未确认项目。</rationale>'
        self._run_capacity(False, source=SOURCE, extra_questions=[
            {"field":"dessert_type","question":"双人套餐的甜点品类需要写进笔记吗？","source_quote":"甜点品类尚未定","object":"双人套餐","time_range":"9月","required":False},
            {"field":"parking_offer","question":"这次门店停车优惠具体是什么？","source_quote":"停车优惠另议","object":"蓝猫咖啡店","time_range":"9月","required":True}])
        uid = 'synthetic-capacity-owner'
        before = dict(db.fetchone('SELECT * FROM idempotency_requests WHERE user_id=?', (uid,)))
        sid, usage_id = before['id'], before['usage_id']
        saved = json.loads(db.fetchone('SELECT generate_ctx_json FROM chat_sessions WHERE id=?', (sid,))['generate_ctx_json'])
        task = saved['task_continuation']; prepared = task['prepared']
        first_physical = {r['id'] for r in db.fetchall('SELECT id FROM public_trial_calls WHERE user_id=?', (uid,))}
        questions = {q['field']: q for q in task['questions']}
        answers = [
            {'question_id':questions['drink_count']['question_id'],'status':'confirmed','answer':ANSWER},
            {'question_id':questions['dessert_type']['question_id'],'status':'omitted','answer':''},
            {'question_id':questions['parking_offer']['question_id'],'status':'unknown','answer':''}]
        calls = []
        async def gateway_http(request):
            payload=json.loads(request.content);calls.append(payload)
            self.assertLessEqual(len(calls),12, 'synthetic response cannot start an unbounded repair loop')
            self.assertNotIn('自然澄清，沿用本次商家信息',payload['system'], 'original expert must not rerun')
            user=payload['messages'][-1]['content']
            self.assertIn(ANSWER,user)
            self.assertIn('原问题范围仅用于定位问题',user)
            self.assertIn('所有标题、方案及后续优化都不得写入此项',user)
            self.assertIn('用户暂不确定',user)
            usage={'input_tokens':1000,'output_tokens':1000,'cache_read_input_tokens':0,'cache_creation_input_tokens':0}
            base={'protocol_version':api._mr._cgp.PROTOCOL_VERSION}
            if request.url.path == api._mr._cgp.STREAM_PATH:
                self.assertEqual(payload['model'],api._mr.CLAUDE_SONNET)
                self.assertEqual(payload['thinking_budget'],10000)
                ndjson='\n'.join(json.dumps({**base,**e},ensure_ascii=False) for e in [
                    {'type':'content','text':RAW}, {'type':'usage','model':payload['model'],'stop_reason':'end_turn','usage':usage}, {'type':'done'}])+'\n'
                return httpx.Response(200,content=ndjson,headers={'Content-Type':'application/x-ndjson'})
            self.assertEqual(request.url.path,api._mr._cgp.MESSAGES_PATH)
            text=BODY if '文案交付编辑' in payload['system'] else RAW
            return httpx.Response(200,json={**base,'text_blocks':[text], 'model':payload['model'],'stop_reason':'end_turn','usage':usage})

        features={'body_len':len(BODY),'tag_count':6,'body_cta_count':2,'body_has_price':1,'body_has_address':1,'body_has_hours':1,'body_has_must_order':1}
        state={'active':{t:{'model':api._mr.CLAUDE_HAIKU if t!='arbitrate' else api._mr.CLAUDE_SONNET,'enabled':True,'max_tokens':16000} for t in api._mr._runtime_config.TASKS}}
        async def resume_and_read():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app),base_url='http://isolated') as client:
                headers={'Origin':'https://noteaipro.com','X-Request-ID':'synthetic-original-resume'}
                payload={'session_id':sid,'task_version':task['version'],'task_answers':answers,'message':'按本次说明继续'}
                response=await client.post('/chat/message',headers=headers,json=payload)
                self.assertEqual(response.status_code,200,response.text)
                events=[json.loads(v.removeprefix('data: ').strip()) for v in response.text.split('\n\n') if v.startswith('data: ')]
                self.assertEqual(events[-1]['type'],'complete',events)
                complete=events[-1]
                readback=await client.get('/chat/tasks/'+sid,headers={'Origin':'https://noteaipro.com'})
                self.assertEqual(readback.status_code,200,readback.text)
                stored_result=readback.json()['result']
                transport_fields={'transport_schema_version','operation','trace_id','seq','server_ts','elapsed_ms','stage_elapsed_ms','terminal','outcome','schema_version'}
                self.assertEqual(stored_result,{k:v for k,v in complete.items() if k not in transport_fields})
                self.assertTrue(complete['terminal']); self.assertEqual(complete['outcome'],'success')
                count=len(calls)
                duplicate=await client.post('/chat/message',headers=headers,json=payload)
                self.assertEqual(duplicate.status_code,409,duplicate.text)
                self.assertEqual(len(calls),count)
                return events,complete
        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ,{'NOTEAI_TASK_CLARIFICATION_ENABLED':'1','NOTEAI_PUBLIC_PRODUCT':'1','NOTEAI_PUBLIC_ORIGINS':'https://noteaipro.com','NOTEAI_MODEL_CONFIG_ENABLED':'1','NOTEAI_FACT_SEARCH':'0','NOTEAI_CLAUDE_TRANSPORT':'gateway','NOTEAI_CLAUDE_GATEWAY_CONFIG_EPOCH':'synthetic-config-1','NOTEAI_CLAUDE_GATEWAY_KEY_EPOCH':'synthetic-key-1'}))
            transport=api._mr.GatewayClaudeTransport(base_url='https://gateway.example.invalid',key_id='synthetic-key',secret='synthetic-only-secret',http_transport=httpx.MockTransport(gateway_http))
            stack.enter_context(mock.patch.object(api._mr,'get_claude_transport',return_value=transport))
            stack.enter_context(mock.patch.object(api._mr._runtime_config,'read',return_value=state))
            stack.enter_context(mock.patch.object(api._public_product,'authenticated_user',new=mock.AsyncMock(return_value={'id':uid})))
            api.app.dependency_overrides[api._auth.get_current_user]=lambda:{'id':uid}
            stack.callback(api.app.dependency_overrides.clear)
            stack.enter_context(mock.patch.object(api.asyncio,'sleep',new=mock.AsyncMock()))
            # Numeric scorer/model artifacts are isolated. Semantic/grounding functions,
            # title/body shaping, candidate selector, pipeline and persistence are real.
            stack.enter_context(mock.patch.object(api,'_predict',return_value=(80.0,features)))
            stack.enter_context(mock.patch.object(api,'_score_generated_note',new=mock.AsyncMock(return_value=(80.0,features,'优秀'))))
            stack.enter_context(mock.patch.object(api,'_v04_publishable_probability',return_value=None))
            stack.enter_context(mock.patch.object(api,'get_v04_preference_ranker',return_value=None))
            for name in ('_gent_content','_gent_growth','_gent_user','_kimi_video_understand','_kimi_image_understand'):
                if hasattr(api,name):
                    stack.enter_context(mock.patch.object(api,name,new=mock.AsyncMock(side_effect=AssertionError('replayed '+name))))
            events,result=asyncio.run(resume_and_read())
        self.assertEqual(events[0]['type'],'clarification_acknowledged')
        self.assertFalse(events[0]['charged_again'])
        self.assertEqual(result['continuation_session_id'],sid)
        self.assertEqual(result['saved_note_id'],sid)
        self.assertEqual(result['saved_note_version'],1)
        self.assertEqual(result['merchant_confirmations'][0]['answer'],ANSWER)
        self.assertEqual(result['expert_opinions_basis'],'pre_clarification')
        self.assertEqual(result['pending_confirmation'],[questions['parking_offer']['question']])
        self.assertIn('2杯拿铁',result['note_body'])
        for text in [result['note_title'],result['note_body'],*result['title_variants']]:
            self.assertNotIn('甜点',text);self.assertNotIn('停车',text)
        self.assertIn(SOURCE,result['fact_context']);self.assertIn(ANSWER,result['fact_context'])
        final=dict(db.fetchone('SELECT * FROM idempotency_requests WHERE id=?',(sid,)))
        self.assertEqual((final['usage_id'],final['status'],final['credits_used'],final['charge_applied'],final['refund_applied'],final['complete_applied']),(usage_id,'completed',8,1,0,1))
        self.assertEqual(db.fetchone('SELECT count(*) n FROM usage_records WHERE user_id=?',(uid,))['n'],1)
        notes=[dict(n) for n in db.fetchall('SELECT id,title,body FROM notes WHERE user_id=?',(uid,))]
        self.assertEqual(notes,[{'id':sid,'title':result['note_title'],'body':result['note_body']}])
        stored=json.loads(db.fetchone('SELECT generate_ctx_json FROM chat_sessions WHERE id=?',(sid,))['generate_ctx_json'])['task_continuation']
        self.assertEqual(stored['prepared'],prepared)
        # Read a pre-field completed task without rewriting its historical bytes.
        legacy = json.loads(db.fetchone('SELECT generate_ctx_json FROM chat_sessions WHERE id=?',(sid,))['generate_ctx_json'])
        legacy['task_continuation']['result'].pop('expert_opinions_basis')
        legacy_bytes = json.dumps(legacy, ensure_ascii=False)
        db.execute('UPDATE chat_sessions SET generate_ctx_json=? WHERE id=?',(legacy_bytes,sid))
        import task_clarification as clarification
        restored = clarification.read(uid,sid)['result']
        self.assertEqual(restored['expert_opinions_basis'],'pre_clarification')
        self.assertEqual(db.fetchone('SELECT generate_ctx_json FROM chat_sessions WHERE id=?',(sid,))['generate_ctx_json'],legacy_bytes)
        chat = asyncio.run(api.chat_start(api.ChatStartInput(note_title=restored['note_title'],
            note_body=restored['note_body'], note_id=sid, domain='美食', local_time='2030-01-01',
            generate_context=restored), user={'id':uid}))
        api._chat_sessions.pop(chat.session_id)
        session = api._load_chat_session_from_db(chat.session_id)
        self.assertIsNotNone(session)
        context = session['generate_context']
        self.assertEqual(context['expert_opinions_basis'],'pre_clarification')
        self.assertEqual(context['merchant_confirmations'][0]['answer'],ANSWER)
        prompt = api._build_chat_system_prompt(session)
        self.assertIn('最新完整回答中明确的门店、套餐和适用日期优先',prompt)
        self.assertIn(ANSWER,prompt)
        # An ordinary result is not mislabelled by this compatibility read path.
        ordinary = dict(legacy['task_continuation'], answers=[])
        self.assertNotIn('expert_opinions_basis',clarification.public_state({'id':sid,'domain':'美食'},ordinary)['result'])
        linked=[dict(r) for r in db.fetchall('SELECT id,state,http_status,usage_record_id,model_usage_record_id FROM public_trial_calls WHERE user_id=?',(uid,))]
        self.assertEqual(len(linked),len(first_physical)+len(calls))
        self.assertTrue(all(r['state']=='responded' and r['http_status']==200 and r['usage_record_id']==usage_id and r['model_usage_record_id'] for r in linked),linked)
        print('SYNTHETIC_ASGI_RESUME',json.dumps({'first_experts':3,'resume_physical':len(calls),'same_usage':True,'credits':8,'charge':1,'refund':0,'notes':1,'pending':1,'duplicate_rejected':True}),flush=True)

if __name__ == "__main__":
    unittest.main()
