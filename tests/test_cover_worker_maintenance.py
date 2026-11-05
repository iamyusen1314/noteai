"""Real local worker/ledger recovery with controlled runtime, no supplier calls."""
import asyncio
from datetime import datetime, timedelta, timezone
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
from tests import test_cover_jobs as job_fixtures


class CoverWorkerMaintenanceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixture = job_fixtures.CoverJobsTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.env = mock.patch.dict(os.environ, {"DATABASE_URL": "", "PYTHON_DOTENV_DISABLED": "1",
            "NOTEAI_PUBLIC_PRODUCT": "0", "NOTEAI_MODEL_CAPACITY_ENABLED": "0",
            "NOTEAI_COVER_AGENT_STATE_ROOT": str(Path(self.fixture.temp.name) / "worker-state")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.network = mock.patch("socket.socket.connect", side_effect=AssertionError("No supplier network in worker tests"))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.admission = model_admission.Admission(model_admission.Limits(physical=2, seedream=1))
        self.admission_patch = mock.patch.object(model_admission, "current", return_value=self.admission)
        self.admission_patch.start()
        self.addCleanup(self.admission_patch.stop)
        self.interval = mock.patch.object(service, "_COVER_MAINTENANCE_SECONDS", .02, create=True)
        self.interval.start()
        self.addCleanup(self.interval.stop)

    async def wait_until(self, predicate, *, seconds=2):
        deadline = asyncio.get_running_loop().time() + seconds
        while not predicate():
            if asyncio.get_running_loop().time() >= deadline:
                self.fail("Expected worker state was not reached within the controlled local bound")
            await asyncio.sleep(.01)

    def financial(self, job_id):
        return dict(db.fetchone("SELECT * FROM idempotency_requests WHERE id=?", (job_id,)))

    def second_owner_job(self):
        report = str(uuid.uuid4())
        db.execute("INSERT INTO saved_diagnoses(id,user_id,note_title,domain,diagnosis_json,created_at) VALUES(?,?,?,?,?,?)",
            (report, self.fixture.other, "另一份真实报告", "美食", "{}", self.fixture.now.isoformat()))
        source = self.fixture.image(self.fixture.other, small=True)
        return self.fixture.submit(key="maintenance-queued-owner", user_id=self.fixture.other,
            report_id=report, source_refs=[source.id])

    async def test_blocked_runtime_does_not_delay_queued_expiry_or_replay_unknown_and_stop_joins(self):
        active = self.fixture.submit(key="maintenance-active")
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        calls, recoveries = [], []
        original_recover = jobs.recover_jobs
        physical_id = str(uuid.uuid4())

        def recover(**kwargs):
            recoveries.append(threading.get_ident())
            return original_recover(**kwargs)

        def blocked_runtime(**kwargs):
            calls.append(kwargs["job_id"])
            usage = db.fetchone("SELECT usage_id FROM cover_jobs WHERE id=?", (kwargs["job_id"],))[0]
            # Controlled retained supplier-UNKNOWN row, not an HTTP dispatch.
            kwargs["hooks"].before_call("design", physical_id, {})
            db.execute("INSERT INTO public_trial_calls(id,budget_id,user_id,request_hash,state,reserve_milli_cny,created_at,usage_record_id,http_status) "
                "VALUES(?,?,?,?,?,?,?,?,?)", (physical_id, self.fixture.policy["budget_id"], self.fixture.user,
                "retained-maintenance-fixture", "unknown", 600, datetime.now(timezone.utc).isoformat(), usage, None))
            entered.set()
            try:
                if not release.wait(8):
                    raise AssertionError("Controlled runtime was not released")
                raise cover_runtime.CoverRuntimeError("COVER_MAINTENANCE_FIXTURE_UNKNOWN", outcome_unknown=True)
            finally:
                finished.set()

        worker = service.CoverWorker()
        tasks_before = set(asyncio.all_tasks())
        with mock.patch.object(cover_runtime, "run_cover", side_effect=blocked_runtime), \
                mock.patch.object(jobs, "recover_jobs", side_effect=recover):
            worker.start()
            try:
                await self.wait_until(entered.is_set)
                original = dict(db.fetchone("SELECT * FROM cover_jobs WHERE id=?", (active["job_id"],)))
                unknown = dict(db.fetchone("SELECT * FROM public_trial_calls WHERE id=?", (physical_id,)))
                queued = self.second_owner_job()
                expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
                db.execute("UPDATE cover_jobs SET deadline_at=? WHERE id=?", (expired, queued["job_id"]))
                await self.wait_until(lambda: jobs.get_job(self.fixture.other, queued["job_id"])["status"] == "failed")
                self.assertFalse(finished.is_set())
                self.assertEqual(calls, [active["job_id"]])
                state = self.financial(queued["job_id"])
                self.assertEqual((state["refund_applied"], state["complete_applied"]), (1, 0))
                self.assertEqual(jobs.get_job(self.fixture.other, queued["job_id"])["failure_code"], "cover_queue_expired")
                refunded_version = dict(state)
                count = len(recoveries)
                await self.wait_until(lambda: len(recoveries) >= count + 3)
                self.assertEqual(self.financial(queued["job_id"]), refunded_version)
                running = dict(db.fetchone("SELECT * FROM cover_jobs WHERE id=?", (active["job_id"],)))
                for field in ("status", "lease_fence", "lease_token_hash", "lease_expires_at", "deadline_at", "call_intents_json"):
                    self.assertEqual(running[field], original[field], field)
                self.assertEqual(dict(db.fetchone("SELECT * FROM public_trial_calls WHERE id=?", (physical_id,))), unknown)
                self.assertEqual(self.financial(active["job_id"])["refund_applied"], 0)
                # A cancelled asyncio owner must still join its original thread.
                worker.task.cancel()
                await asyncio.sleep(.03)
                self.assertFalse(worker.task.done())
                stopping = asyncio.create_task(worker.stop())
                await asyncio.sleep(.03)
                self.assertFalse(stopping.done())
                self.assertFalse(finished.is_set())
                release.set()
                await asyncio.wait_for(stopping, 2)
                self.assertTrue(finished.is_set())
                self.assertEqual(calls, [active["job_id"]])
                self.assertEqual(jobs.get_job(self.fixture.user, active["job_id"])["status"], "outcome_unknown")
                self.assertEqual(self.financial(active["job_id"])["refund_applied"], 0)
                self.assertEqual(dict(db.fetchone("SELECT * FROM public_trial_calls WHERE id=?", (physical_id,))), unknown)
                self.assertEqual(db.fetchone("SELECT count(*) FROM public_trial_calls")[0], 1)
                self.assertEqual(db.fetchone("SELECT count(*) FROM model_usage_records")[0], 0)
                self.assertEqual(self.admission.operations, {})
                await asyncio.sleep(0)
                self.assertFalse([t for t in asyncio.all_tasks() - tasks_before if not t.done()])
                self.assertFalse([t for t in threading.enumerate() if t.name == "noteai-cover-heartbeat"])
                print("COVER_WORKER_MAINTENANCE_LEDGER_PROOF=" + json.dumps({
                    "real_temporary_DB_and_worker": True, "blocked_runtime_calls": len(calls),
                    "queued_expiry_refund_once": True, "active_fence_and_unknown_preserved": True,
                    "repeated_ticks": True, "cancel_stop_joined_original_thread": True,
                    "orphan_worker_tasks": 0, "supplier_calls": 0, "merchant_quality_acceptance": False}, sort_keys=True))
            finally:
                release.set()
                await asyncio.wait_for(worker.stop(), 3)

    async def test_idle_skips_new_DB_scans_but_active_claim_recovers_serially_after_error(self):
        original_recover = jobs.recover_jobs
        runtime_entered, runtime_release = threading.Event(), threading.Event()
        recover_entered, recover_release = threading.Event(), threading.Event()
        block_next = threading.Event()
        lock = threading.Lock()
        state = {"calls": 0, "active": 0, "peak": 0, "real_successes": 0}

        def controlled_recover(**kwargs):
            with lock:
                state["calls"] += 1
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
                block = block_next.is_set()
                if block:
                    block_next.clear()
            try:
                if block:
                    recover_entered.set()
                    if not recover_release.wait(8):
                        raise AssertionError("Controlled recovery was not released")
                    raise RuntimeError("controlled recovery boundary failure")
                result = original_recover(**kwargs)
                with lock:
                    state["real_successes"] += 1
                return result
            finally:
                with lock:
                    state["active"] -= 1

        def blocked_runtime(**kwargs):
            block_next.set()
            runtime_entered.set()
            if not runtime_release.wait(8):
                raise AssertionError("Controlled active claim was not released")
            raise cover_runtime.CoverRuntimeError("COVER_MAINTENANCE_FIXTURE_FINISHED")

        worker = service.CoverWorker()
        tasks_before = set(asyncio.all_tasks())
        direct = None
        with mock.patch.object(jobs, "recover_jobs", side_effect=controlled_recover), \
                mock.patch.object(cover_runtime, "run_cover", side_effect=blocked_runtime):
            worker.start()
            try:
                dispatch = worker.task
                worker.start()
                self.assertIs(worker.task, dispatch)
                await self.wait_until(lambda: state["real_successes"] == 1)
                await asyncio.sleep(.1)
                self.assertEqual(state["calls"], 1, "Idle maintenance must add no DB scans")
                self.fixture.submit(key="active-only-maintenance")
                await self.wait_until(runtime_entered.is_set)
                await self.wait_until(recover_entered.is_set)
                held = state["calls"]
                direct = asyncio.create_task(asyncio.to_thread(service.run_next))
                await asyncio.sleep(.06)
                self.assertEqual(state["calls"], held)
                self.assertEqual(state["peak"], 1)
                self.assertFalse(direct.done())
                recover_release.set()
                await asyncio.wait_for(direct, 2)
                await self.wait_until(lambda: state["real_successes"] >= 4)
                self.assertEqual(state["peak"], 1)
                runtime_release.set()
                await asyncio.wait_for(worker.stop(), 2)
                self.assertEqual(state["active"], 0)
                await asyncio.sleep(0)
                self.assertFalse([t for t in asyncio.all_tasks() - tasks_before if not t.done()])
                self.assertEqual(db.fetchone("SELECT count(*) FROM public_trial_calls")[0], 0)
                print("COVER_WORKER_MAINTENANCE_SERIAL_PROOF=" + json.dumps({
                    "real_worker_and_DB": True, "idle_extra_maintenance_DB_scans": 0,
                    "active_real_claim_enables_maintenance": True,
                    "recovery_peak_across_dispatch_and_maintenance": state["peak"],
                    "known_recovery_error_then_real_success": True, "start_idempotent": True,
                    "stop_joined_all_owned_work": True, "supplier_calls": 0}, sort_keys=True))
            finally:
                recover_release.set()
                runtime_release.set()
                if direct is not None:
                    await asyncio.wait_for(direct, 3)
                await asyncio.wait_for(worker.stop(), 3)

    async def test_cancelled_stop_still_joins_its_original_recovery_thread(self):
        original_recover = jobs.recover_jobs
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        calls = []

        def blocked_recover(**kwargs):
            calls.append(threading.get_ident())
            if len(calls) == 1:
                entered.set()
                try:
                    if not release.wait(8):
                        raise AssertionError("Controlled stop recovery was not released")
                    return original_recover(**kwargs)
                finally:
                    finished.set()
            return original_recover(**kwargs)

        worker = service.CoverWorker()
        tasks_before = set(asyncio.all_tasks())
        with mock.patch.object(jobs, "recover_jobs", side_effect=blocked_recover):
            worker.start()
            try:
                await self.wait_until(entered.is_set)
                stopping = asyncio.create_task(worker.stop())
                await asyncio.sleep(.03)
                stopping.cancel()
                await asyncio.sleep(.03)
                self.assertFalse(stopping.done())
                self.assertFalse(finished.is_set())
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(stopping, 2)
                self.assertTrue(finished.is_set())
                self.assertTrue(worker.task.done())
                self.assertTrue(worker.maintenance_task.done())
                await asyncio.sleep(0)
                self.assertFalse([t for t in asyncio.all_tasks() - tasks_before if not t.done()])
                self.assertEqual(db.fetchone("SELECT count(*) FROM public_trial_calls")[0], 0)
                print("COVER_WORKER_MAINTENANCE_STOP_PROOF=" + json.dumps({
                    "cancelled_stop_waited_for_original_recovery": True,
                    "owned_tasks_joined": True, "supplier_calls": 0}, sort_keys=True))
            finally:
                release.set()
                await asyncio.wait_for(worker.stop(), 3)

    async def test_parallel_direct_claims_keep_maintenance_active_and_late_waiter_skips_after_last_claim(self):
        first = self.fixture.submit(key="direct-first-active")
        second = self.second_owner_job()
        entered = {first["job_id"]: threading.Event(), second["job_id"]: threading.Event()}
        release = {key: threading.Event() for key in entered}
        held_recover, release_recover, block_next = threading.Event(), threading.Event(), threading.Event()
        lock = threading.Lock()
        state = {"calls": 0}
        recovery_waiter = threading.Event()
        recovery_mutex = threading.Lock()

        class ObservedRecoveryLock:
            def __enter__(self):
                if recovery_mutex.locked():
                    recovery_waiter.set()
                recovery_mutex.acquire()

            def __exit__(self, *exc):
                recovery_mutex.release()

        original_recover = jobs.recover_jobs
        actual_run_next = service.run_next

        def recover(**kwargs):
            with lock:
                state["calls"] += 1
                block = block_next.is_set()
                if block:
                    block_next.clear()
            if block:
                held_recover.set()
                if not release_recover.wait(8):
                    raise AssertionError("Controlled late recovery was not released")
            return original_recover(**kwargs)

        def blocked_runtime(**kwargs):
            key = kwargs["job_id"]
            entered[key].set()
            if not release[key].wait(8):
                raise AssertionError("Controlled direct claim was not released")
            raise cover_runtime.CoverRuntimeError("COVER_MAINTENANCE_DIRECT_FIXTURE_FINISHED")

        worker = service.CoverWorker()
        tasks_before = set(asyncio.all_tasks())
        running = []
        with mock.patch.object(jobs, "recover_jobs", side_effect=recover), \
                mock.patch.object(cover_runtime, "run_cover", side_effect=blocked_runtime), \
                mock.patch.object(service, "run_next", return_value=None), \
                mock.patch.object(service, "_COVER_RECOVERY_LOCK", ObservedRecoveryLock()):
            try:
                running.append(asyncio.create_task(asyncio.to_thread(actual_run_next)))
                await self.wait_until(entered[first["job_id"]].is_set)
                running.append(asyncio.create_task(asyncio.to_thread(actual_run_next)))
                await self.wait_until(entered[second["job_id"]].is_set)
                worker.start()
                await asyncio.sleep(.06)
                release[first["job_id"]].set()
                first_result = await asyncio.wait_for(running[0], 2)
                self.assertEqual(first_result["status"], "failed")
                self.assertFalse(running[1].done())
                count = state["calls"]
                await self.wait_until(lambda: state["calls"] >= count + 3, seconds=.5)
                # A waiting maintenance tick checked while a claim was active.
                # End the last claim while it waits for the shared recovery lock.
                block_next.set()
                running.append(asyncio.create_task(asyncio.to_thread(actual_run_next)))
                await self.wait_until(held_recover.is_set)
                await self.wait_until(recovery_waiter.is_set)
                release[second["job_id"]].set()
                second_result = await asyncio.wait_for(running[1], 2)
                self.assertEqual(second_result["status"], "failed")
                last = state["calls"]
                release_recover.set()
                self.assertIsNone(await asyncio.wait_for(running[2], 2))
                await asyncio.sleep(.06)
                self.assertEqual(state["calls"], last, "Late waiter must recheck active claims before DB")
                await asyncio.wait_for(worker.stop(), 2)
                self.assertEqual(self.admission.operations, {})
                self.assertEqual(db.fetchone("SELECT count(*) FROM public_trial_calls")[0], 0)
                await asyncio.sleep(0)
                self.assertFalse([t for t in asyncio.all_tasks() - tasks_before if not t.done()])
                print("COVER_WORKER_MAINTENANCE_ACTIVE_COUNT_PROOF=" + json.dumps({
                    "two_actual_direct_run_next_claims": True,
                    "first_finisher_did_not_disable_second_claim_maintenance": True,
                    "waiting_tick_rechecked_zero_after_last_claim": True,
                    "idle_extra_maintenance_DB_scans": 0, "supplier_calls": 0}, sort_keys=True))
            finally:
                release_recover.set()
                for event in release.values():
                    event.set()
                await asyncio.gather(*running, return_exceptions=True)
                await asyncio.wait_for(worker.stop(), 3)
