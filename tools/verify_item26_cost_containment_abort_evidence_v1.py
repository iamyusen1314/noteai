#!/usr/bin/env python3
"""Offline verifier for the Item 26 cost-containment abort.

The abort is a cost stop, not a restore success.  Its authority root and raw
provider extractor are intentionally unfinalized in this source checkpoint,
so repository JSON cannot self-authorize a destructive action or readiness
credit.  Lower-level receipt/evidence/checkpoint validators are complete and
pure, allowing the action contract to be reviewed before any cloud write.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any

from validate_item26_cost_containment_abort_result_v1 import (
    OPERATION_ID,
    READINESS_25_TO_25,
    TASK_ID,
    TERMINAL_STATUS,
    VALIDATOR_REF,
    validate_abort_result,
)
ROOT = Path(__file__).resolve().parents[1]
VERIFIER_REF = "tools/verify_item26_cost_containment_abort_evidence_v1.py"
BUILDER_REF = "tools/build_item26_cost_containment_abort_evidence_v1.py"
RECEIPT_SCHEMA = "noteai.item26.cost-containment-abort-provider-receipt.v1"
EVIDENCE_SCHEMA = "noteai.item26.cost-containment-abort-evidence.v1"
CHECKPOINT_SCHEMA = (
    "noteai.item26.cost-containment-abort-terminal-checkpoint.v1"
)
RECEIPT_REF = (
    "deploy/production/evidence/item26-cost-containment-abort-provider-receipt-20260816.json"
)
EVIDENCE_REF = (
    "deploy/production/evidence/production-item26-cost-containment-abort-20260816.json"
)
TERMINAL_CHECKPOINT_REF = (
    "deploy/production/evidence/item26-cost-containment-abort-terminal-checkpoint-20260816.json"
)
NO_REPLAY_REGISTRY_REF = "deploy/production/plans/item26-no-replay-registry-v1.json"
REQUIRED_ARTIFACT_REFS = {
    RECEIPT_REF,
    EVIDENCE_REF,
    TERMINAL_CHECKPOINT_REF,
    NO_REPLAY_REGISTRY_REF,
    VERIFIER_REF,
    BUILDER_REF,
    VALIDATOR_REF,
}
NO_REPLAY_REGISTRY_SCHEMA = "noteai.item26.no-replay-registry.v1"
EXPECTED_NO_REPLAY_REGISTRY_SHA256 = (
    "763ae967af95f55347e427f9df8e6c7014b16e645957417915e3ccd44d20e5d9"
)
EXPECTED_NO_REPLAY_ENTRY_COUNT = 25
EXPECTED_NO_REPLAY_KEYS = (
    "v1_source_capture",
    "v1_source_manifest_readback",
    "v1_source_manifest_diagnostic",
    "v1_source_manifest_cleanup",
    "v2_corrected_recovery",
    "v2_corrected_recovery_readback_1",
    "v2_corrected_recovery_readback_2",
    "v3_source_capture",
    "v3_source_manifest_readback",
    "v3_semantic_validator",
    "v3_fixed_timestamp_reader",
    "api_c_preflight_v1",
    "api_c_preflight_v2",
    "cloud_shell_toolchain_atom_v1",
    "wrapper_parent_diagnostic_v1",
    "retired_04c_history_probe",
    "retired_04c_impact_body",
    "failed_ci_checkpoint_a7c3350",
    "failed_ci_checkpoint_7cfe583",
    "original_exact_one_clone_request",
    "untracked_item26_envelope_rotate_promote",
    "untracked_item26_envelope_rotate_stage_template",
    "untracked_item26_source_manifest_executor",
    "untracked_item26_source_manifest_readback",
    "untracked_item26_source_manifest_recovery_executor",
)

# These values may be populated only in a new source checkpoint after the
# provider, action-confirmation and CI public keys plus the exact action plan
# are installed root-owned, and before any cloud mutation.  Keeping both
# fail-closed here prevents this scaffold from authorizing a browser action.
EXPECTED_AUTHORITY_ROOT_FILE_SHA256 = ""
RAW_PROVIDER_EXTRACTOR_FINALIZED = False

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MAX_BYTES = 2 * 1024 * 1024
GIT = Path("/usr/bin/git")
ACCEPTANCE_DOMAIN = b"noteai-item26-cost-containment-abort-terminal-v1\0"
RAW_CLOSURE_DOMAIN = b"noteai-item26-cost-containment-abort-raw-closure-v1\0"
NO_REPLAY_REGISTRY_DOMAIN = b"noteai-item26-no-replay-registry-v1\0"

RECEIPT_KEYS = {
    "schema_version",
    "schema",
    "task_id",
    "operation_id",
    "action",
    "status",
    "observed_at_utc",
    "source_revision",
    "source_binding",
    "authorization",
    "identity_ledger",
    "preflight",
    "ordered_actions",
    "billing_closure",
    "resource_dispositions",
    "final_state",
    "raw_closure",
    "no_replay",
    "execution_boundary",
    "readiness",
    "terminal_acceptance_sha256",
}

EVIDENCE_KEYS = {
    "schema_version",
    "schema",
    "task_id",
    "operation_id",
    "status",
    "source_revision",
    "provider_receipt",
    "external_authority",
    "abort_outcome",
    "final_runtime_state",
    "cost_and_data_boundary",
    "no_replay",
    "secret_free_evidence",
    "readiness",
}

CHECKPOINT_KEYS = {
    "schema",
    "task_id",
    "operation_id",
    "status",
    "execution_revision",
    "evidence_revision",
    "evidence_file_sha256",
    "evidence_semantic_sha256",
    "receipt_file_sha256",
    "receipt_semantic_sha256",
    "terminal_acceptance_sha256",
    "automatic_retry_allowed",
    "readiness_credit_added",
    "item26_status",
}

AUTHORITY_BINDING_KEYS = {
    "authority_root_file_sha256",
    "provider_export_semantic_sha256",
    "confirmation_export_semantic_sha256",
    "provider_key_spki_sha256",
    "confirmation_key_spki_sha256",
    "ci_key_spki_sha256",
    "authority_keys_distinct",
    "root_frozen_before_execution",
    "raw_projection_rederived",
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


def _semantic(value: Any) -> str:
    return _sha(_canonical(value)[:-1])


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
            return None, None, "abort artifact identity invalid"
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
            return None, None, "abort artifact identity changed"

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
        return None, None, "cannot read canonical abort JSON"
    if type(value) is not dict or _canonical(value) != raw:
        return None, None, "abort JSON is not canonical"
    return value, raw, None


def git_tree_binding(revision: str, *, root: Path = ROOT) -> tuple[str, int]:
    if HEX40.fullmatch(revision or "") is None:
        raise ValueError("abort source tree identity")
    try:
        before = GIT.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or before.st_uid != 0
            or stat.S_IMODE(before.st_mode) & 0o022
        ):
            raise ValueError("abort git identity")
        result = subprocess.run(
            [
                str(GIT),
                "--no-replace-objects",
                "ls-tree",
                "-r",
                "--full-tree",
                "-z",
                revision,
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
        after = GIT.lstat()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("abort source tree identity") from exc
    if (
        result.returncode != 0
        or not result.stdout
        or len(result.stdout) > MAX_BYTES * 16
        or not result.stdout.endswith(b"\0")
        or _stable(before) != _stable(after)
    ):
        raise ValueError("abort source tree identity")
    return _sha(result.stdout), result.stdout.count(b"\0")


def _revision_is_strict_ancestor(
    ancestor: str,
    descendant: str,
    *,
    root: Path = ROOT,
) -> bool:
    if (
        HEX40.fullmatch(ancestor or "") is None
        or HEX40.fullmatch(descendant or "") is None
        or ancestor == descendant
    ):
        return False
    try:
        result = subprocess.run(
            [
                str(GIT),
                "--no-replace-objects",
                "merge-base",
                "--is-ancestor",
                ancestor,
                descendant,
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
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def no_replay_registry_sha256(registry: dict[str, Any]) -> str:
    projection = dict(registry)
    projection.pop("registry_sha256", None)
    return _sha(NO_REPLAY_REGISTRY_DOMAIN + _canonical(projection))


def validate_no_replay_registry(value: Any) -> list[str]:
    top_keys = {
        "schema",
        "task_id",
        "status",
        "unknown_resolution_policy",
        "automatic_retry_allowed",
        "all_replay_allowed_false",
        "all_replacement_allowed_false",
        "untracked_script_execution_authorized",
        "entry_count",
        "entries",
        "registry_sha256",
    }
    entry_keys = {
        "key",
        "category",
        "consumption_state",
        "terminal_class",
        "readback_policy",
        "replay_allowed",
        "replacement_allowed",
        "automatic_retry_allowed",
        "artifact_bytes",
        "artifact_sha256",
    }
    if type(value) is not dict or set(value) != top_keys:
        return ["abort no-replay registry schema mismatch"]
    entries = value["entries"]
    if (
        value["schema"] != NO_REPLAY_REGISTRY_SCHEMA
        or value["task_id"] != TASK_ID
        or value["status"] != "FROZEN_SOURCE_CHECKPOINT_POLICY"
        or value["unknown_resolution_policy"]
        != "EXACT_EXISTING_IDENTITY_READBACK_ONLY"
        or value["automatic_retry_allowed"] is not False
        or value["all_replay_allowed_false"] is not True
        or value["all_replacement_allowed_false"] is not True
        or value["untracked_script_execution_authorized"] is not False
        or type(value["entry_count"]) is not int
        or value["entry_count"] != EXPECTED_NO_REPLAY_ENTRY_COUNT
        or type(entries) is not list
        or len(entries) != EXPECTED_NO_REPLAY_ENTRY_COUNT
        or not _hex64(value["registry_sha256"])
        or value["registry_sha256"] != EXPECTED_NO_REPLAY_REGISTRY_SHA256
        or value["registry_sha256"] != no_replay_registry_sha256(value)
    ):
        return ["abort no-replay registry identity mismatch"]
    observed_keys: list[str] = []
    for row in entries:
        if type(row) is not dict or set(row) != entry_keys:
            return ["abort no-replay registry entry schema mismatch"]
        observed_keys.append(row["key"])
        artifact_bytes = row["artifact_bytes"]
        artifact_sha256 = row["artifact_sha256"]
        if (
            any(
                type(row[key]) is not str or not row[key]
                for key in (
                    "key",
                    "category",
                    "consumption_state",
                    "terminal_class",
                    "readback_policy",
                )
            )
            or row["replay_allowed"] is not False
            or row["replacement_allowed"] is not False
            or row["automatic_retry_allowed"] is not False
            or (
                artifact_bytes is None
                and artifact_sha256 is not None
            )
            or (
                artifact_bytes is not None
                and (
                    type(artifact_bytes) is not int
                    or artifact_bytes <= 0
                    or not _hex64(artifact_sha256)
                )
            )
        ):
            return ["abort no-replay registry entry mismatch"]
    if tuple(observed_keys) != EXPECTED_NO_REPLAY_KEYS:
        return ["abort no-replay registry frozen identity set mismatch"]
    return []


def terminal_acceptance_sha256(receipt: dict[str, Any]) -> str:
    projection = dict(receipt)
    projection.pop("terminal_acceptance_sha256", None)
    return _sha(ACCEPTANCE_DOMAIN + _canonical(projection))


def raw_closure_sha256(receipt: dict[str, Any]) -> str:
    return _sha(RAW_CLOSURE_DOMAIN + _canonical(receipt["raw_closure"]))


def _terminal_authority_finalized() -> bool:
    return bool(
        RAW_PROVIDER_EXTRACTOR_FINALIZED
        and _hex64(EXPECTED_AUTHORITY_ROOT_FILE_SHA256)
    )


def validate_receipt(
    value: Any,
    *,
    expected_execution_revision: str,
    root: Path = ROOT,
) -> tuple[list[str], str | None]:
    errors: list[str] = []
    if type(value) is not dict or set(value) != RECEIPT_KEYS:
        return ["abort receipt schema mismatch"], None
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["schema"] != RECEIPT_SCHEMA
        or value["task_id"] != TASK_ID
        or value["operation_id"] != OPERATION_ID
        or value["action"] != "COST_CONTAINMENT_ABORT"
        or value["status"] != TERMINAL_STATUS
        or value["source_revision"] != expected_execution_revision
        or HEX40.fullmatch(value["source_revision"] or "") is None
        or UTC.fullmatch(value["observed_at_utc"] or "") is None
    ):
        errors.append("abort receipt identity mismatch")
    try:
        tree_sha256, tracked_file_count = git_tree_binding(
            expected_execution_revision,
            root=root,
        )
    except (OSError, ValueError):
        tree_sha256, tracked_file_count = "", -1
        errors.append("abort source Git tree unavailable")
    if not _strict(
        value.get("source_binding"),
        {
            "revision": expected_execution_revision,
            "tree_sha256": tree_sha256,
            "tracked_file_count": tracked_file_count,
            "dirty_path_count": 0,
        },
    ):
        errors.append("abort source binding mismatch")
    registry, _registry_raw, registry_error = _load(
        root / NO_REPLAY_REGISTRY_REF
    )
    if registry_error or registry is None:
        errors.append(registry_error or "abort no-replay registry unavailable")
    else:
        registry_errors = validate_no_replay_registry(registry)
        if (
            registry_errors
            or registry["registry_sha256"]
            != (
                value["no_replay"].get("registry_sha256")
                if type(value.get("no_replay")) is dict
                else None
            )
        ):
            errors.extend(
                registry_errors or ["abort receipt no-replay registry mismatch"]
            )
    errors.extend(validate_abort_result(value))
    acceptance = terminal_acceptance_sha256(value)
    if not _hex64(value.get("terminal_acceptance_sha256")) or value[
        "terminal_acceptance_sha256"
    ] != acceptance:
        errors.append("abort terminal acceptance mismatch")
    return errors, acceptance if not errors else None


def validate_evidence(
    value: Any,
    receipt: dict[str, Any],
    receipt_raw: bytes,
    *,
    expected_execution_revision: str,
    authority_binding: dict[str, Any],
) -> list[str]:
    if type(value) is not dict or set(value) != EVIDENCE_KEYS:
        return ["abort evidence schema mismatch"]
    errors: list[str] = []
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["schema"] != EVIDENCE_SCHEMA
        or value["task_id"] != TASK_ID
        or value["operation_id"] != OPERATION_ID
        or value["status"] != "PASS_NO_READINESS_CREDIT"
        or value["source_revision"] != expected_execution_revision
    ):
        errors.append("abort evidence identity mismatch")
    if (
        type(authority_binding) is not dict
        or set(authority_binding) != AUTHORITY_BINDING_KEYS
        or any(
            not _hex64(authority_binding[key])
            for key in AUTHORITY_BINDING_KEYS
            if key.endswith("_sha256")
        )
        or len({
            authority_binding["provider_key_spki_sha256"],
            authority_binding["confirmation_key_spki_sha256"],
            authority_binding["ci_key_spki_sha256"],
        }) != 3
        or authority_binding["authority_keys_distinct"] is not True
        or authority_binding["root_frozen_before_execution"] is not True
        or authority_binding["raw_projection_rederived"] is not True
    ):
        errors.append("abort evidence authority binding invalid")
    if not _strict(
        value["provider_receipt"],
        {
            "file_sha256": _sha(receipt_raw),
            "semantic_sha256": _semantic(receipt),
            "terminal_acceptance_sha256": receipt[
                "terminal_acceptance_sha256"
            ],
            "raw_closure_sha256": raw_closure_sha256(receipt),
        },
    ):
        errors.append("abort evidence receipt binding mismatch")
    if not _strict(
        value["external_authority"],
        authority_binding,
    ):
        errors.append("abort evidence external authority mismatch")
    if not _strict(
        value["abort_outcome"],
        {
            "status": TERMINAL_STATUS,
            "old_clone_absent": True,
            "billing_closed": True,
            "temporary_cleanup_terminal": True,
            "item26_verified": False,
            "future_successor_requires_new_fee_authorization": True,
        },
    ):
        errors.append("abort evidence outcome mismatch")
    if not _strict(value["final_runtime_state"], receipt["final_state"]):
        errors.append("abort evidence final state mismatch")
    expected_cost = {
        "currency": receipt["billing_closure"]["currency"],
        "approved_24h_ceiling_cny": receipt["billing_closure"][
            "approved_24h_ceiling_cny"
        ],
        "pre_abort_gross_cny": receipt["billing_closure"]["pre_abort_gross_cny"],
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
    }
    if not _strict(value["cost_and_data_boundary"], expected_cost):
        errors.append("abort evidence cost/data boundary mismatch")
    if not _strict(value["no_replay"], receipt["no_replay"]):
        errors.append("abort evidence no-replay mismatch")
    if not _strict(
        value["secret_free_evidence"],
        {
            "secret_value_count": 0,
            "password_value_count": 0,
            "private_key_value_count": 0,
            "connection_string_value_count": 0,
            "database_row_value_count": 0,
            "resource_identifier_value_count": 0,
            "raw_provider_payload_count": 0,
        },
    ):
        errors.append("abort evidence Secret-free boundary mismatch")
    if not _strict(value["readiness"], READINESS_25_TO_25):
        errors.append("abort evidence readiness mismatch")
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
    if type(value) is not dict or set(value) != CHECKPOINT_KEYS:
        return ["abort checkpoint schema mismatch"]
    expected = {
        "schema": CHECKPOINT_SCHEMA,
        "task_id": TASK_ID,
        "operation_id": OPERATION_ID,
        "status": "ABORT_EVIDENCE_CHECKPOINT_EXACT_HEAD_CI_ACCEPTED",
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
        "item26_status": "unverified",
    }
    if (
        HEX40.fullmatch(expected_execution_revision or "") is None
        or HEX40.fullmatch(expected_evidence_revision or "") is None
        or expected_execution_revision == expected_evidence_revision
    ):
        return ["abort checkpoint revision identity mismatch"]
    return [] if _strict(value, expected) else ["abort checkpoint mismatch"]


def validate_abort_authority_bundle(
    *,
    root: Path = ROOT,
) -> tuple[list[str], dict[str, Any] | None]:
    """Fail closed until the pre-action root and raw extractor are frozen.

    The terminal implementation must reload root-owned provider raw bytes and
    the action-time confirmation, derive the receipt projection, verify three
    distinct provider/confirmation/CI signatures, and bind three revisions plus
    six attempt-one CI receipts.  This source revision intentionally cannot do
    that because no destructive-action confirmation has been issued.
    """

    del root
    if not _terminal_authority_finalized():
        return ["abort external authority/raw extractor is not finalized"], None
    return ["abort external authority implementation is not installed"], None


def validate_terminal_artifacts(
    *,
    root: Path = ROOT,
) -> tuple[list[str], dict[str, Any] | None]:
    authority_errors, authority = validate_abort_authority_bundle(root=root)
    if authority_errors or authority is None:
        return authority_errors or ["abort external authority missing"], None
    required_authority = {
        "execution_revision",
        "evidence_revision",
        "terminal_revision",
        "receipt_file_sha256",
        "evidence_file_sha256",
        "checkpoint_file_sha256",
        "authority_root_file_sha256",
        "authority_bundle_file_sha256",
        "raw_closure_file_sha256",
        "confirmation_envelope_file_sha256",
        "old_clone_create_request_sha256",
        "old_clone_create_body_sha256",
        "old_clone_client_token_sha256",
        "old_clone_name_sha256",
        "terminal_observed_at_utc",
        "terminal_acceptance_sha256",
        "raw_closure_sha256",
        "no_replay_registry_sha256",
        "external_authority_binding",
    }
    if set(authority) != required_authority:
        return ["abort authority binding schema mismatch"], None
    if (
        any(
            not _hex64(authority[key])
            for key in (
                "old_clone_create_request_sha256",
                "old_clone_create_body_sha256",
                "old_clone_client_token_sha256",
                "old_clone_name_sha256",
            )
        )
        or len({
            authority["old_clone_create_request_sha256"],
            authority["old_clone_create_body_sha256"],
            authority["old_clone_client_token_sha256"],
            authority["old_clone_name_sha256"],
        }) != 4
        or UTC.fullmatch(authority["terminal_observed_at_utc"] or "") is None
    ):
        return ["abort original clone identity authority mismatch"], None
    if not (
        _revision_is_strict_ancestor(
            authority["execution_revision"],
            authority["evidence_revision"],
            root=root,
        )
        and _revision_is_strict_ancestor(
            authority["evidence_revision"],
            authority["terminal_revision"],
            root=root,
        )
    ):
        return ["abort terminal revision ancestry mismatch"], None
    receipt, receipt_raw, receipt_error = _load(root / RECEIPT_REF)
    evidence, evidence_raw, evidence_error = _load(root / EVIDENCE_REF)
    checkpoint, checkpoint_raw, checkpoint_error = _load(
        root / TERMINAL_CHECKPOINT_REF
    )
    registry, _registry_raw, registry_error = _load(root / NO_REPLAY_REGISTRY_REF)
    if receipt_error or evidence_error or checkpoint_error or registry_error:
        return [
            receipt_error
            or evidence_error
            or checkpoint_error
            or registry_error
            or "abort artifact read failure"
        ], None
    assert receipt is not None and receipt_raw is not None
    assert evidence is not None and evidence_raw is not None
    assert checkpoint is not None and checkpoint_raw is not None
    assert registry is not None
    if (
        _sha(receipt_raw) != authority["receipt_file_sha256"]
        or _sha(evidence_raw) != authority["evidence_file_sha256"]
        or _sha(checkpoint_raw) != authority["checkpoint_file_sha256"]
        or receipt["raw_closure"]["root_owned_raw_file_sha256"]
        != authority["raw_closure_file_sha256"]
        or receipt["authorization"]["confirmation_envelope_sha256"]
        != authority["confirmation_envelope_file_sha256"]
        or evidence["external_authority"]["authority_root_file_sha256"]
        != authority["authority_root_file_sha256"]
        or evidence["external_authority"]
        != authority["external_authority_binding"]
        or receipt["observed_at_utc"] != authority["terminal_observed_at_utc"]
    ):
        return ["abort terminal artifact authority mismatch"], None
    registry_errors = validate_no_replay_registry(registry)
    if (
        registry_errors
        or registry["registry_sha256"]
        != authority["no_replay_registry_sha256"]
        or registry["registry_sha256"] != receipt["no_replay"]["registry_sha256"]
        or registry["registry_sha256"] != no_replay_registry_sha256(registry)
    ):
        return registry_errors or ["abort no-replay registry mismatch"], None
    receipt_errors, acceptance = validate_receipt(
        receipt,
        expected_execution_revision=authority["execution_revision"],
        root=root,
    )
    if (
        receipt_errors
        or acceptance != authority["terminal_acceptance_sha256"]
        or raw_closure_sha256(receipt) != authority["raw_closure_sha256"]
    ):
        return receipt_errors or ["abort receipt authority mismatch"], None
    evidence_errors = validate_evidence(
        evidence,
        receipt,
        receipt_raw,
        expected_execution_revision=authority["execution_revision"],
        authority_binding=authority["external_authority_binding"],
    )
    checkpoint_errors = validate_checkpoint(
        checkpoint,
        evidence,
        evidence_raw,
        receipt,
        receipt_raw,
        expected_execution_revision=authority["execution_revision"],
        expected_evidence_revision=authority["evidence_revision"],
    )
    errors = [*evidence_errors, *checkpoint_errors]
    if errors:
        return errors, None
    return [], {
        "status": TERMINAL_STATUS,
        "terminal_acceptance_sha256": acceptance,
        "old_clone_sha256": receipt["identity_ledger"]["old_clone_sha256"],
        "billing_closure_sha256": _semantic(receipt["billing_closure"]),
        "resource_disposition_sha256": _semantic(receipt["resource_dispositions"]),
        "no_replay_registry_sha256": registry["registry_sha256"],
        "authority_root_file_sha256": authority[
            "authority_root_file_sha256"
        ],
        "authority_bundle_file_sha256": authority[
            "authority_bundle_file_sha256"
        ],
        "raw_closure_file_sha256": authority["raw_closure_file_sha256"],
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
        "old_clone_name_sha256": authority["old_clone_name_sha256"],
        "terminal_observed_at_utc": authority["terminal_observed_at_utc"],
        "execution_revision": authority["execution_revision"],
        "evidence_revision": authority["evidence_revision"],
        "terminal_revision": authority["terminal_revision"],
        "readiness": READINESS_25_TO_25,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    errors, binding = validate_terminal_artifacts(root=args.root)
    if errors or binding is None:
        if args.json:
            print(
                _canonical(
                    {
                        "errors": errors or ["abort terminal binding missing"],
                        "binding": None,
                    }
                ).decode("ascii"),
                end="",
            )
        else:
            for error in errors:
                print("ERROR: " + error)
        return 1
    if args.json:
        print(_canonical({"errors": [], "binding": binding}).decode("ascii"), end="")
        return 0
    print("item26_cost_containment_abort=PASS_NO_READINESS_CREDIT")
    print("terminal_acceptance_sha256=" + binding["terminal_acceptance_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BUILDER_REF",
    "CHECKPOINT_SCHEMA",
    "EVIDENCE_REF",
    "EVIDENCE_SCHEMA",
    "EXPECTED_AUTHORITY_ROOT_FILE_SHA256",
    "OPERATION_ID",
    "RAW_PROVIDER_EXTRACTOR_FINALIZED",
    "RECEIPT_REF",
    "RECEIPT_SCHEMA",
    "REQUIRED_ARTIFACT_REFS",
    "TASK_ID",
    "TERMINAL_CHECKPOINT_REF",
    "TERMINAL_STATUS",
    "VERIFIER_REF",
    "raw_closure_sha256",
    "terminal_acceptance_sha256",
    "validate_abort_authority_bundle",
    "validate_checkpoint",
    "validate_evidence",
    "validate_receipt",
    "validate_terminal_artifacts",
]
