#!/usr/bin/env python3
"""Collect a sanitized, read-only database fragment for production Gate 0.

The connection string is accepted only through NOTEAI_PREFLIGHT_DATABASE_URL.
The collector forces read-only mode at both session and transaction scope,
returns only migration metadata, predefined role state and aggregate counts,
and never emits exception text or business row values.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable, Iterable, Sequence
from typing import Any

try:
    from tools.production_readonly_preflight_gate import (
        EXPECTED_ROLE_STATE,
        MIGRATION_DIR,
        SOURCE_INFORMATIONAL_AGGREGATES,
        SOURCE_ZERO_AGGREGATES,
        _current_migration_hashes,
    )
except ModuleNotFoundError:
    from production_readonly_preflight_gate import (  # type: ignore[no-redef]
        EXPECTED_ROLE_STATE,
        MIGRATION_DIR,
        SOURCE_INFORMATIONAL_AGGREGATES,
        SOURCE_ZERO_AGGREGATES,
        _current_migration_hashes,
    )


DATABASE_URL_ENV = "NOTEAI_PREFLIGHT_DATABASE_URL"
RUNTIME_ROLES = ("noteai_app", "noteai_admin", "noteai_xhs")
EXPECTED_APPLIED_VERSIONS = tuple(f"{number:04d}" for number in range(1, 9))
EXPECTED_PENDING_VERSIONS = tuple(f"{number:04d}" for number in range(9, 16))
_SHA256 = re.compile(r"[0-9a-f]{64}")
_MIGRATION_VERSION = re.compile(r"(?P<version>[0-9]{4})(?:_|$)")
_RETENTION_CLOCK_PATTERN = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ]"
    r"([01][0-9]|2[0-3]):[0-5][0-9]"
    r"(:[0-5][0-9](\.[0-9]{1,6})?)?"
    r"(Z|[+-]((0[0-9]|1[0-3])(:?[0-5][0-9])?|14(:?00)?))?$"
)
_TRACKING_CLOCK_PATTERN = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    r"([.][0-9]{1,6})?"
    r"(Z|[+-](0[0-9]|1[0-3]):[0-5][0-9]|[+-]14:00)$"
)
EXPECTED_PUBLIC_TABLES = (
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
EXPECTED_PUBLIC_SEQUENCES = (
    "analysis_log_id_seq",
    "crawler_events_id_seq",
    "hot_keywords_id_seq",
    "keyword_snapshots_id_seq",
    "prompt_history_id_seq",
)
TABLE_PRIVILEGES = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
)
SEQUENCE_PRIVILEGES = ("USAGE", "SELECT", "UPDATE")
APP_TABLE_PRIVILEGES = {
    "admin_sessions": ("SELECT", "INSERT", "DELETE"),
    "ai_operation_admissions": ("SELECT", "INSERT"),
    "ai_operation_events": ("SELECT", "INSERT"),
    "ai_operations": ("SELECT", "INSERT", "UPDATE"),
    "ai_provider_attempts": ("SELECT", "INSERT", "UPDATE"),
    "analysis_log": ("INSERT",),
    "chat_sessions": ("SELECT", "INSERT", "UPDATE"),
    "crawler_events": ("SELECT", "INSERT"),
    "credit_transactions": ("SELECT", "INSERT"),
    "credits": ("SELECT", "INSERT", "UPDATE"),
    "growth_records": ("SELECT", "INSERT", "DELETE"),
    "hot_keywords": ("SELECT", "INSERT", "UPDATE"),
    "idempotency_requests": ("SELECT", "INSERT", "UPDATE"),
    "keyword_snapshots": ("SELECT", "INSERT"),
    "managed_prompts": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "model_usage_records": ("SELECT", "INSERT"),
    "notes": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "prompt_history": ("SELECT", "INSERT"),
    "saved_diagnoses": ("SELECT", "INSERT", "DELETE"),
    "subscriptions": ("SELECT", "INSERT", "UPDATE"),
    "system_settings": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "tracked_notes": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "usage_records": ("SELECT", "INSERT", "UPDATE"),
    "user_learn": ("SELECT", "INSERT", "UPDATE"),
    "user_memories": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "user_sessions": ("SELECT", "INSERT", "DELETE"),
    "users": ("SELECT", "INSERT", "UPDATE"),
    "xhs_crawler_health": ("SELECT", "INSERT"),
    "xhs_freshness_ledger": ("SELECT", "INSERT", "UPDATE"),
}
XHS_TABLE_PRIVILEGES = {
    "crawler_events": ("INSERT",),
    "growth_records": ("INSERT",),
    "hot_keywords": ("SELECT", "INSERT", "UPDATE"),
    "keyword_snapshots": ("SELECT", "INSERT"),
    "system_settings": ("SELECT", "INSERT", "UPDATE"),
    "tracked_notes": ("SELECT", "UPDATE"),
    "user_memories": ("SELECT", "INSERT", "DELETE"),
    "xhs_crawler_health": ("SELECT", "INSERT"),
    "xhs_freshness_ledger": ("SELECT", "INSERT", "UPDATE"),
}
EXPECTED_TABLE_PRIVILEGE_ROWS = tuple(
    {"role_name": role, "object_name": table, "privilege_type": privilege}
    for role, matrix in (
        ("noteai_app", APP_TABLE_PRIVILEGES),
        ("noteai_xhs", XHS_TABLE_PRIVILEGES),
    )
    for table, privileges in matrix.items()
    for privilege in privileges
)
EXPECTED_SEQUENCE_PRIVILEGE_ROWS = tuple(
    {"role_name": role, "object_name": sequence, "privilege_type": "USAGE"}
    for role, sequences in (
        ("noteai_app", EXPECTED_PUBLIC_SEQUENCES),
        (
            "noteai_xhs",
            (
                "crawler_events_id_seq",
                "hot_keywords_id_seq",
                "keyword_snapshots_id_seq",
            ),
        ),
    )
    for sequence in sequences
)


class CollectionError(RuntimeError):
    """A sanitized database collection failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _invalid_required_clock(column: str, pattern: str) -> str:
    return (
        f"({column} IS NULL OR btrim({column}) !~ '{pattern}' "
        "OR NOT pg_input_is_valid("
        f"btrim({column}), 'timestamp with time zone'))"
    )


def _invalid_optional_clock(column: str, pattern: str) -> str:
    return (
        f"({column} IS NOT NULL AND (btrim({column}) !~ '{pattern}' "
        "OR NOT pg_input_is_valid("
        f"btrim({column}), 'timestamp with time zone')))"
    )


SOURCE_AGGREGATE_QUERIES: dict[str, str] = {
    "noncanonical_phone_count": """
        SELECT COUNT(*) FROM users
        WHERE phone IS NOT NULL AND phone <> ''
          AND phone !~ '^\\+861[3-9][0-9]{9}$'
    """,
    "duplicate_phone_count": """
        SELECT COUNT(*) FROM (
            SELECT phone FROM users
            WHERE phone IS NOT NULL AND phone <> ''
            GROUP BY phone HAVING COUNT(*) > 1
        ) duplicate_phone_groups
    """,
    "invalid_note_created_at_count": f"""
        SELECT COUNT(*) FROM notes
        WHERE {_invalid_required_clock("created_at", _RETENTION_CLOCK_PATTERN)}
    """,
    "invalid_diagnosis_created_at_count": f"""
        SELECT COUNT(*) FROM saved_diagnoses
        WHERE {_invalid_required_clock("created_at", _RETENTION_CLOCK_PATTERN)}
    """,
    "invalid_subscription_started_at_count": f"""
        SELECT COUNT(*) FROM subscriptions
        WHERE {_invalid_required_clock("started_at", _RETENTION_CLOCK_PATTERN)}
    """,
    "invalid_subscription_expires_at_count": f"""
        SELECT COUNT(*) FROM subscriptions
        WHERE {_invalid_required_clock("expires_at", _RETENTION_CLOCK_PATTERN)}
    """,
    "tracking_noncanonical_identity_count": """
        SELECT COUNT(*) FROM tracked_notes
        WHERE xhs_note_id IS NULL
           OR xhs_note_id !~ '^[0-9a-f]{24}$'
           OR xhs_url <>
              'https://www.xiaohongshu.com/explore/' || xhs_note_id
    """,
    "tracking_duplicate_url_count": """
        SELECT COUNT(*) FROM (
            SELECT user_id, xhs_url FROM tracked_notes
            GROUP BY user_id, xhs_url HAVING COUNT(*) > 1
        ) duplicate_tracking_urls
    """,
    "tracking_duplicate_note_count": """
        SELECT COUNT(*) FROM (
            SELECT user_id, xhs_note_id FROM tracked_notes
            GROUP BY user_id, xhs_note_id HAVING COUNT(*) > 1
        ) duplicate_tracking_notes
    """,
    "tracking_invalid_status_or_metric_count": """
        SELECT COUNT(*) FROM tracked_notes
        WHERE status IS NULL OR status NOT IN (
                'pending', 'checking_24h', 'checking_7d', 'needs_manual',
                'complete', 'failed', 'account_deletion_pending'
              )
           OR COALESCE(likes_24h, 0) NOT BETWEEN 0 AND 2147483647
           OR COALESCE(saves_24h, 0) NOT BETWEEN 0 AND 2147483647
           OR COALESCE(comments_24h, 0) NOT BETWEEN 0 AND 2147483647
           OR COALESCE(likes_7d, 0) NOT BETWEEN 0 AND 2147483647
           OR COALESCE(saves_7d, 0) NOT BETWEEN 0 AND 2147483647
           OR COALESCE(comments_7d, 0) NOT BETWEEN 0 AND 2147483647
           OR COALESCE(views_est, 0) NOT BETWEEN 0 AND 2147483647
           OR attempt_count IS NULL OR attempt_count NOT BETWEEN 0 AND 2
           OR max_attempts IS NULL OR max_attempts NOT BETWEEN 1 AND 2
           OR manual_filled IS NULL OR manual_filled NOT IN (0, 1)
           OR training_eligible IS NULL OR training_eligible NOT IN (0, 1)
           OR (confidence IS NOT NULL AND confidence NOT BETWEEN 0 AND 1)
    """,
    "tracking_invalid_or_unordered_clock_count": f"""
        SELECT COUNT(*) FROM tracked_notes
        WHERE {_invalid_required_clock("submitted_at", _TRACKING_CLOCK_PATTERN)}
           OR {_invalid_optional_clock("published_at", _TRACKING_CLOCK_PATTERN)}
           OR {_invalid_optional_clock("next_check_at", _TRACKING_CLOCK_PATTERN)}
           OR {_invalid_optional_clock("check_24h_at", _TRACKING_CLOCK_PATTERN)}
           OR {_invalid_optional_clock("check_7d_at", _TRACKING_CLOCK_PATTERN)}
           OR {_invalid_optional_clock("last_checked_at", _TRACKING_CLOCK_PATTERN)}
           OR {_invalid_optional_clock("completed_at", _TRACKING_CLOCK_PATTERN)}
           OR CASE
                WHEN check_24h_at IS NOT NULL
                 AND check_7d_at IS NOT NULL
                 AND pg_input_is_valid(
                     btrim(check_24h_at), 'timestamp with time zone')
                 AND pg_input_is_valid(
                     btrim(check_7d_at), 'timestamp with time zone')
                THEN btrim(check_24h_at)::timestamptz >
                     btrim(check_7d_at)::timestamptz
                ELSE FALSE
              END
    """,
    "tracking_incomplete_terminal_count": """
        SELECT COUNT(*) FROM tracked_notes
        WHERE status = 'complete'
          AND (
              completed_at IS NULL OR check_7d_at IS NULL
              OR likes_7d IS NULL OR saves_7d IS NULL
              OR comments_7d IS NULL OR actual_ces IS NULL
          )
    """,
    "tracking_active_legacy_work_count": """
        SELECT COUNT(*) FROM tracked_notes
        WHERE status IN ('pending', 'checking_24h', 'checking_7d')
    """,
    "retention_backfill_candidate_count": """
        SELECT
            (SELECT COUNT(*) FROM notes)
          + (SELECT COUNT(*) FROM saved_diagnoses)
    """,
    "retention_immediate_deadline_count": f"""
        SELECT
            (SELECT COUNT(*) FROM notes content
             WHERE CASE
                 WHEN NOT {_invalid_required_clock("content.created_at", _RETENTION_CLOCK_PATTERN)}
                 THEN btrim(content.created_at)::timestamptz
                      <= CURRENT_TIMESTAMP - INTERVAL '7 days'
                  AND NOT EXISTS (
                      SELECT 1 FROM subscriptions paid_term
                      WHERE paid_term.user_id = content.user_id
                        AND paid_term.tier <> 'free'
                        AND CASE
                            WHEN NOT {_invalid_required_clock("paid_term.started_at", _RETENTION_CLOCK_PATTERN)}
                             AND NOT {_invalid_required_clock("paid_term.expires_at", _RETENTION_CLOCK_PATTERN)}
                            THEN btrim(paid_term.started_at)::timestamptz
                                 <= btrim(content.created_at)::timestamptz
                             AND btrim(paid_term.expires_at)::timestamptz
                                 > btrim(content.created_at)::timestamptz
                            ELSE FALSE
                        END
                  )
                 ELSE FALSE
             END)
          + (SELECT COUNT(*) FROM saved_diagnoses content
             WHERE CASE
                 WHEN NOT {_invalid_required_clock("content.created_at", _RETENTION_CLOCK_PATTERN)}
                 THEN btrim(content.created_at)::timestamptz
                      <= CURRENT_TIMESTAMP - INTERVAL '7 days'
                  AND NOT EXISTS (
                      SELECT 1 FROM subscriptions paid_term
                      WHERE paid_term.user_id = content.user_id
                        AND paid_term.tier <> 'free'
                        AND CASE
                            WHEN NOT {_invalid_required_clock("paid_term.started_at", _RETENTION_CLOCK_PATTERN)}
                             AND NOT {_invalid_required_clock("paid_term.expires_at", _RETENTION_CLOCK_PATTERN)}
                            THEN btrim(paid_term.started_at)::timestamptz
                                 <= btrim(content.created_at)::timestamptz
                             AND btrim(paid_term.expires_at)::timestamptz
                                 > btrim(content.created_at)::timestamptz
                            ELSE FALSE
                        END
                  )
                 ELSE FALSE
             END)
    """,
}

MIGRATION_QUERY = """
    SELECT version, sha256
    FROM public.schema_migrations
    ORDER BY version
"""
ROLE_QUERY = """
    SELECT rolname, rolsuper, rolinherit, rolcreaterole, rolcreatedb,
           rolcanlogin, rolreplication, rolbypassrls
    FROM pg_catalog.pg_roles
    WHERE rolname = ANY(%s)
    ORDER BY rolname
"""
OWNER_COUNT_QUERY = """
    SELECT
        (SELECT COUNT(*) FROM pg_catalog.pg_class relation
         JOIN pg_catalog.pg_roles owner
           ON owner.oid = relation.relowner
         WHERE owner.rolname = ANY(%s))
      + (SELECT COUNT(*) FROM pg_catalog.pg_namespace namespace
         JOIN pg_catalog.pg_roles owner
           ON owner.oid = namespace.nspowner
         WHERE owner.rolname = ANY(%s))
      + (SELECT COUNT(*) FROM pg_catalog.pg_proc procedure
         JOIN pg_catalog.pg_roles owner
           ON owner.oid = procedure.proowner
         WHERE owner.rolname = ANY(%s))
"""
MEMBERSHIP_COUNT_QUERY = """
    SELECT COUNT(*)
    FROM pg_catalog.pg_auth_members membership
    JOIN pg_catalog.pg_roles member_role
      ON member_role.oid = membership.member
    JOIN pg_catalog.pg_roles granted_role
      ON granted_role.oid = membership.roleid
    WHERE member_role.rolname = ANY(%s)
       OR granted_role.rolname = ANY(%s)
"""
DATABASE_CAPABILITY_COUNT_QUERY = """
    SELECT COUNT(*)
    FROM pg_catalog.pg_roles role
    CROSS JOIN LATERAL (
        VALUES
            (has_database_privilege(
                role.rolname, current_database(), 'CREATE')),
            (has_database_privilege(
                role.rolname, current_database(), 'TEMP'))
    ) capability(allowed)
    WHERE role.rolname = ANY(%s) AND capability.allowed
"""
SCHEMA_CAPABILITY_COUNT_QUERY = """
    SELECT COUNT(*)
    FROM pg_catalog.pg_roles role
    CROSS JOIN LATERAL (
        VALUES
            (has_schema_privilege(role.rolname, 'public', 'CREATE')),
            (has_schema_privilege(role.rolname, 'pg_catalog', 'CREATE'))
    ) capability(allowed)
    WHERE role.rolname = ANY(%s) AND capability.allowed
"""
MIGRATION_PRIVILEGE_COUNT_QUERY = """
    SELECT COUNT(*)
    FROM pg_catalog.pg_roles role
    CROSS JOIN LATERAL (
        VALUES
            (has_table_privilege(
                role.rolname, 'public.schema_migrations', 'SELECT')),
            (has_table_privilege(
                role.rolname, 'public.schema_migrations', 'INSERT')),
            (has_table_privilege(
                role.rolname, 'public.schema_migrations', 'UPDATE')),
            (has_table_privilege(
                role.rolname, 'public.schema_migrations', 'DELETE')),
            (has_table_privilege(
                role.rolname, 'public.schema_migrations', 'TRUNCATE')),
            (has_table_privilege(
                role.rolname, 'public.schema_migrations', 'REFERENCES')),
            (has_table_privilege(
                role.rolname, 'public.schema_migrations', 'TRIGGER'))
    ) capability(allowed)
    WHERE role.rolname = ANY(%s) AND capability.allowed
"""
GRANT_OPTION_COUNT_QUERY = """
    SELECT
        (SELECT COUNT(*) FROM information_schema.table_privileges
         WHERE grantee = ANY(%s) AND is_grantable = 'YES')
      + (SELECT COUNT(*) FROM information_schema.column_privileges
         WHERE grantee = ANY(%s) AND is_grantable = 'YES')
      + (SELECT COUNT(*) FROM information_schema.routine_privileges
         WHERE grantee = ANY(%s) AND is_grantable = 'YES')
      + (SELECT COUNT(*) FROM information_schema.usage_privileges
         WHERE grantee = ANY(%s) AND is_grantable = 'YES')
"""
TABLE_PRIVILEGE_MISMATCH_COUNT_QUERY = """
    WITH expected_tables(object_name) AS (
        SELECT unnest(%s::text[])
    ),
    expected_positive(role_name, object_name, privilege_type) AS (
        SELECT role_name, object_name, privilege_type
        FROM jsonb_to_recordset(%s::jsonb)
          AS expected(
              role_name text,
              object_name text,
              privilege_type text
          )
    ),
    runtime_roles(role_name) AS (
        SELECT unnest(%s::text[])
    ),
    privilege_types(privilege_type) AS (
        SELECT unnest(%s::text[])
    ),
    inventory_mismatch AS (
        SELECT COUNT(*) AS count
        FROM (
            SELECT missing.object_name FROM (
                SELECT expected.object_name
                FROM expected_tables expected
                EXCEPT
                SELECT tablename
                FROM pg_catalog.pg_tables
                WHERE schemaname = 'public'
            ) missing
            UNION ALL
            SELECT extra.object_name FROM (
                SELECT tablename AS object_name
                FROM pg_catalog.pg_tables
                WHERE schemaname = 'public'
                EXCEPT
                SELECT expected.object_name
                FROM expected_tables expected
            ) extra
        ) mismatch
    ),
    privilege_mismatch AS (
        SELECT COUNT(*) AS count
        FROM runtime_roles role
        CROSS JOIN expected_tables object
        JOIN pg_catalog.pg_tables actual
          ON actual.schemaname = 'public'
         AND actual.tablename = object.object_name
        CROSS JOIN privilege_types privilege
        LEFT JOIN expected_positive expected
          ON expected.role_name = role.role_name
         AND expected.object_name = object.object_name
         AND expected.privilege_type = privilege.privilege_type
        WHERE has_table_privilege(
                  role.role_name,
                  format('public.%%I', object.object_name),
                  privilege.privilege_type
              )
              IS DISTINCT FROM (expected.role_name IS NOT NULL)
    )
    SELECT inventory_mismatch.count + privilege_mismatch.count
    FROM inventory_mismatch, privilege_mismatch
"""
SEQUENCE_PRIVILEGE_MISMATCH_COUNT_QUERY = """
    WITH expected_sequences(object_name) AS (
        SELECT unnest(%s::text[])
    ),
    expected_positive(role_name, object_name, privilege_type) AS (
        SELECT role_name, object_name, privilege_type
        FROM jsonb_to_recordset(%s::jsonb)
          AS expected(
              role_name text,
              object_name text,
              privilege_type text
          )
    ),
    runtime_roles(role_name) AS (
        SELECT unnest(%s::text[])
    ),
    privilege_types(privilege_type) AS (
        SELECT unnest(%s::text[])
    ),
    inventory_mismatch AS (
        SELECT COUNT(*) AS count
        FROM (
            SELECT missing.object_name FROM (
                SELECT expected.object_name
                FROM expected_sequences expected
                EXCEPT
                SELECT sequence.relname
                FROM pg_catalog.pg_class sequence
                JOIN pg_catalog.pg_namespace namespace
                  ON namespace.oid = sequence.relnamespace
                WHERE namespace.nspname = 'public'
                  AND sequence.relkind = 'S'
            ) missing
            UNION ALL
            SELECT extra.object_name FROM (
                SELECT sequence.relname AS object_name
                FROM pg_catalog.pg_class sequence
                JOIN pg_catalog.pg_namespace namespace
                  ON namespace.oid = sequence.relnamespace
                WHERE namespace.nspname = 'public'
                  AND sequence.relkind = 'S'
                EXCEPT
                SELECT expected.object_name
                FROM expected_sequences expected
            ) extra
        ) mismatch
    ),
    privilege_mismatch AS (
        SELECT COUNT(*) AS count
        FROM runtime_roles role
        CROSS JOIN expected_sequences object
        JOIN pg_catalog.pg_class actual
          ON actual.relname = object.object_name
         AND actual.relkind = 'S'
        JOIN pg_catalog.pg_namespace actual_namespace
          ON actual_namespace.oid = actual.relnamespace
         AND actual_namespace.nspname = 'public'
        CROSS JOIN privilege_types privilege
        LEFT JOIN expected_positive expected
          ON expected.role_name = role.role_name
         AND expected.object_name = object.object_name
         AND expected.privilege_type = privilege.privilege_type
        WHERE has_sequence_privilege(
                  role.role_name,
                  format('public.%%I', object.object_name),
                  privilege.privilege_type
              )
              IS DISTINCT FROM (expected.role_name IS NOT NULL)
    )
    SELECT inventory_mismatch.count + privilege_mismatch.count
    FROM inventory_mismatch, privilege_mismatch
"""


def _fetch_scalar(cursor: Any, query: str, params: Sequence[Any] = ()) -> int:
    cursor.execute(query, params)
    row = cursor.fetchone()
    if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or not row:
        raise CollectionError("query_result_invalid")
    value = row[0]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise CollectionError("query_result_invalid")
    return value


def _migration_state(
    rows: Iterable[Sequence[Any]],
) -> tuple[dict[str, str], list[str], int]:
    repository_hashes = _current_migration_hashes()
    repository_filenames = {
        path.name.split("_", 1)[0]: path.name
        for path in MIGRATION_DIR.glob("*.sql")
    }
    observed: dict[str, str] = {}
    drift_count = 0
    for row in rows:
        if (
            not isinstance(row, Sequence)
            or isinstance(row, (str, bytes))
            or len(row) != 2
        ):
            drift_count += 1
            continue
        raw_version, raw_sha = row
        match = _MIGRATION_VERSION.match(str(raw_version))
        if match is None:
            drift_count += 1
            continue
        version = match.group("version")
        if (
            version not in repository_hashes
            or str(raw_version) != repository_filenames.get(version)
            or version in observed
            or not isinstance(raw_sha, str)
            or not _SHA256.fullmatch(raw_sha)
        ):
            drift_count += 1
            continue
        observed[version] = raw_sha
        if raw_sha != repository_hashes[version]:
            drift_count += 1
    applied = {
        version: observed.get(version, "0" * 64)
        for version in EXPECTED_APPLIED_VERSIONS
    }
    pending = [
        version for version in repository_hashes if version not in observed
    ]
    drift_count += sum(
        1 for version in EXPECTED_APPLIED_VERSIONS if version not in observed
    )
    return applied, pending, drift_count


def _collect_with_connection(connection: Any) -> dict[str, Any]:
    aggregate_query_count = 0
    began = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("BEGIN TRANSACTION READ ONLY")
            began = True
            cursor.execute("SHOW default_transaction_read_only")
            default_read_only = cursor.fetchone()
            cursor.execute("SHOW transaction_read_only")
            transaction_read_only = cursor.fetchone()
            if default_read_only != ("on",) or transaction_read_only != ("on",):
                raise CollectionError("readonly_not_enforced")

            cursor.execute(MIGRATION_QUERY)
            applied_hashes, pending_versions, drift_count = _migration_state(
                cursor.fetchall()
            )

            source_aggregates: dict[str, int] = {}
            for name, query in SOURCE_AGGREGATE_QUERIES.items():
                source_aggregates[name] = _fetch_scalar(cursor, query)
                aggregate_query_count += 1

            cursor.execute(ROLE_QUERY, (list(EXPECTED_ROLE_STATE),))
            role_rows = cursor.fetchall()
            present_roles: set[str] = set()
            runtime_superuser_count = 0
            runtime_bypassrls_count = 0
            elevated_attribute_count = 0
            for row in role_rows:
                if (
                    not isinstance(row, Sequence)
                    or isinstance(row, (str, bytes))
                    or len(row) != 8
                    or row[0] not in EXPECTED_ROLE_STATE
                ):
                    raise CollectionError("role_result_invalid")
                role_name = str(row[0])
                present_roles.add(role_name)
                if role_name in RUNTIME_ROLES:
                    runtime_superuser_count += int(row[1] is True)
                    runtime_bypassrls_count += int(row[7] is True)
                    elevated_attribute_count += sum(
                        int(flag)
                        for flag in (
                            row[2] is True,
                            row[3] is True,
                            row[4] is True,
                            row[5] is not True,
                            row[6] is True,
                        )
                    )
            role_state = {
                role: ("present" if role in present_roles else "absent")
                for role in EXPECTED_ROLE_STATE
            }

            runtime_owner_count = _fetch_scalar(
                cursor,
                OWNER_COUNT_QUERY,
                (list(RUNTIME_ROLES),) * 3,
            )
            unexpected_grant_count = elevated_attribute_count
            unexpected_grant_count += _fetch_scalar(
                cursor,
                MEMBERSHIP_COUNT_QUERY,
                (list(RUNTIME_ROLES),) * 2,
            )
            unexpected_grant_count += _fetch_scalar(
                cursor,
                DATABASE_CAPABILITY_COUNT_QUERY,
                (list(RUNTIME_ROLES),),
            )
            unexpected_grant_count += _fetch_scalar(
                cursor,
                SCHEMA_CAPABILITY_COUNT_QUERY,
                (list(RUNTIME_ROLES),),
            )
            unexpected_grant_count += _fetch_scalar(
                cursor,
                MIGRATION_PRIVILEGE_COUNT_QUERY,
                (list(RUNTIME_ROLES),),
            )
            unexpected_grant_count += _fetch_scalar(
                cursor,
                GRANT_OPTION_COUNT_QUERY,
                (list(RUNTIME_ROLES),) * 4,
            )
            unexpected_grant_count += _fetch_scalar(
                cursor,
                TABLE_PRIVILEGE_MISMATCH_COUNT_QUERY,
                (
                    list(EXPECTED_PUBLIC_TABLES),
                    json.dumps(
                        EXPECTED_TABLE_PRIVILEGE_ROWS,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    list(RUNTIME_ROLES),
                    list(TABLE_PRIVILEGES),
                ),
            )
            unexpected_grant_count += _fetch_scalar(
                cursor,
                SEQUENCE_PRIVILEGE_MISMATCH_COUNT_QUERY,
                (
                    list(EXPECTED_PUBLIC_SEQUENCES),
                    json.dumps(
                        EXPECTED_SEQUENCE_PRIVILEGE_ROWS,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    list(RUNTIME_ROLES),
                    list(SEQUENCE_PRIVILEGES),
                ),
            )

            blocker_count = sum(
                source_aggregates[name] for name in SOURCE_ZERO_AGGREGATES
            )
            if set(source_aggregates) != (
                SOURCE_ZERO_AGGREGATES | SOURCE_INFORMATIONAL_AGGREGATES
            ):
                raise CollectionError("aggregate_set_invalid")

            return {
                "metadata_session_read_only": True,
                "business_row_values_read": 0,
                "aggregate_query_count": aggregate_query_count,
                "applied_migration_hashes": applied_hashes,
                "pending_versions": pending_versions,
                "stored_migration_drift_count": drift_count,
                "source_preflight_complete": True,
                "source_preflight_blocker_count": blocker_count,
                "effective_role_audit_complete": True,
                "unexpected_grant_count": unexpected_grant_count,
                "runtime_owner_count": runtime_owner_count,
                "runtime_superuser_count": runtime_superuser_count,
                "runtime_bypassrls_count": runtime_bypassrls_count,
                "role_state": role_state,
                "source_aggregates": source_aggregates,
            }
    except CollectionError:
        raise
    except Exception as exc:
        raise CollectionError("database_query_failed") from exc
    finally:
        if began:
            try:
                connection.rollback()
            except Exception as exc:
                raise CollectionError("database_cleanup_failed") from exc


def _connect(database_url: str) -> Any:
    try:
        import psycopg
    except ImportError as exc:
        raise CollectionError("psycopg_unavailable") from exc
    try:
        return psycopg.connect(
            database_url,
            autocommit=True,
            connect_timeout=10,
            options=(
                "-c default_transaction_read_only=on "
                "-c statement_timeout=15000 "
                "-c lock_timeout=3000 "
                "-c idle_in_transaction_session_timeout=20000 "
                "-c timezone=UTC"
            ),
        )
    except Exception as exc:
        raise CollectionError("database_connection_failed") from exc


def collect(
    environ: dict[str, str] | None = None,
    connector: Callable[[str], Any] = _connect,
) -> dict[str, Any]:
    environment = os.environ if environ is None else environ
    database_url = environment.get(DATABASE_URL_ENV, "").strip()
    if not database_url:
        raise CollectionError("database_url_missing")
    connection = connector(database_url)
    try:
        return _collect_with_connection(connection)
    finally:
        try:
            connection.close()
        except Exception as exc:
            raise CollectionError("database_close_failed") from exc


def main() -> int:
    try:
        evidence = collect()
    except CollectionError as exc:
        print(
            json.dumps(
                {"status": "error", "error_code": exc.code},
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            evidence,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
