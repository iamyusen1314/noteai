#!/usr/bin/env bash
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
unset DOCKER_HOST DOCKER_CONTEXT DOCKER_TLS_VERIFY DOCKER_CERT_PATH
unset PYTHONHOME PYTHONPATH PYTHONSTARTUP PYTHONUSERBASE PYTHONWARNINGS PYTHONINSPECT

python3 -I -B - <<'PY'
import json
import os
import stat
import subprocess

task_root = "/run/noteai-item21-worker-secret-v1"
stage_root = "/etc/noteai/.worker-secret-install-v1"
env_root = "/etc/noteai"
finals = (
    "/etc/noteai/ai-worker.env",
    "/etc/noteai/private-storage.env",
)
container_name = "noteai-item21-worker-secret-install-worker-c"
docker_config = os.path.join(task_root, "docker-config")


def lexists(path):
    return os.path.lexists(path)


def safe_dir(path, mode):
    try:
        row = os.lstat(path)
    except OSError:
        return False
    return bool(
        stat.S_ISDIR(row.st_mode)
        and not stat.S_ISLNK(row.st_mode)
        and row.st_uid == 0 and row.st_gid == 0
        and stat.S_IMODE(row.st_mode) == mode
    )


def names(path):
    try:
        return os.listdir(path)
    except OSError:
        return None


env = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LC_ALL": "C",
    "DOCKER_CONFIG": docker_config,
}
try:
    completed = subprocess.run(
        [
            "/usr/bin/docker", "--context=default", "container", "ls", "-a",
            "--filter", "name=^/{}$".format(container_name), "--format", "{{.ID}}",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        timeout=20,
    )
except (OSError, subprocess.TimeoutExpired):
    completed = None

container_query_ok = bool(completed is not None and completed.returncode == 0)
container_ids = []
if container_query_ok:
    container_ids = [row for row in completed.stdout.decode("ascii").splitlines() if row]

task_exists = lexists(task_root)
stage_exists = lexists(stage_root)
env_exists = lexists(env_root)
final_count = sum(1 for path in finals if lexists(path))
task_names = names(task_root) if task_exists else []
env_names = names(env_root) if env_exists else []

known_rolled_back = bool(
    container_query_ok
    and len(container_ids) == 0
    and final_count == 0
    and not stage_exists
    and not task_exists
    and (
        not env_exists
        or (safe_dir(env_root, 0o755) and env_names == [])
    )
)
material_retained = bool(
    container_query_ok
    and len(container_ids) == 0
    and final_count == 0
    and not stage_exists
    and safe_dir(task_root, 0o700)
    and isinstance(task_names, list)
)

if known_rolled_back:
    status = "KNOWN_PRE_DOCKER_ROLLED_BACK_KEY_ROOT_REMOVED"
elif material_retained:
    status = "RECOVERY_MATERIAL_RETAINED"
else:
    status = "FILE_STATE_UNKNOWN"

print(json.dumps({
    "automatic_retry_allowed": False,
    "ciphertext_value_read_count": 0,
    "container_query_ok": container_query_ok,
    "final_file_count": final_count,
    "host": "Worker-C",
    "install_command_rerun_allowed": False,
    "source_secret_value_read_count": 0,
    "stage_root_exists": stage_exists,
    "status": status,
    "task_container_count": len(container_ids),
    "task_root_entry_count": len(task_names) if isinstance(task_names, list) else -1,
    "task_root_exists": task_exists,
    "worker_f_allowed": False,
    "worker_rekey_required": known_rolled_back,
}, sort_keys=True, separators=(",", ":")))
PY
