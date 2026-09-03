#!/usr/bin/env python3
"""Validate Item 26 source/restored manifests and terminal projections."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "model"
if str(MODEL) not in sys.path:
    sys.path.insert(0, str(MODEL))

from storage_recovery_evidence import (  # noqa: E402
    RecoveryEvidenceError,
    validate_manifest,
    verify_restore,
)


VALIDATOR_REF = "tools/validate_item26_pitr_restore_result_v1.py"
TASK_ID = "PROD-FIRST-LAUNCH-PITR-RESTORE-001"
EXPECTED_EQUAL_FIELDS = [
    "release_commit",
    "database_engine",
    "database_schema",
    "database_migrations",
    "database_tables",
    "database_references",
    "private_objects",
]
EXPECTED_TABLES = (
    "account_deletion_requests",
    "admin_sessions",
    "ai_dispatch_state",
    "ai_operation_admissions",
    "ai_operation_events",
    "ai_operation_media_refs",
    "ai_operation_outbox",
    "ai_operation_settlements",
    "ai_operations",
    "ai_payload_refs",
    "ai_provider_attempts",
    "analysis_log",
    "auth_login_limits",
    "auth_verification_challenges",
    "chat_sessions",
    "content_retention",
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
    "prompt_history",
    "saved_diagnoses",
    "schema_migrations",
    "subscriptions",
    "system_settings",
    "tracked_notes",
    "tracking_provider_attempts",
    "usage_records",
    "user_contract_acceptances",
    "user_learn",
    "user_memories",
    "user_sessions",
    "users",
    "xhs_crawler_health",
    "xhs_freshness_ledger",
    "xhs_trends_provider_attempts",
    "xhs_trends_runs",
    "xhs_trends_service_state",
    "xhs_trends_snapshot_evidence",
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
    ("0017_durable_ai_postgres_wakeup.sql", "a73cbefd853cefe7b56c42bed2c5a7f0ba1626e57755c6f9464629b49c42cbbe"),
)
EXPECTED_RLS_TABLES = (
    "admin_sessions",
    "ai_dispatch_state",
    "ai_operation_media_refs",
    "ai_operation_outbox",
    "ai_operation_settlements",
    "ai_payload_refs",
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
    "system_settings",
)


def validate_terminal_result(
    *,
    source_manifest: Any,
    restored_manifest: Any,
    source_capture: Any,
    restored_capture: Any,
    reconciliation: Any,
    expected_execution_revision: str,
) -> list[str]:
    """Return errors for any content, shape or projection mismatch."""

    errors: list[str] = []
    try:
        source = validate_manifest(source_manifest)
        restored = validate_manifest(restored_manifest)
        comparison = verify_restore(source, restored)
    except (RecoveryEvidenceError, TypeError, ValueError) as exc:
        return ["Item26 recovery manifest invalid: " + str(exc)]
    for label, capture, manifest in (
        ("source", source_capture, source),
        ("restored", restored_capture, restored),
    ):
        if type(capture) is not dict:
            errors.append(label + " capture projection invalid")
            continue
        database = manifest.get("database")
        privacy = manifest.get("privacy")
        objects = manifest.get("objects")
        references = database.get("references") if type(database) is dict else None
        migrations = database.get("migrations") if type(database) is dict else None
        expected_migrations = [
            {"version": version, "sha256": sha256}
            for version, sha256 in EXPECTED_MIGRATIONS
        ]
        if (
            capture.get("manifest_sha256") != manifest.get("manifest_sha256")
            or manifest.get("release_commit") != expected_execution_revision
            or type(database) is not dict
            or capture.get("postgresql_major_version") != 16
            or database.get("engine") != "postgresql"
            or database.get("table_count") != len(EXPECTED_TABLES)
            or set(database.get("tables", {})) != set(EXPECTED_TABLES)
            or migrations != expected_migrations
            or capture.get("table_count") != len(EXPECTED_TABLES)
            or capture.get("migration_count") != len(EXPECTED_MIGRATIONS)
            or capture.get("rls_tables") != list(EXPECTED_RLS_TABLES)
            or capture.get("force_rls_tables") != []
            or capture.get("owner_role") != "noteai_admin"
            or type(privacy) is not dict
            or any(privacy.get(key) is not False for key in privacy)
            or type(references) is not dict
            or any(
                type(references.get(key)) is not dict
                or references[key].get("present") is not True
                for key in ("ai_payload_refs", "private_media_refs")
            )
            or type(objects) is not dict
            or "not_captured" in objects
            or set(objects) != {
                "object_count",
                "size_bytes",
                "aggregate_sha256",
                "content_included",
                "object_keys_included",
            }
            or capture.get("object_head_count")
            != objects.get("object_count")
            or type(capture.get("object_list_count")) is not int
            or capture["object_list_count"] < 1
        ):
            errors.append(label + " capture/manifest projection mismatch")
    expected_reconciliation = {
        "verified": True,
        "mismatch_codes": [],
        "source_manifest_sha256": source["manifest_sha256"],
        "restored_manifest_sha256": restored["manifest_sha256"],
        "equal_fields": EXPECTED_EQUAL_FIELDS,
        "content_included": False,
    }
    if comparison != {
        "verified": True,
        "mismatch_codes": [],
        "source_manifest_sha256": source["manifest_sha256"],
        "restored_manifest_sha256": restored["manifest_sha256"],
        "content_included": False,
    }:
        errors.append("Item26 source/restored semantic reconciliation failed")
    if type(reconciliation) is not dict or reconciliation != expected_reconciliation:
        errors.append("Item26 reconciliation projection mismatch")
    return errors


__all__ = ["TASK_ID", "VALIDATOR_REF", "validate_terminal_result"]
