#!/usr/bin/env python3
"""Classify the outcome of the bounded production schema transaction.

This incident audit is intentionally independent of the schema executor and
its full contract verifier.  It opens one forced-read-only connection, reads
only migration/schema/role metadata and fixed aggregate counts, and classifies
the database as the exact legacy state, the exact committed state, or a
conflict.  It never reads business-row values.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - exercised by deployment environment
    psycopg = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_DIR = ROOT / "model" / "migrations" / "postgres"
DATABASE_URL_ENV = "NOTEAI_SCHEMA_OUTCOME_DATABASE_URL"
TASK_ID = "PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-001"
AUDIT_ID = "PROD-SCHEMA-OUTCOME-READONLY-001"
EXPECTED_VERSIONS = tuple(f"{number:04d}" for number in range(1, 17))
LEGACY_VERSIONS = EXPECTED_VERSIONS[:8]
MIGRATION_LEDGER_CONSTRAINT = "schema_migrations_sha256_format"
PROVEN_PRECONNECT_CODES = frozenset({
    "database_url_missing",
    "migration_set",
    "psycopg_unavailable",
})

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
EXPECTED_TABLES = tuple(sorted((*LEGACY_TABLES, *NEW_TABLES)))
EXPECTED_SEQUENCES = (
    "analysis_log_id_seq",
    "crawler_events_id_seq",
    "hot_keywords_id_seq",
    "keyword_snapshots_id_seq",
    "prompt_history_id_seq",
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
EXPECTED_PRESENT_RUNTIME_ROLES = tuple(sorted(RUNTIME_ROLES))
LEGACY_RUNTIME_ROLES = ("noteai_app", "noteai_xhs")
NEW_RUNTIME_ROLES = tuple(
    role for role in RUNTIME_ROLES if role not in LEGACY_RUNTIME_ROLES
)


class OutcomeAuditError(RuntimeError):
    """A sanitized fail-closed audit error."""

    def __init__(self, code: str, *, stage: str):
        super().__init__(code)
        self.code = code
        self.stage = stage


def _migration_manifest() -> tuple[tuple[str, ...], dict[str, str]]:
    paths = sorted(MIGRATION_DIR.glob("*.sql"))
    versions = tuple(path.name.split("_", 1)[0] for path in paths)
    if versions != EXPECTED_VERSIONS:
        raise OutcomeAuditError("migration_set", stage="local_source")
    names = tuple(path.name for path in paths)
    hashes = {
        path.name.split("_", 1)[0]: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }
    return names, hashes


def _migration_hashes() -> dict[str, str]:
    return _migration_manifest()[1]


def _value(row: Any) -> Any:
    if row is None:
        raise OutcomeAuditError("missing_scalar", stage="database_read")
    return next(iter(row.values())) if isinstance(row, dict) else row[0]


def _scalar(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> Any:
    return _value(conn.execute(sql, params).fetchone())


def _version(value: Any) -> str:
    return str(value).split("_", 1)[0]


def _ledger_state(
    rows: list[Any],
    *,
    sha_column_count: int,
    expected_hashes: dict[str, str],
) -> tuple[tuple[str, ...], int]:
    versions = tuple(_version(row["version"]) for row in rows)
    if sha_column_count == 0:
        return versions, 0
    matching_hashes = sum(
        str(row["sha256"]) == expected_hashes.get(_version(row["version"]))
        for row in rows
    )
    return versions, matching_hashes


def _classify(observation: dict[str, Any]) -> str:
    legacy = (
        observation["ledger_versions"] == LEGACY_VERSIONS
        and observation["legacy_ledger_names_exact"]
        and observation["sha_column_count"] == 0
        and observation["sha_constraint_count"] == 0
        and observation["sha_constraint_exact_count"] == 0
        and observation["matching_migration_hash_count"] == 0
        and observation["tables"] == LEGACY_TABLES
        and observation["sequences"] == EXPECTED_SEQUENCES
        and observation["present_runtime_roles"] == LEGACY_RUNTIME_ROLES
        and observation["new_runtime_role_count"] == 0
        and observation["runtime_elevation_count"] == 0
        and observation["runtime_membership_count"] == 0
        and observation["runtime_ownership_count"] == 0
        and observation["trends_seed_count"] is None
        and observation["dispatcher_seed_count"] is None
        and observation["retention_row_count"] is None
    )
    committed = (
        observation["ledger_versions"] == EXPECTED_VERSIONS
        and observation["complete_ledger_names_exact"]
        and observation["sha_column_count"] == 1
        and observation["sha_data_type"] == "text"
        and observation["sha_nullable"] == "NO"
        and observation["sha_constraint_count"] == 1
        and observation["sha_constraint_exact_count"] == 1
        and observation["matching_migration_hash_count"]
        == len(EXPECTED_VERSIONS)
        and observation["tables"] == EXPECTED_TABLES
        and observation["sequences"] == EXPECTED_SEQUENCES
        and observation["present_runtime_roles"] == EXPECTED_PRESENT_RUNTIME_ROLES
        and observation["new_runtime_role_count"] == len(NEW_RUNTIME_ROLES)
        and observation["new_runtime_login_count"] == 0
        and observation["runtime_elevation_count"] == 0
        and observation["runtime_membership_count"] == 0
        and observation["runtime_ownership_count"] == 0
        and observation["trends_seed_count"] == 1
        and observation["trends_seed_exact_count"] == 1
        and observation["dispatcher_seed_count"] == 1
        and observation["dispatcher_seed_exact_count"] == 1
        and observation["retention_row_count"] == 0
    )
    if legacy:
        return "ROLLED_BACK"
    if committed:
        return "COMMITTED"
    return "CONFLICT"


def _optional_count(conn: Any, table: str, tables: tuple[str, ...]) -> int | None:
    if table not in tables:
        return None
    return int(_scalar(conn, f"SELECT COUNT(*) FROM public.{table}"))


def _constraint_definition_exact(row: Any) -> bool:
    normalized = "".join(str(row["definition"]).split())
    return (
        row["contype"] == "c"
        and bool(row["convalidated"])
        and normalized == "CHECK((sha256~'^[0-9a-f]{64}$'::text))"
    )


def collect_outcome(
    conn: Any,
    *,
    migration_manifest: tuple[tuple[str, ...], dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Collect and classify one exact read-only database snapshot."""
    expected_names, expected_hashes = (
        migration_manifest
        if migration_manifest is not None
        else _migration_manifest()
    )
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
                raise OutcomeAuditError(
                    "readonly_not_enforced",
                    stage="readonly_proof",
                )

            tables = tuple(
                row["table_name"]
                for row in conn.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='public' "
                    "AND table_type='BASE TABLE' ORDER BY table_name"
                ).fetchall()
            )
            ledger_columns = conn.execute(
                "SELECT column_name,data_type,is_nullable "
                "FROM information_schema.columns "
                "WHERE table_schema='public' "
                "AND table_name='schema_migrations' "
                "ORDER BY ordinal_position"
            ).fetchall()
            column_by_name = {
                row["column_name"]: row for row in ledger_columns
            }
            sha_row = column_by_name.get("sha256")
            sha_column_count = int(sha_row is not None)
            sha_data_type = None if sha_row is None else str(sha_row["data_type"])
            sha_nullable = None if sha_row is None else str(sha_row["is_nullable"])
            if "schema_migrations" in tables:
                constraint_rows = conn.execute(
                    "SELECT contype,convalidated,"
                    "pg_get_constraintdef(oid) AS definition "
                    "FROM pg_constraint "
                    "WHERE conrelid='schema_migrations'::regclass "
                    "AND conname=%s",
                    (MIGRATION_LEDGER_CONSTRAINT,),
                ).fetchall()
            else:
                constraint_rows = []
            sha_constraint_count = len(constraint_rows)
            sha_constraint_exact_count = sum(
                _constraint_definition_exact(row) for row in constraint_rows
            )
            if (
                "schema_migrations" in tables
                and "version" in column_by_name
            ):
                if sha_column_count:
                    ledger_rows = conn.execute(
                        "SELECT version,sha256 "
                        "FROM schema_migrations ORDER BY version"
                    ).fetchall()
                else:
                    ledger_rows = conn.execute(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    ).fetchall()
            else:
                ledger_rows = []
            ledger_versions, matching_hashes = _ledger_state(
                ledger_rows,
                sha_column_count=sha_column_count,
                expected_hashes=expected_hashes,
            )
            ledger_names = tuple(str(row["version"]) for row in ledger_rows)
            canonical_name_count = sum(
                actual == expected
                for actual, expected in zip(ledger_names, expected_names)
            )

            sequences = tuple(
                row["sequence_name"]
                for row in conn.execute(
                    "SELECT sequence_name FROM information_schema.sequences "
                    "WHERE sequence_schema='public' ORDER BY sequence_name"
                ).fetchall()
            )
            role_rows = conn.execute(
                "SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,"
                "rolcanlogin,rolreplication,rolbypassrls FROM pg_roles "
                "WHERE rolname = ANY(%s) ORDER BY rolname",
                (list(RUNTIME_ROLES),),
            ).fetchall()
            present_roles = tuple(sorted(row["rolname"] for row in role_rows))
            new_role_count = sum(
                row["rolname"] in NEW_RUNTIME_ROLES for row in role_rows
            )
            new_login_count = sum(
                row["rolname"] in NEW_RUNTIME_ROLES and bool(row["rolcanlogin"])
                for row in role_rows
            )
            elevation_count = sum(
                bool(row[key])
                for row in role_rows
                for key in (
                    "rolsuper",
                    "rolinherit",
                    "rolcreaterole",
                    "rolcreatedb",
                    "rolreplication",
                    "rolbypassrls",
                )
            )
            membership_count = int(
                _scalar(
                    conn,
                    "SELECT COUNT(*) FROM pg_auth_members membership "
                    "JOIN pg_roles granted_role "
                    "ON granted_role.oid=membership.roleid "
                    "JOIN pg_roles member_role "
                    "ON member_role.oid=membership.member "
                    "WHERE granted_role.rolname = ANY(%s) "
                    "OR member_role.rolname = ANY(%s)",
                    (list(RUNTIME_ROLES), list(RUNTIME_ROLES)),
                )
            )
            ownership_count = int(
                _scalar(
                    conn,
                    "SELECT ("
                    "(SELECT COUNT(*) FROM pg_class object "
                    "JOIN pg_roles role ON role.oid=object.relowner "
                    "WHERE role.rolname = ANY(%s)) + "
                    "(SELECT COUNT(*) FROM pg_namespace object "
                    "JOIN pg_roles role ON role.oid=object.nspowner "
                    "WHERE role.rolname = ANY(%s)) + "
                    "(SELECT COUNT(*) FROM pg_proc object "
                    "JOIN pg_roles role ON role.oid=object.proowner "
                    "WHERE role.rolname = ANY(%s)))",
                    (
                        list(RUNTIME_ROLES),
                        list(RUNTIME_ROLES),
                        list(RUNTIME_ROLES),
                    ),
                )
            )
            observation = {
                "ledger_versions": ledger_versions,
                "legacy_ledger_names_exact": (
                    ledger_names == expected_names[: len(LEGACY_VERSIONS)]
                ),
                "complete_ledger_names_exact": ledger_names == expected_names,
                "canonical_migration_name_count": canonical_name_count,
                "sha_column_count": sha_column_count,
                "sha_data_type": sha_data_type,
                "sha_nullable": sha_nullable,
                "sha_constraint_count": sha_constraint_count,
                "sha_constraint_exact_count": sha_constraint_exact_count,
                "matching_migration_hash_count": matching_hashes,
                "tables": tables,
                "sequences": sequences,
                "present_runtime_roles": present_roles,
                "new_runtime_role_count": new_role_count,
                "new_runtime_login_count": new_login_count,
                "runtime_elevation_count": elevation_count,
                "runtime_membership_count": membership_count,
                "runtime_ownership_count": ownership_count,
                "trends_seed_count": _optional_count(
                    conn,
                    "xhs_trends_service_state",
                    tables,
                ),
                "trends_seed_exact_count": (
                    None
                    if "xhs_trends_service_state" not in tables
                    else int(
                        _scalar(
                            conn,
                            "SELECT COUNT(*) "
                            "FROM public.xhs_trends_service_state "
                            "WHERE service_key='market_timing' "
                            "AND status='idle' "
                            "AND active_run_id IS NULL "
                            "AND lease_token_hash IS NULL "
                            "AND lease_fence=0 "
                            "AND lease_expires_at IS NULL "
                            "AND session_blocked=FALSE "
                            "AND session_block_reason='' "
                            "AND session_blocked_at IS NULL",
                        )
                    )
                ),
                "dispatcher_seed_count": _optional_count(
                    conn,
                    "ai_dispatch_state",
                    tables,
                ),
                "dispatcher_seed_exact_count": (
                    None
                    if "ai_dispatch_state" not in tables
                    else int(
                        _scalar(
                            conn,
                            "SELECT COUNT(*) FROM public.ai_dispatch_state "
                            "WHERE service_key='durable_ai' "
                            "AND priority_streak=0 "
                            "AND updated_at='1970-01-01T00:00:00+00:00'",
                        )
                    )
                ),
                "retention_row_count": _optional_count(
                    conn,
                    "content_retention",
                    tables,
                ),
            }
    except OutcomeAuditError:
        raise
    except BaseException as exc:
        raise OutcomeAuditError(
            "database_read_failed",
            stage="database_read",
        ) from exc

    outcome = _classify(observation)
    versions = observation["ledger_versions"]
    public_observation = {
        "ledger_count": len(versions),
        "ledger_first": versions[0] if versions else None,
        "ledger_last": versions[-1] if versions else None,
        "sha_column_count": observation["sha_column_count"],
        "sha_constraint_count": observation["sha_constraint_count"],
        "sha_constraint_exact_count": observation[
            "sha_constraint_exact_count"
        ],
        "matching_migration_hash_count": observation[
            "matching_migration_hash_count"
        ],
        "canonical_migration_name_count": observation[
            "canonical_migration_name_count"
        ],
        "table_count": len(observation["tables"]),
        "sequence_count": len(observation["sequences"]),
        "runtime_role_count": len(observation["present_runtime_roles"]),
        "new_runtime_role_count": observation["new_runtime_role_count"],
        "new_runtime_login_count": observation["new_runtime_login_count"],
        "runtime_elevation_count": observation["runtime_elevation_count"],
        "runtime_membership_count": observation["runtime_membership_count"],
        "runtime_ownership_count": observation["runtime_ownership_count"],
        "trends_seed_count": observation["trends_seed_count"],
        "trends_seed_exact_count": observation["trends_seed_exact_count"],
        "dispatcher_seed_count": observation["dispatcher_seed_count"],
        "dispatcher_seed_exact_count": observation[
            "dispatcher_seed_exact_count"
        ],
        "retention_row_count": observation["retention_row_count"],
        "business_row_values_read": 0,
    }
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "audit_id": AUDIT_ID,
        "status": "classified",
        "database_outcome": outcome,
        "read_only": True,
        "default_transaction_read_only": True,
        "transaction_read_only": True,
        "observation": public_observation,
        "provider_calls": 0,
        "service_changes": 0,
        "public_traffic_requests": 0,
        "secret_values_exposed": 0,
    }


def _connect() -> Any:
    if psycopg is None:
        raise OutcomeAuditError("psycopg_unavailable", stage="connect")
    database_url = os.environ.get(DATABASE_URL_ENV, "").strip()
    if not database_url:
        raise OutcomeAuditError("database_url_missing", stage="connect")
    return psycopg.connect(
        database_url,
        row_factory=dict_row,
        connect_timeout=10,
        application_name="noteai_schema_outcome_audit_v1",
        options="-c default_transaction_read_only=on",
    )


def _report_failure(
    *,
    stage: str,
    connected: bool,
    connection_attempted: bool,
    proven_preconnect: bool,
) -> int:
    if proven_preconnect:
        print(
            "production_schema_outcome_audit=FAIL "
            f"stage={stage} incident_class=PRE_CONNECT "
            "database_connected=0 connection_attempted=0 "
            "database_outcome=NOT_CONNECTED retry_same_path=0",
            file=sys.stderr,
        )
        return 2
    print(
        "production_schema_outcome_audit=FAIL "
        f"stage={stage} incident_class=CONNECTED_UNKNOWN "
        f"database_connected={int(connected)} "
        f"connection_attempted={int(connection_attempted)} "
        "database_outcome=UNKNOWN no_retry=1",
        file=sys.stderr,
    )
    return 1


def main() -> int:
    connected = False
    connection_attempted = False
    try:
        migration_manifest = _migration_manifest()
        connection_attempted = True
        conn = _connect()
        connected = True
        try:
            result = collect_outcome(
                conn,
                migration_manifest=migration_manifest,
            )
        finally:
            conn.close()
    except OutcomeAuditError as exc:
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
        )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
