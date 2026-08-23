#!/usr/bin/env python3
"""Run the one-host Item 28 managed failure and rollback rehearsal.

The production mode is intentionally limited to API-F.  It installs one
volatile systemd drop-in which makes the next restart fail before ExecStart,
then delegates restoration to a separately managed, host-local guardian.  No
cloud/provider, object-storage, IAM, public HTTP, or database command exists in
this program.
"""

import argparse
import ctypes
import errno
import hashlib
import http.client
import json
import os
import signal
import stat
import subprocess
import sys
import time


TASK_ID = "PROD-FIRST-LAUNCH-INTERNAL-ROLLBACK-001"
SCHEMA = "noteai.item28.internal-failure-rollback.v1"
MODE = "api-f"
UNIT = "noteai-api.service"
UNIT_PATH = "/etc/systemd/system/noteai-api.service"
UNIT_SHA256 = "f591f43b0377402dbc026c4e7f5eee08bc8b884fd9e3523fe775fa5a8f0bb936"
CONTAINER = "noteai-api-f"
DOCKER_SOCKET = "/var/run/docker.sock"
DOCKER_HOST = "unix:///var/run/docker.sock"
TASK_ROOT = "/run/noteai-item28-internal-rollback-v1"
GUARDIAN_SOURCE = TASK_ROOT + "/guardian.py"
GUARDIAN_UNIT = "noteai-item28-internal-rollback-guardian-v1.service"
VOLATILE_DIR = "/run/systemd/system/noteai-api.service.d"
DROPIN_PATH = VOLATILE_DIR + "/90-noteai-item28-preconnect-failure.conf"
STAGED_VOLATILE_DIR = TASK_ROOT + "/volatile-dropin-stage"
STAGED_DROPIN_PATH = (
    STAGED_VOLATILE_DIR + "/90-noteai-item28-preconnect-failure.conf"
)
DROPIN_BYTES = (
    b"[Service]\n"
    b"# Item28: fail the one managed restart before ExecStart.\n"
    b"ExecStartPre=/usr/bin/false\n"
)
DROPIN_SHA256 = hashlib.sha256(DROPIN_BYTES).hexdigest()
ARMED_PATH = TASK_ROOT + "/armed"
ABORT_PATH = TASK_ROOT + "/abort"
ROLLBACK_REQUEST_PATH = TASK_ROOT + "/rollback-request"
BASELINE_PATH = TASK_ROOT + "/baseline.json"
GUARDIAN_RESULT_PATH = TASK_ROOT + "/guardian-result.json"
GUARDIAN_RESULT_TEMP = TASK_ROOT + "/guardian-result.tmp"
PATH_VALUE = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
COMMAND_ENV = {"PATH": PATH_VALUE, "LC_ALL": "C", "LANG": "C"}
RUN_BUDGET_SECONDS = 600
PROVIDER_TIMEOUT_SECONDS = 960
GUARDIAN_BUDGET_SECONDS = PROVIDER_TIMEOUT_SECONDS + 120
MAX_OUTPUT_BYTES = 65536


class RollbackError(RuntimeError):
    def __init__(self, code):
        RuntimeError.__init__(self, code)
        self.code = code


def canonical(value):
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    )


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _strict_int(value, minimum=0):
    return type(value) is int and value >= minimum


class Host:
    def __init__(self, clock=None):
        self._clock = clock or time.monotonic
        self._deadline = self._clock() + RUN_BUDGET_SECONDS
        self._docker_fingerprint = None
        self._task_root_created = False
        self._guardian_start_attempted = False
        self._guardian_started = False
        self._guardian_start_uncertain = False

    def remaining(self, maximum):
        value = min(float(maximum), self._deadline - self._clock())
        if value <= 0:
            raise RollbackError("deadline")
        return value

    def command(self, args, code, allowed=(0,), timeout=30, input_bytes=None):
        try:
            result = subprocess.run(
                list(args), input=input_bytes, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=COMMAND_ENV,
                timeout=self.remaining(timeout), check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise RollbackError(code)
        if (
            result.returncode not in allowed
            or len(result.stdout) > MAX_OUTPUT_BYTES
            or len(result.stderr) > MAX_OUTPUT_BYTES
        ):
            raise RollbackError(code)
        return result.returncode, result.stdout

    def _regular_file(self, path, expected_mode, expected_sha=None):
        try:
            before = os.lstat(path)
            if (
                not stat.S_ISREG(before.st_mode)
                or stat.S_ISLNK(before.st_mode)
                or before.st_uid != 0
                or before.st_gid != 0
                or stat.S_IMODE(before.st_mode) != expected_mode
                or before.st_nlink != 1
            ):
                raise RollbackError("file_identity")
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                opened = os.fstat(fd)
                if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                    raise RollbackError("file_identity")
                raw = b""
                while True:
                    chunk = os.read(fd, 65536)
                    if not chunk:
                        break
                    raw += chunk
                    if len(raw) > 256 * 1024:
                        raise RollbackError("file_identity")
            finally:
                os.close(fd)
            after = os.lstat(path)
        except RollbackError:
            raise
        except OSError:
            raise RollbackError("file_identity")
        identity = (
            before.st_dev, before.st_ino, before.st_mode, before.st_uid,
            before.st_gid, before.st_nlink, before.st_size, before.st_mtime_ns,
        )
        if identity != (
            after.st_dev, after.st_ino, after.st_mode, after.st_uid,
            after.st_gid, after.st_nlink, after.st_size, after.st_mtime_ns,
        ):
            raise RollbackError("file_identity")
        digest = sha256(raw)
        if expected_sha is not None and digest != expected_sha:
            raise RollbackError("file_identity")
        return identity, digest, raw

    def unit_manager(self, expected_dropins):
        _rc, raw = self.command([
            "/usr/bin/systemctl", "show", UNIT,
            "--property=FragmentPath", "--property=DropInPaths",
            "--property=NeedDaemonReload", "--no-pager",
        ], "unit_manager")
        values = {}
        try:
            for line in raw.decode("ascii").splitlines():
                key, value = line.split("=", 1)
                values[key] = value
        except (UnicodeError, ValueError):
            raise RollbackError("unit_manager")
        if values != {
            "FragmentPath": UNIT_PATH,
            "DropInPaths": expected_dropins,
            "NeedDaemonReload": "no",
        }:
            raise RollbackError("unit_manager")
        return values

    def unit_state(self, expected_active, *, require_result=None):
        _rc, raw = self.command([
            "/usr/bin/systemctl", "show", UNIT,
            "--property=LoadState", "--property=ActiveState",
            "--property=SubState", "--property=Result",
            "--property=NRestarts", "--no-pager",
        ], "unit_state")
        values = {}
        try:
            for line in raw.decode("ascii").splitlines():
                key, value = line.split("=", 1)
                values[key] = value
            restarts = int(values["NRestarts"], 10)
        except (KeyError, UnicodeError, ValueError):
            raise RollbackError("unit_state")
        if set(values) != {
            "LoadState", "ActiveState", "SubState", "Result", "NRestarts",
        } or values["LoadState"] != "loaded" or restarts < 0:
            raise RollbackError("unit_state")
        if expected_active:
            if values["ActiveState"] != "active" or values["SubState"] != "running":
                raise RollbackError("unit_state")
        elif values["ActiveState"] not in {"failed", "inactive"}:
            raise RollbackError("unit_state")
        if require_result is not None and values["Result"] != require_result:
            raise RollbackError("unit_state")
        rc, raw = self.command(
            ["/usr/bin/systemctl", "is-enabled", UNIT], "unit_enabled",
            allowed=(0, 1),
        )
        if rc != 0 or raw.decode("ascii").strip() != "enabled":
            raise RollbackError("unit_enabled")
        return restarts

    def docker_binding(self):
        try:
            row = os.lstat(DOCKER_SOCKET)
        except OSError:
            raise RollbackError("docker_socket")
        fingerprint = (
            row.st_dev, row.st_ino, row.st_mode, row.st_uid,
            row.st_gid, row.st_nlink,
        )
        if (
            not stat.S_ISSOCK(row.st_mode)
            or stat.S_ISLNK(row.st_mode)
            or row.st_uid != 0
            or row.st_nlink != 1
            or (self._docker_fingerprint is not None
                and fingerprint != self._docker_fingerprint)
        ):
            raise RollbackError("docker_socket")
        _rc, raw = self.command([
            "/usr/bin/docker", "--context=default", "context", "inspect",
            "default", "--format", "{{.Endpoints.docker.Host}}",
        ], "docker_context")
        if raw.decode("ascii").strip() != DOCKER_HOST:
            raise RollbackError("docker_context")
        self._docker_fingerprint = fingerprint
        return fingerprint

    def docker(self, args, code, allowed=(0,), timeout=30):
        before = self.docker_binding()
        result = self.command(
            ["/usr/bin/docker", "--host=" + DOCKER_HOST] + list(args),
            code, allowed=allowed, timeout=timeout,
        )
        if self.docker_binding() != before:
            raise RollbackError("docker_socket")
        return result

    def container_count(self):
        _rc, raw = self.docker([
            "container", "ls", "-aq", "--filter", "name=^/" + CONTAINER + "$",
        ], "container_state")
        return len([line for line in raw.decode("ascii").splitlines() if line])

    def release_identity(self):
        if self.container_count() != 1:
            raise RollbackError("container_state")
        values = []
        for template in (
            "{{.Image}}", "{{.Config.Image}}", "{{.Config.User}}",
            "{{.HostConfig.ReadonlyRootfs}}", "{{.State.Running}}",
        ):
            _rc, raw = self.docker([
                "container", "inspect", "--format", template, CONTAINER,
            ], "container_identity")
            values.append(raw.decode("ascii").strip())
        if not values[0] or not values[1] or values[2:] != ["999:999", "true", "true"]:
            raise RollbackError("container_identity")
        return sha256(("\n".join(values[:2]) + "\n").encode("ascii"))

    def public_listener_count(self):
        _rc, raw = self.docker(["port", CONTAINER], "container_listener")
        count = 0
        for line in raw.decode("ascii").splitlines():
            if not line.strip():
                continue
            if " -> " not in line:
                raise RollbackError("container_listener")
            endpoint = line.rsplit(" -> ", 1)[1]
            if not endpoint.startswith("127.0.0.1:"):
                count += 1
        return count

    def health(self):
        projections = []
        for path, expected_state in (("/health/live", "ok"), ("/health/ready", "ready")):
            deadline = self._clock() + 120
            last = None
            while self._clock() < deadline:
                conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=2)
                try:
                    conn.request("GET", path)
                    response = conn.getresponse()
                    raw = response.read(16385)
                    last = (response.status, raw)
                except (OSError, http.client.HTTPException):
                    time.sleep(0.2)
                    continue
                finally:
                    conn.close()
                if response.status == 200:
                    break
                time.sleep(0.2)
            if last is None or last[0] != 200 or len(last[1]) > 16384:
                raise RollbackError("loopback_health")
            try:
                value = json.loads(last[1].decode("utf-8"))
            except (UnicodeError, ValueError):
                raise RollbackError("loopback_health")
            if (
                type(value) is not dict
                or value.get("status") != expected_state
                or value.get("service") != "noteai-api"
            ):
                raise RollbackError("loopback_health")
            if path.endswith("ready"):
                checks = value.get("checks")
                if (
                    type(checks) is not dict or not checks
                    or any(type(row) is not dict or row.get("ok") is not True
                           for row in checks.values())
                ):
                    raise RollbackError("loopback_health")
            projections.append({"path": path, "status": 200, "state": expected_state})
        return projections

    def baseline(self):
        self.unit_manager("")
        self._regular_file(UNIT_PATH, 0o644, UNIT_SHA256)
        restarts = self.unit_state(True, require_result="success")
        identity = self.release_identity()
        if self.public_listener_count() != 0:
            raise RollbackError("public_listener")
        health = self.health()
        return {"nrestarts": restarts, "release_identity_sha256": identity, "health": health}

    def _make_root(self):
        if os.path.lexists(TASK_ROOT):
            raise RollbackError("task_root_exists")
        try:
            os.mkdir(TASK_ROOT, 0o700)
        except OSError:
            raise RollbackError("task_root_create")
        self._task_root_created = True
        row = os.lstat(TASK_ROOT)
        if (
            not stat.S_ISDIR(row.st_mode) or stat.S_ISLNK(row.st_mode)
            or row.st_uid != 0 or row.st_gid != 0
            or stat.S_IMODE(row.st_mode) != 0o700
        ):
            raise RollbackError("task_root_create")

    def _write_exclusive(self, path, raw, mode):
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
            try:
                os.fchmod(fd, mode)
                written = 0
                while written < len(raw):
                    count = os.write(fd, raw[written:])
                    if count <= 0:
                        raise OSError("short write")
                    written += count
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            raise RollbackError("exclusive_write")

    def dropin_directory_state(self, directory, dropin_path):
        if not os.path.lexists(directory):
            return "ABSENT" if not os.path.lexists(dropin_path) else "PARTIAL"
        try:
            before = os.lstat(directory)
            if (
                not stat.S_ISDIR(before.st_mode)
                or stat.S_ISLNK(before.st_mode)
                or before.st_uid != 0 or before.st_gid != 0
                or stat.S_IMODE(before.st_mode) != 0o755
                or before.st_nlink != 2
            ):
                return "PARTIAL"
            names = os.listdir(directory)
            after = os.lstat(directory)
        except OSError:
            return "PARTIAL"
        identity = (
            before.st_dev, before.st_ino, before.st_mode, before.st_uid,
            before.st_gid, before.st_nlink, before.st_size, before.st_mtime_ns,
        )
        if identity != (
            after.st_dev, after.st_ino, after.st_mode, after.st_uid,
            after.st_gid, after.st_nlink, after.st_size, after.st_mtime_ns,
        ):
            return "PARTIAL"
        if names == []:
            return "EMPTY"
        if names != [os.path.basename(dropin_path)]:
            return "PARTIAL"
        try:
            self._regular_file(dropin_path, 0o644, DROPIN_SHA256)
            final = os.lstat(directory)
            final_names = os.listdir(directory)
        except RollbackError:
            return "PARTIAL"
        except OSError:
            return "PARTIAL"
        if identity != (
            final.st_dev, final.st_ino, final.st_mode, final.st_uid,
            final.st_gid, final.st_nlink, final.st_size, final.st_mtime_ns,
        ) or final_names != names:
            return "PARTIAL"
        return "COMPLETE"

    def _rename_noreplace(self, source, target):
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            renameat2 = libc.renameat2
            renameat2.argtypes = [
                ctypes.c_int, ctypes.c_char_p,
                ctypes.c_int, ctypes.c_char_p, ctypes.c_uint,
            ]
            renameat2.restype = ctypes.c_int
            result = renameat2(
                -100, os.fsencode(source), -100, os.fsencode(target), 1
            )
        except (AttributeError, OSError, TypeError, ValueError):
            raise RollbackError("dropin_publish_unsupported")
        if result != 0:
            code = ctypes.get_errno()
            raise RollbackError(
                "volatile_collision" if code == errno.EEXIST
                else "dropin_publish"
            )

    def prepare_guardian(self, baseline):
        self._make_root()
        try:
            source_path = os.path.realpath(__file__)
            before = os.lstat(source_path)
            if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
                raise OSError("source identity")
            fd = os.open(source_path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                opened = os.fstat(fd)
                if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                    raise OSError("source identity")
                source = b""
                while True:
                    chunk = os.read(fd, 65536)
                    if not chunk:
                        break
                    source += chunk
                    if len(source) > 256 * 1024:
                        raise OSError("source size")
            finally:
                os.close(fd)
            after = os.lstat(source_path)
            if (
                before.st_dev, before.st_ino, before.st_mode, before.st_size,
                before.st_mtime_ns,
            ) != (
                after.st_dev, after.st_ino, after.st_mode, after.st_size,
                after.st_mtime_ns,
            ):
                raise OSError("source changed")
        except OSError:
            raise RollbackError("guardian_source")
        baseline_record = {
            "schema": "noteai.item28.guardian-baseline.v1",
            "unit_fragment_sha256": UNIT_SHA256,
            "release_identity_sha256": baseline["release_identity_sha256"],
            "volatile_dropin_sha256": DROPIN_SHA256,
        }
        self._write_exclusive(
            BASELINE_PATH,
            canonical(baseline_record).encode("ascii") + b"\n",
            0o600,
        )
        self._write_exclusive(GUARDIAN_SOURCE, source, 0o700)
        self._regular_file(GUARDIAN_SOURCE, 0o700, sha256(source))
        parent_starttime = _process_starttime(os.getpid())
        if parent_starttime is None:
            raise RollbackError("guardian_parent_identity")
        self._guardian_start_attempted = True
        try:
            self.command([
                "/usr/bin/systemd-run", "--unit=" + GUARDIAN_UNIT, "--collect",
                "--property=Type=exec", "--property=User=root",
                "--property=Group=root", "--property=UMask=0077",
                "--property=NoNewPrivileges=yes", "--property=PrivateTmp=yes",
                "--property=ProtectHome=yes", "--property=ProtectSystem=no",
                GUARDIAN_SOURCE, "--guardian", "--parent-pid", str(os.getpid()),
                "--parent-starttime", parent_starttime,
            ], "guardian_start", timeout=30)
        except Exception:
            self._guardian_start_uncertain = True
            raise
        self._guardian_started = True

    def wait_guardian_active(self):
        deadline = self._clock() + 20
        while self._clock() < deadline:
            rc, raw = self.command([
                "/usr/bin/systemctl", "is-active", GUARDIAN_UNIT,
            ], "guardian_state", allowed=(0, 3), timeout=5)
            if rc == 0 and raw.decode("ascii").strip() == "active":
                return
            time.sleep(0.2)
        raise RollbackError("guardian_state")

    def arm(self):
        self._write_exclusive(ARMED_PATH, b"ARMED\n", 0o600)

    def install_dropin(self):
        if (
            os.path.lexists(STAGED_VOLATILE_DIR)
            or os.path.lexists(STAGED_DROPIN_PATH)
            or os.path.lexists(VOLATILE_DIR)
            or os.path.lexists(DROPIN_PATH)
        ):
            raise RollbackError("volatile_residue")
        try:
            os.mkdir(STAGED_VOLATILE_DIR, 0o755)
            os.chmod(STAGED_VOLATILE_DIR, 0o755, follow_symlinks=False)
        except OSError:
            raise RollbackError("dropin_dir")
        if self.dropin_directory_state(
            STAGED_VOLATILE_DIR, STAGED_DROPIN_PATH
        ) != "EMPTY":
            raise RollbackError("dropin_dir")
        self._write_exclusive(STAGED_DROPIN_PATH, DROPIN_BYTES, 0o644)
        if self.dropin_directory_state(
            STAGED_VOLATILE_DIR, STAGED_DROPIN_PATH
        ) != "COMPLETE":
            raise RollbackError("dropin_stage")
        self._rename_noreplace(STAGED_VOLATILE_DIR, VOLATILE_DIR)
        if (
            self.dropin_directory_state(
                STAGED_VOLATILE_DIR, STAGED_DROPIN_PATH
            ) != "ABSENT"
            or self.dropin_directory_state(VOLATILE_DIR, DROPIN_PATH)
            != "COMPLETE"
        ):
            raise RollbackError("dropin_publish")

    def daemon_reload(self):
        self.command(["/usr/bin/systemctl", "daemon-reload"], "daemon_reload", timeout=30)

    def restore_runtime_if_needed(self):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            rc, raw = self.command(
                ["/usr/bin/systemctl", "is-active", UNIT],
                "rollback_runtime_state", allowed=(0, 3), timeout=15,
            )
            try:
                state = raw.decode("ascii").strip()
            except UnicodeError:
                raise RollbackError("rollback_runtime_state")
            if rc == 0 and state == "active":
                return 0
            if rc == 3 and state in {"failed", "inactive"}:
                break
            if state not in {"activating", "deactivating", "reloading"}:
                raise RollbackError("rollback_runtime_state")
            time.sleep(0.2)
        else:
            raise RollbackError("rollback_runtime_state")
        self.command(
            ["/usr/bin/systemctl", "reset-failed", UNIT], "reset_failed"
        )
        self.command(
            ["/usr/bin/systemctl", "start", UNIT],
            "rollback_start", timeout=180,
        )
        return 1

    def restart_expected_failure(self):
        rc, _raw = self.command(
            ["/usr/bin/systemctl", "restart", UNIT], "restart",
            allowed=tuple(range(0, 256)), timeout=180,
        )
        return rc

    def verify_preconnect_failure(self):
        self.unit_manager(DROPIN_PATH)
        self._regular_file(DROPIN_PATH, 0o644, DROPIN_SHA256)
        self.unit_state(False, require_result="exit-code")
        if self.container_count() != 0:
            raise RollbackError("failure_started_container")

    def request_rollback(self):
        self._write_exclusive(ROLLBACK_REQUEST_PATH, b"ROLLBACK\n", 0o600)

    def request_abort(self):
        self._write_exclusive(ABORT_PATH, b"ABORT\n", 0o600)

    def wait_guardian_result(self):
        deadline = self._clock() + GUARDIAN_BUDGET_SECONDS
        while self._clock() < deadline:
            if os.path.isfile(GUARDIAN_RESULT_PATH):
                try:
                    _identity, _digest, raw = self._regular_file(
                        GUARDIAN_RESULT_PATH, 0o600
                    )
                    value = json.loads(raw.decode("ascii"))
                except (RollbackError, OSError, UnicodeError, ValueError):
                    raise RollbackError("guardian_result")
                if canonical(value).encode("ascii") + b"\n" != raw:
                    raise RollbackError("guardian_result")
                return value
            time.sleep(0.25)
        raise RollbackError("guardian_timeout")

    def wait_guardian_collected(self):
        deadline = self._clock() + 30
        while self._clock() < deadline:
            rc, raw = self.command([
                "/usr/bin/systemctl", "show", GUARDIAN_UNIT,
                "--property=LoadState", "--value", "--no-pager",
            ], "guardian_collect", allowed=(0, 1, 3, 4), timeout=5)
            if rc != 0 or raw.decode("ascii").strip() == "not-found":
                return
            time.sleep(0.2)
        raise RollbackError("guardian_collect")

    def cancel_guardian_setup(self):
        if not self._task_root_created:
            raise RollbackError("guardian_setup_ownership")
        if self._guardian_start_uncertain:
            raise RollbackError("guardian_start_uncertain")
        if self._guardian_started:
            self.command(
                ["/usr/bin/systemctl", "stop", GUARDIAN_UNIT],
                "guardian_setup_stop", allowed=(0, 1, 3, 4, 5), timeout=30,
            )
            self.command(
                ["/usr/bin/systemctl", "reset-failed", GUARDIAN_UNIT],
                "guardian_setup_reset", allowed=(0, 1, 3, 4, 5), timeout=15,
            )
        for path in (
            GUARDIAN_RESULT_PATH, GUARDIAN_RESULT_TEMP,
            ROLLBACK_REQUEST_PATH, ABORT_PATH, ARMED_PATH, BASELINE_PATH,
            GUARDIAN_SOURCE,
        ):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            except OSError:
                raise RollbackError("guardian_setup_cleanup")
        try:
            os.rmdir(TASK_ROOT)
        except FileNotFoundError:
            pass
        except OSError:
            raise RollbackError("guardian_setup_cleanup")
        if os.path.lexists(TASK_ROOT):
            raise RollbackError("guardian_setup_cleanup")

    def final_verify(self, expected_identity):
        self.unit_manager("")
        self._regular_file(UNIT_PATH, 0o644, UNIT_SHA256)
        restarts = self.unit_state(True, require_result="success")
        identity = self.release_identity()
        if identity != expected_identity or self.public_listener_count() != 0:
            raise RollbackError("release_restore")
        health = self.health()
        if os.path.lexists(DROPIN_PATH) or os.path.lexists(VOLATILE_DIR):
            raise RollbackError("volatile_residue")
        return {"nrestarts": restarts, "release_identity_sha256": identity, "health": health}

    def cleanup_task_root(self):
        for path in (
            GUARDIAN_RESULT_PATH, GUARDIAN_RESULT_TEMP,
            ROLLBACK_REQUEST_PATH, ABORT_PATH, ARMED_PATH, BASELINE_PATH,
            GUARDIAN_SOURCE,
        ):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            except OSError:
                raise RollbackError("task_cleanup")
        try:
            os.rmdir(TASK_ROOT)
        except OSError:
            raise RollbackError("task_cleanup")
        if os.path.lexists(TASK_ROOT):
            raise RollbackError("task_cleanup")


class LocalGuardian:
    """Synchronous test guardian; production uses the managed guardian mode."""

    def __init__(self, host):
        self.host = host
        self.setup_uncertain = False

    def prepare(self, baseline):
        try:
            self.host.prepare_guardian(baseline)
            self.host.wait_guardian_active()
        except Exception:
            try:
                self.host.cancel_guardian_setup()
            except Exception:
                self.setup_uncertain = True
            raise

    def rollback(self):
        self.host.request_rollback()
        value = self.host.wait_guardian_result()
        self.host.wait_guardian_collected()
        return value

    def cancel(self):
        self.host.request_abort()
        value = self.host.wait_guardian_result()
        self.host.wait_guardian_collected()
        return value


def result_payload(baseline, final, guardian_result, restart_rc):
    return {
        "schema": SCHEMA,
        "task_id": TASK_ID,
        "status": "PASS",
        "mode": MODE,
        "failure_phase": "PRE_CONNECT",
        "failure_mechanism": "VOLATILE_SYSTEMD_EXECSTARTPRE_FALSE",
        "unit_fragment_sha256": UNIT_SHA256,
        "volatile_dropin_sha256": DROPIN_SHA256,
        "pre_health": baseline["health"],
        "post_health": final["health"],
        "release_identity_sha256": baseline["release_identity_sha256"],
        "release_identity_unchanged": (
            baseline["release_identity_sha256"] == final["release_identity_sha256"]
        ),
        "restart_attempt_count": 1,
        "restart_return_code_nonzero": restart_rc != 0,
        "restart_success_count": 0,
        "restart_failed_pre_connect_count": 1,
        "guardian_rollback_count": 1,
        "guardian_rollback_status": guardian_result["status"],
        "restored_runtime_start_count": 1,
        "original_release_restored": True,
        "volatile_residue_count": 0,
        "daemon_reload_count": 2,
        "provider_call_count": 0,
        "provider_attempt_count": 0,
        "oss_mutation_count": 0,
        "iam_mutation_count": 0,
        "host_executor_database_command_count": 0,
        "production_database_mutation_count": 0,
        "cloud_resource_create_count": 0,
        "public_request_count": 0,
        "automatic_retry_allowed": False,
        "same_invocation_replay_allowed": False,
    }


def execute(host=None, guardian=None):
    host = host or Host()
    guardian = guardian or LocalGuardian(host)
    mutation_attempted = False
    rollback_requested = False
    guardian_prepared = False
    baseline = None
    restart_rc = None
    try:
        baseline = host.baseline()
        guardian.prepare(baseline)
        guardian_prepared = True
        host.arm()
        mutation_attempted = True
        host.install_dropin()
        host.daemon_reload()
        restart_rc = host.restart_expected_failure()
        if restart_rc == 0:
            raise RollbackError("restart_unexpected_success")
        host.verify_preconnect_failure()
        rollback_requested = True
        guardian_result = guardian.rollback()
        if guardian_result != {
            "schema": "noteai.item28.guardian-result.v1",
            "status": "RESTORED",
            "dropin_removed": True,
            "staged_cleanup_status": "ABSENT",
            "staged_residue_count": 0,
            "daemon_reload_count": 1,
            "runtime_start_count": 1,
            "volatile_residue_count": 0,
        }:
            raise RollbackError("guardian_result")
        final = host.final_verify(baseline["release_identity_sha256"])
        payload = result_payload(baseline, final, guardian_result, restart_rc)
        host.cleanup_task_root()
        return 0, payload
    except Exception as exc:
        code = exc.code if isinstance(exc, RollbackError) else "unexpected"
        if mutation_attempted and not rollback_requested:
            rollback_requested = True
            try:
                guardian_result = guardian.rollback()
            except Exception:
                guardian_result = None
        cancelled = False
        if guardian_prepared and not mutation_attempted:
            try:
                cancelled_result = guardian.cancel()
                cancelled = cancelled_result == {
                    "schema": "noteai.item28.guardian-result.v1",
                    "status": "ABORTED_NO_MUTATION",
                    "dropin_removed": False,
                    "staged_cleanup_status": "ABSENT",
                    "staged_residue_count": 0,
                    "daemon_reload_count": 0,
                    "runtime_start_count": 0,
                    "volatile_residue_count": 0,
                }
                if cancelled:
                    host.cleanup_task_root()
            except Exception:
                cancelled = False
        unknown = (
            mutation_attempted
            or (guardian_prepared and not cancelled)
            or bool(getattr(guardian, "setup_uncertain", False))
        )
        return (4 if unknown else 3), {
            "schema": SCHEMA,
            "task_id": TASK_ID,
            "status": "UNKNOWN" if unknown else "FAIL",
            "mode": MODE,
            "code": code,
            "runtime_mutation_attempted": mutation_attempted,
            "rollback_requested": rollback_requested,
            "restart_attempt_count": 1 if restart_rc is not None else 0,
            "automatic_retry_allowed": False,
            "same_invocation_replay_allowed": False,
        }


def _process_starttime(pid):
    try:
        with open("/proc/{}/stat".format(pid), "rb") as handle:
            raw = handle.read(4097)
    except OSError:
        return None
    if not 1 <= len(raw) <= 4096 or b"\x00" in raw:
        return None
    marker = raw.rfind(b") ")
    if marker < 1:
        return None
    fields = raw[marker + 2:].split()
    if len(fields) < 20 or not fields[19].isdigit():
        return None
    return fields[19].decode("ascii")


def _pid_alive(pid, expected_starttime):
    return _process_starttime(pid) == expected_starttime


def _write_guardian_result(host, value):
    if (
        os.path.lexists(GUARDIAN_RESULT_PATH)
        or os.path.lexists(GUARDIAN_RESULT_TEMP)
    ):
        raise RollbackError("guardian_result_exists")
    host._write_exclusive(
        GUARDIAN_RESULT_TEMP,
        canonical(value).encode("ascii") + b"\n",
        0o600,
    )
    os.rename(GUARDIAN_RESULT_TEMP, GUARDIAN_RESULT_PATH)


def _write_guardian_unknown(host, staged_state, volatile_state):
    value = {
        "schema": "noteai.item28.guardian-result.v1",
        "status": "UNKNOWN",
        "dropin_removed": False,
        "staged_cleanup_status": "UNKNOWN_" + staged_state,
        "staged_residue_count": int(staged_state != "ABSENT"),
        "daemon_reload_count": 0,
        "runtime_start_count": 0,
        "volatile_residue_count": int(volatile_state != "ABSENT"),
    }
    try:
        _write_guardian_result(host, value)
    except Exception:
        pass
    return 4


def _verify_original_runtime(host, baseline):
    host.unit_manager("")
    host._regular_file(UNIT_PATH, 0o644, UNIT_SHA256)
    host.unit_state(True, require_result="success")
    if host.release_identity() != baseline["release_identity_sha256"]:
        raise RollbackError("release_restore")
    if host.public_listener_count() != 0:
        raise RollbackError("public_listener")
    host.health()


def guardian_main(parent_pid, parent_starttime):
    deadline = time.monotonic() + GUARDIAN_BUDGET_SECONDS
    armed = False
    while time.monotonic() < deadline:
        armed = armed or os.path.isfile(ARMED_PATH)
        abort = os.path.isfile(ABORT_PATH)
        if (
            abort or os.path.isfile(ROLLBACK_REQUEST_PATH)
            or (armed and not _pid_alive(parent_pid, parent_starttime))
        ):
            break
        if not _pid_alive(parent_pid, parent_starttime) and not armed:
            abort = True
            break
        time.sleep(0.2)
    else:
        return 4
    host = Host()
    try:
        try:
            _identity, _digest, baseline_raw = host._regular_file(
                BASELINE_PATH, 0o600
            )
            baseline = json.loads(baseline_raw.decode("ascii"))
        except (RollbackError, OSError, UnicodeError, ValueError):
            raise RollbackError("guardian_baseline")
        if (
            canonical(baseline).encode("ascii") + b"\n" != baseline_raw
            or baseline != {
                "schema": "noteai.item28.guardian-baseline.v1",
                "unit_fragment_sha256": UNIT_SHA256,
                "release_identity_sha256": baseline.get("release_identity_sha256"),
                "volatile_dropin_sha256": DROPIN_SHA256,
            }
            or type(baseline.get("release_identity_sha256")) is not str
            or len(baseline["release_identity_sha256"]) != 64
            or any(character not in "0123456789abcdef"
                   for character in baseline["release_identity_sha256"])
        ):
            raise RollbackError("guardian_baseline")
        staged_state = host.dropin_directory_state(
            STAGED_VOLATILE_DIR, STAGED_DROPIN_PATH
        )
        volatile_state = host.dropin_directory_state(VOLATILE_DIR, DROPIN_PATH)
        if (
            staged_state == "PARTIAL"
            or volatile_state in {"EMPTY", "PARTIAL"}
            or (
                staged_state != "ABSENT"
                and volatile_state != "ABSENT"
            )
        ):
            return _write_guardian_unknown(host, staged_state, volatile_state)
        if volatile_state == "ABSENT":
            cleanup_status = "ABSENT"
            try:
                if staged_state == "COMPLETE":
                    host._regular_file(
                        STAGED_DROPIN_PATH, 0o644, DROPIN_SHA256
                    )
                    os.unlink(STAGED_DROPIN_PATH)
                    os.rmdir(STAGED_VOLATILE_DIR)
                    cleanup_status = "CLEANED_COMPLETE"
                elif staged_state == "EMPTY":
                    os.rmdir(STAGED_VOLATILE_DIR)
                    cleanup_status = "CLEANED_EMPTY"
            except Exception:
                return _write_guardian_unknown(
                    host,
                    host.dropin_directory_state(
                        STAGED_VOLATILE_DIR, STAGED_DROPIN_PATH
                    ),
                    host.dropin_directory_state(VOLATILE_DIR, DROPIN_PATH),
                )
            if (
                host.dropin_directory_state(
                    STAGED_VOLATILE_DIR, STAGED_DROPIN_PATH
                ) != "ABSENT"
                or host.dropin_directory_state(VOLATILE_DIR, DROPIN_PATH)
                != "ABSENT"
            ):
                return _write_guardian_unknown(
                    host,
                    host.dropin_directory_state(
                        STAGED_VOLATILE_DIR, STAGED_DROPIN_PATH
                    ),
                    host.dropin_directory_state(VOLATILE_DIR, DROPIN_PATH),
                )
            _verify_original_runtime(host, baseline)
            value = {
                "schema": "noteai.item28.guardian-result.v1",
                "status": (
                    "ABORTED_NO_MUTATION" if cleanup_status == "ABSENT"
                    else "STAGED_CLEANED_NO_RUNTIME_MUTATION"
                ),
                "dropin_removed": False,
                "staged_cleanup_status": cleanup_status,
                "staged_residue_count": 0,
                "daemon_reload_count": 0,
                "runtime_start_count": 0,
                "volatile_residue_count": 0,
            }
            _write_guardian_result(host, value)
            return 0
        if staged_state != "ABSENT" or volatile_state != "COMPLETE":
            return _write_guardian_unknown(host, staged_state, volatile_state)
        host._regular_file(DROPIN_PATH, 0o644, DROPIN_SHA256)
        os.unlink(DROPIN_PATH)
        os.rmdir(VOLATILE_DIR)
        host.daemon_reload()
        runtime_start_count = host.restore_runtime_if_needed()
        _verify_original_runtime(host, baseline)
        if (
            host.dropin_directory_state(
                STAGED_VOLATILE_DIR, STAGED_DROPIN_PATH
            ) != "ABSENT"
            or host.dropin_directory_state(VOLATILE_DIR, DROPIN_PATH)
            != "ABSENT"
        ):
            raise RollbackError("volatile_residue")
        value = {
            "schema": "noteai.item28.guardian-result.v1",
            "status": "RESTORED",
            "dropin_removed": True,
            "staged_cleanup_status": "ABSENT",
            "staged_residue_count": 0,
            "daemon_reload_count": 1,
            "runtime_start_count": runtime_start_count,
            "volatile_residue_count": 0,
        }
        _write_guardian_result(host, value)
        return 0
    except Exception:
        return 4


def _signal(_number, _frame):
    raise RollbackError("signal")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=[MODE])
    parser.add_argument("--guardian", action="store_true")
    parser.add_argument("--parent-pid", type=int)
    parser.add_argument("--parent-starttime")
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        return 3
    os.umask(0o077)
    for name in tuple(os.environ):
        if (
            name.endswith("_PROXY") or name.startswith("ALIBABA_CLOUD_")
            or name in {
                "DOCKER_HOST", "DOCKER_CONFIG", "DOCKER_CERT_PATH",
                "DOCKER_TLS_VERIFY", "DATABASE_URL",
            }
        ):
            os.environ.pop(name, None)
    if args.guardian:
        if (
            args.mode is not None or not _strict_int(args.parent_pid, 1)
            or type(args.parent_starttime) is not str
            or not args.parent_starttime.isdigit()
        ):
            return 3
        return guardian_main(args.parent_pid, args.parent_starttime)
    if (
        args.mode != MODE or args.parent_pid is not None
        or args.parent_starttime is not None
    ):
        return 3
    for number in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(number, _signal)
    rc, payload = execute()
    print(canonical(payload), file=sys.stdout if rc == 0 else sys.stderr)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
