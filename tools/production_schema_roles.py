#!/usr/bin/env python3
"""Apply and verify the first-launch PostgreSQL schema/runtime-role contract.

The production apply path is deliberately separate from Render predeploy: it
does not seed managed prompts, start services, enable providers or distribute
credentials. Migrations 0009-0016, the credential-free role ACL and their
complete negative matrix are committed in one PostgreSQL transaction.
"""

from __future__ import annotations

import argparse
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

try:
    from tools.collect_production_database_preflight import (
        APP_TABLE_PRIVILEGES,
        EXPECTED_PUBLIC_SEQUENCES,
        EXPECTED_PUBLIC_TABLES,
        SEQUENCE_PRIVILEGES,
        TABLE_PRIVILEGES,
        XHS_TABLE_PRIVILEGES,
    )
except ModuleNotFoundError:
    from collect_production_database_preflight import (  # type: ignore[no-redef]
        APP_TABLE_PRIVILEGES,
        EXPECTED_PUBLIC_SEQUENCES,
        EXPECTED_PUBLIC_TABLES,
        SEQUENCE_PRIVILEGES,
        TABLE_PRIVILEGES,
        XHS_TABLE_PRIVILEGES,
    )


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_DIR = ROOT / "model" / "migrations" / "postgres"
ACL_PATH = ROOT / "scripts" / "postgres" / "noteai_production_runtime_roles.sql"
DATABASE_URL_ENV = "NOTEAI_SCHEMA_DATABASE_URL"
CONFIRM_ENV = "NOTEAI_SCHEMA_APPLY_CONFIRM"
TASK_ID = "PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-001"
ACCEPTED_ROLE_RISK_PROFILE = "FIRST_LAUNCH_LEGACY_ROLE_RISK_V1"
ACCEPTED_ROLE_RISK_IDS = (
    "FIRST-LAUNCH-LEGACY-XHS-ADMIN-MEMBERSHIP-20260728",
    "FIRST-LAUNCH-LEGACY-APP-INHERIT-20260728",
)
MIGRATION_OWNER_ROLE = "noteai_admin"
EXPECTED_VERSIONS = tuple(f"{number:04d}" for number in range(1, 17))
LEGACY_VERSIONS = EXPECTED_VERSIONS[:8]
NEW_VERSIONS = EXPECTED_VERSIONS[8:]
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
ACL_STAGE_MARKER = "-- NOTEAI-RUNTIME-ACL-STAGE: "
EXPECTED_ACL_STAGES = (
    "role_contract",
    "database_schema",
    "clear_new_roles",
    "api",
    "tracking",
    "trends",
    "durable_ai",
    "private_storage",
    "payment",
    "admin",
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
EXPECTED_TABLES = tuple(sorted((*EXPECTED_PUBLIC_TABLES, *NEW_TABLES)))
TRIGGER_FUNCTIONS = (
    "public.noteai_retained_primary_insert_guard_h20()",
    "public.noteai_validate_operation_media_link_v1()",
    "public.noteai_payment_order_identity_guard_v1()",
    "public.noteai_payment_refund_identity_guard_v1()",
    "public.noteai_payment_event_identity_guard_v1()",
    "public.noteai_payment_credit_position_identity_guard_v1()",
    "public.noteai_payment_credit_position_user_guard_v1()",
    "public.noteai_payment_credit_consumption_guard_v1()",
    "public.noteai_payment_refund_insert_guard_v1()",
    "public.noteai_payment_append_only_guard_v1()",
)
ADVISORY_FUNCTIONS = (
    "pg_catalog.hashtext(text)",
    "pg_catalog.pg_advisory_xact_lock(bigint)",
)
COLUMN_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "REFERENCES")
MIGRATION_LEDGER_CONSTRAINT = "schema_migrations_sha256_format"
APPLY_FAILURE_STAGES = frozenset({
    "local_source",
    "transaction_begin",
    "session_controls",
    "migration_owner_activation",
    "advisory_lock",
    "ledger_inventory",
    "schema_inventory",
    "role_preconditions",
    "accepted_role_risk",
    "ledger_contract",
    "ledger_prepare",
    "legacy_hash_backfill",
    "migration_apply",
    *(f"runtime_acl_{name}" for name in EXPECTED_ACL_STAGES),
    "postcondition_verification",
    "transaction_commit",
    "result_build",
})


class SchemaRoleError(RuntimeError):
    """Fail-closed schema/role validation error."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _privileges(*values: str) -> tuple[str, ...]:
    return tuple(values)


APP_PRIVILEGES = {
    **APP_TABLE_PRIVILEGES,
    "notes": _privileges("SELECT", "INSERT", "DELETE"),
    "ai_operation_admissions": _privileges("SELECT", "INSERT", "DELETE"),
    "chat_sessions": _privileges("SELECT", "INSERT", "UPDATE", "DELETE"),
    "user_learn": _privileges("SELECT", "INSERT", "UPDATE", "DELETE"),
    "users": _privileges("SELECT", "INSERT", "UPDATE", "DELETE"),
    "auth_login_limits": _privileges("SELECT", "INSERT", "UPDATE", "DELETE"),
    "auth_verification_challenges": _privileges("SELECT", "INSERT", "UPDATE"),
    "content_retention": _privileges("SELECT", "INSERT"),
    "account_deletion_requests": _privileges("SELECT", "INSERT", "UPDATE"),
    "user_contract_acceptances": _privileges("SELECT", "INSERT"),
    "ai_payload_refs": _privileges("SELECT", "INSERT"),
    "ai_operation_outbox": _privileges("INSERT"),
    "ai_operation_settlements": _privileges("SELECT", "INSERT"),
    "private_media_refs": _privileges("SELECT", "INSERT"),
    "ai_operation_media_refs": _privileges("SELECT", "INSERT"),
    "payment_orders": _privileges("SELECT", "INSERT"),
    "payment_credit_positions": _privileges("SELECT"),
    "payment_credit_consumptions": _privileges("SELECT", "INSERT"),
}

TRACKING_PRIVILEGES = {
    "tracked_notes": _privileges("SELECT"),
    "tracking_provider_attempts": _privileges("SELECT", "INSERT"),
    "growth_records": _privileges("INSERT"),
    "user_memories": _privileges("INSERT"),
    "crawler_events": _privileges("INSERT"),
    "system_settings": _privileges("SELECT"),
}
TRENDS_PRIVILEGES = {
    "hot_keywords": _privileges("SELECT", "INSERT"),
    "keyword_snapshots": _privileges("SELECT", "INSERT"),
    "xhs_crawler_health": _privileges("SELECT", "INSERT"),
    "xhs_freshness_ledger": _privileges("SELECT", "INSERT"),
    "xhs_trends_runs": _privileges("SELECT", "INSERT"),
    "xhs_trends_provider_attempts": _privileges("SELECT", "INSERT"),
    "xhs_trends_service_state": _privileges("SELECT"),
    "xhs_trends_snapshot_evidence": _privileges("SELECT", "INSERT"),
}
DISPATCHER_PRIVILEGES = {
    "ai_operation_outbox": _privileges("SELECT"),
    "ai_dispatch_state": _privileges("SELECT"),
}
WORKER_PRIVILEGES = {
    "ai_payload_refs": _privileges("SELECT", "INSERT"),
    "ai_operations": _privileges("SELECT"),
    "ai_operation_events": _privileges("SELECT", "INSERT"),
    "ai_provider_attempts": _privileges("SELECT", "INSERT"),
    "ai_operation_admissions": _privileges("SELECT"),
    "ai_operation_settlements": _privileges("SELECT"),
    "idempotency_requests": _privileges("SELECT"),
    "credits": _privileges("INSERT"),
    "credit_transactions": _privileges("INSERT"),
    "model_usage_records": _privileges("INSERT"),
    "private_media_refs": _privileges("SELECT"),
    "ai_operation_media_refs": _privileges("SELECT"),
    "payment_credit_positions": _privileges("SELECT"),
    "payment_credit_consumptions": _privileges("SELECT"),
}
PAYMENT_TABLES = (
    "payment_orders",
    "payment_refunds",
    "payment_events",
    "payment_cash_ledger",
    "payment_entitlement_ledger",
    "payment_credit_positions",
    "payment_credit_consumptions",
    "payment_reconciliation_runs",
    "payment_reconciliation_items",
    "payment_settlement_summaries",
)
PAYMENT_PRIVILEGES = {
    **{table: _privileges("SELECT") for table in PAYMENT_TABLES},
    "payment_refunds": _privileges("SELECT", "INSERT"),
    "payment_events": _privileges("SELECT", "INSERT"),
    "payment_cash_ledger": _privileges("SELECT", "INSERT"),
    "payment_entitlement_ledger": _privileges("SELECT", "INSERT"),
    "payment_credit_positions": _privileges("SELECT", "INSERT"),
    "payment_reconciliation_runs": _privileges("SELECT", "INSERT"),
    "payment_reconciliation_items": _privileges("SELECT", "INSERT"),
    "payment_settlement_summaries": _privileges("SELECT", "INSERT"),
    "subscriptions": _privileges("INSERT"),
    "credits": _privileges("INSERT"),
    "credit_transactions": _privileges("INSERT"),
}
ADMIN_SELECT_TABLES = (
    "subscriptions",
    "credits",
    "usage_records",
    "model_usage_records",
    "managed_prompts",
    "prompt_history",
    "system_settings",
    "tracked_notes",
    "ai_operations",
    "ai_operation_settlements",
    "ai_operation_outbox",
    "xhs_freshness_ledger",
    "xhs_crawler_health",
    "xhs_trends_runs",
    *PAYMENT_TABLES,
)
ADMIN_PRIVILEGES = {
    **{table: _privileges("SELECT") for table in ADMIN_SELECT_TABLES},
    "admin_sessions": _privileges("SELECT", "INSERT", "DELETE"),
}
ROLE_TABLE_PRIVILEGES = {
    "noteai_app": APP_PRIVILEGES,
    "noteai_admin_runtime": ADMIN_PRIVILEGES,
    "noteai_ai_dispatcher": DISPATCHER_PRIVILEGES,
    "noteai_ai_worker": WORKER_PRIVILEGES,
    "noteai_payment": PAYMENT_PRIVILEGES,
    "noteai_xhs": XHS_TABLE_PRIVILEGES,
    "noteai_xhs_tracking": TRACKING_PRIVILEGES,
    "noteai_xhs_trends": TRENDS_PRIVILEGES,
}

SCOPED_SELECT = {
    ("noteai_app", "ai_operation_outbox"): {"id", "operation_id", "state"},
    ("noteai_app", "xhs_trends_runs"): {"id", "status", "completed_at"},
    ("noteai_ai_dispatcher", "ai_operations"): {"id", "priority"},
    ("noteai_ai_worker", "users"): {"id", "deletion_requested_at"},
    ("noteai_ai_worker", "credits"): {"user_id", "balance"},
    ("noteai_payment", "users"): {"id", "deletion_requested_at"},
    ("noteai_payment", "subscriptions"): {
        "id", "user_id", "tier", "started_at", "is_active",
    },
    ("noteai_payment", "credits"): {"user_id", "balance", "total_purchased"},
    ("noteai_payment", "usage_records"): {
        "user_id", "recorded_at", "credits_used", "source",
    },
    ("noteai_admin_runtime", "users"): {
        "id", "username", "email", "phone", "nickname", "avatar_emoji",
        "created_at", "last_login",
    },
    ("noteai_admin_runtime", "notes"): {"id", "user_id", "score"},
    ("noteai_admin_runtime", "credit_transactions"): {
        "user_id", "type", "amount", "balance_after", "description",
        "paid_rmb", "package_id", "recorded_at",
    },
}
SCOPED_UPDATE = {
    ("noteai_app", "notes"): {"parent_id"},
    ("noteai_app", "content_retention"): {
        "active_until", "recovery_until", "deleted_at", "purge_after",
        "purged_at", "updated_at",
    },
    ("noteai_app", "credit_transactions"): {"user_id"},
    ("noteai_app", "xhs_trends_runs"): set(),
    ("noteai_app", "ai_payload_refs"): {"state", "deleted_at"},
    ("noteai_app", "ai_operation_outbox"): {"state", "updated_at"},
    ("noteai_app", "ai_operation_settlements"): {
        "billing_state", "failure_code", "updated_at", "settled_at",
    },
    ("noteai_app", "private_media_refs"): {"state", "deleted_at"},
    ("noteai_app", "payment_orders"): {
        "user_id", "provider_payment_id", "payment_status", "updated_at",
        "terminal_at",
    },
    ("noteai_app", "payment_credit_positions"): {
        "user_id", "remaining_milli", "state", "updated_at",
    },
    ("noteai_app", "payment_credit_consumptions"): {"state", "updated_at"},
    ("noteai_xhs_tracking", "tracked_notes"): {
        "claim_token", "claim_expires_at", "active_attempt_id", "note_title",
        "likes_24h", "saves_24h", "comments_24h", "check_24h_at",
        "likes_7d", "saves_7d", "comments_7d", "check_7d_at", "views_est",
        "next_check_at", "last_checked_at", "attempt_count", "actual_ces",
        "confidence", "confidence_label", "evidence_source",
        "training_eligible", "status", "last_error_code", "last_error",
        "completed_at", "insights_json",
    },
    ("noteai_xhs_tracking", "tracking_provider_attempts"): {
        "status", "completed_at", "error_code",
    },
    ("noteai_xhs_trends", "hot_keywords"): {
        "search_vol", "trend_dir", "source", "sample_count", "quality_score",
        "evidence_level", "quality_reason", "captured_at",
    },
    ("noteai_xhs_trends", "xhs_freshness_ledger"): {
        "source", "evidence_count", "status", "acquired_at", "fresh_until",
        "last_run_id", "details_json",
    },
    ("noteai_xhs_trends", "xhs_trends_runs"): {
        "status", "completed_at", "provider_attempt_count", "last_error_code",
        "snapshot_sha256", "snapshot_size",
    },
    ("noteai_xhs_trends", "xhs_trends_provider_attempts"): {
        "status", "completed_at", "error_code",
    },
    ("noteai_xhs_trends", "xhs_trends_service_state"): {
        "active_run_id", "status", "lease_token_hash", "lease_fence",
        "lease_expires_at", "session_blocked", "session_block_reason",
        "session_blocked_at", "updated_at",
    },
    ("noteai_ai_dispatcher", "ai_operation_outbox"): {
        "state", "available_at", "attempt_count", "lease_owner_hash",
        "lease_fence", "lease_expires_at", "updated_at", "delivered_at",
    },
    ("noteai_ai_dispatcher", "ai_dispatch_state"): {
        "priority_streak", "updated_at",
    },
    ("noteai_ai_worker", "ai_payload_refs"): {"state", "deleted_at"},
    ("noteai_ai_worker", "ai_operations"): {
        "status", "provider_phase", "lease_owner_hash", "lease_fence",
        "lease_expires_at", "heartbeat_at", "claim_count",
        "provider_attempt_count", "event_sequence", "result_hash",
        "result_count", "updated_at", "started_at", "terminal_at",
    },
    ("noteai_ai_worker", "ai_provider_attempts"): {
        "state", "response_hash", "output_count", "updated_at", "terminal_at",
    },
    ("noteai_ai_worker", "idempotency_requests"): {
        "status", "refund_applied", "failure_code", "refunded_at", "failed_at",
        "complete_applied", "completed_at", "updated_at",
    },
    ("noteai_ai_worker", "ai_operation_settlements"): {
        "result_ref_id", "billing_state", "failure_code", "updated_at",
        "settled_at",
    },
    ("noteai_ai_worker", "subscriptions"): {"used_monthly_credits"},
    ("noteai_ai_worker", "credits"): {"balance", "total_used", "updated_at"},
    ("noteai_ai_worker", "usage_records"): {"source", "credits_used"},
    ("noteai_ai_worker", "payment_credit_positions"): {
        "remaining_milli", "state", "updated_at",
    },
    ("noteai_ai_worker", "payment_credit_consumptions"): {
        "state", "updated_at",
    },
    ("noteai_payment", "payment_orders"): {
        "provider_payment_id", "payment_status", "entitlement_status",
        "entitlement_ref", "refund_status", "refunded_fen", "refund_count",
        "updated_at", "succeeded_at", "terminal_at",
    },
    ("noteai_payment", "payment_refunds"): {
        "provider_refund_id", "status", "updated_at", "terminal_at",
    },
    ("noteai_payment", "payment_events"): {
        "processing_state", "reason_code", "order_id", "refund_id",
        "processed_at",
    },
    ("noteai_payment", "payment_credit_positions"): {
        "user_id", "remaining_milli", "state", "updated_at",
    },
    ("noteai_payment", "subscriptions"): {"is_active"},
    ("noteai_payment", "credits"): {
        "balance", "total_purchased", "updated_at",
    },
}
ROLE_SEQUENCES = {
    "noteai_app": set(EXPECTED_PUBLIC_SEQUENCES),
    "noteai_xhs": {
        "crawler_events_id_seq", "hot_keywords_id_seq",
        "keyword_snapshots_id_seq",
    },
    "noteai_xhs_tracking": {"crawler_events_id_seq"},
    "noteai_xhs_trends": {"hot_keywords_id_seq", "keyword_snapshots_id_seq"},
}


def _migration_payloads() -> dict[str, tuple[bytes, str]]:
    paths = sorted(MIGRATION_DIR.glob("*.sql"))
    versions = tuple(path.name.split("_", 1)[0] for path in paths)
    if versions != EXPECTED_VERSIONS:
        raise SchemaRoleError("migration_set")
    result: dict[str, tuple[bytes, str]] = {}
    for path in paths:
        payload = path.read_bytes()
        result[path.name.split("_", 1)[0]] = (
            payload,
            hashlib.sha256(payload).hexdigest(),
        )
    return result


def _runtime_acl_payloads() -> tuple[tuple[str, str], ...]:
    """Load the fixed ACL sections without changing their transaction scope."""
    sections: list[tuple[str, str]] = []
    stage_name: str | None = None
    stage_lines: list[str] = []
    preamble: list[str] = []
    for line in ACL_PATH.read_text(encoding="utf-8").splitlines(keepends=True):
        if line.startswith(ACL_STAGE_MARKER):
            if stage_name is not None:
                sections.append((stage_name, "".join(stage_lines)))
            stage_name = line.removeprefix(ACL_STAGE_MARKER).strip()
            stage_lines = [*preamble, line] if not sections else [line]
            preamble = []
        elif stage_name is None:
            preamble.append(line)
        else:
            stage_lines.append(line)
    if stage_name is not None:
        sections.append((stage_name, "".join(stage_lines)))
    if tuple(name for name, _ in sections) != EXPECTED_ACL_STAGES:
        raise SchemaRoleError("runtime_acl_stage_set")
    if preamble or any(not payload.strip() for _, payload in sections):
        raise SchemaRoleError("runtime_acl_stage_set")
    return tuple(sections)


def _fetch_scalar(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        raise SchemaRoleError("missing_scalar")
    return next(iter(row.values())) if isinstance(row, dict) else row[0]


def _migration_owner_metrics(conn: Any) -> dict[str, int]:
    owner = conn.execute(
        "SELECT rolsuper,rolcreaterole FROM pg_roles WHERE rolname=%s",
        (MIGRATION_OWNER_ROLE,),
    ).fetchone()
    if (
        owner is None
        or bool(owner["rolsuper"])
        or not bool(owner["rolcreaterole"])
    ):
        raise SchemaRoleError("migration_owner_role")
    if not bool(_fetch_scalar(
        conn,
        "SELECT database.datdba=%s::regrole "
        "FROM pg_database database WHERE database.datname=current_database()",
        (MIGRATION_OWNER_ROLE,),
    )):
        raise SchemaRoleError("migration_owner_database")
    if not bool(_fetch_scalar(
        conn,
        "SELECT has_schema_privilege(%s,'public','USAGE') "
        "AND has_schema_privilege(%s,'public','CREATE WITH GRANT OPTION')",
        (MIGRATION_OWNER_ROLE, MIGRATION_OWNER_ROLE),
    )):
        raise SchemaRoleError("migration_owner_schema")
    ownership = conn.execute(
        "SELECT "
        "(SELECT COUNT(*) FROM pg_class object "
        "JOIN pg_namespace namespace ON namespace.oid=object.relnamespace "
        "WHERE namespace.nspname='public')::integer AS relation_count,"
        "(SELECT COUNT(*) FROM pg_proc object "
        "JOIN pg_namespace namespace ON namespace.oid=object.pronamespace "
        "WHERE namespace.nspname='public')::integer AS function_count,"
        "((SELECT COUNT(*) FROM pg_class object "
        "JOIN pg_namespace namespace ON namespace.oid=object.relnamespace "
        "WHERE namespace.nspname='public' "
        "AND object.relowner<>%s::regrole) + "
        "(SELECT COUNT(*) FROM pg_proc object "
        "JOIN pg_namespace namespace ON namespace.oid=object.pronamespace "
        "WHERE namespace.nspname='public' "
        "AND object.proowner<>%s::regrole))::integer AS mismatch_count",
        (MIGRATION_OWNER_ROLE, MIGRATION_OWNER_ROLE),
    ).fetchone()
    if ownership is None or int(ownership["mismatch_count"]):
        raise SchemaRoleError("migration_owner_ownership")
    return {
        "migration_owner_relation_count": int(ownership["relation_count"]),
        "migration_owner_function_count": int(ownership["function_count"]),
        "migration_owner_mismatch_count": 0,
    }


def _activate_migration_owner(conn: Any) -> dict[str, int]:
    identity = conn.execute(
        "SELECT session_user AS session_name,current_user AS current_name"
    ).fetchone()
    if (
        identity is None
        or str(identity["session_name"]) in RUNTIME_ROLES
    ):
        raise SchemaRoleError("migration_executor_identity")
    if str(identity["current_name"]) != MIGRATION_OWNER_ROLE:
        conn.execute(f"SET LOCAL ROLE {MIGRATION_OWNER_ROLE}")
    if not bool(_fetch_scalar(
        conn,
        "SELECT current_user=%s AND current_role=%s "
        "AND session_user::text <> ALL(%s::text[])",
        (
            MIGRATION_OWNER_ROLE,
            MIGRATION_OWNER_ROLE,
            list(RUNTIME_ROLES),
        ),
    )):
        raise SchemaRoleError("migration_owner_activation")
    metrics = _migration_owner_metrics(conn)
    executor_owned_objects = int(_fetch_scalar(
        conn,
        "SELECT CASE WHEN session_user=current_user THEN 0 ELSE ("
        "(SELECT COUNT(*) FROM pg_class object "
        "JOIN pg_namespace namespace ON namespace.oid=object.relnamespace "
        "WHERE namespace.nspname='public' "
        "AND object.relowner=session_user::regrole) + "
        "(SELECT COUNT(*) FROM pg_proc object "
        "JOIN pg_namespace namespace ON namespace.oid=object.pronamespace "
        "WHERE namespace.nspname='public' "
        "AND object.proowner=session_user::regrole)) END",
    ))
    if executor_owned_objects:
        raise SchemaRoleError("migration_executor_ownership")
    return {
        **metrics,
        "executor_owned_object_count": executor_owned_objects,
    }


def _prepare_migration_ledger(conn: Any) -> None:
    """Upgrade the legacy 0001-0008 ledger before selecting its hashes."""
    conn.execute(
        "ALTER TABLE schema_migrations "
        "ADD COLUMN IF NOT EXISTS sha256 TEXT"
    )
    conn.execute(
        f"""
        DO $ledger$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'schema_migrations'::regclass
                  AND conname = '{MIGRATION_LEDGER_CONSTRAINT}'
            ) THEN
                ALTER TABLE schema_migrations
                    ADD CONSTRAINT {MIGRATION_LEDGER_CONSTRAINT}
                    CHECK (sha256 ~ '^[0-9a-f]{{64}}$');
            END IF;
        END
        $ledger$;
        """
    )


def _expected_column(
    role: str,
    table: str,
    column: str,
    privilege: str,
) -> bool:
    table_privileges = set(ROLE_TABLE_PRIVILEGES.get(role, {}).get(table, ()))
    if privilege in table_privileges:
        return True
    if privilege == "SELECT":
        scoped = SCOPED_SELECT
    elif privilege == "UPDATE":
        scoped = SCOPED_UPDATE
    else:
        return False
    return column in scoped.get((role, table), set())


def _acl_matrix_metrics(
    conn: Any,
    *,
    roles: tuple[str, ...],
    tables: tuple[str, ...],
    sequences: tuple[str, ...],
) -> dict[str, int]:
    """Validate table/column/sequence ACLs in one set-based query."""
    columns = conn.execute(
        "SELECT table_name,column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name = ANY(%s) "
        "ORDER BY table_name,ordinal_position",
        (list(tables),),
    ).fetchall()
    expected_table = [
        (role, table, privilege)
        for role in roles
        for table, privileges in ROLE_TABLE_PRIVILEGES.get(role, {}).items()
        for privilege in privileges
        if table in tables
    ]
    expected_column = [
        (role, str(row["table_name"]), str(row["column_name"]), privilege)
        for role in roles
        for row in columns
        for privilege in COLUMN_PRIVILEGES
        if _expected_column(
            role,
            str(row["table_name"]),
            str(row["column_name"]),
            privilege,
        )
    ]
    expected_sequence = [
        (role, sequence, privilege)
        for role in roles
        for sequence in sequences
        for privilege in SEQUENCE_PRIVILEGES
        if (
            privilege == "USAGE"
            and sequence in ROLE_SEQUENCES.get(role, set())
        )
    ]

    def _items(
        rows: list[tuple[str, ...]],
        index: int,
    ) -> list[str]:
        return [row[index] for row in rows]

    row = conn.execute(
        """
        WITH
        expected_table(role_name,object_name,privilege_type) AS (
            SELECT * FROM unnest(%s::text[],%s::text[],%s::text[])
        ),
        table_matrix AS (
            SELECT
                role_name,object_name,privilege_type,
                expected_table.role_name IS NOT NULL AS expected,
                has_table_privilege(
                    role_name,
                    format('%%I.%%I','public',object_name),
                    privilege_type
                ) AS actual,
                has_table_privilege(
                    role_name,
                    format('%%I.%%I','public',object_name),
                    privilege_type || ' WITH GRANT OPTION'
                ) AS grantable
            FROM unnest(%s::text[]) AS role_name
            CROSS JOIN unnest(%s::text[]) AS object_name
            CROSS JOIN unnest(%s::text[]) AS privilege_type
            LEFT JOIN expected_table
                USING(role_name,object_name,privilege_type)
        ),
        expected_column(
            role_name,object_name,column_name,privilege_type
        ) AS (
            SELECT * FROM unnest(
                %s::text[],%s::text[],%s::text[],%s::text[]
            )
        ),
        column_inventory(object_name,column_name) AS (
            SELECT * FROM unnest(%s::text[],%s::text[])
        ),
        column_matrix AS (
            SELECT
                role_name,object_name,column_name,privilege_type,
                expected_column.role_name IS NOT NULL AS expected,
                has_column_privilege(
                    role_name,
                    format('%%I.%%I','public',object_name),
                    column_name,
                    privilege_type
                ) AS actual,
                has_column_privilege(
                    role_name,
                    format('%%I.%%I','public',object_name),
                    column_name,
                    privilege_type || ' WITH GRANT OPTION'
                ) AS grantable
            FROM unnest(%s::text[]) AS role_name
            CROSS JOIN column_inventory
            CROSS JOIN unnest(%s::text[]) AS privilege_type
            LEFT JOIN expected_column
                USING(role_name,object_name,column_name,privilege_type)
        ),
        expected_sequence(role_name,object_name,privilege_type) AS (
            SELECT * FROM unnest(%s::text[],%s::text[],%s::text[])
        ),
        sequence_matrix AS (
            SELECT
                role_name,object_name,privilege_type,
                expected_sequence.role_name IS NOT NULL AS expected,
                has_sequence_privilege(
                    role_name,
                    format('%%I.%%I','public',object_name),
                    privilege_type
                ) AS actual,
                has_sequence_privilege(
                    role_name,
                    format('%%I.%%I','public',object_name),
                    privilege_type || ' WITH GRANT OPTION'
                ) AS grantable
            FROM unnest(%s::text[]) AS role_name
            CROSS JOIN unnest(%s::text[]) AS object_name
            CROSS JOIN unnest(%s::text[]) AS privilege_type
            LEFT JOIN expected_sequence
                USING(role_name,object_name,privilege_type)
        )
        SELECT
            (SELECT COUNT(*) FROM table_matrix)::integer
                AS table_checks,
            (SELECT COUNT(*) FROM table_matrix
             WHERE actual IS DISTINCT FROM expected)::integer
                AS table_mismatches,
            (SELECT COUNT(*) FROM table_matrix WHERE actual)::integer
                AS table_positive,
            (SELECT COUNT(*) FROM table_matrix WHERE grantable)::integer
                AS table_grantable,
            (SELECT COUNT(*) FROM column_matrix)::integer
                AS column_checks,
            (SELECT COUNT(*) FROM column_matrix
             WHERE actual IS DISTINCT FROM expected)::integer
                AS column_mismatches,
            (SELECT COUNT(*) FROM column_matrix WHERE actual)::integer
                AS column_positive,
            (SELECT COUNT(*) FROM column_matrix WHERE grantable)::integer
                AS column_grantable,
            (SELECT COUNT(*) FROM sequence_matrix)::integer
                AS sequence_checks,
            (SELECT COUNT(*) FROM sequence_matrix
             WHERE actual IS DISTINCT FROM expected)::integer
                AS sequence_mismatches,
            (SELECT COUNT(*) FROM sequence_matrix WHERE actual)::integer
                AS sequence_positive,
            (SELECT COUNT(*) FROM sequence_matrix WHERE grantable)::integer
                AS sequence_grantable
        """,
        (
            _items(expected_table, 0),
            _items(expected_table, 1),
            _items(expected_table, 2),
            list(roles),
            list(tables),
            list(TABLE_PRIVILEGES),
            _items(expected_column, 0),
            _items(expected_column, 1),
            _items(expected_column, 2),
            _items(expected_column, 3),
            [str(column["table_name"]) for column in columns],
            [str(column["column_name"]) for column in columns],
            list(roles),
            list(COLUMN_PRIVILEGES),
            _items(expected_sequence, 0),
            _items(expected_sequence, 1),
            _items(expected_sequence, 2),
            list(roles),
            list(sequences),
            list(SEQUENCE_PRIVILEGES),
        ),
    ).fetchone()
    if row is None:
        raise SchemaRoleError("acl_matrix_shape")
    metrics = {key: int(value) for key, value in row.items()}
    if (
        metrics["table_mismatches"]
        or metrics["table_grantable"]
        or metrics["column_mismatches"]
        or metrics["column_grantable"]
        or metrics["sequence_mismatches"]
        or metrics["sequence_grantable"]
    ):
        raise SchemaRoleError("acl_matrix")
    return metrics


def _accepted_role_risk_state(
    conn: Any,
    *,
    tables: tuple[str, ...],
    sequences: tuple[str, ...],
) -> dict[str, int | str]:
    if not bool(_fetch_scalar(
        conn,
        "SELECT session_user <> 'noteai_xhs' "
        "AND current_user <> 'noteai_xhs'",
    )):
        raise SchemaRoleError("migration_executor_identity")

    membership_rows = conn.execute(
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
        (list(RUNTIME_ROLES), list(RUNTIME_ROLES)),
    ).fetchall()
    present_new_roles = {
        str(row["rolname"])
        for row in conn.execute(
            "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)",
            (list(NEW_RUNTIME_ROLES),),
        ).fetchall()
    }
    expected_memberships = {("noteai_xhs", MIGRATION_OWNER_ROLE)}
    expected_memberships.update(
        (role, MIGRATION_OWNER_ROLE) for role in present_new_roles
    )
    observed_memberships = {
        (str(row["granted_name"]), str(row["member_name"]))
        for row in membership_rows
    }
    if (
        observed_memberships != expected_memberships
        or len(membership_rows) != len(expected_memberships)
        or any(
            not bool(row["admin_option"])
            or row["inherit_option"] is not False
            or row["set_option"] is not False
            for row in membership_rows
        )
    ):
        raise SchemaRoleError("accepted_role_membership")

    app_incoming_memberships = int(_fetch_scalar(
        conn,
        "SELECT COUNT(*) FROM pg_auth_members membership "
        "JOIN pg_roles member ON member.oid=membership.member "
        "WHERE member.rolname='noteai_app'",
    ))
    if app_incoming_memberships:
        raise SchemaRoleError("accepted_app_inheritance")
    app_high_privilege_inheritance = int(_fetch_scalar(
        conn,
        "SELECT COUNT(*) FROM pg_roles role "
        "WHERE role.rolname <> 'noteai_app' "
        "AND pg_has_role('noteai_app',role.oid,'USAGE') "
        "AND (role.rolsuper OR role.rolcreaterole OR role.rolcreatedb "
        "OR role.rolreplication OR role.rolbypassrls)",
    ))
    if app_high_privilege_inheritance:
        raise SchemaRoleError("accepted_app_inheritance")

    xhs_role = conn.execute(
        "SELECT rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,"
        "rolreplication,rolbypassrls FROM pg_roles "
        "WHERE rolname='noteai_xhs'"
    ).fetchone()
    if xhs_role is None or any(
        bool(xhs_role[key])
        for key in (
            "rolsuper", "rolinherit", "rolcreaterole", "rolcreatedb",
            "rolreplication", "rolbypassrls",
        )
    ):
        raise SchemaRoleError("accepted_xhs_effective_privileges")
    if not bool(xhs_role["rolcanlogin"]):
        raise SchemaRoleError("accepted_xhs_effective_privileges")

    if not bool(_fetch_scalar(
        conn,
        "SELECT has_database_privilege("
        "'noteai_xhs',current_database(),'CONNECT')",
    )):
        raise SchemaRoleError("accepted_xhs_effective_privileges")
    for privilege in ("CREATE", "TEMP"):
        if bool(_fetch_scalar(
            conn,
            "SELECT has_database_privilege("
            "'noteai_xhs',current_database(),%s)",
            (privilege,),
        )):
            raise SchemaRoleError("accepted_xhs_effective_privileges")
        if bool(_fetch_scalar(
            conn,
            "SELECT has_database_privilege("
            "'noteai_xhs',current_database(),%s)",
            (f"{privilege} WITH GRANT OPTION",),
        )):
            raise SchemaRoleError("accepted_xhs_effective_privileges")
    if bool(_fetch_scalar(
        conn,
        "SELECT has_database_privilege("
        "'noteai_xhs',current_database(),'CONNECT WITH GRANT OPTION')",
    )):
        raise SchemaRoleError("accepted_xhs_effective_privileges")
    if not bool(_fetch_scalar(
        conn,
        "SELECT has_schema_privilege('noteai_xhs','public','USAGE')",
    )) or bool(_fetch_scalar(
        conn,
        "SELECT has_schema_privilege('noteai_xhs','public','CREATE')",
    )):
        raise SchemaRoleError("accepted_xhs_effective_privileges")
    for privilege in ("USAGE", "CREATE"):
        if bool(_fetch_scalar(
            conn,
            "SELECT has_schema_privilege("
            "'noteai_xhs','public',%s)",
            (f"{privilege} WITH GRANT OPTION",),
        )):
            raise SchemaRoleError("accepted_xhs_effective_privileges")

    acl_metrics = _acl_matrix_metrics(
        conn,
        roles=("noteai_xhs",),
        tables=tables,
        sequences=sequences,
    )
    public_function_count = int(_fetch_scalar(
        conn,
        "SELECT COUNT(*) FROM pg_proc function "
        "JOIN pg_namespace namespace "
        "ON namespace.oid=function.pronamespace "
        "WHERE namespace.nspname='public'",
    ))
    public_function_execute_count = int(_fetch_scalar(
        conn,
        "SELECT COUNT(*) FROM pg_proc function "
        "JOIN pg_namespace namespace "
        "ON namespace.oid=function.pronamespace "
        "WHERE namespace.nspname='public' "
        "AND has_function_privilege("
        "'noteai_xhs',function.oid,'EXECUTE')",
    ))
    public_function_grantable_count = int(_fetch_scalar(
        conn,
        "SELECT COUNT(*) FROM pg_proc function "
        "JOIN pg_namespace namespace "
        "ON namespace.oid=function.pronamespace "
        "WHERE namespace.nspname='public' "
        "AND has_function_privilege("
        "'noteai_xhs',function.oid,'EXECUTE WITH GRANT OPTION')",
    ))
    if public_function_execute_count or public_function_grantable_count:
        raise SchemaRoleError("accepted_xhs_effective_privileges")
    default_acl_entry_count = int(_fetch_scalar(
        conn,
        "SELECT COUNT(*) FROM pg_default_acl default_acl "
        "CROSS JOIN LATERAL aclexplode(default_acl.defaclacl) exploded "
        "WHERE exploded.grantee='noteai_xhs'::regrole",
    ))
    if default_acl_entry_count:
        raise SchemaRoleError("accepted_xhs_effective_privileges")

    if int(_fetch_scalar(
        conn,
        "SELECT ("
        "(SELECT COUNT(*) FROM pg_class object "
        "WHERE object.relowner='noteai_xhs'::regrole) + "
        "(SELECT COUNT(*) FROM pg_namespace object "
        "WHERE object.nspowner='noteai_xhs'::regrole) + "
        "(SELECT COUNT(*) FROM pg_proc object "
        "WHERE object.proowner='noteai_xhs'::regrole))",
    )):
        raise SchemaRoleError("accepted_xhs_effective_privileges")

    return {
        "profile": ACCEPTED_ROLE_RISK_PROFILE,
        "accepted_risk_count": len(ACCEPTED_ROLE_RISK_IDS),
        "accepted_attribute_count": 1,
        "accepted_membership_count": 1,
        "management_membership_count": len(present_new_roles),
        "unexpected_attribute_count": 0,
        "unexpected_membership_count": 0,
        "app_incoming_membership_count": app_incoming_memberships,
        "app_high_privilege_inheritance_count": (
            app_high_privilege_inheritance
        ),
        "xhs_effective_table_privilege_count": (
            acl_metrics["table_positive"]
        ),
        "xhs_table_privilege_checks": acl_metrics["table_checks"],
        "xhs_effective_column_privilege_count": (
            acl_metrics["column_positive"]
        ),
        "xhs_column_privilege_checks": acl_metrics["column_checks"],
        "xhs_effective_sequence_privilege_count": (
            acl_metrics["sequence_positive"]
        ),
        "xhs_sequence_privilege_checks": acl_metrics["sequence_checks"],
        "xhs_public_function_execute_count": public_function_execute_count,
        "xhs_default_acl_entry_count": default_acl_entry_count,
    }


def validate_contract(conn: Any, *, expect_login: bool = False) -> dict[str, int]:
    migration_payloads = _migration_payloads()
    ledger_sha_column = conn.execute(
        "SELECT data_type,is_nullable "
        "FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='schema_migrations' "
        "AND column_name='sha256'"
    ).fetchone()
    if (
        ledger_sha_column is None
        or ledger_sha_column["data_type"] != "text"
        or ledger_sha_column["is_nullable"] != "NO"
    ):
        raise SchemaRoleError("migration_ledger_contract")
    if not _fetch_scalar(
        conn,
        "SELECT EXISTS ("
        "SELECT 1 FROM pg_constraint "
        "WHERE conrelid='schema_migrations'::regclass AND conname=%s)",
        (MIGRATION_LEDGER_CONSTRAINT,),
    ):
        raise SchemaRoleError("migration_ledger_contract")
    ledger_rows = conn.execute(
        "SELECT version,sha256 FROM schema_migrations ORDER BY version"
    ).fetchall()
    if tuple(str(row["version"]).split("_", 1)[0] for row in ledger_rows) != EXPECTED_VERSIONS:
        raise SchemaRoleError("migration_versions")
    for row in ledger_rows:
        version = str(row["version"]).split("_", 1)[0]
        if str(row["sha256"]) != migration_payloads[version][1]:
            raise SchemaRoleError("migration_drift")

    tables = tuple(
        row["table_name"]
        for row in conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_type='BASE TABLE' "
            "ORDER BY table_name"
        ).fetchall()
    )
    if tables != EXPECTED_TABLES:
        raise SchemaRoleError("table_inventory")
    sequences = tuple(
        row["sequence_name"]
        for row in conn.execute(
            "SELECT sequence_name FROM information_schema.sequences "
            "WHERE sequence_schema='public' ORDER BY sequence_name"
        ).fetchall()
    )
    if sequences != tuple(sorted(EXPECTED_PUBLIC_SEQUENCES)):
        raise SchemaRoleError("sequence_inventory")

    migration_owner = _migration_owner_metrics(conn)
    accepted_role_risks = _accepted_role_risk_state(
        conn,
        tables=tables,
        sequences=sequences,
    )
    role_rows = conn.execute(
        "SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,"
        "rolcanlogin,rolreplication,rolbypassrls FROM pg_roles "
        "WHERE rolname = ANY(%s) ORDER BY rolname",
        (list(RUNTIME_ROLES),),
    ).fetchall()
    if {row["rolname"] for row in role_rows} != set(RUNTIME_ROLES):
        raise SchemaRoleError("role_inventory")
    for row in role_rows:
        prohibited = (
            "rolsuper", "rolcreaterole", "rolcreatedb",
            "rolreplication", "rolbypassrls",
        )
        if any(row[key] for key in prohibited):
            raise SchemaRoleError("role_elevation")
        if row["rolname"] == "noteai_app":
            if not bool(row["rolinherit"]):
                raise SchemaRoleError("accepted_app_inheritance")
        elif bool(row["rolinherit"]):
            raise SchemaRoleError("role_elevation")
        if row["rolname"] in NEW_RUNTIME_ROLES:
            if bool(row["rolcanlogin"]) is not bool(expect_login):
                raise SchemaRoleError("role_login_state")

    if _fetch_scalar(
        conn,
        "SELECT ("
        "(SELECT COUNT(*) FROM pg_class object JOIN pg_roles role "
        "ON role.oid=object.relowner WHERE role.rolname = ANY(%s)) + "
        "(SELECT COUNT(*) FROM pg_namespace object JOIN pg_roles role "
        "ON role.oid=object.nspowner WHERE role.rolname = ANY(%s)) + "
        "(SELECT COUNT(*) FROM pg_proc object JOIN pg_roles role "
        "ON role.oid=object.proowner WHERE role.rolname = ANY(%s)))",
        (list(RUNTIME_ROLES), list(RUNTIME_ROLES), list(RUNTIME_ROLES)),
    ):
        raise SchemaRoleError("role_ownership")

    for role in RUNTIME_ROLES:
        if not _fetch_scalar(
            conn,
            "SELECT has_database_privilege(%s,current_database(),'CONNECT')",
            (role,),
        ):
            raise SchemaRoleError("database_connect")
        for privilege in ("CREATE", "TEMP"):
            if _fetch_scalar(
                conn,
                "SELECT has_database_privilege(%s,current_database(),%s)",
                (role, privilege),
            ):
                raise SchemaRoleError("database_capability")
            if _fetch_scalar(
                conn,
                "SELECT has_database_privilege(%s,current_database(),%s)",
                (role, f"{privilege} WITH GRANT OPTION"),
            ):
                raise SchemaRoleError("database_grant_option")
        if _fetch_scalar(
            conn,
            "SELECT has_database_privilege("
            "%s,current_database(),'CONNECT WITH GRANT OPTION')",
            (role,),
        ):
            raise SchemaRoleError("database_grant_option")
        if not _fetch_scalar(
            conn,
            "SELECT has_schema_privilege(%s,'public','USAGE')",
            (role,),
        ) or _fetch_scalar(
            conn,
            "SELECT has_schema_privilege(%s,'public','CREATE')",
            (role,),
        ):
            raise SchemaRoleError("schema_capability")
        for privilege in ("USAGE", "CREATE"):
            if _fetch_scalar(
                conn,
                "SELECT has_schema_privilege(%s,'public',%s)",
                (role, f"{privilege} WITH GRANT OPTION"),
            ):
                raise SchemaRoleError("schema_grant_option")

    acl_metrics = _acl_matrix_metrics(
        conn,
        roles=RUNTIME_ROLES,
        tables=tables,
        sequences=sequences,
    )

    for role in RUNTIME_ROLES:
        for signature in TRIGGER_FUNCTIONS:
            if _fetch_scalar(
                conn,
                "SELECT has_function_privilege(%s,%s,'EXECUTE')",
                (role, signature),
            ):
                raise SchemaRoleError("trigger_function_execute")
            if _fetch_scalar(
                conn,
                "SELECT has_function_privilege("
                "%s,%s,'EXECUTE WITH GRANT OPTION')",
                (role, signature),
            ):
                raise SchemaRoleError("function_grant_option")
    for role in (
        "noteai_app", "noteai_ai_worker", "noteai_payment", "noteai_xhs",
        "noteai_xhs_tracking", "noteai_xhs_trends",
    ):
        for signature in ADVISORY_FUNCTIONS:
            if not _fetch_scalar(
                conn,
                "SELECT has_function_privilege(%s,%s,'EXECUTE')",
                (role, signature),
            ):
                raise SchemaRoleError("advisory_function_execute")
            if _fetch_scalar(
                conn,
                "SELECT has_function_privilege("
                "%s,%s,'EXECUTE WITH GRANT OPTION')",
                (role, signature),
            ):
                raise SchemaRoleError("function_grant_option")

    default_acl_entries = int(_fetch_scalar(
        conn,
        "SELECT COUNT(*) FROM pg_default_acl default_acl "
        "CROSS JOIN LATERAL aclexplode(default_acl.defaclacl) exploded "
        "JOIN pg_roles grantee ON grantee.oid=exploded.grantee "
        "WHERE grantee.rolname = ANY(%s)",
        (list(RUNTIME_ROLES),),
    ))
    if default_acl_entries:
        raise SchemaRoleError("default_acl")

    if int(_fetch_scalar(conn, "SELECT COUNT(*) FROM content_retention")) != 0:
        raise SchemaRoleError("unexpected_retention_backfill")
    if int(_fetch_scalar(
        conn,
        "SELECT COUNT(*) FROM xhs_trends_service_state "
        "WHERE service_key='market_timing' "
        "AND status='idle' "
        "AND active_run_id IS NULL "
        "AND lease_token_hash IS NULL "
        "AND lease_fence=0 "
        "AND lease_expires_at IS NULL "
        "AND session_blocked IS FALSE "
        "AND session_block_reason='' "
        "AND session_blocked_at IS NULL "
        "AND updated_at IS NOT NULL",
    )) != 1 or int(_fetch_scalar(
        conn,
        "SELECT COUNT(*) FROM xhs_trends_service_state",
    )) != 1:
        raise SchemaRoleError("trends_seed")
    if int(_fetch_scalar(
        conn,
        "SELECT COUNT(*) FROM ai_dispatch_state "
        "WHERE service_key='durable_ai' "
        "AND priority_streak=0 "
        "AND updated_at='1970-01-01T00:00:00+00:00'",
    )) != 1 or int(_fetch_scalar(
        conn,
        "SELECT COUNT(*) FROM ai_dispatch_state",
    )) != 1:
        raise SchemaRoleError("dispatcher_seed")

    return {
        "migration_count": len(ledger_rows),
        "runtime_role_count": len(role_rows),
        "table_count": len(tables),
        "sequence_count": len(sequences),
        "table_privilege_checks": acl_metrics["table_checks"],
        "table_grant_option_count": acl_metrics["table_grantable"],
        "column_privilege_checks": acl_metrics["column_checks"],
        "column_grant_option_count": acl_metrics["column_grantable"],
        "sequence_privilege_checks": acl_metrics["sequence_checks"],
        "sequence_grant_option_count": acl_metrics["sequence_grantable"],
        "default_acl_entry_count": default_acl_entries,
        "schema_seed_rows": 2,
        "retention_backfill_rows": 0,
        "accepted_role_risk_count": int(
            accepted_role_risks["accepted_risk_count"]
        ),
        "accepted_role_attribute_count": int(
            accepted_role_risks["accepted_attribute_count"]
        ),
        "accepted_role_membership_count": int(
            accepted_role_risks["accepted_membership_count"]
        ),
        "runtime_management_membership_count": int(
            accepted_role_risks["management_membership_count"]
        ),
        "unexpected_role_attribute_count": int(
            accepted_role_risks["unexpected_attribute_count"]
        ),
        "unexpected_role_membership_count": int(
            accepted_role_risks["unexpected_membership_count"]
        ),
        "app_high_privilege_inheritance_count": int(
            accepted_role_risks["app_high_privilege_inheritance_count"]
        ),
        **migration_owner,
    }


def apply_contract(conn: Any) -> dict[str, Any]:
    """Apply atomically while converting unexpected failures to fixed stages."""
    stage = {"name": "local_source"}
    try:
        return _apply_contract(conn, stage=stage)
    except SchemaRoleError:
        raise
    except BaseException as exc:
        stage_name = stage["name"]
        if stage_name not in APPLY_FAILURE_STAGES:
            stage_name = "result_build"
        raise SchemaRoleError(f"apply_{stage_name}_failed") from exc


def _apply_contract(
    conn: Any,
    *,
    stage: dict[str, str],
) -> dict[str, Any]:
    payloads = _migration_payloads()
    migration_paths = sorted(MIGRATION_DIR.glob("*.sql"))
    expected_ledger_names = tuple(path.name for path in migration_paths)
    legacy_ledger_names = expected_ledger_names[:8]
    acl_payloads = _runtime_acl_payloads()
    stage["name"] = "transaction_begin"
    with conn.transaction():
        stage["name"] = "session_controls"
        conn.execute("SET LOCAL statement_timeout='120s'")
        conn.execute("SET LOCAL lock_timeout='5s'")
        conn.execute("SET LOCAL idle_in_transaction_session_timeout='180s'")
        stage["name"] = "migration_owner_activation"
        _activate_migration_owner(conn)
        stage["name"] = "advisory_lock"
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext('noteai_schema_migrations'))"
        )
        stage["name"] = "ledger_inventory"
        ledger_names = tuple(
            str(row["version"])
            for row in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        )
        if ledger_names not in (legacy_ledger_names, expected_ledger_names):
            raise SchemaRoleError("precondition_migration_versions")
        stage["name"] = "schema_inventory"
        prewrite_tables = tuple(
            row["table_name"]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE' "
                "ORDER BY table_name"
            ).fetchall()
        )
        prewrite_sequences = tuple(
            row["sequence_name"]
            for row in conn.execute(
                "SELECT sequence_name FROM information_schema.sequences "
                "WHERE sequence_schema='public' ORDER BY sequence_name"
            ).fetchall()
        )
        stage["name"] = "role_preconditions"
        if ledger_names == legacy_ledger_names:
            if prewrite_tables != EXPECTED_PUBLIC_TABLES:
                raise SchemaRoleError("precondition_table_inventory")
            if prewrite_sequences != EXPECTED_PUBLIC_SEQUENCES:
                raise SchemaRoleError("precondition_sequence_inventory")
            if int(_fetch_scalar(
                conn,
                "SELECT COUNT(*) FROM pg_roles "
                "WHERE rolname = ANY(%s)",
                (list(NEW_RUNTIME_ROLES),),
            )):
                raise SchemaRoleError("precondition_new_roles")
            if int(_fetch_scalar(
                conn,
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema='public' "
                "AND table_name = ANY(%s)",
                (list(NEW_TABLES),),
            )):
                raise SchemaRoleError("precondition_new_tables")
            if int(_fetch_scalar(
                conn,
                "SELECT (SELECT COUNT(*) FROM notes) + "
                "(SELECT COUNT(*) FROM saved_diagnoses)",
            )):
                raise SchemaRoleError("precondition_retention_backfill")
        else:
            if prewrite_tables != EXPECTED_TABLES:
                raise SchemaRoleError("precondition_table_inventory")
            if prewrite_sequences != tuple(sorted(EXPECTED_PUBLIC_SEQUENCES)):
                raise SchemaRoleError("precondition_sequence_inventory")
        stage["name"] = "accepted_role_risk"
        _accepted_role_risk_state(
            conn,
            tables=prewrite_tables,
            sequences=prewrite_sequences,
        )
        stage["name"] = "ledger_contract"
        ledger_sha_column = conn.execute(
            "SELECT data_type,is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema='public' "
            "AND table_name='schema_migrations' "
            "AND column_name='sha256'"
        ).fetchone()
        ledger_constraint_count = int(_fetch_scalar(
            conn,
            "SELECT COUNT(*) FROM pg_constraint "
            "WHERE conrelid='schema_migrations'::regclass "
            "AND conname=%s",
            (MIGRATION_LEDGER_CONSTRAINT,),
        ))
        if ledger_names == legacy_ledger_names:
            if ledger_sha_column is not None or ledger_constraint_count:
                raise SchemaRoleError("precondition_legacy_ledger_shape")
            rows = [
                {"version": name, "sha256": None}
                for name in ledger_names
            ]
        else:
            if (
                ledger_sha_column is None
                or ledger_sha_column["data_type"] != "text"
                or ledger_sha_column["is_nullable"] != "NO"
                or ledger_constraint_count != 1
            ):
                raise SchemaRoleError("precondition_migration_ledger_contract")
            rows = conn.execute(
                "SELECT version,sha256 FROM schema_migrations "
                "ORDER BY version"
            ).fetchall()
            for row in rows:
                version = str(row["version"]).split("_", 1)[0]
                if str(row["sha256"]) != payloads[version][1]:
                    raise SchemaRoleError("precondition_migration_drift")

        stage["name"] = "ledger_prepare"
        _prepare_migration_ledger(conn)
        stage["name"] = "legacy_hash_backfill"
        migration_hash_backfills = 0
        for row in rows:
            if row["sha256"] is None:
                version = str(row["version"]).split("_", 1)[0]
                update_result = conn.execute(
                    "UPDATE schema_migrations SET sha256=%s "
                    "WHERE version=%s AND sha256 IS NULL",
                    (payloads[version][1], row["version"]),
                )
                if update_result.rowcount != 1:
                    raise SchemaRoleError("migration_hash_backfill_count")
                migration_hash_backfills += 1
        expected_backfills = 8 if ledger_names == legacy_ledger_names else 0
        if migration_hash_backfills != expected_backfills:
            raise SchemaRoleError("migration_hash_backfill_count")
        conn.execute(
            "ALTER TABLE schema_migrations ALTER COLUMN sha256 SET NOT NULL"
        )
        existing = {
            name.split("_", 1)[0]
            for name in ledger_names
        }
        stage["name"] = "migration_apply"
        applied: list[str] = []
        for path in migration_paths:
            version = path.name.split("_", 1)[0]
            if version in existing:
                continue
            payload, digest = payloads[version]
            conn.execute(payload.decode("utf-8"))
            insert_result = conn.execute(
                "INSERT INTO schema_migrations(version,sha256) VALUES(%s,%s)",
                (path.name, digest),
            )
            if insert_result.rowcount != 1:
                raise SchemaRoleError("migration_ledger_insert_count")
            applied.append(version)
        expected_applied = list(NEW_VERSIONS) if (
            ledger_names == legacy_ledger_names
        ) else []
        if applied != expected_applied:
            raise SchemaRoleError("migration_ledger_insert_count")
        for acl_stage, acl_payload in acl_payloads:
            stage["name"] = f"runtime_acl_{acl_stage}"
            conn.execute(acl_payload)
        stage["name"] = "postcondition_verification"
        final_owner = _activate_migration_owner(conn)
        verification = validate_contract(conn, expect_login=False)
        schema_seed_writes = 2 if applied else 0
        stage["name"] = "transaction_commit"
    stage["name"] = "result_build"
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "verified",
        "transaction_committed": True,
        "applied_versions": applied,
        "database_writes": {
            "migration_ledger_rows": len(applied),
            "migration_ledger_hash_backfills": migration_hash_backfills,
            "schema_seed_rows": schema_seed_writes,
            "retention_backfill_rows": verification["retention_backfill_rows"],
            "existing_business_row_updates": 0,
        },
        "roles": {
            "runtime_role_count": verification["runtime_role_count"],
            "new_roles_login_enabled": 0,
            "privilege_mismatch_count": 0,
            "ownership_count": 0,
            "membership_count": (
                verification["accepted_role_membership_count"]
                + verification["runtime_management_membership_count"]
            ),
            "management_membership_count": (
                verification["runtime_management_membership_count"]
            ),
            "migration_owner_mismatch_count": (
                verification["migration_owner_mismatch_count"]
            ),
            "executor_owned_object_count": (
                final_owner["executor_owned_object_count"]
            ),
            "elevation_count": (
                verification["accepted_role_attribute_count"]
            ),
            "accepted_risk_profile": ACCEPTED_ROLE_RISK_PROFILE,
            "accepted_risk_count": (
                verification["accepted_role_risk_count"]
            ),
            "unexpected_membership_count": (
                verification["unexpected_role_membership_count"]
            ),
            "unexpected_elevation_count": (
                verification["unexpected_role_attribute_count"]
            ),
            "high_privilege_inheritance_count": (
                verification["app_high_privilege_inheritance_count"]
            ),
        },
        "verification": verification,
        "provider_calls": 0,
        "service_changes": 0,
        "public_traffic_requests": 0,
        "secret_values_exposed": 0,
    }


def verify_contract(conn: Any, *, expect_login: bool = False) -> dict[str, Any]:
    with conn.transaction():
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL statement_timeout='60s'")
        conn.execute("SET LOCAL lock_timeout='5s'")
        verification = validate_contract(conn, expect_login=expect_login)
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "verified",
        "read_only": True,
        "verification": verification,
        "provider_calls": 0,
        "service_changes": 0,
        "public_traffic_requests": 0,
        "secret_values_exposed": 0,
    }


def _connect(database_url: str | None = None) -> Any:
    if psycopg is None:
        raise SchemaRoleError("psycopg_unavailable")
    resolved_url = (
        database_url
        if database_url is not None
        else os.environ.get(DATABASE_URL_ENV, "")
    ).strip()
    if not resolved_url:
        raise SchemaRoleError("database_url_missing")
    return psycopg.connect(
        resolved_url,
        row_factory=dict_row,
        connect_timeout=10,
        application_name="noteai_schema_roles_v2",
    )


def main(
    argv: list[str] | None = None,
    *,
    database_url: str | None = None,
    confirmation: str | None = None,
) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--expect-login", action="store_true")
    args = parser.parse_args(argv)
    resolved_confirmation = (
        confirmation
        if confirmation is not None
        else os.environ.get(CONFIRM_ENV)
    )
    if args.apply and resolved_confirmation != TASK_ID:
        print("production_schema_roles=FAIL code=confirmation_missing", file=sys.stderr)
        return 2
    connected = False
    try:
        conn = _connect(database_url)
        connected = True
        try:
            result = (
                apply_contract(conn)
                if args.apply
                else verify_contract(conn, expect_login=args.expect_login)
            )
        finally:
            conn.close()
    except SchemaRoleError as exc:
        print(f"production_schema_roles=FAIL code={exc.code}", file=sys.stderr)
        return 1
    except BaseException:
        code = "execution_failed" if connected else "database_connection_failed"
        print(f"production_schema_roles=FAIL code={code}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
