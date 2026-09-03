#!/usr/bin/env python3
"""Render and atomically install the fixed C17 Durable AI systemd units.

This host-local tool never pulls an image, starts a unit, enables a unit, or
connects to a database.  Formal units are installed under ``/etc`` and remain
inactive/disabled.  One-shot acceptance units live under ``/run`` and are
removed after the bounded acceptance.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import stat
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import parse_qsl, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from scripts.validate_production_env_files import (
        EnvFileValidationError,
        validate_role_env_file,
    )
except ModuleNotFoundError:  # pragma: no cover - host-local package layout
    from validate_production_env_files import (  # type: ignore[no-redef]
        EnvFileValidationError,
        validate_role_env_file,
    )

TEMPLATE_ROOT = ROOT / "deploy" / "production" / "systemd"
FORMAL_ROOT = Path("/etc/systemd/system")
ACCEPTANCE_ROOT = Path("/run/systemd/system")
LOCK_PATH = Path("/run/lock/noteai-durable-ai-units.lock")
TASK_ID = "PROD-FIRST-LAUNCH-DURABLE-AI-UNITS-001"

C17_COMMIT = "cad5ce35664f617c6e19f90a6159285ddf975594"
IMAGE_MANIFEST = (
    "sha256:407eef2b50b13cefc365f9decd34de39ee0f8e327b7fbfc0eda15fa519ae321b"
)
IMAGE_CONFIG = (
    "sha256:1f503665de518d871813133335418822e9383544fbfd1cde3e2b66bb51470c95"
)
IMAGE_REF = (
    "noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/"
    f"noteai/app@{IMAGE_MANIFEST}"
)

IMAGE_PLACEHOLDER = "@@NOTEAI_AI_WORKER_IMAGE@@"
OPERATION_PLACEHOLDER = "@@NOTEAI_DURABLE_AI_ACCEPTANCE_OPERATION_ID@@"
ACTION_PLACEHOLDER = "@@NOTEAI_DURABLE_AI_ACCEPTANCE_ACTION@@"

HOST_COMPONENT = {
    "API-C": "dispatcher",
    "Worker-C": "worker",
    "Worker-F": "worker",
}
HOST_ACCEPTANCE_ACTION = {
    "Worker-C": "hold_after_payload",
    "Worker-F": "fail_before_provider",
}
TEMPLATE_SHA256 = {
    "noteai-ai-dispatcher.service.template": (
        "54faf30f67022ccab1e5cd2395ca17c1792a417c2f84f3cca920c1dbe2b7f5b7"
    ),
    "noteai-ai-worker.service.template": (
        "bac4b119e6cec1f16004c82f82cadcb8485619cf7cda7cc226cb0aeb9a84f922"
    ),
    "noteai-ai-dispatcher-acceptance.service.template": (
        "b0cffda85f25a53987d6ca80ca386db7b7b63987ec1442454a3f2478bab38dff"
    ),
    "noteai-ai-worker-acceptance.service.template": (
        "fab43abe159b291cc3fbeb54b18fbd01686badb792153fdddf35f68b83d704fc"
    ),
}

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
DOCKER_COMMAND = ("/usr/bin/docker", "--context=default")
DATABASE_QUERY_KEYS = frozenset(
    {
        "sslmode",
        "connect_timeout",
        "target_session_attrs",
        "channel_binding",
        "keepalives",
        "keepalives_idle",
        "keepalives_interval",
        "keepalives_count",
        "tcp_user_timeout",
    }
)
STORAGE_KEYS = frozenset(
    {
        "NOTEAI_PRIVATE_STORAGE_BACKEND",
        "NOTEAI_OSS_PRIVATE_BUCKET",
        "NOTEAI_OSS_REGION",
        "NOTEAI_OSS_ENDPOINT",
        "NOTEAI_OSS_RAM_ROLE",
        "NOTEAI_PRIVATE_STORAGE_KEY_EPOCH",
        "NOTEAI_OSS_KEY_PREFIX",
    }
)


class DurableAiUnitError(RuntimeError):
    """A fixed, Secret-free unit operation failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _canonical_operation_id(value: str | None) -> str:
    raw = str(value or "")
    try:
        normalized = str(uuid.UUID(raw))
    except (AttributeError, ValueError) as exc:
        raise DurableAiUnitError("operation_id_shape") from exc
    if raw != normalized:
        raise DurableAiUnitError("operation_id_shape")
    return raw


def _template_name(host_label: str, tier: str) -> str:
    try:
        component = HOST_COMPONENT[host_label]
    except KeyError as exc:
        raise DurableAiUnitError("host_label") from exc
    suffix = "-acceptance" if tier == "acceptance" else ""
    return f"noteai-ai-{component}{suffix}.service.template"


def _unit_name(host_label: str, tier: str) -> str:
    return _template_name(host_label, tier).removesuffix(".template")


def render_unit(
    host_label: str,
    tier: str,
    *,
    operation_id: str | None = None,
) -> str:
    if tier not in {"formal", "acceptance"}:
        raise DurableAiUnitError("tier")
    template_name = _template_name(host_label, tier)
    template_path = TEMPLATE_ROOT / template_name
    try:
        payload = template_path.read_bytes()
    except OSError as exc:
        raise DurableAiUnitError("template_read") from exc
    if hashlib.sha256(payload).hexdigest() != TEMPLATE_SHA256[template_name]:
        raise DurableAiUnitError("template_hash")
    try:
        rendered = payload.decode("utf-8")
    except UnicodeError as exc:
        raise DurableAiUnitError("template_encoding") from exc
    if rendered.count(IMAGE_PLACEHOLDER) != 2:
        raise DurableAiUnitError("image_placeholder")
    rendered = rendered.replace(IMAGE_PLACEHOLDER, IMAGE_REF)
    if tier == "formal":
        if OPERATION_PLACEHOLDER in rendered or ACTION_PLACEHOLDER in rendered:
            raise DurableAiUnitError("formal_placeholder")
    else:
        operation_id = _canonical_operation_id(operation_id)
        if rendered.count(OPERATION_PLACEHOLDER) != 1:
            raise DurableAiUnitError("operation_placeholder")
        rendered = rendered.replace(OPERATION_PLACEHOLDER, operation_id)
        if HOST_COMPONENT[host_label] == "worker":
            expected_action = HOST_ACCEPTANCE_ACTION[host_label]
            if rendered.count(ACTION_PLACEHOLDER) != 1:
                raise DurableAiUnitError("action_placeholder")
            rendered = rendered.replace(ACTION_PLACEHOLDER, expected_action)
        elif ACTION_PLACEHOLDER in rendered:
            raise DurableAiUnitError("dispatcher_action_placeholder")
    if "@@NOTEAI_" in rendered:
        raise DurableAiUnitError("unresolved_placeholder")
    if rendered.count(IMAGE_REF) != 2:
        raise DurableAiUnitError("rendered_image_count")
    return rendered


def _run(
    command: Sequence[str],
    *,
    runner: CommandRunner,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        return runner(
            list(command),
            check=check,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise DurableAiUnitError("command_failed") from exc


def verify_local_image(*, runner: CommandRunner = subprocess.run) -> dict[str, Any]:
    completed = _run(
        [*DOCKER_COMMAND, "image", "inspect", IMAGE_REF],
        runner=runner,
    )
    try:
        rows = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise DurableAiUnitError("image_inspect_json") from exc
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise DurableAiUnitError("image_inspect_shape")
    row = rows[0]
    config = row.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    repo_digests = row.get("RepoDigests")
    if (
        row.get("Id") != IMAGE_CONFIG
        or row.get("Os") != "linux"
        or row.get("Architecture") != "amd64"
        or not isinstance(labels, dict)
        or labels.get("org.opencontainers.image.revision") != C17_COMMIT
        or labels.get("com.noteai.runtime.role") != "ai-worker"
        or not isinstance(repo_digests, list)
        or repo_digests.count(IMAGE_REF) != 1
        or config.get("User") != "noteai"
        or config.get("Entrypoint") != ["/app/scripts/docker_entrypoint.sh"]
        or config.get("Cmd") != ["python", "durable_ai_worker.py", "--once"]
    ):
        raise DurableAiUnitError("image_contract")
    return {
        "image_manifest": IMAGE_MANIFEST,
        "image_config": IMAGE_CONFIG,
        "revision": C17_COMMIT,
    }


def _require_root() -> None:
    if os.geteuid() != 0:
        raise DurableAiUnitError("root_required")


@contextlib.contextmanager
def _exclusive_lock(path: Path):
    try:
        path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        descriptor = os.open(
            path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
    except OSError as exc:
        raise DurableAiUnitError("unit_lock") from exc
    try:
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _write_candidate(
    candidate: Path,
    body: str,
    *,
    expected_uid: int,
) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(candidate, flags, 0o644)
        os.fchmod(descriptor, 0o644)
        if os.geteuid() == 0:
            os.fchown(descriptor, expected_uid, expected_uid)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        candidate.unlink(missing_ok=True)
        raise DurableAiUnitError("unit_write") from exc


def _file_matches(path: Path, body: str, *, expected_uid: int) -> bool:
    try:
        metadata = path.lstat()
        observed = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    return (
        stat.S_ISREG(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and metadata.st_uid == expected_uid
        and metadata.st_gid == (
            expected_uid if expected_uid == 0 else os.getegid()
        )
        and stat.S_IMODE(metadata.st_mode) == 0o644
        and observed == body
    )


def _inactive(
    unit_name: str,
    *,
    runner: CommandRunner,
    allow_unknown: bool = False,
    allow_failed: bool = False,
) -> str:
    completed = _run(
        ["/usr/bin/systemctl", "is-active", unit_name],
        runner=runner,
        check=False,
    )
    allowed = {"inactive"}
    if allow_unknown:
        allowed.add("unknown")
    if allow_failed:
        allowed.add("failed")
    if completed.returncode == 0 or completed.stdout.strip() not in allowed:
        raise DurableAiUnitError("unit_active")
    return completed.stdout.strip()


def _disabled(
    unit_name: str,
    tier: str,
    *,
    runner: CommandRunner,
    allow_not_found: bool = False,
) -> None:
    completed = _run(
        ["/usr/bin/systemctl", "is-enabled", unit_name],
        runner=runner,
        check=False,
    )
    state = completed.stdout.strip()
    accepted = (
        (tier == "acceptance" and completed.returncode == 0 and state == "static")
        or (tier == "formal" and completed.returncode != 0 and state == "disabled")
        or (
            allow_not_found
            and completed.returncode != 0
            and state == "not-found"
        )
    )
    if not accepted:
        raise DurableAiUnitError("unit_enabled")


def _loaded_exact(
    unit_name: str,
    target: Path,
    *,
    runner: CommandRunner,
) -> None:
    completed = _run(
        [
            "/usr/bin/systemctl",
            "show",
            unit_name,
            "--property=LoadState",
            "--property=FragmentPath",
            "--property=DropInPaths",
        ],
        runner=runner,
        check=False,
    )
    observed: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        if "=" in line:
            name, value = line.split("=", 1)
            observed[name] = value
    if (
        completed.returncode
        or observed != {
            "LoadState": "loaded",
            "FragmentPath": str(target),
            "DropInPaths": "",
        }
    ):
        raise DurableAiUnitError("unit_not_loaded")


def _container_absent(host_label: str, tier: str, *, runner: CommandRunner) -> None:
    component = HOST_COMPONENT[host_label]
    suffix = "-acceptance" if tier == "acceptance" else ""
    name = f"noteai-ai-{component}{suffix}"
    completed = _run(
        [
            *DOCKER_COMMAND,
            "container",
            "ls",
            "-a",
            "--filter",
            f"name=^/{name}$",
            "--format",
            "{{.ID}}",
        ],
        runner=runner,
        check=False,
    )
    if completed.returncode != 0:
        raise DurableAiUnitError("container_state_unknown")
    if completed.stdout.strip():
        raise DurableAiUnitError("container_present")


def _private_regular(path: Path, *, expected_uid: int) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise DurableAiUnitError("env_file_missing") from exc
    expected_gid = expected_uid if expected_uid == 0 else os.getegid()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != expected_uid
        or metadata.st_gid != expected_gid
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise DurableAiUnitError("env_file_metadata")


def _env_rows(path: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    names: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise DurableAiUnitError("env_file_read") from exc
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            raise DurableAiUnitError("env_file_contract")
        if "=" not in stripped:
            raise DurableAiUnitError("env_file_contract")
        name, value = stripped.split("=", 1)
        name = name.strip()
        if not name or name in names or any(
            marker in value for marker in ("\x00", "\r", "\n")
        ):
            raise DurableAiUnitError("env_file_contract")
        names.add(name)
        rows.append((name, value))
    return rows


def _database_url_role(database_url: str) -> str:
    try:
        parsed = urlsplit(database_url)
        query = parse_qsl(
            parsed.query,
            keep_blank_values=True,
            strict_parsing=True,
        )
    except (TypeError, ValueError) as exc:
        raise DurableAiUnitError("database_url_contract") from exc
    names: set[str] = set()
    for raw_name, value in query:
        name = raw_name.lower()
        if (
            name not in DATABASE_QUERY_KEYS
            or name in names
            or any(
                marker in raw_name or marker in value
                for marker in ("\x00", "\r", "\n")
            )
        ):
            raise DurableAiUnitError("database_url_contract")
        names.add(name)
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or parsed.password in (None, "")
        or not parsed.hostname
        or parsed.path in {"", "/"}
        or parsed.fragment
    ):
        raise DurableAiUnitError("database_url_contract")
    return unquote(parsed.username or "")


def _validate_database_env(
    path: Path,
    *,
    role: str,
    expected_user: str,
) -> None:
    try:
        validate_role_env_file(role, path)
    except EnvFileValidationError as exc:
        raise DurableAiUnitError("env_file_contract") from exc
    rows = _env_rows(path)
    if len(rows) != 1 or rows[0][0] != "DATABASE_URL":
        raise DurableAiUnitError("env_file_contract")
    if _database_url_role(rows[0][1]) != expected_user:
        raise DurableAiUnitError("database_role_contract")


def _validate_storage_env(path: Path) -> None:
    rows = _env_rows(path)
    if {name for name, _ in rows} != STORAGE_KEYS:
        raise DurableAiUnitError("storage_env_contract")
    values = dict(rows)
    region = values["NOTEAI_OSS_REGION"]
    if (
        values["NOTEAI_PRIVATE_STORAGE_BACKEND"] != "aliyun_oss"
        or not region.startswith("cn-")
        or values["NOTEAI_OSS_ENDPOINT"]
        != f"https://oss-{region}-internal.aliyuncs.com"
        or not values["NOTEAI_OSS_PRIVATE_BUCKET"]
        or not values["NOTEAI_OSS_RAM_ROLE"]
        or not values["NOTEAI_PRIVATE_STORAGE_KEY_EPOCH"]
        or values["NOTEAI_OSS_KEY_PREFIX"].strip("/") != "noteai-private"
    ):
        raise DurableAiUnitError("storage_env_contract")


def _verify_env_files(
    host_label: str,
    *,
    env_root: Path,
    expected_uid: int,
) -> None:
    if HOST_COMPONENT[host_label] == "dispatcher":
        dispatcher = env_root / "ai-dispatcher.env"
        _private_regular(dispatcher, expected_uid=expected_uid)
        _validate_database_env(
            dispatcher,
            role="ai_dispatcher",
            expected_user="noteai_ai_dispatcher",
        )
        return
    worker = env_root / "ai-worker.env"
    storage = env_root / "private-storage.env"
    _private_regular(worker, expected_uid=expected_uid)
    _private_regular(storage, expected_uid=expected_uid)
    _validate_database_env(
        worker,
        role="ai_worker",
        expected_user="noteai_ai_worker",
    )
    _validate_storage_env(storage)


def _unit_root(tier: str, formal_root: Path, acceptance_root: Path) -> Path:
    return formal_root if tier == "formal" else acceptance_root


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise DurableAiUnitError("directory_fsync") from exc


def _stage_directory_matches(path: Path, *, expected_uid: int) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    expected_gid = expected_uid if expected_uid == 0 else os.getegid()
    return (
        stat.S_ISDIR(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and metadata.st_uid == expected_uid
        and metadata.st_gid == expected_gid
        and stat.S_IMODE(metadata.st_mode) == 0o700
    )


def _remove_stage(stage_root: Path, candidate: Path) -> None:
    try:
        candidate.unlink(missing_ok=True)
        stage_root.rmdir()
    except OSError as exc:
        raise DurableAiUnitError("cleanup_unknown") from exc


def verify_unit(
    host_label: str,
    tier: str,
    *,
    operation_id: str | None = None,
    formal_root: Path = FORMAL_ROOT,
    acceptance_root: Path = ACCEPTANCE_ROOT,
    env_root: Path = Path("/etc/noteai"),
    expected_uid: int = 0,
    require_root: bool = True,
    runner: CommandRunner = subprocess.run,
) -> dict[str, Any]:
    if require_root:
        _require_root()
    _verify_env_files(
        host_label,
        env_root=env_root,
        expected_uid=expected_uid,
    )
    body = render_unit(host_label, tier, operation_id=operation_id)
    unit_name = _unit_name(host_label, tier)
    target = _unit_root(tier, formal_root, acceptance_root) / unit_name
    if not _file_matches(target, body, expected_uid=expected_uid):
        raise DurableAiUnitError("unit_contract")
    _loaded_exact(unit_name, target, runner=runner)
    _inactive(unit_name, runner=runner)
    _disabled(unit_name, tier, runner=runner)
    _container_absent(host_label, tier, runner=runner)
    image = verify_local_image(runner=runner)
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "verified",
        "host_label": host_label,
        "tier": tier,
        "unit_name": unit_name,
        "unit_active": False,
        "unit_enabled": False,
        "provider_calls": 0,
        "database_connections": 0,
        "service_starts": 0,
        **image,
    }


def install_unit(
    host_label: str,
    tier: str,
    *,
    operation_id: str | None = None,
    formal_root: Path = FORMAL_ROOT,
    acceptance_root: Path = ACCEPTANCE_ROOT,
    env_root: Path = Path("/etc/noteai"),
    lock_path: Path = LOCK_PATH,
    expected_uid: int = 0,
    require_root: bool = True,
    runner: CommandRunner = subprocess.run,
) -> dict[str, Any]:
    if require_root:
        _require_root()
    body = render_unit(host_label, tier, operation_id=operation_id)
    _verify_env_files(
        host_label,
        env_root=env_root,
        expected_uid=expected_uid,
    )
    verify_local_image(runner=runner)
    unit_name = _unit_name(host_label, tier)
    _inactive(unit_name, runner=runner, allow_unknown=True)
    _disabled(
        unit_name,
        tier,
        runner=runner,
        allow_not_found=True,
    )
    root = _unit_root(tier, formal_root, acceptance_root)
    try:
        root.mkdir(mode=0o755, parents=True, exist_ok=True)
    except OSError as exc:
        raise DurableAiUnitError("unit_root") from exc
    target = root / unit_name
    with _exclusive_lock(lock_path):
        stage_root = root / f".{TASK_ID}"
        candidate = stage_root / unit_name
        target_present = target.exists() or target.is_symlink()
        stage_present = stage_root.exists() or stage_root.is_symlink()
        if target_present and not stage_present:
            if target.is_symlink() or not _file_matches(
                target,
                body,
                expected_uid=expected_uid,
            ):
                raise DurableAiUnitError("unit_preexists")
            _run(["/usr/bin/systemctl", "daemon-reload"], runner=runner)
            result = verify_unit(
                host_label,
                tier,
                operation_id=operation_id,
                formal_root=formal_root,
                acceptance_root=acceptance_root,
                env_root=env_root,
                expected_uid=expected_uid,
                require_root=False,
                runner=runner,
            )
            return {
                **result,
                "status": "already_installed",
                "unit_file_writes": 0,
            }
        if stage_present:
            if (
                not _stage_directory_matches(
                    stage_root,
                    expected_uid=expected_uid,
                )
                or not _file_matches(
                    candidate,
                    body,
                    expected_uid=expected_uid,
                )
            ):
                raise DurableAiUnitError("stage_residue")
            if target_present:
                try:
                    candidate_stat = candidate.lstat()
                    target_stat = target.lstat()
                except OSError as exc:
                    raise DurableAiUnitError("stage_residue") from exc
                if (
                    target.is_symlink()
                    or not _file_matches(
                        target,
                        body,
                        expected_uid=expected_uid,
                    )
                    or candidate_stat.st_dev != target_stat.st_dev
                    or candidate_stat.st_ino != target_stat.st_ino
                    or candidate_stat.st_nlink != 2
                    or target_stat.st_nlink != 2
                ):
                    raise DurableAiUnitError("stage_residue")
        else:
            try:
                stage_root.mkdir(mode=0o700)
                if os.geteuid() == 0:
                    os.chown(stage_root, expected_uid, expected_uid)
            except OSError as exc:
                raise DurableAiUnitError("stage_create") from exc
            _write_candidate(candidate, body, expected_uid=expected_uid)

        target_owned = bool(target_present)
        target_inode = target.lstat().st_ino if target_owned else None
        try:
            _run(
                ["/usr/bin/systemd-analyze", "verify", str(candidate)],
                runner=runner,
            )
            if not target_owned:
                os.link(candidate, target, follow_symlinks=False)
                target_owned = True
                target_inode = candidate.lstat().st_ino
            _fsync_directory(root)
            _run(["/usr/bin/systemctl", "daemon-reload"], runner=runner)
            _remove_stage(stage_root, candidate)
            _fsync_directory(root)
            result = verify_unit(
                host_label,
                tier,
                operation_id=operation_id,
                formal_root=formal_root,
                acceptance_root=acceptance_root,
                env_root=env_root,
                expected_uid=expected_uid,
                require_root=False,
                runner=runner,
            )
        except BaseException as exc:
            cleanup_ok = True
            try:
                if (
                    target.exists()
                    and not target.is_symlink()
                    and target_owned
                    and target_inode is not None
                    and target.lstat().st_ino == target_inode
                    and _file_matches(target, body, expected_uid=expected_uid)
                ):
                    target.unlink()
                    _fsync_directory(root)
                    _run(
                        ["/usr/bin/systemctl", "daemon-reload"],
                        runner=runner,
                    )
                if stage_root.exists() and not stage_root.is_symlink():
                    _remove_stage(stage_root, candidate)
            except BaseException:
                cleanup_ok = False
            if not cleanup_ok:
                raise DurableAiUnitError("cleanup_unknown") from exc
            if isinstance(exc, DurableAiUnitError):
                raise
            raise DurableAiUnitError("unit_link") from exc
        return {**result, "status": "installed", "unit_file_writes": 1}


def remove_unit(
    host_label: str,
    tier: str,
    *,
    operation_id: str | None = None,
    formal_root: Path = FORMAL_ROOT,
    acceptance_root: Path = ACCEPTANCE_ROOT,
    lock_path: Path = LOCK_PATH,
    expected_uid: int = 0,
    require_root: bool = True,
    runner: CommandRunner = subprocess.run,
) -> dict[str, Any]:
    if require_root:
        _require_root()
    body = render_unit(host_label, tier, operation_id=operation_id)
    unit_name = _unit_name(host_label, tier)
    target = _unit_root(tier, formal_root, acceptance_root) / unit_name
    with _exclusive_lock(lock_path):
        unit_state = _inactive(
            unit_name,
            runner=runner,
            allow_failed=True,
        )
        _disabled(unit_name, tier, runner=runner)
        _container_absent(host_label, tier, runner=runner)
        if not _file_matches(target, body, expected_uid=expected_uid):
            raise DurableAiUnitError("unit_contract")
        if unit_state == "failed":
            _run(
                ["/usr/bin/systemctl", "reset-failed", unit_name],
                runner=runner,
            )
        try:
            target.unlink()
        except OSError as exc:
            raise DurableAiUnitError("unit_remove") from exc
        _fsync_directory(target.parent)
        _run(["/usr/bin/systemctl", "daemon-reload"], runner=runner)
        if target.exists() or target.is_symlink():
            raise DurableAiUnitError("unit_remove_verify")
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "removed",
        "host_label": host_label,
        "tier": tier,
        "unit_name": unit_name,
        "unit_file_removals": 1,
        "provider_calls": 0,
        "database_connections": 0,
        "service_starts": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--install", action="store_true")
    action.add_argument("--verify", action="store_true")
    action.add_argument("--remove", action="store_true")
    parser.add_argument("--host-label", choices=tuple(HOST_COMPONENT), required=True)
    parser.add_argument("--tier", choices=("formal", "acceptance"), required=True)
    parser.add_argument("--operation-id")
    args = parser.parse_args(argv)
    try:
        if args.tier == "formal" and args.operation_id is not None:
            raise DurableAiUnitError("formal_operation_id")
        if args.tier == "acceptance" and args.operation_id is None:
            raise DurableAiUnitError("operation_id_missing")
        kwargs = {
            "operation_id": args.operation_id,
        }
        if args.install:
            result = install_unit(args.host_label, args.tier, **kwargs)
        elif args.verify:
            result = verify_unit(args.host_label, args.tier, **kwargs)
        else:
            result = remove_unit(args.host_label, args.tier, **kwargs)
    except DurableAiUnitError as exc:
        print(
            f"production_durable_ai_unit_installer=FAIL code={exc.code}",
            file=sys.stderr,
        )
        return 1
    except BaseException:
        print(
            "production_durable_ai_unit_installer=FAIL code=unexpected",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
