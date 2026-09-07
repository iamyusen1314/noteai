import hashlib
import fcntl
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import execute_item32_readonly_trends_successor as successor


def completed(args, stdout=b"", returncode=0):
    return subprocess.CompletedProcess(args, returncode, stdout, b"")


class Item32ReadonlySuccessorExecutorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_readback_never_creates_state_or_calls_execution_tools(self):
        with mock.patch.object(successor, "WORK_ROOT", self.root / "absent"), mock.patch.object(
            successor, "execute", side_effect=AssertionError("execution forbidden")
        ), mock.patch.object(successor, "_run", side_effect=AssertionError("external forbidden")), mock.patch.object(
            successor, "_read_secret_env", side_effect=AssertionError("Secret forbidden")
        ):
            self.assertEqual(successor.main(["--readback-only"]), 2)
            self.assertFalse((self.root / "absent").exists())

    def test_readback_missing_bound_run_busy_lock_and_symlink_stay_unknown(self):
        work = self.root / "work"
        work.mkdir(mode=0o700)
        lock_path = work / "executor.lock"
        lock_path.write_bytes(b"")
        lock_path.chmod(0o600)
        with mock.patch.object(successor, "WORK_ROOT", work):
            self.assertEqual(successor.read_retained_result()["status"], "UNKNOWN_HOLD")
            with lock_path.open("rb") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertEqual(successor.read_retained_result()["status"], "UNKNOWN_HOLD")
            (work / "item32-admission.json").symlink_to(self.root / "not-to-read")
            self.assertEqual(successor.read_retained_result()["status"], "UNKNOWN_HOLD")

    def snapshot_bytes(self, *, real_per_domain=12, baseline_per_domain=3):
        generated_at = "2026-09-07T00:04:00+00:00"
        domains = {}
        for domain in successor.DOMAINS:
            real_rows = [
                {
                    "keyword": f"{domain}-real-{index}",
                    "search_vol": 80,
                    "trend_dir": 1,
                    "source": (
                        "search_recommend"
                        if index == 0
                        else "search_phrase"
                    ),
                    "category": domain,
                    "sample_count": 1,
                    "quality_score": 80,
                    "evidence_level": "strong",
                    "quality_reason": "bounded real source",
                    "captured_at": generated_at,
                }
                for index in range(real_per_domain)
            ]
            baseline_rows = [
                {
                    "keyword": f"{domain}-baseline-{index}",
                    "search_vol": 45,
                    "trend_dir": 0,
                    "source": successor.BASELINE_SOURCE,
                    "category": domain,
                    "sample_count": 3,
                    "quality_score": 80,
                    "evidence_level": "strong",
                    "quality_reason": "labelled industry baseline",
                    "captured_at": generated_at,
                }
                for index in range(baseline_per_domain)
            ]
            domains[domain] = {
                "captured_at": generated_at,
                "keywords": real_rows + baseline_rows,
            }
        return json.dumps(
            {
                "schema_version": 1,
                "generated_at": generated_at,
                "freshness_max_hours": 30,
                "domains": domains,
            },
            ensure_ascii=False,
        ).encode()

    def test_snapshot_quality_separates_real_rows_from_labelled_baseline(self):
        counts, search_domains, recommend_domains, total = successor._snapshot_quality(
            self.snapshot_bytes(),
            execution_started_at="2026-09-07T00:03:00+00:00",
            execution_finished_at="2026-09-07T00:05:00+00:00",
        )
        self.assertEqual(counts, {domain: 12 for domain in successor.DOMAINS})
        self.assertEqual(set(search_domains), successor.DOMAINS)
        self.assertEqual(set(recommend_domains), successor.DOMAINS)
        self.assertEqual(total, 90)

    def test_labelled_baseline_cannot_satisfy_real_count(self):
        with self.assertRaisesRegex(successor.Item32Error, "snapshot_quality"):
            successor._snapshot_quality(
                self.snapshot_bytes(real_per_domain=11, baseline_per_domain=4),
                execution_started_at="2026-09-07T00:03:00+00:00",
                execution_finished_at="2026-09-07T00:05:00+00:00",
            )

    def test_committed_plan_binds_executor_adapter_and_hold_closure(self):
        plan = ROOT / "deploy/production/plans/item32-readonly-successor-20260907.json"
        loaded, digest = successor._load_plan(
            plan,
            ROOT / "tools/execute_item32_readonly_trends_successor.py",
            ROOT / "model/spider_xhs_http.py",
            ROOT / successor.HOLD_EVIDENCE_REF,
        )
        self.assertEqual(loaded["schema"], successor.PLAN_SCHEMA)
        self.assertEqual(
            loaded["browser_binding"]["user_agent"],
            successor.SIGNER_USER_AGENT,
        )
        self.assertEqual(digest, hashlib.sha256(plan.read_bytes()).hexdigest())

        changed = dict(loaded)
        changed["provider_calls_dispatched"] = 1
        candidate = self.root / "plan.json"
        candidate.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaisesRegex(successor.Item32Error, "plan_binding"):
            successor._load_plan(
                candidate,
                ROOT / "tools/execute_item32_readonly_trends_successor.py",
                ROOT / "model/spider_xhs_http.py",
                ROOT / successor.HOLD_EVIDENCE_REF,
            )

    def test_utc_budget_waits_for_fresh_bucket_and_requires_zero_prior(self):
        plan = {
            "admission": {
                "not_before_utc": successor.NOT_BEFORE_UTC,
                "bucket_date_utc": successor.BUCKET_DATE_UTC,
                "dispatch_deadline_utc": successor.DISPATCH_DEADLINE_UTC,
                "must_finish_before_utc": successor.BUCKET_END_UTC,
            }
        }
        predecessor = {"call_dates": ["2026-09-05", "2026-09-06"]}
        with self.assertRaisesRegex(
            successor.Item32Error, "utc_budget_not_available"
        ):
            successor._admission_budget(
                plan,
                predecessor,
                now=datetime(2026, 9, 6, 23, 59, tzinfo=timezone.utc),
            )
        budget = successor._admission_budget(
            plan,
            predecessor,
            now=datetime(2026, 9, 7, 0, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(
            budget,
            {
                "bucket_date": "2026-09-07",
                "used_before": 0,
                "remaining_before": 34,
                "planned": 34,
                "limit": 34,
            },
        )
        with self.assertRaisesRegex(
            successor.Item32Error, "utc_budget_not_available"
        ):
            successor._admission_budget(
                plan,
                {"call_dates": ["2026-09-05", "2026-09-07"]},
                now=datetime(2026, 9, 7, 0, 1, tzinfo=timezone.utc),
            )
        with self.assertRaisesRegex(
            successor.Item32Error, "utc_budget_not_available"
        ):
            successor._admission_budget(
                plan,
                predecessor,
                now=datetime(2026, 9, 8, 0, 0, tzinfo=timezone.utc),
            )

    def test_dispatch_requires_fresh_runtime_readback_and_bucket_margin(self):
        plan = {
            "admission": {
                "bucket_date_utc": successor.BUCKET_DATE_UTC,
                "dispatch_deadline_utc": successor.DISPATCH_DEADLINE_UTC,
                "must_finish_before_utc": successor.BUCKET_END_UTC,
            }
        }
        budget = {"bucket_date": successor.BUCKET_DATE_UTC}
        successor._assert_dispatch_window(
            plan,
            budget,
            {"observed_at": "2026-09-07T12:00:00+00:00"},
            now=datetime(2026, 9, 7, 12, 10, tzinfo=timezone.utc),
        )
        for observed_at, now in (
            (
                "2026-09-07T11:00:00+00:00",
                datetime(2026, 9, 7, 12, 10, tzinfo=timezone.utc),
            ),
            (
                "2026-09-07T23:39:00+00:00",
                datetime(2026, 9, 7, 23, 40, tzinfo=timezone.utc),
            ),
        ):
            with self.subTest(observed_at=observed_at, now=now):
                with self.assertRaisesRegex(
                    successor.Item32Error, "dispatch_window"
                ):
                    successor._assert_dispatch_window(
                        plan,
                        budget,
                        {"observed_at": observed_at},
                        now=now,
                    )

    def test_new_admission_is_exclusive_bound_and_no_replay(self):
        work = self.root / "successor"
        work.mkdir()
        predecessor = {"closure_sha256": successor.HOLD_EVIDENCE_SHA256}
        budget = {
            "bucket_date": "2026-09-07",
            "used_before": 0,
            "remaining_before": 34,
            "planned": 34,
            "limit": 34,
        }
        with mock.patch.object(successor, "WORK_ROOT", work):
            successor._create_admission(
                "a" * 64,
                plan_sha256="b" * 64,
                predecessor=predecessor,
                budget=budget,
            )
            payload = json.loads(
                (work / "item32-admission.json").read_text(encoding="utf-8")
            )
            self.assertTrue(payload["no_replay"])
            self.assertEqual(payload["predecessor_closure_sha256"], successor.HOLD_EVIDENCE_SHA256)
            with self.assertRaisesRegex(
                successor.Item32Error, "item32_already_dispatched"
            ):
                successor._create_admission(
                    "c" * 64,
                    plan_sha256="d" * 64,
                    predecessor=predecessor,
                    budget=budget,
                )

    def test_predecessor_closure_binds_both_immutable_holds(self):
        original_root = self.root / "original"
        diagnostic_root = self.root / "diagnostic"
        database = original_root / "run-sealed" / "task-store" / "hot_keywords.db"
        database.parent.mkdir(parents=True)
        connection = sqlite3.connect(database)
        connection.execute(
            "CREATE TABLE xhs_trends_provider_attempts("
            "ordinal INTEGER,admitted_at TEXT,status TEXT)"
        )
        connection.execute(
            "INSERT INTO xhs_trends_provider_attempts VALUES(1,?,?)",
            ("2026-09-05T14:00:00+00:00", "failed"),
        )
        connection.commit()
        connection.close()
        store_raw = database.read_bytes()
        original = json.dumps(
            {
                "status": "HOLD",
                "provider_calls": 1,
                "outcome_unknown_count": 0,
                "automatic_retry_count": 0,
            },
            sort_keys=True,
        ).encode()
        result = json.dumps(
            {
                "schema": "noteai.item32.xhs_diagnostic_result.v1",
                "status": "DIAGNOSTIC_HOLD_UNKNOWN_NO_CREDIT",
                "readiness_credit": False,
                "result": {
                    "classification": "UNKNOWN_HOLD",
                    "provider_call_count": 1,
                    "outcome_unknown_count": 1,
                    "automatic_retry_count": 0,
                },
            },
            sort_keys=True,
        ).encode()
        result_sha = hashlib.sha256(result).hexdigest()
        diagnostic_admission = json.dumps(
            {
                "status": "HOLD_UNKNOWN",
                "provider_call_count": 1,
                "outcome_unknown_count": 1,
                "automatic_retry_count": 0,
                "no_replay": True,
                "result_sha256": result_sha,
            },
            sort_keys=True,
        ).encode()
        original_sha = hashlib.sha256(original).hexdigest()
        diagnostic_admission_sha = hashlib.sha256(diagnostic_admission).hexdigest()
        store_sha = hashlib.sha256(store_raw).hexdigest()
        closure = {
            "schema": successor.HOLD_EVIDENCE_SCHEMA,
            "status": "DIAGNOSTIC_HOLD_UNKNOWN_NO_CREDIT",
            "readiness_credit": False,
            "classification": "UNKNOWN_HOLD",
            "admission_status": "HOLD_UNKNOWN",
            "no_replay": True,
            "retained_audit_boundary": {
                "admission_sha256": diagnostic_admission_sha,
                "result_sha256": result_sha,
                "admission_bound_result_sha256": result_sha,
                "admission_result_sha256_match": True,
            },
            "diagnostic_attempt": {
                "observed_at": "2026-09-06T06:33:07+00:00",
                "provider_call_count": 1,
                "outcome_unknown_count": 1,
                "automatic_retry_count": 0,
                "response_received": False,
            },
            "sealed_prior_attempt": {
                "admission_sha256": original_sha,
                "isolated_store_sha256": store_sha,
                "provider_call_count": 1,
                "outcome_unknown_count": 0,
                "automatic_retry_count": 0,
                "no_replay": True,
            },
            "counters": {
                "cumulative_provider_call_count": 2,
                "automatic_retry_count": 0,
                "production_database_writes": 0,
            },
            "acceptance": {
                "item32_credit": False,
                "further_xhs_provider_actions_authorized": False,
            },
        }
        closure_path = self.root / "closure.json"
        closure_path.write_text(json.dumps(closure, sort_keys=True), encoding="utf-8")
        closure_sha = hashlib.sha256(closure_path.read_bytes()).hexdigest()
        reads = {
            original_root / "item32-admission.json": original,
            diagnostic_root / "admission.json": diagnostic_admission,
            diagnostic_root / "result.json": result,
        }
        original_reader = successor._read_regular_file

        def read(path, *, max_size, root_only):
            if path in reads:
                return reads[path]
            return original_reader(path, max_size=max_size, root_only=root_only)

        patches = (
            mock.patch.object(successor, "HOLD_EVIDENCE_SHA256", closure_sha),
            mock.patch.object(successor, "EXPECTED_ORIGINAL_ADMISSION_SHA256", original_sha),
            mock.patch.object(successor, "EXPECTED_ORIGINAL_STORE_SHA256", store_sha),
            mock.patch.object(successor, "EXPECTED_DIAGNOSTIC_ADMISSION_SHA256", diagnostic_admission_sha),
            mock.patch.object(successor, "EXPECTED_DIAGNOSTIC_RESULT_SHA256", result_sha),
            mock.patch.object(successor, "SEALED_ORIGINAL_ROOT", original_root),
            mock.patch.object(successor, "SEALED_ORIGINAL_ADMISSION", original_root / "item32-admission.json"),
            mock.patch.object(successor, "SEALED_DIAGNOSTIC_ROOT", diagnostic_root),
            mock.patch.object(successor, "SEALED_DIAGNOSTIC_ADMISSION", diagnostic_root / "admission.json"),
            mock.patch.object(successor, "SEALED_DIAGNOSTIC_RESULT", diagnostic_root / "result.json"),
            mock.patch.object(successor, "_read_regular_file", side_effect=read),
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10]:
            verified = successor._verify_predecessors({}, closure_path)
        self.assertEqual(verified["call_dates"], ["2026-09-05", "2026-09-06"])
        self.assertEqual(database.read_bytes(), store_raw)

    def test_collection_mounts_only_task_store_and_exact_adapter_overlay(self):
        run_dir = self.root / "run"
        runtime_dir = self.root / "runtime"
        adapter = self.root / "spider_xhs_http.py"
        run_dir.mkdir()
        runtime_dir.mkdir()
        adapter.write_text("# synthetic adapter", encoding="utf-8")
        container_id = "a" * 64
        calls = []

        def fake_run(args, **_kwargs):
            calls.append(args)
            if args[:2] == ["docker", "create"]:
                return completed(args, (container_id + "\n").encode())
            if args[:2] == ["docker", "inspect"]:
                task_dir = run_dir / "task-store"
                return completed(
                    args,
                    json.dumps([
                        {
                            "Image": successor.IMAGE,
                            "Config": {
                                "Env": [
                                    "NOTEAI_XHS_COOKIES_JSON=[]",
                                    "NOTEAI_SQLITE_PATH=/task/noteai.db",
                                    "NOTEAI_HOT_KEYWORD_DB_PATH=/task/hot_keywords.db",
                                ],
                                "Cmd": ["python", "market_timing_worker.py", "--once"],
                            },
                            "Mounts": [
                                {"Destination": "/task", "Source": str(task_dir), "RW": True},
                                {"Destination": successor.ADAPTER_CONTAINER_PATH, "Source": str(adapter), "RW": False},
                            ],
                            "HostConfig": {
                                "ReadonlyRootfs": True,
                                "Privileged": False,
                                "CapDrop": ["ALL"],
                            },
                        }
                    ]).encode(),
                )
            return completed(args)

        registry = {}
        with mock.patch.object(successor, "_run", side_effect=fake_run), mock.patch.object(successor.os, "chown"):
            _name, actual_id, cookie_env = successor._create_collection_container(
                run_dir, runtime_dir, "[]", adapter, registry
            )
        self.assertEqual(actual_id, container_id)
        self.assertEqual(registry, {_name: container_id})
        create = next(call for call in calls if call[:2] == ["docker", "create"])
        self.assertIn(
            f"type=bind,src={adapter},dst={successor.ADAPTER_CONTAINER_PATH},readonly",
            create,
        )
        self.assertNotIn("DATABASE_URL", "\n".join(create))
        self.assertFalse(cookie_env.exists())

    def test_predecessor_rejection_happens_before_secret_or_provider_setup(self):
        lock = os.open(self.root / "lock", os.O_RDWR | os.O_CREAT, 0o600)
        secret = mock.Mock()
        with mock.patch.object(successor.os, "geteuid", return_value=0), mock.patch.object(
            successor, "_load_plan", return_value=({}, "a" * 64)
        ), mock.patch.object(successor, "_ensure_work_root"), mock.patch.object(
            successor, "_acquire_executor_lock", return_value=lock
        ), mock.patch.object(successor, "WORK_ROOT", self.root / "work"), mock.patch.object(
            successor, "EXPORT_ROOT", self.root / "export"
        ), mock.patch.object(
            successor, "_acquire_predecessor_locks", return_value=[]
        ), mock.patch.object(
            successor,
            "_verify_predecessors",
            side_effect=successor.Item32Error("predecessor_digest"),
        ), mock.patch.object(successor, "_read_secret_env", secret):
            with self.assertRaisesRegex(successor.Item32Error, "predecessor_digest"):
                successor.execute(
                    self.root / "plan",
                    self.root / "executor",
                    self.root / "adapter",
                    self.root / "closure",
                )
        secret.assert_not_called()

    def test_export_is_fd_copied_from_protected_staging(self):
        work = self.root / "work"
        export = self.root / "export"
        run = work / "run-fixed"
        work.mkdir(mode=0o700)
        export.mkdir(mode=0o755)
        run.mkdir(mode=0o700)
        candidate = run / "item32-evidence.candidate.tar.gz"
        candidate.write_bytes(b"canonical-item32-evidence")
        candidate.chmod(0o600)
        account = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
        with mock.patch.object(successor, "WORK_ROOT", work), mock.patch.object(
            successor, "EXPORT_ROOT", export
        ), mock.patch.object(
            successor, "_validated_export_account", return_value=account
        ):
            staged = successor._stage_export(candidate)
            self.assertEqual(staged.parent, work)
            self.assertEqual(staged.read_bytes(), candidate.read_bytes())
            self.assertEqual(staged.stat().st_mode & 0o777, 0o600)
            published = successor._publish_export(staged)
        self.assertFalse(staged.exists())
        self.assertEqual(published.parent, export)
        self.assertEqual(published.read_bytes(), candidate.read_bytes())
        self.assertEqual(published.stat().st_mode & 0o777, 0o600)

    def test_publish_never_replaces_an_existing_export(self):
        work = self.root / "work"
        export = self.root / "export"
        run = work / "run-fixed"
        work.mkdir(mode=0o700)
        export.mkdir(mode=0o755)
        run.mkdir(mode=0o700)
        candidate = run / "item32-evidence.candidate.tar.gz"
        candidate.write_bytes(b"candidate")
        candidate.chmod(0o600)
        account = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
        with mock.patch.object(successor, "WORK_ROOT", work), mock.patch.object(
            successor, "EXPORT_ROOT", export
        ), mock.patch.object(
            successor, "_validated_export_account", return_value=account
        ):
            staged = successor._stage_export(candidate)
            public_name = staged.name[1:-len(".candidate")]
            existing = export / public_name
            existing.write_bytes(b"existing")
            with self.assertRaises(FileExistsError):
                successor._publish_export(staged)
        self.assertEqual(existing.read_bytes(), b"existing")
        self.assertTrue(staged.exists())


if __name__ == "__main__":
    unittest.main()
