#!/usr/bin/env python3
"""Verify final role files through forced-readonly role-bound connections."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - deployment dependency
    psycopg = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]

try:
    from tools import production_managed_secret_files as managed_files
except ModuleNotFoundError:
    import production_managed_secret_files as managed_files  # type: ignore[no-redef]


TASK_ID = managed_files.TASK_ID


class ManagedSecretLoginAuditError(RuntimeError):
    """A fixed, Secret-free runtime-login audit failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _audit_connection(role: str, database_url: str) -> dict[str, int]:
    if psycopg is None:
        raise ManagedSecretLoginAuditError("psycopg_unavailable")
    connected = False
    try:
        conn = psycopg.connect(
            database_url,
            row_factory=dict_row,
            connect_timeout=10,
            application_name=f"noteai_secret_audit_{role}",
        )
        connected = True
        try:
            with conn.transaction():
                conn.execute("SET TRANSACTION READ ONLY")
                conn.execute("SET LOCAL statement_timeout='15s'")
                conn.execute("SET LOCAL lock_timeout='5s'")
                row = conn.execute(
                    "SELECT session_user AS session_name,"
                    "current_user AS current_name,"
                    "current_setting('transaction_read_only') AS read_only,"
                    "role.rolcanlogin,role.rolsuper,role.rolcreatedb,"
                    "role.rolcreaterole,role.rolinherit,role.rolreplication,"
                    "role.rolbypassrls,"
                    "(SELECT COUNT(*) FROM pg_auth_members membership "
                    "WHERE membership.member=role.oid)::integer "
                    "AS incoming_membership_count,"
                    "((SELECT COUNT(*) FROM pg_class object "
                    "WHERE object.relowner=role.oid) + "
                    "(SELECT COUNT(*) FROM pg_namespace object "
                    "WHERE object.nspowner=role.oid) + "
                    "(SELECT COUNT(*) FROM pg_proc object "
                    "WHERE object.proowner=role.oid))::integer "
                    "AS owned_object_count,"
                    "has_database_privilege("
                    "current_user,current_database(),'CONNECT') AS db_connect,"
                    "has_database_privilege("
                    "current_user,current_database(),'CREATE') AS db_create,"
                    "has_database_privilege("
                    "current_user,current_database(),'TEMP') AS db_temp,"
                    "has_schema_privilege("
                    "current_user,'public','USAGE') AS schema_usage,"
                    "has_schema_privilege("
                    "current_user,'public','CREATE') AS schema_create,"
                    "has_table_privilege("
                    "current_user,'schema_migrations','SELECT') AS ledger_read "
                    "FROM pg_roles role WHERE role.rolname=current_user"
                ).fetchone()
        finally:
            conn.close()
    except ManagedSecretLoginAuditError:
        raise
    except BaseException as exc:
        code = "connected_audit_failed" if connected else "connection_failed"
        raise ManagedSecretLoginAuditError(code) from exc
    expected_user = managed_files.ROLE_DATABASE_USERS[role]
    if (
        row is None
        or str(row["session_name"]) != expected_user
        or str(row["current_name"]) != expected_user
        or str(row["read_only"]).lower() != "on"
        or not bool(row["rolcanlogin"])
        or bool(row["rolsuper"])
        or bool(row["rolcreatedb"])
        or bool(row["rolcreaterole"])
        or bool(row["rolreplication"])
        or bool(row["rolbypassrls"])
        or bool(row["db_create"])
        or bool(row["db_temp"])
        or bool(row["schema_create"])
        or bool(row["ledger_read"])
        or not bool(row["db_connect"])
        or not bool(row["schema_usage"])
        or int(row["incoming_membership_count"])
        or int(row["owned_object_count"])
    ):
        raise ManagedSecretLoginAuditError("role_contract")
    if bool(row["rolinherit"]) is not (role == "api"):
        raise ManagedSecretLoginAuditError("role_inherit")
    return {
        "connection_count": 1,
        "read_only_transaction_count": 1,
        "unexpected_elevation_count": 0,
        "incoming_membership_count": 0,
        "owned_object_count": 0,
        "ledger_read_count": 0,
    }


def audit_host(
    host_label: str,
    *,
    env_root: Path = managed_files.ENV_ROOT,
    expected_uid: int = 0,
    require_root: bool = True,
) -> dict[str, Any]:
    file_result = managed_files.verify_distribution(
        host_label,
        env_root=env_root,
        expected_uid=expected_uid,
        require_root=require_root,
    )
    metrics = {
        "connection_count": 0,
        "read_only_transaction_count": 0,
        "unexpected_elevation_count": 0,
        "incoming_membership_count": 0,
        "owned_object_count": 0,
        "ledger_read_count": 0,
    }
    for role in managed_files.HOST_ROLES[host_label]:
        rows = managed_files._parse_env(
            env_root / managed_files.ROLE_FILES[role]
        )
        values = dict(rows)
        result = _audit_connection(role, values["DATABASE_URL"])
        for key, value in result.items():
            metrics[key] += value
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "verified",
        "host_label": host_label,
        "forced_read_only": True,
        "file_count": file_result["verified_file_count"],
        **metrics,
        "secret_values_emitted": 0,
        "service_changes": 0,
        "business_values_read": 0,
        "public_traffic_requests": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--host-label",
        choices=tuple(managed_files.HOST_ROLES),
        required=True,
    )
    parser.add_argument(
        "--env-root",
        type=Path,
        default=managed_files.ENV_ROOT,
    )
    args = parser.parse_args(argv)
    try:
        result = audit_host(args.host_label, env_root=args.env_root)
    except (
        managed_files.ManagedSecretFileError,
        ManagedSecretLoginAuditError,
    ) as exc:
        print(
            f"production_managed_secret_login_audit=FAIL code={exc.code}",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
