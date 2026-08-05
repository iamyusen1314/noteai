import asyncio
import importlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

db = importlib.import_module("db")
billing = importlib.import_module("billing")
durable_ai = importlib.import_module("durable_ai")
durable_ai_worker = importlib.import_module("durable_ai_worker")
api = importlib.import_module("api")


class DurableAiApiTests(unittest.TestCase):
    def setUp(self):
        self.old_db_path = db._DB_PATH
        self.old_database_url = os.environ.pop("DATABASE_URL", None)
        self.old_enabled = os.environ.get("NOTEAI_DURABLE_AI_ADMISSION_ENABLED")
        self.old_suspended = os.environ.get("NOTEAI_DURABLE_AI_SUSPENDED")
        self.old_role = os.environ.get("NOTEAI_RUNTIME_ROLE")
        self.temp = tempfile.TemporaryDirectory()
        db._DB_PATH = Path(self.temp.name) / "noteai.db"
        db.init_db()
        self.store = durable_ai.InMemoryPayloadStore()
        durable_ai.configure_payload_store(self.store)
        os.environ["NOTEAI_DURABLE_AI_ADMISSION_ENABLED"] = "1"
        os.environ["NOTEAI_DURABLE_AI_SUSPENDED"] = "0"
        os.environ["NOTEAI_RUNTIME_ROLE"] = "ai-worker"
        self.user = {"id": "u-api-durable"}
        self.other = {"id": "u-api-other"}
        self._create_user(self.user["id"])
        self._create_user(self.other["id"])

    def tearDown(self):
        durable_ai.reset_payload_store()
        billing.clear_active_usage()
        db._DB_PATH = self.old_db_path
        if self.old_database_url is not None:
            os.environ["DATABASE_URL"] = self.old_database_url
        else:
            os.environ.pop("DATABASE_URL", None)
        for key, value in (
            ("NOTEAI_DURABLE_AI_ADMISSION_ENABLED", self.old_enabled),
            ("NOTEAI_DURABLE_AI_SUSPENDED", self.old_suspended),
            ("NOTEAI_RUNTIME_ROLE", self.old_role),
        ):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temp.cleanup()

    def _create_user(self, user_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO users(id,username,email,password_hash,password_salt,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (user_id, user_id, f"{user_id}@example.com", "hash", "salt", now),
        )
        billing.get_subscription(user_id)
        db.execute(
            "INSERT INTO credits(user_id,balance,total_purchased,total_used,updated_at) "
            "VALUES(?,1000,1000,0,?) ON CONFLICT(user_id) DO NOTHING",
            (user_id, now),
        )

    @staticmethod
    def _body(response) -> dict:
        return json.loads(response.body.decode("utf-8"))

    def submit(self, *, request_id="durable-api-key", req=None):
        return asyncio.run(
            api.durable_analyze_job(
                req
                or api.AnalyzeInput(
                    note_title="标题",
                    desc="正文",
                    domain="美食",
                ),
                user=self.user,
                request_id=request_id,
            )
        )

    def deliver(self, operation_id: str) -> None:
        delivered = []
        result = durable_ai_worker.OutboxDispatcher(delivered.append).run_once(
            owner_token=f"api-test-dispatch-{operation_id}",
        )
        self.assertEqual(result["status"], "delivered")
        self.assertEqual(delivered, [operation_id])

    def test_202_duplicate_status_events_and_owner_hiding(self):
        first = self.submit()
        duplicate = self.submit()
        self.assertEqual(first.status_code, 202)
        self.assertEqual(duplicate.status_code, 202)
        first_body = self._body(first)
        duplicate_body = self._body(duplicate)
        self.assertEqual(first_body["idempotency_state"], "admitted")
        self.assertEqual(duplicate_body["idempotency_state"], "existing")
        self.assertEqual(
            first_body["operation_id"],
            duplicate_body["operation_id"],
        )
        status = asyncio.run(
            api.durable_ai_job_status(
                first_body["operation_id"],
                user=self.user,
            )
        )
        self.assertEqual(status["status"], "queued")
        events = asyncio.run(
            api.durable_ai_job_events(
                first_body["operation_id"],
                after_sequence=0,
                user=self.user,
            )
        )
        self.assertEqual(
            [event["event_type"] for event in events["events"]],
            ["enqueued"],
        )
        with self.assertRaises(HTTPException) as hidden:
            asyncio.run(
                api.durable_ai_job_status(
                    first_body["operation_id"],
                    user=self.other,
                )
            )
        self.assertEqual(hidden.exception.status_code, 404)

    def test_disabled_or_missing_store_fails_before_charge(self):
        os.environ["NOTEAI_DURABLE_AI_ADMISSION_ENABLED"] = "0"
        with self.assertRaises(HTTPException) as disabled:
            self.submit(request_id="disabled")
        self.assertEqual(disabled.exception.status_code, 503)
        self.assertEqual(
            disabled.exception.detail["code"],
            "DURABLE_AI_ADMISSION_DISABLED",
        )
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM ai_operations")["c"],
            0,
        )

        os.environ["NOTEAI_DURABLE_AI_ADMISSION_ENABLED"] = "1"
        durable_ai.reset_payload_store()
        with self.assertRaises(HTTPException) as unavailable:
            self.submit(request_id="unavailable")
        self.assertEqual(unavailable.exception.status_code, 503)
        self.assertEqual(
            unavailable.exception.detail["code"],
            "DURABLE_AI_STORAGE_UNAVAILABLE",
        )
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM usage_records")["c"],
            0,
        )

    def test_inline_media_is_rejected_before_charge(self):
        request = api.AnalyzeInput(
            note_title="标题",
            desc="正文",
            domain="美食",
            cover_image="data:image/png;base64,AAAA",
        )
        with self.assertRaises(HTTPException) as rejected:
            self.submit(request_id="inline-media", req=request)
        self.assertEqual(rejected.exception.status_code, 422)
        self.assertEqual(
            rejected.exception.detail["code"],
            "DURABLE_AI_MEDIA_REFERENCE_REQUIRED",
        )
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM usage_records")["c"],
            0,
        )

    def test_result_endpoint_replays_only_owner_bound_result(self):
        admitted = self._body(self.submit(request_id="result-replay"))
        self.deliver(admitted["operation_id"])

        def processor(payload, context):
            context.invoke_provider(
                provider="claude",
                model="claude-sonnet-4-6",
                request={"title": payload["note_title"]},
                call=lambda: {"accepted": True},
            )
            return {"diagnosis": "safe delivered result"}

        run = durable_ai_worker.DurableAiWorker(
            processor=processor,
            store=self.store,
        ).run_message(
            admitted["operation_id"],
            owner_token="api-result-worker-owner",
        )
        self.assertEqual(run["status"], "succeeded")
        result = asyncio.run(
            api.durable_ai_job_result(
                admitted["operation_id"],
                user=self.user,
            )
        )
        self.assertEqual(result, {"diagnosis": "safe delivered result"})
        with self.assertRaises(HTTPException) as hidden:
            asyncio.run(
                api.durable_ai_job_result(
                    admitted["operation_id"],
                    user=self.other,
                )
            )
        self.assertEqual(hidden.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
