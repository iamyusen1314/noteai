#!/usr/bin/env python3
"""Pure builder for Item 26 manual post-action cost-stop artifacts."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from verify_item26_manual_cost_stop_authority_v1 import (
    AUTHORITY_DIRECTORY,
    load_verified_projection,
)
from verify_item26_manual_cost_stop_evidence_v1 import (
    CHECKPOINT_SCHEMA,
    EVIDENCE_SCHEMA,
    EXPECTED_AUTHORITY_ROOT_FILE_SHA256,
    EXPECTED_CONSUMED_MANUAL_MUTATION_SET_SHA256,
    EXPECTED_DELETE_COMMITMENTS,
    EXPECTED_IDENTITY_COMMITMENTS,
    EXPECTED_NO_REPLAY_ENTRY_COUNT,
    EXPECTED_NO_REPLAY_REGISTRY_SHA256,
    EXPECTED_PROTECTION_COMMITMENTS,
    EXPECTED_SOURCE_PRE_TUPLE_SHA256,
    KIND,
    MANUAL_RAW_EXTRACTOR_FINALIZED,
    OPERATION_ID,
    READINESS_25_TO_25,
    RAW_PROVIDER_EXTRACTION_IMPLEMENTED,
    RECEIPT_SCHEMA,
    TASK_ID,
    TERMINAL_STATUS,
    canonical_bytes,
    raw_closure_sha256,
    semantic_sha256,
    sha256,
    terminal_acceptance_sha256,
    validate_checkpoint,
    validate_evidence,
    validate_receipt,
)


BUILDER_REF = "tools/build_item26_manual_cost_stop_evidence_v1.py"


def build_receipt(
    *,
    expected_control_revision: str,
    root: Path = Path(__file__).resolve().parents[1],
    authority_directory: Path = AUTHORITY_DIRECTORY,
) -> dict[str, Any]:
    projection, _binding = load_verified_projection(
        expected_control_revision=expected_control_revision,
        expected_authority_root_file_sha256=(
            EXPECTED_AUTHORITY_ROOT_FILE_SHA256
        ),
        root=root,
        authority_directory=authority_directory,
    )
    if projection.control_revision != expected_control_revision:
        raise ValueError("manual projection revision mismatch")
    provider = projection.provider
    trail = projection.actiontrail
    if (
        provider.get("observed_at_utc") != trail.get("observed_at_utc")
        or
        trail.get("historical_mutation_request_ids_rederived") is not True
        or trail.get("historical_request_bodies_rederived") is not True
        or trail.get("historical_client_tokens_rederived") is not True
        or trail.get("old_clone_create_identity_rederived") is not True
    ):
        raise ValueError("manual historical predecessor identity incomplete")
    events = {
        row.get("event_name"): row
        for row in trail.get("events", [])
        if type(row) is dict
    }
    protection_event = events.get(
        "ModifyDBInstanceDeletionProtection"
    )
    delete_event = events.get("DeleteDBInstance")
    create_event = trail.get("clone_create")
    if any(
        type(row) is not dict
        for row in (protection_event, delete_event, create_event)
    ):
        raise ValueError("manual historical predecessor event set incomplete")
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "schema": RECEIPT_SCHEMA,
        "task_id": TASK_ID,
        "operation_id": OPERATION_ID,
        "kind": KIND,
        "status": TERMINAL_STATUS,
        "observed_at_utc": provider["observed_at_utc"],
        "ledger_context_revision": (
            "41c489cf5ebfedfa2959bcee1f09183a9491f7f6"
        ),
        "control_revision": expected_control_revision,
        "action_precedes_control_checkpoint": True,
        "abort_v1_terminal_authority": False,
        "action_authorization_granted": False,
        "item26_verified": False,
        "identity_ledger": {
            **copy.deepcopy(EXPECTED_IDENTITY_COMMITMENTS),
            "old_clone_create_request_sha256": create_event[
                "provider_request_id_sha256"
            ],
            "old_clone_create_body_sha256": create_event[
                "request_body_sha256"
            ],
            "old_clone_client_token_sha256": create_event[
                "client_token_sha256"
            ],
        },
        "mutation_outcomes": {
            "protection_disable": {
                "operation": "ModifyDBInstanceDeletionProtection",
                "target_sha256": EXPECTED_IDENTITY_COMMITMENTS[
                    "old_clone_sha256"
                ],
                "request_id_sha256": protection_event[
                    "provider_request_id_sha256"
                ],
                "request_body_sha256": protection_event[
                    "request_body_sha256"
                ],
                "response_sha256": EXPECTED_PROTECTION_COMMITMENTS[
                    "response_sha256"
                ],
                "client_token_sha256": protection_event[
                    "client_token_sha256"
                ],
                "same_identity_readback_sha256": (
                    EXPECTED_PROTECTION_COMMITMENTS[
                        "same_identity_readback_sha256"
                    ]
                ),
                "submit_count": 1,
                "automatic_retry_count": 0,
                "manual_resend_count": 0,
                "replacement_count": 0,
                "outcome": "PROTECTION_FALSE_READBACK_CONFIRMED",
            },
            "delete": {
                "operation": "DeleteDBInstance",
                "target_sha256": EXPECTED_IDENTITY_COMMITMENTS[
                    "old_clone_sha256"
                ],
                "request_id_sha256": delete_event[
                    "provider_request_id_sha256"
                ],
                "request_body_sha256": delete_event[
                    "request_body_sha256"
                ],
                "response_sha256": EXPECTED_DELETE_COMMITMENTS[
                    "response_sha256"
                ],
                "client_token_present": delete_event[
                    "client_token_present"
                ],
                "exact_identity_absence_readback_sha256": (
                    EXPECTED_DELETE_COMMITMENTS[
                        "exact_identity_absence_readback_sha256"
                    ]
                ),
                "submit_count": 1,
                "automatic_retry_count": 0,
                "manual_resend_count": 0,
                "replacement_count": 0,
                "outcome": "DELETE_ACCEPTED_EXACT_ID_ABSENT",
            },
            "ordered_mutation_set_sha256": "",
        },
        "source_reconciliation": {
            "pre_tuple_sha256": EXPECTED_SOURCE_PRE_TUPLE_SHA256,
            "post_tuple_sha256": provider["source"]["tuple_sha256"],
            "source_unchanged": True,
            "source_status": provider["source"]["status"],
            "source_pay_type": provider["source"]["pay_type"],
            "source_deleted": False,
        },
        "billing_snapshot": {
            key: copy.deepcopy(provider["billing"][key])
            for key in (
                "currency",
                "pretax_gross_cny",
                "service_seconds",
                "response_sha256",
                "recorded_baseline_pretax_gross_cny",
                "recorded_baseline_service_seconds",
                "recorded_baseline_response_sha256",
                "historical_snapshot_only",
                "native_non_accruing_marker_proven",
                "settlement_terminal_proven",
            )
        },
        "residual_resources": {
            "non_clone_resource_disposition": (
                "UNPROVEN_RETAINED_FRESH_PREFLIGHT_REQUIRED"
            ),
            "temporary_account_cleanup_terminal": False,
            "iam_cleanup_terminal": False,
            "vswitch_cleanup_terminal": False,
            "shared_builder_retained": True,
            "shared_disk_retained": True,
        },
        "raw_closure": {
            "provider_raw_file_sha256": provider[
                "provider_raw_file_sha256"
            ],
            "actiontrail_raw_file_sha256": trail[
                "actiontrail_raw_file_sha256"
            ],
            "provider_projection_sha256": semantic_sha256(provider),
            "actiontrail_projection_sha256": semantic_sha256(trail),
            "complete_pagination_proven": True,
            "secret_free_projection": True,
            "historical_response_commitments_are_ledger_context": True,
            "historical_response_bytes_rederived_from_fresh_raw": False,
        },
        "no_replay": {
            "registry_schema": "noteai.item26.no-replay-registry.v2",
            "registry_sha256": EXPECTED_NO_REPLAY_REGISTRY_SHA256,
            "entry_count": EXPECTED_NO_REPLAY_ENTRY_COUNT,
            "automatic_retry_allowed": False,
            "manual_resend_allowed": False,
            "replacement_allowed": False,
            "historical_script_execution_count": 0,
        },
        "execution_boundary": {
            "cloud_control_plane_write_count": 2,
            "rds_control_plane_write_count": 2,
            "database_connection_count": 0,
            "database_transaction_count": 0,
            "database_write_count": 0,
            "object_write_count": 0,
            "builder_start_count": 0,
            "cloud_assistant_dispatch_count": 0,
            "sendfile_dispatch_count": 0,
            "new_paid_resource_count": 0,
            "readiness_write_count": 0,
        },
        "readiness": copy.deepcopy(READINESS_25_TO_25),
        "terminal_acceptance_sha256": "",
    }
    receipt["mutation_outcomes"]["ordered_mutation_set_sha256"] = (
        EXPECTED_CONSUMED_MANUAL_MUTATION_SET_SHA256
    )
    receipt["terminal_acceptance_sha256"] = terminal_acceptance_sha256(
        receipt
    )
    errors, acceptance = validate_receipt(
        receipt,
        expected_control_revision=expected_control_revision,
    )
    if errors or acceptance is None:
        raise ValueError(
            errors[0] if errors else "manual terminal acceptance missing"
        )
    return receipt


def build_evidence(
    receipt: Any,
    *,
    expected_control_revision: str,
    root: Path = Path(__file__).resolve().parents[1],
    authority_directory: Path = AUTHORITY_DIRECTORY,
) -> dict[str, Any]:
    if not (
        MANUAL_RAW_EXTRACTOR_FINALIZED
        and RAW_PROVIDER_EXTRACTION_IMPLEMENTED
        and len(EXPECTED_AUTHORITY_ROOT_FILE_SHA256) == 64
    ):
        raise ValueError("manual cost-stop external authority is not finalized")
    if type(receipt) is not dict:
        raise ValueError("manual terminal receipt required")
    receipt_raw = canonical_bytes(receipt)
    errors, acceptance = validate_receipt(
        receipt,
        expected_control_revision=expected_control_revision,
    )
    if errors or acceptance is None:
        raise ValueError(errors[0] if errors else "manual acceptance missing")
    evidence = {
        "schema_version": 1,
        "schema": EVIDENCE_SCHEMA,
        "task_id": TASK_ID,
        "operation_id": OPERATION_ID,
        "kind": KIND,
        "status": "CANDIDATE_NO_READINESS_CREDIT",
        "control_revision": expected_control_revision,
        "provider_receipt": {
            "file_sha256": sha256(receipt_raw),
            "semantic_sha256": semantic_sha256(receipt),
            "terminal_acceptance_sha256": acceptance,
            "raw_closure_sha256": raw_closure_sha256(receipt),
        },
        "external_authority": {
            "required": True,
            "provider_authority_validated": False,
            "confirmation_authority_validated": False,
            "ci_authority_validated": False,
            "mathematically_distinct_key_count": 3,
            "root_frozen_before_action": False,
            "authorizes_new_action": False,
            "terminal_authority_pending": True,
        },
        "cost_stop_outcome": {
            "status": TERMINAL_STATUS,
            "old_clone_absent": True,
            "source_unchanged": True,
            "abort_v1_terminal_authority": False,
            "action_authorization_granted": False,
            "item26_verified": False,
            "native_non_accruing_marker_proven": False,
            "settlement_terminal_proven": False,
            "non_clone_resource_disposition": (
                "UNPROVEN_RETAINED_FRESH_PREFLIGHT_REQUIRED"
            ),
        },
        "no_replay": copy.deepcopy(receipt["no_replay"]),
        "secret_free_evidence": {
            "complete_resource_identifier_value_count": 0,
            "raw_provider_payload_count": 0,
            "credential_value_count": 0,
            "private_key_value_count": 0,
            "database_row_value_count": 0,
        },
        "readiness": copy.deepcopy(READINESS_25_TO_25),
    }
    evidence_errors = validate_evidence(
        evidence,
        receipt,
        receipt_raw,
        expected_control_revision=expected_control_revision,
    )
    if evidence_errors:
        raise ValueError(evidence_errors[0])
    return evidence


def build_checkpoint(
    *,
    receipt: dict[str, Any],
    evidence: dict[str, Any],
    expected_control_revision: str,
    evidence_revision: str,
) -> dict[str, Any]:
    if not (
        MANUAL_RAW_EXTRACTOR_FINALIZED
        and RAW_PROVIDER_EXTRACTION_IMPLEMENTED
        and len(EXPECTED_AUTHORITY_ROOT_FILE_SHA256) == 64
    ):
        raise ValueError("manual cost-stop external authority is not finalized")
    receipt_raw = canonical_bytes(receipt)
    evidence_raw = canonical_bytes(evidence)
    receipt_errors, acceptance = validate_receipt(
        receipt,
        expected_control_revision=expected_control_revision,
    )
    if receipt_errors or acceptance is None:
        raise ValueError(
            receipt_errors[0]
            if receipt_errors
            else "manual terminal acceptance missing"
        )
    evidence_errors = validate_evidence(
        evidence,
        receipt,
        receipt_raw,
        expected_control_revision=expected_control_revision,
    )
    if evidence_errors:
        raise ValueError(evidence_errors[0])
    checkpoint = {
        "schema": CHECKPOINT_SCHEMA,
        "task_id": TASK_ID,
        "operation_id": OPERATION_ID,
        "kind": KIND,
        "status": "MANUAL_COST_STOP_CANDIDATE_AWAITING_AUTHORITY",
        "control_revision": expected_control_revision,
        "evidence_revision": evidence_revision,
        "evidence_file_sha256": sha256(evidence_raw),
        "evidence_semantic_sha256": semantic_sha256(evidence),
        "receipt_file_sha256": sha256(receipt_raw),
        "receipt_semantic_sha256": semantic_sha256(receipt),
        "terminal_acceptance_sha256": acceptance,
        "no_replay_registry_sha256": receipt["no_replay"][
            "registry_sha256"
        ],
        "automatic_retry_allowed": False,
        "action_authorization_granted": False,
        "readiness_credit_added": False,
        "item26_status": "unverified",
    }
    errors = validate_checkpoint(
        checkpoint,
        evidence,
        evidence_raw,
        receipt,
        receipt_raw,
        expected_control_revision=expected_control_revision,
        expected_evidence_revision=evidence_revision,
    )
    if errors:
        raise ValueError(errors[0])
    return checkpoint


__all__ = [
    "BUILDER_REF",
    "build_checkpoint",
    "build_evidence",
    "build_receipt",
]
