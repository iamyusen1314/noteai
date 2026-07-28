#!/usr/bin/env python3
"""Fixed-query read-only preflight for the production migration owner.

The production path uses one protected connection, one explicit
repeatable-read read-only transaction, three fixed aggregate queries, one
fixed ``SET LOCAL ROLE`` command and a terminal ``ROLLBACK``.  It never
returns role names, connection details, object names or business-row values.
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
    from tools import production_schema_outcome_audit as outcome_contract
    from tools import production_schema_roles as schema_role_contract
except ModuleNotFoundError:
    import production_schema_outcome_audit as outcome_contract  # type: ignore[no-redef]
    import production_schema_roles as schema_role_contract  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_DIR = ROOT / "model" / "migrations" / "postgres"
ACL_PATH = ROOT / "scripts" / "postgres" / "noteai_production_runtime_roles.sql"
EXECUTOR_PATH = ROOT / "tools" / "production_schema_roles.py"
REGISTRY_REVIEW_PATH = (
    ROOT / "security" / "vex" / "b06671f-registry-release-review.json"
)
TASK_ID = (
    "PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-OWNER-AUTHORITY-PREFLIGHT-004"
)
AUDIT_ID = "PROD-SCHEMA-OWNER-AUTHORITY-READONLY-001"
RUN_ID = "PROD-SCHEMA-OWNER-AUTHORITY-READONLY-RUN-001"
APPLICATION_NAME = "noteai_schema_owner_authority_preflight_v1"
MIGRATION_OWNER_ROLE = schema_role_contract.MIGRATION_OWNER_ROLE
RUNTIME_ROLES = schema_role_contract.RUNTIME_ROLES
NEW_RUNTIME_ROLES = schema_role_contract.NEW_RUNTIME_ROLES
LEGACY_LEDGER_NAMES = tuple(
    path.name
    for path in sorted(MIGRATION_DIR.glob("*.sql"))
    if path.name.split("_", 1)[0] in outcome_contract.LEGACY_VERSIONS
)
LEGACY_TABLES = outcome_contract.LEGACY_TABLES
LEGACY_SEQUENCES = outcome_contract.EXPECTED_SEQUENCES
EXPECTED_REGISTRY_EVIDENCE_SHA256 = (
    "b44b8861202d97b9f0784dd89f3b6056e5fc4af2b6939d28bdfe1b2f49b540f3"
)
EXPECTED_REGISTRY_REVISION = "b06671fbcca51f884b04c86edcf116e373c6cfa8"
STAGE_ORDER = (
    "session",
    "migration_owner_activation",
    "owner_contract",
    "production_state",
    "rollback",
)
_SQLSTATE = re.compile(r"^[0-9A-Z]{5}$")


class OwnerAuthorityPreflightError(RuntimeError):
    """Sanitized owner-authority preflight failure."""

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
WITH executor AS (
    SELECT oid
    FROM pg_roles
    WHERE rolname = session_user
)
SELECT
    current_setting('default_transaction_read_only') = 'on' AS default_ro,
    current_setting('transaction_read_only') = 'on' AS transaction_ro,
    session_user = current_user
        AND current_user = current_role AS identity_unchanged,
    session_user::text <> ALL(%s::text[]) AS executor_not_runtime,
    session_user = %s AS executor_is_owner,
    (
        session_user = %s
        OR pg_has_role(session_user, %s, 'SET')
    ) AS owner_activation_capable,
    CASE WHEN session_user = %s THEN 0 ELSE (
        (SELECT COUNT(*) FROM pg_class object
         JOIN pg_namespace namespace ON namespace.oid=object.relnamespace
         WHERE namespace.nspname='public'
           AND object.relowner=(SELECT oid FROM executor))
        + (SELECT COUNT(*) FROM pg_proc object
           JOIN pg_namespace namespace ON namespace.oid=object.pronamespace
           WHERE namespace.nspname='public'
             AND object.proowner=(SELECT oid FROM executor))
        + (SELECT COUNT(*) FROM pg_database database
           WHERE database.datdba=(SELECT oid FROM executor))
        + (SELECT COUNT(*) FROM pg_namespace namespace
           WHERE namespace.nspowner=(SELECT oid FROM executor))
        + (SELECT COUNT(*) FROM pg_default_acl default_acl
           WHERE default_acl.defaclrole=(SELECT oid FROM executor))
    ) END::integer AS transient_executor_dependency_count,
    (
        SELECT COUNT(*)::integer
        FROM pg_auth_members membership
        JOIN pg_roles granted ON granted.oid=membership.roleid
        WHERE membership.member=(SELECT oid FROM executor)
          AND granted.rolname = ANY(%s::text[])
    ) AS unexpected_runtime_membership_count,
    (
        SELECT COUNT(*)::integer
        FROM pg_auth_members membership
        JOIN pg_roles granted ON granted.oid=membership.roleid
        WHERE membership.member=(SELECT oid FROM executor)
          AND granted.rolname=%s
          AND (to_jsonb(membership)->>'set_option')::boolean
    ) AS direct_owner_set_membership_count
FROM executor
"""


OWNER_CONTRACT_SQL = """
WITH owner_role AS (
    SELECT oid, rolsuper, rolcreaterole
    FROM pg_roles
    WHERE rolname=%s
),
public_relations AS (
    SELECT object.relowner
    FROM pg_class object
    JOIN pg_namespace namespace ON namespace.oid=object.relnamespace
    WHERE namespace.nspname='public'
),
public_functions AS (
    SELECT object.proowner
    FROM pg_proc object
    JOIN pg_namespace namespace ON namespace.oid=object.pronamespace
    WHERE namespace.nspname='public'
)
SELECT
    current_user=%s AND current_role=%s AS owner_activated,
    session_user::text <> ALL(%s::text[]) AS executor_not_runtime,
    COALESCE(
        (SELECT NOT rolsuper FROM owner_role),
        FALSE
    ) AS owner_non_superuser,
    COALESCE(
        (SELECT rolcreaterole FROM owner_role),
        FALSE
    ) AS owner_createrole,
    COALESCE((
        SELECT database.datdba=(SELECT oid FROM owner_role)
        FROM pg_database database
        WHERE database.datname=current_database()
    ), FALSE) AS owner_database_exact,
    has_schema_privilege(%s, 'public', 'USAGE')
        AS owner_schema_usage,
    has_schema_privilege(
        %s, 'public', 'CREATE WITH GRANT OPTION'
    ) AS owner_schema_create_grantable,
    (SELECT COUNT(*)::integer FROM public_relations)
        AS public_relation_count,
    (SELECT COUNT(*)::integer FROM public_functions)
        AS public_function_count,
    (
        (SELECT COUNT(*) FROM public_relations
         WHERE relowner<>(SELECT oid FROM owner_role))
        + (SELECT COUNT(*) FROM public_functions
           WHERE proowner<>(SELECT oid FROM owner_role))
    )::integer AS owner_mismatch_count
"""


PRODUCTION_STATE_SQL = """
WITH
ledger AS (
    SELECT
        COALESCE(array_agg(version ORDER BY version), ARRAY[]::text[])
            AS names,
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
    WHERE table_schema='public' AND table_type='BASE TABLE'
),
sequences AS (
    SELECT
        COALESCE(
            array_agg(sequence_name::text ORDER BY sequence_name),
            ARRAY[]::text[]
        ) AS names,
        COUNT(*)::integer AS row_count
    FROM information_schema.sequences
    WHERE sequence_schema='public'
),
runtime_roles AS (
    SELECT
        rolname, rolsuper, rolinherit, rolcreaterole, rolcreatedb,
        rolcanlogin, rolreplication, rolbypassrls
    FROM pg_roles
    WHERE rolname = ANY(%s::text[])
),
runtime_memberships AS (
    SELECT
        granted.rolname AS granted_name,
        member.rolname AS member_name,
        membership.admin_option,
        (to_jsonb(membership)->>'inherit_option')::boolean
            AS inherit_option,
        (to_jsonb(membership)->>'set_option')::boolean AS set_option
    FROM pg_auth_members membership
    JOIN pg_roles granted ON granted.oid=membership.roleid
    JOIN pg_roles member ON member.oid=membership.member
    WHERE granted.rolname = ANY(%s::text[])
       OR member.rolname = ANY(%s::text[])
),
accepted_membership AS (
    SELECT *
    FROM runtime_memberships
    WHERE granted_name='noteai_xhs'
      AND member_name=%s
)
SELECT
    ledger.names=%s::text[] AS ledger_exact,
    ledger.row_count AS ledger_count,
    tables.names=%s::text[] AS tables_exact,
    tables.row_count AS table_count,
    sequences.names=%s::text[] AS sequences_exact,
    sequences.row_count AS sequence_count,
    (
        SELECT COUNT(*)::integer
        FROM information_schema.columns
        WHERE table_schema='public'
          AND table_name='schema_migrations'
          AND column_name='sha256'
    ) AS ledger_sha_column_count,
    (
        SELECT COUNT(*)::integer
        FROM runtime_roles
    ) AS runtime_role_count,
    (
        SELECT COUNT(*)::integer
        FROM runtime_roles
        WHERE rolname = ANY(%s::text[])
    ) AS new_runtime_role_count,
    COALESCE((
        SELECT
            NOT rolsuper AND rolinherit AND NOT rolcreaterole
            AND NOT rolcreatedb AND rolcanlogin AND NOT rolreplication
            AND NOT rolbypassrls
        FROM runtime_roles
        WHERE rolname='noteai_app'
    ), FALSE) AS app_attributes_exact,
    COALESCE((
        SELECT
            NOT rolsuper AND NOT rolinherit AND NOT rolcreaterole
            AND NOT rolcreatedb AND rolcanlogin AND NOT rolreplication
            AND NOT rolbypassrls
        FROM runtime_roles
        WHERE rolname='noteai_xhs'
    ), FALSE) AS xhs_attributes_exact,
    (SELECT COUNT(*)::integer FROM runtime_memberships)
        AS runtime_membership_count,
    (SELECT COUNT(*)::integer FROM accepted_membership)
        AS accepted_membership_count,
    COALESCE(
        (SELECT admin_option FROM accepted_membership LIMIT 1),
        FALSE
    ) AS accepted_membership_admin,
    (SELECT inherit_option FROM accepted_membership LIMIT 1)
        AS accepted_membership_inherit,
    (SELECT set_option FROM accepted_membership LIMIT 1)
        AS accepted_membership_set,
    (
        SELECT COUNT(*)::integer
        FROM pg_auth_members membership
        JOIN pg_roles member ON member.oid=membership.member
        WHERE member.rolname='noteai_app'
    ) AS app_incoming_membership_count,
    (
        SELECT COUNT(*)::integer
        FROM pg_roles role
        WHERE role.rolname<>'noteai_app'
          AND pg_has_role('noteai_app', role.oid, 'USAGE')
          AND (
              role.rolsuper OR role.rolcreaterole OR role.rolcreatedb
              OR role.rolreplication OR role.rolbypassrls
          )
    ) AS app_high_privilege_inheritance_count,
    (
        (SELECT COUNT(*) FROM notes)
        + (SELECT COUNT(*) FROM saved_diagnoses)
    )::integer AS retention_backfill_source_count,
    (
        SELECT COUNT(*)::integer
        FROM pg_roles
        WHERE (
            rolname LIKE 'noteai_schema_task_%%'
            OR rolname LIKE 'noteai_schema_roles_v5_%%'
        )
          AND rolname<>session_user
    ) AS task_role_residue_count
FROM ledger, tables, sequences
"""


def _source_registry() -> dict[str, str]:
    migrations = sorted(MIGRATION_DIR.glob("*.sql"))
    versions = tuple(path.name.split("_", 1)[0] for path in migrations)
    if versions != schema_role_contract.EXPECTED_VERSIONS:
        raise OwnerAuthorityPreflightError(
            "source_set",
            stage="local_source",
            incident_class="PRE_CONNECT",
        )
    try:
        registry_review = json.loads(
            REGISTRY_REVIEW_PATH.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise OwnerAuthorityPreflightError(
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
        raise OwnerAuthorityPreflightError(
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
        raise OwnerAuthorityPreflightError(
            "query_failed",
            stage=stage,
            sqlstate=_sqlstate(exc),
        ) from exc
    if len(rows) != 1:
        raise OwnerAuthorityPreflightError(
            "stage_shape",
            stage=stage,
        )
    return dict(rows[0])


def collect_owner_authority(conn: Any) -> dict[str, Any]:
    """Run the fixed owner-authority audit and terminal rollback."""
    completed: list[str] = []
    transaction_declared_read_only = False
    rollback_confirmed = False
    active_error: OwnerAuthorityPreflightError | None = None
    try:
        try:
            conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
            transaction_declared_read_only = True
        except BaseException as exc:
            raise OwnerAuthorityPreflightError(
                "begin_failed",
                stage="session",
                sqlstate=_sqlstate(exc),
            ) from exc

        session = _one(
            conn,
            stage="session",
            sql=SESSION_SQL,
            params=(
                list(RUNTIME_ROLES),
                MIGRATION_OWNER_ROLE,
                MIGRATION_OWNER_ROLE,
                MIGRATION_OWNER_ROLE,
                MIGRATION_OWNER_ROLE,
                list(RUNTIME_ROLES),
                MIGRATION_OWNER_ROLE,
            ),
        )
        completed.append("session")
        try:
            conn.execute(f"SET LOCAL ROLE {MIGRATION_OWNER_ROLE}")
        except BaseException as exc:
            raise OwnerAuthorityPreflightError(
                "owner_activation_failed",
                stage="migration_owner_activation",
                sqlstate=_sqlstate(exc),
            ) from exc
        completed.append("migration_owner_activation")
        owner_contract = _one(
            conn,
            stage="owner_contract",
            sql=OWNER_CONTRACT_SQL,
            params=(
                MIGRATION_OWNER_ROLE,
                MIGRATION_OWNER_ROLE,
                MIGRATION_OWNER_ROLE,
                list(RUNTIME_ROLES),
                MIGRATION_OWNER_ROLE,
                MIGRATION_OWNER_ROLE,
            ),
        )
        completed.append("owner_contract")
        production_state = _one(
            conn,
            stage="production_state",
            sql=PRODUCTION_STATE_SQL,
            params=(
                list(RUNTIME_ROLES),
                list(RUNTIME_ROLES),
                list(RUNTIME_ROLES),
                MIGRATION_OWNER_ROLE,
                list(LEGACY_LEDGER_NAMES),
                list(LEGACY_TABLES),
                list(LEGACY_SEQUENCES),
                list(NEW_RUNTIME_ROLES),
            ),
        )
        completed.append("production_state")
    except OwnerAuthorityPreflightError as exc:
        active_error = exc
    finally:
        if transaction_declared_read_only:
            try:
                conn.execute("ROLLBACK")
                rollback_confirmed = True
                completed.append("rollback")
            except BaseException as exc:
                raise OwnerAuthorityPreflightError(
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
        and bool(session["identity_unchanged"])
        and bool(session["executor_not_runtime"])
        and bool(session["owner_activation_capable"])
        and int(session["transient_executor_dependency_count"]) == 0
        and int(session["unexpected_runtime_membership_count"]) == 0
        and (
            bool(session["executor_is_owner"])
            or int(session["direct_owner_set_membership_count"]) == 1
        )
    )
    owner_ok = (
        bool(owner_contract["owner_activated"])
        and bool(owner_contract["executor_not_runtime"])
        and bool(owner_contract["owner_non_superuser"])
        and bool(owner_contract["owner_createrole"])
        and bool(owner_contract["owner_database_exact"])
        and bool(owner_contract["owner_schema_usage"])
        and bool(owner_contract["owner_schema_create_grantable"])
        and int(owner_contract["public_relation_count"]) > 0
        and int(owner_contract["owner_mismatch_count"]) == 0
    )
    state_ok = (
        bool(production_state["ledger_exact"])
        and int(production_state["ledger_count"]) == 8
        and bool(production_state["tables_exact"])
        and int(production_state["table_count"]) == len(LEGACY_TABLES)
        and bool(production_state["sequences_exact"])
        and int(production_state["sequence_count"]) == len(LEGACY_SEQUENCES)
        and int(production_state["ledger_sha_column_count"]) == 0
        and int(production_state["runtime_role_count"]) == 2
        and int(production_state["new_runtime_role_count"]) == 0
        and bool(production_state["app_attributes_exact"])
        and bool(production_state["xhs_attributes_exact"])
        and int(production_state["runtime_membership_count"]) == 1
        and int(production_state["accepted_membership_count"]) == 1
        and bool(production_state["accepted_membership_admin"])
        and production_state["accepted_membership_inherit"] is False
        and production_state["accepted_membership_set"] is False
        and int(production_state["app_incoming_membership_count"]) == 0
        and int(
            production_state["app_high_privilege_inheritance_count"]
        ) == 0
        and int(production_state["retention_backfill_source_count"]) == 0
        and int(production_state["task_role_residue_count"]) == 0
    )
    verified = (
        session_ok
        and owner_ok
        and state_ok
        and completed == list(STAGE_ORDER)
        and rollback_confirmed
    )
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "audit_id": AUDIT_ID,
        "run_id": RUN_ID,
        "status": (
            "owner_authority_verified" if verified else "state_changed"
        ),
        "incident_class": "CONNECTED_KNOWN",
        "read_only": True,
        "isolation_level": "repeatable_read",
        "transaction_rolled_back": rollback_confirmed,
        "stage_order": completed,
        "fixed_query_count": 3,
        "owner_activation_command_count": 1,
        "database_connection_count": 1,
        "database_write_count": 0,
        "business_row_values_read": 0,
        "session": session,
        "owner_contract": owner_contract,
        "production_state": production_state,
        "acceptance": {
            "session": session_ok,
            "owner_contract": owner_ok,
            "production_state": state_ok,
        },
        "source_registry": _source_registry(),
        "provider_calls": 0,
        "service_changes": 0,
        "public_traffic_requests": 0,
        "secret_values_exposed": 0,
    }


def _connect(database_url: str) -> Any:
    if psycopg is None:
        raise OwnerAuthorityPreflightError(
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
            raise OwnerAuthorityPreflightError(
                "database_url_missing",
                stage="connect",
                incident_class="PRE_CONNECT",
            )
        connection_attempted = True
        conn = _connect(database_url.strip())
        connected = True
        try:
            result = collect_owner_authority(conn)
        finally:
            conn.close()
    except OwnerAuthorityPreflightError as exc:
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
            "production_schema_owner_authority_preflight=FAIL "
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
            "production_schema_owner_authority_preflight=FAIL "
            "stage=unexpected sqlstate=XXXXX "
            "incident_class=CONNECTED_UNKNOWN "
            f"database_connected={int(connected)} "
            "database_outcome=UNKNOWN automatic_retry=0 secrets=0",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "owner_authority_verified" else 30


if __name__ == "__main__":
    raise SystemExit(main())
