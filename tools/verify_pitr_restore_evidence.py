#!/usr/bin/env python3
"""Offline semantic verifier for Item 26 PITR restore evidence.

The Secret-free generation-v2 public root is tracked and hash-frozen.  Signed
terminal artifacts remain absent until their prescribed stages, so neither the
public root nor a manifest-only status change can grant Item 26 credit.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any

from verify_item26_external_authority_v1 import (
    VERIFIER_REF as EXTERNAL_AUTHORITY_VERIFIER_REF,
    _frozen_before as _revision_is_strict_ancestor,
    git_tree_binding,
    validate_authority_bundle,
)
from validate_item26_pitr_restore_result_v1 import validate_terminal_result
from validate_item26_pitr_restore_result_v1 import EXPECTED_RLS_TABLES


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_REF = "tools/verify_pitr_restore_evidence.py"
RESULT_VALIDATOR_REF = "tools/validate_item26_pitr_restore_result_v1.py"
EVIDENCE_BUILDER_REF = "tools/build_item26_pitr_restore_evidence_v1.py"
MANUAL_COST_STOP_VERIFIER_REF = (
    "tools/verify_item26_manual_cost_stop_evidence_v2.py"
)
MANUAL_COST_STOP_BUILDER_REF = (
    "tools/build_item26_manual_cost_stop_evidence_v2.py"
)
MANUAL_COST_STOP_AUTHORITY_VERIFIER_REF = (
    "tools/verify_item26_manual_cost_stop_authority_v2.py"
)
MANUAL_COST_STOP_RAW_EXTRACTOR_REF = (
    "tools/extract_item26_manual_cost_stop_raw_v2.py"
)
MANUAL_COST_STOP_COLLECTOR_REF = (
    "tools/collect_item26_manual_cost_stop_raw_v2.py"
)
MANUAL_COST_STOP_ROOT_BUILDER_REF = (
    "tools/build_item26_manual_cost_stop_authority_root_v2.py"
)
MANUAL_COST_STOP_ACTIVATION_RECEIPT_BUILDER_REF = (
    "tools/build_item26_manual_cost_stop_activation_receipt_v3.py"
)
MANUAL_COST_STOP_INSTALLER_REF = (
    "tools/install_item26_manual_cost_stop_runtime_v3.py"
)
MANUAL_COST_STOP_BOOTSTRAP_REF = (
    "tools/bootstrap_item26_manual_cost_stop_keys_v2.py"
)
MANUAL_COST_STOP_CONTRACT_REF = (
    "deploy/production/plans/item26-manual-cost-stop-contract-v2.json"
)
MANUAL_COST_STOP_CI_WORKFLOW_REF = ".github/workflows/ci.yml"
MANUAL_COST_STOP_PUBLIC_ROOT_REF = (
    "deploy/production/authorities/"
    "item26-manual-cost-stop-authority-root-v2.json"
)
MANUAL_COST_STOP_NO_REPLAY_REGISTRY_REF = (
    "deploy/production/plans/item26-no-replay-registry-v2.json"
)
NO_REPLAY_REGISTRY_V1_REF = (
    "deploy/production/plans/item26-no-replay-registry-v1.json"
)
MANUAL_COST_STOP_EVIDENCE_REF = (
    "deploy/production/evidence/"
    "production-item26-manual-cost-stop-v2-20260817.json"
)
MANUAL_COST_STOP_RECEIPT_REF = (
    "deploy/production/evidence/"
    "item26-manual-cost-stop-provider-receipt-v2-20260817.json"
)
MANUAL_COST_STOP_CHECKPOINT_REF = (
    "deploy/production/evidence/"
    "item26-manual-cost-stop-terminal-checkpoint-v2-20260817.json"
)
TASK_ID = "PROD-FIRST-LAUNCH-PITR-RESTORE-001"
RECEIPT_SCHEMA = "noteai.item26.pitr-restore-provider-receipt.v1"
EVIDENCE_SCHEMA = "noteai.item26.pitr-restore-evidence.v1"
CHECKPOINT_SCHEMA = "noteai.item26.terminal-evidence-checkpoint.v1"
EVIDENCE_REF = (
    "deploy/production/evidence/production-pitr-restore-verified-20260816.json"
)
RECEIPT_REF = (
    "deploy/production/evidence/pitr-restore-provider-receipt-20260816.json"
)
TERMINAL_CHECKPOINT_REF = (
    "deploy/production/evidence/pitr-restore-terminal-checkpoint-20260816.json"
)
NO_REPLAY_REGISTRY_REF = MANUAL_COST_STOP_NO_REPLAY_REGISTRY_REF
NO_REPLAY_REGISTRY_SCHEMA = "noteai.item26.no-replay-registry.v2"
PREDECESSOR_COST_STOP_SCHEMA = (
    "noteai.item26.manual-cost-stop-dependency.v2"
)
PREDECESSOR_COST_STOP_KIND = (
    "MANUAL_BROWSER_POST_ACTION_COST_STOP_AUTHORITY_V2"
)
PREDECESSOR_AUTHORITY_GENERATION_ID = (
    TASK_ID + ":MANUAL-POST-ACTION-COST-STOP-AUTHORITY:v2"
)
PREDECESSOR_AUTHORITY_EPOCH_ID = (
    "noteai.item26.manual-cost-stop-authority-generation.v2"
)
PREDECESSOR_ACTIVATION_RECEIPT_SCHEMA = (
    "noteai.item26.manual-cost-stop-runtime-activation-receipt.v3"
)
REQUIRED_MANIFEST_PATH_REFS = {
    EVIDENCE_REF,
    RECEIPT_REF,
    TERMINAL_CHECKPOINT_REF,
    NO_REPLAY_REGISTRY_REF,
    NO_REPLAY_REGISTRY_V1_REF,
    VERIFIER_REF,
    EXTERNAL_AUTHORITY_VERIFIER_REF,
    RESULT_VALIDATOR_REF,
    EVIDENCE_BUILDER_REF,
    MANUAL_COST_STOP_VERIFIER_REF,
    MANUAL_COST_STOP_BUILDER_REF,
    MANUAL_COST_STOP_AUTHORITY_VERIFIER_REF,
    MANUAL_COST_STOP_RAW_EXTRACTOR_REF,
    MANUAL_COST_STOP_COLLECTOR_REF,
    MANUAL_COST_STOP_ROOT_BUILDER_REF,
    MANUAL_COST_STOP_ACTIVATION_RECEIPT_BUILDER_REF,
    MANUAL_COST_STOP_INSTALLER_REF,
    MANUAL_COST_STOP_BOOTSTRAP_REF,
    MANUAL_COST_STOP_CONTRACT_REF,
    MANUAL_COST_STOP_CI_WORKFLOW_REF,
    MANUAL_COST_STOP_PUBLIC_ROOT_REF,
    "tools/internal_deployment_readiness_gate.py",
    "model/storage_recovery_evidence.py",
}
# The complete Secret-free generation-v2 public root is tracked and frozen.
# Receipt signing/install/readback remain later gates; this hash alone grants
# no readiness credit and authorizes no action.
EXPECTED_AUTHORITY_ROOT_FILE_SHA256 = (
    "8bfb8834c1e241a18cde984d42524759f53423bcf809dd8657fa4b2be102ff85"
)

# Filled mechanically only after the manual post-action cost-stop freezes its
# independent provider/confirmation/CI authority and terminal artifacts.  This
# is deliberately not the abort-v1 authority: the two browser mutations
# predated these controls and cannot be retroactively authorized.  A future
# PITR successor must dynamically reload this exact verifier and bundle.
EXPECTED_PREDECESSOR_COST_STOP = {
    "schema": PREDECESSOR_COST_STOP_SCHEMA,
    "kind": PREDECESSOR_COST_STOP_KIND,
    "authority_generation_id": PREDECESSOR_AUTHORITY_GENERATION_ID,
    "authority_epoch_id": PREDECESSOR_AUTHORITY_EPOCH_ID,
    "activation_receipt_schema": PREDECESSOR_ACTIVATION_RECEIPT_SCHEMA,
    "authority_root": "",
    "verifier_path": "",
    "verifier_sha256": "",
    "builder_path": "",
    "builder_sha256": "",
    "authority_verifier_path": "",
    "authority_verifier_sha256": "",
    "raw_extractor_path": "",
    "raw_extractor_sha256": "",
    "collector_path": "",
    "collector_sha256": "",
    "root_builder_path": "",
    "root_builder_sha256": "",
    "activation_receipt_builder_path": "",
    "activation_receipt_builder_sha256": "",
    "installer_path": "",
    "installer_sha256": "",
    "bootstrap_path": "",
    "bootstrap_sha256": "",
    "contract_path": "",
    "contract_sha256": "",
    "ci_workflow_path": "",
    "ci_workflow_sha256": "",
    "public_root_path": "",
    "public_root_sha256": "",
    "no_replay_registry_path": "",
    "no_replay_registry_file_sha256": "",
    "evidence_path": "",
    "evidence_sha256": "",
    "receipt_path": "",
    "receipt_sha256": "",
    "checkpoint_path": "",
    "checkpoint_sha256": "",
    "authority_root_file_sha256": "",
    "authority_root_git_blob_sha256": "",
    "authority_bundle_file_sha256": "",
    "activation_receipt_sha256": "",
    "provider_raw_file_sha256": "",
    "actiontrail_raw_file_sha256": "",
    "confirmation_envelope_file_sha256": "",
    "terminal_acceptance_sha256": "",
    "old_clone_sha256": "",
    "old_clone_name_sha256": "",
    "source_pre_tuple_sha256": "",
    "source_post_tuple_sha256": "",
    "billing_snapshot_sha256": "",
    "no_replay_registry_sha256": "",
    "old_clone_create_request_sha256": "",
    "old_clone_create_body_sha256": "",
    "old_clone_client_token_sha256": "",
    "protection_disable_request_id_sha256": "",
    "protection_disable_request_body_sha256": "",
    "protection_disable_client_token_sha256": "",
    "delete_request_id_sha256": "",
    "delete_request_body_sha256": "",
    "delete_client_token_present": False,
    "consumed_mutation_identity_set_sha256": "",
    "post_action_observed_at_utc": "",
    "manual_terminal_accepted_at_utc": "",
    "control_revision": "",
    "evidence_revision": "",
    "terminal_revision": "",
}

DEFAULT_READINESS = {
    "internal_verified_before": 25,
    "internal_verified_after": 26,
    "internal_total": 29,
    "internal_percentage_after": 90,
    "complete_public_verified_before": 25,
    "complete_public_verified_after": 26,
    "complete_public_total": 38,
    "complete_public_percentage_after": 68,
    "next_task": "PROD-FIRST-LAUNCH-INTERNAL-SMOKE-001",
    "public_launch_authorized": False,
    "real_provider_chain_verified": False,
    "full_system_failure_rollback_verified": False,
    "capacity_100_jobs_verified": False,
}

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$"
)
DECIMAL_CNY = re.compile(r"^(0|[1-9]\d*)(?:\.\d{1,6})?$")
MAX_BYTES = 2 * 1024 * 1024
GIT = Path("/usr/bin/git")
PROC_SELF_EXE = Path("/proc/self/exe")
PREDECESSOR_COST_STOP_AUTHORITY_DOMAIN = (
    b"noteai-item26-manual-cost-stop-dependency-authority-v2\0"
)
PREDECESSOR_COST_STOP_MUTATION_IDENTITY_DOMAIN = (
    b"noteai-item26-manual-cost-stop-consumed-mutations-v1\0"
)
PREDECESSOR_COST_STOP_TOKEN_BOUND_MUTATION_IDENTITY_DOMAIN = (
    b"noteai-item26-manual-cost-stop-consumed-mutations-token-bound-v1\0"
)
SUCCESSOR_IDENTITY_DOMAIN = b"noteai-item26-pitr-successor-identity-v1\0"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
ACCEPTANCE_DOMAIN = b"noteai-item26-pitr-terminal-acceptance-v1\0"
RAW_CLOSURE_DOMAIN = b"noteai-item26-raw-closure-v1\0"
NO_REPLAY_REGISTRY_V1_DOMAIN = b"noteai-item26-no-replay-registry-v1\0"
NO_REPLAY_REGISTRY_DOMAIN = b"noteai-item26-no-replay-registry-v2\0"
NO_REPLAY_REGISTRY_V1_FILE_SHA256 = (
    "003a6541e20bce6256f52a4b7bdd0e983997d17af634e113ff7525b5a6bb4535"
)
NO_REPLAY_REGISTRY_V1_SHA256 = (
    "763ae967af95f55347e427f9df8e6c7014b16e645957417915e3ccd44d20e5d9"
)
NO_REPLAY_CONSUMED_MANUAL_MUTATION_SET_SHA256 = (
    "8647c02f5879dcb7a986fc87ce3668ac4e35d63d610c4da1e54a57a8b7263105"
)
EXPECTED_ACTIONS = (
    "successor_preflight",
    "clone_create",
    "clone_terminal_readback",
    "capture_preflight",
    "restored_capture",
    "capture_terminal_readback",
    "reconciliation",
    "deletion_protection_disable",
    "clone_delete",
    "clone_absence_billing_readback",
    "task_resource_cleanup",
    "cleanup_readback",
    "final_baseline",
)
FROZEN_NO_REPLAY_IDENTITIES = (
    (
        "v1_source_capture",
        "CLOUD_ASSISTANT",
        "CONSUMED",
        "TERMINAL_NO_MANIFEST",
        "NONE",
        None,
        None,
    ),
    (
        "v1_source_manifest_readback",
        "CLOUD_ASSISTANT",
        "CONSUMED",
        "TERMINAL_NO_MANIFEST",
        "NONE",
        None,
        None,
    ),
    (
        "v1_source_manifest_diagnostic",
        "CLOUD_ASSISTANT",
        "CONSUMED",
        "TERMINAL_DIAGNOSTIC",
        "NONE",
        None,
        None,
    ),
    (
        "v1_source_manifest_cleanup",
        "CLOUD_ASSISTANT",
        "CONSUMED",
        "TERMINAL_CLEAN",
        "NONE",
        None,
        None,
    ),
    (
        "v2_corrected_recovery",
        "CLOUD_ASSISTANT",
        "CONSUMED",
        "TERMINAL_UNKNOWN",
        "EXACT_EXISTING_IDENTITY_ONLY",
        None,
        None,
    ),
    (
        "v2_corrected_recovery_readback_1",
        "CLOUD_ASSISTANT",
        "CONSUMED",
        "TERMINAL_UNKNOWN_READBACK",
        "EXACT_EXISTING_IDENTITY_ONLY",
        None,
        None,
    ),
    (
        "v2_corrected_recovery_readback_2",
        "CLOUD_ASSISTANT",
        "CONSUMED",
        "TERMINAL_UNKNOWN_READBACK",
        "EXACT_EXISTING_IDENTITY_ONLY",
        None,
        None,
    ),
    (
        "v3_source_capture",
        "CLOUD_ASSISTANT",
        "CONSUMED",
        "TERMINAL_READ_ONLY_PASS",
        "NONE",
        None,
        None,
    ),
    (
        "v3_source_manifest_readback",
        "CLOUD_ASSISTANT",
        "CONSUMED",
        "TERMINAL_READBACK_REQUIRED",
        "NONE",
        None,
        None,
    ),
    (
        "v3_semantic_validator",
        "CLOUD_ASSISTANT",
        "CONSUMED",
        "TERMINAL_UNKNOWN_FALSE_NEGATIVE",
        "EXACT_EXISTING_IDENTITY_ONLY",
        None,
        None,
    ),
    (
        "v3_fixed_timestamp_reader",
        "CLOUD_ASSISTANT",
        "CONSUMED",
        "TERMINAL_READ_ONLY_PASS",
        "NONE",
        None,
        None,
    ),
    (
        "api_c_preflight_v1",
        "CLOUD_ASSISTANT",
        "CONSUMED",
        "TERMINAL_KNOWN_FAIL",
        "NONE",
        None,
        None,
    ),
    (
        "api_c_preflight_v2",
        "CLOUD_ASSISTANT",
        "CONSUMED",
        "TERMINAL_KNOWN_FAIL",
        "NONE",
        None,
        None,
    ),
    (
        "cloud_shell_toolchain_atom_v1",
        "CLOUD_SHELL",
        "CONSUMED",
        "TERMINAL_BLOCKED",
        "NONE",
        None,
        None,
    ),
    (
        "wrapper_parent_diagnostic_v1",
        "CLOUD_ASSISTANT",
        "CONSUMED",
        "TERMINAL_DIAGNOSTIC",
        "NONE",
        None,
        None,
    ),
    (
        "retired_04c_history_probe",
        "CLOUD_ASSISTANT",
        "CONSUMED",
        "TERMINAL_UNKNOWN",
        "EXACT_EXISTING_IDENTITY_ONLY",
        None,
        None,
    ),
    (
        "retired_04c_impact_body",
        "LOCAL_CONTROL_BODY",
        "RETIRED_UNEXECUTED",
        "NO_EXECUTION_AUTHORITY",
        "NONE",
        None,
        None,
    ),
    (
        "failed_ci_checkpoint_a7c3350",
        "CI_CHECKPOINT",
        "RETIRED_FAILED_CI",
        "NO_EXECUTION_AUTHORITY",
        "NONE",
        None,
        None,
    ),
    (
        "failed_ci_checkpoint_7cfe583",
        "CI_CHECKPOINT",
        "RETIRED_FAILED_CI",
        "NO_EXECUTION_AUTHORITY",
        "NONE",
        None,
        None,
    ),
    (
        "original_exact_one_clone_request",
        "RDS_CONTROL_PLANE",
        "CONSUMED",
        "TERMINAL_RESOURCE_CREATED",
        "EXACT_EXISTING_IDENTITY_ONLY",
        None,
        None,
    ),
    (
        "untracked_item26_envelope_rotate_promote",
        "LOCAL_UNTRACKED_ARTIFACT",
        "PRESERVED_UNTRACKED",
        "NO_EXECUTION_AUTHORITY",
        "NONE",
        7971,
        "dbe2c3e8744b1e97b4c244413286ec00ac640b66d96f059417ec17120cf9f8b4",
    ),
    (
        "untracked_item26_envelope_rotate_stage_template",
        "LOCAL_UNTRACKED_ARTIFACT",
        "PRESERVED_UNTRACKED",
        "NO_EXECUTION_AUTHORITY",
        "NONE",
        18240,
        "1c297c3ef7d68879ec6f30499061a14e1cb3d8f8aa0e890ee90c3e3f0bad871d",
    ),
    (
        "untracked_item26_source_manifest_executor",
        "LOCAL_UNTRACKED_ARTIFACT",
        "PRESERVED_UNTRACKED",
        "NO_EXECUTION_AUTHORITY",
        "NONE",
        4550,
        "5ec4984da1094994d7781835d912e6a0c666bf88d124a5cdf304e3b4f1385f97",
    ),
    (
        "untracked_item26_source_manifest_readback",
        "LOCAL_UNTRACKED_ARTIFACT",
        "PRESERVED_HISTORICAL_BYTES",
        "NO_EXECUTION_AUTHORITY",
        "NONE",
        17547,
        "243d7a719da404e245ec8cfee470922502df7bd81aab68957b07b27e81482ba3",
    ),
    (
        "untracked_item26_source_manifest_recovery_executor",
        "LOCAL_UNTRACKED_ARTIFACT",
        "PRESERVED_HISTORICAL_BYTES",
        "NO_EXECUTION_AUTHORITY",
        "NONE",
        9310,
        "dfa4c106bd8cc5bef09c910d236112a9e6d68080142e288395080d6898a027c8",
    ),
)
FROZEN_ADDITIONAL_NO_REPLAY_IDENTITIES = (
    (
        "failed_ci_checkpoint_80c5091",
        "CI_CHECKPOINT",
        "RETIRED_FAILED_CI",
        "NO_EXECUTION_AUTHORITY",
        "NONE",
        40,
        "371114b94400a132e3851a994fca2b7bf9b51df5bc8134c288037dd288188f7c",
    ),
    (
        "failed_ci_checkpoint_41c489c",
        "CI_CHECKPOINT",
        "RETIRED_FAILED_CI",
        "NO_EXECUTION_AUTHORITY",
        "NONE",
        40,
        "2efe397d77cb2b98f882bad32ac47911f3697e239e7bb6386c57eb7c61fef5c6",
    ),
    (
        "manual_cost_stop_protection_disable",
        "RDS_CONTROL_PLANE",
        "CONSUMED",
        "TERMINAL_PROTECTION_FALSE_READBACK",
        "EXACT_EXISTING_IDENTITY_OR_ACTIONTRAIL_ONLY",
        None,
        None,
    ),
    (
        "manual_cost_stop_delete",
        "RDS_CONTROL_PLANE",
        "CONSUMED",
        "TERMINAL_RESOURCE_ABSENT",
        "EXACT_EXISTING_IDENTITY_OR_ACTIONTRAIL_ONLY",
        None,
        None,
    ),
)
CAPTURE_KEYS = {
    "manifest_sha256",
    "postgresql_major_version",
    "server_version_num",
    "table_count",
    "migration_count",
    "rls_table_count",
    "rls_tables",
    "force_rls_table_count",
    "force_rls_tables",
    "owner_role",
    "owner_mismatch_count",
    "reader_role_sha256",
    "reader_superuser",
    "reader_can_login",
    "reader_direct_membership_count",
    "reader_member_of_managed_role",
    "reader_can_set_owner_role",
    "managed_role_can_set_owner_role",
    "session_identity_matches_reader_before_set_role",
    "active_role",
    "public_schema_usage",
    "search_path",
    "row_security",
    "database_connection_count",
    "database_transaction_count",
    "transaction_read_only",
    "transaction_isolation",
    "default_transaction_read_only",
    "rollback_terminal_idle",
    "database_write_count",
    "object_read_mode",
    "object_list_count",
    "object_head_count",
    "object_content_read_count",
    "object_key_emitted_count",
    "object_get_content_count",
    "object_put_count",
    "object_delete_count",
    "object_acl_mutation_count",
    "object_multipart_mutation_count",
    "content_included",
    "object_keys_included",
    "secret_values_included",
}


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _utc(value: Any) -> datetime | None:
    if type(value) is not str or UTC.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    if parsed.tzinfo != timezone.utc or parsed.microsecond != 0:
        return None
    return parsed


def _rfc3339(value: Any) -> datetime | None:
    if type(value) is not str or RFC3339.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed if parsed.tzinfo == timezone.utc else None


def successor_clone_identity_set_sha256(identity: dict[str, Any]) -> str:
    keys = (
        "successor_clone_sha256",
        "successor_clone_name_sha256",
        "successor_clone_create_request_sha256",
        "successor_clone_create_body_sha256",
        "successor_clone_client_token_sha256",
        "restore_time_sha256",
    )
    return _sha(
        SUCCESSOR_IDENTITY_DOMAIN
        + _canonical({key: identity.get(key) for key in keys})[:-1]
    )


def _semantic(value: Any) -> str:
    return _sha(_canonical(value)[:-1])


def _strict(value: Any, expected: Any) -> bool:
    if type(value) is not type(expected):
        return False
    if type(expected) is dict:
        return set(value) == set(expected) and all(
            _strict(value[key], item) for key, item in expected.items()
        )
    if type(expected) is list:
        return len(value) == len(expected) and all(
            _strict(left, right) for left, right in zip(value, expected)
        )
    return value == expected


def _hex64(value: Any) -> bool:
    return type(value) is str and HEX64.fullmatch(value) is not None


def _nonnegative(value: Any) -> bool:
    return type(value) is int and value >= 0


def _stable(row: os.stat_result) -> tuple[int, ...]:
    return (
        row.st_dev,
        row.st_ino,
        row.st_mode,
        row.st_nlink,
        row.st_size,
        row.st_mtime_ns,
    )


def _load(path: Path) -> tuple[dict[str, Any] | None, bytes | None, str | None]:
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o644
        ):
            return None, None, "artifact identity invalid"
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            opened = os.fstat(descriptor)
            raw = b""
            while len(raw) <= MAX_BYTES:
                chunk = os.read(
                    descriptor,
                    min(65536, MAX_BYTES + 1 - len(raw)),
                )
                if not chunk:
                    break
                raw += chunk
            closed = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after = path.lstat()
        if (
            not 1 <= len(raw) <= MAX_BYTES
            or _stable(before) != _stable(opened)
            or _stable(opened) != _stable(closed)
            or _stable(closed) != _stable(after)
        ):
            return None, None, "artifact identity changed"

        def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, item in pairs:
                if key in result:
                    raise ValueError("duplicate key")
                result[key] = item
            return result

        value = json.loads(
            raw.decode("ascii"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("nonfinite number")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return None, None, "cannot read canonical JSON"
    if type(value) is not dict or _canonical(value) != raw:
        return None, None, "JSON is not canonical"
    return value, raw, None


def _terminal_roots_finalized() -> bool:
    return _hex64(EXPECTED_AUTHORITY_ROOT_FILE_SHA256)


def _predecessor_cost_stop_complete(value: Any) -> bool:
    def safe_ref(candidate: Any, prefix: str, suffix: str) -> bool:
        if type(candidate) is not str:
            return False
        parsed = PurePosixPath(candidate)
        return bool(
            str(parsed) == candidate
            and not parsed.is_absolute()
            and ".." not in parsed.parts
            and candidate.startswith(prefix)
            and candidate.endswith(suffix)
        )

    digest_keys = {
        "authority_root",
        "verifier_sha256",
        "builder_sha256",
        "authority_verifier_sha256",
        "raw_extractor_sha256",
        "collector_sha256",
        "root_builder_sha256",
        "activation_receipt_builder_sha256",
        "installer_sha256",
        "bootstrap_sha256",
        "contract_sha256",
        "ci_workflow_sha256",
        "public_root_sha256",
        "no_replay_registry_file_sha256",
        "evidence_sha256",
        "receipt_sha256",
        "checkpoint_sha256",
        "authority_root_file_sha256",
        "authority_root_git_blob_sha256",
        "authority_bundle_file_sha256",
        "activation_receipt_sha256",
        "provider_raw_file_sha256",
        "actiontrail_raw_file_sha256",
        "confirmation_envelope_file_sha256",
        "terminal_acceptance_sha256",
        "old_clone_sha256",
        "old_clone_name_sha256",
        "source_pre_tuple_sha256",
        "source_post_tuple_sha256",
        "billing_snapshot_sha256",
        "no_replay_registry_sha256",
        "old_clone_create_request_sha256",
        "old_clone_create_body_sha256",
        "old_clone_client_token_sha256",
        "protection_disable_request_id_sha256",
        "protection_disable_request_body_sha256",
        "protection_disable_client_token_sha256",
        "delete_request_id_sha256",
        "delete_request_body_sha256",
        "consumed_mutation_identity_set_sha256",
    }
    revision_keys = {
        "control_revision",
        "evidence_revision",
        "terminal_revision",
    }
    return bool(
        type(value) is dict
        and set(value) == set(EXPECTED_PREDECESSOR_COST_STOP)
        and value.get("schema") == PREDECESSOR_COST_STOP_SCHEMA
        and value.get("kind") == PREDECESSOR_COST_STOP_KIND
        and value.get("authority_generation_id")
        == PREDECESSOR_AUTHORITY_GENERATION_ID
        and value.get("authority_epoch_id") == PREDECESSOR_AUTHORITY_EPOCH_ID
        and value.get("activation_receipt_schema")
        == PREDECESSOR_ACTIVATION_RECEIPT_SCHEMA
        and value.get("delete_client_token_present") is False
        and value.get("verifier_path") == MANUAL_COST_STOP_VERIFIER_REF
        and value.get("builder_path") == MANUAL_COST_STOP_BUILDER_REF
        and value.get("authority_verifier_path")
        == MANUAL_COST_STOP_AUTHORITY_VERIFIER_REF
        and value.get("raw_extractor_path") == MANUAL_COST_STOP_RAW_EXTRACTOR_REF
        and value.get("collector_path") == MANUAL_COST_STOP_COLLECTOR_REF
        and value.get("root_builder_path")
        == MANUAL_COST_STOP_ROOT_BUILDER_REF
        and value.get("activation_receipt_builder_path")
        == MANUAL_COST_STOP_ACTIVATION_RECEIPT_BUILDER_REF
        and value.get("installer_path") == MANUAL_COST_STOP_INSTALLER_REF
        and value.get("bootstrap_path") == MANUAL_COST_STOP_BOOTSTRAP_REF
        and value.get("contract_path") == MANUAL_COST_STOP_CONTRACT_REF
        and value.get("ci_workflow_path")
        == MANUAL_COST_STOP_CI_WORKFLOW_REF
        and value.get("public_root_path") == MANUAL_COST_STOP_PUBLIC_ROOT_REF
        and value.get("no_replay_registry_path")
        == MANUAL_COST_STOP_NO_REPLAY_REGISTRY_REF
        and value.get("evidence_path") == MANUAL_COST_STOP_EVIDENCE_REF
        and value.get("receipt_path") == MANUAL_COST_STOP_RECEIPT_REF
        and value.get("checkpoint_path") == MANUAL_COST_STOP_CHECKPOINT_REF
        and safe_ref(value.get("verifier_path"), "tools/", ".py")
        and safe_ref(value.get("builder_path"), "tools/", ".py")
        and safe_ref(value.get("authority_verifier_path"), "tools/", ".py")
        and safe_ref(value.get("raw_extractor_path"), "tools/", ".py")
        and safe_ref(value.get("collector_path"), "tools/", ".py")
        and safe_ref(value.get("root_builder_path"), "tools/", ".py")
        and safe_ref(
            value.get("activation_receipt_builder_path"), "tools/", ".py"
        )
        and safe_ref(value.get("installer_path"), "tools/", ".py")
        and safe_ref(value.get("bootstrap_path"), "tools/", ".py")
        and safe_ref(
            value.get("contract_path"),
            "deploy/production/plans/",
            ".json",
        )
        and safe_ref(
            value.get("ci_workflow_path"),
            ".github/workflows/",
            ".yml",
        )
        and safe_ref(
            value.get("no_replay_registry_path"),
            "deploy/production/plans/",
            ".json",
        )
        and safe_ref(
            value.get("public_root_path"),
            "deploy/production/authorities/",
            ".json",
        )
        and all(_hex64(value.get(key)) for key in digest_keys)
        and all(
            type(value.get(key)) is str
            and HEX40.fullmatch(value[key]) is not None
            for key in revision_keys
        )
        and len({value[key] for key in revision_keys}) == 3
        and _rfc3339(value.get("post_action_observed_at_utc")) is not None
        and type(value.get("manual_terminal_accepted_at_utc")) is str
        and UTC.fullmatch(value["manual_terminal_accepted_at_utc"]) is not None
        and _rfc3339(value["post_action_observed_at_utc"])
        < _utc(value["manual_terminal_accepted_at_utc"])
        and len({
            value["old_clone_create_request_sha256"],
            value["old_clone_create_body_sha256"],
            value["old_clone_client_token_sha256"],
            value["old_clone_name_sha256"],
        }) == 4
        and len({
            value["protection_disable_request_id_sha256"],
            value["protection_disable_request_body_sha256"],
            value["protection_disable_client_token_sha256"],
            value["delete_request_id_sha256"],
            value["delete_request_body_sha256"],
        }) == 5
        and value["source_pre_tuple_sha256"]
        == value["source_post_tuple_sha256"]
        and value["public_root_sha256"]
        == value["authority_root_file_sha256"]
        == value["authority_root_git_blob_sha256"]
        and value["consumed_mutation_identity_set_sha256"]
        == predecessor_cost_stop_mutation_identity_set_sha256(value)
        and value["consumed_mutation_identity_set_sha256"]
        == NO_REPLAY_CONSUMED_MANUAL_MUTATION_SET_SHA256
    )


def predecessor_cost_stop_authority_root(dependency: dict[str, Any]) -> str:
    return _sha(
        PREDECESSOR_COST_STOP_AUTHORITY_DOMAIN
        + _canonical({
            key: dependency[key]
            for key in sorted(dependency)
            if key != "authority_root"
        })[:-1]
    )


def predecessor_cost_stop_mutation_identity_set_sha256(
    dependency: dict[str, Any],
) -> str:
    base_keys = (
        "protection_disable_request_id_sha256",
        "protection_disable_request_body_sha256",
        "protection_disable_client_token_sha256",
        "delete_request_id_sha256",
        "delete_request_body_sha256",
    )
    base_sha256 = _sha(
        PREDECESSOR_COST_STOP_MUTATION_IDENTITY_DOMAIN
        + _canonical({key: dependency.get(key) for key in base_keys})[:-1]
    )
    return _sha(
        PREDECESSOR_COST_STOP_TOKEN_BOUND_MUTATION_IDENTITY_DOMAIN
        + _canonical({
            "delete_client_token_present": dependency.get(
                "delete_client_token_present"
            ),
            "mutation_identity_v1_sha256": base_sha256,
        })[:-1]
    )


def _read_stable_bytes(path: Path) -> bytes:
    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or before.st_nlink != 1
        or stat.S_IMODE(before.st_mode) != 0o644
    ):
        raise ValueError("manual cost-stop predecessor file identity invalid")
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        opened = os.fstat(descriptor)
        raw = b""
        while len(raw) <= MAX_BYTES:
            chunk = os.read(descriptor, min(65536, MAX_BYTES + 1 - len(raw)))
            if not chunk:
                break
            raw += chunk
        closed = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after = path.lstat()
    if (
        not 1 <= len(raw) <= MAX_BYTES
        or _stable(before) != _stable(opened)
        or _stable(opened) != _stable(closed)
        or _stable(closed) != _stable(after)
    ):
        raise ValueError("manual cost-stop predecessor file identity changed")
    return raw


def _git_blob_bytes(
    revision: str,
    path_ref: str,
    *,
    root: Path,
) -> bytes:
    if HEX40.fullmatch(revision or "") is None:
        raise ValueError("manual cost-stop predecessor revision invalid")
    result = subprocess.run(
        [
            str(GIT),
            "--no-replace-objects",
            "show",
            revision + ":" + path_ref,
        ],
        cwd=root,
        env={
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C",
            "LANG": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )
    if result.returncode != 0 or not 1 <= len(result.stdout) <= MAX_BYTES:
        raise ValueError("manual cost-stop predecessor Git blob unavailable")
    return result.stdout


def _git_blob_absent(
    revision: str,
    path_ref: str,
    *,
    root: Path,
) -> bool:
    if HEX40.fullmatch(revision or "") is None:
        raise ValueError("manual cost-stop predecessor revision invalid")
    result = subprocess.run(
        [
            str(GIT),
            "--no-replace-objects",
            "ls-tree",
            "-z",
            "--full-tree",
            revision,
            "--",
            path_ref,
        ],
        cwd=root,
        env={
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C",
            "LANG": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )
    if result.returncode != 0 or len(result.stdout) > MAX_BYTES:
        raise ValueError("manual cost-stop predecessor Git tree unavailable")
    return result.stdout == b""


def _write_exclusive(path: Path, raw: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        offset = 0
        while offset < len(raw):
            offset += os.write(descriptor, raw[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _python_executable_identity(path: Path) -> tuple[Any, ...]:
    """Return a continuity token, not an origin policy, for an executable."""

    try:
        before = path.lstat()
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
    except OSError as exc:
        raise ValueError("isolated Python unavailable") from exc
    digest = hashlib.sha256()
    total = 0
    try:
        opened = os.fstat(descriptor)
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
        closed = os.fstat(descriptor)
    except OSError as exc:
        raise ValueError("isolated Python unavailable") from exc
    finally:
        os.close(descriptor)
    try:
        after = path.lstat()
    except OSError as exc:
        raise ValueError("isolated Python unavailable") from exc

    def identity(row: os.stat_result) -> tuple[int, ...]:
        return (
            row.st_dev,
            row.st_ino,
            row.st_mode,
            row.st_nlink,
            row.st_uid,
            row.st_gid,
            row.st_size,
            row.st_mtime_ns,
            row.st_ctime_ns,
        )

    if (
        not path.is_absolute()
        or not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or not stat.S_IMODE(before.st_mode) & 0o111
        or before.st_size <= 0
        or total != before.st_size
        or identity(before) != identity(opened)
        or identity(opened) != identity(closed)
        or identity(closed) != identity(after)
    ):
        raise ValueError("isolated Python identity invalid")
    return (*identity(opened), digest.hexdigest())


def _run_frozen_predecessor_cost_stop_verifier(
    *,
    verifier_raw: bytes,
    authority_verifier_raw: bytes,
    raw_extractor_raw: bytes,
    root: Path,
) -> tuple[list[str], dict[str, Any] | None]:
    configured_python = Path(sys.executable)
    if not configured_python.is_absolute():
        raise ValueError("isolated Python identity invalid")
    try:
        python = configured_python.resolve(strict=True)
    except OSError as exc:
        raise ValueError("isolated Python unavailable") from exc
    python_identity = _python_executable_identity(python)
    subprocess_executable: str | None = None
    if sys.platform.startswith("linux"):
        try:
            proc_python = PROC_SELF_EXE.resolve(strict=True)
        except OSError as exc:
            raise ValueError("isolated Python unavailable") from exc
        if _python_executable_identity(proc_python) != python_identity:
            raise ValueError("isolated Python identity invalid")
        subprocess_executable = str(PROC_SELF_EXE)
    else:
        python_stat = python.lstat()
        if stat.S_IMODE(python_stat.st_mode) & 0o022:
            raise ValueError("isolated Python identity invalid")
    wrapper = (
        "import runpy,sys;"
        "d=sys.argv[1];p=sys.argv[2];"
        "sys.path.insert(0,d);"
        "sys.argv=[p,*sys.argv[3:]];"
        "runpy.run_path(p,run_name='__main__')"
    )
    with tempfile.TemporaryDirectory(
        prefix="noteai-item26-manual-cost-stop-verifier-"
    ) as directory:
        temp_root = Path(directory)
        verifier_path = temp_root / Path(MANUAL_COST_STOP_VERIFIER_REF).name
        authority_verifier_path = temp_root / Path(
            MANUAL_COST_STOP_AUTHORITY_VERIFIER_REF
        ).name
        raw_extractor_path = temp_root / Path(
            MANUAL_COST_STOP_RAW_EXTRACTOR_REF
        ).name
        _write_exclusive(verifier_path, verifier_raw)
        _write_exclusive(authority_verifier_path, authority_verifier_raw)
        _write_exclusive(raw_extractor_path, raw_extractor_raw)
        arguments = [
            str(python),
            "-I",
            "-S",
            "-B",
            "-c",
            wrapper,
            str(temp_root),
            str(verifier_path),
            "--root",
            str(root.resolve()),
            "--json",
        ]
        run_kwargs: dict[str, Any] = {}
        if subprocess_executable is not None:
            run_kwargs["executable"] = subprocess_executable
        result = subprocess.run(
            arguments,
            cwd=temp_root,
            env={
                "PATH": "/usr/bin:/bin",
                "LC_ALL": "C",
                "LANG": "C",
                "PYTHONHASHSEED": "0",
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
            **run_kwargs,
        )
    if _python_executable_identity(python) != python_identity:
        raise ValueError("isolated Python identity changed")
    if sys.platform.startswith("linux"):
        try:
            proc_python = PROC_SELF_EXE.resolve(strict=True)
        except OSError as exc:
            raise ValueError("isolated Python unavailable") from exc
        if _python_executable_identity(proc_python) != python_identity:
            raise ValueError("isolated Python identity changed")
    if not 1 <= len(result.stdout) <= MAX_BYTES:
        raise ValueError("isolated manual cost-stop verifier output invalid")
    try:
        value = json.loads(result.stdout.decode("ascii"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("isolated manual cost-stop verifier output invalid") from exc
    if (
        type(value) is not dict
        or set(value) != {"errors", "binding"}
        or _canonical(value) != result.stdout
        or type(value["errors"]) is not list
        or any(type(item) is not str or not item for item in value["errors"])
        or (value["binding"] is not None and type(value["binding"]) is not dict)
    ):
        raise ValueError("isolated manual cost-stop verifier output schema mismatch")
    if result.returncode != 0:
        return value["errors"] or ["isolated manual cost-stop verifier rejected"], None
    if value["errors"] or type(value["binding"]) is not dict:
        raise ValueError("isolated manual cost-stop verifier success output mismatch")
    return [], value["binding"]


def validate_predecessor_cost_stop(
    *,
    expected_successor_revision: str,
    root: Path = ROOT,
) -> tuple[list[str], dict[str, Any] | None]:
    if not _predecessor_cost_stop_complete(EXPECTED_PREDECESSOR_COST_STOP):
        return ["Item26 manual cost-stop predecessor is not finalized"], None
    dependency = dict(EXPECTED_PREDECESSOR_COST_STOP)
    if dependency["authority_root"] != predecessor_cost_stop_authority_root(
        dependency
    ):
        return ["Item26 manual cost-stop authority root mismatch"], None
    bindings = (
        ("verifier_path", "verifier_sha256"),
        ("builder_path", "builder_sha256"),
        ("authority_verifier_path", "authority_verifier_sha256"),
        ("raw_extractor_path", "raw_extractor_sha256"),
        ("collector_path", "collector_sha256"),
        ("root_builder_path", "root_builder_sha256"),
        (
            "activation_receipt_builder_path",
            "activation_receipt_builder_sha256",
        ),
        ("installer_path", "installer_sha256"),
        ("bootstrap_path", "bootstrap_sha256"),
        ("contract_path", "contract_sha256"),
        ("ci_workflow_path", "ci_workflow_sha256"),
        ("public_root_path", "public_root_sha256"),
        ("no_replay_registry_path", "no_replay_registry_file_sha256"),
        ("evidence_path", "evidence_sha256"),
        ("receipt_path", "receipt_sha256"),
        ("checkpoint_path", "checkpoint_sha256"),
    )
    try:
        loaded_raw: dict[str, bytes] = {}
        for path_key, digest_key in bindings:
            raw = _read_stable_bytes(root / dependency[path_key])
            loaded_raw[path_key] = raw
            if _sha(raw) != dependency[digest_key]:
                return ["Item26 manual cost-stop predecessor artifact mismatch"], None
        for path_key, digest_key in (
            ("verifier_path", "verifier_sha256"),
            ("builder_path", "builder_sha256"),
            ("authority_verifier_path", "authority_verifier_sha256"),
            ("raw_extractor_path", "raw_extractor_sha256"),
            ("collector_path", "collector_sha256"),
            ("root_builder_path", "root_builder_sha256"),
            (
                "activation_receipt_builder_path",
                "activation_receipt_builder_sha256",
            ),
            ("installer_path", "installer_sha256"),
            ("bootstrap_path", "bootstrap_sha256"),
            ("contract_path", "contract_sha256"),
            ("ci_workflow_path", "ci_workflow_sha256"),
            ("public_root_path", "public_root_sha256"),
            ("no_replay_registry_path", "no_replay_registry_file_sha256"),
        ):
            for revision in (
                dependency["control_revision"],
                dependency["evidence_revision"],
                dependency["terminal_revision"],
                expected_successor_revision,
            ):
                if _sha(
                    _git_blob_bytes(
                        revision,
                        dependency[path_key],
                        root=root,
                    )
                ) != dependency[digest_key]:
                    return ["Item26 manual cost-stop control source drifted"], None
        artifact_bindings = (
            ("evidence_path", "evidence_sha256"),
            ("receipt_path", "receipt_sha256"),
            ("checkpoint_path", "checkpoint_sha256"),
        )
        for path_key, _digest_key in artifact_bindings:
            if not _git_blob_absent(
                dependency["control_revision"],
                dependency[path_key],
                root=root,
            ):
                return [
                    "Item26 manual cost-stop control revision contains terminal artifact"
                ], None
        for path_key, digest_key in artifact_bindings[:2]:
            if _sha(
                _git_blob_bytes(
                    dependency["evidence_revision"],
                    dependency[path_key],
                    root=root,
                )
            ) != dependency[digest_key]:
                return [
                    "Item26 manual cost-stop evidence artifact blob mismatch"
                ], None
        if not _git_blob_absent(
            dependency["evidence_revision"],
            dependency["checkpoint_path"],
            root=root,
        ):
            return [
                "Item26 manual cost-stop checkpoint appeared before terminal revision"
            ], None
        for path_key, digest_key in artifact_bindings:
            if _sha(
                _git_blob_bytes(
                    dependency["terminal_revision"],
                    dependency[path_key],
                    root=root,
                )
            ) != dependency[digest_key]:
                return ["Item26 manual cost-stop terminal artifact blob mismatch"], None
            if _sha(
                _git_blob_bytes(
                    expected_successor_revision,
                    dependency[path_key],
                    root=root,
                )
            ) != dependency[digest_key]:
                return [
                    "Item26 manual cost-stop successor artifact blob mismatch"
                ], None
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return ["Item26 manual cost-stop predecessor unavailable: " + str(exc)], None
    if not (
        _revision_is_strict_ancestor(
            dependency["control_revision"],
            dependency["evidence_revision"],
            root=root,
        )
        and _revision_is_strict_ancestor(
            dependency["evidence_revision"],
            dependency["terminal_revision"],
            root=root,
        )
        and _revision_is_strict_ancestor(
            dependency["terminal_revision"],
            expected_successor_revision,
            root=root,
        )
    ):
        return ["Item26 successor must strictly descend from manual cost-stop terminal"], None
    try:
        errors, binding = _run_frozen_predecessor_cost_stop_verifier(
            verifier_raw=loaded_raw["verifier_path"],
            authority_verifier_raw=loaded_raw["authority_verifier_path"],
            raw_extractor_raw=loaded_raw["raw_extractor_path"],
            root=root,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return ["Item26 isolated manual cost-stop verifier failed: " + str(exc)], None
    if errors or type(binding) is not dict:
        return [
            "Item26 frozen manual cost-stop verifier rejected: "
            + (errors[0] if errors else "binding missing")
        ], None
    expected_binding = {
        "status": "POST_ACTION_RECONCILED_COST_STOP",
        "kind": PREDECESSOR_COST_STOP_KIND,
        "authority_generation_id": PREDECESSOR_AUTHORITY_GENERATION_ID,
        "authority_epoch_id": PREDECESSOR_AUTHORITY_EPOCH_ID,
        "activation_receipt_schema": PREDECESSOR_ACTIVATION_RECEIPT_SCHEMA,
        "activation_receipt_sha256": dependency[
            "activation_receipt_sha256"
        ],
        "terminal_acceptance_sha256": dependency[
            "terminal_acceptance_sha256"
        ],
        "old_clone_sha256": dependency["old_clone_sha256"],
        "old_clone_name_sha256": dependency["old_clone_name_sha256"],
        "source_pre_tuple_sha256": dependency["source_pre_tuple_sha256"],
        "source_post_tuple_sha256": dependency["source_post_tuple_sha256"],
        "billing_snapshot_sha256": dependency["billing_snapshot_sha256"],
        "no_replay_registry_sha256": dependency[
            "no_replay_registry_sha256"
        ],
        "authority_root_file_sha256": dependency[
            "authority_root_file_sha256"
        ],
        "authority_root_git_blob_sha256": dependency[
            "authority_root_git_blob_sha256"
        ],
        "authority_bundle_file_sha256": dependency[
            "authority_bundle_file_sha256"
        ],
        "provider_raw_file_sha256": dependency["provider_raw_file_sha256"],
        "actiontrail_raw_file_sha256": dependency[
            "actiontrail_raw_file_sha256"
        ],
        "confirmation_envelope_file_sha256": dependency[
            "confirmation_envelope_file_sha256"
        ],
        "old_clone_create_request_sha256": dependency[
            "old_clone_create_request_sha256"
        ],
        "old_clone_create_body_sha256": dependency[
            "old_clone_create_body_sha256"
        ],
        "old_clone_client_token_sha256": dependency[
            "old_clone_client_token_sha256"
        ],
        "protection_disable_request_id_sha256": dependency[
            "protection_disable_request_id_sha256"
        ],
        "protection_disable_request_body_sha256": dependency[
            "protection_disable_request_body_sha256"
        ],
        "protection_disable_client_token_sha256": dependency[
            "protection_disable_client_token_sha256"
        ],
        "delete_request_id_sha256": dependency["delete_request_id_sha256"],
        "delete_request_body_sha256": dependency["delete_request_body_sha256"],
        "delete_client_token_present": False,
        "consumed_mutation_identity_set_sha256": dependency[
            "consumed_mutation_identity_set_sha256"
        ],
        "post_action_observed_at_utc": dependency[
            "post_action_observed_at_utc"
        ],
        "terminal_accepted_at_utc": dependency[
            "manual_terminal_accepted_at_utc"
        ],
        "control_revision": dependency["control_revision"],
        "evidence_revision": dependency["evidence_revision"],
        "terminal_revision": dependency["terminal_revision"],
        "readiness": {
            "internal_verified_before": 25,
            "internal_verified_after": 25,
            "internal_total": 29,
            "internal_percentage_after": 86,
            "complete_public_verified_before": 25,
            "complete_public_verified_after": 25,
            "complete_public_total": 38,
            "complete_public_percentage_after": 66,
            "item26_status_before": "unverified",
            "item26_status_after": "unverified",
            "manifest_status_unchanged": True,
            "readiness_credit_added": False,
            "future_successor_requires_new_fee_authorization": True,
        },
        "abort_v1_terminal_authority": False,
        "action_authorization_granted": False,
        "non_clone_resource_disposition": (
            "UNPROVEN_RETAINED_FRESH_PREFLIGHT_REQUIRED"
        ),
    }
    if not _strict(binding, expected_binding):
        return ["Item26 manual cost-stop terminal binding mismatch"], None
    return [], dependency


def terminal_acceptance_sha256(receipt: dict[str, Any]) -> str:
    projection = dict(receipt)
    projection.pop("terminal_acceptance_sha256", None)
    return _sha(ACCEPTANCE_DOMAIN + _canonical(projection))


def raw_closure_sha256(receipt: dict[str, Any]) -> str:
    return _sha(RAW_CLOSURE_DOMAIN + _canonical(receipt["raw_closure"]))


def _no_replay_rows(
    identities: tuple[tuple[Any, ...], ...],
) -> list[dict[str, Any]]:
    return [
        {
            "artifact_bytes": artifact_bytes,
            "artifact_sha256": artifact_sha256,
            "automatic_retry_allowed": False,
            "category": category,
            "consumption_state": consumption_state,
            "key": key,
            "readback_policy": readback_policy,
            "replacement_allowed": False,
            "replay_allowed": False,
            "terminal_class": terminal_class,
        }
        for (
            key,
            category,
            consumption_state,
            terminal_class,
            readback_policy,
            artifact_bytes,
            artifact_sha256,
        ) in identities
    ]


def _expected_no_replay_entries() -> list[dict[str, Any]]:
    return _no_replay_rows(FROZEN_NO_REPLAY_IDENTITIES)


def _expected_additional_no_replay_entries() -> list[dict[str, Any]]:
    return _no_replay_rows(FROZEN_ADDITIONAL_NO_REPLAY_IDENTITIES)


def no_replay_registry_sha256(registry: dict[str, Any]) -> str:
    projection = dict(registry)
    projection.pop("registry_sha256", None)
    return _sha(NO_REPLAY_REGISTRY_DOMAIN + _canonical(projection))


def validate_no_replay_registry_v1(value: Any, raw: bytes) -> list[str]:
    expected_entries = _expected_no_replay_entries()
    expected = {
        "all_replacement_allowed_false": True,
        "all_replay_allowed_false": True,
        "automatic_retry_allowed": False,
        "entries": expected_entries,
        "entry_count": len(expected_entries),
        "registry_sha256": NO_REPLAY_REGISTRY_V1_SHA256,
        "schema": "noteai.item26.no-replay-registry.v1",
        "status": "FROZEN_SOURCE_CHECKPOINT_POLICY",
        "task_id": TASK_ID,
        "unknown_resolution_policy": "EXACT_EXISTING_IDENTITY_READBACK_ONLY",
        "untracked_script_execution_authorized": False,
    }
    if (
        type(raw) is not bytes
        or _sha(raw) != NO_REPLAY_REGISTRY_V1_FILE_SHA256
        or type(value) is not dict
        or not _strict(value, expected)
    ):
        return ["Item26 predecessor no-replay registry mismatch"]
    projection = dict(value)
    projection.pop("registry_sha256")
    if value["registry_sha256"] != _sha(
        NO_REPLAY_REGISTRY_V1_DOMAIN + _canonical(projection)
    ):
        return ["Item26 predecessor no-replay registry digest mismatch"]
    return []


def validate_no_replay_registry(value: Any) -> list[str]:
    added_entries = _expected_additional_no_replay_entries()
    expected = {
        "all_replacement_allowed_false": True,
        "all_replay_allowed_false": True,
        "automatic_retry_allowed": False,
        "consumed_manual_mutation_set_sha256": (
            NO_REPLAY_CONSUMED_MANUAL_MUTATION_SET_SHA256
        ),
        "predecessor_registry_ref": NO_REPLAY_REGISTRY_V1_REF,
        "predecessor_registry_file_sha256": NO_REPLAY_REGISTRY_V1_FILE_SHA256,
        "predecessor_registry_sha256": NO_REPLAY_REGISTRY_V1_SHA256,
        "predecessor_entry_count": len(FROZEN_NO_REPLAY_IDENTITIES),
        "added_entries": added_entries,
        "added_entry_count": len(added_entries),
        "entry_count": len(FROZEN_NO_REPLAY_IDENTITIES) + len(added_entries),
        "registry_sha256": value.get("registry_sha256")
        if type(value) is dict
        else None,
        "schema": NO_REPLAY_REGISTRY_SCHEMA,
        "status": "FROZEN_POST_ACTION_NO_REPLAY_POLICY",
        "task_id": TASK_ID,
        "unknown_resolution_policy": (
            "EXACT_EXISTING_IDENTITY_OR_ACTIONTRAIL_READBACK_ONLY"
        ),
        "untracked_script_execution_authorized": False,
    }
    if type(value) is not dict or not _strict(value, expected):
        return ["Item26 no-replay registry schema mismatch"]
    if not _hex64(value["registry_sha256"]):
        return ["Item26 no-replay registry digest invalid"]
    if value["registry_sha256"] != no_replay_registry_sha256(value):
        return ["Item26 no-replay registry digest mismatch"]
    return []


def _validate_capture(value: Any, label: str) -> list[str]:
    errors: list[str] = []
    if type(value) is not dict or set(value) != CAPTURE_KEYS:
        return [label + " capture schema mismatch"]
    expected = {
        "postgresql_major_version": 16,
        "table_count": 56,
        "migration_count": 17,
        "rls_table_count": 19,
        "rls_tables": list(EXPECTED_RLS_TABLES),
        "force_rls_table_count": 0,
        "force_rls_tables": [],
        "owner_role": "noteai_admin",
        "owner_mismatch_count": 0,
        "reader_superuser": False,
        "reader_can_login": True,
        "reader_direct_membership_count": 1,
        "reader_member_of_managed_role": True,
        "reader_can_set_owner_role": True,
        "managed_role_can_set_owner_role": True,
        "session_identity_matches_reader_before_set_role": True,
        "active_role": "noteai_admin",
        "public_schema_usage": True,
        "search_path": "pg_catalog, public",
        "row_security": "off",
        "database_connection_count": 1,
        "database_transaction_count": 1,
        "transaction_read_only": True,
        "transaction_isolation": "repeatable read",
        "default_transaction_read_only": True,
        "rollback_terminal_idle": True,
        "database_write_count": 0,
        "object_read_mode": "LIST_HEAD_ONLY",
        "object_content_read_count": 0,
        "object_key_emitted_count": 0,
        "object_get_content_count": 0,
        "object_put_count": 0,
        "object_delete_count": 0,
        "object_acl_mutation_count": 0,
        "object_multipart_mutation_count": 0,
        "content_included": False,
        "object_keys_included": False,
        "secret_values_included": False,
    }
    if not _hex64(value.get("manifest_sha256")):
        errors.append(label + " manifest digest invalid")
    if not _hex64(value.get("reader_role_sha256")):
        errors.append(label + " reader role digest invalid")
    if (
        type(value.get("server_version_num")) is not int
        or not 160000 <= value["server_version_num"] < 170000
    ):
        errors.append(label + " server version mismatch")
    if (
        type(value.get("object_list_count")) is not int
        or value["object_list_count"] < 1
        or type(value.get("object_head_count")) is not int
        or value["object_head_count"] < 0
    ):
        errors.append(label + " object inventory read mismatch")
    for key, expected_value in expected.items():
        if type(value.get(key)) is not type(expected_value) or value.get(key) != expected_value:
            errors.append(label + " " + key + " mismatch")
    return errors


def _decimal(value: Any, label: str, errors: list[str]) -> Decimal | None:
    if type(value) is not str or DECIMAL_CNY.fullmatch(value) is None:
        errors.append(label + " is not canonical CNY")
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        errors.append(label + " is invalid")
        return None


def validate_receipt(
    value: Any,
    *,
    expected_execution_revision: str | None = None,
    expected_predecessor_cost_stop: dict[str, Any] | None = None,
    root: Path = ROOT,
) -> tuple[list[str], str | None]:
    errors: list[str] = []
    execution_revision = expected_execution_revision or ""
    top_keys = {
        "schema_version",
        "schema",
        "task_id",
        "status",
        "observed_at_utc",
        "source_revision",
        "source_binding",
        "predecessor_cost_stop",
        "provider_identity",
        "raw_closure",
        "ordered_actions",
        "source_capture",
        "restored_capture",
        "reconciliation",
        "cleanup",
        "cost_boundary",
        "no_replay",
        "execution_boundary",
        "terminal_acceptance_sha256",
    }
    if type(value) is not dict or set(value) != top_keys:
        return ["Item26 receipt schema mismatch"], None
    expected_scalars = {
        "schema_version": 1,
        "schema": RECEIPT_SCHEMA,
        "task_id": TASK_ID,
        "status": "PROVIDER_TERMINAL_VERIFIED_CLEAN",
        "source_revision": execution_revision,
    }
    for key, expected in expected_scalars.items():
        if type(value.get(key)) is not type(expected) or value.get(key) != expected:
            errors.append("receipt " + key + " mismatch")
    if type(value.get("observed_at_utc")) is not str or UTC.fullmatch(
        value["observed_at_utc"]
    ) is None:
        errors.append("receipt observed_at_utc mismatch")

    try:
        expected_tree_sha256, expected_tracked_file_count = git_tree_binding(
            execution_revision,
            root=root,
        )
    except (OSError, ValueError):
        expected_tree_sha256, expected_tracked_file_count = "", -1
        errors.append("receipt source Git tree unavailable")
    source_binding = value.get("source_binding")
    if type(source_binding) is not dict or set(source_binding) != {
        "revision",
        "tree_sha256",
        "tracked_file_count",
        "dirty_path_count",
    }:
        errors.append("receipt source binding schema mismatch")
    elif (
        source_binding["revision"] != execution_revision
        or source_binding["tree_sha256"] != expected_tree_sha256
        or source_binding["tracked_file_count"]
        != expected_tracked_file_count
        or source_binding["dirty_path_count"] != 0
    ):
        errors.append("receipt source binding mismatch")

    dependency = (
        expected_predecessor_cost_stop or EXPECTED_PREDECESSOR_COST_STOP
    )
    if (
        not _predecessor_cost_stop_complete(dependency)
        or not _strict(value.get("predecessor_cost_stop"), dependency)
    ):
        errors.append("receipt strict manual cost-stop predecessor mismatch")

    identity = value.get("provider_identity")
    identity_keys = {
        "source_rds_sha256",
        "successor_clone_sha256",
        "successor_clone_name_sha256",
        "successor_clone_create_request_sha256",
        "successor_clone_create_body_sha256",
        "successor_clone_client_token_sha256",
        "successor_clone_identity_set_sha256",
        "builder_sha256",
        "restore_time_sha256",
        "region_sha256",
        "vpc_sha256",
        "vswitch_set_sha256",
        "postgresql_major_version",
        "private_endpoint_count",
        "public_endpoint_count",
        "source_clone_distinct",
    }
    if type(identity) is not dict or set(identity) != identity_keys:
        errors.append("receipt provider identity schema mismatch")
    elif (
        any(
            not _hex64(identity[key])
            for key in identity_keys
            if key.endswith("_sha256")
        )
        or identity["source_rds_sha256"] == identity["successor_clone_sha256"]
        or identity["postgresql_major_version"] != 16
        or identity["private_endpoint_count"] != 1
        or identity["public_endpoint_count"] != 0
        or identity["source_clone_distinct"] is not True
        or identity["successor_clone_identity_set_sha256"]
        != successor_clone_identity_set_sha256(identity)
        or identity["successor_clone_sha256"]
        == dependency.get("old_clone_sha256")
        or identity["successor_clone_name_sha256"]
        == dependency.get("old_clone_name_sha256")
        or identity["successor_clone_create_request_sha256"]
        == dependency.get("old_clone_create_request_sha256")
        or identity["successor_clone_create_body_sha256"]
        == dependency.get("old_clone_create_body_sha256")
        or identity["successor_clone_client_token_sha256"]
        == dependency.get("old_clone_client_token_sha256")
        or len({
            identity["successor_clone_name_sha256"],
            identity["successor_clone_create_request_sha256"],
            identity["successor_clone_create_body_sha256"],
            identity["successor_clone_client_token_sha256"],
        }) != 4
        or bool(
            {
                identity["successor_clone_sha256"],
                identity["successor_clone_name_sha256"],
                identity["successor_clone_create_request_sha256"],
                identity["successor_clone_create_body_sha256"],
                identity["successor_clone_client_token_sha256"],
            }
            & {
                dependency.get("old_clone_sha256"),
                dependency.get("old_clone_name_sha256"),
                dependency.get("old_clone_create_request_sha256"),
                dependency.get("old_clone_create_body_sha256"),
                dependency.get("old_clone_client_token_sha256"),
            }
        )
    ):
        errors.append("receipt provider identity mismatch")

    raw_closure = value.get("raw_closure")
    if type(raw_closure) is not dict or set(raw_closure) != {
        "provider_response_set_sha256",
        "command_history_sha256",
        "sendfile_history_sha256",
        "billing_readback_sha256",
        "account_inventory_sha256",
        "network_inventory_sha256",
        "successor_clone_identity_set_sha256",
        "fee_authorization_sha256",
        "raw_payload_retained_in_repository",
        "secret_value_emitted_count",
    }:
        errors.append("receipt raw closure schema mismatch")
    elif (
        any(
            not _hex64(raw_closure[key])
            for key in raw_closure
            if key.endswith("_sha256")
        )
        or raw_closure["raw_payload_retained_in_repository"] is not False
        or raw_closure["secret_value_emitted_count"] != 0
        or raw_closure["successor_clone_identity_set_sha256"]
        != (
            identity.get("successor_clone_identity_set_sha256")
            if type(identity) is dict
            else None
        )
        or raw_closure["fee_authorization_sha256"]
        != (
            value["cost_boundary"].get("fee_authorization_sha256")
            if type(value.get("cost_boundary")) is dict
            else None
        )
    ):
        errors.append("receipt raw closure mismatch")

    actions = value.get("ordered_actions")
    action_keys = {
        "name",
        "target_sha256",
        "request_sha256",
        "response_sha256",
        "provider_request_id_sha256",
        "provider_execution_id_sha256",
        "client_token_sha256",
        "terminal_status",
        "exit_code",
        "repeat_count",
        "drop_count",
        "prehistory_count",
        "posthistory_count",
        "automatic_retry_allowed",
        "manual_resend_count",
    }
    if type(actions) is not list or len(actions) != len(EXPECTED_ACTIONS):
        errors.append("receipt ordered action count mismatch")
    else:
        for expected_name, action in zip(EXPECTED_ACTIONS, actions):
            if type(action) is not dict or set(action) != action_keys:
                errors.append("receipt ordered action schema mismatch")
                break
            if (
                action["name"] != expected_name
                or any(
                    not _hex64(action[key])
                    for key in action_keys
                    if key.endswith("_sha256")
                )
                or action["terminal_status"] != "PASS"
                or action["exit_code"] != 0
                or action["repeat_count"] != 1
                or action["drop_count"] != 0
                or action["prehistory_count"] != 0
                or action["posthistory_count"] != 1
                or action["automatic_retry_allowed"] is not False
                or action["manual_resend_count"] != 0
            ):
                errors.append("receipt ordered action mismatch: " + expected_name)
        if type(identity) is dict and len(actions) > 1:
            clone_create = actions[1]
            if type(clone_create) is not dict or (
                clone_create.get("target_sha256")
                != identity.get("successor_clone_name_sha256")
                or clone_create.get("request_sha256")
                != identity.get("successor_clone_create_body_sha256")
                or clone_create.get("provider_request_id_sha256")
                != identity.get("successor_clone_create_request_sha256")
                or clone_create.get("client_token_sha256")
                != identity.get("successor_clone_client_token_sha256")
            ):
                errors.append("receipt successor clone request identity mismatch")

    errors.extend(_validate_capture(value.get("source_capture"), "source"))
    errors.extend(_validate_capture(value.get("restored_capture"), "restored"))

    reconciliation = value.get("reconciliation")
    if type(reconciliation) is not dict or set(reconciliation) != {
        "verified",
        "mismatch_codes",
        "source_manifest_sha256",
        "restored_manifest_sha256",
        "equal_fields",
        "content_included",
    }:
        errors.append("receipt reconciliation schema mismatch")
    elif (
        reconciliation["verified"] is not True
        or reconciliation["mismatch_codes"] != []
        or reconciliation["source_manifest_sha256"]
        != value["source_capture"].get("manifest_sha256")
        or reconciliation["restored_manifest_sha256"]
        != value["restored_capture"].get("manifest_sha256")
        or reconciliation["equal_fields"]
        != [
            "release_commit",
            "database_engine",
            "database_schema",
            "database_migrations",
            "database_tables",
            "database_references",
            "private_objects",
        ]
        or reconciliation["content_included"] is not False
    ):
        errors.append("receipt reconciliation mismatch")

    cleanup = value.get("cleanup")
    cleanup_keys = {
        "successor_clone_absent",
        "clone_billing_closed",
        "builder_stopped_stop_charging",
        "temporary_account_count",
        "ram_role_count",
        "ram_policy_count",
        "ram_attachment_count",
        "task_vswitch_count",
        "temporary_reader_count",
        "key_residue_count",
        "envelope_residue_count",
        "host_residue_count",
        "container_residue_count",
        "process_residue_count",
        "source_rds_unchanged",
        "source_rds_deleted",
        "shared_builder_deleted",
    }
    if type(cleanup) is not dict or set(cleanup) != cleanup_keys:
        errors.append("receipt cleanup schema mismatch")
    elif (
        cleanup["successor_clone_absent"] is not True
        or cleanup["clone_billing_closed"] is not True
        or cleanup["builder_stopped_stop_charging"] is not True
        or any(
            cleanup[key] != 0
            for key in cleanup_keys
            if key.endswith("_count")
        )
        or cleanup["source_rds_unchanged"] is not True
        or cleanup["source_rds_deleted"] is not False
        or cleanup["shared_builder_deleted"] is not False
    ):
        errors.append("receipt cleanup mismatch")

    cost = value.get("cost_boundary")
    cost_keys = {
        "currency",
        "approved_cap_cny",
        "fee_authorization_cap_cny",
        "fee_authorization_sha256",
        "fee_confirmation_sha256",
        "fee_authorization_nonce_sha256",
        "fee_authorization_issued_at_utc",
        "fee_authorization_approved_at_utc",
        "fee_authorization_expires_at_utc",
        "clone_create_started_at_utc",
        "fee_authorization_postdates_manual_cost_stop",
        "actual_incremental_cny",
        "rds_incremental_cny",
        "builder_incremental_cny",
        "disk_incremental_cny",
        "other_incremental_cny",
        "attribution_proven",
        "noncleanup_paid_action_after_breach_count",
    }
    if type(cost) is not dict or set(cost) != cost_keys:
        errors.append("receipt cost boundary schema mismatch")
    else:
        amounts = {
            key: _decimal(cost[key], "receipt " + key, errors)
            for key in cost_keys
            if key.endswith("_cny")
        }
        if (
            cost["currency"] != "CNY"
            or not _hex64(cost["fee_authorization_sha256"])
            or not _hex64(cost["fee_confirmation_sha256"])
            or not _hex64(cost["fee_authorization_nonce_sha256"])
            or cost["fee_authorization_sha256"]
            == cost["fee_confirmation_sha256"]
            or cost["fee_authorization_postdates_manual_cost_stop"] is not True
            or _utc(cost["fee_authorization_issued_at_utc"]) is None
            or _utc(cost["fee_authorization_approved_at_utc"]) is None
            or _utc(cost["fee_authorization_expires_at_utc"]) is None
            or _utc(cost["clone_create_started_at_utc"]) is None
            or _utc(dependency.get("manual_terminal_accepted_at_utc")) is None
            or _utc(value.get("observed_at_utc")) is None
            or not (
                _utc(dependency["manual_terminal_accepted_at_utc"])
                < _utc(cost["fee_authorization_issued_at_utc"])
                == _utc(cost["fee_authorization_approved_at_utc"])
                <= _utc(cost["clone_create_started_at_utc"])
                < _utc(cost["fee_authorization_expires_at_utc"])
                <= _utc(value["observed_at_utc"])
            )
            or _utc(cost["fee_authorization_expires_at_utc"])
            - _utc(cost["fee_authorization_approved_at_utc"])
            > timedelta(minutes=10)
            or cost["attribution_proven"] is not True
            or cost["noncleanup_paid_action_after_breach_count"] != 0
            or any(item is None for item in amounts.values())
        ):
            errors.append("receipt cost boundary mismatch")
        elif (
            amounts["actual_incremental_cny"]
            != amounts["rds_incremental_cny"]
            + amounts["builder_incremental_cny"]
            + amounts["disk_incremental_cny"]
            + amounts["other_incremental_cny"]
            or amounts["actual_incremental_cny"]
            > amounts["approved_cap_cny"]
            or amounts["approved_cap_cny"] <= 0
            or amounts["fee_authorization_cap_cny"]
            != amounts["approved_cap_cny"]
        ):
            errors.append("receipt cost arithmetic mismatch")

    no_replay = value.get("no_replay")
    no_replay_keys = {
        "registry_sha256",
        "historical_entry_count",
        "historical_replay_count",
        "historical_replacement_count",
        "successor_names_disjoint",
        "successor_identity_set_sha256",
        "successor_fee_authorization_nonce_sha256",
        "old_clone_identity_reuse_count",
        "provider_unknown_count",
        "automatic_retry_count",
        "manual_resend_count",
        "second_clone_count",
        "restore_time_change_count",
        "untracked_script_execution_count",
    }
    if type(no_replay) is not dict or set(no_replay) != no_replay_keys:
        errors.append("receipt no-replay schema mismatch")
    elif (
        not _hex64(no_replay["registry_sha256"])
        or not _hex64(no_replay["successor_identity_set_sha256"])
        or not _hex64(no_replay["successor_fee_authorization_nonce_sha256"])
        or no_replay["successor_identity_set_sha256"]
        != (
            identity.get("successor_clone_identity_set_sha256")
            if type(identity) is dict
            else None
        )
        or no_replay["successor_fee_authorization_nonce_sha256"]
        != (
            cost.get("fee_authorization_nonce_sha256")
            if type(cost) is dict
            else None
        )
        or not _nonnegative(no_replay["historical_entry_count"])
        or no_replay["historical_entry_count"] == 0
        or no_replay["successor_names_disjoint"] is not True
        or any(
            no_replay[key] != 0
            for key in no_replay_keys
            if key.endswith("_count") and key != "historical_entry_count"
        )
    ):
        errors.append("receipt no-replay mismatch")

    boundary = value.get("execution_boundary")
    boundary_keys = {
        "clone_create_count",
        "clone_delete_count",
        "builder_start_count",
        "builder_stop_count",
        "cloud_assistant_dispatch_count",
        "sendfile_dispatch_count",
        "database_write_count",
        "object_write_count",
        "persistent_permission_mutation_count",
        "public_request_count",
        "workload_provider_call_count",
        "service_restart_count",
        "automatic_retry_allowed",
    }
    if type(boundary) is not dict or set(boundary) != boundary_keys:
        errors.append("receipt execution boundary schema mismatch")
    elif (
        boundary["clone_create_count"] != 1
        or boundary["clone_delete_count"] != 1
        or any(
            not _nonnegative(boundary[key])
            for key in boundary_keys
            if key.endswith("_count")
        )
        or any(
            boundary[key] != 0
            for key in (
                "database_write_count",
                "object_write_count",
                "persistent_permission_mutation_count",
                "public_request_count",
                "workload_provider_call_count",
                "service_restart_count",
            )
        )
        or boundary["automatic_retry_allowed"] is not False
    ):
        errors.append("receipt execution boundary mismatch")

    computed = terminal_acceptance_sha256(value)
    if not _hex64(value.get("terminal_acceptance_sha256")) or value[
        "terminal_acceptance_sha256"
    ] != computed:
        errors.append("receipt terminal acceptance mismatch")
    return errors, computed if not errors else None


def validate_evidence(
    value: Any,
    receipt: dict[str, Any],
    receipt_raw: bytes,
    *,
    expected_execution_revision: str,
) -> list[str]:
    top_keys = {
        "schema_version",
        "schema",
        "task_id",
        "status",
        "source_revision",
        "provider_receipt",
        "external_authority",
        "restore_provenance",
        "source_state",
        "restored_state",
        "reconciliation",
        "cleanup",
        "final_runtime_state",
        "cost_and_data_boundary",
        "no_replay",
        "secret_free_evidence",
        "readiness",
    }
    if type(value) is not dict or set(value) != top_keys:
        return ["Item26 evidence schema mismatch"]
    errors: list[str] = []
    expected = {
        "schema_version": 1,
        "schema": EVIDENCE_SCHEMA,
        "task_id": TASK_ID,
        "status": "PASS",
        "source_revision": expected_execution_revision,
    }
    for key, item in expected.items():
        if type(value.get(key)) is not type(item) or value.get(key) != item:
            errors.append("evidence " + key + " mismatch")
    provider_receipt = value.get("provider_receipt")
    if not _strict(
        provider_receipt,
        {
            "file_sha256": _sha(receipt_raw),
            "semantic_sha256": _semantic(receipt),
            "terminal_acceptance_sha256": receipt[
                "terminal_acceptance_sha256"
            ],
        },
    ):
        errors.append("evidence provider receipt mismatch")
    if not _strict(
        value.get("external_authority"),
        {
            "required": True,
            "provider_authority": "DETACHED_ROOT_OWNED",
            "confirmation_authority": "DETACHED_ROOT_OWNED",
            "ci_authority": "DETACHED_ROOT_OWNED",
            "mathematically_distinct_key_count": 3,
        },
    ):
        errors.append("evidence external authority contract mismatch")
    if not _strict(value.get("restore_provenance"), receipt["provider_identity"]):
        errors.append("evidence restore provenance mismatch")
    if not _strict(value.get("source_state"), receipt["source_capture"]):
        errors.append("evidence source state mismatch")
    if not _strict(value.get("restored_state"), receipt["restored_capture"]):
        errors.append("evidence restored state mismatch")
    if not _strict(value.get("reconciliation"), receipt["reconciliation"]):
        errors.append("evidence reconciliation mismatch")
    if not _strict(value.get("cleanup"), receipt["cleanup"]):
        errors.append("evidence cleanup mismatch")
    if not _strict(
        value.get("final_runtime_state"),
        {
            "source_rds_status": "Running",
            "successor_clone_absent": True,
            "builder_status": "Stopped_StopCharging",
            "active_task_container_count": 0,
            "active_task_process_count": 0,
            "established_5432_count": 0,
        },
    ):
        errors.append("evidence final runtime state mismatch")
    if not _strict(
        value.get("cost_and_data_boundary"),
        {
            **receipt["cost_boundary"],
            "database_write_count": 0,
            "object_write_count": 0,
            "public_request_count": 0,
            "workload_provider_call_count": 0,
        },
    ):
        errors.append("evidence cost/data boundary mismatch")
    if not _strict(value.get("no_replay"), receipt["no_replay"]):
        errors.append("evidence no-replay mismatch")
    if not _strict(
        value.get("secret_free_evidence"),
        {
            "secret_value_count": 0,
            "password_value_count": 0,
            "private_key_value_count": 0,
            "connection_string_value_count": 0,
            "database_row_value_count": 0,
            "object_key_value_count": 0,
            "raw_provider_payload_count": 0,
        },
    ):
        errors.append("evidence Secret-free contract mismatch")
    if not _strict(value.get("readiness"), DEFAULT_READINESS):
        errors.append("evidence readiness mismatch")
    return errors


def validate_checkpoint(
    value: Any,
    evidence: dict[str, Any],
    evidence_raw: bytes,
    receipt: dict[str, Any],
    receipt_raw: bytes,
    *,
    expected_execution_revision: str,
    expected_evidence_revision: str,
) -> list[str]:
    expected = {
        "schema": CHECKPOINT_SCHEMA,
        "task_id": TASK_ID,
        "status": "EVIDENCE_CHECKPOINT_EXACT_HEAD_CI_ACCEPTED",
        "execution_revision": expected_execution_revision,
        "evidence_revision": expected_evidence_revision,
        "evidence_file_sha256": _sha(evidence_raw),
        "evidence_semantic_sha256": _semantic(evidence),
        "receipt_file_sha256": _sha(receipt_raw),
        "receipt_semantic_sha256": _semantic(receipt),
        "terminal_acceptance_sha256": receipt[
            "terminal_acceptance_sha256"
        ],
        "automatic_retry_allowed": False,
        "readiness_credit_added": False,
    }
    return [] if _strict(value, expected) else ["Item26 terminal checkpoint mismatch"]


def validate_manifest_evidence(
    entries: Any,
    *,
    root: Path = ROOT,
) -> tuple[list[str], str | None]:
    if not _terminal_roots_finalized():
        return ["Item26 terminal semantic verifier is not finalized"], None
    authority_errors, authority = validate_authority_bundle(
        expected_authority_root_file_sha256=(
            EXPECTED_AUTHORITY_ROOT_FILE_SHA256
        ),
        root=root,
    )
    if authority_errors or authority is None:
        return authority_errors or ["Item26 external authority missing"], None
    if type(entries) is not list:
        return ["Item26 manifest evidence must be a list"], None
    execution_revision = authority["execution_revision"]
    evidence_revision = authority["evidence_revision"]
    terminal_revision = authority["terminal_revision"]
    actual = [
        (row.get("kind"), row.get("ref"))
        for row in entries
        if type(row) is dict and set(row) == {"kind", "ref"}
    ]
    expected = {
        ("git", execution_revision),
        ("git", evidence_revision),
        ("git", terminal_revision),
        *(("path", ref) for ref in REQUIRED_MANIFEST_PATH_REFS),
    }
    if len(actual) != len(entries) or len(set(actual)) != len(actual) or set(actual) != expected:
        return ["Item26 exact terminal evidence refs required"], None
    artifact_specs = (
        (EVIDENCE_REF, authority["evidence_file_sha256"]),
        (RECEIPT_REF, authority["receipt_file_sha256"]),
        (
            TERMINAL_CHECKPOINT_REF,
            authority["checkpoint_file_sha256"],
        ),
        (
            NO_REPLAY_REGISTRY_REF,
            authority["no_replay_registry_file_sha256"],
        ),
        (
            NO_REPLAY_REGISTRY_V1_REF,
            authority["predecessor_no_replay_registry_file_sha256"],
        ),
    )
    loaded: dict[str, tuple[dict[str, Any], bytes]] = {}
    for ref, expected_sha256 in artifact_specs:
        value, raw, error = _load(root / ref)
        if error or value is None or raw is None:
            return ["Item26 " + ref + ": " + (error or "missing")], None
        if _sha(raw) != expected_sha256:
            return ["Item26 terminal artifact file hash mismatch"], None
        loaded[ref] = (value, raw)
    evidence, evidence_raw = loaded[EVIDENCE_REF]
    receipt, receipt_raw = loaded[RECEIPT_REF]
    checkpoint, _checkpoint_raw = loaded[TERMINAL_CHECKPOINT_REF]
    registry, _registry_raw = loaded[NO_REPLAY_REGISTRY_REF]
    predecessor_registry, predecessor_registry_raw = loaded[
        NO_REPLAY_REGISTRY_V1_REF
    ]
    predecessor_registry_errors = validate_no_replay_registry_v1(
        predecessor_registry,
        predecessor_registry_raw,
    )
    if predecessor_registry_errors:
        return predecessor_registry_errors, None
    predecessor_errors, predecessor_cost_stop = validate_predecessor_cost_stop(
        expected_successor_revision=execution_revision,
        root=root,
    )
    if predecessor_errors or predecessor_cost_stop is None:
        return predecessor_errors or [
            "Item26 terminal manual cost-stop predecessor missing"
        ], None
    if (
        authority.get("predecessor_cost_stop_authority_root")
        != predecessor_cost_stop["authority_root"]
        or authority.get("predecessor_cost_stop_terminal_acceptance_sha256")
        != predecessor_cost_stop["terminal_acceptance_sha256"]
    ):
        return ["Item26 provider authority manual predecessor mismatch"], None
    receipt_errors, acceptance = validate_receipt(
        receipt,
        expected_execution_revision=execution_revision,
        expected_predecessor_cost_stop=predecessor_cost_stop,
        root=root,
    )
    if receipt_errors or acceptance is None:
        return receipt_errors or ["Item26 receipt acceptance missing"], None
    if acceptance != authority["terminal_acceptance_sha256"]:
        return ["Item26 frozen terminal acceptance mismatch"], None
    if raw_closure_sha256(receipt) != authority["raw_closure_sha256"]:
        return ["Item26 provider raw closure binding mismatch"], None
    if (
        authority.get("successor_clone_identity_set_sha256")
        != receipt["provider_identity"]["successor_clone_identity_set_sha256"]
        or authority.get("successor_fee_authorization_sha256")
        != receipt["cost_boundary"]["fee_authorization_sha256"]
        or authority.get("fee_confirmation_sha256")
        != receipt["cost_boundary"]["fee_confirmation_sha256"]
        or authority.get("fee_authorization_nonce_sha256")
        != receipt["cost_boundary"]["fee_authorization_nonce_sha256"]
        or authority.get("fee_authorization_cap_cny")
        != receipt["cost_boundary"]["fee_authorization_cap_cny"]
        or authority.get("fee_authorization_approved_at_utc")
        != receipt["cost_boundary"]["fee_authorization_approved_at_utc"]
        or authority.get("fee_authorization_expires_at_utc")
        != receipt["cost_boundary"]["fee_authorization_expires_at_utc"]
        or authority.get("successor_confirmation_export_semantic_sha256")
        != authority.get("confirmation_export_semantic_sha256")
    ):
        return ["Item26 provider successor authorization mismatch"], None
    result_errors = validate_terminal_result(
        source_manifest=authority["source_manifest"],
        restored_manifest=authority["restored_manifest"],
        source_capture=receipt.get("source_capture"),
        restored_capture=receipt.get("restored_capture"),
        reconciliation=receipt.get("reconciliation"),
        expected_execution_revision=execution_revision,
    )
    if result_errors:
        return result_errors, None
    evidence_errors = validate_evidence(
        evidence,
        receipt,
        receipt_raw,
        expected_execution_revision=execution_revision,
    )
    if evidence_errors:
        return evidence_errors, None
    checkpoint_errors = validate_checkpoint(
        checkpoint,
        evidence,
        evidence_raw,
        receipt,
        receipt_raw,
        expected_execution_revision=execution_revision,
        expected_evidence_revision=evidence_revision,
    )
    if checkpoint_errors:
        return checkpoint_errors, None
    registry_errors = validate_no_replay_registry(registry)
    if registry_errors:
        return registry_errors, None
    if (
        registry["registry_sha256"]
        != receipt["no_replay"]["registry_sha256"]
        or registry["entry_count"]
        != receipt["no_replay"]["historical_entry_count"]
    ):
        return ["Item26 no-replay registry mismatch"], None
    return [], acceptance


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        default=str(
            ROOT / "deploy" / "production" / "internal-deployment-readiness.json"
        ),
    )
    args = parser.parse_args()
    try:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        controls = [
            control
            for layer in manifest["layers"]
            for control in layer["controls"]
            if control.get("id") == "backup_pitr_restore"
        ]
        if len(controls) != 1:
            raise ValueError("exact Item26 control required")
        entries = controls[0].get("evidence")
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print("pitr_restore_evidence=FAIL")
        print("- Item26 readiness manifest unavailable: " + str(exc))
        return 1
    errors, acceptance = validate_manifest_evidence(entries)
    if errors or acceptance is None:
        print("pitr_restore_evidence=FAIL")
        for error in errors:
            print("- " + error)
        return 1
    print("pitr_restore_evidence=PASS")
    print("terminal_acceptance_sha256=" + acceptance)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
