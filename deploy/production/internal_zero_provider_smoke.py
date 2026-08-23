#!/usr/bin/env python3
"""Run one host-local, provider-free Item27 production smoke fragment.

The four modes are dispatched separately.  Every dormant service is required
to be inactive/dead and disabled before it is touched.  Only a unit started by
this invocation is stopped during cleanup; no unit is enabled, restarted, or
otherwise reconfigured.
"""

import argparse
import hashlib
import http.client
import json
import os
import signal
import stat
import subprocess
import sys
import time


TASK_ID = "PROD-FIRST-LAUNCH-INTERNAL-SMOKE-001"
SCHEMA = "noteai.item27.internal-zero-provider-smoke.v1"
SYSTEMD_ROOT = "/etc/systemd/system"
DOCKER_SOCKET_PATH = "/var/run/docker.sock"
DOCKER_HOST_URI = "unix://" + DOCKER_SOCKET_PATH
PATH_VALUE = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
COMMAND_ENV = {"PATH": PATH_VALUE, "LC_ALL": "C", "LANG": "C"}

# These worst cases sum every per-command timeout in each mode, including two
# Docker binding checks and the before/after systemd load checks.  Run budgets
# add a bounded Python/host scheduling margin above those command sums.
MODE_COMMAND_WORST_CASE_SECONDS = {
    "api-c": 2796,
    "api-f": 2250,
    "worker-c": 870,
    "worker-f": 870,
}
MODE_RUN_BUDGET_SECONDS = {
    "api-c": 2880,
    "api-f": 2340,
    "worker-c": 960,
    "worker-f": 960,
}
CLEANUP_COMMAND_WORST_CASE_SECONDS = 180
CLEANUP_RESERVE_SECONDS = 300
WRAPPER_SETUP_WORST_CASE_SECONDS = 60
WRAPPER_CLEANUP_RESERVE_SECONDS = 60
CONTAINER_READY_TIMEOUT_SECONDS = 15
CONTAINER_READY_POLL_SECONDS = 0.2
# Cleanup has a separate reserve.  The renderer additionally reserves bounded
# wrapper setup/import time and a final wrapper cleanup interval so Cloud
# Assistant cannot terminate the process while runtime cleanup runs.
REQUIRED_PROVIDER_TIMEOUT_SECONDS = {
    mode: budget + CLEANUP_RESERVE_SECONDS
    + WRAPPER_SETUP_WORST_CASE_SECONDS + WRAPPER_CLEANUP_RESERVE_SECONDS
    for mode, budget in MODE_RUN_BUDGET_SECONDS.items()
}
if (set(MODE_COMMAND_WORST_CASE_SECONDS) != set(MODE_RUN_BUDGET_SECONDS)
        or any(MODE_RUN_BUDGET_SECONDS[mode] <= worst
               for mode, worst in MODE_COMMAND_WORST_CASE_SECONDS.items())
        or CLEANUP_RESERVE_SECONDS <= CLEANUP_COMMAND_WORST_CASE_SECONDS):
    raise RuntimeError("invalid timeout budgets")

# These are the accepted, installed Item25 unit identities, not template
# identities.  Binding them prevents this smoke from starting an unreviewed
# command while keeping resource IDs and configuration values out of output.
MODES = {
    "api-c": {
        "active": (
            ("noteai-api.service", "46010368ded3db5567bca45afb75f18383ccf23de6aa6d0d99299d87701677e6", "noteai-api-c"),
            ("noteai-admin.service", "1fafeefad045aafdede1a77e1266f4159972dea1862904723823aed397c458f7", "noteai-admin-c"),
        ),
        "http": (
            (8000, "GET", "/health/live", 200), (8000, "GET", "/health/ready", 200),
            (8000, "GET", "/legal/contracts", 200), (8000, "GET", "/billing/tiers", 200),
            (8000, "GET", "/payments/capabilities", 200),
            (8001, "GET", "/health/live", 200), (8001, "GET", "/health/ready", 200),
            (8001, "GET", "/admin/capabilities", 403),
        ),
        "dormant": (
            ("dispatcher", "noteai-ai-dispatcher.service", "8e2d9dc59b87585e5921f5c2b838db4c150efeebeb8e243e194bce586fc102fc", "noteai-ai-dispatcher"),
            ("payment", "noteai-payment.service", "40a49dbee82bbb6f617d2ec439b1ab608b980ceea60125a20dc09a83737547bb", "noteai-payment"),
        ),
    },
    "api-f": {
        "active": (("noteai-api.service", "f591f43b0377402dbc026c4e7f5eee08bc8b884fd9e3523fe775fa5a8f0bb936", "noteai-api-f"),),
        "http": (
            (8000, "GET", "/health/live", 200), (8000, "GET", "/health/ready", 200),
            (8000, "GET", "/legal/contracts", 200), (8000, "GET", "/billing/tiers", 200),
            (8000, "GET", "/payments/capabilities", 200),
        ),
        "dormant": (
            # The accepted B55 xhs-http release image contains both XHS
            # healthcheck and suspended one-shot contracts.
            ("trends", "noteai-xhs-trends.service", "b6199734eb0dc676385050f55f0055a18effb812941af576253ed0b588c56d67", "noteai-xhs-trends"),
            ("tracking", "noteai-xhs-tracking.service", "4968fcb8e33ddd68cbedc16580e7a984377ea218657341cfd6aee3c990f23767", "noteai-xhs-tracking"),
        ),
    },
    "worker-c": {
        "active": (), "http": (),
        "dormant": (("worker", "noteai-ai-worker.service", "a3fa4407202620d5c3e0f6f1fd6de4babe564d3b0cea79c1cbded7a2e13fd200", "noteai-ai-worker"),),
    },
    "worker-f": {
        "active": (), "http": (),
        "dormant": (("worker", "noteai-ai-worker.service", "a3fa4407202620d5c3e0f6f1fd6de4babe564d3b0cea79c1cbded7a2e13fd200", "noteai-ai-worker"),),
    },
}


class SmokeError(RuntimeError):
    def __init__(self, code):
        RuntimeError.__init__(self, code)
        self.code = code


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _nonnegative_int(value):
    return type(value) is int and value >= 0


def _zero_int(value):
    return type(value) is int and value == 0


class Host:
    def __init__(self, mode, clock=None):
        if mode not in MODE_RUN_BUDGET_SECONDS:
            raise SmokeError("mode_budget")
        self._clock = clock or time.monotonic
        started = self._clock()
        self._run_deadline = started + MODE_RUN_BUDGET_SECONDS[mode]
        self._outer_deadline = (
            self._run_deadline + CLEANUP_RESERVE_SECONDS
        )
        self._deadline = self._run_deadline
        self._cleanup_phase = False

    def _bounded_timeout(self, requested):
        remaining = self._deadline - self._clock()
        if remaining <= 0:
            raise SmokeError(
                "cleanup_deadline" if self._cleanup_phase else "run_deadline"
            )
        return min(float(requested), remaining)

    def _timeout_until(self, deadline):
        remaining = min(self._deadline, deadline) - self._clock()
        if remaining <= 0:
            raise SmokeError(
                "cleanup_deadline" if self._cleanup_phase else "run_deadline"
            )
        return remaining

    def begin_cleanup(self):
        now = self._clock()
        self._cleanup_phase = True
        self._deadline = min(
            self._outer_deadline,
            now + CLEANUP_RESERVE_SECONDS,
        )

    def command(self, args, code, allowed=(0,), timeout=30):
        try:
            result = subprocess.run(
                args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=COMMAND_ENV, timeout=self._bounded_timeout(timeout), check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise SmokeError(code)
        if result.returncode not in allowed or len(result.stdout) > 65536:
            raise SmokeError(code)
        return result.returncode, result.stdout

    def _manager_unit_identity(self, unit, path):
        _rc, raw = self.command([
            "/usr/bin/systemctl", "show", unit,
            "--property=FragmentPath", "--property=DropInPaths",
            "--property=NeedDaemonReload", "--no-pager",
        ], "unit_identity")
        values = {}
        try:
            for line in raw.decode("ascii").splitlines():
                key, value = line.split("=", 1)
                values[key] = value
        except (UnicodeError, ValueError):
            raise SmokeError("unit_identity")
        if values != {
                "FragmentPath": path,
                "DropInPaths": "",
                "NeedDaemonReload": "no",
        }:
            raise SmokeError("unit_identity")

    def _docker_socket_identity(self):
        try:
            row = os.lstat(DOCKER_SOCKET_PATH)
        except OSError:
            raise SmokeError("docker_socket")
        if (not stat.S_ISSOCK(row.st_mode) or stat.S_ISLNK(row.st_mode)
                or row.st_uid != 0 or row.st_nlink != 1):
            raise SmokeError("docker_socket")
        return (
            row.st_dev, row.st_ino, row.st_mode, row.st_uid,
            row.st_gid, row.st_nlink,
        )

    def docker_binding(self):
        before = self._docker_socket_identity()
        known = getattr(self, "_docker_socket_fingerprint", None)
        if known is not None and known != before:
            raise SmokeError("docker_socket")
        _rc, raw = self.command([
            "/usr/bin/docker", "--context=default", "context", "inspect",
            "default", "--format", "{{.Endpoints.docker.Host}}",
        ], "docker_context")
        try:
            context_host = raw.decode("ascii").strip()
        except UnicodeError:
            raise SmokeError("docker_context")
        if context_host != DOCKER_HOST_URI:
            raise SmokeError("docker_context")
        _rc, raw = self.command([
            "/usr/bin/docker", "--host=" + DOCKER_HOST_URI, "version",
            "--format", "{{.Server.Version}}",
        ], "docker_socket")
        try:
            version = raw.decode("ascii").strip()
        except UnicodeError:
            raise SmokeError("docker_socket")
        if not version or "\n" in version or "\r" in version:
            raise SmokeError("docker_socket")
        after = self._docker_socket_identity()
        if after != before:
            raise SmokeError("docker_socket")
        self._docker_socket_fingerprint = before
        return before

    def docker_command(self, args, code, allowed=(0,), timeout=30):
        expected = getattr(self, "_docker_socket_fingerprint", None)
        if expected is None or self._docker_socket_identity() != expected:
            raise SmokeError("docker_socket")
        result = self.command(
            ["/usr/bin/docker", "--host=" + DOCKER_HOST_URI] + list(args),
            code, allowed=allowed, timeout=timeout,
        )
        if self._docker_socket_identity() != expected:
            raise SmokeError("docker_socket")
        return result

    def unit_identity(self, unit, expected_sha):
        path = SYSTEMD_ROOT + "/" + unit
        self._manager_unit_identity(unit, path)
        try:
            before = os.lstat(path)
            if (not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode)
                    or before.st_uid != 0 or before.st_gid != 0
                    or stat.S_IMODE(before.st_mode) != 0o644 or before.st_nlink != 1):
                raise SmokeError("unit_identity")
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                opened = os.fstat(fd)
                if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                    raise SmokeError("unit_identity")
                data = b""
                while True:
                    part = os.read(fd, 65536)
                    if not part:
                        break
                    data += part
                    if len(data) > 131072:
                        raise SmokeError("unit_identity")
            finally:
                os.close(fd)
        except SmokeError:
            raise
        except OSError:
            raise SmokeError("unit_identity")
        if hashlib.sha256(data).hexdigest() != expected_sha:
            raise SmokeError("unit_identity")
        self._manager_unit_identity(unit, path)

    def unit_state(self, unit):
        _rc, raw = self.command([
            "/usr/bin/systemctl", "show", unit, "--property=LoadState",
            "--property=ActiveState", "--property=SubState", "--property=Result",
            "--property=NRestarts", "--property=FragmentPath",
            "--property=DropInPaths", "--property=NeedDaemonReload", "--no-pager",
        ], "unit_state")
        values = {}
        try:
            for line in raw.decode("ascii").splitlines():
                key, value = line.split("=", 1)
                values[key] = value
        except (UnicodeError, ValueError):
            raise SmokeError("unit_state")
        if set(values) != {
                "LoadState", "ActiveState", "SubState", "Result", "NRestarts",
                "FragmentPath", "DropInPaths", "NeedDaemonReload",
        }:
            raise SmokeError("unit_state")
        rc, enabled = self.command(
            ["/usr/bin/systemctl", "is-enabled", unit], "unit_state",
            allowed=(0, 1),
        )
        values["enabled"] = enabled.decode("ascii").strip()
        values["enabled_rc"] = rc
        return values

    def container_present(self, name):
        _rc, raw = self.docker_command([
            "container", "ls", "-aq",
            "--filter", "name=^/" + name + "$",
        ], "container_state")
        return len([line for line in raw.decode("ascii").splitlines() if line])

    def wait_container_running(self, name):
        deadline = min(
            self._deadline,
            self._clock() + CONTAINER_READY_TIMEOUT_SECONDS,
        )
        while True:
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise SmokeError("container_ready")
            rc, raw = self.docker_command([
                "container", "inspect", "--format", "{{.State.Running}}", name,
            ], "container_ready", allowed=(0, 1), timeout=min(3, remaining))
            if rc == 0:
                try:
                    running = raw.decode("ascii").strip()
                except UnicodeError:
                    raise SmokeError("container_ready")
                if running == "true":
                    return
                if running != "false":
                    raise SmokeError("container_ready")
            time.sleep(min(CONTAINER_READY_POLL_SECONDS, remaining))

    def runtime_fingerprint(self, name):
        values = []
        for template in (
                "{{.Id}}", "{{.Image}}", "{{.State.StartedAt}}",
                "{{.State.Running}}",
        ):
            _rc, raw = self.docker_command([
                "container", "inspect",
                "--format", template, name,
            ], "container_identity")
            values.append(raw.decode("ascii").strip())
        if not all(values[:3]) or values[3] != "true":
            raise SmokeError("container_identity")
        return hashlib.sha256("\n".join(values).encode("ascii")).hexdigest()

    def public_listener_count(self, name):
        _rc, raw = self.docker_command([
            "port", name,
        ], "container_listener")
        lines = [line.strip() for line in raw.decode("ascii").splitlines() if line.strip()]
        endpoints = []
        for line in lines:
            if " -> " not in line:
                raise SmokeError("container_listener")
            endpoints.append(line.rsplit(" -> ", 1)[1])
        return sum(1 for endpoint in endpoints if not endpoint.startswith("127.0.0.1:"))

    def start(self, unit):
        self.command(["/usr/bin/systemctl", "start", unit], "unit_start", timeout=210)

    def stop(self, unit):
        self.command(["/usr/bin/systemctl", "stop", unit], "unit_stop", timeout=90)

    def exec_json(self, container, args, code):
        _rc, raw = self.docker_command(
            ["exec", container] + list(args),
            code, timeout=45,
        )
        lines = [line for line in raw.decode("utf-8").splitlines() if line.strip()]
        try:
            value = json.loads(lines[-1])
        except (IndexError, UnicodeError, ValueError):
            raise SmokeError(code)
        if not isinstance(value, dict):
            raise SmokeError(code)
        return value

    def http_json(self, port, method, path, expected_status):
        operation_deadline = min(self._deadline, self._clock() + 6)
        connection = http.client.HTTPConnection(
            "127.0.0.1", port, timeout=self._timeout_until(operation_deadline),
        )
        try:
            connection.connect()
            local_socket = connection.sock
            if local_socket is None:
                raise SmokeError("loopback_http")
            local_socket.settimeout(self._timeout_until(operation_deadline))
            connection.request(method, path, body=b"" if method == "POST" else None,
                               headers={"Content-Type": "application/x-www-form-urlencoded"} if method == "POST" else {})
            local_socket.settimeout(self._timeout_until(operation_deadline))
            response = connection.getresponse()
            local_socket.settimeout(self._timeout_until(operation_deadline))
            body = response.read(16385)
        except (OSError, http.client.HTTPException):
            raise SmokeError("loopback_http")
        finally:
            connection.close()
        if response.status != expected_status or len(body) > 16384:
            raise SmokeError("loopback_http")
        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeError, ValueError):
            raise SmokeError("loopback_http")
        if not isinstance(value, dict):
            raise SmokeError("loopback_http")
        return value

    def wait_http_json(self, port, method, path, expected_status):
        deadline = min(
            self._deadline,
            self._clock() + CONTAINER_READY_TIMEOUT_SECONDS,
        )
        while True:
            try:
                return self.http_json(port, method, path, expected_status)
            except SmokeError as exc:
                if exc.code != "loopback_http":
                    raise
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise SmokeError("loopback_http")
            time.sleep(min(CONTAINER_READY_POLL_SECONDS, remaining))


def _require_state(host, unit, expected):
    state = host.unit_state(unit)
    manager = {
        "FragmentPath": SYSTEMD_ROOT + "/" + unit,
        "DropInPaths": "",
        "NeedDaemonReload": "no",
    }
    if expected == "active-enabled":
        wanted = {"LoadState": "loaded", "ActiveState": "active", "SubState": "running", "Result": "success", "NRestarts": "0", "enabled": "enabled", "enabled_rc": 0}
    elif expected == "active-disabled":
        wanted = {"LoadState": "loaded", "ActiveState": "active", "SubState": "running", "Result": "success", "NRestarts": "0", "enabled": "disabled", "enabled_rc": 1}
    else:
        wanted = {"LoadState": "loaded", "ActiveState": "inactive", "SubState": "dead", "Result": "success", "NRestarts": "0", "enabled": "disabled", "enabled_rc": 1}
    wanted.update(manager)
    if state != wanted:
        raise SmokeError(expected + "_unit_state")


def _api_payload(port, path, status, payload):
    if port == 8001 and path == "/admin/capabilities":
        return (status == 403 and payload.get("detail") == "\u9700\u8981\u7ba1\u7406\u5458\u6743\u9650"), {
            "path": path, "status": status, "authorization": "REJECTED",
        }
    if path == "/health/live":
        service = "noteai-admin" if port == 8001 else "noteai-api"
        ok = payload.get("status") == "ok" and payload.get("service") == service
        return ok, {"path": path, "status": status, "service": service, "state": "ok"}
    if path == "/health/ready":
        service = "noteai-admin" if port == 8001 else "noteai-api"
        checks = payload.get("checks")
        ok = (payload.get("status") == "ready" and payload.get("service") == service
              and isinstance(checks, dict) and checks
              and all(isinstance(value, dict) and value.get("ok") is True for value in checks.values()))
        return ok, {"path": path, "status": status, "service": service,
                    "state": "ready", "checks": sorted(checks) if isinstance(checks, dict) else []}
    if path in ("/legal/contracts", "/billing/tiers"):
        return bool(payload), {"path": path, "status": status,
                               "sha256": hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()}
    ok = (path == "/payments/capabilities"
          and payload.get("ordering_available") is False
          and payload.get("currency") == "CNY"
          and payload.get("auto_renewal") is False)
    return ok, {"path": path, "status": status, "ordering_available": False,
                "currency": "CNY", "auto_renewal": False}


def _role_checks(host, role, container):
    health = one_shot = None
    if role in ("dispatcher", "worker"):
        health = host.exec_json(container, ["python", "durable_ai_worker.py", "--healthcheck"], "role_health")
        option = "--dispatcher-once" if role == "dispatcher" else "--worker-once"
        one_shot = host.exec_json(container, ["python", "durable_ai_worker.py", option], "role_one_shot")
        if (health.get("ok") is not True or health.get("suspended") is not True
                or health.get("provider_called") is not False
                or health.get("database_write") is not False
                or one_shot.get("status") != "suspended"
                or one_shot.get("provider_called") is not False
                or one_shot.get("database_write") is not False):
            raise SmokeError("role_contract")
        if role == "dispatcher" and not (
                _nonnegative_int(health.get("pending_outbox"))
                and _zero_int(health.get("exhausted_outbox"))):
            raise SmokeError("role_contract")
        if role == "worker" and not (
                all(_zero_int(health.get(name)) for name in (
                    "needs_manual", "expired_ready", "stale_provider_outcome"
                ))
                and _nonnegative_int(health.get("recoverable_unstarted"))):
            raise SmokeError("role_contract")
    elif role == "trends":
        health = host.exec_json(container, ["python", "market_timing_worker.py", "--healthcheck"], "role_health")
        one_shot = host.exec_json(container, ["python", "market_timing_worker.py", "--once"], "role_one_shot")
        if (health.get("status") != "ready"
                or one_shot.get("skipped") is not True
                or health.get("provider_called") is not False
                or any(not _zero_int(health.get(name)) for name in (
                    "active_provider_attempts", "unknown_provider_attempts",
                    "unlinked_provider_attempts"))
                or one_shot.get("reason") != "collection_suspended"
                or one_shot.get("provider_called") is not False
                or not _zero_int(one_shot.get("database_writes"))
                or one_shot.get("snapshot_written") is not False):
            raise SmokeError("role_contract")
    elif role == "tracking":
        health = host.exec_json(container, ["python", "crawler_worker.py", "--healthcheck"], "role_health")
        one_shot = host.exec_json(container, ["python", "crawler_worker.py", "--once", "--force", "--limit", "1"], "role_one_shot")
        if (health.get("status") != "ready" or health.get("provider_called") is not False
                or any(not _zero_int(health.get(name)) for name in (
                    "active_provider_attempts", "stale_provider_attempts",
                    "unlinked_started_attempts"))
                or one_shot.get("skipped") is not True
                or one_shot.get("reason") != "collection_suspended"
                or not _zero_int(one_shot.get("collected"))):
            raise SmokeError("role_contract")
    elif role == "payment":
        live = host.wait_http_json(8002, "GET", "/health/live", 200)
        ready = host.http_json(8002, "GET", "/health/ready", 503)
        callback = host.http_json(8002, "POST", "/payments/adapay/callback", 503)
        checks = ready.get("checks")
        if (live != {"status": "ok", "service": "noteai-payment"}
                or ready.get("status") != "not_ready"
                or ready.get("service") != "noteai-payment"
                or not isinstance(checks, dict)
                or checks.get("runtime_role", {}).get("ok") is not True
                or checks.get("database", {}).get("ok") is not True
                or checks.get("database_role", {}).get("ok") is not True
                or checks.get("callback_enabled", {}).get("ok") is not False
                or callback.get("detail") != "PAYMENT_CALLBACK_UNAVAILABLE"):
            raise SmokeError("role_contract")
    else:
        raise SmokeError("role_contract")
    evidence = {"role": role, "health_passed": True,
                "suspended_one_shot_passed": role != "payment",
                "expected_negative_passed": role == "payment"}
    if role == "dispatcher":
        evidence.update({"pending_outbox": health["pending_outbox"],
                         "exhausted_outbox": health["exhausted_outbox"]})
    elif role == "worker":
        evidence.update({"needs_manual": 0, "expired_ready": 0,
                         "stale_provider_outcome": 0,
                         "recoverable_unstarted": health["recoverable_unstarted"]})
    elif role == "trends":
        evidence["provider_attempt_counts"] = {"active": 0, "unknown": 0, "unlinked": 0}
    elif role == "tracking":
        evidence["provider_attempt_counts"] = {"active": 0, "stale": 0, "unlinked": 0}
    return evidence


class SmokeRun:
    def __init__(self, mode, host):
        self.mode = mode
        self.host = host
        self.started = []
        self.mutation_attempted = False
        self.start_count = 0
        self.stop_count = 0

    def cleanup(self):
        self.host.begin_cleanup()
        ok = True
        for unit, container in reversed(self.started):
            try:
                self.host.stop(unit)
                self.stop_count += 1
                _require_state(self.host, unit, "inactive")
                if self.host.container_present(container) != 0:
                    raise SmokeError("cleanup_container")
            except Exception:
                ok = False
        if ok:
            self.started = []
        return ok

    def run(self):
        spec = MODES[self.mode]
        docker_identity = self.host.docker_binding()
        fingerprints = {}
        for unit, digest, container in spec["active"]:
            self.host.unit_identity(unit, digest)
            _require_state(self.host, unit, "active-enabled")
            if self.host.container_present(container) != 1:
                raise SmokeError("active_container_state")
            if self.host.public_listener_count(container) != 0:
                raise SmokeError("public_listener")
            fingerprints[container] = self.host.runtime_fingerprint(container)
        for _role, unit, digest, container in spec["dormant"]:
            self.host.unit_identity(unit, digest)
            _require_state(self.host, unit, "inactive")
            if self.host.container_present(container) != 0:
                raise SmokeError("dormant_container_state")
        endpoint_count = 0
        projections = []
        for port, method, path, status in spec["http"]:
            payload = self.host.http_json(port, method, path, status)
            ok, projection = _api_payload(port, path, status, payload)
            if not ok:
                raise SmokeError("loopback_contract")
            projections.append(projection)
            endpoint_count += 1
        roles = []
        for role, unit, _digest, container in spec["dormant"]:
            self.mutation_attempted = True
            self.started.append((unit, container))
            self.host.start(unit)
            self.start_count += 1
            self.host.wait_container_running(container)
            _require_state(self.host, unit, "active-disabled")
            if self.host.container_present(container) != 1:
                raise SmokeError("dormant_start_state")
            if self.host.public_listener_count(container) != 0:
                raise SmokeError("public_listener")
            roles.append(_role_checks(self.host, role, container))
            self.host.stop(unit)
            self.stop_count += 1
            _require_state(self.host, unit, "inactive")
            if self.host.container_present(container) != 0:
                raise SmokeError("dormant_restore_state")
            self.started.pop()
        for unit, digest, container in spec["active"]:
            self.host.unit_identity(unit, digest)
            _require_state(self.host, unit, "active-enabled")
            if (self.host.container_present(container) != 1
                    or self.host.public_listener_count(container) != 0
                    or self.host.runtime_fingerprint(container) != fingerprints[container]):
                raise SmokeError("active_runtime_drift")
        if self.host.docker_binding() != docker_identity:
            raise SmokeError("docker_socket")
        return {
            "schema": SCHEMA, "task_id": TASK_ID, "status": "PASS", "mode": self.mode,
            "loopback_endpoint_count": endpoint_count, "endpoint_projections": projections,
            "roles": roles, "active_runtime_identity_unchanged": True,
            "public_listener_count": 0,
            "service_start_count": self.start_count, "service_stop_count": self.stop_count,
            "original_state_restored": True, "provider_call_count": 0,
            "provider_attempt_count": 0, "oss_mutation_count": 0,
            "production_database_mutation_count": 0, "synthetic_record_count": 0,
            "public_request_count": 0, "cleanup": "RESTORED",
            "automatic_retry_allowed": False, "same_invocation_replay_allowed": False,
        }


def execute(mode, host=None):
    run = SmokeRun(mode, host or Host(mode))
    try:
        return 0, run.run()
    except Exception as exc:
        code = exc.code if isinstance(exc, SmokeError) else "unexpected"
        cleanup_ok = run.cleanup()
        unknown = run.mutation_attempted or not cleanup_ok
        cleanup = ("UNKNOWN" if not cleanup_ok else
                   "RESTORED" if run.mutation_attempted else "NOT_NEEDED")
        return (4 if unknown else 3), {
            "schema": SCHEMA, "task_id": TASK_ID,
            "status": "UNKNOWN" if unknown else "FAIL", "mode": mode,
            "code": code, "runtime_mutation_attempted": run.mutation_attempted,
            "cleanup": cleanup,
            "service_start_count": run.start_count, "service_stop_count": run.stop_count,
            "automatic_retry_allowed": False, "same_invocation_replay_allowed": False,
        }


def _signal(_number, _frame):
    raise SmokeError("signal")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=sorted(MODES), required=True)
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        print(canonical({"schema": SCHEMA, "task_id": TASK_ID, "status": "FAIL", "code": "euid", "automatic_retry_allowed": False, "same_invocation_replay_allowed": False}), file=sys.stderr)
        return 3
    os.umask(0o077)
    for name in tuple(os.environ):
        if name.endswith("_PROXY") or name.startswith("ALIBABA_CLOUD_") or name in {"DOCKER_HOST", "DOCKER_CONFIG", "DOCKER_CERT_PATH", "DOCKER_TLS_VERIFY"}:
            os.environ.pop(name, None)
    for path in ("/usr/bin/docker", "/usr/bin/systemctl"):
        if not os.path.isfile(path) or not os.access(path, os.X_OK):
            print(canonical({"schema": SCHEMA, "task_id": TASK_ID, "status": "FAIL", "code": "required_tool", "automatic_retry_allowed": False, "same_invocation_replay_allowed": False}), file=sys.stderr)
            return 3
    for number in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(number, _signal)
    returncode, payload = execute(args.mode)
    print(canonical(payload), file=sys.stdout if returncode == 0 else sys.stderr)
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
