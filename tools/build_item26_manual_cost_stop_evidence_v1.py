#!/usr/bin/env python3
"""Pure builder for Item 26 manual post-action cost-stop artifacts."""

from __future__ import annotations

import copy
from typing import Any

from verify_item26_manual_cost_stop_evidence_v1 import (
    CHECKPOINT_SCHEMA,
    EVIDENCE_SCHEMA,
    EXPECTED_AUTHORITY_ROOT_FILE_SHA256,
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
    candidate: Any,
    *,
    expected_control_revision: str,
) -> dict[str, Any]:
    if type(candidate) is not dict:
        raise ValueError("manual cost-stop receipt candidate must be an object")
    receipt = copy.deepcopy(candidate)
    if (
        receipt.get("schema") != RECEIPT_SCHEMA
        or receipt.get("task_id") != TASK_ID
        or receipt.get("operation_id") != OPERATION_ID
        or receipt.get("kind") != KIND
        or receipt.get("status") != TERMINAL_STATUS
    ):
        raise ValueError("manual cost-stop receipt identity mismatch")
    if receipt.get("terminal_acceptance_sha256") not in {None, ""}:
        raise ValueError("manual terminal acceptance must be builder-owned")
    receipt["terminal_acceptance_sha256"] = terminal_acceptance_sha256(
        receipt
    )
    errors, acceptance = validate_receipt(
        receipt,
        expected_control_revision=expected_control_revision,
    )
    if errors or acceptance != receipt["terminal_acceptance_sha256"]:
        raise ValueError(errors[0] if errors else "manual acceptance mismatch")
    return receipt


def build_evidence(
    receipt: Any,
    *,
    expected_control_revision: str,
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
        "status": "PASS_NO_READINESS_CREDIT",
        "control_revision": expected_control_revision,
        "provider_receipt": {
            "file_sha256": sha256(receipt_raw),
            "semantic_sha256": semantic_sha256(receipt),
            "terminal_acceptance_sha256": acceptance,
            "raw_closure_sha256": raw_closure_sha256(receipt),
        },
        "external_authority": {
            "required": True,
            "provider_authority": "DETACHED_ROOT_OWNED",
            "confirmation_authority": "DETACHED_ROOT_OWNED",
            "ci_authority": "DETACHED_ROOT_OWNED",
            "mathematically_distinct_key_count": 3,
            "root_frozen_before_action": False,
            "authorizes_new_action": False,
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
    checkpoint = {
        "schema": CHECKPOINT_SCHEMA,
        "task_id": TASK_ID,
        "operation_id": OPERATION_ID,
        "kind": KIND,
        "status": "MANUAL_COST_STOP_EVIDENCE_CHECKPOINT_ACCEPTED",
        "control_revision": expected_control_revision,
        "evidence_revision": evidence_revision,
        "evidence_file_sha256": sha256(evidence_raw),
        "evidence_semantic_sha256": semantic_sha256(evidence),
        "receipt_file_sha256": sha256(receipt_raw),
        "receipt_semantic_sha256": semantic_sha256(receipt),
        "terminal_acceptance_sha256": receipt[
            "terminal_acceptance_sha256"
        ],
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
