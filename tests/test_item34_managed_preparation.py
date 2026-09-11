import copy
from contextlib import contextmanager, nullcontext
import hashlib
import json
import os
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

from tools import prepare_item34_managed_tracking as managed
from tools.run_item34_tracking_durable import Journal
from tools import run_item34_tracking_durable as durable_managed


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "deploy/production/systemd/noteai-xhs-tracking.service.template"
OLD = "registry.example.invalid/noteai/xhs@sha256:" + "a" * 64
NEW = "registry.example.invalid/noteai/xhs@sha256:" + "b" * 64
CONFIG = "sha256:" + "c" * 64


def snapshots():
    # Only the exact native fields required by the validator are projected.
    # These are synthetic values, not host/registry/readiness Evidence.
    service = {
        "Id": managed.UNIT, "LoadState": "loaded", "ActiveState": "active",
        "SubState": "running", "UnitFileState": "disabled", "Restart": "no",
        "NRestarts": "0", "MainPID": "100", "InvocationID": "d" * 32,
        "FragmentPath": "/etc/systemd/system/" + managed.UNIT, "DropInPaths": [],
    }
    container = {
        "Id": "e" * 64, "Name": "/" + managed.CONTAINER, "Image": CONFIG,
        "RestartCount": 0, "State": {"Running": True, "Pid": 101},
        "Config": {"Image": NEW, "User": "999:999", "Cmd": managed.WORKER.copy(),
                   "Labels": {"com.noteai.service": managed.CONTAINER}},
        "Suspended": True,
        "Mounts": [{"Type": "bind", "Source": "/var/lib/noteai/data",
                    "Destination": "/app/model/data", "RW": True}],
        "HostConfig": {
            "Memory": 268435456, "NanoCpus": 250000000, "PidsLimit": 64,
            "ReadonlyRootfs": True, "CapDrop": ["ALL"], "CapAdd": None,
            "Privileged": False, "SecurityOpt": ["no-new-privileges:true"],
            "NetworkMode": "bridge", "IpcMode": "private", "PortBindings": {},
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
            "LogConfig": {"Type": "local", "Config": {"max-size": "10m", "max-file": "2"}},
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,nodev,size=512m,mode=1777,uid=999,gid=999"},
        },
    }
    health = {"status": "ready", "active_provider_attempts": 0,
              "stale_provider_attempts": 0, "unlinked_started_attempts": 0,
              "provider_called": False}
    return service, [container], health


class ManagedTrackingPreparationTests(unittest.TestCase):
    def setUp(self):
        self.template = TEMPLATE.read_bytes()
        self.original = self.template.replace(managed.TOKEN, OLD.encode())
        self.source = hashlib.sha256(self.original).hexdigest()

    def render(self, **changes):
        args = {"current_sha256": self.source, "current_image": OLD, "candidate_image": NEW}
        args.update(changes)
        return managed.render_unit(self.template, self.original, **args)

    def validate(self, service, containers, health):
        return managed.validate_readback(service, containers, health,
                                         template=self.template, image_ref=NEW, image_id=CONFIG,
                                         unit_sha256=managed.digest(self.template.replace(managed.TOKEN, NEW.encode())))

    def test_old_unit_and_new_running_image_do_not_satisfy_binding(self):
        with self.assertRaisesRegex(ValueError, "managed_unit_image_binding"):
            managed.validate_readback(*snapshots(), template=self.template,
                                      image_ref=NEW, image_id=CONFIG, unit_sha256=self.source)

    def test_only_two_images_change_and_suspended_commands_remain_exact(self):
        candidate, rollback = self.render()
        self.assertEqual(rollback, self.original)
        self.assertEqual(candidate.replace(NEW.encode(), OLD.encode()), self.original)
        self.assertEqual(candidate.count(NEW.encode()), 2)
        self.assertIn(b"NOTEAI_XHS_COLLECTION_SUSPENDED=1", candidate)
        self.assertIn(b"Restart=no\n", candidate)
        self.assertIn(b"--loop --interval-minutes 60 --limit 50", candidate)

    def test_modified_template_or_current_unit_is_rejected(self):
        for old, new in ((b"SUSPENDED=1", b"SUSPENDED=0"),
                         (b"Restart=no", b"Restart=always"),
                         (b"ExecStart=/", b"ExecStartPre=/")):
            with self.subTest(change=old), self.assertRaisesRegex(ValueError, "template_drift"):
                managed.render_unit(self.template.replace(old, new), self.original,
                                    current_sha256=self.source, current_image=OLD, candidate_image=NEW)
        altered = self.original + b"ExecStartPost=/bin/true\n"
        with self.assertRaisesRegex(ValueError, "current_unit_drift"):
            managed.render_unit(self.template, altered, current_sha256=managed.digest(altered),
                                current_image=OLD, candidate_image=NEW)

    def test_saved_real_legacy_config_digest_and_exact_unit_are_supported(self):
        original = self.template.replace(managed.TOKEN, managed.LEGACY_IMAGE.encode())
        self.assertEqual(managed.digest(original), managed.LEGACY_UNIT_SHA256)
        candidate, rollback = managed.render_unit(
            self.template, original, current_sha256=managed.LEGACY_UNIT_SHA256,
            current_image=managed.LEGACY_IMAGE, candidate_image=NEW,
        )
        self.assertEqual(rollback, original)
        self.assertEqual(candidate.count(NEW.encode()), 2)
        before = {"unit_sha256": managed.LEGACY_UNIT_SHA256, "image_ref": managed.LEGACY_IMAGE,
                  "UnitFileState": "disabled", "ActiveState": "inactive", "SubState": "dead",
                  "running_container_count": 0}
        managed.verify_rollback(before, copy.deepcopy(before))
        with self.assertRaises(ValueError):
            self.render(candidate_image=managed.LEGACY_IMAGE)
        with self.assertRaises(ValueError):
            self.render(current_image="sha256:" + "f" * 64)

    def test_mutable_image_or_wrong_binding_rejected(self):
        for options in ({"candidate_image": "registry.example.invalid/noteai/xhs:latest"},
                        {"current_sha256": "0" * 64}, {"current_image": NEW}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.render(**options)

    def test_ready_projection_remains_incomplete_without_other_live_evidence(self):
        result = self.validate(*snapshots())
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertEqual(result["singleton_winner_count"], 1)
        self.assertEqual(result["health_check"], "PASS")
        for absent in ("readiness_credit", "alert_controls", "log_controls", "rollback_rehearsal",
                       "bounded_validation_attempt_identity_sha256"):
            self.assertNotIn(absent, result)

    def test_service_and_singleton_drift_rejected(self):
        for field, value in (("Restart", "always"), ("NRestarts", "1"),
                             ("MainPID", "0"), ("UnitFileState", "enabled"),
                             ("DropInPaths", ["/unexpected.conf"]), ("InvocationID", "0" * 32)):
            service, containers, health = snapshots()
            service[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate(service, containers, health)
        for count in (0, 2):
            service, containers, health = snapshots()
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, "singleton"):
                self.validate(service, containers * count, health)

    def test_actual_container_controls_must_match(self):
        changes = (("Memory", 0), ("NanoCpus", 0), ("PidsLimit", True),
                   ("ReadonlyRootfs", False), ("Privileged", True), ("CapAdd", ["SYS_ADMIN"]),
                   ("NetworkMode", "host"), ("PortBindings", {"80/tcp": []}),
                   ("RestartPolicy", {"Name": "always", "MaximumRetryCount": 0}),
                   ("LogConfig", {"Type": "json-file", "Config": {}}), ("Tmpfs", {}))
        for field, value in changes:
            service, containers, health = snapshots()
            containers[0]["HostConfig"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate(service, containers, health)
        for field, value in (("Suspended", False), ("Image", "sha256:" + "f" * 64),
                             ("RestartCount", 1), ("Mounts", [])):
            service, containers, health = snapshots()
            containers[0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate(service, containers, health)

    def test_secret_shaped_full_inspect_is_rejected_without_echo(self):
        service, containers, health = snapshots()
        containers[0]["Config"]["Env"] = ["TOKEN=synthetic-never-echo"]
        with self.assertRaisesRegex(ValueError, "^config_projection$"):
            self.validate(service, containers, health)

    def test_health_stale_unlinked_unknown_role_or_boolean_counter_rejected(self):
        for field, value in (("stale_provider_attempts", 1), ("unlinked_started_attempts", 1),
                             ("status", "not_ready"), ("provider_called", True),
                             ("active_provider_attempts", False)):
            service, containers, health = snapshots()
            health[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate(service, containers, health)

    def test_exact_stopped_state_rollback_only(self):
        before = {"unit_sha256": self.source, "image_ref": OLD, "UnitFileState": "disabled",
                  "ActiveState": "inactive", "SubState": "dead", "running_container_count": 0}
        managed.verify_rollback(before, copy.deepcopy(before))
        for field, value in (("unit_sha256", "f" * 64), ("image_ref", NEW),
                             ("running_container_count", 1), ("running_container_count", False),
                             ("running_container_count", 0.0), ("UnitFileState", "enabled")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                managed.verify_rollback(before, {**before, field: value})

    def test_cli_writes_exclusive_local_candidate_and_original_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unit = root / "original.service"
            unit.write_bytes(self.original)
            args = ["prepare", "--template", str(TEMPLATE), "--current-unit", str(unit),
                    "--current-sha256", self.source, "--current-image", OLD,
                    "--candidate-image", NEW, "--output-dir", str(root / "prepared")]
            with mock.patch("sys.argv", args), mock.patch("builtins.print"):
                self.assertEqual(managed.main(), 0)
                self.assertEqual((root / "prepared/rollback.service").read_bytes(), self.original)
                with self.assertRaises(FileExistsError):
                    managed.main()


class FakeManagedHost:
    """No system calls, database, provider, environment or real service access."""
    def __init__(self, failure=None):
        self.original = TEMPLATE.read_bytes().replace(managed.TOKEN, OLD.encode())
        self.current = self.original
        self.running = False
        self.calls = []
        self.failure = failure

    def locked(self):
        return nullcontext()

    def unit_bytes(self):
        return self.current

    def prepare_candidate(self, candidate, image_ref, image_id, original_image):
        assert image_ref == NEW and image_id == CONFIG and original_image == OLD

    def stopped_state(self):
        return {"unit_sha256": managed.digest(self.current),
                "image_ref": OLD if self.current == self.original else NEW,
                "UnitFileState": "disabled", "ActiveState": "active" if self.running else "inactive",
                "SubState": "running" if self.running else "dead", "running_container_count": int(self.running)}

    def replace_unit(self, expected, content):
        if managed.digest(self.current) != expected:
            raise ValueError("CAS_conflict")
        self.calls.append("restore" if content == self.original else "apply")
        if content == self.original and self.failure == "restore_conflict":
            self.current += b"# concurrent change\n"
            raise ValueError("CAS_conflict")
        self.current = content
        if content != self.original and self.failure == "apply_unknown":
            raise TimeoutError("synthetic-apply-unknown")

    def reload(self):
        self.calls.append("reload")

    def start_once(self, unit_sha, image_ref, image_id):
        assert unit_sha == managed.digest(self.current) and image_ref == NEW and image_id == CONFIG
        self.calls.append("start")
        self.running = True
        if self.failure == "start_unknown":
            raise TimeoutError("synthetic-secret-do-not-echo")

    def read_managed(self):
        self.calls.append("health")
        data = snapshots()
        if self.failure == "health":
            data[2]["status"] = "not_ready"
        return data

    def stop_candidate(self, unit_sha, image_ref, image_id):
        assert unit_sha == managed.digest(self.current) and image_ref == NEW and image_id == CONFIG
        self.calls.append("stop")
        if self.failure == "stop_unknown":
            raise TimeoutError("synthetic-stop-unknown")
        self.running = False


class ManagedRehearsalTests(unittest.TestCase):
    def exercise(self, host, journal):
        return managed.rehearse(host, journal, template=TEMPLATE.read_bytes(),
                                current_image=OLD, candidate_image=NEW, image_id=CONFIG)

    def test_real_durable_journal_contains_original_before_bounded_actions(self):
        host = FakeManagedHost()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "managed.jsonl"
            journal = Journal(path)
            try:
                result = self.exercise(host, journal)
            finally:
                journal.close()
            records = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(records[0]["event"], "managed_original")
            self.assertEqual(records[0]["unit"].encode(), host.original)
            self.assertEqual(records[-1]["result"], result)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(host.calls, ["apply", "reload", "start", "health", "stop", "restore", "reload"])
        self.assertEqual(host.current, host.original)
        self.assertFalse(host.running)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertTrue(result["restored"])
        self.assertNotIn("rollback_rehearsal", result["partial"])

    def test_health_failure_and_unknown_start_each_restore_without_retry(self):
        for failure in ("health", "start_unknown", "apply_unknown"):
            host = FakeManagedHost(failure)
            journal = mock.Mock()
            result = self.exercise(host, journal)
            with self.subTest(failure=failure):
                self.assertEqual(result["status"], "UNKNOWN")
                self.assertTrue(result["restored"])
                self.assertEqual(host.current, host.original)
                self.assertFalse(host.running)
                self.assertLessEqual(host.calls.count("start"), 1)
                self.assertNotIn("synthetic-secret", json.dumps(result))

    def test_first_journal_failure_prevents_all_mutation(self):
        host = FakeManagedHost()
        journal = mock.Mock()
        journal.write.side_effect = OSError("disk_failure")
        with self.assertRaises(OSError):
            self.exercise(host, journal)
        self.assertEqual(host.calls, [])

    def test_real_journal_fsync_failure_after_start_still_restores(self):
        host = FakeManagedHost()
        with tempfile.TemporaryDirectory() as directory:
            journal = Journal(Path(directory) / "managed.jsonl")
            original_fsync = os.fsync
            calls = 0

            def fail_readback_fsync(fd):
                nonlocal calls
                calls += 1
                if calls == 4:
                    raise OSError("synthetic_fsync_failure")
                original_fsync(fd)

            try:
                with mock.patch("tools.run_item34_tracking_durable.os.fsync", side_effect=fail_readback_fsync):
                    result = self.exercise(host, journal)
                self.assertTrue(journal.failed)
            finally:
                journal.close()
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertTrue(result["restored"])
        self.assertEqual(host.calls.count("start"), 1)
        self.assertEqual(host.calls.count("stop"), 1)
        self.assertEqual(host.current, host.original)

    def test_later_journal_failures_do_not_suppress_stop_or_restore(self):
        for event in ("managed_readback", "managed_stop_intent", "managed_restored", "managed_local_result"):
            host = FakeManagedHost()
            journal = mock.Mock()
            failed = False

            def write(name, **data):
                nonlocal failed
                if name == event:
                    failed = True
                if failed:
                    raise OSError("disk_failure")

            journal.write.side_effect = write
            result = self.exercise(host, journal)
            with self.subTest(event=event):
                self.assertEqual(result["status"], "UNKNOWN")
                self.assertTrue(result["restored"])
                self.assertEqual(host.calls.count("start"), 1)
                self.assertEqual(host.calls.count("stop"), 1)
                self.assertEqual(host.current, host.original)

    def test_failed_stop_or_concurrent_restore_prevents_false_success(self):
        for failure in ("stop_unknown", "restore_conflict"):
            host = FakeManagedHost(failure)
            result = self.exercise(host, mock.Mock())
            with self.subTest(failure=failure):
                self.assertEqual(result["status"], "UNKNOWN")
                self.assertFalse(result["restored"])
                self.assertNotEqual(host.current, host.original)
                self.assertEqual(host.calls.count("start"), 1)
                if failure == "stop_unknown":
                    self.assertNotIn("restore", host.calls)


class NativeRunner:
    """Native-shaped command results only; no systemd/docker subprocess runs."""
    def __init__(self, unit, failure=None):
        self.unit, self.failure = unit, failure
        self.loaded = unit.read_bytes()
        self.state = snapshots()[0]
        self.state.update(ActiveState="inactive", SubState="dead", MainPID="0", InvocationID="")
        self.job = ""
        self.container = None
        self.calls = []

    def __call__(self, argv, **kwargs):
        assert kwargs["env"] == {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"}
        assert kwargs["stderr"] == subprocess.DEVNULL and 0 < kwargs["timeout"] <= 190
        program = Path(argv[0]).name
        if program == "docker":
            assert argv[1] == "--config" and argv[3:5] == ["--host", "unix:///var/run/docker.sock"]
            assert json.loads((Path(argv[2]) / "config.json").read_text()) == {"auths": {}}
            args = argv[5:]
        else:
            assert program == "systemctl"
            args = argv[1:]
        self.calls.append((program, args.copy()))
        raw = ""
        if program == "systemctl":
            if args[0] == "show":
                values = {**self.state, "DropInPaths": "", "Job": self.job,
                          "NeedDaemonReload": "no" if self.loaded == self.unit.read_bytes() else "yes"}
                raw = "\n".join(key + "=" + str(value) for key, value in values.items())
            elif args == ["daemon-reload"]:
                self.loaded = self.unit.read_bytes()
            elif args == ["start", managed.UNIT]:
                self.job = "17"
                if self.failure in ("start_job_unknown", "stop_job_unknown"):
                    raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
                self.state.update(ActiveState="active", SubState="running", MainPID="100", InvocationID="d" * 32)
                self.job = ""
                self.container = snapshots()[1][0]
                if self.failure == "foreign_container":
                    self.container["Image"] = "sha256:" + "f" * 64
            elif args == ["stop", managed.UNIT]:
                if self.failure == "stop_job_unknown":
                    raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
                self.job = ""
                self.container = None
                self.state.update(ActiveState="inactive", SubState="dead", MainPID="0", InvocationID="")
            else:
                raise AssertionError("unreviewed_systemctl_command")
        elif args[:2] == ["image", "inspect"]:
            raw = json.dumps({"Id": CONFIG, "Os": "linux", "Architecture": "amd64",
                              "Entrypoint": ["/app/scripts/docker_entrypoint.sh"],
                              "RepoDigests": [NEW], "Role": "xhs-http"})
        elif args[:2] == ["ps", "-aq"]:
            raw = self.container["Id"] if self.container else ""
        elif args[:2] == ["container", "inspect"]:
            assert args[2:4] == ["--format", managed.container_projection_format()]
            raw = json.dumps(self.container)
        elif args[0] == "exec":
            assert args[1:] == ["e" * 64, "python", "crawler_worker.py", "--healthcheck"]
            raw = json.dumps(snapshots()[2])
        else:
            raise AssertionError("unreviewed_docker_command")
        return SimpleNamespace(returncode=0, stdout=raw.encode())


class NativeManagedBindingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.unit = self.root / "etc/systemd/system" / managed.UNIT
        self.unit.parent.mkdir(parents=True)
        (self.root / "run/lock").mkdir(parents=True)
        self.workdir = self.root / "task"
        self.workdir.mkdir(mode=0o700)
        self.original = TEMPLATE.read_bytes().replace(managed.TOKEN, OLD.encode())
        self.unit.write_bytes(self.original)
        self.unit.chmod(0o644)

    def exercise(self, runner):
        adapter = managed.NativeHostAdapter(self.workdir, root=self.root, runner=runner)
        journal = Journal(self.workdir / "managed.jsonl")
        try:
            return managed.rehearse(adapter, journal, template=TEMPLATE.read_bytes(),
                                    current_image=OLD, candidate_image=NEW, image_id=CONFIG)
        finally:
            journal.close()

    def test_native_binding_uses_bounded_argv_and_restores_real_temporary_unit(self):
        runner = NativeRunner(self.unit)
        result = self.exercise(runner)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertTrue(result["restored"])
        self.assertEqual(self.unit.read_bytes(), self.original)
        commands = [args for program, args in runner.calls if program == "systemctl" and args[0] != "show"]
        self.assertEqual(commands, [["daemon-reload"], ["start", managed.UNIT],
                                    ["stop", managed.UNIT], ["daemon-reload"]])
        self.assertFalse(list(self.workdir.glob("managed-docker-*")))

    def test_start_timeout_with_pending_job_and_no_container_still_stops_unit(self):
        runner = NativeRunner(self.unit, "start_job_unknown")
        result = self.exercise(runner)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertTrue(result["restored"])
        self.assertEqual(runner.job, "")
        self.assertEqual(sum(args == ["start", managed.UNIT] for _, args in runner.calls), 1)
        self.assertEqual(sum(args == ["stop", managed.UNIT] for _, args in runner.calls), 1)
        self.assertFalse(any(args[0] == "exec" for _, args in runner.calls))

    def test_stop_timeout_pending_job_prevents_unit_restore(self):
        runner = NativeRunner(self.unit, "stop_job_unknown")
        result = self.exercise(runner)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertFalse(result["restored"])
        self.assertEqual(runner.job, "17")
        self.assertNotEqual(self.unit.read_bytes(), self.original)
        self.assertEqual(sum(args == ["stop", managed.UNIT] for _, args in runner.calls), 1)

    def test_foreign_running_container_is_not_execed_or_stopped(self):
        runner = NativeRunner(self.unit, "foreign_container")
        result = self.exercise(runner)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertFalse(result["restored"])
        self.assertFalse(any(args[0] in ("exec", "stop") for _, args in runner.calls))

    def test_stopped_same_name_residue_prevents_any_mutation(self):
        runner = NativeRunner(self.unit)
        runner.container = snapshots()[1][0]
        runner.container["State"]["Running"] = False
        with self.assertRaisesRegex(ValueError, "managed_not_quiescent"):
            self.exercise(runner)
        self.assertEqual(self.unit.read_bytes(), self.original)
        self.assertFalse(any(args[0] in ("start", "stop", "daemon-reload") for _, args in runner.calls))

    def test_symlink_unit_and_cooperating_second_owner_are_rejected(self):
        adapter = managed.NativeHostAdapter(self.workdir, root=self.root, runner=NativeRunner(self.unit))
        second = managed.NativeHostAdapter(self.workdir, root=self.root, runner=NativeRunner(self.unit))
        with adapter.locked():
            with self.assertRaises(BlockingIOError), second.locked():
                self.fail("lock unexpectedly acquired")
        copy_path = self.root / "saved-unit"
        self.unit.rename(copy_path)
        self.unit.symlink_to(copy_path)
        with self.assertRaises(OSError):
            adapter.unit_bytes()

    def test_test_root_requires_injected_runner_and_sticky_lock_directory_is_safe(self):
        with self.assertRaisesRegex(ValueError, "isolated_root_requires_test_runner"):
            managed.NativeHostAdapter(self.workdir, root=self.root)
        with self.assertRaisesRegex(ValueError, "managed_runner_must_be_callable"):
            managed.NativeHostAdapter(self.workdir, root=self.root, runner=False)
        falsey_runner = mock.MagicMock()
        falsey_runner.__bool__.return_value = False
        self.assertIs(managed.NativeHostAdapter(self.workdir, root=self.root, runner=falsey_runner).runner,
                      falsey_runner)
        lock_directory = self.root / "run/lock"
        lock_directory.chmod(0o1777)
        adapter = managed.NativeHostAdapter(self.workdir, root=self.root, runner=NativeRunner(self.unit))
        with adapter.locked():
            self.assertEqual(adapter.unit_bytes(), self.original)
        lock_directory.chmod(0o0777)
        with self.assertRaisesRegex(ValueError, "managed_directory_identity"), adapter.locked():
            self.fail("unsafe lock directory accepted")


class PrivateTrackingEnvTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.work = self.root / "task"
        self.work.mkdir(mode=0o700)
        self.target = self.root / "etc/noteai/xhs-tracking.env"
        self.target.parent.mkdir(parents=True)
        self.original = (b"# keep this comment\nDATABASE_URL=FAKE_DATABASE\n"
                         b"NOTEAI_XHS_COOKIES_JSON=[]\nNOTEAI_XHS_COLLECTION_SUSPENDED=0\n"
                         b"UNRELATED=keep-exactly\nNOTEAI_XHS_WEB_SSK_JSON=old\n")
        self.cookie = self.work / "cookies.env"
        self.access = self.work / "access.env"
        self.records = [{"name": "a1", "value": "FAKE_A1"},
                        {"name": "web_session", "value": "FAKE_SESSION"}]
        self.context = {"note_id": "6a7954010000000026034707",
                        "xsec_token": "FAKE_ACCESS", "xsec_source": "pc_user"}
        self.write(self.target, self.original)
        self.write(self.cookie, b"NOTEAI_XHS_COOKIES_JSON=" + json.dumps(self.records).encode() + b"\n")
        self.write(self.access, b"NOTEAI_XHS_NOTE_ACCESS_JSON=" + json.dumps(self.context).encode() + b"\n")
        self.adapter = SimpleNamespace(root=self.root, workdir=self.work, active=True,
                                       stopped_state=mock.Mock(return_value={}))
        self.journal = Journal(self.work / "journal.jsonl")
        self.addCleanup(self.journal.close)
        self.update = managed.TrackingEnvUpdate(self.adapter, self.journal)

    @staticmethod
    def write(path, raw):
        path.write_bytes(raw)
        path.chmod(0o600)

    def prepare(self):
        self.update.prepare(self.cookie, self.access)

    def test_actual_private_files_apply_and_restore_original_bytes_without_log_secrets(self):
        self.prepare()
        self.update.apply()
        changed = self.target.read_bytes()
        for line in (b"# keep this comment\n", b"DATABASE_URL=FAKE_DATABASE\n",
                     b"UNRELATED=keep-exactly\n", b"NOTEAI_XHS_COLLECTION_SUSPENDED=0\n"):
            self.assertIn(line, changed)
        self.assertIn(b"NOTEAI_XHS_PROTOCOL=pc_v5\n", changed)
        self.assertIn(b"NOTEAI_XHS_WEB_SSK_JSON=\n", changed)
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)
        # Rehydrate the original task after a lost connection, without preparing again.
        recovered = managed.TrackingEnvUpdate(self.adapter, self.journal)
        recovered.restore()
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertEqual(recovered.candidate.read_bytes(), changed)
        self.assertNotIn(b"FAKE_", (self.work / "journal.jsonl").read_bytes())
        with self.assertRaises(FileExistsError):
            self.prepare()

    def test_concurrent_config_change_is_never_overwritten_on_apply_or_restore(self):
        self.prepare()
        drift = self.original + b"NEW_OWNER_SETTING=keep\n"
        self.write(self.target, drift)
        for operation in (self.update.apply, self.update.restore):
            with self.assertRaisesRegex(ValueError, "tracking_env_cas_conflict"):
                operation()
            self.assertEqual(self.target.read_bytes(), drift)

    def test_candidate_cannot_change_database_or_unrelated_keys(self):
        self.prepare()
        self.write(self.update.candidate, self.update.candidate.read_bytes().replace(
            b"FAKE_DATABASE", b"WRONG_DATABASE"))
        with self.assertRaisesRegex(ValueError, "tracking_env_candidate_drift"):
            self.update.apply()
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_bad_object_duplicate_keys_or_symlink_never_mutate_managed_env(self):
        invalid = self.access.read_bytes().replace(b"6a7954010000000026034707", b"0" * 24)
        with self.assertRaisesRegex(ValueError, "^tracking_env_candidate_invalid$"):
            managed.merge_tracking_env(self.original, self.cookie.read_bytes(), invalid)
        with self.assertRaisesRegex(ValueError, "^tracking_env_candidate_invalid$"):
            managed.merge_tracking_env(self.original, self.cookie.read_bytes() * 2, self.access.read_bytes())
        link = self.work / "cookie-link.env"
        link.symlink_to(self.cookie)
        with self.assertRaises(OSError):
            self.update.prepare(link, self.access)
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_fsync_failure_after_replace_remains_recoverable_without_reapply(self):
        self.prepare()
        write = self.journal.write
        def fail_result(event, **data):
            if event == "tracking_env_applied":
                raise OSError("synthetic storage failure")
            return write(event, **data)
        with mock.patch.object(self.journal, "write", side_effect=fail_result):
            with self.assertRaises(OSError):
                self.update.apply()
        self.assertEqual(self.target.read_bytes(), self.update.candidate.read_bytes())
        self.update.restore()
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_lock_and_quiescent_service_are_required(self):
        self.adapter.active = False
        with self.assertRaisesRegex(ValueError, "managed_lock_required"):
            self.prepare()
        self.adapter.active = True
        self.adapter.stopped_state.side_effect = ValueError("managed_not_quiescent")
        with self.assertRaisesRegex(ValueError, "managed_not_quiescent"):
            self.prepare()
        self.assertFalse(self.update.original.exists())

    def test_persistent_journal_failure_cannot_prevent_verified_env_restore(self):
        self.prepare()
        self.update.apply()
        self.journal.failed = True  # Real Journal remains failed after any fsync error.
        recovered = managed.TrackingEnvUpdate(self.adapter, self.journal)
        with self.assertRaisesRegex(ValueError, "tracking_env_restored_journal_unknown"):
            recovered.restore()
        self.assertEqual(self.target.read_bytes(), self.original)


class ManagedLauncherTests(unittest.TestCase):
    def args(self):
        return ["managed", "--journal", "/unopened/managed.host.jsonl", "--image", NEW,
                "--current-image", OLD, "--image-id", CONFIG]

    def test_managed_action_reuses_journal_and_never_loads_frozen_sampler(self):
        result = {"status": "INCOMPLETE", "restored": True, "failed_steps": [], "partial": {}}
        with mock.patch.object(durable_managed.os, "geteuid", return_value=0), \
                mock.patch.object(durable_managed, "Journal") as journal, \
                mock.patch.object(durable_managed, "load_wrapper") as old_sampler, \
                mock.patch.object(managed, "NativeHostAdapter") as adapter, \
                mock.patch.object(managed, "rehearse", return_value=result) as rehearsal, \
                mock.patch("builtins.print"):
            self.assertEqual(durable_managed.main(self.args()), 0)
            old_sampler.assert_not_called()
            adapter.assert_called_once_with(Path("/unopened"))
            self.assertEqual(rehearsal.call_args.kwargs["candidate_image"], NEW)
            self.assertEqual(rehearsal.call_args.kwargs["current_image"], OLD)
            journal.return_value.close.assert_called_once()

    def test_unknown_result_is_nonzero_and_mixed_old_arguments_are_rejected(self):
        result = {"status": "UNKNOWN", "restored": False, "failed_steps": ["stop"], "partial": None}
        with mock.patch.object(durable_managed.os, "geteuid", return_value=0), \
                mock.patch.object(durable_managed, "Journal"), \
                mock.patch.object(durable_managed, "load_wrapper") as old_sampler, \
                mock.patch.object(managed, "NativeHostAdapter"), \
                mock.patch.object(managed, "rehearse", return_value=result) as rehearsal, \
                mock.patch("builtins.print"):
            self.assertEqual(durable_managed.main(self.args()), 1)
            rehearsal.return_value = {**result, "restored": True, "failed_steps": []}
            self.assertEqual(durable_managed.main(self.args()), 1)
            with self.assertRaisesRegex(ValueError, "managed_arguments"):
                durable_managed.main(self.args() + ["--stage", "24h"])
            with self.assertRaisesRegex(ValueError, "managed_arguments_require_managed_action"):
                durable_managed.main(["run", "--journal", "/unopened/old", "--current-image", OLD])
            old_sampler.assert_not_called()

    def test_initial_journal_failure_prevents_adapter_construction(self):
        with mock.patch.object(durable_managed.os, "geteuid", return_value=0), \
                mock.patch.object(durable_managed, "Journal") as journal, \
                mock.patch.object(managed, "NativeHostAdapter") as adapter:
            journal.return_value.write.side_effect = OSError("disk_failure")
            with self.assertRaises(OSError):
                durable_managed.main(self.args())
            adapter.assert_not_called()
            journal.return_value.close.assert_called_once()

    def test_private_inputs_require_pair_and_managed_action_before_journal(self):
        for argv in (self.args() + ["--cookie-candidate", "/unused/cookie"],
                     self.args() + ["--note-access-candidate", "/unused/access"],
                     ["run", "--journal", "/unused/journal", "--cookie-candidate", "/unused/cookie"],
                     ["restore", "--journal", "/unused/journal", "--note-access-candidate", "/unused/access"]):
            with mock.patch.object(os, "geteuid", return_value=0), \
                    mock.patch.object(durable_managed, "Journal") as journal:
                with self.assertRaisesRegex(ValueError, "managed_arguments"):
                    durable_managed.main(argv)
                journal.assert_not_called()


class ManagedPrivateEnvIntegrationTests(PrivateTrackingEnvTests):
    """Real private files and durable journal; only native service actions are fake."""
    def execute(self, *, failure=None, journal_failure=None):
        fixture = self
        class Host(FakeManagedHost):
            active = False
            @contextmanager
            def locked(self):
                fixture.assertFalse(self.active, "nested lock")
                self.active = True
                try:
                    yield
                finally:
                    self.active = False

            def stopped_state(self):
                fixture.assertTrue(self.active)
                if self.running:
                    raise ValueError("managed_not_quiescent")
                return super().stopped_state()

            def read_managed(self):
                if self.failure == "env_drift":
                    fixture.write(fixture.target, b"UNRELATED=concurrent-owner-change\n")
                return super().read_managed()

        host = Host(failure)
        host.root, host.workdir = self.root, self.work
        original_write = self.journal.write
        def write(event, **data):
            if event == journal_failure:
                self.journal.failed = True
            return original_write(event, **data)
        with mock.patch.object(durable_managed, "Journal", return_value=self.journal), \
                mock.patch.object(self.journal, "close"), \
                mock.patch.object(self.journal, "write", side_effect=write), \
                mock.patch.object(managed, "NativeHostAdapter", return_value=host), \
                mock.patch.object(durable_managed, "load_wrapper", side_effect=AssertionError("sampler")), \
                mock.patch("builtins.print"):
            # Keep the real private-file owner identity in the isolated fixture.
            parsed = SimpleNamespace(journal=self.work / "journal.jsonl", image=NEW,
                                     current_image=OLD, image_id=CONFIG,
                                     cookie_candidate=self.cookie, note_access_candidate=self.access)
            result = durable_managed.execute_managed(parsed)
        return host, result

    def test_success_retains_candidate_after_durable_result_under_single_lock(self):
        host, result = self.execute()
        self.assertEqual(result, 0)
        self.assertEqual(host.current, host.original)
        self.assertEqual(host.calls.count("start"), 1)
        self.assertEqual(self.target.read_bytes(), self.update.candidate.read_bytes())
        records = [json.loads(line) for line in (self.work / "journal.jsonl").read_text().splitlines()]
        self.assertTrue(records[-1]["result"]["tracking_env_applied"])
        self.assertEqual(records[-1]["result"]["status"], "INCOMPLETE")
        self.assertNotIn("FAKE_SESSION", json.dumps(records))

    def test_failed_managed_start_restores_both_unit_and_env_once(self):
        host, result = self.execute(failure="start_unknown")
        self.assertEqual(result, 1)
        self.assertEqual(host.current, host.original)
        self.assertFalse(host.running)
        self.assertEqual(host.calls.count("start"), 1)
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_final_result_storage_failure_restores_env_without_replaying_cycle(self):
        with self.assertRaisesRegex(ValueError, "tracking_env_restored_journal_unknown"):
            self.execute(journal_failure="result")
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_apply_result_storage_failure_restores_env_before_managed_start(self):
        with self.assertRaisesRegex(ValueError, "tracking_env_restored_journal_unknown"):
            self.execute(journal_failure="tracking_env_applied")
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_concurrent_env_change_during_cycle_is_unknown_and_never_overwritten(self):
        with self.assertRaisesRegex(ValueError, "tracking_env_cas_conflict"):
            self.execute(failure="env_drift")
        self.assertEqual(self.target.read_bytes(), b"UNRELATED=concurrent-owner-change\n")
        records = [json.loads(line) for line in (self.work / "journal.jsonl").read_text().splitlines()]
        self.assertFalse(any(r["event"] == "result" for r in records))
