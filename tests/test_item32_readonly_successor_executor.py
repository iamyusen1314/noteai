import hashlib
import fcntl
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from contextlib import ExitStack, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import execute_item32_readonly_trends_successor as successor


TEST_WINDOW = {
    "not_before_utc": "2026-09-07T00:00:00+00:00",
    "bucket_date_utc": "2026-09-07",
    "dispatch_deadline_utc": "2026-09-07T23:40:00+00:00",
    "must_finish_before_utc": "2026-09-08T00:00:00+00:00",
}


def completed(args, stdout=b"", returncode=0):
    return subprocess.CompletedProcess(args, returncode, stdout, b"")


class Item32CommandDiagnosticTests(unittest.TestCase):
    def test_failure_keeps_stable_error_and_only_fixed_diagnostic_fields(self):
        private = "cookie-value https://private.invalid/path secret-module /private/source.py"
        result = subprocess.CompletedProcess(["private-command", private], 1,
            private.encode(), ("ModuleNotFoundError: " + private).encode())
        output = io.StringIO()
        with mock.patch.object(successor.subprocess, "run", return_value=result) as run, redirect_stderr(output):
            with self.assertRaises(successor.Item32CommandError) as caught:
                successor._run(result.args, phase="RUNTIME_OVERLAY_CHECK")
        self.assertEqual(str(caught.exception), "command_failed")
        expected = {"event": "item32_host_command_failed", "phase": "RUNTIME_OVERLAY_CHECK",
            "returncode": 1, "stderr_category": "PYTHON_IMPORT_ERROR_PATTERN"}
        self.assertEqual(caught.exception.diagnostic, expected)
        self.assertEqual(json.loads(output.getvalue()), expected)
        self.assertNotIn(private, repr(caught.exception))
        self.assertNotIn(private, output.getvalue())
        self.assertEqual(run.call_count, 1)

    def test_fixed_categories_do_not_copy_exception_or_provider_content(self):
        cases = (
            (b"SyntaxError: private-syntax", "PYTHON_SYNTAX_ERROR_PATTERN"),
            (b"ImportError: private-module", "PYTHON_IMPORT_ERROR_PATTERN"),
            (b"PermissionError: private-path", "PYTHON_PERMISSION_ERROR_PATTERN"),
            (b"sqlite3.OperationalError: unable to open database file /private", "SQLITE_OPEN_ERROR_PATTERN"),
            (b"sqlite3.OperationalError: attempt to write a readonly database /private", "SQLITE_READ_ONLY_PATTERN"),
            (b"sqlite3.OperationalError: read-only file system /private", "READ_ONLY_FILESYSTEM_PATTERN"),
            (b"Cannot connect to the Docker daemon at private-address", "DOCKER_DAEMON_UNAVAILABLE_PATTERN"),
            (b'invalid mount config for type "bind": /private', "DOCKER_MOUNT_ERROR_PATTERN"),
            (b"authorization=private cookie=private https://private.invalid", "UNCLASSIFIED"),
        )
        for raw, expected in cases:
            with self.subTest(category=expected), mock.patch.object(successor.subprocess, "run",
                return_value=subprocess.CompletedProcess(["private"], 1, b"private-stdout", raw)
            ) as run, redirect_stderr(io.StringIO()) as output:
                with self.assertRaisesRegex(successor.Item32Error, "^command_failed$"):
                    successor._run(["private"])
                diagnostic = json.loads(output.getvalue())
                self.assertEqual(diagnostic["stderr_category"], expected)
                self.assertEqual(diagnostic["phase"], "HOST_COMMAND")
                self.assertNotIn("private", output.getvalue())
                self.assertEqual(run.call_count, 1)

    def test_merged_output_remains_private_and_returncode_does_not_claim_oom(self):
        result = subprocess.CompletedProcess(["private"], 137,
            b"cookie=private https://private.invalid", None)
        with mock.patch.object(successor.subprocess, "run", return_value=result) as run, redirect_stderr(io.StringIO()) as output:
            with self.assertRaises(successor.Item32CommandError):
                successor._run(["private"], stderr_to_stdout=True, phase="DB_BEFORE_PROBE")
        diagnostic = json.loads(output.getvalue())
        self.assertEqual(diagnostic["returncode"], 137)
        self.assertEqual(diagnostic["stderr_category"], "UNCLASSIFIED")
        self.assertNotIn("private", output.getvalue())
        self.assertEqual(run.call_count, 1)

    def test_success_and_unchecked_cleanup_keep_original_silent_behavior(self):
        for returncode, check in ((0, True), (1, False)):
            result = subprocess.CompletedProcess(["private"], returncode, b"private", b"private")
            with self.subTest(returncode=returncode), mock.patch.object(successor.subprocess, "run", return_value=result) as run, redirect_stderr(io.StringIO()) as output:
                self.assertIs(successor._run(["private"], check=check), result)
                self.assertEqual(output.getvalue(), "")
                self.assertEqual(run.call_count, 1)

    def test_dynamic_phase_is_rejected_before_command_without_echo(self):
        with mock.patch.object(successor.subprocess, "run", side_effect=AssertionError("command forbidden")) as run, redirect_stderr(io.StringIO()) as output:
            with self.assertRaisesRegex(successor.Item32Error, "^command_phase$"):
                successor._run(["unused"], phase="private https://private.invalid")
            run.assert_not_called()
            self.assertEqual(output.getvalue(), "")

    def test_main_preserves_exit_two_and_original_command_failed_line(self):
        result = subprocess.CompletedProcess(["private"], 1, b"private", b"private")
        with mock.patch.object(successor.subprocess, "run", return_value=result) as run, mock.patch.object(
            successor, "execute", side_effect=lambda *_args: successor._run(["private"], phase="RUNTIME_OVERLAY_CHECK")
        ), redirect_stderr(io.StringIO()) as output:
            self.assertEqual(successor.main(["--plan", "unused", "--adapter", "unused", "--hold-evidence", "unused"]), 2)
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["phase"], "RUNTIME_OVERLAY_CHECK")
        self.assertEqual(lines[1], "ITEM32_EXECUTION_REJECTED code=command_failed automatic_retry_count=0")
        self.assertNotIn("private", output.getvalue())
        self.assertEqual(run.call_count, 1)


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

    def test_frozen_plan_rejects_current_runtime_until_prospective_binding(self):
        plan = ROOT / "deploy/production/plans/item32-readonly-successor-20260907.json"
        original = plan.read_bytes()
        with self.assertRaisesRegex(successor.Item32Error, "plan_binding"):
            successor._load_plan(plan, ROOT / "tools/execute_item32_readonly_trends_successor.py",
                ROOT / "model/spider_xhs_http.py", ROOT / successor.HOLD_EVIDENCE_REF)
        loaded = json.loads(original)
        digest = hashlib.sha256(original).hexdigest()
        self.assertEqual(plan.read_bytes(), original)
        self.assertEqual(loaded["schema"], "noteai.item32.readonly_successor_plan.v1")
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

    def test_synthetic_authorized_plan_binds_effective_sources_without_changing_old_plan(self):
        original_path = ROOT / "deploy/production/plans/item32-readonly-successor-20260907.json"
        original = original_path.read_bytes()
        plan = json.loads((ROOT / "deploy/production/plans/item32-readonly-successor-prospective.json").read_text())
        plan["admission"].update(TEST_WINDOW)
        executor = ROOT / "tools/execute_item32_readonly_trends_successor.py"
        adapter = ROOT / successor.ADAPTER_SOURCE_REF
        plan["outer_executor_sha256"] = hashlib.sha256(executor.read_bytes()).hexdigest()
        plan["adapter_overlay_sha256"] = hashlib.sha256(adapter.read_bytes()).hexdigest()
        plan["source_sha256"] = {
            **successor.EXPECTED_IMAGE_SOURCE_SHA256, **successor.RUNTIME_OVERLAY_SHA256,
        }
        plan["authorization"] = {
            "status": "AUTHORIZED",
            "confirmed_at_utc": "2026-09-06T12:00:00+00:00",
            "approved_scope_sha256": successor._approval_scope_sha256(plan),
        }
        candidate = self.root / "plan.json"
        candidate.write_text(json.dumps(plan), encoding="utf-8")
        loaded, _ = successor._load_plan(
            candidate, executor, adapter, ROOT / successor.HOLD_EVIDENCE_REF,
        )
        self.assertEqual(loaded["source_sha256"], plan["source_sha256"])
        self.assertEqual(loaded["admission"]["bucket_date_utc"], "2026-09-07")
        self.assertEqual(original_path.read_bytes(), original)
        with self.assertRaisesRegex(successor.Item32Error, "utc_budget_not_available"):
            successor._admission_budget(loaded, {"call_dates": []},
                now=datetime(2026, 9, 15, tzinfo=timezone.utc))

    def test_utc_budget_waits_for_fresh_bucket_and_requires_zero_prior(self):
        plan = {
            "admission": {
                "not_before_utc": TEST_WINDOW["not_before_utc"],
                "bucket_date_utc": TEST_WINDOW["bucket_date_utc"],
                "dispatch_deadline_utc": TEST_WINDOW["dispatch_deadline_utc"],
                "must_finish_before_utc": TEST_WINDOW["must_finish_before_utc"],
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

    def synthetic_prospective_plan(self):
        canonical = ROOT / "deploy/production/plans/item32-readonly-successor-prospective.json"
        plan = json.loads(canonical.read_text())
        # The deployed plan keeps its original executor binding. Tests exercise
        # the local candidate using only temporary, explicitly synthetic copies.
        plan["outer_executor_sha256"] = hashlib.sha256(
            (ROOT / "tools/execute_item32_readonly_trends_successor.py").read_bytes()
        ).hexdigest()
        return plan

    def test_pending_plan_rejected_before_any_host_secret_or_admission_action(self):
        pending = self.synthetic_prospective_plan()
        pending["authorization"] = {
            "status": "PENDING", "confirmed_at_utc": None, "approved_scope_sha256": None,
        }
        plan = self.root / "pending-synthetic-only.json"
        plan.write_text(json.dumps(pending))
        with mock.patch.object(successor.os, "geteuid", return_value=0), mock.patch.object(
            successor, "_ensure_work_root", side_effect=AssertionError("state forbidden")
        ), mock.patch.object(successor, "_run", side_effect=AssertionError("host forbidden")), mock.patch.object(
            successor, "_read_secret_env", side_effect=AssertionError("Secret forbidden")
        ), mock.patch.object(successor, "_create_admission", side_effect=AssertionError("admission forbidden")):
            with self.assertRaisesRegex(successor.Item32Error, "plan_not_authorized"):
                successor.execute(plan, ROOT / "tools/execute_item32_readonly_trends_successor.py",
                    ROOT / successor.ADAPTER_SOURCE_REF, ROOT / successor.HOLD_EVIDENCE_REF)
        self.assertEqual(json.loads(plan.read_text())["authorization"], {
            "status": "PENDING", "confirmed_at_utc": None, "approved_scope_sha256": None,
        })

    def test_prospective_window_and_scope_approval_are_bound_without_code_dates(self):
        plan = self.synthetic_prospective_plan()
        plan["authorization"] = {
            "status": "AUTHORIZED", "confirmed_at_utc": "2026-09-15T12:00:00+00:00",
            "approved_scope_sha256": successor._approval_scope_sha256(plan),
        }
        candidate = self.root / "authorized-synthetic-only.json"
        candidate.write_text(json.dumps(plan))
        executor = ROOT / "tools/execute_item32_readonly_trends_successor.py"
        loaded, _ = successor._load_plan(candidate, executor,
            ROOT / successor.ADAPTER_SOURCE_REF, ROOT / successor.HOLD_EVIDENCE_REF)
        budget = successor._admission_budget(loaded, {"call_dates": ["2026-09-05", "2026-09-06"]},
            now=datetime(2026, 9, 15, 14, 0, tzinfo=timezone.utc))
        self.assertEqual((budget["bucket_date"], budget["used_before"], budget["remaining_before"]),
            ("2026-09-15", 0, 34))
        for now in (datetime(2026, 9, 15, 13, 59, tzinfo=timezone.utc),
                    datetime(2026, 9, 15, 14, 40, tzinfo=timezone.utc)):
            with self.assertRaisesRegex(successor.Item32Error, "utc_budget_not_available"):
                successor._admission_budget(loaded, {"call_dates": []}, now=now)
        plan["admission"]["not_before_utc"] = "2026-09-15T13:00:00+00:00"
        candidate.write_text(json.dumps(plan))
        with self.assertRaisesRegex(successor.Item32Error, "plan_authorization_binding"):
            successor._load_plan(candidate, executor, ROOT / successor.ADAPTER_SOURCE_REF,
                ROOT / successor.HOLD_EVIDENCE_REF)

    def test_plan_rejects_non_utc_cross_day_and_insufficient_cleanup_margin(self):
        original = json.loads((ROOT / "deploy/production/plans/item32-readonly-successor-prospective.json").read_text())["admission"]
        for field, value in (
            ("not_before_utc", "2026-09-15T22:00:00+08:00"),
            ("bucket_date_utc", "2026-09-16"),
            ("dispatch_deadline_utc", "2026-09-15T14:41:00+00:00"),
            ("must_finish_before_utc", "2026-09-16T01:00:00+00:00"),
        ):
            with self.subTest(field=field), self.assertRaises(successor.Item32Error):
                successor._plan_window({**original, field: value})

    def test_future_confirmation_cannot_authorize_a_future_window(self):
        plan = self.synthetic_prospective_plan()
        for field in ("not_before_utc", "bucket_date_utc", "dispatch_deadline_utc", "must_finish_before_utc"):
            plan["admission"][field] = plan["admission"][field].replace("2026-09-15", "2099-09-15")
        plan["authorization"] = {
            "status": "AUTHORIZED", "confirmed_at_utc": "2099-09-15T12:00:00+00:00",
            "approved_scope_sha256": successor._approval_scope_sha256(plan),
        }
        candidate = self.root / "future-confirmation-synthetic-only.json"
        candidate.write_text(json.dumps(plan))
        with self.assertRaisesRegex(successor.Item32Error, "plan_authorization_binding"):
            successor._load_plan(candidate, ROOT / "tools/execute_item32_readonly_trends_successor.py",
                ROOT / successor.ADAPTER_SOURCE_REF, ROOT / successor.HOLD_EVIDENCE_REF)

    def test_artifact_rejects_same_day_execution_outside_approved_window(self):
        plan = json.loads((ROOT / "deploy/production/plans/item32-readonly-successor-prospective.json").read_text())
        for start, finish in (
            ("2026-09-15T13:59:00+00:00", "2026-09-15T14:10:00+00:00"),
            ("2026-09-15T14:40:00+00:00", "2026-09-15T14:50:00+00:00"),
            ("2026-09-15T14:10:00+00:00", "2026-09-15T15:00:00+00:00"),
        ):
            with self.subTest(start=start, finish=finish), mock.patch.object(
                successor, "_read_task_result", return_value=({"started_at": start, "completed_at": finish}, [], b"")
            ), mock.patch.object(successor, "_snapshot_quality", side_effect=AssertionError("quality after window")):
                with self.assertRaisesRegex(successor.Item32Error, "execution_window"):
                    successor._build_artifacts(run_dir=self.root, plan=plan, plan_sha256="a"*64,
                        executor_sha256="b"*64, container_id="c"*64, pre_probe={}, post_probe={},
                        predecessor={}, budget={"bucket_date": "2026-09-15"}, runtime_readback={})

    def test_dispatch_requires_fresh_runtime_readback_and_bucket_margin(self):
        plan = {
            "admission": {
                "not_before_utc": TEST_WINDOW["not_before_utc"],
                "bucket_date_utc": TEST_WINDOW["bucket_date_utc"],
                "dispatch_deadline_utc": TEST_WINDOW["dispatch_deadline_utc"],
                "must_finish_before_utc": TEST_WINDOW["must_finish_before_utc"],
            }
        }
        budget = {"bucket_date": TEST_WINDOW["bucket_date_utc"]}
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

    def test_browser_preflight_initialization_uses_only_bounded_disposable_sqlite(self):
        plan = self.synthetic_prospective_plan()
        unit = self.root / "synthetic-unit"
        unit.write_bytes(b"synthetic suspended unit")
        captured = []
        source_commands = []

        def fake_run(args, **kwargs):
            phase = kwargs.get("phase")
            if phase == "UNIT_FRAGMENT_READBACK":
                return completed(args, str(unit).encode())
            if phase == "TASK_CONTAINER_READBACK":
                return completed(args)
            if phase == "IMAGE_INSPECT":
                return completed(args, json.dumps([{"Id": successor.IMAGE, "Config": {
                    "Labels": {"com.noteai.runtime.role": "xhs-http"},
                    "Entrypoint": ["/app/scripts/docker_entrypoint.sh"], "Cmd": ["/bin/false"],
                }}]).encode())
            if phase == "IMAGE_SOURCE_CHECK":
                source_commands.append(args)
                rows = [f"{plan['image_source_sha256'][name]}  {path}"
                    for name, path in successor.IMAGE_SOURCE_CONTAINER_PATHS.items()]
                rows.append(f"{successor.EXPECTED_SIGNER_ASSET_SHA256}  {successor.SIGNER_ASSET_CONTAINER_PATH}")
                return completed(args, ("\n".join(rows) + "\n").encode())
            if phase == "RUNTIME_OVERLAY_CHECK":
                captured.append(args)
                raise successor.Item32Error("synthetic_browser_command_captured")
            raise AssertionError("unexpected synthetic host command")

        with ExitStack() as stack:
            for name in ("_validated_export_account", "_assert_runtime_overlay_sources",
                         "_assert_trends_unit_suspended", "_assert_fixed_trends_container_absent",
                         "_remove_container"):
                stack.enter_context(mock.patch.object(successor, name))
            stack.enter_context(mock.patch.object(successor, "EXPECTED_UNIT_SHA256", hashlib.sha256(unit.read_bytes()).hexdigest()))
            stack.enter_context(mock.patch.object(successor, "_run", side_effect=fake_run))
            with self.assertRaisesRegex(successor.Item32Error, "synthetic_browser_command_captured"):
                successor._preflight_host(plan, ROOT / successor.ADAPTER_SOURCE_REF)
        self.assertEqual(len(captured), 1)
        args = captured[0]
        self.assertIn("--network=none", args)
        self.assertIn("--read-only", args)
        self.assertIn("--user=999:999", args)
        self.assertIn("--tmpfs=/tmp/item32-import:rw,nosuid,nodev,noexec,size=8m,mode=0700,uid=999,gid=999", args)
        self.assertEqual([arg for arg in args if arg.startswith("--env=")],
            ["--env=DATABASE_URL=", "--env=NOTEAI_SQLITE_PATH=/tmp/item32-import/noteai.db"])
        self.assertFalse(any("--env-file" in arg for arg in args))
        self.assertEqual(len(source_commands), 1)
        self.assertFalse(any("item32-import" in arg or "DATABASE_URL" in arg for arg in source_commands[0]))
        mounts = [args[index + 1] for index, arg in enumerate(args) if arg == "--mount"]
        self.assertEqual(len(mounts), len(successor.RUNTIME_OVERLAY_SHA256))
        self.assertTrue(all(mount.endswith(",readonly") for mount in mounts))
        compile(args[-1], "<synthetic-browser-check>", "exec")

    def test_db_probes_keep_original_connection_env_without_browser_tmpfs(self):
        # Synthetic command receipts only: no connection or subprocess runs.
        result = {"server_enforced_read_only": True, "write_count": 0,
            "tuple_write_count": 0, "write_tables": [], "xid_assigned": False,
            "transaction_rolled_back": True, "readback_query_sha256": successor.DB_PROBE_QUERYSET_SHA256,
            "secret_values_recorded": False, "active_or_manual_count": 0,
            "session_blocked_count": 0, "today_attempt_count": 0,
            "session_identity_sha256": "a" * 64}
        calls = []

        def fake_run(args, **kwargs):
            calls.append((args, kwargs))
            return completed(args, json.dumps(result).encode())

        with mock.patch.object(successor, "_run", side_effect=fake_run), mock.patch.object(
            successor, "_remove_registered_container"
        ):
            for phase in ("before", "after"):
                successor._run_db_probe(self.root, "", phase, {})
                self.assertFalse((self.root / f"db-{phase}.env").exists())
        self.assertEqual(len(calls), 2)
        for (args, kwargs), phase in zip(calls, ("before", "after")):
            self.assertEqual(kwargs["phase"], {"before": "DB_BEFORE_PROBE", "after": "DB_AFTER_PROBE"}[phase])
            self.assertIn("--network=bridge", args)
            self.assertIn("--read-only", args)
            self.assertEqual(args[args.index("--env-file") + 1], str(self.root / f"db-{phase}.env"))
            self.assertFalse(any("item32-import" in arg or arg.startswith("--env=DATABASE_URL=")
                or arg.startswith("--env=NOTEAI_SQLITE_PATH=") for arg in args))

    def test_collection_mounts_only_task_store_and_exact_runtime_overlays(self):
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
                                *[{"Destination":successor.RUNTIME_OVERLAY_CONTAINER_PATHS[n],"Source":str(p),"RW":False}
                                  for n,p in successor._runtime_overlay_paths(adapter).items()],
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
        with mock.patch.object(successor, "_run", side_effect=fake_run), mock.patch.object(successor.os, "chown"), \
             mock.patch.object(successor, "_assert_runtime_overlay_sources"):

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
        self.assertNotIn("item32-import", "\n".join(create))
        self.assertIn("--env=NOTEAI_SQLITE_PATH=/task/noteai.db", create)
        self.assertIn("--network=bridge", create)
        self.assertFalse(cookie_env.exists())

    def test_current_runtime_files_are_fixed_and_missing_or_changed_fails_before_container(self):
        adapter = self.root / "spider_xhs_http.py"
        for name,path in successor._runtime_overlay_paths(adapter).items():
            path.write_bytes((ROOT/name).read_bytes())
        with mock.patch.object(successor,"_assert_adapter_source"):
            successor._assert_runtime_overlay_sources(adapter)
            (self.root/"security_redaction.py").write_text("changed")
            with self.assertRaises(successor.Item32Error):
                successor._assert_runtime_overlay_sources(adapter)
        mounts=successor._runtime_overlay_mounts(adapter)
        self.assertEqual(mounts.count("--mount"),3)
        self.assertTrue(all(x.endswith(",readonly")for x in mounts if x!="--mount"))
        with mock.patch.object(successor,"_write_env")as secret, mock.patch.object(successor,"_run")as run, \
             mock.patch.object(successor,"_assert_adapter_source"):
            with self.assertRaisesRegex(successor.Item32Error,"runtime_overlay_source_binding"):
                successor._create_collection_container(self.root/"run",self.root/"runtime","[]",adapter,{})
            (self.root/"security_redaction.py").unlink()
            with self.assertRaises(FileNotFoundError):
                successor._create_collection_container(self.root/"run",self.root/"runtime","[]",adapter,{})
            secret.assert_not_called();run.assert_not_called()

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
