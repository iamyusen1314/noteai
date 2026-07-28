#!/usr/bin/env python3
"""Fixed-query read-only audit for the two first-launch legacy-role risks.

The production path uses one connection, one explicit repeatable-read
read-only transaction, four fixed set-based queries and a terminal ROLLBACK.
It reads schema/catalog metadata and aggregate business-row counts only.
"""

from __future__ import annotations

import hashlib
import json
import re
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
except (ImportError, ModuleNotFoundError):
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
REGISTRY_REVIEW_PATH = (
    ROOT / "security" / "vex" / "b06671f-registry-release-review.json"
)
TASK_ID = "PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-001"
AUDIT_ID = "PROD-FIRST-LAUNCH-LEGACY-ROLE-RISK-SET-AUDIT-002"
RUN_ID = "PROD-FIRST-LAUNCH-LEGACY-ROLE-RISK-SET-AUDIT-RUN-001"
APPLICATION_NAME = "noteai_role_risk_set_audit_v2"
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
NEW_RUNTIME_ROLES = tuple(
    role for role in RUNTIME_ROLES if role not in {"noteai_app", "noteai_xhs"}
)
NEW_TABLES = (
    "account_deletion_requests",
    "ai_dispatch_state",
    "ai_operation_media_refs",
    "ai_operation_outbox",
    "ai_operation_settlements",
    "ai_payload_refs",
    "auth_login_limits",
    "auth_verification_challenges",
    "content_retention",
    "payment_cash_ledger",
    "payment_credit_consumptions",
    "payment_credit_positions",
    "payment_entitlement_ledger",
    "payment_events",
    "payment_orders",
    "payment_reconciliation_items",
    "payment_reconciliation_runs",
    "payment_refunds",
    "payment_settlement_summaries",
    "private_media_refs",
    "tracking_provider_attempts",
    "user_contract_acceptances",
    "xhs_trends_provider_attempts",
    "xhs_trends_runs",
    "xhs_trends_service_state",
    "xhs_trends_snapshot_evidence",
)
EXPECTED_REGISTRY_EVIDENCE_SHA256 = (
    "b44b8861202d97b9f0784dd89f3b6056e5fc4af2b6939d28bdfe1b2f49b540f3"
)
EXPECTED_REGISTRY_REVISION = "b06671fbcca51f884b04c86edcf116e373c6cfa8"
STAGE_ORDER = (
    "session",
    "ledger_inventory",
    "role_graph",
    "xhs_acl",
    "rollback",
)
_SQLSTATE = re.compile(r"^[0-9A-Z]{5}$")


class RoleRiskSetAuditError(RuntimeError):
    """Sanitized fixed-query audit failure."""

    def __init__(
        self,
        code: str,
        *,
        stage: str,
        sqlstate: str = "NONE0",
        incident_class: str = "CONNECTED_UNKNOWN",
    ):
        super().__init__(code)
        self.code = code
        self.stage = stage
        self.sqlstate = sqlstate if _SQLSTATE.fullmatch(sqlstate) else "XXXXX"
        self.incident_class = incident_class


SESSION_SQL = """
SELECT
    current_setting('default_transaction_read_only') = 'on' AS default_ro,
    current_setting('transaction_read_only') = 'on' AS transaction_ro,
    session_user <> 'noteai_xhs'
        AND current_user <> 'noteai_xhs' AS executor_not_xhs,
    session_user = current_user
        AND current_user = current_role AS identity_unchanged
"""

LEDGER_INVENTORY_SQL = """
WITH
ledger AS (
    SELECT
        COALESCE(array_agg(version ORDER BY version), ARRAY[]::text[]) AS names,
        COUNT(*)::integer AS row_count
    FROM schema_migrations
),
tables AS (
    SELECT
        COALESCE(
            array_agg(table_name::text ORDER BY table_name),
            ARRAY[]::text[]
        ) AS names,
        COUNT(*)::integer AS row_count
    FROM information_schema.tables
    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
),
sequences AS (
    SELECT
        COALESCE(
            array_agg(sequence_name::text ORDER BY sequence_name),
            ARRAY[]::text[]
        ) AS names,
        COUNT(*)::integer AS row_count
    FROM information_schema.sequences
    WHERE sequence_schema = 'public'
)
SELECT
    ledger.names = %s::text[] AS ledger_exact,
    ledger.row_count AS ledger_count,
    tables.names = %s::text[] AS tables_exact,
    tables.row_count AS table_count,
    sequences.names = %s::text[] AS sequences_exact,
    sequences.row_count AS sequence_count,
    (
        SELECT COUNT(*)::integer
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'schema_migrations'
          AND column_name = 'sha256'
    ) AS ledger_sha_column_count,
    (
        SELECT COUNT(*)::integer
        FROM pg_constraint
        WHERE conrelid = 'schema_migrations'::regclass
          AND conname = 'schema_migrations_sha256_format'
    ) AS ledger_sha_constraint_count,
    (
        SELECT COUNT(*)::integer
        FROM pg_roles
        WHERE rolname = ANY(%s)
    ) AS new_runtime_role_count,
    (
        SELECT COUNT(*)::integer
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type = 'BASE TABLE'
          AND table_name = ANY(%s)
    ) AS new_table_count,
    (
        (SELECT COUNT(*) FROM notes)
        + (SELECT COUNT(*) FROM saved_diagnoses)
    )::integer AS retention_backfill_source_count
FROM ledger, tables, sequences
"""

ROLE_GRAPH_SQL = """
WITH
runtime_roles AS (
    SELECT
        rolname, rolsuper, rolinherit, rolcreaterole, rolcreatedb,
        rolcanlogin, rolreplication, rolbypassrls
    FROM pg_roles
    WHERE rolname = ANY(%s)
),
memberships AS (
    SELECT
        granted.rolname AS granted_name,
        member.rolname AS member_name,
        membership.admin_option,
        (to_jsonb(membership)->>'inherit_option')::boolean AS inherit_option,
        (to_jsonb(membership)->>'set_option')::boolean AS set_option,
        membership.grantor = membership.member AS grantor_is_member
    FROM pg_auth_members membership
    JOIN pg_roles granted ON granted.oid = membership.roleid
    JOIN pg_roles member ON member.oid = membership.member
    WHERE granted.rolname = ANY(%s) OR member.rolname = ANY(%s)
),
exact_membership AS (
    SELECT *
    FROM memberships
    WHERE granted_name = 'noteai_xhs'
      AND member_name = 'noteai_admin'
)
SELECT
    (SELECT COUNT(*)::integer FROM runtime_roles) AS runtime_role_count,
    (
        SELECT COUNT(*)::integer FROM runtime_roles
        WHERE rolname = ANY(%s)
    ) AS new_runtime_role_count,
    COALESCE((
        SELECT
            NOT rolsuper AND rolinherit AND NOT rolcreaterole
            AND NOT rolcreatedb AND rolcanlogin AND NOT rolreplication
            AND NOT rolbypassrls
        FROM runtime_roles WHERE rolname = 'noteai_app'
    ), FALSE) AS app_attributes_exact,
    COALESCE((
        SELECT
            NOT rolsuper AND NOT rolinherit AND NOT rolcreaterole
            AND NOT rolcreatedb AND rolcanlogin AND NOT rolreplication
            AND NOT rolbypassrls
        FROM runtime_roles WHERE rolname = 'noteai_xhs'
    ), FALSE) AS xhs_attributes_exact,
    (SELECT COUNT(*)::integer FROM memberships) AS membership_count,
    (SELECT COUNT(*)::integer FROM exact_membership) AS exact_edge_count,
    COALESCE(
        (SELECT admin_option FROM exact_membership LIMIT 1),
        FALSE
    ) AS membership_admin,
    (SELECT inherit_option FROM exact_membership LIMIT 1)
        AS membership_inherit,
    (SELECT set_option FROM exact_membership LIMIT 1) AS membership_set,
    COALESCE(
        (SELECT grantor_is_member FROM exact_membership LIMIT 1),
        FALSE
    ) AS grantor_is_member,
    (
        SELECT COUNT(*)::integer
        FROM pg_auth_members membership
        JOIN pg_roles member ON member.oid = membership.member
        WHERE member.rolname = 'noteai_app'
    ) AS app_incoming_membership_count,
    (
        SELECT COUNT(*)::integer
        FROM pg_roles role
        WHERE role.rolname <> 'noteai_app'
          AND pg_has_role('noteai_app', role.oid, 'USAGE')
          AND (
              role.rolsuper OR role.rolcreaterole OR role.rolcreatedb
              OR role.rolreplication OR role.rolbypassrls
          )
    ) AS app_high_privilege_inheritance_count
"""

XHS_ACL_SQL = """
WITH
expected_table(table_name, privilege_type) AS (
    SELECT * FROM unnest(%s::text[], %s::text[])
),
table_matrix AS (
    SELECT
        table_inventory.table_name,
        privilege.privilege_type,
        expected_table.table_name IS NOT NULL AS expected,
        has_table_privilege(
            'noteai_xhs',
            format('%%I.%%I', 'public', table_inventory.table_name),
            privilege.privilege_type
        ) AS actual,
        has_table_privilege(
            'noteai_xhs',
            format('%%I.%%I', 'public', table_inventory.table_name),
            privilege.privilege_type || ' WITH GRANT OPTION'
        ) AS grantable
    FROM unnest(%s::text[]) AS table_inventory(table_name)
    CROSS JOIN unnest(%s::text[]) AS privilege(privilege_type)
    LEFT JOIN expected_table USING (table_name, privilege_type)
),
column_matrix AS (
    SELECT
        column_inventory.table_name,
        column_inventory.column_name,
        privilege.privilege_type,
        expected_table.table_name IS NOT NULL AS expected,
        has_column_privilege(
            'noteai_xhs',
            format('%%I.%%I', 'public', column_inventory.table_name),
            column_inventory.column_name,
            privilege.privilege_type
        ) AS actual,
        has_column_privilege(
            'noteai_xhs',
            format('%%I.%%I', 'public', column_inventory.table_name),
            column_inventory.column_name,
            privilege.privilege_type || ' WITH GRANT OPTION'
        ) AS grantable
    FROM information_schema.columns column_inventory
    CROSS JOIN unnest(%s::text[]) AS privilege(privilege_type)
    LEFT JOIN expected_table
      ON expected_table.table_name = column_inventory.table_name
     AND expected_table.privilege_type = privilege.privilege_type
    WHERE column_inventory.table_schema = 'public'
      AND column_inventory.table_name = ANY(%s)
),
expected_sequence(sequence_name, privilege_type) AS (
    SELECT * FROM unnest(%s::text[], %s::text[])
),
sequence_matrix AS (
    SELECT
        sequence_inventory.sequence_name,
        privilege.privilege_type,
        expected_sequence.sequence_name IS NOT NULL AS expected,
        has_sequence_privilege(
            'noteai_xhs',
            format('%%I.%%I', 'public', sequence_inventory.sequence_name),
            privilege.privilege_type
        ) AS actual,
        has_sequence_privilege(
            'noteai_xhs',
            format('%%I.%%I', 'public', sequence_inventory.sequence_name),
            privilege.privilege_type || ' WITH GRANT OPTION'
        ) AS grantable
    FROM unnest(%s::text[]) AS sequence_inventory(sequence_name)
    CROSS JOIN unnest(%s::text[]) AS privilege(privilege_type)
    LEFT JOIN expected_sequence USING (sequence_name, privilege_type)
),
public_functions AS (
    SELECT function.oid
    FROM pg_proc function
    JOIN pg_namespace namespace ON namespace.oid = function.pronamespace
    WHERE namespace.nspname = 'public'
)
SELECT
    has_database_privilege(
        'noteai_xhs', current_database(), 'CONNECT'
    ) AS database_connect,
    has_database_privilege(
        'noteai_xhs', current_database(), 'CREATE'
    ) AS database_create,
    has_database_privilege(
        'noteai_xhs', current_database(), 'TEMP'
    ) AS database_temporary,
    (
        has_database_privilege(
            'noteai_xhs', current_database(), 'CONNECT WITH GRANT OPTION'
        )::integer
        + has_database_privilege(
            'noteai_xhs', current_database(), 'CREATE WITH GRANT OPTION'
        )::integer
        + has_database_privilege(
            'noteai_xhs', current_database(), 'TEMP WITH GRANT OPTION'
        )::integer
    )::integer AS database_grantable_count,
    has_schema_privilege(
        'noteai_xhs', 'public', 'USAGE'
    ) AS schema_usage,
    has_schema_privilege(
        'noteai_xhs', 'public', 'CREATE'
    ) AS schema_create,
    (
        has_schema_privilege(
            'noteai_xhs', 'public', 'USAGE WITH GRANT OPTION'
        )::integer
        + has_schema_privilege(
            'noteai_xhs', 'public', 'CREATE WITH GRANT OPTION'
        )::integer
    )::integer AS schema_grantable_count,
    (SELECT COUNT(*)::integer FROM table_matrix) AS table_check_count,
    (
        SELECT COUNT(*)::integer FROM table_matrix
        WHERE actual IS DISTINCT FROM expected
    ) AS table_mismatch_count,
    (
        SELECT COUNT(*)::integer FROM table_matrix WHERE actual
    ) AS table_positive_count,
    (
        SELECT COUNT(*)::integer FROM table_matrix WHERE grantable
    ) AS table_grantable_count,
    (SELECT COUNT(*)::integer FROM column_matrix) AS column_check_count,
    (
        SELECT COUNT(*)::integer FROM column_matrix
        WHERE actual IS DISTINCT FROM expected
    ) AS column_mismatch_count,
    (
        SELECT COUNT(*)::integer FROM column_matrix WHERE actual
    ) AS column_positive_count,
    (
        SELECT COUNT(*)::integer FROM column_matrix WHERE grantable
    ) AS column_grantable_count,
    (SELECT COUNT(*)::integer FROM sequence_matrix) AS sequence_check_count,
    (
        SELECT COUNT(*)::integer FROM sequence_matrix
        WHERE actual IS DISTINCT FROM expected
    ) AS sequence_mismatch_count,
    (
        SELECT COUNT(*)::integer FROM sequence_matrix WHERE actual
    ) AS sequence_positive_count,
    (
        SELECT COUNT(*)::integer FROM sequence_matrix WHERE grantable
    ) AS sequence_grantable_count,
    (SELECT COUNT(*)::integer FROM public_functions)
        AS public_function_count,
    (
        SELECT COUNT(*)::integer FROM public_functions
        WHERE has_function_privilege('noteai_xhs', oid, 'EXECUTE')
    ) AS public_function_execute_count,
    (
        SELECT COUNT(*)::integer FROM public_functions
        WHERE has_function_privilege(
            'noteai_xhs', oid, 'EXECUTE WITH GRANT OPTION'
        )
    ) AS public_function_grantable_count,
    (
        (SELECT COUNT(*) FROM pg_class
         WHERE relowner = 'noteai_xhs'::regrole)
        + (SELECT COUNT(*) FROM pg_namespace
           WHERE nspowner = 'noteai_xhs'::regrole)
        + (SELECT COUNT(*) FROM pg_proc
           WHERE proowner = 'noteai_xhs'::regrole)
    )::integer AS ownership_count,
    (
        SELECT COUNT(*)::integer
        FROM pg_default_acl default_acl
        CROSS JOIN LATERAL aclexplode(default_acl.defaclacl) exploded
        WHERE exploded.grantee = 'noteai_xhs'::regrole
    ) AS default_acl_entry_count
"""


def _source_registry() -> dict[str, str]:
    migrations = sorted(MIGRATION_DIR.glob("*.sql"))
    versions = tuple(path.name.split("_", 1)[0] for path in migrations)
    if versions != tuple(f"{number:04d}" for number in range(1, 17)):
        raise RoleRiskSetAuditError(
            "source_set",
            stage="local_source",
            incident_class="PRE_CONNECT",
        )
    try:
        registry_review = json.loads(
            REGISTRY_REVIEW_PATH.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise RoleRiskSetAuditError(
            "registry_evidence",
            stage="local_source",
            incident_class="PRE_CONNECT",
        ) from exc
    if not (
        registry_review.get("result") == "PASS"
        and registry_review.get("application_revision")
        == EXPECTED_REGISTRY_REVISION
        and registry_review.get("evidence_sha256")
        == EXPECTED_REGISTRY_EVIDENCE_SHA256
        and registry_review.get("checks", {}).get(
            "five_unique_registry_manifest_digests"
        ) is True
        and registry_review.get("scope", {}).get(
            "application_deployed"
        ) is False
    ):
        raise RoleRiskSetAuditError(
            "registry_evidence",
            stage="local_source",
            incident_class="PRE_CONNECT",
        )
    return {
        "auditor": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "executor": hashlib.sha256(EXECUTOR_PATH.read_bytes()).hexdigest(),
        "acl": hashlib.sha256(ACL_PATH.read_bytes()).hexdigest(),
        "registry_review": hashlib.sha256(
            REGISTRY_REVIEW_PATH.read_bytes()
        ).hexdigest(),
        "registry_evidence": EXPECTED_REGISTRY_EVIDENCE_SHA256,
        **{
            path.name.split("_", 1)[0]: hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in migrations
        },
    }


def _sqlstate(exc: BaseException) -> str:
    value = str(getattr(exc, "sqlstate", "") or "").upper()
    return value if _SQLSTATE.fullmatch(value) else "XXXXX"


def _one(
    conn: Any,
    *,
    stage: str,
    sql: str,
    params: tuple[Any, ...] = (),
) -> dict[str, Any]:
    try:
        rows = conn.execute(sql, params).fetchall()
    except BaseException as exc:
        raise RoleRiskSetAuditError(
            "query_failed",
            stage=stage,
            sqlstate=_sqlstate(exc),
            incident_class="CONNECTED_KNOWN",
        ) from exc
    if len(rows) != 1:
        raise RoleRiskSetAuditError(
            "stage_shape",
            stage=stage,
            incident_class="CONNECTED_KNOWN",
        )
    row = rows[0]
    return dict(row) if isinstance(row, dict) else dict(row)


def _table_expectations() -> tuple[list[str], list[str]]:
    pairs = [
        (table, privilege)
        for table, privileges in XHS_TABLE_PRIVILEGES.items()
        for privilege in privileges
    ]
    return (
        [table for table, _ in pairs],
        [privilege for _, privilege in pairs],
    )


def _sequence_expectations() -> tuple[list[str], list[str]]:
    expected_sequences = (
        "crawler_events_id_seq",
        "hot_keywords_id_seq",
        "keyword_snapshots_id_seq",
    )
    return list(expected_sequences), ["USAGE"] * len(expected_sequences)


def collect_role_risk_set(conn: Any) -> dict[str, Any]:
    """Run four fixed queries and a terminal rollback."""
    completed: list[str] = []
    transaction_declared_read_only = False
    rollback_confirmed = False
    active_error: RoleRiskSetAuditError | None = None
    try:
        try:
            conn.execute(
                "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
            transaction_declared_read_only = True
        except BaseException as exc:
            raise RoleRiskSetAuditError(
                "begin_failed",
                stage="session",
                sqlstate=_sqlstate(exc),
            ) from exc

        session = _one(conn, stage="session", sql=SESSION_SQL)
        completed.append("session")
        ledger_inventory = _one(
            conn,
            stage="ledger_inventory",
            sql=LEDGER_INVENTORY_SQL,
            params=(
                list(LEGACY_LEDGER_NAMES),
                list(EXPECTED_PUBLIC_TABLES),
                list(EXPECTED_PUBLIC_SEQUENCES),
                list(NEW_RUNTIME_ROLES),
                list(NEW_TABLES),
            ),
        )
        completed.append("ledger_inventory")
        role_graph = _one(
            conn,
            stage="role_graph",
            sql=ROLE_GRAPH_SQL,
            params=(
                list(RUNTIME_ROLES),
                list(RUNTIME_ROLES),
                list(RUNTIME_ROLES),
                list(NEW_RUNTIME_ROLES),
            ),
        )
        completed.append("role_graph")
        table_names, table_privileges = _table_expectations()
        sequence_names, sequence_privileges = _sequence_expectations()
        xhs_acl = _one(
            conn,
            stage="xhs_acl",
            sql=XHS_ACL_SQL,
            params=(
                table_names,
                table_privileges,
                list(EXPECTED_PUBLIC_TABLES),
                list(TABLE_PRIVILEGES),
                ["SELECT", "INSERT", "UPDATE", "REFERENCES"],
                list(EXPECTED_PUBLIC_TABLES),
                sequence_names,
                sequence_privileges,
                list(EXPECTED_PUBLIC_SEQUENCES),
                list(SEQUENCE_PRIVILEGES),
            ),
        )
        completed.append("xhs_acl")
    except RoleRiskSetAuditError as exc:
        active_error = exc
    finally:
        if transaction_declared_read_only:
            try:
                conn.execute("ROLLBACK")
                rollback_confirmed = True
                completed.append("rollback")
            except BaseException as exc:
                raise RoleRiskSetAuditError(
                    "rollback_failed",
                    stage="rollback",
                    sqlstate=_sqlstate(exc),
                ) from exc
    if active_error is not None:
        if rollback_confirmed:
            active_error.incident_class = "CONNECTED_KNOWN"
        raise active_error

    session_ok = (
        bool(session["default_ro"])
        and bool(session["transaction_ro"])
        and bool(session["executor_not_xhs"])
        and bool(session["identity_unchanged"])
    )
    ledger_ok = (
        bool(ledger_inventory["ledger_exact"])
        and int(ledger_inventory["ledger_count"]) == 8
        and bool(ledger_inventory["tables_exact"])
        and int(ledger_inventory["table_count"])
        == len(EXPECTED_PUBLIC_TABLES)
        and bool(ledger_inventory["sequences_exact"])
        and int(ledger_inventory["sequence_count"])
        == len(EXPECTED_PUBLIC_SEQUENCES)
        and int(ledger_inventory["ledger_sha_column_count"]) == 0
        and int(ledger_inventory["ledger_sha_constraint_count"]) == 0
        and int(ledger_inventory["new_runtime_role_count"]) == 0
        and int(ledger_inventory["new_table_count"]) == 0
        and int(ledger_inventory["retention_backfill_source_count"]) == 0
    )
    role_ok = (
        int(role_graph["runtime_role_count"]) == 2
        and int(role_graph["new_runtime_role_count"]) == 0
        and bool(role_graph["app_attributes_exact"])
        and bool(role_graph["xhs_attributes_exact"])
        and int(role_graph["membership_count"]) == 1
        and int(role_graph["exact_edge_count"]) == 1
        and bool(role_graph["membership_admin"])
        and role_graph["membership_inherit"] is False
        and role_graph["membership_set"] is False
        and int(role_graph["app_incoming_membership_count"]) == 0
        and int(role_graph["app_high_privilege_inheritance_count"]) == 0
    )
    acl_ok = (
        bool(xhs_acl["database_connect"])
        and not bool(xhs_acl["database_create"])
        and not bool(xhs_acl["database_temporary"])
        and int(xhs_acl["database_grantable_count"]) == 0
        and bool(xhs_acl["schema_usage"])
        and not bool(xhs_acl["schema_create"])
        and int(xhs_acl["schema_grantable_count"]) == 0
        and int(xhs_acl["table_check_count"])
        == len(EXPECTED_PUBLIC_TABLES) * len(TABLE_PRIVILEGES)
        and int(xhs_acl["table_mismatch_count"]) == 0
        and int(xhs_acl["table_positive_count"])
        == sum(len(value) for value in XHS_TABLE_PRIVILEGES.values())
        and int(xhs_acl["table_grantable_count"]) == 0
        and int(xhs_acl["column_check_count"]) > 0
        and int(xhs_acl["column_mismatch_count"]) == 0
        and int(xhs_acl["column_grantable_count"]) == 0
        and int(xhs_acl["sequence_check_count"])
        == len(EXPECTED_PUBLIC_SEQUENCES) * len(SEQUENCE_PRIVILEGES)
        and int(xhs_acl["sequence_mismatch_count"]) == 0
        and int(xhs_acl["sequence_positive_count"]) == 3
        and int(xhs_acl["sequence_grantable_count"]) == 0
        and int(xhs_acl["public_function_count"]) == 0
        and int(xhs_acl["public_function_execute_count"]) == 0
        and int(xhs_acl["public_function_grantable_count"]) == 0
        and int(xhs_acl["ownership_count"]) == 0
        and int(xhs_acl["default_acl_entry_count"]) == 0
    )
    accepted = (
        session_ok
        and ledger_ok
        and role_ok
        and acl_ok
        and completed == list(STAGE_ORDER)
        and rollback_confirmed
    )
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "audit_id": AUDIT_ID,
        "run_id": RUN_ID,
        "status": "accepted_risk_observed" if accepted else "state_changed",
        "incident_class": "CONNECTED_KNOWN",
        "risk_profile": RISK_PROFILE,
        "risk_ids": list(RISK_IDS),
        "read_only": True,
        "isolation_level": "repeatable_read",
        "transaction_rolled_back": rollback_confirmed,
        "stage_order": completed,
        "fixed_query_count": 4,
        "database_connection_count": 1,
        "database_write_count": 0,
        "business_row_values_read": 0,
        "session": session,
        "ledger_inventory": ledger_inventory,
        "role_graph": role_graph,
        "xhs_acl": xhs_acl,
        "acceptance": {
            "session": session_ok,
            "ledger_inventory": ledger_ok,
            "role_graph": role_ok,
            "xhs_acl": acl_ok,
        },
        "source_registry": _source_registry(),
        "provider_calls": 0,
        "service_changes": 0,
        "public_traffic_requests": 0,
        "secret_values_exposed": 0,
    }


def _connect(database_url: str) -> Any:
    if psycopg is None:
        raise RoleRiskSetAuditError(
            "psycopg_unavailable",
            stage="connect",
            incident_class="PRE_CONNECT",
        )
    return psycopg.connect(
        database_url,
        row_factory=dict_row,
        connect_timeout=10,
        application_name=APPLICATION_NAME,
        options=(
            "-c default_transaction_read_only=on "
            "-c statement_timeout=30000 "
            "-c lock_timeout=2000 "
            "-c idle_in_transaction_session_timeout=45000"
        ),
        autocommit=True,
    )


def main(*, database_url: str | None = None) -> int:
    connected = False
    connection_attempted = False
    try:
        _source_registry()
        if not database_url or not database_url.strip():
            raise RoleRiskSetAuditError(
                "database_url_missing",
                stage="connect",
                incident_class="PRE_CONNECT",
            )
        connection_attempted = True
        conn = _connect(database_url.strip())
        connected = True
        try:
            result = collect_role_risk_set(conn)
        finally:
            conn.close()
    except RoleRiskSetAuditError as exc:
        incident_class = exc.incident_class
        if not connected and not connection_attempted:
            incident_class = "PRE_CONNECT"
        database_outcome = (
            "NOT_CONNECTED"
            if incident_class == "PRE_CONNECT"
            else "KNOWN_READ_ONLY_FAILURE"
            if incident_class == "CONNECTED_KNOWN"
            else "UNKNOWN"
        )
        print(
            "production_first_launch_role_risk_set_audit=FAIL "
            f"stage={exc.stage} sqlstate={exc.sqlstate} "
            f"incident_class={incident_class} "
            f"database_connected={int(connected)} "
            f"database_outcome={database_outcome} "
            "automatic_retry=0 secrets=0",
            file=sys.stderr,
        )
        return (
            2
            if incident_class == "PRE_CONNECT"
            else 31
            if incident_class == "CONNECTED_KNOWN"
            else 1
        )
    except BaseException:
        print(
            "production_first_launch_role_risk_set_audit=FAIL "
            "stage=unexpected sqlstate=XXXXX "
            "incident_class=CONNECTED_UNKNOWN "
            f"database_connected={int(connected)} "
            "database_outcome=UNKNOWN automatic_retry=0 secrets=0",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "accepted_risk_observed" else 30


if __name__ == "__main__":
    raise SystemExit(main())
