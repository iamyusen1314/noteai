#!/usr/bin/env python3
"""Build canonical Item 26 receipt/evidence from a fixed provider closure.

The builder is pure: it neither contacts Alibaba Cloud nor reads a database.
Callers must provide the exact root-only source/restored manifests and a
Secret-free provider receipt projection.  The detached authority verifier is
responsible for binding that projection to external provider,
user-confirmation and CI exports.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from validate_item26_pitr_restore_result_v1 import (  # noqa: E402
    validate_terminal_result,
)
from verify_pitr_restore_evidence import (  # noqa: E402
    DEFAULT_READINESS,
    EVIDENCE_SCHEMA,
    RECEIPT_SCHEMA,
    TASK_ID,
    terminal_acceptance_sha256,
    validate_receipt,
)


BUILDER_REF = "tools/build_item26_pitr_restore_evidence_v1.py"


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


def build_receipt(
    candidate: Any,
    *,
    source_manifest: Any,
    restored_manifest: Any,
    expected_predecessor_cost_stop: dict[str, Any],
) -> dict[str, Any]:
    if type(candidate) is not dict:
        raise ValueError("Item26 receipt candidate must be an object")
    receipt = copy.deepcopy(candidate)
    if receipt.get("schema") != RECEIPT_SCHEMA or receipt.get("task_id") != TASK_ID:
        raise ValueError("Item26 receipt identity mismatch")
    if receipt.get("terminal_acceptance_sha256") not in {None, ""}:
        raise ValueError("Item26 terminal acceptance must be builder-owned")
    receipt["terminal_acceptance_sha256"] = terminal_acceptance_sha256(receipt)
    result_errors = validate_terminal_result(
        source_manifest=source_manifest,
        restored_manifest=restored_manifest,
        source_capture=receipt.get("source_capture"),
        restored_capture=receipt.get("restored_capture"),
        reconciliation=receipt.get("reconciliation"),
        expected_execution_revision=receipt.get("source_revision"),
    )
    receipt_errors, acceptance = validate_receipt(
        receipt,
        expected_execution_revision=receipt.get("source_revision"),
        expected_predecessor_cost_stop=expected_predecessor_cost_stop,
    )
    errors = [*result_errors, *receipt_errors]
    if errors or acceptance != receipt["terminal_acceptance_sha256"]:
        raise ValueError(errors[0] if errors else "Item26 acceptance mismatch")
    return receipt


def build_evidence(
    receipt: Any,
    *,
    source_manifest: Any,
    restored_manifest: Any,
    expected_predecessor_cost_stop: dict[str, Any],
) -> dict[str, Any]:
    if type(receipt) is not dict:
        raise ValueError("Item26 terminal receipt required")
    receipt_raw = canonical_bytes(receipt)
    errors, acceptance = validate_receipt(
        receipt,
        expected_execution_revision=receipt.get("source_revision"),
        expected_predecessor_cost_stop=expected_predecessor_cost_stop,
    )
    result_errors = validate_terminal_result(
        source_manifest=source_manifest,
        restored_manifest=restored_manifest,
        source_capture=receipt.get("source_capture"),
        restored_capture=receipt.get("restored_capture"),
        reconciliation=receipt.get("reconciliation"),
        expected_execution_revision=receipt.get("source_revision"),
    )
    errors = [*result_errors, *errors]
    if errors or acceptance is None:
        raise ValueError(errors[0] if errors else "Item26 acceptance missing")
    return {
        "schema_version": 1,
        "schema": EVIDENCE_SCHEMA,
        "task_id": TASK_ID,
        "status": "PASS",
        "source_revision": receipt["source_revision"],
        "provider_receipt": {
            "file_sha256": sha256(receipt_raw),
            "semantic_sha256": sha256(receipt_raw[:-1]),
            "terminal_acceptance_sha256": acceptance,
        },
        "external_authority": {
            "required": True,
            "provider_authority": "DETACHED_ROOT_OWNED",
            "confirmation_authority": "DETACHED_ROOT_OWNED",
            "ci_authority": "DETACHED_ROOT_OWNED",
            "mathematically_distinct_key_count": 3,
        },
        "restore_provenance": copy.deepcopy(receipt["provider_identity"]),
        "source_state": copy.deepcopy(receipt["source_capture"]),
        "restored_state": copy.deepcopy(receipt["restored_capture"]),
        "reconciliation": copy.deepcopy(receipt["reconciliation"]),
        "cleanup": copy.deepcopy(receipt["cleanup"]),
        "final_runtime_state": {
            "source_rds_status": "Running",
            "successor_clone_absent": True,
            "builder_status": "Stopped_StopCharging",
            "active_task_container_count": 0,
            "active_task_process_count": 0,
            "established_5432_count": 0,
        },
        "cost_and_data_boundary": {
            **copy.deepcopy(receipt["cost_boundary"]),
            "database_write_count": 0,
            "object_write_count": 0,
            "public_request_count": 0,
            "workload_provider_call_count": 0,
        },
        "no_replay": copy.deepcopy(receipt["no_replay"]),
        "secret_free_evidence": {
            "secret_value_count": 0,
            "password_value_count": 0,
            "private_key_value_count": 0,
            "connection_string_value_count": 0,
            "database_row_value_count": 0,
            "object_key_value_count": 0,
            "raw_provider_payload_count": 0,
        },
        "readiness": copy.deepcopy(DEFAULT_READINESS),
    }


__all__ = [
    "BUILDER_REF",
    "build_evidence",
    "build_receipt",
    "canonical_bytes",
]
