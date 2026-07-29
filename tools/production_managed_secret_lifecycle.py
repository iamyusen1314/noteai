#!/usr/bin/env python3
"""Rotate or revoke one production runtime credential without value output.

Install this same file as both ``noteai-rotate-production-secrets`` and
``noteai-revoke-production-secrets``.  The non-Secret role and confirmation
are argv inputs; the privileged DSN and new password are stdin-only JSON.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit

try:
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - deployment dependency
    psycopg = None  # type: ignore[assignment]
    sql = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]


TASK_ID = "PROD-FIRST-LAUNCH-MANAGED-SECRETS-LIFECYCLE-001"
MIGRATION_OWNER_ROLE = "noteai_admin"
ENV_ROOT = Path("/etc/noteai")
ROLE_FILES = {
    "noteai_admin_runtime": "admin.env",
    "noteai_ai_worker": "ai-worker.env",
    "noteai_payment": "payment.env",
    "noteai_xhs_tracking": "xhs-tracking.env",
    "noteai_xhs_trends": "xhs-trends.env",
}
PASSWORD_PATTERN = re.compile(r"[A-Za-z0-9_-]{48,128}")
ROTATE_BASENAME = "noteai-rotate-production-secrets"
REVOKE_BASENAME = "noteai-revoke-production-secrets"


class ManagedSecretLifecycleError(RuntimeError):
    """A fixed, Secret-free lifecycle failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _require_root() -> None:
    if os.geteuid() != 0:
        raise ManagedSecretLifecycleError("root_required")


def _private_regular(path: Path) -> None:
    try:
        file_stat = path.lstat()
    except OSError as exc:
        raise ManagedSecretLifecycleError("role_file_missing") from exc
    if (
        not stat.S_ISREG(file_stat.st_mode)
        or stat.S_ISLNK(file_stat.st_mode)
        or file_stat.st_uid != 0
        or file_stat.st_gid != 0
        or stat.S_IMODE(file_stat.st_mode) != 0o600
    ):
        raise ManagedSecretLifecycleError("role_file_metadata")


def _env_rows(path: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    names: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ManagedSecretLifecycleError("role_file_read") from exc
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        if "=" not in stripped:
            raise ManagedSecretLifecycleError("role_file_shape")
        name, value = stripped.split("=", 1)
        name = name.strip()
        if not name or name in names:
            raise ManagedSecretLifecycleError("role_file_shape")
        names.add(name)
        rows.append((name, value))
    return rows


def _parse_role_dsn(role: str, database_url: str) -> Any:
    try:
        parsed = urlsplit(database_url)
        username = unquote(parsed.username or "")
    except (TypeError, ValueError) as exc:
        raise ManagedSecretLifecycleError("database_url_shape") from exc
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or username != role
        or parsed.password in (None, "")
        or not parsed.hostname
        or parsed.path in {"", "/"}
        or parsed.fragment
    ):
        raise ManagedSecretLifecycleError("database_url_shape")
    return parsed


def _replace_password(role: str, database_url: str, password: str) -> str:
    parsed = _parse_role_dsn(role, database_url)
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    port = f":{parsed.port}" if parsed.port is not None else ""
    netloc = f"{quote(role, safe='')}:{quote(password, safe='')}@{hostname}{port}"
    return urlunsplit(
        (parsed.scheme, netloc, parsed.path, parsed.query, "")
    )


def _write_stage(path: Path, rows: list[tuple[str, str]]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            os.fchown(descriptor, 0, 0)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor = -1
                for name, value in rows:
                    handle.write(f"{name}={value}\n")
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except OSError as exc:
        raise ManagedSecretLifecycleError("stage_write") from exc


def _connect(database_url: str, application_name: str) -> Any:
    if psycopg is None:
        raise ManagedSecretLifecycleError("psycopg_unavailable")
    return psycopg.connect(
        database_url,
        row_factory=dict_row,
        connect_timeout=10,
        application_name=application_name,
    )


def _alter_role(
    control_database_url: str,
    role: str,
    *,
    password: str | None,
) -> None:
    if sql is None:
        raise ManagedSecretLifecycleError("psycopg_unavailable")
    connected = False
    try:
        conn = _connect(
            control_database_url,
            "noteai_managed_secret_lifecycle",
        )
        connected = True
        try:
            with conn.transaction():
                conn.execute("SET LOCAL statement_timeout='30s'")
                conn.execute("SET LOCAL lock_timeout='5s'")
                identity = conn.execute(
                    "SELECT session_user AS session_name,"
                    "current_user AS current_name"
                ).fetchone()
                if identity is None or str(identity["session_name"]) in {
                    *ROLE_FILES,
                    "noteai_app",
                    "noteai_xhs",
                }:
                    raise ManagedSecretLifecycleError("executor_identity")
                if str(identity["current_name"]) != MIGRATION_OWNER_ROLE:
                    conn.execute(f"SET LOCAL ROLE {MIGRATION_OWNER_ROLE}")
                row = conn.execute(
                    "SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,"
                    "rolinherit,rolreplication,rolbypassrls "
                    "FROM pg_roles WHERE rolname=%s",
                    (role,),
                ).fetchone()
                if (
                    row is None
                    or not bool(row["rolcanlogin"])
                    or any(
                        bool(row[key])
                        for key in (
                            "rolsuper",
                            "rolcreatedb",
                            "rolcreaterole",
                            "rolinherit",
                            "rolreplication",
                            "rolbypassrls",
                        )
                    )
                ):
                    raise ManagedSecretLifecycleError("role_precondition")
                conn.execute(
                    "SELECT pg_advisory_xact_lock("
                    "hashtext('noteai_managed_secrets_v1'))"
                )
                statement = (
                    sql.SQL(
                        "ALTER ROLE {} LOGIN PASSWORD {} "
                        "VALID UNTIL 'infinity'"
                    ).format(sql.Identifier(role), sql.Literal(password))
                    if password is not None
                    else sql.SQL("ALTER ROLE {} NOLOGIN").format(
                        sql.Identifier(role)
                    )
                )
                conn.execute(statement)
        finally:
            conn.close()
    except ManagedSecretLifecycleError:
        raise
    except BaseException as exc:
        code = (
            "connected_unknown_role_change"
            if connected
            else "pre_connect_control_database"
        )
        raise ManagedSecretLifecycleError(code) from exc


def _verify_login(database_url: str, role: str) -> None:
    connected = False
    try:
        conn = _connect(database_url, "noteai_managed_secret_verify")
        connected = True
        try:
            with conn.transaction():
                conn.execute("SET TRANSACTION READ ONLY")
                row = conn.execute(
                    "SELECT current_user AS current_name,"
                    "current_setting('transaction_read_only') AS read_only"
                ).fetchone()
        finally:
            conn.close()
    except BaseException as exc:
        code = (
            "connected_known_new_login_failed"
            if connected
            else "connected_known_new_login_rejected"
        )
        raise ManagedSecretLifecycleError(code) from exc
    if (
        row is None
        or str(row["current_name"]) != role
        or str(row["read_only"]).lower() != "on"
    ):
        raise ManagedSecretLifecycleError(
            "connected_known_new_login_contract"
        )


def _verify_rejected(database_url: str) -> None:
    try:
        conn = _connect(database_url, "noteai_managed_secret_rejection")
    except BaseException as exc:
        sqlstate = getattr(exc, "sqlstate", None) or getattr(
            getattr(exc, "diag", None),
            "sqlstate",
            None,
        )
        fixed_message = str(exc).lower()
        if sqlstate in {"28P01", "28000"} or any(
            marker in fixed_message
            for marker in (
                "password authentication failed",
                "is not permitted to log in",
            )
        ):
            return
        raise ManagedSecretLifecycleError(
            "connected_known_rejection_unclassified"
        ) from exc
    else:
        conn.close()
        raise ManagedSecretLifecycleError(
            "connected_known_old_credential_accepted"
        )


def rotate(
    role: str,
    protected_payload: dict[str, Any],
    *,
    env_root: Path = ENV_ROOT,
) -> dict[str, Any]:
    _require_root()
    if set(protected_payload) != {"control_database_url", "new_password"}:
        raise ManagedSecretLifecycleError("protected_payload_shape")
    new_password = protected_payload["new_password"]
    if (
        not isinstance(new_password, str)
        or not PASSWORD_PATTERN.fullmatch(new_password)
    ):
        raise ManagedSecretLifecycleError("password_shape")
    final_path = env_root / ROLE_FILES[role]
    stage_path = env_root / f".{ROLE_FILES[role]}.rotate"
    if stage_path.exists() or stage_path.is_symlink():
        raise ManagedSecretLifecycleError("stage_residue")
    _private_regular(final_path)
    rows = _env_rows(final_path)
    values = dict(rows)
    old_database_url = values.get("DATABASE_URL", "")
    old_parsed = _parse_role_dsn(role, old_database_url)
    if unquote(old_parsed.password or "") == new_password:
        raise ManagedSecretLifecycleError("password_reuse")
    new_database_url = _replace_password(role, old_database_url, new_password)
    staged_rows = [
        (name, new_database_url if name == "DATABASE_URL" else value)
        for name, value in rows
    ]
    _write_stage(stage_path, staged_rows)
    try:
        _alter_role(
            protected_payload["control_database_url"],
            role,
            password=new_password,
        )
        try:
            os.replace(stage_path, final_path)
        except OSError as exc:
            raise ManagedSecretLifecycleError(
                "connected_known_file_promotion"
            ) from exc
        _verify_login(new_database_url, role)
        _verify_rejected(old_database_url)
    except BaseException:
        stage_path.unlink(missing_ok=True)
        raise
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "rotated",
        "role": role,
        "database_transactions": 1,
        "role_attribute_writes": 1,
        "file_replacements": 1,
        "new_credential_read_only_verified": True,
        "old_credential_rejected": True,
        "secret_values_emitted": 0,
        "service_changes": 0,
    }


def revoke(
    role: str,
    protected_payload: dict[str, Any],
    *,
    env_root: Path = ENV_ROOT,
) -> dict[str, Any]:
    _require_root()
    if set(protected_payload) != {"control_database_url"}:
        raise ManagedSecretLifecycleError("protected_payload_shape")
    final_path = env_root / ROLE_FILES[role]
    stage_path = env_root / f".{ROLE_FILES[role]}.revoke"
    if stage_path.exists() or stage_path.is_symlink():
        raise ManagedSecretLifecycleError("stage_residue")
    _private_regular(final_path)
    values = dict(_env_rows(final_path))
    old_database_url = values.get("DATABASE_URL", "")
    _parse_role_dsn(role, old_database_url)
    _alter_role(
        protected_payload["control_database_url"],
        role,
        password=None,
    )
    try:
        os.replace(final_path, stage_path)
    except OSError as exc:
        raise ManagedSecretLifecycleError(
            "connected_known_file_quarantine"
        ) from exc
    try:
        _verify_rejected(old_database_url)
    except BaseException:
        stage_path.unlink(missing_ok=True)
        raise
    else:
        stage_path.unlink()
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "revoked",
        "role": role,
        "database_transactions": 1,
        "role_attribute_writes": 1,
        "file_removals": 1,
        "old_credential_rejected": True,
        "secret_values_emitted": 0,
        "service_changes": 0,
    }


def _action_from_program(program: str) -> str | None:
    basename = Path(program).name
    if basename == ROTATE_BASENAME:
        return "rotate"
    if basename == REVOKE_BASENAME:
        return "revoke"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        nargs="?",
        choices=("rotate", "revoke"),
        default=_action_from_program(sys.argv[0]),
    )
    parser.add_argument("--role", choices=tuple(ROLE_FILES), required=True)
    parser.add_argument("--confirm")
    parser.add_argument("--env-root", type=Path, default=ENV_ROOT)
    args = parser.parse_args(argv)
    if args.action is None or args.confirm != TASK_ID:
        print(
            "production_managed_secret_lifecycle=FAIL "
            "code=confirmation_missing",
            file=sys.stderr,
        )
        return 2
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ManagedSecretLifecycleError("protected_payload_shape")
        result = (
            rotate(args.role, payload, env_root=args.env_root)
            if args.action == "rotate"
            else revoke(args.role, payload, env_root=args.env_root)
        )
    except (UnicodeError, json.JSONDecodeError):
        print(
            "production_managed_secret_lifecycle=FAIL "
            "code=protected_payload_parse",
            file=sys.stderr,
        )
        return 1
    except ManagedSecretLifecycleError as exc:
        print(
            f"production_managed_secret_lifecycle=FAIL code={exc.code}",
            file=sys.stderr,
        )
        return 1
    except BaseException:
        print(
            "production_managed_secret_lifecycle=FAIL code=execution_failed",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
