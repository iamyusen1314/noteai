#!/usr/bin/env python3
"""Correct the two independently identified legacy runtime-role conflicts.

This tool is intentionally narrower than the production schema executor.  It
can only set the historical API role to NOINHERIT and revoke the single
historical XHS-to-admin membership edge.  It never changes schema, migration
ledger rows, table data, credentials, LOGIN state, ownership or privileges.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

try:
    import psycopg
    from psycopg.pq import TransactionStatus
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - exercised by deployment environment
    psycopg = None  # type: ignore[assignment]
    TransactionStatus = None  # type: ignore[assignment,misc]
    dict_row = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_DIR = ROOT / "model" / "migrations" / "postgres"
EXECUTOR_PATH = ROOT / "tools" / "production_schema_roles.py"
ACL_PATH = ROOT / "scripts" / "postgres" / "noteai_production_runtime_roles.sql"
TASK_ID = "PROD-FIRST-LAUNCH-LEGACY-RUNTIME-ROLE-CORRECTION-001"
PARENT_TASK_ID = "PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-001"
EXPECTED_LEDGER_NAMES = (
    "0001_initial.sql",
    "0002_shared_runtime_state.sql",
    "0003_market_timing.sql",
    "0004_xhs_freshness.sql",
    "0005_idempotency_requests.sql",
    "0006_model_usage_records.sql",
    "0007_ai_operations.sql",
    "0008_ai_operation_admissions.sql",
)
LEGACY_TABLES = (
    "admin_sessions",
    "ai_operation_admissions",
    "ai_operation_events",
    "ai_operations",
    "ai_provider_attempts",
    "analysis_log",
    "chat_sessions",
    "crawler_events",
    "credit_transactions",
    "credits",
    "growth_records",
    "hot_keywords",
    "idempotency_requests",
    "keyword_snapshots",
    "managed_prompts",
    "model_usage_records",
    "notes",
    "prompt_history",
    "saved_diagnoses",
    "schema_migrations",
    "subscriptions",
    "system_settings",
    "tracked_notes",
    "usage_records",
    "user_learn",
    "user_memories",
    "user_sessions",
    "users",
    "xhs_crawler_health",
    "xhs_freshness_ledger",
)
EXPECTED_SEQUENCES = (
    "analysis_log_id_seq",
    "crawler_events_id_seq",
    "hot_keywords_id_seq",
    "keyword_snapshots_id_seq",
    "prompt_history_id_seq",
)
LEGACY_RUNTIME_ROLES = ("noteai_app", "noteai_xhs")
KNOWN_RUNTIME_ROLES = (
    "noteai_admin_runtime",
    "noteai_ai_dispatcher",
    "noteai_ai_worker",
    "noteai_app",
    "noteai_payment",
    "noteai_xhs",
    "noteai_xhs_tracking",
    "noteai_xhs_trends",
)
ELEVATED_ATTRIBUTES = (
    "rolsuper",
    "rolinherit",
    "rolcreaterole",
    "rolcreatedb",
    "rolreplication",
    "rolbypassrls",
)
EXPECTED_SOURCE_PATH_SHA256 = {
    "tools/production_schema_roles.py":
        "267da28ba72c5ebf2593fe5793544764c59df776944d4180c6c2632ba97671e5",
    "scripts/postgres/noteai_production_runtime_roles.sql":
        "fc41ee2867fdfa3965a78e9eea017cf26466bb10f2a5e8879865182431fc93c0",
    "model/migrations/postgres/0001_initial.sql":
        "8ea5d32bc5c1a3e84452d93722324b9a9b4bb2e156c69b4a9656efa13ed51718",
    "model/migrations/postgres/0002_shared_runtime_state.sql":
        "d3a939479990cfe080fce71ebd122e19e633874bd2cd6883b5b03507eadefcb7",
    "model/migrations/postgres/0003_market_timing.sql":
        "772636cab88c2abf169a5b1a3fd5419ba1e3b12bbae92e211e296e89b1850192",
    "model/migrations/postgres/0004_xhs_freshness.sql":
        "1c817056eea3df9e0e1dd6ba6aceaf0c9a172b3cbba92ba3aeb621adb857a2a1",
    "model/migrations/postgres/0005_idempotency_requests.sql":
        "3a02a45bf0211580c5db97fc80ab9fb8eedab94a9cf981c59f3de231789981e6",
    "model/migrations/postgres/0006_model_usage_records.sql":
        "392eb82adca68493566f6469ce6ce4f1fba0cfc9ab76757deb4e1404c45cb735",
    "model/migrations/postgres/0007_ai_operations.sql":
        "477d4ea776d701c4b359b36eb254c68263131f74dedeb766ff46081bff619037",
    "model/migrations/postgres/0008_ai_operation_admissions.sql":
        "3bdd896ce06f7a5ae8deeba01145d9556775c45a71cd83576240d24a01bc05fe",
    "model/migrations/postgres/0009_account_security_compliance.sql":
        "1cfa46144b9a4d424215dd861a9817ec3a4612e7e62c1f2df5fec6f2e728f750",
    "model/migrations/postgres/0010_tracking_execution_contract.sql":
        "8ab5bbddad28ea60afad48bc27d71b105c5313d0229e263d06b65db4f38a3459",
    "model/migrations/postgres/0011_trends_execution_contract.sql":
        "abd55623a8903d6a6c01bed5fe4336b07be182abde2b86fa4b9cc5e7cb4b9802",
    "model/migrations/postgres/0012_durable_ai_execution_contract.sql":
        "df72dedfb292700104fc394b5b326f33e4339cbf195f704278c56e08e44bec83",
    "model/migrations/postgres/0013_private_storage_recovery_contract.sql":
        "1268cdb9696965f02d5be88882b3dc8a2f9f7b589a2b0da5193d1bb8408ccb76",
    "model/migrations/postgres/0014_payment_execution_contract.sql":
        "ed788fdf33e256713767101e85005e95a712a7e5c5aae0ec258c5f14091cb0ad",
    "model/migrations/postgres/0015_admin_runtime_contract.sql":
        "3ee9b85c9c154117d6e81ee83283160cede9bd182450b0de193f94a431b7d66c",
    "model/migrations/postgres/0016_admin_runtime_role_collision.sql":
        "5cdd8dc0bb6eefd4fee086458e964495d7163bf123026c4511c4dd7ccf93fde6",
}
PROVEN_PRECONNECT_CODES = frozenset({
    "confirmation_missing",
    "database_url_missing",
    "psycopg_unavailable",
    "source_drift",
})


class RoleCorrectionError(RuntimeError):
    """A sanitized fail-closed role-correction error."""

    def __init__(self, code: str, *, stage: str):
        super().__init__(code)
        self.code = code
        self.stage = stage


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_local_source() -> dict[str, str]:
    paths = sorted(MIGRATION_DIR.glob("*.sql"))
    observed = {
        str(EXECUTOR_PATH.relative_to(ROOT)): _sha256(EXECUTOR_PATH),
        str(ACL_PATH.relative_to(ROOT)): _sha256(ACL_PATH),
        **{
            str(path.relative_to(ROOT)): _sha256(path)
            for path in paths
        },
    }
    if observed != EXPECTED_SOURCE_PATH_SHA256:
        raise RoleCorrectionError("source_drift", stage="local_source")
    return observed


def _value(row: Any) -> Any:
    if row is None:
        raise RoleCorrectionError("missing_scalar", stage="database_read")
    return next(iter(row.values())) if isinstance(row, dict) else row[0]


def _scalar(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> Any:
    return _value(conn.execute(sql, params).fetchone())


def _snapshot(conn: Any) -> dict[str, Any]:
    sha_column_count = int(_scalar(
        conn,
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='schema_migrations' "
        "AND column_name='sha256'",
    ))
    ledger_names = tuple(
        str(row["version"])
        for row in conn.execute(
            "SELECT version FROM public.schema_migrations ORDER BY version"
        ).fetchall()
    )
    tables = tuple(
        str(row["table_name"])
        for row in conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_type='BASE TABLE' "
            "ORDER BY table_name"
        ).fetchall()
    )
    sequences = tuple(
        str(row["sequence_name"])
        for row in conn.execute(
            "SELECT sequence_name FROM information_schema.sequences "
            "WHERE sequence_schema='public' ORDER BY sequence_name"
        ).fetchall()
    )
    role_rows = conn.execute(
        "SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,"
        "rolcanlogin,rolreplication,rolbypassrls "
        "FROM pg_catalog.pg_roles WHERE rolname = ANY(%s) ORDER BY rolname",
        (list(KNOWN_RUNTIME_ROLES),),
    ).fetchall()
    present_roles = tuple(str(row["rolname"]) for row in role_rows)
    elevated = tuple(
        (str(row["rolname"]), attribute)
        for row in role_rows
        for attribute in ELEVATED_ATTRIBUTES
        if bool(row[attribute])
    )
    memberships = tuple(
        conn.execute(
            "SELECT granted.rolname AS granted_name,"
            "granted.rolcanlogin AS granted_canlogin,"
            "granted.rolsuper AS granted_super,"
            "member.rolname AS member_name,"
            "member.rolcanlogin AS member_canlogin,"
            "member.rolsuper AS member_super,"
            "quote_ident(grantor.rolname) AS grantor_sql,"
            "grantor.rolcanlogin AS grantor_canlogin,"
            "grantor.rolsuper AS grantor_super,"
            "(executor.oid=membership.grantor) AS executor_is_grantor,"
            "executor.rolsuper AS executor_super,"
            "executor.rolcreaterole AS executor_createrole,"
            "EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members app_admin "
            "JOIN pg_catalog.pg_roles app_role "
            "ON app_role.oid=app_admin.roleid "
            "WHERE app_role.rolname='noteai_app' "
            "AND app_admin.member=executor.oid "
            "AND app_admin.admin_option) AS executor_admin_on_app,"
            "membership.admin_option,"
            "(to_jsonb(membership)->>'inherit_option')::boolean "
            "AS inherit_option,"
            "(to_jsonb(membership)->>'set_option')::boolean AS set_option "
            "FROM pg_catalog.pg_auth_members membership "
            "JOIN pg_catalog.pg_roles granted "
            "ON granted.oid=membership.roleid "
            "JOIN pg_catalog.pg_roles member "
            "ON member.oid=membership.member "
            "JOIN pg_catalog.pg_roles grantor "
            "ON grantor.oid=membership.grantor "
            "JOIN pg_catalog.pg_roles executor "
            "ON executor.rolname=current_user "
            "WHERE (granted.rolname = ANY(%s) "
            "OR member.rolname = ANY(%s)) "
            "ORDER BY granted.rolname,member.rolname",
            (list(LEGACY_RUNTIME_ROLES), list(LEGACY_RUNTIME_ROLES)),
        ).fetchall()
    )
    ownership_count = int(_scalar(
        conn,
        "SELECT ("
        "(SELECT COUNT(*) FROM pg_catalog.pg_class object "
        "JOIN pg_catalog.pg_roles role ON role.oid=object.relowner "
        "WHERE role.rolname = ANY(%s)) + "
        "(SELECT COUNT(*) FROM pg_catalog.pg_namespace object "
        "JOIN pg_catalog.pg_roles role ON role.oid=object.nspowner "
        "WHERE role.rolname = ANY(%s)) + "
        "(SELECT COUNT(*) FROM pg_catalog.pg_proc object "
        "JOIN pg_catalog.pg_roles role ON role.oid=object.proowner "
        "WHERE role.rolname = ANY(%s)))",
        (
            list(LEGACY_RUNTIME_ROLES),
            list(LEGACY_RUNTIME_ROLES),
            list(LEGACY_RUNTIME_ROLES),
        ),
    ))
    return {
        "sha_column_count": sha_column_count,
        "ledger_names": ledger_names,
        "tables": tables,
        "sequences": sequences,
        "present_roles": present_roles,
        "role_rows": role_rows,
        "elevated": elevated,
        "memberships": memberships,
        "ownership_count": ownership_count,
    }


def _require_common(snapshot: dict[str, Any]) -> None:
    if (
        snapshot["sha_column_count"] != 0
        or snapshot["ledger_names"] != EXPECTED_LEDGER_NAMES
        or snapshot["tables"] != LEGACY_TABLES
        or snapshot["sequences"] != EXPECTED_SEQUENCES
        or snapshot["present_roles"] != LEGACY_RUNTIME_ROLES
        or snapshot["ownership_count"] != 0
    ):
        raise RoleCorrectionError(
            "legacy_state_changed",
            stage="database_precondition",
        )
    for row in snapshot["role_rows"]:
        if not bool(row["rolcanlogin"]):
            raise RoleCorrectionError(
                "legacy_login_state_changed",
                stage="database_precondition",
            )


def _require_precondition(snapshot: dict[str, Any]) -> None:
    _require_common(snapshot)
    if snapshot["elevated"] != (("noteai_app", "rolinherit"),):
        raise RoleCorrectionError(
            "elevation_identity_changed",
            stage="database_precondition",
        )
    memberships = snapshot["memberships"]
    if len(memberships) != 1:
        raise RoleCorrectionError(
            "membership_identity_changed",
            stage="database_precondition",
        )
    membership = memberships[0]
    if (
        str(membership["granted_name"]) != "noteai_xhs"
        or not bool(membership["granted_canlogin"])
        or bool(membership["granted_super"])
        or str(membership["member_name"]) != "noteai_admin"
        or not bool(membership["member_canlogin"])
        or bool(membership["member_super"])
        or not bool(membership["admin_option"])
        or membership["inherit_option"] is not True
        or membership["set_option"] is not False
    ):
        raise RoleCorrectionError(
            "membership_identity_changed",
            stage="database_precondition",
        )
    if not (
        (
            bool(membership["executor_super"])
            or (
                bool(membership["executor_createrole"])
                and bool(membership["executor_admin_on_app"])
            )
        )
        and (
            bool(membership["executor_super"])
            or bool(membership["executor_is_grantor"])
        )
    ):
        raise RoleCorrectionError(
            "executor_capability_unproven",
            stage="database_precondition",
        )


def _require_postcondition(snapshot: dict[str, Any]) -> None:
    _require_common(snapshot)
    if snapshot["elevated"] or snapshot["memberships"]:
        raise RoleCorrectionError(
            "correction_postcondition",
            stage="database_postcondition",
        )


def _transaction_is_idle(conn: Any) -> bool:
    if TransactionStatus is None:
        return False
    info = getattr(conn, "info", None)
    return (
        info is not None
        and info.transaction_status == TransactionStatus.IDLE
    )


def preflight(conn: Any) -> dict[str, Any]:
    try:
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            conn.execute("SET LOCAL statement_timeout='30s'")
            conn.execute("SET LOCAL lock_timeout='2s'")
            if str(_scalar(conn, "SHOW transaction_read_only")) != "on":
                raise RoleCorrectionError(
                    "readonly_not_enforced",
                    stage="database_precondition",
                )
            snapshot = _snapshot(conn)
            _require_precondition(snapshot)
    except RoleCorrectionError:
        raise
    except BaseException as exc:
        if _transaction_is_idle(conn):
            raise RoleCorrectionError(
                "database_preflight_failed",
                stage="database_precondition",
            ) from exc
        raise
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "status": "ready",
        "incident_class": "CONNECTED_KNOWN",
        "read_only": True,
        "database_write_count": 0,
        "business_row_values_read": 0,
        "precondition": {
            "ledger_count": len(snapshot["ledger_names"]),
            "ledger_first": "0001",
            "ledger_last": "0008",
            "public_table_count": len(snapshot["tables"]),
            "public_sequence_count": len(snapshot["sequences"]),
            "legacy_runtime_role_count": len(snapshot["present_roles"]),
            "elevated_attribute_count": len(snapshot["elevated"]),
            "bidirectional_membership_count": len(snapshot["memberships"]),
            "runtime_ownership_count": snapshot["ownership_count"],
            "executor_superuser": bool(
                snapshot["memberships"][0]["executor_super"]
            ),
            "executor_is_membership_grantor": bool(
                snapshot["memberships"][0]["executor_is_grantor"]
            ),
            "alter_capability_proven": True,
            "revoke_capability_proven": True,
            "membership_grantor_login": bool(
                snapshot["memberships"][0]["grantor_canlogin"]
            ),
            "membership_grantor_superuser": bool(
                snapshot["memberships"][0]["grantor_super"]
            ),
        },
        "provider_calls": 0,
        "service_changes": 0,
        "public_traffic_requests": 0,
        "secret_values_exposed": 0,
    }


def apply_correction(conn: Any) -> dict[str, Any]:
    try:
        with conn.transaction():
            conn.execute("SET LOCAL statement_timeout='30s'")
            conn.execute("SET LOCAL lock_timeout='2s'")
            conn.execute(
                "SET LOCAL idle_in_transaction_session_timeout='60s'"
            )
            conn.execute(
                "SELECT pg_advisory_xact_lock("
                "hashtext('noteai_schema_migrations'))"
            )
            before = _snapshot(conn)
            _require_precondition(before)
            conn.execute("ALTER ROLE noteai_app NOINHERIT")
            membership = before["memberships"][0]
            if bool(membership["executor_is_grantor"]):
                conn.execute(
                    "REVOKE noteai_xhs FROM noteai_admin "
                    "GRANTED BY CURRENT_USER"
                )
            else:
                conn.execute(
                    "REVOKE noteai_xhs FROM noteai_admin GRANTED BY "
                    f"{membership['grantor_sql']}"
                )
            after = _snapshot(conn)
            _require_postcondition(after)
    except RoleCorrectionError:
        raise
    except BaseException as exc:
        if _transaction_is_idle(conn):
            raise RoleCorrectionError(
                "database_apply_failed",
                stage="database_apply",
            ) from exc
        raise
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "status": "corrected",
        "incident_class": "CONNECTED_KNOWN",
        "transaction_committed": True,
        "database_writes": {
            "legacy_runtime_role_attribute_changes": 1,
            "legacy_runtime_membership_revocations": 1,
            "migration_ledger_changes": 0,
            "schema_changes": 0,
            "table_row_changes": 0,
            "existing_business_row_updates": 0,
        },
        "postcondition": {
            "ledger_count": len(after["ledger_names"]),
            "ledger_first": "0001",
            "ledger_last": "0008",
            "public_table_count": len(after["tables"]),
            "public_sequence_count": len(after["sequences"]),
            "legacy_runtime_role_count": len(after["present_roles"]),
            "elevated_attribute_count": len(after["elevated"]),
            "bidirectional_membership_count": len(after["memberships"]),
            "runtime_ownership_count": after["ownership_count"],
        },
        "provider_calls": 0,
        "service_changes": 0,
        "public_traffic_requests": 0,
        "secret_values_exposed": 0,
    }


def _connect(database_url: str, *, read_only: bool) -> Any:
    if psycopg is None:
        raise RoleCorrectionError("psycopg_unavailable", stage="connect")
    options = "-c default_transaction_read_only=on" if read_only else ""
    return psycopg.connect(
        database_url,
        row_factory=dict_row,
        connect_timeout=10,
        application_name="noteai_legacy_role_correction_v1",
        options=options,
    )


def _report_failure(
    *,
    stage: str,
    connected: bool,
    connection_attempted: bool,
    proven_preconnect: bool,
    connected_known: bool,
    database_outcome: str,
) -> int:
    if proven_preconnect:
        print(
            "production_legacy_runtime_role_correction=FAIL "
            f"stage={stage} incident_class=PRE_CONNECT "
            "database_connected=0 connection_attempted=0 "
            "database_outcome=NOT_CONNECTED retry_same_path=0",
            file=sys.stderr,
        )
        return 2
    if connected_known:
        print(
            "production_legacy_runtime_role_correction=FAIL "
            f"stage={stage} incident_class=CONNECTED_KNOWN "
            "database_connected=1 connection_attempted=1 "
            f"database_outcome={database_outcome} database_write=0 "
            "no_retry=1",
            file=sys.stderr,
        )
        return 30
    print(
        "production_legacy_runtime_role_correction=FAIL "
        f"stage={stage} incident_class=CONNECTED_UNKNOWN "
        f"database_connected={int(connected)} "
        f"connection_attempted={int(connection_attempted)} "
        "database_outcome=UNKNOWN no_retry=1",
        file=sys.stderr,
    )
    return 1


def main(
    argv: list[str] | None = None,
    *,
    database_url: str | None = None,
    confirmation: str | None = None,
) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    connected = False
    connection_attempted = False
    try:
        validate_local_source()
        if args.apply and confirmation != TASK_ID:
            raise RoleCorrectionError(
                "confirmation_missing",
                stage="confirmation",
            )
        if not database_url or not database_url.strip():
            raise RoleCorrectionError("database_url_missing", stage="connect")
        connection_attempted = True
        conn = _connect(database_url.strip(), read_only=args.preflight)
        connected = True
        try:
            result = preflight(conn) if args.preflight else apply_correction(conn)
        finally:
            conn.close()
    except RoleCorrectionError as exc:
        return _report_failure(
            stage=exc.stage,
            connected=connected,
            connection_attempted=connection_attempted,
            proven_preconnect=(
                not connected
                and (
                    not connection_attempted
                    or exc.code in PROVEN_PRECONNECT_CODES
                )
            ),
            connected_known=connected,
            database_outcome=(
                "READ_ONLY_REJECTED" if args.preflight else "ROLLED_BACK"
            ),
        )
    except BaseException:
        return _report_failure(
            stage=(
                "connect"
                if connection_attempted and not connected
                else "unexpected"
            ),
            connected=connected,
            connection_attempted=connection_attempted,
            proven_preconnect=not connection_attempted,
            connected_known=False,
            database_outcome="UNKNOWN",
        )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
