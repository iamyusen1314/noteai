import importlib.util
import json
import stat
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "deploy" / "production" / "internal_zero_provider_smoke.py"
SPEC = importlib.util.spec_from_file_location("internal_zero_provider_smoke", SOURCE)
smoke = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(smoke)


class FakeHost:
    def __init__(self, fail=None):
        self.states = {}
        self.containers = {}
        self.calls = []
        self.fail = fail

    def begin_cleanup(self):
        self.calls.append(("begin_cleanup",))

    def docker_binding(self):
        self.calls.append(("docker_binding",))
        return (1, 2, stat.S_IFSOCK | 0o660, 0, 999, 1)

    def unit_identity(self, unit, digest):
        self.calls.append(("identity", unit))
        self.states.setdefault(unit, "active" if unit in {"noteai-api.service", "noteai-admin.service"} else "inactive")
        container = next((entry[-1] for spec in smoke.MODES.values() for entry in spec["active"] + spec["dormant"] if entry[-2] == digest), None)
        if container is not None:
            self.containers.setdefault(container, 1 if self.states[unit] == "active" else 0)

    def unit_state(self, unit):
        active = self.states[unit] == "active"
        return {
            "LoadState": "loaded", "ActiveState": "active" if active else "inactive",
            "SubState": "running" if active else "dead", "Result": "success",
            "NRestarts": "0", "enabled": "enabled" if unit in {"noteai-api.service", "noteai-admin.service"} else "disabled",
            "enabled_rc": 0 if unit in {"noteai-api.service", "noteai-admin.service"} else 1,
            "FragmentPath": smoke.SYSTEMD_ROOT + "/" + unit,
            "DropInPaths": "", "NeedDaemonReload": "no",
        }

    def container_present(self, name):
        return self.containers.get(name, 0)

    def runtime_fingerprint(self, name):
        return "f" * 64

    def public_listener_count(self, name):
        return 0

    def start(self, unit):
        self.calls.append(("start", unit))
        container = next(entry[-1] for spec in smoke.MODES.values() for entry in spec["dormant"] if entry[1] == unit)
        self.states[unit] = "active"
        self.containers[container] = 1
        if self.fail == ("start", unit):
            raise smoke.SmokeError("injected_start")

    def stop(self, unit):
        self.calls.append(("stop", unit))
        if self.fail == ("stop", unit):
            raise smoke.SmokeError("injected_stop")
        container = next(entry[-1] for spec in smoke.MODES.values() for entry in spec["dormant"] if entry[1] == unit)
        self.states[unit] = "inactive"
        self.containers[container] = 0

    def exec_json(self, container, args, code):
        self.calls.append(("exec", container, args[-1]))
        command = args[-1]
        if command == "--healthcheck":
            if "trends" in container:
                return {"status": "ready", "provider_called": False,
                        "active_provider_attempts": 0, "unknown_provider_attempts": 0,
                        "unlinked_provider_attempts": 0}
            if "tracking" in container:
                return {"status": "ready", "provider_called": False,
                        "active_provider_attempts": 0, "stale_provider_attempts": 0,
                        "unlinked_started_attempts": 0}
            if "dispatcher" in container:
                return {"ok": True, "suspended": True, "provider_called": False,
                        "database_write": False, "pending_outbox": 2,
                        "exhausted_outbox": 0}
            return {"ok": True, "suspended": True, "provider_called": False,
                    "database_write": False, "needs_manual": 0, "expired_ready": 0,
                    "stale_provider_outcome": 0, "recoverable_unstarted": 1}
        if "trends" in container:
            return {"ok": True, "skipped": True, "reason": "collection_suspended", "provider_called": False, "database_writes": 0, "snapshot_written": False}
        if "tracking" in container:
            return {"skipped": True, "reason": "collection_suspended", "collected": 0}
        return {"status": "suspended", "provider_called": False, "database_write": False}

    def http_json(self, port, method, path, status):
        self.calls.append(("http", port, method, path, status))
        if port == 8002:
            if path == "/health/live":
                return {"status": "ok", "service": "noteai-payment"}
            if path == "/health/ready":
                return {"status": "not_ready", "service": "noteai-payment", "checks": {
                    "runtime_role": {"ok": True}, "database": {"ok": True},
                    "database_role": {"ok": True}, "callback_enabled": {"ok": False}}}
            return {"detail": "PAYMENT_CALLBACK_UNAVAILABLE"}
        service = "noteai-admin" if port == 8001 else "noteai-api"
        if path == "/health/live":
            return {"status": "ok", "service": service}
        if path in {"/health/ready", "/admin/health"}:
            return {"status": "ready", "service": service, "checks": {"database": {"ok": True}, "model": {"ok": True}}}
        if path == "/admin/capabilities":
            return {"detail": "\u9700\u8981\u7ba1\u7406\u5458\u6743\u9650"}
        if path == "/legal/contracts":
            return {"version": "fixed", "status": "pending"}
        if path == "/billing/tiers":
            return {"tiers": {"free": {"price": 0}}}
        return {"ordering_available": False, "currency": "CNY", "auto_renewal": False}


class InternalZeroProviderSmokeTests(unittest.TestCase):
    def test_four_modes_are_exact_and_source_has_no_mutating_external_tools(self):
        self.assertEqual(set(smoke.MODES), {"api-c", "api-f", "worker-c", "worker-f"})
        source = SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("curl ", source)
        self.assertNotIn("aliyun", source.lower())
        self.assertNotIn("docker pull", source)
        self.assertIn('"--context=default", "context", "inspect"', source)
        self.assertIn('"--host=" + DOCKER_HOST_URI', source)
        self.assertEqual(smoke.DOCKER_HOST_URI, "unix:///var/run/docker.sock")
        self.assertEqual(source.count("self._manager_unit_identity(unit, path)"), 2)
        self.assertNotIn("systemctl enable", source)
        self.assertNotIn("systemctl restart", source)
        self.assertNotIn("DELETE FROM", source)
        self.assertNotIn("INSERT INTO", source)
        self.assertTrue(SOURCE.read_bytes().endswith(b"\n"))
        SOURCE.read_bytes().decode("ascii")

    def test_all_modes_pass_and_restore_every_started_unit_serially(self):
        expected = {"api-c": (8, 2), "api-f": (5, 2), "worker-c": (0, 1), "worker-f": (0, 1)}
        for mode, counts in expected.items():
            with self.subTest(mode=mode):
                host = FakeHost()
                rc, result = smoke.execute(mode, host)
                self.assertEqual(rc, 0)
                self.assertEqual(result["status"], "PASS")
                self.assertEqual((result["loopback_endpoint_count"], result["service_start_count"]), counts)
                self.assertEqual(result["service_start_count"], result["service_stop_count"])
                self.assertEqual(result["provider_call_count"], 0)
                self.assertEqual(result["production_database_mutation_count"], 0)
                self.assertTrue(result["original_state_restored"])
                starts = [call for call in host.calls if call[0] == "start"]
                stops = [call for call in host.calls if call[0] == "stop"]
                bindings = [call for call in host.calls if call[0] == "docker_binding"]
                self.assertEqual(len(starts), len(stops))
                self.assertEqual(len(bindings), 2)
                for role, unit, _digest, container in smoke.MODES[mode]["dormant"]:
                    self.assertEqual(host.states[unit], "inactive")
                    self.assertEqual(host.containers[container], 0)

    def test_api_c_payment_negative_is_exact_503_contract(self):
        host = FakeHost()
        rc, result = smoke.execute("api-c", host)
        self.assertEqual(rc, 0)
        payment = [item for item in result["roles"] if item["role"] == "payment"][0]
        self.assertTrue(payment["expected_negative_passed"])
        payment_calls = [call for call in host.calls if call[:2] == ("http", 8002)]
        self.assertIn(("http", 8002, "GET", "/health/ready", 503), payment_calls)
        self.assertIn(("http", 8002, "POST", "/payments/adapay/callback", 503), payment_calls)

    def test_role_counters_and_skip_flags_reject_bool_string_and_coercion_aliases(self):
        cases = (
            ("dispatcher", "noteai-ai-dispatcher", "health", "pending_outbox", True),
            ("dispatcher", "noteai-ai-dispatcher", "health", "pending_outbox", -1),
            ("dispatcher", "noteai-ai-dispatcher", "health", "exhausted_outbox", False),
            ("worker", "noteai-ai-worker", "health", "needs_manual", False),
            ("worker", "noteai-ai-worker", "health", "expired_ready", "0"),
            ("worker", "noteai-ai-worker", "health", "stale_provider_outcome", False),
            ("worker", "noteai-ai-worker", "health", "recoverable_unstarted", "1"),
            ("worker", "noteai-ai-worker", "health", "recoverable_unstarted", -1),
            ("trends", "noteai-xhs-trends", "one_shot", "skipped", 1),
            ("trends", "noteai-xhs-trends", "health", "active_provider_attempts", False),
            ("trends", "noteai-xhs-trends", "health", "unknown_provider_attempts", "0"),
            ("trends", "noteai-xhs-trends", "health", "unlinked_provider_attempts", False),
            ("trends", "noteai-xhs-trends", "one_shot", "database_writes", False),
            ("tracking", "noteai-xhs-tracking", "health", "active_provider_attempts", False),
            ("tracking", "noteai-xhs-tracking", "health", "stale_provider_attempts", "0"),
            ("tracking", "noteai-xhs-tracking", "health", "unlinked_started_attempts", False),
            ("tracking", "noteai-xhs-tracking", "one_shot", "skipped", "yes"),
            ("tracking", "noteai-xhs-tracking", "one_shot", "collected", False),
        )
        for role, container, phase, field, alias in cases:
            with self.subTest(role=role, phase=phase, field=field, alias=alias):
                host = FakeHost()
                original = host.exec_json

                def changed(name, args, code):
                    value = original(name, args, code)
                    current = "health" if args[-1] == "--healthcheck" else "one_shot"
                    if current == phase:
                        value[field] = alias
                    return value

                host.exec_json = changed
                with self.assertRaisesRegex(smoke.SmokeError, "role_contract"):
                    smoke._role_checks(host, role, container)

    def test_pre_mutation_failure_is_fail_and_does_not_stop_any_unit(self):
        host = FakeHost()
        host.http_json = lambda *_args: {"status": "wrong"}
        rc, result = smoke.execute("api-f", host)
        self.assertEqual(rc, 3)
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["runtime_mutation_attempted"])
        self.assertEqual(result["cleanup"], "NOT_NEEDED")
        self.assertFalse(any(call[0] == "stop" for call in host.calls))
        self.assertFalse(result["automatic_retry_allowed"])

    def test_post_start_failure_is_unknown_but_restores_only_started_unit(self):
        unit = "noteai-xhs-trends.service"
        host = FakeHost(fail=("start", unit))
        rc, result = smoke.execute("api-f", host)
        self.assertEqual(rc, 4)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["cleanup"], "RESTORED")
        self.assertIn(("stop", unit), host.calls)
        self.assertNotIn(("stop", "noteai-xhs-tracking.service"), host.calls)
        self.assertEqual(host.states[unit], "inactive")
        self.assertFalse(result["same_invocation_replay_allowed"])

    def test_cleanup_failure_remains_unknown_and_no_replay(self):
        unit = "noteai-ai-worker.service"
        host = FakeHost(fail=("stop", unit))
        rc, result = smoke.execute("worker-c", host)
        self.assertEqual(rc, 4)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["cleanup"], "UNKNOWN")
        self.assertFalse(result["automatic_retry_allowed"])

    def test_non_root_cli_fails_canonically_without_host_action(self):
        code = (
            "import importlib.util;"
            f"s=importlib.util.spec_from_file_location('m',{str(SOURCE)!r});"
            "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
            "m.os.geteuid=lambda:1;raise SystemExit(m.main(['--mode','api-c']))"
        )
        result = subprocess.run([sys.executable, "-c", code], text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 3)
        payload = json.loads(result.stderr)
        self.assertEqual(payload["status"], "FAIL")
        self.assertEqual(payload["code"], "euid")
        self.assertFalse(payload["automatic_retry_allowed"])

    def test_systemd_manager_binding_is_exact_and_state_rejects_drop_ins(self):
        unit = "noteai-ai-worker.service"
        path = smoke.SYSTEMD_ROOT + "/" + unit
        host = object.__new__(smoke.Host)
        host.command = mock.Mock(return_value=(0, (
            "FragmentPath=" + path + "\n"
            "DropInPaths=\n"
            "NeedDaemonReload=no\n"
        ).encode("ascii")))
        host._manager_unit_identity(unit, path)
        host.command.assert_called_once()
        for changed in (
            "FragmentPath=/tmp/other.service\nDropInPaths=\nNeedDaemonReload=no\n",
            "FragmentPath=" + path + "\nDropInPaths=/etc/systemd/system/x.conf\nNeedDaemonReload=no\n",
            "FragmentPath=" + path + "\nDropInPaths=\nNeedDaemonReload=yes\n",
        ):
            with self.subTest(changed=changed), mock.patch.object(
                    host, "command", return_value=(0, changed.encode("ascii"))):
                with self.assertRaisesRegex(smoke.SmokeError, "unit_identity"):
                    host._manager_unit_identity(unit, path)

        fake = FakeHost()
        fake.unit_identity(unit, smoke.MODES["worker-c"]["dormant"][0][2])
        original = fake.unit_state
        fake.unit_state = lambda value: {
            **original(value),
            "DropInPaths": "/etc/systemd/system/noteai-ai-worker.service.d/x.conf",
        }
        with self.assertRaisesRegex(smoke.SmokeError, "inactive_unit_state"):
            smoke._require_state(fake, unit, "inactive")

    def test_docker_binding_requires_default_local_context_and_stable_root_socket(self):
        host = object.__new__(smoke.Host)
        responses = iter(((0, b"unix:///var/run/docker.sock\n"), (0, b"28.0.0\n")))
        host.command = mock.Mock(side_effect=lambda *_args, **_kwargs: next(responses))
        socket_row = SimpleNamespace(
            st_dev=1, st_ino=2, st_mode=stat.S_IFSOCK | 0o660,
            st_uid=0, st_gid=999, st_nlink=1,
        )
        with mock.patch.object(smoke.os, "lstat", return_value=socket_row):
            self.assertEqual(
                host.docker_binding(),
                (1, 2, stat.S_IFSOCK | 0o660, 0, 999, 1),
            )
        calls = host.command.call_args_list
        self.assertIn("--context=default", calls[0].args[0])
        self.assertIn("--host=unix:///var/run/docker.sock", calls[1].args[0])
        host.command = mock.Mock(return_value=(0, b"ok\n"))
        with mock.patch.object(smoke.os, "lstat", return_value=socket_row):
            self.assertEqual(
                host.docker_command(["container", "ls"], "container_state"),
                (0, b"ok\n"),
            )
        self.assertEqual(
            host.command.call_args.args[0][:2],
            ["/usr/bin/docker", "--host=unix:///var/run/docker.sock"],
        )

        host.command = mock.Mock(return_value=(0, b"tcp://remote.invalid:2376\n"))
        with mock.patch.object(smoke.os, "lstat", return_value=socket_row):
            with self.assertRaisesRegex(smoke.SmokeError, "docker_context"):
                host.docker_binding()
        not_socket = SimpleNamespace(**{**socket_row.__dict__, "st_mode": stat.S_IFREG | 0o660})
        with mock.patch.object(smoke.os, "lstat", return_value=not_socket):
            with self.assertRaisesRegex(smoke.SmokeError, "docker_socket"):
                host._docker_socket_identity()

    def test_global_deadline_reserves_cleanup_before_provider_timeout(self):
        now = [100.0]
        host = smoke.Host("worker-c", clock=lambda: now[0])
        self.assertEqual(host._bounded_timeout(30), 30.0)
        now[0] += smoke.MODE_RUN_BUDGET_SECONDS["worker-c"] - 5
        self.assertEqual(host._bounded_timeout(30), 5.0)
        host.begin_cleanup()
        self.assertEqual(
            host._bounded_timeout(999),
            smoke.CLEANUP_RESERVE_SECONDS,
        )
        now[0] += smoke.CLEANUP_RESERVE_SECONDS + 1
        with self.assertRaisesRegex(smoke.SmokeError, "cleanup_deadline"):
            host._bounded_timeout(1)
        self.assertEqual(
            smoke.REQUIRED_PROVIDER_TIMEOUT_SECONDS["worker-c"],
            smoke.MODE_RUN_BUDGET_SECONDS["worker-c"]
            + smoke.CLEANUP_RESERVE_SECONDS
            + smoke.WRAPPER_SETUP_WORST_CASE_SECONDS
            + smoke.WRAPPER_CLEANUP_RESERVE_SECONDS,
        )
        for mode, worst in smoke.MODE_COMMAND_WORST_CASE_SECONDS.items():
            with self.subTest(mode=mode):
                self.assertGreater(smoke.MODE_RUN_BUDGET_SECONDS[mode], worst)
        self.assertGreater(
            smoke.CLEANUP_RESERVE_SECONDS,
            smoke.CLEANUP_COMMAND_WORST_CASE_SECONDS,
        )

    def test_loopback_http_uses_one_total_deadline_across_socket_operations(self):
        now = [100.0]
        host = smoke.Host("worker-c", clock=lambda: now[0])

        class Socket:
            def __init__(self):
                self.timeouts = []

            def settimeout(self, value):
                self.timeouts.append(value)

        class Response:
            status = 200

            def read(self, _limit):
                now[0] += 1
                return b"{}"

        class Connection:
            def __init__(self, _host, _port, timeout):
                self.initial_timeout = timeout
                self.sock = None

            def connect(self):
                now[0] += 1
                self.sock = Socket()

            def request(self, *_args, **_kwargs):
                now[0] += 1

            def getresponse(self):
                now[0] += 1
                return Response()

            def close(self):
                return None

        connection = None

        def factory(*args, **kwargs):
            nonlocal connection
            connection = Connection(*args, **kwargs)
            return connection

        with mock.patch.object(smoke.http.client, "HTTPConnection", side_effect=factory):
            self.assertEqual(host.http_json(8000, "GET", "/x", 200), {})
        self.assertEqual(connection.initial_timeout, 6.0)
        self.assertEqual(connection.sock.timeouts, [5.0, 4.0, 3.0])


if __name__ == "__main__":
    unittest.main()
