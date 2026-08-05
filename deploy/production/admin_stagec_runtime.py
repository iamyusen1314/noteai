#!/usr/bin/env python3
"""Bounded, Secret-free Admin Stage C runtime executor."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


STAGE = Path("/root/.noteai-admin-stagec-5335-v3")
RESULTS = STAGE / "results"
STATE = STAGE / "state.json"
RUN_ROOT = Path("/run/noteai-admin-stagec-5335-v3")
TOKEN_FILE = RUN_ROOT / "admin-bearer"
CANDIDATE = STAGE / "noteai-admin.candidate-5335-v3.service"
ROLLBACK = STAGE / "noteai-admin.rollback.service"
INSTALLED = Path("/etc/systemd/system/noteai-admin.service")
SERVICE = "noteai-admin"
FORMAL = "noteai-admin-c"
CANARY = "noteai-admin-canary-stagec-5335-v3"
CANARY_DATA = STAGE / "canary-data"

OLD_UNIT_SHA = "c299059d167eab0863639355a6485094e58e3dca6bcec7adbe9f78a3857a1ab2"
CANDIDATE_SHA = "101f8814d89736c2aa920f3107916b9b1ab53cabffdde0d69908285fd6d1fe8a"
OLD_CONFIG = "sha256:2283095764622e373e30b51ba749819751e6bfb0c37c6bb82e2d3bfe4937760f"
NEW_CONFIG = "sha256:fa0e658cba59a0adda16f64efb9bdfe543f459d90fe35997bd39046eb7743bd4"
REVISION = "5335bdaed933b1f999b5f819c047ec50c11821ae"

FULL_SELECT_TABLES = {
    "subscriptions",
    "credits",
    "usage_records",
    "model_usage_records",
    "managed_prompts",
    "prompt_history",
    "system_settings",
    "tracked_notes",
    "ai_operations",
    "ai_operation_settlements",
    "ai_operation_outbox",
    "xhs_freshness_ledger",
    "xhs_crawler_health",
    "xhs_trends_runs",
    "payment_orders",
    "payment_refunds",
    "payment_events",
    "payment_cash_ledger",
    "payment_entitlement_ledger",
    "payment_credit_positions",
    "payment_credit_consumptions",
    "payment_reconciliation_runs",
    "payment_reconciliation_items",
    "payment_settlement_summaries",
}
SELECT_COLUMNS = {
    "users": {
        "id",
        "username",
        "email",
        "phone",
        "nickname",
        "avatar_emoji",
        "created_at",
        "last_login",
    },
    "notes": {"id", "user_id", "score"},
    "credit_transactions": {
        "user_id",
        "type",
        "amount",
        "balance_after",
        "description",
        "paid_rmb",
        "package_id",
        "recorded_at",
    },
}


def safe_exception_code(exc: Exception | None) -> str:
    if exc is None:
        return "stage_failure"
    value = str(exc)
    if (
        1 <= len(value) <= 64
        and all(character.islower() or character.isdigit() or character == "_" for character in value)
    ):
        return value
    if isinstance(exc, subprocess.CalledProcessError):
        return "subprocess_failed"
    return "unclassified_failure"


class StageFailure(RuntimeError):
    def __init__(self, payload: dict, cause: Exception | None = None):
        super().__init__("stage_failure")
        self.payload = payload
        self.payload.setdefault("failure_detail_code", safe_exception_code(cause))


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def id_hash(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def run(
    args: list[str],
    *,
    check: bool = True,
    input_bytes: bytes | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        args,
        input=input_bytes,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=check,
    )


def regular_root(path: Path, mode: int) -> bool:
    try:
        item = os.lstat(path)
    except FileNotFoundError:
        return False
    return (
        stat.S_ISREG(item.st_mode)
        and not stat.S_ISLNK(item.st_mode)
        and stat.S_IMODE(item.st_mode) == mode
        and item.st_uid == 0
        and item.st_gid == 0
        and item.st_nlink == 1
    )


def atomic_json(path: Path, payload: dict) -> None:
    RESULTS.mkdir(mode=0o700, exist_ok=True)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    temp = path.with_suffix(path.suffix + ".tmp")
    if temp.exists() or path.exists():
        raise RuntimeError("result_exists")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    os.chmod(path, 0o600)


def load_state() -> dict:
    if not regular_root(STATE, 0o600):
        return {}
    value = json.loads(STATE.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("state_shape")
    return value


def save_state(value: dict) -> None:
    temp = STATE.with_suffix(".tmp")
    if temp.exists():
        raise RuntimeError("state_temp_exists")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, STATE)
    os.chmod(STATE, 0o600)


def result_path(mode: str) -> Path:
    return RESULTS / f"{mode}.json"


def successful_result(mode: str) -> bool:
    path = result_path(mode)
    if not regular_root(path, 0o600):
        return False
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False
    return isinstance(value, dict) and value.get("status") == "PASS"


def inspect_container(name: str) -> dict:
    raw = run(["docker", "inspect", name], capture=True).stdout
    values = json.loads(raw)
    if len(values) != 1:
        raise RuntimeError("container_count")
    return values[0]


def inspect_image(image: str) -> dict:
    raw = run(["docker", "image", "inspect", image], capture=True).stdout
    values = json.loads(raw)
    if len(values) != 1:
        raise RuntimeError("image_count")
    return values[0]


def container_exists(name: str) -> bool:
    return run(
        ["docker", "inspect", name],
        check=False,
    ).returncode == 0


def unit_tokens(path: Path) -> list[str]:
    line = next(
        value[len("ExecStart=") :]
        for value in path.read_text(encoding="utf-8").splitlines()
        if value.startswith("ExecStart=")
    )
    return shlex.split(line)


def option_value(tokens: list[str], option: str) -> str | bool:
    values: list[str | bool] = []
    for index, token in enumerate(tokens):
        if token == option:
            if index + 1 < len(tokens) and not tokens[index + 1].startswith("--"):
                values.append(tokens[index + 1])
            else:
                values.append(True)
        elif token.startswith(option + "="):
            values.append(token.split("=", 1)[1])
    if len(values) != 1:
        raise RuntimeError("option_cardinality")
    return values[0]


def replace_option(tokens: list[str], option: str, value: str) -> None:
    indexes = [index for index, token in enumerate(tokens) if token == option]
    if len(indexes) != 1 or indexes[0] + 1 >= len(tokens):
        raise RuntimeError("replace_option")
    tokens[indexes[0] + 1] = value


def protected_env_values(path_value: str) -> dict[str, str]:
    path = Path(path_value)
    if not regular_root(path, 0o600):
        raise RuntimeError("env_file_shape")
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise RuntimeError("env_file_line")
        key, value = line.split("=", 1)
        if not key or key in values:
            raise RuntimeError("env_file_key")
        values[key] = value
    return values


def http_json(
    port: int,
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    token: str = "",
) -> tuple[int, object | None]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            status = response.status
            raw = response.read(1_000_000)
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read(1_000_000)
    except Exception:
        return 0, None
    try:
        payload = json.loads(raw)
    except Exception:
        payload = None
    return status, payload


def cors_allow_origin(port: int, path: str, token: str) -> str | None:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": "https://stagec-untrusted.invalid",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return response.headers.get("Access-Control-Allow-Origin")
    except urllib.error.HTTPError as exc:
        return exc.headers.get("Access-Control-Allow-Origin")
    except Exception:
        raise RuntimeError("cors_request")


def health_once(port: int) -> bool:
    live_status, live = http_json(port, "/health/live")
    ready_status, ready = http_json(port, "/health/ready")
    return (
        live_status == 200
        and isinstance(live, dict)
        and live.get("status") == "ok"
        and live.get("service") == "noteai-admin"
        and ready_status == 200
        and isinstance(ready, dict)
        and ready.get("status") == "ready"
        and ready.get("service") == "noteai-admin"
        and set((ready.get("checks") or {}).keys())
        == {"admin_credentials", "database"}
        and all(
            isinstance(value, dict) and value.get("ok") is True
            for value in (ready.get("checks") or {}).values()
        )
    )


def api_health_once(port: int) -> bool:
    live_status, live = http_json(port, "/health/live")
    ready_status, ready = http_json(port, "/health/ready")
    return (
        live_status == 200
        and isinstance(live, dict)
        and live.get("status") == "ok"
        and live.get("service") == "noteai-api"
        and ready_status == 200
        and isinstance(ready, dict)
        and ready.get("status") == "ready"
        and ready.get("service") == "noteai-api"
        and set((ready.get("checks") or {}).keys()) == {"database", "model"}
        and all(
            isinstance(value, dict) and value.get("ok") is True
            for value in (ready.get("checks") or {}).values()
        )
    )


def wait_health(port: int, rounds: int = 1) -> bool:
    for _ in range(80):
        if health_once(port):
            break
        time.sleep(0.25)
    else:
        return False
    for _ in range(rounds - 1):
        time.sleep(0.25)
        if not health_once(port):
            return False
    return True


def safe_container_shape(name: str, port: int) -> dict:
    item = inspect_container(name)
    image = inspect_image(item["Image"])
    config = item.get("Config") or {}
    host = item.get("HostConfig") or {}
    state = item.get("State") or {}
    labels = config.get("Labels") or {}
    env = {}
    for value in config.get("Env") or []:
        if "=" in value:
            key, content = value.split("=", 1)
            env[key] = content
    mounts = [
        mount
        for mount in item.get("Mounts") or []
        if mount.get("Destination") == "/app/model/data"
    ]
    ports = ((item.get("NetworkSettings") or {}).get("Ports") or {}).get("8001/tcp")
    expected_port = [{"HostIp": "127.0.0.1", "HostPort": str(port)}]
    expected_tokens = canary_command() if name == CANARY else unit_tokens(CANDIDATE)
    expected_env = {
        expected_tokens[index + 1].split("=", 1)[0]: expected_tokens[index + 1].split(
            "=", 1
        )[1]
        for index, token in enumerate(expected_tokens)
        if token == "--env" and "=" in expected_tokens[index + 1]
    }
    expected_env_file = protected_env_values(
        str(option_value(expected_tokens, "--env-file"))
    )
    expected_labels = {
        expected_tokens[index + 1].split("=", 1)[0]: expected_tokens[
            index + 1
        ].split("=", 1)[1]
        for index, token in enumerate(expected_tokens)
        if token == "--label" and "=" in expected_tokens[index + 1]
    }
    expected_all_env = {
        value.split("=", 1)[0]: value.split("=", 1)[1]
        for value in (image.get("Config") or {}).get("Env") or []
        if "=" in value
    }
    expected_all_env.update(expected_env_file)
    expected_all_env.update(expected_env)
    expected_all_labels = dict((image.get("Config") or {}).get("Labels") or {})
    expected_all_labels.update(expected_labels)
    expected_mount = option_value(expected_tokens, "--mount")
    expected_mount_parts = str(expected_mount).split(",")
    if len(expected_mount_parts) != 3 or any(
        "=" not in value for value in expected_mount_parts
    ):
        raise RuntimeError("candidate_mount")
    expected_mount_values = dict(
        value.split("=", 1)
        for value in expected_mount_parts
    )
    if (
        set(expected_mount_values) != {"type", "src", "dst"}
        or expected_mount_values.get("type") != "bind"
        or expected_mount_values.get("dst") != "/app/model/data"
    ):
        raise RuntimeError("candidate_mount")
    expected_mount_source = expected_mount_values["src"]
    exact = (
        item.get("Image") == NEW_CONFIG
        and image.get("Id") == NEW_CONFIG
        and (image.get("Config") or {}).get("Entrypoint")
        == ["/app/scripts/docker_entrypoint.sh"]
        and (image.get("Config") or {}).get("Cmd")
        == ["/app/scripts/render_start_admin.sh"]
        and config.get("Entrypoint") == ["/app/scripts/docker_entrypoint.sh"]
        and config.get("Cmd") == ["/app/scripts/render_start_admin.sh"]
        and (image.get("Config") or {}).get("Labels", {}).get(
            "org.opencontainers.image.revision"
        )
        == REVISION
        and (image.get("Config") or {}).get("Labels", {}).get(
            "com.noteai.runtime.role"
        )
        == "admin"
        and image.get("Os") == "linux"
        and image.get("Architecture") == "amd64"
        and config.get("User") == "999:999"
        and host.get("ReadonlyRootfs") is True
        and host.get("Privileged") is False
        and host.get("CapDrop") == ["ALL"]
        and not (host.get("CapAdd") or [])
        and host.get("SecurityOpt") == ["no-new-privileges:true"]
        and not (host.get("Devices") or [])
        and host.get("PidsLimit") == 512
        and host.get("Memory") == 1073741824
        and host.get("NanoCpus") == 1000000000
        and host.get("NetworkMode") == "bridge"
        and host.get("IpcMode") == "private"
        and (host.get("RestartPolicy") or {}).get("Name") in {"", "no"}
        and host.get("Tmpfs")
        == {"/tmp": "rw,noexec,nosuid,nodev,size=512m,mode=1777,uid=999,gid=999"}
        and len(mounts) == 1
        and mounts[0].get("Type") == "bind"
        and mounts[0].get("RW") is True
        and mounts[0].get("Source") == expected_mount_source
        and ports == expected_port
        and labels == expected_all_labels
        and state.get("Running") is True
        and item.get("RestartCount") == 0
        and env.get("NOTEAI_RUNTIME_ROLE") == "admin"
        and env.get("NOTEAI_CLOUD_RUNTIME") == "1"
        and env.get("NOTEAI_SKIP_MODEL_ARTIFACT_CHECK") == "1"
        and env.get("NOTEAI_ENABLE_CLOUD_MODEL_MUTATION") == "0"
        and env.get("PORT") == "8001"
        and "DATABASE_URL" in env
        and bool(env.get("ADMIN_PASSWORD"))
        and env == expected_all_env
        and "PGOPTIONS" not in env
    )
    return {
        "exact": exact,
        "container_identity_sha256": id_hash(item.get("Id", "")),
        "started_at_utc": state.get("StartedAt", ""),
        "restart_count": item.get("RestartCount"),
        "image_config_id": item.get("Image"),
        "running": state.get("Running") is True,
        "health_status": (state.get("Health") or {}).get("Status", ""),
        "loopback_port": port,
        "environment_key_count": len(env),
        "pgoptions_absent": "PGOPTIONS" not in env,
        "declared_environment_exact": env == expected_all_env,
        "declared_labels_exact": labels == expected_all_labels,
        "mount_source_exact": (
            mounts[0].get("Source") == expected_mount_source
            if len(mounts) == 1
            else False
        ),
    }


def bounded_log_counts(name: str) -> dict:
    completed = subprocess.run(
        ["docker", "logs", "--tail", "200", name],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True,
    )
    raw = completed.stdout
    lower = raw.lower()
    return {
        "bytes_reviewed": len(raw),
        "traceback_hits": lower.count(b"traceback"),
        "fatal_hits": lower.count(b"fatal"),
        "dsn_hits": lower.count(b"postgresql://"),
        "alternate_dsn_hits": lower.count(b"postgres://"),
        "password_assignment_hits": lower.count(b"password="),
        "admin_password_assignment_hits": lower.count(b"admin_password="),
        "database_url_assignment_hits": lower.count(b"database_url="),
        "private_key_hits": lower.count(b"private key"),
        "bearer_prefix_hits": lower.count(b"admin_"),
        "authorization_bearer_hits": lower.count(b"authorization: bearer"),
        "token_assignment_hits": lower.count(b"token="),
    }


def docker_exec_python(container: str, source: str) -> dict:
    result = run(
        ["docker", "exec", "-i", container, "python", "-"],
        input_bytes=source.encode("utf-8"),
        capture=True,
    )
    lines = result.stdout.decode("utf-8").splitlines()
    if not lines:
        raise RuntimeError("container_python_output")
    value = json.loads(lines[-1])
    if not isinstance(value, dict):
        raise RuntimeError("container_python_shape")
    return value


ACL_AUDIT_SOURCE = r'''
import json, os
import psycopg
from psycopg.rows import dict_row

FULL = {
    "subscriptions", "credits", "usage_records", "model_usage_records",
    "managed_prompts", "prompt_history", "system_settings", "tracked_notes",
    "ai_operations", "ai_operation_settlements", "ai_operation_outbox",
    "xhs_freshness_ledger", "xhs_crawler_health", "xhs_trends_runs",
    "payment_orders", "payment_refunds", "payment_events",
    "payment_cash_ledger", "payment_entitlement_ledger",
    "payment_credit_positions", "payment_credit_consumptions",
    "payment_reconciliation_runs", "payment_reconciliation_items",
    "payment_settlement_summaries",
}
COLUMNS = {
    "users": {"id","username","email","phone","nickname","avatar_emoji","created_at","last_login"},
    "notes": {"id","user_id","score"},
    "credit_transactions": {"user_id","type","amount","balance_after","description","paid_rmb","package_id","recorded_at"},
}
out = {"status": "FAILED"}
conn = psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)
conn.autocommit = True
try:
    default_ro = conn.execute("SHOW default_transaction_read_only").fetchone()["default_transaction_read_only"]
    conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
    tx_ro = conn.execute("SHOW transaction_read_only").fetchone()["transaction_read_only"]
    identity = conn.execute("SELECT session_user,current_user,txid_current_if_assigned() AS xid").fetchone()
    attrs = conn.execute(
        "SELECT rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,"
        "rolreplication,rolbypassrls FROM pg_roles "
        "WHERE rolname='noteai_admin_runtime'"
    ).fetchone()
    privileges = ("SELECT","INSERT","UPDATE","DELETE","TRUNCATE","REFERENCES","TRIGGER")
    table_matrix = conn.execute(
        "SELECT c.relname AS table_name,p.privilege,"
        "has_table_privilege(current_user,c.oid,p.privilege) AS actual,"
        "has_table_privilege(current_user,c.oid,"
        "p.privilege || ' WITH GRANT OPTION') AS grantable "
        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "CROSS JOIN unnest(%s::text[]) AS p(privilege) "
        "WHERE n.nspname='public' AND c.relkind='r' "
        "ORDER BY c.relname,p.privilege",
        (list(privileges),),
    ).fetchall()
    tables = sorted({row["table_name"] for row in table_matrix})
    table_checks = table_allow = table_deny = table_mismatch = table_grantable = 0
    for row in table_matrix:
        table = row["table_name"]
        privilege = row["privilege"]
        allowed = set()
        if table in FULL:
            allowed.add("SELECT")
        if table == "admin_sessions":
            allowed.update({"SELECT","INSERT","DELETE"})
        expected = privilege in allowed
        table_checks += 1
        table_allow += int(bool(row["actual"]))
        table_deny += int(not bool(row["actual"]))
        table_mismatch += int(bool(row["actual"]) != expected)
        table_grantable += int(bool(row["grantable"]))
    column_privileges = ("SELECT","INSERT","UPDATE","REFERENCES")
    column_matrix = conn.execute(
        "SELECT c.relname AS table_name,a.attname AS column_name,p.privilege,"
        "has_column_privilege(current_user,c.oid,a.attnum,p.privilege) AS actual,"
        "has_column_privilege(current_user,c.oid,a.attnum,"
        "p.privilege || ' WITH GRANT OPTION') AS grantable "
        "FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "CROSS JOIN unnest(%s::text[]) AS p(privilege) "
        "WHERE n.nspname='public' AND c.relkind='r' "
        "AND a.attnum>0 AND NOT a.attisdropped "
        "ORDER BY c.relname,a.attnum,p.privilege",
        (list(column_privileges),),
    ).fetchall()
    column_checks = column_allow = column_mismatch = column_grantable = 0
    for row in column_matrix:
        table = row["table_name"]
        column = row["column_name"]
        privilege = row["privilege"]
        expected = (
            (
                privilege == "SELECT"
                and (
                    table in FULL or table == "admin_sessions"
                    or column in COLUMNS.get(table, set())
                )
            )
            or (privilege == "INSERT" and table == "admin_sessions")
        )
        column_checks += 1
        column_allow += int(bool(row["actual"]))
        column_mismatch += int(bool(row["actual"]) != expected)
        column_grantable += int(bool(row["grantable"]))
    sequence_privileges = ("USAGE","SELECT","UPDATE")
    sequence_matrix = conn.execute(
        "SELECT c.relname AS sequence_name,p.privilege,"
        "has_sequence_privilege(current_user,c.oid,p.privilege) AS actual,"
        "has_sequence_privilege(current_user,c.oid,"
        "p.privilege || ' WITH GRANT OPTION') AS grantable "
        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "CROSS JOIN unnest(%s::text[]) AS p(privilege) "
        "WHERE n.nspname='public' AND c.relkind='S' "
        "ORDER BY c.relname,p.privilege",
        (list(sequence_privileges),),
    ).fetchall()
    sequences = sorted({row["sequence_name"] for row in sequence_matrix})
    sequence_checks = sequence_allowed = sequence_grantable = 0
    for row in sequence_matrix:
        sequence_checks += 1
        sequence_allowed += int(bool(row["actual"]))
        sequence_grantable += int(bool(row["grantable"]))
    memberships = conn.execute(
        "SELECT granted.rolname AS granted_name,member.rolname AS member_name,"
        "m.admin_option,"
        "(to_jsonb(m)->>'inherit_option')::boolean AS inherit_option,"
        "(to_jsonb(m)->>'set_option')::boolean AS set_option "
        "FROM pg_auth_members m "
        "JOIN pg_roles granted ON granted.oid=m.roleid "
        "JOIN pg_roles member ON member.oid=m.member "
        "WHERE granted.rolname='noteai_admin_runtime' "
        "OR member.rolname='noteai_admin_runtime' "
        "ORDER BY granted.rolname,member.rolname"
    ).fetchall()
    membership_exact = (
        len(memberships) == 1
        and memberships[0]["granted_name"] == "noteai_admin_runtime"
        and memberships[0]["member_name"] == "noteai_admin"
        and memberships[0]["admin_option"] is True
        and memberships[0]["inherit_option"] is False
        and memberships[0]["set_option"] is False
    )
    ownership = conn.execute(
        "SELECT "
        "(SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid=c.relowner "
        " WHERE r.rolname='noteai_admin_runtime') + "
        "(SELECT count(*) FROM pg_namespace n JOIN pg_roles r ON r.oid=n.nspowner "
        " WHERE r.rolname='noteai_admin_runtime') + "
        "(SELECT count(*) FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner "
        " WHERE r.rolname='noteai_admin_runtime') AS count"
    ).fetchone()["count"]
    functions = conn.execute(
        "SELECT count(*) AS total,"
        "count(*) FILTER (WHERE has_function_privilege(current_user,p.oid,'EXECUTE')) AS executable,"
        "count(*) FILTER (WHERE has_function_privilege("
        "current_user,p.oid,'EXECUTE WITH GRANT OPTION')) AS grantable,"
        "count(*) FILTER (WHERE p.prosecdef AND has_function_privilege(current_user,p.oid,'EXECUTE')) AS secdef "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='public'"
    ).fetchone()
    database_acl = conn.execute(
        "SELECT has_database_privilege(current_user,current_database(),'CONNECT') AS connect,"
        "has_database_privilege(current_user,current_database(),'CREATE') AS create,"
        "has_database_privilege(current_user,current_database(),'TEMP') AS temp,"
        "has_database_privilege(current_user,current_database(),"
        "'CONNECT WITH GRANT OPTION') AS connect_grantable,"
        "has_database_privilege(current_user,current_database(),"
        "'CREATE WITH GRANT OPTION') AS create_grantable,"
        "has_database_privilege(current_user,current_database(),"
        "'TEMP WITH GRANT OPTION') AS temp_grantable"
    ).fetchone()
    schema_acl = conn.execute(
        "SELECT has_schema_privilege(current_user,'public','USAGE') AS usage,"
        "has_schema_privilege(current_user,'public','CREATE') AS create,"
        "has_schema_privilege(current_user,'public',"
        "'USAGE WITH GRANT OPTION') AS usage_grantable,"
        "has_schema_privilege(current_user,'public',"
        "'CREATE WITH GRANT OPTION') AS create_grantable"
    ).fetchone()
    default_acl_count = conn.execute(
        "SELECT count(*) AS count FROM pg_default_acl d "
        "CROSS JOIN LATERAL aclexplode(d.defaclacl) x "
        "WHERE x.grantee='noteai_admin_runtime'::regrole"
    ).fetchone()["count"]
    role_policies = conn.execute(
        "SELECT policyname FROM pg_policies "
        "WHERE schemaname='public' AND ("
        "coalesce(qual,'') LIKE '%noteai_admin_runtime%' "
        "OR coalesce(with_check,'') LIKE '%noteai_admin_runtime%') "
        "ORDER BY policyname"
    ).fetchall()
    expected_policies = {
        "noteai_payment_orders_read_v1",
        "noteai_payment_refunds_read_v1",
        "noteai_payment_events_read_v1",
        "noteai_payment_cash_read_v1",
        "noteai_payment_entitlement_read_v1",
        "noteai_payment_positions_read_v1",
        "noteai_payment_consumptions_read_v1",
        "noteai_payment_reconciliation_runs_read_v1",
        "noteai_payment_reconciliation_items_read_v1",
        "noteai_payment_settlements_read_v1",
        "noteai_admin_sessions_runtime_v1",
        "noteai_system_settings_admin_read_v1",
        "noteai_ai_outbox_admin_read_v1",
        "noteai_ai_settlement_select_v1",
    }
    role_policies_exact = (
        {row["policyname"] for row in role_policies} == expected_policies
        and len(role_policies) == len(expected_policies)
    )
    settings_policy_rows = conn.execute(
        "SELECT schemaname,tablename,policyname,permissive,roles,cmd,qual,with_check "
        "FROM pg_policies WHERE schemaname='public' "
        "AND policyname='noteai_system_settings_admin_read_v1'"
    ).fetchall()
    expected_settings_qual = (
        "((CURRENT_USER = 'noteai_admin_runtime'::name) AND (is_secret = 0) "
        "AND (key = ANY (ARRAY['model_registry'::text, "
        "'crawler_config'::text])))"
    )
    settings_policy_exact = (
        len(settings_policy_rows) == 1
        and settings_policy_rows[0]["schemaname"] == "public"
        and settings_policy_rows[0]["tablename"] == "system_settings"
        and settings_policy_rows[0]["policyname"]
        == "noteai_system_settings_admin_read_v1"
        and settings_policy_rows[0]["permissive"] == "PERMISSIVE"
        and list(settings_policy_rows[0]["roles"]) == ["public"]
        and settings_policy_rows[0]["cmd"] == "SELECT"
        and settings_policy_rows[0]["qual"] == expected_settings_qual
        and settings_policy_rows[0]["with_check"] is None
    )
    migration_select = conn.execute(
        "SELECT has_table_privilege(current_user,'schema_migrations','SELECT') AS allowed"
    ).fetchone()["allowed"]
    settings = conn.execute(
        "SELECT key,is_secret FROM system_settings ORDER BY key"
    ).fetchall()
    tuple_writes = conn.execute(
        "SELECT coalesce(sum(n_tup_ins+n_tup_upd+n_tup_del),0)::bigint AS writes "
        "FROM pg_stat_xact_user_tables"
    ).fetchone()["writes"]
    xid = identity["xid"]
    expected_attrs = {
        "rolsuper": False, "rolinherit": False, "rolcreaterole": False,
        "rolcreatedb": False, "rolcanlogin": True, "rolreplication": False,
        "rolbypassrls": False,
    }
    visible_setting_keys = {row["key"] for row in settings}
    settings_ok = (
        visible_setting_keys <= {"model_registry", "crawler_config"}
        and len(visible_setting_keys) == len(settings)
        and all(int(row["is_secret"]) == 0 for row in settings)
    )
    ok = (
        default_ro == "off" and tx_ro == "on"
        and identity["session_user"] == "noteai_admin_runtime"
        and identity["current_user"] == "noteai_admin_runtime" and xid is None
        and dict(attrs) == expected_attrs
        and len(tables) == 56 and table_checks == 392
        and table_allow == 27 and table_deny == 365
        and table_mismatch == 0 and table_grantable == 0
        and column_mismatch == 0 and column_grantable == 0
        and len(sequences) == 5 and sequence_checks == 15
        and sequence_allowed == 0 and sequence_grantable == 0
        and membership_exact
        and ownership == 0
        and functions["executable"] == 0 and functions["grantable"] == 0
        and functions["secdef"] == 0 and default_acl_count == 0
        and database_acl["connect"] is True
        and database_acl["create"] is False and database_acl["temp"] is False
        and database_acl["connect_grantable"] is False
        and database_acl["create_grantable"] is False
        and database_acl["temp_grantable"] is False
        and schema_acl["usage"] is True and schema_acl["create"] is False
        and schema_acl["usage_grantable"] is False
        and schema_acl["create_grantable"] is False
        and role_policies_exact
        and settings_policy_exact
        and migration_select is False and settings_ok and tuple_writes == 0
    )
    out = {
        "status": "PASS" if ok else "FAILED",
        "default_transaction_read_only": default_ro,
        "transaction_read_only": tx_ro,
        "runtime_role_exact": identity["session_user"] == identity["current_user"] == "noteai_admin_runtime",
        "xid_unassigned": xid is None,
        "role_attributes_exact": dict(attrs) == expected_attrs,
        "table_count": len(tables),
        "table_privilege_check_count": table_checks,
        "table_allow_count": table_allow,
        "table_deny_count": table_deny,
        "table_mismatch_count": table_mismatch,
        "table_grantable_count": table_grantable,
        "column_privilege_check_count": column_checks,
        "column_allow_count": column_allow,
        "column_mismatch_count": column_mismatch,
        "column_grantable_count": column_grantable,
        "sequence_count": len(sequences),
        "sequence_privilege_check_count": sequence_checks,
        "sequence_allowed_count": sequence_allowed,
        "sequence_grantable_count": sequence_grantable,
        "runtime_membership_count": len(memberships),
        "runtime_management_membership_exact": membership_exact,
        "outgoing_membership_count": sum(
            row["member_name"] == "noteai_admin_runtime" for row in memberships
        ),
        "incoming_management_membership_count": sum(
            row["granted_name"] == "noteai_admin_runtime" for row in memberships
        ),
        "ownership_count": ownership,
        "function_count": functions["total"],
        "function_execute_count": functions["executable"],
        "function_grantable_count": functions["grantable"],
        "security_definer_execute_count": functions["secdef"],
        "default_acl_entry_count": default_acl_count,
        "database_connect": database_acl["connect"],
        "database_create": database_acl["create"],
        "database_temp": database_acl["temp"],
        "database_grantable_count": sum(
            bool(database_acl[key])
            for key in ("connect_grantable","create_grantable","temp_grantable")
        ),
        "schema_usage": schema_acl["usage"],
        "schema_create": schema_acl["create"],
        "schema_grantable_count": sum(
            bool(schema_acl[key])
            for key in ("usage_grantable","create_grantable")
        ),
        "runtime_rls_policy_count": len(role_policies),
        "runtime_rls_policies_exact": role_policies_exact,
        "system_settings_rls_policy_exact": settings_policy_exact,
        "schema_migrations_select": migration_select,
        "visible_system_setting_count": len(settings),
        "visible_system_settings_exact": settings_ok,
        "transaction_tuple_write_count": tuple_writes,
    }
finally:
    try:
        conn.execute("ROLLBACK")
    finally:
        conn.close()
print(json.dumps(out,sort_keys=True,separators=(",",":")))
'''


SESSION_SNAPSHOT_SOURCE = r'''
import json, os
import psycopg
from psycopg.rows import dict_row
conn=psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row)
conn.autocommit=True
try:
    conn.execute("BEGIN READ ONLY")
    conn.execute("SELECT pg_stat_clear_snapshot()")
    count=conn.execute("SELECT count(*) AS count FROM admin_sessions").fetchone()["count"]
    stats=conn.execute(
        "SELECT n_tup_ins,n_tup_del FROM pg_stat_user_tables "
        "WHERE schemaname='public' AND relname='admin_sessions'"
    ).fetchone()
    out={"count":count,"inserted":stats["n_tup_ins"],"deleted":stats["n_tup_del"]}
finally:
    try: conn.execute("ROLLBACK")
    finally: conn.close()
print(json.dumps(out,sort_keys=True,separators=(",",":")))
'''


SESSION_TOKEN_SNAPSHOT_SOURCE = r'''
import hashlib, json, os, sys
import psycopg
raw=sys.stdin.read()
digest=hashlib.sha256(raw.encode("utf-8")).hexdigest()
conn=psycopg.connect(os.environ["DATABASE_URL"])
conn.autocommit=True
try:
    conn.execute("BEGIN READ ONLY")
    row=conn.execute(
        "SELECT count(*) FILTER (WHERE token=%s) AS raw_count,"
        "count(*) FILTER (WHERE token=%s) AS digest_count "
        "FROM admin_sessions",
        (raw,digest),
    ).fetchone()
    xid=conn.execute("SELECT txid_current_if_assigned()").fetchone()[0]
    out={
        "raw_count":row[0],
        "digest_count":row[1],
        "xid_unassigned":xid is None,
    }
finally:
    try: conn.execute("ROLLBACK")
    finally: conn.close()
print(json.dumps(out,sort_keys=True,separators=(",",":")))
'''


SIDE_EFFECT_SNAPSHOT_SOURCE = r'''
import json, os
import psycopg
from psycopg.rows import dict_row
conn=psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row)
conn.autocommit=True
try:
    conn.execute("BEGIN READ ONLY")
    conn.execute("SELECT pg_stat_clear_snapshot()")
    out=conn.execute(
        "SELECT "
        "(SELECT coalesce(sum(n_tup_ins+n_tup_upd+n_tup_del),0)::bigint "
        " FROM pg_stat_user_tables WHERE relname<>'admin_sessions') "
        " AS business_tuple_writes,"
        "(SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        " WHERE n.nspname='public' AND c.relkind='r') AS table_count,"
        "(SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        " WHERE n.nspname='public' AND c.relkind='S') AS sequence_count,"
        "(SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
        " WHERE n.nspname='public') AS function_count,"
        "(SELECT count(*) FROM pg_policies WHERE schemaname='public') AS policy_count,"
        "(SELECT count(*) FROM pg_roles) AS role_count"
    ).fetchone()
    out=dict(out)
    out["xid_unassigned"]=(
        conn.execute("SELECT txid_current_if_assigned()").fetchone()[0] is None
    )
finally:
    try: conn.execute("ROLLBACK")
    finally: conn.close()
print(json.dumps(out,sort_keys=True,separators=(",",":")))
'''


LOGIN_SOURCE = r'''
import json, os, urllib.error, urllib.request
def call(path,method="GET",body=None,token=""):
    data=None if body is None else json.dumps(body).encode()
    headers={"Content-Type":"application/json"}
    if token: headers["Authorization"]="Bearer "+token
    req=urllib.request.Request("http://127.0.0.1:8001"+path,data=data,headers=headers,method=method)
    try:
        with urllib.request.urlopen(req,timeout=8) as r:
            return r.status,json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code,None
user=os.environ.get("ADMIN_USERNAME","noteai_admin")
password=os.environ["ADMIN_PASSWORD"]
unauth,_=call("/admin/me")
wrong,_=call("/admin/login","POST",{"username":user,"password":password+"-invalid"})
good,payload=call("/admin/login","POST",{"username":user,"password":password})
token=payload.get("token","") if isinstance(payload,dict) else ""
print(json.dumps({"unauth":unauth,"wrong":wrong,"good":good,"token":token},separators=(",",":")))
'''


DEFAULT_RO_SOURCE = r'''
import json, os
import psycopg
conn=psycopg.connect(os.environ["DATABASE_URL"])
conn.autocommit=True
try:
    default=conn.execute("SHOW default_transaction_read_only").fetchone()[0]
    conn.execute("BEGIN READ ONLY")
    tx=conn.execute("SHOW transaction_read_only").fetchone()[0]
    xid=conn.execute("SELECT txid_current_if_assigned()").fetchone()[0]
finally:
    try: conn.execute("ROLLBACK")
    finally: conn.close()
print(json.dumps({"default":default,"transaction":tx,"xid_unassigned":xid is None},separators=(",",":")))
'''


def session_snapshot(container: str) -> dict:
    return docker_exec_python(container, SESSION_SNAPSHOT_SOURCE)


def session_token_snapshot(container: str, token: str) -> dict:
    result = run(
        [
            "docker",
            "exec",
            "-i",
            container,
            "python",
            "-c",
            SESSION_TOKEN_SNAPSHOT_SOURCE,
        ],
        input_bytes=token.encode("utf-8"),
        capture=True,
    )
    lines = result.stdout.decode("utf-8").splitlines()
    if not lines:
        raise RuntimeError("session_token_output")
    value = json.loads(lines[-1])
    if not isinstance(value, dict):
        raise RuntimeError("session_token_shape")
    return value


def side_effect_snapshot(container: str) -> dict:
    return docker_exec_python(container, SIDE_EFFECT_SNAPSHOT_SOURCE)


def container_process_count(container: str) -> int:
    raw = run(
        ["docker", "top", container, "-eo", "pid"],
        capture=True,
    ).stdout.decode("utf-8").splitlines()
    if len(raw) < 2:
        raise RuntimeError("container_process_shape")
    return len(raw) - 1


def observe_side_effect_outcome(
    container: str,
    before: dict,
    process_before: int,
    rounds: int = 8,
) -> dict:
    after = {}
    catalog_keys = {
        "table_count",
        "sequence_count",
        "function_count",
        "policy_count",
        "role_count",
    }
    catalog_changed = False
    business_delta = 0
    for _ in range(rounds):
        time.sleep(0.25)
        after = side_effect_snapshot(container)
        business_delta = int(after["business_tuple_writes"]) - int(
            before["business_tuple_writes"]
        )
        catalog_changed = catalog_changed or any(
            after[key] != before[key] for key in catalog_keys
        )
    process_after = container_process_count(container)
    data_entry_count = len(list(CANARY_DATA.iterdir()))
    exact = (
        business_delta == 0
        and not catalog_changed
        and process_after == process_before
        and data_entry_count == 0
        and after.get("xid_unassigned") is True
    )
    return {
        "exact": exact,
        "observation_rounds": rounds,
        "database_business_write_count": (
            business_delta if business_delta >= 0 else None
        ),
        "business_tuple_stat_delta": business_delta,
        "catalog_changed": catalog_changed,
        "process_count_before": process_before,
        "process_count_after": process_after,
        "process_count_delta": process_after - process_before,
        "data_entry_count": data_entry_count,
        "side_effect_detected_count": sum(
            (
                business_delta != 0,
                catalog_changed,
                process_after != process_before,
                data_entry_count != 0,
            )
        ),
    }


def load_token() -> str:
    if not regular_root(TOKEN_FILE, 0o600):
        raise RuntimeError("token_file")
    token = TOKEN_FILE.read_text(encoding="utf-8")
    if not token.startswith("admin_") or len(token) < 30:
        raise RuntimeError("token_shape")
    return token


def save_token(token: str) -> None:
    if TOKEN_FILE.exists():
        raise RuntimeError("token_exists")
    temp = TOKEN_FILE.with_suffix(".tmp")
    if RUN_ROOT.exists() or temp.exists():
        raise RuntimeError("token_root_exists")
    try:
        RUN_ROOT.mkdir(mode=0o700)
        os.chmod(RUN_ROOT, 0o700)
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(token)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, TOKEN_FILE)
    except Exception:
        if temp.is_file() and not temp.is_symlink():
            temp.unlink()
        if RUN_ROOT.is_dir() and not list(RUN_ROOT.iterdir()):
            RUN_ROOT.rmdir()
        raise


def api_peer_state() -> dict:
    raw = run(
        [
            "docker",
            "ps",
            "-q",
            "--filter",
            "label=com.noteai.runtime.role=api",
        ],
        capture=True,
    ).stdout.decode("utf-8").split()
    if len(raw) != 1:
        raise RuntimeError("api_peer_count")
    item = inspect_container(raw[0])
    if not api_health_once(8000):
        raise RuntimeError("api_peer_health")
    return {
        "container_identity_sha256": id_hash(item.get("Id", "")),
        "started_at_utc": (item.get("State") or {}).get("StartedAt", ""),
        "image_config_id": item.get("Image"),
        "restart_count": item.get("RestartCount"),
        "live_ready_200": True,
    }


def systemd_state() -> dict:
    active = run(
        ["systemctl", "is-active", SERVICE],
        check=False,
        capture=True,
    )
    enabled = run(
        ["systemctl", "is-enabled", SERVICE],
        check=False,
        capture=True,
    )
    values = {}
    for key in ("Result", "NRestarts", "ExecMainStatus"):
        completed = run(
            ["systemctl", "show", SERVICE, f"--property={key}", "--value"],
            capture=True,
        )
        values[key] = completed.stdout.decode("utf-8").strip()
    return {
        "active": active.returncode == 0
        and active.stdout.decode("utf-8").strip() == "active",
        "enabled": enabled.returncode == 0
        and enabled.stdout.decode("utf-8").strip() == "enabled",
        "result": values["Result"],
        "automatic_restart_count": int(values["NRestarts"]),
        "exec_main_status": int(values["ExecMainStatus"]),
    }


def systemd_state_exact() -> dict:
    state = systemd_state()
    if state != {
        "active": True,
        "enabled": True,
        "result": "success",
        "automatic_restart_count": 0,
        "exec_main_status": 0,
    }:
        raise RuntimeError("systemd_state")
    return state


def canary_command() -> list[str]:
    tokens = unit_tokens(CANDIDATE)
    if len(tokens) != 46 or tokens[0:2] != ["/usr/bin/docker", "run"]:
        raise RuntimeError("candidate_tokens")
    if option_value(tokens, "--name") != FORMAL:
        raise RuntimeError("candidate_name")
    if option_value(tokens, "--publish") != "127.0.0.1:8001:8001":
        raise RuntimeError("candidate_port")
    env_values = [
        tokens[index + 1]
        for index, token in enumerate(tokens)
        if token == "--env"
    ]
    if any(value.startswith("PGOPTIONS=") for value in env_values):
        raise RuntimeError("candidate_pgoptions")
    tokens[1] = "create"
    replace_option(tokens, "--name", CANARY)
    replace_option(tokens, "--publish", "127.0.0.1:18001:8001")
    mount_index = tokens.index("--mount") + 1
    mount = tokens[mount_index].split(",")
    if len(mount) != 3 or any("=" not in value for value in mount):
        raise RuntimeError("candidate_mount")
    mount_values = dict(
        value.split("=", 1)
        for value in mount
    )
    if (
        set(mount_values) != {"type", "src", "dst"}
        or mount_values.get("type") != "bind"
        or mount_values.get("dst") != "/app/model/data"
    ):
        raise RuntimeError("candidate_mount")
    mount = [
        f"src={CANARY_DATA}" if value.startswith("src=") else value
        for value in mount
    ]
    tokens[mount_index] = ",".join(mount)
    label_indexes = [
        index + 1
        for index, token in enumerate(tokens)
        if token == "--label"
    ]
    service_labels = [
        index
        for index in label_indexes
        if tokens[index].startswith("com.noteai.service=")
    ]
    if len(service_labels) != 1:
        raise RuntimeError("candidate_service_label")
    tokens[service_labels[0]] = "com.noteai.service=noteai-admin-canary-stagec-5335-v3"
    return tokens


def mode_canary_start() -> dict:
    if not regular_root(CANDIDATE, 0o600) or sha256_file(CANDIDATE) != CANDIDATE_SHA:
        raise RuntimeError("candidate")
    if not regular_root(ROLLBACK, 0o600) or sha256_file(ROLLBACK) != OLD_UNIT_SHA:
        raise RuntimeError("rollback")
    if sha256_file(INSTALLED) != OLD_UNIT_SHA:
        raise RuntimeError("installed_prestate")
    if container_exists(CANARY) or CANARY_DATA.exists() or RUN_ROOT.exists():
        raise RuntimeError("canary_residue")
    formal = inspect_container(FORMAL)
    if formal.get("Image") != OLD_CONFIG or formal.get("RestartCount") != 0:
        raise RuntimeError("formal_prestate")
    if not wait_health(8001, 3):
        raise RuntimeError("formal_health")
    formal_systemd = systemd_state_exact()
    state = {
        "old_formal_identity_sha256": id_hash(formal.get("Id", "")),
        "old_formal_started_at_utc": (formal.get("State") or {}).get("StartedAt", ""),
        "api_peer_pre": api_peer_state(),
        "old_formal_systemd": formal_systemd,
    }
    command = canary_command()
    result = {
        "status": "FAILED",
        "canary_create_count": 0,
        "canary_start_count": 0,
        "canary_restart_count": 0,
        "service_mutation_count": 0,
        "database_connection_count": 0,
        "database_write_count": 0,
        "automatic_retry_count": 0,
        "command_sha256": sha256_bytes(
            b"\0".join(value.encode("utf-8") for value in command)
        ),
        "failure_cleanup_container_remove_count": 0,
        "failure_cleanup_data_directory_remove_count": 0,
        "failure_cleanup_exact": False,
    }
    try:
        CANARY_DATA.mkdir(mode=0o700)
        os.chown(CANARY_DATA, 999, 999)
        result["canary_create_count"] = 1
        run(command)
        result["canary_start_count"] = 1
        run(["docker", "start", CANARY])
        if not wait_health(18001, 3):
            raise RuntimeError("canary_health")
        state["canary_command_sha256"] = result["command_sha256"]
        state["canary_started"] = True
        save_state(state)
        result["status"] = "PASS"
        result["health_rounds"] = 3
        return result
    except Exception as exc:
        if container_exists(CANARY):
            removed = run(["docker", "rm", "-f", CANARY], check=False).returncode == 0
            result["failure_cleanup_container_remove_count"] = int(removed)
        if (
            CANARY_DATA.is_dir()
            and not CANARY_DATA.is_symlink()
            and not list(CANARY_DATA.iterdir())
        ):
            CANARY_DATA.rmdir()
            result["failure_cleanup_data_directory_remove_count"] = 1
        result["failure_cleanup_exact"] = (
            not container_exists(CANARY) and not CANARY_DATA.exists()
        )
        result["connected_unknown_count"] = int(not result["failure_cleanup_exact"])
        raise StageFailure(result, exc)


def mode_canary_validate() -> dict:
    state = load_state()
    if state.get("canary_started") is not True or not successful_result("canary-start"):
        raise RuntimeError("state")
    shape = safe_container_shape(CANARY, 18001)
    logs = bounded_log_counts(CANARY)
    if not shape["exact"] or not wait_health(18001, 3):
        raise RuntimeError("canary_identity")
    if any(logs[key] for key in logs if key != "bytes_reviewed"):
        raise RuntimeError("canary_logs")
    entries = list(CANARY_DATA.iterdir())
    if entries:
        raise RuntimeError("canary_data")
    return {
        "status": "PASS",
        "health_rounds": 3,
        "live_200_count": 3,
        "ready_200_count": 3,
        "ready_payload_exact_count": 3,
        "container": shape,
        "bounded_logs": logs,
        "canary_data_entry_count": 0,
        "database_connection_count": 0,
        "database_write_count": 0,
        "provider_call_count": 0,
        "object_write_count": 0,
    }


def mode_acl_audit() -> dict:
    if not successful_result("canary-validate"):
        raise RuntimeError("canary_validation")
    if not wait_health(18001, 1):
        raise RuntimeError("canary_health")
    audit = docker_exec_python(CANARY, ACL_AUDIT_SOURCE)
    if audit.get("status") != "PASS":
        raise RuntimeError("acl_matrix")
    return {
        "status": "PASS",
        "audit": audit,
        "database_connection_count": 1,
        "read_only_transaction_count": 1,
        "database_rollback_count": 1,
        "database_write_count": 0,
        "business_value_read_count": 0,
    }


def cleanup_failed_session(
    token: str,
    baseline: dict | None,
    result: dict,
) -> None:
    result["failure_cleanup_attempted"] = True
    try:
        logout_status, _ = http_json(
            18001,
            "/admin/logout",
            method="POST",
            body={},
            token=token,
        )
        replay_status = http_json(18001, "/admin/me", token=token)[0]
        token_storage = session_token_snapshot(CANARY, token)
        result["session_audit_connection_count"] += 1
        cleanup_after = {}
        if baseline is not None:
            for _ in range(10):
                cleanup_after = session_snapshot(CANARY)
                result["session_audit_connection_count"] += 1
                if (
                    cleanup_after.get("count") == baseline["count"]
                    and cleanup_after.get("inserted") == baseline["inserted"] + 1
                    and cleanup_after.get("deleted") == baseline["deleted"] + 1
                ):
                    break
                time.sleep(0.2)
        cleanup_exact = (
            logout_status == 200
            and replay_status == 403
            and token_storage
            == {
                "raw_count": 0,
                "digest_count": 0,
                "xid_unassigned": True,
            }
            and baseline is not None
            and cleanup_after.get("count") == baseline["count"]
            and cleanup_after.get("inserted") == baseline["inserted"] + 1
            and cleanup_after.get("deleted") == baseline["deleted"] + 1
        )
        result["failure_cleanup_exact"] = cleanup_exact
        if not cleanup_exact:
            result["connected_unknown_count"] = 1
            return
        result["task_session_delete_count"] = 1
        result["task_session_residue_count"] = 0
        if (
            regular_root(TOKEN_FILE, 0o600)
            and TOKEN_FILE.read_text(encoding="utf-8") == token
        ):
            TOKEN_FILE.unlink()
            if RUN_ROOT.is_dir() and not list(RUN_ROOT.iterdir()):
                RUN_ROOT.rmdir()
            else:
                result["connected_unknown_count"] = 1
    except Exception as exc:
        result["connected_unknown_count"] = 1


def mode_session_open() -> dict:
    if not successful_result("acl-audit"):
        raise RuntimeError("acl_missing")
    result = {
        "status": "FAILED",
        "unauthenticated_me_status": 403,
        "wrong_login_status": 401,
        "successful_login_count": 0,
        "successful_login_status": 0,
        "task_session_insert_count": 0,
        "task_session_delete_count": 0,
        "task_session_residue_count": 0,
        "token_persisted_in_task_evidence": False,
        "token_digest_persisted_in_task_evidence": False,
        "token_file_mode": 600,
        "session_audit_connection_count": 0,
        "database_session_write_count": 0,
        "database_business_write_count": None,
        "provider_call_count": None,
        "process_spawn_count": None,
        "failure_cleanup_attempted": False,
        "failure_cleanup_exact": False,
        "connected_unknown_count": 0,
    }
    baseline = None
    token = ""
    login_attempted = False
    login_succeeded = False
    side_effect_before = None
    process_before = None
    side_effect_observation = None
    try:
        baseline = session_snapshot(CANARY)
        result["session_audit_connection_count"] += 1
        login_attempted = True
        login = docker_exec_python(CANARY, LOGIN_SOURCE)
        if (
            login.get("unauth") != 403
            or login.get("wrong") != 401
            or login.get("good") != 200
        ):
            raise RuntimeError("login_status")
        token = login.pop("token", "")
        login_succeeded = True
        result.update(
            {
                "successful_login_count": 1,
                "successful_login_status": 200,
                "task_session_insert_count": 1,
                "task_session_residue_count": 1,
                "database_session_write_count": 1,
            }
        )
        save_token(token)
        token_storage = session_token_snapshot(CANARY, token)
        result["session_audit_connection_count"] += 1
        if token_storage != {
            "raw_count": 0,
            "digest_count": 1,
            "xid_unassigned": True,
        }:
            raise RuntimeError("token_storage")
        me_status, me = http_json(18001, "/admin/me", token=token)
        cap_status, cap = http_json(18001, "/admin/capabilities", token=token)
        expected_capabilities = {
            "business_mutation": False,
            "prompt_mutation": False,
            "model_mutation": False,
            "crawler_control": False,
            "tracking_requeue": False,
        }
        if (
            me_status != 200
            or not isinstance(me, dict)
            or cap_status != 200
            or not isinstance(cap, dict)
            or cap.get("mode") != "production_read_only"
            or cap.get("read_only") is not True
            or cap.get("capabilities") != expected_capabilities
            or cors_allow_origin(18001, "/admin/capabilities", token) is not None
        ):
            raise RuntimeError("authenticated_contract")
        side_effect_before = side_effect_snapshot(CANARY)
        result["session_audit_connection_count"] += 1
        process_before = container_process_count(CANARY)
        if list(CANARY_DATA.iterdir()):
            raise RuntimeError("canary_data_before_http")
        overview_status, overview = http_json(18001, "/admin/overview", token=token)
        if (
            overview_status != 200
            or not isinstance(overview, dict)
            or set(overview) != {"users", "finance", "usage", "system"}
            or not isinstance(overview.get("system"), dict)
            or overview["system"].get("database_ok") is not True
            or overview["system"].get("database_backend") != "postgresql"
            or not isinstance(overview["system"].get("ai_runtime"), dict)
        ):
            raise RuntimeError("overview_shape")
        users_status, users_payload = http_json(
            18001,
            "/admin/users?page=1&page_size=5",
            token=token,
        )
        if (
            users_status != 200
            or not isinstance(users_payload, dict)
            or set(users_payload) != {"total", "page", "page_size", "users"}
            or not isinstance(users_payload.get("total"), int)
            or users_payload.get("page") != 1
            or users_payload.get("page_size") != 5
            or not isinstance(users_payload.get("users"), list)
        ):
            raise RuntimeError("users_shape")
        forbidden_user_keys = {
            "phone",
            "email",
            "password",
            "password_hash",
            "password_salt",
            "payment_ref",
        }
        user_rows = users_payload["users"]
        if any(
            not isinstance(row, dict)
            or not {"id", "phone_masked", "email_masked"}.issubset(row)
            or bool(forbidden_user_keys.intersection(row))
            for row in user_rows
        ):
            raise RuntimeError("users_masking")
        detail_checked = False
        if user_rows:
            user_id = urllib.parse.quote(str(user_rows[0]["id"]), safe="")
            detail_status, detail = http_json(
                18001,
                f"/admin/users/{user_id}",
                token=token,
            )
            if (
                detail_status != 200
                or not isinstance(detail, dict)
                or not isinstance(detail.get("user"), dict)
                or not {
                    "phone_masked",
                    "email_masked",
                }.issubset(detail["user"])
                or bool(forbidden_user_keys.intersection(detail["user"]))
                or not isinstance(detail.get("credit_txns"), list)
                or any(
                    not isinstance(row, dict) or "payment_ref" in row
                    for row in detail["credit_txns"]
                )
            ):
                raise RuntimeError("user_detail_masking")
            detail_checked = True
        usage_status, usage = http_json(
            18001,
            "/admin/usage-stats",
            token=token,
        )
        if (
            usage_status != 200
            or not isinstance(usage, dict)
            or set(usage)
            != {
                "by_operation",
                "top_users",
                "daily_trend",
                "by_source",
                "by_model",
                "cache",
                "coverage",
            }
        ):
            raise RuntimeError("usage_shape")
        ai_status, ai = http_json(18001, "/admin/ai-operations", token=token)
        if (
            ai_status != 200
            or not isinstance(ai, dict)
            or set(ai)
            != {
                "operations",
                "settlements",
                "outbox",
                "oldest_queued_at",
                "raw_payload_included",
                "provider_called",
            }
            or ai.get("raw_payload_included") is not False
            or ai.get("provider_called") is not False
        ):
            raise RuntimeError("ai_shape")
        read_shapes = {
            "overview": True,
            "users": True,
            "usage": True,
            "ai_operations": True,
        }
        mutations = (
            (
                "POST",
                "/admin/users/synthetic/adjust",
                {"action": "add_credits", "value": "1"},
                409,
            ),
            ("POST", "/admin/tracked-notes/synthetic/trigger-check", {}, 409),
            ("PUT", "/admin/prompts/synthetic", {"content": "synthetic"}, 409),
            ("POST", "/admin/prompts/synthetic/rollback", {"version": 1}, 409),
            ("POST", "/admin/models/v0.4-composite/deploy", {}, 409),
            ("POST", "/admin/models/train", {"description": "synthetic"}, 409),
            ("POST", "/admin/crawler/toggle", {"enabled": True}, 409),
            ("POST", "/admin/crawler/run", {"limit": 1}, 409),
            ("POST", "/admin/crawler/update-cookie", {}, 410),
        )
        statuses = []
        for method, path, body, expected in mutations:
            status, _ = http_json(
                18001,
                path,
                method=method,
                body=body,
                token=token,
            )
            statuses.append(status)
            if status != expected:
                raise RuntimeError("mutation_status")
        side_effect_observation = observe_side_effect_outcome(
            CANARY,
            side_effect_before,
            process_before,
        )
        result["session_audit_connection_count"] += side_effect_observation[
            "observation_rounds"
        ]
        if not side_effect_observation["exact"]:
            result.update(
                {
                    "database_business_write_count": side_effect_observation[
                        "database_business_write_count"
                    ],
                    "process_spawn_count": (
                        max(0, side_effect_observation["process_count_delta"])
                    ),
                    "object_write_count": side_effect_observation[
                        "data_entry_count"
                    ],
                    "side_effect_observation": side_effect_observation,
                }
            )
            raise RuntimeError("http_side_effect_detected")
        process_after = side_effect_observation["process_count_after"]
        mutation_logs = bounded_log_counts(CANARY)
        if any(
            mutation_logs[key]
            for key in mutation_logs
            if key != "bytes_reviewed"
        ):
            raise RuntimeError("mutation_log_safety")
        result.update(
            {
                "database_business_write_count": 0,
                "provider_call_count": 0,
                "provider_call_zero_basis": (
                    "guarded_http_contract_and_bound_revision"
                ),
                "process_spawn_count": 0,
                "object_write_count": 0,
                "side_effect_observation": side_effect_observation,
            }
        )
        after = {}
        after_poll_count = 0
        for after_poll_count in range(1, 11):
            after = session_snapshot(CANARY)
            result["session_audit_connection_count"] += 1
            if (
                after.get("count") == baseline["count"] + 1
                and after.get("inserted") == baseline["inserted"] + 1
                and after.get("deleted") == baseline["deleted"]
            ):
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("session_insert")
        state = load_state()
        state["session_baseline"] = baseline
        state["session_after_login"] = after
        state["session_open"] = True
        save_state(state)
        result.update(
            {
                "status": "PASS",
                "capability_mode": "production_read_only",
                "mutation_capability_false_count": 5,
                "untrusted_cors_origin_denied": True,
                "read_shape_count": len(read_shapes),
                "masked_user_row_count": len(user_rows),
                "user_detail_masking_checked": detail_checked,
                "mutation_409_count": statuses.count(409),
                "cookie_410_count": statuses.count(410),
                "after_login_snapshot_poll_count": after_poll_count,
                "token_database_raw_count": token_storage["raw_count"],
                "token_database_digest_count": token_storage["digest_count"],
                "database_business_write_count": 0,
                "provider_call_count": 0,
                "provider_call_zero_basis": (
                    "guarded_http_contract_and_bound_revision"
                ),
                "process_spawn_count": 0,
                "process_count_before": process_before,
                "process_count_after": process_after,
                "side_effect_observation_rounds": 8,
                "side_effect_snapshot_exact": True,
                "side_effect_observation": side_effect_observation,
                "object_write_count": 0,
                "bounded_logs": mutation_logs,
            }
        )
        return result
    except Exception as exc:
        if isinstance(side_effect_before, dict) and isinstance(process_before, int):
            try:
                if not isinstance(side_effect_observation, dict):
                    side_effect_observation = observe_side_effect_outcome(
                        CANARY,
                        side_effect_before,
                        process_before,
                    )
                    result[
                        "session_audit_connection_count"
                    ] += side_effect_observation["observation_rounds"]
                result.update(
                    {
                        "database_business_write_count": side_effect_observation[
                            "database_business_write_count"
                        ],
                        "process_spawn_count": max(
                            0,
                            side_effect_observation["process_count_delta"],
                        ),
                        "object_write_count": side_effect_observation[
                            "data_entry_count"
                        ],
                        "side_effect_observation": side_effect_observation,
                    }
                )
            except Exception:
                result["connected_unknown_count"] = 1
        if login_attempted and not login_succeeded:
            result["connected_unknown_count"] = 1
        if login_succeeded:
            cleanup_failed_session(token, baseline, result)
        raise StageFailure(result, exc)


def install_unit(source: Path) -> None:
    temp = INSTALLED.with_suffix(".service.noteai-admin-stagec.tmp")
    if temp.exists():
        raise RuntimeError("unit_temp_exists")
    try:
        shutil.copyfile(source, temp)
        os.chown(temp, 0, 0)
        os.chmod(temp, 0o644)
        with temp.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temp, INSTALLED)
    except Exception as exc:
        if temp.is_file() and not temp.is_symlink():
            temp.unlink()
        raise


def wait_formal_identity(previous_hash: str, expected_image: str) -> dict:
    for poll in range(1, 81):
        try:
            item = inspect_container(FORMAL)
        except Exception:
            time.sleep(0.25)
            continue
        current_hash = id_hash(item.get("Id", ""))
        if (
            current_hash != previous_hash
            and item.get("Image") == expected_image
            and (item.get("State") or {}).get("Running") is True
        ):
            return {"poll": poll, "item": item}
        time.sleep(0.25)
    raise RuntimeError("formal_visibility")


def rollback_service(previous_hash: str) -> bool:
    try:
        if not regular_root(ROLLBACK, 0o600) or sha256_file(ROLLBACK) != OLD_UNIT_SHA:
            return False
        install_unit(ROLLBACK)
        run(["systemctl", "daemon-reload"])
        run(["systemctl", "restart", SERVICE])
        wait_formal_identity(previous_hash, OLD_CONFIG)
        return (
            sha256_file(INSTALLED) == OLD_UNIT_SHA
            and wait_health(8001, 3)
            and systemd_state_exact()["active"] is True
        )
    except Exception:
        return False


def mode_promote() -> dict:
    state = load_state()
    if state.get("session_open") is not True or not successful_result("session-open"):
        raise RuntimeError("session_state")
    token = load_token()
    if http_json(18001, "/admin/me", token=token)[0] != 200:
        raise RuntimeError("canary_token")
    if sha256_file(INSTALLED) != OLD_UNIT_SHA:
        raise RuntimeError("installed_prestate")
    if not regular_root(CANDIDATE, 0o600) or sha256_file(CANDIDATE) != CANDIDATE_SHA:
        raise RuntimeError("candidate")
    old_item = inspect_container(FORMAL)
    old_hash = id_hash(old_item.get("Id", ""))
    result = {
        "status": "FAILED",
        "unit_mutation_started": False,
        "service_mutation_started": False,
        "promotion_restart_count": 0,
        "rollback_required": False,
        "rollback_restart_count": 0,
        "rollback_result": "NOT_REQUIRED",
        "automatic_retry_count": 0,
        "database_write_count": 0,
        "provider_call_count": 0,
        "object_write_count": 0,
    }
    try:
        install_unit(CANDIDATE)
        result["unit_mutation_started"] = True
        run(["systemctl", "daemon-reload"])
        result["service_mutation_started"] = True
        result["promotion_restart_count"] = 1
        run(["systemctl", "restart", SERVICE])
        visibility = wait_formal_identity(old_hash, NEW_CONFIG)
        if not wait_health(8001, 3):
            raise RuntimeError("formal_health")
        promoted_systemd = systemd_state_exact()
        if http_json(8001, "/admin/me", token=token)[0] != 200:
            raise RuntimeError("formal_token")
        if http_json(18001, "/admin/me", token=token)[0] != 200:
            raise RuntimeError("canary_token_after_promotion")
        state["promotion_complete"] = True
        state["promoted_formal_identity_sha256"] = id_hash(
            visibility["item"].get("Id", "")
        )
        save_state(state)
        result.update(
            {
                "status": "PASS",
                "service_outcome": "KNOWN_ACTIVE",
                "visibility_poll": visibility["poll"],
                "health_rounds": 3,
                "same_token_formal_valid": True,
                "same_token_canary_valid": True,
                "installed_unit_sha256": sha256_file(INSTALLED),
                "systemd": promoted_systemd,
            }
        )
        return result
    except Exception as exc:
        if result["unit_mutation_started"]:
            result["rollback_required"] = True
            result["rollback_restart_count"] = 1
            ok = rollback_service(old_hash)
            result["rollback_result"] = "PASS" if ok else "FAILED"
            result["service_outcome"] = "KNOWN_ROLLED_BACK" if ok else "UNKNOWN"
            result["connected_unknown_count"] = int(not ok)
        raise StageFailure(result, exc)


def mode_formal_validate() -> dict:
    state = load_state()
    if state.get("promotion_complete") is not True or not successful_result("promote"):
        raise RuntimeError("promotion_state")
    token = load_token()
    current = inspect_container(FORMAL)
    current_hash = id_hash(current.get("Id", ""))
    result = {
        "status": "FAILED",
        "validation_started": False,
        "rollback_required": False,
        "rollback_restart_count": 0,
        "rollback_result": "NOT_REQUIRED",
        "database_connection_count": 0,
        "database_write_count": 0,
        "connected_unknown_count": 0,
    }
    try:
        result["validation_started"] = True
        shape = safe_container_shape(FORMAL, 8001)
        logs = bounded_log_counts(FORMAL)
        database = docker_exec_python(FORMAL, DEFAULT_RO_SOURCE)
        result["database_connection_count"] = 1
        formal_systemd = systemd_state_exact()
        if (
            sha256_file(INSTALLED) != CANDIDATE_SHA
            or not shape["exact"]
            or not wait_health(8001, 3)
            or any(logs[key] for key in logs if key != "bytes_reviewed")
            or database
            != {"default": "off", "transaction": "on", "xid_unassigned": True}
            or http_json(8001, "/admin/me", token=token)[0] != 200
            or http_json(18001, "/admin/me", token=token)[0] != 200
        ):
            raise RuntimeError("formal_validation")
        result.update(
            {
                "status": "PASS",
                "health_rounds": 3,
                "container": shape,
                "bounded_logs": logs,
                "systemd": formal_systemd,
                "database": database,
                "read_only_transaction_count": 1,
                "database_rollback_count": 1,
                "same_token_formal_valid": True,
                "same_token_canary_valid": True,
            }
        )
        return result
    except Exception as exc:
        result["rollback_required"] = True
        result["rollback_restart_count"] = 1
        ok = rollback_service(current_hash)
        result["rollback_result"] = "PASS" if ok else "FAILED"
        result["service_outcome"] = "KNOWN_ROLLED_BACK" if ok else "UNKNOWN"
        result["connected_unknown_count"] = int(not ok)
        raise StageFailure(result, exc)


def mode_explicit_restart() -> dict:
    state = load_state()
    if not successful_result("formal-validate"):
        raise RuntimeError("formal_result")
    if sha256_file(INSTALLED) != CANDIDATE_SHA:
        raise RuntimeError("installed_prestate")
    token = load_token()
    before = inspect_container(FORMAL)
    before_hash = id_hash(before.get("Id", ""))
    result = {
        "status": "FAILED",
        "service_mutation_started": False,
        "explicit_restart_count": 0,
        "automatic_retry_count": 0,
        "rollback_required": False,
        "rollback_restart_count": 0,
        "rollback_result": "NOT_REQUIRED",
    }
    try:
        result["service_mutation_started"] = True
        result["explicit_restart_count"] = 1
        run(["systemctl", "restart", SERVICE])
        visibility = wait_formal_identity(before_hash, NEW_CONFIG)
        if (
            not wait_health(8001, 3)
            or http_json(8001, "/admin/me", token=token)[0] != 200
            or http_json(18001, "/admin/me", token=token)[0] != 200
        ):
            raise RuntimeError("restart_acceptance")
        restarted_systemd = systemd_state_exact()
        state["explicit_restart_complete"] = True
        state["final_formal_identity_sha256"] = id_hash(
            visibility["item"].get("Id", "")
        )
        save_state(state)
        result.update(
            {
                "status": "PASS",
                "service_outcome": "KNOWN_ACTIVE",
                "visibility_poll": visibility["poll"],
                "container_identity_changed": True,
                "health_rounds": 3,
                "same_token_formal_valid": True,
                "same_token_canary_valid": True,
                "systemd": restarted_systemd,
            }
        )
        return result
    except Exception as exc:
        result["rollback_required"] = True
        result["rollback_restart_count"] = 1
        ok = rollback_service(before_hash)
        result["rollback_result"] = "PASS" if ok else "FAILED"
        result["service_outcome"] = "KNOWN_ROLLED_BACK" if ok else "UNKNOWN"
        result["connected_unknown_count"] = int(not ok)
        raise StageFailure(result, exc)


def mode_session_close() -> dict:
    state = load_state()
    if (
        state.get("explicit_restart_complete") is not True
        or not successful_result("explicit-restart")
    ):
        raise RuntimeError("restart_state")
    token = load_token()
    baseline = state["session_baseline"]
    formal_hash = id_hash(inspect_container(FORMAL).get("Id", ""))
    before = session_snapshot(FORMAL)
    if (
        before.get("count") != baseline["count"] + 1
        or before.get("inserted") != baseline["inserted"] + 1
        or before.get("deleted") != baseline["deleted"]
    ):
        raise RuntimeError("session_prestate")
    result = {
        "status": "FAILED",
        "successful_logout_count": 0,
        "logout_status": 0,
        "formal_replay_status": 0,
        "canary_replay_status": 0,
        "task_session_insert_count": 1,
        "task_session_delete_count": 0,
        "task_session_residue_count": 1,
        "other_session_delta": 0,
        "token_file_count": 1,
        "token_persisted_in_task_evidence": False,
        "token_digest_persisted_in_task_evidence": False,
        "session_audit_connection_count": 1,
        "database_business_write_count": 0,
        "connected_unknown_count": 0,
        "rollback_required": False,
        "rollback_restart_count": 0,
        "rollback_result": "NOT_REQUIRED",
    }
    after = {}
    token_storage = {}
    try:
        status, payload = http_json(
            8001,
            "/admin/logout",
            method="POST",
            body={},
            token=token,
        )
        result["logout_status"] = status
        if status != 200 or not isinstance(payload, dict) or payload.get("ok") is not True:
            raise RuntimeError("logout_status")
        result["successful_logout_count"] = 1
        formal_replay = http_json(8001, "/admin/me", token=token)[0]
        canary_replay = http_json(18001, "/admin/me", token=token)[0]
        token_storage = session_token_snapshot(FORMAL, token)
        result["session_audit_connection_count"] += 1
        result["formal_replay_status"] = formal_replay
        result["canary_replay_status"] = canary_replay
        after_poll_count = 0
        for after_poll_count in range(1, 11):
            after = session_snapshot(FORMAL)
            result["session_audit_connection_count"] += 1
            if (
                after.get("count") == baseline["count"]
                and after.get("inserted") == baseline["inserted"] + 1
                and after.get("deleted") == baseline["deleted"] + 1
            ):
                break
            time.sleep(0.2)
        if (
            formal_replay != 403
            or canary_replay != 403
            or token_storage
            != {
                "raw_count": 0,
                "digest_count": 0,
                "xid_unassigned": True,
            }
            or after.get("count") != baseline["count"]
            or after.get("inserted") != baseline["inserted"] + 1
            or after.get("deleted") != baseline["deleted"] + 1
        ):
            raise RuntimeError("session_close")
        TOKEN_FILE.unlink()
        RUN_ROOT.rmdir()
        state["session_closed"] = True
        save_state(state)
        result.update(
            {
                "status": "PASS",
                "task_session_delete_count": 1,
                "task_session_residue_count": 0,
                "token_file_count": 0,
                "token_database_raw_count": 0,
                "token_database_digest_count": 0,
                "after_logout_snapshot_poll_count": after_poll_count,
            }
        )
        return result
    except Exception as exc:
        known_closed = (
            result["formal_replay_status"] == 403
            and result["canary_replay_status"] == 403
            and token_storage
            == {
                "raw_count": 0,
                "digest_count": 0,
                "xid_unassigned": True,
            }
            and after.get("count") == baseline["count"]
            and after.get("inserted") == baseline["inserted"] + 1
            and after.get("deleted") == baseline["deleted"] + 1
        )
        if known_closed:
            result["task_session_delete_count"] = 1
            result["task_session_residue_count"] = 0
            if (
                regular_root(TOKEN_FILE, 0o600)
                and TOKEN_FILE.read_text(encoding="utf-8") == token
            ):
                TOKEN_FILE.unlink()
                if RUN_ROOT.is_dir() and not list(RUN_ROOT.iterdir()):
                    RUN_ROOT.rmdir()
            result["token_file_count"] = int(TOKEN_FILE.exists())
        else:
            result["connected_unknown_count"] = 1
        result["rollback_required"] = True
        result["rollback_restart_count"] = 1
        rollback_ok = rollback_service(formal_hash)
        result["rollback_result"] = "PASS" if rollback_ok else "FAILED"
        result["service_outcome"] = (
            "KNOWN_ROLLED_BACK" if rollback_ok else "UNKNOWN"
        )
        if not rollback_ok:
            result["connected_unknown_count"] = 1
        raise StageFailure(result, exc)


def mode_cleanup() -> dict:
    state = load_state()
    if state.get("session_closed") is not True or not successful_result("session-close"):
        raise RuntimeError("session_state")
    if RUN_ROOT.exists() or TOKEN_FILE.exists():
        raise RuntimeError("token_residue")
    if not container_exists(CANARY):
        raise RuntimeError("canary_missing")
    run(["docker", "rm", "-f", CANARY])
    if container_exists(CANARY):
        raise RuntimeError("canary_remove")
    if not CANARY_DATA.is_dir() or CANARY_DATA.is_symlink():
        raise RuntimeError("canary_data_shape")
    if list(CANARY_DATA.iterdir()):
        raise RuntimeError("canary_data_not_empty")
    CANARY_DATA.rmdir()
    if run(
        ["sh", "-c", "ss -ltnH 'sport = :18001' | grep -q ."],
        check=False,
    ).returncode == 0:
        raise RuntimeError("canary_listener")
    shape = safe_container_shape(FORMAL, 8001)
    final_systemd = systemd_state_exact()
    if not shape["exact"] or not wait_health(8001, 3):
        raise RuntimeError("formal_final")
    peer_after = api_peer_state()
    peer_before = state["api_peer_pre"]
    peer_exact = peer_after == peer_before
    if not peer_exact:
        raise RuntimeError("api_peer_regression")
    state["cleanup_complete"] = True
    save_state(state)
    return {
        "status": "PASS",
        "canary_remove_count": 1,
        "canary_container_count": 0,
        "canary_listener_count": 0,
        "canary_data_directory_count": 0,
        "token_file_count": 0,
        "formal_health_rounds": 3,
        "formal_container": shape,
        "formal_systemd": final_systemd,
        "api_c_peer_non_regression": True,
        "api_c_peer": peer_after,
        "database_write_count": 0,
        "provider_call_count": 0,
        "object_write_count": 0,
        "public_traffic_change_count": 0,
    }


def failed_result_summary() -> dict:
    if not RESULTS.is_dir():
        return {
            "failed_count": 0,
            "connected_unknown_count": 0,
            "side_effect_evidence_complete": True,
            "side_effect_detected_count": 0,
            "database_business_write_count": 0,
            "provider_call_count": 0,
            "process_spawn_count": 0,
            "object_write_count": 0,
        }
    count = 0
    connected_unknown = 0
    side_effect_complete = True
    side_effect_detected = 0
    side_effect_totals = {
        "database_business_write_count": 0,
        "provider_call_count": 0,
        "process_spawn_count": 0,
        "object_write_count": 0,
    }
    for path in RESULTS.glob("*.json"):
        if not regular_root(path, 0o600):
            raise RuntimeError("abort_result_shape")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError("abort_result_json")
        if value.get("status") == "FAILED":
            count += 1
            connected_unknown += int(value.get("connected_unknown_count") or 0)
            if value.get("mode") == "session-open":
                for key in side_effect_totals:
                    observed = value.get(key)
                    if not isinstance(observed, int) or isinstance(observed, bool):
                        side_effect_complete = False
                        side_effect_totals[key] = None
                    elif side_effect_totals[key] is not None:
                        side_effect_totals[key] += observed
                observation = value.get("side_effect_observation")
                if isinstance(observation, dict):
                    side_effect_detected += int(
                        observation.get("side_effect_detected_count") or 0
                    )
                elif any(
                    value.get(key) not in (0, None)
                    for key in side_effect_totals
                ):
                    side_effect_detected += 1
    return {
        "failed_count": count,
        "connected_unknown_count": connected_unknown,
        "side_effect_evidence_complete": side_effect_complete,
        "side_effect_detected_count": side_effect_detected,
        **side_effect_totals,
    }


def abort_session_cleanup(state: dict, prior_connected_unknown: int) -> dict:
    result = {
        "token_file_found": TOKEN_FILE.exists(),
        "logout_attempt_count": 0,
        "logout_success_count": 0,
        "token_database_raw_count": 0,
        "token_database_digest_count": 0,
        "token_file_count": int(TOKEN_FILE.exists()),
        "session_cleanup_exact": False,
        "database_connection_count": 0,
    }
    if not TOKEN_FILE.exists():
        if prior_connected_unknown:
            raise RuntimeError("abort_prior_connected_unknown")
        known_closed = (
            state.get("session_open") is not True
            or (
                state.get("session_closed") is True
                and successful_result("session-close")
            )
        )
        failed_close = result_path("session-close")
        if not known_closed and regular_root(failed_close, 0o600):
            failed_value = json.loads(failed_close.read_text(encoding="utf-8"))
            known_closed = (
                isinstance(failed_value, dict)
                and failed_value.get("status") == "FAILED"
                and failed_value.get("task_session_residue_count") == 0
                and failed_value.get("token_file_count") == 0
                and failed_value.get("connected_unknown_count") == 0
            )
        if not known_closed:
            raise RuntimeError("abort_missing_token_unknown_session")
        if RUN_ROOT.is_dir() and not list(RUN_ROOT.iterdir()):
            RUN_ROOT.rmdir()
        if RUN_ROOT.exists():
            raise RuntimeError("abort_token_root_residue")
        result["token_file_count"] = 0
        result["session_cleanup_exact"] = True
        return result
    token = load_token()
    if container_exists(CANARY) and health_once(18001):
        container, port = CANARY, 18001
    elif container_exists(FORMAL) and health_once(8001):
        container, port = FORMAL, 8001
    else:
        raise RuntimeError("abort_session_endpoint")
    before = session_token_snapshot(container, token)
    result["database_connection_count"] += 1
    if before.get("raw_count") != 0 or before.get("xid_unassigned") is not True:
        raise RuntimeError("abort_token_storage")
    if before.get("digest_count") == 1:
        result["logout_attempt_count"] = 1
        status, payload = http_json(
            port,
            "/admin/logout",
            method="POST",
            body={},
            token=token,
        )
        if (
            status != 200
            or not isinstance(payload, dict)
            or payload.get("ok") is not True
        ):
            raise RuntimeError("abort_logout")
        result["logout_success_count"] = 1
    elif before.get("digest_count") != 0:
        raise RuntimeError("abort_token_cardinality")
    after = session_token_snapshot(container, token)
    result["database_connection_count"] += 1
    if after != {
        "raw_count": 0,
        "digest_count": 0,
        "xid_unassigned": True,
    }:
        raise RuntimeError("abort_session_residue")
    if http_json(port, "/admin/me", token=token)[0] != 403:
        raise RuntimeError("abort_token_replay")
    baseline = state.get("session_baseline")
    if isinstance(baseline, dict):
        global_after = session_snapshot(container)
        result["database_connection_count"] += 1
        if (
            global_after.get("count") != baseline.get("count")
            or global_after.get("inserted") != baseline.get("inserted") + 1
            or global_after.get("deleted") != baseline.get("deleted") + 1
        ):
            raise RuntimeError("abort_session_stats")
    TOKEN_FILE.unlink()
    if not RUN_ROOT.is_dir() or list(RUN_ROOT.iterdir()):
        raise RuntimeError("abort_token_root_shape")
    RUN_ROOT.rmdir()
    result.update(
        {
            "token_database_raw_count": 0,
            "token_database_digest_count": 0,
            "token_file_count": 0,
            "session_cleanup_exact": True,
        }
    )
    return result


def mode_abort() -> dict:
    failure_summary = failed_result_summary()
    failures = failure_summary["failed_count"]
    if failures < 1:
        raise RuntimeError("abort_without_failure")
    state = load_state()
    result = {
        "status": "FAILED",
        "failed_stage_result_count": failures,
        "prior_connected_unknown_count": failure_summary[
            "connected_unknown_count"
        ],
        "automatic_retry_count": 0,
        "formal_rollback_restart_count": 0,
        "canary_remove_count": 0,
        "connected_unknown_count": 0,
        "prior_failure_side_effect_evidence_complete": failure_summary[
            "side_effect_evidence_complete"
        ],
        "prior_side_effect_detected_count": failure_summary[
            "side_effect_detected_count"
        ],
        "database_business_write_count": failure_summary[
            "database_business_write_count"
        ],
        "provider_call_count": failure_summary["provider_call_count"],
        "process_spawn_count": failure_summary["process_spawn_count"],
        "object_write_count": failure_summary["object_write_count"],
        "cleanup_only": True,
        "release_accepted": False,
    }
    try:
        result["session"] = abort_session_cleanup(
            state,
            failure_summary["connected_unknown_count"],
        )
        try:
            formal = inspect_container(FORMAL)
            formal_hash = id_hash(formal.get("Id", ""))
            formal_image = formal.get("Image")
        except Exception:
            formal_hash = ""
            formal_image = ""
        installed_hash = sha256_file(INSTALLED) if INSTALLED.is_file() else ""
        if installed_hash != OLD_UNIT_SHA or formal_image != OLD_CONFIG:
            result["formal_rollback_restart_count"] = 1
            if not rollback_service(formal_hash):
                raise RuntimeError("abort_formal_rollback")
        if (
            sha256_file(INSTALLED) != OLD_UNIT_SHA
            or inspect_container(FORMAL).get("Image") != OLD_CONFIG
            or not wait_health(8001, 3)
        ):
            raise RuntimeError("abort_formal_outcome")
        result["formal_systemd"] = systemd_state_exact()
        if container_exists(CANARY):
            if run(["docker", "rm", "-f", CANARY], check=False).returncode != 0:
                raise RuntimeError("abort_canary_remove")
            result["canary_remove_count"] = 1
        if container_exists(CANARY):
            raise RuntimeError("abort_canary_residue")
        if CANARY_DATA.exists():
            if (
                not CANARY_DATA.is_dir()
                or CANARY_DATA.is_symlink()
                or list(CANARY_DATA.iterdir())
            ):
                raise RuntimeError("abort_canary_data")
            CANARY_DATA.rmdir()
        if run(
            ["sh", "-c", "ss -ltnH 'sport = :18001' | grep -q ."],
            check=False,
        ).returncode == 0:
            raise RuntimeError("abort_canary_listener")
        if RUN_ROOT.exists() or TOKEN_FILE.exists():
            raise RuntimeError("abort_token_residue")
        peer = api_peer_state()
        if isinstance(state.get("api_peer_pre"), dict):
            if peer != state["api_peer_pre"]:
                raise RuntimeError("abort_api_peer")
        prior_side_effect_safe = (
            failure_summary["side_effect_evidence_complete"] is True
            and failure_summary["side_effect_detected_count"] == 0
        )
        result.update(
            {
                "status": "PASS" if prior_side_effect_safe else "FAILED",
                "cleanup_status": "PASS",
                "service_outcome": "KNOWN_ROLLED_BACK",
                "installed_unit_sha256": sha256_file(INSTALLED),
                "formal_image_config_id": inspect_container(FORMAL).get("Image"),
                "formal_health_rounds": 3,
                "canary_container_count": 0,
                "canary_listener_count": 0,
                "canary_data_directory_count": 0,
                "token_file_count": 0,
                "api_c_peer_healthy": True,
                "prior_failure_preserved": True,
            }
        )
        if not prior_side_effect_safe:
            code = (
                "abort_prior_side_effect_detected"
                if failure_summary["side_effect_detected_count"]
                else "abort_prior_side_effect_unresolved"
            )
            raise StageFailure(result, RuntimeError(code))
        return result
    except StageFailure:
        raise
    except Exception as exc:
        result["connected_unknown_count"] = 1
        result["service_outcome"] = "UNKNOWN"
        raise StageFailure(result, exc)


MODES = {
    "canary-start": mode_canary_start,
    "canary-validate": mode_canary_validate,
    "acl-audit": mode_acl_audit,
    "session-open": mode_session_open,
    "promote": mode_promote,
    "formal-validate": mode_formal_validate,
    "explicit-restart": mode_explicit_restart,
    "session-close": mode_session_close,
    "cleanup": mode_cleanup,
    "abort": mode_abort,
}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in MODES:
        return 2
    mode = sys.argv[1]
    path = result_path(mode)
    result = {
        "schema_version": 1,
        "mode": mode,
        "status": "FAILED",
        "failure_stage_code": mode.replace("-", "_").upper(),
        "connected_unknown_count": 0,
        "automatic_retry_count": 0,
    }
    try:
        if path.exists():
            raise RuntimeError("result_exists")
        value = MODES[mode]()
        result.update(value)
        result["failure_stage_code"] = None
    except StageFailure as exc:
        result.update(exc.payload)
        result["status"] = "FAILED"
    except Exception as exc:
        result["status"] = "FAILED"
        result["failure_detail_code"] = safe_exception_code(exc)
    try:
        atomic_json(path, result)
    except Exception:
        print(
            "NOTEAI_ADMIN_STAGE_" + mode.replace("-", "_").upper() + "=RESULT_WRITE_FAILED",
            flush=True,
        )
        return 1
    print(
        "NOTEAI_ADMIN_STAGE_"
        + mode.replace("-", "_").upper()
        + "="
        + ("PASS" if result["status"] == "PASS" else "FAIL"),
        flush=True,
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
