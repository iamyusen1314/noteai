#!/usr/bin/env python3
"""Offline semantic verifier for Item 28 failure/rollback evidence.

All terminal authority roots intentionally remain empty in the source-only
checkpoint.  Consequently the current readiness manifest stays BLOCKED even
if a locally fabricated receipt has the right JSON shape.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

from build_item28_internal_failure_rollback_evidence_v1 import (
    BUILDER_REF, CAPTURE_CONTRACT, EXECUTOR_REF, RECEIPT_SCHEMA, RENDERER_REF,
    terminal_acceptance_sha256,
)
from validate_item28_internal_failure_rollback_result_v1 import (
    VALIDATOR_REF, validate_executor_result,
)


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_REF = "tools/verify_internal_failure_rollback_evidence.py"
TASK_ID = "PROD-FIRST-LAUNCH-INTERNAL-ROLLBACK-001"
EVIDENCE_SCHEMA = "noteai.item28.internal-failure-rollback-evidence.v1"
CHECKPOINT_SCHEMA = "noteai.item28.terminal-evidence-checkpoint.v1"
EVIDENCE_REF = (
    "deploy/production/evidence/"
    "production-internal-failure-rollback-verified-20260814.json"
)
RECEIPT_REF = (
    "deploy/production/evidence/"
    "internal-failure-rollback-api-f-provider-receipt-20260814.json"
)
TERMINAL_CHECKPOINT_REF = (
    "deploy/production/evidence/"
    "internal-failure-rollback-terminal-checkpoint-20260814.json"
)
REQUIRED_MANIFEST_PATH_REFS = {
    EVIDENCE_REF, RECEIPT_REF, TERMINAL_CHECKPOINT_REF, VERIFIER_REF,
    EXECUTOR_REF, RENDERER_REF, BUILDER_REF, VALIDATOR_REF,
}
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

# Filled only by a post-execution, exact-HEAD terminal checkpoint.
EXPECTED_SOURCE_REVISION = ""
EXPECTED_EVIDENCE_FILE_SHA256 = ""
EXPECTED_EVIDENCE_SEMANTIC_SHA256 = ""
EXPECTED_RECEIPT_FILE_SHA256 = ""
EXPECTED_RECEIPT_SEMANTIC_SHA256 = ""
EXPECTED_TERMINAL_CHECKPOINT_FILE_SHA256 = ""
EXPECTED_TERMINAL_CHECKPOINT_SEMANTIC_SHA256 = ""

# Independent predecessor trust roots.  A manifest status is never accepted as
# a substitute for these values.
EXPECTED_ITEM25_TERMINAL_VERIFIER_REF = ""
EXPECTED_ITEM25_TERMINAL_EVIDENCE_REF = ""
EXPECTED_ITEM25_TERMINAL_VERIFIER_SHA256 = ""
EXPECTED_ITEM25_TERMINAL_EVIDENCE_SHA256 = ""
EXPECTED_ITEM25_TERMINAL_ACCEPTANCE_SHA256 = ""
EXPECTED_ITEM26_TERMINAL_VERIFIER_REF = ""
EXPECTED_ITEM26_TERMINAL_EVIDENCE_REF = ""
EXPECTED_ITEM26_TERMINAL_VERIFIER_SHA256 = ""
EXPECTED_ITEM26_TERMINAL_EVIDENCE_SHA256 = ""
EXPECTED_ITEM26_TERMINAL_ACCEPTANCE_SHA256 = ""
EXPECTED_ITEM27_TERMINAL_VERIFIER_REF = ""
EXPECTED_ITEM27_TERMINAL_EVIDENCE_REF = ""
EXPECTED_ITEM27_TERMINAL_VERIFIER_SHA256 = ""
EXPECTED_ITEM27_TERMINAL_EVIDENCE_SHA256 = ""
EXPECTED_ITEM27_TERMINAL_ACCEPTANCE_SHA256 = ""

DEFAULT_READINESS = {
    "internal_verified_before": 27,
    "internal_verified_after": 28,
    "internal_total": 29,
    "internal_percentage_after": 97,
    "complete_public_verified_before": 27,
    "complete_public_verified_after": 28,
    "complete_public_total": 38,
    "complete_public_percentage_after": 74,
    "next_task": "PROD-FIRST-LAUNCH-CAPACITY-100-001",
    "public_launch_authorized": False,
    "real_provider_chain_verified": False,
    "capacity_100_jobs_verified": False,
}


def _canonical(value: Any) -> bytes:
    return (json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ) + "\n").encode("ascii")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _semantic(value: Any) -> str:
    return _sha(_canonical(value)[:-1])


def _hex64(value: Any) -> bool:
    return type(value) is str and HEX64.fullmatch(value) is not None


def _strict(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if type(right) is dict:
        return set(left) == set(right) and all(_strict(left[key], item) for key, item in right.items())
    if type(right) is list:
        return len(left) == len(right) and all(_strict(a, b) for a, b in zip(left, right))
    return left == right


def _load(path: Path) -> tuple[dict[str, Any] | None, bytes | None, str | None]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, None, "cannot read canonical JSON"
    if type(value) is not dict or _canonical(value) != raw:
        return None, None, "JSON is not canonical"
    return value, raw, None


def _source_hash(root: Path, ref: str) -> str | None:
    identity = _source_identity(root, ref)
    return identity[1] if identity is not None else None


def _source_identity(root: Path, ref: str) -> tuple[int, str] | None:
    try:
        path = root / ref
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode)
            or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o644
        ):
            return None
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                return None
            raw = b""
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                raw += chunk
                if len(raw) > 2 * 1024 * 1024:
                    return None
        finally:
            os.close(fd)
        after = path.lstat()
    except OSError:
        return None
    if (
        before.st_dev, before.st_ino, before.st_mode, before.st_size,
        before.st_mtime_ns,
    ) != (
        after.st_dev, after.st_ino, after.st_mode, after.st_size,
        after.st_mtime_ns,
    ):
        return None
    return len(raw), _sha(raw)


def predecessor_authority_roots() -> dict[str, dict[str, str]]:
    return {
        "item25": {
            "verifier_ref": EXPECTED_ITEM25_TERMINAL_VERIFIER_REF,
            "evidence_ref": EXPECTED_ITEM25_TERMINAL_EVIDENCE_REF,
            "verifier_sha256": EXPECTED_ITEM25_TERMINAL_VERIFIER_SHA256,
            "evidence_sha256": EXPECTED_ITEM25_TERMINAL_EVIDENCE_SHA256,
            "terminal_acceptance_sha256": EXPECTED_ITEM25_TERMINAL_ACCEPTANCE_SHA256,
        },
        "item26": {
            "verifier_ref": EXPECTED_ITEM26_TERMINAL_VERIFIER_REF,
            "evidence_ref": EXPECTED_ITEM26_TERMINAL_EVIDENCE_REF,
            "verifier_sha256": EXPECTED_ITEM26_TERMINAL_VERIFIER_SHA256,
            "evidence_sha256": EXPECTED_ITEM26_TERMINAL_EVIDENCE_SHA256,
            "terminal_acceptance_sha256": EXPECTED_ITEM26_TERMINAL_ACCEPTANCE_SHA256,
        },
        "item27": {
            "verifier_ref": EXPECTED_ITEM27_TERMINAL_VERIFIER_REF,
            "evidence_ref": EXPECTED_ITEM27_TERMINAL_EVIDENCE_REF,
            "verifier_sha256": EXPECTED_ITEM27_TERMINAL_VERIFIER_SHA256,
            "evidence_sha256": EXPECTED_ITEM27_TERMINAL_EVIDENCE_SHA256,
            "terminal_acceptance_sha256": EXPECTED_ITEM27_TERMINAL_ACCEPTANCE_SHA256,
        },
    }


def validate_predecessor_evidence(controls_by_id: Any, *, root: Path = ROOT):
    errors: list[str] = []
    if type(controls_by_id) is not dict:
        return ["Item28 predecessor controls invalid"], None
    expected_controls = {
        "item25": "monitoring_alerting",
        "item26": "backup_pitr_restore",
        "item27": "internal_zero_provider_smoke",
    }
    roots = predecessor_authority_roots()
    acceptances: dict[str, str] = {}
    for item, control_id in expected_controls.items():
        control = controls_by_id.get(control_id)
        if type(control) is not dict or control.get("status") != "verified":
            errors.append(item + " terminal verification required")
            continue
        authority = roots[item]
        if (
            not all(type(value) is str and value for value in authority.values())
            or not all(_hex64(authority[key]) for key in (
                "verifier_sha256", "evidence_sha256", "terminal_acceptance_sha256",
            ))
        ):
            errors.append(item + " terminal authority root is not finalized")
            continue
        if (
            _source_hash(root, authority["verifier_ref"]) != authority["verifier_sha256"]
            or _source_hash(root, authority["evidence_ref"]) != authority["evidence_sha256"]
        ):
            errors.append(item + " terminal authority bytes mismatch")
            continue
        evidence_refs = {
            row.get("ref") for row in control.get("evidence", [])
            if type(row) is dict and row.get("kind") == "path"
        }
        if authority["verifier_ref"] not in evidence_refs or authority["evidence_ref"] not in evidence_refs:
            errors.append(item + " terminal authority refs missing")
            continue
        acceptances[item] = authority["terminal_acceptance_sha256"]
    if errors or set(acceptances) != set(expected_controls):
        return errors or ["Item28 predecessor terminal closure incomplete"], None
    if len(set(acceptances.values())) != 3:
        return ["Item28 predecessor acceptance hashes must be distinct"], None
    return [], acceptances


def validate_receipt(value: Any, *, expected_predecessors: dict[str, str], root: Path = ROOT):
    errors: list[str] = []
    top_keys = {
        "schema_version", "schema", "task_id", "action", "status",
        "observed_at_utc", "source_revision", "source_binding",
        "predecessors", "raw_closure", "request", "pre_dispatch",
        "terminal_readback", "result", "result_binding", "execution_boundary",
    }
    if type(value) is not dict or set(value) != top_keys:
        return ["Item28 receipt schema mismatch"], None
    expected_scalars = {
        "schema_version": 1,
        "schema": RECEIPT_SCHEMA,
        "task_id": TASK_ID,
        "action": "api_f_rollback",
        "status": "PROVIDER_TERMINAL_VERIFIED",
        "source_revision": EXPECTED_SOURCE_REVISION,
    }
    for key, expected in expected_scalars.items():
        if type(value.get(key)) is not type(expected) or value.get(key) != expected:
            errors.append("receipt " + key + " mismatch")
    if type(value.get("observed_at_utc")) is not str or UTC.fullmatch(value["observed_at_utc"]) is None:
        errors.append("receipt observed_at_utc mismatch")
    if not _strict(value.get("predecessors"), expected_predecessors):
        errors.append("receipt predecessors mismatch")
    source = value.get("source_binding")
    expected_refs = {
        "executor": EXECUTOR_REF, "renderer": RENDERER_REF,
        "builder": BUILDER_REF, "validator": VALIDATOR_REF,
    }
    if type(source) is not dict or set(source) != set(expected_refs):
        errors.append("receipt source binding schema mismatch")
    else:
        for label, ref in expected_refs.items():
            row = source[label]
            actual = _source_identity(root, ref)
            if (
                type(row) is not dict or set(row) != {"path", "bytes", "sha256"}
                or actual is None or row.get("path") != ref
                or row.get("bytes") != actual[0]
                or row.get("sha256") != actual[1]
            ):
                errors.append("receipt source " + label + " mismatch")
    raw = value.get("raw_closure") or {}
    if (
        set(raw) != {
            "capture_contract", "capture_file_count",
            "capture_manifest_canonical_bytes",
            "capture_manifest_canonical_sha256",
            "raw_provider_bodies_retained_root_only",
            "raw_provider_value_emitted_count",
            "raw_response_commitment_count",
            "provider_request_commitment_count",
        }
        or raw.get("capture_contract") != CAPTURE_CONTRACT
        or raw.get("capture_file_count") != 13
        or type(raw.get("capture_manifest_canonical_bytes")) is not int
        or raw["capture_manifest_canonical_bytes"] <= 0
        or not _hex64(raw.get("capture_manifest_canonical_sha256"))
        or raw.get("raw_provider_bodies_retained_root_only") is not True
        or raw.get("raw_provider_value_emitted_count") != 0
        or raw.get("raw_response_commitment_count") != 6
        or raw.get("provider_request_commitment_count") != 6
    ):
        errors.append("receipt raw closure mismatch")
    request = value.get("request") or {}
    request_keys = {
        "canonical_bytes", "canonical_sha256", "command_name",
        "command_content_sha256", "executor_sha256", "client_token_sha256",
        "target_identity_sha256", "provider_request_id_sha256",
        "provider_command_id_sha256", "provider_invoke_id_sha256",
        "run_command_response_raw_bytes", "run_command_response_raw_sha256",
    }
    if (
        set(request) != request_keys
        or type(request.get("canonical_bytes")) is not int
        or request["canonical_bytes"] <= 0
        or type(request.get("run_command_response_raw_bytes")) is not int
        or request["run_command_response_raw_bytes"] <= 0
        or request.get("command_name")
        != "noteai-item28-internal-rollback-api-f-20260824-unit-fix1"
        or any(not _hex64(request.get(key)) for key in request_keys
               if key.endswith("sha256"))
    ):
        errors.append("receipt request binding mismatch")
    pre = value.get("pre_dispatch") or {}
    if (
        set(pre) != {
            "all_pages", "page_number", "page_size",
            "exact_command_name_history_count",
            "exact_invocation_name_history_count",
            "provider_client_token_readback_supported",
            "commands_request_bytes", "commands_request_sha256",
            "commands_response_raw_bytes", "commands_response_raw_sha256",
            "invocations_request_bytes", "invocations_request_sha256",
            "invocations_response_raw_bytes", "invocations_response_raw_sha256",
        }
        or pre.get("all_pages") is not True
        or pre.get("page_number") != 1 or pre.get("page_size") != 50
        or pre.get("exact_command_name_history_count") != 0
        or pre.get("exact_invocation_name_history_count") != 0
        or pre.get("provider_client_token_readback_supported") is not False
        or any(not _hex64(pre.get(key)) for key in pre if key.endswith("sha256"))
        or any(type(pre.get(key)) is not int or pre[key] <= 0
               for key in pre if key.endswith("bytes"))
    ):
        errors.append("receipt pre-dispatch history mismatch")
    terminal = value.get("terminal_readback") or {}
    terminal_scalars = {
        "all_pages": True, "command_match_count": 1,
        "invocation_match_count": 1, "result_match_count": 1,
        "provider_status": "Finished", "provider_result_status": "Success",
        "exit_code": 0, "dropped_count": 0, "repeat_count": 1,
        "provider_readable_run_command_field_count": 7,
    }
    if (
        set(terminal) != {
            *terminal_scalars,
            "request_canonical_sha256",
            "provider_readable_run_command_sha256",
            "commands_response_raw_bytes", "commands_response_raw_sha256",
            "invocations_response_raw_bytes", "invocations_response_raw_sha256",
            "results_response_raw_bytes", "results_response_raw_sha256",
        }
        or any(terminal.get(key) != expected for key, expected in terminal_scalars.items())
        or any(not _hex64(terminal.get(key)) for key in terminal if key.endswith("sha256"))
        or any(type(terminal.get(key)) is not int or terminal[key] <= 0
               for key in terminal if key.endswith("bytes"))
    ):
        errors.append("receipt terminal readback mismatch")
    result_errors, derived = validate_executor_result(value.get("result"))
    if result_errors or derived is None or not _strict(value.get("result_binding"), derived):
        errors.append("receipt executor result mismatch")
    boundary = value.get("execution_boundary") or {}
    boundary_expected = {
        "dispatch_count": 1, "automatic_retry_count": 0,
        "same_request_resubmit_allowed": False,
        "same_invocation_replay_allowed": False, "provider_unknown": False,
        "local_o_excl_plan_nonce_required": True,
        "provider_client_token_readback_supported": False,
        "provider_call_count": 0, "oss_mutation_count": 0,
        "iam_mutation_count": 0, "production_database_mutation_count": 0,
        "cloud_resource_create_count": 0,
    }
    if set(boundary) != set(boundary_expected) or any(
        type(boundary.get(key)) is not type(expected)
        or boundary.get(key) != expected
        for key, expected in boundary_expected.items()
    ):
        errors.append("receipt execution boundary mismatch")
    acceptance = terminal_acceptance_sha256(value) if not errors else None
    return errors, acceptance


def validate_evidence(value: Any, receipt: Any, *, expected_predecessors: dict[str, str], expected_readiness: dict[str, Any], root: Path = ROOT):
    errors: list[str] = []
    keys = {
        "schema_version", "schema", "task_id", "status", "source_revision",
        "predecessors", "provider_receipt", "rehearsal", "final_runtime_state",
        "mutation_counters", "cost_and_data_boundary", "readiness",
    }
    if type(value) is not dict or set(value) != keys:
        return ["Item28 evidence schema mismatch"]
    if (
        value.get("schema_version") != 1 or value.get("schema") != EVIDENCE_SCHEMA
        or value.get("task_id") != TASK_ID or value.get("status") != "PASS"
        or value.get("source_revision") != EXPECTED_SOURCE_REVISION
        or not _strict(value.get("predecessors"), expected_predecessors)
        or not _strict(value.get("readiness"), expected_readiness)
    ):
        errors.append("Item28 evidence identity/readiness mismatch")
    receipt_row = value.get("provider_receipt") or {}
    if (
        set(receipt_row) != {
            "path", "file_sha256", "semantic_sha256",
            "terminal_acceptance_sha256",
        }
        or receipt_row.get("path") != RECEIPT_REF
        or receipt_row.get("file_sha256") != EXPECTED_RECEIPT_FILE_SHA256
        or receipt_row.get("semantic_sha256") != EXPECTED_RECEIPT_SEMANTIC_SHA256
        or receipt_row.get("terminal_acceptance_sha256") != terminal_acceptance_sha256(receipt)
    ):
        errors.append("Item28 receipt binding mismatch")
    result = receipt.get("result") if type(receipt) is dict else {}
    rehearsal = value.get("rehearsal") or {}
    rehearsal_keys = (
        "failure_phase", "restart_attempt_count", "restart_success_count",
        "restart_failed_pre_connect_count", "guardian_rollback_count",
        "guardian_rollback_status", "original_release_restored",
        "volatile_residue_count", "release_identity_sha256",
        "release_identity_unchanged",
    )
    if set(rehearsal) != set(rehearsal_keys) or any(
        type(rehearsal.get(key)) is not type(result.get(key))
        or rehearsal.get(key) != result.get(key)
        for key in rehearsal_keys
    ):
        errors.append("Item28 rehearsal projection mismatch")
    final_state = value.get("final_runtime_state") or {}
    if final_state != {
        "api_f_active": True, "api_f_enabled": True,
        "api_f_loopback_live_ready": True, "public_listener_count": 0,
        "volatile_dropin_residue_count": 0,
        "original_release_restored": True,
    }:
        errors.append("Item28 final runtime state mismatch")
    counters = value.get("mutation_counters") or {}
    if counters != {
        "managed_restart_attempt_count": 1,
        "managed_restart_success_count": 0,
        "guardian_rollback_count": 1,
        "provider_call_count": 0,
        "oss_mutation_count": 0,
        "iam_mutation_count": 0,
        "production_database_mutation_count": 0,
        "cloud_resource_create_count": 0,
        "public_request_count": 0,
    }:
        errors.append("Item28 mutation counters mismatch")
    boundary = value.get("cost_and_data_boundary") or {}
    if boundary != {
        "incremental_cloud_cost_cny": 0,
        "provider_payload_content_sent": False,
        "user_content_sent": False,
        "database_write_requested": False,
        "new_paid_resource_created": False,
        "public_traffic_sent": False,
    }:
        errors.append("Item28 cost/data boundary mismatch")
    return errors


def validate_manifest_evidence(entries: Any, *, root: Path = ROOT, expected_predecessors: dict[str, str], expected_readiness: dict[str, Any]):
    errors: list[str] = []
    path_refs = [
        row.get("ref") for row in entries or []
        if type(row) is dict and set(row) == {"kind", "ref"}
        and row.get("kind") == "path"
    ]
    git_refs = [
        row.get("ref") for row in entries or []
        if type(row) is dict and set(row) == {"kind", "ref"}
        and row.get("kind") == "git"
    ]
    if (
        type(entries) is not list
        or len(entries) != len(REQUIRED_MANIFEST_PATH_REFS) + 1
        or len(path_refs) != len(REQUIRED_MANIFEST_PATH_REFS)
        or set(path_refs) != REQUIRED_MANIFEST_PATH_REFS
        or git_refs != [EXPECTED_SOURCE_REVISION]
    ):
        return ["Item28 exact manifest evidence refs required"]
    authorities = (
        EXPECTED_SOURCE_REVISION, EXPECTED_EVIDENCE_FILE_SHA256,
        EXPECTED_EVIDENCE_SEMANTIC_SHA256, EXPECTED_RECEIPT_FILE_SHA256,
        EXPECTED_RECEIPT_SEMANTIC_SHA256,
        EXPECTED_TERMINAL_CHECKPOINT_FILE_SHA256,
        EXPECTED_TERMINAL_CHECKPOINT_SEMANTIC_SHA256,
    )
    if (
        HEX40.fullmatch(EXPECTED_SOURCE_REVISION or "") is None
        or any(not _hex64(value) for value in authorities[1:])
    ):
        return ["Item28 terminal evidence authority is not finalized"]
    evidence, evidence_raw, error = _load(root / EVIDENCE_REF)
    receipt, receipt_raw, receipt_error = _load(root / RECEIPT_REF)
    checkpoint, checkpoint_raw, checkpoint_error = _load(root / TERMINAL_CHECKPOINT_REF)
    if error or receipt_error or checkpoint_error:
        return [error or receipt_error or checkpoint_error or "Item28 evidence read error"]
    assert evidence is not None and evidence_raw is not None
    assert receipt is not None and receipt_raw is not None
    assert checkpoint is not None and checkpoint_raw is not None
    if _sha(evidence_raw) != EXPECTED_EVIDENCE_FILE_SHA256 or _semantic(evidence) != EXPECTED_EVIDENCE_SEMANTIC_SHA256:
        errors.append("Item28 evidence authority mismatch")
    if _sha(receipt_raw) != EXPECTED_RECEIPT_FILE_SHA256 or _semantic(receipt) != EXPECTED_RECEIPT_SEMANTIC_SHA256:
        errors.append("Item28 receipt authority mismatch")
    if _sha(checkpoint_raw) != EXPECTED_TERMINAL_CHECKPOINT_FILE_SHA256 or _semantic(checkpoint) != EXPECTED_TERMINAL_CHECKPOINT_SEMANTIC_SHA256:
        errors.append("Item28 checkpoint authority mismatch")
    receipt_errors, _acceptance = validate_receipt(
        receipt, expected_predecessors=expected_predecessors, root=root,
    )
    errors.extend(receipt_errors)
    errors.extend(validate_evidence(
        evidence, receipt, expected_predecessors=expected_predecessors,
        expected_readiness=expected_readiness, root=root,
    ))
    checkpoint_expected = {
        "schema": CHECKPOINT_SCHEMA,
        "task_id": TASK_ID,
        "status": "EXACT_HEAD_CI_ACCEPTED",
        "source_revision": EXPECTED_SOURCE_REVISION,
        "evidence_file_sha256": EXPECTED_EVIDENCE_FILE_SHA256,
        "evidence_semantic_sha256": EXPECTED_EVIDENCE_SEMANTIC_SHA256,
        "receipt_file_sha256": EXPECTED_RECEIPT_FILE_SHA256,
        "receipt_semantic_sha256": EXPECTED_RECEIPT_SEMANTIC_SHA256,
        "automatic_retry_allowed": False,
        "readiness_credit_added": True,
    }
    if not _strict(checkpoint, checkpoint_expected):
        errors.append("Item28 terminal checkpoint mismatch")
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    predecessor_errors, predecessors = validate_predecessor_evidence({}, root=args.root)
    if predecessor_errors or predecessors is None:
        for error in predecessor_errors:
            print(error)
        return 1
    errors = validate_manifest_evidence(
        [{"kind": "path", "ref": ref} for ref in sorted(REQUIRED_MANIFEST_PATH_REFS)]
        + [{"kind": "git", "ref": EXPECTED_SOURCE_REVISION}],
        root=args.root, expected_predecessors=predecessors,
        expected_readiness=DEFAULT_READINESS,
    )
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
