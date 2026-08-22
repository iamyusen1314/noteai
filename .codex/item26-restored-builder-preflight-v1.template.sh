#!/usr/bin/env bash
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy NO_PROXY no_proxy
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONINSPECT PYTHONOPTIMIZE
unset DATABASE_URL NOTEAI_SQLITE_PATH PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD PGSERVICE PGSERVICEFILE
unset ALIBABA_CLOUD_ACCESS_KEY_ID ALIBABA_CLOUD_ACCESS_KEY_SECRET ALIBABA_CLOUD_SECURITY_TOKEN
unset ALICLOUD_ACCESS_KEY ALICLOUD_SECRET_KEY ALICLOUD_SECURITY_TOKEN OSS_ACCESS_KEY_ID OSS_ACCESS_KEY_SECRET
unset DOCKER_HOST DOCKER_CONTEXT DOCKER_CONFIG DOCKER_TLS DOCKER_TLS_VERIFY DOCKER_CERT_PATH

if ! command -v python3 >/dev/null 2>&1; then
  printf '%s\n' '{"NOTEAI_ITEM26_RESTORED_BUILDER_PREFLIGHT":"FAIL","application_secret_value_read_count":0,"automatic_retry_allowed":false,"container_start_count":0,"database_connection_count":0,"database_write_count":0,"environment_value_read_count":0,"host_task_write_count":0,"phase":"python","private_key_value_read_count":0,"resource_id_values_emitted":0,"same_invocation_replay_allowed":false,"secret_values_emitted":0}' >&2
  exit 3
fi

exec python3 -I -B - <<'PY'
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import urllib.request

BUILDER_IDENTITY_SHA256 = "@@BUILDER_IDENTITY_SHA256@@"
BUILDER_RAM_ROLE = "noteai-item26-pitr-oss-reader-v1"
PERSISTENT_PARENT = "/var/lib/noteai"
RESTORED_BASE = "/var/lib/noteai/item26-restored-v1"
IMAGE_REF = "noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:407eef2b50b13cefc365f9decd34de39ee0f8e327b7fbfc0eda15fa519ae321b"
IMAGE_CONFIG = "sha256:1f503665de518d871813133335418822e9383544fbfd1cde3e2b66bb51470c95"
RELEASE_COMMIT = "cad5ce35664f617c6e19f90a6159285ddf975594"
CONTAINER_NAMES = (
    "noteai-item26-restored-capture-v1",
    "noteai-item26-restored-capture-successor-v1",
    "noteai-item26-restored-capture-ssl-corrected-v1",
)
DOCKER_CONFIG_ROOT = "/run/noteai-item26-restored-preflight-docker-config-v1"
MIN_MEMORY_KIB = 15 * 1024 * 1024
MIN_FILESYSTEM_BYTES = 100 * 1024 * 1024 * 1024
MIN_AVAILABLE_BYTES = 20 * 1024 * 1024 * 1024
MIN_AVAILABLE_INODES = 100000
HEX64 = re.compile(r"^[0-9a-f]{64}$")
COMMAND_ENV = {
    "DOCKER_CONFIG": DOCKER_CONFIG_ROOT,
    "HOME": "/root",
    "LC_ALL": "C",
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
}


class Failure(Exception):
    def __init__(self, phase, unknown=False):
        Exception.__init__(self, phase)
        self.phase = phase
        self.unknown = unknown


def canonical(value):
    return (json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ) + "\n").encode("ascii")


def common():
    return {
        "application_secret_value_read_count": 0,
        "automatic_retry_allowed": False,
        "container_start_count": 0,
        "database_connection_count": 0,
        "database_write_count": 0,
        "environment_value_read_count": 0,
        "host_task_write_count": 0,
        "private_key_value_read_count": 0,
        "resource_id_values_emitted": 0,
        "same_invocation_replay_allowed": False,
        "secret_values_emitted": 0,
    }


def emit(value, code):
    body = canonical(value)
    if len(body) > 4096:
        os._exit(4)
    descriptor = 1 if code == 0 else 2
    try:
        if os.write(descriptor, body) != len(body):
            os._exit(4)
    except BaseException:
        os._exit(4)
    os._exit(code)


def fixed(state, phase):
    value = common()
    value.update({
        "NOTEAI_ITEM26_RESTORED_BUILDER_PREFLIGHT": state,
        "phase": phase,
    })
    if state == "UNKNOWN":
        value["readback_required"] = True
    return value


def stable_tuple(row):
    return (
        row.st_dev,
        row.st_ino,
        row.st_mode,
        row.st_uid,
        row.st_gid,
        row.st_nlink,
        row.st_size,
        getattr(row, "st_mtime_ns", int(row.st_mtime * 1000000000)),
        getattr(row, "st_ctime_ns", int(row.st_ctime * 1000000000)),
    )


def pin_directory(path, phase, exact_mode=0o700, expected_uid=0, expected_gid=0, observed=None):
    if observed is None:
        try:
            before = os.lstat(path)
        except FileNotFoundError:
            raise Failure(phase)
        except OSError:
            raise Failure(phase + "_runtime", True)
    else:
        before = observed
    if (
        not stat.S_ISDIR(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or before.st_uid != expected_uid
        or before.st_gid != expected_gid
        or (
            stat.S_IMODE(before.st_mode) != exact_mode
            if exact_mode is not None
            else stat.S_IMODE(before.st_mode) & 0o022 != 0
        )
    ):
        raise Failure(phase)
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        opened = os.fstat(fd)
        after = os.lstat(path)
    except OSError:
        if fd is not None:
            os.close(fd)
        raise Failure(phase + "_race", True)
    if stable_tuple(before) != stable_tuple(opened) or stable_tuple(before) != stable_tuple(after):
        os.close(fd)
        raise Failure(phase + "_race", True)
    return {"fd": fd, "path": path, "snapshot": stable_tuple(before)}


def verify_pinned_directory(pinned, phase):
    try:
        opened = os.fstat(pinned["fd"])
        current = os.lstat(pinned["path"])
    except OSError:
        raise Failure(phase + "_race", True)
    if pinned["snapshot"] != stable_tuple(opened) or pinned["snapshot"] != stable_tuple(current):
        raise Failure(phase + "_race", True)


def stable_read_at(pinned, name, size, phase):
    try:
        before = os.stat(name, dir_fd=pinned["fd"], follow_symlinks=False)
    except FileNotFoundError:
        raise Failure(phase)
    except OSError:
        raise Failure(phase + "_runtime", True)
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or before.st_uid != 0
        or before.st_gid != 0
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_nlink != 1
        or before.st_size != size
    ):
        raise Failure(phase)
    fd = None
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=pinned["fd"])
        body = os.read(fd, size + 1)
        opened = os.fstat(fd)
        os.close(fd)
        fd = None
        after = os.stat(name, dir_fd=pinned["fd"], follow_symlinks=False)
    except OSError:
        if fd is not None:
            os.close(fd)
        raise Failure(phase + "_race", True)
    if (
        stable_tuple(before) != stable_tuple(opened)
        or stable_tuple(before) != stable_tuple(after)
        or len(body) != size
    ):
        raise Failure(phase + "_race", True)
    return body


def child_absent(pinned, name, phase):
    try:
        os.stat(name, dir_fd=pinned["fd"], follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError:
        raise Failure(phase + "_runtime", True)
    raise Failure(phase, True)


def optional_directory(path, phase):
    try:
        before = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError:
        raise Failure(phase + "_runtime", True)
    return pin_directory(path, phase, exact_mode=None, observed=before)


def command(args, phase, timeout=10, limit=65536):
    try:
        process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=COMMAND_ENV,
            close_fds=True,
            start_new_session=True,
        )
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except BaseException:
            pass
        try:
            process.communicate(timeout=2)
        except BaseException:
            pass
        raise Failure(phase + "_runtime", True)
    except BaseException:
        raise Failure(phase + "_runtime", True)
    if len(stdout) + len(stderr) > limit:
        raise Failure(phase + "_runtime", True)
    return process.returncode, stdout, stderr


def identity_exact():
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, file_pointer, code, message, headers, new_url):
            raise RuntimeError("redirect")

    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        request = urllib.request.Request(
            "http://100.100.100.200/latest/api/token",
            method="PUT",
            headers={"X-aliyun-ecs-metadata-token-ttl-seconds": "60"},
        )
        with opener.open(request, timeout=3) as response:
            token = response.read(512).decode("ascii").strip()
        if not token or len(token) > 256:
            raise RuntimeError("token")
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
                raise RuntimeError("metadata")
            values.append(body.decode("ascii").strip())
    except BaseException:
        raise Failure("identity_runtime", True)
    roles = [row for row in values[1].splitlines() if row]
    if (
        re.fullmatch(r"i-[a-z0-9]+", values[0]) is None
        or roles != [BUILDER_RAM_ROLE]
    ):
        raise Failure("identity")
    body = json.dumps(
        {"instance_id": values[0], "ram_role": roles[0]},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    if hashlib.sha256(body).hexdigest() != BUILDER_IDENTITY_SHA256:
        raise Failure("identity")


def path_absent(path, phase):
    try:
        os.lstat(path)
    except FileNotFoundError:
        return
    except OSError:
        raise Failure(phase + "_runtime", True)
    raise Failure(phase)


def docker_command(*arguments):
    return ["/usr/bin/docker", "--config", DOCKER_CONFIG_ROOT, *arguments]


def docker_config_exact():
    path_absent(DOCKER_CONFIG_ROOT, "docker_config")
    returncode, stdout, stderr = command(
        docker_command("context", "show"),
        "docker",
        limit=4096,
    )
    if returncode != 0 or stderr:
        raise Failure("docker_runtime", True)
    if stdout != b"default\n":
        raise Failure("docker_config")
    path_absent(DOCKER_CONFIG_ROOT, "docker_config")


def service_state(arguments, expected_state):
    returncode, stdout, stderr = command(arguments, "docker", limit=4096)
    state = stdout.strip()
    if returncode == 0 and not stderr:
        if state == expected_state:
            return
        raise Failure("docker_service")
    if stderr:
        raise Failure("docker_runtime", True)
    known = {
        b"active", b"activating", b"deactivating", b"failed", b"inactive",
        b"maintenance", b"enabled", b"disabled", b"masked", b"static",
        b"indirect", b"generated", b"transient", b"not-found",
    }
    if state in known:
        raise Failure("docker_service")
    raise Failure("docker_runtime", True)


def docker_exact():
    for arguments, expected in (
        (["/usr/bin/systemctl", "is-active", "docker"], b"active"),
        (["/usr/bin/systemctl", "is-enabled", "docker"], b"enabled"),
    ):
        service_state(arguments, expected)
    docker_config_exact()
    returncode, _stdout, version_stderr = command(
        docker_command("--context=default", "version"),
        "docker",
    )
    if returncode != 0 or version_stderr:
        raise Failure("docker_runtime", True)
    returncode, stdout, stderr = command(
        docker_command(
            "--context=default",
            "image",
            "inspect",
            IMAGE_REF,
            "--format",
            '{{.Id}}|{{.Os}}|{{.Architecture}}|{{index .Config.Labels "org.opencontainers.image.revision"}}',
        ),
        "image",
        limit=4096,
    )
    expected = (IMAGE_CONFIG + "|linux|amd64|" + RELEASE_COMMIT + "\n").encode("ascii")
    if returncode != 0 or stderr:
        raise Failure("image_runtime", True)
    if stdout != expected:
        raise Failure("image")
    for container_name in CONTAINER_NAMES:
        returncode, stdout, stderr = command(
            docker_command(
                "--context=default",
                "container",
                "ls",
                "-a",
                "--filter",
                "name=^/" + container_name + "$",
                "--format",
                "{{.Names}}",
            ),
            "docker",
            limit=4096,
        )
        if returncode != 0 or stderr:
            raise Failure("docker_runtime", True)
        if stdout:
            raise Failure("container_present", True)
    path_absent(DOCKER_CONFIG_ROOT, "docker_config")


def tcp_5432_zero():
    returncode, stdout, stderr = command(
        ["/usr/sbin/ss", "-Htan", "state", "established"],
        "socket",
        limit=131072,
    )
    if returncode != 0 or stderr:
        raise Failure("socket_runtime", True)
    count = 0
    for raw in stdout.splitlines():
        fields = raw.split()
        if len(fields) < 4:
            raise Failure("socket_runtime", True)
        if any(endpoint.rsplit(b":", 1)[-1] == b"5432" for endpoint in fields[-2:]):
            count += 1
    if count != 0:
        raise Failure("db_socket")


def capacity_exact(persistent):
    if os.cpu_count() != 4:
        raise Failure("capacity")
    try:
        body = open("/proc/meminfo", "rb").read(65537)
    except OSError:
        raise Failure("capacity_runtime", True)
    if len(body) > 65536:
        raise Failure("capacity_runtime", True)
    match = re.search(br"^MemTotal:\s+([0-9]+)\s+kB$", body, re.MULTILINE)
    if match is None or int(match.group(1)) < MIN_MEMORY_KIB:
        raise Failure("capacity")
    try:
        row = os.fstatvfs(persistent["fd"])
    except OSError:
        raise Failure("capacity_runtime", True)
    total = row.f_frsize * row.f_blocks
    available = row.f_frsize * row.f_bavail
    if total < MIN_FILESYSTEM_BYTES or available < MIN_AVAILABLE_BYTES or row.f_favail < MIN_AVAILABLE_INODES:
        raise Failure("capacity")


def restored_base_absent(persistent):
    child_absent(persistent, os.path.basename(RESTORED_BASE), "restored_base_present")


def required_tool(path):
    try:
        row = os.lstat(path)
    except FileNotFoundError:
        raise Failure("tool")
    except OSError:
        raise Failure("tool_runtime", True)
    if not stat.S_ISREG(row.st_mode) or stat.S_ISLNK(row.st_mode) or not os.access(path, os.X_OK):
        raise Failure("tool")


try:
    if os.geteuid() != 0 or os.getegid() != 0:
        raise Failure("root")
    if HEX64.fullmatch(BUILDER_IDENTITY_SHA256) is None:
        raise Failure("binding")
    for path in ("/usr/bin/docker", "/usr/sbin/ss", "/usr/bin/systemctl"):
        required_tool(path)
    persistent = pin_directory(PERSISTENT_PARENT, "persistent_parent")
    restored_base_absent(persistent)
    identity_exact()
    capacity_exact(persistent)
    docker_exact()
    tcp_5432_zero()
    restored_base_absent(persistent)
    verify_pinned_directory(persistent, "persistent_parent")
    result = common()
    result.update({
        "NOTEAI_ITEM26_RESTORED_BUILDER_PREFLIGHT": "PASS",
        "builder_capacity_exact": True,
        "docker_config_exact": True,
        "docker_service_exact": True,
        "established_tcp_5432_count": 0,
        "fixed_ram_role_exact": True,
        "identity_exact": True,
        "image_exact": True,
        "persistent_parent_exact": True,
        "restored_base_absent": True,
        "schema_version": 1,
        "task_container_count": 0,
    })
    emit(result, 0)
except Failure as exc:
    emit(fixed("UNKNOWN" if exc.unknown else "FAIL", exc.phase), 4 if exc.unknown else 3)
except BaseException:
    emit(fixed("UNKNOWN", "unexpected"), 4)
PY
