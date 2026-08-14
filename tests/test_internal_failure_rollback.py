import copy
import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

SPEC = importlib.util.spec_from_file_location(
    "internal_failure_rollback",
    ROOT / "deploy" / "production" / "internal_failure_rollback.py",
)
rollback = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(rollback)
REAL_HOST = rollback.Host

from validate_item28_internal_failure_rollback_result_v1 import (  # noqa: E402
    validate_executor_result,
)


HEALTH = [
    {"path": "/health/live", "status": 200, "state": "ok"},
    {"path": "/health/ready", "status": 200, "state": "ready"},
]


class FakeHost:
    def __init__(self, restart_rc=1, fail_at=None):
        self.restart_rc = restart_rc
        self.fail_at = fail_at
        self.calls = []

    def _call(self, name):
        self.calls.append(name)
        if self.fail_at == name:
            raise rollback.RollbackError(name)

    def baseline(self):
        self._call("baseline")
        return {
            "nrestarts": 0,
            "release_identity_sha256": "a" * 64,
            "health": copy.deepcopy(HEALTH),
        }

    def arm(self):
        self._call("arm")

    def install_dropin(self):
        self._call("install_dropin")

    def daemon_reload(self):
        self._call("daemon_reload")

    def restart_expected_failure(self):
        self._call("restart")
        return self.restart_rc

    def verify_preconnect_failure(self):
        self._call("verify_preconnect_failure")

    def final_verify(self, expected):
        self._call("final_verify")
        if expected != "a" * 64:
            raise rollback.RollbackError("identity")
        return {
            "nrestarts": 0,
            "release_identity_sha256": expected,
            "health": copy.deepcopy(HEALTH),
        }

    def cleanup_task_root(self):
        self._call("cleanup_task_root")


class FakeGuardian:
    def __init__(self, fail=False):
        self.prepare_count = 0
        self.rollback_count = 0
        self.cancel_count = 0
        self.fail = fail

    def prepare(self, baseline):
        if baseline["release_identity_sha256"] != "a" * 64:
            raise rollback.RollbackError("baseline")
        self.prepare_count += 1

    def rollback(self):
        self.rollback_count += 1
        if self.fail:
            raise rollback.RollbackError("guardian")
        return {
            "schema": "noteai.item28.guardian-result.v1",
            "status": "RESTORED",
            "dropin_removed": True,
            "staged_cleanup_status": "ABSENT",
            "staged_residue_count": 0,
            "daemon_reload_count": 1,
            "runtime_start_count": 1,
            "volatile_residue_count": 0,
        }

    def cancel(self):
        self.cancel_count += 1
        return {
            "schema": "noteai.item28.guardian-result.v1",
            "status": "ABORTED_NO_MUTATION",
            "dropin_removed": False,
            "staged_cleanup_status": "ABSENT",
            "staged_residue_count": 0,
            "daemon_reload_count": 0,
            "runtime_start_count": 0,
            "volatile_residue_count": 0,
        }


class FakeGuardianRuntimeHost:
    def __init__(self, identity, runtime_active=False, runtime_states=None):
        self.identity = identity
        self.runtime_active = runtime_active
        self.runtime_states = list(runtime_states or [])
        self.calls = []

    def _regular_file(self, path, mode, expected_sha=None):
        self.calls.append(("regular", path, mode, expected_sha))
        raw = Path(path).read_bytes() if Path(path).is_file() else b""
        return ((), expected_sha, raw)

    def unit_manager(self, dropins):
        self.calls.append(("manager", dropins))

    def unit_state(self, active, require_result=None):
        self.calls.append(("state", active, require_result))
        return 0

    def release_identity(self):
        self.calls.append(("identity",))
        return self.identity

    def daemon_reload(self):
        self.calls.append(("reload",))

    def command(self, args, code, allowed=(0,), timeout=30):
        self.calls.append(("command", tuple(args), code, timeout, allowed))
        if "is-active" in args:
            if self.runtime_states:
                state = self.runtime_states.pop(0)
                return (0 if state == "active" else 3), (state + "\n").encode()
            return (
                (0, b"active\n") if self.runtime_active
                else (3, b"failed\n")
            )
        return 0, b""

    def restore_runtime_if_needed(self):
        return REAL_HOST.restore_runtime_if_needed(self)

    def public_listener_count(self):
        return 0

    def health(self):
        return copy.deepcopy(HEALTH)

    def _write_exclusive(self, path, raw, mode):
        fd = rollback.os.open(
            path,
            rollback.os.O_WRONLY | rollback.os.O_CREAT
            | rollback.os.O_EXCL | rollback.os.O_NOFOLLOW,
            mode,
        )
        try:
            rollback.os.write(fd, raw)
        finally:
            rollback.os.close(fd)

    def dropin_directory_state(self, directory, dropin_path):
        directory = Path(directory)
        dropin = Path(dropin_path)
        if not os.path.lexists(directory):
            return "ABSENT" if not os.path.lexists(dropin) else "PARTIAL"
        if directory.is_symlink() or not directory.is_dir():
            return "PARTIAL"
        if stat.S_IMODE(directory.stat().st_mode) != 0o755:
            return "PARTIAL"
        names = [item.name for item in directory.iterdir()]
        if names == []:
            return "EMPTY"
        if names != [dropin.name]:
            return "PARTIAL"
        if (
            dropin.is_symlink() or not dropin.is_file()
            or stat.S_IMODE(dropin.stat().st_mode) != 0o644
            or dropin.read_bytes() != rollback.DROPIN_BYTES
        ):
            return "PARTIAL"
        return "COMPLETE"


class FakeGuardianSetupHost(FakeHost):
    def __init__(self, cleanup_fails=False):
        FakeHost.__init__(self)
        self.cleanup_fails = cleanup_fails
        self.setup_cleanup_count = 0

    def prepare_guardian(self, baseline):
        del baseline
        raise rollback.RollbackError("guardian_start")

    def wait_guardian_active(self):
        raise AssertionError("not reached")

    def cancel_guardian_setup(self):
        self.setup_cleanup_count += 1
        if self.cleanup_fails:
            raise rollback.RollbackError("guardian_setup_cleanup")

class InternalFailureRollbackTests(unittest.TestCase):
    def test_exact_managed_failure_and_guardian_rollback_pass(self):
        host = FakeHost()
        guardian = FakeGuardian()

        rc, payload = rollback.execute(host=host, guardian=guardian)

        self.assertEqual(rc, 0)
        self.assertEqual(guardian.prepare_count, 1)
        self.assertEqual(guardian.rollback_count, 1)
        self.assertEqual(
            host.calls,
            [
                "baseline", "arm", "install_dropin", "daemon_reload",
                "restart", "verify_preconnect_failure", "final_verify",
                "cleanup_task_root",
            ],
        )
        errors, derived = validate_executor_result(payload)
        self.assertEqual(errors, [])
        self.assertIsNotNone(derived)
        self.assertEqual(payload["restart_attempt_count"], 1)
        self.assertEqual(payload["restart_success_count"], 0)
        self.assertEqual(payload["guardian_rollback_count"], 1)
        self.assertEqual(payload["production_database_mutation_count"], 0)

    def test_unexpected_restart_success_is_unknown_and_never_replayed(self):
        host = FakeHost(restart_rc=0)
        guardian = FakeGuardian()

        rc, payload = rollback.execute(host=host, guardian=guardian)

        self.assertEqual(rc, 4)
        self.assertEqual(payload["status"], "UNKNOWN")
        self.assertEqual(payload["code"], "restart_unexpected_success")
        self.assertEqual(payload["restart_attempt_count"], 1)
        self.assertEqual(guardian.rollback_count, 1)
        self.assertFalse(payload["automatic_retry_allowed"])
        self.assertFalse(payload["same_invocation_replay_allowed"])

    def test_guardian_failure_is_not_automatically_retried(self):
        host = FakeHost()
        guardian = FakeGuardian(fail=True)

        rc, payload = rollback.execute(host=host, guardian=guardian)

        self.assertEqual(rc, 4)
        self.assertEqual(payload["status"], "UNKNOWN")
        self.assertEqual(guardian.rollback_count, 1)
        self.assertTrue(payload["rollback_requested"])

    def test_pre_mutation_failure_is_known_fail(self):
        host = FakeHost(fail_at="baseline")
        guardian = FakeGuardian()

        rc, payload = rollback.execute(host=host, guardian=guardian)

        self.assertEqual(rc, 3)
        self.assertEqual(payload["status"], "FAIL")
        self.assertFalse(payload["runtime_mutation_attempted"])
        self.assertEqual(guardian.prepare_count, 0)
        self.assertEqual(guardian.rollback_count, 0)

    def test_guardian_is_cancelled_when_arm_fails_before_mutation(self):
        host = FakeHost(fail_at="arm")
        guardian = FakeGuardian()

        rc, payload = rollback.execute(host=host, guardian=guardian)

        self.assertEqual(rc, 3)
        self.assertEqual(payload["status"], "FAIL")
        self.assertEqual(guardian.prepare_count, 1)
        self.assertEqual(guardian.cancel_count, 1)
        self.assertEqual(guardian.rollback_count, 0)
        self.assertIn("cleanup_task_root", host.calls)

    def test_result_validator_rejects_type_aliases_and_counter_drift(self):
        rc, payload = rollback.execute(host=FakeHost(), guardian=FakeGuardian())
        self.assertEqual(rc, 0)

        broken = copy.deepcopy(payload)
        broken["restart_attempt_count"] = True
        self.assertTrue(validate_executor_result(broken)[0])

        broken = copy.deepcopy(payload)
        broken["provider_call_count"] = 1
        self.assertTrue(validate_executor_result(broken)[0])

        broken = copy.deepcopy(payload)
        broken["failure_phase"] = "POST_CONNECT"
        self.assertTrue(validate_executor_result(broken)[0])

    def test_source_contains_independent_guardian_and_only_volatile_fault(self):
        source = (ROOT / "deploy" / "production" / "internal_failure_rollback.py").read_text()
        self.assertIn("/usr/bin/systemd-run", source)
        self.assertIn("/run/systemd/system/noteai-api.service.d", source)
        self.assertIn("ExecStartPre=/usr/bin/false", source)
        self.assertIn('"--guardian"', source)
        self.assertIn('"restart", UNIT', source)
        self.assertIn('"start", UNIT', source)
        self.assertNotIn('"enable", UNIT', source)
        self.assertNotIn('"disable", UNIT', source)
        self.assertNotIn('"mask", UNIT', source)
        self.assertIn("renameat2", source)
        self.assertIn("STAGED_VOLATILE_DIR", source)

    def _run_guardian_parent_kill_case(self, staged_state, volatile_state):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "task"
            staged = root / "volatile-dropin-stage"
            volatile = Path(temp_dir) / "unit.d"
            root.mkdir(mode=0o700)
            paths = {
                "TASK_ROOT": str(root),
                "BASELINE_PATH": str(root / "baseline.json"),
                "ARMED_PATH": str(root / "armed"),
                "ABORT_PATH": str(root / "abort"),
                "ROLLBACK_REQUEST_PATH": str(root / "rollback-request"),
                "GUARDIAN_RESULT_PATH": str(root / "guardian-result.json"),
                "GUARDIAN_RESULT_TEMP": str(root / "guardian-result.tmp"),
                "STAGED_VOLATILE_DIR": str(staged),
                "STAGED_DROPIN_PATH": str(staged / "fault.conf"),
                "VOLATILE_DIR": str(volatile),
                "DROPIN_PATH": str(volatile / "fault.conf"),
            }
            baseline = {
                "schema": "noteai.item28.guardian-baseline.v1",
                "unit_fragment_sha256": rollback.UNIT_SHA256,
                "release_identity_sha256": "a" * 64,
                "volatile_dropin_sha256": rollback.DROPIN_SHA256,
            }
            Path(paths["BASELINE_PATH"]).write_bytes(
                rollback.canonical(baseline).encode() + b"\n"
            )
            Path(paths["ARMED_PATH"]).write_text("ARMED\n")

            def materialize(directory, dropin, state):
                if state == "ABSENT":
                    return
                directory.mkdir(mode=0o755)
                directory.chmod(0o755)
                if state == "BAD_MODE":
                    directory.chmod(0o700)
                    return
                if state == "COMPLETE":
                    dropin.write_bytes(rollback.DROPIN_BYTES)
                    dropin.chmod(0o644)
                elif state == "PARTIAL":
                    dropin.write_bytes(b"partial")
                    dropin.chmod(0o644)

            materialize(staged, Path(paths["STAGED_DROPIN_PATH"]), staged_state)
            materialize(volatile, Path(paths["DROPIN_PATH"]), volatile_state)
            host = FakeGuardianRuntimeHost(
                "a" * 64,
                runtime_active=(volatile_state == "COMPLETE"),
            )
            patches = [
                mock.patch.object(rollback, key, value)
                for key, value in paths.items()
            ]
            for patcher in patches:
                patcher.start()
            try:
                with mock.patch.object(rollback, "Host", return_value=host), \
                     mock.patch.object(rollback, "_pid_alive", return_value=False):
                    rc = rollback.guardian_main(999, "1")
            finally:
                for patcher in reversed(patches):
                    patcher.stop()
            result = json.loads(Path(paths["GUARDIAN_RESULT_PATH"]).read_text())
            return {
                "rc": rc,
                "result": result,
                "staged_exists": os.path.lexists(staged),
                "volatile_exists": os.path.lexists(volatile),
                "calls": host.calls,
            }

    def test_parent_kill_cleans_owned_empty_and_complete_stages(self):
        for state, cleanup in (
            ("EMPTY", "CLEANED_EMPTY"),
            ("COMPLETE", "CLEANED_COMPLETE"),
        ):
            with self.subTest(state=state):
                outcome = self._run_guardian_parent_kill_case(state, "ABSENT")
                self.assertEqual(outcome["rc"], 0)
                self.assertEqual(
                    outcome["result"]["status"],
                    "STAGED_CLEANED_NO_RUNTIME_MUTATION",
                )
                self.assertEqual(
                    outcome["result"]["staged_cleanup_status"], cleanup
                )
                self.assertEqual(outcome["result"]["staged_residue_count"], 0)
                self.assertEqual(outcome["result"]["volatile_residue_count"], 0)
                self.assertFalse(outcome["staged_exists"])
                self.assertFalse(outcome["volatile_exists"])

    def test_parent_kill_after_atomic_publish_restores_runtime(self):
        outcome = self._run_guardian_parent_kill_case("ABSENT", "COMPLETE")
        self.assertEqual(outcome["rc"], 0)
        self.assertEqual(outcome["result"]["status"], "RESTORED")
        self.assertTrue(outcome["result"]["dropin_removed"])
        self.assertEqual(outcome["result"]["runtime_start_count"], 0)
        self.assertFalse(outcome["staged_exists"])
        self.assertFalse(outcome["volatile_exists"])
        self.assertFalse(any(
            call[0] == "command" and "start" in call[1]
            for call in outcome["calls"]
        ))

    def test_guardian_waits_for_interrupted_restart_then_starts_once(self):
        host = FakeGuardianRuntimeHost(
            "a" * 64, runtime_states=["deactivating", "failed"]
        )
        with mock.patch.object(rollback.time, "sleep"):
            count = host.restore_runtime_if_needed()
        self.assertEqual(count, 1)
        self.assertEqual(sum(
            call[0] == "command" and "start" in call[1]
            for call in host.calls
        ), 1)

    def test_parent_kill_partial_or_collision_is_unknown_with_residue(self):
        cases = (
            ("PARTIAL", "ABSENT", 1, 0),
            ("BAD_MODE", "ABSENT", 1, 0),
            ("ABSENT", "EMPTY", 0, 1),
            ("ABSENT", "PARTIAL", 0, 1),
            ("COMPLETE", "COMPLETE", 1, 1),
        )
        for staged, volatile, staged_count, volatile_count in cases:
            with self.subTest(staged=staged, volatile=volatile):
                outcome = self._run_guardian_parent_kill_case(staged, volatile)
                self.assertEqual(outcome["rc"], 4)
                self.assertEqual(outcome["result"]["status"], "UNKNOWN")
                self.assertEqual(
                    outcome["result"]["staged_residue_count"], staged_count
                )
                self.assertEqual(
                    outcome["result"]["volatile_residue_count"], volatile_count
                )
                self.assertEqual(outcome["staged_exists"], bool(staged_count))
                self.assertEqual(outcome["volatile_exists"], bool(volatile_count))

    def test_install_dropin_validates_complete_stage_before_atomic_publish(self):
        host = rollback.Host()
        with mock.patch.object(os.path, "lexists", return_value=False), \
             mock.patch.object(os, "mkdir") as mkdir, \
             mock.patch.object(os, "chmod") as chmod, \
             mock.patch.object(host, "_write_exclusive") as write, \
             mock.patch.object(host, "_rename_noreplace") as rename, \
             mock.patch.object(
                 host, "dropin_directory_state",
                 side_effect=["EMPTY", "COMPLETE", "ABSENT", "COMPLETE"],
             ):
            host.install_dropin()
        mkdir.assert_called_once_with(rollback.STAGED_VOLATILE_DIR, 0o755)
        chmod.assert_called_once_with(
            rollback.STAGED_VOLATILE_DIR, 0o755, follow_symlinks=False
        )
        write.assert_called_once_with(
            rollback.STAGED_DROPIN_PATH, rollback.DROPIN_BYTES, 0o644
        )
        rename.assert_called_once_with(
            rollback.STAGED_VOLATILE_DIR, rollback.VOLATILE_DIR
        )

    def test_atomic_publish_collision_has_no_nonatomic_fallback(self):
        class RenameAt2:
            argtypes = None
            restype = None

            def __call__(self, *_args):
                return -1

        class Libc:
            renameat2 = RenameAt2()

        host = rollback.Host()
        with mock.patch.object(rollback.ctypes, "CDLL", return_value=Libc()), \
             mock.patch.object(
                 rollback.ctypes, "get_errno", return_value=rollback.errno.EEXIST
             ), mock.patch.object(rollback.os, "rename") as fallback:
            with self.assertRaisesRegex(
                rollback.RollbackError, "volatile_collision"
            ):
                host._rename_noreplace("stage", "target")
        fallback.assert_not_called()

    def test_guardian_process_removes_exact_dropin_and_restores_release(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "task"
            volatile = Path(temp_dir) / "unit.d"
            root.mkdir(mode=0o700)
            volatile.mkdir(mode=0o755)
            paths = {
                "TASK_ROOT": str(root),
                "BASELINE_PATH": str(root / "baseline.json"),
                "ARMED_PATH": str(root / "armed"),
                "ABORT_PATH": str(root / "abort"),
                "ROLLBACK_REQUEST_PATH": str(root / "rollback-request"),
                "GUARDIAN_RESULT_PATH": str(root / "guardian-result.json"),
                "GUARDIAN_RESULT_TEMP": str(root / "guardian-result.tmp"),
                "STAGED_VOLATILE_DIR": str(root / "volatile-dropin-stage"),
                "STAGED_DROPIN_PATH": str(root / "volatile-dropin-stage" / "fault.conf"),
                "VOLATILE_DIR": str(volatile),
                "DROPIN_PATH": str(volatile / "fault.conf"),
            }
            baseline = {
                "schema": "noteai.item28.guardian-baseline.v1",
                "unit_fragment_sha256": rollback.UNIT_SHA256,
                "release_identity_sha256": "a" * 64,
                "volatile_dropin_sha256": rollback.DROPIN_SHA256,
            }
            Path(paths["BASELINE_PATH"]).write_bytes(
                rollback.canonical(baseline).encode() + b"\n"
            )
            Path(paths["ARMED_PATH"]).write_text("ARMED\n")
            Path(paths["ROLLBACK_REQUEST_PATH"]).write_text("ROLLBACK\n")
            Path(paths["DROPIN_PATH"]).write_bytes(rollback.DROPIN_BYTES)
            host = FakeGuardianRuntimeHost("a" * 64)
            patches = [mock.patch.object(rollback, key, value) for key, value in paths.items()]
            for patcher in patches:
                patcher.start()
            try:
                with mock.patch.object(rollback, "Host", return_value=host):
                    rc = rollback.guardian_main(rollback.os.getpid(), "1")
            finally:
                for patcher in reversed(patches):
                    patcher.stop()

            self.assertEqual(rc, 0)
            self.assertFalse(Path(paths["DROPIN_PATH"]).exists())
            self.assertFalse(volatile.exists())
            result = json.loads(Path(paths["GUARDIAN_RESULT_PATH"]).read_text())
            self.assertEqual(result["status"], "RESTORED")
            self.assertIn(("reload",), host.calls)
            self.assertTrue(any(
                call[0] == "command" and "reset-failed" in call[1]
                for call in host.calls
            ))
            self.assertTrue(any(
                call[0] == "command" and "start" in call[1]
                for call in host.calls
            ))

    def test_exclusive_writer_sets_requested_mode_despite_process_umask(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "dropin.conf"
            previous = os.umask(0o077)
            try:
                rollback.Host()._write_exclusive(
                    str(path), rollback.DROPIN_BYTES, 0o644
                )
            finally:
                os.umask(previous)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
            self.assertEqual(path.read_bytes(), rollback.DROPIN_BYTES)

    def test_guardian_parent_identity_binds_proc_starttime(self):
        fields = [b"S"] + [b"0"] * 18 + [b"12345"]
        proc_stat = b"123 (python test) " + b" ".join(fields) + b"\n"
        with mock.patch("builtins.open", mock.mock_open(read_data=proc_stat)):
            value = rollback._process_starttime(123)
        self.assertEqual(value, "12345")
        with mock.patch.object(rollback, "_process_starttime", return_value=value):
            self.assertTrue(rollback._pid_alive(123, value))
            self.assertFalse(rollback._pid_alive(123, "12346"))

    def test_guardian_outlives_provider_timeout(self):
        self.assertGreater(
            rollback.GUARDIAN_BUDGET_SECONDS,
            rollback.PROVIDER_TIMEOUT_SECONDS,
        )

    def test_existing_task_root_is_never_claimed_or_cleaned(self):
        host = rollback.Host()
        with mock.patch.object(os.path, "lexists", return_value=True):
            with self.assertRaisesRegex(rollback.RollbackError, "task_root_exists"):
                host._make_root()
        with mock.patch.object(host, "command") as command:
            with self.assertRaisesRegex(
                rollback.RollbackError, "guardian_setup_ownership"
            ):
                host.cancel_guardian_setup()
        command.assert_not_called()

    def test_guardian_setup_failure_is_cleaned_or_classified_unknown(self):
        host = FakeGuardianSetupHost()
        rc, payload = rollback.execute(
            host=host, guardian=rollback.LocalGuardian(host)
        )
        self.assertEqual(rc, 3)
        self.assertEqual(payload["status"], "FAIL")
        self.assertEqual(host.setup_cleanup_count, 1)

        host = FakeGuardianSetupHost(cleanup_fails=True)
        rc, payload = rollback.execute(
            host=host, guardian=rollback.LocalGuardian(host)
        )
        self.assertEqual(rc, 4)
        self.assertEqual(payload["status"], "UNKNOWN")
        self.assertEqual(host.setup_cleanup_count, 1)


if __name__ == "__main__":
    unittest.main()
