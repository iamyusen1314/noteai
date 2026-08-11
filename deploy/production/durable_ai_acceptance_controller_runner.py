#!/usr/bin/env python3
"""Run the fixed provider-free Durable AI controller on API-C.

Only ``DATABASE_URL`` is streamed from the existing API env file to Docker's
stdin env-file.  Provider credentials are never forwarded, copied, printed,
or placed in process arguments.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from deploy.production import durable_ai_unit_installer as units


TASK_ID = "PROD-FIRST-LAUNCH-DURABLE-AI-CONTROLLER-001"
API_ENV = Path("/etc/noteai/api.env")
STORAGE_ENV = Path("/etc/noteai/private-storage.env")
CONTROLLER_SOURCE = ROOT / "deploy" / "production" / "durable_ai_acceptance.py"
CONTROLLER_SHA256 = (
    "5897aed7ae8cce032c4b5cb57dcebf49a43e5f9aa5891f704f89c32360368b74"
)
CONTAINER_NAME = "noteai-durable-ai-acceptance-controller"
LOCK_PATH = Path("/run/lock/noteai-durable-ai-controller.lock")
CONTROLLER_TASK_ID = "PROD-FIRST-LAUNCH-DURABLE-AI-RUNTIME-001"
CONTROLLER_CONFIRM_ENV = "NOTEAI_DURABLE_AI_ACCEPTANCE_MUTATION_CONFIRM"
CONTROLLER_CARRIER_ENV = "NOTEAI_DURABLE_AI_ACCEPTANCE_CARRIER_ROLE"
CONTROLLER_CARRIER_ROLE = "ai-worker"
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
ALLOWED_DATABASE_QUERY_KEYS = frozenset(
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
ACTION_TIMEOUT_SECONDS = {
    "admit": 180,
    "resolve-admit": 120,
    "hold": 120,
    "terminal": 120,
    "delete-primary": 300,
    "resolve-delete": 120,
}
MUTATING_ACTIONS = frozenset({"admit", "delete-primary"})

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
ENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class AcceptanceControllerRunnerError(RuntimeError):
    """A fixed, Secret-free controller runner failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


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
        raise AcceptanceControllerRunnerError("controller_lock") from exc
    try:
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _canonical_uuid(value: str, code: str) -> str:
    raw = str(value or "")
    try:
        normalized = str(uuid.UUID(raw))
    except (AttributeError, ValueError) as exc:
        raise AcceptanceControllerRunnerError(code) from exc
    if raw != normalized:
        raise AcceptanceControllerRunnerError(code)
    return raw


def _private_regular(
    path: Path,
    *,
    mode: int,
    expected_uid: int,
) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise AcceptanceControllerRunnerError("required_file_missing") from exc
    expected_gid = expected_uid if expected_uid == 0 else os.getegid()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != expected_uid
        or metadata.st_gid != expected_gid
        or stat.S_IMODE(metadata.st_mode) != mode
    ):
        raise AcceptanceControllerRunnerError("required_file_metadata")


def _env_rows(path: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    names: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise AcceptanceControllerRunnerError("env_read") from exc
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            raise AcceptanceControllerRunnerError("env_shape")
        if "=" not in stripped:
            raise AcceptanceControllerRunnerError("env_shape")
        name, value = stripped.split("=", 1)
        name = name.strip()
        if not name or name in names or any(
            marker in value for marker in ("\x00", "\r", "\n")
        ):
            raise AcceptanceControllerRunnerError("env_shape")
        names.add(name)
        rows.append((name, value))
    return rows


def _database_env(path: Path) -> str:
    names: set[str] = set()
    database_url = ""
    try:
        handle = path.open("r", encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise AcceptanceControllerRunnerError("env_read") from exc
    try:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("export "):
                raise AcceptanceControllerRunnerError("env_shape")
            if "=" not in stripped:
                raise AcceptanceControllerRunnerError("env_shape")
            name, value = stripped.split("=", 1)
            name = name.strip()
            if (
                not ENV_KEY.fullmatch(name)
                or name in names
                or any(marker in value for marker in ("\x00", "\r", "\n"))
            ):
                raise AcceptanceControllerRunnerError("env_shape")
            names.add(name)
            if name == "DATABASE_URL":
                database_url = value
    except UnicodeError as exc:
        raise AcceptanceControllerRunnerError("env_read") from exc
    finally:
        handle.close()
    if "DATABASE_URL" not in names:
        raise AcceptanceControllerRunnerError("api_database_url")
    try:
        parsed = urlsplit(database_url)
        query = parse_qsl(
            parsed.query,
            keep_blank_values=True,
            strict_parsing=True,
        )
    except (TypeError, ValueError) as exc:
        raise AcceptanceControllerRunnerError("api_database_url") from exc
    query_names: set[str] = set()
    for raw_name, value in query:
        name = raw_name.lower()
        if (
            name not in ALLOWED_DATABASE_QUERY_KEYS
            or name in query_names
            or any(
                marker in raw_name or marker in value
                for marker in ("\x00", "\r", "\n")
            )
        ):
            raise AcceptanceControllerRunnerError("api_database_url")
        query_names.add(name)
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or unquote(parsed.username or "") != "noteai_app"
        or parsed.password in (None, "")
        or not parsed.hostname
        or parsed.path in {"", "/"}
        or parsed.fragment
    ):
        raise AcceptanceControllerRunnerError("api_database_url")
    return f"DATABASE_URL={database_url}\n"


def _validate_storage_env(path: Path) -> None:
    rows = _env_rows(path)
    if {name for name, _ in rows} != STORAGE_KEYS:
        raise AcceptanceControllerRunnerError("storage_env_keys")
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
        raise AcceptanceControllerRunnerError("storage_env_contract")


def _verify_source(path: Path, *, expected_uid: int) -> None:
    _private_regular(path, mode=0o644, expected_uid=expected_uid)
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise AcceptanceControllerRunnerError("controller_source_read") from exc
    if digest != CONTROLLER_SHA256:
        raise AcceptanceControllerRunnerError("controller_source_hash")


def _container_absent(*, runner: CommandRunner) -> None:
    try:
        completed = runner(
            [
                *units.DOCKER_COMMAND,
                "container",
                "ls",
                "-a",
                "--filter",
                f"name=^/{CONTAINER_NAME}$",
                "--format",
                "{{.ID}}",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise AcceptanceControllerRunnerError("docker_unavailable") from exc
    if completed.returncode != 0:
        raise AcceptanceControllerRunnerError("container_state_unknown")
    if completed.stdout.strip():
        raise AcceptanceControllerRunnerError("controller_container_present")


def _cleanup_container_if_present(
    action: str,
    nonce: str,
    *,
    runner: CommandRunner,
) -> None:
    try:
        listed = runner(
            [
                *units.DOCKER_COMMAND,
                "container",
                "ls",
                "-a",
                "--filter",
                f"name=^/{CONTAINER_NAME}$",
                "--format",
                "{{.ID}}",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise AcceptanceControllerRunnerError("cleanup_unknown") from exc
    if listed.returncode != 0:
        raise AcceptanceControllerRunnerError("cleanup_unknown")
    container_ids = [line.strip() for line in listed.stdout.splitlines() if line.strip()]
    if not container_ids:
        return
    if len(container_ids) != 1 or not re.fullmatch(r"[0-9a-f]{12,64}", container_ids[0]):
        raise AcceptanceControllerRunnerError("cleanup_unknown")
    container_id = container_ids[0]
    try:
        inspected = runner(
            [*units.DOCKER_COMMAND, "container", "inspect", container_id],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise AcceptanceControllerRunnerError("cleanup_unknown") from exc
    if inspected.returncode != 0:
        raise AcceptanceControllerRunnerError("cleanup_unknown")
    try:
        rows = json.loads(inspected.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AcceptanceControllerRunnerError("cleanup_unknown") from exc
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise AcceptanceControllerRunnerError("cleanup_unknown")
    row = rows[0]
    config = row.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    if (
        row.get("Name") != f"/{CONTAINER_NAME}"
        or row.get("Image") != units.IMAGE_CONFIG
        or not isinstance(config, dict)
        or config.get("Image") != units.IMAGE_REF
        or not isinstance(labels, dict)
        or labels.get("com.noteai.acceptance")
        != "durable-ai-controller-v1"
        or labels.get("com.noteai.acceptance.nonce") != nonce
        or labels.get("com.noteai.acceptance.action") != action
    ):
        raise AcceptanceControllerRunnerError("cleanup_unknown")
    try:
        removed = runner(
            [
                *units.DOCKER_COMMAND,
                "container",
                "rm",
                "--force",
                container_id,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise AcceptanceControllerRunnerError("cleanup_unknown") from exc
    if removed.returncode != 0:
        raise AcceptanceControllerRunnerError("cleanup_unknown")
    _container_absent(runner=runner)


def _controller_args(
    action: str,
    nonce: str,
    operation_id: str | None,
) -> list[str]:
    if action == "admit":
        return ["--admit", "--nonce", nonce]
    if action == "resolve-admit":
        return ["--resolve-admit", "--nonce", nonce]
    if action in {"hold", "terminal"}:
        return ["--observe", action, "--nonce", nonce]
    if action == "delete-primary":
        return [
            "--delete-primary",
            "--nonce",
            nonce,
            "--operation-id",
            str(operation_id),
        ]
    if action == "resolve-delete":
        return [
            "--resolve-delete",
            "--nonce",
            nonce,
            "--operation-id",
            str(operation_id),
        ]
    raise AcceptanceControllerRunnerError("action")


def _validate_result(
    action: str,
    nonce: str,
    operation_id: str | None,
    result: Any,
) -> dict[str, Any]:
    if not isinstance(result, dict) or result.get("provider_calls") != 0:
        raise AcceptanceControllerRunnerError("controller_result")
    if action == "admit":
        anchor_created = result.get("anchor_created")
        if (
            result.get("status") != "admitted"
            or result.get("nonce") != nonce
            or (anchor_created is not True and anchor_created is not False)
            or result.get("private_object_anchor_writes")
            != int(bool(anchor_created))
            or result.get("private_object_anchor_reads") != 1
        ):
            raise AcceptanceControllerRunnerError("controller_result")
        _canonical_uuid(str(result.get("operation_id", "")), "operation_id")
    elif action == "resolve-admit":
        if result.get("nonce") != nonce or result.get("read_only") is not True:
            raise AcceptanceControllerRunnerError("controller_result")
        if result.get("status") == "admission_resolved":
            _canonical_uuid(str(result.get("operation_id", "")), "operation_id")
        elif (
            result.get("status") != "admission_absent"
            or result.get("recoverable") is not True
            or (
                result.get("user_present") is not True
                and result.get("user_present") is not False
            )
        ):
            raise AcceptanceControllerRunnerError("controller_result")
    elif action in {"hold", "terminal"}:
        if result.get("acceptance") != action or result.get("nonce") != nonce:
            raise AcceptanceControllerRunnerError("controller_result")
    else:
        if (
            result.get("status") != "primary_deleted"
            or result.get("operation_id") != operation_id
            or result.get("nonce") != nonce
        ):
            raise AcceptanceControllerRunnerError("controller_result")
        if action == "resolve-delete" and result.get("read_only") is not True:
            raise AcceptanceControllerRunnerError("controller_result")
    return result


def run_controller(
    action: str,
    nonce: str,
    *,
    operation_id: str | None = None,
    api_env: Path = API_ENV,
    storage_env: Path = STORAGE_ENV,
    controller_source: Path = CONTROLLER_SOURCE,
    expected_uid: int = 0,
    require_root: bool = True,
    lock_path: Path = LOCK_PATH,
    runner: CommandRunner = subprocess.run,
) -> dict[str, Any]:
    if require_root and os.geteuid() != 0:
        raise AcceptanceControllerRunnerError("root_required")
    nonce = _canonical_uuid(nonce, "nonce_shape")
    if action not in ACTION_TIMEOUT_SECONDS:
        raise AcceptanceControllerRunnerError("action")
    if action in {"delete-primary", "resolve-delete"}:
        operation_id = _canonical_uuid(
            str(operation_id or ""),
            "operation_id",
        )
    elif operation_id is not None:
        raise AcceptanceControllerRunnerError("unexpected_operation_id")
    _private_regular(api_env, mode=0o600, expected_uid=expected_uid)
    _private_regular(storage_env, mode=0o600, expected_uid=expected_uid)
    _verify_source(controller_source, expected_uid=expected_uid)
    database_env = _database_env(api_env)
    _validate_storage_env(storage_env)
    units.verify_local_image(runner=runner)
    command = [
        *units.DOCKER_COMMAND,
        "run",
        "--pull=never",
        "--rm",
        f"--name={CONTAINER_NAME}",
        "--label=com.noteai.acceptance=durable-ai-controller-v1",
        f"--label=com.noteai.acceptance.nonce={nonce}",
        f"--label=com.noteai.acceptance.action={action}",
        "--user=999:999",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--network=bridge",
        "--ipc=private",
        "--memory=256m",
        "--cpus=0.25",
        "--pids-limit=64",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777,uid=999,gid=999",
        "--env-file=/dev/stdin",
        f"--env-file={storage_env}",
        "--env=NOTEAI_RUNTIME_ROLE=api",
        "--env=NOTEAI_DEPLOYMENT_STAGE=production",
        "--env=NOTEAI_CLOUD_RUNTIME=1",
        "--env=NOTEAI_SKIP_MODEL_ARTIFACT_CHECK=1",
        "--env=NOTEAI_DURABLE_AI_ACCEPTANCE_MODE=1",
        f"--env={CONTROLLER_CARRIER_ENV}={CONTROLLER_CARRIER_ROLE}",
    ]
    if action in MUTATING_ACTIONS:
        command.append(
            "--env="
            f"{CONTROLLER_CONFIRM_ENV}={CONTROLLER_TASK_ID}"
        )
    command.extend(
        [
            f"--volume={controller_source}:/task/durable_ai_acceptance.py:ro",
            "--entrypoint=python",
            units.IMAGE_REF,
            "/task/durable_ai_acceptance.py",
            *_controller_args(action, nonce, operation_id),
        ]
    )
    with _exclusive_lock(lock_path):
        _container_absent(runner=runner)
        try:
            completed = runner(
                command,
                input=database_env,
                check=False,
                capture_output=True,
                text=True,
                timeout=ACTION_TIMEOUT_SECONDS[action],
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            _cleanup_container_if_present(action, nonce, runner=runner)
            code = (
                "controller_mutation_outcome_unknown"
                if action in MUTATING_ACTIONS
                else "controller_read_timeout"
            )
            raise AcceptanceControllerRunnerError(code) from exc
        if completed.returncode != 0:
            _cleanup_container_if_present(action, nonce, runner=runner)
            code = (
                "controller_mutation_outcome_unknown"
                if action in MUTATING_ACTIONS
                else "controller_read_failed"
            )
            raise AcceptanceControllerRunnerError(code)
        try:
            result = json.loads(completed.stdout)
        except (json.JSONDecodeError, TypeError) as exc:
            code = (
                "controller_mutation_outcome_unknown"
                if action in MUTATING_ACTIONS
                else "controller_result_json"
            )
            raise AcceptanceControllerRunnerError(code) from exc
        _container_absent(runner=runner)
        try:
            return _validate_result(action, nonce, operation_id, result)
        except AcceptanceControllerRunnerError as exc:
            if action in MUTATING_ACTIONS:
                raise AcceptanceControllerRunnerError(
                    "controller_mutation_outcome_unknown"
                ) from exc
            raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--admit", action="store_true")
    action.add_argument("--resolve-admit", action="store_true")
    action.add_argument("--observe", choices=("hold", "terminal"))
    action.add_argument("--delete-primary", action="store_true")
    action.add_argument("--resolve-delete", action="store_true")
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--operation-id")
    args = parser.parse_args(argv)
    selected = (
        "admit"
        if args.admit
        else "resolve-admit"
        if args.resolve_admit
        else args.observe
        if args.observe
        else "delete-primary"
        if args.delete_primary
        else "resolve-delete"
    )
    try:
        result = run_controller(
            selected,
            args.nonce,
            operation_id=args.operation_id,
        )
    except AcceptanceControllerRunnerError as exc:
        print(
            "production_durable_ai_acceptance_controller_runner=FAIL "
            f"code={exc.code}",
            file=sys.stderr,
        )
        return 1
    except BaseException:
        print(
            "production_durable_ai_acceptance_controller_runner=FAIL "
            "code=unexpected",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
