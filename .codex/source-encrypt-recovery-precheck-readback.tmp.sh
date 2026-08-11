#!/usr/bin/env bash
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
unset DOCKER_HOST DOCKER_CONTEXT DOCKER_CONFIG DOCKER_TLS_VERIFY DOCKER_CERT_PATH
unset PYTHONHOME PYTHONPATH PYTHONSTARTUP PYTHONUSERBASE PYTHONWARNINGS PYTHONINSPECT

python3 -I -B - <<'PY'
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
IMAGE_REF = "noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:407eef2b50b13cefc365f9decd34de39ee0f8e327b7fbfc0eda15fa519ae321b"
IMAGE_CONFIG = "sha256:1f503665de518d871813133335418822e9383544fbfd1cde3e2b66bb51470c95"
C17 = "cad5ce35664f617c6e19f90a6159285ddf975594"
FIXED_ERROR = b"timeout: failed to run command 'docker_task': No such file or directory\n"
EXPECTED_TOP = {"docker-config", "helper.stderr", "helper.stdout", "input", "output"}
EXPECTED_INPUTS = {
    "worker-c-public.pem": 625,
    "worker-c-public.sha256": 65,
    "worker-f-public.pem": 625,
    "worker-f-public.sha256": 65,
}
EXPECTED_PUBLIC_HASHES = {
    "worker-c": "bf55278e59bc9911ab77a51c59f117e3afc575fd2c941c32d4bf2186fa8f94e0",
    "worker-f": "53abc24853f96a2882d756632d2f6781c211bbc3966a652d1cff50d090858863",
}
EXPECTED_TOOLS = {
    "production_secret_envelope.py": "b6a67fab3fd66f8c378716935b105ac1fbe83c54190eb57baf1b1c3d6b7e2fbf",
    "source-driver.py": "ff9bdcfa6b8979848ff35e7d8c7c9c05450d9573d21eb220fbcc367d9ce1c3d2",
}
ENV = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LC_ALL": "C",
    "DOCKER_CONFIG": DOCKER_CONFIG_ROOT,
}


def lstat_row(path):
    try:
        return os.lstat(path)
    except OSError:
        return None


def safe_dir(path):
    row = lstat_row(path)
    return bool(
        row is not None
        and stat.S_ISDIR(row.st_mode)
        and not stat.S_ISLNK(row.st_mode)
        and row.st_uid == 0 and row.st_gid == 0
        and stat.S_IMODE(row.st_mode) == 0o700
    )


def safe_file(path, expected_size=None, maximum=None):
    row = lstat_row(path)
    if row is None:
        return False
    size_ok = expected_size is None or row.st_size == expected_size
    if maximum is not None:
        size_ok = size_ok and 0 < row.st_size <= maximum
    return bool(
        stat.S_ISREG(row.st_mode)
        and not stat.S_ISLNK(row.st_mode)
        and row.st_uid == 0 and row.st_gid == 0
        and stat.S_IMODE(row.st_mode) == 0o600
        and row.st_nlink == 1
        and size_ok
    )


def names(path):
    try:
        return set(os.listdir(path))
    except OSError:
        return None


def read_limited(path, maximum, expected_size=None):
    row = lstat_row(path)
    if not bool(
        row is not None
        and stat.S_ISREG(row.st_mode)
        and not stat.S_ISLNK(row.st_mode)
        and row.st_uid == 0 and row.st_gid == 0
        and stat.S_IMODE(row.st_mode) == 0o600
        and row.st_nlink == 1
        and row.st_size <= maximum
        and (expected_size is None or row.st_size == expected_size)
    ):
        return None
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = None
    try:
        descriptor = os.open(path, flags)
        current = os.fstat(descriptor)
        if not bool(
            current.st_dev == row.st_dev and current.st_ino == row.st_ino
            and stat.S_ISREG(current.st_mode)
            and current.st_uid == 0 and current.st_gid == 0
            and stat.S_IMODE(current.st_mode) == 0o600
            and current.st_nlink == 1
            and current.st_size == row.st_size
        ):
            return None
        chunks = []
        total = 0
        while total <= maximum:
            chunk = os.read(descriptor, min(65536, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        raw = b"".join(chunks)
    except OSError:
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(raw) != row.st_size or len(raw) > maximum:
        return None
    return raw


def sha256_file(path, maximum):
    raw = read_limited(path, maximum)
    return hashlib.sha256(raw).hexdigest() if raw is not None else None


def run(command, timeout=20):
    try:
        return subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=ENV,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


checks = []
checks.append(("task_root", safe_dir(TASK_ROOT)))
checks.append(("task_top_level", names(TASK_ROOT) == EXPECTED_TOP))
checks.append(("docker_config_root", safe_dir(DOCKER_CONFIG_ROOT)))
checks.append(("input_root", safe_dir(INPUT_ROOT)))
checks.append(("output_root", safe_dir(OUTPUT_ROOT)))
checks.append(("docker_config_empty", names(DOCKER_CONFIG_ROOT) == set()))
checks.append(("input_names", names(INPUT_ROOT) == set(EXPECTED_INPUTS)))
checks.append(("output_empty", names(OUTPUT_ROOT) == set()))
input_metadata_count = sum(
    1 for name, size in EXPECTED_INPUTS.items()
    if safe_file(os.path.join(INPUT_ROOT, name), expected_size=size)
)
checks.append(("input_metadata", input_metadata_count == 4))
helper_stdout = read_limited(os.path.join(TASK_ROOT, "helper.stdout"), 0, expected_size=0)
helper_stderr = read_limited(os.path.join(TASK_ROOT, "helper.stderr"), 72, expected_size=72)
checks.append(("helper_stdout_empty", helper_stdout == b""))
checks.append(("helper_stderr_fixed", helper_stderr == FIXED_ERROR))
checks.append(("helper_stderr_bytes", helper_stderr is not None and len(helper_stderr) == 72))

tool_names = names(TOOL_ROOT)
checks.append(("tool_root", safe_dir(TOOL_ROOT)))
checks.append(("tool_names", tool_names == set(EXPECTED_TOOLS)))
tool_metadata_count = sum(
    1 for name in EXPECTED_TOOLS
    if safe_file(os.path.join(TOOL_ROOT, name), maximum=65536)
)
tool_hash_count = sum(
    1 for name, expected in EXPECTED_TOOLS.items()
    if sha256_file(os.path.join(TOOL_ROOT, name), 65536) == expected
)
checks.append(("tool_metadata", tool_metadata_count == 2))
checks.append(("tool_hash", tool_hash_count == 2))

public_hash_file_count = 0
for host, expected in EXPECTED_PUBLIC_HASHES.items():
    raw = read_limited(
        os.path.join(INPUT_ROOT, host + "-public.sha256"),
        65,
        expected_size=65,
    )
    if raw == (expected + "\n").encode("ascii"):
        public_hash_file_count += 1
checks.append(("public_hash_files", public_hash_file_count == 2))

openssl_path = shutil.which("openssl", path=ENV["PATH"])
public_der_hash_count = 0
if openssl_path:
    for host, expected in EXPECTED_PUBLIC_HASHES.items():
        public_path = os.path.join(INPUT_ROOT, host + "-public.pem")
        if not safe_file(public_path, expected_size=625):
            continue
        completed = run([
            openssl_path,
            "pkey",
            "-pubin",
            "-in",
            public_path,
            "-outform",
            "DER",
        ])
        if (
            completed is not None
            and completed.returncode == 0
            and len(completed.stdout) == 422
            and hashlib.sha256(completed.stdout).hexdigest() == expected
        ):
            public_der_hash_count += 1
checks.append(("openssl_available", openssl_path is not None))
checks.append(("public_der_hash", public_der_hash_count == 2))

source_metadata_count = sum(
    1 for path in ("/etc/noteai/ai-worker.env", "/etc/noteai/private-storage.env")
    if safe_file(path, maximum=16384)
)
checks.append(("source_metadata", source_metadata_count == 2))

active = run(["/usr/bin/systemctl", "is-active", "docker"])
enabled = run(["/usr/bin/systemctl", "is-enabled", "docker"])
checks.append(("docker_active", active is not None and active.returncode == 0 and active.stdout == b"active\n"))
checks.append(("docker_enabled", enabled is not None and enabled.returncode == 0 and enabled.stdout == b"enabled\n"))

context = run([
    "/usr/bin/docker",
    "--context=default",
    "context",
    "inspect",
    "default",
    "--format",
    '{{(index .Endpoints "docker").Host}}',
])
checks.append((
    "docker_context",
    context is not None and context.returncode == 0 and context.stdout == b"unix:///var/run/docker.sock\n",
))
container = run([
    "/usr/bin/docker",
    "--context=default",
    "container",
    "ls",
    "-a",
    "--filter",
    "name=^/{}$".format(CONTAINER_NAME),
    "--format",
    "{{.ID}}",
])
checks.append(("task_container_absent", container is not None and container.returncode == 0 and container.stdout == b""))

c17_exact = False
image = run([
    "/usr/bin/docker",
    "--context=default",
    "image",
    "inspect",
    IMAGE_REF,
])
if image is not None and image.returncode == 0:
    try:
        rows = json.loads(image.stdout.decode("utf-8"))
        row = rows[0] if isinstance(rows, list) and len(rows) == 1 else {}
        cfg = row.get("Config") or {}
        labels = cfg.get("Labels") or {}
        rootfs = row.get("RootFS") or {}
        c17_exact = bool(
            row.get("Id") == IMAGE_CONFIG
            and row.get("Os") == "linux"
            and row.get("Architecture") == "amd64"
            and (row.get("RepoDigests") or []).count(IMAGE_REF) == 1
            and isinstance(row.get("Size"), int) and row.get("Size") > 0
            and isinstance(rootfs.get("Layers"), list) and len(rootfs["Layers"]) > 0
            and cfg.get("User") == "noteai"
            and cfg.get("Entrypoint") == ["/app/scripts/docker_entrypoint.sh"]
            and cfg.get("Cmd") == ["python", "durable_ai_worker.py", "--once"]
            and cfg.get("WorkingDir") == "/app/model"
            and (cfg.get("Healthcheck") or {}).get("Test") == ["NONE"]
            and labels.get("org.opencontainers.image.revision") == C17
            and labels.get("com.noteai.runtime.role") == "ai-worker"
            and (cfg.get("Env") or []).count("NOTEAI_DURABLE_AI_SUSPENDED=1") == 1
            and (cfg.get("Env") or []).count("NOTEAI_RUNTIME_ROLE=ai-worker") == 1
        )
    except (IndexError, TypeError, ValueError, UnicodeError):
        c17_exact = False
checks.append(("c17_exact", c17_exact))

first_failed = next((name for name, passed in checks if not passed), None)
result = {
    "automatic_retry_allowed": False,
    "c17_exact": c17_exact,
    "check_count": len(checks),
    "ciphertext_value_read_count": 0,
    "failed_check_count": sum(1 for _name, passed in checks if not passed),
    "first_failed_predicate": first_failed,
    "host": "API-C",
    "input_metadata_pass_count": input_metadata_count,
    "original_recovery_command_rerun_allowed": False,
    "public_der_hash_match_count": public_der_hash_count,
    "public_hash_file_match_count": public_hash_file_count,
    "source_metadata_pass_count": source_metadata_count,
    "source_secret_value_read_count": 0,
    "status": "RECOVERY_PRECHECK_DIAGNOSED" if first_failed else "RECOVERY_PRECHECK_ALL_PASS",
    "tool_hash_match_count": tool_hash_count,
    "worker_stage_allowed": False,
}
print(json.dumps(result, sort_keys=True, separators=(",", ":")))
PY
