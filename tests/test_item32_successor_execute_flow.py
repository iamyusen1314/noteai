import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import execute_item32_readonly_trends_successor as successor


def completed(args, stdout=b"", returncode=0):
    return subprocess.CompletedProcess(args, returncode, stdout, b"")


class Item32SuccessorExecuteFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def execute_harness(
        self,
        *,
        post_probe_unknown=False,
        attempt_readback=(34, 0),
        collection_remove_failures=0,
        final_cleanup_unknown=False,
    ):
        work = self.root / "successor"
        export = self.root / "export"
        runtime = self.root / "runtime"
        for path in (work, export, runtime):
            path.mkdir()
        work.chmod(0o700)
        executor_path = self.root / "executor.py"
        executor_path.write_text("# synthetic executor\n", encoding="utf-8")
        events = []
        starts = []
        removals = []
        remove_failures_remaining = collection_remove_failures
        attempt_readbacks = (
            list(attempt_readback)
            if isinstance(attempt_readback, list)
            else None
        )
        predecessor = {
            "closure_sha256": successor.HOLD_EVIDENCE_SHA256,
            "original_admission_sha256": "1" * 64,
            "original_store_sha256": "2" * 64,
            "diagnostic_admission_sha256": "3" * 64,
            "diagnostic_result_sha256": "4" * 64,
            "call_dates": ["2026-09-05", "2026-09-06"],
        }
        budget = {
            "bucket_date": successor.BUCKET_DATE_UTC,
            "used_before": 0,
            "remaining_before": 34,
            "planned": 34,
            "limit": 34,
        }
        runtime_readback = {"observed_at": "2026-09-07T00:00:00+00:00"}
        probe = {
            "today_attempt_count": 0,
            "session_identity_sha256": "5" * 64,
        }
        probe_count = 0

        def acquire_lock():
            return os.open(
                work / "executor.lock", os.O_RDWR | os.O_CREAT, 0o600
            )

        def verify(*_args):
            events.append("predecessors")
            return dict(predecessor)

        def read_secret(*_args):
            events.append("secret")
            return {
                "DATABASE_URL": "synthetic-database-url",
                "NOTEAI_XHS_COOKIES_JSON": json.dumps(
                    [
                        {
                            "name": "a1",
                            "value": "synthetic-a1",
                            "domain": ".xiaohongshu.com",
                            "path": "/",
                        },
                        {
                            "name": "web_session",
                            "value": "synthetic-web-session",
                            "domain": ".xiaohongshu.com",
                            "path": "/",
                        },
                    ]
                ),
            }

        def db_probe(*_args):
            nonlocal probe_count
            probe_count += 1
            events.append(f"db-{probe_count}")
            if post_probe_unknown and probe_count == 2:
                raise successor.Item32Error("post_probe_outcome_unknown")
            return dict(probe)

        def create_container(run_dir, runtime_dir, *_args):
            events.append("container-create")
            (run_dir / "task-store").mkdir()
            return "item32-test", "a" * 64, runtime_dir / "cookie.env"

        def fake_run(args, **_kwargs):
            if args[:3] == ["docker", "start", "--attach"]:
                self.assertTrue((work / "item32-admission.json").is_file())
                events.append("start")
                starts.append(list(args))
                return completed(args, b"worker-output")
            if args[:2] == ["docker", "inspect"]:
                return completed(
                    args,
                    json.dumps([{"State": {"ExitCode": 0}}]).encode(),
                )
            if args[:2] == ["docker", "ps"]:
                return completed(args)
            raise AssertionError(args)

        def update_admission(status, provider_calls, unknown_count):
            path = work / "item32-admission.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload.update(
                {
                    "status": status,
                    "provider_calls": (
                        "UNKNOWN" if provider_calls is None else provider_calls
                    ),
                    "outcome_unknown_count": (
                        "UNKNOWN" if unknown_count is None else unknown_count
                    ),
                }
            )
            path.write_text(json.dumps(payload), encoding="utf-8")

        def build_artifacts(**kwargs):
            candidate = kwargs["run_dir"] / "candidate.tar.gz"
            candidate.write_bytes(b"candidate")
            candidate.chmod(0o600)
            return candidate

        def remove_container(name):
            nonlocal remove_failures_remaining
            events.append(f"remove:{name}")
            removals.append(name)
            if name == "item32-test" and remove_failures_remaining:
                remove_failures_remaining -= 1
                raise successor.Item32Error("container_cleanup")

        def attempt_count(_path):
            events.append("attempt-count")
            if attempt_readbacks is not None:
                return attempt_readbacks.pop(0)
            return attempt_readback

        real_cleanup = successor._cleanup_registered_containers
        cleanup_call_count = 0

        def cleanup_registered(registry):
            nonlocal cleanup_call_count
            cleanup_call_count += 1
            real_cleanup(registry)
            if final_cleanup_unknown and cleanup_call_count > 1:
                raise successor.Item32Error("container_cleanup")

        def publish(staged):
            events.append("publish")
            self.assertEqual(list(runtime.iterdir()), [])
            self.assertFalse(any(work.glob("run-*")))
            staged.unlink()
            return export / "item32-evidence.tar.gz"

        with ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(successor.os, "geteuid", return_value=0)
            )
            stack.enter_context(mock.patch.object(successor, "WORK_ROOT", work))
            stack.enter_context(mock.patch.object(successor, "EXPORT_ROOT", export))
            stack.enter_context(mock.patch.object(successor, "RUNTIME_ROOT", runtime))
            stack.enter_context(
                mock.patch.object(
                    successor,
                    "_load_plan",
                    return_value=({"admission": {}}, "b" * 64),
                )
            )
            stack.enter_context(mock.patch.object(successor, "_ensure_work_root"))
            stack.enter_context(
                mock.patch.object(
                    successor,
                    "_acquire_executor_lock",
                    side_effect=acquire_lock,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    successor, "_acquire_predecessor_locks", return_value=[]
                )
            )
            stack.enter_context(
                mock.patch.object(
                    successor, "_verify_predecessors", side_effect=verify
                )
            )
            stack.enter_context(
                mock.patch.object(
                    successor, "_admission_budget", return_value=budget
                )
            )
            stack.enter_context(
                mock.patch.object(
                    successor,
                    "_preflight_host",
                    return_value=runtime_readback,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    successor, "_read_secret_env", side_effect=read_secret
                )
            )
            stack.enter_context(
                mock.patch.object(successor, "_prior_attempt_count", return_value=0)
            )
            stack.enter_context(
                mock.patch.object(successor, "_run_db_probe", side_effect=db_probe)
            )
            stack.enter_context(
                mock.patch.object(
                    successor,
                    "_create_collection_container",
                    side_effect=create_container,
                )
            )
            stack.enter_context(
                mock.patch.object(successor, "_assert_dispatch_window")
            )
            stack.enter_context(
                mock.patch.object(successor, "_assert_trends_unit_suspended")
            )
            stack.enter_context(
                mock.patch.object(
                    successor, "_assert_fixed_trends_container_absent"
                )
            )
            stack.enter_context(mock.patch.object(successor, "_run", side_effect=fake_run))
            stack.enter_context(
                mock.patch.object(successor, "_record_worker_receipt")
            )
            stack.enter_context(
                mock.patch.object(
                    successor,
                    "_remove_container",
                    side_effect=remove_container,
                )
            )
            stack.enter_context(
                mock.patch.object(successor, "_attempt_count", side_effect=attempt_count)
            )
            stack.enter_context(
                mock.patch.object(
                    successor,
                    "_cleanup_registered_containers",
                    side_effect=cleanup_registered,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    successor, "_build_artifacts", side_effect=build_artifacts
                )
            )
            stack.enter_context(
                mock.patch.object(successor, "_ensure_export_secret_free")
            )
            stack.enter_context(
                mock.patch.object(
                    successor, "_update_admission", side_effect=update_admission
                )
            )
            stack.enter_context(
                mock.patch.object(
                    successor,
                    "_publish_export",
                    side_effect=publish,
                )
            )

            arguments = (
                self.root / "plan",
                executor_path,
                self.root / "adapter",
                self.root / "hold",
            )
            expected_error = None
            if post_probe_unknown:
                expected_error = "post_probe_outcome_unknown"
            elif isinstance(attempt_readback, list):
                expected_error = "terminal_staging"
            elif attempt_readback != (34, 0):
                expected_error = "attempt_readback"
            elif collection_remove_failures:
                expected_error = "container_cleanup"
            elif final_cleanup_unknown:
                expected_error = "cleanup_incomplete"
            if expected_error:
                with self.assertRaisesRegex(
                    successor.Item32Error, expected_error
                ):
                    successor.execute(*arguments)
                first_run = next(work.glob("run-*"))
                self.assertTrue((first_run / "task-store").is_dir())
                self.assertFalse(any(export.iterdir()))
                admission = json.loads(
                    (work / "item32-admission.json").read_text(encoding="utf-8")
                )
                self.assertEqual(admission["status"], "HOLD")
                if post_probe_unknown:
                    with self.assertRaisesRegex(
                        successor.Item32Error, "item32_already_dispatched"
                    ):
                        successor.execute(*arguments)
            else:
                result = successor.execute(*arguments)
                self.assertEqual(result, export / "item32-evidence.tar.gz")

        return events, starts, removals, runtime

    def test_admission_is_durable_before_the_single_provider_start(self):
        events, starts, removals, runtime = self.execute_harness()
        self.assertEqual(len(starts), 1)
        self.assertLess(events.index("db-1"), events.index("container-create"))
        self.assertLess(events.index("container-create"), events.index("start"))
        self.assertEqual(removals, ["item32-test"])
        self.assertEqual(list(runtime.iterdir()), [])

    def test_post_dispatch_unknown_is_held_without_replay_or_export(self):
        _events, starts, removals, runtime = self.execute_harness(
            post_probe_unknown=True
        )
        self.assertEqual(len(starts), 1)
        self.assertEqual(removals, ["item32-test"])
        self.assertEqual(list(runtime.iterdir()), [])

    def test_unreadable_store_is_recorded_as_unknown_not_zero(self):
        self.execute_harness(attempt_readback=(None, None))
        admission = json.loads(
            (self.root / "successor" / "item32-admission.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(admission["provider_calls"], "UNKNOWN")
        self.assertEqual(admission["outcome_unknown_count"], "UNKNOWN")

    def test_writer_is_stopped_before_failure_ledger_readback(self):
        events, starts, removals, _runtime = self.execute_harness(
            collection_remove_failures=1
        )
        self.assertEqual(len(starts), 1)
        self.assertEqual(removals, ["item32-test", "item32-test"])
        removal_indexes = [
            index
            for index, event in enumerate(events)
            if event == "remove:item32-test"
        ]
        self.assertLess(removal_indexes[-1], events.index("attempt-count"))

    def test_cleanup_unknown_preserves_store_and_never_publishes(self):
        events, starts, _removals, runtime = self.execute_harness(
            final_cleanup_unknown=True
        )
        self.assertEqual(len(starts), 1)
        self.assertNotIn("publish", events)
        self.assertTrue(next((self.root / "successor").glob("run-*")).is_dir())
        self.assertEqual(list(runtime.iterdir()), [])

    def test_second_store_readback_unknown_preserves_store_and_hidden_export_is_removed(self):
        events, starts, _removals, runtime = self.execute_harness(
            attempt_readback=[(34, 0), (None, None)]
        )
        self.assertEqual(len(starts), 1)
        self.assertEqual(events.count("attempt-count"), 2)
        self.assertTrue(next((self.root / "successor").glob("run-*")).is_dir())
        self.assertEqual(list((self.root / "export").iterdir()), [])
        self.assertEqual(list(runtime.iterdir()), [])
        admission = json.loads(
            (self.root / "successor" / "item32-admission.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(admission["status"], "HOLD")
        self.assertEqual(admission["provider_calls"], "UNKNOWN")
        self.assertEqual(admission["outcome_unknown_count"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
