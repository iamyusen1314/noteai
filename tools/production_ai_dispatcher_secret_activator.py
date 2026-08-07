#!/usr/bin/env python3
"""Activate, verify, reconcile, or revoke the one Dispatcher credential.

The privileged database URL is stdin-only.  The generated password is kept in
memory and in the final root-only role file; output and errors are fixed and
Secret-free.  This task is deliberately separate from the completed five-role
managed-secret activation.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, quote, unquote, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - production image owns psycopg
    psycopg = None  # type: ignore[assignment]
    sql = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]

try:
    from scripts.validate_production_env_files import (
        EnvFileValidationError,
        validate_role_env_file,
    )
    from tools import production_durable_ai_schema_0017 as schema_0017
    from tools import production_managed_secret_roles as managed_roles
except ModuleNotFoundError:  # pragma: no cover - host-local package layout
    from validate_production_env_files import (  # type: ignore[no-redef]
        EnvFileValidationError,
        validate_role_env_file,
    )
    import production_durable_ai_schema_0017 as schema_0017  # type: ignore[no-redef]
    import production_managed_secret_roles as managed_roles  # type: ignore[no-redef]


TASK_ID = "PROD-FIRST-LAUNCH-DURABLE-AI-DISPATCHER-SECRET-001"
CONFIRM_ENV = "NOTEAI_DURABLE_AI_DISPATCHER_SECRET_CONFIRM"
DISPATCHER_ROLE = "noteai_ai_dispatcher"
OWNER_ROLE = "noteai_admin"
CONTROL_ROLE = "noteai_schema_task_durable_ai_0017"
ENV_ROOT = Path("/etc/noteai")
FINAL_NAME = "ai-dispatcher.env"
TASK_NAME = ".ai-dispatcher-activation-v1"
STAGE_NAME = "ai-dispatcher.env"
EXISTING_LOGIN_ROLES = frozenset(managed_roles.TARGET_LOGIN_ROLES)
ALL_RUNTIME_ROLES = frozenset((*managed_roles.ALL_RUNTIME_ROLES, DISPATCHER_ROLE))
ALLOWED_QUERY_KEYS = frozenset(
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
PASSWORD_BYTES = 48
SCRAM_ITERATIONS = 4096


class DispatcherSecretError(RuntimeError):
    """A fixed, Secret-free activation failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _require_root() -> None:
    if os.geteuid() != 0:
        raise DispatcherSecretError("root_required")


def _safe_text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value or any(
        marker in value for marker in ("\x00", "\r", "\n")
    ):
        raise DispatcherSecretError(code)
    return value


def _validated_query(query: str) -> list[tuple[str, str]]:
    try:
        pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=True)
    except (TypeError, ValueError) as exc:
        raise DispatcherSecretError("database_url_query") from exc
    names: set[str] = set()
    for raw_name, value in pairs:
        name = raw_name.lower()
        if (
            name not in ALLOWED_QUERY_KEYS
            or name in names
            or any(marker in raw_name or marker in value for marker in ("\x00", "\r", "\n"))
        ):
            raise DispatcherSecretError("database_url_query")
        names.add(name)
    return pairs


def build_role_database_url(control_database_url: str, password: str) -> str:
    raw = _safe_text(control_database_url, "control_database_url_shape")
    secret = _safe_text(password, "password_shape")
    try:
        parsed = urlsplit(raw)
        base_user = unquote(parsed.username or "")
        _validated_query(parsed.query)
    except (TypeError, ValueError) as exc:
        raise DispatcherSecretError("control_database_url_shape") from exc
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or not base_user
        or parsed.password in (None, "")
        or not parsed.hostname
        or parsed.path in {"", "/"}
        or parsed.fragment
    ):
        raise DispatcherSecretError("control_database_url_shape")
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    port = f":{parsed.port}" if parsed.port is not None else ""
    netloc = (
        f"{quote(DISPATCHER_ROLE, safe='')}:{quote(secret, safe='')}@"
        f"{hostname}{port}"
    )
    return urlunsplit(
        (parsed.scheme, netloc, parsed.path, parsed.query, "")
    )


def _scram_verifier(password: str, *, salt: bytes | None = None) -> str:
    secret = _safe_text(password, "password_shape")
    raw_salt = salt if salt is not None else os.urandom(16)
    if not isinstance(raw_salt, bytes) or len(raw_salt) != 16:
        raise DispatcherSecretError("scram_salt")
    salted = hashlib.pbkdf2_hmac(
        "sha256",
        secret.encode("utf-8"),
        raw_salt,
        SCRAM_ITERATIONS,
    )
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    return (
        f"SCRAM-SHA-256${SCRAM_ITERATIONS}:"
        f"{base64.b64encode(raw_salt).decode('ascii')}$"
        f"{base64.b64encode(stored_key).decode('ascii')}:"
        f"{base64.b64encode(server_key).decode('ascii')}"
    )


def _connect(database_url: str, application_name: str) -> Any:
    if psycopg is None:
        raise DispatcherSecretError("psycopg_unavailable")
    _safe_text(database_url, "database_url_shape")
    try:
        return psycopg.connect(
            database_url,
            row_factory=dict_row,
            connect_timeout=10,
            application_name=application_name,
        )
    except BaseException as exc:
        raise DispatcherSecretError("database_connect") from exc


def _activate_owner(conn: Any) -> None:
    identity = conn.execute(
        "SELECT session_user AS session_name,current_user AS current_name"
    ).fetchone()
    if (
        identity is None
        or str(identity["session_name"]) != CONTROL_ROLE
        or str(identity["session_name"]) in ALL_RUNTIME_ROLES
    ):
        raise DispatcherSecretError("executor_identity")
    if str(identity["current_name"]) != OWNER_ROLE:
        conn.execute(f"SET LOCAL ROLE {OWNER_ROLE}")
    identity = conn.execute(
        "SELECT session_user AS session_name,current_user AS current_name"
    ).fetchone()
    if identity is None or str(identity["current_name"]) != OWNER_ROLE:
        raise DispatcherSecretError("owner_activation")


def validate_database_contract(
    conn: Any,
    *,
    expected_dispatcher_login: bool,
) -> dict[str, Any]:
    contract = schema_0017.source_contract()
    schema_0017._verify_postconditions(conn, contract)
    roles = conn.execute(
        "SELECT rolname,rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,"
        "rolinherit,rolreplication,rolbypassrls FROM pg_roles "
        "WHERE rolname = ANY(%s) ORDER BY rolname",
        (list((*EXISTING_LOGIN_ROLES, DISPATCHER_ROLE)),),
    ).fetchall()
    if {str(row["rolname"]) for row in roles} != {
        *EXISTING_LOGIN_ROLES,
        DISPATCHER_ROLE,
    }:
        raise DispatcherSecretError("runtime_roles")
    for row in roles:
        role = str(row["rolname"])
        expected_login = (
            expected_dispatcher_login
            if role == DISPATCHER_ROLE
            else True
        )
        if bool(row["rolcanlogin"]) is not expected_login or any(
            bool(row[name])
            for name in (
                "rolsuper",
                "rolcreatedb",
                "rolcreaterole",
                "rolinherit",
                "rolreplication",
                "rolbypassrls",
            )
        ):
            raise DispatcherSecretError("runtime_role_attributes")
    memberships = conn.execute(
        "SELECT granted.rolname AS granted_name,"
        "member.rolname AS member_name,m.admin_option,"
        "(to_jsonb(m)->>'inherit_option')::boolean AS inherit_option,"
        "(to_jsonb(m)->>'set_option')::boolean AS set_option "
        "FROM pg_auth_members m "
        "JOIN pg_roles granted ON granted.oid=m.roleid "
        "JOIN pg_roles member ON member.oid=m.member "
        "WHERE granted.rolname=%s OR member.rolname=%s",
        (DISPATCHER_ROLE, DISPATCHER_ROLE),
    ).fetchall()
    if (
        len(memberships) != 1
        or str(memberships[0]["granted_name"]) != DISPATCHER_ROLE
        or str(memberships[0]["member_name"]) != OWNER_ROLE
        or not bool(memberships[0]["admin_option"])
        or memberships[0]["inherit_option"] is not False
        or memberships[0]["set_option"] is not False
    ):
        raise DispatcherSecretError("dispatcher_membership")
    ownership = conn.execute(
        "SELECT ((SELECT COUNT(*) FROM pg_class o JOIN pg_roles r "
        "ON r.oid=o.relowner WHERE r.rolname=%s) + "
        "(SELECT COUNT(*) FROM pg_namespace o JOIN pg_roles r "
        "ON r.oid=o.nspowner WHERE r.rolname=%s) + "
        "(SELECT COUNT(*) FROM pg_proc o JOIN pg_roles r "
        "ON r.oid=o.proowner WHERE r.rolname=%s))::integer AS count",
        (DISPATCHER_ROLE, DISPATCHER_ROLE, DISPATCHER_ROLE),
    ).fetchone()
    sessions = conn.execute(
        "SELECT COUNT(*)::integer AS count FROM pg_stat_activity "
        "WHERE usename=%s AND pid<>pg_backend_pid()",
        (DISPATCHER_ROLE,),
    ).fetchone()
    if (
        ownership is None
        or int(ownership["count"] or 0) != 0
        or sessions is None
        or int(sessions["count"] or 0) != 0
    ):
        raise DispatcherSecretError("dispatcher_residue")
    return {
        "migration_count": 17,
        "existing_login_role_count": len(EXISTING_LOGIN_ROLES),
        "dispatcher_login": expected_dispatcher_login,
        "management_membership_count": 1,
        "owned_object_count": 0,
        "active_session_count": 0,
    }


def _database_preflight(control_database_url: str) -> dict[str, Any]:
    conn = _connect(control_database_url, "noteai_dispatcher_secret_preflight")
    try:
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            conn.execute("SET LOCAL statement_timeout='30s'")
            conn.execute("SET LOCAL lock_timeout='5s'")
            _activate_owner(conn)
            return validate_database_contract(
                conn,
                expected_dispatcher_login=False,
            )
    finally:
        conn.close()


def _safe_directory(path: Path, *, expected_uid: int) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise DispatcherSecretError("env_root_missing") from exc
    expected_gid = expected_uid if expected_uid == 0 else os.getegid()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != expected_uid
        or metadata.st_gid != expected_gid
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise DispatcherSecretError("env_root_metadata")


def _empty_task_directory(path: Path, *, expected_uid: int) -> None:
    try:
        metadata = path.lstat()
        entries = list(path.iterdir())
    except OSError as exc:
        raise DispatcherSecretError("task_root_metadata") from exc
    expected_gid = expected_uid if expected_uid == 0 else os.getegid()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != expected_uid
        or metadata.st_gid != expected_gid
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or entries
    ):
        raise DispatcherSecretError("task_root_metadata")


def _parse_dispatcher_file(
    path: Path,
    *,
    expected_uid: int,
    expected_nlinks: frozenset[int] = frozenset({1}),
) -> str:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise DispatcherSecretError("dispatcher_file_missing") from exc
    expected_gid = expected_uid if expected_uid == 0 else os.getegid()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != expected_uid
        or metadata.st_gid != expected_gid
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink not in expected_nlinks
    ):
        raise DispatcherSecretError("dispatcher_file_metadata")
    try:
        validate_role_env_file("ai_dispatcher", path)
        lines = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    except (OSError, UnicodeError, EnvFileValidationError) as exc:
        raise DispatcherSecretError("dispatcher_file_contract") from exc
    if len(lines) != 1 or not lines[0].startswith("DATABASE_URL="):
        raise DispatcherSecretError("dispatcher_file_contract")
    database_url = _safe_text(
        lines[0].split("=", 1)[1],
        "dispatcher_database_url_shape",
    )
    try:
        parsed = urlsplit(database_url)
        _validated_query(parsed.query)
    except (TypeError, ValueError) as exc:
        raise DispatcherSecretError("dispatcher_database_url_shape") from exc
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or unquote(parsed.username or "") != DISPATCHER_ROLE
        or parsed.password in (None, "")
        or any(marker in unquote(parsed.password or "") for marker in ("\x00", "\r", "\n"))
        or not parsed.hostname
        or parsed.path in {"", "/"}
        or parsed.fragment
    ):
        raise DispatcherSecretError("dispatcher_database_url_shape")
    return database_url


def _write_stage(
    task_root: Path,
    database_url: str,
    *,
    expected_uid: int,
) -> Path:
    try:
        task_root.mkdir(mode=0o700)
        if os.geteuid() == 0:
            os.chown(task_root, expected_uid, expected_uid)
    except OSError as exc:
        raise DispatcherSecretError("task_root_create") from exc
    stage = task_root / STAGE_NAME
    descriptor = -1
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(stage, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        if os.geteuid() == 0:
            os.fchown(descriptor, expected_uid, expected_uid)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(f"DATABASE_URL={database_url}\n")
            handle.flush()
            os.fsync(handle.fileno())
        directory = os.open(task_root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise DispatcherSecretError("stage_write") from exc
    _parse_dispatcher_file(stage, expected_uid=expected_uid)
    return stage


def _publish_stage(
    stage: Path,
    final: Path,
    task_root: Path,
    *,
    expected_uid: int,
) -> None:
    if final.exists() or final.is_symlink():
        raise DispatcherSecretError("final_preexists")
    try:
        os.link(stage, final, follow_symlinks=False)
        directory = os.open(final.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        stage.unlink()
        task_root.rmdir()
        directory = os.open(final.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as exc:
        raise DispatcherSecretError("connected_known_file_promotion") from exc
    _parse_dispatcher_file(final, expected_uid=expected_uid)


def _apply_role(conn: Any, verifier: str) -> dict[str, Any]:
    if sql is None:  # pragma: no cover
        raise DispatcherSecretError("psycopg_unavailable")
    try:
        with conn.transaction():
            conn.execute("SET LOCAL statement_timeout='30s'")
            conn.execute("SET LOCAL lock_timeout='5s'")
            conn.execute("SET LOCAL idle_in_transaction_session_timeout='60s'")
            _activate_owner(conn)
            conn.execute(
                "SELECT pg_advisory_xact_lock("
                "hashtext('noteai_managed_secrets_v1'))"
            )
            validate_database_contract(conn, expected_dispatcher_login=False)
            conn.execute(
                sql.SQL(
                    "ALTER ROLE {} LOGIN PASSWORD {} VALID UNTIL 'infinity'"
                ).format(
                    sql.Identifier(DISPATCHER_ROLE),
                    sql.Literal(verifier),
                )
            )
            verification = validate_database_contract(
                conn,
                expected_dispatcher_login=True,
            )
    except DispatcherSecretError:
        raise
    except BaseException as exc:
        raise DispatcherSecretError("connected_unknown_role_apply") from exc
    return {
        "transaction_committed": True,
        "role_attribute_writes": 1,
        "password_writes": 1,
        "membership_writes": 0,
        "acl_writes": 0,
        "schema_writes": 0,
        "business_row_writes": 0,
        "verification": verification,
    }


def _audit_dispatcher_login(database_url: str) -> dict[str, Any]:
    conn = _connect(database_url, "noteai_dispatcher_secret_verify")
    try:
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            conn.execute("SET LOCAL statement_timeout='15s'")
            row = conn.execute(
                "SELECT session_user AS session_name,current_user AS current_name,"
                "current_role AS role_name,"
                "current_setting('transaction_read_only') AS read_only,"
                "r.rolcanlogin,r.rolsuper,r.rolcreatedb,r.rolcreaterole,"
                "r.rolinherit,r.rolreplication,r.rolbypassrls,"
                "(SELECT COUNT(*) FROM pg_auth_members m "
                "WHERE m.member=r.oid)::integer AS incoming_membership_count,"
                "has_database_privilege(current_user,current_database(),'CONNECT') "
                "AS db_connect,"
                "has_database_privilege(current_user,current_database(),'CREATE') "
                "AS db_create,"
                "has_database_privilege(current_user,current_database(),'TEMP') "
                "AS db_temp,"
                "has_schema_privilege(current_user,'public','USAGE') AS schema_usage,"
                "has_schema_privilege(current_user,'public','CREATE') AS schema_create,"
                "has_table_privilege(current_user,'schema_migrations','SELECT') "
                "AS ledger_read FROM pg_roles r WHERE r.rolname=current_user"
            ).fetchone()
    finally:
        conn.close()
    if (
        row is None
        or str(row["session_name"]) != DISPATCHER_ROLE
        or str(row["current_name"]) != DISPATCHER_ROLE
        or str(row["role_name"]) != DISPATCHER_ROLE
        or str(row["read_only"]).lower() != "on"
        or not bool(row["rolcanlogin"])
        or any(
            bool(row[name])
            for name in (
                "rolsuper",
                "rolcreatedb",
                "rolcreaterole",
                "rolinherit",
                "rolreplication",
                "rolbypassrls",
                "db_create",
                "db_temp",
                "schema_create",
                "ledger_read",
            )
        )
        or not bool(row["db_connect"])
        or not bool(row["schema_usage"])
        or int(row["incoming_membership_count"] or 0) != 0
    ):
        raise DispatcherSecretError("dispatcher_login_contract")
    return {
        "connection_count": 1,
        "read_only_transaction_count": 1,
        "unexpected_elevation_count": 0,
        "incoming_membership_count": 0,
        "ledger_read_count": 0,
    }


def _credential_rejected(database_url: str) -> None:
    if psycopg is None:
        raise DispatcherSecretError("psycopg_unavailable")
    try:
        conn = psycopg.connect(database_url, connect_timeout=10)
    except BaseException as exc:
        sqlstate = getattr(exc, "sqlstate", None) or getattr(
            getattr(exc, "diag", None), "sqlstate", None
        )
        message = str(exc).lower()
        if sqlstate in {"28P01", "28000"} or any(
            marker in message
            for marker in (
                "password authentication failed",
                "is not permitted to log in",
            )
        ):
            return
        raise DispatcherSecretError("credential_rejection_unknown") from exc
    else:
        conn.close()
        raise DispatcherSecretError("credential_still_accepted")


def preflight_activation(
    control_database_url: str,
    *,
    env_root: Path = ENV_ROOT,
    task_root: Path | None = None,
    expected_uid: int = 0,
    require_root: bool = True,
) -> dict[str, Any]:
    if require_root:
        _require_root()
    resolved_task = task_root or env_root / TASK_NAME
    _safe_directory(env_root, expected_uid=expected_uid)
    final = env_root / FINAL_NAME
    if final.exists() or final.is_symlink():
        raise DispatcherSecretError("final_preexists")
    if resolved_task.exists() or resolved_task.is_symlink():
        raise DispatcherSecretError("task_residue")
    verification = _database_preflight(control_database_url)
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "preflight_verified",
        "incident_class": "CONNECTED_KNOWN",
        "database_outcome": "READ_ONLY_VERIFIED",
        "database_connections": 1,
        "database_transactions": 1,
        "database_writes": 0,
        "staged_files": 0,
        "promoted_files": 0,
        "service_changes": 0,
        "provider_calls": 0,
        "secret_values_emitted": 0,
        "verification": verification,
    }


def apply_activation(
    control_database_url: str,
    *,
    env_root: Path = ENV_ROOT,
    task_root: Path | None = None,
    expected_uid: int = 0,
    require_root: bool = True,
    password_factory: Callable[[int], str] = secrets.token_urlsafe,
) -> dict[str, Any]:
    resolved_task = task_root or env_root / TASK_NAME
    preflight_activation(
        control_database_url,
        env_root=env_root,
        task_root=resolved_task,
        expected_uid=expected_uid,
        require_root=require_root,
    )
    password = password_factory(PASSWORD_BYTES)
    if not isinstance(password, str) or not (48 <= len(password) <= 128):
        raise DispatcherSecretError("password_shape")
    database_url = build_role_database_url(control_database_url, password)
    stage = _write_stage(
        resolved_task,
        database_url,
        expected_uid=expected_uid,
    )
    conn = None
    try:
        conn = _connect(
            control_database_url,
            "noteai_dispatcher_secret_apply",
        )
        role_result = _apply_role(conn, _scram_verifier(password))
    except DispatcherSecretError as exc:
        if exc.code == "database_connect":
            stage.unlink(missing_ok=True)
            try:
                resolved_task.rmdir()
            except OSError:
                pass
            raise DispatcherSecretError(
                "connected_known_apply_connect_failed"
            ) from exc
        raise
    finally:
        if conn is not None:
            conn.close()
    final = env_root / FINAL_NAME
    _publish_stage(
        stage,
        final,
        resolved_task,
        expected_uid=expected_uid,
    )
    try:
        audit = _audit_dispatcher_login(database_url)
    except DispatcherSecretError as exc:
        raise DispatcherSecretError(
            "connected_known_committed_login_audit"
        ) from exc
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "activated",
        "incident_class": "CONNECTED_KNOWN",
        "database_outcome": "COMMITTED",
        "database_connections": 3,
        "database_transactions": 3,
        "database_write_transactions": 1,
        "read_only_transactions": 2,
        "role_attribute_writes": role_result["role_attribute_writes"],
        "password_writes": role_result["password_writes"],
        "membership_writes": 0,
        "acl_writes": 0,
        "schema_writes": 0,
        "business_row_writes": 0,
        "staged_files": 1,
        "promoted_files": 1,
        "read_only_audits": audit["read_only_transaction_count"],
        "service_changes": 0,
        "provider_calls": 0,
        "secret_values_emitted": 0,
    }


def verify_activation(
    *,
    env_root: Path = ENV_ROOT,
    expected_uid: int = 0,
    require_root: bool = True,
) -> dict[str, Any]:
    if require_root:
        _require_root()
    database_url = _parse_dispatcher_file(
        env_root / FINAL_NAME,
        expected_uid=expected_uid,
    )
    audit = _audit_dispatcher_login(database_url)
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "verified",
        "forced_read_only": True,
        "file_count": 1,
        **audit,
        "service_changes": 0,
        "provider_calls": 0,
        "secret_values_emitted": 0,
    }


def _read_dispatcher_login(control_database_url: str) -> bool:
    conn = _connect(control_database_url, "noteai_dispatcher_secret_reconcile")
    try:
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            conn.execute("SET LOCAL statement_timeout='30s'")
            _activate_owner(conn)
            row = conn.execute(
                "SELECT rolcanlogin FROM pg_roles WHERE rolname=%s",
                (DISPATCHER_ROLE,),
            ).fetchone()
            if row is None:
                raise DispatcherSecretError("dispatcher_role_missing")
            observed = bool(row["rolcanlogin"])
            validate_database_contract(
                conn,
                expected_dispatcher_login=observed,
            )
            return observed
    finally:
        conn.close()


def reconcile_activation(
    control_database_url: str,
    *,
    env_root: Path = ENV_ROOT,
    task_root: Path | None = None,
    expected_uid: int = 0,
    require_root: bool = True,
) -> dict[str, Any]:
    if require_root:
        _require_root()
    resolved_task = task_root or env_root / TASK_NAME
    final = env_root / FINAL_NAME
    stage = resolved_task / STAGE_NAME
    candidates = [path for path in (final, stage) if path.exists()]
    linked_pair = False
    if len(candidates) == 2:
        try:
            final_stat = final.lstat()
            stage_stat = stage.lstat()
        except OSError as exc:
            raise DispatcherSecretError("reconcile_file_state") from exc
        linked_pair = (
            final_stat.st_dev == stage_stat.st_dev
            and final_stat.st_ino == stage_stat.st_ino
            and final_stat.st_nlink == 2
            and stage_stat.st_nlink == 2
        )
        if not linked_pair:
            raise DispatcherSecretError("reconcile_file_state")
        database_url = _parse_dispatcher_file(
            final,
            expected_uid=expected_uid,
            expected_nlinks=frozenset({2}),
        )
    elif len(candidates) == 1:
        database_url = _parse_dispatcher_file(
            candidates[0],
            expected_uid=expected_uid,
        )
    else:
        raise DispatcherSecretError("reconcile_file_state")
    login = _read_dispatcher_login(control_database_url)
    if login:
        try:
            _audit_dispatcher_login(database_url)
            if linked_pair:
                stage.unlink()
                resolved_task.rmdir()
                directory = os.open(env_root, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            elif candidates[0] == stage:
                _publish_stage(
                    stage,
                    final,
                    resolved_task,
                    expected_uid=expected_uid,
                )
            elif resolved_task.exists() or resolved_task.is_symlink():
                _empty_task_directory(
                    resolved_task,
                    expected_uid=expected_uid,
                )
                resolved_task.rmdir()
                directory = os.open(env_root, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        except BaseException as exc:
            raise DispatcherSecretError(
                "connected_known_reconcile_required"
            ) from exc
        return {
            "schema_version": 1,
            "task_id": TASK_ID,
            "status": "reconciled_committed",
            "incident_class": "CONNECTED_KNOWN",
            "database_outcome": "COMMITTED",
            "automatic_retries": 0,
            "promoted_files": int(linked_pair or candidates[0] == stage),
            "secret_values_emitted": 0,
        }
    try:
        _credential_rejected(database_url)
        for path in candidates:
            path.unlink()
        if resolved_task.exists():
            resolved_task.rmdir()
        directory = os.open(env_root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException as exc:
        raise DispatcherSecretError(
            "connected_known_reconcile_rolled_back_cleanup"
        ) from exc
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "reconciled_not_committed",
        "incident_class": "CONNECTED_KNOWN",
        "database_outcome": "ROLLED_BACK",
        "automatic_retries": 0,
        "promoted_files": 0,
        "secret_values_emitted": 0,
    }


def _units_inactive(*, runner: Callable[..., subprocess.CompletedProcess[str]]) -> None:
    for unit in (
        "noteai-ai-dispatcher.service",
        "noteai-ai-dispatcher-acceptance.service",
    ):
        try:
            completed = runner(
                ["/usr/bin/systemctl", "is-active", unit],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise DispatcherSecretError("unit_state_unknown") from exc
        if completed.returncode == 0 or completed.stdout.strip() not in {
            "inactive",
            "unknown",
        }:
            raise DispatcherSecretError("dispatcher_unit_active")


def _revoke_role(control_database_url: str) -> None:
    if sql is None:  # pragma: no cover
        raise DispatcherSecretError("psycopg_unavailable")
    conn = _connect(control_database_url, "noteai_dispatcher_secret_rollback")
    try:
        with conn.transaction():
            conn.execute("SET LOCAL statement_timeout='30s'")
            conn.execute("SET LOCAL lock_timeout='5s'")
            _activate_owner(conn)
            conn.execute(
                "SELECT pg_advisory_xact_lock("
                "hashtext('noteai_managed_secrets_v1'))"
            )
            validate_database_contract(conn, expected_dispatcher_login=True)
            conn.execute(
                sql.SQL("ALTER ROLE {} NOLOGIN PASSWORD NULL").format(
                    sql.Identifier(DISPATCHER_ROLE)
                )
            )
            validate_database_contract(conn, expected_dispatcher_login=False)
    except DispatcherSecretError:
        raise
    except BaseException as exc:
        raise DispatcherSecretError("connected_unknown_role_revoke") from exc
    finally:
        conn.close()


def rollback_activation(
    control_database_url: str,
    *,
    env_root: Path = ENV_ROOT,
    task_root: Path | None = None,
    expected_uid: int = 0,
    require_root: bool = True,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    if require_root:
        _require_root()
    _units_inactive(runner=runner)
    resolved_task = task_root or env_root / TASK_NAME
    final = env_root / FINAL_NAME
    stage = resolved_task / STAGE_NAME
    candidates = [path for path in (final, stage) if path.exists()]
    if len(candidates) == 2:
        final_stat = final.lstat()
        stage_stat = stage.lstat()
        if not (
            final_stat.st_dev == stage_stat.st_dev
            and final_stat.st_ino == stage_stat.st_ino
            and final_stat.st_nlink == 2
            and stage_stat.st_nlink == 2
        ):
            raise DispatcherSecretError("rollback_file_state")
        database_url = _parse_dispatcher_file(
            final,
            expected_uid=expected_uid,
            expected_nlinks=frozenset({2}),
        )
    elif len(candidates) == 1:
        database_url = _parse_dispatcher_file(
            candidates[0],
            expected_uid=expected_uid,
        )
    else:
        raise DispatcherSecretError("rollback_file_state")
    _revoke_role(control_database_url)
    try:
        if _read_dispatcher_login(control_database_url):
            raise DispatcherSecretError("rollback_login_state")
        _credential_rejected(database_url)
        for path in candidates:
            path.unlink()
        if resolved_task.exists():
            resolved_task.rmdir()
        directory = os.open(env_root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException as exc:
        raise DispatcherSecretError(
            "connected_known_committed_role_revoke_reconcile"
        ) from exc
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "rolled_back",
        "incident_class": "CONNECTED_KNOWN",
        "database_outcome": "COMMITTED",
        "database_transactions": 1,
        "role_attribute_writes": 1,
        "password_clears": 1,
        "file_removals": 1,
        "old_credential_rejected": True,
        "service_changes": 0,
        "provider_calls": 0,
        "secret_values_emitted": 0,
    }


def _protected_payload() -> dict[str, Any]:
    try:
        payload = json.load(sys.stdin)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DispatcherSecretError("protected_payload_parse") from exc
    if not isinstance(payload, dict) or set(payload) != {"control_database_url"}:
        raise DispatcherSecretError("protected_payload_shape")
    _safe_text(payload["control_database_url"], "control_database_url_shape")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--preflight", action="store_true")
    action.add_argument("--apply", action="store_true")
    action.add_argument("--verify", action="store_true")
    action.add_argument("--reconcile", action="store_true")
    action.add_argument("--rollback", action="store_true")
    args = parser.parse_args(argv)
    protected_actions = args.apply or args.reconcile or args.rollback
    if protected_actions and os.environ.get(CONFIRM_ENV) != TASK_ID:
        print(
            "production_ai_dispatcher_secret_activator=FAIL "
            "code=confirmation_missing",
            file=sys.stderr,
        )
        return 2
    try:
        if args.verify:
            result = verify_activation()
        else:
            payload = _protected_payload()
            control_database_url = payload["control_database_url"]
            if args.preflight:
                result = preflight_activation(control_database_url)
            elif args.apply:
                result = apply_activation(control_database_url)
            elif args.reconcile:
                result = reconcile_activation(control_database_url)
            else:
                result = rollback_activation(control_database_url)
    except DispatcherSecretError as exc:
        print(
            f"production_ai_dispatcher_secret_activator=FAIL code={exc.code}",
            file=sys.stderr,
        )
        return 1
    except BaseException:
        print(
            "production_ai_dispatcher_secret_activator=FAIL code=unexpected",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
