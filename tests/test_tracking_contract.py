import asyncio
import hashlib
import importlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from fastapi import HTTPException
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

db = importlib.import_module("db")
api = importlib.import_module("api")
admin_server = importlib.import_module("admin_server")
crawler = importlib.import_module("crawler")
crawler_worker = importlib.import_module("crawler_worker")
tracking_contract = importlib.import_module("tracking_contract")


class TrackingContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db_path = db._DB_PATH
        db._DB_PATH = Path(self.temp.name) / "tracking.db"
        db.init_db()
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO users("
            "id,username,password_hash,password_salt,created_at"
            ") VALUES(?,?,?,?,?)",
            ("u1", "tracking-user", "hash", "salt", now),
        )

    def tearDown(self):
        db._DB_PATH = self.old_db_path
        self.temp.cleanup()

    def _insert_due(
        self,
        track_id: str,
        *,
        status: str = "pending",
        submitted_delta: timedelta = timedelta(days=2),
    ) -> None:
        now = datetime.now(timezone.utc)
        note_id = hashlib.sha256(track_id.encode("utf-8")).hexdigest()[:24]
        db.execute(
            "INSERT INTO tracked_notes("
            "id,user_id,xhs_url,xhs_note_id,submitted_at,next_check_at,status,"
            "likes_24h,saves_24h,comments_24h"
            ") VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                track_id,
                "u1",
                f"https://www.xiaohongshu.com/explore/{note_id}",
                note_id,
                (now - submitted_delta).isoformat(),
                (now - timedelta(minutes=1)).isoformat(),
                status,
                10 if status != "pending" else None,
                5 if status != "pending" else None,
                1 if status != "pending" else None,
            ),
        )

    def test_url_parser_rejects_spoofing_and_returns_secret_free_canonical_url(self):
        invalid = (
            "https://evil.invalid/xiaohongshu.com/explore/0123456789abcdef01234567",
            "https://xiaohongshu.com.evil.invalid/explore/0123456789abcdef01234567",
            "http://www.xiaohongshu.com/explore/0123456789abcdef01234567",
            "https://user:pass@www.xiaohongshu.com/explore/0123456789abcdef01234567",
            "https://www.xiaohongshu.com:8443/explore/0123456789abcdef01234567",
            "https://www.xiaohongshu.com/explore/not-a-note",
            "https://xhslink.com/example",
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(
                tracking_contract.TrackingContractError
            ):
                tracking_contract.normalize_xhs_note_url(value)

        canonical, note_id = tracking_contract.normalize_xhs_note_url(
            "https://xiaohongshu.com/discovery/item/"
            "ABCDEF0123456789ABCDEF01?xsec_token=SECRET&xsec_source=pc#fragment"
        )
        self.assertEqual(note_id, "abcdef0123456789abcdef01")
        self.assertEqual(
            canonical,
            "https://www.xiaohongshu.com/explore/abcdef0123456789abcdef01",
        )
        self.assertNotIn("SECRET", canonical)
        self.assertNotIn("?", canonical)
        self.assertNotIn("#", canonical)

    def test_api_stores_canonical_url_and_database_uniqueness_catches_variants(self):
        first = asyncio.run(
            api.track_url(
                api.TrackUrlInput(
                    xhs_url=(
                        "https://xiaohongshu.com/discovery/item/"
                        "ABCDEF0123456789ABCDEF01?xsec_token=SECRET"
                    )
                ),
                user={"id": "u1"},
            )
        )
        stored = db.fetchone(
            "SELECT xhs_url,xhs_note_id FROM tracked_notes WHERE id=?",
            (first["id"],),
        )
        self.assertEqual(
            stored["xhs_url"],
            "https://www.xiaohongshu.com/explore/abcdef0123456789abcdef01",
        )
        self.assertEqual(stored["xhs_note_id"], "abcdef0123456789abcdef01")

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                api.track_url(
                    api.TrackUrlInput(
                        xhs_url=(
                            "https://www.xiaohongshu.com/explore/"
                            "abcdef0123456789abcdef01?different=1"
                        )
                    ),
                    user={"id": "u1"},
                )
            )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM tracked_notes")["c"],
            1,
        )

    def test_tracking_inputs_fail_closed(self):
        for value in (-1, 2_147_483_648):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                api.ManualFillInput(likes=value)
        with self.assertRaises(ValidationError):
            api.ManualFillInput(evidence_source="crawler")
        with self.assertRaises(ValidationError):
            api.TrackUrlInput(
                xhs_url=(
                    "https://www.xiaohongshu.com/explore/"
                    "abcdef0123456789abcdef01"
                ),
                predicted_ces=101,
            )

        for published_at in ("not-a-clock", "2026-07-26T12:00:00"):
            with self.subTest(published_at=published_at), self.assertRaises(
                HTTPException
            ) as raised:
                asyncio.run(
                    api.track_url(
                        api.TrackUrlInput(
                            xhs_url=(
                                "https://www.xiaohongshu.com/explore/"
                                "abcdef0123456789abcdef01"
                            ),
                            published_at=published_at,
                        ),
                        user={"id": "u1"},
                    )
                )
            self.assertEqual(raised.exception.status_code, 400)

    def test_claim_is_atomic_ordered_and_enforces_hard_limit(self):
        self._insert_due("b")
        self._insert_due("a", submitted_delta=timedelta(days=3))
        db.execute(
            "UPDATE tracked_notes SET next_check_at=NULL WHERE id IN (?,?)",
            ("a", "b"),
        )
        self.assertEqual(
            [row["id"] for row in crawler._claim_due_tracking_notes(1)],
            ["a"],
        )

        barrier = threading.Barrier(3)
        results: list[list[str]] = []

        def claim():
            barrier.wait()
            rows = crawler._claim_due_tracking_notes(1)
            results.append([row["id"] for row in rows])

        workers = [threading.Thread(target=claim) for _ in range(2)]
        for worker in workers:
            worker.start()
        barrier.wait()
        for worker in workers:
            worker.join()

        flattened = [item for result in results for item in result]
        self.assertEqual(flattened, ["b"])
        self.assertEqual(len(flattened), len(set(flattened)))
        for invalid in (0, -1, tracking_contract.MAX_ROUND_LIMIT + 1):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                crawler._claim_due_tracking_notes(invalid)

    def test_sqlite_claim_compares_offset_clocks_by_instant(self):
        self._insert_due("offset-due")
        due = (
            datetime.now(timezone.utc) - timedelta(minutes=1)
        ).astimezone(timezone(timedelta(hours=8))).isoformat()
        db.execute(
            "UPDATE tracked_notes SET next_check_at=? WHERE id=?",
            (due, "offset-due"),
        )
        self.assertEqual(
            [row["id"] for row in crawler._claim_due_tracking_notes(1)],
            ["offset-due"],
        )

    def test_terminal_worker_commit_is_fenced_atomic_and_idempotent(self):
        self._insert_due("track-seven", status="checking_7d")
        note = crawler._claim_due_tracking_notes(1)[0]
        admitted = crawler._admit_provider_attempt(note)
        crawler._record_tracking_success(
            admitted,
            {"likes": 100, "saves": 40, "comments": 10, "title": "标题"},
        )

        row = db.fetchone(
            "SELECT status,claim_token,active_attempt_id FROM tracked_notes WHERE id=?",
            ("track-seven",),
        )
        self.assertEqual(row["status"], "complete")
        self.assertIsNone(row["claim_token"])
        self.assertIsNone(row["active_attempt_id"])
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM growth_records")["c"],
            1,
        )
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM user_memories "
                "WHERE memory_type='context'"
            )["c"],
            1,
        )
        self.assertEqual(
            db.fetchone(
                "SELECT status FROM tracking_provider_attempts"
            )["status"],
            "succeeded",
        )

        with self.assertRaises(ValueError):
            crawler._record_tracking_success(
                admitted,
                {"likes": 200, "saves": 80, "comments": 20, "title": "重放"},
            )
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM growth_records")["c"],
            1,
        )
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM user_memories")["c"],
            1,
        )

    def test_provider_metrics_and_full_two_stage_lifecycle_are_bounded(self):
        for value in (-1, 2_147_483_648, True, "1"):
            with self.subTest(value=value), self.assertRaises(
                tracking_contract.TrackingContractError
            ):
                tracking_contract.validate_provider_metrics(
                    {"likes": value, "saves": 1, "comments": 1}
                )

        self._insert_due("two-stage")
        first = crawler._admit_provider_attempt(
            crawler._claim_due_tracking_notes(1)[0]
        )
        crawler._record_tracking_success(
            first,
            {"likes": 10, "saves": 5, "comments": 1, "title": "24h"},
        )
        after_24h = db.fetchone(
            "SELECT status,next_check_at FROM tracked_notes WHERE id=?",
            ("two-stage",),
        )
        self.assertEqual(after_24h["status"], "checking_7d")
        self.assertEqual(crawler._claim_due_tracking_notes(1), [])

        db.execute(
            "UPDATE tracked_notes SET next_check_at=? WHERE id=?",
            (
                (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
                "two-stage",
            ),
        )
        second = crawler._admit_provider_attempt(
            crawler._claim_due_tracking_notes(1)[0]
        )
        crawler._record_tracking_success(
            second,
            {"likes": 100, "saves": 50, "comments": 10, "title": "7d"},
        )
        attempts = db.fetchall(
            "SELECT stage,status FROM tracking_provider_attempts "
            "WHERE track_id=? ORDER BY stage",
            ("two-stage",),
        )
        self.assertEqual(
            [(row["stage"], row["status"]) for row in attempts],
            [("24h", "succeeded"), ("7d", "succeeded")],
        )

    def test_account_deletion_fence_wins_before_provider_admission(self):
        self._insert_due("delete-race")
        claimed = crawler._claim_due_tracking_notes(1)[0]
        db.execute(
            "UPDATE tracked_notes SET status='account_deletion_pending' "
            "WHERE id=?",
            ("delete-race",),
        )
        with self.assertRaisesRegex(ValueError, "write fenced"):
            crawler._admit_provider_attempt(claimed)
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM tracking_provider_attempts"
            )["c"],
            0,
        )

    def test_sqlite_attempt_owner_and_active_track_are_persistently_fenced(self):
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO users("
            "id,username,password_hash,password_salt,created_at"
            ") VALUES(?,?,?,?,?)",
            ("u2", "tracking-user-two", "hash", "salt", now),
        )
        self._insert_due("owner-track")
        self._insert_due("other-track")
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO tracking_provider_attempts("
                "id,track_id,user_id,run_id,stage,status,admitted_at"
                ") VALUES(?,?,?,?,?,?,?)",
                (
                    "wrong-owner-attempt",
                    "owner-track",
                    "u2",
                    "00000000-0000-0000-0000-000000000020",
                    "24h",
                    "started",
                    now,
                ),
            )
        admitted = crawler._admit_provider_attempt(
            crawler._claim_due_tracking_notes(1)[0]
        )
        other_id = (
            "other-track"
            if admitted["id"] == "owner-track"
            else "owner-track"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(
                "UPDATE tracked_notes SET active_attempt_id=? WHERE id=?",
                (admitted["active_attempt_id"], other_id),
            )

    def test_indeterminate_provider_attempt_is_never_automatically_retried(self):
        self._insert_due("crash-window")
        note = crawler._claim_due_tracking_notes(1)[0]
        admitted = crawler._admit_provider_attempt(note)
        db.execute(
            "UPDATE tracked_notes SET claim_expires_at=? WHERE id=?",
            (
                (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
                admitted["id"],
            ),
        )

        self.assertEqual(crawler._claim_due_tracking_notes(1), [])
        reconciled = crawler._reconcile_stale_provider_attempts(limit=1)
        self.assertEqual(reconciled, 1)
        row = db.fetchone(
            "SELECT active_attempt_id,status,last_error_code "
            "FROM tracked_notes WHERE id=?",
            (admitted["id"],),
        )
        self.assertIsNone(row["active_attempt_id"])
        self.assertEqual(row["status"], "needs_manual")
        self.assertEqual(row["last_error_code"], "provider_outcome_unknown")
        attempt = db.fetchone(
            "SELECT status,error_code FROM tracking_provider_attempts WHERE id=?",
            (admitted["active_attempt_id"],),
        )
        self.assertEqual(attempt["status"], "failed")
        self.assertEqual(attempt["error_code"], "provider_outcome_unknown")

    def test_account_deletion_is_blocked_while_provider_attempt_is_active(self):
        self._insert_due("delete-active")
        admitted = crawler._admit_provider_attempt(
            crawler._claim_due_tracking_notes(1)[0]
        )
        content_retention = importlib.import_module("content_retention")

        with self.assertRaisesRegex(ValueError, "tracking attempt"):
            content_retention.request_account_deletion("u1")
        user = db.fetchone(
            "SELECT deletion_requested_at FROM users WHERE id=?",
            ("u1",),
        )
        self.assertIsNone(user["deletion_requested_at"])
        row = db.fetchone(
            "SELECT status,active_attempt_id FROM tracked_notes WHERE id=?",
            (admitted["id"],),
        )
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["active_attempt_id"], admitted["active_attempt_id"])

    def test_legacy_tracking_urls_are_never_returned_or_exported_raw(self):
        self._insert_due("legacy-public")
        note_id = "abcdef0123456789abcdef01"
        db.execute(
            "UPDATE tracked_notes SET xhs_note_id=?,xhs_url=? WHERE id=?",
            (
                note_id,
                "https://www.xiaohongshu.com/explore/"
                f"{note_id}?xsec_token=SECRET#fragment",
                "legacy-public",
            ),
        )
        row = db.fetchone(
            "SELECT * FROM tracked_notes WHERE id=?",
            ("legacy-public",),
        )
        public = api._public_tracking_row(row)
        self.assertEqual(
            public["xhs_url"],
            f"https://www.xiaohongshu.com/explore/{note_id}",
        )
        self.assertNotIn("SECRET", str(public))
        exported = api._account_export_payload(
            dict(db.fetchone("SELECT * FROM users WHERE id=?", ("u1",)))
        )
        self.assertNotIn("SECRET", str(exported))
        admin_payload = asyncio.run(
            admin_server.admin_tracked_notes(
                page=1,
                page_size=20,
                admin={"id": "admin"},
            )
        )
        self.assertNotIn("SECRET", str(admin_payload))
        self.assertEqual(
            admin_payload["notes"][0]["xhs_url"],
            f"https://www.xiaohongshu.com/explore/{note_id}",
        )

    def test_round_claims_only_one_fresh_lease_at_a_time(self):
        self._insert_due("round-a")
        self._insert_due("round-b")
        claimed_limits = []
        original = crawler._claim_due_tracking_notes

        def claim(limit, **kwargs):
            claimed_limits.append(limit)
            return original(limit, **kwargs)

        async def fetch(note):
            return {"likes": 1, "saves": 1, "comments": 1, "title": "safe"}

        with mock.patch.object(
            crawler,
            "_claim_due_tracking_notes",
            side_effect=claim,
        ):
            result = asyncio.run(
                crawler._process_due_tracking_notes(
                    2,
                    fetch,
                    run_id="00000000-0000-0000-0000-000000000001",
                )
            )
        self.assertEqual(claimed_limits, [1, 1])
        self.assertEqual(result["attempted"], 2)

    def test_tracking_healthcheck_is_read_only_and_checks_contract(self):
        old_role = os.environ.get("NOTEAI_RUNTIME_ROLE")
        os.environ["NOTEAI_RUNTIME_ROLE"] = "xhs-http"
        try:
            status = crawler.tracking_readiness_status()
        finally:
            if old_role is None:
                os.environ.pop("NOTEAI_RUNTIME_ROLE", None)
            else:
                os.environ["NOTEAI_RUNTIME_ROLE"] = old_role
        self.assertEqual(status["status"], "ready")
        self.assertIn("active_provider_attempts", status)

    def test_stale_health_fails_without_mutating_then_manual_reconcile_clears(self):
        self._insert_due("stale-health")
        admitted = crawler._admit_provider_attempt(
            crawler._claim_due_tracking_notes(1)[0]
        )
        db.execute(
            "UPDATE tracked_notes SET claim_expires_at=? WHERE id=?",
            (
                (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
                admitted["id"],
            ),
        )
        before = dict(
            db.fetchone(
                "SELECT status,active_attempt_id FROM tracked_notes WHERE id=?",
                (admitted["id"],),
            )
        )
        old_role = os.environ.get("NOTEAI_RUNTIME_ROLE")
        os.environ["NOTEAI_RUNTIME_ROLE"] = "xhs-http"
        try:
            health = crawler.tracking_readiness_status()
        finally:
            if old_role is None:
                os.environ.pop("NOTEAI_RUNTIME_ROLE", None)
            else:
                os.environ["NOTEAI_RUNTIME_ROLE"] = old_role
        after = dict(
            db.fetchone(
                "SELECT status,active_attempt_id FROM tracked_notes WHERE id=?",
                (admitted["id"],),
            )
        )
        self.assertEqual(before, after)
        self.assertEqual(health["status"], "not_ready")
        self.assertEqual(health["reason"], "provider_outcome_unknown")
        self.assertFalse(health["provider_called"])
        self.assertEqual(crawler._reconcile_stale_provider_attempts(limit=1), 1)

    def test_healthcheck_cli_exit_contract_and_zero_provider_path(self):
        env = dict(os.environ)
        env["NOTEAI_RUNTIME_ROLE"] = "xhs-http"
        env["NOTEAI_SQLITE_PATH"] = str(db._DB_PATH)
        command = [
            sys.executable,
            str(MODEL_DIR / "crawler_worker.py"),
            "--healthcheck",
        ]
        ready = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(ready.returncode, 0, ready.stderr)
        payload = json.loads(ready.stdout.strip())
        self.assertEqual(payload["status"], "ready")
        self.assertFalse(payload["provider_called"])
        self.assertNotIn("xhs_url", payload)

        wrong_role_env = dict(env)
        wrong_role_env["NOTEAI_RUNTIME_ROLE"] = "api"
        wrong_role = subprocess.run(
            command,
            cwd=ROOT,
            env=wrong_role_env,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        self.assertNotEqual(wrong_role.returncode, 0)
        self.assertEqual(
            json.loads(wrong_role.stdout.strip())["reason"],
            "runtime_role_not_allowed",
        )

        missing_env = dict(env)
        missing_env.pop("NOTEAI_SQLITE_PATH", None)
        missing_env["DATABASE_URL"] = (
            "postgresql://synthetic@127.0.0.1:1/"
            "missing_tracking_contract?connect_timeout=1"
        )
        missing = subprocess.run(
            command,
            cwd=ROOT,
            env=missing_env,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        self.assertNotEqual(missing.returncode, 0)
        missing_payload = json.loads(missing.stdout.strip())
        self.assertEqual(missing_payload["status"], "not_ready")
        self.assertFalse(missing_payload["provider_called"])

        with mock.patch.object(
            crawler,
            "_extract_note_data_with_spider_http",
        ) as supplier, mock.patch.object(
            sys,
            "argv",
            ["crawler_worker.py", "--healthcheck"],
        ), mock.patch.dict(
            os.environ,
            {"NOTEAI_RUNTIME_ROLE": "xhs-http"},
        ):
            with self.assertRaises(SystemExit) as exited:
                crawler_worker.main()
        self.assertEqual(exited.exception.code, 0)
        supplier.assert_not_called()

    def test_admin_global_trigger_fails_closed_and_does_not_record_false_success(self):
        with self.assertRaises(HTTPException) as invalid:
            asyncio.run(
                admin_server.admin_crawler_run(
                    {"limit": 0},
                    None,
                    admin={"id": "admin"},
                )
            )
        self.assertEqual(invalid.exception.status_code, 400)
        with self.assertRaises(HTTPException) as disabled:
            asyncio.run(
                admin_server.admin_crawler_run(
                    {"limit": 1},
                    None,
                    admin={"id": "admin"},
                )
            )
        self.assertEqual(disabled.exception.status_code, 409)

        with mock.patch.object(
            crawler,
            "run_collection_round",
            new=mock.AsyncMock(
                return_value={
                    "skipped": True,
                    "reason": "runtime_role_not_allowed",
                    "collected": 0,
                }
            ),
        ), mock.patch.object(admin_server._settings, "set_json") as save:
            asyncio.run(admin_server._run_crawler_bg(1))
        save.assert_not_called()

    def test_postgres_contract_fences_identity_owner_status_and_real_clocks(self):
        migration = (
            ROOT
            / "model"
            / "migrations"
            / "postgres"
            / "0010_tracking_execution_contract.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("tracking migration blocked: noncanonical note identity", migration)
        self.assertIn("UNIQUE(id, user_id)", migration)
        self.assertIn(
            "FOREIGN KEY(track_id, user_id)",
            migration,
        )
        self.assertIn(
            "FOREIGN KEY(id, active_attempt_id)",
            migration,
        )
        self.assertIn("status IS NOT NULL", migration)
        self.assertIn("submitted_at::timestamptz IS NOT NULL", migration)

    def test_expired_claim_cannot_start_provider_and_daily_cap_is_durable(self):
        self._insert_due("expired-claim")
        expired = crawler._claim_due_tracking_notes(1)[0]
        db.execute(
            "UPDATE tracked_notes SET claim_expires_at=? WHERE id=?",
            (
                (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
                expired["id"],
            ),
        )
        with self.assertRaisesRegex(ValueError, "claim expired"):
            crawler._admit_provider_attempt(expired)
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM tracking_provider_attempts"
            )["c"],
            0,
        )

        first = crawler._claim_due_tracking_notes(1)[0]
        with mock.patch.object(
            tracking_contract,
            "DAILY_PROVIDER_LIMIT",
            1,
        ):
            crawler._admit_provider_attempt(first)
            self._insert_due("daily-cap")
            second = crawler._claim_due_tracking_notes(1)[0]
            with self.assertRaises(
                tracking_contract.TrackingDailyLimitReached
            ):
                crawler._admit_provider_attempt(second)
        row = db.fetchone(
            "SELECT active_attempt_id FROM tracked_notes WHERE id=?",
            ("daily-cap",),
        )
        self.assertIsNone(row["active_attempt_id"])
        self.assertEqual(
            db.fetchone(
                "SELECT COUNT(*) AS c FROM tracking_provider_attempts"
            )["c"],
            1,
        )

    def test_manual_fill_is_single_terminal_commit_and_rejects_active_or_complete(self):
        self._insert_due("manual-one", status="needs_manual")
        request = api.ManualFillInput(
            likes=120,
            saves=80,
            comments=12,
            views=900,
        )
        first = asyncio.run(
            api.fill_tracking_data("manual-one", request, user={"id": "u1"})
        )
        self.assertTrue(first["ok"])
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                api.fill_tracking_data(
                    "manual-one",
                    request,
                    user={"id": "u1"},
                )
            )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM growth_records")["c"],
            1,
        )
        self.assertEqual(
            db.fetchone("SELECT COUNT(*) AS c FROM user_memories")["c"],
            1,
        )

    def test_deleted_account_rows_are_not_claimed(self):
        self._insert_due("deleting")
        db.execute(
            "UPDATE tracked_notes SET status='account_deletion_pending' WHERE id=?",
            ("deleting",),
        )
        self.assertEqual(crawler._claim_due_tracking_notes(1), [])

    def test_once_exit_code_distinguishes_safe_noop_from_failure(self):
        self.assertEqual(
            crawler_worker._result_exit_code(
                {"skipped": True, "reason": "collection_suspended", "collected": 0}
            ),
            0,
        )
        self.assertEqual(
            crawler_worker._result_exit_code(
                {"message": "暂无待采集记录", "collected": 0}
            ),
            0,
        )
        for result in (
            {"error": "配置错误", "collected": 0},
            {"collected": 0, "failed": 1, "attempted": 1},
            {"collected": 1, "failed": 1, "attempted": 2},
            {"skipped": True, "reason": "runtime_role_not_allowed", "collected": 0},
        ):
            with self.subTest(result=result):
                self.assertEqual(crawler_worker._result_exit_code(result), 1)

    def test_direct_crawler_main_classifies_unsafe_skip_as_failure(self):
        self.assertEqual(
            crawler._result_exit_code(
                {
                    "skipped": True,
                    "reason": "runtime_role_not_allowed",
                    "collected": 0,
                }
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
