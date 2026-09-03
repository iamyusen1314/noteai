#!/bin/bash
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONINSPECT PYTHONOPTIMIZE
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy NO_PROXY no_proxy
unset DATABASE_URL NOTEAI_SQLITE_PATH PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD PGSERVICE PGSERVICEFILE
unset ALIBABA_CLOUD_ACCESS_KEY_ID ALIBABA_CLOUD_ACCESS_KEY_SECRET ALIBABA_CLOUD_SECURITY_TOKEN
unset ALICLOUD_ACCESS_KEY ALICLOUD_SECRET_KEY ALICLOUD_SECURITY_TOKEN OSS_ACCESS_KEY_ID OSS_ACCESS_KEY_SECRET

exec python3 -I -B - <<'PY'
import gzip
import hashlib
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import time


TRANSFER = "/run/noteai-item26-source-manifest-transfer-v3.sh.gz"
TRANSFER_BYTES = @@TRANSFER_BYTES@@
TRANSFER_SHA256 = "@@TRANSFER_SHA256@@"
RAW_BYTES = @@RAW_BYTES@@
RAW_SHA256 = "@@RAW_SHA256@@"
MAX_OUTPUT_BYTES = 65536
MAX_PASS_STDOUT_BYTES = 4096
INNER_TIMEOUT_SECONDS = 1260
INNER_KILL_GRACE_SECONDS = 20
HEX64 = re.compile(r"^[0-9a-f]{64}$")

PASS_KEYS = frozenset({
    "NOTEAI_ITEM26_SOURCE_MANIFEST",
    "incident_class",
    "transaction",
    "manifest_bytes",
    "manifest_file_sha256",
    "manifest_sha256",
    "postgresql_major_version",
    "table_count",
    "migration_count",
    "object_count",
    "object_size_bytes",
    "database_connection_count",
    "database_transaction_count",
    "database_write_count",
    "object_write_count",
    "row_values_emitted",
    "object_keys_emitted",
    "object_contents_read",
    "secret_values_emitted",
    "executor_native_superuser",
    "managed_owner_activation_count",
    "owner_table_contract_exact",
    "owner_mismatch_count",
    "rls_contract_exact",
    "rls_table_count",
    "force_rls_table_count",
    "row_security_off",
    "persistent_permission_mutation_count",
    "runtime_container_start_count",
    "container_residue_count",
    "task_root_residue_count",
    "source_manifest_retained",
    "temporary_account_delete_required",
    "provider_control_plane_mutation_count",
    "registry_call_count",
    "automatic_retry_allowed",
})

PASS_CONSTANTS = {
    "NOTEAI_ITEM26_SOURCE_MANIFEST": "PASS",
    "incident_class": "CONNECTED_KNOWN_READ_ONLY",
    "transaction": "REPEATABLE_READ_READ_ONLY_ROLLBACK",
    "postgresql_major_version": 16,
    "table_count": 56,
    "migration_count": 17,
    "database_connection_count": 1,
    "database_transaction_count": 1,
    "database_write_count": 0,
    "object_write_count": 0,
    "row_values_emitted": 0,
    "object_keys_emitted": 0,
    "object_contents_read": 0,
    "secret_values_emitted": 0,
    "executor_native_superuser": False,
    "managed_owner_activation_count": 1,
    "owner_table_contract_exact": True,
    "owner_mismatch_count": 0,
    "rls_contract_exact": True,
    "rls_table_count": 19,
    "force_rls_table_count": 0,
    "row_security_off": True,
    "persistent_permission_mutation_count": 0,
    "runtime_container_start_count": 1,
    "container_residue_count": 0,
    "task_root_residue_count": 0,
    "source_manifest_retained": True,
    "temporary_account_delete_required": True,
    "provider_control_plane_mutation_count": 0,
    "registry_call_count": 0,
    "automatic_retry_allowed": False,
}


class ExecutorError(Exception):
    def __init__(self, phase, inner_spawned=False, transfer_state="UNVERIFIED"):
        Exception.__init__(self, phase)
        self.phase = phase
        self.inner_spawned = inner_spawned
        self.transfer_state = transfer_state


def canonical(value):
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def fixed_result(status, phase, transfer_state):
    if status == "FAIL":
        return {
            "NOTEAI_ITEM26_SOURCE_MANIFEST_EXECUTOR": "FAIL",
            "incident_class": "PRE_CONNECT",
            "phase": phase,
            "database_attempted_state": "NO",
            "transfer_state": transfer_state,
            "readback_required": False,
            "automatic_retry_allowed": False,
        }
    return {
        "NOTEAI_ITEM26_SOURCE_MANIFEST_EXECUTOR": "UNKNOWN",
        "incident_class": "CONNECTED_UNKNOWN",
        "phase": phase,
        "database_attempted_state": "UNKNOWN",
        "transfer_state": transfer_state,
        "readback_required": True,
        "automatic_retry_allowed": False,
    }


def read_transfer():
    parent, name = os.path.split(TRANSFER)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    dirfd = os.open(parent, flags)
    fd = None
    try:
        parent_row = os.fstat(dirfd)
        if not (
            stat.S_ISDIR(parent_row.st_mode)
            and parent_row.st_uid == 0
            and parent_row.st_gid == 0
        ):
            raise ExecutorError("transfer_parent")
        before = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
        if not (
            stat.S_ISREG(before.st_mode)
            and not stat.S_ISLNK(before.st_mode)
            and before.st_uid == 0
            and before.st_gid == 0
            and stat.S_IMODE(before.st_mode) == 0o600
            and before.st_nlink == 1
            and before.st_size == TRANSFER_BYTES
        ):
            raise ExecutorError("transfer_metadata")
        file_flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NOATIME", 0)
        fd = os.open(name, file_flags, dir_fd=dirfd)
        body = read_current_transfer(dirfd, fd, name, before)
        if body is None:
            raise ExecutorError("transfer_hash")
        try:
            raw = gzip.decompress(body)
        except BaseException:
            raise ExecutorError("transfer_gzip")
        if len(raw) != RAW_BYTES or hashlib.sha256(raw).hexdigest() != RAW_SHA256:
            raise ExecutorError("raw_hash")
        return dirfd, fd, name, before, raw
    except BaseException:
        if fd is not None:
            os.close(fd)
        os.close(dirfd)
        raise


def process_group_exists(process):
    try:
        os.killpg(process.pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


def terminate(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except BaseException:
        pass
    deadline = time.monotonic() + INNER_KILL_GRACE_SECONDS
    while time.monotonic() < deadline and process_group_exists(process):
        time.sleep(0.1)
    if process_group_exists(process):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except BaseException:
            pass
    try:
        process.wait(timeout=INNER_KILL_GRACE_SECONDS)
    except BaseException:
        pass


def run_inner(raw):
    deadline = time.monotonic() + INNER_TIMEOUT_SECONDS
    try:
        process = subprocess.Popen(
            ["/bin/bash", "-s"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"},
            close_fds=True,
            bufsize=0,
            start_new_session=True,
        )
    except BaseException:
        raise ExecutorError("inner_spawn", False, "EXACT_RETAINED")
    selector = None
    offset = 0
    input_complete = False
    try:
        selector = selectors.DefaultSelector()
        outputs = {"stdout": bytearray(), "stderr": bytearray()}
        os.set_blocking(process.stdin.fileno(), False)
        selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
        for label, pipe in (("stdout", process.stdout), ("stderr", process.stderr)):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, label)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ExecutorError("inner_timeout", True, "UNKNOWN")
            events = selector.select(min(remaining, 1.0))
            if not events and process.poll() is not None:
                events = [
                    (key, selectors.EVENT_READ)
                    for key in tuple(selector.get_map().values())
                ]
            for key, _mask in events:
                if key.data == "stdin":
                    try:
                        written = os.write(key.fileobj.fileno(), raw[offset:offset + 65536])
                    except BlockingIOError:
                        continue
                    except (BrokenPipeError, OSError):
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                        continue
                    if written <= 0:
                        raise ExecutorError("inner_stdin", True, "UNKNOWN")
                    offset += written
                    if offset == len(raw):
                        input_complete = True
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                    continue
                try:
                    chunk = os.read(key.fileobj.fileno(), 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                output = outputs[key.data]
                output.extend(chunk)
                if len(outputs["stdout"]) + len(outputs["stderr"]) > MAX_OUTPUT_BYTES:
                    raise ExecutorError("inner_output_limit", True, "UNKNOWN")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ExecutorError("inner_timeout", True, "UNKNOWN")
        returncode = process.wait(timeout=remaining)
        if not input_complete:
            raise ExecutorError("inner_stdin_incomplete", True, "UNKNOWN")
        return returncode, bytes(outputs["stdout"]), bytes(outputs["stderr"])
    except BaseException:
        terminate(process)
        raise
    finally:
        if selector is not None:
            selector.close()
        for pipe in (process.stdin, process.stdout, process.stderr):
            try:
                pipe.close()
            except BaseException:
                pass


def object_no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate")
        result[key] = value
    return result


def validated_pass(stdout, stderr):
    if len(stdout) > MAX_PASS_STDOUT_BYTES or stderr or not stdout.endswith(b"\n") or stdout.count(b"\n") != 1:
        raise ExecutorError("inner_pass_output", True, "UNKNOWN")
    try:
        text = stdout.decode("ascii")
        value = json.loads(text, object_pairs_hook=object_no_duplicates)
    except BaseException:
        raise ExecutorError("inner_pass_json", True, "UNKNOWN")
    if not isinstance(value, dict) or set(value) != PASS_KEYS:
        raise ExecutorError("inner_pass_keys", True, "UNKNOWN")
    for key, expected in PASS_CONSTANTS.items():
        if value.get(key) != expected or type(value.get(key)) is not type(expected):
            raise ExecutorError("inner_pass_contract", True, "UNKNOWN")
    for key, minimum, maximum in (
        ("manifest_bytes", 1, 1048576),
        ("object_count", 0, 100000),
        ("object_size_bytes", 0, 1000000000000000),
    ):
        supplied = value.get(key)
        if type(supplied) is not int or not minimum <= supplied <= maximum:
            raise ExecutorError("inner_pass_bounds", True, "UNKNOWN")
    for key in ("manifest_file_sha256", "manifest_sha256"):
        if not isinstance(value.get(key), str) or HEX64.fullmatch(value[key]) is None:
            raise ExecutorError("inner_pass_hash", True, "UNKNOWN")
    return value


def inner_known_failure(returncode, stdout, stderr):
    if returncode != 3 or stdout or len(stderr) > 2048:
        return False
    try:
        text = stderr.decode("ascii")
    except UnicodeError:
        return False
    pattern = (
        r"^NOTEAI_ITEM26_SOURCE_MANIFEST=FAIL incident_class=PRE_CONNECT "
        r"phase=[a-z0-9_]{1,64} cleanup=VERIFIED_TASK_ZERO "
        r"database_connections=0 database_writes=0 object_writes=0 "
        r"row_values_emitted=0 object_keys_emitted=0 secret_values_emitted=0 "
        r"automatic_retry_allowed=false\n$"
    )
    return re.fullmatch(pattern, text) is not None


def read_current_transfer(dirfd, fd, name, before):
    try:
        current = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
        opened = os.fstat(fd)
        expected = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_uid,
            before.st_gid,
            before.st_nlink,
            before.st_size,
        )
        if (
            current.st_dev,
            current.st_ino,
            current.st_mode,
            current.st_uid,
            current.st_gid,
            current.st_nlink,
            current.st_size,
        ) != expected or (
            opened.st_dev,
            opened.st_ino,
            opened.st_mode,
            opened.st_uid,
            opened.st_gid,
            opened.st_nlink,
            opened.st_size,
        ) != expected:
            return None
        os.lseek(fd, 0, os.SEEK_SET)
        body = b""
        while len(body) <= TRANSFER_BYTES:
            chunk = os.read(fd, min(65536, TRANSFER_BYTES + 1 - len(body)))
            if not chunk:
                break
            body += chunk
        if len(body) != TRANSFER_BYTES or hashlib.sha256(body).hexdigest() != TRANSFER_SHA256:
            return None
        current_after = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
        opened_after = os.fstat(fd)
        if (
            current_after.st_dev,
            current_after.st_ino,
            current_after.st_mode,
            current_after.st_uid,
            current_after.st_gid,
            current_after.st_nlink,
            current_after.st_size,
        ) != expected or (
            opened_after.st_dev,
            opened_after.st_ino,
            opened_after.st_mode,
            opened_after.st_uid,
            opened_after.st_gid,
            opened_after.st_nlink,
            opened_after.st_size,
        ) != expected:
            return None
        return body
    except BaseException:
        return None


def main():
    if os.geteuid() != 0 or os.getegid() != 0:
        raise ExecutorError("identity")
    dirfd = None
    fd = None
    try:
        try:
            dirfd, fd, name, before, raw = read_transfer()
        except ExecutorError:
            raise
        except BaseException:
            raise ExecutorError("transfer_preflight", False, "UNVERIFIED")
        try:
            returncode, stdout, stderr = run_inner(raw)
        except ExecutorError as exc:
            if exc.phase == "inner_spawn" and not exc.inner_spawned:
                if read_current_transfer(dirfd, fd, name, before) is None:
                    raise ExecutorError("transfer_after_spawn_failure", False, "UNVERIFIED_RETAINED")
                raise ExecutorError("inner_spawn", False, "EXACT_RETAINED")
            raise
        if returncode == 0:
            result = validated_pass(stdout, stderr)
            if read_current_transfer(dirfd, fd, name, before) is None:
                raise ExecutorError("transfer_after_pass", True, "UNKNOWN")
            result["transfer_state"] = "EXACT_RETAINED"
            result["transfer_retained"] = True
            result["readback_required"] = True
            return 0, 1, result
        if inner_known_failure(returncode, stdout, stderr):
            if read_current_transfer(dirfd, fd, name, before) is None:
                raise ExecutorError("transfer_after_known_failure", True, "UNKNOWN")
            return 3, 2, fixed_result("FAIL", "inner_preconnect", "EXACT_RETAINED")
        raise ExecutorError("inner_execute", True, "UNKNOWN")
    finally:
        if fd is not None:
            os.close(fd)
        if dirfd is not None:
            os.close(dirfd)


try:
    code, output_fd, receipt = main()
except ExecutorError as exc:
    code = 4 if exc.inner_spawned else 3
    output_fd = 2
    status = "UNKNOWN" if exc.inner_spawned else "FAIL"
    receipt = fixed_result(status, exc.phase, exc.transfer_state)
except BaseException:
    code = 4
    output_fd = 2
    receipt = fixed_result("UNKNOWN", "executor_exception", "UNKNOWN")
try:
    terminal = canonical(receipt)
    if len(terminal) > 4096:
        os._exit(4)
    written = os.write(output_fd, terminal)
    if written != len(terminal):
        os._exit(4)
except BaseException:
    os._exit(4)
os._exit(code)
PY
