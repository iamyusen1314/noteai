#!/usr/bin/env python3
"""Identify the bounded legacy production runtime-role conflict.

The auditor is independent of the schema executor. It validates the exact
source that was used by the failed schema transaction before connecting, then
opens one forced-read-only connection and reads only migration and role
metadata. Database account names are mapped to fixed functional labels before
the Secret-free result is emitted.
"""

from __future__ import annotations

import hashlib
import json
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
EXECUTOR_PATH = ROOT / "tools" / "production_schema_roles.py"
ACL_PATH = ROOT / "scripts" / "postgres" / "noteai_production_runtime_roles.sql"
TASK_ID = "PROD-FIRST-LAUNCH-LEGACY-RUNTIME-ROLE-CONFLICT-001"
AUDIT_ID = "PROD-LEGACY-RUNTIME-ROLE-IDENTITY-READONLY-001"
EXPECTED_LEDGER_NAMES = (
    "0001_initial.sql",
    "0002_shared_runtime_state.sql",
    "0003_market_timing.sql",
    "0004_xhs_freshness.sql",
    "0005_idempotency_requests.sql",
    "0006_model_usage_records.sql",
    "0007_ai_operations.sql",
    "0008_ai_operation_admissions.sql",
)
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
EXPECTED_SEQUENCES = (
    "analysis_log_id_seq",
    "crawler_events_id_seq",
    "hot_keywords_id_seq",
    "keyword_snapshots_id_seq",
    "prompt_history_id_seq",
)
LEGACY_RUNTIME_ROLES = ("noteai_app", "noteai_xhs")
ROLE_LABELS = {
    "noteai_app": "legacy_api_runtime",
    "noteai_xhs": "legacy_xhs_runtime",
}
KNOWN_RUNTIME_ROLES = frozenset({
    *LEGACY_RUNTIME_ROLES,
    "noteai_admin_runtime",
    "noteai_ai_dispatcher",
    "noteai_ai_worker",
    "noteai_payment",
    "noteai_xhs_tracking",
    "noteai_xhs_trends",
})
ELEVATED_ATTRIBUTES = (
    "rolsuper",
    "rolinherit",
    "rolcreaterole",
    "rolcreatedb",
    "rolreplication",
    "rolbypassrls",
)
EXPECTED_SOURCE_SHA256 = {
    "executor": "267da28ba72c5ebf2593fe5793544764c59df776944d4180c6c2632ba97671e5",
    "acl": "fc41ee2867fdfa3965a78e9eea017cf26466bb10f2a5e8879865182431fc93c0",
    "0001": "8ea5d32bc5c1a3e84452d93722324b9a9b4bb2e156c69b4a9656efa13ed51718",
    "0002": "d3a939479990cfe080fce71ebd122e19e633874bd2cd6883b5b03507eadefcb7",
    "0003": "772636cab88c2abf169a5b1a3fd5419ba1e3b12bbae92e211e296e89b1850192",
    "0004": "1c817056eea3df9e0e1dd6ba6aceaf0c9a172b3cbba92ba3aeb621adb857a2a1",
    "0005": "3a02a45bf0211580c5db97fc80ab9fb8eedab94a9cf981c59f3de231789981e6",
    "0006": "392eb82adca68493566f6469ce6ce4f1fba0cfc9ab76757deb4e1404c45cb735",
    "0007": "477d4ea776d701c4b359b36eb254c68263131f74dedeb766ff46081bff619037",
    "0008": "3bdd896ce06f7a5ae8deeba01145d9556775c45a71cd83576240d24a01bc05fe",
    "0009": "1cfa46144b9a4d424215dd861a9817ec3a4612e7e62c1f2df5fec6f2e728f750",
    "0010": "8ab5bbddad28ea60afad48bc27d71b105c5313d0229e263d06b65db4f38a3459",
    "0011": "abd55623a8903d6a6c01bed5fe4336b07be182abde2b86fa4b9cc5e7cb4b9802",
    "0012": "df72dedfb292700104fc394b5b326f33e4339cbf195f704278c56e08e44bec83",
    "0013": "1268cdb9696965f02d5be88882b3dc8a2f9f7b589a2b0da5193d1bb8408ccb76",
    "0014": "ed788fdf33e256713767101e85005e95a712a7e5c5aae0ec258c5f14091cb0ad",
    "0015": "3ee9b85c9c154117d6e81ee83283160cede9bd182450b0de193f94a431b7d66c",
    "0016": "5cdd8dc0bb6eefd4fee086458e964495d7163bf123026c4511c4dd7ccf93fde6",
}
PROVEN_PRECONNECT_CODES = frozenset({
    "database_url_missing",
    "psycopg_unavailable",
    "source_drift",
})


class LegacyRoleAuditError(RuntimeError):
    """A sanitized fail-closed identity-audit error."""

    def __init__(self, code: str, *, stage: str):
        super().__init__(code)
        self.code = code
        self.stage = stage


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_local_source() -> dict[str, str]:
    paths = sorted(MIGRATION_DIR.glob("*.sql"))
    versions = tuple(path.name.split("_", 1)[0] for path in paths)
    if versions != tuple(f"{number:04d}" for number in range(1, 17)):
        raise LegacyRoleAuditError("source_drift", stage="local_source")
    observed = {
        "executor": _sha256(EXECUTOR_PATH),
        "acl": _sha256(ACL_PATH),
        **{
            path.name.split("_", 1)[0]: _sha256(path)
            for path in paths
        },
    }
    if observed != EXPECTED_SOURCE_SHA256:
        raise LegacyRoleAuditError("source_drift", stage="local_source")
    return observed


def _value(row: Any) -> Any:
    if row is None:
        raise LegacyRoleAuditError("missing_scalar", stage="database_read")
    return next(iter(row.values())) if isinstance(row, dict) else row[0]


def _scalar(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> Any:
    return _value(conn.execute(sql, params).fetchone())


def _role_category(
    role_name: str,
    *,
    current_user: str,
    can_login: bool,
) -> str:
    if role_name in ROLE_LABELS:
        return ROLE_LABELS[role_name]
    if role_name in KNOWN_RUNTIME_ROLES:
        return "known_runtime"
    if role_name == current_user:
        return "task_executor"
    if role_name == "noteai_admin":
        return "legacy_admin"
    if role_name.startswith(("pg_", "rds")):
        return "provider_or_system"
    return "other_login" if can_login else "other_nonlogin"


def _endpoint(
    row: Any,
    *,
    prefix: str,
    current_user: str,
) -> dict[str, Any]:
    name = str(row[f"{prefix}_name"])
    return {
        "category": _role_category(
            name,
            current_user=current_user,
            can_login=bool(row[f"{prefix}_canlogin"]),
        ),
        "login": bool(row[f"{prefix}_canlogin"]),
        "superuser": bool(row[f"{prefix}_super"]),
    }


def collect_identity(conn: Any) -> dict[str, Any]:
    """Collect one exact forced-read-only legacy role identity snapshot."""
    try:
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            if _scalar(conn, "SHOW default_transaction_read_only") != "on":
                raise LegacyRoleAuditError(
                    "readonly_not_enforced",
                    stage="database_read",
                )
            if _scalar(conn, "SHOW transaction_read_only") != "on":
                raise LegacyRoleAuditError(
                    "readonly_not_enforced",
                    stage="database_read",
                )

            current_user = str(_scalar(conn, "SELECT current_user"))
            sha_column_count = int(_scalar(
                conn,
                "SELECT COUNT(*) FROM information_schema.columns "
                "WHERE table_schema='public' "
                "AND table_name='schema_migrations' "
                "AND column_name='sha256'",
            ))
            ledger_rows = conn.execute(
                "SELECT version FROM public.schema_migrations ORDER BY version"
            ).fetchall()
            ledger_names = tuple(str(row["version"]) for row in ledger_rows)
            tables = tuple(
                str(row["table_name"])
                for row in conn.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='public' "
                    "AND table_type='BASE TABLE' ORDER BY table_name"
                ).fetchall()
            )
            sequences = tuple(
                str(row["sequence_name"])
                for row in conn.execute(
                    "SELECT sequence_name FROM information_schema.sequences "
                    "WHERE sequence_schema='public' ORDER BY sequence_name"
                ).fetchall()
            )

            role_rows = conn.execute(
                "SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,"
                "rolcanlogin,rolreplication,rolbypassrls "
                "FROM pg_catalog.pg_roles "
                "WHERE rolname = ANY(%s) ORDER BY rolname",
                (list(KNOWN_RUNTIME_ROLES),),
            ).fetchall()
            present_roles = tuple(str(row["rolname"]) for row in role_rows)
            elevated = [
                (str(row["rolname"]), attribute)
                for row in role_rows
                for attribute in ELEVATED_ATTRIBUTES
                if bool(row[attribute])
            ]
            login_state = {
                ROLE_LABELS[str(row["rolname"])]: bool(row["rolcanlogin"])
                for row in role_rows
                if str(row["rolname"]) in ROLE_LABELS
            }

            membership_rows = conn.execute(
                "SELECT "
                "granted.rolname AS granted_name,"
                "granted.rolcanlogin AS granted_canlogin,"
                "granted.rolsuper AS granted_super,"
                "member.rolname AS member_name,"
                "member.rolcanlogin AS member_canlogin,"
                "member.rolsuper AS member_super,"
                "membership.admin_option,"
                "(to_jsonb(membership)->>'inherit_option')::boolean "
                "AS inherit_option,"
                "(to_jsonb(membership)->>'set_option')::boolean "
                "AS set_option "
                "FROM pg_catalog.pg_auth_members membership "
                "JOIN pg_catalog.pg_roles granted "
                "ON granted.oid=membership.roleid "
                "JOIN pg_catalog.pg_roles member "
                "ON member.oid=membership.member "
                "WHERE granted.rolname = ANY(%s) "
                "OR member.rolname = ANY(%s)",
                (
                    list(LEGACY_RUNTIME_ROLES),
                    list(LEGACY_RUNTIME_ROLES),
                ),
            ).fetchall()
            ownership_count = int(_scalar(
                conn,
                "SELECT ("
                "(SELECT COUNT(*) FROM pg_catalog.pg_class object "
                "JOIN pg_catalog.pg_roles role ON role.oid=object.relowner "
                "WHERE role.rolname = ANY(%s)) + "
                "(SELECT COUNT(*) FROM pg_catalog.pg_namespace object "
                "JOIN pg_catalog.pg_roles role ON role.oid=object.nspowner "
                "WHERE role.rolname = ANY(%s)) + "
                "(SELECT COUNT(*) FROM pg_catalog.pg_proc object "
                "JOIN pg_catalog.pg_roles role ON role.oid=object.proowner "
                "WHERE role.rolname = ANY(%s)))",
                (
                    list(LEGACY_RUNTIME_ROLES),
                    list(LEGACY_RUNTIME_ROLES),
                    list(LEGACY_RUNTIME_ROLES),
                ),
            ))
    except LegacyRoleAuditError:
        raise
    except BaseException as exc:
        raise LegacyRoleAuditError(
            "database_read_failed",
            stage="database_read",
        ) from exc

    exact_conflict = (
        sha_column_count == 0
        and ledger_names == EXPECTED_LEDGER_NAMES
        and tables == LEGACY_TABLES
        and sequences == EXPECTED_SEQUENCES
        and present_roles == LEGACY_RUNTIME_ROLES
        and len(elevated) == 1
        and len(membership_rows) == 1
        and ownership_count == 0
    )
    public_membership = None
    if len(membership_rows) == 1:
        membership = membership_rows[0]
        granted_is_runtime = str(membership["granted_name"]) in ROLE_LABELS
        member_is_runtime = str(membership["member_name"]) in ROLE_LABELS
        if granted_is_runtime and member_is_runtime:
            direction = "runtime_to_runtime"
        elif granted_is_runtime:
            direction = "runtime_as_granted_role"
        elif member_is_runtime:
            direction = "runtime_as_member"
        else:  # pragma: no cover - excluded by the query predicate
            direction = "not_runtime_related"
        public_membership = {
            "direction": direction,
            "granted_endpoint": _endpoint(
                membership,
                prefix="granted",
                current_user=current_user,
            ),
            "member_endpoint": _endpoint(
                membership,
                prefix="member",
                current_user=current_user,
            ),
            "admin_option": bool(membership["admin_option"]),
            "inherit_option": (
                None
                if membership["inherit_option"] is None
                else bool(membership["inherit_option"])
            ),
            "set_option": (
                None
                if membership["set_option"] is None
                else bool(membership["set_option"])
            ),
        }
    public_elevation = None
    if len(elevated) == 1:
        public_elevation = {
            "runtime_role": ROLE_LABELS.get(
                elevated[0][0],
                "unexpected_runtime_role",
            ),
            "attribute": elevated[0][1],
        }

    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "audit_id": AUDIT_ID,
        "status": "identified" if exact_conflict else "state_changed",
        "incident_class": "CONNECTED_KNOWN",
        "read_only": True,
        "default_transaction_read_only": True,
        "transaction_read_only": True,
        "database_write_count": 0,
        "business_row_values_read": 0,
        "observation": {
            "ledger_count": len(ledger_names),
            "ledger_first": (
                ledger_names[0].split("_", 1)[0] if ledger_names else None
            ),
            "ledger_last": (
                ledger_names[-1].split("_", 1)[0] if ledger_names else None
            ),
            "legacy_ledger_exact": ledger_names == EXPECTED_LEDGER_NAMES,
            "sha256_column_count": sha_column_count,
            "public_table_count": len(tables),
            "legacy_table_inventory_exact": tables == LEGACY_TABLES,
            "public_sequence_count": len(sequences),
            "sequence_inventory_exact": sequences == EXPECTED_SEQUENCES,
            "legacy_runtime_role_count": len(present_roles),
            "new_runtime_role_count": sum(
                role not in LEGACY_RUNTIME_ROLES for role in present_roles
            ),
            "legacy_runtime_login_state": login_state,
            "elevated_attribute_count": len(elevated),
            "elevated_identity": public_elevation,
            "bidirectional_membership_count": len(membership_rows),
            "membership_identity": public_membership,
            "runtime_ownership_count": ownership_count,
            "new_schema_seed_count": 0 if tables == LEGACY_TABLES else None,
            "retention_row_count": None,
        },
        "failed_schema_transaction": {
            "source_set_exact": True,
            "legacy_role_attribute_mutation_count": 0,
            "legacy_role_membership_mutation_count": 0,
            "conflict_could_be_created_by_transaction": False,
        },
        "provider_calls": 0,
        "service_changes": 0,
        "public_traffic_requests": 0,
        "secret_values_exposed": 0,
    }


def _connect(database_url: str) -> Any:
    if psycopg is None:
        raise LegacyRoleAuditError("psycopg_unavailable", stage="connect")
    return psycopg.connect(
        database_url,
        row_factory=dict_row,
        connect_timeout=10,
        application_name="noteai_legacy_role_audit_v1",
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
            "production_legacy_runtime_role_audit=FAIL "
            f"stage={stage} incident_class=PRE_CONNECT "
            "database_connected=0 connection_attempted=0 "
            "database_outcome=NOT_CONNECTED retry_same_path=0",
            file=sys.stderr,
        )
        return 2
    print(
        "production_legacy_runtime_role_audit=FAIL "
        f"stage={stage} incident_class=CONNECTED_UNKNOWN "
        f"database_connected={int(connected)} "
        f"connection_attempted={int(connection_attempted)} "
        "database_outcome=UNKNOWN no_retry=1",
        file=sys.stderr,
    )
    return 1


def main(*, database_url: str | None = None) -> int:
    connected = False
    connection_attempted = False
    try:
        _validate_local_source()
        if not database_url or not database_url.strip():
            raise LegacyRoleAuditError("database_url_missing", stage="connect")
        connection_attempted = True
        conn = _connect(database_url.strip())
        connected = True
        try:
            result = collect_identity(conn)
        finally:
            conn.close()
    except LegacyRoleAuditError as exc:
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
    return 0 if result["status"] == "identified" else 30


if __name__ == "__main__":
    raise SystemExit(main())
