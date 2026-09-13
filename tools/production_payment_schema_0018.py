#!/usr/bin/env python3
"""Atomically apply or read-only verify the fixed PostgreSQL 0018 delta."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - deployment image owns psycopg
    psycopg = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_DIR = ROOT / "model" / "migrations" / "postgres"
MIGRATION_NAME = "0018_direct_payment_providers.sql"
MIGRATION_SHA256 = (
    "01064affc00e77811408b0a21b127d7d0890825ebb5d689adc4ec00e829d2c77"
)
DATABASE_URL_ENV = "NOTEAI_SCHEMA_DATABASE_URL"
CONFIRM_ENV = "NOTEAI_PAYMENT_SCHEMA_0018_APPLY_CONFIRM"
TASK_ID = "PROD-FIRST-LAUNCH-PAYMENT-SCHEMA-0018"
OWNER_ROLE = "noteai_admin"
RUNTIME_ROLE = "noteai_payment"
PROVIDERS_BEFORE = {"adapay"}
PROVIDERS_AFTER = {"adapay", "wechatpay_direct", "alipay_direct"}
PROVIDER_CONSTRAINTS = {
    "payment_orders": "payment_orders_provider_check",
    "payment_reconciliation_runs": "payment_reconciliation_runs_provider_check",
    "payment_settlement_summaries": "payment_settlement_summaries_provider_check",
}
TRIGGER_FUNCTIONS = {
    "noteai_payment_refund_identity_v1": (
        "noteai_payment_refund_identity_guard_v1"
    ),
    "noteai_payment_refund_insert_v1": (
        "noteai_payment_refund_insert_guard_v1"
    ),
}
EVENT_IDENTITY_FIELDS = (
    "id",
    "provider_event_id_hash",
    "event_type",
    "payload_sha256",
    "signature_sha256",
    "app_id_hash",
    "prod_mode",
    "provider_created_at",
    "received_at",
)
EXPECTED_MIGRATION_NAMES = tuple(
    f"{number:04d}_{suffix}.sql"
    for number, suffix in enumerate(
        (
            "initial",
            "shared_runtime_state",
            "market_timing",
            "xhs_freshness",
            "idempotency_requests",
            "model_usage_records",
            "ai_operations",
            "ai_operation_admissions",
            "account_security_compliance",
            "tracking_execution_contract",
            "trends_execution_contract",
            "durable_ai_execution_contract",
            "private_storage_recovery_contract",
            "payment_execution_contract",
            "admin_runtime_contract",
            "admin_runtime_role_collision",
            "durable_ai_postgres_wakeup",
            "direct_payment_providers",
        ),
        start=1,
    )
)
PRIOR_MIGRATION_NAMES = EXPECTED_MIGRATION_NAMES[:-1]


class PaymentSchemaError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def source_contract() -> dict[str, Any]:
    paths = tuple(sorted(MIGRATION_DIR.glob("*.sql")))
    expected_paths = paths[: len(EXPECTED_MIGRATION_NAMES)]
    if tuple(path.name for path in expected_paths) != EXPECTED_MIGRATION_NAMES:
        raise PaymentSchemaError("migration_set")
    payloads = {path.name: path.read_bytes() for path in expected_paths}
    hashes = {
        name: hashlib.sha256(payload).hexdigest()
        for name, payload in payloads.items()
    }
    if hashes[MIGRATION_NAME] != MIGRATION_SHA256:
        raise PaymentSchemaError("migration_source_hash")
    return {
        "migration_payload": payloads[MIGRATION_NAME],
        "migration_sha256": MIGRATION_SHA256,
        "migration_hashes": hashes,
        "successor_hashes": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths[len(EXPECTED_MIGRATION_NAMES):]
        },
    }


def _connect() -> Any:
    database_url = os.environ.get(DATABASE_URL_ENV, "").strip()
    if not database_url:
        raise PaymentSchemaError("database_url_missing")
    return connect_database_url(database_url)


def connect_database_url(database_url: str) -> Any:
    """Connect from one protected in-memory value without logging it."""
    if psycopg is None:
        raise PaymentSchemaError("psycopg_unavailable")
    if not isinstance(database_url, str) or not database_url:
        raise PaymentSchemaError("database_url_missing")
    try:
        return psycopg.connect(
            database_url,
            row_factory=dict_row,
            connect_timeout=10,
            options="-c timezone=UTC",
        )
    except Exception:
        raise PaymentSchemaError("database_connect") from None


def _activate_owner(
    conn: Any,
    *,
    expected_session_role: str | None = None,
) -> None:
    conn.execute(f"SET LOCAL ROLE {OWNER_ROLE}")
    identity = conn.execute(
        "SELECT session_user AS session_role,current_user AS current_role"
    ).fetchone()
    if (
        identity is None
        or identity["current_role"] != OWNER_ROLE
        or identity["session_role"] == RUNTIME_ROLE
        or (
            expected_session_role is not None
            and identity["session_role"] != expected_session_role
        )
    ):
        raise PaymentSchemaError("owner_activation")


def _ledger_rows(conn: Any) -> list[dict[str, Any]]:
    return list(
        conn.execute(
            "SELECT version,sha256 FROM schema_migrations ORDER BY version"
        ).fetchall()
    )


def _verify_ledger(
    rows: list[dict[str, Any]],
    names: tuple[str, ...],
    hashes: dict[str, str],
    *,
    successor_hashes: dict[str, str] | None = None,
) -> None:
    versions = tuple(str(row["version"]) for row in rows)
    if successor_hashes is not None:
        extras = versions[len(names):]
        if (versions[:len(names)] != names or len(set(versions)) != len(versions)
                or tuple(sorted(extras)) != extras
                or any(name not in successor_hashes for name in extras)):
            raise PaymentSchemaError("ledger_versions")
        hashes = {**hashes, **successor_hashes}
    elif versions != names:
        raise PaymentSchemaError("ledger_versions")
    if any(
        str(row["sha256"] or "") != hashes[str(row["version"])]
        for row in rows
    ):
        raise PaymentSchemaError("ledger_hash")


def _runtime_role_snapshot(conn: Any) -> str:
    row = conn.execute(
        """
        WITH role_state AS (
            SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,
                   rolcanlogin,rolreplication,rolbypassrls
              FROM pg_roles WHERE rolname=%s
        ), memberships AS (
            SELECT granted.rolname AS granted_name,
                   member.rolname AS member_name,m.admin_option,
                   to_jsonb(m)->>'inherit_option' AS inherit_option,
                   to_jsonb(m)->>'set_option' AS set_option
              FROM pg_auth_members m
              JOIN pg_roles granted ON granted.oid=m.roleid
              JOIN pg_roles member ON member.oid=m.member
             WHERE granted.rolname=%s OR member.rolname=%s
        ), ownership AS (
            SELECT kind,COUNT(*)::integer AS count FROM (
                SELECT 'relation' AS kind FROM pg_class o
                  JOIN pg_roles owner ON owner.oid=o.relowner
                 WHERE owner.rolname=%s
                UNION ALL
                SELECT 'schema' FROM pg_namespace o
                  JOIN pg_roles owner ON owner.oid=o.nspowner
                 WHERE owner.rolname=%s
                UNION ALL
                SELECT 'function' FROM pg_proc o
                  JOIN pg_roles owner ON owner.oid=o.proowner
                 WHERE owner.rolname=%s
            ) owned GROUP BY kind
        )
        SELECT (SELECT COUNT(*) FROM role_state)::integer AS role_count,
               jsonb_build_object(
                 'role',COALESCE((SELECT to_jsonb(r) FROM role_state r),
                                 '{}'::jsonb),
                 'memberships',COALESCE((SELECT jsonb_agg(to_jsonb(m)
                    ORDER BY granted_name,member_name) FROM memberships m),
                    '[]'::jsonb),
                 'ownership',COALESCE((SELECT jsonb_agg(to_jsonb(o)
                    ORDER BY kind) FROM ownership o),'[]'::jsonb)
               )::text AS snapshot
        """,
        (RUNTIME_ROLE,) * 6,
    ).fetchone()
    if row is None or int(row["role_count"]) != 1:
        raise PaymentSchemaError("runtime_role_missing")
    return str(row["snapshot"])


def _column_privilege_snapshot(conn: Any) -> set[tuple[str, str, str, str]]:
    rows = conn.execute(
        "SELECT table_name,column_name,privilege_type,is_grantable "
        "FROM information_schema.column_privileges "
        "WHERE table_schema='public' AND grantee=%s "
        "ORDER BY table_name,column_name,privilege_type",
        (RUNTIME_ROLE,),
    ).fetchall()
    return {
        (
            str(row["table_name"]),
            str(row["column_name"]),
            str(row["privilege_type"]),
            str(row["is_grantable"]),
        )
        for row in rows
    }


def _provider_constraint_sets(conn: Any) -> dict[str, set[str]]:
    rows = conn.execute(
        "SELECT c.conname,pg_get_constraintdef(c.oid,true) AS definition "
        "FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid "
        "JOIN pg_namespace n ON n.oid=t.relnamespace "
        "WHERE n.nspname='public' AND c.conname = ANY(%s) "
        "ORDER BY c.conname",
        (list(PROVIDER_CONSTRAINTS.values()),),
    ).fetchall()
    observed: dict[str, set[str]] = {}
    constraint_to_table = {
        constraint: table
        for table, constraint in PROVIDER_CONSTRAINTS.items()
    }
    for row in rows:
        table = constraint_to_table.get(str(row["conname"]))
        if table is None or table in observed:
            raise PaymentSchemaError("provider_constraints")
        observed[table] = set(
            re.findall(r"'([a-z][a-z0-9_]*)'", str(row["definition"]))
        )
    if set(observed) != set(PROVIDER_CONSTRAINTS):
        raise PaymentSchemaError("provider_constraints")
    return observed


def _provider_submitted_column(conn: Any) -> dict[str, Any] | None:
    return conn.execute(
        "SELECT data_type,is_nullable FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='payment_refunds' "
        "AND column_name='provider_submitted_at'"
    ).fetchone()


def _duplicate_delivery_column(conn: Any) -> dict[str, Any] | None:
    return conn.execute(
        "SELECT data_type,is_nullable,column_default "
        "FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='payment_events' "
        "AND column_name='duplicate_delivery_count'"
    ).fetchone()


def _normalized_expression(value: Any) -> str:
    return re.sub(r"[()\s]+", " ", str(value)).strip().lower()


def _exact_bounded_check(
    definition: Any,
    *,
    column: str,
    lower: int,
    upper: int,
    nullable: bool,
) -> bool:
    expression = _normalized_expression(definition)
    bounds = f"{column} >= {lower} and {column} <= {upper}"
    expected = f"check {column} is null or {bounds}" if nullable else f"check {bounds}"
    return expression == expected


def _event_guard_definition_exact(
    definition: Any,
    *,
    require_counter: bool = True,
) -> bool:
    normalized = re.sub(r"\s+", " ", str(definition)).strip().lower()
    if any(
        f"new.{field} <> old.{field}" not in normalized
        for field in EVENT_IDENTITY_FIELDS
    ):
        return False
    required = [
        "old.processing_state <> 'accepted'",
        "new.processing_state <> old.processing_state",
        "old.processing_state = 'accepted'",
        "new.processing_state not in ( "
        "'accepted','processed','ignored','needs_manual' )",
        "return new;",
    ]
    if require_counter:
        required.extend(
            (
                "new.duplicate_delivery_count < old.duplicate_delivery_count",
                "new.duplicate_delivery_count > "
                "old.duplicate_delivery_count + 1",
            )
        )
    return all(fragment in normalized for fragment in required)


def _event_trigger_row_exact(row: Any) -> bool:
    return bool(
        row is not None
        and str(row.get("tgname")) == "noteai_payment_event_identity_v1"
        and str(row.get("proname"))
        == "noteai_payment_event_identity_guard_v1"
        and str(row.get("tgenabled")) == "O"
        and int(row.get("tgtype", -1)) == 19
        and int(row.get("pronargs", -1)) == 0
        and str(row.get("return_type")) == "trigger"
    )


def _event_guard_function(conn: Any, *, require_counter: bool = True) -> str:
    rows = conn.execute(
        "SELECT pg_get_functiondef(p.oid) AS definition,p.prosecdef,"
        "p.provolatile,p.proconfig,p.pronargs,"
        "format_type(p.prorettype,NULL) AS return_type "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='public' "
        "AND p.proname='noteai_payment_event_identity_guard_v1'"
    ).fetchall()
    if (
        len(rows) != 1
        or (row := rows[0]) is None
        or bool(row["prosecdef"])
        or str(row["provolatile"]) != "v"
        or not row["proconfig"]
        or "search_path=pg_catalog, public" not in set(row["proconfig"])
        or int(row["pronargs"]) != 0
        or str(row["return_type"]) != "trigger"
    ):
        raise PaymentSchemaError("event_guard_function")
    definition = re.sub(r"\s+", " ", str(row["definition"])).lower()
    if not _event_guard_definition_exact(
        definition,
        require_counter=require_counter,
    ):
        raise PaymentSchemaError("event_guard_function")
    return definition


def _verify_event_trigger_binding(conn: Any) -> None:
    rows = conn.execute(
        "SELECT t.tgname,p.proname,t.tgenabled,t.tgtype,p.pronargs,"
        "format_type(p.prorettype,NULL) AS return_type FROM pg_trigger t "
        "JOIN pg_proc p ON p.oid=t.tgfoid "
        "WHERE t.tgrelid='public.payment_events'::regclass "
        "AND NOT t.tgisinternal "
        "AND t.tgname='noteai_payment_event_identity_v1'"
    ).fetchall()
    if len(rows) != 1 or not _event_trigger_row_exact(rows[0]):
        raise PaymentSchemaError("event_guard_trigger")


def _refund_guard_functions(conn: Any) -> dict[str, str]:
    names = sorted(set(TRIGGER_FUNCTIONS.values()))
    rows = conn.execute(
        "SELECT p.proname,pg_get_functiondef(p.oid) AS definition,"
        "p.prosecdef,p.provolatile,p.proconfig "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='public' AND p.proname = ANY(%s) "
        "ORDER BY p.proname",
        (names,),
    ).fetchall()
    if len(rows) != len(names):
        raise PaymentSchemaError("refund_guard_functions")
    definitions: dict[str, str] = {}
    for row in rows:
        if (
            bool(row["prosecdef"])
            or str(row["provolatile"]) != "v"
            or not row["proconfig"]
            or "search_path=pg_catalog, public" not in set(row["proconfig"])
        ):
            raise PaymentSchemaError("refund_guard_functions")
        definitions[str(row["proname"])] = re.sub(
            r"\s+", " ", str(row["definition"])
        ).lower()
    return definitions


def _verify_trigger_bindings(conn: Any) -> None:
    rows = conn.execute(
        "SELECT t.tgname,p.proname FROM pg_trigger t "
        "JOIN pg_proc p ON p.oid=t.tgfoid "
        "WHERE t.tgrelid='public.payment_refunds'::regclass "
        "AND NOT t.tgisinternal AND t.tgname = ANY(%s) "
        "ORDER BY t.tgname",
        (list(TRIGGER_FUNCTIONS),),
    ).fetchall()
    observed = {
        str(row["tgname"]): str(row["proname"])
        for row in rows
    }
    if observed != TRIGGER_FUNCTIONS:
        raise PaymentSchemaError("refund_guard_triggers")


def _verify_preconditions(conn: Any, contract: dict[str, Any]) -> dict[str, Any]:
    _verify_ledger(
        _ledger_rows(conn),
        PRIOR_MIGRATION_NAMES,
        contract["migration_hashes"],
    )
    if any(
        providers != PROVIDERS_BEFORE
        for providers in _provider_constraint_sets(conn).values()
    ):
        raise PaymentSchemaError("precondition_provider_constraints")
    if _provider_submitted_column(conn) is not None:
        raise PaymentSchemaError("precondition_refund_column")
    if _duplicate_delivery_column(conn) is not None:
        raise PaymentSchemaError("precondition_event_column")
    functions = _refund_guard_functions(conn)
    if any("provider_submitted_at" in definition for definition in functions.values()):
        raise PaymentSchemaError("precondition_refund_guards")
    _verify_trigger_bindings(conn)
    event_guard = _event_guard_function(conn, require_counter=False)
    if "duplicate_delivery_count" in event_guard:
        raise PaymentSchemaError("precondition_event_guard")
    _verify_event_trigger_binding(conn)
    privileges = _column_privilege_snapshot(conn)
    _runtime_role_snapshot(conn)
    return {
        "ledger_count": len(PRIOR_MIGRATION_NAMES),
        "ledger_last": PRIOR_MIGRATION_NAMES[-1],
        "provider_constraint_count": len(PROVIDER_CONSTRAINTS),
        "provider_submitted_at_column_count": 0,
        "duplicate_delivery_count_column_count": 0,
        "payment_column_privilege_count": len(privileges),
        "runtime_role_count": 1,
    }


def _verify_postconditions(conn: Any, contract: dict[str, Any], *, allow_successors: bool = False) -> dict[str, Any]:
    rows = _ledger_rows(conn)
    _verify_ledger(rows, EXPECTED_MIGRATION_NAMES, contract["migration_hashes"],
                   successor_hashes=contract.get("successor_hashes", {}) if allow_successors else None)
    if any(
        providers != PROVIDERS_AFTER
        for providers in _provider_constraint_sets(conn).values()
    ):
        raise PaymentSchemaError("provider_constraints")
    column = _provider_submitted_column(conn)
    if (
        column is None
        or str(column["data_type"]) != "bigint"
        or str(column["is_nullable"]) != "YES"
    ):
        raise PaymentSchemaError("refund_column")
    checks = conn.execute(
        "SELECT pg_get_constraintdef(c.oid,true) AS definition "
        "FROM pg_constraint c "
        "WHERE c.conrelid='public.payment_refunds'::regclass "
        "AND c.contype='c' AND pg_get_constraintdef(c.oid,true) "
        "LIKE '%provider_submitted_at%'"
    ).fetchall()
    if len(checks) != 1:
        raise PaymentSchemaError("refund_column_check")
    event_column = _duplicate_delivery_column(conn)
    if (
        event_column is None
        or str(event_column["data_type"]) != "bigint"
        or str(event_column["is_nullable"]) != "NO"
        or str(event_column["column_default"]) != "0"
    ):
        raise PaymentSchemaError("event_column")
    event_checks = conn.execute(
        "SELECT pg_get_constraintdef(c.oid,true) AS definition "
        "FROM pg_constraint c "
        "WHERE c.conrelid='public.payment_events'::regclass "
        "AND c.contype='c' AND pg_get_constraintdef(c.oid,true) "
        "LIKE '%duplicate_delivery_count%'"
    ).fetchall()
    if len(event_checks) != 1:
        raise PaymentSchemaError("event_column_check")
    if not _exact_bounded_check(
        event_checks[0]["definition"],
        column="duplicate_delivery_count",
        lower=0,
        upper=1000000,
        nullable=False,
    ):
        raise PaymentSchemaError("event_column_check")
    event_guard = _event_guard_function(conn)
    if not _event_guard_definition_exact(event_guard):
        raise PaymentSchemaError("event_guard_function")
    _verify_event_trigger_binding(conn)
    if not _exact_bounded_check(
        checks[0]["definition"],
        column="provider_submitted_at",
        lower=946684800,
        upper=4102444800,
        nullable=True,
    ):
        raise PaymentSchemaError("refund_column_check")
    functions = _refund_guard_functions(conn)
    identity = functions["noteai_payment_refund_identity_guard_v1"]
    insert = functions["noteai_payment_refund_insert_guard_v1"]
    if not all(
        fragment in identity
        for fragment in (
            "old.provider_submitted_at is not null",
            "new.provider_submitted_at",
            "provider = 'wechatpay_direct'",
        )
    ) or not all(
        fragment in insert
        for fragment in (
            "new.provider_submitted_at is not null",
            "provider = 'wechatpay_direct'",
        )
    ):
        raise PaymentSchemaError("refund_guard_functions")
    _verify_trigger_bindings(conn)
    privileges = _column_privilege_snapshot(conn)
    target = ("payment_refunds", "provider_submitted_at", "UPDATE", "NO")
    if target not in privileges:
        raise PaymentSchemaError("refund_column_privilege")
    event_target = (
        "payment_events",
        "duplicate_delivery_count",
        "UPDATE",
        "NO",
    )
    if event_target not in privileges:
        raise PaymentSchemaError("event_column_privilege")
    broad = conn.execute(
        "SELECT "
        "has_table_privilege(%s,'public.payment_refunds','UPDATE') "
        "AS refund_broad_update,"
        "has_table_privilege(%s,'public.payment_events','UPDATE') "
        "AS event_broad_update",
        (RUNTIME_ROLE, RUNTIME_ROLE),
    ).fetchone()
    if (
        broad is None
        or bool(broad["refund_broad_update"])
        or bool(broad["event_broad_update"])
    ):
        raise PaymentSchemaError("payment_broad_privilege")
    return {
        "ledger_count": len(rows),
        "ledger_last": str(rows[-1]["version"]),
        "migration_sha256": MIGRATION_SHA256,
        "provider_constraint_count": len(PROVIDER_CONSTRAINTS),
        "direct_provider_count": 2,
        "provider_submitted_at_column_count": 1,
        "duplicate_delivery_count_column_count": 1,
        "event_guard_function_count": 1,
        "event_guard_trigger_count": 1,
        "refund_guard_function_count": len(TRIGGER_FUNCTIONS),
        "refund_guard_trigger_count": len(TRIGGER_FUNCTIONS),
        "payment_column_privilege_count": len(privileges),
        "payment_broad_update_count": 0,
    }


def preflight_schema(
    conn: Any,
    contract: dict[str, Any],
    *,
    expected_session_role: str | None = None,
) -> dict[str, Any]:
    with conn.transaction():
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL statement_timeout='30s'")
        conn.execute("SET LOCAL lock_timeout='5s'")
        _activate_owner(conn, expected_session_role=expected_session_role)
        verification = _verify_preconditions(conn, contract)
    return {
        "status": "verified",
        "mode": "preflight",
        "read_only": True,
        "database_writes": 0,
        "provider_calls": 0,
        "verification": verification,
    }


def apply_schema(
    conn: Any,
    contract: dict[str, Any],
    *,
    expected_session_role: str | None = None,
) -> dict[str, Any]:
    target_privileges = {
        # SELECT and INSERT are inherited from existing table grants when the
        # column is added. UPDATE is the sole explicit 0018 grant.
        ("payment_refunds", "provider_submitted_at", "SELECT", "NO"),
        ("payment_refunds", "provider_submitted_at", "INSERT", "NO"),
        ("payment_refunds", "provider_submitted_at", "UPDATE", "NO"),
        ("payment_events", "duplicate_delivery_count", "SELECT", "NO"),
        ("payment_events", "duplicate_delivery_count", "INSERT", "NO"),
        ("payment_events", "duplicate_delivery_count", "UPDATE", "NO"),
    }
    with conn.transaction():
        conn.execute("SET LOCAL statement_timeout='60s'")
        conn.execute("SET LOCAL lock_timeout='5s'")
        conn.execute("SET LOCAL idle_in_transaction_session_timeout='90s'")
        _activate_owner(conn, expected_session_role=expected_session_role)
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext('noteai_schema_migrations'))"
        )
        _verify_preconditions(conn, contract)
        role_before = _runtime_role_snapshot(conn)
        privileges_before = _column_privilege_snapshot(conn)
        conn.execute(contract["migration_payload"].decode("utf-8"))
        inserted = conn.execute(
            "INSERT INTO schema_migrations(version,sha256) VALUES(%s,%s)",
            (MIGRATION_NAME, MIGRATION_SHA256),
        )
        if int(inserted.rowcount or 0) != 1:
            raise PaymentSchemaError("ledger_insert")
        verification = _verify_postconditions(conn, contract)
        if _runtime_role_snapshot(conn) != role_before:
            raise PaymentSchemaError("runtime_role_drift")
        if _column_privilege_snapshot(conn) != privileges_before | target_privileges:
            raise PaymentSchemaError("runtime_privilege_drift")
    return {
        "status": "verified",
        "mode": "apply",
        "transaction_committed": True,
        "applied_versions": [MIGRATION_NAME],
        "provider_calls": 0,
        "database_writes": {
            "migration_ledger_rows": 1,
            "business_row_updates": 0,
            "payment_rows_created": 0,
        },
        "runtime_roles_unchanged": True,
        "runtime_privilege_delta": [
            "payment_refunds.provider_submitted_at:INSERT",
            "payment_refunds.provider_submitted_at:SELECT",
            "payment_refunds.provider_submitted_at:UPDATE",
            "payment_events.duplicate_delivery_count:INSERT",
            "payment_events.duplicate_delivery_count:SELECT",
            "payment_events.duplicate_delivery_count:UPDATE",
        ],
        "verification": verification,
    }


def verify_schema(
    conn: Any,
    contract: dict[str, Any],
    *,
    expected_session_role: str | None = None,
) -> dict[str, Any]:
    with conn.transaction():
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL statement_timeout='30s'")
        conn.execute("SET LOCAL lock_timeout='5s'")
        _activate_owner(conn, expected_session_role=expected_session_role)
        verification = _verify_postconditions(conn, contract, allow_successors=True)
    return {
        "status": "verified",
        "mode": "verify",
        "read_only": True,
        "database_writes": 0,
        "provider_calls": 0,
        "verification": verification,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--preflight", action="store_true")
    action.add_argument("--apply", action="store_true")
    action.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    if args.apply and os.environ.get(CONFIRM_ENV) != TASK_ID:
        print(
            "production_payment_schema_0018=FAIL code=confirmation_missing",
            file=sys.stderr,
        )
        return 2
    conn = None
    try:
        contract = source_contract()
        conn = _connect()
        if args.preflight:
            result = preflight_schema(conn, contract)
        elif args.apply:
            result = apply_schema(conn, contract)
        else:
            result = verify_schema(conn, contract)
    except PaymentSchemaError as exc:
        print(
            f"production_payment_schema_0018=FAIL code={exc.code}",
            file=sys.stderr,
        )
        return 1
    except Exception:
        print(
            "production_payment_schema_0018=FAIL code=unexpected",
            file=sys.stderr,
        )
        return 1
    finally:
        if conn is not None:
            conn.close()
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
