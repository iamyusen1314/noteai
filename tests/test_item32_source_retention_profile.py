"""Prospective source-retention profile; synthetic local evidence, no dispatch."""
import copy
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import unittest
from unittest import mock

from tests import test_item32_v5_profile as prior

e, ROOT = prior.e, prior.ROOT


class SourceRetentionProfileTests(unittest.TestCase):
    def setUp(self):
        self.f = f = prior.V5ProfileTests()
        f.setUp(); self.addCleanup(f.tearDown)
        f.plan["admission"].update(work_root=str(e.V5_SOURCE_RETENTION_WORK_ROOT),
            not_before_utc="2026-09-18T06:30:00+00:00", bucket_date_utc="2026-09-18",
            dispatch_deadline_utc="2026-09-18T07:25:00+00:00", must_finish_before_utc="2026-09-18T08:00:00+00:00")
        f.plan["runtime_overlay_sha256"] = {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest()
                                            for n in e.V5_SOURCE_RETENTION_OVERLAYS}
        f.plan["source_sha256"] = {**f.plan["image_source_sha256"], **f.plan["runtime_overlay_sha256"]}
        f.plan["previous_v5_successor"] = e._sep17_previous_binding(ROOT)
        f.plan.update(e._network_repair_bindings(ROOT))
        f.plan["previous_v5_full_cycle_hold"] = e._source_retention_previous_binding(ROOT)
        self.authorize()

    def authorize(self):
        self.f.plan["authorization"] = {"status": "AUTHORIZED", "confirmed_at_utc": "2026-09-18T05:00:00+00:00",
            "approved_scope_sha256": e._approval_scope_sha256(self.f.plan)}

    def test_exact_new_root_eight_overlays_and_all_prior_calls_remain_bound(self):
        plan, _ = self.f.load()
        self.assertEqual(e.WORK_ROOT, e.V5_SOURCE_RETENTION_WORK_ROOT)
        self.assertEqual(len(e._runtime_overlay_paths(ROOT / e.ADAPTER_SOURCE_REF)), 8)
        old = plan["previous_v5_full_cycle_hold"]
        self.assertEqual((old["collection_admissions"], old["initialization_count"], old["physical_http_count"]), (34, 2, 36))
        self.assertEqual((len(old["files"]), len(old["previous_files"])), (12, 36))
        self.assertEqual(plan["previous_v5_initialization_hold"]["initialization_outcome_unknown_count"], 1)

    def test_pending_and_prior_cycle_authority_cannot_activate_new_profile(self):
        self.f.plan["authorization"] = {"status": "PENDING", "confirmed_at_utc": None, "approved_scope_sha256": None}
        with self.assertRaisesRegex(e.Item32Error, "plan_not_authorized"): self.f.load()
        self.assertIsNone(e.ACTIVE_V5_PLAN)
        self.authorize(); self.f.plan["authorization"]["confirmed_at_utc"] = "2026-09-17T15:16:30+00:00"
        with self.assertRaisesRegex(e.Item32Error, "plan_binding"): self.f.load()

    def test_reauthorization_does_not_allow_old_counts_or_missing_seal_or_changed_budget(self):
        baseline = copy.deepcopy(self.f.plan)
        for field, value in (("collection_admissions", 0), ("outcome_unknown_count", 1),
                             ("automatic_retry_count", False), ("no_replay", 1)):
            with self.subTest(field=field):
                self.f.plan = copy.deepcopy(baseline)
                self.f.plan["previous_v5_full_cycle_hold"][field] = value; self.authorize()
                with self.assertRaisesRegex(e.Item32Error, "plan_binding"): self.f.load()
        self.f.plan = copy.deepcopy(baseline); self.f.plan.pop("previous_v5_full_cycle_hold"); self.authorize()
        with self.assertRaisesRegex(e.Item32Error, "plan_binding"): self.f.load()
        self.f.plan = copy.deepcopy(baseline); self.f.plan["physical_http_budget"]["collection"] = 35; self.authorize()
        with self.assertRaisesRegex(e.Item32Error, "plan_binding"): self.f.load()

    def test_both_actual_repair_files_and_exact_future_window_are_required(self):
        baseline = copy.deepcopy(self.f.plan)
        for name in ("model/trends_contract.py", "model/market_timing_worker.py"):
            self.f.plan = copy.deepcopy(baseline); self.f.plan["runtime_overlay_sha256"].pop(name); self.authorize()
            with self.assertRaisesRegex(e.Item32Error, "plan_binding"): self.f.load()
        self.f.plan = copy.deepcopy(baseline)
        self.f.plan["admission"]["dispatch_deadline_utc"] = "2026-09-18T07:26:00+00:00"; self.authorize()
        with self.assertRaisesRegex(e.Item32Error, "plan_binding"): self.f.load()

    def test_old_profile_still_rejects_the_eight_overlay_scope(self):
        self.f.plan["admission"]["work_root"] = str(e.V5_NETWORK_WORK_ROOT)
        self.f.plan.pop("previous_v5_full_cycle_hold")
        self.authorize()
        with self.assertRaisesRegex(e.Item32Error, "plan_binding"): self.f.load()

    def test_expired_window_remains_rejected_even_with_its_own_scope_digest(self):
        self.f.plan["admission"].update(not_before_utc="2026-09-18T00:00:00+00:00",
            dispatch_deadline_utc="2026-09-18T00:55:00+00:00", must_finish_before_utc="2026-09-18T01:30:00+00:00")
        self.authorize()
        self.f.plan["authorization"]["confirmed_at_utc"] = "2026-09-17T16:22:00+00:00"
        with self.assertRaisesRegex(e.Item32Error, "plan_binding"): self.f.load()

    def test_new_dispatch_start_is_inclusive_and_deadline_is_exclusive(self):
        self.f.load()
        previous = {"call_dates": ["2026-09-17"] * 34}
        for clock, allowed in (("06:29:59", False), ("06:30:00", True),
                               ("07:24:59", True), ("07:25:00", False)):
            with self.subTest(clock=clock):
                now = datetime.fromisoformat(f"2026-09-18T{clock}+00:00")
                budget = {"bucket_date": "2026-09-18"}
                runtime = {"observed_at": now.isoformat()}
                if allowed:
                    self.assertEqual(e._admission_budget(self.f.plan, previous, now=now)["remaining_before"], 34)
                    e._assert_dispatch_window(self.f.plan, budget, runtime, now=now)
                else:
                    with self.assertRaisesRegex(e.Item32Error, "utc_budget_not_available"):
                        e._admission_budget(self.f.plan, previous, now=now)
                    with self.assertRaisesRegex(e.Item32Error, "dispatch_window"):
                        e._assert_dispatch_window(self.f.plan, budget, runtime, now=now)

    def test_old_full_cycle_cannot_be_omitted_from_daily_budget(self):
        self.f.load()
        previous = {"call_dates": ["2026-09-06"] * 2 + ["2026-09-15"] + ["2026-09-16"] * 11 + ["2026-09-17"] * 34}
        self.assertEqual(len(previous["call_dates"]), 48)
        actual = e._admission_budget(self.f.plan, previous, now=datetime.fromisoformat("2026-09-18T06:31:00+00:00"))
        self.assertEqual((actual["used_before"], actual["remaining_before"]), (0, 34))
        previous["call_dates"].append("2026-09-18")
        with self.assertRaisesRegex(e.Item32Error, "utc_budget_not_available"):
            e._admission_budget(self.f.plan, previous, now=datetime.fromisoformat("2026-09-18T06:31:00+00:00"))

    def test_all_six_prior_locks_include_consumed_full_cycle(self):
        roots = []
        for name in ("SEALED_ORIGINAL_ROOT", "SEALED_DIAGNOSTIC_ROOT", "SEALED_SUCCESSOR_ROOT",
                     "V5_WORK_ROOT", "V5_SEP17_WORK_ROOT", "V5_NETWORK_WORK_ROOT"):
            path = self.f.path / name; path.mkdir(); (path / "executor.lock").touch(mode=0o600)
            roots.append(path); self.f.stack.enter_context(mock.patch.object(e, name, path))
        self.f.stack.enter_context(mock.patch.object(e, "ACTIVE_V5_PLAN", self.f.plan))
        held = e._acquire_predecessor_locks()
        try: self.assertEqual(len(held), 6)
        finally:
            for fd in held: os.close(fd)
        fd = os.open(roots[-1] / "executor.lock", os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(e.Item32Error, "predecessor_active"): e._acquire_predecessor_locks()
        finally: os.close(fd)

    def test_new_readback_never_dispatches_and_keeps_old_identity_separate(self):
        with mock.patch.object(e, "read_retained_result", return_value={"status": "RETAINED_BYTES_READBACK_ONLY"}), \
                mock.patch.object(e, "execute") as dispatch, mock.patch("builtins.print"):
            self.assertEqual(e.main(["--v5-source-retention-readback-only"]), 0)
            self.assertEqual(e.WORK_ROOT, e.V5_SOURCE_RETENTION_WORK_ROOT)
            dispatch.assert_not_called()
            with self.assertRaises(SystemExit): e.main(["--v5-source-retention-readback-only", "--v5-network-repair-readback-only"])

    def test_original_seal_bytes_are_pinned(self):
        path = self.f.path / e.V5_NETWORK_FINAL_REF; path.parent.mkdir(parents=True)
        path.write_bytes((ROOT / e.V5_NETWORK_FINAL_REF).read_bytes())
        self.assertEqual(e._source_retention_previous_binding(self.f.path), self.f.plan["previous_v5_full_cycle_hold"])
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(e.Item32Error, "predecessor_final_seal"): e._source_retention_previous_binding(self.f.path)

    def test_host_immutable_ledger_reads_thirty_four_without_reclassifying_failure(self):
        seal_raw = (ROOT / e.V5_NETWORK_FINAL_REF).read_bytes(); seal = json.loads(seal_raw)
        root = self.f.path / "old-full-cycle"; run = root / seal["run_directory_name"]; run.mkdir(parents=True)
        self.f.stack.enter_context(mock.patch.object(e, "V5_NETWORK_WORK_ROOT", root))
        binding = copy.deepcopy(self.f.plan["previous_v5_full_cycle_hold"])
        admission = {**seal["admission"], "run_directory_name": run.name, "budget": {"bucket_date": "2026-09-17"}}
        files = {root / "item32-admission.json": admission, run / "worker-receipt.json": seal["worker_receipt"]}
        files.update({run / f"database-{phase}-probe.json": seal["database_probes"][phase] for phase in ("before", "after")})
        for path, value in files.items(): path.write_bytes(e._json_bytes(value)); path.chmod(0o600)
        database = run / "task-store/hot_keywords.db"; database.parent.mkdir()
        with sqlite3.connect(database) as conn:
            conn.execute("CREATE TABLE xhs_trends_provider_attempts(ordinal,endpoint,status,admitted_at,admitted_date,completed_at)")
            conn.executemany("INSERT INTO xhs_trends_provider_attempts VALUES (?,?,?,?,?,?)", [
                (i+1, endpoint, "succeeded", "2026-09-17T16:05:10+00:00", "2026-09-17", "2026-09-17T16:05:11+00:00")
                for i, endpoint in enumerate(e.ENDPOINT_SEQUENCE)])
            conn.execute("CREATE TABLE xhs_trends_runs(status,provider_attempt_count,last_error_code,snapshot_size)")
            conn.execute("INSERT INTO xhs_trends_runs VALUES ('failed',34,'trends_current_run_xhs_evidence_incomplete',0)")
        database.chmod(0o644)
        empty_lock = root / "executor.lock"; empty_lock.touch(mode=0o600)
        lock_descriptor = os.open(empty_lock, os.O_RDONLY)
        self.f.stack.callback(os.close, lock_descriptor)
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        original = root / "old-proof.json"; original.write_bytes(b"synthetic prior proof"); original.chmod(0o600)
        def entry(path): return {"bytes": path.stat().st_size, "mode": oct(path.stat().st_mode & 0o777), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        binding["files"] = {str(p): entry(p) for p in (*files, database, empty_lock)}
        binding["previous_files"] = {str(original): entry(original)}
        path = root / "final.json"; path.write_bytes(seal_raw); path.chmod(0o600)
        binding["final_readback"]["host_ref"] = str(path)
        before = database.read_bytes()
        proof, dates = e._verify_full_cycle_hold(binding, lock_descriptor=lock_descriptor)
        self.assertTrue(proof["collection_ledger_verified"]); self.assertEqual(dates, ["2026-09-17"] * 34)
        self.assertEqual(before, database.read_bytes())
        with self.assertRaisesRegex(e.Item32Error, "predecessor_metadata"):
            e._read_regular_file(empty_lock, max_size=1, root_only=True)
        empty_lock.write_bytes(b"not empty")
        binding["files"][str(empty_lock)] = entry(empty_lock)
        with self.assertRaisesRegex(e.Item32Error, "predecessor_metadata"):
            e._verify_full_cycle_hold(binding, lock_descriptor=lock_descriptor)
        empty_lock.write_bytes(b""); binding["files"][str(empty_lock)] = entry(empty_lock)
        empty_lock.chmod(0o644)
        with self.assertRaisesRegex(e.Item32Error, "predecessor_metadata"):
            e._verify_full_cycle_hold(binding, lock_descriptor=lock_descriptor)
        empty_lock.chmod(0o600)
        with sqlite3.connect(database) as conn: conn.execute("UPDATE xhs_trends_provider_attempts SET status='failed' WHERE ordinal=34")
        binding["files"][str(database)] = entry(database)
        with self.assertRaisesRegex(e.Item32Error, "predecessor_store_shape"):
            e._verify_full_cycle_hold(binding, lock_descriptor=lock_descriptor)
        replacement = root / "replacement.lock"; replacement.touch(mode=0o600)
        os.replace(replacement, empty_lock)
        with self.assertRaisesRegex(e.Item32Error, "predecessor_metadata"):
            e._verify_full_cycle_hold(binding, lock_descriptor=lock_descriptor)


if __name__ == "__main__": unittest.main()
