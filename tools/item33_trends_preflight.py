"""Targeted, rollback-only database facts for Item33's existing preflight.

No connection, credentials, CLI, schema changes or provider calls are made here.
The caller supplies the original Trends connection. These facts do not certify
capture coverage, install triggers, or authorize a managed cycle on their own.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re

try:
    from . import production_schema_roles as roles
except ImportError:
    import production_schema_roles as roles


ROLE = "noteai_xhs_trends"
TABLES = frozenset(roles.TRENDS_PRIVILEGES)
IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class Item33PreflightError(RuntimeError):
    """Only fixed, non-sensitive reason codes escape this reader."""


def require(condition, code):
    if not condition:
        raise Item33PreflightError(code)


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_database_facts(connection, *, now: datetime) -> dict:
    """Read the actual role, ACL and UTC ledger in one READ ONLY transaction.

    Reject an existing transaction instead of committing/rolling it back. Once
    this reader starts its own transaction it always rolls it back. All SQL is
    fixed and all row reads are counts or catalog metadata, never user content.
    """
    from psycopg.rows import dict_row

    require(isinstance(now, datetime) and now.tzinfo is not None, "clock")
    now = now.astimezone(timezone.utc)
    require(connection.autocommit is True and connection.info.transaction_status == 0,
            "connection_not_idle_autocommit")
    begun = False
    try:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("BEGIN READ ONLY")
            begun = True
            cursor.execute("SET LOCAL statement_timeout='5000ms'")
            identity = cursor.execute("""
                SELECT session_user::text AS session_role,current_user::text AS current_role,
                    current_setting('transaction_read_only') AS read_only,
                    (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date::text AS bucket,
                    CURRENT_TIMESTAMP AS observed_at,pg_current_xact_id_if_assigned()::text AS xid
            """).fetchone()
            require(identity["session_role"] == identity["current_role"] == ROLE
                    and identity["read_only"] == "on" and identity["xid"] is None,
                    "role_or_readonly")
            require(identity["bucket"] == now.date().isoformat()
                    and abs((identity["observed_at"] - now).total_seconds()) <= 60, "database_clock")
            role = cursor.execute("""
                SELECT rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls,
                    rolcanlogin,
                    (SELECT count(*) FROM pg_auth_members m WHERE m.member=r.oid)::int AS memberships,
                    (SELECT count(*) FROM pg_class c WHERE c.relowner=r.oid)::int AS owned_relations,
                    (SELECT count(*) FROM pg_namespace n WHERE n.nspowner=r.oid)::int AS owned_schemas,
                    (SELECT count(*) FROM pg_proc p WHERE p.proowner=r.oid)::int AS owned_functions
                FROM pg_roles r WHERE rolname=%s
            """, (ROLE,)).fetchone()
            require(role is not None and role["rolcanlogin"] is True
                    and all(role[key] is False for key in ("rolsuper", "rolinherit", "rolcreaterole",
                            "rolcreatedb", "rolreplication", "rolbypassrls"))
                    and all(type(role[key]) is int and role[key] == 0 for key in
                            ("memberships", "owned_relations", "owned_schemas", "owned_functions")),
                    "role_contract")
            objects = cursor.execute("""
                SELECT n.nspname AS schema,c.relname AS name,c.relkind AS kind
                FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f','S')
                ORDER BY c.relname LIMIT 513
            """).fetchall()
            require(8 <= len(objects) <= 512 and all(IDENTIFIER.fullmatch(x["name"]) for x in objects),
                    "object_inventory")
            tables = tuple(x["name"] for x in objects if x["kind"] != "S")
            sequences = tuple(x["name"] for x in objects if x["kind"] == "S")
            require(TABLES <= set(tables) and all(x["kind"] == "r" for x in objects if x["name"] in TABLES),
                    "trends_table_shape")
            try:
                acl = roles._acl_matrix_metrics(cursor, roles=(ROLE,), tables=tables, sequences=sequences)
            except roles.SchemaRoleError:
                raise Item33PreflightError("acl_contract") from None
            outside = cursor.execute("""
                SELECT
                  (SELECT count(*) FROM pg_namespace n WHERE n.nspname NOT LIKE 'pg_%%'
                   AND n.nspname<>'information_schema' AND has_schema_privilege(%s,n.oid,'CREATE'))::int
                    AS schema_create,
                  (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                   WHERE n.nspname NOT LIKE 'pg_%%' AND n.nspname NOT IN ('public','information_schema')
                   AND c.relkind IN ('r','p','v','m','f') AND
                     (has_table_privilege(%s,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,TRIGGER')
                      OR has_any_column_privilege(%s,c.oid,'INSERT,UPDATE')))::int AS outside_writable,
                  has_database_privilege(%s,current_database(),'CREATE') AS database_create
            """, (ROLE, ROLE, ROLE, ROLE)).fetchone()
            require(outside == {"schema_create": 0, "outside_writable": 0, "database_create": False},
                    "outside_acl")
            ledger = cursor.execute("""
                SELECT
                  (SELECT count(*) FROM xhs_trends_runs WHERE status IN ('running','needs_manual'))::int AS active_run_count,
                  (SELECT count(*) FROM xhs_trends_runs WHERE bucket_key=%s)::int AS same_bucket_run_count,
                  (SELECT count(*) FROM xhs_trends_provider_attempts WHERE status='outcome_unknown')::int AS outcome_unknown_count,
                  (SELECT count(*) FROM xhs_trends_provider_attempts a LEFT JOIN xhs_trends_runs r ON r.id=a.run_id
                   WHERE r.id IS NULL)::int AS unlinked_attempt_count,
                  (SELECT count(*) FROM xhs_trends_provider_attempts a JOIN xhs_trends_runs r ON r.id=a.run_id
                   WHERE r.bucket_key=%s)::int AS utc_provider_budget_used_before,
                  (SELECT count(*) FROM xhs_trends_provider_attempts WHERE status='admitted')::int AS admitted_count,
                  (SELECT count(*) FROM xhs_trends_service_state WHERE service_key='market_timing'
                   AND status='idle' AND active_run_id IS NULL AND session_blocked=FALSE)::int AS idle_service_count
            """, (identity["bucket"], identity["bucket"])).fetchone()
            # Existing local/isolated Item32 usage must separately be merged by
            # the later-UTC controller; database0 is not fresh on the Item32 day.
            require(ledger["idle_service_count"] == 1 and all(type(value) is int and value == 0
                    for key, value in ledger.items() if key != "idle_service_count"), "ledger_not_fresh")
            catalog = cursor.execute("""
                SELECT c.relname AS table_name,t.tgname AS trigger_name,t.tgenabled AS enabled,
                    t.tgisinternal AS internal,p.prosecdef AS security_definer,
                    encode(sha256(convert_to(pg_get_triggerdef(t.oid),'UTF8')),'hex') AS trigger_sha256,
                    encode(sha256(convert_to(pg_get_functiondef(p.oid),'UTF8')),'hex') AS function_sha256
                FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
                JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_proc p ON p.oid=t.tgfoid
                WHERE n.nspname='public' AND c.relname=ANY(%s) ORDER BY c.relname,t.tgname LIMIT 257
            """, (sorted(TABLES),)).fetchall()
            require(len(catalog) <= 256, "trigger_inventory")
            end = cursor.execute("""
                SELECT current_setting('transaction_read_only') AS read_only,
                       pg_current_xact_id_if_assigned()::text AS xid
            """).fetchone()
            require(end == {"read_only": "on", "xid": None}, "readonly_changed")
            result = {"schema": "noteai.item33.database_preflight.v1",
                "observed_at": identity["observed_at"].isoformat(), "bucket_key": identity["bucket"],
                "database_role": ROLE, "role_exact": True, "acl_exact": True,
                "server_enforced_read_only": True, "xid_assigned": False,
                "production_database_writes": 0, "provider_calls": 0,
                "role_metrics": dict(role), "acl_metrics": dict(acl), "outside_acl": dict(outside),
                "ledger": dict(ledger), "utc_provider_budget_remaining_before": 34,
                "object_inventory_sha256": _hash(objects), "triggers": [dict(x) for x in catalog],
                "capture_coverage_verified": False, "business_ddl_count_verified": False,
                "secret_values_recorded": False}
        connection.rollback()
        begun = False
        result["transaction_rolled_back"] = True
        result["canonical_sha256"] = _hash(result)
        return result
    except Item33PreflightError:
        raise
    except Exception:
        raise Item33PreflightError("database_preflight_unknown") from None
    finally:
        if begun:
            try:
                connection.rollback()
            except Exception:
                raise Item33PreflightError("database_rollback_unknown") from None
