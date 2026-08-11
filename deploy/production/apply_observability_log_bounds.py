#!/usr/bin/env python3
"""Apply the accepted Item25 bounded-log contract to one production host."""

import hashlib
import http.client
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request


TASK_ID = "PROD-FIRST-LAUNCH-OBSERVABILITY-001"
TASK_ROOT = "/run/noteai-item25-observability-v1"
DOCKER_CONFIG = TASK_ROOT + "/docker-config"
SYSTEMD_ROOT = "/etc/systemd/system"
JOURNALD_ROOT = "/etc/systemd/journald.conf.d"
JOURNALD_PATH = JOURNALD_ROOT + "/30-noteai-runtime-log-bounds.conf"
JOURNALD_CONTENT = (
    b"[Journal]\n"
    b"Storage=persistent\n"
    b"SystemMaxUse=256M\n"
    b"RuntimeMaxUse=64M\n"
    b"MaxRetentionSec=7day\n"
    b"MaxFileSec=1day\n"
)
LOG_FLAGS = (
    b"--log-driver=local --log-opt=max-size=10m --log-opt=max-file=2 "
)
INSERTION_POINT = b"ExecStart=/usr/bin/docker run "
REPLACEMENT = INSERTION_POINT + LOG_FLAGS
PATH_VALUE = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
COMMAND_ENV = {"PATH": PATH_VALUE, "LC_ALL": "C"}


HOSTS = {
    "i-wz9j36od3nf2b1uw7bvg": {
        "label": "API-C",
        "units": (
            (
                "noteai-api.service",
                "364a5e539b14a83d24ef9c1726ee3e14b988c398206b2711db5613b9e0a1fc77",
                "active",
                "noteai-api-c",
            ),
            (
                "noteai-admin.service",
                "101f8814d89736c2aa920f3107916b9b1ab53cabffdde0d69908285fd6d1fe8a",
                "active",
                "noteai-admin-c",
            ),
            (
                "noteai-ai-dispatcher.service",
                "18336a06fb850a38077840b899f6146b67a039d5bb524c45c810b0f48b433bfd",
                "suspended",
                "noteai-ai-dispatcher",
            ),
            (
                "noteai-payment.service",
                "3f7b7594b26862c5a760a6015fe491f215ee4a59abe1452ea3141c12bb2367a2",
                "suspended",
                "noteai-payment",
            ),
        ),
        "active_containers": (("noteai-api-c", 8000, "noteai-api"), ("noteai-admin-c", 8001, "noteai-admin")),
    },
    "i-wz9bgztwf1tiakww2ops": {
        "label": "API-F",
        "units": (
            (
                "noteai-api.service",
                "23750496447ad6e31ad27b1461f1164bbf14c28296a0ac28be7e5886eb4e65c1",
                "active",
                "noteai-api-f",
            ),
            (
                "noteai-xhs-trends.service",
                "3557cfa0e15cd12d676ef652f8436a6d37ee9bb9490b6f90a886a75e7571fcd6",
                "suspended",
                "noteai-xhs-trends",
            ),
            (
                "noteai-xhs-tracking.service",
                "20997e7661381e767aaa6ad1b3dda9b04fc4d9ed5317f44108973a5d0d1e52f7",
                "suspended",
                "noteai-xhs-tracking",
            ),
        ),
        "active_containers": (("noteai-api-f", 8000, "noteai-api"),),
    },
    "i-wz98zwcdtcmxzmmoso3w": {
        "label": "Worker-C",
        "units": (
            (
                "noteai-ai-worker.service",
                "ac58cd4e324150668e9cb6a0f05f7165ce78a36240bd50db6207dd20eaef9411",
                "suspended",
                "noteai-ai-worker",
            ),
        ),
        "active_containers": (),
    },
    "i-wz93qgvlu1bllpjcfwfj": {
        "label": "Worker-F",
        "units": (
            (
                "noteai-ai-worker.service",
                "ac58cd4e324150668e9cb6a0f05f7165ce78a36240bd50db6207dd20eaef9411",
                "suspended",
                "noteai-ai-worker",
            ),
        ),
        "active_containers": (),
    },
}


class Item25Error(RuntimeError):
    def __init__(self, code):
        RuntimeError.__init__(self, code)
        self.code = code


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Item25Error("metadata_redirect")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def command(args, code, timeout=30, input_bytes=None):
    try:
        result = subprocess.run(
            args,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=COMMAND_ENV,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise Item25Error(code)
    if result.returncode != 0:
        raise Item25Error(code)
    return result.stdout


def command_state(args, allowed, code, timeout=20):
    try:
        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=COMMAND_ENV,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise Item25Error(code)
    if result.returncode not in allowed:
        raise Item25Error(code)
    return result.returncode, result.stdout.strip()


def docker(args, code, timeout=30):
    return command(
        [
            "/usr/bin/env",
            "DOCKER_CONFIG=" + DOCKER_CONFIG,
            "/usr/bin/docker",
            "--context=default",
        ]
        + list(args),
        code,
        timeout=timeout,
    )


def imds(path, method="GET", headers=None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(
        "http://100.100.100.200" + path,
        headers=headers or {},
        method=method,
    )
    try:
        with opener.open(request, timeout=3) as response:
            if response.status != 200:
                raise Item25Error("host_identity")
            value = response.read(4097)
    except (OSError, urllib.error.URLError, Item25Error):
        raise Item25Error("host_identity")
    if len(value) > 4096:
        raise Item25Error("host_identity")
    return value.decode("ascii").strip()


def instance_identity():
    token = imds(
        "/latest/api/token",
        method="PUT",
        headers={"X-aliyun-ecs-metadata-token-ttl-seconds": "60"},
    )
    if not token or len(token) > 256:
        raise Item25Error("host_identity")
    instance_id = imds(
        "/latest/meta-data/instance-id",
        headers={"X-aliyun-ecs-metadata-token": token},
    )
    if instance_id not in HOSTS:
        raise Item25Error("host_identity")
    return instance_id, HOSTS[instance_id]


def safe_dir(path, mode):
    try:
        info = os.lstat(path)
    except OSError:
        raise Item25Error("unsafe_directory")
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != 0
        or info.st_gid != 0
        or stat.S_IMODE(info.st_mode) != mode
    ):
        raise Item25Error("unsafe_directory")


def safe_persistent_journal():
    try:
        info = os.lstat("/var/log/journal")
    except OSError:
        raise Item25Error("persistent_journal")
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != 0
        or stat.S_IMODE(info.st_mode) not in (0o755, 0o2755)
    ):
        raise Item25Error("persistent_journal")


def read_safe_file(path, expected_hash=None, expected_mode=0o644):
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
            raise Item25Error("unit_metadata")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise Item25Error("unit_race")
            data = b""
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                data += chunk
                if len(data) > 131072:
                    raise Item25Error("unit_size")
        finally:
            os.close(fd)
    except Item25Error:
        raise
    except OSError:
        raise Item25Error("unit_read")
    if expected_hash is not None and sha256(data) != expected_hash:
        raise Item25Error("unit_hash")
    return data


def write_new_file(path, data, mode):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, mode)
        try:
            offset = 0
            while offset < len(data):
                written = os.write(fd, data[offset:])
                if written <= 0:
                    raise Item25Error("file_write")
                offset += written
            os.fsync(fd)
            os.fchmod(fd, mode)
            os.fchown(fd, 0, 0)
        finally:
            os.close(fd)
    except Item25Error:
        raise
    except OSError:
        raise Item25Error("file_write")


def atomic_replace(path, data):
    parent = os.path.dirname(path)
    temporary = parent + "/.noteai-item25-" + os.path.basename(path) + ".tmp"
    if os.path.lexists(temporary):
        raise Item25Error("temporary_path_exists")
    write_new_file(temporary, data, 0o644)
    try:
        os.replace(temporary, path)
        directory_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError:
        raise Item25Error("file_replace")


def unit_state(unit, expected):
    raw = command(
        [
            "/usr/bin/systemctl",
            "show",
            unit,
            "--property=ActiveState",
            "--property=SubState",
            "--property=Result",
            "--property=NRestarts",
            "--property=LoadState",
            "--property=FragmentPath",
            "--property=DropInPaths",
            "--no-pager",
        ],
        "unit_active_state",
    )
    state = {}
    for line in raw.decode("ascii").splitlines():
        if "=" not in line:
            raise Item25Error("unit_active_state")
        key, value = line.split("=", 1)
        state[key] = value
    if set(state) != {
        "ActiveState",
        "SubState",
        "Result",
        "NRestarts",
        "LoadState",
        "FragmentPath",
        "DropInPaths",
    }:
        raise Item25Error("unit_active_state")
    common_state = {
        "LoadState": "loaded",
        "FragmentPath": SYSTEMD_ROOT + "/" + unit,
        "DropInPaths": "",
    }
    enabled_rc, enabled_out = command_state(
        ["/usr/bin/systemctl", "is-enabled", unit],
        (0, 1),
        "unit_enabled_state",
    )
    if expected == "active":
        if state != {
            "ActiveState": "active",
            "SubState": "running",
            "Result": "success",
            "NRestarts": "0",
            **common_state,
        } or enabled_rc != 0 or enabled_out != b"enabled":
            raise Item25Error("active_unit_state")
    else:
        if state != {
            "ActiveState": "inactive",
            "SubState": "dead",
            "Result": "success",
            "NRestarts": "0",
            **common_state,
        } or enabled_rc != 1 or enabled_out != b"disabled":
            raise Item25Error("suspended_unit_state")


def container_ids(name):
    raw = docker(
        ["container", "ls", "-aq", "--filter", "name=^/" + name + "$"],
        "container_query",
    )
    return [item for item in raw.decode("ascii").splitlines() if item]


def inspect_value(name, template):
    return docker(
        ["container", "inspect", "--format", template, name],
        "container_inspect",
    ).decode("utf-8").strip()


def safe_container_fingerprint(name):
    if len(container_ids(name)) != 1:
        raise Item25Error("active_container_count")
    values = {
        "id": inspect_value(name, "{{.Id}}"),
        "image_id": inspect_value(name, "{{.Image}}"),
        "config_image": inspect_value(name, "{{.Config.Image}}"),
        "running": inspect_value(name, "{{.State.Running}}"),
        "started_at": inspect_value(name, "{{.State.StartedAt}}"),
        "restart_count": inspect_value(name, "{{.RestartCount}}"),
        "user": inspect_value(name, "{{.Config.User}}"),
        "readonly": inspect_value(name, "{{.HostConfig.ReadonlyRootfs}}"),
        "network": inspect_value(name, "{{.HostConfig.NetworkMode}}"),
        "ipc": inspect_value(name, "{{.HostConfig.IpcMode}}"),
        "memory": inspect_value(name, "{{.HostConfig.Memory}}"),
        "nanocpus": inspect_value(name, "{{.HostConfig.NanoCpus}}"),
        "pids": inspect_value(name, "{{.HostConfig.PidsLimit}}"),
        "cap_drop": inspect_value(name, "{{json .HostConfig.CapDrop}}"),
        "security_opt": inspect_value(name, "{{json .HostConfig.SecurityOpt}}"),
        "ports": inspect_value(name, "{{json .HostConfig.PortBindings}}"),
    }
    if values["running"] != "true":
        raise Item25Error("active_container_state")
    return values


def stable_container_contract(fingerprint):
    return {
        key: value
        for key, value in fingerprint.items()
        if key not in ("id", "started_at", "restart_count")
    }


def log_config(name):
    try:
        value = json.loads(inspect_value(name, "{{json .HostConfig.LogConfig}}"))
    except (TypeError, ValueError):
        raise Item25Error("log_config")
    if not isinstance(value, dict):
        raise Item25Error("log_config")
    return value


def require_local_log_config(name):
    value = log_config(name)
    if value.get("Type") != "local" or value.get("Config") != {
        "max-file": "2",
        "max-size": "10m",
    }:
        raise Item25Error("log_config")


def health(port, service, endpoint):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("GET", "/health/" + endpoint)
        response = connection.getresponse()
        body = response.read(4097)
        if response.status != 200 or len(body) > 4096:
            raise Item25Error("health")
    except (OSError, http.client.HTTPException):
        raise Item25Error("health")
    finally:
        connection.close()
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise Item25Error("health")
    if payload.get("service") != service:
        raise Item25Error("health")
    if endpoint == "live":
        if payload.get("status") != "ok":
            raise Item25Error("health")
    else:
        expected_checks = (
            {"database", "model"}
            if service == "noteai-api"
            else {"admin_credentials", "database"}
        )
        checks = payload.get("checks")
        if (
            payload.get("status") != "ready"
            or not isinstance(checks, dict)
            or set(checks) != expected_checks
            or not all(
                isinstance(checks[name], dict) and checks[name].get("ok") is True
                for name in expected_checks
            )
        ):
            raise Item25Error("health")


def health_rounds(active_containers):
    requests = 0
    database_probes = 0
    for _round in (1, 2, 3):
        for _name, port, service in active_containers:
            health(port, service, "live")
            health(port, service, "ready")
            requests += 2
            database_probes += 1
    return requests, database_probes


def verify_suspended_units(units):
    for unit, _old_hash, expected, container in units:
        unit_state(unit, expected)
        if expected == "suspended" and container_ids(container):
            raise Item25Error("suspended_container_present")


def verify_acceptance_residue():
    for unit in (
        "noteai-ai-dispatcher-acceptance.service",
        "noteai-ai-worker-acceptance.service",
    ):
        for root in ("/etc/systemd/system", "/run/systemd/system"):
            if os.path.lexists(root + "/" + unit):
                raise Item25Error("acceptance_unit_residue")
    for container in (
        "noteai-ai-dispatcher-acceptance",
        "noteai-ai-worker-acceptance",
    ):
        if container_ids(container):
            raise Item25Error("acceptance_container_residue")


def verify_resume_state(host, units):
    if host["label"] not in ("Worker-C", "Worker-F") or len(units) != 1:
        raise Item25Error("resume_scope")
    safe_dir(TASK_ROOT, 0o700)
    safe_dir(DOCKER_CONFIG, 0o700)
    if os.listdir(DOCKER_CONFIG):
        raise Item25Error("resume_docker_config")
    safe_dir(JOURNALD_ROOT, 0o700)
    if os.listdir(JOURNALD_ROOT) or os.path.lexists(JOURNALD_PATH):
        raise Item25Error("resume_journald_state")
    expected_entries = {"docker-config"}
    resumed = {}
    for unit, old_hash, _expected, _container in units:
        expected_entries.update((unit, unit + ".before"))
        before = read_safe_file(
            TASK_ROOT + "/" + unit + ".before",
            old_hash,
            expected_mode=0o600,
        )
        candidate = read_safe_file(
            TASK_ROOT + "/" + unit,
            expected_mode=0o600,
        )
        installed = read_safe_file(SYSTEMD_ROOT + "/" + unit)
        if (
            before.count(INSERTION_POINT) != 1
            or LOG_FLAGS in before
            or candidate != before.replace(INSERTION_POINT, REPLACEMENT, 1)
            or installed != candidate
            or installed.count(LOG_FLAGS) != 1
        ):
            raise Item25Error("resume_unit_state")
        resumed[unit] = installed
    if set(os.listdir(TASK_ROOT)) != expected_entries:
        raise Item25Error("resume_task_inventory")
    return resumed


def wait_for_admin_ready(before):
    request_count = 0
    database_probe_count = 0
    for _attempt in range(60):
        try:
            current = safe_container_fingerprint("noteai-admin-c")
        except Item25Error:
            time.sleep(2)
            continue
        if current["id"] == before["id"]:
            time.sleep(2)
            continue
        if stable_container_contract(current) != stable_container_contract(before):
            raise Item25Error("admin_fingerprint_drift")
        if current["started_at"] == before["started_at"]:
            raise Item25Error("admin_fingerprint_drift")
        if current["restart_count"] != "0":
            raise Item25Error("admin_restart_count")
        try:
            require_local_log_config("noteai-admin-c")
            request_count += 1
            health(8001, "noteai-admin", "live")
            request_count += 1
            database_probe_count += 1
            health(8001, "noteai-admin", "ready")
        except Item25Error:
            time.sleep(2)
            continue
        return current, request_count, database_probe_count
    raise Item25Error("admin_readiness_timeout")


def main():
    global mutation_started, task_created
    if os.geteuid() != 0:
        raise Item25Error("euid")
    os.umask(0o077)
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_CONFIG",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
        "ALIBABA_CLOUD_ACCESS_KEY_ID",
        "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
        "ALIBABA_CLOUD_SECURITY_TOKEN",
    ):
        os.environ.pop(name, None)
    for path in (
        "/usr/bin/docker",
        "/usr/bin/env",
        "/usr/bin/systemctl",
        "/usr/bin/systemd-analyze",
    ):
        if not os.path.isfile(path) or not os.access(path, os.X_OK):
            raise Item25Error("required_tool")
    safe_dir("/run", 0o755)
    safe_dir(SYSTEMD_ROOT, 0o755)
    safe_persistent_journal()
    instance_id, host = instance_identity()
    units = host["units"]
    active_containers = host["active_containers"]
    if os.path.lexists(JOURNALD_PATH):
        raise Item25Error("preexisting_path")
    resumed = {}
    if os.path.lexists(TASK_ROOT):
        mutation_started = True
        resumed = verify_resume_state(host, units)
    else:
        os.mkdir(TASK_ROOT, 0o700)
        task_created = True
        os.mkdir(DOCKER_CONFIG, 0o700)
    verify_suspended_units(units)
    verify_acceptance_residue()
    if command(["/usr/bin/systemctl", "is-active", "--quiet", "systemd-journald.service"], "journald_state") != b"":
        raise Item25Error("journald_state")

    before_fingerprints = {}
    for name, _port, _service in active_containers:
        before_fingerprints[name] = safe_container_fingerprint(name)
        if name.startswith("noteai-api-"):
            require_local_log_config(name)
        elif log_config(name).get("Type") == "local":
            raise Item25Error("admin_already_changed")
    pre_health, pre_db = health_rounds(active_containers)

    rendered = {}
    if not resumed:
        for unit, old_hash, _expected, _container in units:
            source = read_safe_file(SYSTEMD_ROOT + "/" + unit, old_hash)
            if source.count(INSERTION_POINT) != 1 or LOG_FLAGS in source:
                raise Item25Error("unit_transform")
            candidate = source.replace(INSERTION_POINT, REPLACEMENT, 1)
            if candidate.count(LOG_FLAGS) != 1:
                raise Item25Error("unit_transform")
            write_new_file(TASK_ROOT + "/" + unit + ".before", source, 0o600)
            write_new_file(TASK_ROOT + "/" + unit, candidate, 0o600)
            rendered[unit] = candidate
            command(
                ["/usr/bin/systemd-analyze", "verify", TASK_ROOT + "/" + unit],
                "unit_verify",
                timeout=30,
            )

        mutation_started = True
        for unit, candidate in rendered.items():
            atomic_replace(SYSTEMD_ROOT + "/" + unit, candidate)
            if read_safe_file(SYSTEMD_ROOT + "/" + unit) != candidate:
                raise Item25Error("unit_readback")

    if not os.path.lexists(JOURNALD_ROOT):
        os.mkdir(JOURNALD_ROOT, 0o755)
        os.chown(JOURNALD_ROOT, 0, 0)
        os.chmod(JOURNALD_ROOT, 0o755)
    elif resumed:
        safe_dir(JOURNALD_ROOT, 0o700)
        if os.listdir(JOURNALD_ROOT):
            raise Item25Error("resume_journald_state")
        os.chmod(JOURNALD_ROOT, 0o755)
    safe_dir(JOURNALD_ROOT, 0o755)
    atomic_replace(JOURNALD_PATH, JOURNALD_CONTENT)
    if read_safe_file(JOURNALD_PATH) != JOURNALD_CONTENT:
        raise Item25Error("journald_readback")

    command(["/usr/bin/systemctl", "daemon-reload"], "daemon_reload", timeout=30)
    command(
        ["/usr/bin/systemctl", "restart", "systemd-journald.service"],
        "journald_restart",
        timeout=30,
    )
    command(
        ["/usr/bin/systemctl", "is-active", "--quiet", "systemd-journald.service"],
        "journald_state",
    )
    effective = command(
        ["/usr/bin/systemd-analyze", "cat-config", "systemd/journald.conf"],
        "journald_effective",
    )
    effective_values = {}
    for raw_line in effective.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(b"#") or b"=" not in line:
            continue
        key, value = line.split(b"=", 1)
        effective_values[key] = value
    for line in JOURNALD_CONTENT.splitlines()[1:]:
        key, value = line.split(b"=", 1)
        if effective_values.get(key) != value:
            raise Item25Error("journald_effective")

    admin_restarts = 0
    admin_readiness_requests = 0
    admin_readiness_database_probes = 0
    admin_ready_fingerprint = None
    if host["label"] == "API-C":
        command(
            ["/usr/bin/systemctl", "restart", "noteai-admin.service"],
            "admin_restart",
            timeout=150,
        )
        admin_restarts = 1
        (
            admin_ready_fingerprint,
            admin_readiness_requests,
            admin_readiness_database_probes,
        ) = wait_for_admin_ready(before_fingerprints["noteai-admin-c"])

    verify_suspended_units(units)
    verify_acceptance_residue()
    post_fingerprints = {}
    for name, _port, _service in active_containers:
        post_fingerprints[name] = safe_container_fingerprint(name)
        require_local_log_config(name)
        if name.startswith("noteai-api-") and post_fingerprints[name] != before_fingerprints[name]:
            raise Item25Error("api_fingerprint_drift")
        if name == "noteai-admin-c":
            if (
                post_fingerprints[name] != admin_ready_fingerprint
                or stable_container_contract(post_fingerprints[name])
                != stable_container_contract(before_fingerprints[name])
                or post_fingerprints[name]["id"] == before_fingerprints[name]["id"]
                or post_fingerprints[name]["started_at"]
                == before_fingerprints[name]["started_at"]
                or post_fingerprints[name]["restart_count"] != "0"
            ):
                raise Item25Error("admin_fingerprint_drift")
    post_health, post_db = health_rounds(active_containers)

    accepted_units = dict(resumed)
    accepted_units.update(rendered)
    updated_hashes = {
        unit: sha256(candidate) for unit, candidate in sorted(accepted_units.items())
    }
    safe_dir(TASK_ROOT, 0o700)
    shutil.rmtree(TASK_ROOT)
    if os.path.lexists(TASK_ROOT):
        raise Item25Error("task_cleanup")
    return {
        "status": "PASS",
        "task_id": TASK_ID,
        "host": host["label"],
        "unit_updates": len(rendered),
        "resumed_unit_updates": len(resumed),
        "updated_unit_sha256": updated_hashes,
        "docker_log_driver": "local",
        "docker_max_size": "10m",
        "docker_max_file": 2,
        "journald_restart_count": 1,
        "admin_restart_count": admin_restarts,
        "api_restart_count": 0,
        "application_container_start_count": admin_restarts,
        "admin_readiness_health_requests": admin_readiness_requests,
        "pre_health_requests": pre_health,
        "post_health_requests": post_health,
        "database_health_probe_count": (
            pre_db + post_db + admin_readiness_database_probes
        ),
        "suspended_unit_start_count": 0,
        "acceptance_unit_residue": 0,
        "acceptance_container_residue": 0,
        "metadata_identity_read_count": 2,
        "provider_control_plane_mutation_count": 0,
        "production_database_write_count": 0,
        "task_root_residue": 0,
        "automatic_retry_allowed": False,
    }


mutation_started = False
task_created = False
if sys.argv[1:] == ["--offline-self-test"]:
    fixture = b"ExecStart=/usr/bin/docker run --pull=never --rm image\n"
    transformed = fixture.replace(INSERTION_POINT, REPLACEMENT, 1)
    if (
        fixture.count(INSERTION_POINT) != 1
        or transformed.count(LOG_FLAGS) != 1
        or len(HOSTS) != 4
        or sum(len(item["units"]) for item in HOSTS.values()) != 9
        or sum(len(item["active_containers"]) for item in HOSTS.values()) != 3
        or sha256(JOURNALD_CONTENT)
        != "b703a523ce01cfea84a843f526b98b6fa0f39f4f91043cd5dabb20646130065b"
    ):
        raise SystemExit(1)
    print("NOTEAI_ITEM25_LOG_BOUNDS_OFFLINE_SELF_TEST=PASS")
    raise SystemExit(0)
if sys.argv[1:]:
    raise SystemExit(2)
try:
    result = main()
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
except Exception as exc:
    failure_code = exc.code if isinstance(exc, Item25Error) else "unexpected"
    cleanup = "UNKNOWN"
    if not mutation_started and task_created:
        try:
            safe_dir(TASK_ROOT, 0o700)
            shutil.rmtree(TASK_ROOT)
            cleanup = "VERIFIED_ZERO" if not os.path.lexists(TASK_ROOT) else "UNKNOWN"
        except Exception:
            cleanup = "UNKNOWN"
    elif not mutation_started and not os.path.lexists(TASK_ROOT):
        cleanup = "NOT_NEEDED"
    state = "UNKNOWN" if mutation_started or cleanup == "UNKNOWN" else "FAIL"
    print(
        json.dumps(
            {
                "status": state,
                "task_id": TASK_ID,
                "code": failure_code,
                "cleanup": cleanup,
                "mutation_started": mutation_started,
                "automatic_retry_allowed": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        file=sys.stderr,
    )
    raise SystemExit(4 if state == "UNKNOWN" else 3)
