"""Source-bounded original cover holds and owned bounded workers; no supplier I/O."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import unittest
import uuid
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import cover_jobs as jobs
import cover_runtime
import cover_service as service
import db
import model_admission
import private_storage
from tests import test_cover_jobs as fixtures


class CoverQueueWorkerTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.CoverJobsTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.mode = mock.patch.dict(os.environ, {"NOTEAI_MODEL_CAPACITY_ENABLED": "0",
            "NOTEAI_PUBLIC_PRODUCT": "0", "NOTEAI_COVER_AGENT_STATE_ROOT": str(Path(self.f.temp.name) / "work")})
        self.mode.start()
        self.addCleanup(self.mode.stop)
        self.network = mock.patch("socket.socket.connect", side_effect=AssertionError("supplier network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.admission = model_admission.Admission(model_admission.Limits(operations=4, operations_per_user=1))
        patch = mock.patch.object(model_admission, "current", return_value=self.admission)
        patch.start()
        self.addCleanup(patch.stop)

    def source(self, user=None, *, seconds=7200):
        _, body = private_storage.load_media_bytes(self.f.source.id, user_id=self.f.user, purpose="image")
        return private_storage.store_media_bytes(user or self.f.user, purpose="image", content_type="image/png",
            payload=body, item_count=1, ttl_seconds=seconds, lifecycle="temporary", now=self.f.now)

    def other_job(self, key="other"):
        report = str(uuid.uuid4())
        db.execute("INSERT INTO saved_diagnoses(id,user_id,note_title,domain,diagnosis_json,created_at) VALUES(?,?,?,?,?,?)",
            (report, self.f.other, "另一真实报告", "美食", "{}", self.f.now.isoformat()))
        source = self.source(self.f.other)
        return self.f.submit(key=key, user_id=self.f.other, report_id=report, source_refs=[source.id])

    def row(self, job):
        return dict(db.fetchone("SELECT * FROM cover_jobs WHERE id=?", (job["job_id"],)))

    def financial(self, job):
        return dict(db.fetchone("SELECT * FROM idempotency_requests WHERE id=?", (job["job_id"],)))

    def test_source_bound_wait_then_first_claim_mode_off_gets_only_original_execution_window(self):
        short = self.source()
        policy_before = json.dumps(self.f.policy, sort_keys=True)
        quote_before = jobs.policy_quote_version(self.f.policy)
        job = self.f.submit(key="source-queue", source_refs=[self.f.source.id, short.id], now=self.f.now)
        repeated = self.f.submit(key="source-queue", source_refs=[self.f.source.id, short.id], now=self.f.now)
        row, financial = self.row(job), self.financial(job)
        self.assertEqual(row["deadline_at"], short.expires_at)
        self.assertEqual(financial["lease_expires_at"], short.expires_at)
        self.assertEqual(row["usage_id"], self.row(repeated)["usage_id"])
        self.assertEqual(job["billing"]["reserved_credits"], 8)
        self.assertEqual(json.dumps(self.f.policy, sort_keys=True), policy_before)
        self.assertEqual(row["quote_version"], quote_before)
        self.assertEqual(jobs.policy_quote_version(self.f.policy), quote_before)
        self.assertTrue(all("source_expires_at" in item for item in json.loads(row["source_manifest_json"])))
        started = self.f.now + timedelta(minutes=90)  # Beyond the former30min queue.
        claim = jobs.claim_job(job["job_id"], now=started)
        self.assertIsNotNone(claim)
        deadline = (started + timedelta(seconds=jobs.HOLD_SECONDS)).isoformat()
        self.assertEqual(self.row(job)["deadline_at"], deadline)
        self.assertEqual(self.financial(job)["lease_expires_at"], deadline)
        jobs.recover_jobs(now=started + timedelta(seconds=301))
        resumed_at = started + timedelta(seconds=350)
        claim = jobs.claim_job(job["job_id"], now=resumed_at)
        self.assertIsNotNone(claim)
        self.assertEqual(self.row(job)["deadline_at"], deadline, "Provider-free recovery must not renew30min")
        self.assertEqual(self.financial(job)["lease_expires_at"], deadline)
        jobs.before_text_call(claim, "design", str(uuid.uuid4()), now=resumed_at)
        jobs.fail_job(claim, failure_code="COVER_CONTROLLED_UNKNOWN", outcome_unknown=True, now=resumed_at)
        self.assertEqual(jobs.release_expired_unknowns(now=started + timedelta(minutes=29)), 0)
        self.assertEqual(jobs.release_expired_unknowns(now=started + timedelta(minutes=30, seconds=1)), 1)
        self.assertEqual(jobs.release_expired_unknowns(now=started + timedelta(minutes=31)), 0)
        self.assertEqual(self.financial(job)["refund_applied"], 1)
        self.assertEqual(db.fetchone("SELECT count(*) FROM usage_records WHERE operation='cover_generate'")[0], 1)
        self.assertEqual(db.fetchone("SELECT count(*) FROM public_trial_calls")[0], 0)

    def test_expired_unstarted_queue_releases_original_hold_once_without_unknown(self):
        source = self.source(seconds=3600)
        job = self.f.submit(source_refs=[source.id], now=self.f.now)
        self.assertEqual(jobs.release_expired_unknowns(now=self.f.now + timedelta(minutes=59)), 0)
        self.assertEqual(jobs.release_expired_unknowns(now=self.f.now + timedelta(hours=1, seconds=1)), 1)
        self.assertEqual(jobs.release_expired_unknowns(now=self.f.now + timedelta(hours=1, seconds=2)), 0)
        row = self.row(job)
        self.assertEqual((row["status"], row["failure_code"], row["unknown_at"]), ("failed", "cover_queue_expired", None))
        self.assertEqual((self.financial(job)["refund_applied"], self.financial(job)["complete_applied"]), (1, 0))
        self.assertEqual(db.fetchone("SELECT count(*) FROM public_trial_calls")[0], 0)

    def test_legacy_queue_is_not_extended_and_partial_new_expiry_is_rejected(self):
        job = self.f.submit(source_refs=[self.f.source.id, self.source().id], now=self.f.now)
        row = self.row(job)
        manifest = json.loads(row["source_manifest_json"])
        manifest[1].pop("source_expires_at")
        db.execute("UPDATE cover_jobs SET source_manifest_json=? WHERE id=?", (json.dumps(manifest), job["job_id"]))
        with self.assertRaisesRegex(ValueError, "complete original cover source expiry"):
            jobs.claim_job(job["job_id"], now=self.f.now + timedelta(minutes=5))
        self.assertEqual(self.row(job)["lease_fence"], 0)
        for item in manifest:
            item.pop("source_expires_at", None)
        deadline = (self.f.now + timedelta(seconds=jobs.HOLD_SECONDS)).isoformat()
        db.execute("UPDATE cover_jobs SET source_manifest_json=?,deadline_at=? WHERE id=?", (json.dumps(manifest), deadline, job["job_id"]))
        db.execute("UPDATE idempotency_requests SET lease_expires_at=? WHERE id=?", (deadline, job["job_id"]))
        self.assertIsNotNone(jobs.claim_job(job["job_id"], now=self.f.now + timedelta(minutes=5)))
        self.assertEqual(self.row(job)["deadline_at"], deadline)

    def test_preclaim_owner_race_skips_borrowed_operation_and_releases_only_owned_scope(self):
        first = self.f.submit(key="race-first")
        other = self.other_job("race-other")
        entered, release = threading.Event(), threading.Event()
        actual_claim = jobs.claim_job
        seen = []

        def claim(job_id):
            if job_id == first["job_id"]:
                entered.set()
                if not release.wait(3):
                    raise AssertionError("controlled claim not released")
            return actual_claim(job_id)

        def run(claim, *, runtime=None, operation=None):
            self.assertIs(self.admission.find(claim["user_id"], hashlib.sha256(claim["request_id"].encode()).hexdigest()), operation)
            seen.append(claim["request_id"])
            return claim["request_id"]

        with mock.patch.object(jobs, "claim_job", side_effect=claim), mock.patch.object(service, "_run_claim", side_effect=run):
            with ThreadPoolExecutor(max_workers=2) as pool:
                one = pool.submit(service.run_next)
                try:
                    self.assertTrue(entered.wait(2))
                    owner = self.admission.find(self.f.user, hashlib.sha256(first["job_id"].encode()).hexdigest())
                    self.assertIsNotNone(owner)
                    snapshot = service.work_snapshot()
                    self.assertEqual(snapshot["counts"]["cover_claims"], 1)
                    self.assertTrue(snapshot["active"], "Owned preclaim work must remain visible before its DB transaction")
                    two = pool.submit(service.run_next)
                    self.assertEqual(two.result(2), other["job_id"])
                    self.assertIs(self.admission.find(self.f.user, owner.request_hash), owner)
                    self.assertEqual(self.row(first)["status"], "queued")
                finally:
                    release.set()
                self.assertEqual(one.result(2), first["job_id"])
        self.assertCountEqual(seen, [first["job_id"], other["job_id"]])
        self.assertEqual(self.admission.operations, {})
        follow = self.f.submit(key="claim-none-or-error")
        with mock.patch.object(jobs, "claim_job", return_value=None):
            self.assertIsNone(service.run_next())
        self.assertEqual(self.admission.operations, {})
        self.assertEqual(service.work_snapshot()["counts"]["cover_claims"], 0)
        with mock.patch.object(jobs, "claim_job", side_effect=RuntimeError("controlled claim failure")):
            with self.assertRaisesRegex(RuntimeError, "controlled claim failure"):
                service.run_next()
        self.assertEqual(self.admission.operations, {})
        self.assertEqual(service.work_snapshot()["counts"]["cover_claims"], 0)
        self.assertEqual(self.row(follow)["lease_fence"], 0)
        actual_finish = self.admission.finish

        def finish(operation):
            self.assertEqual(service.work_snapshot()["counts"]["cover_claims"], 1)
            actual_finish(operation)
            raise RuntimeError("controlled finish failure")

        with mock.patch.object(jobs, "claim_job", return_value=None), \
                mock.patch.object(self.admission, "finish", side_effect=finish):
            with self.assertRaisesRegex(RuntimeError, "controlled finish failure"):
                service.run_next()
        self.assertEqual(self.admission.operations, {})
        self.assertEqual(service.work_snapshot()["counts"]["cover_claims"], 0)


class CoverOwnedWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatch_and_maintenance_isolate_context_on_reused_owned_thread(self):
        context = ContextVar("cover_worker_context", default="unset")
        token = context.set("parent")
        seen = []
        worker = service.CoverWorker()
        # A single real thread forces both kinds of callbacks to reuse it.
        worker.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cover-context")

        def observe(kind):
            seen.append((kind, context.get(), threading.get_ident()))
            context.set("dirty-" + kind)

        try:
            with mock.patch.object(service, "run_next", side_effect=lambda: observe("dispatch")), \
                    mock.patch.object(service, "_recover_cover_jobs", side_effect=lambda **kwargs: observe("maintenance")), \
                    mock.patch.object(service, "_COVER_MAINTENANCE_SECONDS", .02):
                worker.task = asyncio.create_task(worker.loop())
                worker.tasks = [worker.task]
                worker.maintenance_task = asyncio.create_task(worker.maintenance_loop())
                deadline = asyncio.get_running_loop().time() + 3
                while sum(kind == "dispatch" for kind, _, _ in seen) < 2 or not any(kind == "maintenance" for kind, _, _ in seen):
                    if asyncio.get_running_loop().time() >= deadline:
                        self.fail("owned callbacks did not complete")
                    await asyncio.sleep(.01)
                await worker.stop()
            self.assertEqual({value for _, value, _ in seen}, {"parent"})
            self.assertEqual(len({thread for _, _, thread in seen}), 1)
            self.assertEqual(context.get(), "parent")
            self.assertTrue(all(not thread.is_alive() for thread in worker.executor._threads))
        finally:
            await worker.stop()
            context.reset(token)

    async def test_two_slots_progress_different_users_keep_same_user_queued_and_cancelled_stop_joins(self):
        f = CoverQueueWorkerTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        active = f.f.submit(key="slot-one")
        same = f.f.submit(key="slot-same-user")
        other = f.other_job("slot-other-user")
        entered = {active["job_id"]: threading.Event(), other["job_id"]: threading.Event()}
        release = threading.Event()
        finished = []
        thread_names = []

        def runtime(**kwargs):
            job = kwargs["job_id"]
            self.assertIn(job, entered)
            thread_names.append(threading.current_thread().name)
            entered[job].set()
            try:
                if not release.wait(5):
                    raise AssertionError("controlled runtime not released")
                raise cover_runtime.CoverRuntimeError("COVER_CONTROLLED_STOP")
            finally:
                finished.append(job)

        async def wait_for(predicate):
            until = asyncio.get_running_loop().time() + 3
            while not predicate():
                if asyncio.get_running_loop().time() >= until:
                    self.fail("bounded worker state not observed")
                await asyncio.sleep(.01)

        with mock.patch.dict(os.environ, {"NOTEAI_COVER_WORKER_SLOTS": "2"}), \
                mock.patch.object(service, "_COVER_MAINTENANCE_SECONDS", .02), \
                mock.patch.object(cover_runtime, "run_cover", side_effect=runtime):
            worker = service.CoverWorker().start()
            try:
                await wait_for(lambda: all(event.is_set() for event in entered.values()))
                self.assertEqual(len(worker.tasks), 2)
                self.assertEqual(service.work_snapshot()["counts"]["cover_claims"], 2)
                self.assertEqual(f.row(same)["status"], "queued")
                self.assertEqual(f.row(same)["lease_fence"], 0)
                self.assertTrue(all(name.startswith("noteai-cover") for name in thread_names))
                stopping = asyncio.create_task(worker.stop())
                await asyncio.sleep(.03)
                stopping.cancel()
                await asyncio.sleep(.03)
                self.assertFalse(stopping.done())
                self.assertEqual(finished, [])
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(stopping, 3)
                self.assertCountEqual(finished, entered)
                self.assertTrue(all(task.done() for task in (*worker.tasks, worker.maintenance_task)))
                self.assertTrue(all(not thread.is_alive() for thread in worker.executor._threads))
                self.assertEqual(f.admission.operations, {})
                self.assertEqual(service.work_snapshot()["counts"]["cover_claims"], 0)
                self.assertEqual(db.fetchone("SELECT count(*) FROM public_trial_calls")[0], 0)
            finally:
                release.set()
                await worker.stop()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NOTEAI_COVER_WORKER_SLOTS", None)
            self.assertEqual(service.CoverWorker().slots, 1)


class CoverQueueRuntimeBoundaryTests(unittest.TestCase):
    def test_new_queue_metadata_is_not_forwarded_to_actual_run_cover_or_model_payload(self):
        from tests.test_cover_service import CoverServiceIntegrationTests
        h = CoverServiceIntegrationTests()
        h.setUp()
        try:
            with mock.patch.dict(os.environ, {"NOTEAI_MODEL_CAPACITY_ENABLED": "0"}):
                job = h.submit(key="source-bounded-runtime-boundary")
                frozen = json.loads(db.fetchone("SELECT source_manifest_json FROM cover_jobs WHERE id=?", (job["job_id"],))[0])
                self.assertIn("source_expires_at", frozen[0])
                seen = []

                def observe(request, kwargs):
                    sources = kwargs["sources"]
                    self.assertEqual(set(sources[0]), {"media_ref", "sha256", "size_bytes", "payload"})
                    self.assertEqual(sources[0]["sha256"], hashlib.sha256(sources[0]["payload"]).hexdigest())
                    self.assertNotIn(b"source_expires_at", request.content)
                    seen.append(kwargs["job_id"])

                result = service.run_next(runtime=h.wrapper(request_observer=observe))
                self.assertEqual(result["status"], "completed", result)
                self.assertEqual(result["billing"]["credits_used"], 8)
                self.assertEqual(len(seen), 2)
                self.assertEqual(h.admission.operations, {})
                self.assertEqual(h.fixture.balances()[1], 8)
        finally:
            h.tearDown()
