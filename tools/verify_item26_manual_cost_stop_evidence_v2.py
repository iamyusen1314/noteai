#!/usr/bin/env python3
"""Fail-closed verifier for Item 26 manual post-action cost stop.

This generation-v2 evidence domain records a cost stop after two already-
consumed browser mutations.  It is neither abort-v1 terminal authority nor a
PITR success, and it cannot add readiness credit.  It defaults closed until
the complete public root-v2, root-owned raw material, staged artifacts, and
detached terminal authority all exist.
"""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

from extract_item26_manual_cost_stop_raw_v2 import (
    RAW_ACTIONTRAIL_EXTRACTION_IMPLEMENTED,
    RAW_PROVIDER_EXTRACTION_IMPLEMENTED,
    consumed_mutation_identity_set_sha256 as raw_mutation_set_sha256,
)
from verify_item26_manual_cost_stop_authority_v2 import (
    AUTHORITY_EPOCH_ID,
    AUTHORITY_GENERATION_ID,
    EXPECTED_AUTHORITY_ROOT_FILE_SHA256,
    OPERATION_ID,
    git_blob_absent,
    git_blob_bytes,
    revision_is_strict_ancestor,
    validate_authority_bundle,
)


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "PROD-FIRST-LAUNCH-PITR-RESTORE-001"
HISTORICAL_OPERATION_ID = TASK_ID + ":MANUAL-POST-ACTION-COST-STOP:v1"
KIND = "MANUAL_BROWSER_POST_ACTION_COST_STOP_AUTHORITY_V2"
TERMINAL_STATUS = "POST_ACTION_RECONCILED_COST_STOP"
VERIFIER_REF = "tools/verify_item26_manual_cost_stop_evidence_v2.py"
BUILDER_REF = "tools/build_item26_manual_cost_stop_evidence_v2.py"
AUTHORITY_VERIFIER_REF = "tools/verify_item26_manual_cost_stop_authority_v2.py"
RAW_EXTRACTOR_REF = "tools/extract_item26_manual_cost_stop_raw_v2.py"
CONTRACT_REF = "deploy/production/plans/item26-manual-cost-stop-contract-v2.json"
NO_REPLAY_REGISTRY_V1_REF = (
    "deploy/production/plans/item26-no-replay-registry-v1.json"
)
NO_REPLAY_REGISTRY_REF = (
    "deploy/production/plans/item26-no-replay-registry-v2.json"
)
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
RECEIPT_SCHEMA = "noteai.item26.manual-cost-stop-provider-receipt.v2"
EVIDENCE_SCHEMA = "noteai.item26.manual-cost-stop-evidence.v2"
CHECKPOINT_SCHEMA = "noteai.item26.manual-cost-stop-terminal-checkpoint.v2"
MANUAL_RAW_EXTRACTOR_FINALIZED = True
EXPECTED_NO_REPLAY_REGISTRY_FILE_SHA256 = (
    "994c521e22abd9be0c88d4b252ce4d3ef9a47f8131a065ab7964018f224d0f47"
)
EXPECTED_NO_REPLAY_REGISTRY_SHA256 = (
    "93abb46e3e329dd28edab6bab14ec6c1a09177d0effe0e80d881d43f1e878be5"
)
EXPECTED_NO_REPLAY_ENTRY_COUNT = 29
EXPECTED_CONSUMED_MANUAL_MUTATION_SET_SHA256 = (
    "8647c02f5879dcb7a986fc87ce3668ac4e35d63d610c4da1e54a57a8b7263105"
)
EXPECTED_SOURCE_PRE_TUPLE_SHA256 = (
    "7b19a9ce8091ef52b11cd722d3d3a52671ba7888811ad47adbbae80abe5d5771"
)
EXPECTED_RECORDED_BILLING_RESPONSE_SHA256 = (
    "ed2fda069a1902bda37abfb7e551929cc40f3c139cb4117179b1176b0127631a"
)
LEDGER_CONTEXT_REVISION = "41c489cf5ebfedfa2959bcee1f09183a9491f7f6"
EXPECTED_IDENTITY_COMMITMENTS = {
    "old_clone_sha256": (
        "820121638125fcebe3b7c03f3416ddae1fef1a0a9f1de731320fa75dd69a1525"
    ),
    "old_clone_name_sha256": (
        "cdffd0d0a0dd6d6a57f19d8479125671d4484fabe502d5cf4073b016767e4ef1"
    ),
    "source_rds_sha256": (
        "d3712c09b28ee82257ab128fa1b5ba79b223f8b774e5fa20f761a2c4782eee8d"
    ),
    "source_name_sha256": (
        "3911925626a615785629237e9dd27bb98e8b902f6eebaae6b185df6c0b84ebd7"
    ),
}
EXPECTED_PROTECTION_COMMITMENTS = {
    "request_id_sha256": (
        "c44eb336fc53b7850778bf61049f4df43ca562642084d3b3e6498be72d3cdc75"
    ),
    "response_sha256": (
        "d819defe8b66a6884248cb857b355dc1c9efbc82cc32894c6f42e4c7bdac5c44"
    ),
    "client_token_sha256": (
        "4a3216763ad561a7d6ddef25e4a387188fe91964fa9bb2ab86bf464050f25ec5"
    ),
    "same_identity_readback_sha256": (
        "9735c5562a53b8fb674b75862280541f7053894bd47f21582894155cb0ee5694"
    ),
}
EXPECTED_DELETE_COMMITMENTS = {
    "request_id_sha256": (
        "4ea974bc7aeba8cc49af916a68939d10e54107928fb0dfebcf0deca644c088ed"
    ),
    "response_sha256": (
        "f68679aef8173c37c0de1615f35a858c818bd8bc2e1e25cf58e0bd7b738d5eab"
    ),
    "exact_identity_absence_readback_sha256": (
        "abe028f275d4b7da1bb7181f7c95d6b834653c47091b4b528052867c3f551e4e"
    ),
}
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$"
)
DECIMAL_CNY = re.compile(r"^(?:0|[1-9]\d*)(?:\.\d{1,6})?$")
ACCEPTANCE_DOMAIN = b"noteai-item26-manual-cost-stop-terminal-v2\0"
RAW_CLOSURE_DOMAIN = b"noteai-item26-manual-cost-stop-raw-closure-v2\0"
MUTATION_IDENTITY_DOMAIN = (
    b"noteai-item26-manual-cost-stop-consumed-mutations-v1\0"
)
MUTATION_IDENTITY_TOKEN_BOUND_DOMAIN = (
    b"noteai-item26-manual-cost-stop-consumed-mutations-token-bound-v1\0"
)

READINESS_25_TO_25 = {
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
}
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


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


def _stable_file_identity(row: os.stat_result) -> tuple[int, ...]:
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


def _read_repo_artifact(path: Path) -> bytes:
    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o644
        or before.st_nlink != 1
    ):
        raise ValueError("manual terminal artifact file identity")
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        opened = os.fstat(descriptor)
        raw = b""
        while len(raw) <= MAX_ARTIFACT_BYTES:
            chunk = os.read(
                descriptor,
                min(65536, MAX_ARTIFACT_BYTES + 1 - len(raw)),
            )
            if not chunk:
                break
            raw += chunk
        closed = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after = path.lstat()
    if (
        not 1 <= len(raw) <= MAX_ARTIFACT_BYTES
        or _stable_file_identity(before) != _stable_file_identity(opened)
        or _stable_file_identity(opened) != _stable_file_identity(closed)
        or _stable_file_identity(closed) != _stable_file_identity(after)
    ):
        raise ValueError("manual terminal artifact file changed")
    return raw


def _parse_artifact(raw: bytes, label: str) -> dict[str, Any]:
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


def terminal_acceptance_sha256(receipt: dict[str, Any]) -> str:
    projection = dict(receipt)
    projection.pop("terminal_acceptance_sha256", None)
    return sha256(ACCEPTANCE_DOMAIN + canonical_bytes(projection))


def raw_closure_sha256(receipt: dict[str, Any]) -> str:
    return sha256(
        RAW_CLOSURE_DOMAIN + canonical_bytes(receipt["raw_closure"])
    )


def consumed_mutation_identity_set_sha256(receipt: dict[str, Any]) -> str:
    mutations = receipt.get("mutation_outcomes", {})
    protection = mutations.get("protection_disable", {})
    deletion = mutations.get("delete", {})
    return raw_mutation_set_sha256(
        protection_request_id_sha256=protection.get("request_id_sha256"),
        protection_request_body_sha256=protection.get(
            "request_body_sha256"
        ),
        protection_client_token_sha256=protection.get(
            "client_token_sha256"
        ),
        delete_request_id_sha256=deletion.get("request_id_sha256"),
        delete_request_body_sha256=deletion.get("request_body_sha256"),
        delete_client_token_present=deletion.get("client_token_present"),
    )


def validate_receipt(
    value: Any,
    *,
    expected_control_revision: str,
) -> tuple[list[str], str | None]:
    errors: list[str] = []
    keys = {
        "schema_version",
        "schema",
        "task_id",
        "operation_id",
        "authority_generation_id",
        "authority_epoch_id",
        "kind",
        "status",
        "observed_at_utc",
        "ledger_context_revision",
        "control_revision",
        "action_precedes_control_checkpoint",
        "abort_v1_terminal_authority",
        "action_authorization_granted",
        "item26_verified",
        "identity_ledger",
        "mutation_outcomes",
        "source_reconciliation",
        "billing_snapshot",
        "residual_resources",
        "raw_closure",
        "no_replay",
        "execution_boundary",
        "readiness",
        "terminal_acceptance_sha256",
    }
    if type(value) is not dict or set(value) != keys:
        return ["manual cost-stop receipt schema mismatch"], None
    expected_scalars = {
        "schema_version": 2,
        "schema": RECEIPT_SCHEMA,
        "task_id": TASK_ID,
        "operation_id": OPERATION_ID,
        "authority_generation_id": AUTHORITY_GENERATION_ID,
        "authority_epoch_id": AUTHORITY_EPOCH_ID,
        "kind": KIND,
        "status": TERMINAL_STATUS,
        "control_revision": expected_control_revision,
        "action_precedes_control_checkpoint": True,
        "abort_v1_terminal_authority": False,
        "action_authorization_granted": False,
        "item26_verified": False,
    }
    for key, expected in expected_scalars.items():
        if type(value.get(key)) is not type(expected) or value.get(key) != expected:
            errors.append("manual receipt " + key + " mismatch")
    if (
        RFC3339.fullmatch(value.get("observed_at_utc") or "") is None
        or value.get("ledger_context_revision") != LEDGER_CONTEXT_REVISION
        or HEX40.fullmatch(expected_control_revision or "") is None
        or value.get("ledger_context_revision") == expected_control_revision
    ):
        errors.append("manual receipt revision/timestamp mismatch")

    identity = value.get("identity_ledger")
    identity_safe = identity if type(identity) is dict else {}
    identity_keys = {
        "old_clone_sha256",
        "old_clone_name_sha256",
        "source_rds_sha256",
        "source_name_sha256",
        "old_clone_create_request_sha256",
        "old_clone_create_body_sha256",
        "old_clone_client_token_sha256",
    }
    if (
        type(identity) is not dict
        or set(identity) != identity_keys
        or any(not _hex64(identity.get(key)) for key in identity_keys)
        or identity["old_clone_sha256"] == identity["source_rds_sha256"]
        or identity["old_clone_name_sha256"] == identity["source_name_sha256"]
        or any(
            identity.get(key) != expected
            for key, expected in EXPECTED_IDENTITY_COMMITMENTS.items()
        )
    ):
        errors.append("manual receipt identity ledger mismatch")

    mutations = value.get("mutation_outcomes")
    mutation_keys = {
        "protection_disable",
        "delete",
        "ordered_mutation_set_sha256",
    }
    if type(mutations) is not dict or set(mutations) != mutation_keys:
        errors.append("manual receipt mutation schema mismatch")
    else:
        protection = mutations.get("protection_disable")
        deletion = mutations.get("delete")
        common = {
            "operation",
            "target_sha256",
            "request_id_sha256",
            "request_body_sha256",
            "response_sha256",
            "submit_count",
            "automatic_retry_count",
            "manual_resend_count",
            "replacement_count",
            "outcome",
        }
        if type(protection) is not dict or set(protection) != common | {
            "client_token_sha256",
            "same_identity_readback_sha256",
        }:
            errors.append("manual protection-disable schema mismatch")
        elif (
            protection["operation"] != "ModifyDBInstanceDeletionProtection"
            or protection["outcome"] != "PROTECTION_FALSE_READBACK_CONFIRMED"
            or any(
                not _hex64(protection[key])
                for key in (
                    "target_sha256",
                    "request_id_sha256",
                    "request_body_sha256",
                    "response_sha256",
                    "client_token_sha256",
                    "same_identity_readback_sha256",
                )
            )
            or protection["target_sha256"]
            != identity_safe.get("old_clone_sha256")
            or any(
                protection.get(key) != expected
                for key, expected in EXPECTED_PROTECTION_COMMITMENTS.items()
            )
            or any(
                protection[key] != expected
                for key, expected in {
                    "submit_count": 1,
                    "automatic_retry_count": 0,
                    "manual_resend_count": 0,
                    "replacement_count": 0,
                }.items()
            )
        ):
            errors.append("manual protection-disable outcome mismatch")
        if type(deletion) is not dict or set(deletion) != common | {
            "client_token_present",
            "exact_identity_absence_readback_sha256",
        }:
            errors.append("manual delete schema mismatch")
        elif (
            deletion["operation"] != "DeleteDBInstance"
            or deletion["outcome"] != "DELETE_ACCEPTED_EXACT_ID_ABSENT"
            or deletion["client_token_present"] is not False
            or any(
                not _hex64(deletion[key])
                for key in (
                    "target_sha256",
                    "request_id_sha256",
                    "request_body_sha256",
                    "response_sha256",
                    "exact_identity_absence_readback_sha256",
                )
            )
            or deletion["target_sha256"]
            != identity_safe.get("old_clone_sha256")
            or any(
                deletion.get(key) != expected
                for key, expected in EXPECTED_DELETE_COMMITMENTS.items()
            )
            or any(
                deletion[key] != expected
                for key, expected in {
                    "submit_count": 1,
                    "automatic_retry_count": 0,
                    "manual_resend_count": 0,
                    "replacement_count": 0,
                }.items()
            )
        ):
            errors.append("manual delete outcome mismatch")
        if type(protection) is not dict or type(deletion) is not dict:
            errors.append("manual mutation-set digest mismatch")
        else:
            computed_mutation_set_sha256 = (
                consumed_mutation_identity_set_sha256(value)
            )
            if (
                not _hex64(mutations.get("ordered_mutation_set_sha256"))
                or mutations["ordered_mutation_set_sha256"]
                != computed_mutation_set_sha256
                or computed_mutation_set_sha256
                != EXPECTED_CONSUMED_MANUAL_MUTATION_SET_SHA256
            ):
                errors.append("manual mutation-set digest mismatch")

    source = value.get("source_reconciliation")
    if (
        type(source) is not dict
        or set(source) != {
            "pre_tuple_sha256",
            "post_tuple_sha256",
            "source_unchanged",
            "source_status",
            "source_pay_type",
            "source_deleted",
        }
        or not _hex64(source.get("pre_tuple_sha256"))
        or source.get("pre_tuple_sha256")
        != EXPECTED_SOURCE_PRE_TUPLE_SHA256
        or source.get("pre_tuple_sha256") != source.get("post_tuple_sha256")
        or source.get("source_unchanged") is not True
        or source.get("source_status") != "Running"
        or source.get("source_pay_type") != "Prepaid"
        or source.get("source_deleted") is not False
    ):
        errors.append("manual source reconciliation mismatch")

    billing = value.get("billing_snapshot")
    if (
        type(billing) is not dict
        or set(billing) != {
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
        }
        or billing.get("currency") != "CNY"
        or type(billing.get("pretax_gross_cny")) is not str
        or DECIMAL_CNY.fullmatch(billing["pretax_gross_cny"]) is None
        or (
            "." in billing["pretax_gross_cny"]
            and billing["pretax_gross_cny"].endswith("0")
        )
        or type(billing.get("service_seconds")) is not int
        or billing["service_seconds"] < 345600
        or not _hex64(billing.get("response_sha256"))
        or billing.get("recorded_baseline_pretax_gross_cny")
        != "198.462"
        or billing.get("recorded_baseline_service_seconds") != 345600
        or not _hex64(
            billing.get("recorded_baseline_response_sha256")
        )
        or billing.get("recorded_baseline_response_sha256")
        != EXPECTED_RECORDED_BILLING_RESPONSE_SHA256
        or billing.get("historical_snapshot_only") is not True
        or billing.get("native_non_accruing_marker_proven") is not False
        or billing.get("settlement_terminal_proven") is not False
    ):
        errors.append("manual historical billing snapshot mismatch")
    else:
        try:
            gross = Decimal(billing["pretax_gross_cny"])
        except InvalidOperation:
            errors.append("manual historical billing snapshot mismatch")
        else:
            if not gross.is_finite() or gross < Decimal("198.462"):
                errors.append("manual historical billing snapshot mismatch")

    residual = value.get("residual_resources")
    if not _strict(
        residual,
        {
            "non_clone_resource_disposition": (
                "UNPROVEN_RETAINED_FRESH_PREFLIGHT_REQUIRED"
            ),
            "temporary_account_cleanup_terminal": False,
            "iam_cleanup_terminal": False,
            "vswitch_cleanup_terminal": False,
            "shared_builder_retained": True,
            "shared_disk_retained": True,
        },
    ):
        errors.append("manual residual resource boundary mismatch")

    raw = value.get("raw_closure")
    raw_keys = {
        "authority_epoch_id",
        "authority_root_file_sha256",
        "authority_root_git_blob_sha256",
        "activation_receipt_schema",
        "activation_receipt_sha256",
        "provider_raw_file_sha256",
        "actiontrail_raw_file_sha256",
        "provider_projection_sha256",
        "actiontrail_projection_sha256",
        "complete_pagination_proven",
        "secret_free_projection",
        "historical_response_commitments_are_ledger_context",
        "historical_response_bytes_rederived_from_fresh_raw",
    }
    if (
        type(raw) is not dict
        or set(raw) != raw_keys
        or any(not _hex64(raw.get(key)) for key in raw_keys if key.endswith("_sha256"))
        or raw.get("authority_epoch_id") != AUTHORITY_EPOCH_ID
        or raw.get("activation_receipt_schema")
        != "noteai.item26.manual-cost-stop-runtime-activation-receipt.v3"
        or raw.get("complete_pagination_proven") is not True
        or raw.get("secret_free_projection") is not True
        or raw.get(
            "historical_response_commitments_are_ledger_context"
        ) is not True
        or raw.get(
            "historical_response_bytes_rederived_from_fresh_raw"
        ) is not False
    ):
        errors.append("manual raw closure mismatch")

    no_replay = value.get("no_replay")
    if (
        type(no_replay) is not dict
        or set(no_replay) != {
            "registry_schema",
            "registry_sha256",
            "entry_count",
            "automatic_retry_allowed",
            "manual_resend_allowed",
            "replacement_allowed",
            "historical_script_execution_count",
        }
        or no_replay.get("registry_schema")
        != "noteai.item26.no-replay-registry.v2"
        or not _hex64(no_replay.get("registry_sha256"))
        or no_replay.get("registry_sha256")
        != EXPECTED_NO_REPLAY_REGISTRY_SHA256
        or no_replay.get("entry_count") != EXPECTED_NO_REPLAY_ENTRY_COUNT
        or no_replay.get("automatic_retry_allowed") is not False
        or no_replay.get("manual_resend_allowed") is not False
        or no_replay.get("replacement_allowed") is not False
        or no_replay.get("historical_script_execution_count") != 0
    ):
        errors.append("manual no-replay boundary mismatch")

    boundary = value.get("execution_boundary")
    if not _strict(
        boundary,
        {
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
    ):
        errors.append("manual execution boundary mismatch")
    if not _strict(value.get("readiness"), READINESS_25_TO_25):
        errors.append("manual readiness boundary mismatch")
    acceptance = terminal_acceptance_sha256(value)
    if (
        not _hex64(value.get("terminal_acceptance_sha256"))
        or value["terminal_acceptance_sha256"] != acceptance
    ):
        errors.append("manual terminal acceptance mismatch")
        return errors, None
    return errors, acceptance


def validate_evidence(
    value: Any,
    receipt: dict[str, Any],
    receipt_raw: bytes,
    *,
    expected_control_revision: str,
) -> list[str]:
    acceptance = receipt.get("terminal_acceptance_sha256")
    expected = {
        "schema_version": 2,
        "schema": EVIDENCE_SCHEMA,
        "task_id": TASK_ID,
        "operation_id": OPERATION_ID,
        "authority_generation_id": AUTHORITY_GENERATION_ID,
        "authority_epoch_id": AUTHORITY_EPOCH_ID,
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
            "authority_generation_id": AUTHORITY_GENERATION_ID,
            "authority_epoch_id": AUTHORITY_EPOCH_ID,
            "legacy_v1_authority_allowed": False,
            "legacy_receipt_v2_allowed": False,
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
        "no_replay": receipt["no_replay"],
        "secret_free_evidence": {
            "complete_resource_identifier_value_count": 0,
            "raw_provider_payload_count": 0,
            "credential_value_count": 0,
            "private_key_value_count": 0,
            "database_row_value_count": 0,
        },
        "readiness": READINESS_25_TO_25,
    }
    return [] if _strict(value, expected) else [
        "manual cost-stop evidence mismatch"
    ]


def validate_checkpoint(
    value: Any,
    evidence: dict[str, Any],
    evidence_raw: bytes,
    receipt: dict[str, Any],
    receipt_raw: bytes,
    *,
    expected_control_revision: str,
    expected_evidence_revision: str,
) -> list[str]:
    expected = {
        "schema": CHECKPOINT_SCHEMA,
        "task_id": TASK_ID,
        "operation_id": OPERATION_ID,
        "authority_generation_id": AUTHORITY_GENERATION_ID,
        "authority_epoch_id": AUTHORITY_EPOCH_ID,
        "kind": KIND,
        "status": "MANUAL_COST_STOP_CANDIDATE_AWAITING_AUTHORITY",
        "control_revision": expected_control_revision,
        "evidence_revision": expected_evidence_revision,
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
    if HEX40.fullmatch(expected_evidence_revision or "") is None:
        return ["manual evidence revision mismatch"]
    return [] if _strict(value, expected) else [
        "manual cost-stop checkpoint mismatch"
    ]


def validate_terminal_artifacts(
    *,
    root: Path = ROOT,
) -> tuple[list[str], dict[str, Any] | None]:
    if (
        not MANUAL_RAW_EXTRACTOR_FINALIZED
        or not RAW_PROVIDER_EXTRACTION_IMPLEMENTED
        or not RAW_ACTIONTRAIL_EXTRACTION_IMPLEMENTED
        or not _hex64(EXPECTED_AUTHORITY_ROOT_FILE_SHA256)
    ):
        return ["manual cost-stop external authority is not finalized"], None
    try:
        receipt_raw = _read_repo_artifact(root / RECEIPT_REF)
        evidence_raw = _read_repo_artifact(root / EVIDENCE_REF)
        checkpoint_raw = _read_repo_artifact(root / CHECKPOINT_REF)
        receipt = _parse_artifact(receipt_raw, "manual receipt")
        evidence = _parse_artifact(evidence_raw, "manual evidence")
        checkpoint = _parse_artifact(
            checkpoint_raw, "manual checkpoint"
        )
    except FileNotFoundError:
        return ["manual cost-stop terminal artifacts are not installed"], None
    except (OSError, ValueError) as exc:
        return ["manual cost-stop terminal artifacts rejected: " + str(exc)], None
    control_revision = receipt.get("control_revision")
    evidence_revision = checkpoint.get("evidence_revision")
    receipt_errors, acceptance = validate_receipt(
        receipt,
        expected_control_revision=control_revision,
    )
    if receipt_errors or acceptance is None:
        return receipt_errors or ["manual cost-stop acceptance missing"], None
    evidence_errors = validate_evidence(
        evidence,
        receipt,
        receipt_raw,
        expected_control_revision=control_revision,
    )
    if evidence_errors:
        return evidence_errors, None
    checkpoint_errors = validate_checkpoint(
        checkpoint,
        evidence,
        evidence_raw,
        receipt,
        receipt_raw,
        expected_control_revision=control_revision,
        expected_evidence_revision=evidence_revision,
    )
    if checkpoint_errors:
        return checkpoint_errors, None
    receipt_binding = {
        "receipt_file_sha256": sha256(receipt_raw),
        "receipt_semantic_sha256": semantic_sha256(receipt),
        "terminal_acceptance_sha256": acceptance,
        "raw_closure_sha256": raw_closure_sha256(receipt),
    }
    authority_errors, authority = validate_authority_bundle(
        expected_authority_root_file_sha256=(
            EXPECTED_AUTHORITY_ROOT_FILE_SHA256
        ),
        expected_receipt_binding=receipt_binding,
        root=root,
    )
    if authority_errors or authority is None:
        return authority_errors or ["manual cost-stop authority missing"], None
    identity = receipt["identity_ledger"]
    mutations = receipt["mutation_outcomes"]
    protection = mutations["protection_disable"]
    deletion = mutations["delete"]
    source = receipt["source_reconciliation"]
    billing = receipt["billing_snapshot"]
    raw = receipt["raw_closure"]
    no_replay = receipt["no_replay"]
    if not (
        receipt["authority_generation_id"]
        == authority.get("authority_generation_id")
        and receipt["authority_epoch_id"]
        == authority.get("authority_epoch_id")
        and raw["authority_root_file_sha256"]
        == authority.get("authority_root_file_sha256")
        and raw["authority_root_git_blob_sha256"]
        == authority.get("authority_root_git_blob_sha256")
        and receipt["observed_at_utc"]
        == authority.get("post_action_observed_at_utc")
        and identity["old_clone_sha256"]
        == authority.get("old_clone_sha256")
        and identity["old_clone_name_sha256"]
        == authority.get("old_clone_name_sha256")
        and identity["old_clone_create_request_sha256"]
        == authority.get("old_clone_create_request_sha256")
        and identity["old_clone_create_body_sha256"]
        == authority.get("old_clone_create_body_sha256")
        and identity["old_clone_client_token_sha256"]
        == authority.get("old_clone_client_token_sha256")
        and protection["request_id_sha256"]
        == authority.get("protection_disable_request_id_sha256")
        and protection["request_body_sha256"]
        == authority.get("protection_disable_request_body_sha256")
        and protection["client_token_sha256"]
        == authority.get("protection_disable_client_token_sha256")
        and deletion["request_id_sha256"]
        == authority.get("delete_request_id_sha256")
        and deletion["request_body_sha256"]
        == authority.get("delete_request_body_sha256")
        and deletion["client_token_present"]
        is authority.get("delete_client_token_present")
        and mutations["ordered_mutation_set_sha256"]
        == authority.get("consumed_mutation_identity_set_sha256")
        and source["pre_tuple_sha256"]
        == authority.get("source_pre_tuple_sha256")
        and source["post_tuple_sha256"]
        == authority.get("source_post_tuple_sha256")
        and semantic_sha256(billing)
        == authority.get("billing_snapshot_sha256")
        and raw["provider_raw_file_sha256"]
        == authority.get("provider_raw_file_sha256")
        and raw["actiontrail_raw_file_sha256"]
        == authority.get("actiontrail_raw_file_sha256")
        and raw["provider_projection_sha256"]
        == authority.get("provider_projection_sha256")
        and raw["actiontrail_projection_sha256"]
        == authority.get("actiontrail_projection_sha256")
        and raw["activation_receipt_sha256"]
        == authority.get("activation_receipt_sha256")
        and no_replay["registry_sha256"]
        == authority.get("no_replay_registry_sha256")
    ):
        return ["manual cost-stop receipt/raw authority mismatch"], None
    terminal_revision = authority.get("terminal_revision")
    if (
        authority.get("control_revision") != control_revision
        or authority.get("evidence_revision") != evidence_revision
        or not all(
            type(value) is str and HEX40.fullmatch(value) is not None
            for value in (
                control_revision,
                evidence_revision,
                terminal_revision,
            )
        )
        or not revision_is_strict_ancestor(
            control_revision, evidence_revision, root=root
        )
        or not revision_is_strict_ancestor(
            evidence_revision, terminal_revision, root=root
        )
        or authority.get("receipt_file_sha256") != sha256(receipt_raw)
        or authority.get("evidence_file_sha256") != sha256(evidence_raw)
        or authority.get("checkpoint_file_sha256")
        != sha256(checkpoint_raw)
        or authority.get("terminal_acceptance_sha256") != acceptance
    ):
        return ["manual cost-stop terminal authority mismatch"], None
    artifact_rows = (
        (RECEIPT_REF, receipt_raw),
        (EVIDENCE_REF, evidence_raw),
        (CHECKPOINT_REF, checkpoint_raw),
    )
    try:
        if any(
            not git_blob_absent(control_revision, ref, root=root)
            for ref, _raw in artifact_rows
        ):
            return [
                "manual cost-stop control revision contains artifact"
            ], None
        for ref, raw in artifact_rows[:2]:
            if git_blob_bytes(evidence_revision, ref, root=root) != raw:
                return [
                    "manual cost-stop evidence revision artifact mismatch"
                ], None
        if not git_blob_absent(
            evidence_revision, CHECKPOINT_REF, root=root
        ):
            return [
                "manual cost-stop checkpoint appeared before terminal"
            ], None
        for ref, raw in artifact_rows:
            if git_blob_bytes(terminal_revision, ref, root=root) != raw:
                return [
                    "manual cost-stop terminal revision artifact mismatch"
                ], None
    except (OSError, ValueError) as exc:
        return ["manual cost-stop Git evidence rejected: " + str(exc)], None
    return [], {
        "status": TERMINAL_STATUS,
        "kind": KIND,
        "authority_generation_id": AUTHORITY_GENERATION_ID,
        "authority_epoch_id": AUTHORITY_EPOCH_ID,
        "activation_receipt_schema": receipt["raw_closure"][
            "activation_receipt_schema"
        ],
        "activation_receipt_sha256": authority[
            "activation_receipt_sha256"
        ],
        "terminal_acceptance_sha256": acceptance,
        "old_clone_sha256": authority["old_clone_sha256"],
        "old_clone_name_sha256": authority["old_clone_name_sha256"],
        "source_pre_tuple_sha256": authority[
            "source_pre_tuple_sha256"
        ],
        "source_post_tuple_sha256": authority[
            "source_post_tuple_sha256"
        ],
        "billing_snapshot_sha256": authority["billing_snapshot_sha256"],
        "no_replay_registry_sha256": authority[
            "no_replay_registry_sha256"
        ],
        "authority_root_file_sha256": authority[
            "authority_root_file_sha256"
        ],
        "authority_root_git_blob_sha256": authority[
            "authority_root_git_blob_sha256"
        ],
        "authority_bundle_file_sha256": authority[
            "authority_bundle_file_sha256"
        ],
        "provider_raw_file_sha256": authority[
            "provider_raw_file_sha256"
        ],
        "actiontrail_raw_file_sha256": authority[
            "actiontrail_raw_file_sha256"
        ],
        "confirmation_envelope_file_sha256": authority[
            "confirmation_envelope_file_sha256"
        ],
        "old_clone_create_request_sha256": authority[
            "old_clone_create_request_sha256"
        ],
        "old_clone_create_body_sha256": authority[
            "old_clone_create_body_sha256"
        ],
        "old_clone_client_token_sha256": authority[
            "old_clone_client_token_sha256"
        ],
        "protection_disable_request_id_sha256": authority[
            "protection_disable_request_id_sha256"
        ],
        "protection_disable_request_body_sha256": authority[
            "protection_disable_request_body_sha256"
        ],
        "protection_disable_client_token_sha256": authority[
            "protection_disable_client_token_sha256"
        ],
        "delete_request_id_sha256": authority[
            "delete_request_id_sha256"
        ],
        "delete_request_body_sha256": authority[
            "delete_request_body_sha256"
        ],
        "delete_client_token_present": False,
        "consumed_mutation_identity_set_sha256": authority[
            "consumed_mutation_identity_set_sha256"
        ],
        "post_action_observed_at_utc": authority[
            "post_action_observed_at_utc"
        ],
        "terminal_accepted_at_utc": authority[
            "terminal_accepted_at_utc"
        ],
        "control_revision": control_revision,
        "evidence_revision": evidence_revision,
        "terminal_revision": terminal_revision,
        "readiness": READINESS_25_TO_25,
        "abort_v1_terminal_authority": False,
        "action_authorization_granted": False,
        "non_clone_resource_disposition": (
            "UNPROVEN_RETAINED_FRESH_PREFLIGHT_REQUIRED"
        ),
    }


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    errors, binding = validate_terminal_artifacts(root=args.root)
    if args.json:
        print(
            canonical_bytes({"errors": errors, "binding": binding})
            .decode("ascii"),
            end="",
        )
    elif errors:
        print(errors[0])
    return 0 if not errors and binding is not None else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "AUTHORITY_EPOCH_ID",
    "AUTHORITY_GENERATION_ID",
    "CHECKPOINT_REF",
    "CHECKPOINT_SCHEMA",
    "EVIDENCE_REF",
    "EVIDENCE_SCHEMA",
    "EXPECTED_AUTHORITY_ROOT_FILE_SHA256",
    "KIND",
    "HISTORICAL_OPERATION_ID",
    "MANUAL_RAW_EXTRACTOR_FINALIZED",
    "OPERATION_ID",
    "READINESS_25_TO_25",
    "RECEIPT_REF",
    "RECEIPT_SCHEMA",
    "TASK_ID",
    "TERMINAL_STATUS",
    "canonical_bytes",
    "consumed_mutation_identity_set_sha256",
    "raw_closure_sha256",
    "semantic_sha256",
    "sha256",
    "terminal_acceptance_sha256",
    "validate_checkpoint",
    "validate_evidence",
    "validate_receipt",
    "validate_terminal_artifacts",
]
