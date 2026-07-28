#!/usr/bin/env python3
"""Read-only evidence for the two accepted first-launch legacy-role risks."""

from __future__ import annotations

import hashlib
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
    from tools.collect_production_database_preflight import (
        EXPECTED_PUBLIC_SEQUENCES,
        EXPECTED_PUBLIC_TABLES,
        SEQUENCE_PRIVILEGES,
        TABLE_PRIVILEGES,
        XHS_TABLE_PRIVILEGES,
    )
except ModuleNotFoundError:
    from collect_production_database_preflight import (  # type: ignore[no-redef]
        EXPECTED_PUBLIC_SEQUENCES,
        EXPECTED_PUBLIC_TABLES,
        SEQUENCE_PRIVILEGES,
        TABLE_PRIVILEGES,
        XHS_TABLE_PRIVILEGES,
    )


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_DIR = ROOT / "model" / "migrations" / "postgres"
ACL_PATH = ROOT / "scripts" / "postgres" / "noteai_production_runtime_roles.sql"
EXECUTOR_PATH = ROOT / "tools" / "production_schema_roles.py"
TASK_ID = "PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-001"
AUDIT_ID = "PROD-FIRST-LAUNCH-LEGACY-ROLE-RISK-READONLY-001"
RISK_PROFILE = "FIRST_LAUNCH_LEGACY_ROLE_RISK_V1"
RISK_IDS = (
    "FIRST-LAUNCH-LEGACY-XHS-ADMIN-MEMBERSHIP-20260728",
    "FIRST-LAUNCH-LEGACY-APP-INHERIT-20260728",
)
LEGACY_LEDGER_NAMES = (
    "0001_initial.sql",
    "0002_shared_runtime_state.sql",
    "0003_market_timing.sql",
    "0004_xhs_freshness.sql",
    "0005_idempotency_requests.sql",
    "0006_model_usage_records.sql",
    "0007_ai_operations.sql",
    "0008_ai_operation_admissions.sql",
)
RUNTIME_ROLES = (
    "noteai_app",
    "noteai_admin_runtime",
    "noteai_ai_dispatcher",
    "noteai_ai_worker",
    "noteai_payment",
    "noteai_xhs",
    "noteai_xhs_tracking",
    "noteai_xhs_trends",
)
PROVEN_PRECONNECT_CODES = frozenset({
    "database_url_missing",
    "psycopg_unavailable",
    "source_set",
})


class RoleRiskAuditError(RuntimeError):
    """A sanitized role-risk audit failure."""

    def __init__(self, code: str, *, stage: str):
        super().__init__(code)
        self.code = code
        self.stage = stage


def _source_registry() -> dict[str, str]:
    migrations = sorted(MIGRATION_DIR.glob("*.sql"))
    versions = tuple(path.name.split("_", 1)[0] for path in migrations)
    if versions != tuple(f"{number:04d}" for number in range(1, 17)):
        raise RoleRiskAuditError("source_set", stage="local_source")
    return {
        "executor": hashlib.sha256(EXECUTOR_PATH.read_bytes()).hexdigest(),
        "acl": hashlib.sha256(ACL_PATH.read_bytes()).hexdigest(),
        **{
            path.name.split("_", 1)[0]: hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in migrations
        },
    }


def _scalar(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        raise RoleRiskAuditError("missing_scalar", stage="database_read")
    return next(iter(row.values())) if isinstance(row, dict) else row[0]


def collect_role_risk(conn: Any) -> dict[str, Any]:
    """Collect the exact legacy role state without reading business values."""
    try:
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            conn.execute("SET LOCAL statement_timeout='30s'")
            conn.execute("SET LOCAL lock_timeout='2s'")
            default_read_only = str(
                _scalar(conn, "SHOW default_transaction_read_only")
            )
            transaction_read_only = str(
                _scalar(conn, "SHOW transaction_read_only")
            )
            if default_read_only != "on" or transaction_read_only != "on":
                raise RoleRiskAuditError(
                    "readonly_not_enforced",
                    stage="database_read",
                )

            executor_not_xhs = bool(_scalar(
                conn,
                "SELECT session_user <> 'noteai_xhs' "
                "AND current_user <> 'noteai_xhs'",
            ))
            session_identity_unchanged = bool(_scalar(
                conn,
                "SELECT session_user=current_user "
                "AND current_user=current_role",
            ))
            ledger_names = tuple(
                str(row["version"])
                for row in conn.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                ).fetchall()
            )
            tables = tuple(
                str(row["table_name"])
                for row in conn.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='public' "
                    "AND table_type='BASE TABLE' ORDER BY table_name"
                ).fetchall()
            )
            sequences = tuple(
                str(row["sequence_name"])
                for row in conn.execute(
                    "SELECT sequence_name FROM information_schema.sequences "
                    "WHERE sequence_schema='public' ORDER BY sequence_name"
                ).fetchall()
            )
            membership_rows = conn.execute(
                "SELECT granted.rolname AS granted_name,"
                "member.rolname AS member_name,membership.admin_option,"
                "(to_jsonb(membership)->>'inherit_option')::boolean "
                "AS inherit_option,"
                "(to_jsonb(membership)->>'set_option')::boolean "
                "AS set_option,"
                "membership.grantor=membership.member AS grantor_is_member "
                "FROM pg_auth_members membership "
                "JOIN pg_roles granted ON granted.oid=membership.roleid "
                "JOIN pg_roles member ON member.oid=membership.member "
                "WHERE granted.rolname = ANY(%s) "
                "OR member.rolname = ANY(%s) "
                "ORDER BY granted.rolname,member.rolname",
                (list(RUNTIME_ROLES), list(RUNTIME_ROLES)),
            ).fetchall()
            exact_membership = (
                len(membership_rows) == 1
                and membership_rows[0]["granted_name"] == "noteai_xhs"
                and membership_rows[0]["member_name"] == "noteai_admin"
                and bool(membership_rows[0]["admin_option"])
                and membership_rows[0]["inherit_option"] is True
                and membership_rows[0]["set_option"] is False
            )
            app_role = conn.execute(
                "SELECT rolsuper,rolinherit,rolcreaterole,rolcreatedb,"
                "rolcanlogin,rolreplication,rolbypassrls FROM pg_roles "
                "WHERE rolname='noteai_app'"
            ).fetchone()
            xhs_role = conn.execute(
                "SELECT rolsuper,rolinherit,rolcreaterole,rolcreatedb,"
                "rolcanlogin,rolreplication,rolbypassrls FROM pg_roles "
                "WHERE rolname='noteai_xhs'"
            ).fetchone()
            app_incoming_membership_count = int(_scalar(
                conn,
                "SELECT COUNT(*) FROM pg_auth_members membership "
                "JOIN pg_roles member ON member.oid=membership.member "
                "WHERE member.rolname='noteai_app'",
            ))
            app_high_privilege_inheritance_count = int(_scalar(
                conn,
                "SELECT COUNT(*) FROM pg_roles role "
                "WHERE role.rolname <> 'noteai_app' "
                "AND pg_has_role('noteai_app',role.oid,'USAGE') "
                "AND (role.rolsuper OR role.rolcreaterole "
                "OR role.rolcreatedb OR role.rolreplication "
                "OR role.rolbypassrls)",
            ))

            database_connect = bool(_scalar(
                conn,
                "SELECT has_database_privilege("
                "'noteai_xhs',current_database(),'CONNECT')",
            ))
            database_create = bool(_scalar(
                conn,
                "SELECT has_database_privilege("
                "'noteai_xhs',current_database(),'CREATE')",
            ))
            database_temp = bool(_scalar(
                conn,
                "SELECT has_database_privilege("
                "'noteai_xhs',current_database(),'TEMP')",
            ))
            schema_usage = bool(_scalar(
                conn,
                "SELECT has_schema_privilege("
                "'noteai_xhs','public','USAGE')",
            ))
            schema_create = bool(_scalar(
                conn,
                "SELECT has_schema_privilege("
                "'noteai_xhs','public','CREATE')",
            ))

            table_checks = 0
            table_positive = 0
            table_grantable = 0
            column_checks = 0
            column_positive = 0
            column_grantable = 0
            table_mismatch = 0
            for table in tables:
                allowed = set(XHS_TABLE_PRIVILEGES.get(table, ()))
                for privilege in TABLE_PRIVILEGES:
                    actual = bool(_scalar(
                        conn,
                        "SELECT has_table_privilege(%s,%s,%s)",
                        ("noteai_xhs", f"public.{table}", privilege),
                    ))
                    grantable = bool(_scalar(
                        conn,
                        "SELECT has_table_privilege(%s,%s,%s)",
                        (
                            "noteai_xhs",
                            f"public.{table}",
                            f"{privilege} WITH GRANT OPTION",
                        ),
                    ))
                    table_mismatch += int(actual != (privilege in allowed))
                    table_checks += 1
                    table_positive += int(actual)
                    table_grantable += int(grantable)
                columns = conn.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=%s "
                    "ORDER BY ordinal_position",
                    (table,),
                ).fetchall()
                for column_row in columns:
                    column = str(column_row["column_name"])
                    for privilege in (
                        "SELECT", "INSERT", "UPDATE", "REFERENCES",
                    ):
                        actual = bool(_scalar(
                            conn,
                            "SELECT has_column_privilege(%s,%s,%s,%s)",
                            (
                                "noteai_xhs",
                                f"public.{table}",
                                column,
                                privilege,
                            ),
                        ))
                        grantable = bool(_scalar(
                            conn,
                            "SELECT has_column_privilege(%s,%s,%s,%s)",
                            (
                                "noteai_xhs",
                                f"public.{table}",
                                column,
                                f"{privilege} WITH GRANT OPTION",
                            ),
                        ))
                        table_mismatch += int(
                            actual != (privilege in allowed)
                        )
                        column_checks += 1
                        column_positive += int(actual)
                        column_grantable += int(grantable)

            sequence_checks = 0
            sequence_positive = 0
            sequence_grantable = 0
            sequence_mismatch = 0
            expected_xhs_sequences = {
                "crawler_events_id_seq",
                "hot_keywords_id_seq",
                "keyword_snapshots_id_seq",
            }
            for sequence in sequences:
                for privilege in SEQUENCE_PRIVILEGES:
                    actual = bool(_scalar(
                        conn,
                        "SELECT has_sequence_privilege(%s,%s,%s)",
                        (
                            "noteai_xhs",
                            f"public.{sequence}",
                            privilege,
                        ),
                    ))
                    grantable = bool(_scalar(
                        conn,
                        "SELECT has_sequence_privilege(%s,%s,%s)",
                        (
                            "noteai_xhs",
                            f"public.{sequence}",
                            f"{privilege} WITH GRANT OPTION",
                        ),
                    ))
                    expected = (
                        privilege == "USAGE"
                        and sequence in expected_xhs_sequences
                    )
                    sequence_mismatch += int(actual != expected)
                    sequence_checks += 1
                    sequence_positive += int(actual)
                    sequence_grantable += int(grantable)

            public_function_execute_count = int(_scalar(
                conn,
                "SELECT COUNT(*) FROM pg_proc function "
                "JOIN pg_namespace namespace "
                "ON namespace.oid=function.pronamespace "
                "WHERE namespace.nspname='public' "
                "AND has_function_privilege("
                "'noteai_xhs',function.oid,'EXECUTE')",
            ))
            public_function_grantable_count = int(_scalar(
                conn,
                "SELECT COUNT(*) FROM pg_proc function "
                "JOIN pg_namespace namespace "
                "ON namespace.oid=function.pronamespace "
                "WHERE namespace.nspname='public' "
                "AND has_function_privilege("
                "'noteai_xhs',function.oid,"
                "'EXECUTE WITH GRANT OPTION')",
            ))
            ownership_count = int(_scalar(
                conn,
                "SELECT ("
                "(SELECT COUNT(*) FROM pg_class "
                "WHERE relowner='noteai_xhs'::regrole) + "
                "(SELECT COUNT(*) FROM pg_namespace "
                "WHERE nspowner='noteai_xhs'::regrole) + "
                "(SELECT COUNT(*) FROM pg_proc "
                "WHERE proowner='noteai_xhs'::regrole))",
            ))
    except RoleRiskAuditError:
        raise
    except BaseException as exc:
        raise RoleRiskAuditError(
            "database_read_failed",
            stage="database_read",
        ) from exc

    app_exact = (
        app_role is not None
        and not bool(app_role["rolsuper"])
        and bool(app_role["rolinherit"])
        and not bool(app_role["rolcreaterole"])
        and not bool(app_role["rolcreatedb"])
        and bool(app_role["rolcanlogin"])
        and not bool(app_role["rolreplication"])
        and not bool(app_role["rolbypassrls"])
    )
    xhs_exact = (
        xhs_role is not None
        and not any(bool(xhs_role[key]) for key in (
            "rolsuper", "rolinherit", "rolcreaterole", "rolcreatedb",
            "rolreplication", "rolbypassrls",
        ))
        and bool(xhs_role["rolcanlogin"])
    )
    accepted = (
        default_read_only == "on"
        and transaction_read_only == "on"
        and executor_not_xhs
        and session_identity_unchanged
        and ledger_names == LEGACY_LEDGER_NAMES
        and tables == EXPECTED_PUBLIC_TABLES
        and sequences == EXPECTED_PUBLIC_SEQUENCES
        and exact_membership
        and app_exact
        and xhs_exact
        and app_incoming_membership_count == 0
        and app_high_privilege_inheritance_count == 0
        and database_connect
        and not database_create
        and not database_temp
        and schema_usage
        and not schema_create
        and table_mismatch == 0
        and table_grantable == 0
        and column_grantable == 0
        and sequence_mismatch == 0
        and sequence_grantable == 0
        and public_function_grantable_count == 0
        and ownership_count == 0
    )
    membership_options = None
    if len(membership_rows) == 1:
        membership_options = {
            "admin": bool(membership_rows[0]["admin_option"]),
            "inherit": membership_rows[0]["inherit_option"],
            "set": membership_rows[0]["set_option"],
            "grantor_is_member": bool(
                membership_rows[0]["grantor_is_member"]
            ),
        }
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "audit_id": AUDIT_ID,
        "status": "accepted_risk_observed" if accepted else "state_changed",
        "incident_class": "CONNECTED_KNOWN",
        "risk_profile": RISK_PROFILE,
        "risk_ids": list(RISK_IDS),
        "read_only": True,
        "default_transaction_read_only": True,
        "transaction_read_only": True,
        "database_write_count": 0,
        "business_row_values_read": 0,
        "executor": {
            "not_noteai_xhs": executor_not_xhs,
            "session_identity_unchanged": session_identity_unchanged,
            "literal_identity_emitted": False,
        },
        "ledger": {
            "exact_0001_0008": ledger_names == LEGACY_LEDGER_NAMES,
            "count": len(ledger_names),
        },
        "legacy_membership": {
            "exact_edge": exact_membership,
            "edge_count": len(membership_rows),
            "direction": (
                "noteai_xhs_to_noteai_admin"
                if exact_membership else "changed"
            ),
            "options": membership_options,
        },
        "noteai_app_inherit": {
            "rolinherit": None if app_role is None else bool(
                app_role["rolinherit"]
            ),
            "incoming_membership_count": app_incoming_membership_count,
            "high_privilege_inheritance_count": (
                app_high_privilege_inheritance_count
            ),
        },
        "noteai_xhs_effective_privileges": {
            "role_attributes_exact": xhs_exact,
            "database_connect": database_connect,
            "database_create": database_create,
            "database_temporary": database_temp,
            "public_schema_usage": schema_usage,
            "public_schema_create": schema_create,
            "table_positive_count": table_positive,
            "table_check_count": table_checks,
            "table_or_column_mismatch_count": table_mismatch,
            "table_grantable_count": table_grantable,
            "column_positive_count": column_positive,
            "column_check_count": column_checks,
            "column_grantable_count": column_grantable,
            "sequence_positive_count": sequence_positive,
            "sequence_check_count": sequence_checks,
            "sequence_mismatch_count": sequence_mismatch,
            "sequence_grantable_count": sequence_grantable,
            "public_function_execute_count": (
                public_function_execute_count
            ),
            "public_function_grantable_count": (
                public_function_grantable_count
            ),
            "ownership_count": ownership_count,
        },
        "source_registry": _source_registry(),
        "provider_calls": 0,
        "service_changes": 0,
        "public_traffic_requests": 0,
        "secret_values_exposed": 0,
    }


def _connect(database_url: str) -> Any:
    if psycopg is None:
        raise RoleRiskAuditError("psycopg_unavailable", stage="connect")
    return psycopg.connect(
        database_url,
        row_factory=dict_row,
        connect_timeout=10,
        application_name="noteai_role_risk_audit_v1",
        options="-c default_transaction_read_only=on",
    )


def main(*, database_url: str | None = None) -> int:
    connected = False
    connection_attempted = False
    try:
        _source_registry()
        if not database_url or not database_url.strip():
            raise RoleRiskAuditError(
                "database_url_missing",
                stage="connect",
            )
        connection_attempted = True
        conn = _connect(database_url.strip())
        connected = True
        try:
            result = collect_role_risk(conn)
        finally:
            conn.close()
    except RoleRiskAuditError as exc:
        if not connected and (
            not connection_attempted
            or exc.code in PROVEN_PRECONNECT_CODES
        ):
            print(
                "production_first_launch_role_risk_audit=FAIL "
                f"stage={exc.stage} incident_class=PRE_CONNECT "
                "database_connected=0 database_outcome=NOT_CONNECTED "
                "retry_same_path=0",
                file=sys.stderr,
            )
            return 2
        print(
            "production_first_launch_role_risk_audit=FAIL "
            f"stage={exc.stage} incident_class=CONNECTED_UNKNOWN "
            f"database_connected={int(connected)} "
            "database_outcome=UNKNOWN no_retry=1",
            file=sys.stderr,
        )
        return 1
    except BaseException:
        print(
            "production_first_launch_role_risk_audit=FAIL "
            "stage=unexpected incident_class=CONNECTED_UNKNOWN "
            f"database_connected={int(connected)} "
            "database_outcome=UNKNOWN no_retry=1",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "accepted_risk_observed" else 30


if __name__ == "__main__":
    raise SystemExit(main())
