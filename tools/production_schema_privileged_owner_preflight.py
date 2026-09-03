#!/usr/bin/env python3
"""Forced-readonly owner preflight for a short-term RDS privileged account.

This is a separately named successor to owner-authority preflight 004.  It
uses one protected connection, one repeatable-read read-only transaction,
three fixed aggregate queries, one fixed ``SET LOCAL ROLE`` command and a
terminal ``ROLLBACK``.  It never returns role names, connection details,
object names or business-row values.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, unquote, urlsplit, urlunsplit

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - deployment dependency
    psycopg = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]

try:
    from tools import production_schema_owner_authority_preflight as base
except ModuleNotFoundError:
    import production_schema_owner_authority_preflight as base  # type: ignore[no-redef]


TASK_ID = (
    "PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-PRIVILEGED-OWNER-PREFLIGHT-005"
)
AUDIT_ID = "PROD-SCHEMA-PRIVILEGED-OWNER-READONLY-001"
RUN_ID = "PROD-SCHEMA-PRIVILEGED-OWNER-READONLY-RUN-001"
APPLICATION_NAME = "noteai_schema_privileged_owner_preflight_v2"
TASK_ACCOUNT_NAME = "noteai_schema_task_owner_pf_005"
MANAGED_PRIVILEGED_ROLE = "pg_rds_superuser"
MIGRATION_OWNER_ROLE = base.MIGRATION_OWNER_ROLE
RUNTIME_ROLES = base.RUNTIME_ROLES
NEW_RUNTIME_ROLES = base.NEW_RUNTIME_ROLES
LEGACY_LEDGER_NAMES = base.LEGACY_LEDGER_NAMES
LEGACY_TABLES = base.LEGACY_TABLES
LEGACY_SEQUENCES = base.LEGACY_SEQUENCES
STAGE_ORDER = base.STAGE_ORDER
_SQLSTATE = re.compile(r"^[0-9A-Z]{5}$")
_FORBIDDEN_QUERY_KEYS = frozenset({
    "application_name",
    "dbname",
    "host",
    "hostaddr",
    "options",
    "passfile",
    "password",
    "port",
    "service",
    "servicefile",
    "sslpassword",
    "user",
})


SESSION_SQL = """
WITH executor AS (
    SELECT oid, rolsuper, rolcanlogin
    FROM pg_roles
    WHERE rolname = session_user
),
managed_privileged_role AS (
    SELECT oid
    FROM pg_roles
    WHERE rolname = %s
)
SELECT
    current_setting('default_transaction_read_only') = 'on' AS default_ro,
    current_setting('transaction_read_only') = 'on' AS transaction_ro,
    session_user = current_user
        AND current_user = current_role AS identity_unchanged,
    session_user::text <> ALL(%s::text[]) AS executor_not_runtime,
    session_user = %s AS executor_is_expected_task_account,
    session_user = %s AS executor_is_owner,
    COALESCE((SELECT NOT rolsuper FROM executor), FALSE)
        AS executor_non_superuser,
    COALESCE((SELECT rolcanlogin FROM executor), FALSE)
        AS executor_can_login,
    COALESCE((
        SELECT pg_has_role(
            session_user,
            managed_privileged_role.oid,
            'MEMBER'
        )
        FROM managed_privileged_role
    ), FALSE) AS executor_rds_privileged,
    pg_has_role(session_user, %s, 'SET') AS owner_activation_capable,
    COALESCE((
        SELECT pg_has_role(
            managed_privileged_role.oid,
            %s,
            'SET'
        )
        FROM managed_privileged_role
    ), FALSE) AS managed_role_owner_activation_capable,
    (
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
    )::integer AS transient_executor_dependency_count,
    (
        SELECT COUNT(*)::integer
        FROM pg_shdepend dependency
        WHERE dependency.refclassid='pg_authid'::regclass
          AND dependency.refobjid=(SELECT oid FROM executor)
          AND dependency.deptype IN ('a', 'o')
    ) AS executor_shared_dependency_count,
    (
        SELECT COUNT(*)::integer
        FROM pg_auth_members membership
        JOIN pg_roles granted ON granted.oid=membership.roleid
        JOIN pg_roles member ON member.oid=membership.member
        WHERE (
            membership.member=(SELECT oid FROM executor)
            AND granted.rolname = ANY(%s::text[])
        ) OR (
            membership.roleid=(SELECT oid FROM executor)
            AND member.rolname = ANY(%s::text[])
        )
    ) AS unexpected_runtime_membership_count,
    (
        SELECT COUNT(*)::integer
        FROM pg_auth_members membership
        WHERE membership.member=(SELECT oid FROM executor)
          AND membership.roleid=(
              SELECT oid FROM managed_privileged_role
          )
    ) AS direct_managed_privileged_membership_count,
    (
        SELECT COUNT(*)::integer
        FROM pg_auth_members membership
        WHERE membership.member=(SELECT oid FROM executor)
          AND membership.roleid<>(
              SELECT oid FROM managed_privileged_role
          )
    ) AS unexpected_direct_membership_count,
    (
        SELECT COUNT(*)::integer
        FROM pg_auth_members membership
        JOIN pg_roles granted ON granted.oid=membership.roleid
        WHERE membership.member=(SELECT oid FROM executor)
          AND granted.rolname=%s
    ) AS direct_owner_membership_count,
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


def _source_registry() -> dict[str, str]:
    registry = base._source_registry()
    registry["base_auditor"] = registry.pop("auditor")
    registry["auditor"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return registry


def _sqlstate(exc: BaseException) -> str:
    value = str(getattr(exc, "sqlstate", "") or "").upper()
    return value if _SQLSTATE.fullmatch(value) else "XXXXX"


def _parse_database_uri(value: str) -> Any:
    decoded_value = unquote(value)
    if (
        not value
        or len(value) > 2048
        or any(character in value for character in ("\x00", "\r", "\n"))
        or any(
            character in decoded_value
            for character in ("\x00", "\r", "\n")
        )
        or any(character.isspace() for character in value)
    ):
        raise base.OwnerAuthorityPreflightError(
            "protected_input_invalid",
            stage="protected_input",
            incident_class="PRE_CONNECT",
        )
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
        query = parse_qsl(
            parsed.query,
            keep_blank_values=True,
            strict_parsing=True,
        )
    except (TypeError, ValueError) as exc:
        raise base.OwnerAuthorityPreflightError(
            "protected_input_invalid",
            stage="protected_input",
            incident_class="PRE_CONNECT",
        ) from exc
    query_keys = [key.lower() for key, _value in query]
    query_has_secret = any(
        key in _FORBIDDEN_QUERY_KEYS
        or "password" in key
        or "secret" in key
        or "token" in key
        for key in query_keys
    )
    query_has_control = any(
        any(character in item for character in ("\x00", "\r", "\n"))
        for pair in query
        for item in pair
    )
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or not hostname
        or not parsed.path
        or parsed.fragment
        or "," in parsed.netloc
        or "," in hostname
        or query_has_secret
        or query_has_control
    ):
        raise base.OwnerAuthorityPreflightError(
            "protected_input_invalid",
            stage="protected_input",
            incident_class="PRE_CONNECT",
        )
    rendered_host = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None:
        rendered_host = f"{rendered_host}:{port}"
    return parsed, rendered_host


def sanitize_admin_database_topology(admin_database_url: str) -> str:
    """Strip all Admin userinfo before the audit container boundary."""
    parsed, rendered_host = _parse_database_uri(admin_database_url)
    if (
        parsed.username is None
        or parsed.password is None
        or parsed.netloc.count("@") != 1
    ):
        raise base.OwnerAuthorityPreflightError(
            "protected_input_invalid",
            stage="protected_input",
            incident_class="PRE_CONNECT",
        )
    return urlunsplit((
        parsed.scheme,
        rendered_host,
        parsed.path,
        parsed.query,
        "",
    ))


def sanitize_admin_topology_from_protected_input(payload: str) -> int:
    """Emit only sanitized connection topology for the root host pipeline."""
    try:
        topology = sanitize_admin_database_topology(payload)
    except base.OwnerAuthorityPreflightError:
        print(
            "production_schema_privileged_owner_preflight=FAIL "
            "stage=topology_sanitization sqlstate=NONE0 "
            "incident_class=PRE_CONNECT database_connected=0 "
            "database_outcome=NOT_CONNECTED automatic_retry=0 secrets=0",
            file=sys.stderr,
        )
        return 2
    try:
        sys.stdout.write(topology)
        return 0
    finally:
        del topology


def build_task_database_url(database_topology: str, password: str) -> str:
    """Add only the fixed task account userinfo to sanitized topology."""
    if (
        not password
        or len(password) > 256
        or any(character in password for character in ("\x00", "\r", "\n"))
    ):
        raise base.OwnerAuthorityPreflightError(
            "protected_input_invalid",
            stage="protected_input",
            incident_class="PRE_CONNECT",
        )
    parsed, rendered_host = _parse_database_uri(database_topology)
    if (
        parsed.username is not None
        or parsed.password is not None
        or "@" in parsed.netloc
    ):
        raise base.OwnerAuthorityPreflightError(
            "protected_input_invalid",
            stage="protected_input",
            incident_class="PRE_CONNECT",
        )
    task_userinfo = (
        f"{quote(TASK_ACCOUNT_NAME, safe='')}:"
        f"{quote(password, safe='')}@"
    )
    return urlunsplit((
        parsed.scheme,
        f"{task_userinfo}{rendered_host}",
        parsed.path,
        parsed.query,
        "",
    ))


def main_from_protected_input(payload: bytes) -> int:
    """Consume the Admin topology and task password from anonymous stdin."""
    try:
        if payload.count(b"\x00") != 1:
            raise ValueError
        admin_bytes, password_bytes = payload.split(b"\x00", 1)
        database_topology = admin_bytes.decode("utf-8", errors="strict")
        password = password_bytes.decode("utf-8", errors="strict")
        task_database_url = build_task_database_url(
            database_topology,
            password,
        )
    except (UnicodeError, ValueError, base.OwnerAuthorityPreflightError):
        print(
            "production_schema_privileged_owner_preflight=FAIL "
            "stage=protected_input sqlstate=NONE0 "
            "incident_class=PRE_CONNECT database_connected=0 "
            "database_outcome=NOT_CONNECTED automatic_retry=0 secrets=0",
            file=sys.stderr,
        )
        return 2
    finally:
        if "admin_bytes" in locals():
            del admin_bytes
        if "password_bytes" in locals():
            del password_bytes
        if "database_topology" in locals():
            del database_topology
        if "password" in locals():
            del password
    try:
        return main(database_url=task_database_url)
    finally:
        del task_database_url


def collect_privileged_owner_authority(conn: Any) -> dict[str, Any]:
    """Run the fixed managed-privileged owner audit and terminal rollback."""
    completed: list[str] = []
    transaction_declared_read_only = False
    rollback_confirmed = False
    active_error: base.OwnerAuthorityPreflightError | None = None
    try:
        try:
            conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
            transaction_declared_read_only = True
        except BaseException as exc:
            raise base.OwnerAuthorityPreflightError(
                "begin_failed",
                stage="session",
                sqlstate=_sqlstate(exc),
            ) from exc

        session = base._one(
            conn,
            stage="session",
            sql=SESSION_SQL,
            params=(
                MANAGED_PRIVILEGED_ROLE,
                list(RUNTIME_ROLES),
                TASK_ACCOUNT_NAME,
                MIGRATION_OWNER_ROLE,
                MIGRATION_OWNER_ROLE,
                MIGRATION_OWNER_ROLE,
                list(RUNTIME_ROLES),
                list(RUNTIME_ROLES),
                MIGRATION_OWNER_ROLE,
                MIGRATION_OWNER_ROLE,
            ),
        )
        completed.append("session")
        try:
            conn.execute(f"SET LOCAL ROLE {MIGRATION_OWNER_ROLE}")
        except BaseException as exc:
            raise base.OwnerAuthorityPreflightError(
                "owner_activation_failed",
                stage="migration_owner_activation",
                sqlstate=_sqlstate(exc),
            ) from exc
        completed.append("migration_owner_activation")
        owner_contract = base._one(
            conn,
            stage="owner_contract",
            sql=base.OWNER_CONTRACT_SQL,
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
        production_state = base._one(
            conn,
            stage="production_state",
            sql=base.PRODUCTION_STATE_SQL,
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
    except base.OwnerAuthorityPreflightError as exc:
        active_error = exc
    finally:
        if transaction_declared_read_only:
            try:
                conn.execute("ROLLBACK")
                rollback_confirmed = True
                completed.append("rollback")
            except BaseException as exc:
                raise base.OwnerAuthorityPreflightError(
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
        and bool(session["executor_is_expected_task_account"])
        and not bool(session["executor_is_owner"])
        and bool(session["executor_non_superuser"])
        and bool(session["executor_can_login"])
        and bool(session["executor_rds_privileged"])
        and bool(session["owner_activation_capable"])
        and bool(session["managed_role_owner_activation_capable"])
        and int(session["transient_executor_dependency_count"]) == 0
        and int(session["executor_shared_dependency_count"]) == 0
        and int(session["unexpected_runtime_membership_count"]) == 0
        and int(
            session["direct_managed_privileged_membership_count"]
        ) == 1
        and int(session["unexpected_direct_membership_count"]) == 0
        and int(session["direct_owner_membership_count"]) == 0
        and int(session["direct_owner_set_membership_count"]) == 0
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
        "predecessor_task_id": base.TASK_ID,
        "predecessor_disposition": "no_retry",
        "same_database_action_retry": False,
        "audit_id": AUDIT_ID,
        "run_id": RUN_ID,
        "status": (
            "privileged_owner_authority_verified"
            if verified
            else "state_changed"
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
        raise base.OwnerAuthorityPreflightError(
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
            raise base.OwnerAuthorityPreflightError(
                "database_url_missing",
                stage="connect",
                incident_class="PRE_CONNECT",
            )
        connection_attempted = True
        conn = _connect(database_url.strip())
        connected = True
        try:
            result = collect_privileged_owner_authority(conn)
        finally:
            conn.close()
    except base.OwnerAuthorityPreflightError as exc:
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
            "production_schema_privileged_owner_preflight=FAIL "
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
            "production_schema_privileged_owner_preflight=FAIL "
            "stage=unexpected sqlstate=XXXXX "
            "incident_class=CONNECTED_UNKNOWN "
            f"database_connected={int(connected)} "
            "database_outcome=UNKNOWN automatic_retry=0 secrets=0",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return (
        0
        if result["status"] == "privileged_owner_authority_verified"
        else 30
    )


if __name__ == "__main__":
    raise SystemExit(main())
