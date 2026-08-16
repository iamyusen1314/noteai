#!/usr/bin/env python3
"""Pure builder for Item 26 cost-containment abort artifacts.

The builder neither calls Alibaba Cloud nor accepts complete production
identifiers.  It consumes a Secret-free projection already derived from the
root-owned provider closure and validates it before emitting canonical
receipt/evidence/checkpoint objects.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from verify_item26_cost_containment_abort_evidence_v1 import (
    CHECKPOINT_SCHEMA,
    EVIDENCE_SCHEMA,
    OPERATION_ID,
    RECEIPT_SCHEMA,
    TASK_ID,
    TERMINAL_STATUS,
    raw_closure_sha256,
    terminal_acceptance_sha256,
    validate_checkpoint,
    validate_evidence,
    validate_receipt,
)
from validate_item26_cost_containment_abort_result_v1 import READINESS_25_TO_25


BUILDER_REF = "tools/build_item26_cost_containment_abort_evidence_v1.py"


def canonical_bytes(value: Any) -> bytes:
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


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def semantic_sha256(value: Any) -> str:
    return sha256(canonical_bytes(value)[:-1])


def build_receipt(
    candidate: Any,
    *,
    root,
) -> dict[str, Any]:
    if type(candidate) is not dict:
        raise ValueError("abort receipt candidate must be an object")
    receipt = copy.deepcopy(candidate)
    if (
        receipt.get("schema") != RECEIPT_SCHEMA
        or receipt.get("task_id") != TASK_ID
        or receipt.get("operation_id") != OPERATION_ID
        or receipt.get("status") != TERMINAL_STATUS
    ):
        raise ValueError("abort receipt identity mismatch")
    if receipt.get("terminal_acceptance_sha256") not in {None, ""}:
        raise ValueError("abort terminal acceptance must be builder-owned")
    receipt["terminal_acceptance_sha256"] = terminal_acceptance_sha256(receipt)
    errors, acceptance = validate_receipt(
        receipt,
        expected_execution_revision=receipt.get("source_revision"),
        root=root,
    )
    if errors or acceptance != receipt["terminal_acceptance_sha256"]:
        raise ValueError(errors[0] if errors else "abort acceptance mismatch")
    return receipt


def build_evidence(
    receipt: Any,
    *,
    authority_binding: dict[str, Any],
    root,
) -> dict[str, Any]:
    if type(receipt) is not dict or type(authority_binding) is not dict:
        raise ValueError("abort terminal receipt and authority required")
    receipt_raw = canonical_bytes(receipt)
    errors, acceptance = validate_receipt(
        receipt,
        expected_execution_revision=receipt.get("source_revision"),
        root=root,
    )
    if errors or acceptance is None:
        raise ValueError(errors[0] if errors else "abort acceptance missing")
    evidence = {
        "schema_version": 1,
        "schema": EVIDENCE_SCHEMA,
        "task_id": TASK_ID,
        "operation_id": OPERATION_ID,
        "status": "PASS_NO_READINESS_CREDIT",
        "source_revision": receipt["source_revision"],
        "provider_receipt": {
            "file_sha256": sha256(receipt_raw),
            "semantic_sha256": semantic_sha256(receipt),
            "terminal_acceptance_sha256": acceptance,
            "raw_closure_sha256": raw_closure_sha256(receipt),
        },
        "external_authority": copy.deepcopy(authority_binding),
        "abort_outcome": {
            "status": TERMINAL_STATUS,
            "old_clone_absent": True,
            "billing_closed": True,
            "temporary_cleanup_terminal": True,
            "item26_verified": False,
            "future_successor_requires_new_fee_authorization": True,
        },
        "final_runtime_state": copy.deepcopy(receipt["final_state"]),
        "cost_and_data_boundary": {
            "currency": receipt["billing_closure"]["currency"],
            "approved_24h_ceiling_cny": receipt["billing_closure"][
                "approved_24h_ceiling_cny"
            ],
            "pre_abort_gross_cny": receipt["billing_closure"][
                "pre_abort_gross_cny"
            ],
            "final_gross_cny": receipt["billing_closure"]["final_gross_cny"],
            "incremental_after_preflight_cny": receipt["billing_closure"][
                "incremental_after_preflight_cny"
            ],
            "historical_charge_retained": True,
            "ongoing_metering_closed": True,
            "database_connection_count": 0,
            "database_transaction_count": 0,
            "database_write_count": 0,
            "object_write_count": 0,
            "new_paid_resource_count": 0,
        },
        "no_replay": copy.deepcopy(receipt["no_replay"]),
        "secret_free_evidence": {
            "secret_value_count": 0,
            "password_value_count": 0,
            "private_key_value_count": 0,
            "connection_string_value_count": 0,
            "database_row_value_count": 0,
            "resource_identifier_value_count": 0,
            "raw_provider_payload_count": 0,
        },
        "readiness": copy.deepcopy(READINESS_25_TO_25),
    }
    evidence_errors = validate_evidence(
        evidence,
        receipt,
        receipt_raw,
        expected_execution_revision=receipt["source_revision"],
        authority_binding=authority_binding,
    )
    if evidence_errors:
        raise ValueError(evidence_errors[0])
    return evidence


def build_checkpoint(
    *,
    receipt: dict[str, Any],
    evidence: dict[str, Any],
    evidence_revision: str,
) -> dict[str, Any]:
    receipt_raw = canonical_bytes(receipt)
    evidence_raw = canonical_bytes(evidence)
    checkpoint = {
        "schema": CHECKPOINT_SCHEMA,
        "task_id": TASK_ID,
        "operation_id": OPERATION_ID,
        "status": "ABORT_EVIDENCE_CHECKPOINT_EXACT_HEAD_CI_ACCEPTED",
        "execution_revision": receipt["source_revision"],
        "evidence_revision": evidence_revision,
        "evidence_file_sha256": sha256(evidence_raw),
        "evidence_semantic_sha256": semantic_sha256(evidence),
        "receipt_file_sha256": sha256(receipt_raw),
        "receipt_semantic_sha256": semantic_sha256(receipt),
        "terminal_acceptance_sha256": receipt[
            "terminal_acceptance_sha256"
        ],
        "automatic_retry_allowed": False,
        "readiness_credit_added": False,
        "item26_status": "unverified",
    }
    errors = validate_checkpoint(
        checkpoint,
        evidence,
        evidence_raw,
        receipt,
        receipt_raw,
        expected_execution_revision=receipt["source_revision"],
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
    "canonical_bytes",
    "semantic_sha256",
    "sha256",
]
