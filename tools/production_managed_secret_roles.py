#!/usr/bin/env python3
"""Enable the five first-launch runtime logins in one bounded transaction.

The privileged DSN and generated passwords are accepted only as an in-memory
argument or stdin JSON.  Output and errors are fixed and Secret-free.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

try:
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - deployment dependency
    psycopg = None  # type: ignore[assignment]
    sql = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]


TASK_ID = "PROD-FIRST-LAUNCH-MANAGED-SECRETS-001"
MIGRATION_OWNER_ROLE = "noteai_admin"
TARGET_LOGIN_ROLES = (
    "noteai_admin_runtime",
    "noteai_ai_worker",
    "noteai_payment",
    "noteai_xhs_tracking",
    "noteai_xhs_trends",
)
INERT_ROLE = "noteai_ai_dispatcher"
NEW_RUNTIME_ROLES = (
    "noteai_admin_runtime",
    "noteai_ai_dispatcher",
    "noteai_ai_worker",
    "noteai_payment",
    "noteai_xhs_tracking",
    "noteai_xhs_trends",
)
ALL_RUNTIME_ROLES = (
    "noteai_app",
    *NEW_RUNTIME_ROLES,
    "noteai_xhs",
)
EXPECTED_MIGRATIONS = (
    ("0001_initial.sql", "8ea5d32bc5c1a3e84452d93722324b9a9b4bb2e156c69b4a9656efa13ed51718"),
    ("0002_shared_runtime_state.sql", "d3a939479990cfe080fce71ebd122e19e633874bd2cd6883b5b03507eadefcb7"),
    ("0003_market_timing.sql", "772636cab88c2abf169a5b1a3fd5419ba1e3b12bbae92e211e296e89b1850192"),
    ("0004_xhs_freshness.sql", "1c817056eea3df9e0e1dd6ba6aceaf0c9a172b3cbba92ba3aeb621adb857a2a1"),
    ("0005_idempotency_requests.sql", "3a02a45bf0211580c5db97fc80ab9fb8eedab94a9cf981c59f3de231789981e6"),
    ("0006_model_usage_records.sql", "392eb82adca68493566f6469ce6ce4f1fba0cfc9ab76757deb4e1404c45cb735"),
    ("0007_ai_operations.sql", "477d4ea776d701c4b359b36eb254c68263131f74dedeb766ff46081bff619037"),
    ("0008_ai_operation_admissions.sql", "3bdd896ce06f7a5ae8deeba01145d9556775c45a71cd83576240d24a01bc05fe"),
    ("0009_account_security_compliance.sql", "1cfa46144b9a4d424215dd861a9817ec3a4612e7e62c1f2df5fec6f2e728f750"),
    ("0010_tracking_execution_contract.sql", "8ab5bbddad28ea60afad48bc27d71b105c5313d0229e263d06b65db4f38a3459"),
    ("0011_trends_execution_contract.sql", "abd55623a8903d6a6c01bed5fe4336b07be182abde2b86fa4b9cc5e7cb4b9802"),
    ("0012_durable_ai_execution_contract.sql", "df72dedfb292700104fc394b5b326f33e4339cbf195f704278c56e08e44bec83"),
    ("0013_private_storage_recovery_contract.sql", "1268cdb9696965f02d5be88882b3dc8a2f9f7b589a2b0da5193d1bb8408ccb76"),
    ("0014_payment_execution_contract.sql", "ed788fdf33e256713767101e85005e95a712a7e5c5aae0ec258c5f14091cb0ad"),
    ("0015_admin_runtime_contract.sql", "3ee9b85c9c154117d6e81ee83283160cede9bd182450b0de193f94a431b7d66c"),
    ("0016_admin_runtime_role_collision.sql", "5cdd8dc0bb6eefd4fee086458e964495d7163bf123026c4511c4dd7ccf93fde6"),
)
PASSWORD_PATTERN = re.compile(r"[A-Za-z0-9_-]{48,128}")
APPLY_STAGES = frozenset(
    {
        "transaction_begin",
        "session_controls",
        "owner_activation",
        "advisory_lock",
        "precondition",
        "credential_apply",
        "postcondition",
        "transaction_commit",
        "result_build",
    }
)


class ManagedSecretRoleError(RuntimeError):
    """A fixed, Secret-free role operation failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def validate_passwords(passwords: Any) -> dict[str, str]:
    if not isinstance(passwords, dict) or set(passwords) != set(
        TARGET_LOGIN_ROLES
    ):
        raise ManagedSecretRoleError("password_set")
    normalized: dict[str, str] = {}
    for role in TARGET_LOGIN_ROLES:
        value = passwords.get(role)
        if not isinstance(value, str) or not PASSWORD_PATTERN.fullmatch(value):
            raise ManagedSecretRoleError("password_shape")
        normalized[role] = value
    if len(set(normalized.values())) != len(normalized):
        raise ManagedSecretRoleError("password_reuse")
    return normalized


def _fetch_scalar(conn: Any, query: str, params: Any = None) -> Any:
    row = conn.execute(query, params).fetchone()
    if row is None:
        raise ManagedSecretRoleError("query_result")
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


def _activate_owner(conn: Any) -> None:
    identity = conn.execute(
        "SELECT session_user AS session_name,current_user AS current_name"
    ).fetchone()
    if (
        identity is None
        or str(identity["session_name"]) in ALL_RUNTIME_ROLES
    ):
        raise ManagedSecretRoleError("executor_identity")
    if str(identity["current_name"]) != MIGRATION_OWNER_ROLE:
        conn.execute(f"SET LOCAL ROLE {MIGRATION_OWNER_ROLE}")
    if not bool(
        _fetch_scalar(
            conn,
            "SELECT current_user=%s AND current_role=%s "
            "AND session_user::text <> ALL(%s::text[])",
            (
                MIGRATION_OWNER_ROLE,
                MIGRATION_OWNER_ROLE,
                list(ALL_RUNTIME_ROLES),
            ),
        )
    ):
        raise ManagedSecretRoleError("owner_activation")


def _validate_ledger(conn: Any) -> None:
    rows = conn.execute(
        "SELECT version,sha256 FROM schema_migrations ORDER BY version"
    ).fetchall()
    observed = tuple(
        (str(row["version"]), str(row["sha256"])) for row in rows
    )
    if observed != EXPECTED_MIGRATIONS:
        raise ManagedSecretRoleError("migration_ledger")


def _validate_memberships(conn: Any) -> None:
    rows = conn.execute(
        "SELECT granted.rolname AS granted_name,"
        "member.rolname AS member_name,membership.admin_option,"
        "(to_jsonb(membership)->>'inherit_option')::boolean "
        "AS inherit_option,"
        "(to_jsonb(membership)->>'set_option')::boolean AS set_option "
        "FROM pg_auth_members membership "
        "JOIN pg_roles granted ON granted.oid=membership.roleid "
        "JOIN pg_roles member ON member.oid=membership.member "
        "WHERE granted.rolname = ANY(%s) "
        "OR member.rolname = ANY(%s) "
        "ORDER BY granted.rolname,member.rolname",
        (list(ALL_RUNTIME_ROLES), list(ALL_RUNTIME_ROLES)),
    ).fetchall()
    expected = {("noteai_xhs", MIGRATION_OWNER_ROLE)}
    expected.update(
        (role, MIGRATION_OWNER_ROLE) for role in NEW_RUNTIME_ROLES
    )
    observed = {
        (str(row["granted_name"]), str(row["member_name"])) for row in rows
    }
    if (
        len(rows) != len(expected)
        or observed != expected
        or any(
            not bool(row["admin_option"])
            or row["inherit_option"] is not False
            or row["set_option"] is not False
            for row in rows
        )
    ):
        raise ManagedSecretRoleError("role_membership")


def validate_contract(
    conn: Any,
    *,
    expected_login_roles: frozenset[str],
) -> dict[str, int]:
    _validate_ledger(conn)
    rows = conn.execute(
        "SELECT rolname,rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,"
        "rolinherit,rolreplication,rolbypassrls "
        "FROM pg_roles WHERE rolname = ANY(%s) ORDER BY rolname",
        (list(NEW_RUNTIME_ROLES),),
    ).fetchall()
    if tuple(str(row["rolname"]) for row in rows) != tuple(
        sorted(NEW_RUNTIME_ROLES)
    ):
        raise ManagedSecretRoleError("role_inventory")
    observed_logins: set[str] = set()
    for row in rows:
        role = str(row["rolname"])
        if bool(row["rolcanlogin"]):
            observed_logins.add(role)
        if any(
            bool(row[key])
            for key in (
                "rolsuper",
                "rolcreatedb",
                "rolcreaterole",
                "rolinherit",
                "rolreplication",
                "rolbypassrls",
            )
        ):
            raise ManagedSecretRoleError("role_attributes")
    if observed_logins != set(expected_login_roles):
        raise ManagedSecretRoleError("role_login_state")
    _validate_memberships(conn)
    ownership_count = int(
        _fetch_scalar(
            conn,
            "SELECT "
            "(SELECT COUNT(*) FROM pg_class object "
            "JOIN pg_roles role ON role.oid=object.relowner "
            "WHERE role.rolname = ANY(%s)) + "
            "(SELECT COUNT(*) FROM pg_namespace object "
            "JOIN pg_roles role ON role.oid=object.nspowner "
            "WHERE role.rolname = ANY(%s)) + "
            "(SELECT COUNT(*) FROM pg_proc object "
            "JOIN pg_roles role ON role.oid=object.proowner "
            "WHERE role.rolname = ANY(%s))",
            (
                list(NEW_RUNTIME_ROLES),
                list(NEW_RUNTIME_ROLES),
                list(NEW_RUNTIME_ROLES),
            ),
        )
    )
    if ownership_count:
        raise ManagedSecretRoleError("role_ownership")
    return {
        "migration_count": len(EXPECTED_MIGRATIONS),
        "new_runtime_role_count": len(NEW_RUNTIME_ROLES),
        "login_role_count": len(expected_login_roles),
        "inert_role_count": int(INERT_ROLE not in expected_login_roles),
        "management_membership_count": len(NEW_RUNTIME_ROLES),
        "unexpected_membership_count": 0,
        "unexpected_elevation_count": 0,
        "role_owned_object_count": 0,
    }


def apply_contract(conn: Any, passwords: Any) -> dict[str, Any]:
    normalized = validate_passwords(passwords)
    stage = {"name": "transaction_begin"}
    try:
        with conn.transaction():
            stage["name"] = "session_controls"
            conn.execute("SET LOCAL statement_timeout='30s'")
            conn.execute("SET LOCAL lock_timeout='5s'")
            conn.execute("SET LOCAL idle_in_transaction_session_timeout='60s'")
            stage["name"] = "owner_activation"
            _activate_owner(conn)
            stage["name"] = "advisory_lock"
            conn.execute(
                "SELECT pg_advisory_xact_lock("
                "hashtext('noteai_managed_secrets_v1'))"
            )
            stage["name"] = "precondition"
            validate_contract(conn, expected_login_roles=frozenset())
            stage["name"] = "credential_apply"
            if sql is None:  # pragma: no cover
                raise ManagedSecretRoleError("psycopg_unavailable")
            for role in TARGET_LOGIN_ROLES:
                conn.execute(
                    sql.SQL(
                        "ALTER ROLE {} LOGIN PASSWORD {} VALID UNTIL 'infinity'"
                    ).format(
                        sql.Identifier(role),
                        sql.Literal(normalized[role]),
                    )
                )
            stage["name"] = "postcondition"
            verification = validate_contract(
                conn,
                expected_login_roles=frozenset(TARGET_LOGIN_ROLES),
            )
            stage["name"] = "transaction_commit"
        stage["name"] = "result_build"
    except ManagedSecretRoleError:
        raise
    except BaseException as exc:
        stage_name = stage["name"]
        if stage_name not in APPLY_STAGES:
            stage_name = "result_build"
        raise ManagedSecretRoleError(f"apply_{stage_name}_failed") from exc
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "verified",
        "transaction_committed": True,
        "role_attribute_writes": len(TARGET_LOGIN_ROLES),
        "password_writes": len(TARGET_LOGIN_ROLES),
        "membership_writes": 0,
        "acl_writes": 0,
        "schema_writes": 0,
        "business_row_writes": 0,
        "dispatcher_login_enabled": 0,
        "verification": verification,
        "secret_values_emitted": 0,
        "service_changes": 0,
        "public_traffic_requests": 0,
    }


def verify_contract(conn: Any) -> dict[str, Any]:
    with conn.transaction():
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL statement_timeout='30s'")
        conn.execute("SET LOCAL lock_timeout='5s'")
        verification = validate_contract(
            conn,
            expected_login_roles=frozenset(TARGET_LOGIN_ROLES),
        )
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "verified",
        "read_only": True,
        "verification": verification,
        "secret_values_emitted": 0,
        "service_changes": 0,
        "public_traffic_requests": 0,
    }


def _connect(database_url: str) -> Any:
    if psycopg is None:
        raise ManagedSecretRoleError("psycopg_unavailable")
    if not isinstance(database_url, str) or not database_url.strip():
        raise ManagedSecretRoleError("database_url_missing")
    return psycopg.connect(
        database_url,
        row_factory=dict_row,
        connect_timeout=10,
        application_name="noteai_managed_secrets_v1",
    )


def _protected_payload() -> dict[str, Any]:
    try:
        payload = json.load(sys.stdin)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ManagedSecretRoleError("protected_payload_parse") from exc
    if not isinstance(payload, dict):
        raise ManagedSecretRoleError("protected_payload_shape")
    return payload


def main(
    argv: list[str] | None = None,
    *,
    protected_payload: dict[str, Any] | None = None,
) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--confirm")
    args = parser.parse_args(argv)
    if args.apply and args.confirm != TASK_ID:
        print(
            "production_managed_secret_roles=FAIL code=confirmation_missing",
            file=sys.stderr,
        )
        return 2
    connected = False
    try:
        payload = (
            protected_payload
            if protected_payload is not None
            else _protected_payload()
        )
        expected_keys = {"database_url", "passwords"} if args.apply else {
            "database_url"
        }
        if set(payload) != expected_keys:
            raise ManagedSecretRoleError("protected_payload_shape")
        if args.apply:
            validate_passwords(payload["passwords"])
        conn = _connect(payload["database_url"])
        connected = True
        try:
            result = (
                apply_contract(conn, payload["passwords"])
                if args.apply
                else verify_contract(conn)
            )
        finally:
            conn.close()
    except ManagedSecretRoleError as exc:
        print(
            f"production_managed_secret_roles=FAIL code={exc.code}",
            file=sys.stderr,
        )
        return 1
    except BaseException:
        code = "execution_failed" if connected else "database_connection_failed"
        print(
            f"production_managed_secret_roles=FAIL code={code}",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
