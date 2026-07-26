#!/usr/bin/env python3
"""Collect a Secret-free, read-only host fragment for production Gate 0.

Run as root on exactly API-C or API-F. The collector reads metadata, parses
environment key names without emitting values, calls only loopback health
routes and performs no registry request or service/database mutation.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import pwd
import re
import shutil
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable

try:
    from tools.production_readonly_preflight_gate import (
        EXPECTED_DIGESTS,
        EXPECTED_ENV_ROLES,
        EXPECTED_HOST_ROLES,
        EXPECTED_PORTS,
    )
except ModuleNotFoundError:
    from production_readonly_preflight_gate import (  # type: ignore[no-redef]
        EXPECTED_DIGESTS,
        EXPECTED_ENV_ROLES,
        EXPECTED_HOST_ROLES,
        EXPECTED_PORTS,
    )


PRIVATE_REGISTRY = (
    "noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com"
)
EXPECTED_CONTAINERS = {
    "API-C": {
        "api": {
            "name": "noteai-api-c",
            "unit": "noteai-api.service",
            "port": 8000,
        },
        "admin": {
            "name": "noteai-admin-c",
            "unit": "noteai-admin.service",
            "port": 8001,
        },
    },
    "API-F": {
        "api": {
            "name": "noteai-api-f",
            "unit": "noteai-api.service",
            "port": 8000,
        },
    },
}
ENV_PATHS = {
    "API-C": {
        "api": Path("/etc/noteai/api.env"),
        "admin": Path("/etc/noteai/admin.env"),
    },
    "API-F": {
        "api": Path("/etc/noteai/api.env"),
        "xhs": Path("/etc/noteai/xhs.env"),
    },
}
ALLOWED_SECRET_KEYS = {
    "api": {
        "DATABASE_URL",
        "ANTHROPIC_API_KEY",
        "MOONSHOT_API_KEY",
        "AMAP_WEB_KEY",
        "BAIDU_MAP_AK",
        "TENCENT_MAP_KEY",
        "SERPAPI_API_KEY",
        "BING_SEARCH_API_KEY",
        "GOOGLE_API_KEY",
        "MEITUAN_AI_HUB_TOKEN",
        "MEITUAN_OPEN_TOKEN",
        "MEITUAN_SIGN_KEY",
        "MEITUAN_APP_AUTH_TOKEN",
        "MEITUAN_OPEN_APP_KEY",
        "MEITUAN_OPEN_APP_SECRET",
        "MEITUAN_OPEN_SIGN",
        "MEITUAN_OPEN_AES_KEY",
        "NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET",
        "NOTEAI_CLAUDE_GATEWAY_PREVIOUS_HMAC_SECRET",
        "NOTEAI_MARKET_TIMING_REFRESH_TOKEN",
        "NOTEAI_AUTHORIZED_TREND_TOKEN",
        "NOTEAI_AI_API_STORE_ACCESS_KEY_ID",
        "NOTEAI_AI_API_STORE_SECRET_ACCESS_KEY",
        "NOTEAI_AI_API_STORE_SESSION_TOKEN",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "NOTEAI_ADAPAY_API_KEY",
        "NOTEAI_ADAPAY_MERCHANT_PRIVATE_KEY",
        "NOTEAI_ADAPAY_PUBLIC_KEY",
    },
    "admin": {"DATABASE_URL", "ADMIN_PASSWORD"},
    "xhs": {"DATABASE_URL", "NOTEAI_XHS_COOKIES_JSON"},
}
_ENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SECRET_NAME = re.compile(
    r"(?:PASSWORD|SECRET|TOKEN|COOKIE|CREDENTIALS?|PRIVATE_KEY|API_KEY|WEB_KEY|"
    r"ACCESS_KEY_ID|SECRET_ACCESS_KEY|SIGN_KEY|AES_KEY|AK)$"
)
_MIGRATION_LOG = re.compile(
    r"\b(?:migration|schema_migrations|render_predeploy)\b", re.IGNORECASE
)
_PROVIDER_LOG = re.compile(
    r"\b(?:anthropic|moonshot|kimi|amap|meituan|xiaohongshu|"
    r"provider[_ -]?call)\b",
    re.IGNORECASE,
)
_SECRET_LOG = re.compile(
    r"\b(?:password|secret|token|cookie|api[_-]?key)\s*[=:]\s*\S+",
    re.IGNORECASE,
)
_RFC1918_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
_PRIVATE_SERVICE_NETWORKS = _RFC1918_NETWORKS + (
    ipaddress.ip_network("100.64.0.0/10"),
)
_TEMP_PROCESS_PATTERNS = (
    "market_timing_worker.py",
    "crawler_worker.py",
    "durable_ai_worker.py",
    "payment_adapter_runtime.py",
    r"noteai-\S*(canary|diag|snapshot|retry)",
)


class CollectionError(RuntimeError):
    """Raised when a required read-only observation cannot be proven."""


class CommandRunner:
    def run(self, *args: str, timeout: int = 15) -> str:
        try:
            result = subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, "LC_ALL": "C", "LANG": "C"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CollectionError(f"command unavailable: {args[0]}") from exc
        if result.returncode != 0:
            raise CollectionError(
                f"command failed: {args[0]} exit={result.returncode}"
            )
        return result.stdout.strip()

    def combined(self, *args: str, timeout: int = 15) -> str:
        try:
            result = subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, "LC_ALL": "C", "LANG": "C"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CollectionError(f"command unavailable: {args[0]}") from exc
        if result.returncode != 0:
            raise CollectionError(
                f"command failed: {args[0]} exit={result.returncode}"
            )
        return "\n".join(
            part.strip() for part in (result.stdout, result.stderr) if part.strip()
        )

    def optional(self, *args: str, timeout: int = 15) -> str | None:
        try:
            return self.run(*args, timeout=timeout)
        except CollectionError:
            return None


def _secret_like(name: str) -> bool:
    return name == "DATABASE_URL" or bool(_SECRET_NAME.search(name))


def _env_file_evidence(role: str, path: Path) -> dict[str, Any]:
    try:
        path_stat = path.lstat()
    except OSError as exc:
        raise CollectionError(f"{role}: env file missing") from exc
    regular = stat.S_ISREG(path_stat.st_mode) and not stat.S_ISLNK(path_stat.st_mode)
    try:
        owner = pwd.getpwuid(path_stat.st_uid).pw_name
    except KeyError:
        owner = "unknown"
    mode = f"{stat.S_IMODE(path_stat.st_mode):04o}"
    names: list[str] = []
    duplicate_count = 0
    rejected_count = 0
    seen: set[str] = set()
    try:
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                stripped = raw_line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if stripped.startswith("export "):
                    stripped = stripped[7:].lstrip()
                if "=" not in stripped:
                    rejected_count += 1
                    continue
                name = stripped.split("=", 1)[0].strip()
                if not _ENV_KEY.fullmatch(name):
                    rejected_count += 1
                    continue
                if name in seen:
                    duplicate_count += 1
                seen.add(name)
                names.append(name)
                if _secret_like(name) and name not in ALLOWED_SECRET_KEYS[role]:
                    rejected_count += 1
    except (OSError, UnicodeError) as exc:
        raise CollectionError(f"{role}: cannot parse env key names") from exc
    return {
        "role": role,
        "file_label": f"{role}.env",
        "regular": regular,
        "owner": owner,
        "mode": mode,
        "key_count": len(names),
        "duplicate_key_count": duplicate_count,
        "rejected_key_count": rejected_count,
    }


def _docker_value(runner: CommandRunner, name: str, template: str) -> str:
    return runner.run("docker", "inspect", "--format", template, name)


def _health(port: int, route: str) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{route}",
        method="GET",
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read(65536)
            status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read(65536)
        status = exc.code
    except (OSError, urllib.error.URLError) as exc:
        raise CollectionError(f"loopback health unavailable on port {port}") from exc
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CollectionError(f"health JSON invalid on port {port}") from exc
    if not isinstance(payload, dict):
        raise CollectionError(f"health shape invalid on port {port}")
    return status, payload


def _readiness_core_checks(payload: dict[str, Any]) -> list[str]:
    checks = payload.get("checks")
    if not isinstance(checks, dict):
        return []
    return sorted(
        key
        for key, value in checks.items()
        if isinstance(key, str)
        and isinstance(value, dict)
        and value.get("ok") is True
    )


def _listener(runner: CommandRunner, name: str, port: int) -> tuple[str, int]:
    raw = runner.run("docker", "port", name, f"{port}/tcp")
    endpoints = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(endpoints) != 1:
        return "", len(endpoints)
    endpoint = endpoints[0]
    public = 0 if endpoint.startswith("127.0.0.1:") else 1
    return endpoint, public


def _log_counts(runner: CommandRunner, name: str) -> tuple[int, int, int]:
    logs = runner.combined("docker", "logs", "--tail", "200", name)
    return (
        len(_MIGRATION_LOG.findall(logs)),
        len(_PROVIDER_LOG.findall(logs)),
        len(_SECRET_LOG.findall(logs)),
    )


def _collect_container(
    runner: CommandRunner, host: str, role: str, spec: dict[str, Any]
) -> dict[str, Any]:
    name = str(spec["name"])
    unit = str(spec["unit"])
    port = int(spec["port"])
    image_ref = _docker_value(runner, name, "{{.Config.Image}}")
    digest_match = re.search(r"@sha256:([0-9a-f]{64})$", image_ref)
    image_digest_hex = digest_match.group(1) if digest_match else ""
    local_image_id = runner.run(
        "docker", "image", "inspect", "--format", "{{.Id}}", image_ref
    )
    local_image_id_hex = local_image_id.removeprefix("sha256:")
    revision = _docker_value(
        runner, name, "{{index .Config.Labels \"org.opencontainers.image.revision\"}}"
    )
    runtime_role = _docker_value(
        runner, name, "{{index .Config.Labels \"com.noteai.runtime.role\"}}"
    )
    if runtime_role != role:
        raise CollectionError(f"{host}.{role}: runtime role mismatch")
    running = _docker_value(runner, name, "{{.State.Running}}") == "true"
    user = _docker_value(runner, name, "{{.Config.User}}")
    read_only = _docker_value(runner, name, "{{.HostConfig.ReadonlyRootfs}}") == "true"
    privileged = _docker_value(runner, name, "{{.HostConfig.Privileged}}") == "true"
    cap_drop_raw = _docker_value(runner, name, "{{json .HostConfig.CapDrop}}")
    security_opt_raw = _docker_value(runner, name, "{{json .HostConfig.SecurityOpt}}")
    try:
        cap_drop = json.loads(cap_drop_raw) or []
        security_opt = json.loads(security_opt_raw) or []
    except json.JSONDecodeError as exc:
        raise CollectionError(f"{host}.{role}: Docker security shape") from exc
    restart_policy = _docker_value(runner, name, "{{.HostConfig.RestartPolicy.Name}}")
    mounts_raw = _docker_value(
        runner, name, "{{range .Mounts}}{{println .Destination}}{{end}}"
    )
    mounts = sorted(line for line in mounts_raw.splitlines() if line)
    listener, public_listener_count = _listener(runner, name, port)
    live_status, _ = _health(port, "/health/live")
    ready_status, ready_payload = _health(port, "/health/ready")
    migration_hits, provider_hits, secret_hits = _log_counts(runner, name)
    unit_path = Path("/etc/systemd/system") / unit
    try:
        unit_sha256 = hashlib.sha256(unit_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise CollectionError(f"{host}.{role}: unit file missing") from exc
    return {
        "role": role,
        "running": running,
        "managed": True,
        "image_digest_hex": image_digest_hex,
        "local_image_id_hex": local_image_id_hex,
        "oci_revision": revision,
        "unit_sha256": unit_sha256,
        "unit_active": runner.run("systemctl", "is-active", unit) == "active",
        "unit_enabled": runner.run("systemctl", "is-enabled", unit) == "enabled",
        "unit_result": runner.run(
            "systemctl", "show", unit, "--property=Result", "--value"
        ),
        "user": user,
        "read_only_root": read_only,
        "privileged": privileged,
        "cap_drop_all": set(cap_drop) == {"ALL"},
        "no_new_privileges": any(
            option.split(":", 1)[0] == "no-new-privileges"
            for option in security_opt
        ),
        "restart_policy": restart_policy,
        "mount_destinations": mounts,
        "loopback_listener": listener,
        "public_listener_count": public_listener_count,
        "live_http_status": live_status,
        "ready_http_status": ready_status,
        "ready_core_checks": _readiness_core_checks(ready_payload),
        "log_migration_hit_count": migration_hits,
        "log_provider_hit_count": provider_hits,
        "log_secret_pattern_hit_count": secret_hits,
    }


def _private_network_only(runner: CommandRunner) -> bool:
    raw = runner.run("ip", "-o", "-4", "addr", "show", "scope", "global")
    addresses: list[ipaddress.IPv4Address] = []
    for token in raw.split():
        if "/" not in token:
            continue
        try:
            interface = ipaddress.ip_interface(token)
        except ValueError:
            continue
        if isinstance(interface.ip, ipaddress.IPv4Address):
            addresses.append(interface.ip)
    return bool(addresses) and all(
        any(address in network for network in _RFC1918_NETWORKS)
        for address in addresses
    )


def _private_acr_route(runner: CommandRunner) -> tuple[bool, bool]:
    raw = runner.run("getent", "ahostsv4", PRIVATE_REGISTRY)
    addresses: list[ipaddress.IPv4Address] = []
    for line in raw.splitlines():
        first = line.split(maxsplit=1)[0] if line.split() else ""
        try:
            address = ipaddress.ip_address(first)
        except ValueError:
            continue
        if isinstance(address, ipaddress.IPv4Address):
            addresses.append(address)
    dns_private = bool(addresses) and all(
        any(address in network for network in _PRIVATE_SERVICE_NETWORKS)
        for address in addresses
    )
    route_ok = False
    if dns_private:
        route_ok = runner.optional("ip", "route", "get", str(addresses[0])) is not None
    return dns_private, route_ok


def _docker_auth_count(paths: Iterable[Path]) -> int:
    count = 0
    for path in paths:
        if not path.is_file() or path.is_symlink():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return count + 1
        if not isinstance(payload, dict):
            return count + 1
        for key in ("auths", "credHelpers"):
            entries = payload.get(key)
            if isinstance(entries, dict) and PRIVATE_REGISTRY in entries:
                count += 1
        if payload.get("credsStore"):
            count += 1
    return count


def _unexpected_listener_count(runner: CommandRunner, host: str) -> int:
    raw = runner.run("ss", "-H", "-lnt")
    expected = set(EXPECTED_PORTS[host].values())
    observed: set[str] = set()
    for line in raw.splitlines():
        for token in line.split():
            match = re.search(r"((?:127\.0\.0\.1|0\.0\.0\.0|\[::\])):(8000|8001|8002|18000)$", token)
            if match:
                observed.add(f"{match.group(1)}:{match.group(2)}")
    return len(observed - expected) + len(expected - observed)


def collect_host(host: str, runner: CommandRunner | None = None) -> dict[str, Any]:
    if host not in EXPECTED_HOST_ROLES:
        raise CollectionError("host label must be API-C or API-F")
    if os.geteuid() != 0:
        raise CollectionError("collector must run as root")
    command_runner = runner or CommandRunner()
    architecture = command_runner.run("uname", "-m")
    docker_version = command_runner.run(
        "docker", "version", "--format", "{{.Server.Version}}"
    )
    compose_version = command_runner.optional(
        "docker", "compose", "version", "--short"
    ) or "absent"
    docker_root = Path(
        command_runner.run("docker", "info", "--format", "{{.DockerRootDir}}")
    )
    try:
        disk_free_gib = round(shutil.disk_usage(docker_root).free / (1024**3), 2)
        meminfo = Path("/proc/meminfo").read_text(encoding="utf-8")
    except OSError as exc:
        raise CollectionError("host capacity metadata unavailable") from exc
    memory_match = re.search(r"^MemAvailable:\s+(\d+)\s+kB$", meminfo, re.MULTILINE)
    if not memory_match:
        raise CollectionError("MemAvailable is missing")
    memory_available_mib = int(memory_match.group(1)) // 1024
    private_acr_dns, private_acr_route = _private_acr_route(command_runner)
    containers = [
        _collect_container(command_runner, host, role, spec)
        for role, spec in EXPECTED_CONTAINERS[host].items()
    ]
    all_noteai_names = {
        line
        for line in command_runner.run(
            "docker", "ps", "-a", "--format", "{{.Names}}"
        ).splitlines()
        if line.startswith("noteai-")
    }
    expected_names = {
        str(spec["name"]) for spec in EXPECTED_CONTAINERS[host].values()
    }
    mutable_refs = sum(
        container["image_digest_hex"] != EXPECTED_DIGESTS[container["role"]]
        for container in containers
    )
    temporary_process_count = 0
    for pattern in _TEMP_PROCESS_PATTERNS:
        count = command_runner.optional("pgrep", "-fc", pattern)
        if count is not None and count.isdigit():
            temporary_process_count += int(count)
    return {
        "label": host,
        "instance_state": "Running",
        "system_status": (
            "OK"
            if command_runner.run("systemctl", "is-system-running") == "running"
            else "NOT_OK"
        ),
        "private_only": _private_network_only(command_runner),
        "architecture": architecture,
        "docker_version": docker_version,
        "compose_version": compose_version,
        "docker_free_gib": disk_free_gib,
        "memory_available_mib": memory_available_mib,
        "private_acr_dns": private_acr_dns,
        "private_acr_route": private_acr_route,
        "containers": containers,
        "env_files": [
            _env_file_evidence(role, ENV_PATHS[host][role])
            for role in EXPECTED_ENV_ROLES[host]
        ],
        "unexpected_container_count": len(all_noteai_names - expected_names),
        "unexpected_listener_count": _unexpected_listener_count(
            command_runner, host
        ),
        "mutable_image_ref_count": mutable_refs,
        "temporary_auth_entry_count": _docker_auth_count(
            (
                Path("/root/.docker/config.json"),
                Path("/home/ecs-assist-user/.docker/config.json"),
            )
        ),
        "temporary_process_count": temporary_process_count,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect a sanitized read-only API-C/API-F Gate 0 fragment."
    )
    parser.add_argument("--host-label", choices=tuple(EXPECTED_HOST_ROLES), required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        evidence = collect_host(args.host_label)
    except CollectionError as exc:
        print(
            json.dumps(
                {
                    "collector_status": "invalid",
                    "error_code": re.sub(
                        r"[^a-z0-9]+", "_", str(exc).lower()
                    ).strip("_")[:80],
                },
                sort_keys=True,
            )
        )
        return 1
    json.dump(evidence, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
