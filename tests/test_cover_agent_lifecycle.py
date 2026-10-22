"""Provider-free recovery and privacy lifetime of the local host workspace."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import cover_agent_runtime as runtime
import cover_jobs
import db
import idempotency
import private_storage
from tests import test_cover_jobs as fixtures


class WorkspaceLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CoverJobsTests()
        self.fixture.setUp()
        self.root = Path(self.fixture.temp.name) / "private-host"
        self.env = mock.patch.dict(os.environ, {"NOTEAI_COVER_AGENT_STATE_ROOT": str(self.root)})
        self.env.start()
        self.task, self.claim = self.fixture.claim()
        self.directory = self.root / self.claim["request_id"]
        (self.directory / "host-state").mkdir(parents=True)
        (self.directory / "photo.png").write_bytes(b"synthetic private payload")
        (self.directory / "owner.json").write_text(json.dumps({"subject_hash": idempotency.operation_subject_hash(self.fixture.user)}))
        (self.directory / "host-state/host-checkpoint.json").write_text(json.dumps({"session_id": "offline-session",
            "status": "UNKNOWN", "pending_request": {"ordinal": 1, "body_sha256": "a" * 64,
                "label": "primary"}, "model_requests": 1, "untrusted_report": "PRIVATE_REPORT_BYTES"}))

    def tearDown(self):
        self.env.stop()
        self.fixture.tearDown()

    def test_provider_free_recovery_removes_only_original_private_workspace(self):
        runtime.prepare_original_workspace(self.claim)
        self.assertFalse(self.directory.exists())
        receipt = (self.root / "receipts" / (self.claim["request_id"] + ".json")).read_text()
        self.assertIn("offline-session", receipt)
        self.assertNotIn("PRIVATE_REPORT_BYTES", receipt)

    def test_dispatched_job_is_never_cleaned_as_provider_free_or_replayed(self):
        self.fixture.physical(self.claim, state="unknown", http=None)
        with self.assertRaisesRegex(runtime.cover_runtime.CoverRuntimeError, "NO_REPLAY"):
            runtime.prepare_original_workspace(self.claim)
        self.assertTrue(self.directory.exists())

    def test_sweep_preserves_active_and_other_owner_then_cleans_terminal(self):
        runtime.cleanup_stale_workspaces(user_id=self.fixture.other)
        runtime.cleanup_stale_workspaces(user_id=self.fixture.user)
        self.assertTrue(self.directory.exists())
        cover_jobs.fail_job(self.claim, failure_code="COVER_OFFLINE_FIXTURE")
        runtime.cleanup_stale_workspaces(user_id=self.fixture.user)
        self.assertFalse(self.directory.exists())

    def test_account_deletion_stays_pending_until_active_private_workspace_drains(self):
        private_storage.delete_user_media(self.fixture.user)
        with db.transaction(write=False) as tx:
            self.assertTrue(private_storage.has_ready_user_media(tx, self.fixture.user))
        cover_jobs.fail_job(self.claim, failure_code="COVER_OFFLINE_FIXTURE")
        private_storage.delete_user_media(self.fixture.user)
        with db.transaction(write=False) as tx:
            self.assertFalse(private_storage.has_ready_user_media(tx, self.fixture.user))

    def test_database_owner_precedes_workspace_descriptor(self):
        (self.directory / "owner.json").write_text(json.dumps({
            "subject_hash": idempotency.operation_subject_hash(self.fixture.other)}))
        with db.transaction(write=False) as tx:
            self.assertTrue(runtime.has_private_workspace(tx, self.fixture.user))
            self.assertFalse(runtime.has_private_workspace(tx, self.fixture.other))

    def test_free_edit_workspace_is_managed_until_expired(self):
        from datetime import datetime, timedelta, timezone
        directory = runtime.prepare_edit_workspace(self.fixture.user, self.claim["request_id"])
        self.assertEqual(directory.parent, (self.root / "edits").resolve())
        runtime.cleanup_stale_workspaces(user_id=self.fixture.other)
        runtime.cleanup_stale_workspaces(user_id=self.fixture.user)
        self.assertTrue(directory.exists())
        owner = json.loads((directory / "owner.json").read_text())
        owner["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        (directory / "owner.json").write_text(json.dumps(owner))
        runtime.cleanup_stale_workspaces(user_id=self.fixture.user)
        self.assertFalse(directory.exists())


if __name__ == "__main__":
    unittest.main()
