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
unset DOCKER_HOST DOCKER_CONTEXT DOCKER_CONFIG DOCKER_TLS DOCKER_TLS_VERIFY DOCKER_CERT_PATH

exec python3 -I -B - <<'PY'
import hashlib
import json
import os
import re
import stat
import subprocess
import urllib.request


RUN_ROOT = "/run"
TASK_NAME = "noteai-item26-source-manifest-capture-v3"
DOCKER_CONFIG_NAME = "docker-config"
OUTPUT_NAME = "output"
DRIVER_NAME = "driver.py"
HELPER_OUT_NAME = "helper.stdout"
HELPER_ERR_NAME = "helper.stderr"
FINAL_NAME = "noteai-item26-source-manifest-v3"
FINAL_MANIFEST_NAME = "source-manifest.json"
TRANSFER = "/run/noteai-item26-source-manifest-transfer-v3.sh.gz"
TRANSFER_NAME = os.path.basename(TRANSFER)
CONTROL_NAME = "noteai-item26-source-account-v2"
PRIVATE_KEY_NAME = "control-private.pem"
PUBLIC_KEY_NAME = "control-public.pem"
ENVELOPE_NAME = "control-database-url.enc"
READBACK_DOCKER_CONFIG_NAME = "noteai-item26-source-manifest-readback-v3-no-config"
CONTAINER_NAME = "noteai-item26-source-manifest-capture-v3"
CONTAINER_LABEL = "PROD-FIRST-LAUNCH-PITR-RESTORE-001-source-manifest-v3"
IMAGE_CONFIG = "sha256:1f503665de518d871813133335418822e9383544fbfd1cde3e2b66bb51470c95"
EXPECTED_INSTANCE = "i-wz9j36od3nf2b1uw7bvg"
EXPECTED_ROLE = "noteai-storage-api-20260729-c60cc608"
TRANSFER_BYTES = @@TRANSFER_BYTES@@
TRANSFER_SHA256 = "@@TRANSFER_SHA256@@"
DRIVER_BYTES = @@DRIVER_BYTES@@
DRIVER_SHA256 = "@@DRIVER_SHA256@@"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
FIXED_CODES = frozenset({
    "metadata", "race", "read", "env", "dsn", "identity", "capability",
    "envelope", "key", "write", "output", "payload", "api_env",
    "topology", "storage", "backend", "session", "owner", "tables",
    "rls", "migrations", "database", "references", "privacy", "size",
    "rollback",
})
PRE_CONNECT_CODES = frozenset({
    "metadata", "race", "read", "env", "dsn", "identity", "capability",
    "envelope", "key", "output", "payload", "api_env", "topology",
    "storage", "backend",
})
DEFINITE_CONNECTED_CODES = frozenset({
    "session", "owner", "tables", "rls", "write", "database",
    "references", "privacy", "size",
})
AMBIGUOUS_MIGRATION_CODES = frozenset({"migrations"})
ROLLBACK_UNKNOWN_CODES = frozenset({"rollback"})


def identity_tuple(row):
    return (
        row.st_dev,
        row.st_ino,
        row.st_mode,
        row.st_uid,
        row.st_gid,
        row.st_nlink,
        row.st_size,
    )


def directory_flags():
    return (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_NOATIME", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def file_flags():
    return (
        os.O_RDONLY
        | os.O_NOFOLLOW
        | getattr(os, "O_NOATIME", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def present_at(parent_fd, name):
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return True


def open_directory_at(parent_fd, name, mode):
    try:
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False, None
    except OSError:
        return True, None
    if not (
        stat.S_ISDIR(before.st_mode)
        and not stat.S_ISLNK(before.st_mode)
        and before.st_uid == 0
        and before.st_gid == 0
        and stat.S_IMODE(before.st_mode) == mode
    ):
        return True, None
    try:
        fd = os.open(name, directory_flags(), dir_fd=parent_fd)
    except OSError:
        return True, None
    try:
        current = os.fstat(fd)
        if identity_tuple(current) != identity_tuple(before):
            os.close(fd)
            return True, None
    except BaseException:
        os.close(fd)
        raise
    return True, fd


def exact_names_fd(fd, expected):
    try:
        names = os.listdir(fd)
    except OSError:
        return False
    return len(names) == len(set(names)) and set(names) == set(expected)


def file_row_at(parent_fd, name, low, high):
    try:
        row = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError:
        return None
    if not (
        stat.S_ISREG(row.st_mode)
        and not stat.S_ISLNK(row.st_mode)
        and row.st_uid == 0
        and row.st_gid == 0
        and stat.S_IMODE(row.st_mode) == 0o600
        and row.st_nlink == 1
        and low <= row.st_size <= high
    ):
        return None
    return row


def read_safe_at(parent_fd, name, low, high):
    before = file_row_at(parent_fd, name, low, high)
    if before is None:
        raise ValueError("metadata")
    fd = os.open(name, file_flags(), dir_fd=parent_fd)
    try:
        opened = os.fstat(fd)
        if identity_tuple(opened) != identity_tuple(before):
            raise ValueError("race")
        body = b""
        while len(body) <= high:
            chunk = os.read(fd, min(65536, high + 1 - len(body)))
            if not chunk:
                break
            body += chunk
        after = os.fstat(fd)
        if identity_tuple(after) != identity_tuple(opened):
            raise ValueError("race")
    finally:
        os.close(fd)
    if len(body) != before.st_size or not low <= len(body) <= high:
        raise ValueError("read")
    return body


def exact_hash_at(parent_fd, name, size, digest):
    try:
        body = read_safe_at(parent_fd, name, size, size)
    except (OSError, ValueError):
        return False
    return hashlib.sha256(body).hexdigest() == digest


def control_metadata_exact(run_fd):
    present, control_fd = open_directory_at(run_fd, CONTROL_NAME, 0o700)
    if not present or control_fd is None:
        return False
    try:
        return (
            exact_names_fd(
                control_fd,
                {PRIVATE_KEY_NAME, PUBLIC_KEY_NAME, ENVELOPE_NAME},
            )
            and file_row_at(control_fd, PRIVATE_KEY_NAME, 2000, 5000) is not None
            and file_row_at(control_fd, PUBLIC_KEY_NAME, 625, 625) is not None
            and file_row_at(control_fd, ENVELOPE_NAME, 894, 894) is not None
        )
    finally:
        os.close(control_fd)


def helper_error_code(task_fd):
    try:
        body = read_safe_at(task_fd, HELPER_ERR_NAME, 1, 512)
    except (OSError, ValueError):
        return None
    supplied = hashlib.sha256(body).hexdigest()
    matched = []
    for code in FIXED_CODES:
        expected = (
            json.dumps(
                {
                    "status": "SOURCE_MANIFEST_FAILED",
                    "code": code,
                    "automatic_retry_allowed": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("ascii")
        if hashlib.sha256(expected).hexdigest() == supplied:
            matched.append(code)
    if len(matched) == 1:
        return matched[0]
    return None


def host_identity_exact():
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise RuntimeError("redirect")

    try:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            NoRedirect(),
        )
        request = urllib.request.Request(
            "http://100.100.100.200/latest/api/token",
            method="PUT",
            headers={"X-aliyun-ecs-metadata-token-ttl-seconds": "60"},
        )
        with opener.open(request, timeout=3) as response:
            token = response.read(512).decode("ascii").strip()
        if not token or len(token) > 256:
            return False
        headers = {"X-aliyun-ecs-metadata-token": token}
        values = []
        for suffix in ("instance-id", "ram/security-credentials/"):
            request = urllib.request.Request(
                "http://100.100.100.200/latest/meta-data/" + suffix,
                headers=headers,
                method="GET",
            )
            with opener.open(request, timeout=3) as response:
                body = response.read(4096)
            if len(body) >= 4096:
                return False
            values.append(body.decode("ascii").strip())
        return (
            re.fullmatch(r"i-[a-z0-9]+", values[0]) is not None
            and values[0] == EXPECTED_INSTANCE
            and [row for row in values[1].splitlines() if row]
            == [EXPECTED_ROLE]
        )
    except BaseException:
        return False


def established_5432_count():
    try:
        result = subprocess.run(
            ["/usr/sbin/ss", "-Htan", "state", "established"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"},
            timeout=10,
        )
    except BaseException:
        return None
    if (
        result.returncode != 0
        or len(result.stdout) > 65536
        or len(result.stderr) > 65536
    ):
        return None
    try:
        lines = result.stdout.decode("ascii").splitlines()
    except UnicodeError:
        return None
    count = 0
    for line in lines:
        fields = line.split()
        if len(fields) < 4:
            return None
        if (
            fields[-2].rsplit(":", 1)[-1] == "5432"
            or fields[-1].rsplit(":", 1)[-1] == "5432"
        ):
            count += 1
    return count


def readback_config_absent(run_fd):
    return not present_at(run_fd, READBACK_DOCKER_CONFIG_NAME)


def container_state(run_fd):
    if not readback_config_absent(run_fd):
        return {"query_ok": False, "count": None, "exact": False}
    docker_config = os.path.join(RUN_ROOT, READBACK_DOCKER_CONFIG_NAME)
    env = {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LC_ALL": "C",
        "HOME": "/run/noteai-item26-no-home",
        "DOCKER_CONFIG": docker_config,
    }
    command = [
        "/usr/bin/docker",
        "--context=default",
        "container",
        "ls",
        "-aq",
        "--filter",
        "name=^/{}$".format(CONTAINER_NAME),
    ]
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            timeout=10,
        )
    except BaseException:
        return {"query_ok": False, "count": None, "exact": False}
    if not readback_config_absent(run_fd):
        return {"query_ok": False, "count": None, "exact": False}
    if (
        result.returncode != 0
        or len(result.stdout) > 4096
        or len(result.stderr) > 4096
    ):
        return {"query_ok": False, "count": None, "exact": False}
    try:
        ids = [
            line
            for line in result.stdout.decode("ascii", "strict").splitlines()
            if line
        ]
    except UnicodeError:
        return {"query_ok": False, "count": None, "exact": False}
    if not ids:
        return {"query_ok": True, "count": 0, "exact": True}
    if len(ids) != 1 or re.fullmatch(r"[0-9a-f]{12,64}", ids[0]) is None:
        return {"query_ok": True, "count": len(ids), "exact": False}
    try:
        inspect = subprocess.run(
            [
                "/usr/bin/docker",
                "--context=default",
                "inspect",
                ids[0],
                "--format",
                '{{index .Config.Labels "com.noteai.task"}}|{{.Image}}',
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            timeout=10,
        )
    except BaseException:
        return {"query_ok": True, "count": 1, "exact": False}
    if not readback_config_absent(run_fd):
        return {"query_ok": False, "count": 1, "exact": False}
    expected = "{}|{}\n".format(CONTAINER_LABEL, IMAGE_CONFIG).encode("ascii")
    exact = (
        inspect.returncode == 0
        and len(inspect.stdout) <= 4096
        and len(inspect.stderr) <= 4096
        and inspect.stdout == expected
    )
    return {"query_ok": True, "count": 1, "exact": exact}


def task_state(run_fd):
    state = {
        "present": False,
        "exact": False,
        "inventory": "ABSENT",
        "output": "ABSENT",
        "helper_stdout_bytes": None,
        "helper_error_code": None,
        "driver_exact": False,
        "docker_config_exact": False,
    }
    present, task_fd = open_directory_at(run_fd, TASK_NAME, 0o700)
    state["present"] = present
    if not present:
        return state
    if task_fd is None:
        state["inventory"] = "UNSAFE"
        return state
    state["inventory"] = "UNSAFE"
    try:
        pre_docker_names = {DOCKER_CONFIG_NAME, OUTPUT_NAME, DRIVER_NAME}
        helper_names = {
            DOCKER_CONFIG_NAME,
            OUTPUT_NAME,
            DRIVER_NAME,
            HELPER_OUT_NAME,
            HELPER_ERR_NAME,
        }
        post_move_names = {
            DOCKER_CONFIG_NAME,
            DRIVER_NAME,
            HELPER_OUT_NAME,
            HELPER_ERR_NAME,
        }
        try:
            names = os.listdir(task_fd)
        except OSError:
            return state
        if len(names) != len(set(names)):
            return state
        name_set = set(names)
        if name_set == pre_docker_names:
            candidate_inventory = "PRE_DOCKER_EXACT"
        elif name_set == helper_names:
            candidate_inventory = "HELPER_EXACT"
        elif name_set == post_move_names:
            candidate_inventory = "POST_MOVE_EXACT"
        else:
            return state

        state["driver_exact"] = exact_hash_at(
            task_fd,
            DRIVER_NAME,
            DRIVER_BYTES,
            DRIVER_SHA256,
        )
        docker_present, docker_fd = open_directory_at(
            task_fd,
            DOCKER_CONFIG_NAME,
            0o700,
        )
        if docker_present and docker_fd is not None:
            try:
                state["docker_config_exact"] = (
                    exact_names_fd(docker_fd, {"config.json"})
                    and read_safe_at(docker_fd, "config.json", 2, 2) == b"{}"
                )
            except (OSError, ValueError):
                state["docker_config_exact"] = False
            finally:
                os.close(docker_fd)

        output_present, output_fd = open_directory_at(task_fd, OUTPUT_NAME, 0o700)
        if not output_present:
            state["output"] = "ABSENT"
        elif output_fd is None:
            state["output"] = "UNSAFE"
        else:
            try:
                if exact_names_fd(output_fd, set()):
                    state["output"] = "EMPTY"
                elif (
                    exact_names_fd(output_fd, {FINAL_MANIFEST_NAME})
                    and file_row_at(
                        output_fd,
                        FINAL_MANIFEST_NAME,
                        1,
                        1048576,
                    )
                    is not None
                ):
                    state["output"] = "MANIFEST_PRESENT"
                else:
                    state["output"] = "UNSAFE"
            finally:
                os.close(output_fd)

        helper_stdout = None
        helpers_metadata_exact = False
        if candidate_inventory in {"HELPER_EXACT", "POST_MOVE_EXACT"}:
            helper_stdout = file_row_at(task_fd, HELPER_OUT_NAME, 0, 4096)
            helper_stderr = file_row_at(task_fd, HELPER_ERR_NAME, 0, 512)
            helpers_metadata_exact = (
                helper_stdout is not None and helper_stderr is not None
            )
        state["helper_stdout_bytes"] = (
            None if helper_stdout is None else helper_stdout.st_size
        )
        common_exact = state["driver_exact"] and state["docker_config_exact"]
        if (
            candidate_inventory == "PRE_DOCKER_EXACT"
            and common_exact
            and state["output"] == "EMPTY"
        ):
            state["exact"] = True
            state["inventory"] = candidate_inventory
        elif (
            candidate_inventory == "HELPER_EXACT"
            and common_exact
            and helpers_metadata_exact
            and state["output"] in {"EMPTY", "MANIFEST_PRESENT"}
        ):
            state["exact"] = True
            state["inventory"] = candidate_inventory
            state["helper_error_code"] = helper_error_code(task_fd)
        elif (
            candidate_inventory == "POST_MOVE_EXACT"
            and common_exact
            and helpers_metadata_exact
            and state["output"] == "ABSENT"
        ):
            state["exact"] = True
            state["inventory"] = candidate_inventory
        return state
    finally:
        os.close(task_fd)


def final_state(run_fd):
    present, final_fd = open_directory_at(run_fd, FINAL_NAME, 0o700)
    if not present:
        return {"present": False, "exact": False}
    if final_fd is None:
        return {"present": True, "exact": False}
    try:
        exact = (
            exact_names_fd(final_fd, {FINAL_MANIFEST_NAME})
            and file_row_at(final_fd, FINAL_MANIFEST_NAME, 1, 1048576)
            is not None
        )
        return {"present": True, "exact": exact}
    finally:
        os.close(final_fd)


def classify(identity_exact, control_exact, transfer_exact, task, final, container, socket_count):
    status = "UNCLASSIFIED_UNKNOWN"
    database_state = "UNKNOWN"
    manifest_readback_allowed = False
    if not identity_exact or not control_exact or socket_count is None:
        status = "IDENTITY_OR_CONTROL_UNKNOWN"
    elif socket_count != 0:
        status = "DATABASE_SOCKET_PRESENT_UNKNOWN"
        database_state = "CURRENT_CONNECTION_PRESENT_UNKNOWN"
    elif not container["query_ok"] or container["count"] is None:
        status = "CONTAINER_STATE_UNKNOWN"
    elif container["count"] > 0:
        status = "CONTAINER_PRESENT_UNKNOWN"
        database_state = "TASK_EXECUTION_OR_RESIDUE_UNKNOWN"
    elif final["present"]:
        committed_path_exact = (
            (not task["present"] and transfer_exact)
            or (
                task["exact"]
                and task["inventory"] == "POST_MOVE_EXACT"
                and task["driver_exact"]
            )
        )
        if final["exact"] and committed_path_exact:
            status = "MANIFEST_COMMITTED_READBACK_REQUIRED"
            database_state = "CONNECTED_READ_ONLY_ROLLBACK"
            manifest_readback_allowed = True
        else:
            status = "UNSAFE_FINAL_RESIDUE"
    elif not task["present"]:
        if transfer_exact:
            status = "NO_TASK_NO_FINAL_EXECUTION_UNPROVEN"
            database_state = "EXECUTION_UNPROVEN"
        else:
            status = "MISSING_OR_UNSAFE_INPUT"
    elif not task["exact"]:
        status = "UNSAFE_TASK_RESIDUE"
    elif (
        task["inventory"] == "PRE_DOCKER_EXACT"
        and task["output"] == "EMPTY"
    ):
        status = "PRE_DOCKER_RESIDUE"
        database_state = "PRE_DATABASE_BARRIER"
    elif (
        task["inventory"] == "HELPER_EXACT"
        and task["output"] == "MANIFEST_PRESENT"
    ):
        status = "STAGED_UNCOMMITTED_READBACK_REQUIRED"
        database_state = "CONNECTED_READ_ONLY_ROLLBACK"
        manifest_readback_allowed = True
    elif (
        task["inventory"] == "HELPER_EXACT"
        and task["output"] == "EMPTY"
        and task["helper_stdout_bytes"] == 0
        and task["helper_error_code"] in PRE_CONNECT_CODES
    ):
        status = "PRECONNECT_FIXED_RETAINED"
        database_state = "PRE_CONNECT"
    elif (
        task["inventory"] == "HELPER_EXACT"
        and task["output"] == "EMPTY"
        and task["helper_stdout_bytes"] == 0
        and task["helper_error_code"] in DEFINITE_CONNECTED_CODES
    ):
        status = "POSTCONNECT_FIXED_NO_COMMIT"
        database_state = "CONNECTED_READ_ONLY_ROLLBACK_EXPECTED"
    elif (
        task["inventory"] == "HELPER_EXACT"
        and task["output"] == "EMPTY"
        and task["helper_stdout_bytes"] == 0
        and task["helper_error_code"] in AMBIGUOUS_MIGRATION_CODES
    ):
        status = "MIGRATIONS_PHASE_NO_COMMIT_UNKNOWN"
        database_state = "MIGRATIONS_BARRIER_UNKNOWN"
    elif (
        task["inventory"] == "HELPER_EXACT"
        and task["output"] == "EMPTY"
        and task["helper_stdout_bytes"] == 0
        and task["helper_error_code"] in ROLLBACK_UNKNOWN_CODES
    ):
        status = "ROLLBACK_OUTCOME_UNKNOWN"
        database_state = "CONNECTED_ROLLBACK_UNKNOWN"
    elif (
        task["inventory"] == "HELPER_EXACT"
        and task["output"] == "EMPTY"
        and task["helper_stdout_bytes"] == 0
    ):
        status = "DB_BARRIER_NO_COMMIT_UNKNOWN"
        database_state = "DB_BARRIER_UNKNOWN"
    return status, database_state, manifest_readback_allowed


def main():
    if os.geteuid() != 0 or os.getegid() != 0:
        raise SystemExit(3)
    partitions = (
        PRE_CONNECT_CODES,
        DEFINITE_CONNECTED_CODES,
        AMBIGUOUS_MIGRATION_CODES,
        ROLLBACK_UNKNOWN_CODES,
    )
    if (
        len(FIXED_CODES) != 26
        or set().union(*partitions) != set(FIXED_CODES)
        or sum(len(group) for group in partitions) != len(FIXED_CODES)
        or os.path.dirname(TRANSFER) != RUN_ROOT
        or TRANSFER_NAME != "noteai-item26-source-manifest-transfer-v3.sh.gz"
        or not isinstance(TRANSFER_BYTES, int)
        or not 1 <= TRANSFER_BYTES <= 131072
        or HEX64.fullmatch(TRANSFER_SHA256) is None
        or not isinstance(DRIVER_BYTES, int)
        or not 1 <= DRIVER_BYTES <= 131072
        or HEX64.fullmatch(DRIVER_SHA256) is None
    ):
        raise SystemExit(4)

    run_fd = os.open(RUN_ROOT, directory_flags())
    try:
        identity_exact = host_identity_exact()
        control_exact = control_metadata_exact(run_fd)
        transfer_exact = exact_hash_at(
            run_fd,
            TRANSFER_NAME,
            TRANSFER_BYTES,
            TRANSFER_SHA256,
        )
        task = task_state(run_fd)
        final = final_state(run_fd)
        container = container_state(run_fd)
        socket_count = established_5432_count()
        status, database_state, manifest_readback_allowed = classify(
            identity_exact,
            control_exact,
            transfer_exact,
            task,
            final,
            container,
            socket_count,
        )
    finally:
        os.close(run_fd)

    result = {
        "NOTEAI_ITEM26_SOURCE_MANIFEST_READBACK": status,
        "host": "API-C",
        "host_identity_exact": identity_exact,
        "control_metadata_exact": control_exact,
        "control_value_read_count": 0,
        "transfer_exact": transfer_exact,
        "task_root_present": task["present"],
        "task_root_exact": task["exact"],
        "task_inventory_state": task["inventory"],
        "driver_exact": task["driver_exact"],
        "task_docker_config_exact": task["docker_config_exact"],
        "final_root_present": final["present"],
        "final_root_exact": final["exact"],
        "output_state": task["output"],
        "helper_stdout_bytes": task["helper_stdout_bytes"],
        "helper_stdout_value_read_count": 0,
        "helper_error_code": task["helper_error_code"],
        "task_container_query_ok": container["query_ok"],
        "task_container_count": container["count"],
        "task_container_exact": container["exact"],
        "established_5432_count": socket_count,
        "original_database_state": database_state,
        "manifest_readback_allowed": manifest_readback_allowed,
        "same_invocation_replay_allowed": False,
        "new_capture_allowed": False,
        "cleanup_allowed": False,
        "temporary_account_delete_allowed": False,
        "pitr_stage_allowed": False,
        "worker_stage_allowed": False,
        "automatic_retry_allowed": False,
        "api_environment_value_read_count": 0,
        "storage_environment_value_read_count": 0,
        "source_secret_value_read_count": 0,
        "ciphertext_value_read_count": 0,
        "manifest_value_read_count": 0,
        "database_connection_count": 0,
        "database_write_count": 0,
        "object_read_count": 0,
        "object_write_count": 0,
        "provider_control_plane_mutation_count": 0,
        "runtime_container_start_count": 0,
    }
    encoded = json.dumps(
        result,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    if len(encoded) > 4096:
        raise SystemExit(4)
    return encoded + b"\n"


try:
    terminal_body = main()
    terminal_exit = 0
except BaseException:
    terminal_body = (
        b'{"NOTEAI_ITEM26_SOURCE_MANIFEST_READBACK":"READBACK_UNKNOWN",'
        b'"automatic_retry_allowed":false,"cleanup_allowed":false,'
        b'"manifest_readback_allowed":false,"new_capture_allowed":false,'
        b'"pitr_stage_allowed":false,"same_invocation_replay_allowed":false,'
        b'"temporary_account_delete_allowed":false,"worker_stage_allowed":false}\n'
    )
    terminal_exit = 4

try:
    terminal_written = os.write(1, terminal_body)
except BaseException:
    raise SystemExit(4)
if terminal_written != len(terminal_body):
    raise SystemExit(4)
raise SystemExit(terminal_exit)
PY
