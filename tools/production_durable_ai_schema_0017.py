#!/usr/bin/env python3
"""Atomically apply or read-only verify the fixed PostgreSQL 0017 delta."""

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
MIGRATION_NAME = "0017_durable_ai_postgres_wakeup.sql"
MIGRATION_SHA256 = (
    "a73cbefd853cefe7b56c42bed2c5a7f0ba1626e57755c6f9464629b49c42cbbe"
)
DATABASE_URL_ENV = "NOTEAI_SCHEMA_DATABASE_URL"
CONFIRM_ENV = "NOTEAI_DURABLE_AI_SCHEMA_0017_APPLY_CONFIRM"
TASK_ID = "PROD-FIRST-LAUNCH-DURABLE-AI-SCHEMA-0017"
OWNER_ROLE = "noteai_admin"
RUNTIME_ROLES = ("noteai_ai_dispatcher", "noteai_ai_worker")
INDEX_NAME = "idx_ai_operation_outbox_delivered_claim"
POLICY_NAME = "noteai_ai_outbox_worker_delivered_v1"
EXPECTED_MIGRATION_NAMES = tuple(
    f"{number:04d}_{suffix}.sql"
    for number, suffix in enumerate((
        "initial", "shared_runtime_state", "market_timing", "xhs_freshness",
        "idempotency_requests", "model_usage_records", "ai_operations",
        "ai_operation_admissions", "account_security_compliance",
        "tracking_execution_contract", "trends_execution_contract",
        "durable_ai_execution_contract", "private_storage_recovery_contract",
        "payment_execution_contract", "admin_runtime_contract",
        "admin_runtime_role_collision", "durable_ai_postgres_wakeup",
    ), start=1)
)
PRIOR_MIGRATION_NAMES = EXPECTED_MIGRATION_NAMES[:-1]
WORKER_SELECT_BEFORE = {
    "ai_operation_outbox": set(),
    "subscriptions": set(),
    "credits": {"user_id", "balance"},
    "usage_records": set(),
}
WORKER_SELECT_AFTER = {
    "ai_operation_outbox": {"id", "operation_id", "state", "delivered_at"},
    "subscriptions": {"id", "user_id", "period_start", "used_monthly_credits"},
    "credits": {"user_id", "balance", "total_used"},
    "usage_records": {"id", "user_id"},
}


class DurableAiSchemaError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def source_contract() -> dict[str, Any]:
    paths = tuple(sorted(MIGRATION_DIR.glob("*.sql")))
    if tuple(path.name for path in paths) != EXPECTED_MIGRATION_NAMES:
        raise DurableAiSchemaError("migration_set")
    payloads = {path.name: path.read_bytes() for path in paths}
    hashes = {
        name: hashlib.sha256(payload).hexdigest()
        for name, payload in payloads.items()
    }
    if hashes[MIGRATION_NAME] != MIGRATION_SHA256:
        raise DurableAiSchemaError("migration_source_hash")
    return {
        "migration_payload": payloads[MIGRATION_NAME],
        "migration_sha256": MIGRATION_SHA256,
        "migration_hashes": hashes,
    }


def _connect() -> Any:
    if psycopg is None:
        raise DurableAiSchemaError("psycopg_unavailable")
    database_url = os.environ.get(DATABASE_URL_ENV, "").strip()
    if not database_url:
        raise DurableAiSchemaError("database_url_missing")
    try:
        return psycopg.connect(
            database_url, row_factory=dict_row, connect_timeout=10,
            options="-c timezone=UTC",
        )
    except Exception:
        raise DurableAiSchemaError("database_connect") from None


def _activate_owner(conn: Any) -> None:
    conn.execute(f"SET LOCAL ROLE {OWNER_ROLE}")
    identity = conn.execute(
        "SELECT session_user AS session_role,current_user AS current_role"
    ).fetchone()
    if (
        identity is None
        or identity["current_role"] != OWNER_ROLE
        or identity["session_role"] in RUNTIME_ROLES
    ):
        raise DurableAiSchemaError("owner_activation")


def _ledger_rows(conn: Any) -> list[dict[str, Any]]:
    return list(conn.execute(
        "SELECT version,sha256 FROM schema_migrations ORDER BY version"
    ).fetchall())


def _verify_ledger(
    rows: list[dict[str, Any]], names: tuple[str, ...], hashes: dict[str, str]
) -> None:
    if tuple(str(row["version"]) for row in rows) != names:
        raise DurableAiSchemaError("ledger_versions")
    if any(
        str(row["sha256"] or "") != hashes[str(row["version"])]
        for row in rows
    ):
        raise DurableAiSchemaError("ledger_hash")


def _worker_select_columns(conn: Any) -> dict[str, set[str]]:
    rows = conn.execute(
        "SELECT table_name,column_name,is_grantable "
        "FROM information_schema.column_privileges "
        "WHERE table_schema='public' AND grantee='noteai_ai_worker' "
        "AND privilege_type='SELECT' AND table_name = ANY(%s) "
        "ORDER BY table_name,column_name",
        (list(WORKER_SELECT_AFTER),),
    ).fetchall()
    if any(str(row["is_grantable"]) != "NO" for row in rows):
        raise DurableAiSchemaError("worker_select_grantable")
    observed = {table: set() for table in WORKER_SELECT_AFTER}
    for row in rows:
        observed[str(row["table_name"])].add(str(row["column_name"]))
    return observed


def _runtime_role_snapshot(conn: Any) -> str:
    """Compare role state before/after; LOGIN may already differ by role."""
    row = conn.execute(
        """
        WITH roles AS (
            SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,
                   rolcanlogin,rolreplication,rolbypassrls
              FROM pg_roles WHERE rolname = ANY(%s)
        ), memberships AS (
            SELECT granted.rolname AS granted_name,
                   member.rolname AS member_name,m.admin_option,
                   to_jsonb(m)->>'inherit_option' AS inherit_option,
                   to_jsonb(m)->>'set_option' AS set_option
              FROM pg_auth_members m
              JOIN pg_roles granted ON granted.oid=m.roleid
              JOIN pg_roles member ON member.oid=m.member
             WHERE granted.rolname = ANY(%s) OR member.rolname = ANY(%s)
        ), ownership AS (
            SELECT owner_name,kind,COUNT(*)::integer AS count FROM (
                SELECT owner.rolname owner_name,'relation' kind
                  FROM pg_class o JOIN pg_roles owner ON owner.oid=o.relowner
                UNION ALL SELECT owner.rolname,'schema'
                  FROM pg_namespace o JOIN pg_roles owner ON owner.oid=o.nspowner
                UNION ALL SELECT owner.rolname,'function'
                  FROM pg_proc o JOIN pg_roles owner ON owner.oid=o.proowner
            ) owned WHERE owner_name = ANY(%s) GROUP BY owner_name,kind
        )
        SELECT (SELECT COUNT(*) FROM roles)::integer AS role_count,
               jsonb_build_object(
                 'roles',COALESCE((SELECT jsonb_agg(to_jsonb(r) ORDER BY rolname)
                                      FROM roles r),'[]'::jsonb),
                 'memberships',COALESCE((SELECT jsonb_agg(to_jsonb(m)
                                      ORDER BY granted_name,member_name)
                                      FROM memberships m),'[]'::jsonb),
                 'ownership',COALESCE((SELECT jsonb_agg(to_jsonb(o)
                                      ORDER BY owner_name,kind)
                                      FROM ownership o),'[]'::jsonb)
               )::text AS snapshot
        """,
        (list(RUNTIME_ROLES),) * 4,
    ).fetchone()
    if row is None or int(row["role_count"]) != len(RUNTIME_ROLES):
        raise DurableAiSchemaError("runtime_roles_missing")
    return str(row["snapshot"])


def _verify_postconditions(conn: Any, contract: dict[str, Any]) -> dict[str, Any]:
    rows = _ledger_rows(conn)
    _verify_ledger(rows, EXPECTED_MIGRATION_NAMES, contract["migration_hashes"])
    index = conn.execute(
        "SELECT indexdef FROM pg_indexes WHERE schemaname='public' "
        "AND tablename='ai_operation_outbox' AND indexname=%s", (INDEX_NAME,),
    ).fetchone()
    indexdef = re.sub(r"\s+", " ", str(index["indexdef"] if index else ""))
    if not all(part in indexdef for part in (
        "(delivered_at, id)", "INCLUDE (operation_id)",
        "WHERE (state = 'delivered'::text)",
    )):
        raise DurableAiSchemaError("delivered_index")
    policy = conn.execute(
        "SELECT permissive,roles::text AS roles,cmd,qual,with_check "
        "FROM pg_policies WHERE schemaname='public' "
        "AND tablename='ai_operation_outbox' AND policyname=%s", (POLICY_NAME,),
    ).fetchone()
    qual = re.sub(r"\s+", "", str(policy["qual"] if policy else ""))
    if (
        policy is None or str(policy["permissive"]) != "PERMISSIVE"
        or str(policy["roles"]) != "{public}" or str(policy["cmd"]) != "SELECT"
        or policy["with_check"] is not None
        or "current_user='noteai_ai_worker'::name" not in qual
        or "state='delivered'::text" not in qual
    ):
        raise DurableAiSchemaError("worker_rls_policy")
    rls = conn.execute(
        "SELECT relrowsecurity FROM pg_class WHERE "
        "oid='public.ai_operation_outbox'::regclass"
    ).fetchone()
    if rls is None or not bool(rls["relrowsecurity"]):
        raise DurableAiSchemaError("worker_rls_disabled")
    columns = _worker_select_columns(conn)
    if columns != WORKER_SELECT_AFTER:
        raise DurableAiSchemaError("worker_select_columns")
    broad = conn.execute(
        "SELECT COUNT(*)::integer AS count FROM unnest(%s::text[]) table_name "
        "WHERE has_table_privilege('noteai_ai_worker',table_name,'SELECT')",
        (list(WORKER_SELECT_AFTER),),
    ).fetchone()
    if broad is None or int(broad["count"]):
        raise DurableAiSchemaError("worker_broad_select")
    return {
        "ledger_count": len(rows), "ledger_last": MIGRATION_NAME,
        "migration_sha256": MIGRATION_SHA256, "delivered_index_count": 1,
        "delivered_policy_count": 1,
        "worker_scoped_select_column_count": sum(map(len, columns.values())),
        "worker_broad_select_count": 0,
    }


def apply_schema(conn: Any, contract: dict[str, Any]) -> dict[str, Any]:
    with conn.transaction():
        conn.execute("SET LOCAL statement_timeout='60s'")
        conn.execute("SET LOCAL lock_timeout='5s'")
        conn.execute("SET LOCAL idle_in_transaction_session_timeout='90s'")
        _activate_owner(conn)
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext('noteai_schema_migrations'))"
        )
        _verify_ledger(
            _ledger_rows(conn), PRIOR_MIGRATION_NAMES,
            contract["migration_hashes"],
        )
        if _worker_select_columns(conn) != WORKER_SELECT_BEFORE:
            raise DurableAiSchemaError("precondition_worker_select_columns")
        present = conn.execute(
            "SELECT to_regclass(%s) IS NOT NULL AS index_present,"
            "EXISTS(SELECT 1 FROM pg_policies WHERE schemaname='public' "
            "AND tablename='ai_operation_outbox' AND policyname=%s) "
            "AS policy_present",
            (f"public.{INDEX_NAME}", POLICY_NAME),
        ).fetchone()
        if present["index_present"] or present["policy_present"]:
            raise DurableAiSchemaError("precondition_schema_object")
        role_before = _runtime_role_snapshot(conn)
        conn.execute(contract["migration_payload"].decode("utf-8"))
        inserted = conn.execute(
            "INSERT INTO schema_migrations(version,sha256) VALUES(%s,%s)",
            (MIGRATION_NAME, MIGRATION_SHA256),
        )
        if int(inserted.rowcount or 0) != 1:
            raise DurableAiSchemaError("ledger_insert")
        verification = _verify_postconditions(conn, contract)
        if _runtime_role_snapshot(conn) != role_before:
            raise DurableAiSchemaError("runtime_role_drift")
    return {
        "status": "verified", "mode": "apply", "transaction_committed": True,
        "applied_versions": [MIGRATION_NAME], "provider_calls": 0,
        "database_writes": {"migration_ledger_rows": 1,
                            "business_row_updates": 0,
                            "prompt_row_updates": 0},
        "runtime_roles_unchanged": True, "verification": verification,
    }


def verify_schema(conn: Any, contract: dict[str, Any]) -> dict[str, Any]:
    with conn.transaction():
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL statement_timeout='30s'")
        conn.execute("SET LOCAL lock_timeout='5s'")
        _activate_owner(conn)
        verification = _verify_postconditions(conn, contract)
    return {
        "status": "verified", "mode": "verify", "read_only": True,
        "database_writes": 0, "provider_calls": 0,
        "verification": verification,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--apply", action="store_true")
    action.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    if args.apply and os.environ.get(CONFIRM_ENV) != TASK_ID:
        print("production_durable_ai_schema_0017=FAIL "
              "code=confirmation_missing", file=sys.stderr)
        return 2
    conn = None
    try:
        contract = source_contract()
        conn = _connect()
        result = apply_schema(conn, contract) if args.apply else verify_schema(
            conn, contract
        )
    except DurableAiSchemaError as exc:
        print(f"production_durable_ai_schema_0017=FAIL code={exc.code}",
              file=sys.stderr)
        return 1
    except Exception:
        print("production_durable_ai_schema_0017=FAIL code=unexpected",
              file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
