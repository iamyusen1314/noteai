#!/usr/bin/env python3
"""Fail-closed v2 authority boundary for the Item 26 cost-stop readback.

The tracked public root is complete and hash-frozen, but this root-bearing
revision still requires its own attempt-one push/PR dual-green CI before a
receipt can be signed or any runtime installation can start.  Production
entry points call :func:`_require_finalized` before filesystem or Git I/O.
There is deliberately no v1 authority/collector compatibility fallback.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "PROD-FIRST-LAUNCH-PITR-RESTORE-001"
OPERATION_ID = TASK_ID + ":MANUAL-POST-ACTION-COST-STOP:v1"
AUTHORITY_GENERATION_ID = (
    TASK_ID + ":MANUAL-POST-ACTION-COST-STOP-AUTHORITY:v2"
)
AUTHORITY_EPOCH_ID = "noteai.item26.manual-cost-stop-authority-generation.v2"
AUTHORITY_EPOCH = AUTHORITY_EPOCH_ID

REPOSITORY = "iamyusen1314/noteai"
SOURCE_REF = "refs/heads/codex/quality-stabilization-real-chain"
LEDGER_STOP_REVISION = "653a4f350c679dff047426e0c0c5969461bd39fc"
A0_REVISION = "34bfcf029d7ba641728fc18777b11943cb02fe1d"
A1_REVISION = "db7b99d86e4fcf022e243ad1833c5f5d01d97095"
A2_REVISION = "72e356fe5e8bcde14cea9153227881504d2a3afc"
BOOTSTRAP_AUTHORIZATION_ANCHOR_REVISION = (
    "2cfd03a9968f3ac5c2146a12377620aef7aed8e1"
)
REJECTED_BOOTSTRAP_SOURCE_REVISION = (
    "514fbe075fe96096d641595a87423af4418ed90a"
)
HELPER_SOURCE_ACCEPTED_REVISION = (
    "b2d2e89d76f311350468cc3f1e8c20988796e923"
)
BOOTSTRAP_LEDGER_ACCEPTANCE_REVISION = (
    "4eab99188332b156fde0f8892daa668375fff245"
)
REJECTED_ROOT_ACTIVATION_REVISION = (
    "78828093048c8b2f2dccd111412703f068155543"
)

COLLECTOR_REF = "tools/collect_item26_manual_cost_stop_raw_v2.py"
EXTRACTOR_REF = "tools/extract_item26_manual_cost_stop_raw_v2.py"
VERIFIER_REF = "tools/verify_item26_manual_cost_stop_authority_v2.py"
ROOT_BUILDER_REF = "tools/build_item26_manual_cost_stop_authority_root_v2.py"
RECEIPT_BUILDER_REF = (
    "tools/build_item26_manual_cost_stop_activation_receipt_v3.py"
)
EVIDENCE_VERIFIER_REF = "tools/verify_item26_manual_cost_stop_evidence_v2.py"
EVIDENCE_BUILDER_REF = "tools/build_item26_manual_cost_stop_evidence_v2.py"
INSTALLER_REF = "tools/install_item26_manual_cost_stop_runtime_v3.py"
BOOTSTRAP_REF = "tools/bootstrap_item26_manual_cost_stop_keys_v2.py"
CONTRACT_REF = "deploy/production/plans/item26-manual-cost-stop-contract-v2.json"
NO_REPLAY_REF = "deploy/production/plans/item26-no-replay-registry-v2.json"
PUBLIC_ROOT_REF = (
    "deploy/production/authorities/"
    "item26-manual-cost-stop-authority-root-v2.json"
)
CI_WORKFLOW_REF = ".github/workflows/ci.yml"
HANDOFF_REF = ".codex/handoffs/current-task.md"
RISK_REGISTER_REF = ".codex/notes/risk-register.md"
READINESS_MANIFEST_REF = "deploy/production/internal-deployment-readiness.json"

AUTHORITY_DIRECTORY = Path(
    "/Library/Application Support/NoteAI/item26-manual-cost-stop-v2"
)
RUNTIME_DIRECTORY = Path(
    "/Library/Application Support/NoteAI/item26-manual-cost-stop-v2-tools"
)
CUSTODY_DIRECTORY = Path(
    "/Library/Application Support/NoteAI/item26-manual-cost-stop-v2-custody"
)
JOURNAL_DIRECTORY = Path(
    "/Library/Application Support/NoteAI/item26-manual-cost-stop-v2-journal"
)
ROOT_FILE = "authority-root-v2.json"
PROVIDER_RAW_FILE = "provider-raw-v2.json"
ACTIONTRAIL_RAW_FILE = "actiontrail-raw-v2.json"
CONFIRMATION_FILE = "confirmation-envelope-v2.json"
BUNDLE_FILE = "authority-bundle-v2.json"
ACTIVATION_RECEIPT_FILE = "runtime-activation-receipt-v3.json"
ACTIVATION_INVENTORY = (ROOT_FILE,)
CAPTURE_INVENTORY = (ROOT_FILE, PROVIDER_RAW_FILE, ACTIONTRAIL_RAW_FILE)
FINAL_INVENTORY = (
    ROOT_FILE,
    PROVIDER_RAW_FILE,
    ACTIONTRAIL_RAW_FILE,
    CONFIRMATION_FILE,
    BUNDLE_FILE,
)
RUNTIME_INVENTORY = (
    Path(COLLECTOR_REF).name,
    Path(EXTRACTOR_REF).name,
    Path(VERIFIER_REF).name,
    ACTIVATION_RECEIPT_FILE,
)

ROOT_SCHEMA = "noteai.item26.manual-cost-stop-authority-root.v2"
ACTIVATION_RECEIPT_SCHEMA = (
    "noteai.item26.manual-cost-stop-runtime-activation-receipt.v3"
)
ACTIVATION_RECEIPT_ENVELOPE_SCHEMA = (
    "noteai.item26.manual-cost-stop-runtime-activation-envelope.v3"
)
CONTEXT_ENVELOPE_SCHEMA = (
    "noteai.item26.manual-cost-stop-context-signed-envelope.v2"
)
PROVIDER_SCHEMA = "noteai.item26.manual-cost-stop-provider-authority.v2"
CONFIRMATION_SCHEMA = (
    "noteai.item26.manual-cost-stop-confirmation-authority.v2"
)
LOCAL_CI_SCHEMA = "noteai.item26.manual-cost-stop-local-ci-authority.v2"
BUNDLE_SCHEMA = "noteai.item26.manual-cost-stop-authority-bundle.v2"
RECEIPT_REF = (
    "deploy/production/evidence/"
    "item26-manual-cost-stop-provider-receipt-v2-20260817.json"
)
EVIDENCE_REF = (
    "deploy/production/evidence/"
    "production-item26-manual-cost-stop-v2-20260817.json"
)
CHECKPOINT_REF = (
    "deploy/production/evidence/"
    "item26-manual-cost-stop-terminal-checkpoint-v2-20260817.json"
)
RECEIPT_SIGNATURE_DOMAIN_TEXT = (
    "noteai-item26-manual-cost-stop-runtime-activation-receipt-v3"
)
RECEIPT_SIGNATURE_DOMAIN = (
    RECEIPT_SIGNATURE_DOMAIN_TEXT.encode("ascii") + b"\0"
)

# Filled only after the complete canonical public root is generated.  The
# public root itself never embeds this digest, avoiding a hash self-reference.
EXPECTED_ROOT_SHA = (
    "8bfb8834c1e241a18cde984d42524759f53423bcf809dd8657fa4b2be102ff85"
)
EXPECTED_AUTHORITY_ROOT_FILE_SHA256 = EXPECTED_ROOT_SHA
AUTHORITY_V2_FINALIZED = True
AUTHORITY_IMPLEMENTED = AUTHORITY_V2_FINALIZED
ROOT_UID = 0
EXPECTED_CONTRACT_FILE_SHA256 = (
    "190ed155a410b20c1b081b5bc090bbc4c4a6609789d94c51296ce1460bc5ffd1"
)
EXPECTED_BOOTSTRAP_GIT_BLOB_OID = (
    "e2b0b04f2bc5d8dc80185e29c059699209f2965f"
)
EXPECTED_BOOTSTRAP_FILE_SHA256 = (
    "2e35d16c2a2f55ddfa1436190ed8869449dd05fb8ae5fb45878ab9c50c0cd9ff"
)
EXPECTED_BOOTSTRAP_FILE_BYTES = 26443
EXPECTED_NO_REPLAY_FILE_SHA256 = (
    "994c521e22abd9be0c88d4b252ce4d3ef9a47f8131a065ab7964018f224d0f47"
)
EXPECTED_NO_REPLAY_REGISTRY_SHA256 = (
    "93abb46e3e329dd28edab6bab14ec6c1a09177d0effe0e80d881d43f1e878be5"
)
EXPECTED_V1_ROOT_FILE_SHA256 = (
    "f0f7cfce319009ad696cf762f30ca25b2f237d4bda2f4f0643baeea409514f3c"
)
EXPECTED_HISTORICAL_CONFIRMATION_SHA256 = (
    "0b2a6a3e3a20b1e9faf94affd8b966082ba58530268f5850b05cc9b1655c1479"
)
EXPECTED_MUTATION_SET_SHA256 = (
    "8647c02f5879dcb7a986fc87ce3668ac4e35d63d610c4da1e54a57a8b7263105"
)
EXPECTED_SOURCE_PRE_TUPLE_SHA256 = (
    "7b19a9ce8091ef52b11cd722d3d3a52671ba7888811ad47adbbae80abe5d5771"
)

PROVIDER_PAYLOAD_KEYS = {
    "schema",
    "task_id",
    "historical_operation_id",
    "authority_generation_id",
    "authority_epoch_id",
    "control_revision",
    "observed_at_utc",
    "signed_at_utc",
    "authority_root_file_sha256",
    "authority_root_git_blob_sha256",
    "activation_receipt_sha256",
    "provider_raw_file_sha256",
    "actiontrail_raw_file_sha256",
    "provider_projection_sha256",
    "actiontrail_projection_sha256",
    "receipt_file_sha256",
    "receipt_semantic_sha256",
    "terminal_acceptance_sha256",
    "raw_closure_sha256",
    "confirmation_export_semantic_sha256",
    "historical_user_confirmation_sha256",
    "no_replay_registry_sha256",
    "consumed_mutation_identity_set_sha256",
    "old_clone_sha256",
    "old_clone_name_sha256",
    "old_clone_create_request_sha256",
    "old_clone_create_body_sha256",
    "old_clone_client_token_sha256",
    "protection_disable_request_id_sha256",
    "protection_disable_request_body_sha256",
    "protection_disable_client_token_sha256",
    "delete_request_id_sha256",
    "delete_request_body_sha256",
    "delete_client_token_present",
    "source_pre_tuple_sha256",
    "source_post_tuple_sha256",
    "billing_snapshot_sha256",
    "old_clone_absent",
    "source_unchanged",
    "historical_billing_only",
    "new_action_authorized",
    "readiness_credit_added",
}
CONFIRMATION_PAYLOAD_KEYS = {
    "schema",
    "task_id",
    "historical_operation_id",
    "authority_generation_id",
    "authority_epoch_id",
    "control_revision",
    "confirmed_at_utc",
    "post_action_observed_at_utc",
    "authority_root_file_sha256",
    "authority_root_git_blob_sha256",
    "activation_receipt_sha256",
    "provider_raw_file_sha256",
    "actiontrail_raw_file_sha256",
    "provider_projection_sha256",
    "actiontrail_projection_sha256",
    "receipt_file_sha256",
    "receipt_semantic_sha256",
    "terminal_acceptance_sha256",
    "raw_closure_sha256",
    "historical_user_confirmation_sha256",
    "no_replay_registry_sha256",
    "consumed_mutation_identity_set_sha256",
    "retroactive_action_authorization",
    "new_action_authorization",
    "readiness_credit_added",
}
LOCAL_CI_PAYLOAD_KEYS = {
    "schema",
    "task_id",
    "historical_operation_id",
    "authority_generation_id",
    "authority_epoch_id",
    "status",
    "control_revision",
    "evidence_revision",
    "terminal_revision",
    "repository",
    "source_ref",
    "authority_root_file_sha256",
    "authority_root_git_blob_sha256",
    "activation_receipt_sha256",
    "provider_export_semantic_sha256",
    "confirmation_export_semantic_sha256",
    "provider_raw_file_sha256",
    "actiontrail_raw_file_sha256",
    "provider_projection_sha256",
    "actiontrail_projection_sha256",
    "receipt_file_sha256",
    "receipt_semantic_sha256",
    "terminal_acceptance_sha256",
    "raw_closure_sha256",
    "evidence_file_sha256",
    "checkpoint_file_sha256",
    "control_sources",
    "control_push",
    "control_pull_request",
    "evidence_push",
    "evidence_pull_request",
    "terminal_push",
    "terminal_pull_request",
    "terminal_accepted_at_utc",
}

ROLE_NAMES = ("provider", "confirmation", "local_ci_observation")
SIGNATURE_ALGORITHM = "RSASSA-PKCS1-v1_5-SHA256"
ROLE_SIGNATURE_DOMAIN_TEXT = {
    "provider": "noteai-item26-manual-cost-stop-provider-authority-v2",
    "confirmation": (
        "noteai-item26-manual-cost-stop-confirmation-authority-v2"
    ),
    "local_ci_observation": (
        "noteai-item26-manual-cost-stop-local-ci-observation-authority-v2"
    ),
}
ROLE_SIGNATURE_DOMAINS = {
    role: text.encode("ascii") + b"\0"
    for role, text in ROLE_SIGNATURE_DOMAIN_TEXT.items()
}
ROLE_ISSUERS = {
    role: f"noteai-item26-manual-cost-stop-{role.replace('_', '-')}-v2"
    for role in ROLE_NAMES
}
ROLE_AUDIENCE = "noteai-item26-manual-cost-stop-verifier-v2"

LEDGER_STOP_BINDINGS = {
    HANDOFF_REF: {
        "git_blob_oid": "cbfcaa05ae21054b1f54d4c5a769d09ebb94942d",
        "file_sha256": (
            "23547b18e4561c4bb4cddb1822ea7daa296df866822cd00f77f6a8d0bc429d63"
        ),
    },
    RISK_REGISTER_REF: {
        "git_blob_oid": "5b661b7a0756e69cb2173479ca4d775e5d055f89",
        "file_sha256": (
            "2f7305d33e59efab0d77296c580481dfa1c1a76160cd71ecd2e86a924ad0cdc2"
        ),
    },
    READINESS_MANIFEST_REF: {
        "git_blob_oid": "2c2d28500c631123817f6e7fbac06aabef9d9b26",
        "file_sha256": (
            "8eed4acc60cb4f99b584f2ebe84b0b8da79da9ebecdecdca3ed055c2dcbdcf8e"
        ),
    },
}

EXPECTED_A0_TERMINAL = {
    "revision": A0_REVISION,
    "native_dispatch_count": 2,
    "push": {
        "run_id": 31969004410,
        "job_id": 95218382487,
        "event": "push",
        "attempt": 1,
        "status": "completed",
        "conclusion": "success",
        "head_sha": A0_REVISION,
        "workflow_name": "CI",
        "workflow_path": CI_WORKFLOW_REF,
        "job_name": "test",
        "completed_at_utc": "2026-08-16T20:26:05Z",
        "dispatch_count": 1,
        "rerun_count": 0,
    },
    "pull_request": {
        "run_id": 31969006941,
        "job_id": 95218387957,
        "event": "pull_request",
        "attempt": 1,
        "status": "completed",
        "conclusion": "cancelled",
        "head_sha": A0_REVISION,
        "workflow_name": "CI",
        "workflow_path": CI_WORKFLOW_REF,
        "job_name": "test",
        "completed_at_utc": "2026-08-16T20:30:28Z",
        "timeout_minutes": 35,
        "timeout_annotation": (
            "The job has exceeded the maximum execution time of 35m0s"
        ),
        "dispatch_count": 1,
        "rerun_count": 0,
    },
    "rerun_allowed": False,
    "replacement_required": True,
}

EXPECTED_A1_TERMINAL = {
    "revision": A1_REVISION,
    "native_dispatch_count": 2,
    "push": {
        "run_id": 31976746482,
        "job_id": 95237268946,
        "event": "push",
        "attempt": 1,
        "status": "completed",
        "conclusion": "failure",
        "head_sha": A1_REVISION,
        "workflow_name": "CI",
        "workflow_path": CI_WORKFLOW_REF,
        "job_name": "test",
        "created_at_utc": "2026-08-16T22:35:12Z",
        "started_at_utc": "2026-08-16T22:35:15Z",
        "completed_at_utc": "2026-08-16T23:05:35Z",
        "failure_class": "UNIT_TEST_STEP_NONZERO_EXIT",
        "failed_step_name": "Unit tests",
        "failure_annotation": "Process completed with exit code 1.",
        "unit_test_count": 2413,
        "unit_test_failure_count": 11,
        "unit_test_error_count": 34,
        "unit_test_skip_count": 34,
        "dispatch_count": 1,
        "rerun_count": 0,
    },
    "pull_request": {
        "run_id": 31976748605,
        "job_id": 95237273323,
        "event": "pull_request",
        "attempt": 1,
        "status": "completed",
        "conclusion": "failure",
        "head_sha": A1_REVISION,
        "workflow_name": "CI",
        "workflow_path": CI_WORKFLOW_REF,
        "job_name": "test",
        "created_at_utc": "2026-08-16T22:35:15Z",
        "started_at_utc": "2026-08-16T22:35:18Z",
        "completed_at_utc": "2026-08-16T23:08:54Z",
        "failure_class": "UNIT_TEST_STEP_NONZERO_EXIT",
        "failed_step_name": "Unit tests",
        "failure_annotation": "Process completed with exit code 1.",
        "unit_test_count": 2413,
        "unit_test_failure_count": 11,
        "unit_test_error_count": 34,
        "unit_test_skip_count": 34,
        "dispatch_count": 1,
        "rerun_count": 0,
    },
    "rerun_allowed": False,
    "replacement_required": True,
}

EXPECTED_A2_TERMINAL = {
    "revision": A2_REVISION,
    "native_dispatch_count": 2,
    "push": {
        "run_id": 31988863587,
        "job_id": 95268612746,
        "event": "push",
        "attempt": 1,
        "status": "completed",
        "conclusion": "success",
        "head_sha": A2_REVISION,
        "workflow_name": "CI",
        "workflow_path": CI_WORKFLOW_REF,
        "job_name": "test",
        "created_at_utc": "2026-08-17T02:43:25Z",
        "started_at_utc": "2026-08-17T02:43:27Z",
        "completed_at_utc": "2026-08-17T03:10:29Z",
        "dispatch_count": 1,
        "rerun_count": 0,
        "job_count": 1,
        "step_count": 22,
        "failed_step_count": 0,
        "unit_test_count": 2419,
        "unit_test_skip_count": 34,
        "unit_test_failure_count": 0,
        "unit_test_error_count": 0,
        "frozen_topology_test_counts": [10, 1, 12, 22, 21],
        "quality_gate_pass_count": 7,
        "quality_expected_fail_count": 1,
        "postgres_test_count": 6,
        "readiness_check_count": 138,
        "compose_config_success": True,
        "error_annotation_count": 0,
    },
    "pull_request": {
        "run_id": 31988866730,
        "job_id": 95268621512,
        "event": "pull_request",
        "attempt": 1,
        "status": "completed",
        "conclusion": "success",
        "head_sha": A2_REVISION,
        "workflow_name": "CI",
        "workflow_path": CI_WORKFLOW_REF,
        "job_name": "test",
        "created_at_utc": "2026-08-17T02:43:29Z",
        "started_at_utc": "2026-08-17T02:43:33Z",
        "completed_at_utc": "2026-08-17T03:15:22Z",
        "dispatch_count": 1,
        "rerun_count": 0,
        "job_count": 1,
        "step_count": 22,
        "failed_step_count": 0,
        "unit_test_count": 2419,
        "unit_test_skip_count": 34,
        "unit_test_failure_count": 0,
        "unit_test_error_count": 0,
        "frozen_topology_test_counts": [10, 1, 12, 22, 21],
        "quality_gate_pass_count": 7,
        "quality_expected_fail_count": 1,
        "postgres_test_count": 6,
        "readiness_check_count": 138,
        "compose_config_success": True,
        "error_annotation_count": 0,
    },
    "rerun_allowed": False,
}

EXPECTED_LEDGER_STOP_TERMINAL = {
    "revision": LEDGER_STOP_REVISION,
    "native_dispatch_count": 2,
    "push": {
        "run_id": 31991665789,
        "job_id": 95276203708,
        "event": "push",
        "attempt": 1,
        "status": "completed",
        "conclusion": "success",
        "head_sha": LEDGER_STOP_REVISION,
        "created_at_utc": "2026-08-17T03:35:50Z",
        "started_at_utc": "2026-08-17T03:35:53Z",
        "completed_at_utc": "2026-08-17T04:09:46Z",
        "dispatch_count": 1,
        "rerun_count": 0,
        "workflow_name": "CI",
        "workflow_path": CI_WORKFLOW_REF,
        "job_name": "test",
        "job_count": 1,
        "failed_step_count": 0,
        "step_count": 22,
        "unit_test_count": 2419,
        "unit_test_failure_count": 0,
        "unit_test_error_count": 0,
        "unit_test_skip_count": 34,
        "frozen_topology_test_counts": [10, 1, 12, 22, 21],
        "postgres_test_count": 6,
        "readiness_check_count": 138,
        "quality_gate_pass_count": 7,
        "quality_expected_fail_count": 1,
        "error_annotation_count": 0,
        "compose_config_success": True,
    },
    "pull_request": {
        "run_id": 31991668131,
        "job_id": 95276210136,
        "event": "pull_request",
        "attempt": 1,
        "status": "completed",
        "conclusion": "success",
        "head_sha": LEDGER_STOP_REVISION,
        "created_at_utc": "2026-08-17T03:35:53Z",
        "started_at_utc": "2026-08-17T03:35:56Z",
        "completed_at_utc": "2026-08-17T04:08:39Z",
        "dispatch_count": 1,
        "rerun_count": 0,
        "workflow_name": "CI",
        "workflow_path": CI_WORKFLOW_REF,
        "job_name": "test",
        "job_count": 1,
        "failed_step_count": 0,
        "step_count": 22,
        "unit_test_count": 2419,
        "unit_test_failure_count": 0,
        "unit_test_error_count": 0,
        "unit_test_skip_count": 34,
        "frozen_topology_test_counts": [10, 1, 12, 22, 21],
        "postgres_test_count": 6,
        "readiness_check_count": 138,
        "quality_gate_pass_count": 7,
        "quality_expected_fail_count": 1,
        "error_annotation_count": 0,
        "compose_config_success": True,
    },
    "rerun_allowed": False,
}


EXPECTED_REJECTED_BOOTSTRAP_SOURCE_TERMINAL = {
    "revision": REJECTED_BOOTSTRAP_SOURCE_REVISION,
    "native_dispatch_count": 2,
    "push": {
        "run_id": 32045476729,
        "job_id": 95432282589,
        "event": "push",
        "attempt": 1,
        "status": "completed",
        "conclusion": "failure",
        "head_sha": REJECTED_BOOTSTRAP_SOURCE_REVISION,
        "created_at_utc": "2026-08-17T16:24:43Z",
        "started_at_utc": "2026-08-17T16:24:46Z",
        "completed_at_utc": "2026-08-17T16:26:07Z",
        "dispatch_count": 1,
        "rerun_count": 0,
        "workflow_name": "CI",
        "workflow_path": CI_WORKFLOW_REF,
        "job_name": "test",
        "job_count": 1,
        "step_count": 21,
        "failed_step_count": 1,
        "failure_class": "MODEL_ARTIFACT_HTTP_DOWNLOAD_TIMEOUT_SINGLE_ATTEMPT",
        "failed_step_name": "Restore required model artifacts",
        "failed_step_number": 5,
        "unit_test_started": False,
        "readiness_gate_started": False,
        "compose_config_started": False,
        "warning_annotation_count": 1,
        "failure_annotation_count": 1,
        "error_annotation_count": 0,
    },
    "pull_request": {
        "run_id": 32045480527,
        "job_id": 95432294279,
        "event": "pull_request",
        "attempt": 1,
        "status": "completed",
        "conclusion": "success",
        "head_sha": REJECTED_BOOTSTRAP_SOURCE_REVISION,
        "created_at_utc": "2026-08-17T16:24:46Z",
        "started_at_utc": "2026-08-17T16:24:49Z",
        "completed_at_utc": "2026-08-17T17:00:13Z",
        "dispatch_count": 1,
        "rerun_count": 0,
        "workflow_name": "CI",
        "workflow_path": CI_WORKFLOW_REF,
        "job_name": "test",
        "job_count": 1,
        "step_count": 22,
        "failed_step_count": 0,
        "unit_test_count": 2589,
        "unit_test_failure_count": 0,
        "unit_test_error_count": 0,
        "unit_test_skip_count": 34,
        "frozen_topology_test_counts": [10, 1, 12, 22, 21],
        "postgres_test_count": 6,
        "readiness_check_count": 138,
        "quality_gate_pass_count": 7,
        "quality_expected_fail_count": 1,
        "warning_annotation_count": 1,
        "error_annotation_count": 0,
        "compose_config_success": True,
    },
    "rerun_allowed": False,
    "accepted": False,
    "replacement_required": True,
}


def _accepted_attempt_one_ci_row(
    *,
    revision: str,
    run_id: int,
    job_id: int,
    event: str,
    created_at_utc: str,
    started_at_utc: str,
    completed_at_utc: str,
) -> dict[str, Any]:
    """Return the exact common successful CI shape for b2d/4eab."""
    return {
        "run_id": run_id,
        "job_id": job_id,
        "event": event,
        "attempt": 1,
        "status": "completed",
        "conclusion": "success",
        "head_sha": revision,
        "created_at_utc": created_at_utc,
        "started_at_utc": started_at_utc,
        "completed_at_utc": completed_at_utc,
        "dispatch_count": 1,
        "rerun_count": 0,
        "workflow_name": "CI",
        "workflow_path": CI_WORKFLOW_REF,
        "job_name": "test",
        "job_count": 1,
        "failed_step_count": 0,
        "step_count": 22,
        "unit_test_count": 2602,
        "unit_test_failure_count": 0,
        "unit_test_error_count": 0,
        "unit_test_skip_count": 34,
        "frozen_topology_test_counts": [10, 1, 12, 22, 21],
        "postgres_test_count": 6,
        "readiness_check_count": 138,
        "quality_gate_pass_count": 7,
        "quality_expected_fail_count": 1,
        "error_annotation_count": 0,
        "compose_config_success": True,
    }


EXPECTED_HELPER_SOURCE_TERMINAL = {
    "revision": HELPER_SOURCE_ACCEPTED_REVISION,
    "native_dispatch_count": 2,
    "push": _accepted_attempt_one_ci_row(
        revision=HELPER_SOURCE_ACCEPTED_REVISION,
        run_id=32082386775,
        job_id=95547748113,
        event="push",
        created_at_utc="2026-08-17T23:54:24Z",
        started_at_utc="2026-08-17T23:54:27Z",
        completed_at_utc="2026-08-18T00:29:05Z",
    ),
    "pull_request": _accepted_attempt_one_ci_row(
        revision=HELPER_SOURCE_ACCEPTED_REVISION,
        run_id=32082388870,
        job_id=95547753794,
        event="pull_request",
        created_at_utc="2026-08-17T23:54:26Z",
        started_at_utc="2026-08-17T23:54:29Z",
        completed_at_utc="2026-08-18T00:26:42Z",
    ),
    "rerun_allowed": False,
}

EXPECTED_BOOTSTRAP_LEDGER_TERMINAL = {
    "revision": BOOTSTRAP_LEDGER_ACCEPTANCE_REVISION,
    "native_dispatch_count": 2,
    "push": _accepted_attempt_one_ci_row(
        revision=BOOTSTRAP_LEDGER_ACCEPTANCE_REVISION,
        run_id=32085627719,
        job_id=95557448857,
        event="push",
        created_at_utc="2026-08-18T00:44:02Z",
        started_at_utc="2026-08-18T00:44:04Z",
        completed_at_utc="2026-08-18T01:15:58Z",
    ),
    "pull_request": _accepted_attempt_one_ci_row(
        revision=BOOTSTRAP_LEDGER_ACCEPTANCE_REVISION,
        run_id=32085631106,
        job_id=95557458319,
        event="pull_request",
        created_at_utc="2026-08-18T00:44:05Z",
        started_at_utc="2026-08-18T00:44:07Z",
        completed_at_utc="2026-08-18T01:19:02Z",
    ),
    "rerun_allowed": False,
}


EXPECTED_REJECTED_ROOT_ACTIVATION_TERMINAL = {
    "revision": REJECTED_ROOT_ACTIVATION_REVISION,
    "native_dispatch_count": 2,
    "push": {
        "run_id": 32140388587,
        "job_id": 95721382044,
        "event": "push",
        "attempt": 1,
        "status": "completed",
        "conclusion": "failure",
        "head_sha": REJECTED_ROOT_ACTIVATION_REVISION,
        "created_at_utc": "2026-08-18T13:05:37Z",
        "started_at_utc": "2026-08-18T13:05:40Z",
        "completed_at_utc": "2026-08-18T13:37:38Z",
        "dispatch_count": 1,
        "rerun_count": 0,
        "workflow_name": "CI",
        "workflow_path": CI_WORKFLOW_REF,
        "job_name": "test",
        "job_count": 1,
        "step_count": 22,
        "failed_step_count": 1,
        "failure_class": "ITEM26_FAIL_CLOSED_EXPECTATION_NOT_UPDATED",
        "failed_step_name": "Unit tests",
        "failed_step_number": 13,
        "unit_test_count": 2608,
        "unit_test_failure_count": 1,
        "unit_test_error_count": 0,
        "unit_test_skip_count": 34,
        "frozen_topology_tests_started": False,
        "quality_gate_started": False,
        "postgres_test_started": False,
        "readiness_gate_started": False,
        "compose_config_started": False,
        "warning_annotation_count": 1,
        "failure_annotation_count": 1,
        "error_annotation_count": 0,
    },
    "pull_request": {
        "run_id": 32140393870,
        "job_id": 95721399196,
        "event": "pull_request",
        "attempt": 1,
        "status": "completed",
        "conclusion": "failure",
        "head_sha": REJECTED_ROOT_ACTIVATION_REVISION,
        "created_at_utc": "2026-08-18T13:05:40Z",
        "started_at_utc": "2026-08-18T13:05:43Z",
        "completed_at_utc": "2026-08-18T13:38:56Z",
        "dispatch_count": 1,
        "rerun_count": 0,
        "workflow_name": "CI",
        "workflow_path": CI_WORKFLOW_REF,
        "job_name": "test",
        "job_count": 1,
        "step_count": 22,
        "failed_step_count": 1,
        "failure_class": "ITEM26_FAIL_CLOSED_EXPECTATION_NOT_UPDATED",
        "failed_step_name": "Unit tests",
        "failed_step_number": 13,
        "unit_test_count": 2608,
        "unit_test_failure_count": 1,
        "unit_test_error_count": 0,
        "unit_test_skip_count": 34,
        "frozen_topology_tests_started": False,
        "quality_gate_started": False,
        "postgres_test_started": False,
        "readiness_gate_started": False,
        "compose_config_started": False,
        "warning_annotation_count": 1,
        "failure_annotation_count": 1,
        "error_annotation_count": 0,
    },
    "rerun_allowed": False,
    "accepted": False,
    "replacement_required": True,
}


HISTORICAL_SOURCE_BLOBS = {
    "a0": {
        "revision": A0_REVISION,
        "blobs": {
            EXTRACTOR_REF.replace("_v2.py", "_v1.py"): {
                "git_blob_oid": "8c630b1c128af7a25840e2a4c389b465698b6059",
                "file_sha256": "2a8b805bb80e0816af04fbda7f04f8e7cf7690e741a2a84021852b98d4234bfd",
            },
            VERIFIER_REF.replace("_v2.py", "_v1.py"): {
                "git_blob_oid": "07d3d65c1fea68f2ccab486d28811f120b40b7d2",
                "file_sha256": "bcb52bfa79a2131809412ea089fed1a3b19d47ccf745e67521d0ef6a9756bc5f",
            },
            CI_WORKFLOW_REF: {
                "git_blob_oid": "362ee09e940197270ef87132e91330a45a8b72b1",
                "file_sha256": "5260fd79bcd190704324386bbcf43214a7d82a37285b3a266d5c484a08cabe01",
            },
        },
    },
    "a1": {
        "revision": A1_REVISION,
        "blobs": {
            COLLECTOR_REF.replace("_v2.py", "_v1.py"): {
                "git_blob_oid": "d91ade79a17ed757aa0c7243a23d6d2e6408ac05",
                "file_sha256": "a5347899f3117add12c34698db2359e4440288bcba37b7eb913ce2797de31c83",
            },
            EXTRACTOR_REF.replace("_v2.py", "_v1.py"): {
                "git_blob_oid": "793f36225f0feda73da2792f6059a2720a127fd6",
                "file_sha256": "d097c052aea5758c27a3be10e2b072abb32fe51fcaf5b8ff4158c370b474d017",
            },
            VERIFIER_REF.replace("_v2.py", "_v1.py"): {
                "git_blob_oid": "63d84f2820d8225d428552b6b0156b6bd37c8de4",
                "file_sha256": "7706122a169698ce970c89bd660b1eeddfb298ecad4afbba8e6936cc09cbcecb",
            },
            CI_WORKFLOW_REF: {
                "git_blob_oid": "63fac8f7e588007544c96c32096e220f2d07a61f",
                "file_sha256": "74ab44b32802e969183c1a657ef83318692bdeebc2c598195262b3bb9114f26c",
            },
        },
    },
    "a2": {
        "revision": A2_REVISION,
        "blobs": {
            COLLECTOR_REF.replace("_v2.py", "_v1.py"): {
                "git_blob_oid": "d489ad14be314f31b6eb725cf25f8251553c3a7d",
                "file_sha256": "0d75d63e16e17b73e86fb9f42c74d3764aae08ecc58f3956d9fedd997ae4f143",
            },
            EXTRACTOR_REF.replace("_v2.py", "_v1.py"): {
                "git_blob_oid": "793f36225f0feda73da2792f6059a2720a127fd6",
                "file_sha256": "d097c052aea5758c27a3be10e2b072abb32fe51fcaf5b8ff4158c370b474d017",
            },
            VERIFIER_REF.replace("_v2.py", "_v1.py"): {
                "git_blob_oid": "a8d7224bf7478a659a270b16dd7b19b325e00214",
                "file_sha256": "9d7c95981bd40d055ad6b69591efcedd8753ec930bf0f5c7230d6824a50961e2",
            },
            CI_WORKFLOW_REF: {
                "git_blob_oid": "63fac8f7e588007544c96c32096e220f2d07a61f",
                "file_sha256": "74ab44b32802e969183c1a657ef83318692bdeebc2c598195262b3bb9114f26c",
            },
        },
    },
}

CONTROL_SOURCE_REFS = (
    COLLECTOR_REF,
    EXTRACTOR_REF,
    VERIFIER_REF,
    ROOT_BUILDER_REF,
    RECEIPT_BUILDER_REF,
    EVIDENCE_VERIFIER_REF,
    EVIDENCE_BUILDER_REF,
    INSTALLER_REF,
    BOOTSTRAP_REF,
    CONTRACT_REF,
    PUBLIC_ROOT_REF,
    CI_WORKFLOW_REF,
)
RUNTIME_SOURCE_REFS = (COLLECTOR_REF, EXTRACTOR_REF, VERIFIER_REF)

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$"
)
MAX_BYTES = 24 * 1024 * 1024
OPENSSL = Path("/usr/bin/openssl")
GIT = Path("/usr/bin/git")


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        + b"\n"
    )


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _semantic(value: Any) -> str:
    return _sha(canonical_bytes(value)[:-1])


def _hex64(value: Any) -> bool:
    return type(value) is str and HEX64.fullmatch(value) is not None


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


def _utc(value: Any) -> Optional[datetime]:
    if type(value) is not str or RFC3339.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed if parsed.tzinfo == timezone.utc else None


def _require_finalized() -> None:
    """Reject the inert scaffold before any production filesystem/Git I/O."""
    if (
        AUTHORITY_V2_FINALIZED is not True
        or EXPECTED_ROOT_SHA == ""
        or EXPECTED_AUTHORITY_ROOT_FILE_SHA256 != EXPECTED_ROOT_SHA
        or not _hex64(EXPECTED_ROOT_SHA)
    ):
        raise ValueError("manual authority v2 not finalized")


def _stable(row: os.stat_result) -> tuple[int, ...]:
    return (
        row.st_dev,
        row.st_ino,
        row.st_mode,
        row.st_uid,
        row.st_gid,
        row.st_nlink,
        row.st_size,
        row.st_mtime_ns,
        row.st_ctime_ns,
    )


def _validate_directory(row: os.stat_result) -> None:
    if (
        not stat.S_ISDIR(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or stat.S_IMODE(row.st_mode) != 0o700
        or row.st_uid != ROOT_UID
    ):
        raise ValueError("manual authority v2 directory identity")


def _validate_file(row: os.stat_result) -> None:
    if (
        not stat.S_ISREG(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or stat.S_IMODE(row.st_mode) != 0o600
        or row.st_uid != ROOT_UID
        or row.st_nlink != 1
    ):
        raise ValueError("manual authority v2 file identity")


def _validate_parent_chain(directory: Path) -> None:
    current = Path(directory.anchor)
    for component in directory.parts[1:-1]:
        current = current / component
        row = current.lstat()
        if (
            not stat.S_ISDIR(row.st_mode)
            or stat.S_ISLNK(row.st_mode)
            or row.st_uid != ROOT_UID
            or stat.S_IMODE(row.st_mode) & 0o022
        ):
            raise ValueError("manual authority v2 parent identity")


def _read_file_at(directory_fd: int, name: str) -> bytes:
    before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    _validate_file(before)
    descriptor = os.open(
        name,
        os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        dir_fd=directory_fd,
    )
    try:
        opened = os.fstat(descriptor)
        _validate_file(opened)
        chunks: list[bytes] = []
        size = 0
        while size <= MAX_BYTES:
            chunk = os.read(descriptor, min(65536, MAX_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        closed = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    raw = b"".join(chunks)
    if (
        not 1 <= len(raw) <= MAX_BYTES
        or _stable(before) != _stable(opened)
        or _stable(opened) != _stable(closed)
        or _stable(closed) != _stable(after)
    ):
        raise ValueError("manual authority v2 file changed")
    return raw


def _validated_inventory(
    expected_inventory: tuple[str, ...],
    *,
    allowed_inventory: tuple[str, ...] = FINAL_INVENTORY,
    required_name: Optional[str] = ROOT_FILE,
) -> tuple[str, ...]:
    allowed = set(allowed_inventory)
    if (
        type(expected_inventory) is not tuple
        or not expected_inventory
        or (
            required_name is not None
            and required_name not in expected_inventory
        )
        or len(expected_inventory) != len(set(expected_inventory))
        or any(
            type(name) is not str
            or name not in allowed
            or Path(name).name != name
            for name in expected_inventory
        )
    ):
        raise ValueError("manual authority v2 expected inventory")
    return expected_inventory


def _read_exact_directory(
    directory: Path,
    expected_inventory: tuple[str, ...],
    *,
    allowed_inventory: tuple[str, ...] = FINAL_INVENTORY,
    required_name: Optional[str] = ROOT_FILE,
) -> dict[str, bytes]:
    inventory = _validated_inventory(
        expected_inventory,
        allowed_inventory=allowed_inventory,
        required_name=required_name,
    )
    if not isinstance(directory, Path) or not directory.is_absolute():
        raise ValueError("manual authority v2 directory absolute")
    _validate_parent_chain(directory)
    before = directory.lstat()
    _validate_directory(before)
    descriptor = os.open(
        directory,
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        opened = os.fstat(descriptor)
        _validate_directory(opened)
        if _stable(before) != _stable(opened):
            raise ValueError("manual authority v2 directory changed")
        names_before = os.listdir(descriptor)
        if len(names_before) != len(inventory) or set(names_before) != set(inventory):
            raise ValueError("manual authority v2 inventory")
        material = {name: _read_file_at(descriptor, name) for name in inventory}
        names_after = os.listdir(descriptor)
        closed = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after = directory.lstat()
    if (
        len(names_after) != len(names_before)
        or set(names_after) != set(names_before)
        or _stable(opened) != _stable(closed)
        or _stable(closed) != _stable(after)
    ):
        raise ValueError("manual authority v2 directory changed")
    return material


def _read_exact_runtime_directory(directory: Path) -> dict[str, bytes]:
    return _read_exact_directory(
        directory,
        RUNTIME_INVENTORY,
        allowed_inventory=RUNTIME_INVENTORY,
        required_name=ACTIVATION_RECEIPT_FILE,
    )


def _parse(raw: bytes, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(label + " duplicate key")
            result[key] = item
        return result

    try:
        value = json.loads(
            raw.decode("ascii"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError(label + " number")
            ),
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(label + " JSON") from exc
    if type(value) is not dict or canonical_bytes(value) != raw:
        raise ValueError(label + " canonical")
    return value


def _tool_identity(path: Path) -> os.stat_result:
    row = path.lstat()
    if (
        not stat.S_ISREG(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or row.st_uid != 0
        or stat.S_IMODE(row.st_mode) & 0o022
    ):
        raise ValueError("manual authority v2 tool identity")
    return row


def _openssl(
    arguments: list[str],
    *,
    stdin: bytes,
    timeout: int = 15,
) -> bytes:
    before = _tool_identity(OPENSSL)
    try:
        result = subprocess.run(
            [str(OPENSSL), *arguments],
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("manual authority v2 openssl") from exc
    if (
        result.returncode != 0
        or not result.stdout
        or _stable(OPENSSL.lstat()) != _stable(before)
    ):
        raise ValueError("manual authority v2 openssl")
    return result.stdout


def _canonical_public_pem(key: bytes) -> bytes:
    return _openssl(["pkey", "-pubin", "-pubout"], stdin=key)


def _canonical_spki_der(key: bytes) -> bytes:
    return _openssl(
        ["pkey", "-pubin", "-inform", "PEM", "-outform", "DER"],
        stdin=key,
    )


def _der_tlv(raw: bytes, offset: int) -> tuple[int, bytes, int]:
    if type(raw) is not bytes or not 0 <= offset < len(raw):
        raise ValueError("manual authority v2 DER")
    tag = raw[offset]
    offset += 1
    if offset >= len(raw):
        raise ValueError("manual authority v2 DER")
    first = raw[offset]
    offset += 1
    if first & 0x80:
        count = first & 0x7F
        if (
            count == 0
            or count > 4
            or offset + count > len(raw)
            or raw[offset] == 0
        ):
            raise ValueError("manual authority v2 DER")
        length = int.from_bytes(raw[offset : offset + count], "big")
        offset += count
        if length < 128:
            raise ValueError("manual authority v2 DER")
    else:
        length = first
    end = offset + length
    if end > len(raw):
        raise ValueError("manual authority v2 DER")
    return tag, raw[offset:end], end


def _positive_der_integer(raw: bytes) -> int:
    if (
        not raw
        or raw[0] & 0x80
        or (len(raw) > 1 and raw[0] == 0 and raw[1] & 0x80 == 0)
    ):
        raise ValueError("manual authority v2 RSA integer")
    return int.from_bytes(raw, "big")


def _rsa_3072(key: bytes) -> bool:
    try:
        der = _canonical_spki_der(key)
        outer_tag, outer, outer_end = _der_tlv(der, 0)
        algorithm_tag, algorithm, algorithm_end = _der_tlv(outer, 0)
        oid_tag, oid, oid_end = _der_tlv(algorithm, 0)
        null_tag, null_value, null_end = _der_tlv(algorithm, oid_end)
        bit_tag, bit_value, bit_end = _der_tlv(outer, algorithm_end)
        if (
            outer_tag != 0x30
            or outer_end != len(der)
            or algorithm_tag != 0x30
            or oid_tag != 0x06
            or oid != bytes.fromhex("2a864886f70d010101")
            or null_tag != 0x05
            or null_value != b""
            or null_end != len(algorithm)
            or bit_tag != 0x03
            or bit_end != len(outer)
            or not bit_value
            or bit_value[0] != 0
        ):
            return False
        rsa_der = bit_value[1:]
        rsa_tag, rsa_value, rsa_end = _der_tlv(rsa_der, 0)
        modulus_tag, modulus_raw, modulus_end = _der_tlv(rsa_value, 0)
        exponent_tag, exponent_raw, exponent_end = _der_tlv(
            rsa_value, modulus_end
        )
        modulus = _positive_der_integer(modulus_raw)
        exponent = _positive_der_integer(exponent_raw)
    except (TypeError, ValueError):
        return False
    return bool(
        rsa_tag == 0x30
        and rsa_end == len(rsa_der)
        and modulus_tag == 0x02
        and exponent_tag == 0x02
        and exponent_end == len(rsa_value)
        and modulus.bit_length() == 3072
        and 3 <= exponent <= 0xFFFFFFFF
        and exponent % 2 == 1
    )


def public_key_row(role: str, public_key_pem: bytes) -> dict[str, Any]:
    if role not in ROLE_NAMES or type(public_key_pem) is not bytes:
        raise ValueError("manual authority v2 public key input")
    if (
        _canonical_public_pem(public_key_pem) != public_key_pem
        or not _rsa_3072(public_key_pem)
    ):
        raise ValueError("manual authority v2 public key identity")
    return {
        "role": role,
        "issuer": ROLE_ISSUERS[role],
        "audience": ROLE_AUDIENCE,
        "authority_epoch_id": AUTHORITY_EPOCH_ID,
        "algorithm": "RSA-3072",
        "signature_algorithm": SIGNATURE_ALGORITHM,
        "signature_domain": ROLE_SIGNATURE_DOMAIN_TEXT[role],
        "permitted_signature_domains": (
            [
                ROLE_SIGNATURE_DOMAIN_TEXT[role],
                RECEIPT_SIGNATURE_DOMAIN_TEXT,
            ]
            if role == "local_ci_observation"
            else [ROLE_SIGNATURE_DOMAIN_TEXT[role]]
        ),
        "public_key_pem": public_key_pem.decode("ascii"),
        "public_key_sha256": _sha(public_key_pem),
        "public_key_spki_sha256": _sha(_canonical_spki_der(public_key_pem)),
        "organizational_independence_proven": False,
    }


def _decode_key_row(
    value: Any,
    role: str,
) -> tuple[bytes, str]:
    expected_keys = {
        "role",
        "issuer",
        "audience",
        "authority_epoch_id",
        "algorithm",
        "signature_algorithm",
        "signature_domain",
        "permitted_signature_domains",
        "public_key_pem",
        "public_key_sha256",
        "public_key_spki_sha256",
        "organizational_independence_proven",
    }
    if type(value) is not dict or set(value) != expected_keys:
        raise ValueError("manual authority v2 key schema")
    try:
        key = value.get("public_key_pem", "").encode("ascii")
    except (AttributeError, UnicodeError) as exc:
        raise ValueError("manual authority v2 key encoding") from exc
    if (
        value.get("role") != role
        or value.get("issuer") != ROLE_ISSUERS[role]
        or value.get("audience") != ROLE_AUDIENCE
        or value.get("authority_epoch_id") != AUTHORITY_EPOCH_ID
        or value.get("algorithm") != "RSA-3072"
        or value.get("signature_algorithm") != SIGNATURE_ALGORITHM
        or value.get("signature_domain")
        != ROLE_SIGNATURE_DOMAIN_TEXT[role]
        or value.get("permitted_signature_domains")
        != (
            [
                ROLE_SIGNATURE_DOMAIN_TEXT[role],
                RECEIPT_SIGNATURE_DOMAIN_TEXT,
            ]
            if role == "local_ci_observation"
            else [ROLE_SIGNATURE_DOMAIN_TEXT[role]]
        )
        or value.get("organizational_independence_proven") is not False
        or not _hex64(value.get("public_key_sha256"))
        or not _hex64(value.get("public_key_spki_sha256"))
        or _sha(key) != value["public_key_sha256"]
        or _canonical_public_pem(key) != key
        or not _rsa_3072(key)
    ):
        raise ValueError("manual authority v2 key identity")
    spki = _sha(_canonical_spki_der(key))
    if spki != value["public_key_spki_sha256"]:
        raise ValueError("manual authority v2 key SPKI")
    return key, spki


def authority_root_document(
    authorities: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if type(authorities) is not dict or set(authorities) != set(ROLE_NAMES):
        raise ValueError("manual authority v2 roles")
    decoded = {
        role: _decode_key_row(authorities[role], role)
        for role in ROLE_NAMES
    }
    if len({row[1] for row in decoded.values()}) != 3:
        raise ValueError("manual authority v2 keys not distinct")
    return {
        "schema": ROOT_SCHEMA,
        "task_id": TASK_ID,
        "historical_operation_id": OPERATION_ID,
        "authority_generation_id": AUTHORITY_GENERATION_ID,
        "authority_epoch_id": AUTHORITY_EPOCH_ID,
        "status": "PUBLIC_ROOT_V2_FINALIZED_AWAITING_ATTEMPT_ONE_DUAL_CI",
        "repository": REPOSITORY,
        "source_ref": SOURCE_REF,
        "ledger_stop": {
            "revision": LEDGER_STOP_REVISION,
            "status": (
                "A2_ACCEPTED_V1_CUSTODY_UNAVAILABLE_NEW_AUTHORITY_REQUIRED"
            ),
            "bindings": LEDGER_STOP_BINDINGS,
            "item26_status": "unverified",
            "internal_readiness_verified": 25,
            "internal_readiness_total": 29,
            "readiness_credit_added": False,
        },
        "historical_checkpoints": {
            "a0_terminal": EXPECTED_A0_TERMINAL,
            "a1_terminal": EXPECTED_A1_TERMINAL,
            "a2_terminal": EXPECTED_A2_TERMINAL,
            "ledger_stop_terminal": EXPECTED_LEDGER_STOP_TERMINAL,
            "rejected_bootstrap_source_terminal": (
                EXPECTED_REJECTED_BOOTSTRAP_SOURCE_TERMINAL
            ),
            "helper_source_terminal": EXPECTED_HELPER_SOURCE_TERMINAL,
            "bootstrap_ledger_terminal": EXPECTED_BOOTSTRAP_LEDGER_TERMINAL,
            "source_blobs": HISTORICAL_SOURCE_BLOBS,
        },
        "bootstrap_source": {
            "ref": BOOTSTRAP_REF,
            "authorization_anchor_revision": (
                BOOTSTRAP_AUTHORIZATION_ANCHOR_REVISION
            ),
            "rejected_revision": REJECTED_BOOTSTRAP_SOURCE_REVISION,
            "rejected_revision_accepted": False,
            "rejected_revision_rerun_allowed": False,
            "accepted_revision": HELPER_SOURCE_ACCEPTED_REVISION,
            "accepted_revision_attempt_one_dual_ci_passed": True,
            "acceptance_ledger_revision": (
                BOOTSTRAP_LEDGER_ACCEPTANCE_REVISION
            ),
            "git_blob_oid": EXPECTED_BOOTSTRAP_GIT_BLOB_OID,
            "file_sha256": EXPECTED_BOOTSTRAP_FILE_SHA256,
            "bytes": EXPECTED_BOOTSTRAP_FILE_BYTES,
        },
        "v1_custody": {
            "expected_root_file_sha256": EXPECTED_V1_ROOT_FILE_SHA256,
            "expected_root_bytes": 5989,
            "root_bytes_locatable": False,
            "private_keys_locatable": False,
            "destroyed_proven": False,
            "revoked_proven": False,
            "rotated_proven": False,
            "compromised_proven": False,
            "historical_root_activated": False,
            "status": (
                "CUSTODY_UNAVAILABLE_NOT_PROVEN_DESTROYED_"
                "HISTORICAL_UNACTIVATED"
            ),
        },
        "contract": {
            "ref": CONTRACT_REF,
            "file_sha256": EXPECTED_CONTRACT_FILE_SHA256,
        },
        "no_replay": {
            "ref": NO_REPLAY_REF,
            "file_sha256": EXPECTED_NO_REPLAY_FILE_SHA256,
            "registry_sha256": EXPECTED_NO_REPLAY_REGISTRY_SHA256,
            "entry_count": 29,
            "historical_operation_replay_allowed": False,
        },
        "authorities": authorities,
        "authority_key_count": 3,
        "authority_keys_mathematically_distinct": True,
        "independent_organizational_key_custody_proven": False,
        "single_local_root_custody": True,
        "provider_native_signature": False,
        "github_native_signature": False,
        "post_action_readback_only": True,
        "authorizes_new_action": False,
        "readiness_credit_allowed": False,
        "fallback": {
            "authority_v1_allowed": False,
            "collector_v1_allowed": False,
            "receipt_v2_allowed": False,
        },
    }


def _validate_root(
    raw: bytes,
    *,
    expected_hash: str,
    root: Path = ROOT,
) -> tuple[dict[str, Any], dict[str, tuple[bytes, str]]]:
    del root
    if not _hex64(expected_hash) or _sha(raw) != expected_hash:
        raise ValueError("manual authority v2 root hash")
    value = _parse(raw, "manual authority v2 root")
    authorities = value.get("authorities")
    if type(authorities) is not dict or set(authorities) != set(ROLE_NAMES):
        raise ValueError("manual authority v2 root roles")
    expected = authority_root_document(authorities)
    if not _strict(value, expected):
        raise ValueError("manual authority v2 root identity")
    keys = {
        role: _decode_key_row(authorities[role], role)
        for role in ROLE_NAMES
    }
    return value, keys


def _validated_git_arguments(arguments: list[str]) -> list[str]:
    if (
        type(arguments) is not list
        or not arguments
        or any(
            type(value) is not str
            or not value
            or "\0" in value
            or "safe.directory" in value.lower()
            for value in arguments
        )
    ):
        raise ValueError("manual authority v2 git arguments")
    command = arguments[0]
    valid_shape = (
        (command in {"show", "rev-parse"} and len(arguments) == 2)
        or (
            command == "cat-file"
            and len(arguments) == 3
            and arguments[1] == "-e"
        )
        or (
            command == "merge-base"
            and len(arguments) == 4
            and arguments[1] == "--is-ancestor"
        )
    )
    if not valid_shape:
        raise ValueError("manual authority v2 git arguments")
    return list(arguments)


def _git_repository_identity(
    root: Path,
) -> tuple[tuple[str, tuple[int, ...]], ...]:
    directory_paths = [Path(root.anchor)]
    current = Path(root.anchor)
    for component in root.parts[1:]:
        current = current / component
        directory_paths.append(current)
    metadata_path = root / ".git"
    paths = (*directory_paths, metadata_path)
    try:
        rows = tuple(path.lstat() for path in paths)
    except OSError as exc:
        raise ValueError("manual authority v2 git repository identity") from exc
    repository_row = rows[len(directory_paths) - 1]
    repository_owner = repository_row.st_uid
    for index, row in enumerate(rows):
        is_metadata = index == len(rows) - 1
        if (
            not stat.S_ISDIR(row.st_mode)
            or stat.S_ISLNK(row.st_mode)
            or stat.S_IMODE(row.st_mode) & 0o022
            or (
                is_metadata
                and row.st_uid != repository_owner
            )
            or (
                not is_metadata
                and row.st_uid not in {ROOT_UID, repository_owner}
            )
        ):
            raise ValueError("manual authority v2 git repository identity")
    return tuple(
        (str(path), _stable(row)) for path, row in zip(paths, rows)
    )


def _validated_git_repository_root(
    root: Path,
) -> tuple[Path, tuple[tuple[str, tuple[int, ...]], ...]]:
    if (
        not isinstance(root, Path)
        or not root.is_absolute()
        or any(part in {".", ".."} for part in root.parts)
        or any(character in str(root) for character in ("\0", "\r", "\n", "*"))
    ):
        raise ValueError("manual authority v2 git repository root")
    try:
        canonical = root.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("manual authority v2 git repository root") from exc
    if canonical != root:
        raise ValueError("manual authority v2 git repository root")
    return canonical, _git_repository_identity(canonical)


def _git(
    arguments: list[str],
    *,
    root: Path,
    stdout: int = subprocess.PIPE,
) -> subprocess.CompletedProcess[bytes]:
    command = _validated_git_arguments(arguments)
    canonical_root, repository_before = _validated_git_repository_root(root)
    before = _tool_identity(GIT)
    if _git_repository_identity(canonical_root) != repository_before:
        raise ValueError("manual authority v2 git repository changed")
    safe_directory = "safe.directory=" + str(canonical_root)
    if "*" in safe_directory:
        raise ValueError("manual authority v2 git repository root")
    try:
        result = subprocess.run(
            [
                str(GIT),
                "-c",
                safe_directory,
                "--no-replace-objects",
                *command,
            ],
            cwd=canonical_root,
            env={
                "PATH": "/usr/bin:/bin",
                "LC_ALL": "C",
                "LANG": "C",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_NO_REPLACE_OBJECTS": "1",
                "GIT_OPTIONAL_LOCKS": "0",
            },
            stdout=stdout,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("manual authority v2 git") from exc
    if _git_repository_identity(canonical_root) != repository_before:
        raise ValueError("manual authority v2 git repository changed")
    if _stable(GIT.lstat()) != _stable(before):
        raise ValueError("manual authority v2 git identity")
    return result


def _valid_ref(revision: str, ref: str) -> bool:
    return bool(
        HEX40.fullmatch(revision or "") is not None
        and type(ref) is str
        and ref
        and not ref.startswith("/")
        and ".." not in Path(ref).parts
    )


def _git_blob_record(
    revision: str,
    ref: str,
    *,
    root: Path,
) -> dict[str, Any]:
    if not _valid_ref(revision, ref):
        raise ValueError("manual authority v2 git object")
    raw_result = _git(["show", revision + ":" + ref], root=root)
    oid_result = _git(["rev-parse", revision + ":" + ref], root=root)
    if (
        raw_result.returncode != 0
        or not 1 <= len(raw_result.stdout) <= MAX_BYTES
        or oid_result.returncode != 0
    ):
        raise ValueError("manual authority v2 git object")
    try:
        oid = oid_result.stdout.decode("ascii").strip()
    except UnicodeError as exc:
        raise ValueError("manual authority v2 git object") from exc
    if HEX40.fullmatch(oid) is None:
        raise ValueError("manual authority v2 git blob oid")
    return {
        "raw": raw_result.stdout,
        "git_blob_oid": oid,
        "git_blob_sha256": _sha(raw_result.stdout),
        "file_sha256": _sha(raw_result.stdout),
    }


def git_blob_bytes(revision: str, ref: str, *, root: Path = ROOT) -> bytes:
    return _git_blob_record(revision, ref, root=root)["raw"]


def git_blob_absent(revision: str, ref: str, *, root: Path = ROOT) -> bool:
    if not _valid_ref(revision, ref):
        raise ValueError("manual authority v2 git object")
    commit = _git(
        ["cat-file", "-e", revision + "^{commit}"],
        root=root,
        stdout=subprocess.DEVNULL,
    )
    if commit.returncode != 0:
        raise ValueError("manual authority v2 git revision")
    result = _git(
        ["cat-file", "-e", revision + ":" + ref],
        root=root,
        stdout=subprocess.DEVNULL,
    )
    return result.returncode != 0


def revision_is_strict_ancestor(
    earlier: str,
    later: str,
    *,
    root: Path = ROOT,
) -> bool:
    if (
        earlier == later
        or HEX40.fullmatch(earlier or "") is None
        or HEX40.fullmatch(later or "") is None
    ):
        return False
    result = _git(
        ["merge-base", "--is-ancestor", earlier, later],
        root=root,
        stdout=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _control_lineage_is_valid(
    control_revision: str,
    *,
    root: Path,
) -> bool:
    """Bind every append-only bootstrap stage before a control revision."""
    revisions = (
        A0_REVISION,
        A1_REVISION,
        A2_REVISION,
        LEDGER_STOP_REVISION,
        BOOTSTRAP_AUTHORIZATION_ANCHOR_REVISION,
        REJECTED_BOOTSTRAP_SOURCE_REVISION,
        HELPER_SOURCE_ACCEPTED_REVISION,
        BOOTSTRAP_LEDGER_ACCEPTANCE_REVISION,
        REJECTED_ROOT_ACTIVATION_REVISION,
        control_revision,
    )
    return HEX40.fullmatch(control_revision or "") is not None and all(
        revision_is_strict_ancestor(earlier, later, root=root)
        for earlier, later in zip(revisions, revisions[1:])
    )


def _validate_ledger_git_bindings(*, root: Path) -> None:
    for ref, expected in LEDGER_STOP_BINDINGS.items():
        observed = _git_blob_record(LEDGER_STOP_REVISION, ref, root=root)
        if (
            observed["git_blob_oid"] != expected["git_blob_oid"]
            or observed["file_sha256"] != expected["file_sha256"]
        ):
            raise ValueError("manual authority v2 ledger binding")
    no_replay = _git_blob_record(LEDGER_STOP_REVISION, NO_REPLAY_REF, root=root)
    if no_replay["file_sha256"] != EXPECTED_NO_REPLAY_FILE_SHA256:
        raise ValueError("manual authority v2 no-replay binding")
    for revision in (
        REJECTED_BOOTSTRAP_SOURCE_REVISION,
        HELPER_SOURCE_ACCEPTED_REVISION,
        BOOTSTRAP_LEDGER_ACCEPTANCE_REVISION,
    ):
        bootstrap = _git_blob_record(revision, BOOTSTRAP_REF, root=root)
        if (
            bootstrap["git_blob_oid"] != EXPECTED_BOOTSTRAP_GIT_BLOB_OID
            or bootstrap["file_sha256"] != EXPECTED_BOOTSTRAP_FILE_SHA256
            or len(bootstrap["raw"]) != EXPECTED_BOOTSTRAP_FILE_BYTES
        ):
            raise ValueError("manual authority v2 bootstrap binding")
    rejected_root = _git_blob_record(
        REJECTED_ROOT_ACTIVATION_REVISION,
        PUBLIC_ROOT_REF,
        root=root,
    )
    rejected_contract = _git_blob_record(
        REJECTED_ROOT_ACTIVATION_REVISION,
        CONTRACT_REF,
        root=root,
    )
    if (
        rejected_root["file_sha256"] != EXPECTED_ROOT_SHA
        or rejected_contract["file_sha256"]
        != EXPECTED_CONTRACT_FILE_SHA256
    ):
        raise ValueError("manual authority v2 rejected activation binding")


def load_activation_root(
    *,
    expected_control_revision: str,
    expected_authority_root_file_sha256: str = EXPECTED_AUTHORITY_ROOT_FILE_SHA256,
    root: Path = ROOT,
    authority_directory: Path = AUTHORITY_DIRECTORY,
    expected_inventory: tuple[str, ...] = ACTIVATION_INVENTORY,
) -> dict[str, Any]:
    _require_finalized()
    inventory = _validated_inventory(expected_inventory)
    if (
        expected_authority_root_file_sha256 != EXPECTED_ROOT_SHA
        or not _control_lineage_is_valid(
            expected_control_revision,
            root=root,
        )
    ):
        raise ValueError("manual authority v2 control revision")
    tracked_root = _git_blob_record(
        expected_control_revision,
        PUBLIC_ROOT_REF,
        root=root,
    )
    contract = _git_blob_record(
        expected_control_revision,
        CONTRACT_REF,
        root=root,
    )
    if (
        tracked_root["file_sha256"] != EXPECTED_ROOT_SHA
        or tracked_root["git_blob_sha256"] != EXPECTED_ROOT_SHA
        or contract["file_sha256"] != EXPECTED_CONTRACT_FILE_SHA256
    ):
        raise ValueError("manual authority v2 tracked root")
    _validate_ledger_git_bindings(root=root)
    material = _read_exact_directory(authority_directory, inventory)
    if material[ROOT_FILE] != tracked_root["raw"]:
        raise ValueError("manual authority v2 installed root")
    value, keys = _validate_root(
        material[ROOT_FILE],
        expected_hash=expected_authority_root_file_sha256,
        root=root,
    )
    return {
        "authority_root_file_sha256": _sha(material[ROOT_FILE]),
        "authority_root_git_blob_sha256": tracked_root["git_blob_sha256"],
        "authority_root_git_blob_oid": tracked_root["git_blob_oid"],
        "authority_epoch_id": AUTHORITY_EPOCH_ID,
        "authority_generation_id": AUTHORITY_GENERATION_ID,
        "control_revision": expected_control_revision,
        "root_value": value,
        "authority_keys": keys,
        "provider_key_spki_sha256": keys["provider"][1],
        "confirmation_key_spki_sha256": keys["confirmation"][1],
        "local_ci_observation_key_spki_sha256": keys[
            "local_ci_observation"
        ][1],
        "authority_keys_mathematically_distinct": True,
        "independent_organizational_key_custody_proven": False,
        "post_action_readback_only": True,
        "authorizes_new_action": False,
        "readiness_credit_allowed": False,
    }


def load_verified_projection(
    *,
    expected_control_revision: str,
    expected_authority_root_file_sha256: str = EXPECTED_AUTHORITY_ROOT_FILE_SHA256,
    root: Path = ROOT,
    authority_directory: Path = AUTHORITY_DIRECTORY,
    runtime_directory: Path = RUNTIME_DIRECTORY,
) -> tuple[Any, dict[str, Any]]:
    _require_finalized()
    binding = load_activation_root(
        expected_control_revision=expected_control_revision,
        expected_authority_root_file_sha256=(
            expected_authority_root_file_sha256
        ),
        root=root,
        authority_directory=authority_directory,
        expected_inventory=CAPTURE_INVENTORY,
    )
    material = _read_exact_directory(authority_directory, CAPTURE_INVENTORY)
    if _sha(material[ROOT_FILE]) != binding["authority_root_file_sha256"]:
        raise ValueError("manual authority v2 projection root changed")
    extractor = importlib.import_module("extract_item26_manual_cost_stop_raw_v2")
    projection = extractor.extract_verified_projection(
        material[PROVIDER_RAW_FILE],
        material[ACTIONTRAIL_RAW_FILE],
        expected_control_revision=expected_control_revision,
    )
    runtime_material = _read_exact_runtime_directory(runtime_directory)
    installed_source_hashes = {
        "collector_source_sha256": _sha(
            runtime_material[Path(COLLECTOR_REF).name]
        ),
        "extractor_source_sha256": _sha(
            runtime_material[Path(EXTRACTOR_REF).name]
        ),
        "authority_source_sha256": _sha(
            runtime_material[Path(VERIFIER_REF).name]
        ),
    }
    receipt = validate_runtime_activation_receipt(
        runtime_material[ACTIVATION_RECEIPT_FILE],
        root_value=binding["root_value"],
        keys=binding["authority_keys"],
        control_revision=expected_control_revision,
        expected_authority_root_file_sha256=(
            expected_authority_root_file_sha256
        ),
        expected_source_hashes=installed_source_hashes,
        root=root,
    )
    provider = projection.provider
    actiontrail = projection.actiontrail
    expected_capture_binding = {
        **installed_source_hashes,
        "authority_epoch": binding["authority_epoch_id"],
        "authority_root_file_sha256": binding[
            "authority_root_file_sha256"
        ],
        "authority_root_git_blob_sha256": binding[
            "authority_root_git_blob_sha256"
        ],
        "activation_receipt_schema": ACTIVATION_RECEIPT_SCHEMA,
        "activation_receipt_sha256": receipt[
            "activation_receipt_sha256"
        ],
    }
    if any(
        provider.get(key) != value or actiontrail.get(key) != value
        for key, value in expected_capture_binding.items()
    ):
        raise ValueError("manual authority v2 projection activation binding")
    return projection, {
        **binding,
        **receipt,
        "provider_raw_file_sha256": _sha(material[PROVIDER_RAW_FILE]),
        "actiontrail_raw_file_sha256": _sha(material[ACTIONTRAIL_RAW_FILE]),
        "capture_binding": expected_capture_binding,
    }


def _signature_projection(envelope: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in envelope.items()
        if key != "signature_base64"
    }


def terminal_unsigned_envelope(
    *,
    role: str,
    payload: dict[str, Any],
    root_value: dict[str, Any],
    authority_root_file_sha256: str,
) -> dict[str, Any]:
    if (
        role not in ROLE_NAMES
        or type(payload) is not dict
        or not _hex64(authority_root_file_sha256)
        or type(root_value) is not dict
        or type(root_value.get("authorities")) is not dict
        or role not in root_value["authorities"]
    ):
        raise ValueError("manual authority v2 unsigned envelope input")
    key_row = root_value["authorities"][role]
    return {
        "schema": CONTEXT_ENVELOPE_SCHEMA,
        "domain": ROLE_SIGNATURE_DOMAIN_TEXT[role],
        "authority_role": role,
        "issuer": key_row["issuer"],
        "audience": key_row["audience"],
        "signature_algorithm": SIGNATURE_ALGORITHM,
        "authority_epoch_id": AUTHORITY_EPOCH_ID,
        "authority_generation_id": AUTHORITY_GENERATION_ID,
        "root_binding": {
            "task_id": TASK_ID,
            "authority_generation_id": AUTHORITY_GENERATION_ID,
            "authority_epoch_id": AUTHORITY_EPOCH_ID,
            "public_root_ref": PUBLIC_ROOT_REF,
            "authority_root_file_sha256": authority_root_file_sha256,
        },
        "payload": payload,
    }


def terminal_signature_message(unsigned: dict[str, Any], *, role: str) -> bytes:
    if (
        role not in ROLE_NAMES
        or type(unsigned) is not dict
        or "signature_base64" in unsigned
    ):
        raise ValueError("manual authority v2 signature projection")
    return ROLE_SIGNATURE_DOMAINS[role] + canonical_bytes(unsigned)


def _context_envelope(
    value: Any,
    *,
    role: str,
    payload_schema: str,
    root_value: dict[str, Any],
    key: bytes,
    authority_root_file_sha256: str,
) -> dict[str, Any]:
    expected_keys = {
        "schema",
        "domain",
        "authority_role",
        "issuer",
        "audience",
        "signature_algorithm",
        "authority_epoch_id",
        "authority_generation_id",
        "root_binding",
        "payload",
        "signature_base64",
    }
    if type(value) is not dict or set(value) != expected_keys:
        raise ValueError("manual authority v2 context envelope schema")
    payload = value.get("payload")
    unsigned = terminal_unsigned_envelope(
        role=role,
        payload=payload,
        root_value=root_value,
        authority_root_file_sha256=authority_root_file_sha256,
    )
    if (
        payload.get("schema") != payload_schema
        if type(payload) is dict
        else True
    ) or not _strict(_signature_projection(value), unsigned):
        raise ValueError("manual authority v2 context envelope identity")
    try:
        signature = base64.b64decode(
            value["signature_base64"], validate=True
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("manual authority v2 context signature encoding") from exc
    if not signature or not _verify_signature(
        terminal_signature_message(unsigned, role=role),
        signature,
        key,
    ):
        raise ValueError("manual authority v2 context signature")
    return payload


def _verify_signature(payload: bytes, signature: bytes, key: bytes) -> bool:
    before = _tool_identity(OPENSSL)
    try:
        with tempfile.TemporaryDirectory(
            prefix=".item26-v2-signature-verify-",
            dir=ROOT,
        ) as directory:
            base = Path(directory)
            for name, raw in {
                "message": payload,
                "signature": signature,
                "key": key,
            }.items():
                descriptor = os.open(
                    base / name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
                try:
                    os.write(descriptor, raw)
                finally:
                    os.close(descriptor)
            result = subprocess.run(
                [
                    str(OPENSSL),
                    "dgst",
                    "-sha256",
                    "-verify",
                    str(base / "key"),
                    "-signature",
                    str(base / "signature"),
                    str(base / "message"),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
                timeout=15,
                check=False,
            )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and _stable(OPENSSL.lstat()) == _stable(before)


def _run_row(value: Any, *, event: str, revision: str) -> bool:
    keys = {
        "run_id",
        "job_id",
        "event",
        "attempt",
        "status",
        "conclusion",
        "head_sha",
        "created_at_utc",
        "started_at_utc",
        "completed_at_utc",
        "dispatch_count",
        "rerun_count",
        "workflow_name",
        "workflow_path",
        "job_name",
        "job_count",
        "failed_step_count",
        "step_count",
        "unit_test_count",
        "unit_test_failure_count",
        "unit_test_error_count",
        "unit_test_skip_count",
        "frozen_topology_test_counts",
        "postgres_test_count",
        "readiness_check_count",
        "quality_gate_pass_count",
        "quality_expected_fail_count",
        "error_annotation_count",
        "compose_config_success",
    }
    return bool(
        type(value) is dict
        and set(value) == keys
        and type(value["run_id"]) is int
        and value["run_id"] > 0
        and type(value["job_id"]) is int
        and value["job_id"] > 0
        and value["event"] == event
        and type(value["attempt"]) is int
        and value["attempt"] == 1
        and value["status"] == "completed"
        and value["conclusion"] == "success"
        and value["head_sha"] == revision
        and _utc(value["created_at_utc"]) is not None
        and _utc(value["started_at_utc"]) is not None
        and _utc(value["completed_at_utc"]) is not None
        and _utc(value["created_at_utc"])
        <= _utc(value["started_at_utc"])
        < _utc(value["completed_at_utc"])
        and type(value["dispatch_count"]) is int
        and value["dispatch_count"] == 1
        and type(value["rerun_count"]) is int
        and value["rerun_count"] == 0
        and value["workflow_name"] == "CI"
        and value["workflow_path"] == CI_WORKFLOW_REF
        and value["job_name"] == "test"
        and type(value["job_count"]) is int
        and value["job_count"] == 1
        and type(value["failed_step_count"]) is int
        and value["failed_step_count"] == 0
        and type(value["step_count"]) is int
        and value["step_count"] == 22
        and type(value["unit_test_count"]) is int
        and value["unit_test_count"] >= 2419
        and type(value["unit_test_failure_count"]) is int
        and value["unit_test_failure_count"] == 0
        and type(value["unit_test_error_count"]) is int
        and value["unit_test_error_count"] == 0
        and type(value["unit_test_skip_count"]) is int
        and value["unit_test_skip_count"] >= 34
        and type(value["frozen_topology_test_counts"]) is list
        and value["frozen_topology_test_counts"] == [10, 1, 12, 22, 21]
        and all(
            type(item) is int
            for item in value["frozen_topology_test_counts"]
        )
        and type(value["postgres_test_count"]) is int
        and value["postgres_test_count"] == 6
        and type(value["readiness_check_count"]) is int
        and value["readiness_check_count"] >= 138
        and type(value["quality_gate_pass_count"]) is int
        and value["quality_gate_pass_count"] >= 7
        and type(value["quality_expected_fail_count"]) is int
        and value["quality_expected_fail_count"] == 1
        and type(value["error_annotation_count"]) is int
        and value["error_annotation_count"] == 0
        and value["compose_config_success"] is True
    )


def _expected_control_source_blobs(
    control_revision: str,
    *,
    root: Path,
) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for ref in CONTROL_SOURCE_REFS:
        observed = _git_blob_record(control_revision, ref, root=root)
        if ref == BOOTSTRAP_REF and (
            observed["git_blob_oid"] != EXPECTED_BOOTSTRAP_GIT_BLOB_OID
            or observed["file_sha256"] != EXPECTED_BOOTSTRAP_FILE_SHA256
            or len(observed["raw"]) != EXPECTED_BOOTSTRAP_FILE_BYTES
        ):
            raise ValueError("manual activation receipt v3 bootstrap drift")
        result[ref] = {
            "git_blob_oid": observed["git_blob_oid"],
            "file_sha256": observed["file_sha256"],
        }
    return result


def _normalize_installed_source_hashes(
    value: dict[str, str],
) -> dict[str, Any]:
    if type(value) is not dict:
        return {}
    aliases = {
        COLLECTOR_REF: (COLLECTOR_REF, "collector_source_sha256"),
        EXTRACTOR_REF: (EXTRACTOR_REF, "extractor_source_sha256"),
        VERIFIER_REF: (VERIFIER_REF, "authority_source_sha256"),
    }
    normalized: dict[str, Any] = {}
    for ref, names in aliases.items():
        for name in names:
            if name in value:
                normalized[ref] = value[name]
                break
    return normalized


def _exact_zero(value: Any) -> bool:
    return type(value) is int and value == 0


def validate_activation_receipt_unsigned_inputs(
    *,
    root_raw: bytes,
    control_revision: str,
    control_ci: dict[str, dict[str, Any]],
    control_source_blobs: dict[str, dict[str, str]],
    activated_at_utc: str,
    root: Path = ROOT,
) -> tuple[
    dict[str, Any],
    dict[str, tuple[bytes, str]],
    dict[str, dict[str, str]],
]:
    """Validate every public/Git/CI precondition before receipt signing."""
    _require_finalized()
    if not _control_lineage_is_valid(control_revision, root=root):
        raise ValueError("manual activation receipt v3 control revision")
    root_value, keys = _validate_root(
        root_raw,
        expected_hash=EXPECTED_ROOT_SHA,
        root=root,
    )
    tracked_root = _git_blob_record(control_revision, PUBLIC_ROOT_REF, root=root)
    if (
        tracked_root["raw"] != root_raw
        or tracked_root["file_sha256"] != EXPECTED_ROOT_SHA
        or tracked_root["git_blob_sha256"] != EXPECTED_ROOT_SHA
    ):
        raise ValueError("manual activation receipt v3 tracked root")
    expected_sources = _expected_control_source_blobs(
        control_revision, root=root
    )
    if (
        not _strict(control_source_blobs, expected_sources)
        or expected_sources[PUBLIC_ROOT_REF]["file_sha256"]
        != EXPECTED_ROOT_SHA
        or expected_sources[CONTRACT_REF]["file_sha256"]
        != EXPECTED_CONTRACT_FILE_SHA256
    ):
        raise ValueError("manual activation receipt v3 control source drift")
    _validate_ledger_git_bindings(root=root)
    if (
        type(control_ci) is not dict
        or set(control_ci) != {"push", "pull_request"}
        or not _run_row(
            control_ci["push"], event="push", revision=control_revision
        )
        or not _run_row(
            control_ci["pull_request"],
            event="pull_request",
            revision=control_revision,
        )
    ):
        raise ValueError("manual activation receipt v3 control CI")
    all_rows = (
        EXPECTED_A0_TERMINAL["push"],
        EXPECTED_A0_TERMINAL["pull_request"],
        EXPECTED_A1_TERMINAL["push"],
        EXPECTED_A1_TERMINAL["pull_request"],
        EXPECTED_A2_TERMINAL["push"],
        EXPECTED_A2_TERMINAL["pull_request"],
        EXPECTED_LEDGER_STOP_TERMINAL["push"],
        EXPECTED_LEDGER_STOP_TERMINAL["pull_request"],
        EXPECTED_REJECTED_BOOTSTRAP_SOURCE_TERMINAL["push"],
        EXPECTED_REJECTED_BOOTSTRAP_SOURCE_TERMINAL["pull_request"],
        EXPECTED_HELPER_SOURCE_TERMINAL["push"],
        EXPECTED_HELPER_SOURCE_TERMINAL["pull_request"],
        EXPECTED_BOOTSTRAP_LEDGER_TERMINAL["push"],
        EXPECTED_BOOTSTRAP_LEDGER_TERMINAL["pull_request"],
        EXPECTED_REJECTED_ROOT_ACTIVATION_TERMINAL["push"],
        EXPECTED_REJECTED_ROOT_ACTIVATION_TERMINAL["pull_request"],
        control_ci["push"],
        control_ci["pull_request"],
    )
    activated = _utc(activated_at_utc)
    if (
        len({row["run_id"] for row in all_rows}) != len(all_rows)
        or len({row["job_id"] for row in all_rows}) != len(all_rows)
        or max(
            _utc(EXPECTED_A2_TERMINAL["push"]["completed_at_utc"]),
            _utc(EXPECTED_A2_TERMINAL["pull_request"]["completed_at_utc"]),
        )
        >= min(
            _utc(EXPECTED_LEDGER_STOP_TERMINAL["push"]["created_at_utc"]),
            _utc(
                EXPECTED_LEDGER_STOP_TERMINAL["pull_request"][
                    "created_at_utc"
                ]
            ),
        )
        or max(
            _utc(EXPECTED_LEDGER_STOP_TERMINAL["push"]["completed_at_utc"]),
            _utc(
                EXPECTED_LEDGER_STOP_TERMINAL["pull_request"][
                    "completed_at_utc"
                ]
            ),
        )
        >= min(
            _utc(
                EXPECTED_REJECTED_BOOTSTRAP_SOURCE_TERMINAL["push"][
                    "created_at_utc"
                ]
            ),
            _utc(
                EXPECTED_REJECTED_BOOTSTRAP_SOURCE_TERMINAL[
                    "pull_request"
                ]["created_at_utc"]
            ),
        )
        or max(
            _utc(
                EXPECTED_REJECTED_BOOTSTRAP_SOURCE_TERMINAL["push"][
                    "completed_at_utc"
                ]
            ),
            _utc(
                EXPECTED_REJECTED_BOOTSTRAP_SOURCE_TERMINAL[
                    "pull_request"
                ]["completed_at_utc"]
            ),
        )
        >= min(
            _utc(EXPECTED_HELPER_SOURCE_TERMINAL["push"]["created_at_utc"]),
            _utc(
                EXPECTED_HELPER_SOURCE_TERMINAL["pull_request"]
                ["created_at_utc"]
            ),
        )
        or max(
            _utc(EXPECTED_HELPER_SOURCE_TERMINAL["push"]["completed_at_utc"]),
            _utc(
                EXPECTED_HELPER_SOURCE_TERMINAL["pull_request"]
                ["completed_at_utc"]
            ),
        )
        >= min(
            _utc(EXPECTED_BOOTSTRAP_LEDGER_TERMINAL["push"]["created_at_utc"]),
            _utc(
                EXPECTED_BOOTSTRAP_LEDGER_TERMINAL["pull_request"]
                ["created_at_utc"]
            ),
        )
        or max(
            _utc(
                EXPECTED_BOOTSTRAP_LEDGER_TERMINAL["push"]
                ["completed_at_utc"]
            ),
            _utc(
                EXPECTED_BOOTSTRAP_LEDGER_TERMINAL["pull_request"]
                ["completed_at_utc"]
            ),
        )
        >= min(
            _utc(
                EXPECTED_REJECTED_ROOT_ACTIVATION_TERMINAL["push"]
                ["created_at_utc"]
            ),
            _utc(
                EXPECTED_REJECTED_ROOT_ACTIVATION_TERMINAL[
                    "pull_request"
                ]["created_at_utc"]
            ),
        )
        or max(
            _utc(
                EXPECTED_REJECTED_ROOT_ACTIVATION_TERMINAL["push"]
                ["completed_at_utc"]
            ),
            _utc(
                EXPECTED_REJECTED_ROOT_ACTIVATION_TERMINAL[
                    "pull_request"
                ]["completed_at_utc"]
            ),
        )
        >= min(
            _utc(control_ci["push"]["created_at_utc"]),
            _utc(control_ci["pull_request"]["created_at_utc"]),
        )
        or activated is None
        or activated
        <= max(
            _utc(control_ci["push"]["completed_at_utc"]),
            _utc(control_ci["pull_request"]["completed_at_utc"]),
        )
    ):
        raise ValueError("manual activation receipt v3 pre-sign timeline")
    return root_value, keys, expected_sources


def validate_runtime_activation_receipt(
    raw: bytes,
    *,
    root_value: dict[str, Any],
    keys: dict[str, tuple[bytes, str]],
    control_revision: str,
    expected_authority_root_file_sha256: str,
    expected_source_hashes: dict[str, str],
    root: Path = ROOT,
) -> dict[str, Any]:
    _require_finalized()
    if (
        expected_authority_root_file_sha256 != EXPECTED_ROOT_SHA
        or not _control_lineage_is_valid(control_revision, root=root)
    ):
        raise ValueError("manual activation receipt v3 control revision")
    expected_root, expected_keys = _validate_root(
        canonical_bytes(root_value),
        expected_hash=expected_authority_root_file_sha256,
        root=root,
    )
    if not _strict(root_value, expected_root) or {
        role: row[1] for role, row in keys.items()
    } != {role: row[1] for role, row in expected_keys.items()}:
        raise ValueError("manual activation receipt v3 root")
    envelope = _parse(raw, "manual activation receipt v3")
    envelope_keys = {
        "schema",
        "domain",
        "authority_role",
        "issuer",
        "audience",
        "authority_epoch_id",
        "authority_generation_id",
        "root_git_binding",
        "payload",
        "signature_base64",
    }
    key_row = root_value["authorities"]["local_ci_observation"]
    tracked_root = _git_blob_record(control_revision, PUBLIC_ROOT_REF, root=root)
    expected_root_binding = {
        "repository": REPOSITORY,
        "source_ref": SOURCE_REF,
        "control_revision": control_revision,
        "public_root_ref": PUBLIC_ROOT_REF,
        "git_blob_oid": tracked_root["git_blob_oid"],
        "git_blob_sha256": tracked_root["git_blob_sha256"],
        "file_sha256": EXPECTED_ROOT_SHA,
    }
    if (
        set(envelope) != envelope_keys
        or envelope.get("schema") != ACTIVATION_RECEIPT_ENVELOPE_SCHEMA
        or envelope.get("domain") != RECEIPT_SIGNATURE_DOMAIN_TEXT
        or envelope.get("authority_role") != "local_ci_observation"
        or envelope.get("issuer") != key_row["issuer"]
        or envelope.get("audience") != key_row["audience"]
        or envelope.get("authority_epoch_id") != AUTHORITY_EPOCH_ID
        or envelope.get("authority_generation_id") != AUTHORITY_GENERATION_ID
        or not _strict(envelope.get("root_git_binding"), expected_root_binding)
    ):
        raise ValueError("manual activation receipt v3 envelope identity")
    try:
        signature = base64.b64decode(
            envelope["signature_base64"], validate=True
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("manual activation receipt v3 signature encoding") from exc
    signed = RECEIPT_SIGNATURE_DOMAIN + canonical_bytes(
        _signature_projection(envelope)
    )
    if not signature or not _verify_signature(
        signed,
        signature,
        keys["local_ci_observation"][0],
    ):
        raise ValueError("manual activation receipt v3 signature")
    expected_sources = _expected_control_source_blobs(
        control_revision,
        root=root,
    )
    installed = _normalize_installed_source_hashes(expected_source_hashes)
    if installed != {
        ref: expected_sources[ref]["file_sha256"]
        for ref in RUNTIME_SOURCE_REFS
    }:
        raise ValueError("manual activation receipt v3 installed sources")
    payload = envelope.get("payload")
    payload_keys = {
        "schema",
        "task_id",
        "historical_operation_id",
        "authority_generation_id",
        "authority_epoch_id",
        "status",
        "repository",
        "source_ref",
        "ledger_stop_revision",
        "bootstrap_ledger_acceptance_revision",
        "historical_checkpoints",
        "historical_source_blobs",
        "control_revision",
        "control_ci",
        "control_source_blobs",
        "activated_at_utc",
        "readback_started",
        "cloud_read_count",
        "cloud_write_count",
        "database_connection_count",
        "database_write_count",
        "journal_write_count",
        "fallback",
        "item26_status",
        "readiness_credit_added",
    }
    if (
        type(payload) is not dict
        or set(payload) != payload_keys
        or payload.get("schema") != ACTIVATION_RECEIPT_SCHEMA
        or payload.get("task_id") != TASK_ID
        or payload.get("historical_operation_id") != OPERATION_ID
        or payload.get("authority_generation_id") != AUTHORITY_GENERATION_ID
        or payload.get("authority_epoch_id") != AUTHORITY_EPOCH_ID
        or payload.get("status")
        != "A3_ROOT_V2_ATTEMPT1_DUAL_CI_SUCCESS_ACTIVATED"
        or payload.get("repository") != REPOSITORY
        or payload.get("source_ref") != SOURCE_REF
        or payload.get("ledger_stop_revision") != LEDGER_STOP_REVISION
        or payload.get("bootstrap_ledger_acceptance_revision")
        != BOOTSTRAP_LEDGER_ACCEPTANCE_REVISION
        or not _strict(
            payload.get("historical_checkpoints"),
            {
                "a0_terminal": EXPECTED_A0_TERMINAL,
                "a1_terminal": EXPECTED_A1_TERMINAL,
                "a2_terminal": EXPECTED_A2_TERMINAL,
                "ledger_stop_terminal": EXPECTED_LEDGER_STOP_TERMINAL,
                "rejected_bootstrap_source_terminal": (
                    EXPECTED_REJECTED_BOOTSTRAP_SOURCE_TERMINAL
                ),
                "helper_source_terminal": EXPECTED_HELPER_SOURCE_TERMINAL,
                "bootstrap_ledger_terminal": (
                    EXPECTED_BOOTSTRAP_LEDGER_TERMINAL
                ),
                "rejected_root_activation_terminal": (
                    EXPECTED_REJECTED_ROOT_ACTIVATION_TERMINAL
                ),
            },
        )
        or not _strict(
            payload.get("historical_source_blobs"),
            HISTORICAL_SOURCE_BLOBS,
        )
        or payload.get("control_revision") != control_revision
        or type(payload.get("control_ci")) is not dict
        or set(payload["control_ci"]) != {"push", "pull_request"}
        or not _run_row(
            payload["control_ci"]["push"],
            event="push",
            revision=control_revision,
        )
        or not _run_row(
            payload["control_ci"]["pull_request"],
            event="pull_request",
            revision=control_revision,
        )
        or not _strict(payload.get("control_source_blobs"), expected_sources)
        or payload.get("readback_started") is not False
        or not _exact_zero(payload.get("cloud_read_count"))
        or not _exact_zero(payload.get("cloud_write_count"))
        or not _exact_zero(payload.get("database_connection_count"))
        or not _exact_zero(payload.get("database_write_count"))
        or not _exact_zero(payload.get("journal_write_count"))
        or not _strict(
            payload.get("fallback"),
            {
                "authority_v1_used": False,
                "collector_v1_used": False,
                "receipt_v2_used": False,
            },
        )
        or payload.get("item26_status") != "unverified"
        or payload.get("readiness_credit_added") is not False
    ):
        raise ValueError("manual activation receipt v3 payload identity")
    rows = (
        EXPECTED_A0_TERMINAL["push"],
        EXPECTED_A0_TERMINAL["pull_request"],
        EXPECTED_A1_TERMINAL["push"],
        EXPECTED_A1_TERMINAL["pull_request"],
        EXPECTED_A2_TERMINAL["push"],
        EXPECTED_A2_TERMINAL["pull_request"],
        EXPECTED_LEDGER_STOP_TERMINAL["push"],
        EXPECTED_LEDGER_STOP_TERMINAL["pull_request"],
        EXPECTED_REJECTED_BOOTSTRAP_SOURCE_TERMINAL["push"],
        EXPECTED_REJECTED_BOOTSTRAP_SOURCE_TERMINAL["pull_request"],
        EXPECTED_HELPER_SOURCE_TERMINAL["push"],
        EXPECTED_HELPER_SOURCE_TERMINAL["pull_request"],
        EXPECTED_BOOTSTRAP_LEDGER_TERMINAL["push"],
        EXPECTED_BOOTSTRAP_LEDGER_TERMINAL["pull_request"],
        EXPECTED_REJECTED_ROOT_ACTIVATION_TERMINAL["push"],
        EXPECTED_REJECTED_ROOT_ACTIVATION_TERMINAL["pull_request"],
        payload["control_ci"]["push"],
        payload["control_ci"]["pull_request"],
    )
    activated = _utc(payload.get("activated_at_utc"))
    control_rows = (
        payload["control_ci"]["push"],
        payload["control_ci"]["pull_request"],
    )
    if (
        len({row["run_id"] for row in rows}) != len(rows)
        or len({row["job_id"] for row in rows}) != len(rows)
        or max(
            _utc(EXPECTED_A2_TERMINAL["push"]["completed_at_utc"]),
            _utc(EXPECTED_A2_TERMINAL["pull_request"]["completed_at_utc"]),
        )
        >= min(
            _utc(EXPECTED_LEDGER_STOP_TERMINAL["push"]["created_at_utc"]),
            _utc(
                EXPECTED_LEDGER_STOP_TERMINAL["pull_request"][
                    "created_at_utc"
                ]
            ),
        )
        or max(
            _utc(EXPECTED_LEDGER_STOP_TERMINAL["push"]["completed_at_utc"]),
            _utc(
                EXPECTED_LEDGER_STOP_TERMINAL["pull_request"][
                    "completed_at_utc"
                ]
            ),
        )
        >= min(
            _utc(
                EXPECTED_REJECTED_BOOTSTRAP_SOURCE_TERMINAL["push"][
                    "created_at_utc"
                ]
            ),
            _utc(
                EXPECTED_REJECTED_BOOTSTRAP_SOURCE_TERMINAL[
                    "pull_request"
                ]["created_at_utc"]
            ),
        )
        or max(
            _utc(
                EXPECTED_REJECTED_BOOTSTRAP_SOURCE_TERMINAL["push"][
                    "completed_at_utc"
                ]
            ),
            _utc(
                EXPECTED_REJECTED_BOOTSTRAP_SOURCE_TERMINAL[
                    "pull_request"
                ]["completed_at_utc"]
            ),
        )
        >= min(
            _utc(EXPECTED_HELPER_SOURCE_TERMINAL["push"]["created_at_utc"]),
            _utc(
                EXPECTED_HELPER_SOURCE_TERMINAL["pull_request"][
                    "created_at_utc"
                ]
            ),
        )
        or max(
            _utc(EXPECTED_HELPER_SOURCE_TERMINAL["push"]["completed_at_utc"]),
            _utc(
                EXPECTED_HELPER_SOURCE_TERMINAL["pull_request"][
                    "completed_at_utc"
                ]
            ),
        )
        >= min(
            _utc(EXPECTED_BOOTSTRAP_LEDGER_TERMINAL["push"]["created_at_utc"]),
            _utc(
                EXPECTED_BOOTSTRAP_LEDGER_TERMINAL["pull_request"][
                    "created_at_utc"
                ]
            ),
        )
        or max(
            _utc(
                EXPECTED_BOOTSTRAP_LEDGER_TERMINAL["push"][
                    "completed_at_utc"
                ]
            ),
            _utc(
                EXPECTED_BOOTSTRAP_LEDGER_TERMINAL["pull_request"][
                    "completed_at_utc"
                ]
            ),
        )
        >= min(
            _utc(
                EXPECTED_REJECTED_ROOT_ACTIVATION_TERMINAL["push"]
                ["created_at_utc"]
            ),
            _utc(
                EXPECTED_REJECTED_ROOT_ACTIVATION_TERMINAL[
                    "pull_request"
                ]["created_at_utc"]
            ),
        )
        or max(
            _utc(
                EXPECTED_REJECTED_ROOT_ACTIVATION_TERMINAL["push"]
                ["completed_at_utc"]
            ),
            _utc(
                EXPECTED_REJECTED_ROOT_ACTIVATION_TERMINAL[
                    "pull_request"
                ]["completed_at_utc"]
            ),
        )
        >= min(_utc(row["created_at_utc"]) for row in control_rows)
        or activated is None
        or activated <= max(_utc(row["completed_at_utc"]) for row in control_rows)
    ):
        raise ValueError("manual activation receipt v3 timeline")
    return {
        "activation_receipt_sha256": _sha(raw),
        "activation_receipt_semantic_sha256": _semantic(envelope),
        "activated_at_utc": payload["activated_at_utc"],
        "control_revision": control_revision,
        "authority_epoch_id": AUTHORITY_EPOCH_ID,
        "authority_root_file_sha256": EXPECTED_ROOT_SHA,
        "authority_root_git_blob_sha256": tracked_root["git_blob_sha256"],
        "authority_root_git_blob_oid": tracked_root["git_blob_oid"],
        "source_file_sha256": {
            ref: expected_sources[ref]["file_sha256"]
            for ref in RUNTIME_SOURCE_REFS
        },
        "control_ci": payload["control_ci"],
        "readback_started": False,
        "cloud_read_count": 0,
        "cloud_write_count": 0,
        "database_connection_count": 0,
        "journal_write_count": 0,
    }


def _validated_receipt_binding(value: Any) -> dict[str, str]:
    keys = {
        "receipt_file_sha256",
        "receipt_semantic_sha256",
        "terminal_acceptance_sha256",
        "raw_closure_sha256",
    }
    if (
        type(value) is not dict
        or set(value) != keys
        or any(not _hex64(value.get(key)) for key in keys)
    ):
        raise ValueError("manual authority v2 receipt binding")
    return dict(value)


def _terminal_projection_exports(
    *,
    material: dict[str, bytes],
    runtime_material: dict[str, bytes],
    root_value: dict[str, Any],
    keys: dict[str, tuple[bytes, str]],
    bundle: dict[str, Any],
    activation: dict[str, Any],
    expected_receipt_binding: dict[str, str],
    control_revision: str,
) -> tuple[dict[str, Any], dict[str, Any], Any]:
    extractor = importlib.import_module("extract_item26_manual_cost_stop_raw_v2")
    confirmation_file = _parse(
        material[CONFIRMATION_FILE],
        "manual authority v2 confirmation file",
    )
    if not _strict(confirmation_file, bundle["confirmation"]):
        raise ValueError("manual authority v2 confirmation envelope mismatch")
    confirmation = _context_envelope(
        bundle["confirmation"],
        role="confirmation",
        payload_schema=CONFIRMATION_SCHEMA,
        root_value=root_value,
        key=keys["confirmation"][0],
        authority_root_file_sha256=EXPECTED_ROOT_SHA,
    )
    provider = _context_envelope(
        bundle["provider"],
        role="provider",
        payload_schema=PROVIDER_SCHEMA,
        root_value=root_value,
        key=keys["provider"][0],
        authority_root_file_sha256=EXPECTED_ROOT_SHA,
    )
    projection = extractor.extract_verified_projection(
        material[PROVIDER_RAW_FILE],
        material[ACTIONTRAIL_RAW_FILE],
        expected_control_revision=control_revision,
    )
    provider_projection = projection.provider
    actiontrail_projection = projection.actiontrail
    runtime_hashes = {
        "collector_source_sha256": _sha(
            runtime_material[Path(COLLECTOR_REF).name]
        ),
        "extractor_source_sha256": _sha(
            runtime_material[Path(EXTRACTOR_REF).name]
        ),
        "authority_source_sha256": _sha(
            runtime_material[Path(VERIFIER_REF).name]
        ),
    }
    capture_binding = {
        **runtime_hashes,
        "authority_epoch": AUTHORITY_EPOCH_ID,
        "authority_root_file_sha256": EXPECTED_ROOT_SHA,
        "authority_root_git_blob_sha256": EXPECTED_ROOT_SHA,
        "activation_receipt_schema": ACTIVATION_RECEIPT_SCHEMA,
        "activation_receipt_sha256": activation[
            "activation_receipt_sha256"
        ],
    }
    if any(
        provider_projection.get(key) != expected
        or actiontrail_projection.get(key) != expected
        for key, expected in capture_binding.items()
    ):
        raise ValueError("manual authority v2 terminal capture binding")
    events = {
        row.get("event_name"): row
        for row in actiontrail_projection.get("events", [])
        if type(row) is dict
    }
    protection = events.get("ModifyDBInstanceDeletionProtection")
    deletion = events.get("DeleteDBInstance")
    clone_create = actiontrail_projection.get("clone_create")
    if (
        type(protection) is not dict
        or type(deletion) is not dict
        or type(clone_create) is not dict
        or actiontrail_projection.get(
            "historical_mutation_request_ids_rederived"
        )
        is not True
        or actiontrail_projection.get("historical_request_bodies_rederived")
        is not True
        or actiontrail_projection.get("historical_client_tokens_rederived")
        is not True
        or actiontrail_projection.get("old_clone_create_identity_rederived")
        is not True
    ):
        raise ValueError("manual authority v2 ActionTrail identity")
    mutation_set = extractor.consumed_mutation_identity_set_sha256(
        protection_request_id_sha256=protection.get(
            "provider_request_id_sha256"
        ),
        protection_request_body_sha256=protection.get(
            "request_body_sha256"
        ),
        protection_client_token_sha256=protection.get(
            "client_token_sha256"
        ),
        delete_request_id_sha256=deletion.get(
            "provider_request_id_sha256"
        ),
        delete_request_body_sha256=deletion.get("request_body_sha256"),
        delete_client_token_present=deletion.get("client_token_present"),
    )
    provider_digest_fields = {
        key for key in PROVIDER_PAYLOAD_KEYS if key.endswith("_sha256")
    }
    if (
        type(provider) is not dict
        or set(provider) != PROVIDER_PAYLOAD_KEYS
        or any(not _hex64(provider.get(key)) for key in provider_digest_fields)
        or provider.get("schema") != PROVIDER_SCHEMA
        or provider.get("task_id") != TASK_ID
        or provider.get("historical_operation_id") != OPERATION_ID
        or provider.get("authority_generation_id") != AUTHORITY_GENERATION_ID
        or provider.get("authority_epoch_id") != AUTHORITY_EPOCH_ID
        or provider.get("control_revision") != control_revision
        or _utc(provider.get("observed_at_utc")) is None
        or _utc(provider.get("signed_at_utc")) is None
        or provider.get("observed_at_utc")
        != provider_projection.get("observed_at_utc")
        or provider.get("observed_at_utc")
        != actiontrail_projection.get("observed_at_utc")
        or provider.get("authority_root_file_sha256") != EXPECTED_ROOT_SHA
        or provider.get("authority_root_git_blob_sha256") != EXPECTED_ROOT_SHA
        or provider.get("activation_receipt_sha256")
        != activation["activation_receipt_sha256"]
        or provider.get("provider_raw_file_sha256")
        != _sha(material[PROVIDER_RAW_FILE])
        or provider.get("actiontrail_raw_file_sha256")
        != _sha(material[ACTIONTRAIL_RAW_FILE])
        or provider.get("provider_projection_sha256")
        != _semantic(provider_projection)
        or provider.get("actiontrail_projection_sha256")
        != _semantic(actiontrail_projection)
        or any(
            provider.get(key) != expected
            for key, expected in expected_receipt_binding.items()
        )
        or provider.get("confirmation_export_semantic_sha256")
        != _semantic(confirmation)
        or provider.get("historical_user_confirmation_sha256")
        != EXPECTED_HISTORICAL_CONFIRMATION_SHA256
        or provider.get("no_replay_registry_sha256")
        != EXPECTED_NO_REPLAY_REGISTRY_SHA256
        or provider.get("consumed_mutation_identity_set_sha256")
        != EXPECTED_MUTATION_SET_SHA256
        or mutation_set != EXPECTED_MUTATION_SET_SHA256
        or provider.get("old_clone_sha256")
        != extractor.EXPECTED_OLD_CLONE_SHA256
        or provider.get("old_clone_name_sha256")
        != extractor.EXPECTED_OLD_CLONE_NAME_SHA256
        or provider.get("old_clone_create_request_sha256")
        != clone_create.get("provider_request_id_sha256")
        or provider.get("old_clone_create_body_sha256")
        != clone_create.get("request_body_sha256")
        or provider.get("old_clone_client_token_sha256")
        != clone_create.get("client_token_sha256")
        or provider.get("protection_disable_request_id_sha256")
        != extractor.EXPECTED_PROTECTION_REQUEST_ID_SHA256
        or provider.get("protection_disable_request_id_sha256")
        != protection.get("provider_request_id_sha256")
        or provider.get("protection_disable_request_body_sha256")
        != protection.get("request_body_sha256")
        or provider.get("protection_disable_client_token_sha256")
        != extractor.EXPECTED_PROTECTION_CLIENT_TOKEN_SHA256
        or provider.get("protection_disable_client_token_sha256")
        != protection.get("client_token_sha256")
        or provider.get("delete_request_id_sha256")
        != extractor.EXPECTED_DELETE_REQUEST_ID_SHA256
        or provider.get("delete_request_id_sha256")
        != deletion.get("provider_request_id_sha256")
        or provider.get("delete_request_body_sha256")
        != deletion.get("request_body_sha256")
        or provider.get("delete_client_token_present") is not False
        or deletion.get("client_token_present") is not False
        or provider.get("source_pre_tuple_sha256")
        != EXPECTED_SOURCE_PRE_TUPLE_SHA256
        or provider.get("source_post_tuple_sha256")
        != provider_projection.get("source", {}).get("tuple_sha256")
        or provider.get("source_pre_tuple_sha256")
        != provider.get("source_post_tuple_sha256")
        or provider.get("billing_snapshot_sha256")
        != _semantic(provider_projection.get("billing"))
        or provider.get("old_clone_absent") is not True
        or provider_projection.get("old_clone", {}).get("absent") is not True
        or provider.get("source_unchanged") is not True
        or provider.get("historical_billing_only") is not True
        or provider_projection.get("billing", {}).get(
            "historical_snapshot_only"
        )
        is not True
        or provider.get("new_action_authorized") is not False
        or provider.get("readiness_credit_added") is not False
    ):
        raise ValueError("manual authority v2 provider projection binding")
    confirmation_digest_fields = {
        key for key in CONFIRMATION_PAYLOAD_KEYS if key.endswith("_sha256")
    }
    if (
        type(confirmation) is not dict
        or set(confirmation) != CONFIRMATION_PAYLOAD_KEYS
        or any(
            not _hex64(confirmation.get(key))
            for key in confirmation_digest_fields
        )
        or confirmation.get("schema") != CONFIRMATION_SCHEMA
        or confirmation.get("task_id") != TASK_ID
        or confirmation.get("historical_operation_id") != OPERATION_ID
        or confirmation.get("authority_generation_id")
        != AUTHORITY_GENERATION_ID
        or confirmation.get("authority_epoch_id") != AUTHORITY_EPOCH_ID
        or confirmation.get("control_revision") != control_revision
        or _utc(confirmation.get("confirmed_at_utc")) is None
        or confirmation.get("post_action_observed_at_utc")
        != provider.get("observed_at_utc")
        or confirmation.get("authority_root_file_sha256")
        != EXPECTED_ROOT_SHA
        or confirmation.get("authority_root_git_blob_sha256")
        != EXPECTED_ROOT_SHA
        or confirmation.get("activation_receipt_sha256")
        != activation["activation_receipt_sha256"]
        or confirmation.get("provider_raw_file_sha256")
        != _sha(material[PROVIDER_RAW_FILE])
        or confirmation.get("actiontrail_raw_file_sha256")
        != _sha(material[ACTIONTRAIL_RAW_FILE])
        or confirmation.get("provider_projection_sha256")
        != _semantic(provider_projection)
        or confirmation.get("actiontrail_projection_sha256")
        != _semantic(actiontrail_projection)
        or any(
            confirmation.get(key) != expected
            for key, expected in expected_receipt_binding.items()
        )
        or confirmation.get("historical_user_confirmation_sha256")
        != EXPECTED_HISTORICAL_CONFIRMATION_SHA256
        or confirmation.get("no_replay_registry_sha256")
        != EXPECTED_NO_REPLAY_REGISTRY_SHA256
        or confirmation.get("consumed_mutation_identity_set_sha256")
        != EXPECTED_MUTATION_SET_SHA256
        or confirmation.get("retroactive_action_authorization") is not False
        or confirmation.get("new_action_authorization") is not False
        or confirmation.get("readiness_credit_added") is not False
    ):
        raise ValueError("manual authority v2 confirmation binding")
    return provider, confirmation, projection


def _validate_terminal_artifacts(
    *,
    control_revision: str,
    evidence_revision: str,
    terminal_revision: str,
    ci: dict[str, Any],
    expected_receipt_binding: dict[str, str],
    root: Path,
) -> None:
    artifact_refs = (RECEIPT_REF, EVIDENCE_REF, CHECKPOINT_REF)
    if any(
        not git_blob_absent(control_revision, ref, root=root)
        for ref in artifact_refs
    ):
        raise ValueError("manual authority v2 control artifact present")
    if (
        git_blob_absent(evidence_revision, RECEIPT_REF, root=root)
        or git_blob_absent(evidence_revision, EVIDENCE_REF, root=root)
        or not git_blob_absent(evidence_revision, CHECKPOINT_REF, root=root)
    ):
        raise ValueError("manual authority v2 evidence artifact inventory")
    evidence_receipt = _git_blob_record(
        evidence_revision, RECEIPT_REF, root=root
    )
    evidence_evidence = _git_blob_record(
        evidence_revision, EVIDENCE_REF, root=root
    )
    terminal_records = {
        ref: _git_blob_record(terminal_revision, ref, root=root)
        for ref in artifact_refs
    }
    receipt_value = _parse(
        evidence_receipt["raw"], "manual authority v2 evidence receipt"
    )
    if (
        evidence_receipt["file_sha256"]
        != expected_receipt_binding["receipt_file_sha256"]
        or _semantic(receipt_value)
        != expected_receipt_binding["receipt_semantic_sha256"]
        or evidence_evidence["file_sha256"] != ci["evidence_file_sha256"]
        or terminal_records[RECEIPT_REF]["file_sha256"]
        != expected_receipt_binding["receipt_file_sha256"]
        or terminal_records[EVIDENCE_REF]["file_sha256"]
        != ci["evidence_file_sha256"]
        or terminal_records[CHECKPOINT_REF]["file_sha256"]
        != ci["checkpoint_file_sha256"]
    ):
        raise ValueError("manual authority v2 terminal artifact binding")


def _validate_terminal_ci(
    *,
    ci: dict[str, Any],
    provider: dict[str, Any],
    confirmation: dict[str, Any],
    projection: Any,
    activation: dict[str, Any],
    material: dict[str, bytes],
    expected_receipt_binding: dict[str, str],
    control_revision: str,
    evidence_revision: str,
    terminal_revision: str,
    root: Path,
) -> None:
    provider_projection = projection.provider
    actiontrail_projection = projection.actiontrail
    digest_fields = {
        key for key in LOCAL_CI_PAYLOAD_KEYS if key.endswith("_sha256")
    }
    expected_control_sources = _expected_control_source_blobs(
        control_revision, root=root
    )
    if (
        type(ci) is not dict
        or set(ci) != LOCAL_CI_PAYLOAD_KEYS
        or any(not _hex64(ci.get(key)) for key in digest_fields)
        or ci.get("schema") != LOCAL_CI_SCHEMA
        or ci.get("task_id") != TASK_ID
        or ci.get("historical_operation_id") != OPERATION_ID
        or ci.get("authority_generation_id") != AUTHORITY_GENERATION_ID
        or ci.get("authority_epoch_id") != AUTHORITY_EPOCH_ID
        or ci.get("status")
        != "POST_ACTION_RECONCILIATION_TERMINAL_AUTHORITY_V2"
        or ci.get("control_revision") != control_revision
        or ci.get("evidence_revision") != evidence_revision
        or ci.get("terminal_revision") != terminal_revision
        or ci.get("repository") != REPOSITORY
        or ci.get("source_ref") != SOURCE_REF
        or ci.get("authority_root_file_sha256") != EXPECTED_ROOT_SHA
        or ci.get("authority_root_git_blob_sha256") != EXPECTED_ROOT_SHA
        or ci.get("activation_receipt_sha256")
        != activation["activation_receipt_sha256"]
        or ci.get("provider_export_semantic_sha256") != _semantic(provider)
        or ci.get("confirmation_export_semantic_sha256")
        != _semantic(confirmation)
        or ci.get("provider_raw_file_sha256")
        != _sha(material[PROVIDER_RAW_FILE])
        or ci.get("actiontrail_raw_file_sha256")
        != _sha(material[ACTIONTRAIL_RAW_FILE])
        or ci.get("provider_projection_sha256")
        != _semantic(provider_projection)
        or ci.get("actiontrail_projection_sha256")
        != _semantic(actiontrail_projection)
        or any(
            ci.get(key) != expected
            for key, expected in expected_receipt_binding.items()
        )
        or not _strict(ci.get("control_sources"), expected_control_sources)
        or _utc(ci.get("terminal_accepted_at_utc")) is None
    ):
        raise ValueError("manual authority v2 local CI identity")
    for revision in (evidence_revision, terminal_revision):
        for ref, expected in expected_control_sources.items():
            observed = _git_blob_record(revision, ref, root=root)
            if (
                observed["git_blob_oid"] != expected["git_blob_oid"]
                or observed["file_sha256"] != expected["file_sha256"]
            ):
                raise ValueError("manual authority v2 control source drift")
    rows = (
        (ci["control_push"], "push", control_revision),
        (ci["control_pull_request"], "pull_request", control_revision),
        (ci["evidence_push"], "push", evidence_revision),
        (ci["evidence_pull_request"], "pull_request", evidence_revision),
        (ci["terminal_push"], "push", terminal_revision),
        (ci["terminal_pull_request"], "pull_request", terminal_revision),
    )
    if not all(
        _run_row(row, event=event, revision=revision)
        for row, event, revision in rows
    ):
        raise ValueError("manual authority v2 CI row")
    if not _strict(
        activation["control_ci"],
        {
            "push": ci["control_push"],
            "pull_request": ci["control_pull_request"],
        },
    ):
        raise ValueError("manual authority v2 activation CI binding")
    historical_rows = (
        EXPECTED_A0_TERMINAL["push"],
        EXPECTED_A0_TERMINAL["pull_request"],
        EXPECTED_A1_TERMINAL["push"],
        EXPECTED_A1_TERMINAL["pull_request"],
        EXPECTED_A2_TERMINAL["push"],
        EXPECTED_A2_TERMINAL["pull_request"],
        EXPECTED_LEDGER_STOP_TERMINAL["push"],
        EXPECTED_LEDGER_STOP_TERMINAL["pull_request"],
        EXPECTED_REJECTED_BOOTSTRAP_SOURCE_TERMINAL["push"],
        EXPECTED_REJECTED_BOOTSTRAP_SOURCE_TERMINAL["pull_request"],
        EXPECTED_HELPER_SOURCE_TERMINAL["push"],
        EXPECTED_HELPER_SOURCE_TERMINAL["pull_request"],
        EXPECTED_BOOTSTRAP_LEDGER_TERMINAL["push"],
        EXPECTED_BOOTSTRAP_LEDGER_TERMINAL["pull_request"],
        EXPECTED_REJECTED_ROOT_ACTIVATION_TERMINAL["push"],
        EXPECTED_REJECTED_ROOT_ACTIVATION_TERMINAL["pull_request"],
        *(row for row, _event, _revision in rows),
    )
    if (
        len({row["run_id"] for row in historical_rows})
        != len(historical_rows)
        or len({row["job_id"] for row in historical_rows})
        != len(historical_rows)
    ):
        raise ValueError("manual authority v2 historical CI reuse")
    control_completed = max(
        _utc(ci["control_push"]["completed_at_utc"]),
        _utc(ci["control_pull_request"]["completed_at_utc"]),
    )
    first_raw_started = min(
        _utc(provider_projection["first_started_at_utc"]),
        _utc(actiontrail_projection["first_started_at_utc"]),
    )
    raw_observed = _utc(provider_projection["observed_at_utc"])
    evidence_created = min(
        _utc(ci["evidence_push"]["created_at_utc"]),
        _utc(ci["evidence_pull_request"]["created_at_utc"]),
    )
    evidence_completed = max(
        _utc(ci["evidence_push"]["completed_at_utc"]),
        _utc(ci["evidence_pull_request"]["completed_at_utc"]),
    )
    terminal_created = min(
        _utc(ci["terminal_push"]["created_at_utc"]),
        _utc(ci["terminal_pull_request"]["created_at_utc"]),
    )
    terminal_completed = max(
        _utc(ci["terminal_push"]["completed_at_utc"]),
        _utc(ci["terminal_pull_request"]["completed_at_utc"]),
    )
    if not (
        control_completed
        < _utc(activation["activated_at_utc"])
        < first_raw_started
        <= raw_observed
        < evidence_created
        and evidence_completed < terminal_created
        and terminal_completed < _utc(confirmation["confirmed_at_utc"])
        <= _utc(provider["signed_at_utc"])
        < _utc(ci["terminal_accepted_at_utc"])
    ):
        raise ValueError("manual authority v2 terminal timeline")
    _validate_terminal_artifacts(
        control_revision=control_revision,
        evidence_revision=evidence_revision,
        terminal_revision=terminal_revision,
        ci=ci,
        expected_receipt_binding=expected_receipt_binding,
        root=root,
    )


def validate_authority_bundle(
    *,
    expected_authority_root_file_sha256: str,
    expected_receipt_binding: dict[str, str],
    root: Path = ROOT,
    authority_directory: Path = AUTHORITY_DIRECTORY,
    runtime_directory: Path = RUNTIME_DIRECTORY,
) -> tuple[list[str], Optional[dict[str, Any]]]:
    try:
        _require_finalized()
    except ValueError as exc:
        return [str(exc)], None
    if expected_authority_root_file_sha256 != EXPECTED_ROOT_SHA:
        return ["manual authority v2 terminal root hash"], None
    try:
        receipt_binding = _validated_receipt_binding(
            expected_receipt_binding
        )
        material = _read_exact_directory(
            authority_directory, FINAL_INVENTORY
        )
        runtime_material = _read_exact_runtime_directory(runtime_directory)
        bundle = _parse(
            material[BUNDLE_FILE], "manual authority v2 bundle"
        )
        bundle_keys = {
            "schema",
            "task_id",
            "historical_operation_id",
            "authority_generation_id",
            "authority_epoch_id",
            "status",
            "control_revision",
            "evidence_revision",
            "terminal_revision",
            "provider",
            "confirmation",
            "local_ci_observation",
        }
        if type(bundle) is not dict or set(bundle) != bundle_keys:
            raise ValueError("manual authority v2 bundle schema")
        control_revision = bundle["control_revision"]
        evidence_revision = bundle["evidence_revision"]
        terminal_revision = bundle["terminal_revision"]
        if (
            bundle["schema"] != BUNDLE_SCHEMA
            or bundle["task_id"] != TASK_ID
            or bundle["historical_operation_id"] != OPERATION_ID
            or bundle["authority_generation_id"] != AUTHORITY_GENERATION_ID
            or bundle["authority_epoch_id"] != AUTHORITY_EPOCH_ID
            or bundle["status"]
            != "POST_ACTION_RECONCILIATION_TERMINAL_AUTHORITY_V2"
            or any(
                HEX40.fullmatch(value or "") is None
                for value in (
                    control_revision,
                    evidence_revision,
                    terminal_revision,
                )
            )
            or not _control_lineage_is_valid(control_revision, root=root)
            or not revision_is_strict_ancestor(
                control_revision, evidence_revision, root=root
            )
            or not revision_is_strict_ancestor(
                evidence_revision, terminal_revision, root=root
            )
        ):
            raise ValueError("manual authority v2 bundle identity")
        activation_root = load_activation_root(
            expected_control_revision=control_revision,
            expected_authority_root_file_sha256=(
                expected_authority_root_file_sha256
            ),
            root=root,
            authority_directory=authority_directory,
            expected_inventory=FINAL_INVENTORY,
        )
        root_value = activation_root["root_value"]
        keys = activation_root["authority_keys"]
        installed_sources = {
            "collector_source_sha256": _sha(
                runtime_material[Path(COLLECTOR_REF).name]
            ),
            "extractor_source_sha256": _sha(
                runtime_material[Path(EXTRACTOR_REF).name]
            ),
            "authority_source_sha256": _sha(
                runtime_material[Path(VERIFIER_REF).name]
            ),
        }
        activation = validate_runtime_activation_receipt(
            runtime_material[ACTIVATION_RECEIPT_FILE],
            root_value=root_value,
            keys=keys,
            control_revision=control_revision,
            expected_authority_root_file_sha256=(
                expected_authority_root_file_sha256
            ),
            expected_source_hashes=installed_sources,
            root=root,
        )
        provider, confirmation, projection = _terminal_projection_exports(
            material=material,
            runtime_material=runtime_material,
            root_value=root_value,
            keys=keys,
            bundle=bundle,
            activation=activation,
            expected_receipt_binding=receipt_binding,
            control_revision=control_revision,
        )
        ci = _context_envelope(
            bundle["local_ci_observation"],
            role="local_ci_observation",
            payload_schema=LOCAL_CI_SCHEMA,
            root_value=root_value,
            key=keys["local_ci_observation"][0],
            authority_root_file_sha256=EXPECTED_ROOT_SHA,
        )
        _validate_terminal_ci(
            ci=ci,
            provider=provider,
            confirmation=confirmation,
            projection=projection,
            activation=activation,
            material=material,
            expected_receipt_binding=receipt_binding,
            control_revision=control_revision,
            evidence_revision=evidence_revision,
            terminal_revision=terminal_revision,
            root=root,
        )
    except OSError:
        return ["manual authority v2 material is not installed"], None
    except (KeyError, TypeError, ValueError, subprocess.SubprocessError) as exc:
        return ["manual authority v2 rejected: " + str(exc)], None
    provider_projection = projection.provider
    actiontrail_projection = projection.actiontrail
    return [], {
        "authority_generation_id": AUTHORITY_GENERATION_ID,
        "authority_epoch_id": AUTHORITY_EPOCH_ID,
        "authority_root_file_sha256": EXPECTED_ROOT_SHA,
        "authority_root_git_blob_sha256": EXPECTED_ROOT_SHA,
        "authority_bundle_file_sha256": _sha(material[BUNDLE_FILE]),
        "activation_receipt_sha256": activation[
            "activation_receipt_sha256"
        ],
        "provider_raw_file_sha256": _sha(material[PROVIDER_RAW_FILE]),
        "actiontrail_raw_file_sha256": _sha(
            material[ACTIONTRAIL_RAW_FILE]
        ),
        "provider_projection_sha256": _semantic(provider_projection),
        "actiontrail_projection_sha256": _semantic(actiontrail_projection),
        "confirmation_envelope_file_sha256": _sha(
            material[CONFIRMATION_FILE]
        ),
        "receipt_file_sha256": ci["receipt_file_sha256"],
        "receipt_semantic_sha256": ci["receipt_semantic_sha256"],
        "evidence_file_sha256": ci["evidence_file_sha256"],
        "checkpoint_file_sha256": ci["checkpoint_file_sha256"],
        "raw_closure_sha256": ci["raw_closure_sha256"],
        "provider_export_semantic_sha256": _semantic(provider),
        "confirmation_export_semantic_sha256": _semantic(confirmation),
        "provider_key_spki_sha256": keys["provider"][1],
        "confirmation_key_spki_sha256": keys["confirmation"][1],
        "local_ci_observation_key_spki_sha256": keys[
            "local_ci_observation"
        ][1],
        "authority_keys_distinct": True,
        "terminal_acceptance_sha256": provider[
            "terminal_acceptance_sha256"
        ],
        "old_clone_sha256": provider["old_clone_sha256"],
        "old_clone_name_sha256": provider["old_clone_name_sha256"],
        "source_pre_tuple_sha256": provider["source_pre_tuple_sha256"],
        "source_post_tuple_sha256": provider["source_post_tuple_sha256"],
        "billing_snapshot_sha256": provider["billing_snapshot_sha256"],
        "no_replay_registry_sha256": provider[
            "no_replay_registry_sha256"
        ],
        "old_clone_create_request_sha256": provider[
            "old_clone_create_request_sha256"
        ],
        "old_clone_create_body_sha256": provider[
            "old_clone_create_body_sha256"
        ],
        "old_clone_client_token_sha256": provider[
            "old_clone_client_token_sha256"
        ],
        "protection_disable_request_id_sha256": provider[
            "protection_disable_request_id_sha256"
        ],
        "protection_disable_request_body_sha256": provider[
            "protection_disable_request_body_sha256"
        ],
        "protection_disable_client_token_sha256": provider[
            "protection_disable_client_token_sha256"
        ],
        "delete_request_id_sha256": provider[
            "delete_request_id_sha256"
        ],
        "delete_request_body_sha256": provider[
            "delete_request_body_sha256"
        ],
        "delete_client_token_present": False,
        "consumed_mutation_identity_set_sha256": provider[
            "consumed_mutation_identity_set_sha256"
        ],
        "post_action_observed_at_utc": provider["observed_at_utc"],
        "control_revision": control_revision,
        "evidence_revision": evidence_revision,
        "terminal_revision": terminal_revision,
        "terminal_accepted_at_utc": ci["terminal_accepted_at_utc"],
        "authorizes_new_action": False,
        "readiness_credit_allowed": False,
    }


__all__ = [
    "ACTIONTRAIL_RAW_FILE",
    "ACTIVATION_INVENTORY",
    "ACTIVATION_RECEIPT_ENVELOPE_SCHEMA",
    "ACTIVATION_RECEIPT_FILE",
    "ACTIVATION_RECEIPT_SCHEMA",
    "AUTHORITY_DIRECTORY",
    "AUTHORITY_EPOCH",
    "AUTHORITY_EPOCH_ID",
    "AUTHORITY_GENERATION_ID",
    "AUTHORITY_V2_FINALIZED",
    "BOOTSTRAP_AUTHORIZATION_ANCHOR_REVISION",
    "BOOTSTRAP_LEDGER_ACCEPTANCE_REVISION",
    "BOOTSTRAP_REF",
    "BUNDLE_FILE",
    "BUNDLE_SCHEMA",
    "CAPTURE_INVENTORY",
    "COLLECTOR_REF",
    "CONFIRMATION_FILE",
    "CONFIRMATION_SCHEMA",
    "CONTEXT_ENVELOPE_SCHEMA",
    "CONTRACT_REF",
    "CONTROL_SOURCE_REFS",
    "CUSTODY_DIRECTORY",
    "EXPECTED_A0_TERMINAL",
    "EXPECTED_A1_TERMINAL",
    "EXPECTED_A2_TERMINAL",
    "EXPECTED_LEDGER_STOP_TERMINAL",
    "EXPECTED_REJECTED_BOOTSTRAP_SOURCE_TERMINAL",
    "EXPECTED_HELPER_SOURCE_TERMINAL",
    "EXPECTED_BOOTSTRAP_LEDGER_TERMINAL",
    "EXPECTED_REJECTED_ROOT_ACTIVATION_TERMINAL",
    "EXPECTED_AUTHORITY_ROOT_FILE_SHA256",
    "EXPECTED_CONTRACT_FILE_SHA256",
    "EXPECTED_ROOT_SHA",
    "EXTRACTOR_REF",
    "FINAL_INVENTORY",
    "HISTORICAL_SOURCE_BLOBS",
    "INSTALLER_REF",
    "JOURNAL_DIRECTORY",
    "LEDGER_STOP_REVISION",
    "LOCAL_CI_SCHEMA",
    "OPERATION_ID",
    "PROVIDER_SCHEMA",
    "PROVIDER_RAW_FILE",
    "PUBLIC_ROOT_REF",
    "RECEIPT_SIGNATURE_DOMAIN",
    "RECEIPT_SIGNATURE_DOMAIN_TEXT",
    "REJECTED_ROOT_ACTIVATION_REVISION",
    "ROLE_SIGNATURE_DOMAIN_TEXT",
    "ROLE_NAMES",
    "ROOT",
    "ROOT_FILE",
    "ROOT_SCHEMA",
    "RUNTIME_DIRECTORY",
    "RUNTIME_INVENTORY",
    "RUNTIME_SOURCE_REFS",
    "SIGNATURE_ALGORITHM",
    "TASK_ID",
    "authority_root_document",
    "canonical_bytes",
    "git_blob_absent",
    "git_blob_bytes",
    "load_activation_root",
    "load_verified_projection",
    "public_key_row",
    "revision_is_strict_ancestor",
    "terminal_signature_message",
    "terminal_unsigned_envelope",
    "validate_activation_receipt_unsigned_inputs",
    "validate_authority_bundle",
    "validate_runtime_activation_receipt",
    "VERIFIER_REF",
]
