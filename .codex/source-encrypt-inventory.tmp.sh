#!/usr/bin/env bash
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
unset DOCKER_HOST DOCKER_CONTEXT DOCKER_CONFIG DOCKER_TLS_VERIFY DOCKER_CERT_PATH
unset PYTHONHOME PYTHONPATH PYTHONSTARTUP PYTHONUSERBASE PYTHONWARNINGS PYTHONINSPECT

python3 -I - <<'PY'
import hashlib
import json
import os
import shutil
import stat
import subprocess


TASK_ROOT = "/run/noteai-item21-worker-secret-source-v1"
TOOL_ROOT = "/run/noteai-item21-worker-secret-source-tools-v1"
DOCKER_CONFIG_ROOT = os.path.join(TASK_ROOT, "docker-config")
INPUT_ROOT = os.path.join(TASK_ROOT, "input")
OUTPUT_ROOT = os.path.join(TASK_ROOT, "output")
CONTAINER_NAME = "noteai-item21-worker-secret-source"
EXPECTED_TOP = {
    "docker-config",
    "helper.stderr",
    "helper.stdout",
    "input",
    "output",
}
EXPECTED_TOOLS = {
    "production_secret_envelope.py": "b6a67fab3fd66f8c378716935b105ac1fbe83c54190eb57baf1b1c3d6b7e2fbf",
    "source-driver.py": "ff9bdcfa6b8979848ff35e7d8c7c9c05450d9573d21eb220fbcc367d9ce1c3d2",
}
EXPECTED_INPUTS = {
    "worker-c-public.pem": 625,
    "worker-c-public.sha256": 65,
    "worker-f-public.pem": 625,
    "worker-f-public.sha256": 65,
}
EXPECTED_OUTPUTS = {
    "worker-c-database.envelope.json",
    "worker-c-private_storage.envelope.json",
    "worker-f-database.envelope.json",
    "worker-f-private_storage.envelope.json",
}
SUCCESS_STDOUT = (
    b'{"database_payload_unchanged":true,"derived_role_replacement_count":1,'
    b'"envelope_count":4,"plaintext_output_count":0,"source_file_count":2,'
    b'"status":"ENCRYPTED","unchanged_storage_key_count":6,'
    b'"worker_database_payloads_equal":true,"worker_storage_payloads_equal":true}\n'
)
FAILED_STDOUT = b'{"status":"HELPER_FAILED"}\n'
MINIMAL_ENV = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LC_ALL": "C",
    "DOCKER_CONFIG": DOCKER_CONFIG_ROOT,
}


def lstat_row(path):
    try:
        return os.lstat(path)
    except OSError:
        return None


def safe_dir(path, mode):
    row = lstat_row(path)
    return bool(
        row is not None
        and stat.S_ISDIR(row.st_mode)
        and not stat.S_ISLNK(row.st_mode)
        and row.st_uid == 0
        and row.st_gid == 0
        and stat.S_IMODE(row.st_mode) == mode
    )


def safe_file(path, mode, minimum, maximum):
    row = lstat_row(path)
    return bool(
        row is not None
        and stat.S_ISREG(row.st_mode)
        and not stat.S_ISLNK(row.st_mode)
        and row.st_uid == 0
        and row.st_gid == 0
        and stat.S_IMODE(row.st_mode) == mode
        and row.st_nlink == 1
        and minimum <= row.st_size <= maximum
    )


def list_names(path):
    try:
        return set(os.listdir(path)), True
    except OSError:
        return set(), False


def sha256_file(path, maximum):
    row = lstat_row(path)
    if row is None or row.st_size > maximum:
        return None
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(65536)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def read_limited(path, maximum):
    row = lstat_row(path)
    if row is None or row.st_size > maximum:
        return None
    try:
        with open(path, "rb") as handle:
            raw = handle.read(maximum + 1)
    except OSError:
        return None
    if len(raw) > maximum:
        return None
    return raw


def run(command, timeout=20):
    try:
        return subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=MINIMAL_ENV,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


task_root_exists = os.path.lexists(TASK_ROOT)
task_root_safe = safe_dir(TASK_ROOT, 0o700)
top_names, top_read_ok = list_names(TASK_ROOT) if task_root_safe else (set(), False)
task_top_level_exact = bool(top_read_ok and top_names == EXPECTED_TOP)

tool_root_safe = safe_dir(TOOL_ROOT, 0o700)
tool_names, tool_read_ok = list_names(TOOL_ROOT) if tool_root_safe else (set(), False)
tool_name_set_exact = bool(tool_read_ok and tool_names == set(EXPECTED_TOOLS))
tool_hash_match_count = 0
tool_metadata_pass_count = 0
if tool_name_set_exact:
    for name, expected_hash in EXPECTED_TOOLS.items():
        path = os.path.join(TOOL_ROOT, name)
        if safe_file(path, 0o600, 1, 65536):
            tool_metadata_pass_count += 1
        if sha256_file(path, 65536) == expected_hash:
            tool_hash_match_count += 1
tool_contract_exact = bool(
    tool_root_safe
    and tool_name_set_exact
    and tool_metadata_pass_count == 2
    and tool_hash_match_count == 2
)

docker_config_safe = safe_dir(DOCKER_CONFIG_ROOT, 0o700)
docker_config_names, docker_config_read_ok = (
    list_names(DOCKER_CONFIG_ROOT) if docker_config_safe else (set(), False)
)
docker_config_exact_empty = bool(docker_config_read_ok and not docker_config_names)

input_root_safe = safe_dir(INPUT_ROOT, 0o700)
input_names, input_read_ok = list_names(INPUT_ROOT) if input_root_safe else (set(), False)
input_name_set_exact = bool(input_read_ok and input_names == set(EXPECTED_INPUTS))
input_metadata_pass_count = 0
if input_name_set_exact:
    for name, expected_size in EXPECTED_INPUTS.items():
        if safe_file(os.path.join(INPUT_ROOT, name), 0o600, expected_size, expected_size):
            input_metadata_pass_count += 1
input_contract_exact = bool(input_root_safe and input_name_set_exact and input_metadata_pass_count == 4)

helper_stdout_path = os.path.join(TASK_ROOT, "helper.stdout")
helper_stderr_path = os.path.join(TASK_ROOT, "helper.stderr")
helper_stdout_metadata_safe = safe_file(helper_stdout_path, 0o600, 0, 65536)
helper_stderr_metadata_safe = safe_file(helper_stderr_path, 0o600, 0, 65536)
helper_stdout = read_limited(helper_stdout_path, 65536) if helper_stdout_metadata_safe else None
helper_stderr = read_limited(helper_stderr_path, 65536) if helper_stderr_metadata_safe else None
if helper_stdout == SUCCESS_STDOUT:
    helper_class = "ENCRYPTED"
elif helper_stdout == FAILED_STDOUT:
    helper_class = "HELPER_FAILED"
else:
    helper_class = "OTHER"
helper_stdout_bytes = len(helper_stdout) if helper_stdout is not None else -1
helper_stderr_bytes = len(helper_stderr) if helper_stderr is not None else -1
helper_stderr_empty = helper_stderr == b""

output_root_safe = safe_dir(OUTPUT_ROOT, 0o700)
output_names, output_read_ok = list_names(OUTPUT_ROOT) if output_root_safe else (set(), False)
output_unexpected_count = len(output_names - EXPECTED_OUTPUTS) if output_read_ok else -1
output_expected_present = output_names & EXPECTED_OUTPUTS if output_read_ok else set()
output_metadata_pass_count = 0
if output_read_ok:
    for name in sorted(output_expected_present):
        path = os.path.join(OUTPUT_ROOT, name)
        if safe_file(path, 0o600, 1, 12288):
            output_metadata_pass_count += 1
output_count = len(output_expected_present)
output_contract_safe = bool(
    output_root_safe
    and output_read_ok
    and output_unexpected_count == 0
    and output_metadata_pass_count == output_count
)

source_paths = (
    "/etc/noteai/ai-worker.env",
    "/etc/noteai/private-storage.env",
)
source_file_count = 0
source_metadata_pass_count = 0
for path in source_paths:
    row = lstat_row(path)
    if row is not None:
        source_file_count += 1
    if safe_file(path, 0o600, 1, 16384):
        source_metadata_pass_count += 1
source_contract_safe = source_file_count == 2 and source_metadata_pass_count == 2

container_query_ok = False
task_container_count = -1
api_container_query_ok = False
api_container_set_exact = False
if docker_config_exact_empty:
    task_completed = run([
        "/usr/bin/docker", "--context=default", "container", "ls", "-a",
        "--filter", "name=^/{}$".format(CONTAINER_NAME), "--format", "{{.ID}}",
    ])
    if task_completed is not None and task_completed.returncode == 0:
        container_query_ok = True
        task_container_count = len([line for line in task_completed.stdout.splitlines() if line])
    api_completed = run([
        "/usr/bin/docker", "--context=default", "ps", "-a", "--format", "{{.Names}}|{{.State}}",
    ])
    if api_completed is not None and api_completed.returncode == 0:
        api_container_query_ok = True
        rows = sorted(line.decode("ascii") for line in api_completed.stdout.splitlines() if line)
        api_container_set_exact = rows == ["noteai-admin-c|running", "noteai-api-c|running"]

ss_path = shutil.which("ss", path=MINIMAL_ENV["PATH"])
database_socket_query_ok = False
database_socket_count = -1
if ss_path:
    ss_completed = run([ss_path, "-Htan"])
    if ss_completed is not None and ss_completed.returncode == 0:
        database_socket_query_ok = True
        database_socket_count = 0
        for raw_line in ss_completed.stdout.splitlines():
            columns = raw_line.decode("utf-8", "replace").split()
            if any(column.endswith(":5432") for column in columns[-2:]):
                database_socket_count += 1

container_blocked = container_query_ok and task_container_count != 0
missing_root = not task_root_exists
unsafe = not all((
    task_root_safe,
    task_top_level_exact,
    tool_contract_exact,
    docker_config_exact_empty,
    input_contract_exact,
    helper_stdout_metadata_safe,
    helper_stderr_metadata_safe,
    output_contract_safe,
    container_query_ok,
    task_container_count == 0,
))

if missing_root:
    status = "MISSING_RECOVERY_ROOT_BLOCKED"
elif container_blocked:
    status = "CONTAINER_RESIDUE_BLOCKED"
elif unsafe:
    status = "UNSAFE_OR_UNEXPECTED_RESIDUE_BLOCKED"
elif helper_class == "ENCRYPTED" and helper_stderr_empty and output_count == 4:
    status = "RECOVERY_READBACK_ELIGIBLE"
elif helper_class == "HELPER_FAILED" and output_count == 0:
    status = "HELPER_FAILED_ZERO_OUTPUT"
elif 1 <= output_count <= 3:
    status = "PARTIAL_OUTPUT_BLOCKED"
elif output_count == 4:
    status = "FOUR_OUTPUT_UNCONFIRMED"
else:
    status = "ZERO_OUTPUT_UNCONFIRMED"

result = {
    "api_container_set_exact": api_container_set_exact,
    "automatic_retry_allowed": False,
    "ciphertext_value_read_count": 0,
    "database_socket_count": database_socket_count,
    "database_socket_query_ok": database_socket_query_ok,
    "docker_config_exact_empty": docker_config_exact_empty,
    "helper_class": helper_class,
    "helper_stderr_bytes": helper_stderr_bytes,
    "helper_stderr_empty": helper_stderr_empty,
    "helper_stdout_bytes": helper_stdout_bytes,
    "host": "API-C",
    "input_file_count": len(input_names) if input_read_ok else -1,
    "input_metadata_pass_count": input_metadata_pass_count,
    "output_file_count": output_count,
    "output_metadata_pass_count": output_metadata_pass_count,
    "output_unexpected_count": output_unexpected_count,
    "source_file_count": source_file_count,
    "source_secret_value_read_count": 0,
    "status": status,
    "task_container_count": task_container_count,
    "task_container_query_ok": container_query_ok,
    "task_root_safe": task_root_safe,
    "task_top_level_exact": task_top_level_exact,
    "tool_file_count": len(tool_names) if tool_read_ok else -1,
    "tool_hash_match_count": tool_hash_match_count,
    "tool_root_safe": tool_root_safe,
    "readback_allowed": status == "RECOVERY_READBACK_ELIGIBLE",
    "worker_stage_allowed": False,
}
print(json.dumps(result, sort_keys=True, separators=(",", ":")))
PY
